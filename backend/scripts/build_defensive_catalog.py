"""Regenerate backend/defensive_catalog.py from the live game data on wago.tools.

The curated list below decides WHICH abilities count and for whom; the game
data supplies cooldowns, charges, and the talent-tree entries that grant each
ability (so a player is only expected to have what they actually talented).

Run after a patch:  python backend/scripts/build_defensive_catalog.py
Needs network access to wago.tools.
"""
import csv, gzip, io, json, os, pprint, sys, urllib.request

# kind: "personal"   - the player's own button; tracked as active / available / on cooldown
#       "external"   - raid cooldowns and externals from others; shown only when active on the player
#       "healthstone" / "potion" - consumables; tracked as used / not used this pull
# known: "talent"    - available only if the player's talents include it
#        "baseline"  - every player of the class (and spec, if listed) has it
#        "evidence"  - not in any talent tree; counted only if the player cast it in the log
CURATED = [
    # Death Knight
    (48707, "Anti-Magic Shell", "DeathKnight", None, "personal"),
    (48792, "Icebound Fortitude", "DeathKnight", None, "personal"),
    (48743, "Death Pact", "DeathKnight", None, "personal"),
    (49039, "Lichborne", "DeathKnight", None, "personal"),
    (55233, "Vampiric Blood", "DeathKnight", ["Blood"], "personal"),
    (49028, "Dancing Rune Weapon", "DeathKnight", ["Blood"], "personal"),
    (194679, "Rune Tap", "DeathKnight", ["Blood"], "personal"),
    (219809, "Tombstone", "DeathKnight", ["Blood"], "personal"),
    (51052, "Anti-Magic Zone", "DeathKnight", None, "external"),
    # Demon Hunter
    (198589, "Blur", "DemonHunter", ["Havoc", "Devourer"], "personal"),
    (196555, "Netherwalk", "DemonHunter", ["Havoc"], "personal"),
    (187827, "Metamorphosis", "DemonHunter", ["Vengeance"], "personal"),
    (204021, "Fiery Brand", "DemonHunter", ["Vengeance"], "personal"),
    (196718, "Darkness", "DemonHunter", None, "external"),
    # Druid
    (22812, "Barkskin", "Druid", None, "personal"),
    (61336, "Survival Instincts", "Druid", None, "personal"),
    (108238, "Renewal", "Druid", None, "personal"),
    (22842, "Frenzied Regeneration", "Druid", None, "personal"),
    (102342, "Ironbark", "Druid", None, "external"),
    # Evoker
    (363916, "Obsidian Scales", "Evoker", None, "personal"),
    (374348, "Renewing Blaze", "Evoker", None, "personal"),
    (357170, "Time Dilation", "Evoker", None, "external"),
    (374227, "Zephyr", "Evoker", None, "external"),
    # Hunter
    (186265, "Aspect of the Turtle", "Hunter", None, "personal"),
    (264735, "Survival of the Fittest", "Hunter", None, "personal"),
    (109304, "Exhilaration", "Hunter", None, "personal"),
    (53480, "Roar of Sacrifice", "Hunter", None, "external"),
    # Mage
    (45438, "Ice Block", "Mage", None, "personal"),
    (414658, "Ice Cold", "Mage", None, "personal"),
    (110959, "Greater Invisibility", "Mage", None, "personal"),
    (55342, "Mirror Image", "Mage", None, "personal"),
    (235313, "Blazing Barrier", "Mage", ["Fire"], "personal"),
    (11426, "Ice Barrier", "Mage", ["Frost"], "personal"),
    (235450, "Prismatic Barrier", "Mage", ["Arcane"], "personal"),
    (342245, "Alter Time", "Mage", None, "personal"),
    # Monk
    (115203, "Fortifying Brew", "Monk", None, "personal"),
    (122278, "Dampen Harm", "Monk", None, "personal"),
    (122783, "Diffuse Magic", "Monk", None, "personal"),
    (122470, "Touch of Karma", "Monk", ["Windwalker"], "personal"),
    (322507, "Celestial Brew", "Monk", ["Brewmaster"], "personal"),
    (115176, "Zen Meditation", "Monk", None, "personal"),
    (116849, "Life Cocoon", "Monk", None, "external"),
    # Paladin
    (642, "Divine Shield", "Paladin", None, "personal"),
    (498, "Divine Protection", "Paladin", ["Holy", "Retribution"], "personal"),
    (184662, "Shield of Vengeance", "Paladin", ["Retribution"], "personal"),
    (31850, "Ardent Defender", "Paladin", ["Protection"], "personal"),
    (86659, "Guardian of Ancient Kings", "Paladin", ["Protection"], "personal"),
    (633, "Lay on Hands", "Paladin", None, "personal"),
    (1022, "Blessing of Protection", "Paladin", None, "external"),
    (6940, "Blessing of Sacrifice", "Paladin", None, "external"),
    (204018, "Blessing of Spellwarding", "Paladin", None, "external"),
    (31821, "Aura Mastery", "Paladin", None, "external"),
    # Priest
    (47585, "Dispersion", "Priest", ["Shadow"], "personal"),
    (19236, "Desperate Prayer", "Priest", None, "personal"),
    (586, "Fade", "Priest", None, "personal"),
    (33206, "Pain Suppression", "Priest", None, "external"),
    (47788, "Guardian Spirit", "Priest", None, "external"),
    (62618, "Power Word: Barrier", "Priest", None, "external"),
    # Rogue
    (31224, "Cloak of Shadows", "Rogue", None, "personal"),
    (5277, "Evasion", "Rogue", None, "personal"),
    (1966, "Feint", "Rogue", None, "personal"),
    (185311, "Crimson Vial", "Rogue", None, "personal"),
    # Shaman
    (108271, "Astral Shift", "Shaman", None, "personal"),
    (108270, "Stone Bulwark Totem", "Shaman", None, "personal"),
    (98008, "Spirit Link Totem", "Shaman", None, "external"),
    (198838, "Earthen Wall Totem", "Shaman", None, "external"),
    # Warlock
    (104773, "Unending Resolve", "Warlock", None, "personal"),
    (108416, "Dark Pact", "Warlock", None, "personal"),
    # Warrior
    (871, "Shield Wall", "Warrior", None, "personal"),
    (12975, "Last Stand", "Warrior", ["Protection"], "personal"),
    (184364, "Enraged Regeneration", "Warrior", ["Fury"], "personal"),
    (118038, "Die by the Sword", "Warrior", ["Arms"], "personal"),
    (23920, "Spell Reflection", "Warrior", None, "personal"),
    (97462, "Rallying Cry", "Warrior", None, "external"),
    # Consumables (any class)
    (6262, "Healthstone", None, None, "healthstone"),
    (452930, "Demonic Healthstone", None, None, "healthstone"),
    (1234768, "Silvermoon Health Potion", None, None, "potion"),
    (1295247, "Concentrated Silvermoon Health Potion", None, None, "potion"),
    (1238009, "Invigorating Healing Potion", None, None, "potion"),
    (1262857, "Potent Healing Potion", None, None, "potion"),
    (431416, "Algari Healing Potion", None, None, "potion"),
    (431419, "Cavedweller's Delight", None, None, "potion"),
]

