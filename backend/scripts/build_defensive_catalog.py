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

# Cooldowns the game data stores elsewhere (seconds).
COOLDOWN_FALLBACK = {196555: 180, 374348: 90, 184662: 90}

# At or above this base cooldown an ability counts toward the "died with a
# major defensive available" summary; shorter ones are listed but not scored.
MAJOR_COOLDOWN_S = 60

WAGO = "https://wago.tools/db2/{}/csv"


def table(name):
    req = urllib.request.Request(WAGO.format(name), headers={"User-Agent": "Mozilla/5.0"})
    return list(csv.DictReader(io.StringIO(urllib.request.urlopen(req, timeout=300).read().decode("utf-8"))))


def main():
    names = {int(r["ID"]): r["Name_lang"] for r in table("SpellName")}
    cooldowns = {int(r["SpellID"]): max(int(r["RecoveryTime"]), int(r["CategoryRecoveryTime"]))
                 for r in table("SpellCooldowns") if r["DifficultyID"] == "0"}
    charge_cat = {int(r["SpellID"]): int(r["ChargeCategory"])
                  for r in table("SpellCategories") if r["DifficultyID"] == "0"}
    charges = {int(r["ID"]): (int(r["MaxCharges"]), int(r["ChargeRecoveryTime"])) for r in table("SpellCategory")}
    curated_by_name = {name: sid for sid, name, _, _, _ in CURATED if name in NAME_ALIAS_OK}
    def_spell = {}
    replaced_by_def = {}   # spell -> talent definitions that replace it (Ice Cold replaces Ice Block)
    for r in table("TraitDefinition"):
        if r.get("OverridesSpellID") and r["OverridesSpellID"] != "0":
            replaced_by_def.setdefault(int(r["OverridesSpellID"]), set()).add(int(r["ID"]))
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
        }
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
