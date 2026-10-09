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

    def ci(self, hit_, stagger=None):
        win = defensives._Window([hit_], SCHOOLS, stagger=stagger)
        opt = defensives._option("Celestial Infusion", self.comps(1_000_000), 16_000)
        return defensives._simulate([opt], hit_["timestamp"] - 1, win, 0)[0]

    def test_after_the_real_shields_on_the_hit(self):
        # A 500k hit, 100k of it absorbed by a shield the player had: 30% of the 400k left.
        self.assertAlmostEqual(self.ci(hit(100_000, 300_000, 0, overkill=100_000, absorbed=100_000)), 120_000)
        # A Brewmaster's: 200k staggered and 100k by a shield: 30% of the 200k left after both.
        self.assertAlmostEqual(self.ci(hit(100_000, 150_000, 0, overkill=50_000, absorbed=300_000),
                                       stagger={0: (200_000, [])}), 60_000)
        # A Stagger tick partly absorbed by a shield: 30% of what the shield left.
        tick = dict(hit(100_000, 60_000, 0, overkill=20_000, absorbed=20_000), abilityGameID=defensives.STAGGER_TICK)
        self.assertAlmostEqual(self.ci(tick, stagger={}), 24_000)

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

    def test_soul_immolation_is_not_listed(self):
        # The owner's rule (2026-10-08): only true defensives are buttons. Soul Immolation is a Devourer's
        # rotational resource cooldown; its real heal is in the log already.
        for patch in ALL:
            self.assertNotIn("Soul Immolation", defensives._CATALOGS[patch].name_to_id, patch)

    def test_ticks_from_the_press_with_another_option_alongside(self):
        # A heal over time with the game's tick period and a tick on the press (6 ticks of a second, as Soul
        # Immolation logs): the schedule holds whatever else is pressed with it.
        hot = {"heal": 0.24, "ticks": 6, "tick_ms": 1_000, "first_tick": True}
        opt = defensives._option("HoT", [hot], 5_000)
        other = defensives._option("Other", [{"heal": 0.1, "over_ms": 3_000, "ticks": 3}], 3_000)
        for kb, ticks in ((10_500, 1), (11_500, 2), (15_500, 6)):
            win = defensives._Window([hit(9_000, 600_000, 400_000), hit(kb, 400_000, 0, overkill=10)], SCHOOLS)
            self.assertEqual(defensives._simulate([opt], 10_000, win, 1)[1], ticks, kb)
            # The other option's own ticks (every second from 1 s) land on top, never fewer of the first's.
            extra = sum(1 for t in (11_000, 12_000, 13_000) if t < kb)
            self.assertEqual(defensives._simulate([opt, other], 10_000, win, 1)[1], ticks + extra, kb)

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
        # By aura ID: in The War Within the lingering 198103 and the health aura 381755 share the name.
        from checks.source_state import active_mismatches
        bands = lambda guid, name: {"guid": guid, "name": name, "bands": [{"startTime": 80_000, "endTime": 110_000}]}
        for cat, name in ((defensives._LATEST, "Primordial Bond"), (defensives._CATALOGS["11.2.7"], "Earth Elemental")):
            ids = defensives.effect_aura_ids(cat)
            self.assertEqual(active_mismatches(["Earth Elemental"], [bands(381755, name)], 100_000, None, ids), [])
            self.assertEqual(active_mismatches(["Earth Elemental"], [bands(198103, "Earth Elemental")], 100_000, None,
                                               ids), ["Earth Elemental"])

    def test_the_war_within_lingering_aura_is_not_the_button(self):
        tww = defensives._CATALOGS["11.2.7"]
        names_ = {381755: "Earth Elemental", 198103: "Earth Elemental"}
        self.assertIsNone(defensives.aura_name(tww, 198103, names_))
        self.assertEqual(defensives.aura_name(tww, 381755, names_), "Earth Elemental")

    def test_the_health_aura_proves_the_talent(self):
        # Midnight, no talent record: 381755 ("Primordial Bond") seen on them means they have Primordial Bond.
        from test_defensives import names
        ee = defensives._LATEST.name_to_id["Earth Elemental"]
        ability_names = {381755: "Primordial Bond", ee: "Earth Elemental"}
        def die(buffs):
            indexed = {"casts": {1: [(50_000, ee)]}, "talents": {}, "buffs": {1: buffs}}
            return defensives.analyze_death(1, "Shaman", "Elemental", 7, 0, 100_000, indexed, ability_names, {})
        seen = [(50_100, "applybuff", 381755, 1, 0), (80_100, "removebuff", 381755, 1, 0)]
        self.assertIn("Earth Elemental", names(die(seen)["cooldown"]))
        self.assertNotIn("Earth Elemental", names(die([])["cooldown"] + die([])["available"]))

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
            with mock.patch.object(source_durations.defensives, "fetch_defensive_raw", return_value=raw), \
                    mock.patch.object(source_durations.defensives, "filter_defensive_raw",
                                      return_value={"talents": {(1, 7): {}}}), \
                    mock.patch.object(source_durations.defensives, "pull_spec", return_value="Elemental"), \
                    mock.patch.object(source_durations.defensives, "_talented_duration", return_value=36_000),                     mock.patch.object(source_durations.defensives, "_paged", return_value=[]):
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
        # FaC4AgJ8vMTfP1VN (12.1.0), 16 Sentinels with Righteous Protector: the first stack went 3.99-7.01 s
        # after the press (3 s wait, the first stack a second later), the aura lasted 16-25 s: never fewer stacks.
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


