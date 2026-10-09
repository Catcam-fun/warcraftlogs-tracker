import unittest
import os
import sys
import types

import defensives
import features
from defensive_catalog import CATALOG

ICE_BLOCK, ICE_COLD, MIRROR, ALTER_TIME = 45438, 414658, 55342, 342245
FEINT, CLOAK, EVASION = 1966, 31224, 5277
PAIN_SUPP, HEALTHSTONE, POTION = 33206, 6262, 1234768


def entries(*spell_ids):
    return {e for sid in spell_ids for e in CATALOG[sid]["talent_entries"]}


def run(player_class, spec, casts=(), auras=None, talents=None, fight_start=0, death=100_000,
        ability_names=None, actors=None):
    """`auras`: aura IDs listed on the killing blow (None = no killing blow recorded)."""
    indexed = {
        "casts": {1: sorted(casts)},
        "talents": {} if talents is None else {(7, 1): talents},
    }
    names = {sid: d["name"] for sid, d in CATALOG.items()}
    names.update(ability_names or {})
    kb = None
    if auras is not None:
        kb = [{"timestamp": death, "type": "damage", "targetID": 1, "amount": 1, "overkill": 1,
               "buffs": "".join(f"{a}." for a in auras)}]
    return defensives.analyze_death(1, player_class, spec, 7, fight_start, death, indexed, names, actors or {},
                                    hits=kb)


def names(items):
    return {i["name"] for i in items}


class DefensiveAnalysisTests(unittest.TestCase):
    def test_only_talented_abilities_count(self):
        r = run("Mage", "Frost", talents=entries(ICE_BLOCK))
        self.assertIn("Ice Block", names(r["available"]))
        self.assertNotIn("Mirror Image", names(r["available"] + r["cooldown"]))
        self.assertNotIn("Ice Cold", names(r["available"] + r["cooldown"]))
        self.assertTrue(r["talentsKnown"])

    def test_replacing_talent_hides_the_original(self):
        r = run("Mage", "Frost", talents=entries(ICE_COLD))
        self.assertIn("Ice Cold", names(r["available"]))
        self.assertNotIn("Ice Block", names(r["available"] + r["cooldown"]))

    def test_other_classes_abilities_never_appear(self):
        r = run("Mage", "Frost", talents=entries(ICE_BLOCK, CLOAK))
        self.assertNotIn("Cloak of Shadows", names(r["available"]))

    def test_baseline_abilities_need_no_talent(self):
        r = run("Druid", "Balance", talents=set())
        self.assertIn("Barkskin", names(r["available"]))

    def test_short_cooldowns_are_tracked_too(self):
        r = run("Rogue", "Assassination", talents=set(), auras=[])
        self.assertIn("Feint", names(r["available"]))
        r = run("Rogue", "Assassination", talents=set(), auras=[FEINT])
        self.assertIn("Feint", names(r["active"]))

    def test_aura_events_give_exact_state_and_caster(self):
        names_map = {sid: d["name"] for sid, d in CATALOG.items()}
        names_map[999] = "Pain Suppression"
        indexed = {"casts": {1: [(95_000, ICE_BLOCK)]}, "talents": {(7, 1): entries(ICE_BLOCK)},
                   "buffs": {1: [(95_000, "applybuff", ICE_BLOCK, 1), (99_000, "applybuff", 999, 5),
                                 (100_010, "removebuff", ICE_BLOCK, 1), (100_010, "removebuff", 999, 5)]}}
        r = defensives.analyze_death(1, "Mage", "Frost", 7, 0, 100_000, indexed, names_map, {5: "Holypriest"})
        self.assertIn("Ice Block", names(r["active"]))
        pain = next(a for a in r["active"] if a["name"] == "Pain Suppression")
        self.assertEqual((pain["kind"], pain["by"]), ("external", "Holypriest"))
        # Removed well before death -> not active.
        indexed["buffs"][1] = [(50_000, "applybuff", ICE_BLOCK, 1), (60_000, "removebuff", ICE_BLOCK, 1)]
        r = defensives.analyze_death(1, "Mage", "Frost", 7, 0, 100_000, indexed, names_map, {})
        self.assertNotIn("Ice Block", names(r["active"]))

    def test_an_active_defensive_carries_the_players_talented_values(self):
        # Barkskin up at death with Oakskin and Improved Barkskin: 30% for 12s, the talents listed.
        barkskin = 22812
        r = run("Druid", "Balance", talents={123795, 128591}, auras=[barkskin])
        a = next(x for x in r["active"] if x["name"] == "Barkskin")
        self.assertTrue(a["talentsKnown"])
        self.assertEqual(a["effect"], [{"dr": 0.3}])
        self.assertEqual((a["auraMs"], a["cooldownMs"], a["charges"]), (12_000, 60_000, 1))
        self.assertIn({"talent": "Oakskin", "field": "dr", "rank": 1, "add": 0.1}, a["talents"])
        self.assertIn({"talent": "Improved Barkskin", "field": "duration", "rank": 1, "add_ms": 4000}, a["talents"])
        # Without the pull's talents: base values aren't claimed as theirs.
        r = run("Druid", "Balance", auras=[barkskin])
        a = next(x for x in r["active"] if x["name"] == "Barkskin")
        self.assertEqual(a, {"name": "Barkskin", "kind": "personal", "major": True, "talentsKnown": False})

    def test_an_active_external_carries_its_casters_talents(self):
        # Ironbark from a Restoration Druid with Improved Ironbark (-20s) and Regenerative Heartwood (+4s).
        ironbark = 102342
        names_map = {sid: d["name"] for sid, d in CATALOG.items()}
        indexed = {"casts": {}, "talents": {(7, 1): set(), (7, 5): {103141, 103139, 103131}},
                   "buffs": {1: [(95_000, "applybuff", ironbark, 5)]}}
        kb = [{"timestamp": 100_000, "type": "damage", "targetID": 1, "amount": 1, "overkill": 1,
               "buffs": f"{ironbark}."}]
        r = defensives.analyze_death(1, "Mage", "Frost", 7, 0, 100_000, indexed, names_map, {5: "Treehugger"},
                                     hits=kb)
        a = next(x for x in r["active"] if x["name"] == "Ironbark")
        self.assertEqual((a["kind"], a["by"], a["talentsKnown"]), ("external", "Treehugger", True))
        self.assertEqual((a["auraMs"], a["cooldownMs"]), (16_000, 70_000))
        self.assertIn({"talent": "Improved Ironbark", "field": "cooldown", "rank": 1, "add_ms": -20000}, a["talents"])
        # The caster's loadout isn't in the log: talents unknown.
        del indexed["talents"][(7, 5)]
        r = defensives.analyze_death(1, "Mage", "Frost", 7, 0, 100_000, indexed, names_map, {5: "Treehugger"},
                                     hits=kb)
        a = next(x for x in r["active"] if x["name"] == "Ironbark")
        self.assertFalse(a["talentsKnown"])
        self.assertNotIn("auraMs", a)

    def test_missing_aura_removal_is_capped_by_duration(self):
        # The log never recorded Ice Block (10s) ending; 60s later it isn't still up.
        indexed = {"casts": {1: [(40_000, ICE_BLOCK)]}, "talents": {(7, 1): entries(ICE_BLOCK)},
                   "buffs": {1: [(40_000, "applybuff", ICE_BLOCK, 1)]}}
        names_map = {sid: d["name"] for sid, d in CATALOG.items()}
        r = defensives.analyze_death(1, "Mage", "Frost", 7, 0, 100_000, indexed, names_map, {})
        self.assertNotIn("Ice Block", names(r["active"]))
        r = defensives.analyze_death(1, "Mage", "Frost", 7, 0, 45_000, indexed, names_map, {})
        self.assertIn("Ice Block", names(r["active"]))

    def test_killing_blow_snapshot_decides_what_was_up(self):
        names_map = {sid: d["name"] for sid, d in CATALOG.items()}
        names_map[999] = "Pain Suppression"
        indexed = {"casts": {}, "talents": {(7, 1): entries(ICE_BLOCK)},
                   "buffs": {1: [(99_000, "applybuff", ICE_BLOCK, 1), (99_500, "applybuff", 999, 5)]}}
        # Events say Ice Block is up, but the killing blow's aura list only has Pain Suppression.
        kb = [{"timestamp": 100_000, "type": "damage", "targetID": 1, "amount": 1, "overkill": 1, "buffs": "999."}]
        r = defensives.analyze_death(1, "Mage", "Frost", 7, 0, 100_000, indexed, names_map, {5: "Holypriest"},
                                     hits=kb)
        self.assertNotIn("Ice Block", names(r["active"]))
        pain = next(a for a in r["active"] if a["name"] == "Pain Suppression")
        self.assertEqual((pain["kind"], pain["by"]), ("external", "Holypriest"))

    def test_used_ability_is_on_cooldown_with_timings(self):
        r = run("Mage", "Frost", talents=entries(ICE_BLOCK),
                casts=[(40_000, ICE_BLOCK)], fight_start=0, death=100_000)
        cd = {c["name"]: c for c in r["cooldown"]}
        self.assertEqual(cd["Ice Block"]["usedAgo"], 60)
        self.assertEqual(cd["Ice Block"]["readyIn"], 180)   # 240s cooldown, 60s elapsed

    def test_long_cooldowns_reset_between_pulls(self):
        # Pressed last pull (before this pull's start): 240s cooldown resets at encounter end.
        r = run("Mage", "Frost", talents=entries(ICE_BLOCK),
                casts=[(180_000, ICE_BLOCK)], fight_start=200_000, death=230_000)
        self.assertIn("Ice Block", names(r["available"]))

    def test_short_cooldowns_carry_over_from_last_pull(self):
        # Cloak (120s) pressed 10s before the pull is still on cooldown 30s in.
        r = run("Rogue", "Outlaw", talents=entries(CLOAK),
                casts=[(190_000, CLOAK)], fight_start=200_000, death=230_000)
        self.assertIn("Cloak of Shadows", names(r["cooldown"]))

    def test_talent_cooldown_reduction_learned_from_log(self):
        # Evasion recast after 80s (base 120s) proves a shorter cooldown; 85s later it's back.
        r = run("Rogue", "Outlaw", talents=entries(EVASION),
                casts=[(0, EVASION), (80_000, EVASION)], death=165_000 + 1)
        self.assertIn("Evasion", names(r["available"]))

    def test_active_aura_on_killing_blow(self):
        r = run("Mage", "Frost", talents=entries(ICE_BLOCK), casts=[(95_000, ICE_BLOCK)], auras=[ICE_BLOCK])
        self.assertIn("Ice Block", names(r["active"]))
        self.assertNotIn("Ice Block", names(r["cooldown"]))
        self.assertTrue(r["activeKnown"])

    def test_aura_gone_before_death_is_not_active(self):
        r = run("Mage", "Frost", talents=entries(ICE_BLOCK), casts=[(50_000, ICE_BLOCK)], auras=[])
        self.assertNotIn("Ice Block", names(r["active"]))
        self.assertIn("Ice Block", names(r["cooldown"]))

    def test_no_killing_blow_means_active_unknown(self):
        r = run("Mage", "Frost", talents=entries(ICE_BLOCK), auras=None)
        self.assertFalse(r["activeKnown"])
        self.assertEqual(r["active"], [])

    def test_external_on_killing_blow(self):
        r = run("Mage", "Frost", talents=set(), auras=[999], ability_names={999: "Pain Suppression"})
        ext = [a for a in r["active"] if a["kind"] == "external"]
        self.assertEqual(ext, [{"name": "Pain Suppression", "kind": "external", "by": None, "talentsKnown": False}])

    def test_consumables_this_pull_only(self):
        r = run("Mage", "Frost", talents=set(),
                casts=[(150_000, POTION), (270_000, HEALTHSTONE)], fight_start=200_000, death=300_000)
        self.assertEqual(r["healthstone"], {"usedAgo": 30, "name": "Healthstone", "readyIn": 30})
        self.assertEqual(r["potion"], {"usedAgo": None})

    def test_consumables_come_back_after_their_cooldown(self):
        # Healthstone 60s, health potion 5 min, from the last use this pull (measured on live logs).
        r = run("Mage", "Frost", talents=set(),
                casts=[(210_000, HEALTHSTONE), (220_000, POTION)], fight_start=200_000, death=300_000)
        self.assertEqual(r["healthstone"], {"usedAgo": None, "lastUsedAgo": 90})
        self.assertEqual(r["potion"]["readyIn"], 220)
        r = run("Mage", "Frost", talents=set(), casts=[(220_000, POTION)], fight_start=200_000, death=530_000)
        self.assertEqual(r["potion"], {"usedAgo": None, "lastUsedAgo": 310})

    def test_missing_talent_data_falls_back_to_log_evidence(self):
        r = run("Mage", "Frost", talents=None, casts=[(10_000, MIRROR)], death=200_000)
        self.assertFalse(r["talentsKnown"])
        self.assertIn("Mirror Image", names(r["available"] + r["cooldown"]))
        self.assertNotIn("Ice Block", names(r["available"]))  # talent ability, never pressed

    def test_pressing_it_this_pull_proves_ownership(self):
        # Talent record lacks Mirror Image, but they pressed it this pull.
        r = run("Mage", "Frost", talents=entries(ICE_BLOCK), casts=[(20_000, MIRROR)], death=100_000)
        self.assertIn("Mirror Image", names(r["cooldown"]))

    def test_charges_recover_one_at_a_time(self):
        left, ready, _ = defensives._replay([0, 1_000], [], 30_000, lambda t: (25_000, 2))
        self.assertEqual((left, ready), (1, 20_000))  # 2nd charge starts after the 1st returns

    def test_casts_reach_back_to_the_last_encounters_end(self):
        # Long cooldowns reset when an encounter ends, so a press after the last one ended carries into
        # the first kept pull: casts are read from that end (at most the longest cooldown back, Lay on
        # Hands' 10 minutes), and never less than 3 minutes back for short cooldowns.
        cat = defensives._LATEST
        self.assertEqual(cat.longest_cooldown_ms, 600_000)
        self.assertEqual(defensives.cast_lookback(cat, 1_000_000, 500_000), 500_000)
        self.assertEqual(defensives.cast_lookback(cat, 1_000_000, 0), 400_000)
        self.assertEqual(defensives.cast_lookback(cat, 1_000_000, 900_000), 820_000)
        self.assertEqual(defensives.cast_lookback(cat, 100_000, 0), 0)
        starts = {}

        def fake_paged(_tok, _code, data_type, flt, start_time=None, **_kw):
            starts[data_type] = start_time
            return []

        orig = defensives._paged
        defensives._paged = fake_paged
        try:
            defensives.fetch_defensive_raw("t", "R", [7], 1_000_000, 1_100_000, cat, combatants=[], prev_end=500_000)
        finally:
            defensives._paged = orig
        self.assertEqual((starts["Casts"], starts["Buffs"]), (500_000, 820_000))

    def test_fetch_keeps_only_dead_players_without_player_filters(self):
        # WCL returns nothing for source.id / target.id filters on Casts and
        # Buffs, so the queries must not use them; filtering happens here.
        seen = []

        def fake_paged(_tok, _code, data_type, flt, **_kw):
            seen.append(flt or "")
            if data_type == "Casts":
                return [{"type": "cast", "abilityGameID": FEINT, "sourceID": s, "timestamp": 5} for s in (1, 2)]
            if data_type == "Buffs":
                return [{"type": "applybuff", "abilityGameID": FEINT, "targetID": t, "timestamp": 5} for t in (1, 2)]
            return []

        orig = defensives._paged
        defensives._paged = fake_paged
        try:
            out = defensives.fetch_defensive_events("t", "R", [7], 0, 10, {1})
        finally:
            defensives._paged = orig
        self.assertFalse(any("source.id" in f or "target.id" in f for f in seen))
        self.assertEqual(set(out["casts"]), {1})
        self.assertEqual(set(out["buffs"]), {1})


if __name__ == "__main__":
    unittest.main()


MAX = 1_000_000
FROST, PHYS = 16, 1


def hit(ts, amount, hp_after, overkill=0, absorbed=0, ability=500, aoe=False):
    return {"timestamp": ts, "type": "damage", "targetID": 1, "abilityGameID": ability,
            "amount": amount, "absorbed": absorbed, "overkill": overkill, "isAoE": aoe,
            "hitPoints": hp_after, "maxHitPoints": MAX, "resourceActor": 2}


def ready(*sids):
    return [CATALOG[s] for s in sids]


SCHOOLS = {500: FROST, 600: PHYS}
NAMES = {500: "Frost Bolt", 600: "Cleave", 700: "Shadow Strike", 1: "Melee"}
SHIELD_WALL, ASTRAL, DIVINE_SHIELD, EXHIL = 871, 108271, 642, 109304


