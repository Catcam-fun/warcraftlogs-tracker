import unittest
from unittest import mock

import app as app_module
import auth
import supabase_client
import warcraftlogs
from ratelimit import RateLimiter


class FakeResult:
    def __init__(self, data, count=None):
        self.data = data
        self.count = count


class FakeQuery:
    """Just enough of the supabase-py query builder for supabase_client."""

    def __init__(self, rows):
        self.rows = rows
        self.op = 'select'
        self.filters = []
        self.payload = None
        self.count = None

    def select(self, *_cols, count=None):
        self.count = count
        return self

    def insert(self, payload):
        self.op, self.payload = 'insert', payload
        return self

    def delete(self):
        self.op = 'delete'
        return self

    def eq(self, col, val):
        self.filters.append(lambda r: r.get(col) == val)
        return self

    def lt(self, col, val):
        self.filters.append(lambda r: r.get(col) is not None and r.get(col) < val)
        return self

    def gt(self, col, val):
        self.filters.append(lambda r: r.get(col) is not None and r.get(col) > val)
        return self

    def order(self, *_a, **_k):
        return self

    def limit(self, _n):
        return self

    def execute(self):
        if self.op == 'insert':
            self.rows.append(dict(self.payload))
            return FakeResult([self.payload])
        matched = [r for r in self.rows if all(f(r) for f in self.filters)]
        if self.op == 'delete':
            for r in matched:
                self.rows.remove(r)
        return FakeResult(matched, count=len(matched) if self.count else None)


class FakeDB:
    def __init__(self):
        self.tables = {}

    def table(self, name):
        return FakeQuery(self.tables.setdefault(name, []))


ANALYSIS = {"meta": {"guild_name": "Guild"}, "events": {"Bob": []}}
SECRET_CONFIG = {"guildName": "Guild", "clientId": "id-123", "clientSecret": "shh-secret"}


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.db = FakeDB()
        patcher = mock.patch.object(supabase_client, 'db', self.db)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_save_limit_is_five_per_user(self):
        for i in range(5):
            self.assertTrue(supabase_client.save_analysis('u1', f'r{i}', 'G', ANALYSIS).get('success'))
        blocked = supabase_client.save_analysis('u1', 'r6', 'G', ANALYSIS)
        self.assertEqual(blocked.get('code'), 'limit')
        # Another user's quota is independent.
        self.assertTrue(supabase_client.save_analysis('u2', 'x', 'G', ANALYSIS).get('success'))

    def test_concurrent_saves_cannot_exceed_the_limit(self):
        for i in range(4):
            supabase_client.save_analysis('u1', f'r{i}', 'G', ANALYSIS)
        rows = self.db.tables['saved_analyses']
        real_insert = FakeQuery.insert

        def racing_insert(query, payload):
            # Another request's save lands between this one's count and insert.
            if payload.get('analysis_name') == 'late':
                rows.append(dict(payload, id='other', analysis_name='concurrent'))
            return real_insert(query, payload)
        with mock.patch.object(FakeQuery, 'insert', racing_insert):
            result = supabase_client.save_analysis('u1', 'late', 'G', ANALYSIS)
        self.assertEqual(result.get('code'), 'limit')
        self.assertEqual(len([r for r in rows if r['user_id'] == 'u1']), 5)
        self.assertNotIn('late', [r['analysis_name'] for r in rows])

    def test_saved_reports_are_scoped_to_owner_and_strip_secrets(self):
        saved = supabase_client.save_analysis('u1', 'mine', 'G', ANALYSIS, config=SECRET_CONFIG)
        rid = saved['id']
        self.assertEqual(supabase_client.load_analysis(rid, 'u2').get('code'), 'not_found')
        supabase_client.delete_analysis(rid, 'u2')
        loaded = supabase_client.load_analysis(rid, 'u1')
        self.assertEqual(loaded['data'], ANALYSIS)
        self.assertNotIn('clientSecret', loaded['config'])
        self.assertNotIn('clientId', loaded['config'])
        stored = self.db.tables['saved_analyses'][0]['analysis_data']
        self.assertTrue(stored.startswith('br64:'))
        self.assertNotIn('shh-secret', stored)

    def test_legacy_plain_json_rows_still_load(self):
        self.db.tables['saved_analyses'] = [{
            'id': 'old', 'user_id': 'u1', 'analysis_name': 'old',
            'analysis_data': '{"meta": {"guild_name": "G"}, "events": {}}',
        }]
        loaded = supabase_client.load_analysis('old', 'u1')
        self.assertEqual(loaded['data']['meta']['guild_name'], 'G')

    def test_expired_saves_do_not_load(self):
        saved = supabase_client.save_analysis('u1', 'mine', 'G', ANALYSIS, retention_days=7)
        row = self.db.tables['saved_analyses'][0]
        row['expires_at'] = '2000-01-01T00:00:00+00:00'
        self.assertEqual(supabase_client.load_analysis(saved['id'], 'u1').get('code'), 'not_found')
        self.assertEqual(self.db.tables['saved_analyses'], [])

    def test_unexpired_saves_still_load(self):
        saved = supabase_client.save_analysis('u1', 'mine', 'G', ANALYSIS, retention_days=7)
        self.assertTrue(supabase_client.load_analysis(saved['id'], 'u1').get('success'))

    def test_shares_strip_secrets_and_round_trip(self):
        supabase_client.store_share('abc123', ANALYSIS, SECRET_CONFIG)
        share = supabase_client.get_share('abc123')
        self.assertEqual(share['data'], ANALYSIS)
        self.assertEqual(share['config'], {"guildName": "Guild"})
        self.assertNotIn('shh-secret', self.db.tables['shared_results'][0]['payload'])

    def test_shares_fall_back_to_memory_when_table_missing(self):
        with mock.patch.object(supabase_client, 'db', None):
            supabase_client.store_share('memshare', ANALYSIS, SECRET_CONFIG)
            self.assertEqual(supabase_client.get_share('memshare')['config'], {"guildName": "Guild"})


