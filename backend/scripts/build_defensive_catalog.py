"""Regenerate backend/defensive_catalog.py from the live game data on wago.tools.

The curated list below decides WHICH abilities count and for whom; the game
data supplies cooldowns, charges, and the talent-tree entries that grant each
ability (so a player is only expected to have what they actually talented).

Run after a patch:  python backend/scripts/build_defensive_catalog.py
Needs network access to wago.tools.
"""
import csv, gzip, io, json, os, pprint, re, sys, urllib.request

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
    # Every druid can shift; for Guardians it's their normal form, not a defensive.
    (5487, "Bear Form", "Druid", ["Balance", "Feral", "Restoration"], "personal"),
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
            48707, 122470, 5487}

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
    "Blur": {"dr": .25, "dur": 10},
    # "Increasing current health by 40%, healing for that amount, and increasing Armor by 200%".
    "Metamorphosis": {"hp": .40, "heal": .40, "armor": 2.0, "dur": 15},
    "Fiery Brand": {"dr": .40, "dur": 10}, "Netherwalk": {"immune": True, "dur": 2},
    "Barkskin": {"dr": .20, "dur": 8}, "Survival Instincts": {"dr": .50, "dur": 6},
    "Renewal": {"heal": .30},
    "Obsidian Scales": {"dr": .30, "dur": 12},
    "Aspect of the Turtle": {"dr": .30, "dur": 8}, "Exhilaration": {"heal": .30},
    "Survival of the Fittest": {"dr": .30, "dur": 6},
    "Ice Block": {"immune": True, "dur": 10}, "Ice Cold": {"dr": .70, "dur": 6},
    "Blazing Barrier": {"absorb": .30, "dur": 60}, "Ice Barrier": {"absorb": .35, "dur": 60},
    "Prismatic Barrier": {"absorb": .30, "dr": .15, "dur": 60},
    "Mirror Image": {"dr": .20},
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
    # +25% Stamina (max health, health share kept) and +220% armor; its magic
    # reductions come from the game data (Bear Form Passive 2 and the form itself).
    "Bear Form": {"hp": .25, "armor": 2.2},
    # Shields whose size depends on stats or resources: scored only from the
    # player's real shield size seen in the log (absorb=None).
    "Celestial Brew": {"absorb": None}, "Tombstone": {"absorb": None},
    "Stone Bulwark Totem": {"absorb": None},
    # Leech and immunity to charm/fear only, unless Unholy Endurance adds a reduction (TALENT_EFFECTS).
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
    # Effect 2 is absorbs received, not max health; 0 is healing received.
    "Vampiric Blood": [("hp", 55233, 3), ("heal_taken", 55233, "aura:118")],
    "Death Pact": [("heal", 48743, 0)],
    "Anti-Magic Shell": [("absorb", 48707, 0), ("heal_taken", 48707, "aura:118", {"optional": True})],
    "Blur": [("dr", 212800, 2)],
    "Metamorphosis": [("hp", 187827, "aura:133"), ("armor", 187827, "aura:142", {"optional": True}),
                      ("vers", 187827, "aura:471", {"optional": True})],
    "Fiery Brand": [("dr", 207771, 0)],
    "Barkskin": [("dr", 22812, 0), ("heal_taken", 22812, "aura:118", {"optional": True})],
    "Survival Instincts": [("dr", 50322, 0)],
    "Renewal": [("heal", 108238, 0)],
    "Frenzied Regeneration": [("heal", 22842, 0, 3), ("heal_taken", 22842, "aura:118", {"optional": True})],
    # Its own magic reductions only with Glistening Fur (a script); Bear Form
    # Passive 2's only with Empowered Shapeshifting (a modifier on a 0 base).
    "Bear Form": [("hp", 1178, "aura:137"), ("armor", 5487, "aura:142"),
                  ("dr", 5487, "aura:87", {"optional": True, "needs": "Glistening Fur"}),
                  ("dr", 21178, "aura:87", {"optional": True})],
    "Obsidian Scales": [("dr", 363916, 0)],
    "Aspect of the Turtle": [("dr", 186265, 3)], "Exhilaration": [("heal", 109304, 0)],
    "Survival of the Fittest": [("dr", 264735, 0)],
    "Ice Cold": [("dr", 414658, 7)], "Greater Invisibility": [("dr", 113862, 0)],
    "Blazing Barrier": [("absorb", 235313, 0)],
    # Improved Ice Barrier (Midnight) fills in a physical reduction on a 0 base.
    "Ice Barrier": [("absorb", 11426, 0), ("dr", 11426, "aura:87", {"optional": True})],
    "Prismatic Barrier": [("absorb", 235450, 0), ("dr", 235450, "aura:87")],
    "Mirror Image": [("dr", 55342, "aura:87", {"optional": True})],
    "Diffuse Magic": [("dr", 122783, 0)], "Touch of Karma": [("absorb", 122470, 1)],
    "Celestial Brew": [("absorb", 322507, 0)], "Zen Meditation": [("dr", 115176, 1)],
    "Ardent Defender": [("dr", 31850, "aura:87"), ("hp", 31850, "aura:137", {"optional": True}),
                        ("heal_taken", 31850, "aura:118", {"optional": True})],
    "Divine Protection": [("dr", 498, 0), ("heal_taken", 498, "aura:118", {"optional": True})],
    "Guardian of Ancient Kings": [("dr", 86659, 2)], "Lay on Hands": [("heal", 633, 1)],
    "Shield of Vengeance": [("absorb", 184662, 0)],
    "Desperate Prayer": [("hp", 19236, 0), ("heal", 19236, 1)],
    "Dispersion": [("dr", 47585, 0)],
    # Fade reduces damage only with Translucent Image (a script in The War Within data).
    "Fade": [("dr", 586, "aura:87", {"needs": "Translucent Image"})],
    "Crimson Vial": [("heal", 185311, 0, 4)],
    "Feint": [("dr", 1966, 0), ("dr", 1966, 1)],
    # 1: all damage (Elusiveness); 2: magic, only with Bait and Switch (a script
    # in The War Within, a modifier on a 0 base in Midnight).
    "Evasion": [("immune", 5277, 0), ("dr", 5277, 1), ("dr", 5277, 2, 1, {"needs": "Bait and Switch"})],
    "Cloak of Shadows": [("immune", 31224, 0), ("dr", 31224, 2, 1, {"needs": "Bait and Switch"})],
    "Astral Shift": [("dr", 108271, 0)], "Stone Bulwark Totem": [("absorb", 114893, 0)],
    "Dark Pact": [("absorb", 108416, 0)], "Unending Resolve": [("dr", 104773, 2)],
    "Die by the Sword": [("dr", 118038, 1)], "Enraged Regeneration": [("dr", 184364, 0)],
    # "Increasing your current and maximum health": both rise by the same amount.
    # The button's own points carry the values the buff's script reads ($<health>, $<damage>),
    # and talents (Ironshell Brew) modify those.
    "Fortifying Brew": [("hp", 115203, 0, 1, {"current": True}), ("dr", 115203, 1)],
    "Last Stand": [("hp", 12975, 0), ("heal", 12975, 1)], "Shield Wall": [("dr", 871, 0)],
    "Spell Reflection": [("dr", 385391, 0)], "Tombstone": [("absorb", 219809, 0)],
    "Healthstone": [("heal", 6262, 0)], "Demonic Healthstone": [("heal", 452930, 0)],
}

