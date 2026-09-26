"""Regenerate backend/defensive_catalog.py from the live game data on wago.tools.

The curated list below decides WHICH abilities count and for whom; the game
data supplies cooldowns, charges, and the talent-tree entries that grant each
ability (so a player is only expected to have what they actually talented).

Run after a patch:  python backend/scripts/build_defensive_catalog.py
Needs network access to wago.tools.
"""
import csv, io, os, pprint, urllib.request

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
    # Consumables: medians measured across real Midnight logs.
    "Healthstone": {"heal": .25}, "Demonic Healthstone": {"heal": .60},
    "Silvermoon Health Potion": {"heal": .26}, "Concentrated Silvermoon Health Potion": {"heal": .44},
    "Potent Healing Potion": {"heal": .24}, "Invigorating Healing Potion": {"heal": .25},
    "Algari Healing Potion": {"heal": .25},
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
    "Healthstone": [("heal", 6262, 0)],
}

# Buffs that live on a spell the button doesn't point to in the game data.
AURA_SPELLS = {"Fortifying Brew": [120954], "Rallying Cry": [97463], "Renewing Blaze": [374349]}


def aura_durations(names):
    """name -> longest base duration (ms) of that ability's aura, from SpellMisc/SpellDuration.

    Logs sometimes miss the "aura removed" event (the player died, moved out
    of range...), so the analysis never treats an aura as still up much past
    this. Looks at the button, the spells it triggers, and the effect spells.
    """
    triggers = {}
    for r in table("SpellEffect"):
        if r["DifficultyID"] == "0" and int(r["EffectTriggerSpell"] or 0):
            triggers.setdefault(int(r["SpellID"]), set()).add(int(r["EffectTriggerSpell"]))
    index = {int(r["SpellID"]): int(r["DurationIndex"]) for r in table("SpellMisc") if r["DifficultyID"] == "0"}
    length = {int(r["ID"]): int(r["MaxDuration"]) for r in table("SpellDuration")}

    def duration(sid, name):
        spells, frontier = {sid}, {sid}
        for _ in range(2):
            frontier = {t for s in frontier for t in triggers.get(s, ())}
            spells |= frontier
        spells |= {e[1] for e in EFFECTS.get(name, ())} | set(AURA_SPELLS.get(name, ()))
        found = [length.get(index.get(s, 0), 0) for s in spells if names.get(s) == name]
        return max(found, default=0) or None
    return duration


# talent -> catalog spell whose modifier it copies onto potions and Healthstones.
ALSO_CONSUMABLES = {"Iron Stomach": 185311}

# SpellModOp values that change one effect's value -> that effect's index.
MOD_OP_EFFECT_INDEX = {3: 0, 12: 1, 23: 2, 32: 3, 33: 4}
MOD_OP_ALL = 0          # percent modifier on all of a spell's healing / absorb amounts
FIELDS = ("immune", "dr", "absorb", "hp", "heal")


def components(name, values, effects, mods_for):
    """Split a MITIGATION entry into one component per effect, with talent modifiers.

    A component: {<field>: value, "school"?, "observed"?, "mods"?: [...]} where
    field is dr / absorb / hp / heal (fractions of damage or of max health) or
    immune. Absorbs are "observed": the player's real shield size from the log
    wins over the estimate. Returns None when the ability can't be scored.
    """
    if values is None:
        return None
    out, used = [], set()
    for eff in effects or [(f, None, None) for f in FIELDS if f in values]:
        field, spell, index = eff[:3]
        ticks = eff[3] if len(eff) > 3 else 1
        comp = {}
        if field in values and field not in used:
            comp[field] = values[field]
            if values.get("school") not in (None, "all"):
                comp["school"] = values["school"]
            used.add(field)
        else:
            comp[field] = 0.0          # filled in only by a talent
        if field == "absorb":
            comp["observed"] = True
        if spell is not None:
            mods = mods_for(spell, index, field, ticks)
            if mods:
                comp["mods"] = mods
        if comp[field] or comp.get("mods") or comp.get("observed"):
            out.append(comp)
    for field in FIELDS:           # values without a mapped effect (e.g. Fortifying Brew)
        if field in values and field not in used:
            comp = {field: values[field]}
            if values.get("school") not in (None, "all"):
                comp["school"] = values["school"]
            out.append(comp)
    return out


