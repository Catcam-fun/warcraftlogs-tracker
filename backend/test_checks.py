import os
import unittest
from unittest import mock

from checks.registry import CHECKS, select
from checks.verdict import PASS, Verdict, exit_code, fail, format_lines, skip
from checks.rules_counting import counts
from checks.rules_slots import rank
from checks.rules_verdicts import violations
from checks.rules_labels import label, death_hits
from raid_wide_damage import RAID_WIDE
from checks.__main__ import run_checks
from checks import rules_verdicts, rules_counting, rules_defensives, rules_labels, rules_slots, source_deaths
from checks.common import AnalysisError, Run, TableCapped, parse_target, points, raid_week, run_analysis


class VerdictTests(unittest.TestCase):
    def test_fail_keeps_ten_items_and_counts_all(self):
        o = fail([f"m{i}" for i in range(13)])
        self.assertEqual((o.status, len(o.items), o.total), ("fail", 10, 13))

    def test_format_lines_and_exit_code(self):
        vs = [Verdict("deaths", "source", "Deaths match", PASS),
              Verdict("slots", "rules", "Slots follow rules", fail(["pull 37 Bob: site 4, rule 5"])),
              Verdict("state", "source", "State matches", skip("no counted death"))]
        text = format_lines(vs, 212.0)
        self.assertIn("source  deaths          pass  Deaths match", text)
        self.assertIn("rules   slots           FAIL  Slots follow rules  (1 mismatches)", text)
        self.assertIn("        pull 37 Bob: site 4, rule 5", text)
        self.assertIn("source  state           skip  State matches  (no counted death)", text)
        self.assertTrue(text.endswith("points spent: 212\n"))
        self.assertEqual(exit_code(vs), 1)
        self.assertEqual(exit_code([vs[0], vs[2]]), 0)

    def test_points_unknown_and_json(self):
        from checks.verdict import to_json
        vs = [Verdict("a", "source", "A", PASS)]
        self.assertTrue(format_lines(vs, None).endswith("points spent: unknown\n"))
        self.assertEqual(to_json(vs, None)["points"], None)


class RegistryTests(unittest.TestCase):
    def test_select_families_and_unknown(self):
        self.assertEqual(select("all"), CHECKS)
        self.assertTrue(all(f == "rules" for _, f, _ in select("rules")))
        with self.assertRaises(ValueError):
            select("nope")


class RunnerTests(unittest.TestCase):
    def test_exception_in_a_check_is_a_fail_not_a_crash(self):
        def boom(run):
            """Always explodes"""
            raise RuntimeError("wcl down")
        vs = run_checks(object(), [("boom", "source", boom)])
        self.assertEqual(vs[0].outcome.status, "fail")
        self.assertIn("RuntimeError: wcl down", vs[0].outcome.reason)


class TargetTests(unittest.TestCase):
    def test_parse_target_forms(self):
        t = parse_target("ABC123:manaforge")
        self.assertEqual((t.code, t.raid, t.guild), ("ABC123", "manaforge", None))
        t = parse_target("ABC123:nerubar:Big Guild/Area 52/US")
        self.assertEqual(t.guild, ("Big Guild", "Area 52", "US"))
        with self.assertRaises(SystemExit):
            parse_target("ABC123:not-a-raid")

    def test_raid_week_is_the_tuesday_on_or_before(self):
        # 2026-10-01T00:00Z is a Thursday -> week starts Tuesday 2026-09-29
        self.assertEqual(raid_week(1790812800000), ("2026-09-29", "2026-10-06"))
        self.assertEqual(raid_week(1790640000000), ("2026-09-29", "2026-10-06"))   # the Tuesday itself