class SurvivalTests(unittest.TestCase):
    # hit(ts, amount, hp_after, overkill): as in WCL, `amount` is the health the
    # killing blow took (= health before it) and `overkill` the damage beyond.

    def assess(self, killing, available=(), consumables=()):
        return defensives.assess_survival([killing], 100_000, ready(*available), ready(*consumables), NAMES, SCHOOLS)

    def test_one_shot_from_full_health(self):
        # 1.3M hit on a full 1M-health player: WCL records 1M taken + 300k overkill.
        r = self.assess(hit(100_000, 1_000_000, 0, overkill=300_000), available=[SHIELD_WALL])
        self.assertEqual(r["deathType"], "oneShot")
        self.assertEqual(r["hpBeforePct"], 100)
        self.assertEqual(r["killingHit"]["pctOfMax"], 130)
        self.assertTrue(r["wouldSave"]["Shield Wall"])      # 40% of 1.3M = 520k > 300k

    def test_was_low_before_the_killing_blow(self):
        r = self.assess(hit(100_000, 150_000, 0, overkill=250_000))
        self.assertEqual(r["deathType"], "wasLow")
        self.assertEqual(r["hpBeforePct"], 15)

    def test_small_reduction_not_enough_for_huge_overkill(self):
        r = self.assess(hit(100_000, 1_000_000, 0, overkill=1_000_000), available=[DIVINE_PROTECTION])
        self.assertFalse(r["wouldSave"]["Divine Protection"])

    def test_immunity_saves_any_hit(self):
        r = self.assess(hit(100_000, 1_000_000, 0, overkill=4_000_000), available=[DIVINE_SHIELD])
        self.assertTrue(r["wouldSave"]["Divine Shield"])

    def test_heal_limited_to_missing_health(self):
        full = self.assess(hit(100_000, 1_000_000, 0, overkill=100_000), available=[EXHIL])
        self.assertFalse(full["wouldSave"]["Exhilaration"])   # nothing missing to heal
        low = self.assess(hit(100_000, 200_000, 0, overkill=100_000), available=[EXHIL])
        self.assertTrue(low["wouldSave"]["Exhilaration"])     # 30% heal > 100k overkill

    def test_magic_only_defensive_ignores_physical_hits(self):
        phys = self.assess(hit(100_000, 1_000_000, 0, overkill=200_000, ability=600), available=[CLOAK])
        self.assertFalse(phys["wouldSave"]["Cloak of Shadows"])
        magic = self.assess(hit(100_000, 1_000_000, 0, overkill=200_000, ability=500), available=[CLOAK])
        self.assertTrue(magic["wouldSave"]["Cloak of Shadows"])

    def test_combined_can_save_when_each_alone_cannot(self):
        # 1.9M hit from full, 900k overkill. Astral Shift (40%) prevents 760k and
        # Unending Resolve (25%) 475k: neither alone, but together 55% = 1.045M.
        r = self.assess(hit(100_000, 1_000_000, 0, overkill=900_000), available=[ASTRAL, UNENDING])
        self.assertFalse(r["wouldSave"]["Astral Shift"])
        self.assertFalse(r["wouldSave"]["Unending Resolve"])
        self.assertTrue(r["allTogetherWouldSave"])

    def test_unscored_ability_reports_unknown(self):
        r = self.assess(hit(100_000, 1_000_000, 0, overkill=200_000), available=[ALTER_TIME])
        self.assertIsNone(r["wouldSave"]["Alter Time"])

    def test_no_killing_blow_near_the_death(self):
        self.assertIsNone(defensives.assess_survival([hit(60_000, 900_000, 0, overkill=5)], 100_000,
                                                     [], [], NAMES, SCHOOLS))

    def talent(self, sid, name):
        """Trait entries of the talent `name` that modifies catalog ability `sid`."""
        return next(m["entries"] for c in CATALOG[sid]["mitigation"] for m in c.get("mods", ()) if m["talent"] == name)

    def test_talents_that_strengthen_a_defensive_count(self):
        # 1.8M hit from full, 800k overkill.
        kb = hit(100_000, 1_000_000, 0, overkill=800_000)
        base = defensives.assess_survival([kb], 100_000, ready(ASTRAL), [], NAMES, SCHOOLS, talent_entries={})
        self.assertFalse(base["wouldSave"]["Astral Shift"])          # 40% of 1.8M = 720k
        talented = {e: 1 for e in self.talent(ASTRAL, "Astral Bulwark")}
        r = defensives.assess_survival([kb], 100_000, ready(ASTRAL), [], NAMES, SCHOOLS, talent_entries=talented)
        self.assertTrue(r["wouldSave"]["Astral Shift"])              # 60% with Astral Bulwark

    def test_talent_rank_scales_the_bonus(self):
        entry = CATALOG[22812]   # Barkskin: Reinforced Fur +10%
        entries = self.talent(22812, "Reinforced Fur")
        comps, boosted = defensives._resolve(entry, {e: 1 for e in entries}, {})
        self.assertAlmostEqual(comps[0]["dr"], 0.30)
        self.assertEqual(boosted, ["Reinforced Fur"])
        comps, _ = defensives._resolve(entry, {e: 2 for e in entries}, {})
        self.assertAlmostEqual(comps[0]["dr"], 0.40)

    def test_elusiveness_adds_reduction_to_feint_against_single_target_hits(self):
        kb = hit(100_000, 1_000_000, 0, overkill=150_000)             # not AoE
        plain = defensives.assess_survival([kb], 100_000, ready(FEINT), [], NAMES, SCHOOLS, talent_entries={})
        self.assertFalse(plain["wouldSave"]["Feint"])
        talented = {e: 1 for e in self.talent(FEINT, "Elusiveness")}
        r = defensives.assess_survival([kb], 100_000, ready(FEINT), [], NAMES, SCHOOLS, talent_entries=talented)
        self.assertTrue(r["wouldSave"]["Feint"])                      # 20% of 1.15M = 230k

    def test_evasion_dodges_melee_only(self):
        melee = self.assess(hit(100_000, 1_000_000, 0, overkill=500_000, ability=1), available=[EVASION])
        self.assertTrue(melee["wouldSave"]["Evasion"])
        spell = self.assess(hit(100_000, 1_000_000, 0, overkill=500_000), available=[EVASION])
        self.assertFalse(spell["wouldSave"]["Evasion"])

    def test_hit_that_ignored_all_mitigation_ignores_reductions_not_shields(self):
        kb = dict(hit(100_000, 1_000_000, 0, overkill=200_000), mitigated=0, unmitigatedAmount=1_200_000)
        r = self.assess(kb, available=[SHIELD_WALL])
        self.assertFalse(r["wouldSave"]["Shield Wall"])
        self.assertTrue(r["ignoresReduction"])
        shield = defensives.assess_survival([kb], 100_000, ready(11426), [], NAMES, SCHOOLS)   # Ice Barrier
        self.assertTrue(shield["wouldSave"]["Ice Barrier"])

    def test_spells_that_pierce_immunity(self):
        from boss_spell_flags import IGNORES_IMMUNITY
        piercing = min(IGNORES_IMMUNITY)
        kb = hit(100_000, 1_000_000, 0, overkill=200_000, ability=piercing)
        r = defensives.assess_survival([kb], 100_000, ready(DIVINE_SHIELD), [], NAMES, SCHOOLS)
        self.assertFalse(r["wouldSave"]["Divine Shield"])
        self.assertTrue(r["ignoresImmunity"])

    def test_mixed_school_hits(self):
        schools = {**SCHOOLS, 700: 33}                         # shadow + physical
        kb = hit(100_000, 1_000_000, 0, overkill=200_000, ability=700)
        r = defensives.assess_survival([kb], 100_000, ready(CLOAK, 48707), [], NAMES, schools)
        self.assertFalse(r["wouldSave"]["Cloak of Shadows"])          # immunity needs every school covered
        self.assertTrue(r["wouldSave"]["Anti-Magic Shell"])           # a magic shield still soaks it

    def test_real_shield_size_from_the_log(self):
        brew = 322507                                                 # Celestial Brew: no fixed size
        kb = hit(100_000, 1_000_000, 0, overkill=200_000)
        unknown = defensives.assess_survival([kb], 100_000, ready(brew), [], NAMES, SCHOOLS)
        self.assertIsNone(unknown["wouldSave"]["Celestial Brew"])
        seen = defensives.assess_survival([kb], 100_000, ready(brew), [], NAMES, SCHOOLS,
                                          observed_absorbs={"Celestial Brew": 250_000})
        self.assertTrue(seen["wouldSave"]["Celestial Brew"])

    def test_leech_only_defensive_cannot_stop_a_hit(self):
        r = self.assess(hit(100_000, 1_000_000, 0, overkill=10_000), available=[49039])   # Lichborne
        self.assertFalse(r["wouldSave"]["Lichborne"])

    def test_unused_healthstone_only_if_carried(self):
        kb = [hit(300_000, 200_000, 0, overkill=100_000)]
        carried = defensives.analyze_death(
            1, "Mage", "Frost", 7, 200_000, 300_000,
            {"casts": {1: [(10_000, HEALTHSTONE)]}, "talents": {(7, 1): set()}},
            NAMES, {}, hits=kb, ability_schools=SCHOOLS)
        self.assertTrue(carried["survival"]["wouldSave"]["Healthstone"])
        not_carried = defensives.analyze_death(
            1, "Mage", "Frost", 7, 200_000, 300_000,
            {"casts": {}, "talents": {(7, 1): set()}},
            NAMES, {}, hits=kb, ability_schools=SCHOOLS)
        self.assertNotIn("Healthstone", not_carried["survival"]["wouldSave"])

    def test_a_warlock_in_the_pull_means_a_healthstone_from_the_soulwell(self):
        kb = [hit(300_000, 200_000, 0, overkill=100_000)]
        r = defensives.analyze_death(
            1, "Mage", "Frost", 7, 200_000, 300_000, {"casts": {}, "talents": {(7, 1): set()}},
            NAMES, {}, hits=kb, ability_schools=SCHOOLS, soulwell=True)
        self.assertTrue(r["survival"]["wouldSave"]["Healthstone"])
        self.assertTrue(r["survival"]["details"]["Healthstone"]["soulwell"])
        # One they used in this log is theirs, not the Soulwell's guess.
        r = defensives.analyze_death(
            1, "Mage", "Frost", 7, 200_000, 300_000,
            {"casts": {1: [(10_000, HEALTHSTONE)]}, "talents": {(7, 1): set()}},
            NAMES, {}, hits=kb, ability_schools=SCHOOLS, soulwell=True)
        self.assertNotIn("soulwell", r["survival"]["details"]["Healthstone"])

    def test_instant_kill_keeps_the_potion_rank(self):
        conc = next(sid for sid, d in defensives._LATEST.consumable.items()
                    if d["name"] == "Concentrated Silvermoon Health Potion")
        names_map = {**NAMES, conc: "Concentrated Silvermoon Health Potion"}
        r = defensives.analyze_death(
            1, "Mage", "Frost", 7, 200_000, 300_000,
            {"casts": {1: [(10_000, conc)]}, "talents": {(7, 1): set()},
             "heals": {1: [(10_000, conc, 440_000, 1_000_000, 1.0, 400, 3)]}},
            names_map, {}, hits=[{"timestamp": 300_000, "type": "instakill", "targetID": 1,
                                           "abilityGameID": 500}], ability_schools=SCHOOLS)
        det = r["survival"]["details"]["Concentrated Silvermoon Health Potion"]
        self.assertEqual((det["why"], det["rank"]["rank"]), ("instakill", "gold"))


DIVINE_PROTECTION, UNENDING = 498, 104773


BLUR = 198589


class PatchCatalogTests(unittest.TestCase):
    def test_report_uses_the_patch_live_when_it_was_logged(self):
        from datetime import datetime, timezone
        from defensive_catalog import PATCHES
        first_day, first_patch = PATCHES[0]
        ms = lambda d: datetime.fromisoformat(d).replace(tzinfo=timezone.utc).timestamp() * 1000
        self.assertEqual(defensives.catalog_for(ms(first_day)).patch, first_patch)
        self.assertEqual(defensives.catalog_for(ms("2099-01-01")).patch, PATCHES[-1][1])
        self.assertEqual(defensives.catalog_for(None).patch, PATCHES[-1][1])
        for day, patch in PATCHES[1:]:
            self.assertEqual(defensives.catalog_for(ms(day) + 3_600_000).patch, patch)

    def test_talent_that_adds_a_charge(self):
        mod = next(m for m in CATALOG[BLUR].get("charge_mods", ()) if m["talent"] == "Demonic Resilience")
        cast = [(90_000, BLUR)]
        plain = run("DemonHunter", "Havoc", casts=cast, talents={})
        self.assertIn("Blur", names(plain["cooldown"]))
        extra = run("DemonHunter", "Havoc", casts=cast, talents={e: 1 for e in mod["entries"]})
        self.assertIn("Blur", names(extra["available"]))

    def test_spec_passive_that_shortens_a_cooldown(self):
        brew = CATALOG[115203]     # Fortifying Brew: 6 min, 2 min for Windwalker and Mistweaver
        self.assertTrue(any(m.get("specs") == ["Windwalker"] for m in brew.get("cooldown_mods", ())))
        self.assertLess(defensives._talented_cooldown(brew, {}, "Windwalker"), brew["cooldown_ms"])
        self.assertEqual(defensives._talented_cooldown(brew, {}, "Brewmaster"), brew["cooldown_ms"])


class ConsumableEstimateTests(unittest.TestCase):
    cat = defensives.catalog_for(None)

    def test_healthstone_uses_the_players_own_share_of_max_health(self):
        heals = [(1, HEALTHSTONE, 325_000, 1_000_000, 1.3)]         # buffs don't change Healthstones
        e = defensives.consumable_estimate(HEALTHSTONE, self.cat, heals, 1.0, {}, "Frost")
        self.assertEqual(e["mitigation"], [{"heal": 0.325}])
        self.assertEqual(e["source"], "log")

    def test_healthstone_without_a_use_in_the_log_comes_from_game_data(self):
        e = defensives.consumable_estimate(HEALTHSTONE, self.cat, [], 1.0, {}, "Frost")
        self.assertEqual(e["source"], "gameData")
        self.assertAlmostEqual(e["mitigation"][0]["heal"], 0.25)

    def test_potion_takes_buffs_out_of_past_heals_and_puts_death_buffs_in(self):
        heals = [(1, POTION, 240_000, 900_000, 1.2), (2, POTION, 200_000, 900_000, 1.0),
                 (3, POTION, 200_000, 900_000, 1.0)]
        e = defensives.consumable_estimate(POTION, self.cat, heals, 1.3, {}, "Frost")
        self.assertAlmostEqual(e["mitigation"][0]["heal_amount"], 260_000)

    def test_potion_without_a_use_in_the_log_uses_the_typical_heal(self):
        e = defensives.consumable_estimate(POTION, self.cat, [], 1.0, {}, "Frost")
        self.assertEqual(e["source"], "typical")
        self.assertGreater(e["mitigation"][0]["heal_amount"], 0)

    def test_heals_are_indexed_per_player_with_the_buffs_multiplier(self):
        aura = next(iter(self.cat.heal_auras))
        out = defensives.index_defensive_events({"heals": [
            {"type": "heal", "timestamp": 5, "sourceID": 1, "targetID": 1, "abilityGameID": POTION,
             "amount": 150_000, "overheal": 50_000, "maxHitPoints": 900_000, "buffs": f"{aura}.",
             "resourceActor": 1, "versatility": 350},
            {"type": "heal", "timestamp": 6, "sourceID": 3, "targetID": 1, "abilityGameID": POTION, "amount": 9},
        ]}, self.cat)
        self.assertEqual(out["heals"][1], [(5, POTION, 200_000, 900_000, self.cat.heal_auras[aura], 350, None)])


class OlderLogTests(unittest.TestCase):
    def test_feint_is_unknown_when_the_log_does_not_mark_aoe_hits(self):
        kb = dict(hit(100_000, 1_000_000, 0, overkill=300_000), isAoE=False)   # 40% of 1.3M would save
        marked = defensives.assess_survival([kb], 100_000, ready(FEINT), [], NAMES, SCHOOLS, talent_entries={})
        self.assertFalse(marked["wouldSave"]["Feint"])                      # a single-target hit
        unmarked = defensives.assess_survival([kb], 100_000, ready(FEINT), [], NAMES, SCHOOLS, talent_entries={},
                                              aoe_known=False)
        self.assertIsNone(unmarked["wouldSave"]["Feint"])

    def test_cant_tell_gives_the_reason_it_cant_tell(self):
        # An armor increase can't be judged when an earlier hit's armor rule isn't known (Cleave: physical,
        # not measured), though it plainly doesn't reduce the Frost Bolt that killed them. The verdict is
        # "can't tell", and the reason is the earlier hit's, not "armor doesn't reduce Frost Bolt".
        hide = {"name": "Test Hide", "kind": "personal", "mitigation": [{"armor": 1.0}]}
        hits = [dict(hit(95_000, 300_000, 400_000, ability=600), armor=2_000),
                dict(hit(100_000, 400_000, 0, overkill=900_000), armor=2_000)]
        r = defensives.assess_survival(hits, 100_000, [hide], [], NAMES, SCHOOLS, talent_entries={},
                                       armor_k=2_000)
        self.assertIsNone(r["wouldSave"]["Test Hide"])
        self.assertEqual(r["details"]["Test Hide"]["why"], "armorUnknown")
        self.assertEqual(r["details"]["Test Hide"]["whyHit"], "Cleave")
        # The same on unmarked AoE: the reason says area damage isn't marked.
        kb = dict(hit(100_000, 1_000_000, 0, overkill=300_000), isAoE=False)
        r = defensives.assess_survival([kb], 100_000, ready(FEINT), [], NAMES, SCHOOLS, talent_entries={},
                                       aoe_known=False)
        self.assertEqual(r["details"]["Feint"]["why"], "aoeUnknown")
        self.assertNotIn("whyHit", r["details"]["Feint"])

    def test_armor_that_reduces_the_hit_but_whose_size_isnt_known_has_its_own_reason(self):
        # A melee swing: armor surely reduces it. Without their armor on the hit, or without the boss's
        # armor constant, how much more armor would take off can't be worked out: a reason of its own
        # (armorValueUnknown, naming what is missing), not "isn't known whether armor reduces it".
        hide = {"name": "Test Hide", "kind": "personal", "mitigation": [{"armor": 1.0}]}
        swing = hit(100_000, 400_000, 0, overkill=900_000, ability=defensives.MELEE_SWING)
        r = defensives.assess_survival([swing], 100_000, [hide], [], NAMES, SCHOOLS, talent_entries={},
                                       armor_k=2_000)
        self.assertEqual((r["details"]["Test Hide"]["why"], r["details"]["Test Hide"]["missing"]),
                         ("armorValueUnknown", "armor"))
        r = defensives.assess_survival([dict(swing, armor=2_000)], 100_000, [hide], [], NAMES, SCHOOLS,
                                       talent_entries={})
        self.assertEqual((r["details"]["Test Hide"]["why"], r["details"]["Test Hide"]["missing"]),
                         ("armorValueUnknown", "constant"))
        self.assertIsNone(r["wouldSave"]["Test Hide"])

    def test_report_marks_aoe_only_if_some_hit_is_aoe(self):
        self.assertFalse(defensives.logs_mark_aoe({1: [{"isAoE": False}], 2: [{"isAoE": False}]}))
        self.assertTrue(defensives.logs_mark_aoe({1: [{"isAoE": False}], 2: [{"isAoE": True}]}))