# Effects a talent adds to a button that the game data doesn't attach to the
# button's own spell (a script, or a separate spell): talent -> [(button,
# field, value source, options)]. The value source is [(spell, effect)] whose
# base points are multiplied together ("talent" = the talent's own spell).
# Only players with the talent in that pull's loadout get them; a talent not in
# a patch's trees adds nothing there. Options: "over": a heal over time with
# that spell's duration and tick period ("per_tick": the value is per tick);
# "aura": a shield scored from its real size in the log.
TALENT_EFFECTS = {
    "Bloody Fortitude": [("Icebound Fortitude", "dr_missing", [("talent", 0)], {})],
    # The War Within: Lichborne's reduction (Midnight's talent only lengthens it).
    "Unholy Endurance": [("Lichborne", "dr", [(49039, "aura:87")], {"optional": True})],
    "Matted Fur": [("Barkskin", "absorb_aura", [], {"aura": "Matted Fur"}),
                   ("Survival Instincts", "absorb_aura", [], {"aura": "Matted Fur"})],
    "Fount of Strength": [("Frenzied Regeneration", "hp", [("talent", 2)], {})],
    "Ward of the Forest": [("Barkskin", "hp", [("talent", 1)], {})],
    "Empowered Shapeshifting": [],        # reaches Bear Form Passive 2 by label; also lifts FR's form need
    "Rejuvenating Wind": [("Exhilaration", "heal", [("talent", 0)], {"over": 385540})],
    "Den Recovery": [("Aspect of the Turtle", "heal", [("talent", 0)], {"over": 448777}),
                     ("Survival of the Fittest", "heal", [("talent", 0)], {"over": 448777})],
    "Niuzao's Protection": [("Fortifying Brew", "absorb", [(442749, 1)], {})],
    "Invigorating Fury": [("Enraged Regeneration", "heal", [("talent", 1)], {})],
    "Infernal Vitality": [("Unending Resolve", "heal", [(434559, "aura:20")], {"over": 434559, "per_tick": True})],
    "Infernal Bulwark": [("Unending Resolve", "absorb", [("talent", 0)], {})],
    "Friends In Dark Places": [("Dark Pact", "absorb", [(108416, 1), ("talent", 0)], {})],
    "Phantasmal Image": [],               # reaches Mirror Image by label
    # "For 4 sec after shifting into Bear Form, your health and armor are increased by 15%."
    "Ursine Vigor": [("Bear Form", "hp", [("talent", 0)], {}), ("Bear Form", "armor", [("talent", 0)], {})],
    "Mantra of Tenacity": [("Fortifying Brew", "absorb_aura", [], {"aura": "Chi Cocoon"})],
}