class RunTests(unittest.TestCase):
    def test_no_mythic_pulls_gives_empty_pulls(self):
        with mock.patch("checks.common.get_fights", return_value={"report_start": 0, "fights": [
                {"id": 1, "start_time": 0, "end_time": 1, "boss": 3129, "difficulty": 4, "kill": False, "zoneID": 44}],
                "friendlies": [], "player_details": {}, "abilities": {}, "ability_schools": {}}):
            run = Run("t", parse_target("X:manaforge"))
            self.assertEqual(run.pulls, [])

    def test_deaths_table_cap_raises(self):
        with mock.patch("checks.common.graphql_query", return_value={"reportData": {"report": {"t": {"data": {"entries": [{}] * 200}}}}}):
            run = Run("t", parse_target("X:manaforge"))
            with self.assertRaises(TableCapped):
                run.deaths_table("X", 5)

    def test_points_is_none_on_error(self):
        with mock.patch("checks.common.graphql_query", side_effect=Exception("down")):
            self.assertIsNone(points("t"))

    def test_run_analysis_returns_result_or_raises(self):
        body = 'data: {"stage": "x", "message": "m"}\n\ndata: {"result": {"events": {}}}\n\n'
        fake = mock.Mock(); fake.post.return_value.get_data.return_value = body
        with mock.patch("checks.common.app.app.test_client", return_value=fake), \
             mock.patch.dict(os.environ, {"WCL_CLIENT_ID": "a", "WCL_CLIENT_SECRET": "b"}):
            self.assertEqual(run_analysis("t", parse_target("X:manaforge:G/S/US"), "2026-09-29", "2026-10-06"), {"events": {}})
            fake.post.return_value.get_data.return_value = 'data: {"error": "No reports found"}\n\n'
            with self.assertRaises(AnalysisError):
                run_analysis("t", parse_target("X:manaforge:G/S/US"), "2026-09-29", "2026-10-06")


class DeathsCheckTests(unittest.TestCase):
    def _run(self, theirs):
        run = mock.Mock(); run.code, run.raid = "X", "manaforge"
        run.pulls = [{"id": 1, "start_time": 0, "end_time": 9}]
        run.meta = {"friendlies": [], "abilities": {}}
        run.deaths_table.return_value = theirs
        return run

    def test_pass_fail_and_skip(self):
        ours = {1: [{"targetID": 7, "timestamp": 100, "abilityName": "Zap"}]}
        with mock.patch("checks.source_deaths.get_report_deaths_bulk", return_value=ours):
            same = [{"fight": 1, "id": 7, "timestamp": 100, "killingBlow": {"name": "Zap"}}]
            self.assertEqual(source_deaths.check(self._run(same)).status, "pass")
            other = [{"fight": 1, "id": 7, "timestamp": 100, "killingBlow": {"name": "Pow"}}, {"fight": 1, "id": 8, "timestamp": 200}]
            o = source_deaths.check(self._run(other))
            self.assertEqual((o.status, o.total), ("fail", 2))
        run = self._run([]); run.pulls = []
        self.assertEqual(source_deaths.check(run).status, "skip")


class MovedChecksTests(unittest.TestCase):
    def test_registry_names(self):
        names = [n for n, _, _ in CHECKS]
        self.assertTrue({"deaths", "durations", "mitigation", "defensives"} <= set(names))

    def test_defensives_check_reads_talent_entries(self):
        run = mock.Mock(); run.code = "X"; run.pulls = [{"id": 1, "start_time": 0, "end_time": 9}]
        run.cat.all = {1: {"talent_entries": [111]}}
        run.combatants.return_value = [{"sourceID": 1, "fight": 1, "specID": 104, "talentTree": [{"id": 111, "rank": 1}]}]
        self.assertEqual(rules_defensives.check(run).status, "pass")
        run.combatants.return_value = [{"sourceID": 1, "fight": 1, "specID": 104, "talentTree": [{"id": 999, "rank": 1}]}]
        self.assertEqual(rules_defensives.check(run).status, "fail")
        run.combatants.return_value = []
        self.assertEqual(rules_defensives.check(run).status, "skip")
        run.pulls = []
        self.assertEqual(rules_defensives.check(run).status, "skip")


class SlotsRuleTests(unittest.TestCase):
    def test_rank_clauses(self):
        d = lambda ts, who, cheat=False: (ts, who, cheat)
        self.assertEqual(rank([d(10, 1), d(20, 2, True), d(30, 3)]), [(1, False), (2, False), (2, False)])
        self.assertEqual(rank([d(10, 1), d(10, 2)]), [(1, False), (2, False)])
        self.assertEqual(rank([d(10, 1), d(50, 1)]), [(1, False), (2, False)])
        wipe = [d(1000, 0)] + [d(50000 + i, i + 1) for i in range(8)]
        self.assertEqual([w for _, w in rank(wipe)], [False] + [True] * 8)
        seven = [d(49999, 9, True)] + [d(50000 + i, i + 1) for i in range(7)]
        self.assertFalse(any(w for _, w in rank(seven)))
        before = [d(49999, 9, True)] + [d(50000 + i, i + 1) for i in range(8)]
        self.assertTrue(rank(before)[0][1])      # a cheat death just before a wipe's first death is inside it