# Every player of the class/spec has these, whether or not a talent entry
# exists. Anti-Magic Shell and Touch of Karma have talent entries but are
# pressed in real Midnight logs by players without them.
BASELINE = {198589, 187827, 22812, 186265, 109304, 642, 498, 47585, 1966, 185311, 104773,
            48707, 122470}

# Talents that grant the button through a differently numbered spell of the
# same name. Only these are matched by name: in Midnight several same-named
# talent spells are automatic or pet versions (Shield of Vengeance 1261562,
# Diffuse Magic 1243287, Survival of the Fittest 203965), not the button.
# Verified against real logs (players with the entry press the button).
NAME_ALIAS_OK = {"Fortifying Brew"}

# How much each ability would have helped, used for "would it have saved
# them". Values come from the game data (SpellEffect: aura 87 damage-taken
# modifiers, aura 39 immunities, effect 136 %-of-max-health heals, durations
# from SpellMisc/SpellDuration, following triggered spells such as Blur ->
# 212800) or, for consumables, from medians measured across real logs.
# Fields: dr = damage reduction (0-1), school = all | magic | physical | aoe,
# immune = True, absorb / heal / hp = fraction of max health, dur = seconds.
# Abilities missing here (or None) are listed but not scored: their effect
# isn't described well enough in the data to estimate honestly.
MITIGATION = {
    "Icebound Fortitude": {"dr": .30, "dur": 8}, "Rune Tap": {"dr": .20, "dur": 4},
    "Vampiric Blood": {"hp": .30, "dur": 10}, "Death Pact": {"heal": .50},
    "Anti-Magic Shell": {"absorb": .30, "school": "magic", "dur": 5},
    "Blur": {"dr": .25, "dur": 10}, "Metamorphosis": {"hp": .40, "dur": 15},
    "Fiery Brand": {"dr": .40, "dur": 10}, "Netherwalk": {"immune": True, "dur": 2},
    "Barkskin": {"dr": .20, "dur": 8}, "Survival Instincts": {"dr": .50, "dur": 6},
    "Renewal": {"heal": .30},
    "Obsidian Scales": {"dr": .30, "dur": 12},
    "Aspect of the Turtle": {"dr": .30, "dur": 8}, "Exhilaration": {"heal": .30},
    "Survival of the Fittest": {"dr": .30, "dur": 6},
    "Ice Block": {"immune": True, "dur": 10}, "Ice Cold": {"dr": .70, "dur": 6},
    "Blazing Barrier": {"absorb": .30, "dur": 60}, "Ice Barrier": {"absorb": .35, "dur": 60},
    "Prismatic Barrier": {"absorb": .30, "dur": 60},
    "Fortifying Brew": {"dr": .20, "hp": .20, "dur": 15}, "Dampen Harm": {"dr": .20, "dur": 10},
    "Diffuse Magic": {"dr": .60, "school": "magic", "dur": 6}, "Touch of Karma": {"absorb": .50, "dur": 10},
    "Zen Meditation": {"dr": .60, "dur": 8},
    "Ardent Defender": {"dr": .30, "dur": 12}, "Divine Protection": {"dr": .20, "dur": 8},
    "Divine Shield": {"immune": True, "dur": 8}, "Guardian of Ancient Kings": {"dr": .50, "dur": 8},
    "Lay on Hands": {"heal": 1.0}, "Shield of Vengeance": {"absorb": .30, "dur": 10},
    "Desperate Prayer": {"heal": .25, "hp": .25, "dur": 10}, "Dispersion": {"dr": .75, "dur": 6},
    "Fade": {"dr": .10, "dur": 10},
    "Cloak of Shadows": {"immune": True, "school": "magic", "dur": 5},
    "Crimson Vial": {"heal": .20}, "Feint": {"dr": .40, "school": "aoe", "dur": 6},
    "Astral Shift": {"dr": .40, "dur": 12},
    "Dark Pact": {"absorb": .40, "dur": 20}, "Unending Resolve": {"dr": .25, "dur": 8},
    "Die by the Sword": {"dr": .30, "dur": 8}, "Enraged Regeneration": {"dr": .30, "dur": 8},
    "Last Stand": {"hp": .30, "heal": .30, "dur": 8}, "Shield Wall": {"dr": .40, "dur": 8},
    "Spell Reflection": {"dr": .20, "school": "magic", "dur": 5},
    # Dodges melee swings (the boss's "Melee" ability) only; Elusiveness adds a
    # damage reduction on top (see EFFECTS).
    "Evasion": {"immune": True, "school": "melee", "dur": 10},
    "Greater Invisibility": {"dr": .60, "dur": 3},
    "Frenzied Regeneration": {"heal": .24},        # 8% of max health per second for 3s
    # Shields whose size depends on stats or resources: scored only from the
    # player's real shield size seen in the log (absorb=None).
    "Celestial Brew": {"absorb": None}, "Tombstone": {"absorb": None},
    "Stone Bulwark Totem": {"absorb": None},
    # Leech and immunity to charm/fear only: can't stop a hit.
    "Lichborne": {},
    # Consumables. Healthstones heal a share of max health (from the game data);
    # potions heal a fixed amount per quality rank (POTION_TYPICAL below).
    "Healthstone": {"heal": .25}, "Demonic Healthstone": {"heal": .25},
}

