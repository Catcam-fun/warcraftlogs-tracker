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


ALL = ("11.0.2", "11.0.5", "11.0.7", "11.1.0", "11.1.5", "11.1.7", "11.2.0", "11.2.5", "11.2.7") + SINCE_11_2[3:]


def fields(comps):
    return [{k: (round(v, 4) if isinstance(v, float) else v) for k, v in c.items() if k != "school" or v} for c in comps]


class NewDefensivesTests(unittest.TestCase):
    """Defensives players press in real Mythic logs that the catalog lacked, with their game-data values."""

    def test_incarnation_guardian_of_ursoc(self):
        # 102558 effect 12: aura 133, +30% max health, 30 s, 180 s; granted through talent spell 394786 (entry 103201).
        for patch in ALL:
            inc = entry(patch, "Incarnation: Guardian of Ursoc")
            self.assertEqual((inc["class"], inc["specs"], inc["aura_ms"], inc["cooldown_ms"]),
                             ("Druid", ["Guardian"], 30_000, 180_000), patch)
            self.assertEqual(fields(defensives._resolve(inc, {}, {}, "Guardian")[0]), [{"hp": 0.3}], patch)
            self.assertIn(103201, inc["talent_entries"], patch)

    def test_mortal_coil_and_impending_victory_heal(self):
        for patch in ALL:
            mc, iv = entry(patch, "Mortal Coil"), entry(patch, "Impending Victory")
            self.assertEqual(fields(defensives._resolve(mc, {}, {}, "Affliction")[0]), [{"heal": 0.2}], patch)
            self.assertEqual(fields(defensives._resolve(iv, {}, {}, "Arms")[0]), [{"heal": 0.3}], patch)
            self.assertEqual((mc["cooldown_ms"], mc["major"], iv["cooldown_ms"], iv["major"]),
                             (45_000, False, 25_000, False), patch)

    def test_ultimate_penitence_is_its_real_shield(self):
        # applybuff carries the shield (609,600 on P6CwHkgFR9Krf1Bz, fight 10): scored from the log.
        for patch in ALL:
            up = entry(patch, "Ultimate Penitence")
            self.assertEqual((up["specs"], up["aura_ms"]), (["Discipline"], 6_500), patch)
            self.assertIsNone(defensives._resolve(up, {}, {}, "Discipline")[0], patch)
            self.assertEqual(defensives._resolve(up, {}, {"Ultimate Penitence": 609_600}, "Discipline")[0],
                             [{"absorb_amount": 609_600, "school": None}], patch)

    def test_soul_immolation_heals_only_from_12_0_5(self):
        # 12.0.0-12.0.1: it burns the Demon Hunter (aura 3); from 12.0.5 it heals 4% of max health a tick
        # (aura 20), six ticks over 5 s, the first on the press (P6CwHkgFR9Krf1Bz: 6 ticks of 25,254).
        for patch in ALL:
            if patch < "12.0.5":
                self.assertNotIn("Soul Immolation", defensives._CATALOGS[patch].name_to_id, patch)
                continue
            si = entry(patch, "Soul Immolation")
            self.assertEqual((si["specs"], si["aura_ms"]), (["Devourer"], 5_000), patch)
            self.assertEqual(fields(defensives._resolve(si, {}, {}, "Devourer")[0]), [{"heal": 0.24}], patch)
        self.assertEqual(defensives.HEAL_OVER_TIME["Soul Immolation"], 6)

    def test_earth_elemental(self):
        # The War Within: +15% max health while it is out (60 s), for every Shaman with it. Midnight: only with
        # Primordial Bond (1279819, entry 127889), 30 s; without it the button isn't a defensive.
        for patch in ALL:
            ee = entry(patch, "Earth Elemental")
            self.assertEqual(ee["aura_ms"], 60_000 if patch < "12" else 30_000, patch)
            talents = {} if patch < "12" else {127889: 1}
            self.assertEqual(fields(defensives._resolve(ee, talents, {}, "Elemental")[0]), [{"hp": 0.15}], patch)
            self.assertEqual("needs" in ee, patch >= "12", patch)
            if patch < "12":
                # The War Within's Primordial Bond (381764 -> 381761): 5% less damage while an elemental is out.
                self.assertEqual(fields(defensives._resolve(ee, {101847: 1}, {}, "Elemental")[0]),
                                 [{"hp": 0.15}, {"dr": 0.05}], patch)

    def test_earth_elemental_counts_only_with_primordial_bond_in_midnight(self):
        from test_defensives import names, run
        ee = defensives._LATEST.name_to_id["Earth Elemental"]
        has = {e: 1 for e in defensives.CATALOG[ee]["talent_entries"]}
        self.assertNotIn("Earth Elemental", names(run("Shaman", "Elemental", talents=has, auras=[])["available"]))
        r = run("Shaman", "Elemental", talents={**has, 127889: 1}, auras=[])
        self.assertIn("Earth Elemental", names(r["available"]))
        # Pressed this pull proves they had the button, but not the talent: still not a defensive.
        r = run("Shaman", "Elemental", casts=[(50_000, ee)], talents=has, auras=[])
        self.assertNotIn("Earth Elemental", names(r["available"] + r["cooldown"] + r["active"]))