class SlotsCheckTests(unittest.TestCase):
    def _run(self, events, tables):
        run = mock.Mock()
        run.result = {"events": events}
        run.fight.return_value = {"start_time": 1000}
        run.actor_id.side_effect = lambda rid, name: {"A": 1, "B": 2}[name]
        def table(rid, fid):
            t = tables[fid]
            if isinstance(t, Exception):
                raise t
            return t
        run.deaths_table.side_effect = table
        return run

    def _ev(self, fid, who, ts, slot, wipe=False, cheat=False):
        return {"reportId": "r", "fightId": fid, "timestamp": ts, "originalCharacter": who,
                "slot": slot, "inWipe": wipe, "isCheatDeath": cheat}

    def test_check(self):
        table = [{"id": 2, "timestamp": 1900}, {"id": 1, "timestamp": 1500}, {"id": 1, "timestamp": 2500}]
        good = [self._ev(1, "A", 500, 1), self._ev(1, "B", 900, 2), self._ev(1, "A", 1500, 3),
                self._ev(1, "A", 700, 1, cheat=True)]   # cheat death: no item
        self.assertEqual(rules_slots.check(self._run({"A": good}, {1: table})).status, "pass")
        bad = [self._ev(1, "A", 500, 1), self._ev(1, "B", 900, 3)]
        o = rules_slots.check(self._run({"A": bad}, {1: table}))
        self.assertEqual(o.status, "fail")
        self.assertEqual(o.items, ["pull 1 B 900: site slot 3 inWipe False, rule slot 2 inWipe False"])
        o = rules_slots.check(self._run({"A": [self._ev(1, "A", 600, 1)]}, {1: table}))
        self.assertEqual(o.items, ["pull 1 A 600: not in WCL's Deaths table"])
        capped = self._run({"A": [self._ev(2, "A", 500, 1)]}, {2: TableCapped("r", 2)})
        self.assertEqual(rules_slots.check(capped).items, ["pull 2: 200+ deaths, table capped"])
        self.assertEqual(rules_slots.check(self._run({}, {})).status, "skip")


class CountingRuleTests(unittest.TestCase):
    def test_counts_and_defensive_presence(self):
        ev = lambda slot, wipe=False, cheat=False, d=True: {"slot": slot, "inWipe": wipe, "isCheatDeath": cheat,
                                                          "reportId": "R", "fightId": 1, "timestamp": slot, **({"defensives": {}} if d else {})}
        result = {"meta": {"maxCutoff": 2}, "events": {"Bob": [ev(1), ev(3, d=False)], "Amy": [ev(2, wipe=True, d=False)]}}
        self.assertEqual(counts(result, 2), {"Bob": (1, 0), "Amy": (0, 0)})
        run = mock.Mock(); run.result = result
        self.assertEqual(rules_counting.check(run).status, "pass")
        result["events"]["Amy"][0]["defensives"] = {}
        self.assertEqual(rules_counting.check(run).status, "fail")
        result["events"]["Amy"][0].pop("defensives")
        result["events"]["Bob"][0].pop("defensives")
        self.assertEqual(rules_counting.check(run).items, ["Bob pull 1 1: death can count but has no defensives"])
        self.assertEqual(rules_counting.check(mock.Mock(result={"meta": {"maxCutoff": 2}, "events": {}})).status, "skip")