class AoeByAbilityTests(unittest.TestCase):
    # Live 2026-10-08: WCL marks isAoE only on hits that dealt damage. A hit an absorb took whole (amount 0,
    # no health on it), an immune or a missed one is never marked, even of an ability marked AoE on every
    # other hit (Uncontrolled Burn: 31,127 of 41,277 marked, every unmarked one amount 0). The game treats
    # those as AoE: Feint took 0.400 off 54 such hits on Maar (Undermine, 11.1.7) and 10 on Esra
    # (Manaforge Omega), as off the marked ones, and 0.000 off hits of abilities
    # never marked. Every hit that dealt damage of one ability is marked alike (Undermine, Manaforge
    # Omega, Nerub-ar Palace, Voidspire, Coiled Altar logs). An ability is AoE when any hit of it is.
    def absorbed(self, ts, ability, absorbed):
        return {"timestamp": ts, "type": "damage", "targetID": 1, "abilityGameID": ability, "amount": 0,
                "absorbed": absorbed, "overkill": 0, "isAoE": False}

    def test_a_hit_absorbed_whole_counts_as_aoe_when_its_ability_is(self):
        # A Cleave takes them to half health; a 500k hit of ability 500 is absorbed whole; then ability 500
        # kills them with 500k overkill. Feint (40% off AoE) takes 400k off the killing blow alone (not
        # enough), and 200k more off the absorbed hit when ability 500 counts as AoE (enough).
        window = [hit(97_000, 500_000, 500_000, ability=600), self.absorbed(99_000, 500, 500_000),
                  hit(100_000, 500_000, 0, overkill=500_000, aoe=True)]
        args = (window, 100_000, ready(FEINT), [], NAMES, SCHOOLS)
        by_hit = defensives.assess_survival(*args, talent_entries={})
        self.assertFalse(by_hit["wouldSave"]["Feint"])
        by_ability = defensives.assess_survival(*args, talent_entries={}, aoe_abilities={500})
        self.assertTrue(by_ability["wouldSave"]["Feint"])
        self.assertEqual(by_ability["details"]["Feint"]["amount"], 600_000)
        # Its status unknown (the extra fetch failed): the verdict can't be told.
        unknown = defensives.assess_survival(*args, talent_entries={}, aoe_abilities=set(), aoe_unknown={500})
        self.assertIsNone(unknown["wouldSave"]["Feint"])
        # Known not AoE (an ability never marked, whose hits the report could tell): as by hit.
        never = defensives.assess_survival(*args, talent_entries={}, aoe_abilities=set())
        self.assertFalse(never["wouldSave"]["Feint"])

    def test_school_applies_reads_the_abilitys_status(self):
        h = {"abilityGameID": 500, "isAoE": False}
        self.assertFalse(defensives._school_applies("aoe", h, {}))
        self.assertTrue(defensives._school_applies("aoe", dict(h, aoeAbility=True), {}))
        self.assertIsNone(defensives._school_applies("aoe", dict(h, aoeAbility=None), {}))
        self.assertFalse(defensives._school_applies("aoe", dict(h, aoeAbility=False, isAoE=False), {}))
        # A report that marks no hit at all: unknown, whatever else is on the hit.
        self.assertIsNone(defensives._school_applies("aoe", dict(h, aoeKnown=False, aoeAbility=True), {}))

    def test_status_from_the_windows_and_what_they_cannot_tell(self):
        dealt = lambda a, aoe: {"type": "damage", "abilityGameID": a, "amount": 5, "isAoE": aoe}
        none = lambda a: {"type": "damage", "abilityGameID": a, "amount": 0, "absorbed": 9, "isAoE": False}
        windows = {1: [dealt(10, True), none(10), none(20), none(30), {"type": "instakill", "abilityGameID": 40}],
                   2: [dealt(30, False), none(50)]}
        self.assertEqual(defensives.aoe_abilities(windows), {10})
        # 10 is marked; 30 dealt damage unmarked (not AoE); 20 only absorbed whole: can't tell. Only the
        # given players' hits are asked about (50 is player 2's).
        self.assertEqual(defensives.aoe_undecided(windows, [1], {10}), {20})
        self.assertEqual(defensives.aoe_undecided(windows, [1, 2], {10}), {20, 50})

    def test_fetch_reads_the_abilities_hits_in_the_reports_pulls(self):
        from unittest import mock
        # 20 is marked on a hit that dealt damage; 50 dealt damage unmarked; 60 was only ever absorbed
        # whole (WCL never marks those, so it stays unknown, not single-target), even on a hit marked.
        page = {"reportData": {"report": {"a": {"data": [
            {"type": "damage", "abilityGameID": 20, "amount": 5, "isAoE": True},
            {"type": "damage", "abilityGameID": 50, "amount": 5, "isAoE": False},
            {"type": "damage", "abilityGameID": 60, "amount": 0, "absorbed": 9, "isAoE": True}],
            "nextPageTimestamp": None}}}}
        with mock.patch.object(defensives, "graphql_query", return_value=page) as q:
            self.assertEqual(defensives.fetch_aoe_abilities("t", "R", [3, 4], 100, 900, {50, 20, 60}),
                             ({20}, {20, 50}))
        query = q.call_args[0][1]
        self.assertIn("dataType: DamageTaken", query)
        self.assertIn("fightIDs: [3, 4]", query)
        self.assertIn("endTime: 901", query)
        self.assertIn('ability.id in (20, 50, 60)', query)
        self.assertNotIn("includeResources", query)

    def test_fetch_stops_once_every_ability_is_decided(self):
        from unittest import mock
        first = {"reportData": {"report": {"a": {"data": [
            {"type": "damage", "abilityGameID": 20, "amount": 5, "isAoE": True}], "nextPageTimestamp": 500}}}}
        second = {"reportData": {"report": {"a": {"data": [
            {"type": "damage", "abilityGameID": 50, "amount": 5, "isAoE": False}], "nextPageTimestamp": 700}}}}
        import copy
        pages = lambda *ps: [copy.deepcopy(p) for p in ps]
        with mock.patch.object(defensives, "graphql_query", side_effect=pages(first, second)) as q:
            self.assertEqual(defensives.fetch_aoe_abilities("t", "R", [3], 100, 900, {20}), ({20}, {20}))
        self.assertEqual(q.call_count, 1)
        with mock.patch.object(defensives, "graphql_query", side_effect=pages(first, second, first)) as q:
            self.assertEqual(defensives.fetch_aoe_abilities("t", "R", [3], 100, 900, {20, 50}), ({20}, {20, 50}))
        self.assertEqual(q.call_count, 2)

    def test_a_hit_that_dealt_damage_keeps_its_own_mark(self):
        # Only hits that dealt no damage take their ability's status; a hit that dealt damage carries
        # WCL's own mark (every one of an ability marked alike on the logs tried; the safer rule).
        kb = hit(100_000, 1_000_000, 0, overkill=300_000, aoe=False)        # 40% of 1.3M would save
        r = defensives.assess_survival([kb], 100_000, ready(FEINT), [], NAMES, SCHOOLS, talent_entries={},
                                       aoe_abilities={500})
        self.assertFalse(r["wouldSave"]["Feint"])
        r = defensives.assess_survival([dict(kb, isAoE=True)], 100_000, ready(FEINT), [], NAMES, SCHOOLS,
                                       talent_entries={}, aoe_abilities=set(), aoe_unknown={500})
        self.assertTrue(r["wouldSave"]["Feint"])

    def test_classes_with_an_aoe_only_effect(self):
        self.assertEqual(defensives.aoe_classes(defensives._CATALOGS["12.1.0"]), {"Rogue"})
        self.assertEqual(defensives.aoe_classes(defensives._CATALOGS["11.1.7"]), {"Rogue"})
        # Merely a Setback (11.x: 5% avoidance, an AoE-only cut, while Prismatic or Blazing Barrier is up)
        # as a talent component on a Mage barrier brings Mages in; an external would reach anyone.
        from types import SimpleNamespace
        setback = {"dr": 0.05, "school": "aoe", "needs": {"entries": [117252], "talent": "Merely a Setback"}}
        cat = SimpleNamespace(all={1966: CATALOG[FEINT],
                                   235450: {"name": "Prismatic Barrier", "kind": "personal", "class": "Mage",
                                            "mitigation": [{"absorb": 0.3}, setback]}})
        self.assertEqual(defensives.aoe_classes(cat), {"Rogue", "Mage"})
        cat.all[1] = {"name": "Shared", "kind": "external", "class": "Priest", "mitigation": [setback]}
        self.assertIsNone(defensives.aoe_classes(cat))


class StandardPotionTests(unittest.TestCase):
    def test_potion_without_a_typical_heal_uses_the_tiers_standard_potion(self):
        cat = defensives.catalog_for(1_756_857_344_578)                      # Manaforge Omega, 11.2.0
        delight = next(sid for sid, d in cat.consumable.items() if d["name"] == "Cavedweller's Delight")
        e = defensives.consumable_estimate(delight, cat, [], 1.0, {}, "Frost")
        standard = cat.all[cat.standard_potion]
        self.assertEqual(standard["name"], "Invigorating Healing Potion")
        self.assertEqual(e["mitigation"][0]["heal_amount"], standard["mitigation"][0]["heal_amount"])


class ExplainTests(unittest.TestCase):
    """The numbers and reasons sent with each verdict, for the results page tooltips."""

    def details(self, killing, *available, talent_entries=None, schools=SCHOOLS):
        r = defensives.assess_survival([killing], 100_000, ready(*available), [], NAMES, schools,
                                       talent_entries=talent_entries)
        return r["details"]

    def test_amount_prevented_against_the_killing_blow(self):
        # 1.3M hit from full: Shield Wall's 40% prevents 520k, 300k overkill.
        d = self.details(hit(100_000, 1_000_000, 0, overkill=300_000), SHIELD_WALL)["Shield Wall"]
        self.assertEqual(d["amount"], 520_000)
        self.assertNotIn("why", d)
        self.assertNotIn("effect", d)          # no talents: the general effect is sent once per result

    def test_reason_when_it_prevents_nothing(self):
        d = self.details(hit(100_000, 1_000_000, 0, overkill=200_000, ability=600), CLOAK)["Cloak of Shadows"]
        self.assertEqual((d["amount"], d["why"], d["school"]), (0, "school", "magic"))
        d = self.details(hit(100_000, 1_000_000, 0, overkill=100_000), EXHIL)["Exhilaration"]
        self.assertEqual(d["why"], "fullHealth")
        from boss_spell_flags import IGNORES_IMMUNITY
        piercing = min(IGNORES_IMMUNITY)
        d = self.details(hit(100_000, 1_000_000, 0, overkill=200_000, ability=piercing), DIVINE_SHIELD,
                         schools={piercing: FROST})["Divine Shield"]
        self.assertEqual(d["why"], "pierces")
        kb = dict(hit(100_000, 1_000_000, 0, overkill=200_000), mitigated=0, unmitigatedAmount=1_200_000)
        self.assertEqual(self.details(kb, SHIELD_WALL)["Shield Wall"]["why"], "noReduction")

    def test_talent_changes_are_listed(self):
        talented = {e: 1 for e in SurvivalTests.talent(None, ASTRAL, "Astral Bulwark")}
        d = self.details(hit(100_000, 1_000_000, 0, overkill=800_000), ASTRAL, talent_entries=talented)["Astral Shift"]
        self.assertEqual([t["talent"] for t in d["talents"]], ["Astral Bulwark"])
        self.assertAlmostEqual(d["effect"][0]["dr"], 0.6)
        self.assertEqual(d["amount"], 1_080_000)             # 60% of 1.8M


class ResultsPageInfoTests(unittest.TestCase):
    def test_every_catalog_ability_has_an_icon(self):
        from spell_icons import ICONS
        names = {d["name"] for cat in defensives.CATALOGS.values() for d in cat.values()}
        self.assertEqual(names - set(ICONS), set())

    def test_icon_names(self):
        self.assertEqual(defensives.icon_name("Cloak of Shadows"), "spell_shadow_nethercloak")
        # Boss abilities use the report's icon; WCL writes "-" where the file name has a space.
        self.assertEqual(defensives.icon_name("Gravebound", {"Gravebound": "ability_demonhunter_shatteredsouls.jpg"}),
                         "ability_demonhunter_shatteredsouls")
        self.assertEqual(defensives.icon_name("X", {"X": "warlock_-healthstone.jpg"}), "warlock_healthstone")
        self.assertIsNone(defensives.icon_name("Unknown", {}))

    def test_ability_info(self):
        info = defensives.ability_info(defensives._LATEST, "Cloak of Shadows")
        self.assertEqual(info["effect"], [{"immune": True, "school": "magic"}])
        self.assertEqual((info["cooldownMs"], info["auraMs"]), (120_000, 5_000))
        self.assertIsNone(defensives.ability_info(defensives._LATEST, "Not A Spell"))
        # Externals carry no effect numbers in the catalog; their game description explains them.
        self.assertIn("20%", defensives.ability_info(defensives._LATEST, "Ironbark")["description"])


class InstakillTests(unittest.TestCase):
    """A mechanic that kills outright (Eternal Venom at max stacks) deals no damage."""

    def instakill(self, ts=99_990):
        return {"timestamp": ts, "type": "instakill", "targetID": 1, "abilityGameID": 1292348, "fight": 31}

    def test_instant_kills_are_indexed_with_the_hits(self):
        idx = defensives.index_hits([self.instakill(), hit(50_000, 100, 0, overkill=10)])
        self.assertEqual([e["type"] for e in idx[1]], ["damage", "instakill"])

    def test_nothing_saves_from_an_instant_kill(self):
        r = defensives.assess_survival([self.instakill()], 100_000, ready(DIVINE_SHIELD, SHIELD_WALL), [],
                                       {1292348: "Eternal Venom"}, SCHOOLS)
        self.assertEqual(r["deathType"], "instakill")
        self.assertEqual(r["killingHit"]["name"], "Eternal Venom")
        self.assertEqual(r["wouldSave"], {"Divine Shield": False, "Shield Wall": False})
        self.assertEqual(r["details"]["Shield Wall"]["why"], "instakill")
        self.assertFalse(r["allTogetherWouldSave"])


class HealOverTimeTests(unittest.TestCase):
    """Frenzied Regeneration / Crimson Vial heal over their duration, not at once."""

    def test_tick_counts_match_the_catalog_build(self):
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "scripts"))
        import build_defensive_catalog as build
        ticks = {n: e[3] for n, effs in build.EFFECTS.items() for e in effs
                 if len(e) > 3 and isinstance(e[3], int) and e[3] > 1}
        self.assertEqual(ticks, defensives.HEAL_OVER_TIME)

    frenzied = next(sid for sid, d in CATALOG.items() if d["name"] == "Frenzied Regeneration")

    def assess(self, hits, ready_since=None):
        return defensives.assess_survival(hits, 100_000, ready(self.frenzied), [], NAMES, SCHOOLS,
                                          aura_ms={"Frenzied Regeneration": 3_000}, ready_since=ready_since)

    def test_ticks_land_while_they_are_low(self):
        # Low for five seconds, then killed: 24% of 1M over 3 ticks lands in full (240k > 200k overkill).
        r = self.assess([hit(95_000, 700_000, 300_000), hit(100_000, 300_000, 0, overkill=200_000)])
        self.assertTrue(r["wouldSave"]["Frenzied Regeneration"])
        self.assertEqual(r["details"]["Frenzied Regeneration"]["hot"]["ticks"], 3)
        self.assertAlmostEqual(r["details"]["Frenzied Regeneration"]["amount"], 240_000, delta=1)

    def test_real_heals_topping_them_up_waste_the_extra(self):
        # Low when it would tick, but a healer brought them back to full before they were hit from full.
        r = self.assess([hit(95_000, 700_000, 300_000), hit(99_500, 10_000, 990_000),
                         hit(100_000, 990_000, 0, overkill=50_000)])
        self.assertFalse(r["wouldSave"]["Frenzied Regeneration"])
        self.assertLessEqual(r["details"]["Frenzied Regeneration"]["amount"], 10_000)

    def test_cannot_press_before_it_was_ready(self):
        # Off cooldown 1.5s before the killing blow: only the first tick lands in time.
        r = self.assess([hit(90_000, 900_000, 100_000), hit(100_000, 100_000, 0, overkill=150_000)],
                        ready_since={"Frenzied Regeneration": 98_500})
        self.assertEqual(r["details"]["Frenzied Regeneration"]["hot"]["ticks"], 1)
        self.assertAlmostEqual(r["details"]["Frenzied Regeneration"]["amount"], 80_000, delta=1)
        self.assertFalse(r["wouldSave"]["Frenzied Regeneration"])

    def test_ready_since(self):
        # One charge, 36s cooldown, pressed at 10s: ready again at 46s.
        one = lambda t: (36_000, 1)
        self.assertEqual(defensives._replay([10_000], [], 100_000, one)[2], 46_000)
        self.assertIsNone(defensives._replay([], [], 100_000, one)[2])

class PullSpecTests(unittest.TestCase):
    def test_spec_comes_from_each_pulls_record(self):
        idx = defensives.index_defensive_events({"combatants": [
            {"fight": 3, "sourceID": 1, "specID": 266, "talentTree": []},
            {"fight": 4, "sourceID": 1, "specID": 267, "talentTree": []}]})
        self.assertEqual(defensives.pull_spec(idx, 3, 1, "Demonology"), "Demonology")
        self.assertEqual(defensives.pull_spec(idx, 4, 1, "Demonology"), "Destruction")
        self.assertEqual(defensives.pull_spec(idx, 5, 1, "Demonology"), "Demonology")   # not recorded

    def test_spec_names_match_the_catalog(self):
        from defensive_catalog import CATALOGS
        used = {s for c in CATALOGS.values() for d in c.values() for s in d.get("specs") or ()}
        self.assertLessEqual(used, set(defensives.SPEC_NAMES.values()))