class EndpointAuthTests(unittest.TestCase):
    def setUp(self):
        self.client = app_module.app.test_client()

    def test_account_and_saved_endpoints_require_a_session(self):
        for method, url in (('delete', '/api/account'), ('get', '/api/saved'),
                            ('post', '/api/saved'), ('delete', '/api/saved'),
                            ('get', '/api/saved/00000000-0000-0000-0000-000000000000')):
            with self.subTest(url=url, method=method):
                resp = getattr(self.client, method)(url, headers={'Authorization': 'Bearer forged'})
                self.assertEqual(resp.status_code, 401)

    def test_saved_endpoints_use_the_verified_user_not_the_request(self):
        with mock.patch.object(auth, 'verify_token', return_value='real-user'), \
                mock.patch.object(supabase_client, 'get_user_analyses',
                                  return_value={"success": True, "analyses": []}) as listed, \
                mock.patch.object(supabase_client, 'delete_user_account',
                                  return_value={"success": True}) as deleted:
            self.client.get('/api/saved?user_id=victim', headers={'Authorization': 'Bearer t'})
            self.client.delete('/api/account', headers={'Authorization': 'Bearer t'})
        listed.assert_called_once_with('real-user')
        deleted.assert_called_once_with('real-user')

    def test_share_route_reports_memory_only_links_and_real_status(self):
        payload = {"data": ANALYSIS, "config": {}}
        with mock.patch.object(app_module.supabase_client, 'store_share',
                               return_value={"success": True, "expires_at": "x", "ephemeral": True}):
            resp = self.client.post('/api/share', json=payload)
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json["ephemeral"])
        with mock.patch.object(app_module.supabase_client, 'store_share',
                               return_value={"error": "This analysis is too large to share.", "code": "too_large"}):
            self.assertEqual(self.client.post('/api/share', json=payload).status_code, 413)
        with mock.patch.object(app_module.supabase_client, 'store_share',
                               return_value={"error": "Could not create the share link."}):
            self.assertEqual(self.client.post('/api/share', json=payload).status_code, 500)

    def test_share_and_save_accept_gzip_bodies(self):
        import gzip, json as _json
        body = gzip.compress(_json.dumps({"data": ANALYSIS, "config": {}}).encode())
        headers = {"Content-Type": "application/json", "Content-Encoding": "gzip"}
        with mock.patch.object(app_module.supabase_client, 'store_share',
                               return_value={"success": True, "expires_at": "x"}) as store:
            resp = self.client.post('/api/share', data=body, headers=headers)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(store.call_args.args[1], ANALYSIS)
        with mock.patch.object(auth, 'verify_token', return_value='u1'), \
                mock.patch.object(app_module.supabase_client, 'save_analysis',
                                  return_value={"success": True, "id": "i"}) as save:
            resp = self.client.post('/api/saved', data=body, headers={**headers, 'Authorization': 'Bearer t'})
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(save.call_args.kwargs['analysis_data'], ANALYSIS)

    def test_an_oversized_body_is_413(self):
        with mock.patch.object(app_module, 'json_body', side_effect=app_module.BodyTooLarge):
            resp = self.client.post('/api/share', data=b'{}', headers={"Content-Type": "application/json"})
        self.assertEqual(resp.status_code, 413)

    def test_share_rejects_non_analysis_payloads(self):
        resp = self.client.post('/api/share', json={"data": "junk"})
        self.assertEqual(resp.status_code, 400)

    def test_old_unauthenticated_delete_route_is_gone(self):
        resp = self.client.delete('/api/delete-user-account/some-user-id')
        self.assertEqual(resp.status_code, 404)


