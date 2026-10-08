import os
import unittest
from unittest import mock

from checks.registry import CHECKS, select
from checks.verdict import PASS, Verdict, exit_code, fail, format_lines, skip
from checks.__main__ import run_checks
from checks import rules_defensives, source_deaths
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


if __name__ == "__main__":
    unittest.main()
