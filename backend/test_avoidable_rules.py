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


class AuraAndTickRulesTests(unittest.TestCase):
    """bystander: avoidable unless they had the target's debuff when hit; while_debuffed: avoidable only if
    they had it (soak once); ticks_only / impact_only: by WCL's tick mark."""
    ENTRIES = {10: {"rule": "bystander", "auras": [100]}, 11: {"rule": "while_debuffed", "auras": [200]},
               12: {"rule": "ticks_only"}, 13: {"rule": "impact_only"}}

    def setUp(self):
        for name, value in (("AVOIDABLE", self.ENTRIES), ("OVERRIDES", {}), ("RAID_WIDE", {})):
            p = mock.patch.object(avoidable, name, value)
            p.start()
            self.addCleanup(p.stop)

    def test_bystander(self):
        had = lambda auras, t: 100 in auras and t > 5_000      # marked from 5 s on
        self.assertIs(avoidable.judge_hit({"abilityGameID": 10, "timestamp": 6_000}, "Fire", had), False)
        self.assertIs(avoidable.judge_hit({"abilityGameID": 10, "timestamp": 4_000}, "Fire", had), True)
        self.assertIsNone(avoidable.judge_hit({"abilityGameID": 10, "timestamp": 4_000}, "Fire", None))

    def test_while_debuffed(self):
        had = lambda auras, t: 200 in auras
        self.assertIs(avoidable.judge_hit({"abilityGameID": 11, "timestamp": 1}, "Fire", had), True)
        self.assertIs(avoidable.judge_hit({"abilityGameID": 11, "timestamp": 1}, "Fire", lambda a, t: False), False)

    def test_ticks_and_impact(self):
        self.assertIs(avoidable.judge_hit({"abilityGameID": 12, "tick": True}, "Fire"), True)
        self.assertIs(avoidable.judge_hit({"abilityGameID": 12}, "Fire"), False)
        self.assertIs(avoidable.judge_hit({"abilityGameID": 13}, "Fire"), True)
        self.assertIs(avoidable.judge_hit({"abilityGameID": 13, "tick": True}, "Fire"), False)

    def test_aura_ids_lists_every_debuff_a_rule_needs(self):
        self.assertEqual(avoidable.aura_ids(), [100, 200])

    def test_had_aura_from_events(self):
        events = [{"type": "applydebuff", "abilityGameID": 100, "timestamp": 1_000},
                  {"type": "removedebuff", "abilityGameID": 100, "timestamp": 3_000},
                  {"type": "removedebuff", "abilityGameID": 200, "timestamp": 9_000}]   # applied before the window
        had = avoidable.had_aura_from(events)
        self.assertTrue(had([100], 2_000))
        self.assertFalse(had([100], 3_500))
        self.assertFalse(had([100], 1_000))       # the hit that applies it: not "before"
        self.assertTrue(had([200], 5_000))        # removed later, never applied in the window: was on
        self.assertFalse(had([300], 5_000))