class EarthElementalAuraTests(unittest.TestCase):
    """The +15% max health is aura 381755 ("Earth Elemental" in The War Within, "Primordial Bond" in Midnight);
    the button's own aura 198103 ("Earth Elemental", no duration in the data) lingers in the log long after
    the elemental is gone (P6CwHkgFR9Krf1Bz, 12.0.7: 381755 30.2-36.7 s, 198103 up to 7,103 s)."""

    def die(self, auras):
        from test_defensives import run
        ee = defensives._LATEST.name_to_id["Earth Elemental"]
        talents = {**{e: 1 for e in defensives.CATALOG[ee]["talent_entries"]}, 127889: 1}
        return run("Shaman", "Elemental", casts=[(90_000, ee)], talents=talents, auras=auras,
                   ability_names={381755: "Primordial Bond", 198103: "Earth Elemental"})

    def test_active_only_with_the_health_aura(self):
        from test_defensives import names
        self.assertIn("Earth Elemental", names(self.die([381755, 198103])["active"]))
        r = self.die([198103])
        self.assertNotIn("Earth Elemental", names(r["active"]))
        self.assertIn("Earth Elemental", names(r["cooldown"]))

    def test_the_state_check_reads_the_health_aura(self):
        from checks.source_state import active_mismatches
        bands = lambda name: {"name": name, "bands": [{"startTime": 80_000, "endTime": 110_000}]}
        effect = defensives._LATEST.effect_aura_names
        self.assertEqual(active_mismatches(["Earth Elemental"], [bands("Primordial Bond")], 100_000, None, effect), [])
        self.assertEqual(active_mismatches(["Earth Elemental"], [bands("Earth Elemental")], 100_000, None, effect),
                         ["Earth Elemental"])

    def test_the_durations_check_allows_the_despawn(self):
        # 36.2-36.7 s against 36 s: the aura goes when the elemental despawns, a moment after its time.
        from unittest import mock
        from checks import source_durations
        def check(end):
            run = mock.Mock(); run.code = "X"
            run.pulls = [{"id": 1, "start_time": 0, "end_time": 100_000}]
            run.meta = {"abilities": {381755: "Primordial Bond"}, "player_details": {}}
            run.cat = defensives._LATEST
            buffs = [{"type": "applybuff", "abilityGameID": 381755, "targetID": 7, "timestamp": 1_000},
                     {"type": "removebuff", "abilityGameID": 381755, "targetID": 7, "timestamp": 1_000 + end}]
            raw = {"combatants": [{"sourceID": 7}], "casts": [], "buffs": buffs}
            with mock.patch.object(source_durations.defensives, "fetch_defensive_raw", return_value=raw),                     mock.patch.object(source_durations.defensives, "filter_defensive_raw",
                                      return_value={"talents": {(1, 7): {}}}),                     mock.patch.object(source_durations.defensives, "pull_spec", return_value="Elemental"),                     mock.patch.object(source_durations.defensives, "_talented_duration", return_value=36_000):
                return source_durations.check(run).status
        self.assertEqual(check(36_700), "pass")
        self.assertEqual(check(38_000), "fail")

    def test_the_catalog_names_the_aura_per_patch(self):
        self.assertEqual(entry("11.2.7", "Earth Elemental")["auras"], {381755: "Earth Elemental"})
        self.assertEqual(entry("12.1.0", "Earth Elemental")["auras"], {381755: "Primordial Bond"})
        self.assertIn("Primordial Bond", defensives._LATEST.buff_names)