class ZealotsParagonTests(unittest.TestCase):
    """Zealot's Paragon (391142): each Judgment or Hammer of Wrath cast while Sentinel is up extends it by
    0.5 s a rank. FaC4AgJ8vMTfP1VN (12.1.0), a Protection Paladin with Righteous Protector (Sentinel 12 s) and
    two ranks: all 16 Sentinels lasted 12 s + 1 s per such cast while up (16.0 to 25.0 s, to the 10 ms)."""
    RP_ZP = {102440: 1, 102433: 2}
    JUDGMENT, HAMMER = 275779, 1241413

    def test_catalog(self):
        for patch in ALL:
            ext = entry(patch, "Sentinel")["extended_by"]
            self.assertEqual((ext["talent"], ext["ms"]), ("Zealot's Paragon", 500), patch)
            self.assertIn(self.JUDGMENT, ext["casts"], patch)
            # Loadouts are trimmed to the entries the catalog reads: Zealot's Paragon's must survive that.
            self.assertTrue(set(ext["entries"]) <= defensives._CATALOGS[patch].relevant_talent_entries, patch)
        self.assertIn(self.HAMMER, entry("12.1.0", "Sentinel")["extended_by"]["casts"])
        self.assertTrue({self.JUDGMENT, self.HAMMER} <= defensives._LATEST.extend_ids)
        self.assertIn(102433, defensives._LATEST.relevant_talent_entries)

    def test_each_cast_while_up_extends_it(self):
        e = entry("12.1.0", "Sentinel")
        comps, _ = defensives._resolve(e, self.RP_ZP, {}, "Protection")
        dur = defensives._talented_duration(e, self.RP_ZP, "Protection")
        self.assertEqual(dur, 12_000)
        opt = defensives._option("Sentinel", comps, dur)
        # Casts at 1 s, 5 s, 13 s (inside the 14 s the first two give) and 20 s (after it ran out): 12 + 3 = 15 s.
        opt["extend"] = (1_000, [-500, 1_000, 5_000, 13_000, 20_000])
        at = defensives._at_press(opt, 0)
        self.assertEqual(max(ms for _, ms in at["lasting"]), 15_000)
        self.assertEqual(defensives._at_press(dict(opt, extend=None), 0)["lasting"], opt["lasting"])

    def test_the_casts_come_with_the_death_window(self):
        # Judgment casts in the window (from the windows' extras block) keep it up past its 12 s: pressed
        # before a hit at 100 s, it is still up (4 stacks) for the killing blow at 114 s only with them.
        e = entry("12.1.0", "Sentinel")
        kb = 114_000
        casts = [{"timestamp": t, "type": "cast", "sourceID": 1, "abilityGameID": self.JUDGMENT}
                 for t in (101_000, 103_000, 105_000)]
        hits = [hit(100_000, 800_000, 200_000), hit(kb, 200_000, 0, overkill=50_000)]
        def save(with_casts, talents):
            r = defensives.assess_survival(hits + (casts if with_casts else []), kb, [e], [], {500: "Frost Bolt"},
                                           SCHOOLS, talent_entries=talents, spec="Protection",
                                           aura_ms={"Sentinel": 12_000})
            return r["details"]["Sentinel"]["amount"]
        without = save(False, self.RP_ZP)
        self.assertGreater(save(True, self.RP_ZP), without)        # 15 s with the casts
        self.assertEqual(save(True, {102440: 1}), without)          # no Zealot's Paragon: no extension

    def test_the_durations_check_counts_the_casts(self):
        # Deawina's first Sentinel: 20.0 s with 8 Judgments / Hammers of Wrath while up (12 s + 8 x 1 s).
        from unittest import mock
        from checks import source_durations
        def check(n_casts):
            run = mock.Mock(); run.code = "X"
            run.pulls = [{"id": 1, "start_time": 0, "end_time": 100_000}]
            run.meta = {"abilities": {389539: "Sentinel"}, "player_details": {}}
            run.cat = defensives._LATEST
            buffs = [{"type": "applybuff", "abilityGameID": 389539, "targetID": 7, "timestamp": 1_000},
                     {"type": "removebuff", "abilityGameID": 389539, "targetID": 7, "timestamp": 21_000}]
            raw = {"combatants": [{"sourceID": 7}], "casts": [], "buffs": buffs}
            judgments = [{"type": "cast", "sourceID": 7, "abilityGameID": self.JUDGMENT, "timestamp": 2_000 + 1_500 * i}
                         for i in range(n_casts)]
            with mock.patch.object(source_durations.defensives, "fetch_defensive_raw", return_value=raw), \
                    mock.patch.object(source_durations.defensives, "filter_defensive_raw",
                                      return_value={"talents": {(1, 7): self.RP_ZP}}), \
                    mock.patch.object(source_durations.defensives, "pull_spec", return_value="Protection"), \
                    mock.patch.object(source_durations.defensives, "_paged", return_value=judgments):
                return source_durations.check(run).status
        self.assertEqual(check(8), "pass")
        self.assertEqual(check(2), "fail")


