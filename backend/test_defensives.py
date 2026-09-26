import unittest

import defensives
from defensive_catalog import CATALOG

ICE_BLOCK, ICE_COLD, MIRROR = 45438, 414658, 55342
FEINT, CLOAK, EVASION = 1966, 31224, 5277
PAIN_SUPP, HEALTHSTONE, POTION = 33206, 6262, 1234768


def entries(*spell_ids):
    return {e for sid in spell_ids for e in CATALOG[sid]["talent_entries"]}


def run(player_class, spec, casts=(), buffs=(), talents=None, fight_start=0, death=100_000,
        ability_names=None, actors=None):
    indexed = {
        "casts": {1: sorted(casts)},
        "buffs": {1: sorted(buffs, key=lambda b: b[0])},
        "talents": {} if talents is None else {(7, 1): talents},
    }
    names = {sid: d["name"] for sid, d in CATALOG.items()}
    names.update(ability_names or {})
    return defensives.analyze_death(1, player_class, spec, 7, fight_start, death, indexed, names, actors or {})


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
        r = run("Rogue", "Assassination", talents=set())
        self.assertIn("Feint", names(r["available"]))

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

    def test_active_buff_at_death(self):
        r = run("Mage", "Frost", talents=entries(ICE_BLOCK),
                casts=[(95_000, ICE_BLOCK)],
                buffs=[(95_000, "applybuff", ICE_BLOCK, 1), (100_010, "removebuff", ICE_BLOCK, 1)])
        self.assertIn("Ice Block", names(r["active"]))
        self.assertNotIn("Ice Block", names(r["cooldown"]))

    def test_buff_that_expired_before_death_is_not_active(self):
        r = run("Mage", "Frost", talents=entries(ICE_BLOCK),
                casts=[(50_000, ICE_BLOCK)],
                buffs=[(50_000, "applybuff", ICE_BLOCK, 1), (60_000, "removebuff", ICE_BLOCK, 1)])
        self.assertNotIn("Ice Block", names(r["active"]))
        self.assertIn("Ice Block", names(r["cooldown"]))

    def test_external_shows_who_cast_it(self):
        r = run("Mage", "Frost", talents=set(),
                buffs=[(90_000, "applybuff", 999, 5)],
                ability_names={999: "Pain Suppression"}, actors={5: "Holypriest"})
        ext = [a for a in r["active"] if a["kind"] == "external"]
        self.assertEqual(ext, [{"name": "Pain Suppression", "kind": "external", "by": "Holypriest"}])

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

    def test_charges_recover_one_at_a_time(self):
        left, ready = defensives._charges_at(30_000, [0, 1_000], charges=2, recharge_ms=25_000)
        self.assertEqual((left, ready), (1, 20_000))  # 2nd charge starts after the 1st returns


if __name__ == "__main__":
    unittest.main()
