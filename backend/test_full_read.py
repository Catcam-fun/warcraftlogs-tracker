import unittest
from unittest import mock

import testenv  # noqa: F401  (before any backend import)
import warcraftlogs


class FullReadTests(unittest.TestCase):
    def test_full_read_skips_player_details(self):
        # playerDetails made the full read cost 3 points instead of 2 (4 of 4 reports, 2026-11-20). The spec
        # shown comes from each pull's talent record and the class from the report's player list instead.
        reply = {"reportData": {"report": {
            "startTime": 5, "fights": [],
            "masterData": {"actors": [{"id": 10, "gameID": 1, "name": "Bob", "server": "S", "type": "Player",
                                       "subType": "Mage"}], "abilities": []}}}}
        with mock.patch.object(warcraftlogs, "graphql_query", return_value=reply) as q:
            meta = warcraftlogs.get_fights("t", "R1")
        self.assertNotIn("playerDetails", q.call_args.args[1])
        self.assertNotIn("player_details", meta)
        self.assertEqual(meta["friendlies"][0]["type"], "Mage")


if __name__ == "__main__":
    unittest.main()
