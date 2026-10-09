"""
features.py - Cheat-death detection constants (defensive tracking lives in defensives.py)
"""

# =============================================================================
# FEATURE CONSTANTS
# =============================================================================

# A cheat death: a hit that would have killed the player, and they didn't die.
# Each effect below fires only then (checked in the game data and on live logs),
# never from simply having the defensive up.

# The "recently cheated death" debuff each one leaves on the player.
CHEAT_DEATH_DEBUFF_IDS = {
    45181,    # Cheated Death (Rogue: Cheat Death)
    87024,    # Cauterized (Mage: Cauterize)
    123981,   # Perdition (Death Knight: Purgatory)
    211319,   # Restitution (Holy Priest: revived after Spirit of Redemption)
    404369,   # Empty Hourglass (Evoker: Defy Fate)
    209261,   # Uncontained Fel (Demon Hunter: Last Resort)
    1265598,  # Kill or Be Killed (Warrior)
    1236692,  # Void Reconstitution (All-Devouring Nucleus, Manaforge Omega tank trinket)
}

# Saves that leave no debuff, only a heal on the saved player when the lethal hit is stopped.
CHEAT_DEATH_HEAL_IDS = {
    48153,    # Guardian Spirit (Priest, on any target): the spirit sacrifices itself
    66235,    # Ardent Defender (Protection Paladin): brought back up instead of dying
}

CHEAT_DEATH_ABILITY_IDS = CHEAT_DEATH_DEBUFF_IDS | CHEAT_DEATH_HEAL_IDS

# Heals the killing hit itself sets off (game data: the cheat deaths' EffectAura 316 "prevent fatal
# damage" spells and the heals they cast; Embrace the Shadow's absorb turns the shadow damage it takes
# into a heal). Health they bring is not health the player had before the blow. heal ID -> the absorb
# that takes part of the killing hit with it (logged within 2 ms of the heal), or None for a heal with no
# absorb of its own. Read from the death windows (defensives.fetch_death_windows), only these IDs.
KILLING_HIT_HEALS = {
    404381: 404195,     # Defy Fate (Evoker): absorbs the fatal hit, the released energy heals
    87023: 86949,       # Cauterize (Mage): absorbs it, brings you to 35% health
    451571: 451569,     # Embrace the Shadow (Priest): absorbs 3% of magic damage, heals the shadow part
    187827: 209258,     # Metamorphosis's heal (+40%) when Last Resort (Vengeance) absorbed the fatal hit
    48153: None,        # Guardian Spirit (Priest): restores the target to 40% health
    66235: None,        # Ardent Defender (Protection Paladin): brings you to 20% of max health
    1236692: None,      # Void Reconstitution (All-Devouring Nucleus): heals 10% of max health (EffectAura 136)
}
KILLING_HIT_HEAL_IDS = set(KILLING_HIT_HEALS)
