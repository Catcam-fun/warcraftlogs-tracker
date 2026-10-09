"""Catalog entries checked against the game data, patch by patch (scripts/build_defensive_catalog.py)."""
import unittest

import defensives
from test_defensives import MAX, SCHOOLS, hit


def entry(patch, name):
    return next(d for d in defensives._CATALOGS[patch].all.values() if d["name"] == name)


def dr(comps):
    return [round(c["dr"], 4) for c in comps if "dr" in c]


class ImprovedPrismaticBarrierTests(unittest.TestCase):
    """Improved Prismatic Barrier (321745): an Arcane spec passive (SpecializationSpells, spec 62) AND
    talent entry 80301 in 11.0.2-11.2.7, so every Arcane Mage has it there; a talent only from 12.0.0
    (80301 / 134194). +10% magic reduction (12.1.0: +5%)."""

    def test_every_arcane_mage_has_it_in_the_war_within(self):
        pb = entry("11.1.7", "Prismatic Barrier")
        self.assertEqual(dr(defensives._resolve(pb, {}, {}, "Arcane")[0]), [0.25])
        self.assertEqual(dr(defensives._resolve(pb, {80301: 1}, {}, "Arcane")[0]), [0.25])   # once, not twice

    def test_a_talent_in_midnight(self):
        pb = entry("12.0.0", "Prismatic Barrier")
        self.assertEqual(dr(defensives._resolve(pb, {}, {}, "Arcane")[0]), [0.15])
        self.assertEqual(dr(defensives._resolve(pb, {134194: 1}, {}, "Arcane")[0]), [0.25])
        pb = entry("12.1.0", "Prismatic Barrier")
        self.assertEqual(dr(defensives._resolve(pb, {134194: 1}, {}, "Arcane")[0]), [0.2])

    def test_a_modifier_for_a_spec_or_a_talent(self):
        mod = {"talent": "x", "entries": [5], "specs": ["Arcane"], "add": 0.1}
        self.assertEqual(defensives._mod_rank(mod, {}, "Arcane"), 1)
        self.assertEqual(defensives._mod_rank(mod, {5: 1}, "Fire"), 1)
        self.assertEqual(defensives._mod_rank(mod, {}, "Fire"), 0)
        self.assertEqual(defensives._mod_rank(mod, {5: 1}, "Arcane"), 1)


if __name__ == "__main__":
    unittest.main()
