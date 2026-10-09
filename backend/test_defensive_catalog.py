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


class MerelyASetbackTests(unittest.TestCase):
    """Merely a Setback (449330, entry 117252; The War Within): "Your Prismatic Barrier / Blazing Barrier
    now grants 5% avoidance while active" (449330 effect 0; 449336 is the avoidance rating, aura 189,
    filled by a script). Avoidance cuts area damage. Midnight rewrote it (449336 has no aura 189): no
    avoidance there."""

    def comps(self, patch, name, talents):
        return defensives._resolve(entry(patch, name), talents, {}, "Arcane" if name[0] == "P" else "Fire")[0]

    def test_five_percent_against_area_damage_with_the_talent(self):
        for name in ("Prismatic Barrier", "Blazing Barrier"):
            comps = self.comps("11.1.7", name, {117252: 1})
            self.assertIn({"dr": 0.05, "school": "aoe"}, [{k: c[k] for k in ("dr", "school")} for c in comps
                                                          if "dr" in c], name)
            self.assertNotIn(0.05, dr(self.comps("11.1.7", name, {})), name)

    def test_with_the_barrier_on_an_area_hit(self):
        comps = self.comps("11.1.7", "Prismatic Barrier", {117252: 1})
        reductions = [c for c in comps if "dr" in c]
        aoe_magic = hit(1, 100, 0, aoe=True)                 # frost, area: 25% and 5%
        self.assertAlmostEqual(defensives._keep(reductions, aoe_magic, MAX, 0, SCHOOLS), 0.75 * 0.95)
        self.assertAlmostEqual(defensives._keep(reductions, hit(1, 100, 0), MAX, 0, SCHOOLS), 0.75)
        self.assertAlmostEqual(defensives._keep(reductions, hit(1, 100, 0, ability=600, aoe=True), MAX, 0, SCHOOLS),
                               0.95)                         # physical area hit: avoidance only

    def test_not_in_midnight(self):
        for patch in ("12.0.0", "12.1.0"):
            self.assertNotIn(0.05, dr(self.comps(patch, "Prismatic Barrier", {117252: 1})), patch)


if __name__ == "__main__":
    unittest.main()