# Where each value lives in the game data: (field, spell carrying the effect,
# effect index[, ticks]). Talents that modify exactly that effect (SpellEffect
# aura 107 flat / 108 percent modifiers whose class mask covers the spell) are
# attached to the catalog entry and applied at analysis time to players who
# have them (scaled by rank). A second component with a 0 base (Feint's and
# Evasion's all-damage reduction) exists only for players with the talent
# that fills it in (Elusiveness).
EFFECTS = {
    "Icebound Fortitude": [("dr", 48792, 2)], "Rune Tap": [("dr", 194679, 0)],
    "Vampiric Blood": [("hp", 55233, 3)],   # effect 2 is absorbs received, not max health "Death Pact": [("heal", 48743, 0)],
    "Anti-Magic Shell": [("absorb", 48707, 0)],
    "Blur": [("dr", 212800, 2)], "Metamorphosis": [("hp", 187827, 1)],
    "Fiery Brand": [("dr", 207771, 0)],
    "Barkskin": [("dr", 22812, 0)], "Survival Instincts": [("dr", 50322, 0)],
    "Renewal": [("heal", 108238, 0)], "Frenzied Regeneration": [("heal", 22842, 0, 3)],
    "Obsidian Scales": [("dr", 363916, 0)],
    "Aspect of the Turtle": [("dr", 186265, 3)], "Exhilaration": [("heal", 109304, 0)],
    "Survival of the Fittest": [("dr", 264735, 0)],
    "Ice Cold": [("dr", 414658, 7)], "Greater Invisibility": [("dr", 113862, 0)],
    "Blazing Barrier": [("absorb", 235313, 0)], "Ice Barrier": [("absorb", 11426, 0)],
    "Prismatic Barrier": [("absorb", 235450, 0)],
    "Diffuse Magic": [("dr", 122783, 0)], "Touch of Karma": [("absorb", 122470, 1)],
    "Celestial Brew": [("absorb", 322507, 0)], "Zen Meditation": [("dr", 115176, 1)],
    "Ardent Defender": [("dr", 31850, 0)], "Divine Protection": [("dr", 498, 0)],
    "Guardian of Ancient Kings": [("dr", 86659, 2)], "Lay on Hands": [("heal", 633, 1)],
    "Shield of Vengeance": [("absorb", 184662, 0)],
    "Desperate Prayer": [("hp", 19236, 0), ("heal", 19236, 1)],
    "Dispersion": [("dr", 47585, 0)], "Fade": [("dr", 586, 3)],
    "Crimson Vial": [("heal", 185311, 0, 4)],
    "Feint": [("dr", 1966, 0), ("dr", 1966, 1)], "Evasion": [("immune", 5277, 0), ("dr", 5277, 1)],
    "Astral Shift": [("dr", 108271, 0)], "Stone Bulwark Totem": [("absorb", 114893, 0)],
    "Dark Pact": [("absorb", 108416, 0)], "Unending Resolve": [("dr", 104773, 2)],
    "Die by the Sword": [("dr", 118038, 1)], "Enraged Regeneration": [("dr", 184364, 0)],
    "Last Stand": [("hp", 12975, 0), ("heal", 12975, 1)], "Shield Wall": [("dr", 871, 0)],
    "Spell Reflection": [("dr", 385391, 0)], "Tombstone": [("absorb", 219809, 0)],
    "Healthstone": [("heal", 6262, 0)], "Demonic Healthstone": [("heal", 452930, 0)],
}

