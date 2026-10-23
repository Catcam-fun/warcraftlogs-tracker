"""The owner's answers about which boss abilities are avoidable, read by scripts/build_avoidable.py.

An answer here always wins over what the build worked out. Each entry:
    ability ID: {"rule": ..., "name": "Ability", "boss": "Boss"}
Rules:
    "always"    every hit is avoidable (a pool, a frontal, a wave)
    "never"     no hit is (a group soak, damage the raid must take)
    "non_tank"  avoidable for anyone not in a tank spec that pull (a tank soak)
"""

OVERRIDES = {
}