class DurationTalentTests(unittest.TestCase):
    """Talents that lengthen a defensive, checked on live Midnight logs (players' own uses)."""

    def entry(self, name):
        return next(d for d in defensives._LATEST.all.values() if d["name"] == name)

    def with_talent(self, name, talent):
        e = self.entry(name)
        mod = next(m for m in e["duration_mods"] if m["talent"] == talent)
        loadout = {x: 1 for x in mod["entries"]}
        # Loadouts are trimmed to the talents the catalog uses: these must survive that.
        self.assertTrue(set(loadout) <= defensives._LATEST.relevant_talent_entries)
        return defensives._talented_duration(e, loadout, None)

    def test_anti_magic_barrier(self):
        self.assertEqual(defensives._talented_duration(self.entry("Anti-Magic Shell"), {}, None), 5_000)
        self.assertAlmostEqual(self.with_talent("Anti-Magic Shell", "Anti-Magic Barrier"), 7_000)

    def test_improved_barkskin(self):
        self.assertEqual(self.with_talent("Barkskin", "Improved Barkskin"), 12_000)

    def test_renewing_blaze_is_a_button_only_in_the_war_within(self):
        # Since Midnight (12.0.0) it's a passive on Obsidian Scales: no casts in Midnight logs.
        for patch, cat in defensives._CATALOGS.items():
            self.assertEqual("Renewing Blaze" in cat.name_to_id, patch.startswith("11."), patch)

    def test_renewing_blaze_window_is_its_own_aura(self):
        # The 8s window is 374348; Foci of Life shortens only the heal-back after it (374349).
        e = defensives._CATALOGS["11.2.7"].all[374348]
        self.assertEqual(e["aura_ms"], 8_000)
        self.assertNotIn("Foci of Life", [m["talent"] for m in e["duration_mods"]])
        # Augmentation's mastery stretches it by the player's mastery stat: listed, not added.
        mastery = next(m for m in e["duration_mods"] if m["talent"] == "Mastery: Timewalker")
        self.assertEqual((mastery["specs"], mastery["mastery"]), (["Augmentation"], True))
        self.assertEqual(defensives._talented_duration(e, {}, "Augmentation"), 8_000)


class CheckDurationsTests(unittest.TestCase):
    """checks/source_durations.py: a press while the aura is up restarts it (pandemic carry-over)."""

    def test_refresh_keeps_up_to_thirty_percent_of_the_time_left(self):
        from checks.source_durations import carried_over
        self.assertEqual(carried_over([0], 3_000), 0)
        # Frenzied Regeneration pressed again 1.2s in: 1.8s left, 0.9s kept (seen: 3.8s after the press).
        self.assertAlmostEqual(carried_over([0, 1_200], 3_000), 900)
        self.assertAlmostEqual(carried_over([0, 2_600], 3_000), 400)
        self.assertEqual(carried_over([0, 5_000], 3_000), 0)


class LethalWindowTests(unittest.TestCase):
    """The seconds before a death are replayed, not just the killing blow."""

    def assess(self, hits, available=(), consumables=(), **kw):
        durations = {CATALOG[s]["name"]: CATALOG[s].get("aura_ms") for s in available}
        return defensives.assess_survival(hits, 100_000, ready(*available), ready(*consumables), NAMES, SCHOOLS,
                                          aura_ms=durations, **kw)

    def test_reduction_counts_on_the_big_hit_before_a_finishing_tick(self):
        # Full health, a 900k hit leaves them at 100k, then a 180k tick kills (80k overkill).
        # Shield Wall on the tick alone saves 72k (not enough); pressed before the big hit, 432k.
        hits = [hit(98_000, 900_000, 100_000), hit(100_000, 100_000, 0, overkill=80_000)]
        r = self.assess(hits, available=[SHIELD_WALL])
        self.assertTrue(r["wouldSave"]["Shield Wall"])
        self.assertAlmostEqual(r["details"]["Shield Wall"]["amount"], 0.4 * 1_080_000, delta=1)
        self.assertEqual(r["details"]["Shield Wall"]["pressAgo"], 2.0)
        self.assertEqual(r["killingHit"]["pctOfMax"], 18)
        self.assertEqual(r["biggestHit"]["pctOfMax"], 90)
        self.assertEqual(r["biggestHit"]["ago"], 2.0)
        self.assertEqual(r["deathType"], "wasLow")           # two seconds at 10% before the tick

    def test_set_up_hit_is_the_biggest_since_they_were_last_high(self):
        # A big hit healed back to full long before doesn't count; the one after it does.
        hits = [hit(86_000, 600_000, 400_000, ability=600), hit(90_000, 10_000, 990_000),
                hit(97_000, 500_000, 490_000), hit(100_000, 490_000, 0, overkill=50_000)]
        r = self.assess(hits)
        self.assertEqual((r["biggestHit"]["name"], r["biggestHit"]["pctOfMax"], r["biggestHit"]["ago"]),
                         ("Frost Bolt", 50, 3.0))
        # Healed to full, then one-shot: no set-up hit.
        r = self.assess([hit(90_000, 600_000, 400_000), hit(99_000, 10_000, 990_000),
                         hit(100_000, 990_000, 0, overkill=50_000)])
        self.assertNotIn("biggestHit", r)

    def test_rot_is_named_instead_of_a_set_up_hit(self):
        # Ticks of one ability wear them down from full: rot, no set-up hit.
        ticks = [hit(93_000 + 1_000 * k, 150_000, 850_000 - 150_000 * k) for k in range(6)]
        wide = __import__("unittest.mock").mock.patch.dict(defensives.RAID_WIDE, {500: 1.0})
        with wide:
            r = self.assess(ticks + [hit(100_000, 100_000, 0, overkill=40_000)])
        self.assertEqual((r["rot"]["name"], r["rot"]["hits"]), ("Frost Bolt", 6))   # after the first they were still at 85%
        self.assertNotIn("biggestHit", r)
        # The same hits from an ability that isn't raid-wide (a soak they kept taking): no rot,
        # set up by its biggest hit, with how often it hit them.
        r = self.assess(ticks + [hit(100_000, 100_000, 0, overkill=40_000)])
        self.assertNotIn("rot", r)
        self.assertEqual((r["biggestHit"]["times"], r["biggestHit"]["over"]), (6, 6.0))
        # Three hits within a second from full health: a burst (no hit was 80% of their health), not rot.
        r = self.assess([hit(99_200, 300_000, 700_000), hit(99_500, 300_000, 400_000),
                         hit(99_900, 400_000, 0, overkill=40_000)])
        self.assertEqual(r["deathType"], "burst")
        self.assertEqual((r["burst"]["hits"], r["burst"]["total"], r["burst"]["abilities"][0]["times"]),
                         (3, 1_040_000, 3))
        self.assertNotIn("rot", r)
        self.assertNotIn("biggestHit", r)                          # "Set up by" is only for neither
        # One 90% hit and a tick right after it: a one-shot by the 90% hit, not "set up by" it.
        r = self.assess([hit(99_200, 900_000, 100_000), hit(99_900, 100_000, 0, overkill=40_000)])
        self.assertEqual(r["deathType"], "oneShot")
        self.assertNotIn("biggestHit", r)
        self.assertEqual((r["oneShotHit"]["name"], r["oneShotHit"]["pctOfMax"], r["oneShotHit"]["ago"]),
                         ("Frost Bolt", 90, 0.7))
        # A small tick, then a 120% killing blow: a one-shot by the killing blow itself.
        r = self.assess([hit(99_600, 100_000, 900_000), hit(99_900, 900_000, 0, overkill=300_000)])
        self.assertEqual(r["deathType"], "oneShot")
        self.assertNotIn("biggestHit", r)
        self.assertNotIn("oneShotHit", r)
        # Live (Chazh, Voidspire pull 66): Melee for 92% of max health, then a Judgment of 81% kills
        # 0.4s later. The biggest 80%+ hit is named; the killing blow has its own row.
        r = self.assess([hit(99_600, 920_000, 76_000, ability=1), hit(100_000, 76_000, 0, overkill=734_000)])
        self.assertEqual(r["deathType"], "oneShot")
        self.assertNotIn("biggestHit", r)
        self.assertEqual((r["oneShotHit"]["name"], r["oneShotHit"]["pctOfMax"]), ("Melee", 92))
        # Two 80%+ hits and the killing blow is the bigger one: nothing more to name.
        r = self.assess([hit(99_600, 820_000, 176_000, ability=1), hit(100_000, 176_000, 0, overkill=724_000)])
        self.assertEqual(r["deathType"], "oneShot")
        self.assertNotIn("oneShotHit", r)

    def test_one_shot_and_burst_need_high_health_within_a_second_and_a_half(self):
        # Owner's rule (2026-10-08): high health no more than 1.5s before the killing blow.
        # The press cutoff (REACTION_MS) stays at 1s.
        self.assertEqual((defensives.BURST_WINDOW_MS, defensives.REACTION_MS), (1_500, 1_000))
        def at(high_ts):
            return self.assess([hit(high_ts, 10_000, 900_000), hit(99_500, 200_000, 600_000),
                                hit(100_000, 600_000, 0, overkill=10_000)])
        self.assertEqual(at(98_500)["deathType"], "burst")         # exactly 1.5s: inclusive
        self.assertEqual(at(98_501)["deathType"], "burst")         # 1.499s
        self.assertEqual(at(98_499)["deathType"], "wasLow")        # 1.501s
        r = at(98_800)                                             # 1.2s: a burst now, wasLow under 1s
        self.assertEqual((r["deathType"], r["burstMs"]), ("burst", 1200))
        self.assertNotIn("biggestHit", r)
        # One big chunk among them: a set-up hit, not rot.
        r = self.assess([hit(96_000, 600_000, 400_000), hit(98_000, 150_000, 250_000),
                         hit(100_000, 250_000, 0, overkill=40_000)])
        self.assertNotIn("rot", r)
        self.assertEqual(r["biggestHit"]["pctOfMax"], 60)

    def test_heals_need_time_to_react(self):
        # The big hit and the tick 50ms apart: no time to heal in between, and at full health before.
        fast = self.assess([hit(99_900, 900_000, 100_000), hit(99_950, 100_000, 0, overkill=50_000)],
                           available=[EXHIL])
        self.assertFalse(fast["wouldSave"]["Exhilaration"])
        self.assertEqual(fast["details"]["Exhilaration"]["why"], "tooFast")
        self.assertEqual(fast["deathType"], "oneShot")       # full health a moment before
        self.assertEqual(fast["fromPct"], 100)
        # Two seconds between them: pressing it after the big hit heals 300k.
        slow = self.assess([hit(97_950, 900_000, 100_000), hit(99_950, 100_000, 0, overkill=50_000)],
                           available=[EXHIL])
        self.assertTrue(slow["wouldSave"]["Exhilaration"])

    def test_one_shot_needs_a_press_before_the_hit(self):
        # Nothing before the killing blow: Shield Wall still counts, pressed a second before it.
        r = self.assess([hit(100_000, 1_000_000, 0, overkill=300_000)], available=[SHIELD_WALL])
        self.assertTrue(r["wouldSave"]["Shield Wall"])
        self.assertEqual(r["details"]["Shield Wall"]["pressAgo"], 1.0)

    def test_damage_prevented_early_is_lost_when_healers_top_them_up(self):
        # A hit at 91s, healed back to full by 95s, then a 1.69M hit from full kills by 700k.
        # Shield Wall lasts 8s: pressed for the first hit it's gone by the killing blow, and what it
        # saved then was healed over anyway; pressed for the killing blow (and the 10k hit at 95s,
        # 4k of which they keep: they were 10k short of full) it saves 680k: not enough.
        hits = [hit(91_000, 300_000, 700_000), hit(95_000, 10_000, 990_000),
                hit(100_000, 990_000, 0, overkill=700_000)]
        r = self.assess(hits, available=[SHIELD_WALL])
        self.assertFalse(r["wouldSave"]["Shield Wall"])
        self.assertAlmostEqual(r["details"]["Shield Wall"]["amount"], 0.4 * 1_690_000 + 4_000, delta=1)

    def test_window_query_keeps_accented_names(self):
        # WCL matches names as written in the log: an escaped "\\u00e9" matches nobody.
        seen = []
        with __import__("unittest.mock").mock.patch.object(defensives, "graphql_query",
                                                            side_effect=lambda t, q, v: seen.append(q) or {}):
            defensives.fetch_death_windows("t", "R", [(3, [(50_000, "Icéblade")])])
        self.assertIn('target.name in (\\"Icéblade\\")', seen[0])
        self.assertIn("endTime: 50051", seen[0])          # a killing blow logged just after the death

    def test_nearby_pulls_share_a_block_and_only_death_windows_are_kept(self):
        queries = []

        def fake(token, q, v):
            queries.append(q)
            ev = lambda ts: {"timestamp": ts, "type": "damage", "targetID": 1, "amount": 1, "hitPoints": 5,
                             "maxHitPoints": 10, "resourceActor": 2}
            return {"reportData": {"report": {a: {"data": [ev(55_000), ev(80_000), ev(120_000)]}
                                              for a in __import__("re").findall(r"(p\d+): events", q)}}}
        with __import__("unittest.mock").mock.patch.object(defensives, "graphql_query", side_effect=fake):
            hits = defensives.fetch_death_windows("t", "R", [
                (3, [(60_000, "A")]), (4, [(300_000, "B")]),           # 4 minutes apart: one block
                (9, [(60_000 + 2 * defensives.WINDOW_BLOCK_SPAN_MS, "C")])])   # far later: its own
        self.assertEqual(len(queries), 1)
        self.assertIn("fightIDs: [3, 4]", queries[0])
        self.assertIn("fightIDs: [9]", queries[0])
        # 55s is in A's window; 80s and 120s are between deaths (not kept).
        self.assertEqual([h["timestamp"] for h in hits[1]], [55_000, 55_000])

    def test_window_request_reads_the_heals_a_killing_hit_sets_off(self):
        # One more block over all the pulls (All stream) on the players who died: only the killing-hit heals
        # (features.KILLING_HIT_HEALS) and their absorbs, and stacking max-health auras' stack changes.
        queries = []

        def fake(token, q, v):
            queries.append(q)
            dmg = {"timestamp": 59_990, "type": "damage", "targetID": 1, "amount": 5, "overkill": 1,
                   "hitPoints": 0, "maxHitPoints": 10, "resourceActor": 2}
            heal = {"timestamp": 59_989, "type": "heal", "targetID": 1, "abilityGameID": 404381, "amount": 3,
                    "sourceID": 9, "overheal": 0}
            late = dict(heal, timestamp=200_000)
            report = {a: {"data": [dmg]} for a in __import__("re").findall(r"(p\d+): events", q)}
            stack = {"timestamp": 59_000, "type": "removebuffstack", "targetID": 1, "abilityGameID": 389539,
                     "stack": 4, "sourceID": 1}
            report["extras"] = {"data": [heal, late, stack]}
            return {"reportData": {"report": report}}
        with __import__("unittest.mock").mock.patch.object(defensives, "graphql_query", side_effect=fake):
            hits = defensives.fetch_death_windows("t", "R", [(3, [(60_000, "A")])])
        self.assertEqual(len(queries), 1)
        self.assertIn("extras: events(fightIDs: [3]", queries[0])
        self.assertIn("dataType: All", queries[0])
        self.assertIn("389539", queries[0])                 # Sentinel's stacks
        self.assertIn("195181", queries[0])                 # Bone Shield's charges (Foul Bulwark fills it)
        self.assertIn("97463", queries[0])                  # Rallying Cry: who cast it
        self.assertIn("47788", queries[0])                  # Guardian Spirit's aura, removed as it heals
        self.assertIn("404381", queries[0])
        self.assertIn("209258", queries[0])
        self.assertEqual([(h["type"], h["timestamp"]) for h in hits[1]],
                         [("removebuffstack", 59_000), ("heal", 59_989), ("damage", 59_990)])
        self.assertEqual(hits[1][0]["stack"], 4)
        self.assertNotIn("overheal", hits[1][0])
        with __import__("unittest.mock").mock.patch.object(defensives, "graphql_query", side_effect=fake):
            self.assertEqual([h["type"] for h in defensives.fetch_death_windows("t", "R", [(3, [(60_000, "A")])],
                                                                                 heals=False)[1]], ["damage"])

    def test_identical_hits_at_the_same_moment_all_count(self):
        # Two droplets soaked in the same millisecond for the same amount are two hits.
        same = [hit(99_978, 301_233, 698_767), hit(99_978, 301_233, 397_534)]      # from full health
        merged = defensives.merge_hits({1: same}, {1: [hit(99_999, 397_534, 0, overkill=100_000)]})
        self.assertEqual(len(merged[1]), 3)
        r = self.assess(merged[1])
        self.assertEqual((r["deathType"], r["burst"]["hits"]), ("burst", 3))

    def test_ready_too_late(self):
        r = self.assess([hit(100_000, 1_000_000, 0, overkill=300_000)], available=[SHIELD_WALL],
                        ready_since={"Shield Wall": 99_500})
        self.assertFalse(r["wouldSave"]["Shield Wall"])
        self.assertEqual(r["details"]["Shield Wall"]["why"], "readyTooLate")

    def test_an_earlier_death_cuts_the_window(self):
        # Died at 92s, battle-rezzed, then one-shot at 100s: the hits of the first life don't count.
        hits = [hit(91_000, 800_000, 200_000), hit(92_000, 200_000, 0, overkill=10_000),
                hit(100_000, 1_000_000, 0, overkill=900_000)]
        r = self.assess(hits)
        self.assertEqual(r["window"]["hits"], 1)
        self.assertNotIn("biggestHit", r)

    def test_shield_soaks_the_hits_after_it_is_pressed(self):
        # Ice Barrier's shield, pressed before two hits, soaks both until it runs out.
        hits = [hit(98_000, 100_000, 300_000), hit(100_000, 300_000, 0, overkill=150_000)]
        r = defensives.assess_survival(hits, 100_000, ready(11426), [], NAMES, SCHOOLS,
                                       aura_ms={"Ice Barrier": 60_000})
        shield = r["details"]["Ice Barrier"]["amount"]
        self.assertGreater(shield, 0)
        self.assertEqual(r["wouldSave"]["Ice Barrier"], shield > 150_000)