# Potions heal a fixed amount that depends on the potion's quality rank, and
# talents and buffs change it further. Each player's own heals from the same
# report are used when they drank one there; otherwise these typical amounts
# (median heal measured across real logs of that tier) stand in.
POTION_TYPICAL = {
    "Algari Healing Potion": 4_200_000, "Invigorating Healing Potion": 6_600_000,
    "Silvermoon Health Potion": 230_000, "Concentrated Silvermoon Health Potion": 390_000,
    "Potent Healing Potion": 200_000,
}

# Buffs that live on a spell the button doesn't point to in the game data.
AURA_SPELLS = {"Fortifying Brew": [120954], "Rallying Cry": [97463], "Renewing Blaze": [374349]}

# talent -> catalog spell whose modifier it copies onto potions and Healthstones.
ALSO_CONSUMABLES = {"Iron Stomach": 185311}

# Healthstone extras that come from a talent rather than the item: Soulburn
# makes a Warlock's Healthstone also raise max health (Soulburn: Healthstone).
SOULBURN = (385899, 387636)       # talent spell, the buff it adds to a Healthstone

# SpellModOp values that change one effect's value -> that effect's index.
MOD_OP_EFFECT_INDEX = {3: 0, 12: 1, 23: 2, 32: 3, 33: 4}
MOD_OP_ALL = 0          # percent modifier on all of a spell's healing / absorb amounts
MOD_OP_COOLDOWN = 11
AURA_ADD_MOD, AURA_PCT_MOD = "107", "108"
AURA_MAX_CHARGES = "411"            # +N charges of a charge category
AURA_CHARGE_RECOVERY_FLAT = "453"   # +ms to a charge category's recharge
AURA_CHARGE_RECOVERY_PCT = "454"    # +% to a charge category's recharge
AURA_HEALING_TAKEN_PCT = "118"      # healing taken +%
ALL_SCHOOLS = "127"
SPELL_ATTR0_PASSIVE = 0x40
AURA_OVERRIDE_BUTTON = "332"        # base points = new spell, misc value = the button it replaces
FIELDS = ("immune", "dr", "absorb", "hp", "heal")

# Cooldowns the game data stores elsewhere (seconds).
COOLDOWN_FALLBACK = {196555: 180, 374348: 90, 184662: 90}

# At or above this base cooldown an ability counts toward the "died with a
# major defensive available" summary; shorter ones are listed but not scored.
MAJOR_COOLDOWN_S = 60

# Game versions: one catalog per patch from The War Within's first raid tier
# (Nerub-ar Palace, 11.0.2) on. Each patch uses its last build (hotfixes in).
FIRST_PATCH = (11, 0, 2)
WAGO = "https://wago.tools/db2/{}/csv"
WAGO_BUILDS = "https://wago.tools/api/builds"
CACHE_DIR = os.environ.get("WAGO_CACHE")     # optional: keep downloaded tables here


def _get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    return urllib.request.urlopen(req, timeout=600).read()


def table(name, build=None):
    path = CACHE_DIR and os.path.join(CACHE_DIR, f"{name}_{build or 'live'}.csv.gz")
    if path and os.path.exists(path):
        with gzip.open(path, "rt", encoding="utf-8") as f:
            return list(csv.DictReader(f))
    data = _get(WAGO.format(name) + (f"?build={build}" if build else ""))
    if path:
        os.makedirs(CACHE_DIR, exist_ok=True)
        with gzip.open(path, "wb") as f:
            f.write(data)
    return list(csv.DictReader(io.StringIO(data.decode("utf-8"))))