class TokenCacheTests(unittest.TestCase):
    def test_tokens_are_cached_per_credential(self):
        warcraftlogs._token_cache.clear()
        calls = []

        def fake_request(method, url, **kwargs):
            calls.append(kwargs['headers']['Authorization'])
            resp = mock.Mock()
            resp.json.return_value = {"access_token": f"tok{len(calls)}", "expires_in": 3600}
            return resp

        with mock.patch.object(warcraftlogs, 'make_request_with_retry', side_effect=fake_request):
            a1 = warcraftlogs.get_access_token('a', 'secret-a')
            b1 = warcraftlogs.get_access_token('b', 'secret-b')
            a2 = warcraftlogs.get_access_token('a', 'secret-a')
        self.assertNotEqual(a1, b1)
        self.assertEqual(a1, a2)
        self.assertEqual(len(calls), 2)


class RateLimiterTests(unittest.TestCase):
    def test_blocks_after_limit(self):
        limiter = RateLimiter(max_calls=2, per_seconds=60)
        self.assertTrue(limiter.allow('ip'))
        self.assertTrue(limiter.allow('ip'))
        self.assertFalse(limiter.allow('ip'))
        self.assertTrue(limiter.allow('other-ip'))


class AnalyzeFlowTests(unittest.TestCase):
    """Runs /api/analyze end to end with WarcraftLogs mocked out."""

    def _fights(self, _token, rid):
        return {
            "report_start": 1_000_000 if rid == "R1" else 9_000_000,
            "fights": [{"id": 1, "start_time": 0, "end_time": 60_000, "name": "Plexus Sentinel",
                        "boss": 3129, "difficulty": 5, "kill": False, "zoneID": 44,
                        "friendlyPlayers": [10, 11]}],
            "friendlies": [{"id": 10, "name": "Bob", "type": "Mage"},
                           {"id": 11, "name": "Amy", "type": "Priest"}],
            "player_details": {10: {"class": "Mage", "spec": "Fire", "name": "Bob"}},
            "abilities": {},
        }

    def _windows(self, _token, _rid, pulls):
        # Bob's killing blow, from full health.
        return {10: [{"timestamp": 5_000, "type": "damage", "targetID": 10, "abilityGameID": 9, "amount": 900,
                      "overkill": 100, "hitPoints": 0, "maxHitPoints": 900, "resourceActor": 2}]}

    def _run(self, roster_patch=True, bulk_effect=None, **extra):
        from analysis import RAID_ENCOUNTERS
        raid = next(k for k, v in RAID_ENCOUNTERS.items() if 3129 in v)
        deaths = {1: [{"timestamp": 5_000, "targetName": "Bob", "targetID": 10,
                       "abilityName": "Zap"}]}
        reports = [{"id": "R1", "start": 1_000_000, "end": 1_100_000, "owner": "x"},
                   {"id": "R2", "start": 9_000_000, "end": 9_100_000, "owner": "x"}]
        roster = mock.patch.object(app_module, 'get_guild_roster', return_value={'bob', 'amy'}) if roster_patch \
            else mock.MagicMock()
        with mock.patch.object(app_module, 'get_access_token', return_value='t'), roster, \
                mock.patch.object(app_module, 'get_guild_reports', return_value=reports), \
                mock.patch.object(app_module, 'get_fights', autospec=True, side_effect=self._fights) as fights, \
                mock.patch.object(app_module, 'get_report_deaths_bulk', autospec=True, return_value=deaths,
                                  side_effect=bulk_effect) as bulk, \
                mock.patch.object(app_module.defensives, 'fetch_defensive_raw', autospec=True,
                                  return_value={}), \
                mock.patch.object(app_module.defensives, 'fetch_instakills', autospec=True,
                                  return_value={}), \
                mock.patch.object(app_module.defensives, 'fetch_death_windows', autospec=True,
                                  side_effect=self._windows) as windows:
            resp = app_module.app.test_client().post('/api/analyze', json={
                "clientId": "a", "clientSecret": "b", "guildName": "G", "server": "S",
                "region": "US", "fightZone": 0, "selectedRaid": raid, "difficulty": 5, **extra})
            body = resp.get_data(as_text=True)
        results = [l for l in body.split("\n\n") if '"result"' in l]
        self.assertEqual(len(results), 1, body)
        import json
        self.window_calls = windows.call_args_list
        return json.loads(results[0][6:])["result"], fights.call_count, bulk.call_count

    def test_analysis_counts_deaths_and_caches_finished_reports(self):
        app_module.report_meta_cache._data.clear()
        app_module.deaths_lru._data.clear()
        app_module.defensive_lru._data.clear()
        app_module.recap_lru._data.clear()
        result, fights_calls, bulk_calls = self._run()
        self.assertEqual(len(result["events"]["Bob"]), 2)  # one death in each report
        self.assertNotIn("Amy", result["events"])
        self.assertEqual(len(result["pullParticipation"]["Amy"]), 2)
        self.assertNotIn("characterBreakdown", result)
        self.assertEqual(result["meta"]["failedReports"], [])
        self.assertIn("defensives", result["events"]["Bob"][0])
        self.assertEqual(result["events"]["Bob"][0]["defensives"]["survival"]["deathType"], "oneShot")
        self.assertEqual((fights_calls, bulk_calls), (2, 2))
        # Only the deaths that can count get their seconds fetched: Bob's, by his name in the log.
        self.assertEqual(self.window_calls[0].args[2], [(1, [(5_000, "Bob")])])

        # Old reports are finished, so a second run is served from cache.
        _, fights_calls, bulk_calls = self._run()
        self.assertEqual((fights_calls, bulk_calls), (0, 0))

    def test_roster_filter_can_be_turned_off(self):
        for c in (app_module.report_meta_cache, app_module.deaths_lru, app_module.defensive_lru, app_module.recap_lru):
            c._data.clear()
        with mock.patch.object(app_module, 'get_guild_roster', return_value={'amy'}) as roster:
            # Default: only roster members count, so Bob (not on it) is left out.
            result, _, _ = self._run(roster_patch=False)
            self.assertNotIn("Bob", result["pullParticipation"])
            self.assertTrue(result["meta"]["rosterOnly"])
            self.assertEqual(roster.call_count, 1)
            # Off: everyone in the reports counts, and the roster isn't fetched.
            result, _, _ = self._run(roster_patch=False, rosterOnly=False)
            self.assertEqual(len(result["events"]["Bob"]), 2)
            self.assertFalse(result["meta"]["rosterOnly"])
            self.assertEqual(roster.call_count, 1)

    def test_unreadable_report_adds_no_pulls(self):
        for c in (app_module.report_meta_cache, app_module.deaths_lru, app_module.defensive_lru, app_module.recap_lru):
            c._data.clear()
        deaths = {1: [{"timestamp": 5_000, "targetName": "Bob", "targetID": 10, "abilityName": "Zap"}]}

        def bulk(_token, rid, *_a, **_k):
            if rid == "R2":
                raise RuntimeError("WCL unavailable")
            return deaths
        result, _, _ = self._run(bulk_effect=bulk)
        self.assertEqual(result["meta"]["failedReports"], ["R2"])
        # R2's pull is unknown, not deathless: it must not count toward anyone's pulls.
        self.assertEqual(len(result["pullParticipation"]["Amy"]), 1)
        self.assertEqual(len(result["pullParticipation"]["Bob"]), 1)
        self.assertEqual(len(result["events"]["Bob"]), 1)

    def test_cheat_death_requires_sign_in(self):
        app_module.report_meta_cache._data.clear()
        app_module.deaths_lru._data.clear()
        app_module.defensive_lru._data.clear()
        app_module.recap_lru._data.clear()
        result, _, _ = self._run(enableCheatDeath=True)
        self.assertFalse(result["meta"]["cheatDeathEnabled"])
        with mock.patch.object(app_module, 'verify_token', return_value='user-1'):
            result, _, _ = self._run(enableCheatDeath=True)
        self.assertTrue(result["meta"]["cheatDeathEnabled"])


if __name__ == '__main__':
    unittest.main()