class TalentEffectTests(unittest.TestCase):
    """Effects talents add to a button, and the health / armor rules they rely on."""
    tww = defensives.catalog_for(1_740_000_000_000)          # 2025-02-19: The War Within, 11.0.7/11.1

    def by_name(self, cat, name):
        return next(d for d in cat.all.values() if d["name"] == name)

    def talented(self, cat, name, talent):
        entry = self.by_name(cat, name)
        comp = next(c for c in entry["mitigation"] if (c.get("needs") or {}).get("talent") == talent
                    or talent in [m["talent"] for m in c.get("mods", ())])
        return {e: 1 for e in (comp.get("needs") or next(m for m in comp["mods"] if m["talent"] == talent))["entries"]}

    def test_fade_reduces_damage_only_with_translucent_image(self):
        fade = self.by_name(defensives._LATEST, "Fade")
        self.assertEqual(defensives._resolve(fade, {}, {})[0], [])
        comps, boosted = defensives._resolve(fade, self.talented(defensives._LATEST, "Fade", "Translucent Image"), {})
        self.assertEqual([c["dr"] for c in comps], [0.1])
        self.assertEqual(boosted, ["Translucent Image"])

    def test_label_modifiers_reach_their_button(self):
        # Improved Ardent Defender reaches Ardent Defender by spell label, not class mask.
        ad = self.by_name(self.tww, "Ardent Defender")
        self.assertIn("Improved Ardent Defender", [m["talent"] for c in ad["mitigation"] for m in c.get("mods", ())])

    def test_strength_of_will_makes_unending_resolve_forty_percent_in_every_patch(self):
        # Strength of Will (317138: aura 107, a flat -15 on Unending Resolve's -25 reduction) is 0.40 in
        # every patch; live, back-to-back hits read 0.4000 with it (148 pairs, five Warlocks), 0.25 without.
        import defensive_catalog
        for patch in defensive_catalog.CATALOGS:
            ur = defensive_catalog.CATALOGS[patch][104773]
            comps, _ = defensives._resolve(ur, {91468: 1}, {})
            self.assertEqual([c.get("dr") for c in comps if c.get("dr")], [0.4], patch)
            comps, _ = defensives._resolve(ur, {}, {})
            self.assertEqual([c.get("dr") for c in comps if c.get("dr")], [0.25], patch)

    def test_talent_heal_over_time_carries_its_duration(self):
        ur = self.by_name(defensives._LATEST, "Unending Resolve")
        hot = next(c for c in ur["mitigation"] if (c.get("needs") or {}).get("talent") == "Infernal Vitality")
        self.assertEqual((hot["heal"], hot["over_ms"], hot["ticks"]), (0.3, 10_000, 10))

    def test_max_health_increase_keeps_the_health_share(self):
        # At half health, +30% max health is +150k health, not +300k.
        kb = hit(100_000, 500_000, 0, overkill=100_000)
        self.assertAlmostEqual(defensives._prevented([{"hp": 0.3}], kb, MAX, 500_000, SCHOOLS), 150_000)
        # "Current and maximum health" (Fortifying Brew) adds the full amount.
        self.assertAlmostEqual(defensives._prevented([{"hp": 0.2, "current": True}], kb, MAX, 500_000, SCHOOLS), 200_000)
        # Increases multiply: +30% and +15% is x1.495.
        self.assertAlmostEqual(defensives._prevented([{"hp": 0.3}, {"hp": 0.15}], kb, MAX, 500_000, SCHOOLS),
                               247_500)

    def test_healing_received_raises_heals_in_the_same_option(self):
        kb = hit(100_000, 200_000, 0, overkill=100_000)
        self.assertAlmostEqual(defensives._prevented([{"heal": 0.1}, {"heal_taken": 0.2}], kb, MAX, 800_000, SCHOOLS),
                               120_000)

    def test_reduction_by_missing_health(self):
        # Bloody Fortitude: up to 20% more at no health; at 80% missing that's 16%.
        kb = hit(100_000, 200_000, 0, overkill=800_000)
        self.assertAlmostEqual(defensives._prevented([{"dr_missing": 0.2}], kb, MAX, 800_000, SCHOOLS), 160_000)


class BearFormTests(unittest.TestCase):
    """Bear Form for druids who aren't Guardians, checked on live logs (armor 1,173 -> Moonkin
    2,640 -> Bear 3,754; x1.15 with Ursine Vigor; max health x1.30 with Ursoc's Spirit)."""
    cat = defensives._LATEST
    bear = next(d for d in defensives._LATEST.all.values() if d["name"] == "Bear Form")
    frenzied = next(d for d in defensives._LATEST.all.values() if d["name"] == "Frenzied Regeneration")

    def melee(self, armor, overkill=10_000):
        return dict(hit(100_000, 1_000_000, 0, overkill=overkill, ability=1), armor=armor,
                    unmitigatedAmount=2_000_000, mitigated=100_000)

    def test_armor_math(self):
        # K 4,050, armor 2,640 in Moonkin Form (x2.25): Bear Form makes it 1,173 x 3.2 = 3,754.
        kb = dict(self.melee(2_640), armorK=4_050, formArmor=2.25)
        before, after = 2_640 / (2_640 + 4_050), 3_754 / (3_754 + 4_050)
        expected = 1 - (1 - after) / (1 - before)
        prevented = defensives._prevented([{"armor": 2.2, "replaces_form": True}], kb, MAX, 0, {1: PHYS})
        self.assertAlmostEqual(prevented / 1_010_000, expected, places=3)

    def test_armor_doesnt_reduce_magic_and_unknown_spells_are_unknown(self):
        kb = dict(hit(100_000, 1_000_000, 0, overkill=10), armor=2_000, armorK=4_000)
        self.assertFalse(defensives._effect_applies({"armor": 2.2}, kb, SCHOOLS))       # frost
        kb = dict(kb, abilityGameID=999_999_999)
        self.assertIsNone(defensives._effect_applies({"armor": 2.2}, kb, {999_999_999: PHYS}))

    def test_balance_druid_has_bear_form_and_frenzied_needs_it(self):
        entries = set(self.frenzied["talent_entries"])
        r = run("Druid", "Balance", talents={e: 1 for e in entries}, auras=[])
        self.assertIn("Bear Form", names(r["available"]))
        fr = next(a for a in r["available"] if a["name"] == "Frenzied Regeneration")
        self.assertEqual(fr.get("withForm"), "Bear Form")
        # Empowered Shapeshifting lets it be cast in Cat Form: no form needed.
        lift = self.frenzied["needs_form"]["unless"]["entries"]
        r = run("Druid", "Feral", talents={e: 1 for e in entries | set(lift)}, auras=[])
        fr = next(a for a in r["available"] if a["name"] == "Frenzied Regeneration")
        self.assertNotIn("withForm", fr)

    def test_guardians_dont_get_it(self):
        r = run("Druid", "Guardian", talents=set(), auras=[])
        self.assertNotIn("Bear Form", names(r["available"]))


class PotionRankTests(unittest.TestCase):
    cat = defensives._LATEST
    conc = next(sid for sid, d in defensives._LATEST.consumable.items()
                if d["name"] == "Concentrated Silvermoon Health Potion")

    def heal(self, amount, vers, mult=1.0):
        return (1, self.conc, amount, 1_000_000, mult, vers)

    def test_versatility_and_buffs_come_out(self):
        # Live log: 449,991 at 4.74% Versatility, and 539,990 with a +20% healing buff up.
        r = defensives.potion_rank(self.conc, self.cat, [self.heal(449_991, 474), self.heal(539_990, 474, 1.2),
                                                         self.heal(485_316, 1_296)], {}, None)
        self.assertEqual((r["rank"], r["heal"], r["of"]), ("gold", 421_200, 2))
        self.assertEqual(r["vers"], 4.7)

    def test_silver(self):
        # Reaches silver's tooltip but not gold's, with a 6% healing bonus.
        r = defensives.potion_rank(self.conc, self.cat, [self.heal(359_498 * 1.06 * 1.06, 600)], {}, None)
        self.assertEqual((r["rank"], r["bonus"]), ("silver", 6.0))

    def test_each_heal_is_judged_with_the_talents_of_its_own_pull(self):
        # Live log (Feral Druid): silver drunk in pull 48 with both +4% healing talents
        # and in pull 49 with only one; they died in pull 22, with both.
        nr, bwn = (next(m["entries"][0] for m in self.cat.heal_talents if m["talent"] == t)
                   for t in ("Natural Recovery", "Bond with Nature"))
        heals = [(1, self.conc, 419_436, 1_000_000, 1.0, 787, 48), (2, self.conc, 433_561, 1_000_000, 1.0, 1_596, 49)]
        by_fight = {22: {nr: 1, bwn: 1}, 48: {nr: 1, bwn: 1}, 49: {nr: 1}}
        r = defensives.potion_rank(self.conc, self.cat, heals, by_fight[22], "Feral", by_fight)
        self.assertEqual(r["rank"], "silver")
        # Judged with the death's pull's talents alone, the second heal falls under silver.
        self.assertIsNone(defensives.potion_rank(self.conc, self.cat, heals, by_fight[22], "Feral"))

    def test_no_rank_under_every_tooltip_or_without_heals(self):
        self.assertIsNone(defensives.potion_rank(self.conc, self.cat, [self.heal(300_000, 0)], {}, None))
        self.assertIsNone(defensives.potion_rank(self.conc, self.cat, [], {}, None))

    def test_three_ranks_in_the_war_within(self):
        cat = defensives.catalog_for(1_740_000_000_000)
        algari = next(d for d in cat.consumable.values() if d["name"] == "Algari Healing Potion")
        self.assertEqual([r["rank"] for r in algari["ranks"]], ["bronze", "silver", "gold"])
        self.assertEqual(algari["ranks"][-1]["heal"], 3_839_477)
        # 4.3% apart, less than players' own healing bonuses: the rank isn't claimed.
        sid = next(s for s, d in cat.consumable.items() if d["name"] == "Algari Healing Potion")
        r = defensives.potion_rank(sid, cat, [(1, sid, 4_500_000, 9_000_000, 1.0, 500)], {}, None)
        self.assertNotIn("rank", r)
        self.assertEqual(r["unknown"], 4.3)


class ReadyTimeTests(unittest.TestCase):
    """A press is credited only once the ability was really back: its ready time comes from every
    earlier cast of the report, not only those within one cooldown of the death."""
    BARKSKIN, FIERY_BRAND = 22812, 204021

    def die(self, player_class, spec, casts, death, talents=frozenset(), fight_start=20_000, big_hit_at=None,
            other_pulls=None, encounters=None):
        """`other_pulls`: {fight ID: (start, talents)} of the report's other kept pulls."""
        indexed = {"casts": {1: sorted(casts)},
                   "talents": {(7, 1): talents if isinstance(talents, dict) else set(talents),
                               **{(f, 1): t for f, (_, t) in (other_pulls or {}).items()}}}
        hits = [hit(big_hit_at or death - 13_000, 400_000, 600_000), hit(death, 600_000, 0, overkill=50_000)]
        pull_starts = {7: fight_start, **{f: s for f, (s, _) in (other_pulls or {}).items()}}
        return defensives.analyze_death(1, player_class, spec, 7, fight_start, death, indexed,
                                        {**NAMES, **{sid: d["name"] for sid, d in CATALOG.items()}}, {},
                                        hits=hits, ability_schools=SCHOOLS, pull_starts=pull_starts,
                                        encounters=encounters)

    ICE_BARRIER, COLD_SNAP, CELESTIAL_BREW, BLACK_OX_BREW, FADE = 11426, 235219, 322507, 115399, 586

    def test_cold_snap_brings_ice_barrier_back_at_once(self):
        # Ice Barrier (30s) pressed at 50s, Cold Snap at 55s: back at 55s, not 80s.
        r = self.die("Mage", "Frost", [(50_000, self.ICE_BARRIER), (55_000, self.COLD_SNAP)], 63_000,
                     talents=entries(self.ICE_BARRIER), fight_start=40_000, big_hit_at=54_000)
        self.assertIn("Ice Barrier", names(r["available"]))
        self.assertLessEqual(r["survival"]["details"]["Ice Barrier"]["pressAgo"], 8.0)

    def test_a_gap_ended_by_a_reset_is_not_cooldown_reduction(self):
        # Pressed at 50s, Cold Snap at 55s, pressed again at 56s: the 6s gap is the reset, not a 6s
        # cooldown, so at 70s it is on cooldown until 86s.
        casts = [(50_000, self.ICE_BARRIER), (55_000, self.COLD_SNAP), (56_000, self.ICE_BARRIER)]
        r = self.die("Mage", "Frost", casts, 70_000, talents=entries(self.ICE_BARRIER), fight_start=40_000)
        self.assertEqual([c["readyIn"] for c in r["cooldown"] if c["name"] == "Ice Barrier"], [16])

    def test_black_ox_brew_gives_back_one_charge_in_midnight(self):
        # Celestial Brew with Endless Draught (2 charges, 90s): both spent at 50s and 51s; Black Ox Brew at
        # 55s gives one back ("grants one charge"), pressed at 56s: none left at 60s.
        talents = entries(self.CELESTIAL_BREW) | {117618}
        casts = [(50_000, self.CELESTIAL_BREW), (51_000, self.CELESTIAL_BREW), (55_000, self.BLACK_OX_BREW)]
        r = self.die("Monk", "Brewmaster", casts, 60_000, talents=talents, fight_start=40_000)
        self.assertIn("Celestial Brew", names(r["available"]))
        r = self.die("Monk", "Brewmaster", casts + [(56_000, self.CELESTIAL_BREW)], 60_000, talents=talents,
                     fight_start=40_000)
        self.assertNotIn("Celestial Brew", names(r["available"]))

    def test_a_gap_across_an_encounter_is_not_cooldown_reduction(self):
        # Divine Shield (300s): pressed at 200s (pull 3) and 320s (pull 4) is the encounter reset, not a
        # 120s cooldown. Pressed at 610s in this pull (from 600s): back at 910s, so at 740s on cooldown.
        talents = entries(642)
        casts = [(200_000, 642), (320_000, 642), (610_000, 642)]
        for encounters in (None, [(150_000, 250_000), (300_000, 450_000), (600_000, 800_000)]):
            r = self.die("Paladin", "Holy", casts, 740_000, talents=talents, fight_start=600_000,
                         other_pulls={3: (150_000, talents), 4: (300_000, talents)}, encounters=encounters)
            self.assertEqual([c["readyIn"] for c in r["cooldown"] if c["name"] == "Divine Shield"], [170])

    def test_a_press_after_a_wipe_carries_into_the_next_pull(self):
        # Long cooldowns reset when the encounter ends. Divine Shield (300s) pressed at 260s, after pull 3
        # ended (150s to 250s) and before this pull (from 300s): back only at 560s, so at 400s on cooldown.
        talents = entries(642)
        encounters = [(150_000, 250_000), (300_000, 500_000)]
        r = self.die("Paladin", "Holy", [(260_000, 642)], 400_000, talents=talents, fight_start=300_000,
                     other_pulls={3: (150_000, talents)}, encounters=encounters)
        self.assertEqual([(c["readyIn"], c["usedAgo"]) for c in r["cooldown"] if c["name"] == "Divine Shield"],
                         [(160, 140)])
        # Pressed at 200s, during pull 3: the wipe at 250s reset it, so it is ready in this pull.
        r = self.die("Paladin", "Holy", [(200_000, 642)], 400_000, talents=talents, fight_start=300_000,
                     other_pulls={3: (150_000, talents)}, encounters=encounters)
        self.assertIn("Divine Shield", names(r["available"]))

    def test_each_press_counts_with_its_own_pulls_talents(self):
        # Fade: 30s, 20s with two ranks of Improved Fade. Pull 3 (from 0) without it, this pull (from 100s)
        # with it. Pressed at 90s in pull 3: back at 120s, so at 115s it is on cooldown for 5s more.
        talents = {e: 1 for e in entries(self.FADE)}
        r = self.die("Priest", "Shadow", [(90_000, self.FADE)], 115_000, talents={**talents, 103836: 2},
                     fight_start=100_000, other_pulls={3: (0, talents)})
        self.assertEqual([c["readyIn"] for c in r["cooldown"] if c["name"] == "Fade"], [5])

    def test_a_cast_older_than_one_cooldown_still_sets_the_ready_time(self):
        # Barkskin (60s) pressed at 0: back at 60s, 3s before the killing blow at 63s. Pressing it
        # before the big hit at 59s would have saved more, but it wasn't back yet.
        r = self.die("Druid", "Balance", [(0, self.BARKSKIN)], 63_000, big_hit_at=59_000)
        self.assertIn("Barkskin", names(r["available"]))
        self.assertLessEqual(r["survival"]["details"]["Barkskin"]["pressAgo"], 3.0)

    def test_back_less_than_a_second_before_the_killing_blow_is_too_late(self):
        r = self.die("Druid", "Balance", [(0, self.BARKSKIN)], 60_500)
        det = r["survival"]["details"]["Barkskin"]
        self.assertEqual(det.get("why"), "readyTooLate")
        self.assertNotIn("pressAgo", det)
        self.assertFalse(r["survival"]["wouldSave"]["Barkskin"])

    def test_charges_come_back_one_at_a_time_over_every_earlier_cast(self):
        # Fiery Brand with Down in Flames: 2 charges, 48s each. Spent at 0 and 1s, the first charge is
        # back at 48s (spent at 49s), the next at 96s (spent at 97s), the next only at 144s.
        talents = entries(self.FIERY_BRAND) | {112876}
        casts = [(t, self.FIERY_BRAND) for t in (0, 1_000, 49_000, 97_000)]
        r = self.die("DemonHunter", "Vengeance", casts, 143_000, talents=talents)
        self.assertNotIn("Fiery Brand", names(r["available"]))
        self.assertEqual([(c["readyIn"], c["usedAgo"]) for c in r["cooldown"] if c["name"] == "Fiery Brand"],
                         [(1, 46)])

    def test_angels_mercy_shortens_desperate_prayer(self):
        # Angel's Mercy (238100): aura 341, -20000 ms on spell category 671, Desperate Prayer's category.
        import defensive_catalog
        for patch, cat in defensive_catalog.CATALOGS.items():
            mods = cat[19236].get("cooldown_mods") or []
            self.assertIn(-20000, [m.get("add_ms") for m in mods if m["talent"] == "Angel's Mercy"], patch)