def patches():
    """[(patch, first live date, last build)] for every retail patch since FIRST_PATCH."""
    found = {}
    for b in json.loads(_get(WAGO_BUILDS))["wow"]:
        if b.get("is_bgdl"):
            continue
        parts = tuple(int(x) for x in b["version"].split("."))
        if parts[:3] < FIRST_PATCH:
            continue
        patch = ".".join(map(str, parts[:3]))
        first, last = found.get(patch, (None, None))
        day = b["created_at"][:10]
        found[patch] = (min(first or day, day),
                        max(last or b["version"], b["version"], key=lambda v: [int(x) for x in v.split(".")]))
    return sorted(((p, d, v) for p, (d, v) in found.items()), key=lambda x: [int(n) for n in x[0].split(".")])


class GameData:
    """The tables one patch's catalog needs, indexed."""

    def __init__(self, build):
        self.names = {int(r["ID"]): r["Name_lang"] for r in table("SpellName", build)}
        self.effects = {}                         # spell -> {index: row} (base difficulty)
        self.by_aura = {}                         # aura -> [rows]
        self.triggers = {}
        for r in table("SpellEffect", build):
            if r["DifficultyID"] != "0":
                continue
            sid = int(r["SpellID"])
            self.effects.setdefault(sid, {})[int(r["EffectIndex"])] = r
            self.by_aura.setdefault(r["EffectAura"], []).append(r)
            if int(r["EffectTriggerSpell"] or 0):
                self.triggers.setdefault(sid, set()).add(int(r["EffectTriggerSpell"]))
        self.cooldowns = {int(r["SpellID"]): max(int(r["RecoveryTime"]), int(r["CategoryRecoveryTime"]))
                          for r in table("SpellCooldowns", build) if r["DifficultyID"] == "0"}
        self.charge_cat = {int(r["SpellID"]): int(r["ChargeCategory"])
                           for r in table("SpellCategories", build) if r["DifficultyID"] == "0"}
        self.charges = {int(r["ID"]): (int(r["MaxCharges"]), int(r["ChargeRecoveryTime"]))
                        for r in table("SpellCategory", build)}
        self.family = {int(r["SpellID"]): (int(r["SpellClassSet"]),
                                           [int(r[f"SpellClassMask_{i}"]) & 0xffffffff for i in range(4)])
                       for r in table("SpellClassOptions", build)}
        misc_rows = [r for r in table("SpellMisc", build) if r["DifficultyID"] == "0"]
        misc = {int(r["SpellID"]): int(r["DurationIndex"]) for r in misc_rows}
        # Always-on spells (talents and passives, not buttons or temporary buffs).
        self.passive = {int(r["SpellID"]) for r in misc_rows if int(r["Attributes_0"]) & SPELL_ATTR0_PASSIVE}
        length = {int(r["ID"]): int(r["MaxDuration"]) for r in table("SpellDuration", build)}
        self.duration = {sid: length.get(i, 0) for sid, i in misc.items()}
        self.definitions = table("TraitDefinition", build)
        self.node_entries = table("TraitNodeEntry", build)
        specs = {r["ID"]: r["Name_lang"] for r in table("ChrSpecialization", build)}
        self.spec_spells = {}                     # passive spell -> spec names it belongs to
        for r in table("SpecializationSpells", build):
            if r["SpecID"] in specs:
                self.spec_spells.setdefault(int(r["SpellID"]), set()).add(specs[r["SpecID"]])

    def value(self, spell, index):
        r = self.effects.get(spell, {}).get(index)
        return float(r["EffectBasePointsF"]) if r else None


def data_value(field, gd, spell, index, ticks):
    """An effect's base value from the game data, as the catalog stores it."""
    bp = gd.value(spell, index)
    if bp is None:
        return None
    if field == "dr":
        return round(abs(bp) / 100, 4)
    if field in ("heal", "hp"):
        return round(bp / 100 * ticks, 4)
    return None


