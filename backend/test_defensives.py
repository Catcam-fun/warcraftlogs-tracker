import unittest
import os
import sys

import defensives
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
        self.assertIn({"name": "Pain Suppression", "kind": "external", "by": "Holypriest"}, r["active"])
        # Removed well before death -> not active.
        indexed["buffs"][1] = [(50_000, "applybuff", ICE_BLOCK, 1), (60_000, "removebuff", ICE_BLOCK, 1)]
        r = defensives.analyze_death(1, "Mage", "Frost", 7, 0, 100_000, indexed, names_map, {})
        self.assertNotIn("Ice Block", names(r["active"]))

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
        self.assertIn({"name": "Pain Suppression", "kind": "external", "by": "Holypriest"}, r["active"])

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
        self.assertEqual(ext, [{"name": "Pain Suppression", "kind": "external", "by": None}])

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
        left, ready = defensives._charges_at(30_000, [0, 1_000], charges=2, recharge_ms=25_000)
        self.assertEqual((left, ready), (1, 20_000))  # 2nd charge starts after the 1st returns

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

    def test_report_marks_aoe_only_if_some_hit_is_aoe(self):
        self.assertFalse(defensives.logs_mark_aoe({1: [{"isAoE": False}], 2: [{"isAoE": False}]}))
        self.assertTrue(defensives.logs_mark_aoe({1: [{"isAoE": False}], 2: [{"isAoE": True}]}))


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
        self.assertEqual(defensives._ready_since(100_000, [10_000], 1, 36_000), 46_000)
        self.assertIsNone(defensives._ready_since(100_000, [], 1, 36_000))

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
        # One 90% hit and a tick right after it: a one-shot.
        r = self.assess([hit(99_200, 900_000, 100_000), hit(99_900, 100_000, 0, overkill=40_000)])
        self.assertEqual(r["deathType"], "oneShot")
        self.assertEqual(r["biggestHit"]["pctOfMax"], 90)           # the 90% hit is named
        # A small tick, then a 120% killing blow: a one-shot, nothing set it up.
        r = self.assess([hit(99_600, 100_000, 900_000), hit(99_900, 900_000, 0, overkill=300_000)])
        self.assertEqual(r["deathType"], "oneShot")
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
