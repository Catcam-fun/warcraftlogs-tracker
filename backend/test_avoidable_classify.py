import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "scripts"))
import avoidable_classify as ac  # noqa: E402

# Real wago.tools rows (SpellEffect, DifficultyID 0; SpellRadius), read 2026-10-23.
RADIUS = {"8": 5.0, "22": 200.0, "88": 300.0, "118": 100.0}


def fx(effect, aura, t0, t1, r0="0", r1="0", trig="0", index="0"):
    return {"Effect": effect, "EffectAura": aura, "EffectIndex": index, "ImplicitTarget_0": t0,
            "ImplicitTarget_1": t1, "EffectRadiusIndex_0": r0, "EffectRadiusIndex_1": r1, "EffectTriggerSpell": trig}


EFFECTS = {
    # Coalesced Venom: damage to everyone within 200 yd of a point (raid-wide in logs).
    1282408: [fx("2", "0", "87", "16", r1="22")],
    # Necrotic Vapors: within 300 yd of the caster (raid-wide in logs).
    1286835: [fx("2", "0", "18", "16", r1="88")],
    # Fester Burst: damage and a DoT within 100 yd of the caster.
    1310763: [fx("2", "0", "18", "16", r1="118"), fx("6", "3", "18", "16", r1="118", index="1")],
    # Volatile Venom: within 5 yd of a point ("players nearby").
    1282288: [fx("2", "0", "87", "16", r1="8")],
    # Caustic Waves: "waves of venom ... to players in their path", cast by the server on whoever they touch.
    1292403: [fx("2", "0", "25", "0"), fx("6", "3", "25", "0", index="1")],
    # Plague Wave: "waves ... erupt from the target", single-target in the data though it is a wave.
    1295798: [fx("2", "0", "6", "0")],
    # Pulsing Tides: an aura that triggers 1271380, damage within 300 yd.
    1258894: [fx("6", "23", "1", "0", trig="1271380")],
    1271380: [fx("2", "0", "22", "15", r1="88")],
}


class ClassifyTests(unittest.TestCase):
    def test_whole_room_radius_is_unavoidable(self):
        for sid in (1282408, 1286835, 1310763):
            kind, reason = ac.classify(sid, EFFECTS[sid], RADIUS)
            self.assertEqual(kind, "unavoidable", sid)
            self.assertIn("whole room", reason)

    def test_small_area_is_unsure(self):
        kind, reason = ac.classify(1282288, EFFECTS[1282288], RADIUS)
        self.assertEqual(kind, "unsure")
        self.assertIn("5 yd", reason)

    def test_server_cast_spells_are_unsure(self):
        # The client data can't tell a wave from a chosen player: never auto-decided.
        for sid in (1292403, 1295798):
            self.assertEqual(ac.classify(sid, EFFECTS[sid], RADIUS)[0], "unsure", sid)

    def test_no_damage_effect_is_unsure(self):
        kind, reason = ac.classify(1, [fx("6", "4", "1", "0")], RADIUS)
        self.assertEqual(kind, "unsure")
        self.assertIn("no damage", reason)

    def test_dot_link_direct(self):
        self.assertEqual(ac.dot_links(EFFECTS, 1292403), {1292403})
        self.assertEqual(ac.dot_links(EFFECTS, 1282288), set())

    def test_dot_link_through_trigger(self):
        effects = {1: [fx("6", "23", "1", "0", trig="2")], 2: [fx("6", "3", "25", "0")]}
        self.assertEqual(ac.dot_links(effects, 1), {2})


if __name__ == "__main__":
    unittest.main()