class HealthstoneSoulburnTests(unittest.TestCase):
    """Soulburn (385899, a button costing a Soul Shard) buffs the next spell (387626, 20 s): on a Healthstone,
    +30% healing (387626 effect 1) and Soulburn: Healthstone (387636: aura 133 +20% max health, 12 s). Without
    a Soulburn cast none of it happens, so the talent alone adds nothing. Gorebound Fortitude (449701, passive):
    "You always gain the benefit of Soulburn when consuming a Healthstone" (effect 0 triggers 387636). Same
    data in every patch from 11.0.2 to 12.1.0."""
    SOULBURN, GOREBOUND = 91469, 117447

    def test_catalog(self):
        for patch in ALL:
            for name in ("Healthstone", "Demonic Healthstone"):
                comps = entry(patch, name)["mitigation"]
                talents = {m["talent"] for c in comps for m in c.get("mods", ())}
                self.assertNotIn("Soulburn", talents, (patch, name))
                hp = [c for c in comps if "hp" in c]
                self.assertEqual(len(hp), 1, (patch, name))
                self.assertEqual([(m["talent"], m["add"]) for m in hp[0]["mods"]], [("Gorebound Fortitude", 0.2)])
                self.assertEqual(hp[0]["dur_ms"], 12_000, (patch, name))
                heal = next(c for c in comps if "heal" in c)
                # Adds 30% of max health to the share (measured: 0.30 -> 0.60), not x1.3.
                self.assertIn(("Gorebound Fortitude", 0.3),
                              [(m["talent"], m.get("add")) for m in heal["mods"]], (patch, name))
                self.assertNotIn("Gorebound Fortitude", [m["talent"] for m in heal["mods"] if "mult" in m])
                # What a Soulburn cast first adds, credited only when the log shows it was possible.
                # The buff goes to the first spell it empowers: Soulburn's tooltip lists Demonic Circle:
                # Teleport, Demonic Gateway, Drain Life, Health Funnel (The War Within only) and the
                # Healthstone. A cast of one of the others between Soulburn and a Healthstone used it up.
                spent = [48020, 111771, 234153] + ([755] if patch.startswith("11.") else [])
                self.assertEqual(entry(patch, name)["soulburn"], {
                    "talent": "Soulburn", "entries": [91469, 116016], "spell": 385899, "buff": 387626,
                    "buff_ms": 20_000, "cooldown_ms": 6_000, "cost": 10, "heal": 0.3, "hp": 0.2,
                    "dur_ms": 12_000, "consumed_by": sorted(spent)}, (patch, name))

    def test_the_spells_soulburn_empowers_come_from_its_tooltip(self):
        import os, sys
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "scripts"))
        import build_defensive_catalog as b

        class GD:
            names = {48020: "Demonic Circle: Teleport", 111771: "Demonic Gateway", 234153: "Drain Life",
                     755: "Health Funnel"}
        tip = ("Consumes a Soul Shard.\n\n|cFFFFFFFFDemonic Circle: Teleport|r: faster.\n\n"
               "|cFFFFFFFFDemonic Gateway|r: instant.\n\n|cFFFFFFFFHealthstone|r: more healing.")
        problems = []
        self.assertEqual(b.soulburn_consumers(GD, {b.SOULBURN: tip}, problems), [48020, 111771])
        self.assertEqual(problems, [])
        b.soulburn_consumers(GD, {b.SOULBURN: tip + "\n\n|cFFFFFFFFShadow Bolt|r: more."}, problems)
        self.assertEqual(len(problems), 1)        # a spell it now empowers that isn't mapped: fails loudly
        self.assertIn("Shadow Bolt", problems[0])

    def test_soulburn_alone_adds_no_health(self):
        hs = entry("12.1.0", "Healthstone")
        comps, _ = defensives._resolve(hs, {self.SOULBURN: 1}, {}, "Affliction")
        self.assertFalse([c for c in comps if c.get("hp")])
        comps, _ = defensives._resolve(hs, {self.GOREBOUND: 1}, {}, "Affliction")
        self.assertEqual([(c["hp"], c["dur_ms"]) for c in comps if c.get("hp")], [(0.2, 12_000)])


