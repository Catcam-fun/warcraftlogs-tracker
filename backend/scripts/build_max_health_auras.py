"""Regenerate backend/max_health_auras.py from the game data on wago.tools.

How much each aura changes a player's maximum health, per game patch (the last
build of each patch since 11.0.2, as build_defensive_catalog.py uses). The
death analysis needs it because WarcraftLogs logs a killing hit after the death
removed the player's auras: the max health they had just before the blow is
the max on their last hit before it, with the auras that came up or ran out in
between (each hit lists the auras up on it) added or taken out.

An aura's size, from its spell effects (Mythic rows when the spell has them):
  - EffectAura 133 (maximum health percent): base points %, multiplied together;
  - EffectAura 137 (total stat percent) with Stamina in its stat mask
    (EffectMiscValue_1 bit 4: 1 Strength, 2 Agility, 4 Stamina, 8 Intellect):
    base points %, since a player's health is their Stamina times a constant;
  - EffectAura 34 / 230 (maximum health, flat): base points as health;
  - EffectAura 29 (flat stat) on Stamina or all stats: None (health per Stamina point and the
    item-level scaling of those points are not in the data: Seabed Leviathan's Citrine);
  - base points 0 on those auras means the game computes the value: the aura's
    own text names the effect that holds it ("Maximum health increased by
    $s4%": Vampiric Blood), else CURATED says where it is, else it is None
    (the size isn't in the data).
Effects of one aura aimed at different units (ImplicitTarget_0) land on different units: only those
with the first such effect's target count (Fortitude of the Bear: +20% on you, +20% on your pet).
Negative sizes (raid debuffs that lower max health) are kept. Stacks are not in the data a hit
carries, so a stacking aura counts once (Redoubt, 2% Stamina a stack in 11.x).

    WAGO_CACHE=/tmp/wago python backend/scripts/build_max_health_auras.py
"""
import os
import pprint
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from build_defensive_catalog import patches, table  # noqa: E402

PERCENT, STAT_PERCENT, FLAT, FLAT_STAT = "133", "137", ("34", "230"), "29"
STAMINA_STATS = ("2", "-1")     # EffectAura 29 stat: 2 Stamina, -1 all stats (-2 is the primary stat)
STAMINA_BIT = 4
MYTHIC = "16"
# Auras whose value the game computes, with no reference in their own text: (aura, name, spell
# and effect index holding the percent, that spell's name). Checked against the names each build.
CURATED = [
    (97463, "Rallying Cry", 97462, 0, "Rallying Cry"),            # "$s1% temporary and maximum health" (in a raid)
    (120954, "Fortifying Brew", 120954, 5, "Fortifying Brew"),   # "$<health>%": the dummy effect's 20
]


def _rows(build):
    """{spell: {effect index: row}}, the Mythic row over the base one where a spell has both."""
    out = {}
    for r in table("SpellEffect", build):
        if r["DifficultyID"] not in ("0", MYTHIC):
            continue
        slot = out.setdefault(int(r["SpellID"]), {})
        i = int(r["EffectIndex"])
        if i not in slot or r["DifficultyID"] == MYTHIC:
            slot[i] = r
    return out


def _bp(r):
    return float(r["EffectBasePointsF"] or 0)


def sizes(build, problems):
    """{aura: (share, flat) or None} for one build."""
    names = {int(r["ID"]): r["Name_lang"] for r in table("SpellName", build)}
    texts = {int(r["ID"]): r.get("AuraDescription_lang") or "" for r in table("Spell", build)}
    effects = _rows(build)
    curated = {a: (n, s, i, sn) for a, n, s, i, sn in CURATED}
    out = {}
    for sid, effs in effects.items():
        share, flat, unknown, touched, target = 1.0, 0, False, False, None
        for i, r in sorted(effs.items()):
            aura = r["EffectAura"]
            stamina = aura == STAT_PERCENT and int(r["EffectMiscValue_1"] or 0) & STAMINA_BIT
            flat_stamina = aura == FLAT_STAT and r["EffectMiscValue_0"] in STAMINA_STATS
            if r["Effect"] != "6" or not (aura == PERCENT or stamina or aura in FLAT or flat_stamina):
                continue
            # Effects aimed at another unit (Fortitude of the Bear: one for you, one for your pet,
            # ImplicitTarget 1 and 27) are not on the same aura holder: the first one's target counts.
            target = r["ImplicitTarget_0"] if target is None else target
            if r["ImplicitTarget_0"] != target:
                continue
            touched = True
            value = _bp(r)
            if flat_stamina:
                unknown = True       # Stamina points: health per point isn't in the data (gear scaling too)
            elif value == 0:
                m = re.search(r"aximum health[^$]*\$[sw](\d)%|\$[sw](\d)% of maximum|maximum health by \$[sw](\d)%",
                              texts.get(sid, ""))
                n = next((int(g) for g in (m.groups() if m else ()) if g), None)
                if n is not None and n - 1 in effs and n - 1 != i and _bp(effs[n - 1]):
                    share *= 1 + _bp(effs[n - 1]) / 100
                elif sid in curated:
                    name, src, idx, src_name = curated[sid]
                    if names.get(sid) != name or names.get(src) != src_name or idx not in effects.get(src, {}):
                        problems.append(f"curated {sid} {name}: now {names.get(sid)} / {names.get(src)}")
                        unknown = True
                    else:
                        share *= 1 + _bp(effects[src][idx]) / 100
                else:
                    unknown = True
            elif aura in FLAT:
                flat += int(value)
            else:
                share *= 1 + value / 100
        if touched:
            out[sid] = None if unknown else (round(share - 1, 6), flat)
    return out


def main():
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "max_health_auras.py")
    history, problems = {}, []
    for patch, first_day, build in patches():
        print(f"{patch} (build {build})...", flush=True)
        found = sizes(build, problems)
        for aura, value in found.items():
            h = history.setdefault(aura, [])
            if not h or h[-1][1] != value:
                h.append((patch, value))
        for aura, h in history.items():          # no longer changes max health in this patch
            if aura not in found and h[-1][1] != (0.0, 0):
                h.append((patch, (0.0, 0)))
    if problems:
        raise SystemExit("game data changed; update CURATED:\n  " + "\n  ".join(sorted(set(problems))))
    with open(out, "w", newline="\n") as f:
        f.write('"""GENERATED by scripts/build_max_health_auras.py from wago.tools game data. Do not edit.\n\n'
                "How much each aura changes maximum health, by patch: {aura ID: [(first patch, value), ...]}.\n"
                "value: (share, flat): max health x (1 + share) + flat; None when the game computes it and the\n"
                'data does not hold the size."""\n\n')
        f.write("MAX_HEALTH = " + pprint.pformat(history, width=120, sort_dicts=True) + "\n")
    print(f"Wrote {len(history)} auras to {os.path.normpath(out)}")


if __name__ == "__main__":
    main()
