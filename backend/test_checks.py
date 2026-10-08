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
from checks import rules_verdicts, rules_counting, rules_defensives, rules_labels, rules_slots, source_deaths, source_participation, source_selection, source_state
from checks.source_state import active_mismatches, death_strip, entry_for, health_mismatch, ready_at
from checks.source_selection import cluster, walk
from checks.find_logs import good_log
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

    def test_buffs_table_filters_by_the_aura_holder(self):
        # Live 2026-10-07: a Buffs table with targetID lists the auras the player cast, not the
        # ones on them (no Rallying Cry from a Warrior, no Bloodlust); sourceID is the holder.
        reply = {"reportData": {"report": {"t": {"data": {"auras": [{"name": "Rallying Cry"}]}}}}}
        with mock.patch("checks.common.graphql_query", return_value=reply) as q:
            run = Run("t", parse_target("X:manaforge"))
            self.assertEqual(run.buffs("X", 5, 7), [{"name": "Rallying Cry"}])
            query, variables = q.call_args[0][1], q.call_args[0][2]
            self.assertIn("sourceID: $p", query)
            self.assertNotIn("targetID", query)
            self.assertEqual(variables["p"], 7)

    def test_damage_taken_filters_by_the_unit_hit(self):
        # Live 2026-10-07: DamageTaken with targetID returned only a Demon Hunter's 13 self-hits;
        # sourceID returned all 41 hits they took, the boss's killing blow included.
        reply = {"reportData": {"report": {"events": {"data": [{"timestamp": 1}], "nextPageTimestamp": None}}}}
        with mock.patch("checks.common.graphql_query", return_value=reply) as q:
            run = Run("t", parse_target("X:manaforge"))
            self.assertEqual(run.hits_before("X", 5, 7, 20_000), [{"timestamp": 1}])
            query, variables = q.call_args[0][1], q.call_args[0][2]
            self.assertIn("dataType: DamageTaken, sourceID: $p", query)
            self.assertIn("includeResources: true", query)     # hitPoints / maxHitPoints for the labels
            self.assertEqual((variables["p"], variables["s"], variables["e"], variables["f"]), (7, 5_000, 20_050, [5]))

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


    def test_run_analysis_never_touches_the_shared_cache(self):
        import cache, supabase_client
        cache.report_meta_cache.memory.set("R", {"stale": True})      # an earlier run's row
        seen = {}

        def post(*a, **k):
            seen["get"] = cache.report_meta_cache.get("R")
            cache.report_deaths_cache.set("R", {"rows": 1})
            resp = mock.Mock(); resp.get_data.return_value = 'data: {"result": {"events": {}}}\n\n'
            return resp
        fake = mock.Mock(); fake.post.side_effect = post
        with mock.patch("checks.common.app.app.test_client", return_value=fake), \
             mock.patch.object(supabase_client, "cache_get") as get, \
             mock.patch.object(supabase_client, "cache_put") as put, \
             mock.patch.dict(os.environ, {"WCL_CLIENT_ID": "a", "WCL_CLIENT_SECRET": "b"}):
            run_analysis("t", parse_target("X:manaforge:G/S/US"), "2026-09-29", "2026-10-06")
            cache.flush_writes()
        get.assert_not_called()
        put.assert_not_called()
        self.assertIsNone(seen["get"])
        self.assertEqual((len(cache.report_meta_cache), len(cache.report_deaths_cache)), (0, 0))

    def test_failed_analysis_is_not_run_again(self):
        run = Run("t", parse_target("X:manaforge:G/S/US"))
        run._cache[("meta", "X")] = {"report_start": 0, "fights": []}
        with mock.patch("checks.common.run_analysis", side_effect=AnalysisError("No reports found")) as ra:
            for _ in range(3):
                with self.assertRaises(AnalysisError):
                    run.result
        self.assertEqual(ra.call_count, 1)


class MainTests(unittest.TestCase):
    def test_no_targets_prints_usage_before_any_token(self):
        from checks.__main__ import main
        with mock.patch("warcraftlogs.get_access_token") as tok, mock.patch("builtins.print") as out:
            self.assertEqual(main(["all"]), 2)
            self.assertEqual(main(["verdicts", "--json", "x.json"]), 2)
        tok.assert_not_called()
        self.assertIn("python -m checks", out.call_args_list[0].args[0])


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


class DurationsCheckTests(unittest.TestCase):
    def test_auras_extended_mid_fight_are_not_flagged_longer(self):
        # Live 2026-10-07: Havoc Metamorphosis ran 49.7s against 15s; the owner's rule says
        # Metamorphosis and Dancing Rune Weapon can read longer. Barkskin doing the same is flagged.
        from checks import source_durations
        run = mock.Mock(); run.code = "X"
        run.pulls = [{"id": 1, "start_time": 0, "end_time": 100_000}]
        run.meta = {"abilities": {200: "Metamorphosis", 300: "Barkskin"}, "player_details": {}}
        run.cat.name_to_id = {"Metamorphosis": 200, "Barkskin": 300}
        run.cat.all = {200: {"name": "Metamorphosis", "kind": "personal", "duration_mods": [{"talent": "x"}]},
                       300: {"name": "Barkskin", "kind": "personal", "duration_mods": [{"talent": "x"}]}}
        buffs = []
        for aid in (200, 300):
            buffs += [{"type": "applybuff", "abilityGameID": aid, "targetID": 7, "timestamp": 1_000},
                      {"type": "removebuff", "abilityGameID": aid, "targetID": 7, "timestamp": 50_000}]
        raw = {"combatants": [{"sourceID": 7}], "casts": [], "buffs": buffs}
        with mock.patch.object(source_durations.defensives, "fetch_defensive_raw", return_value=raw),              mock.patch.object(source_durations.defensives, "filter_defensive_raw", return_value={"talents": {(1, 7): {}}}),              mock.patch.object(source_durations.defensives, "pull_spec", return_value="Havoc"),              mock.patch.object(source_durations.defensives, "_talented_duration", return_value=15_000):
            o = source_durations.check(run)
        self.assertEqual(o.status, "fail")
        self.assertEqual(o.items, ["Barkskin: 1 of 1 uses longer than predicted, e.g. 49.0s vs 15.0s"])

    def test_nothing_measured_is_a_skip(self):
        from checks import source_durations
        run = mock.Mock(); run.code = "X"
        run.pulls = [{"id": 1, "start_time": 0, "end_time": 100_000}]
        run.meta = {"abilities": {}, "player_details": {}}
        run.cat.name_to_id, run.cat.all = {}, {}
        raw = {"combatants": [], "casts": [], "buffs": []}
        with mock.patch.object(source_durations.defensives, "fetch_defensive_raw", return_value=raw),              mock.patch.object(source_durations.defensives, "filter_defensive_raw", return_value={"talents": {}}):
            o = source_durations.check(run)
        self.assertEqual((o.status, o.reason), ("skip", "no duration-talent defensive uses measured"))