class VerdictRuleTests(unittest.TestCase):
    def base(self):
        return {"available": [{"name": "Barkskin"}], "cooldown": [{"name": "Survival Instincts"}],
                "healthstone": {"usedAgo": None}, "potion": {"usedAgo": None},
                "survival": {"deathType": "wasLow", "overkill": 100, "maxHp": 1000, "ignoresImmunity": False,
                             "wouldSave": {"Barkskin": True}, "details": {"Barkskin": {"amount": 150, "pressAgo": 1.2}}}}

    def test_each_property(self):
        cat = mock.Mock(); cat.name_to_id = {"Barkskin": 1}; cat.all = {1: {"mitigation": [{"dr": 0.2}]}}
        self.assertEqual(violations(self.base(), cat), [])
        d = self.base(); d["survival"]["details"]["Barkskin"]["pressAgo"] = 0.4
        self.assertEqual(len(violations(d, cat)), 1)
        d = self.base(); d["survival"]["wouldSave"]["Survival Instincts"] = False
        self.assertEqual(len(violations(d, cat)), 1)
        d = self.base(); d["survival"]["details"]["Barkskin"]["amount"] = 50
        self.assertEqual(len(violations(d, cat)), 1)
        d = self.base(); d["survival"]["details"]["Barkskin"]["amount"] = 5000
        self.assertEqual(len(violations(d, cat)), 1)
        d = self.base(); d["survival"]["deathType"] = "instakill"
        self.assertEqual(len(violations(d, cat)), 1)
        d = self.base(); d["survival"]["ignoresImmunity"] = True; cat.all[1]["mitigation"] = [{"immune": True}]
        self.assertEqual(len(violations(d, cat)), 1)

    def test_check_over_counted_deaths(self):
        cat = mock.Mock(); cat.name_to_id = {}; cat.all = {}
        ev = lambda slot, d, wipe=False: {"slot": slot, "inWipe": wipe, "isCheatDeath": False, "fightId": 2,
                                          "timestamp": slot, "defensives": d}
        run = mock.Mock(); run.cat = cat
        run.result = {"meta": {"maxCutoff": 2}, "events": {"Bob": [ev(1, {"available": []}), ev(5, self.bad()),
                                                                   ev(2, self.bad(), wipe=True)]}}
        self.assertEqual(rules_verdicts.check(run).status, "skip")
        run.result["events"]["Bob"][0]["defensives"] = self.base()
        self.assertEqual(rules_verdicts.check(run).status, "pass")
        run.result["events"]["Bob"][0]["defensives"] = self.bad()
        o = rules_verdicts.check(run)
        self.assertEqual(o.status, "fail")
        self.assertEqual(o.items, ["Bob pull 2 1: Barkskin: pressed 0.4s before the killing blow (rule: at least 1s)"])

    def test_consumables_and_amount_branches(self):
        cat = mock.Mock(); cat.name_to_id = {}; cat.all = {}
        d = self.base(); d["potion"] = {"name": "Potion", "usedAgo": 5, "readyIn": 100}
        d["survival"]["wouldSave"]["Potion"] = False; d["survival"]["details"]["Potion"] = {"amount": 0}
        self.assertEqual(violations(d, cat), ["Potion: judged but on cooldown"])
        d = self.base(); d["survival"]["consumables"] = {"Healthstone": "healthstone"}
        d["survival"]["wouldSave"]["Healthstone"] = False; d["survival"]["details"]["Healthstone"] = {"amount": 0}
        self.assertEqual(violations(d, cat), [])
        d = self.base(); d["survival"]["wouldSave"]["Ghost"] = False
        self.assertEqual(violations(d, cat), ["Ghost: judged but not ready"])
        d = self.base(); d["survival"]["wouldSave"]["Barkskin"] = False
        self.assertEqual(violations(d, cat), ["Barkskin: amount 150 vs overkill 100 but marked not saves"])
        d = self.base(); d["survival"]["details"]["Barkskin"]["why"] = "school"
        self.assertEqual(violations(d, cat), ["Barkskin: amount 150 vs overkill 100 but marked saves"])

    def bad(self):
        d = self.base(); d["survival"]["details"]["Barkskin"]["pressAgo"] = 0.4
        return d