# Cooldowns the game data stores elsewhere (seconds).
COOLDOWN_FALLBACK = {196555: 180, 374348: 90, 184662: 90}

# At or above this base cooldown an ability counts toward the "died with a
# major defensive available" summary; shorter ones are listed but not scored.
MAJOR_COOLDOWN_S = 60

WAGO = "https://wago.tools/db2/{}/csv"


def table(name):
    req = urllib.request.Request(WAGO.format(name), headers={"User-Agent": "Mozilla/5.0"})
    return list(csv.DictReader(io.StringIO(urllib.request.urlopen(req, timeout=300).read().decode("utf-8"))))


def talent_modifiers(names, def_spell_plain):
    """Return mods_for(spell, effect_index, field, ticks) -> talent modifiers of that value."""
    effects = {}
    for r in table("SpellEffect"):
        if r["DifficultyID"] == "0" and r["EffectAura"] in ("107", "108"):
            effects.setdefault(int(r["SpellID"]), []).append(r)
    family = {int(r["SpellID"]): (int(r["SpellClassSet"]), [int(r[f"SpellClassMask_{i}"]) & 0xffffffff for i in range(4)])
              for r in table("SpellClassOptions")}
    entries_for_def = {}
    for r in table("TraitNodeEntry"):
        entries_for_def.setdefault(int(r["TraitDefinitionID"]), set()).add(int(r["ID"]))
    talent_entries = {}    # talent spell -> trait node entries that grant it
    for d, sid in def_spell_plain.items():
        talent_entries.setdefault(sid, set()).update(entries_for_def.get(d, ()))

    def mods_for(spell, index, field, ticks):
        fam, mask = family.get(spell, (None, [0] * 4))
        found = []
        for tsid, entries in sorted(talent_entries.items()):
            if not entries or family.get(tsid, (None,))[0] != fam:
                continue
            for r in effects.get(tsid, ()):
                m = [int(r[f"EffectSpellClassMask_{i}"]) & 0xffffffff for i in range(4)]
                if not any(a & b for a, b in zip(m, mask)):
                    continue
                op, pct = int(r["EffectMiscValue_0"]), r["EffectAura"] == "108"
                value = float(r["EffectBasePointsF"])
                if not value:
                    continue
                if MOD_OP_EFFECT_INDEX.get(op) != index and not (
                        op == MOD_OP_ALL and pct and field in ("heal", "absorb")):
                    continue
                if field == "immune" or (field == "absorb" and not pct):
                    continue   # absorbs scale with stats: only percent changes apply
                mod = {"talent": names.get(tsid), "entries": sorted(entries)}
                if pct:
                    mod["mult"] = round(1 + value / 100, 4)
                else:
                    # Reductions are negative in the data; heals/health are % of max health.
                    mod["add"] = round((-value if field == "dr" else value) / 100 * ticks, 4)
                found.append(mod)
        return found
    return mods_for


