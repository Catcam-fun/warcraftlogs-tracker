import unittest
from unittest import mock

import analysis


class DeathsQueryScopeTests(unittest.TestCase):
    """The Deaths query reads only the kept pulls (fightIDs), with an endTime, on every page."""

    FIGHTS = [{"id": 7, "start_time": 1_000, "end_time": 5_000}, {"id": 3, "start_time": 9_000, "end_time": 12_000}]

    def _run(self, cheat):
        calls = []

        def fake(token, query, variables=None, **_):
            calls.append((query, variables))
            page = {"data": [{"type": "death", "timestamp": 2_000, "fight": 7, "targetID": 1}],
                    "nextPageTimestamp": 4_000 if len(calls) == 1 else None}
            return {"reportData": {"report": {"deaths": page, "debuffs": {"data": []}, "saveHeals": {"data": []},
                                              "events": {"data": [], "nextPageTimestamp": None}}}}
        with mock.patch.object(analysis, "graphql_query", side_effect=fake):
            analysis.get_report_deaths_bulk("t", "R", self.FIGHTS, [{"id": 1, "name": "Bob"}], {}, cheat)
        return calls

    def test_every_alias_and_page_is_scoped_to_the_pulls(self):
        for cheat in (False, True):
            with self.subTest(cheat=cheat):
                calls = self._run(cheat)
                first, more = calls[0], calls[1:]
                self.assertEqual(first[1]["fightIDs"], [3, 7])
                self.assertEqual(first[1]["endTime"], 12_000)
                aliases = 3 if cheat else 1
                self.assertEqual(first[0].count("fightIDs: $fightIDs"), aliases)
                # The second page of Deaths keeps the same scope.
                self.assertTrue(more)
                self.assertEqual(more[0][1]["fightIDs"], [3, 7])
                self.assertIn("fightIDs: $fightIDs", more[0][0])


if __name__ == "__main__":
    unittest.main()