class LabelRuleTests(unittest.TestCase):
    def hit(self, ts, amount, hp_after, aid=1, overkill=0):
        return {"timestamp": ts, "amount": amount, "overkill": overkill, "absorbed": 0,
                "hitPoints": hp_after, "maxHitPoints": 1000, "abilityGameID": aid}

    def test_one_shot_burst_and_was_low(self):
        kb = self.hit(1000, 900, 0, overkill=50)                       # 950 of 1000 from full
        self.assertEqual(label([self.hit(0, 10, 990), kb], 1)["deathType"], "oneShot")
        burst = [self.hit(0, 10, 990), self.hit(500, 400, 590), self.hit(990, 590, 0, overkill=10)]
        self.assertEqual(label(burst, 2)["deathType"], "burst")
        slow = [self.hit(0, 10, 990), self.hit(500, 400, 590), self.hit(2000, 590, 0, overkill=10)]
        self.assertEqual(label(slow, 2), {"deathType": "wasLow", "rot": None, "biggestHit": 1})

    def test_rot_needs_a_raid_wide_ability(self):
        aid = next(iter(RAID_WIDE))
        hits = [self.hit(0, 10, 990)] + [self.hit(1000 * i, 200, 990 - 200 * i, aid=aid) for i in range(1, 5)] \
             + [self.hit(6000, 190, 0, aid=aid, overkill=10)]
        self.assertEqual(label(hits, 5)["rot"], aid)
        not_wide = [dict(h, abilityGameID=999_999) for h in hits]
        self.assertEqual(label(not_wide, 5)["rot"], None)

    def test_threshold_edges(self):
        # "quick" is measured from the last moment at high health (t=0 here) to the killing blow.
        self.assertEqual(label([self.hit(0, 10, 990), self.hit(600, 790, 200), self.hit(1001, 200, 0, overkill=5)], 2)["deathType"], "wasLow")
        self.assertEqual(label([self.hit(0, 10, 990), self.hit(600, 790, 200), self.hit(999, 200, 0, overkill=5)], 2)["deathType"], "burst")
        # One-shot needs a single hit of 80 % of max HP or more (800 of 1000); 799 is burst.
        self.assertEqual(label([self.hit(0, 10, 990), self.hit(100, 190, 800), self.hit(500, 800, 0)], 2)["deathType"], "oneShot")
        self.assertEqual(label([self.hit(0, 10, 990), self.hit(100, 191, 799), self.hit(500, 799, 0)], 2)["deathType"], "burst")

    def test_set_up_hit_needs_ten_percent_and_a_burst_has_none(self):
        small = [self.hit(0, 10, 990), self.hit(2000, 99, 500), self.hit(3000, 500, 0, overkill=1)]
        self.assertEqual(label(small, 2)["biggestHit"], None)
        pick = [self.hit(0, 10, 990), self.hit(1500, 100, 700, aid=7), self.hit(2000, 200, 500, aid=8),
                self.hit(3000, 500, 0, aid=9, overkill=1)]
        self.assertEqual(label(pick, 3), {"deathType": "wasLow", "rot": None, "biggestHit": 8})

    def test_two_deaths_in_one_pull_use_their_own_hits(self):
        h = self.hit
        hits = [h(0, 10, 990), h(100, 500, 0, aid=5, overkill=20),        # first death
                h(9000, 10, 990), h(9500, 400, 590), h(9900, 590, 0, aid=6, overkill=5)]   # second death
        got = death_hits(hits, 9900)
        self.assertEqual([x["timestamp"] for x in got[0]], [9000, 9500, 9900])
        self.assertEqual(got[1], 2)
        self.assertEqual(label(*got)["deathType"], "burst")
        first = death_hits(hits, 100)
        self.assertEqual([x["timestamp"] for x in first[0]], [0, 100])
        self.assertIsNone(death_hits([h(0, 10, 990)], 100))

    def test_check_compares_with_the_site(self):
        h = self.hit
        hits = [h(0, 10, 990), h(500, 400, 590), h(990, 590, 0, overkill=10)]
        ev = {"slot": 1, "inWipe": False, "isCheatDeath": False, "fightId": 2, "reportId": "R", "timestamp": 1000,
              "originalCharacter": "Bob", "defensives": {"survival": {"deathType": "burst"}}}
        run = mock.Mock()
        run.counted_deaths.return_value = [ev]
        run.actor_id.return_value = 7
        run.fight.return_value = {"start_time": 100000}
        run.hits_before.return_value = hits
        self.assertEqual(rules_labels.check(run).status, "pass")
        run.hits_before.assert_called_with("R", 2, 7, 101000)
        ev["defensives"]["survival"]["deathType"] = "wasLow"
        o = rules_labels.check(run)
        self.assertEqual((o.status, o.items), ("fail", ["Bob pull 2: site wasLow/None/None, rule burst/None/None"]))
        ev["defensives"]["survival"]["deathType"] = "instakill"
        self.assertEqual(rules_labels.check(run).status, "skip")


if __name__ == "__main__":
    unittest.main()
