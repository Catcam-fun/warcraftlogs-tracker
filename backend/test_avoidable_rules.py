import unittest
from unittest import mock

import avoidable

GENERATED = {
    1: {"rule": "always", "name": "Toxic Pool", "boss": "Boss"},
    2: {"rule": "never", "name": "Group Soak", "boss": "Boss"},
    3: {"rule": "non_tank", "name": "Tank Soak", "boss": "Boss"},
    4: {"rule": "always", "name": "Misread Pool", "boss": "Boss"},
    6: {"rule": "always", "name": "Raid Pulse", "boss": "Boss"},
}
OVERRIDES = {4: {"rule": "never", "name": "Misread Pool", "boss": "Boss"}}


def hit(ability):
    return {"abilityGameID": ability, "type": "damage"}


class RulesTests(unittest.TestCase):
    def setUp(self):
        for name, value in (("AVOIDABLE", GENERATED), ("OVERRIDES", OVERRIDES), ("RAID_WIDE", {5: 1.0, 6: 1.0})):
            p = mock.patch.object(avoidable, name, value)
            p.start()
            self.addCleanup(p.stop)

    def test_always_and_never(self):
        self.assertIs(avoidable.judge_hit(hit(1), "Fire"), True)
        self.assertIs(avoidable.judge_hit(hit(2), "Fire"), False)

    def test_override_beats_generated(self):
        self.assertEqual(avoidable.rule_for(4)["rule"], "never")
        self.assertIs(avoidable.judge_hit(hit(4), "Fire"), False)

    def test_raid_wide_never_avoidable(self):
        # Raid-wide damage is never avoidable, even if a list says otherwise.
        self.assertEqual(avoidable.rule_for(5), {"rule": "never"})
        self.assertIs(avoidable.judge_hit(hit(6), "Fire"), False)

    def test_non_tank(self):
        self.assertIs(avoidable.judge_hit(hit(3), "Protection"), False)
        self.assertIs(avoidable.judge_hit(hit(3), "Brewmaster"), False)
        self.assertIs(avoidable.judge_hit(hit(3), "Fire"), True)
        self.assertIsNone(avoidable.judge_hit(hit(3), None))

    def test_unlisted_ability_is_not_avoidable(self):
        self.assertIsNone(avoidable.rule_for(99))
        self.assertIs(avoidable.judge_hit(hit(99), "Fire"), False)


if __name__ == "__main__":
    unittest.main()
