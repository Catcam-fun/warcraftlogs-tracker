import unittest

import defensives
from defensive_catalog import CATALOG

ICE_BLOCK, ICE_COLD, MIRROR = 45438, 414658, 55342
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
                                    killing_blows=kb)


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
        self.assertEqual(r["healthstone"], {"usedAgo": 30})
        self.assertEqual(r["potion"], {"usedAgo": None})

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
NAMES = {500: "Frost Bolt", 600: "Cleave"}
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
        r = self.assess(hit(100_000, 1_000_000, 0, overkill=200_000), available=[MIRROR])
        self.assertIsNone(r["wouldSave"]["Mirror Image"])

    def test_no_killing_blow_near_the_death(self):
        self.assertIsNone(defensives.assess_survival([hit(60_000, 900_000, 0, overkill=5)], 100_000,
                                                     [], [], NAMES, SCHOOLS))

    def test_unused_healthstone_only_if_carried(self):
        kb = [hit(300_000, 200_000, 0, overkill=100_000)]
        carried = defensives.analyze_death(
            1, "Mage", "Frost", 7, 200_000, 300_000,
            {"casts": {1: [(10_000, HEALTHSTONE)]}, "talents": {(7, 1): set()}},
            NAMES, {}, killing_blows=kb, ability_schools=SCHOOLS)
        self.assertTrue(carried["survival"]["wouldSave"]["Healthstone"])
        not_carried = defensives.analyze_death(
            1, "Mage", "Frost", 7, 200_000, 300_000,
            {"casts": {}, "talents": {(7, 1): set()}},
            NAMES, {}, killing_blows=kb, ability_schools=SCHOOLS)
        self.assertNotIn("Healthstone", not_carried["survival"]["wouldSave"])


DIVINE_PROTECTION, UNENDING = 498, 104773