class Modifiers:
    """Talents and spec passives that change a catalog ability.

    Each modifier names who gets it: "entries" (talent-tree entries; a player
    has it when their loadout includes one, scaled by rank) or "specs" (a spec
    passive every player of that spec has).
    """

    def __init__(self, gd):
        self.gd = gd
        entries_for_def = {}
        for r in gd.node_entries:
            entries_for_def.setdefault(int(r["TraitDefinitionID"]), set()).add(int(r["ID"]))
        self.entries_for_spell = {}               # talent spell -> trait node entries that grant it
        for r in gd.definitions:
            if r.get("SpellID") and r["SpellID"] != "0":
                self.entries_for_spell.setdefault(int(r["SpellID"]), set()).update(
                    entries_for_def.get(int(r["ID"]), ()))

    def who(self, spell):
        """{"entries": [...]} or {"specs": [...]} for a modifier source, or None if nobody gets it."""
        entries = self.entries_for_spell.get(spell)
        if entries:
            return {"entries": sorted(entries)}
        specs = self.gd.spec_spells.get(spell)
        if specs:
            return {"specs": sorted(specs)}
        return None

    def _covers(self, row, spell):
        fam, mask = self.gd.family.get(spell, (None, [0] * 4))
        if self.gd.family.get(int(row["SpellID"]), (None,))[0] != fam:
            return False
        m = [int(row[f"EffectSpellClassMask_{i}"]) & 0xffffffff for i in range(4)]
        return any(a & b for a, b in zip(m, mask))

    def _source_rows(self, aura):
        """Effects of always-on talents and spec passives. A talent that is a
        button (Incarnation) changes things only while active, so it's skipped."""
        for r in self.gd.by_aura.get(aura, ()):
            if int(r["SpellID"]) not in self.gd.passive:
                continue
            who = self.who(int(r["SpellID"]))
            if who and float(r["EffectBasePointsF"]):
                yield r, who

    def effect(self, spell, index, field, ticks):
        """Modifiers of one effect value (a reduction, heal, max health or absorb)."""
        found = []
        for aura in (AURA_ADD_MOD, AURA_PCT_MOD):
            pct = aura == AURA_PCT_MOD
            for r, who in self._source_rows(aura):
                if not self._covers(r, spell):
                    continue
                op, value = int(r["EffectMiscValue_0"]), float(r["EffectBasePointsF"])
                if MOD_OP_EFFECT_INDEX.get(op) != index and not (
                        op == MOD_OP_ALL and pct and field in ("heal", "absorb")):
                    continue
                if field == "immune" or (field == "absorb" and not pct):
                    continue   # absorbs scale with stats: only percent changes apply
                mod = {"talent": self.gd.names.get(int(r["SpellID"])), **who}
                if pct:
                    mod["mult"] = round(1 + value / 100, 4)
                else:
                    # Reductions are negative in the data; heals/health are % of max health.
                    mod["add"] = round((-value if field == "dr" else value) / 100 * ticks, 4)
                found.append(mod)
        return _dedupe(found)

    def cooldown(self, spell):
        """Cooldown / recharge modifiers: {"add_ms"} or {"mult"}."""
        found = []
        for aura in (AURA_ADD_MOD, AURA_PCT_MOD):
            for r, who in self._source_rows(aura):
                if int(r["EffectMiscValue_0"]) == MOD_OP_COOLDOWN and self._covers(r, spell):
                    value = float(r["EffectBasePointsF"])
                    mod = {"talent": self.gd.names.get(int(r["SpellID"])), **who}
                    if aura == AURA_PCT_MOD:
                        mod["mult"] = round(1 + value / 100, 4)
                    else:
                        mod["add_ms"] = int(value)
                    found.append(mod)
        cat = self.gd.charge_cat.get(spell, 0)
        if cat:
            for aura, key in ((AURA_CHARGE_RECOVERY_FLAT, "add_ms"), (AURA_CHARGE_RECOVERY_PCT, "mult")):
                for r, who in self._source_rows(aura):
                    if int(r["EffectMiscValue_0"]) == cat:
                        value = float(r["EffectBasePointsF"])
                        found.append({"talent": self.gd.names.get(int(r["SpellID"])), **who,
                                      key: int(value) if key == "add_ms" else round(1 + value / 100, 4)})
        return _dedupe(found)

    def charges(self, spell):
        cat = self.gd.charge_cat.get(spell, 0)
        if not cat:
            return []
        return _dedupe([{"talent": self.gd.names.get(int(r["SpellID"])), **who, "add": int(float(r["EffectBasePointsF"]))}
                        for r, who in self._source_rows(AURA_MAX_CHARGES) if int(r["EffectMiscValue_0"]) == cat])

    def healing_taken(self):
        """Talents and spec passives that raise (or lower) all healing the player takes."""
        return _dedupe([{"talent": self.gd.names.get(int(r["SpellID"])), **who,
                         "mult": round(1 + float(r["EffectBasePointsF"]) / 100, 4)}
                        for r, who in self._source_rows(AURA_HEALING_TAKEN_PCT)
                        if r["EffectMiscValue_0"] == ALL_SCHOOLS])


def _dedupe(mods):
    seen, out = set(), []
    for m in mods:
        key = repr(sorted(m.items()))
        if key not in seen:
            seen.add(key)
            out.append(m)
    return out


def healing_taken_auras(gd, mods):
    """Buffs and debuffs (not talents) that change healing taken: spell -> multiplier.

    Matched against the auras WarcraftLogs lists on the player's heal events
    and killing blow, so temporary effects count only when they were up.
    """
    out = {}
    for r in gd.by_aura.get(AURA_HEALING_TAKEN_PCT, ()):
        sid, value = int(r["SpellID"]), float(r["EffectBasePointsF"])
        if value and r["EffectMiscValue_0"] == ALL_SCHOOLS and mods.who(sid) is None:
            out[sid] = round(out.get(sid, 1.0) * (1 + value / 100), 4)
    return out