class MaxHealthBeforeKillingBlowTests(unittest.TestCase):
    """Health before the killing blow is taken against the max health the player had just before it.

    WCL logs the killing hit after the death removed the player's auras, so its maxHitPoints has lost
    every max-health aura they had (live 2026-10-08, every one of the four 105% deaths: Strikepal,
    nerubar p16, auras stripped at 1910329-1910332, killing hit at 1910349 with max 10061382 against
    11198315 on every hit and heal before; Zorthar, voidspire p58, and Batchester, midnight-s2 p42,
    lost 5% the same way)."""

    NERUBAR = defensives.catalog_for(1740420145769)          # WgYbA1r7fXdZKtPF, patch 11.0.7

    def assess(self, hits, available=(), **kw):
        durations = {CATALOG[s]["name"]: CATALOG[s].get("aura_ms") for s in available}
        return defensives.assess_survival(hits, hits[-1]["timestamp"], ready(*available), [], NAMES, SCHOOLS,
                                          aura_ms=durations, **kw)

    @staticmethod
    def at(ts, amount, hp_after, max_hp, overkill=0, absorbed=0, ability=500, buffs=()):
        return dict(hit(ts, amount, hp_after, overkill=overkill, absorbed=absorbed, ability=ability),
                    maxHitPoints=max_hp, buffs="".join(f"{a}." for a in buffs))

    def sizer(self, player_class="Warrior", spec="Arms", cat=None, names=None):
        cat = cat or self.NERUBAR
        return defensives._aura_sizer(cat, player_class, spec, {}, names or {})

    def test_strikepal_max_health_is_the_last_hit_before_the_killing_blow(self):
        # Live: last hit 1908720 at 6243724 / 11198315, healed to 10531185, then Phase Lunge for
        # 10531185 + 4552041 overkill + 829401 absorbed, logged with max 10061382.
        hits = [self.at(1_908_720, 60_714, 6_243_724, 11_198_315),
                self.at(1_910_349, 10_531_185, 0, 10_061_382, overkill=4_552_041, absorbed=829_401)]
        r = self.assess(hits, available=[DIVINE_SHIELD])
        self.assertEqual(r["maxHp"], 11_198_315)
        self.assertEqual(r["hpBeforePct"], 94)
        self.assertEqual(r["killingHit"]["pctOfMax"], 142)
        self.assertEqual(r["deathType"], "oneShot")
        self.assertTrue(r["wouldSave"]["Divine Shield"])
        missing = 11_198_315 - 10_531_185
        self.assertLessEqual(r["details"]["Divine Shield"]["amount"], missing + 15_912_627 + 1)

    def test_full_health_one_shot_reads_100_percent(self):
        # Live (Zorthar, voidspire p58): 557900 / 557900, Melee for 557900 + 501183 overkill, logged
        # with max 531340 (557900 / 1.05).
        hits = [self.at(6_941_373, 14_798, 543_102, 557_900),
                self.at(6_943_162, 557_900, 0, 531_340, overkill=501_183, ability=1)]
        r = self.assess(hits)
        self.assertEqual((r["maxHp"], r["hpBeforePct"], r["killingHit"]["pctOfMax"]), (557_900, 100, 190))

    def test_auras_lost_before_the_killing_blow_come_off_by_game_data(self):
        # Live (Nerub-ar, 11.0.7): Black Attunement (403295, +2% max health) on the last hit, not on the
        # killing hit; the killing hit took exactly 7587780, its own max. 98% was wrong, 100% is right.
        hits = [self.at(8_773_545, 10_000, 7_700_000, 7_739_535, buffs=[403295]),
                self.at(8_775_890, 7_587_780, 0, 7_587_780, overkill=1_000_000)]
        r = self.assess(hits, aura_size=self.sizer())
        self.assertEqual((r["maxHp"], r["hpBeforePct"]), (7_587_780, 100))
        # gZBT7Y1j8dNCbwqp actor 14 at 3182550: Fortitude of the Bear (388035, +20% in 11.0.7) ran out.
        hits = [self.at(3_177_579, 10_000, 3_000_000, 9_256_106, buffs=[388035]),
                self.at(3_182_550, 2_246_960, 0, 7_713_421, overkill=500_000)]
        r = self.assess(hits, aura_size=self.sizer("Hunter", "BeastMastery"))
        self.assertEqual((r["maxHp"], r["hpBeforePct"]), (7_713_422, 29))
        # An aura on the killing hit that wasn't on the last hit came up in between (Vampiric Blood +30%).
        hits = [self.at(95_000, 10_000, 500_000, 1_000_000), self.at(100_000, 600_000, 0, 1_000_000,
                                                                       overkill=1, buffs=[55233])]
        r = self.assess(hits, aura_size=self.sizer("DeathKnight", "Blood"))
        self.assertEqual((r["maxHp"], r["hpBeforePct"]), (1_300_000, 46))

    def test_a_list_change_the_max_has_not_caught_up_with(self):
        # Live (bpQCAqm89GhTLW7Z actor 19): Black Attunement left the list at 3055385 but the max read
        # 7359162 until later; the killing hit at 3055954 took exactly 7214865 = 7359162 / 1.02.
        hits = [self.at(3_054_635, 10_000, 7_300_000, 7_359_162, buffs=[403295]),
                self.at(3_055_385, 10_000, 7_290_000, 7_359_162),
                self.at(3_055_954, 7_214_865, 0, 7_214_865, overkill=1_000_000)]
        r = self.assess(hits, aura_size=self.sizer())
        self.assertEqual((r["maxHp"], r["hpBeforePct"]), (7_214_865, 100))

    def test_havoc_metamorphosis_is_not_vengeances(self):
        # Havoc's Metamorphosis (162264) has no max-health effect; Vengeance's (187827) is +40%.
        names = {162264: "Metamorphosis", 187827: "Metamorphosis"}
        hits = [self.at(95_000, 10_000, 1_000_000, 1_000_000),
                self.at(100_000, 1_000_000, 0, 1_000_000, overkill=1, buffs=[162264])]
        r = self.assess(hits, aura_size=self.sizer("DemonHunter", "Havoc", names=names))
        self.assertEqual((r["maxHp"], r["hpBeforePct"], r["deathType"]), (1_000_000, 100, "oneShot"))
        hits[-1]["buffs"] = "187827."
        r = self.assess(hits, aura_size=self.sizer("DemonHunter", "Vengeance", names=names))
        self.assertEqual(r["maxHp"], 1_400_000)

    @staticmethod
    def healed(ts, amount, ability, kind="heal"):
        return {"timestamp": ts, "type": kind, "targetID": 1, "abilityGameID": ability, "amount": amount}

    def test_what_the_killing_hit_healed_is_not_health_before_it(self):
        # Live (Soulcleavi, manaforge p54): at 18995479 / 29370419 when Oblivion landed; Last Resort
        # (209258) absorbed part of it and put him in Metamorphosis, which healed 11748168 (187827) in the
        # same moment; the hit was logged at 8002696 with 30743644 taken. Health before the blow: 65%.
        hits = [self.at(8_000_138, 900_304, 15_378_866, 29_370_419),
                dict(hit(8_001_031, 0, 0), resourceActor=None, maxHitPoints=None, hitPoints=None),
                self.healed(8_002_681, 58_740_838, 209258, "absorbed"), self.healed(8_002_681, 11_748_168, 187827),
                self.at(8_002_696, 30_743_644, 0, 29_370_419, overkill=39_340_044, absorbed=58_740_840)]
        r = self.assess(hits)
        self.assertEqual((r["maxHp"], r["hpBeforePct"]), (29_370_419, 65))
        # A Metamorphosis heal without Last Resort's absorb with it is an ordinary press: not the blow's.
        self.assertEqual(self.assess([h for h in hits if h.get("abilityGameID") != 209258])["hpBeforePct"], 100)
        # Heals before the hit before the killing hit were health they had.
        hits[1]["timestamp"] = 8_002_690
        self.assertEqual(self.assess(hits)["hpBeforePct"], 100)

    def test_a_cheat_death_heal_inside_the_killing_hit(self):
        # Live (Arzoker, Quel'Danas p34, k9mC7RxjKPt1TgZW): 339946 / 507980 on his last hit; Defy Fate
        # (404381) healed 136670 inside Terminate and an Ebon Might heal (395152, 92026) landed with it;
        # Terminate read 507980 taken. Before the blow: 507980 - 136670 = 371310, 73%: not a one-shot
        # from full health.
        hits = [self.at(23_324_344, 58_669, 339_946, 507_980),
                self.healed(23_325_226, 1_015_960, 404195, "absorbed"),
                self.healed(23_325_226, 136_670, 404381), self.healed(23_325_226, 92_026, 395152),
                self.at(23_325_227, 507_980, 0, 507_980, overkill=2_896_634, absorbed=1_015_960, ability=1)]
        r = self.assess(hits)
        self.assertEqual((r["maxHp"], r["hpBeforePct"], r["deathType"]), (507_980, 73, "wasLow"))
        # Padflash (Manaforge p79): Cauterize (87023) healed 2919591, leaving exactly his hit-before 2903317.
        hits = [self.at(26_609_056, 3_896_114, 2_903_317, 16_636_880), self.healed(26_609_235, 2_919_591, 87023),
                self.healed(26_609_236, 33_273_760, 86949, "absorbed"),
                self.at(26_609_251, 5_822_908, 0, 16_636_880, overkill=41_093_092, absorbed=33_273_760)]
        self.assertEqual(self.assess(hits)["hpBeforePct"], 17)          # 2903317 / 16636880
        # Live (Alemonk, Quel'Danas p32): a Defy Fate heal 1 ms after the hit before and 31 ms before the
        # killing hit, with no Defy Fate absorb of the killing hit: health they had (301048, 62%).
        hits = [self.at(22_878_976, 19_449, 277_176, 489_498), self.healed(22_878_977, 23_288, 404381),
                self.at(22_879_008, 301_048, 0, 489_498, overkill=10_145)]
        self.assertEqual(self.assess(hits)["hpBeforePct"], 62)

    def test_a_cheat_death_aura_used_up_by_the_killing_hit(self):
        # Guardian Spirit, Ardent Defender and All-Devouring Nucleus carry EffectAura 316 like Defy Fate; WCL
        # logs no absorb for Guardian Spirit, it removes the aura as it heals (live, Manaforge
        # 2VtyDR4CF6PGLjbd p75: 47788 removed at 25624450, 48153 healed 981289 at 25624451).
        removed = dict(self.healed(25_624_450, None, 47788, "removebuff"), sourceID=277)
        hits = [self.at(25_624_000, 100_000, 1_000_000, 4_000_000), removed,
                self.healed(25_624_451, 1_600_000, 48153),
                self.at(25_624_460, 2_600_000, 0, 4_000_000, overkill=5_000_000)]
        self.assertEqual(self.assess(hits)["hpBeforePct"], 25)          # (2600000 - 1600000) / 4000000
        # A Guardian Spirit heal without its aura going after the hit before is not the killing hit's.
        hits[1]["timestamp"] = 25_623_990
        self.assertEqual(self.assess(hits)["hpBeforePct"], 65)
        self.assertEqual({h: features.KILLING_HIT_HEALS[h] for h in (48153, 66235, 1236692)},
                         {48153: 47788, 66235: 31850, 1236692: 1235500})
        # Arzoker p89: Defy Fate healed 42827 at 13395295 and absorbed its part of Terminate at 13395314,
        # 19 ms apart, both after the hit before: the killing hit's.
        hits = [self.at(13_394_226, 37_642, 433_271, 507_980), self.healed(13_395_294, 507_980, 410355, "absorbed"),
                self.healed(13_395_295, 42_827, 404381), self.healed(13_395_314, 1_015_960, 404195, "absorbed"),
                self.at(13_395_315, 507_980, 0, 507_980, overkill=922_534, absorbed=1_523_940)]
        self.assertEqual(self.assess(hits)["hpBeforePct"], 92)          # 465153 / 507980

    def test_a_stacking_aura_counts_per_stack(self):
        # Sentinel (389539): +1% max health per stack, 15 stacks (game data: CumulativeAura 15, "per
        # stack"), losing one a second. 15 stacks on the last hit, 3 at the killing blow: x1.03 / 1.15.
        sizer = defensives._aura_sizer(defensives._LATEST, "Paladin", "Protection", {})
        self.assertEqual(sizer.stacks(389539), 15)
        aura = lambda ts, kind, n: {"timestamp": ts, "type": kind, "targetID": 1, "abilityGameID": 389539, "stack": n}
        hits = [aura(89_000, "applybuffstack", 15), self.at(90_000, 10_000, 1_000_000, 1_150_000, buffs=[389539]),
                aura(95_000, "removebuffstack", 9), aura(98_000, "removebuffstack", 3),
                self.at(100_000, 900_000, 0, 1_000_000, overkill=1, buffs=[389539])]
        r = self.assess(hits, aura_size=sizer)
        self.assertEqual(r["maxHp"], round(1_150_000 * 1.03 / 1.15))
        # Without its stack events the stacks can't be told: the last hit's max stands.
        r = self.assess([hits[1], hits[-1]], aura_size=sizer)
        self.assertEqual(r["maxHp"], 1_150_000)
        self.assertEqual(defensives._stacks_at([aura(95_000, "removebuffstack", 9)], 389539, 90_000), 10)

    def test_earlier_hits_are_measured_against_the_max_they_had_then(self):
        # A 300k hit at 1M max is 30% of max, even though Vampiric Blood ran out before the killing blow.
        hits = [self.at(90_000, 300_000, 700_000, 1_300_000, buffs=[55233]),
                self.at(99_000, 10_000, 680_000, 1_000_000),
                self.at(100_000, 680_000, 0, 1_000_000, overkill=50_000)]
        r = self.assess(hits, aura_size=self.sizer("DeathKnight", "Blood"))
        self.assertEqual(r["biggestHit"]["pctOfMax"], 23)          # 300k of 1.3M
        self.assertEqual(r["deathType"], "wasLow")

    def test_a_recorded_gain_on_the_killing_blow_is_kept(self):
        hits = [self.at(95_000, 100_000, 600_000, 1_000_000),
                self.at(100_000, 600_000, 0, 1_100_000, overkill=200_000)]
        self.assertEqual(self.assess(hits)["maxHp"], 1_100_000)

    def test_replay_caps_extra_health_with_the_max_before_the_killing_blow(self):
        hits = [self.at(95_000, 10_000, 940_000, 1_000_000),
                self.at(100_000, 940_000, 0, 900_000, overkill=50_000)]
        r = self.assess(hits, available=[EXHIL])
        self.assertEqual(r["hpBeforePct"], 94)
        self.assertTrue(r["wouldSave"]["Exhilaration"])       # 60k missing > 50k overkill

    def test_soulburn_healthstone_is_a_max_health_aura(self):
        # Game data: Soulburn: Healthstone (387636), EffectAura 133, +20% max health.
        self.assertEqual(defensives.max_health_size(387636, "11.0.7"), (0.2, 0))


