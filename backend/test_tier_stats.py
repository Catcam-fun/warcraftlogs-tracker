import unittest
from unittest import mock

import tier_stats


def kill(boss, t, code, deaths=1):
    return {"boss": boss, "t": t, "code": code, "fight": 1, "report_start": 0,
            "start": 1000, "end": 9000, "deaths": deaths}


class BuildOutputTests(unittest.TestCase):
    def test_each_boss_keeps_an_unbroken_run_from_its_first_kill(self):
        kills = {"12.1": [kill(10, 3, "c"), kill(10, 1, "a"), kill(10, 2, "b"), kill(10, 4, "d"),
                          kill(20, 5, "e")]}
        mage = {"specs": ["Mage-Frost"], "deaths": [[1, 99, "Mage-Frost"]]}
        records = {("a", 1): mage, ("b", 1): {"specs": [], "deaths": []},   # b: unreadable log
                   ("d", 1): mage, ("e", 1): mage}                          # c: not read yet
        out = tier_stats.build_output("raid", [(10, "Ten"), (20, "Twenty")], kills, records,
                                      {99: ["Smash", "icon", "Smashes."]})
        bosses = out["patches"][0]["bosses"]
        self.assertEqual(len(bosses["10"]), 1)      # a; b skipped; stops at c, so d isn't counted
        self.assertEqual(len(bosses["20"]), 1)
        self.assertEqual(bosses["10"][0], [[0], [1, 0, 0]])
        self.assertEqual(out["specs"], ["Mage-Frost"])
        self.assertEqual(out["abilities"], [[99, "Smash", "icon", "Smashes."]])


class ReadKillTests(unittest.TestCase):
    def test_slots_skip_wipes_and_use_each_players_spec(self):
        details = {"data": {"playerDetails": {
            "tanks": [{"id": 1, "type": "Warrior", "specs": [{"spec": "Protection"}]}],
            "dps": [{"id": i, "type": "Mage", "specs": [{"spec": "Frost"}]} for i in range(2, 12)],
        }}}
        # One early death, then 9 within 8 seconds (a wipe: none of them count).
        deaths = [{"type": "death", "fight": 1, "targetID": 2, "timestamp": 2000, "killingAbilityGameID": 7}]
        deaths += [{"type": "death", "fight": 1, "targetID": i, "timestamp": 20000 + i, "killingAbilityGameID": 8}
                   for i in range(3, 12)]
        response = {"reportData": {"report": {"playerDetails": details,
                                              "deaths": {"data": deaths, "nextPageTimestamp": None}}}}
        with mock.patch.object(tier_stats, "graphql_query", return_value=response):
            rec = tier_stats.read_kill("token", kill(10, 1, "a", deaths=10))
        self.assertEqual(rec["deaths"], [[1, 7, "Mage-Frost"]])
        self.assertEqual(rec["specs"], ["Mage-Frost"] * 10 + ["Warrior-Protection"])

    def test_a_kill_nobody_died_in_skips_the_deaths_query(self):
        details = {"data": {"playerDetails": {"healers": [{"id": 1, "type": "Priest", "specs": [{"spec": "Holy"}]}]}}}
        with mock.patch.object(tier_stats, "graphql_query",
                               return_value={"reportData": {"report": {"playerDetails": details}}}) as q:
            rec = tier_stats.read_kill("token", kill(10, 1, "a", deaths=0))
        self.assertNotIn("Deaths", q.call_args[0][1])
        self.assertEqual(rec, {"specs": ["Priest-Holy"], "deaths": []})


if __name__ == "__main__":
    unittest.main()
