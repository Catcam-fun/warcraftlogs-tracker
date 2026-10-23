import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "scripts"))
import build_avoidable as ba  # noqa: E402


def ability(name, kind="unsure", reason="cast on a unit by the server (target type 25)", share=0.1, desc="text"):
    return {"name": name, "boss": "Boss", "kind": kind, "reason": reason, "median_share": share, "desc": desc}


class MergeTests(unittest.TestCase):
    def test_whole_room_listed_never(self):
        entries, review = ba.merge({1: ability("Blast", "unavoidable", "whole room (300 yd)")}, {}, {}, set())
        self.assertEqual(entries[1]["rule"], "never")
        self.assertEqual(review, [])

    def test_unsure_goes_to_review(self):
        entries, review = ba.merge({2: ability("Caustic Waves", desc="players in their path")}, {}, {}, set())
        self.assertNotIn(2, entries)
        self.assertEqual([(r["id"], r["name"], r["desc"], r["median_share"]) for r in review],
                         [(2, "Caustic Waves", "players in their path", 0.1)])

    def test_override_skips_review(self):
        overrides = {2: {"rule": "always", "name": "Caustic Waves", "boss": "Boss"}}
        entries, review = ba.merge({2: ability("Caustic Waves")}, overrides, {}, set())
        self.assertEqual(entries[2]["rule"], "always")
        self.assertEqual(review, [])

    def test_always_override_hitting_most_of_the_raid_is_flagged(self):
        overrides = {2: {"rule": "always", "name": "Pulse", "boss": "Boss"}}
        entries, review = ba.merge({2: ability("Pulse", share=0.8)}, overrides, {}, set())
        self.assertEqual(entries[2]["rule"], "always")
        self.assertEqual([r["id"] for r in review], [2])
        self.assertIn("most of the raid", review[0]["why"])

    def test_dot_inherits_source_rule(self):
        overrides = {3: {"rule": "non_tank", "name": "Tank Soak", "boss": "Boss"}}
        entries, review = ba.merge({3: ability("Tank Soak"), 30: ability("Soak Burn")}, overrides, {3: {30}}, set())
        self.assertEqual(entries[30], {"rule": "non_tank", "name": "Soak Burn", "boss": "Boss", "source": 3})
        self.assertEqual(review, [])

    def test_dot_with_two_sources_disagreeing_goes_to_review(self):
        overrides = {3: {"rule": "always", "name": "Pool", "boss": "Boss"},
                     4: {"rule": "never", "name": "Soak", "boss": "Boss"}}
        entries, review = ba.merge({3: ability("Pool"), 4: ability("Soak"), 30: ability("Burn")},
                                   overrides, {3: {30}, 4: {30}}, set())
        self.assertNotIn(30, entries)
        self.assertEqual([r["id"] for r in review], [30])
        self.assertIn("sources disagree", review[0]["why"])

    def test_raid_wide_excluded(self):
        entries, review = ba.merge({5: ability("Pulse", share=0.9)}, {}, {}, {5})
        self.assertNotIn(5, entries)
        self.assertEqual(review, [])


if __name__ == "__main__":
    unittest.main()