class MaxHealthWhereTheGameDataPutsItTests(unittest.TestCase):
    """An aura's max-health effect is sized from where the game data puts it (max_health_auras.py)."""

    def assess(self, hits, sizer):
        return defensives.assess_survival(hits, hits[-1]["timestamp"], [], [], NAMES, SCHOOLS, aura_size=sizer)

    @staticmethod
    def at(ts, amount, hp_after, max_hp, overkill=0, buffs=()):
        return dict(hit(ts, amount, hp_after, overkill=overkill), maxHitPoints=max_hp,
                    buffs="".join(f"{a}." for a in buffs))

    def sizer(self, cls, spec, talents=None):
        return defensives._aura_sizer(defensives._LATEST, cls, spec, talents or {})

    def test_a_restoration_druid_shifting_to_bear_form(self):
        # Bear Form (5487) has no max-health effect of its own; its text names its passive 1178's
        # Stamina +25% ("Stamina increased by $1178s2%"), which every druid's Bear Form carries.
        hits = [self.at(95_000, 10_000, 600_000, 1_000_000),
                self.at(100_000, 625_000, 0, 1_000_000, overkill=1, buffs=[5487])]
        r = self.assess(hits, self.sizer("Druid", "Restoration"))
        self.assertEqual((r["maxHp"], r["hpBeforePct"]), (1_250_000, 50))
        # A Guardian's Bear Form also has the spec passive's +10% (270100), Ursoc's Spirit +5% (talent).
        latest = defensives._LATEST.patch
        self.assertEqual(defensives.max_health_size(5487, latest, {}, "Guardian"), (0.35, 0))
        self.assertEqual(defensives.max_health_size(5487, latest, {103297: 1}, "Guardian"), (0.4, 0))

    def test_fount_of_strength_on_frenzied_regeneration(self):
        # Fount of Strength (441675): "Frenzied Regeneration also increases your maximum health by $s3%"
        # (10); only with the talent (entry 117218).
        latest = defensives._LATEST.patch
        self.assertEqual(defensives.max_health_size(22842, latest, {}, "Guardian"), (0.0, 0))
        self.assertEqual(defensives.max_health_size(22842, latest, {117218: 1}, "Guardian"), (0.1, 0))
        hits = [self.at(95_000, 10_000, 500_000, 1_000_000),
                self.at(100_000, 550_000, 0, 1_000_000, overkill=1, buffs=[22842])]
        r = self.assess(hits, self.sizer("Druid", "Guardian", {117218: 1}))
        self.assertEqual((r["maxHp"], r["hpBeforePct"]), (1_100_000, 50))

    def test_talents_on_other_buttons_and_stat_debuffs(self):
        latest = defensives._LATEST.patch
        # Fortifying Brew 20% ($health = 115203 s1), Ironshell Brew +10%.
        self.assertEqual(defensives.max_health_size(120954, latest, {101498: 1}, "Brewmaster"), (0.3, 0))
        # Desperate Prayer 25%, Light's Inspiration +10%; Barkskin only with Ward of the Forest (+20%).
        self.assertEqual(defensives.max_health_size(19236, latest, {103826: 1}, "Holy"), (0.35, 0))
        self.assertEqual(defensives.max_health_size(22812, latest, {}, "Guardian"), (0.0, 0))
        self.assertEqual(defensives.max_health_size(22812, latest, {103224: 1}, "Guardian"), (0.2, 0))
        # Havoc's Metamorphosis stays at nothing; Hexing Strike (EffectAura 80, all stats -5%) lowers it.
        self.assertEqual(defensives.max_health_size(162264, latest, {}, "Havoc"), (0.0, 0))
        self.assertEqual(defensives.max_health_size(1260567, latest), (-0.05, 0))

    def test_base_points_zero_that_talents_fill(self):
        # Game data 12.1.0: Bone Shield 195181 effect 2 is EffectAura 133 with base points 0; Foul Bulwark
        # 206974 (entry 96302) adds 1 to it (EffectAura 107 on effect 2): +1% max health per charge.
        # Ancestral Vigor 207400 effect 0 (133, bp 0) gets +5 from its talent 207401; Grimoire of Sacrifice
        # 196099 effect 1 (137 Stamina, bp 0) +3 from Profane Bargain 389576.
        latest = defensives._LATEST.patch
        self.assertEqual(defensives.max_health_size(195181, latest, {}, "Blood"), (0.0, 0))
        self.assertEqual(defensives.max_health_size(195181, latest, {96302: 1}, "Blood"), (0.01, 0))
        self.assertEqual(defensives.max_health_size(207400, latest, {}, "Restoration"), (0.0, 0))
        self.assertEqual(defensives.max_health_size(207400, latest, {101909: 1}, "Restoration"), (0.05, 0))
        self.assertEqual(defensives.max_health_size(196099, latest, {91426: 1}, "Affliction"), (0.03, 0))
        # Improved Ardent Defender's +20% is its modifier on Ardent Defender's own effect 4, counted once.
        self.assertEqual(defensives.max_health_size(31850, latest, {102441: 1}, "Protection"), (0.2, 0))
        # The loadouts the site reads keep those talents.
        self.assertTrue({96302, 101909, 91426, 134033} <= defensives._LATEST.relevant_talent_entries)
        # Bone Shield with Foul Bulwark: 10 charges on the last hit, 5 at the killing blow -> x1.05 / 1.10.
        sizer = self.sizer("DeathKnight", "Blood", {96302: 1})
        aura = lambda ts, kind, n: {"timestamp": ts, "type": kind, "targetID": 1, "abilityGameID": 195181,
                                    "stack": n, "sourceID": 1}
        hits = [aura(89_000, "applybuffstack", 10), self.at(90_000, 10_000, 1_000_000, 1_100_000, buffs=[195181]),
                aura(95_000, "removebuffstack", 5),
                self.at(100_000, 900_000, 0, 1_000_000, overkill=1, buffs=[195181])]
        self.assertEqual(self.assess(hits, sizer)["maxHp"], 1_050_000)
        # Without the talent the charges change nothing.
        self.assertEqual(self.assess(hits, self.sizer("DeathKnight", "Blood"))["maxHp"], 1_100_000)

    def test_an_aura_is_sized_with_its_casters_loadout(self):
        # Live (Voidspire, P6CwHkgFR9Krf1Bz p43, actor 8): 511853 max on the hit at 4525705; actor 24, a
        # warrior with Battlefield Commander (entry 134033, +2%) and not Inspiring Presence, cast Rallying
        # Cry 97463 on him at 4526123; the next hit read 573274 = 511853 x 1.12. Actor 8 has neither talent.
        loadouts = {24: ({134033: 1}, "Fury")}
        sizer = defensives._aura_sizer(defensives._LATEST, "Priest", "Discipline", {}, None, 8, loadouts.get)
        cry = {"timestamp": 4_526_123, "type": "applybuff", "sourceID": 24, "targetID": 8, "abilityGameID": 97463}
        hits = [self.at(4_525_705, 10_000, 400_000, 511_853), cry,
                self.at(4_526_791, 500_000, 0, 511_853, overkill=1, buffs=[97463])]
        self.assertEqual(self.assess(hits, sizer)["maxHp"], 573_275)
        # With the target's own loadout it would read x1.10.
        self.assertEqual(defensives.max_health_size(97463, defensives._LATEST.patch, {}, "Discipline"), (0.1, 0))
        # A caster whose loadout isn't known: left as it was (the last hit's max).
        sizer = defensives._aura_sizer(defensives._LATEST, "Priest", "Discipline", {}, None, 8, {}.get)
        self.assertEqual(self.assess(hits, sizer)["maxHp"], 511_853)
        # A self-cast aura uses the player's own loadout.
        self.assertEqual(sizer.by_caster(97463, 8), (0.1, 0))

    def test_every_players_loadout_is_kept(self):
        # Another player's talents size an aura they cast on a player who died.
        raw = {"combatants": [{"type": "combatantinfo", "fight": 3, "sourceID": 24, "specID": 72,
                               "talentTree": [{"id": 134033, "rank": 1}, {"id": 1, "rank": 1}]}]}
        idx = defensives.filter_defensive_raw(raw, {8})
        self.assertEqual(idx["talents"][(3, 24)], {134033: 1})
        self.assertEqual(idx["specs"][(3, 24)], "Fury")


STAGGER_TICK, DAMPEN_HARM, DIFFUSE_MAGIC = 124255, 122278, 122783


def stagger_tick(ts, amount, hp_after, overkill=0):
    """A Brewmaster's own Stagger tick as WCL logs it: source and target are the Monk, and a
    `mitigated` share is listed (0.600 through while Invoke Niuzao takes 40% of each tick, defensives or not)."""
    raw = (amount + overkill) / 0.6
    return {"timestamp": ts, "type": "damage", "sourceID": 1, "targetID": 1, "abilityGameID": STAGGER_TICK,
            "amount": amount, "overkill": overkill, "absorbed": 0, "mitigated": round(raw * 0.4),
            "unmitigatedAmount": round(raw), "hitPoints": hp_after, "maxHitPoints": MAX, "resourceActor": 2}


class StaggerTests(unittest.TestCase):
    """Stagger (115069) is an absorb aura (aura 69): damage reductions cut the hit first, Stagger then
    delays a share of what is left into ticks of 124255 every 0.5 s over 10 s. A tick is never reduced by
    a defensive up while it ticks (Weavi, Undermine: 246 ticks under Fortifying Brew, 26 under Dampen
    Harm, 1.000 through, or 0.600 with Invoke Niuzao up, as without them), while shields absorb ticks
    (1194 of Weavi's ticks absorbed)."""

    def assess(self, hits, available, spec="Brewmaster"):
        durations = {CATALOG[s]["name"]: CATALOG[s].get("aura_ms") for s in available}
        return defensives.assess_survival(hits, 100_000, ready(*available), [], NAMES, SCHOOLS,
                                          aura_ms=durations, spec=spec)

    def test_a_stagger_tick_is_never_reduced(self):
        hits = [stagger_tick(99_500, 100_000, 300_000), stagger_tick(100_000, 300_000, 0, overkill=50_000)]
        r = self.assess(hits, [DAMPEN_HARM])
        self.assertFalse(r["wouldSave"]["Dampen Harm"])
        self.assertEqual(r["details"]["Dampen Harm"]["amount"], 0)
        self.assertEqual(r["details"]["Dampen Harm"]["why"], "stagger")
        self.assertTrue(r["ignoresReduction"])
        self.assertTrue(r["staggerTick"])

    def test_shields_still_absorb_a_stagger_tick(self):
        kb = stagger_tick(100_000, 300_000, 0, overkill=50_000)
        self.assertAlmostEqual(defensives._prevented([{"absorb": 0.3}], kb, MAX, 700_000, SCHOOLS), 300_000)
        self.assertEqual(defensives._prevented([{"dr": 0.5}], kb, MAX, 700_000, SCHOOLS), 0)

    def test_a_reduction_counts_only_on_the_part_of_a_hit_that_was_not_staggered(self):
        # A 800k Frost hit: 400k taken at once, 400k staggered (WCL logs it as absorbed) into ticks
        # after it. Diffuse Magic (60% magic) pressed before it shrinks both parts, but the staggered
        # part would only have ticked later, by an amount the log can't give (Purifying Brew, the pool's
        # other hits): only the part taken at once counts, 240k, short of the 300k overkill.
        hits = [hit(97_000, 400_000, 600_000, absorbed=400_000),
                stagger_tick(100_000, 600_000, 0, overkill=300_000)]
        brew = self.assess(hits, [DIFFUSE_MAGIC])
        self.assertAlmostEqual(brew["details"]["Diffuse Magic"]["amount"], 240_000, delta=1)
        self.assertFalse(brew["wouldSave"]["Diffuse Magic"])
        # Anyone else's absorbed part is a shield's: the reduction saves it for later hits.
        other = self.assess(hits, [DIFFUSE_MAGIC], spec="Frost")
        self.assertAlmostEqual(other["details"]["Diffuse Magic"]["amount"], 400_000, delta=1)


FIERY_BRAND, BRANDED = 204021, 207771


def enemy_hit(ts, amount, hp_after, source, instance=None, overkill=0, auras=()):
    h = dict(hit(ts, amount, hp_after, overkill=overkill), sourceID=source,
             buffs="".join(f"{a}." for a in auras))
    if instance is not None:
        h["sourceInstance"] = instance
    return h


class FieryBrandTests(unittest.TestCase):
    """Fiery Brand by patch, from the game data (207771 effect 0):
    - The War Within (11.x): aura 269 on the branded enemy, "dealing 40% less damage to" the Demon Hunter.
      Measured on adjacent hit pairs: the branded unit's hits 0.400 (Lazelele, Nerub-ar, 123 pairs;
      Lunchay, Undermine, 288 pairs), other units' hits 0.00 / -0.025 (77 pairs).
    - Midnight (12.0.0 on): aura 87 on the Demon Hunter himself (implicit target: caster), "reducing the
      damage you take by 40%": every hit. Felvix, Voidspire (Lightblinded Vanguard, 3 bosses): 207771 is a
      buff on him; hits from the branded boss read 0.585 of unbranded, the other bosses' 0.564."""

    def assess(self, hits, patch="11.0.7", friendlies=(), attackable=(50, 60)):
        entry = defensives._CATALOGS[patch].all[FIERY_BRAND]
        return defensives.assess_survival(hits, 100_000, [entry], [], NAMES, SCHOOLS,
                                          aura_ms={"Fiery Brand": entry["aura_ms"]}, friendly_ids=set(friendlies),
                                          attackable=None if attackable is None else set(attackable))

    def test_the_catalog_follows_the_patch(self):
        self.assertEqual(defensives._CATALOGS["11.0.7"].all[FIERY_BRAND]["mitigation"],
                         [{"dr": 0.4, "from_target": BRANDED}])
        self.assertEqual(defensives._CATALOGS["12.0.0"].all[FIERY_BRAND]["mitigation"], [{"dr": 0.4}])

    def test_the_war_within_brands_one_enemy_the_best(self):
        # A 600k hit from the boss (unit 50), then a 500k hit from an add (unit 60) kills (100k overkill).
        hits = [enemy_hit(97_000, 600_000, 400_000, source=50),
                enemy_hit(100_000, 400_000, 0, source=60, overkill=100_000)]
        # Branded, the boss's hit is 240k smaller, the add's 200k: the boss is the better target. Never both.
        r = self.assess(hits)
        self.assertAlmostEqual(r["details"]["Fiery Brand"]["amount"], 240_000, delta=1)
        self.assertTrue(r["wouldSave"]["Fiery Brand"])
        # In Midnight it is on the Demon Hunter: 40% of both hits.
        mid = self.assess(hits, patch="12.0.0")
        self.assertAlmostEqual(mid["details"]["Fiery Brand"]["amount"], 0.4 * 1_100_000, delta=1)

    def test_only_an_enemy_the_raid_attacked_can_be_branded(self):
        # The killing hit came from a rocket nobody damaged (Goblin Guided Rocket): the boss is the only target.
        hits = [enemy_hit(97_000, 600_000, 400_000, source=50),
                enemy_hit(100_000, 400_000, 0, source=60, overkill=300_000)]
        r = self.assess(hits, attackable=(50,))
        self.assertAlmostEqual(r["details"]["Fiery Brand"]["amount"], 240_000, delta=1)
        self.assertFalse(r["wouldSave"]["Fiery Brand"])
        # Nobody it could brand hit them: it helps nothing.
        r = self.assess(hits, attackable=())
        self.assertEqual(r["details"]["Fiery Brand"]["amount"], 0)
        self.assertEqual(r["details"]["Fiery Brand"]["why"], "notBranded")
        self.assertFalse(r["wouldSave"]["Fiery Brand"])
        # Which units the raid attacked isn't known: can't tell.
        r = self.assess(hits, attackable=None)
        self.assertIsNone(r["wouldSave"]["Fiery Brand"])
        self.assertEqual(r["details"]["Fiery Brand"]["why"], "brandUnknown")

    def test_another_instance_of_the_same_add_is_branded_on_its_own(self):
        hits = [enemy_hit(97_000, 600_000, 400_000, source=60, instance=2),
                enemy_hit(100_000, 400_000, 0, source=60, instance=1, overkill=300_000)]
        r = self.assess(hits)
        self.assertAlmostEqual(r["details"]["Fiery Brand"]["amount"], 0.4 * 700_000, delta=1)
        self.assertFalse(r["wouldSave"]["Fiery Brand"])

    def test_nothing_to_brand_for_the_environment_or_a_friend(self):
        for source, friends in ((-1, ()), (None, ()), (7, (7,))):
            hits = [enemy_hit(100_000, 400_000, 0, source=source, overkill=100_000)]
            r = self.assess(hits, friendlies=friends, attackable=(-1, 7))
            self.assertEqual(r["details"]["Fiery Brand"]["amount"], 0, source)
            self.assertEqual(r["details"]["Fiery Brand"]["why"], "notBranded", source)
            self.assertFalse(r["wouldSave"]["Fiery Brand"], source)

    def test_hits_from_a_unit_already_branded_are_not_cut_again(self):
        # The boss was branded for the first hit (WCL lists 207771 on it: already 40% smaller).
        hits = [enemy_hit(97_000, 600_000, 400_000, source=50, auras=(BRANDED,)),
                enemy_hit(100_000, 400_000, 0, source=50, overkill=300_000)]
        r = self.assess(hits)
        self.assertAlmostEqual(r["details"]["Fiery Brand"]["amount"], 0.4 * 700_000, delta=1)


class DampenHarmTests(unittest.TestCase):
    """Dampen Harm (122278): "Reduces all damage you take by 20% to 50% ..., with larger attacks being
    reduced by more" (effects 1 and 2: dummies of 20 and 50, no curve in the data). Fitted on real hits
    (Atlai and Weavi, Undermine): 0.20 + 0.30 x min(x, 1), x the hit after the player's other reductions
    as a share of their max health (0.285 at x = 0.285, 0.350 at 0.500, 0.383 at 0.610)."""
    DH = {"dr": 0.2, "dr_hit": 0.5}

    def test_the_catalog_carries_both_ends_from_the_game_data(self):
        for patch in ("11.0.2", "12.1.0"):
            self.assertEqual(defensives._CATALOGS[patch].all[DAMPEN_HARM]["mitigation"], [self.DH])

    def test_larger_hits_are_reduced_by_more(self):
        kb = hit(100_000, 400_000, 0, overkill=200_000)               # 600k: x = 0.6, cut 0.38
        self.assertAlmostEqual(defensives._prevented([self.DH], kb, MAX, 600_000, SCHOOLS), 0.38 * 600_000)
        small = hit(100_000, 50_000, 0, overkill=50_000)              # 100k: x = 0.1, cut 0.23
        self.assertAlmostEqual(defensives._prevented([self.DH], small, MAX, 50_000, SCHOOLS), 0.23 * 100_000)

    def test_capped_at_half_for_a_hit_of_max_health_or_more(self):
        kb = hit(100_000, 1_000_000, 0, overkill=500_000)             # 1.5M: x = 1.5, cut 0.50
        self.assertAlmostEqual(defensives._prevented([self.DH], kb, MAX, 0, SCHOOLS), 0.5 * 1_500_000)

    def test_size_after_the_other_reductions_pressed_with_it(self):
        # Shield Wall's 40% first: 1M becomes 600k, x = 0.6, Dampen Harm cuts 0.38 of that.
        kb = hit(100_000, 1_000_000, 0)
        keep = 0.6 * (1 - 0.38)
        self.assertAlmostEqual(defensives._prevented([{"dr": 0.4}, self.DH], kb, MAX, 0, SCHOOLS), (1 - keep) * 1_000_000)

    def test_size_after_armor_pressed_with_it(self):
        # Bear Form's +220% armor on a melee swing first: 10k armor against K = 10k takes 50%, 32k takes
        # 76.2%, so the hit keeps 0.238 / 0.5 = 0.476 of itself; x = 0.476, Dampen Harm cuts 0.343 of that.
        kb = dict(hit(100_000, 1_000_000, 0, ability=1), armor=10_000, armorK=10_000)
        armor_keep = (1 - 32_000 / 42_000) / 0.5
        keep = armor_keep * (1 - (0.2 + 0.3 * armor_keep))
        self.assertAlmostEqual(defensives._prevented([{"armor": 2.2}, self.DH], kb, MAX, 0, {1: PHYS}),
                               (1 - keep) * 1_000_000, delta=1)

    def test_size_against_the_max_health_they_had_at_that_hit(self):
        # The same 600k hit on a player with 2M max health: x = 0.3, cut 0.29.
        kb = dict(hit(100_000, 400_000, 0, overkill=200_000), maxHitPoints=2 * MAX)
        self.assertAlmostEqual(defensives._prevented([self.DH], kb, 2 * MAX, 1_600_000, SCHOOLS), 0.29 * 600_000)


def pool_tick(ts, raw, hp_after, overkill=0):
    """A Stagger tick nothing reduced: its size is what it took off the pool."""
    return {"timestamp": ts, "type": "damage", "sourceID": 1, "targetID": 1, "abilityGameID": STAGGER_TICK,
            "amount": raw - overkill, "overkill": overkill, "absorbed": 0, "unmitigatedAmount": raw,
            "hitPoints": hp_after, "maxHitPoints": MAX, "resourceActor": 2}


def staggered(ts, amount, source=50, ability=500):
    """WCL's absorbed event for the share of a hit Stagger delayed."""
    return {"timestamp": ts, "type": "absorbed", "sourceID": 1, "targetID": 1,
            "abilityGameID": defensives.STAGGER_AURA, "attackerID": source, "extraAbilityGameID": ability,
            "amount": amount}