# Every talent that names a defensive in its tooltip with a survival word has
# been reviewed (all patches from 11.0.2): handled through the game data
# (modifiers), in TALENT_EFFECTS or EFFECTS "needs", or left out for the reason
# given. A new one fails the build of the current patch until it's reviewed.
TALENTS_REVIEWED = {
    # handled: modifiers on a mapped effect, EFFECTS "needs", TALENT_EFFECTS, or the form rule
    "Osmosis": "handled", "Improved Vampiric Blood": "handled", "Verdant Heart": "handled",
    "Ironshell Brew": "handled", "Improved Prismatic Barrier": "handled", "Improved Ardent Defender": "handled",
    "Translucent Image": "handled", "Bait and Switch": "handled", "First of the Illidari": "handled",
    "Gorebound Fortitude": "handled", "Ice Cold": "handled", "Pact of Gluttony": "handled",
    "Wildshape Mastery": "only keeps Frenzied Regeneration going after leaving Bear Form; casting still needs it",
    **{t: "handled" for t in TALENT_EFFECTS},
    # left out: not pressed by the player, after the hit, or not something that stops a hit
    "Blood Feast": "heals from damage absorbed: nothing before the killing blow",
    "Vestigial Shell": "shields allies", "Expelling Shield": "slows enemy casts",
    "Pact of the Deathbringer": "casts Death Pact by itself",
    "Red Thirst": "cooldown from resource spent (observed recasts cover it)",
    "Umbilicus Eternus": "after Vampiric Blood ends", "Insatiable Blade": "cooldown from Bone Shield",
    "Revel in Pain": "after Fiery Brand ends", "Flower Walk": "heals allies",
    "Brambles": "damages attackers", "Berserk: Persistence": "cooldown while another button is up",
    "Well-Honed Instincts": "casts Frenzied Regeneration by itself",
    "Guardian of Elune": "depends on the previous Mangle", "Heart of the Wild": "a separate button",
    "Aspects' Favor": "boosts Black Attunement, an aura that isn't tracked",
    "Foci of Life": "heals back damage over time after the hit", "Natural Mending": "cooldown from Focus spent",
    "Cryo-Freeze": "heals inside Ice Block, which already makes them immune",
    "Reduplication": "cooldown when images die", "Reabsorption": "heals when an image dies",
    "Master of Time": "cooldown of Alter Time", "Blackout Combo": "depends on the previous Blackout Kick",
    "Purifying Brew": "depends on Stagger level", "Aspect of Harmony": "depends on stored vitality",
    "Resolute Defender": "cooldown from Holy Power spent", "Gift of the Golden Val'kyr": "cooldown / automatic",
    "Righteous Protector": "cooldown from Holy Power spent", "Tirion's Devotion": "cooldown from Holy Power spent",
    "Laying Down Arms": "cooldown from Armaments", "Healing Hands": "cooldown by target health",
    "Angel's Mercy": "cooldown", "Desperate Measures": "duration, and Angelic Bulwark (automatic)",
    "Intangibility": "Dispersion's heal is a script formula the data doesn't give",
    "Float Like a Butterfly": "cooldown from combo points", "Nimble Fingers": "energy cost",
    "Resolute Barrier": "cooldown from hits taken", "Ichor of Devils": "health cost",
    "Frequent Donor": "cooldown", "Zevrim's Resilience": "a flat heal the data doesn't size",
    "Anger Management": "cooldown from Rage spent", "Impenetrable Wall": "cooldown from Shield Slam",
    "Lifeblood": "Leech after a Healthstone", "Swift Artifice": "cast time",
    "Soulburn": "handled", "Iron Stomach": "handled", "Glistening Fur": "handled", "Inspired Guard": "handled",
    "Berserk": "a separate button", "Incarnation: Guardian of Ursoc": "a separate button (Guardian)",
    "Blood Mist": "parry chance", "Dance of Midnight": "automatic", "Demonsurge": "damage",
    "Elune's Favored": "heals from damage dealt", "Empyreal Ward": "armor after Lay on Hands, which already heals fully",
    "Light's Revocation": "heals per effect removed", "Lycara's Inspiration": "no defensive in Bear Form (movement speed)",
    "Natural Resilience": "turns Frenzied Regeneration's overhealing into a shield whose cap the data doesn't give",
    "Persistence": "after leaving Bear Form", "Reinvigoration": "heals from other spells, and duration",
    "Sanguine Vial": "after a killing blow", "Temporal Realignment": "automatic",
    "The Blood is Life": "automatic", "Ursine Adept": "its Bear Form reduction is 0 in the data",
    "Voidpurge": "cooldown", "Voidrush": "cooldown", "World Killer": "cooldown",
    "Improved Ice Barrier": "handled", "Wilderness Medicine": "cooldown, and heals the pet",
    "Harmonic Surge": "damage", "Improved Blazing Barrier": "heals from damage absorbed",
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

# Each potion comes in quality ranks: separate items with their own item level,
# all casting the same spell (so a log names the potion but not the rank). A
# rank's tooltip heal is the heal effect's coefficient times the item-level
# budget of its scaling class (RandPropPoints at the item's level), rounded
# down: checked against the in-game tooltips of Concentrated Silvermoon Health
# Potion (359,498 / 421,200) and Algari Healing Potion (3,839,477 at rank 3).
# How many ranks a potion has differs by tier (The War Within: 3, Midnight: 2).
POTION_SCALING_COLUMN = {-9: "DamageSecondaryF", -8: "DamageReplaceStatF", -2: "EpicF_0", -1: "EpicF_0"}
RANK_NAMES = {2: ["silver", "gold"], 3: ["bronze", "silver", "gold"]}
HEAL_EFFECT = "10"

# Buttons the game only allows in a form (SpellShapeshift), and the talent that
# lifts it: Empowered Shapeshifting lets Frenzied Regeneration be cast in Cat Form.
FORM_REQUIRED = {"Frenzied Regeneration": ("Bear Form", "Empowered Shapeshifting")}

# Buffs that live on a spell the button doesn't point to in the game data.
AURA_SPELLS = {"Fortifying Brew": [120954], "Rallying Cry": [97463], "Renewing Blaze": [374349]}

# talent -> catalog spell whose modifier it copies onto potions and Healthstones.
ALSO_CONSUMABLES = {"Iron Stomach": 185311}

# Healthstone extras that come from a talent rather than the item: Soulburn
# makes a Warlock's Healthstone also raise max health (Soulburn: Healthstone).
SOULBURN = (385899, 387636)       # talent spell, the buff it adds to a Healthstone
GOREBOUND = ("Gorebound Fortitude", 1.3)   # its tooltip: "increasing its healing by 30%"

# SpellModOp values that change one effect's value -> that effect's index.
MOD_OP_EFFECT_INDEX = {3: 0, 12: 1, 23: 2, 32: 3, 33: 4}
MOD_OP_ALL = 0          # percent modifier on all of a spell's healing / absorb amounts
MOD_OP_DURATION = 1
MOD_OP_COOLDOWN = 11
AURA_ADD_MOD, AURA_PCT_MOD = "107", "108"
# The same, for every spell carrying a label (misc value 1) instead of a class
# mask: how Improved Ardent Defender, Phantasmal Image and Empowered
# Shapeshifting reach their spells.
AURA_ADD_MOD_LABEL, AURA_PCT_MOD_LABEL = "219", "220"
AURA_MAX_CHARGES = "411"            # +N charges of a charge category
AURA_CHARGE_RECOVERY_FLAT = "453"   # +ms to a charge category's recharge
AURA_CHARGE_RECOVERY_PCT = "454"    # +% to a charge category's recharge
AURA_HEALING_TAKEN_PCT = "118"      # healing taken +%
ALL_SCHOOLS = "127"
SPELL_ATTR0_PASSIVE = 0x40
AURA_OVERRIDE_BUTTON = "332"        # base points = new spell, misc value = the button it replaces
FIELDS = ("immune", "dr", "armor", "absorb", "hp", "heal", "heal_taken")

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
    # Only a pinned build is cached: the live table changes with every game
    # build, so a cached copy of it would silently go stale.
    path = CACHE_DIR and build and os.path.join(CACHE_DIR, f"{name}_{build}.csv.gz")
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
        self.labels = {}                          # spell -> label IDs
        for r in table("SpellLabel", build):
            self.labels.setdefault(int(r["SpellID"]), set()).add(int(r["LabelID"]))
        self.periods = {}                         # (spell, effect index) -> tick period (ms)
        for sid, effs in self.effects.items():
            for i, r in effs.items():
                if int(r["EffectAuraPeriod"] or 0):
                    self.periods[(sid, i)] = int(r["EffectAuraPeriod"])
        self.shapeshift = {int(r["SpellID"]): int(r["ShapeshiftMask_0"]) for r in table("SpellShapeshift", build)
                           if int(r["ShapeshiftMask_0"] or 0)}
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


# Damage-reduction auras and the damage they cover: aura 87 names schools in its
# misc value (127 all, 126 magic, 1 physical); aura 229 is AoE damage only.
AURA_AOE_REDUCTION = "229"
AURA_DAMAGE_TAKEN_PCT = "87"
AURA_SHAPESHIFT = "36"
SCHOOL_MASKS = {"127": None, "126": "magic", "1": "physical"}
MAGIC_SCHOOLS = 126


def data_value(field, gd, spell, index, ticks):
    """An effect's base value and school from the game data, as the catalog stores it.

    Returns (value, school) or (None, None) if the effect isn't there.
    """
    r = gd.effects.get(spell, {}).get(index)
    if r is None:
        return None, None
    bp = float(r["EffectBasePointsF"])
    if field == "dr":
        misc = r["EffectMiscValue_0"]
        if r["EffectAura"] == AURA_AOE_REDUCTION:
            return round(abs(bp) / 100, 4), "aoe"
        if r["EffectAura"] != AURA_DAMAGE_TAKEN_PCT:
            return round(abs(bp) / 100, 4), None          # a script's number (dummy effect): all damage
        if misc in SCHOOL_MASKS:
            return round(abs(bp) / 100, 4), SCHOOL_MASKS[misc]
        # Other school sets: magic ones only (Bear Form's "all other magic damage").
        return round(abs(bp) / 100, 4), int(misc) & MAGIC_SCHOOLS
    if field in ("heal", "hp", "armor", "heal_taken", "dr_missing", "absorb_pct"):
        return round(bp / 100 * ticks, 4), None
    if field == "vers":
        return round(bp / 200, 4), None
    return None, None


def effect_indices(gd, spell, where):
    """Indices of a spell's effects: an index, or "aura:N" for every effect with that aura
    (effects move between patches; their aura type doesn't)."""
    effs = gd.effects.get(spell, {})
    if isinstance(where, int):
        return [where] if where in effs else []
    aura = where.split(":")[1]
    return sorted(i for i, r in effs.items() if r["EffectAura"] == aura)


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
        if row["EffectAura"] in (AURA_ADD_MOD_LABEL, AURA_PCT_MOD_LABEL):
            return int(row["EffectMiscValue_1"]) in self.gd.labels.get(spell, ())
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
        for aura in (AURA_ADD_MOD, AURA_PCT_MOD, AURA_ADD_MOD_LABEL, AURA_PCT_MOD_LABEL):
            pct = aura in (AURA_PCT_MOD, AURA_PCT_MOD_LABEL)
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
                    if field == "vers":
                        mod["add"] = round(value / 200, 4)     # Versatility reduces damage taken by half its value
                found.append(mod)
        return _dedupe(found)

    def cooldown(self, spell):
        """Cooldown / recharge modifiers: {"add_ms"} or {"mult"}."""
        found = []
        for aura in (AURA_ADD_MOD, AURA_PCT_MOD, AURA_ADD_MOD_LABEL, AURA_PCT_MOD_LABEL):
            for r, who in self._source_rows(aura):
                if int(r["EffectMiscValue_0"]) == MOD_OP_COOLDOWN and self._covers(r, spell):
                    value = float(r["EffectBasePointsF"])
                    mod = {"talent": self.gd.names.get(int(r["SpellID"])), **who}
                    if aura in (AURA_PCT_MOD, AURA_PCT_MOD_LABEL):
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

    def duration(self, spells):
        """Aura duration modifiers (Anti-Magic Barrier, Improved Barkskin): {"add_ms"} or {"mult"}.
        `spells`: the button and the spells its aura lives on."""
        found = []
        for aura in (AURA_ADD_MOD, AURA_PCT_MOD, AURA_ADD_MOD_LABEL, AURA_PCT_MOD_LABEL):
            for r, who in self._source_rows(aura):
                if int(r["EffectMiscValue_0"]) == MOD_OP_DURATION and any(self._covers(r, s) for s in spells):
                    value = float(r["EffectBasePointsF"])
                    mod = {"talent": self.gd.names.get(int(r["SpellID"])), **who}
                    if aura in (AURA_PCT_MOD, AURA_PCT_MOD_LABEL):
                        mod["mult"] = round(1 + value / 100, 4)
                    else:
                        mod["add_ms"] = int(value)
                    found.append(mod)
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


def potion_ranks(build, gd, problems):
    """spell -> [{"rank", "ilvl", "heal", "items"}], lowest rank first, for every curated potion.

    Only the potion's own items count (same name, or its "Fleeting" copy from a
    cauldron, which has the same item levels); test items are left out.
    """
    potions = {sid: name for sid, name, _, _, kind in CURATED if kind == "potion" and sid in gd.names}
    effect_spell = {r["ID"]: int(r["SpellID"]) for r in table("ItemEffect", build) if int(r["SpellID"]) in potions}
    item_spell = {int(r["ItemID"]): effect_spell[r["ItemEffectID"]]
                  for r in table("ItemXItemEffect", build) if r["ItemEffectID"] in effect_spell}
    levels = {}
    # Only this expansion's potions: an older one scales differently after an
    # item squish (Invigorating Healing Potion heals 90,971 in Midnight).
    expansion = str(int(build.split(".")[0]) - 1)
    for r in table("ItemSparse", build):
        item = int(r["ID"])
        sid = item_spell.get(item)
        if sid and r["ExpansionID"] == expansion and r["Display_lang"] in (potions[sid], "Fleeting " + potions[sid]):
            levels.setdefault(sid, {}).setdefault(int(r["ItemLevel"]), []).append(item)
    budget = {int(r["ID"]): r for r in table("RandPropPoints", build)}
    out = {}
    for sid, by_level in levels.items():
        eff = next((e for e in gd.effects.get(sid, {}).values() if e["Effect"] == HEAL_EFFECT), None)
        column = POTION_SCALING_COLUMN.get(int(eff["ScalingClass"])) if eff else None
        if len(by_level) < 2:
            continue                      # a single rank: nothing to tell apart
        if column is None or not float(eff["Coefficient"] or 0):
            problems.append(f"{potions[sid]}: no scaled heal effect, ranks unknown")
            continue
        names = RANK_NAMES.get(len(by_level)) or [f"rank {i + 1}" for i in range(len(by_level))]
        out[sid] = [{"rank": names[i], "ilvl": lvl, "items": sorted(by_level[lvl]),
                     "heal": int(float(eff["Coefficient"]) * float(budget[lvl][column]))}
                    for i, lvl in enumerate(sorted(by_level))]
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
    return max(found, default=0) if max(found, default=0) > 0 else None   # -1: lasts until cancelled (a form)


def talent_who(gd, mods, name):
    """Who has a talent (by name) in this patch: {"talent", "entries"} or None if it isn't in a tree."""
    for sid, n in gd.names.items():
        if n == name and mods.entries_for_spell.get(sid):
            return {"talent": name, "entries": sorted(mods.entries_for_spell[sid])}, sid
    return None, None


def _talent_mods_reach(mods_list, talent):
    return any(m.get("talent") == talent for m in mods_list or ())


def components(name, gd, mods, problems):
    """One component per effect of an ability, base values from this patch's data, with talent modifiers.

    A component: {<field>: value, "school"?, "observed"?, "mods"?: [...], "needs"?, "current"?,
    "over_ms"/"ticks"?} where field is dr / absorb / hp / heal / armor / heal_taken
    (fractions of damage or of max health; armor: +x of the player's armor) or
    immune. Absorbs are "observed": the player's real shield size from the log
    wins over the estimate. "needs": only players with that talent get it.
    Returns None when the ability can't be scored.
    """
    values = MITIGATION.get(name)
    if values is None:
        return None
    out, used = [], set()
    for eff in EFFECTS.get(name) or [(f, None, None) for f in FIELDS if f in values]:
        opts = eff[-1] if isinstance(eff[-1], dict) else {}
        eff = eff[:-1] if opts else eff
        field, spell, where = eff[:3]
        ticks = eff[3] if len(eff) > 3 else 1
        indices = effect_indices(gd, spell, where) if spell is not None else [None]
        if not indices:
            if not opts.get("optional"):
                problems.append(f"{name}: effect {where} of spell {spell} is missing")
                indices = [None]
            else:
                used.add("dr" if field == "vers" else field)   # not in this patch: no listed fallback either
                continue
        for index in indices:
            out_field = "dr" if field == "vers" else field
            first = out_field in values and out_field not in used     # the hand-listed value covers the first use only
            used.add(out_field)
            listed = values[out_field] if first else 0.0
            school = values.get("school") if first and values.get("school") not in (None, "all") else None
            comp = {out_field: listed}
            if index is not None and field in ("dr", "heal", "hp", "armor", "heal_taken", "vers"):
                from_data, data_school = data_value(field, gd, spell, index, ticks)
                if from_data or not listed:
                    # The data wins; a 0 there with a listed value means a script sets
                    # it (Fortifying Brew), so the listed value stays.
                    comp[out_field] = from_data
                if field == "dr" and school not in ("aoe", "melee"):
                    school = data_school
            if school:
                comp["school"] = school
            if field == "absorb":
                comp["observed"] = True
            if opts.get("current"):
                comp["current"] = True
            if index is not None:
                m = mods.effect(spell, index, field, ticks)
                if m:
                    comp["mods"] = m
            need = opts.get("needs")
            if need and comp[out_field] and not _talent_mods_reach(comp.get("mods"), need):
                # A value in the data that a talent's script turns on (Translucent Image).
                who, _ = talent_who(gd, mods, need)
                if who:
                    comp["needs"] = who
            if comp[out_field] is None or comp[out_field] or comp.get("mods") or comp.get("observed"):
                out.append(comp)
    for field in FIELDS:           # values without a mapped effect (e.g. Metamorphosis' heal)
        if field in values and field not in used:
            comp = {field: values[field]}
            if values.get("school") not in (None, "all"):
                comp["school"] = values["school"]
            out.append(comp)
    for talent, adds in TALENT_EFFECTS.items():
        for ability, field, source, extra in adds:
            if ability != name:
                continue
            comp = talent_component(gd, mods, talent, field, source, extra, problems)
            if comp:
                out.append(comp)
    return out


def talent_component(gd, mods, talent, field, source, extra, problems):
    """An effect a talent adds to a button, for players who have it (TALENT_EFFECTS)."""
    who, talent_spell = talent_who(gd, mods, talent)
    if who is None:
        return None                       # not in this patch's talent trees
    value = 1.0
    for spell, where in source:
        spell = talent_spell if spell == "talent" else spell
        idx = effect_indices(gd, spell, where)
        if not idx:
            if not extra.get("optional"):
                problems.append(f"{talent}: effect {where} of spell {spell} is missing")
            return None
        value *= abs(float(gd.effects[spell][idx[0]]["EffectBasePointsF"])) / 100
    if field == "absorb_aura":
        comp = {"absorb": None, "observed": True, "aura": extra["aura"]}
    else:
        comp = {field: round(value, 4)}
    if extra.get("school"):
        comp["school"] = extra["school"]
    over = extra.get("over")
    if over:
        # A heal over time: the listed value is per tick, spread over the spell's duration.
        dur = gd.duration.get(over, 0)
        period = next((p for (s, _), p in gd.periods.items() if s == over), 0)
        if not dur or not period:
            problems.append(f"{talent}: no duration/tick period on spell {over}")
            return None
        comp["ticks"] = dur // period
        comp[field] = round(value * comp["ticks"], 4) if extra.get("per_tick") else comp[field]
        comp["over_ms"] = dur
    comp["needs"] = who
    return comp


SURVIVAL_WORDS = re.compile(r"damage taken|damage you take|maximum health|absorb|heal|armor|immun|reduc", re.I)


def unreviewed_talents(gd, build, catalog, mods):
    """Talents whose tooltip names a tracked defensive with a survival word and that
    no modifier, TALENT_EFFECTS entry or TALENTS_REVIEWED line covers."""
    desc = {int(r["ID"]): r["Description_lang"] for r in table("Spell", build)}
    handled = set(TALENTS_REVIEWED)
    for d in catalog.values():
        for c in d.get("mitigation") or ():
            handled.update(m["talent"] for m in c.get("mods", ()))
        handled.update(m["talent"] for m in d.get("cooldown_mods", []) + d.get("charge_mods", []))
    names = {d["name"] for d in catalog.values() if d["kind"] in ("personal", "healthstone", "potion")}
    found = set()
    for sid, entries in mods.entries_for_spell.items():
        text, talent = desc.get(sid) or "", gd.names.get(sid)
        if talent in handled or talent in names or not SURVIVAL_WORDS.search(text):
            continue
        if any(re.search(rf"\b{re.escape(n)}\b", text) for n in names):
            found.add(talent)
    return sorted(found)


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
    ranks = potion_ranks(build, gd, problems)
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
            if entry["aura_ms"] and entry["aura_ms"] > 0:
                durations = mods.duration([sid] + list(AURA_SPELLS.get(name, ())))
                if durations:
                    entry["duration_mods"] = durations
        if kind == "potion" and POTION_TYPICAL.get(name):
            entry["mitigation"] = [{"heal_amount": POTION_TYPICAL[name], "observed": True}]
        if kind == "potion" and ranks.get(sid):
            entry["ranks"] = ranks[sid]
        if name == "Bear Form":
            # Shifting replaces the form they're in: its armor bonus (Moonkin Form +125%)
            # comes off before Bear Form's goes on (checked on live logs: no form 1,173,
            # Moonkin 2,640, Bear 3,754, Bear with Ursine Vigor 4,317).
            entry["form_armor"] = {s: round(1 + float(r["EffectBasePointsF"]) / 100, 4)
                                   for s, effs in gd.effects.items() if s != sid
                                   and any(e["EffectAura"] == AURA_SHAPESHIFT for e in effs.values())
                                   for r in effs.values()
                                   if r["EffectAura"] == "142" and r["EffectMiscValue_0"] == "1"
                                   and gd.family.get(s, (None,))[0] == gd.family.get(sid, (None,))[0]}
            for comp in entry["mitigation"] or ():
                if "armor" in comp and "needs" not in comp:
                    comp["replaces_form"] = True
        form = FORM_REQUIRED.get(name)
        if form and gd.shapeshift.get(sid):
            # Castable only in a form (Frenzied Regeneration: Bear Form), unless a talent lifts it.
            unless, _ = talent_who(gd, mods, form[1]) if form[1] else (None, None)
            entry["needs_form"] = {"form": form[0], **({"unless": unless} if unless else {})}
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
            hp_mods = [{"talent": names.get(talent), **who, "add": hp}] if who and hp else []
            # Gorebound Fortitude: the Soulburn benefit on every Healthstone (+30% heal, +20% max health).
            gore, _ = talent_who(gd, mods, GOREBOUND[0])
            if gore and hp:
                hp_mods.append({**gore, "add": hp})
                for comp in entry["mitigation"]:
                    if "heal" in comp:
                        comp.setdefault("mods", []).append({**gore, "mult": GOREBOUND[1]})
            if hp_mods:
                entry["mitigation"].append({"hp": 0.0, "mods": hp_mods})
    heal = {"talents": mods.healing_taken(), "auras": healing_taken_auras(gd, mods)}
    for talent in unreviewed_talents(gd, build, catalog, mods):
        problems.append(f"talent {talent!r} names a defensive: review it (TALENT_EFFECTS / TALENTS_REVIEWED)")
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
