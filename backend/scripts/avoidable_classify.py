"""How a boss damage spell lands, from the client game data (wago.tools SpellEffect, SpellRadius).

The client data decides only one case: damage to everyone within WHOLE_ROOM_YD of the caster or a point
(Coalesced Venom 1282408: 200 yd; Necrotic Vapors 1286835: 300 yd; Fester Burst 1310763: 100 yd) is the
whole room, so never avoidable. Everything else is "unsure", with the evidence as the reason: most boss
damage is cast by the server on whoever a mechanic touches, and the data can't tell a wave or a pool
from a chosen player (Caustic Waves 1292403 "to players in their path" is target type 25, Plague Wave
1295798 "waves ... erupt from the target" is single-target type 6). Those are decided from the spell's
in-game description and real logs, and reviewed by the owner (build_avoidable.py).
"""

SCHOOL_DAMAGE, HEALTH_LEECH, APPLY_AURA = "2", "9", "6"
PERIODIC_DAMAGE = {"3", "53", "89"}     # periodic damage, periodic leech, periodic %-of-health damage
WHOLE_ROOM_YD = 100.0


def _damaging(e):
    return e["Effect"] in (SCHOOL_DAMAGE, HEALTH_LEECH) or e["EffectAura"] in PERIODIC_DAMAGE


def _radius(e, radius_yd):
    """The effect's area in yards (the larger of its two radius indexes), or None for no area."""
    sizes = [radius_yd.get(e[k]) for k in ("EffectRadiusIndex_0", "EffectRadiusIndex_1") if e[k] != "0"]
    sizes = [s for s in sizes if s]
    return max(sizes) if sizes else None


def classify(spell_id, effects, radius_yd):
    """(kind, reason): "unavoidable" with "whole room (N yd)" when every damage effect covers at least
    WHOLE_ROOM_YD, else "unsure" with what the data shows. `effects`: the spell's SpellEffect rows;
    `radius_yd`: SpellRadius ID -> yards."""
    damage = [e for e in effects if _damaging(e)]
    if not damage:
        return "unsure", "no damage effect in the game data"
    areas = [_radius(e, radius_yd) for e in damage]
    if all(a is not None and a >= WHOLE_ROOM_YD for a in areas):
        return "unavoidable", f"whole room ({min(areas):g} yd)"
    if any(a is not None for a in areas):
        return "unsure", f"area of {min(a for a in areas if a is not None):g} yd"
    targets = sorted({e["ImplicitTarget_0"] for e in damage})
    return "unsure", f"cast on a unit by the server (target type {', '.join(targets)})"


def dot_links(effects_by_spell, spell_id, depth=3):
    """Periodic-damage auras the spell applies itself or through the spells it triggers (up to `depth`)."""
    out, seen, stack = set(), set(), [(spell_id, 0)]
    while stack:
        sid, d = stack.pop()
        if sid in seen:
            continue
        seen.add(sid)
        for e in effects_by_spell.get(sid, ()):
            if e["Effect"] == APPLY_AURA and e["EffectAura"] in PERIODIC_DAMAGE:
                out.add(sid)
            trig = int(e.get("EffectTriggerSpell") or 0)
            if trig and d < depth:
                stack.append((trig, d + 1))
    return out