class StaggerPoolTests(unittest.TestCase):
    """The pool as the logs show it (Weavi, Undermine p24): each staggered hit's amount is an absorbed
    event of 115069; every staggered hit restarts 20 ticks and each tick deals the pool over the ticks
    left (pool / tick read 20.00, 19.00, ... on 116 of 130 staggered hits); purifies take part of it off."""

    def test_pool_before_a_staggered_hit_from_the_ticks_around_it(self):
        ticks = [pool_tick(500, 200_000, 0), pool_tick(1_000, 200_000, 0), pool_tick(1_500, 200_000, 0),
                 pool_tick(2_500, 135_000, 0)]
        first, second = staggered(0, 4_000_000), staggered(2_000, 1_000_000)
        pools = defensives._stagger_pools(ticks, [first, second])
        self.assertEqual(pools[id(first)], [0])                     # 20 x 200k - 4M: nothing before
        # The tick before left 200k x 17 = 3.4M; the tick after says 20 x 135k - 1M = 1.7M. A purify
        # came in between; the share it took reads 1 - 1.7M / 3.4M = 0.5000 if it came before the hit,
        # 1 - 2.7M / 4.4M = 0.386 if after: Purifying Brew's 50%, before. The tick after is right.
        self.assertEqual(pools[id(second)], [1_700_000])

    @staticmethod
    def pools(tick, second_amount, casts=None, purify=None, tick_before=200_000, first=4_000_000):
        """The pool estimates before a second staggered hit at 2 s: the first (at 0) staggered `first`,
        three ticks of `tick_before` (the pool then: 17 x tick_before), and `tick` the tick after it."""
        ticks = [pool_tick(500, tick_before, 0), pool_tick(1_000, tick_before, 0),
                 pool_tick(1_500, tick_before, 0), pool_tick(2_500, tick, 0)]
        ins = [staggered(0, first), staggered(2_000, second_amount)]
        cast = lambda t: {"timestamp": t, "type": "cast", "abilityGameID": defensives.PURIFYING_BREW}
        out = defensives._stagger_pools(ticks, ins, None if casts is None else [cast(t) for t in casts], purify)
        return out[id(ins[1])]

    def test_a_purifying_brew_cast_says_which_side(self):
        # Pool 3.4M, 680k staggered, the tick after 102k: 20 x 102k - 680k = 1.36M. Read before the hit
        # the purify took 0.6 (Purifying Brew with Mantra of Purity), read after it 0.5 (without): both
        # fit, so without the casts it can't be told. A cast on one side says which.
        self.assertEqual(self.pools(102_000, 680_000), [3_400_000, 1_360_000])
        self.assertEqual(self.pools(102_000, 680_000, casts=[1_800]), [1_360_000])
        self.assertEqual(self.pools(102_000, 680_000, casts=[2_200]), [3_400_000])
        # 20 x 120k - 1M = 1.4M: 0.588 before, 0.4545 after, neither a purify the game has; a cast on
        # one side doesn't settle it either (the other could have had a flat one): both are kept.
        self.assertEqual(self.pools(120_000, 1_000_000), [3_400_000, 1_400_000])
        self.assertEqual(self.pools(120_000, 1_000_000, casts=[1_800]), [3_400_000, 1_400_000])

    def test_a_cast_on_a_side_that_fits_nothing_keeps_both_readings(self):
        # Pool 3.4M, 600k staggered, the tick after 190k: 3.2M. Read before the hit the purify took
        # 0.0588, read after it 0.05: a Quick Sip after the hit fits, but the Purifying Brew was cast
        # before it, and nothing with a brew fits that side (a flat purify could have been there too).
        # The cast says the purify the after side fits isn't the whole story: both readings are kept.
        # Without the casts the Quick Sip after the hit decides it.
        self.assertEqual(self.pools(190_000, 600_000), [3_400_000])
        self.assertEqual(self.pools(190_000, 600_000, casts=[1_800]), [3_400_000, 3_200_000])
        # The mirror: 3.4M, 600k, the tick after 191.5k: 3.23M, 0.05 before the hit (a Quick Sip), 0.0425
        # after it, where the brew was cast: both readings again. Without the cast the Quick Sip decides.
        self.assertEqual(self.pools(191_500, 600_000), [3_230_000])
        self.assertEqual(self.pools(191_500, 600_000, casts=[2_200]), [3_400_000, 3_230_000])

    def test_one_quick_sip_purifies_ten_percent_at_once(self):
        # Quick Sip purifies 5% for each 3 s of Shuffle gained, in one event: Keg Smash's 5 s can cross
        # two thresholds (Weavi, Quel'Danas p104: 0.1000 on 10 hits). Pool 3.4M, 37,820 staggered, the
        # tick after 154,891: 3.06M, 0.1000 read before the hit, 0.0989 after. Only the first is a share
        # the game has (two separate 5% would be 0.0975).
        self.assertEqual(self.pools(154_891, 37_820), [3_060_000])
        keeps = defensives._purify_keeps(defensives.STAGGER_PURIFY["11.1.0"])
        self.assertEqual(keeps[0], [0.4, 0.5])                       # Purifying Brew, with Mantra of Purity
        self.assertEqual(keeps[2], [0.9, 0.95, 1.0])                 # one Quick Sip event: 10%, 5% or none
        self.assertEqual(keeps[3], 0.95)                             # each Tranquil Spirit

    def test_tranquil_spirit_clears_five_percent_for_every_sphere(self):
        # Atlai (Undermine, AaM31gBWwFHmD7Rz pulls 32 and 38, ticks with no staggered hit between): a
        # sphere alone 0.0500, Expel Harm drawing 1 sphere 0.0975, 2 spheres 0.1426, 5 spheres 0.2649 =
        # 1 - 0.95^6 (The War Within: Expel Harm counts too), two spheres Spinning Crane Kick pulled in
        # 0.0975, a sphere with a brew 0.5250. So any number of 5% purifies can share a stretch; a second
        # 10% Quick Sip can't (one Keg Smash per stretch; Press the Advantage's bonus strike grants no
        # Shuffle).
        keeps = defensives._purify_keeps(defensives.STAGGER_PURIFY["11.1.0"])
        fits = lambda to, brew=False: defensives._purify_fits(1_000_000, to, keeps, 1_000_000, brew)
        self.assertTrue(fits(735_092))                  # 0.95^6: Expel Harm and 5 spheres
        self.assertTrue(fits(698_337))                  # 0.95^7: Expel Harm and 6 spheres
        self.assertTrue(fits(771_637))                  # a 10% Quick Sip and 3 spheres
        self.assertTrue(fits(451_250, True))            # a brew and 2 spheres
        self.assertFalse(fits(810_000))                 # two 10% Quick Sips
        self.assertFalse(fits(451_250))                 # a brew's share, but no brew cast

    def test_a_cast_on_one_side_and_a_quick_sip_on_the_other_is_undecided(self):
        # Pool 340k (17 x 20k), 3.06M staggered, the tick after 161.5k: 170k. Read before the hit the
        # purify took 0.5 (the brew, cast there), read after it 0.05: a Quick Sip could have come after
        # the hit as well, so the truth lies between: both are kept. Without passive purifies in the
        # game data the cast settles it.
        args = dict(casts=[1_800], tick_before=20_000, first=400_000)
        self.assertEqual(self.pools(161_500, 3_060_000, **args), [340_000, 170_000])
        brew_only = {"brew": {"share": 0.5}}
        self.assertEqual(self.pools(161_500, 3_060_000, purify=brew_only, **args), [170_000])

    def test_midnights_purifying_brew_clears_at_least_8_percent_of_max_health(self):
        # Pool 136k (17 x 8k): half is 68k, but Midnight's brew clears at least 8% of max health (1M):
        # 80k, leaving 56k; 1M staggered, the tick after 52.8k. Read before the hit 0.588: a purify
        # only with the minimum, so the tick after is right; The War Within's brew has none.
        args = dict(tick_before=8_000, first=160_000)
        self.assertEqual(self.pools(52_800, 1_000_000, purify=defensives.STAGGER_PURIFY["12.0.0"], **args), [56_000])
        self.assertEqual(self.pools(52_800, 1_000_000, purify=defensives.STAGGER_PURIFY["11.1.0"], **args),
                         [136_000, 56_000])

    def test_undecided_pool_that_decides_the_verdict_is_cant_tell(self):
        # Before the second (fully staggered) hit the pool was 665k (tick before) or 350k (tick after:
        # 20 x 52.5k - 700k); the shares 0.474 and 0.231 match no purify, and no cast says which. Diffuse
        # Magic, ready only after the first hit, cuts 60% of the 700k: 0.308 or 0.4 of the pool, 32.3k or
        # 42k off the two ticks after, against 35k overkill. Saves with one reading, not the other.
        first = dict(hit(80_000, 300_000, 935_000, absorbed=700_000), sourceID=50)
        second = dict(hit(90_000, 0, 70_000, absorbed=700_000), sourceID=50)
        ticks = [pool_tick(80_500, 35_000, 900_000)]
        after = [pool_tick(90_500, 52_500, 17_500), pool_tick(91_000, 52_500, 0, overkill=35_000)]
        ins = [staggered(80_000, 700_000), staggered(90_000, 700_000)]
        pools = defensives._stagger_pools(ticks + after, ins)
        self.assertEqual(pools[id(ins[1])], [665_000, 350_000])
        r = defensives.assess_survival([first, second] + ins + ticks + after, 91_000, ready(DIFFUSE_MAGIC), [],
                                       NAMES, SCHOOLS, aura_ms={"Diffuse Magic": 30_000}, spec="Brewmaster",
                                       ready_since={"Diffuse Magic": 85_000})
        self.assertIsNone(r["wouldSave"]["Diffuse Magic"])
        self.assertEqual(r["details"]["Diffuse Magic"]["why"], "staggerUnknown")
        self.assertIsNone(r["allTogetherWouldSave"])

    def test_a_reduction_before_a_staggered_hit_shrinks_every_later_tick(self):
        # A 1M Frost hit from full: 300k taken at once, 700k staggered (absorbed event), then 20 ticks
        # of 35k; the 20th kills (15k health left, 20k overkill). Diffuse Magic (60% magic) pressed
        # before it cuts the 300k by 180k and the pool by 60%, so every tick by 21k: 600k in all.
        hit_ = dict(hit(90_000, 300_000, 680_000, absorbed=700_000), sourceID=50)
        ticks = [pool_tick(90_500 + 500 * j, 35_000, 680_000 - 35_000 * (j + 1)) for j in range(19)]
        ticks.append(pool_tick(100_000, 35_000, 0, overkill=20_000))
        events = [hit_, staggered(90_000, 700_000)] + ticks
        r = defensives.assess_survival(events, 100_000, ready(DIFFUSE_MAGIC), [], NAMES, SCHOOLS,
                                       aura_ms={"Diffuse Magic": 30_000}, spec="Brewmaster")
        self.assertAlmostEqual(r["details"]["Diffuse Magic"]["amount"], 600_000, delta=2)
        # Without the staggered amount in the log, only the part taken at once counts.
        r = defensives.assess_survival([hit_] + ticks, 100_000, ready(DIFFUSE_MAGIC), [], NAMES, SCHOOLS,
                                       aura_ms={"Diffuse Magic": 30_000}, spec="Brewmaster")
        self.assertAlmostEqual(r["details"]["Diffuse Magic"]["amount"], 180_000, delta=2)

    def test_a_reduction_only_on_part_of_the_pool(self):
        # The pool already held an earlier hit's share when a second 700k came in, pressed between: the
        # cut is 60% of the new share only. The tick before says the pool was 35k x 19 = 665k (the log
        # skips the ticks between here), the tick after 20 x 66.5k - 700k = 630k: the replay takes the
        # estimate that credits least, 665k, so each later tick shrinks by 0.6 x 700k / 1365k.
        ticks = [pool_tick(80_500, 35_000, 900_000)]
        first = dict(hit(80_000, 300_000, 935_000, absorbed=700_000), sourceID=50)
        second = dict(hit(90_000, 300_000, 600_000, absorbed=700_000), sourceID=50)
        after = [pool_tick(90_500, 66_500, 533_500), pool_tick(91_000, 66_500, 0, overkill=400_000)]
        events = [first, staggered(80_000, 700_000), second, staggered(90_000, 700_000)] + ticks + after
        r = defensives.assess_survival(events, 91_000, ready(DIFFUSE_MAGIC), [], NAMES, SCHOOLS,
                                       aura_ms={"Diffuse Magic": 30_000}, spec="Brewmaster")
        share = 0.6 * 700_000 / 1_365_000
        self.assertAlmostEqual(r["details"]["Diffuse Magic"]["amount"], 180_000 + 2 * 66_500 * share, delta=2)


class ShuffleGrantTests(unittest.TestCase):
    """The catalog build reads what grants Shuffle (Quick Sip counts the seconds gained) from Monk
    tooltips; only the grants reviewed for the purify fits pass: Keg Smash 5 s, Blackout Kick 3 s,
    Spinning Crane Kick 1 s."""

    @staticmethod
    def build():
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "scripts"))
        import build_defensive_catalog as build
        return build

    def purify(self, grants):
        """stagger_purify on game data where each of `grants` {name: seconds} has a tooltip granting it."""
        build = self.build()
        values = {(build.PURIFYING_BREW, 0): 50.0, (build.QUICK_SIP, 0): 5.0, (build.QUICK_SIP, 1): 3.0,
                  (build.TRANQUIL_SPIRIT, 0): 5.0}
        names, desc, family = {}, {}, {}
        for k, (name, seconds) in enumerate(grants.items()):
            sid = 900_000 + k
            names[sid], desc[sid], family[sid] = name, "Strike, granting Shuffle for $s2 sec.", (build.MONK_FAMILY, [0] * 4)
            values[(sid, 1)] = seconds
        gd = types.SimpleNamespace(names=names, family=family, value=lambda s, i: values.get((s, i)))
        mods = types.SimpleNamespace(effect=lambda *a: [])
        problems = []
        out = build.stagger_purify(gd, mods, desc, problems)
        return out, problems

    def test_the_three_reviewed_grants_pass(self):
        out, problems = self.purify({"Keg Smash": 5.0, "Blackout Kick": 3.0, "Spinning Crane Kick": 1.0})
        self.assertEqual(problems, [])
        self.assertEqual(out["shuffle_s"], {"Blackout Kick": 3.0, "Keg Smash": 5.0, "Spinning Crane Kick": 1.0})

    def test_a_missing_changed_or_new_grant_fails_the_build(self):
        _, problems = self.purify({"Keg Smash": 5.0, "Blackout Kick": 3.0})
        self.assertEqual(len(problems), 1)
        self.assertIn("Spinning Crane Kick", problems[0])
        _, problems = self.purify({"Keg Smash": 6.0, "Blackout Kick": 3.0, "Spinning Crane Kick": 1.0})
        self.assertEqual(len(problems), 1)
        self.assertIn("Keg Smash", problems[0])
        _, problems = self.purify({"Keg Smash": 5.0, "Blackout Kick": 3.0, "Spinning Crane Kick": 1.0,
                                   "Tiger Palm": 1.0})
        self.assertEqual(len(problems), 1)
        self.assertIn("Tiger Palm", problems[0])


class AttackedUnitsTests(unittest.TestCase):
    def test_units_the_raid_damaged_from_the_damage_done_table(self):
        from unittest import mock
        table = {"reportData": {"report": {"table": {"data": {"entries": [
            {"id": 876, "name": "Chrome King Gallywix", "total": 1561920441},
            {"id": 883, "name": "1500-Pound Dud", "total": 712},
            {"id": 900, "name": "Nothing", "total": 0}]}}}}}
        with mock.patch.object(defensives, "graphql_query", return_value=table) as q:
            self.assertEqual(defensives.fetch_attacked_units("t", "R", [1, 2], 0, 10), [876, 883])
        self.assertIn("dataType: DamageDone", q.call_args[0][1])
        self.assertIn("viewBy: Target", q.call_args[0][1])

    def test_only_patches_with_an_effect_on_the_enemy_fetch_them(self):
        self.assertTrue(defensives.brands_enemies(defensives._CATALOGS["11.0.7"]))
        self.assertFalse(defensives.brands_enemies(defensives._CATALOGS["12.0.0"]))


class StaggerWindowFetchTests(unittest.TestCase):
    def test_the_extras_block_reads_the_stagger_pool_from_before_the_window(self):
        # A Brewmaster's staggered amounts, ticks and Purifying Brew casts (no target: by caster) from
        # STAGGER_LOOKBACK_MS before the window; ticks inside it come once, with the hits.
        queries = []
        tick = lambda t: {"timestamp": t, "type": "damage", "sourceID": 1, "targetID": 1,
                          "abilityGameID": STAGGER_TICK, "amount": 5, "unmitigatedAmount": 5}

        def fake(token, q, v):
            queries.append(q)
            report = {a: {"data": [tick(50_000), dict(tick(59_990), overkill=1, hitPoints=0)]}
                      for a in __import__("re").findall(r"(p\d+): events", q)}
            report["extras"] = {"data": [
                tick(40_000), tick(50_000), tick(30_000),       # before the lookback: dropped
                {"timestamp": 41_000, "type": "absorbed", "sourceID": 1, "targetID": 1,
                 "abilityGameID": defensives.STAGGER_AURA, "attackerID": 9, "extraAbilityGameID": 7, "amount": 100},
                {"timestamp": 42_000, "type": "cast", "sourceID": 1, "targetID": -1,
                 "abilityGameID": defensives.PURIFYING_BREW},
                {"timestamp": 43_000, "type": "applydebuff", "targetID": 1, "abilityGameID": STAGGER_TICK}]}
            return {"reportData": {"report": report}}
        with __import__("unittest.mock").mock.patch.object(defensives, "graphql_query", side_effect=fake):
            hits = defensives.fetch_death_windows("t", "R", [(3, [(60_000, "A")])])
        self.assertIn(f"type = 'cast' and ability.id = {defensives.PURIFYING_BREW}", queries[0])
        self.assertIn("startTime: 34500", queries[0])
        self.assertEqual([(h["type"], h["timestamp"]) for h in hits[1]],
                         [("damage", 40_000), ("absorbed", 41_000), ("cast", 42_000), ("damage", 50_000),
                          ("damage", 59_990)])
        self.assertEqual(hits[1][1]["attackerID"], 9)