class SentinelTests(unittest.TestCase):
    """Sentinel (389539, Protection Paladin): 15 stacks (SpellAuraOptions), each +1% max health (effect 10) and
    -2% damage taken (effect 11). Stacks drop 1 a second: over the last 15 s of its duration in The War Within
    ("After ${$d-15} sec"; 16 s), after $<delay> = effect 13 / 1000 = 5 s in Midnight (16 s, 20 s from 12.0.5),
    the k-th one k seconds after that,
    Righteous Protector shortening both by 40% (12.0.0 on). Holy Power spent delays the drop; the replay
    credits only the drop without it."""

    def test_catalog(self):
        for patch in ALL:
            s = entry(patch, "Sentinel")
            want = {"stacks": 15, **({"decay_end_ms": 15_000} if patch < "12" else {"decay_after_ms": 5_000})}
            for c in s["mitigation"]:
                self.assertEqual({k: c[k] for k in want}, want, patch)
            self.assertEqual(sorted((k, c[k]) for c in s["mitigation"] for k in ("dr", "hp") if k in c),
                             [("dr", 0.02), ("hp", 0.01)], patch)
            self.assertEqual(s["aura_ms"], 20_000 if patch >= "12.0.5" else 16_000, patch)

    def option(self, patch, talents=None, dur=None):
        e = entry(patch, "Sentinel")
        comps, _ = defensives._resolve(e, talents or {}, {}, "Protection")
        return defensives._option("Sentinel", comps, dur or defensives._talented_duration(e, talents or {}, "Protection"))

    def reduction_at(self, opt, t):
        keep = 1.0
        for c, ms in opt["lasting"]:
            if "dr" in c and t < ms:
                keep *= 1 - c["dr"]
        return round(1 - keep, 4)

    def test_stacks_drop_one_a_second(self):
        opt = self.option("12.1.0")                          # 20 s, the drop from 5 s
        self.assertEqual([self.reduction_at(opt, t) for t in (0, 4_999, 5_000, 6_000, 18_000, 19_000, 20_000)],
                         [0.30, 0.30, 0.30, 0.28, 0.04, 0.02, 0.0])
        self.assertAlmostEqual(sum(c["hp"] for c, _ in opt["lasting"] if "hp" in c), 0.15)
        opt = self.option("12.0.0")                          # 16 s: five stacks left when it runs out
        self.assertEqual([self.reduction_at(opt, t) for t in (15_000, 15_999, 16_000)], [0.10, 0.10, 0.0])
        opt = self.option("11.2.7")                          # 16 s, the drop over its last 15 s
        self.assertEqual([self.reduction_at(opt, t) for t in (0, 1_999, 2_000, 15_000, 16_000)], [0.30, 0.30, 0.28, 0.02, 0.0])

    def test_righteous_protector_shortens_the_wait(self):
        rp = next(m for m in entry("12.1.0", "Sentinel")["duration_mods"] if m["talent"] == "Righteous Protector")
        opt = self.option("12.1.0", {e: 1 for e in rp["entries"]})          # 12 s, the drop from 3 s
        self.assertEqual([self.reduction_at(opt, t) for t in (3_999, 4_000, 11_999, 12_000)], [0.30, 0.28, 0.14, 0.0])

    def test_the_mitigation_check_does_not_predict_it(self):
        # WCL lists the aura on a hit, not how many stacks were up: no prediction to compare.
        from checks.source_mitigation import predicted_keep
        comps, _ = defensives._resolve(entry("12.1.0", "Sentinel"), {}, {}, "Protection")
        self.assertEqual(predicted_keep(comps, hit(1, 100, 0), True, SCHOOLS), (None, None))

    def test_saves_with_the_stacks_left(self):
        e = entry("12.1.0", "Sentinel")
        hits = [hit(100_000, 400_000, 100_000), hit(110_000, 100_000, 0, overkill=40_000)]
        r = defensives.assess_survival(hits, 110_000, [e], [], {500: "Frost Bolt"}, SCHOOLS, spec="Protection",
                                       aura_ms={"Sentinel": 20_000})
        self.assertTrue(r["wouldSave"]["Sentinel"])


if __name__ == "__main__":
    unittest.main()