def main():
    names = {int(r["ID"]): r["Name_lang"] for r in table("SpellName")}
    cooldowns = {int(r["SpellID"]): max(int(r["RecoveryTime"]), int(r["CategoryRecoveryTime"]))
                 for r in table("SpellCooldowns") if r["DifficultyID"] == "0"}
    charge_cat = {int(r["SpellID"]): int(r["ChargeCategory"])
                  for r in table("SpellCategories") if r["DifficultyID"] == "0"}
    charges = {int(r["ID"]): (int(r["MaxCharges"]), int(r["ChargeRecoveryTime"])) for r in table("SpellCategory")}
    curated_by_name = {name: sid for sid, name, _, _, _ in CURATED if name in NAME_ALIAS_OK}
    def_spell = {}
    def_spell_plain = {}   # TraitDefinition -> its own SpellID (no name aliases)
    replaced_by_def = {}   # spell -> talent definitions that replace it (Ice Cold replaces Ice Block)
    for r in table("TraitDefinition"):
        if r.get("OverridesSpellID") and r["OverridesSpellID"] != "0":
            replaced_by_def.setdefault(int(r["OverridesSpellID"]), set()).add(int(r["ID"]))
        if r.get("SpellID") and r["SpellID"] != "0":
            def_spell_plain[int(r["ID"])] = int(r["SpellID"])
        for k in ("SpellID", "VisibleSpellID"):
            if r.get(k) and r[k] != "0":
                sid = int(r[k])
                def_spell.setdefault(int(r["ID"]), set()).add(sid)
                # Some talents grant the button through a differently numbered
                # "talent" spell with the same name (Fortifying Brew 388917 -> 115203).
                alias = curated_by_name.get(names.get(sid))
                if alias:
                    def_spell[int(r["ID"])].add(alias)
    mods_for = talent_modifiers(names, def_spell_plain)
    aura_ms = aura_durations(names)
    entries_for_spell, entries_for_def = {}, {}
    for r in table("TraitNodeEntry"):
        entries_for_def.setdefault(int(r["TraitDefinitionID"]), set()).add(int(r["ID"]))
        for sid in def_spell.get(int(r["TraitDefinitionID"]), ()):
            entries_for_spell.setdefault(sid, set()).add(int(r["ID"]))

    catalog, problems = {}, []
    for sid, name, cls, specs, kind in CURATED:
        if names.get(sid) != name:
            problems.append(f"{sid}: expected {name!r}, game data says {names.get(sid)!r}")
        max_charges, charge_ms = charges.get(charge_cat.get(sid, 0), (0, 0))
        cd_ms = cooldowns.get(sid, 0)
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
        catalog[sid] = {
            "name": name, "class": cls, "specs": specs, "kind": kind, "known": known,
            "cooldown_ms": cd_ms, "charges": max(max_charges, 1),
            "major": cd_ms >= MAJOR_COOLDOWN_S * 1000, "talent_entries": entries,
            "replaced_by_entries": replaced_by,
            "mitigation": components(name, MITIGATION.get(name), EFFECTS.get(name), mods_for),
            "aura_ms": aura_ms(sid, name) if kind in ("personal", "external") else None,
        }
    # Talents that also reach consumables (item spells share no class mask with
    # the talent, so the game data can't link them): Iron Stomach boosts
    # healing potions and Healthstones too, per its tooltip.
    for sid, entry in catalog.items():
        if entry["kind"] not in ("healthstone", "potion") or not entry["mitigation"]:
            continue
        for talent, source in ALSO_CONSUMABLES.items():
            mod = next((m for c in catalog[source]["mitigation"] or [] for m in c.get("mods", ())
                        if m["talent"] == talent), None)
            if mod is None:
                problems.append(f"{talent} no longer modifies {catalog[source]['name']}; check ALSO_CONSUMABLES")
                continue
            for comp in entry["mitigation"]:
                if "heal" in comp:
                    comp.setdefault("mods", []).append(dict(mod))
    if problems:
        raise SystemExit("Spell names changed; update CURATED:\n  " + "\n  ".join(problems))

    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "defensive_catalog.py")
    with open(out, "w") as f:
        f.write('"""GENERATED by scripts/build_defensive_catalog.py from wago.tools game data.\n'
                'Edit the curated list in that script, not this file."""\n\n')
        f.write("CATALOG = " + pprint.pformat(catalog, width=110, sort_dicts=True) + "\n")
    print(f"Wrote {len(catalog)} abilities to {os.path.normpath(out)}")


if __name__ == "__main__":
    main()