def aura_duration(gd, sid, name):
    """Longest base duration (ms) of an ability's aura (the button, spells it triggers, effect spells).

    Logs sometimes miss the "aura removed" event (the player died, moved out
    of range...), so the analysis never treats an aura as still up much past this.
    """
    spells, frontier = {sid}, {sid}
    for _ in range(2):
        frontier = {t for s in frontier for t in gd.triggers.get(s, ())}
        spells |= frontier
    spells |= {e[1] for e in EFFECTS.get(name, ())} | set(AURA_SPELLS.get(name, ()))
    found = [gd.duration.get(s, 0) for s in spells if gd.names.get(s) == name]
    return max(found, default=0) or None


def components(name, gd, mods, problems):
    """One component per effect of an ability, base values from this patch's data, with talent modifiers.

    A component: {<field>: value, "school"?, "observed"?, "mods"?: [...]} where
    field is dr / absorb / hp / heal (fractions of damage or of max health) or
    immune. Absorbs are "observed": the player's real shield size from the log
    wins over the estimate. Returns None when the ability can't be scored.
    """
    values = MITIGATION.get(name)
    if values is None:
        return None
    out, used = [], set()
    for eff in EFFECTS.get(name) or [(f, None, None) for f in FIELDS if f in values]:
        field, spell, index = eff[:3]
        ticks = eff[3] if len(eff) > 3 else 1
        comp = {}
        if field in values and field not in used:
            base = values[field]
            if spell is not None and field in ("dr", "heal", "hp"):
                from_data = data_value(field, gd, spell, index, ticks)
                if from_data is None:
                    problems.append(f"{name}: effect {index} of spell {spell} is missing")
                elif base:
                    base = from_data
            comp[field] = base
            if values.get("school") not in (None, "all"):
                comp["school"] = values["school"]
            used.add(field)
        else:
            comp[field] = 0.0          # filled in only by a talent
        if field == "absorb":
            comp["observed"] = True
        if spell is not None:
            m = mods.effect(spell, index, field, ticks)
            if m:
                comp["mods"] = m
        if comp[field] or comp.get("mods") or comp.get("observed"):
            out.append(comp)
    for field in FIELDS:           # values without a mapped effect (e.g. Fortifying Brew)
        if field in values and field not in used:
            comp = {field: values[field]}
            if values.get("school") not in (None, "all"):
                comp["school"] = values["school"]
            out.append(comp)
    return out


