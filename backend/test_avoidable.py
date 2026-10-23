"""Avoidable deaths (rule B′, owner 2026-10-23): with the avoidable hits since they were last at 85%+ health
removed, would they have lived?"""
import unittest
from unittest import mock

import testenv  # noqa: F401  (before any backend import)
import avoidable
import defensives

MAX = 1_000_000
WAVE, RAID, BURN, TANK_SOAK = 900, 800, 950, 960
RULES = {WAVE: {"rule": "always"}, BURN: {"rule": "always", "source": WAVE}, TANK_SOAK: {"rule": "non_tank"}}
NAMES = {WAVE: "Caustic Waves", RAID: "Rage of the Sleeper", BURN: "Venom Burn", TANK_SOAK: "Crushing Slam"}


def hit(ts, amount, hp_after, ability=RAID, overkill=0, absorbed=0):
    return {"timestamp": ts, "type": "damage", "targetID": 1, "abilityGameID": ability, "amount": amount,
            "absorbed": absorbed, "overkill": overkill, "hitPoints": hp_after, "maxHitPoints": MAX,
            "resourceActor": 2}


class AvoidableDeathTests(unittest.TestCase):
    def setUp(self):
        p = mock.patch.object(avoidable, "rule_for", lambda a: RULES.get(a))
        p.start()
        self.addCleanup(p.stop)

    def judge(self, hits, spec="Fire"):
        r = defensives.assess_survival(hits, hits[-1]["timestamp"], [], [], NAMES, {}, spec=spec)
        return r["avoidable"]

    def test_wave_then_unavoidable_kill(self):
        a = self.judge([hit(95_000, 400_000, 600_000, WAVE), hit(100_000, 600_000, 0, overkill=200_000)])
        self.assertIs(a["verdict"], True)
        self.assertEqual(a["hits"], [{"name": "Caustic Waves", "id": WAVE, "times": 1, "pctOfMax": 40}])

    def test_dies_to_wave_at_five_percent(self):
        a = self.judge([hit(90_000, 500_000, 500_000), hit(95_000, 450_000, 50_000),
                        hit(100_000, 50_000, 0, WAVE, overkill=100_000)])
        self.assertIs(a["verdict"], True)

    def test_small_tick_then_huge_unavoidable(self):
        # Still at 97% after the tick: the stretch starts after it, so it isn't even listed.
        a = self.judge([hit(98_000, 30_000, 970_000, WAVE), hit(100_000, 970_000, 0, overkill=500_000)])
        self.assertEqual((a["verdict"], a["hits"]), (False, []))

    def test_hits_listed_when_not_deciding(self):
        # From 80% (already in the stretch): a 3% tick, then a big unavoidable hit. Listed, not deciding.
        a = self.judge([hit(97_000, 200_000, 800_000), hit(98_000, 30_000, 770_000, WAVE),
                        hit(100_000, 770_000, 0, overkill=500_000)])
        self.assertIs(a["verdict"], False)
        self.assertEqual(a["hits"], [{"name": "Caustic Waves", "id": WAVE, "times": 1, "pctOfMax": 3}])

    def test_avoidable_then_healed_to_ninety(self):
        # Hit to 50%, a DoT tick, healed back to 90% (the next hit lands on 90%): that is before the stretch.
        a = self.judge([hit(90_000, 500_000, 500_000, WAVE), hit(91_000, 50_000, 450_000, BURN),
                        hit(97_000, 100_000, 800_000), hit(100_000, 800_000, 0, overkill=50_000)])
        self.assertIs(a["verdict"], False)
        self.assertEqual(a["hits"], [])

    def test_dot_ticks_count_without_their_source_hit(self):
        a = self.judge([hit(95_000, 300_000, 700_000, BURN), hit(96_000, 300_000, 400_000, BURN),
                        hit(100_000, 400_000, 0, overkill=100_000)])
        self.assertIs(a["verdict"], True)
        self.assertEqual(a["hits"], [{"name": "Venom Burn", "id": BURN, "times": 2, "pctOfMax": 60}])

    def test_stretch_before_window_is_window_limited(self):
        a = self.judge([hit(86_000, 100_000, 300_000), hit(100_000, 300_000, 0, overkill=10_000)])
        self.assertTrue(a["windowLimited"])
        self.assertIs(a["verdict"], False)

    def test_no_avoidable_hits(self):
        a = self.judge([hit(99_000, 500_000, 500_000), hit(100_000, 500_000, 0, overkill=10_000)])
        self.assertEqual((a["verdict"], a["hits"], a["windowLimited"]), (False, [], False))

    def test_avoidable_killing_blow(self):
        a = self.judge([hit(99_000, 500_000, 500_000), hit(100_000, 500_000, 0, WAVE, overkill=300_000)])
        self.assertIs(a["verdict"], True)

    def test_instakill_by_avoidable_ability(self):
        r = defensives.assess_survival([{"timestamp": 100_000, "type": "instakill", "targetID": 1,
                                         "abilityGameID": WAVE}], 100_000, [], [], NAMES, {}, spec="Fire")
        self.assertEqual(r["deathType"], "instakill")
        self.assertIs(r["avoidable"]["verdict"], True)
        r = defensives.assess_survival([{"timestamp": 100_000, "type": "instakill", "targetID": 1,
                                         "abilityGameID": RAID}], 100_000, [], [], NAMES, {}, spec="Fire")
        self.assertIs(r["avoidable"]["verdict"], False)

    def test_absorbed_part_not_credited(self):
        # The wave took 50k of health; a shield took 400k of it. Removing it gives back 50k, not 450k.
        a = self.judge([hit(99_000, 100_000, 900_000), hit(99_500, 50_000, 850_000, WAVE, absorbed=400_000),
                        hit(100_000, 850_000, 0, overkill=200_000)])
        self.assertIs(a["verdict"], False)

    def test_unknown_spec_non_tank(self):
        hits = [hit(95_000, 400_000, 600_000, TANK_SOAK), hit(100_000, 600_000, 0, overkill=200_000)]
        a = self.judge(hits, spec=None)
        self.assertIsNone(a["verdict"])          # removing it would flip the verdict: can't tell
        self.assertEqual(a["hits"], [{"name": "Crushing Slam", "id": TANK_SOAK, "times": 1, "pctOfMax": 40,
                                      "unsure": True}])
        self.assertIs(self.judge(hits, spec="Protection")["verdict"], False)
        self.assertIs(self.judge(hits, spec="Fire")["verdict"], True)


if __name__ == "__main__":
    unittest.main()