class UrsineVigorTests(unittest.TestCase):
    """Ursine Vigor (377842, effect 0: aura 231, 15, triggers 393903): "For $340541d after shifting into Bear
    Form, your health and armor are increased by $s1%"; the buff 393903 lasts 4 s (SpellMisc) in every patch."""

    def test_catalog(self):
        for patch in ALL:
            vigor = [c for c in entry(patch, "Bear Form")["mitigation"]
                     if (c.get("needs") or {}).get("talent") == "Ursine Vigor"]
            self.assertEqual(sorted(k for c in vigor for k in ("hp", "armor") if k in c), ["armor", "hp"], patch)
            self.assertEqual({c["dur_ms"] for c in vigor}, {4_000}, patch)

    def test_it_runs_out_after_four_seconds(self):
        bear = entry("12.1.0", "Bear Form")
        has = {e: 1 for c in bear["mitigation"] if (c.get("needs") or {}).get("talent") == "Ursine Vigor"
               for e in c["needs"]["entries"]}
        comps, _ = defensives._resolve(bear, has, {}, "Balance")
        vigor = [c for c in comps if c.get("dur_ms")]
        self.assertEqual(len(vigor), 2)
        lasting = dict((id(c), ms) for c, ms in defensives._option("Bear Form", comps, None)["lasting"])
        self.assertEqual({lasting[id(c)] for c in vigor}, {4_000})
        self.assertEqual({ms for c, ms in defensives._option("Bear Form", vigor, 3_000)["lasting"]}, {3_000})

    def test_max_health_comes_off_when_it_runs_out(self):
        hits = [hit(9_000, 600_000, 400_000), hit(15_000, 400_000, 0, overkill=10)]
        win = defensives._Window(hits, SCHOOLS)
        up = defensives._simulate([defensives._option("x", [{"hp": 0.5}], None)], 10_000, win, 1)[0]
        gone = defensives._simulate([defensives._option("x", [{"hp": 0.5, "dur_ms": 4_000}], None)], 10_000, win, 1)[0]
        self.assertGreater(up, 0)
        self.assertEqual(gone, 0)