def build_catalog(build):
    """The catalog for one game build. Returns (catalog, healing-taken info, problems)."""
    gd = GameData(build)
    mods = Modifiers(gd)
    names = gd.names
    curated_by_name = {name: sid for sid, name, _, _, _ in CURATED if name in NAME_ALIAS_OK}
    def_spell = {}
    replaced_by_def = {}   # spell -> talent definitions that replace it (Ice Cold replaces Ice Block)
    for r in gd.definitions:
        if r.get("OverridesSpellID") and r["OverridesSpellID"] != "0":
            replaced_by_def.setdefault(int(r["OverridesSpellID"]), set()).add(int(r["ID"]))
        # A talent spell that swaps a button on the action bar (aura 332:
        # Ice Cold's talent 414659 puts Ice Cold 414658 in place of Ice Block)
        # grants the new button and replaces the old one.
        for eff in gd.effects.get(int(r["SpellID"] or 0), {}).values():
            if eff["EffectAura"] == AURA_OVERRIDE_BUTTON and float(eff["EffectBasePointsF"]):
                def_spell.setdefault(int(r["ID"]), set()).add(int(float(eff["EffectBasePointsF"])))
                replaced_by_def.setdefault(int(eff["EffectMiscValue_0"]), set()).add(int(r["ID"]))
        for k in ("SpellID", "VisibleSpellID"):
            if r.get(k) and r[k] != "0":
                sid = int(r[k])
                def_spell.setdefault(int(r["ID"]), set()).add(sid)
                # Some talents grant the button through a differently numbered
                # "talent" spell with the same name (Fortifying Brew 388917 -> 115203).
                alias = curated_by_name.get(names.get(sid))
                if alias:
                    def_spell[int(r["ID"])].add(alias)
    entries_for_spell, entries_for_def = {}, {}
    for r in gd.node_entries:
        entries_for_def.setdefault(int(r["TraitDefinitionID"]), set()).add(int(r["ID"]))
        for sid in def_spell.get(int(r["TraitDefinitionID"]), ()):
            entries_for_spell.setdefault(sid, set()).add(int(r["ID"]))

    catalog, problems, missing = {}, [], []
    for sid, name, cls, specs, kind in CURATED:
        if sid not in names:
            missing.append(name)     # not in the game yet (or any more) in this patch
            continue
        if names[sid] != name:
            problems.append(f"{sid}: expected {name!r}, game data says {names[sid]!r}")
            continue
        max_charges, charge_ms = gd.charges.get(gd.charge_cat.get(sid, 0), (0, 0))
        cd_ms = gd.cooldowns.get(sid, 0)
        if charge_ms and max_charges:
            cd_ms = charge_ms
        if cd_ms < 1500 and sid in COOLDOWN_FALLBACK:
            cd_ms = COOLDOWN_FALLBACK[sid] * 1000
        entries = sorted(entries_for_spell.get(sid, ()))
        replaced_by = sorted({e for d in replaced_by_def.get(sid, ()) for e in entries_for_def.get(d, ())}
                             - set(entries))
        if kind in ("personal", "external"):
            known = "baseline" if sid in BASELINE else ("talent" if entries else "evidence")
        else:
            known = "baseline"
        entry = {
            "name": name, "class": cls, "specs": specs, "kind": kind, "known": known,
            "cooldown_ms": cd_ms, "charges": max(max_charges, 1),
            "major": cd_ms >= MAJOR_COOLDOWN_S * 1000, "talent_entries": entries,
            "replaced_by_entries": replaced_by,
            "mitigation": components(name, gd, mods, problems),
            "aura_ms": aura_duration(gd, sid, name) if kind in ("personal", "external") else None,
        }
        if kind in ("personal", "external"):
            if mods.cooldown(sid):
                entry["cooldown_mods"] = mods.cooldown(sid)
            if mods.charges(sid):
                entry["charge_mods"] = mods.charges(sid)
        if kind == "potion" and POTION_TYPICAL.get(name):
            entry["mitigation"] = [{"heal_amount": POTION_TYPICAL[name], "observed": True}]
        catalog[sid] = entry

    # Talents that also reach consumables (item spells share no class mask with
    # the talent, so the game data can't link them): Iron Stomach boosts
    # healing potions and Healthstones too, per its tooltip.
    for sid, entry in catalog.items():
        if entry["kind"] not in ("healthstone", "potion") or not entry["mitigation"]:
            continue
        for talent, source in ALSO_CONSUMABLES.items():
            if source not in catalog:
                continue
            mod = next((m for c in catalog[source]["mitigation"] or [] for m in c.get("mods", ())
                        if m["talent"] == talent), None)
            if mod is None:
                continue
            for comp in entry["mitigation"]:
                if "heal" in comp or "heal_amount" in comp:
                    comp.setdefault("mods", []).append(dict(mod))
        if entry["kind"] == "healthstone":
            talent, buff = SOULBURN
            who, hp = mods.who(talent), None
            for r in gd.effects.get(buff, {}).values():
                if r["EffectAura"] == "133":          # max health +%
                    hp = float(r["EffectBasePointsF"]) / 100
            if who and hp:
                entry["mitigation"].append({"hp": 0.0, "mods": [{"talent": names.get(talent), **who, "add": hp}]})
    heal = {"talents": mods.healing_taken(), "auras": healing_taken_auras(gd, mods)}
    return catalog, heal, problems, missing


def main():
    only = sys.argv[1:]
    all_patches = patches()
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "defensive_catalog.py")
    catalogs, healing, starts = {}, {}, []
    for patch, first_day, build in all_patches:
        if only and patch not in only:
            continue
        print(f"{patch} (live {first_day}, build {build})...", flush=True)
        catalog, heal, problems, missing = build_catalog(build)
        latest = patch == all_patches[-1][0]
        if problems and latest:
            raise SystemExit(f"{patch}: spell data changed; update CURATED / EFFECTS:\n  " + "\n  ".join(problems))
        for p in problems:
            print(f"  note: {p}")
        if missing:
            print(f"  not in this patch: {', '.join(missing)}")
        catalogs[patch] = catalog
        healing[patch] = heal
        starts.append((first_day, patch))
    if only:
        raise SystemExit("Built " + ", ".join(catalogs) + " (dry run: the catalog file is only written for all patches).")
    with open(out, "w") as f:
        f.write('"""GENERATED by scripts/build_defensive_catalog.py from wago.tools game data.\n'
                'Edit the curated lists in that script, not this file.\n\n'
                'One catalog per game patch; a report uses the patch that was live when it was logged."""\n\n')
        f.write("# (first day live, patch), oldest first\n")
        f.write("PATCHES = " + pprint.pformat(starts, width=110) + "\n\n")
        f.write("CATALOGS = " + pprint.pformat(catalogs, width=150, sort_dicts=True) + "\n\n")
        f.write("# Healing-taken modifiers per patch: talents / spec passives, and buffs or debuffs by aura ID.\n")
        f.write("HEALING_TAKEN = " + pprint.pformat(healing, width=150, sort_dicts=True) + "\n\n")
        f.write("LATEST = PATCHES[-1][1]\nCATALOG = CATALOGS[LATEST]\n")
    print(f"Wrote {len(catalogs)} patches to {os.path.normpath(out)}")


if __name__ == "__main__":
    main()
