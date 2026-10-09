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


SINCE_11_2 = ("11.2.0", "11.2.5", "11.2.7", "12.0.0", "12.0.1", "12.0.5", "12.0.7", "12.1.0")


class CelestialInfusionTests(unittest.TestCase):
    """Celestial Infusion (1241059): the Brewmaster choice node 101067 with Celestial Brew from 11.2.0 on
    (entries 124841 Celestial Brew / 133509 Celestial Infusion in 11.2.x, 136146 from 12.0.0; cast 30 times
    in the Manaforge log 2VtyDR4CF6PGLjbd, 11.2). Effect 0 an absorb sized by attack power,
    effect 1 "absorbing 30% of incoming damage, up to X": it takes 30% of what is left of each hit after
    Stagger and earlier shields (Weavi, Quel'Danas pull 104: 0.296-0.300 of each Stagger tick). 16 s.
    Charge category 2293, shared with Celestial Brew: Light Brewing x0.8 recharge, Endless Draught +1
    charge, and Black Ox Brew brings a charge back."""

    def test_in_every_midnight_patch(self):
        for patch in SINCE_11_2:
            ci = entry(patch, "Celestial Infusion")
            self.assertEqual((ci["class"], ci["specs"], ci["kind"], ci["aura_ms"]),
                             ("Monk", ["Brewmaster"], "personal", 16_000), patch)
            self.assertEqual(ci["mitigation"], [{"absorb": None, "observed": True, "share": 0.3}], patch)
            self.assertIn(133509 if patch < "12" else 136146, ci["talent_entries"], patch)
            self.assertNotIn(124841, ci["talent_entries"], patch)
            self.assertEqual(ci["cooldown_ms"], 90_000 if patch == "12.1.0" else 45_000, patch)
            self.assertEqual([m["talent"] for m in ci["cooldown_mods"]], ["Light Brewing"], patch)
            self.assertEqual([(m["talent"], m["add"]) for m in ci["charge_mods"]], [("Endless Draught", 1)], patch)
            # Up to 12.0.1 the tooltip names only Celestial Brew, but Black Ox Brew acts on the charge category.
            self.assertEqual([(r["name"], r["restores"]) for r in ci["reset_by"]],
                             [("Black Ox Brew", "all" if patch < "12.0.5" else "one")], patch)
        self.assertNotIn("Celestial Infusion", defensives._CATALOGS["11.1.7"].name_to_id)

    def comps(self, seen):
        return defensives._resolve(entry("12.1.0", "Celestial Infusion"), {136146: 1},
                                   {"Celestial Infusion": seen} if seen else {}, "Brewmaster")[0]

    def test_scored_only_from_its_real_size(self):
        self.assertIsNone(self.comps(None))
        self.assertEqual([(c["absorb_amount"], c["share"]) for c in self.comps(200_000)], [(200_000, 0.3)])

    def test_takes_thirty_percent_of_each_hit_up_to_its_size(self):
        comps = self.comps(200_000)
        one = hit(100_000, 100_000, 0, overkill=400_000)              # a 500k hit
        self.assertAlmostEqual(defensives._prevented(comps, one, MAX, 0, SCHOOLS), 150_000)
        small = hit(100_000, 50_000, 0, overkill=50_000)               # a 100k hit
        self.assertAlmostEqual(defensives._prevented(comps, small, MAX, 0, SCHOOLS), 30_000)

    def test_runs_out_over_several_hits(self):
        hits = [hit(99_000, 500_000, 500_000), hit(100_000, 500_000, 0, overkill=100_000)]
        r = defensives.assess_survival(hits, 100_000, [entry("12.1.0", "Celestial Infusion")], [], {500: "Frost Bolt"},
                                       SCHOOLS, talent_entries={136146: 1}, spec="Brewmaster",
                                       observed_absorbs={"Celestial Infusion": 200_000},
                                       aura_ms={"Celestial Infusion": 16_000})
        # Pressed before both: 150k off the first, the last 50k off the second.
        self.assertAlmostEqual(r["details"]["Celestial Infusion"]["amount"], 200_000, delta=1)
        self.assertTrue(r["wouldSave"]["Celestial Infusion"])

    def test_black_ox_brew_gives_back_one_charge(self):
        # With Endless Draught (2 charges, 90 s): both spent at 50 s and 51 s, Black Ox Brew at 55 s gives one back.
        from test_defensives import ReadyTimeTests, names
        ci = defensives._LATEST.name_to_id["Celestial Infusion"]
        t = ReadyTimeTests()
        casts = [(50_000, ci), (51_000, ci), (55_000, t.BLACK_OX_BREW)]
        talents = {136146, 117618}
        r = t.die("Monk", "Brewmaster", casts, 60_000, talents=talents, fight_start=40_000)
        self.assertIn("Celestial Infusion", names(r["available"]))
        r = t.die("Monk", "Brewmaster", casts + [(56_000, ci)], 60_000, talents=talents, fight_start=40_000)
        self.assertNotIn("Celestial Infusion", names(r["available"]))

    def test_after_a_full_shield(self):
        comps = self.comps(200_000) + [{"absorb_amount": 100_000, "school": None}]
        one = hit(100_000, 100_000, 0, overkill=400_000)              # a 500k hit
        # The other shield first (100k), then 30% of the 400k left (120k).
        self.assertAlmostEqual(defensives._prevented(comps, one, MAX, 0, SCHOOLS), 220_000)


if __name__ == "__main__":
    unittest.main()