class MaxHealthBuildWhoTests(unittest.TestCase):
    """build_max_health_auras.Data.who: like the catalog's Modifiers.who, a spec passive that is also a talent
    entry carries both; max_health_size reads a term's entries first, so a term with both fails the build."""

    @staticmethod
    def build():
        import os, sys
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "scripts"))
        import build_max_health_auras as build
        return build

    def test_both(self):
        build = self.build()
        d = build.Data.__new__(build.Data)
        d.talent_entries, d.spec_spells = {5: {9}, 6: {8}}, {5: {"Arcane"}, 7: {"Fire"}}
        self.assertEqual(d.who(5), {"entries": [9], "specs": ["Arcane"]})
        self.assertEqual(d.who(6), {"entries": [8]})
        self.assertEqual(d.who(7), {"specs": ["Fire"]})
        self.assertIsNone(d.who(4))

    def test_a_term_with_both_is_a_problem(self):
        build = self.build()
        both = {"entries": [9], "specs": ["Arcane"]}
        self.assertTrue(build.both_problems({1: [{"from": 5, "index": 0, "share": 0.1, **both}]}))
        self.assertTrue(build.both_problems({1: [{"from": 5, "index": 0, "share": 0.1,
                                                  "mods": [{"add": 0.1, "by": 6, **both}]}]}))
        self.assertFalse(build.both_problems({1: [{"from": 5, "index": 0, "share": 0.1, "entries": [9],
                                                   "mods": [{"mult": 1.1, "by": 6, "specs": ["Arcane"]}]}]}))


if __name__ == "__main__":
    unittest.main()


class HealOverTimeScheduleBuildTests(unittest.TestCase):
    """The build reads a heal over time's schedule from the game data: EffectAuraPeriod, the spell's
    duration, a tick on application (SpellMisc Attributes_5 0x200), and fails on a period haste changes
    (Attributes_5 0x2000: Rejuvenation, Renew, every haste-scaled DoT), which the replay doesn't model."""

    class GD:
        def __init__(self, attr5):
            self.periods = {(1, 0): 1_000}
            self.duration = {1: 3_000}
            self.attr5 = {1: attr5}

    def schedule(self, attr5):
        import os, sys
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "scripts"))
        import build_defensive_catalog as build
        problems = []
        return build.hot_schedule(self.GD(attr5), 1, 0, "x", problems), problems

    def test_tick_on_application(self):
        self.assertEqual(self.schedule(0x200), ((4, 1_000, True), []))

    def test_first_tick_after_a_period(self):
        self.assertEqual(self.schedule(0), ((3, 1_000, False), []))

    def test_haste_is_a_problem(self):
        got, problems = self.schedule(0x2200)
        self.assertEqual(len(problems), 1)
