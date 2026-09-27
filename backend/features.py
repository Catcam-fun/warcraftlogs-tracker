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