class MitigationCheckTests(unittest.TestCase):
    def test_compares_with_hits_carrying_the_same_other_auras(self):
        # Live 2026-10-07: Fade measured 0.16 against 0.10 because Protective Light (an untracked 10%)
        # was up on many Fade hits and few others; an Evoker's Obsidian Scales shared onto a Warlock
        # read 0.15 against the Evoker's 0.30; blocked hits read random extra reduction.
        from checks import source_mitigation
        run = mock.Mock(); run.code = "X"
        run.pulls = [{"id": 1, "start_time": 0, "end_time": 100_000}]
        run.meta = {"abilities": {586: "Fade", 9: "Protective Light", 363916: "Obsidian Scales"},
                    "friendlies": [{"id": 7, "name": "Priest", "type": "Priest"},
                                   {"id": 8, "name": "Lock", "type": "Warlock"}],
                    "player_details": {}, "ability_schools": {}}
        run.cat.name_to_id = {"Fade": 586, "Obsidian Scales": 363916}
        run.cat.all = {586: {"name": "Fade", "kind": "personal", "class": "Priest", "mitigation": [{"dr": 0.1}]},
                       363916: {"name": "Obsidian Scales", "kind": "personal", "class": "Evoker",
                                "mitigation": [{"dr": 0.3}]}}
        run.cat.relevant_talent_entries = set()
        run.combatants.return_value = []
        hit = lambda who, through, buffs, blocked=0: {"type": "damage", "targetID": who, "abilityGameID": 1, "fight": 1,
                                                     "unmitigatedAmount": 1250, "mitigated": 1250 - through,
                                                     "amount": through, "blocked": blocked, "buffs": buffs}
        hits = [hit(7, 1000, "")] * 20 + [hit(7, 900, "9.")] * 20      # Protective Light alone: 10% off
        hits += [hit(7, 900, "586.")] * 5 + [hit(7, 810, "586.9.")] * 20  # Fade, mostly with Protective Light
        hits += [hit(7, 500, "586.", blocked=400)] * 10
        hits += [hit(8, 1000, "")] * 20 + [hit(8, 850, "363916.")] * 20   # shared Obsidian Scales
        with mock.patch.object(source_mitigation.defensives, "_paged", return_value=hits):
            self.assertEqual(source_mitigation.check(run).status, "pass")


    def test_aoe_reduction_is_predicted_hit_by_hit(self):
        # Live 2026-10-07 (Esra, Manaforge): one boss ability's hits are not all marked AoE, so Feint's
        # AoE-only 40% must be predicted per hit, not from one sample hit of the ability.
        from checks import source_mitigation
        run = mock.Mock(); run.code = "X"
        run.pulls = [{"id": 1, "start_time": 0, "end_time": 100_000}]
        run.meta = {"abilities": {1966: "Feint"}, "friendlies": [{"id": 2, "name": "Esra", "type": "Rogue"}],
                    "player_details": {}, "ability_schools": {}}
        run.cat.name_to_id = {"Feint": 1966}
        run.cat.all = {1966: {"name": "Feint", "kind": "personal", "class": "Rogue",
                              "mitigation": [{"dr": 0.4, "school": "aoe"}]}}
        run.cat.relevant_talent_entries = set()
        run.combatants.return_value = []
        hit = lambda through, buffs, aoe: {"type": "damage", "targetID": 2, "abilityGameID": 1, "fight": 1,
                                           "unmitigatedAmount": 1250, "mitigated": 1250 - through,
                                           "amount": through, "buffs": buffs, "isAoE": aoe}
        hits = [hit(1000, "", True)] * 10 + [hit(1000, "", False)] * 10
        hits += [hit(600, "1966.", True)] * 20 + [hit(1000, "1966.", False)] * 15 + [hit(600, "1966.", True)]
        with mock.patch.object(source_mitigation.defensives, "_paged", return_value=hits):
            self.assertEqual(source_mitigation.check(run).status, "pass")
        # A log that marks no hit AoE (before Midnight): the AoE-only reduction can't be predicted,
        # so nothing is measured, and that is a skip, never a pass.
        hits = [dict(h, isAoE=False) for h in hits]
        with mock.patch.object(source_mitigation.defensives, "_paged", return_value=hits):
            o = source_mitigation.check(run)
        self.assertEqual(o.status, "skip")
        self.assertIn("no defensive had enough matched hits to measure", o.reason)

    def test_wrong_catalog_value_is_flagged(self):
        # The catalog says Barkskin takes 20% off; matched hits show 10% over 25 hits: one item.
        from checks import source_mitigation
        run = mock.Mock(); run.code = "X"
        run.pulls = [{"id": 1, "start_time": 0, "end_time": 100_000}]
        run.meta = {"abilities": {22812: "Barkskin", 9: "Mark of the Wild"},
                    "friendlies": [{"id": 3, "name": "Oak", "type": "Druid"}],
                    "player_details": {}, "ability_schools": {}}
        run.cat.name_to_id = {"Barkskin": 22812}
        run.cat.all = {22812: {"name": "Barkskin", "kind": "personal", "class": "Druid", "mitigation": [{"dr": 0.2}]}}
        run.cat.relevant_talent_entries = set()
        run.combatants.return_value = []
        hit = lambda through, buffs: {"type": "damage", "targetID": 3, "abilityGameID": 1, "fight": 1,
                                      "unmitigatedAmount": 1250, "mitigated": 1250 - through,
                                      "amount": through, "buffs": buffs}
        hits = [hit(1000, "9.")] * 10 + [hit(900, "22812.9.")] * 25
        with mock.patch.object(source_mitigation.defensives, "_paged", return_value=hits):
            o = source_mitigation.check(run)
        self.assertEqual((o.status, o.items), ("fail", ["Oak Barkskin: measured 0.10, catalog 0.20 over 25 hits"]))
        # Too few matched hits to judge (under 20): a skip, not a pass.
        with mock.patch.object(source_mitigation.defensives, "_paged", return_value=hits[:15]):
            self.assertEqual(source_mitigation.check(run).status, "skip")

    def _wave1_run(self, entries, friendlies, abilities, combatants=()):
        run = mock.Mock(); run.code = "X"
        run.pulls = [{"id": 1, "start_time": 0, "end_time": 100_000}]
        run.meta = {"abilities": abilities, "friendlies": friendlies, "player_details": {}, "ability_schools": {}}
        run.cat.name_to_id = {e["name"]: sid for sid, e in entries.items()}
        run.cat.all = entries
        run.cat.relevant_talent_entries = set()
        run.combatants.return_value = list(combatants)
        return run

    def test_effects_it_cannot_measure_are_left_out(self):
        # Live 2026-10-08 sweep, wave 1: each of these read far from the catalog for a reason that
        # isn't the catalog's value. Stagger ticks (Weavi Fortifying Brew 0.15 vs 0.30) are never reduced
        # at tick time; Bear Form (Zeforus -0.01 vs 0.06) is a Guardian's own form, which the site never judges.
        from checks import source_mitigation
        entries = {115203: {"name": "Fortifying Brew", "kind": "personal", "class": "Monk",
                            "mitigation": [{"dr": 0.3}]},
                   5487: {"name": "Bear Form", "kind": "personal", "class": "Druid",
                          "specs": ["Balance", "Feral", "Restoration"], "mitigation": [{"dr": 0.06}]}}
        abilities = {115203: "Fortifying Brew", 5487: "Bear Form"}
        friendlies = [{"id": 2, "name": "Weavi", "type": "Monk"}, {"id": 3, "name": "Zef", "type": "Druid"}]
        hit = lambda who, ability, through, buffs: {"type": "damage", "targetID": who, "abilityGameID": ability,
                                                    "fight": 1, "unmitigatedAmount": 1000, "mitigated": 1000 - through,
                                                    "amount": through, "buffs": buffs}
        hits = [hit(2, 124255, 600, "")] * 10 + [hit(2, 124255, 600, "115203.")] * 25   # Stagger ticks
        hits += [hit(3, 9, 900, "")] * 10 + [hit(3, 9, 900, "5487.")] * 25
        combatants = [{"fight": 1, "sourceID": 3, "specID": 104, "talentTree": []}]    # 104: Guardian
        run = self._wave1_run(entries, friendlies, abilities, combatants)
        with mock.patch.object(source_mitigation.defensives, "_paged", return_value=hits):
            o = source_mitigation.check(run)
        self.assertEqual(o.status, "skip")
        self.assertIn("(0 rows compared)", o.reason)
        # The same Bear Form hits on a Feral (103) are measured and flagged: 0.00 against 0.06.
        run = self._wave1_run(entries, friendlies, abilities, [dict(combatants[0], specID=103)])
        with mock.patch.object(source_mitigation.defensives, "_paged", return_value=hits):
            o = source_mitigation.check(run)
        self.assertEqual(o.items, ["Zef Bear Form: measured 0.00, catalog 0.06 over 25 hits"])

    def test_fiery_brand_is_measured_on_the_branded_units_raw_hits(self):
        # Live 2026-10-08 (Lazelele, Nerub-ar): Fiery Brand cuts the branded enemy's damage done, which WCL
        # already counts in unmitigatedAmount, so the share through read 0.02 against 0.40. The same unit's
        # same ability, a branded hit next to an unbranded one, read 0.400 (123 pairs; Lunchay, Undermine:
        # 288 pairs). All branded hits against all unbranded ones within 30 s read 0.374: Liquefy's ticks
        # grow over its cast and players brand at its start.
        from checks import source_mitigation
        entries = {204021: {"name": "Fiery Brand", "kind": "personal", "class": "DemonHunter",
                            "specs": ["Vengeance"], "mitigation": [{"dr": 0.4}]}}
        friendlies = [{"id": 1, "name": "Laz", "type": "DemonHunter"}]
        combatants = [{"fight": 1, "sourceID": 1, "specID": 581, "talentTree": []}]      # 581: Vengeance
        hit = lambda t, raw, buffs, unit=50: {"type": "damage", "targetID": 1, "sourceID": unit, "abilityGameID": 9,
                                              "fight": 1, "timestamp": t, "unmitigatedAmount": raw,
                                              "mitigated": raw // 2, "amount": raw - raw // 2, "buffs": buffs}
        hits = []
        for k in range(25):
            t = k * 20_000
            # Branded, then the ability ramps: the next tick is unbranded, later ones bigger still. Only the
            # back-to-back pair (1000 -> 1700) reads 0.41; pairing the branded hit with every unbranded one
            # within 3 s would add 1000 -> 4000 (0.75) and read a median of 0.58, which fails.
            hits += [hit(t, 1000, "207771."), hit(t + 1000, 1700, ""), hit(t + 2000, 4000, ""),
                     hit(t + 9000, 3000, "")]
            hits += [hit(t + 500, 1000, "", unit=51), hit(t + 1500, 1000, "", unit=51)]   # another unit
        run = self._wave1_run(entries, friendlies, {207771: "Fiery Brand"}, combatants)
        with mock.patch.object(source_mitigation.defensives, "_paged", return_value=hits):
            self.assertEqual(source_mitigation.check(run).status, "pass")
        # Pairs that read 0.41 against a catalog value of 0.30: flagged.
        wrong = {204021: dict(entries[204021], mitigation=[{"dr": 0.3}])}
        run = self._wave1_run(wrong, friendlies, {207771: "Fiery Brand"}, combatants)
        with mock.patch.object(source_mitigation.defensives, "_paged", return_value=hits):
            o = source_mitigation.check(run)
        self.assertEqual(o.items, ["Laz Fiery Brand: measured 0.41, catalog 0.30 over 25 pairs"])
        # A branded and an unbranded hit more than PAIR_MS apart are not compared: nothing measured.
        apart = [dict(h, timestamp=h["timestamp"] + 5000) if h["buffs"] == "" else h for h in hits]
        with mock.patch.object(source_mitigation.defensives, "_paged", return_value=apart):
            self.assertEqual(source_mitigation.check(run).status, "skip")
        # On a Havoc (577) the catalog doesn't give it: never judged.
        run = self._wave1_run(wrong, friendlies, {207771: "Fiery Brand"}, [dict(combatants[0], specID=577)])
        with mock.patch.object(source_mitigation.defensives, "_paged", return_value=hits):
            self.assertEqual(source_mitigation.check(run).status, "skip")

    def test_dampen_harm_grows_with_the_hit(self):
        # Live 2026-10-08: Dampen Harm ("20% to 50%, larger attacks reduced by more") took 0.20 off small
        # hits and 0.20 + 0.30 x off a hit of x max health after the player's other reductions (Atlai,
        # Undermine: 0.285 at x = 0.285, 0.350 at 0.500; Weavi: 0.383 at 0.610).
        from checks import source_mitigation
        entries = {122278: {"name": "Dampen Harm", "kind": "personal", "class": "Monk", "mitigation": [{"dr": 0.2}]}}
        friendlies = [{"id": 2, "name": "Weavi", "type": "Monk"}]

        def hit(ability, raw, through, buffs, health=True):
            e = {"type": "damage", "targetID": 2, "abilityGameID": ability, "fight": 1, "unmitigatedAmount": raw,
                 "mitigated": raw - through, "amount": through, "buffs": buffs}
            if health:
                e.update(resourceActor=2, hitPoints=9_000_000 - through, maxHitPoints=10_000_000)
            return e
        small, big = 1_000_000, 6_000_000          # 0.9 through without it: x = 0.09 and 0.54
        hits = [hit(1, small, 900_000, "")] * 5 + [hit(2, big, 5_400_000, "")] * 5
        hits += [hit(1, small, round(900_000 * (1 - 0.2 - 0.3 * 0.09)), "122278.")] * 12
        hits += [hit(2, big, round(5_400_000 * (1 - 0.2 - 0.3 * 0.54)), "122278.")] * 12
        run = self._wave1_run(entries, friendlies, {122278: "Dampen Harm"})
        with mock.patch.object(source_mitigation.defensives, "_paged", return_value=hits):
            self.assertEqual(source_mitigation.check(run).status, "pass")
        # The same hits against a catalog value of 0.30 at no damage: flagged.
        wrong = {122278: dict(entries[122278], mitigation=[{"dr": 0.3}])}
        run = self._wave1_run(wrong, friendlies, {122278: "Dampen Harm"})
        with mock.patch.object(source_mitigation.defensives, "_paged", return_value=hits):
            o = source_mitigation.check(run)
        self.assertEqual(o.items, ["Weavi Dampen Harm: measured 0.29, predicted 0.36 (catalog 0.30) over 24 hits"])
        # Without the player's health on the hits, their size can't be put against max health: left out.
        bare = [hit(h["abilityGameID"], h["unmitigatedAmount"], h["amount"], h["buffs"], health=False) for h in hits]
        run = self._wave1_run(entries, friendlies, {122278: "Dampen Harm"})
        with mock.patch.object(source_mitigation.defensives, "_paged", return_value=bare):
            self.assertEqual(source_mitigation.check(run).status, "skip")

    def test_dampen_harm_size_is_after_other_reductions_and_capped_at_half(self):
        from checks import source_mitigation
        entries = {122278: {"name": "Dampen Harm", "kind": "personal", "class": "Monk", "mitigation": [{"dr": 0.2}]}}
        friendlies = [{"id": 2, "name": "Weavi", "type": "Monk"}]

        def hit(ability, raw, through, buffs):
            return {"type": "damage", "targetID": 2, "abilityGameID": ability, "fight": 1, "unmitigatedAmount": raw,
                    "mitigated": raw - through, "amount": through, "buffs": buffs,
                    "resourceActor": 2, "hitPoints": 9_000_000, "maxHitPoints": 10_000_000}

        def status(hits):
            run = self._wave1_run(entries, friendlies, {122278: "Dampen Harm"})
            with mock.patch.object(source_mitigation.defensives, "_paged", return_value=hits):
                return source_mitigation.check(run).status
        # Heavy other reductions: only 0.5 of the raw 8M gets through, so x = 4M / 10M = 0.4 and the cut is
        # 0.20 + 0.30 x 0.4 = 0.32. Measuring x on the raw hit (0.8) would predict 0.44 and flag it.
        raw, usual = 8_000_000, 0.5
        hits = [hit(3, raw, round(raw * usual), "")] * 5
        hits += [hit(3, raw, round(raw * usual * (1 - 0.32)), "122278.")] * 25
        self.assertEqual(status(hits), "pass")
        # A hit of more than max health (x = 1.14) is capped at the 0.50 reduction, not 0.2 + 0.3 x 1.14 = 0.54.
        raw, usual = 12_000_000, 0.95
        hits = [hit(4, raw, round(raw * usual), "")] * 5
        hits += [hit(4, raw, round(raw * usual * (1 - 0.50)), "122278.")] * 25
        self.assertEqual(status(hits), "pass")
        hits = hits[:5] + [hit(4, raw, round(raw * usual * (1 - 0.54)), "122278.")] * 25
        self.assertEqual(status(hits), "fail")

    def test_one_odd_boss_ability_does_not_decide(self):
        # Live 2026-10-08 (Pumps, Undermine): Barkskin read 0.29-0.32 on every ability but Sonic Ba-Boom,
        # whose hits vary 0.3-0.95 through without any defensive (an untracked fight modifier); the hit-
        # weighted mean gave 0.21 against 0.30. The median gap over hits judges the catalog value.
        from checks import source_mitigation
        entries = {22812: {"name": "Barkskin", "kind": "personal", "class": "Druid", "mitigation": [{"dr": 0.3}]}}
        run = self._wave1_run(entries, [{"id": 3, "name": "Pumps", "type": "Druid"}], {22812: "Barkskin"})
        hit = lambda ability, through, buffs: {"type": "damage", "targetID": 3, "abilityGameID": ability, "fight": 1,
                                               "unmitigatedAmount": 1000, "mitigated": 1000 - through,
                                               "amount": through, "buffs": buffs}
        hits = [hit(1, 900, "")] * 5 + [hit(1, 630, "22812.")] * 12
        hits += [hit(2, 800, "")] * 5 + [hit(2, 560, "22812.")] * 10
        hits += [hit(3, 800, "")] * 5 + [hit(3, 800, "22812.")] * 9                # reads 0.00
        with mock.patch.object(source_mitigation.defensives, "_paged", return_value=hits):
            self.assertEqual(source_mitigation.check(run).status, "pass")
        # A catalog value that is wrong is off on every ability, and is still flagged.
        hits = [h if h["buffs"] == "" else dict(h, amount=round(h["amount"] / 0.7 * 0.8)) for h in hits[:32]]
        with mock.patch.object(source_mitigation.defensives, "_paged", return_value=hits):
            o = source_mitigation.check(run)
        self.assertEqual(o.items, ["Pumps Barkskin: measured 0.20, catalog 0.30 over 22 hits"])

    def test_reduction_by_missing_health_is_predicted_from_each_hit(self):
        # Live 2026-10-08 (Sunnyvi, Blood, Quel'Danas): Icebound Fortitude with Bloody Fortitude (up to
        # 20% more by missing health) read 0.323 at 90%+ health and 0.364 at 50-75%; judged against a
        # flat 0.30 it was flagged "measured 0.35, catalog 0.30 over 56 hits".
        from checks import source_mitigation
        entries = {48792: {"name": "Icebound Fortitude", "kind": "personal", "class": "DeathKnight",
                           "mitigation": [{"dr": 0.3}, {"dr_missing": 0.2,
                                                        "needs": {"entries": [117891], "talent": "Bloody Fortitude"}}]}}
        friendlies = [{"id": 5, "name": "Sunny", "type": "DeathKnight"}]
        hit = lambda through, buffs, before=None: dict(
            {"type": "damage", "targetID": 5, "abilityGameID": 9, "fight": 1, "unmitigatedAmount": 1250,
             "mitigated": 1250 - through, "amount": through, "buffs": buffs},
            **({"resourceActor": 2, "hitPoints": before - through, "maxHitPoints": 10_000} if before else {}))
        # Half health missing: 1 - 0.7 x (1 - 0.2 x 0.5) = 0.37 off. Full health: 0.30.
        hits = [hit(1000, "")] * 10 + [hit(630, "48792.", 5_000)] * 15 + [hit(700, "48792.", 10_000)] * 10
        combatants = [{"fight": 1, "sourceID": 5, "specID": 250, "talentTree": [{"id": 117891, "rank": 1}]}]
        run = self._wave1_run(entries, friendlies, {48792: "Icebound Fortitude"}, combatants)
        run.cat.relevant_talent_entries = {117891}
        with mock.patch.object(source_mitigation.defensives, "_paged", return_value=hits):
            self.assertEqual(source_mitigation.check(run).status, "pass")
        # Without Bloody Fortitude, the half-health hits read 0.37 against a flat 0.30: flagged.
        run = self._wave1_run(entries, friendlies, {48792: "Icebound Fortitude"},
                              [dict(combatants[0], talentTree=[])])
        with mock.patch.object(source_mitigation.defensives, "_paged", return_value=hits):
            o = source_mitigation.check(run)
        self.assertEqual(o.items, ["Sunny Icebound Fortitude: measured 0.37, catalog 0.30 over 25 hits"])
        # Bloody Fortitude taken into account, a wrong catalog value is still flagged: 0.20 against hits
        # that read 0.37 at half health and 0.30 at full (0.28 and 0.20 predicted).
        wrong = {48792: dict(entries[48792], mitigation=[{"dr": 0.2}, entries[48792]["mitigation"][1]])}
        run = self._wave1_run(wrong, friendlies, {48792: "Icebound Fortitude"}, combatants)
        run.cat.relevant_talent_entries = {117891}
        with mock.patch.object(source_mitigation.defensives, "_paged", return_value=hits):
            o = source_mitigation.check(run)
        self.assertEqual(o.items, ["Sunny Icebound Fortitude: measured 0.34, predicted 0.25 (catalog 0.20) over 25 hits"])
        # With the talent but no health on the hits, the reduction can't be predicted: left out.
        run = self._wave1_run(entries, friendlies, {48792: "Icebound Fortitude"}, combatants)
        run.cat.relevant_talent_entries = {117891}
        bare = [hit(1000, "")] * 10 + [hit(630, "48792.")] * 25
        with mock.patch.object(source_mitigation.defensives, "_paged", return_value=bare):
            self.assertEqual(source_mitigation.check(run).status, "skip")


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

    def test_same_player_twice_on_one_millisecond(self):
        # Live 2026-10-07 (Hunterben, Manaforge pull 66): WCL lists two deaths of one player on the
        # same millisecond; the site gives them slots 1 and 2, and so does the rule.
        table = [{"id": 1, "timestamp": 1500}, {"id": 1, "timestamp": 1500}, {"id": 2, "timestamp": 1900}]
        evs = [self._ev(1, "A", 500, 2), self._ev(1, "A", 500, 1), self._ev(1, "B", 900, 3)]
        self.assertEqual(rules_slots.check(self._run({"A": evs}, {1: table})).status, "pass")


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
                             "hpBeforePct": 50, "killingHit": {"size": 600},
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
        cat.all[1]["mitigation"] = [{"immune": True}]
        self.assertEqual(violations(self.base(), cat), [])
        self.assertEqual(len(violations(self.base(), cat, ignores_immunity=True)), 1)

    def test_check_over_counted_deaths(self):
        cat = mock.Mock(); cat.name_to_id = {}; cat.all = {}
        ev = lambda slot, d, wipe=False: {"slot": slot, "inWipe": wipe, "isCheatDeath": False, "fightId": 2,
                                          "timestamp": slot, "defensives": d}
        run = mock.Mock(); run.cat = cat; run.actor_id.return_value = None
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

    def test_amount_is_bounded_by_missing_health_plus_the_killing_hit(self):
        # Live 2026-10-07 (Pelinmerkkii, Obsidian Scales): 30% off a 32.8M one-shot is 10.1M saved,
        # ten times max HP. Only the extra health is capped (500 missing here), not the cut of the hit.
        cat = mock.Mock(); cat.name_to_id = {}; cat.all = {}
        d = self.base(); s = d["survival"]
        s["killingHit"], s["overkill"], s["wouldSave"]["Barkskin"] = {"size": 32_800}, 31_800, False
        s["details"]["Barkskin"]["amount"] = 10_100
        self.assertEqual(violations(d, cat), [])
        d = self.base(); d["survival"]["details"]["Barkskin"]["amount"] = 1_111
        self.assertIn("Barkskin: amount 1111 above missing health 500 plus the killing hit 600", violations(d, cat))
        d = self.base(); d["survival"]["details"]["Barkskin"]["amount"] = 1_110
        self.assertEqual(violations(d, cat), [])
        # Without the killing hit's size, max HP is the bound.
        d = self.base(); del d["survival"]["killingHit"]; d["survival"]["details"]["Barkskin"]["amount"] = 1_001
        self.assertIn("Barkskin: amount above max HP", violations(d, cat))
        d["survival"]["details"]["Barkskin"]["amount"] = 1_000
        self.assertEqual(violations(d, cat), [])

    def test_missing_health_is_never_negative(self):
        # Live 2026-10-08 (Strikepal, Nerub-ar pull 16): the site showed 105% health before the killing
        # blow (state reports that), and Divine Shield's amount was exactly the 15912627 killing hit.
        # Missing health is 0 there, not -503069, so an immunity worth the whole hit is in bounds.
        cat = mock.Mock(); cat.name_to_id = {}; cat.all = {}
        d = self.base(); s = d["survival"]
        s.update(hpBeforePct=105, maxHp=10_061_382, overkill=4_552_041, killingHit={"size": 15_912_627},
                 wouldSave={"Divine Shield": True}, details={"Divine Shield": {"amount": 15_912_627, "pressAgo": 1.0}})
        d["available"] = [{"name": "Divine Shield"}]
        self.assertEqual(violations(d, cat), [])
        s["details"]["Divine Shield"]["amount"] = 16_100_000          # above the hit plus 1% of max HP
        self.assertEqual(violations(d, cat), ["Divine Shield: amount 16100000 above missing health 0 "
                                              "plus the killing hit 15912627"])

    def bad(self):
        d = self.base(); d["survival"]["details"]["Barkskin"]["pressAgo"] = 0.4
        return d

    def test_site_immunity_flag_is_not_trusted(self):
        # The site's ignoresImmunity says False; WCL's killing ability (the death event's abilityId)
        # is on IGNORES_IMMUNITY, so an immunity marked saves is a violation, and the reverse passes.
        from boss_spell_flags import IGNORES_IMMUNITY
        through = min(IGNORES_IMMUNITY)
        cat = mock.Mock(); cat.name_to_id = {"Barkskin": 1}; cat.all = {1: {"mitigation": [{"immune": True}]}}
        run = mock.Mock(); run.cat = cat; run.actor_id.return_value = None
        ev = {"slot": 1, "inWipe": False, "isCheatDeath": False, "fightId": 2, "timestamp": 1, "reportId": "R",
              "abilityId": through, "defensives": self.base()}
        run.result = {"meta": {"maxCutoff": 2}, "events": {"Bob": [ev]}}
        o = rules_verdicts.check(run)
        self.assertEqual(o.items, ["Bob pull 2 1: Barkskin: immunity marked saves against a hit that ignores immunity"])
        ev["defensives"]["survival"]["ignoresImmunity"] = True
        ev["abilityId"] = 1
        self.assertEqual(rules_verdicts.check(run).status, "pass")
        # Without abilityId, the report's abilities named like the killing hit decide.
        del ev["abilityId"]
        ev["defensives"]["survival"]["killingHit"]["name"] = "Sever"
        run.meta_for.return_value = {"abilities": {5: "Other", through: "Sever"}}
        self.assertEqual(rules_verdicts.check(run).status, "fail")
        run.meta_for.assert_called_with("R")
        run.meta_for.return_value = {"abilities": {5: "Sever"}}
        self.assertEqual(rules_verdicts.check(run).status, "pass")

    def test_early_presses(self):
        details = {"A": {"pressAgo": 3.0}, "B": {"pressAgo": 2.0}, "C": {"amount": 0, "why": "readyTooLate"}}
        # A ready 2.0s before the killing blow at 10000, pressed 3.0s before: flagged. B pressed within
        # 100 ms of becoming ready passes; a name with no known ready time is skipped.
        self.assertEqual(rules_verdicts.early_presses(details, 10_000, {"A": 8_000, "B": 8_050, "C": 9_000}),
                         ["A: pressed 3.0s before the killing blow but only ready 2.0s before"])
        self.assertEqual(rules_verdicts.early_presses(details, 10_000, {}), [])
        self.assertEqual(rules_verdicts.killing_hit_ts(
            [{"timestamp": 5, "overkill": 9}, {"timestamp": 8, "overkill": 0}, {"timestamp": 60, "overkill": 1}], 9), 5)
        self.assertIsNone(rules_verdicts.killing_hit_ts([{"timestamp": 5, "overkill": 0}], 9))

    def _press_run(self):
        start = 100_000
        cat = mock.Mock()
        cat.name_to_id = {"Barkskin": 1, "Healthstone": 4}
        cat.all = {1: {"name": "Barkskin", "kind": "personal", "cooldown_ms": 60_000, "charges": 1},
                   4: {"name": "Healthstone", "kind": "healthstone", "cooldown_ms": 60_000, "charges": 1}}
        run = mock.Mock(); run.cat = cat; run.actor_id.return_value = 7
        run.fight.return_value = {"start_time": start, "end_time": start + 120_000}
        run.combatants.return_value = [{"sourceID": 7, "fight": 1, "specID": 104, "talentTree": []}]
        kb = start + 100_000
        run.hits_before.return_value = [{"timestamp": kb - 3_000, "overkill": 0}, {"timestamp": kb, "overkill": 50}]
        # Barkskin pressed 65s before the killing blow (ready again 5s before it); a Healthstone 62s before.
        run.casts.return_value = [{"type": "cast", "abilityGameID": 1, "timestamp": kb - 65_000},
                                  {"type": "cast", "abilityGameID": 4, "timestamp": kb - 62_000}]
        d = self.base(); s = d["survival"]
        s["consumables"] = {"Healthstone": "healthstone"}
        s["wouldSave"] = {"Barkskin": False, "Healthstone": False}
        s["details"] = {"Barkskin": {"amount": 50, "pressAgo": 5.0}, "Healthstone": {"amount": 50, "pressAgo": 2.0}}
        ev = {"slot": 1, "inWipe": False, "isCheatDeath": False, "fightId": 1, "timestamp": 100_000, "reportId": "R",
              "originalCharacter": "Oak", "spec": "Guardian", "defensives": d}
        run.result = {"meta": {"maxCutoff": 2}, "events": {"Oak": [ev]}, "pullParticipation": {"Oak": ["R_1"]}}
        return run, s

    def test_press_never_before_the_ability_was_ready(self):
        run, s = self._press_run()
        self.assertEqual(rules_verdicts.check(run).status, "pass")
        run.hits_before.assert_called_with("R", 1, 7, 200_000)
        s["details"]["Barkskin"]["pressAgo"] = 6.0
        s["details"]["Healthstone"]["pressAgo"] = 2.5
        self.assertEqual(rules_verdicts.check(run).items, [
            "Oak pull 1 100000: Barkskin: pressed 6.0s before the killing blow but only ready 5.0s before",
            "Oak pull 1 100000: Healthstone: pressed 2.5s before the killing blow but only ready 2.0s before"])
        # No killing hit found: the ready times can't be compared, nothing is flagged.
        run.hits_before.return_value = []
        self.assertEqual(rules_verdicts.check(run).status, "pass")

    def test_press_ready_all_along_or_unused_consumable_is_not_flagged(self):
        run, s = self._press_run()
        run.casts.return_value = []
        s["details"]["Barkskin"]["pressAgo"] = 14.0
        s["details"]["Healthstone"]["pressAgo"] = 14.0
        self.assertEqual(rules_verdicts.check(run).status, "pass")


class LabelRuleTests(unittest.TestCase):
    def hit(self, ts, amount, hp_after, aid=1, overkill=0):
        return {"timestamp": ts, "amount": amount, "overkill": overkill, "absorbed": 0,
                "hitPoints": hp_after, "maxHitPoints": 1000, "abilityGameID": aid, "resourceActor": 2}

    def test_one_shot_burst_and_was_low(self):
        kb = self.hit(1000, 900, 0, overkill=50)                       # 950 of 1000 from full
        self.assertEqual(label([self.hit(0, 10, 990), kb], 1)["deathType"], "oneShot")
        burst = [self.hit(0, 10, 990), self.hit(500, 400, 590), self.hit(990, 590, 0, overkill=10)]
        self.assertEqual(label(burst, 2)["deathType"], "burst")
        # High just before the 400 hit (t=500): 1.5 s later is still a burst, 1.6 s is not.
        self.assertEqual(label([self.hit(0, 10, 990), self.hit(500, 400, 590), self.hit(2000, 590, 0, overkill=10)], 2)["deathType"], "burst")
        slow = [self.hit(0, 10, 990), self.hit(500, 400, 590), self.hit(2100, 590, 0, overkill=10)]
        self.assertEqual(label(slow, 2), {"deathType": "wasLow", "rot": None, "biggestHit": 1, "oneShotHit": None})

    def test_rot_needs_a_raid_wide_ability(self):
        aid = next(iter(RAID_WIDE))
        hits = [self.hit(0, 10, 990)] + [self.hit(1000 * i, 200, 990 - 200 * i, aid=aid) for i in range(1, 5)] \
             + [self.hit(6000, 190, 0, aid=aid, overkill=10)]
        self.assertEqual(label(hits, 5)["rot"], aid)
        not_wide = [dict(h, abilityGameID=999_999) for h in hits]
        self.assertEqual(label(not_wide, 5)["rot"], None)

    def test_threshold_edges(self):
        # "quick" is measured from the last moment at high health (t=0 here) to the killing blow:
        # at most 1.5 s (owner's rule, 2026-10-08), not the 1 s press cutoff.
        self.assertEqual(label([self.hit(0, 10, 990), self.hit(600, 100, 700), self.hit(1501, 700, 0, overkill=5)], 2)["deathType"], "wasLow")
        self.assertEqual(label([self.hit(0, 10, 990), self.hit(600, 100, 700), self.hit(1499, 700, 0, overkill=5)], 2)["deathType"], "burst")
        self.assertEqual(label([self.hit(0, 10, 990), self.hit(600, 100, 700), self.hit(1200, 700, 0, overkill=5)], 2)["deathType"], "burst")
        # One-shot needs a single hit of 80 % of max HP or more (800 of 1000); 799 is burst.
        self.assertEqual(label([self.hit(0, 10, 990), self.hit(100, 190, 800), self.hit(500, 800, 0)], 2)["deathType"], "oneShot")
        self.assertEqual(label([self.hit(0, 10, 990), self.hit(100, 191, 799), self.hit(500, 799, 0)], 2)["deathType"], "burst")

    def test_high_just_before_a_hit_and_only_the_players_own_health(self):
        # Live 2026-10-07 (Manaforge): heals land between hits, so a player at 85%+ just before a hit
        # (hitPoints + amount) was at high health then; and hits whose resources are the attacker's
        # (resourceActor 1) say nothing about the player's health.
        h = self.hit
        hits = [h(0, 10, 500), h(2000, 600, 300), h(2500, 300, 0, overkill=5)]   # 90% just before t=2000
        self.assertEqual(label(hits, 2)["deathType"], "burst")
        attacker = dict(h(2200, 10, 990), resourceActor=1)
        hits = [h(0, 10, 500), h(1500, 100, 400), attacker, h(2500, 400, 0, overkill=5)]
        self.assertEqual(label(hits, 3)["deathType"], "wasLow")

    def test_set_up_hit_needs_ten_percent_and_a_burst_has_none(self):
        small = [self.hit(0, 10, 990), self.hit(2000, 99, 500), self.hit(3000, 500, 0, overkill=1)]
        self.assertEqual(label(small, 2)["biggestHit"], None)
        pick = [self.hit(0, 10, 990), self.hit(1500, 100, 700, aid=7), self.hit(2000, 200, 500, aid=8),
                self.hit(3000, 500, 0, aid=9, overkill=1)]
        self.assertEqual(label(pick, 3), {"deathType": "wasLow", "rot": None, "biggestHit": 8, "oneShotHit": None})

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

    def test_exactly_one_and_a_half_seconds_is_quick(self):
        self.assertEqual(label([self.hit(0, 10, 990), self.hit(600, 790, 200), self.hit(1500, 200, 0, overkill=5)], 2)["deathType"], "burst")

    def test_one_shot_names_its_hit_and_never_a_set_up_hit(self):
        h = self.hit
        # Live (Chazh, Voidspire pull 66): Melee 92%, then an 81% Judgment kills 0.4 s later.
        chazh = [h(0, 10, 990), h(600, 920, 70, aid=1), h(1000, 70, 0, aid=2, overkill=740)]
        self.assertEqual(label(chazh, 2), {"deathType": "oneShot", "rot": None, "biggestHit": None, "oneShotHit": 1})
        # The killing blow is the biggest hit: nothing more to name.
        kb_big = [h(0, 10, 990), h(600, 100, 890, aid=1), h(1000, 890, 0, aid=2, overkill=100)]
        self.assertEqual(label(kb_big, 2)["oneShotHit"], None)

    def test_check_biggest_hit_only_where_the_page_shows_it(self):
        h = self.hit
        run = mock.Mock()
        run.actor_id.return_value = 7
        run.fight.return_value = {"start_time": 0}
        def go(hits, survival):
            ev = {"slot": 1, "inWipe": False, "isCheatDeath": False, "fightId": 2, "reportId": "R", "timestamp": hits[-1]["timestamp"],
                  "originalCharacter": "Bob", "defensives": {"survival": survival}}
            run.counted_deaths.return_value = [ev]
            run.hits_before.return_value = hits
            return rules_labels.check(run)
        burst = [h(0, 10, 990), h(500, 400, 590), h(990, 590, 0, overkill=10)]
        self.assertEqual(go(burst, {"deathType": "burst"}).status, "pass")
        # "Set up by" is only for deaths that are neither one-shot nor burst.
        self.assertEqual(go(burst, {"deathType": "burst", "biggestHit": {"abilityId": 1}}).status, "fail")
        shot = [h(0, 10, 990), h(1000, 900, 0, overkill=50)]
        self.assertEqual(go(shot, {"deathType": "oneShot"}).status, "pass")
        o = go(shot, {"deathType": "oneShot", "biggestHit": {"abilityId": 1}})
        self.assertEqual((o.status, len(o.items)), ("fail", 1))
        big_then_tick = [h(0, 10, 990), h(500, 900, 90, aid=4), h(990, 90, 0, aid=5, overkill=10)]
        self.assertEqual(go(big_then_tick, {"deathType": "oneShot", "oneShotHit": {"abilityId": 4}}).status, "pass")
        o = go(big_then_tick, {"deathType": "oneShot", "biggestHit": {"abilityId": 4}})
        self.assertEqual(o.items, ["Bob pull 2: site oneShot/None/4/None, rule oneShot/None/None/4"])


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
        self.assertEqual((o.status, o.items), ("fail", ["Bob pull 2: site wasLow/None/None/None, rule burst/None/None/None"]))
        ev["defensives"]["survival"]["deathType"] = "instakill"
        self.assertEqual(rules_labels.check(run).status, "skip")
        # No killing hit in WCL's hits means nothing was compared: a skip, never a pass.
        ev["defensives"]["survival"]["deathType"] = "burst"
        run.hits_before.return_value = hits[:2]
        self.assertEqual(rules_labels.check(run).status, "skip")


class SelectionTests(unittest.TestCase):
    def test_cluster_overlap_and_boss(self):
        p = lambda key, boss, s, e, kill=False: {"key": key, "boss": boss, "start": s, "end": e, "kill": kill}
        cs = cluster([p("A_1", 1, 0, 100), p("B_7", 1, 50, 120), p("A_2", 1, 200, 300), p("B_8", 2, 0, 100)])
        self.assertEqual(sorted(sorted(x["key"] for x in c) for c in cs), [["A_1", "B_7"], ["A_2"], ["B_8"]])

    def test_check_accepts_either_copy_and_flags_a_missing_one(self):
        pulls = [{"key": "A_1", "boss": 1, "start": 0, "end": 100, "kill": True},
                 {"key": "B_7", "boss": 1, "start": 50, "end": 120, "kill": True},
                 {"key": "A_2", "boss": 1, "start": 200, "end": 300, "kill": False}]
        run = mock.Mock(); run.guild = ("G", "S", "US"); run.meta = {"report_start": 0}
        run.result = {"bossParticipation": {"Boss": {"Bob": ["B_7", "A_2"]}}}
        with mock.patch("checks.source_selection.walk", return_value=pulls):
            self.assertEqual(source_selection.check(run).status, "pass")
            run.result = {"bossParticipation": {"Boss": {"Bob": ["B_7"]}}}
            o = source_selection.check(run)
            self.assertEqual(o.status, "fail")
            self.assertTrue(any(i.startswith("cluster 1 ") and i.endswith(": no kept pull") for i in o.items))

    def test_check_flags_two_copies_stray_key_and_kill_counts(self):
        pulls = [{"key": "A_1", "boss": 1, "name": "Boss", "start": 0, "end": 100, "kill": True},
                 {"key": "B_7", "boss": 1, "name": "Boss", "start": 50, "end": 120, "kill": False}]
        run = mock.Mock(); run.guild = ("G", "S", "US"); run.meta = {"report_start": 0}
        run.result = {"bossParticipation": {"Boss": {"Bob": ["A_1", "B_7", "Z_9"]}}}
        with mock.patch("checks.source_selection.walk", return_value=pulls):
            o = source_selection.check(run)
        self.assertEqual(o.status, "fail")
        self.assertTrue(any("2 kept pulls" in i and "A_1" in i and "B_7" in i for i in o.items))
        self.assertIn("kept pull Z_9: not in any cluster", o.items)
        run.result = {"bossParticipation": {"Boss": {"Bob": ["B_7"]}}}
        with mock.patch("checks.source_selection.walk", return_value=pulls):
            o = source_selection.check(run)
        self.assertEqual(o.items, ["Boss: site kills 0, wcl kills 1"])

    def test_check_skips_without_guild(self):
        run = mock.Mock(); run.guild = None
        self.assertEqual(source_selection.check(run).status, "skip")

    def test_check_skips_when_the_walk_finds_no_pulls(self):
        run = mock.Mock(); run.guild = ("G", "S", "US"); run.meta = {"report_start": 0}; run.raid = "manaforge"
        run.result = {"bossParticipation": {}}
        with mock.patch("checks.source_selection.walk", return_value=[]):
            o = source_selection.check(run)
        self.assertEqual((o.status, o.reason), ("skip", "no Mythic pulls of manaforge in the guild's reports that week"))

    def test_walk_keeps_mythic_raid_fights_with_absolute_times(self):
        import analysis
        raid = "manaforge"
        boss = min(analysis.RAID_ENCOUNTERS[raid])
        run = mock.Mock(); run.guild = ("G", "S", "US"); run.raid = raid; run.token = "t"
        fights = {"report_start": 1000, "fights": [
            {"id": 1, "start_time": 10, "end_time": 20, "name": "B", "boss": boss, "difficulty": 5, "kill": True},
            {"id": 2, "start_time": 10, "end_time": 20, "name": "B", "boss": boss, "difficulty": 4, "kill": True},
            {"id": 3, "start_time": 10, "end_time": 20, "name": "X", "boss": 999999, "difficulty": 5, "kill": True}]}
        with mock.patch("checks.source_selection.get_guild_reports", return_value=[{"id": "R"}]),                 mock.patch("checks.source_selection.get_report_fights", return_value=fights):
            out = walk(run, "2026-01-01", "2026-01-08")
        self.assertEqual(out, [{"key": "R_1", "boss": boss, "name": "B", "start": 1010, "end": 1020, "kill": True}])


class ParticipationTests(unittest.TestCase):
    def test_accents_and_roster(self):
        run = mock.Mock(); run.guild = ("G", "S", "US"); run.token = "t"
        run.result = {"pullParticipation": {"\u00d1anda": ["R_1"], "Bob": ["R_1"]}}
        run.summary.return_value = {"composition": [{"name": "\u00d1anda"}, {"name": "Bob"}, {"name": "Pug"}]}
        with mock.patch("checks.source_participation.get_guild_roster", return_value={"nanda", "bob"}):
            self.assertEqual(source_participation.check(run).status, "pass")
        with mock.patch("checks.source_participation.get_guild_roster", return_value=set()):
            o = source_participation.check(run)
            self.assertEqual(o.status, "fail"); self.assertIn("pug", o.items[0])

    def test_skips(self):
        run = mock.Mock(); run.guild = None
        self.assertEqual(source_participation.check(run).status, "skip")
        run = mock.Mock(); run.guild = ("G", "S", "US"); run.result = {"pullParticipation": {}}
        self.assertEqual(source_participation.check(run).status, "skip")


class StateTests(unittest.TestCase):
    def test_active_bands(self):
        auras = [{"name": "Barkskin", "bands": [{"startTime": 1000, "endTime": 9000}]}]
        self.assertEqual(active_mismatches(["Barkskin"], auras, 5000), [])
        self.assertEqual(len(active_mismatches(["Barkskin"], auras, 9200)), 1)
        self.assertEqual(len(active_mismatches(["Ironbark"], auras, 5000)), 1)

    def test_active_band_reaching_the_death_strip_counts(self):
        # Live 2026-10-08 (dreamrift pull 1, Chickenism): the death stripped all 19 of her auras at
        # 1244582-1244684, Fortitude and Rallying Cry at 1244582, while WCL's death event is at 1244690,
        # 108 ms later. The living kept that Rallying Cry until 1247448.
        pull_long = [("Power Word: Fortitude", 1244582), ("Battle Shout", 1244583), ("Mark of the Wild", 1244583),
                     ("Arcane Intellect", 1244584), ("Skyfury", 1244584), ("Moonkin Form", 1244597),
                     ("Lycara's Teachings", 1244684)]
        auras = [{"name": n, "bands": [{"startTime": 1161232, "endTime": t}]} for n, t in pull_long]
        auras += [{"name": "Rallying Cry", "bands": [{"startTime": 1234456, "endTime": 1244582}]},
                  {"name": "Barkskin", "bands": [{"startTime": 1234000, "endTime": 1244300}]}]
        self.assertEqual(active_mismatches(["Rallying Cry"], auras, 1244690, 1161232), [])
        # Without the pull start there is no strip to read: the death event alone, 108 ms off.
        self.assertEqual(active_mismatches(["Rallying Cry"], auras, 1244690), ["Rallying Cry"])
        # A band that ended 282 ms before the strip is still not up at death.
        self.assertEqual(active_mismatches(["Barkskin"], auras, 1244690, 1161232), ["Barkskin"])
        # Only a band up since the pull started marks the strip: a short buff's natural end does not.
        mid = [dict(a, bands=[dict(a["bands"][0], startTime=1200000)]) for a in auras]
        self.assertEqual(active_mismatches(["Rallying Cry"], mid, 1244690, 1161232), ["Rallying Cry"])

    def test_death_strip_needs_a_cluster_of_pull_long_bands(self):
        # Review 2026-10-08: one pull-long band ending alone (a form dropped 900 ms before death) is not
        # the death's strip; a defensive that ended with it was not up at death.
        auras = [{"name": "Moonkin Form", "bands": [{"startTime": 1000, "endTime": 9100}]},
                 {"name": "Barkskin", "bands": [{"startTime": 5000, "endTime": 9100}]},
                 {"name": "Power Word: Fortitude", "bands": [{"startTime": 1000, "endTime": 9890}]},
                 {"name": "Battle Shout", "bands": [{"startTime": 1000, "endTime": 9900}]},
                 {"name": "Mark of the Wild", "bands": [{"startTime": 1000, "endTime": 9950}]}]
        self.assertEqual(death_strip(auras, 10_000, 1000), 9890)
        self.assertEqual(active_mismatches(["Barkskin"], auras, 10_000, 1000), ["Barkskin"])
        # The form alone, with nothing else ending: no strip, the death event decides.
        self.assertEqual(death_strip(auras[:2], 10_000, 1000), 10_000)
        self.assertEqual(active_mismatches(["Barkskin"], auras[:2], 10_000, 1000), ["Barkskin"])
        # Two bands ending together while three others end elsewhere in the second: not a majority.
        split = [{"name": n, "bands": [{"startTime": 1000, "endTime": t}]}
                 for n, t in (("A", 9100), ("B", 9150), ("C", 9500), ("D", 9800), ("E", 9990))]
        self.assertEqual(death_strip(split, 10_000, 1000), 10_000)

    def test_ready_at_with_charges(self):
        self.assertTrue(ready_at([], 10_000, 60_000, 1))
        self.assertFalse(ready_at([5_000], 10_000, 60_000, 1))
        self.assertTrue(ready_at([5_000], 70_000, 60_000, 1))
        self.assertTrue(ready_at([5_000], 10_000, 60_000, 2))
        self.assertFalse(ready_at([5_000, 6_000], 10_000, 60_000, 2))

    def test_ready_since_is_when_the_last_charge_came_back(self):
        from checks.source_state import ready_since
        self.assertEqual(ready_since([], 100, 60, 1), (True, None))
        self.assertEqual(ready_since([10], 100, 60, 1), (True, 70))
        self.assertEqual(ready_since([10], 50, 60, 1), (False, None))
        # Two charges: one spent at 10 leaves one, so it never ran out; both spent, the first back at 70.
        self.assertEqual(ready_since([10], 100, 60, 2), (True, None))
        self.assertEqual(ready_since([10, 20], 100, 60, 2), (True, 70))

    def test_short_cooldowns_keep_every_earlier_cast(self):
        # Fiery Brand with Down in Flames (2 charges, 48s): spent at 0 and 1s, back at 48s and spent at
        # 49s, back at 96s and spent at 97s; at 143s none is left (next back at 144s). A lookback of
        # cooldown x charges (from 47s) would drop the first two casts and call it ready.
        from checks.source_state import cooldown_window, ready_at
        from defensive_catalog import CATALOG
        entry = CATALOG[204021]
        talents = {e: 1 for e in entry["talent_entries"]} | {112876: 1}
        casts = [{"abilityGameID": 204021, "timestamp": t} for t in (0, 1_000, 49_000, 97_000)]
        times, cd, charges = cooldown_window(entry, 204021, casts, talents, "Vengeance", 20_000, 143_000)
        self.assertEqual((times, cd, charges), ([0, 1_000, 49_000, 97_000], 48_000, 2))
        self.assertFalse(ready_at(times, 143_000, cd, charges))

    def test_health_mismatch_uses_the_killing_event(self):
        s = {"hpBeforePct": 40, "maxHp": 1000, "overkill": 55}
        entry = {"overkill": 55, "events": [{"type": "damage", "amount": 300, "overkill": 0}, {"type": "damage", "amount": 405, "overkill": 55}]}
        self.assertIsNone(health_mismatch(s, entry))
        self.assertIsNotNone(health_mismatch(dict(s, overkill=56), entry))
        self.assertIsNotNone(health_mismatch(dict(s, hpBeforePct=43), entry))

    def test_overkill_is_the_killing_hits_not_the_entrys_sum(self):
        # Live 2026-10-08 (Weavi, Brewmaster, Undermine): two Stagger ticks overkilled for 662478 and
        # 299233 without killing him; WCL's entry sums them with the killing hit's 2653261 (3614972).
        # The site's "Died by" is the killing hit's overkill, which is what WCL's killing event says.
        s = {"hpBeforePct": 0, "maxHp": 21247860, "overkill": 2653261}
        entry = {"overkill": 3614972, "events": [
            {"type": "damage", "amount": 1, "overkill": 2653261, "timestamp": 1358033},
            {"type": "damage", "amount": 521767, "timestamp": 1357943}]}
        self.assertIsNone(health_mismatch(s, entry))
        self.assertEqual(health_mismatch(dict(s, overkill=3614972), entry), "overkill site 3614972 vs wcl 2653261")

    def test_health_above_max_hp_is_a_mismatch(self):
        # Live 2026-10-08 (Strikepal, Nerub-ar pull 16): the killing hit took 10531185 and WCL's max HP on
        # it was 10061382, 11198315 on every hit before; the site showed 105% health before the blow.
        s = {"hpBeforePct": 105, "maxHp": 10061382, "overkill": 4552041}
        entry = {"overkill": 4552041, "events": [{"type": "damage", "amount": 10531185, "overkill": 4552041}]}
        self.assertEqual(health_mismatch(s, entry), "health before 105% of max HP 10061382 (above 100%)")
        self.assertIsNone(health_mismatch(dict(s, hpBeforePct=100), dict(entry, events=[
            {"type": "damage", "amount": 10061382, "overkill": 4552041}])))

    def test_killing_event_is_the_newest_overkill_hit(self):
        s = {"hpBeforePct": 40, "maxHp": 1000, "overkill": 55}
        entry = {"overkill": 55, "events": [{"type": "damage", "amount": 400, "overkill": 55, "timestamp": 900},
                                            {"type": "damage", "amount": 700, "overkill": 10, "timestamp": 800}]}
        self.assertIsNone(health_mismatch(s, entry))

    def test_second_death_of_a_rezzed_player_matches_its_own_entry(self):
        entries = [{"id": 7, "timestamp": 1000, "overkill": 1, "events": []}, {"id": 7, "timestamp": 9000, "overkill": 2, "events": []}]
        self.assertEqual(entry_for(entries, 7, 9010)["overkill"], 2)
        self.assertIsNone(entry_for(entries, 8, 9010))

    def _run(self):
        run = mock.Mock()
        start = 100_000
        run.fight.return_value = {"start_time": start, "end_time": start + 60_000}
        run.result = {"pullParticipation": {"Oak": ["R_1"], "Elm": ["S_4"]}}
        run.actor_id.return_value = 7
        cat = mock.Mock()
        cat.name_to_id = {"Barkskin": 1, "Ironbark": 2, "Renewal": 3, "Healthstone": 4}
        cat.all = {1: {"name": "Barkskin", "kind": "personal", "cooldown_ms": 60_000, "charges": 1},
                   2: {"name": "Ironbark", "kind": "external", "cooldown_ms": 90_000, "charges": 1},
                   3: {"name": "Renewal", "kind": "personal", "cooldown_ms": 90_000, "charges": 1},
                   4: {"name": "Healthstone", "kind": "healthstone", "cooldown_ms": 60_000, "charges": 1}}
        run.cat = cat
        run.combatants.return_value = [{"sourceID": 7, "fight": 1, "specID": 104, "talentTree": [{"id": 111, "rank": 1}]}]
        # Barkskin pressed 20s before death (on cooldown); Renewal never pressed (ready).
        run.casts.return_value = [{"type": "cast", "abilityGameID": 1, "timestamp": start + 30_000}]
        run.buffs.return_value = [{"name": "Ironbark", "bands": [{"startTime": start + 45_000, "endTime": start + 57_000}]}]
        ev = {"reportId": "R", "fightId": 1, "timestamp": 50_000, "originalCharacter": "Oak", "spec": "Guardian",
              "defensives": {"active": [{"name": "Ironbark", "kind": "external"}],
                             "available": [{"name": "Renewal"}, {"name": "Healthstone"}],
                             "cooldown": [{"name": "Barkskin", "readyIn": 40, "usedAgo": 20}],
                             "survival": {"hpBeforePct": 40, "maxHp": 1000, "overkill": 55, "deathType": "damage"}}}
        run.counted_deaths.return_value = [ev]
        run.meta_for.return_value = {"abilities": {207771: "Fiery Brand"}}
        run.hits_before.return_value = []
        run.deaths_table.return_value = [{"id": 7, "timestamp": start + 50_000, "overkill": 55,
                                          "events": [{"type": "damage", "amount": 405, "overkill": 55, "timestamp": start + 50_000}]}]
        return run, ev

    def test_check_pass(self):
        run, _ = self._run()
        self.assertEqual(source_state.check(run).status, "pass")
        # The whole report's kept pulls, from 3 minutes before the first: what the site reads.
        run.casts.assert_called_with("R", 7, 0, 160_000)

    def test_check_mismatches(self):
        run, ev = self._run()
        d = ev["defensives"]
        d["available"], d["cooldown"] = [{"name": "Barkskin"}], [{"name": "Renewal", "readyIn": 1, "usedAgo": 1}]
        d["active"] = [{"name": "Barkskin", "kind": "personal"}]
        d["survival"] = dict(d["survival"], hpBeforePct=50, overkill=60)
        o = source_state.check(run)
        self.assertEqual(o.status, "fail")
        self.assertIn("Oak pull 1 Barkskin: site ready, wcl casts say on cooldown", o.items)
        self.assertIn("Oak pull 1 Renewal: site on cooldown, wcl casts say ready", o.items)
        self.assertIn("Oak pull 1: active Barkskin has no aura band at death", o.items)
        self.assertIn("Oak pull 1: health before 500 vs wcl 405 (max 1000)", o.items)
        self.assertIn("Oak pull 1: overkill site 60 vs wcl 55", o.items)

    def test_check_table_capped_and_skip(self):
        run, _ = self._run()
        run.deaths_table.side_effect = TableCapped("R", 1)
        o = source_state.check(run)
        self.assertEqual((o.status, o.items), ("fail", ["pull 1: 200+ deaths, table capped"]))
        run.counted_deaths.return_value = []
        self.assertEqual(source_state.check(run).status, "skip")

    def test_cooldown_reduction_and_encounter_reset(self):
        run, ev = self._run()
        start = 100_000
        # Barkskin pressed twice 5s apart, well under its 60s cooldown: the player's real cooldown is 5s
        # (reduction the catalog can't see), so 35s after the last press it is ready. Renewal has a
        # 3-minute cooldown and was pressed before the pull: the encounter reset makes it ready.
        run.cat.all[3]["cooldown_ms"] = 180_000
        run.casts.return_value = [{"type": "cast", "abilityGameID": 1, "timestamp": start + 10_000},
                                  {"type": "cast", "abilityGameID": 1, "timestamp": start + 15_000},
                                  {"type": "cast", "abilityGameID": 3, "timestamp": start - 5_000}]
        ev["defensives"]["available"] = [{"name": "Renewal"}, {"name": "Barkskin"}]
        ev["defensives"]["cooldown"] = []
        self.assertEqual(source_state.check(run).status, "pass")

    def test_enemy_debuff_defensive_read_from_the_killing_hit(self):
        # Live 2026-10-07 (Soulcleavi, Manaforge pull 35): Fiery Brand is a debuff on the boss, never a
        # band on the player; WCL's killing hit lists it (207771) when it was up.
        run, ev = self._run()
        start = 100_000
        ev["defensives"]["active"] = [{"name": "Fiery Brand", "kind": "personal"}]
        kb = {"type": "damage", "timestamp": start + 50_000, "overkill": 55, "buffs": "207771.1022."}
        run.hits_before.return_value = [dict(kb, overkill=0, timestamp=start + 40_000, buffs=""), kb]
        self.assertEqual(source_state.check(run).status, "pass")
        run.hits_before.assert_called_with("R", 1, 7, start + 50_000)
        run.hits_before.return_value = [dict(kb, buffs="1022.")]
        self.assertEqual(source_state.check(run).items, ["Oak pull 1: active Fiery Brand has no aura band at death"])

    def test_report_with_no_kept_pull_listed_uses_the_deaths_own_pull(self):
        run, _ = self._run()
        run.result = {"pullParticipation": {"Elm": ["S_4"]}}
        self.assertEqual(source_state.check(run).status, "pass")
        run.casts.assert_called_with("R", 7, 0, 160_000)

    def test_cooldown_reduction_seen_anywhere_in_the_report(self):
        # Live 2026-10-07 (Decoil, Dancing Rune Weapon): the only short gap between presses was in
        # another pull, after this death. The site reads the whole report's casts, so does the check.
        run, ev = self._run()
        start = 100_000
        presses = [{"type": "cast", "abilityGameID": 1, "timestamp": start + 30_000},
                   {"type": "cast", "abilityGameID": 1, "timestamp": start + 300_000},
                   {"type": "cast", "abilityGameID": 1, "timestamp": start + 315_000}]
        run.fight.side_effect = lambda rid, fid: {"start_time": start + (fid - 1) * 280_000,
                                                  "end_time": start + (fid - 1) * 280_000 + 60_000}
        run.result = {"pullParticipation": {"Oak": ["R_1", "R_2"]}}
        run.casts.side_effect = lambda rid, pid, s, e: [c for c in presses if s <= c["timestamp"] <= e]
        ev["defensives"]["available"] = [{"name": "Renewal"}, {"name": "Barkskin"}]
        ev["defensives"]["cooldown"] = []
        self.assertEqual(source_state.check(run).status, "pass")


class FinalRegistryTests(unittest.TestCase):
    def test_final_order(self):
        self.assertEqual([c[0] for c in CHECKS], ["deaths", "selection", "participation", "state", "durations",
                                                  "mitigation", "slots", "counting", "labels", "verdicts", "defensives"])


class FindLogsTests(unittest.TestCase):
    def test_good_log_needs_wipes_and_a_finished_report(self):
        light = {"report_start": 0, "fights": [{"id": i, "start_time": i * 10, "end_time": i * 10 + 5, "boss": 3129,
                                                "difficulty": 5, "kill": i == 3} for i in range(4)]}
        cand = {"code": "X", "guild": ("G", "S", "US")}
        with mock.patch("checks.find_logs.get_report_fights", return_value=light):
            self.assertEqual(good_log("t", "manaforge", cand, now_ms=10**12), "X:manaforge:G/S/US")
            self.assertIsNone(good_log("t", "manaforge", cand, now_ms=1000))
            light["fights"][0]["kill"] = light["fights"][1]["kill"] = True
            self.assertIsNone(good_log("t", "manaforge", cand, now_ms=10**12))


if __name__ == "__main__":
    unittest.main()
