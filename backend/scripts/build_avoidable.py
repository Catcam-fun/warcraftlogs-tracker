"""Regenerate backend/avoidable_damage.py: which boss abilities a player could have avoided.

    WCL_CLIENT_ID=... WCL_CLIENT_SECRET=... WAGO_CACHE=... \
        python backend/scripts/build_avoidable.py --evidence ev.json --review review.json

For every encounter in analysis.RAID_ENCOUNTERS it reads the damage players took on a few guilds'
Mythic kills (as build_raid_wide.py does) and gathers, for every ability that hit them: how the game
data says it lands (avoidable_classify), its in-game description (boss_spell_text) and the share of the
raid each occurrence hit. The game data decides only whole-room damage (never avoidable); raid-wide
damage (RAID_WIDE) is left out. Every other ability needs an answer in avoidable_overrides.py: the
script writes the open ones to --review and exits 1 until there are none. A DoT an answered spell
applies takes its rule. --evidence keeps what was read from WarcraftLogs, so a rerun after answering
spends no points (about 10 per encounter otherwise).
"""
import argparse
import json
import os
import statistics
import sys
from collections import defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

MOST_OF_RAID = 0.5     # an "always" answer whose median occurrence hits more than this is flagged
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "avoidable_damage.py")


def merge(abilities, overrides, dots, raid_wide):
    """(entries to write, review items). `abilities`: {id: {name, boss, kind, reason, median_share, desc}};
    `overrides`: the owner's answers; `dots`: {spell: DoT IDs it applies}; `raid_wide`: IDs never listed."""
    entries, review = {}, []

    def item(aid, why):
        a = abilities[aid]
        review.append({"id": aid, "why": why, **{k: a.get(k) for k in ("name", "boss", "kind", "reason",
                                                                         "median_share", "desc")}})
    for aid, a in abilities.items():
        if aid in raid_wide:
            continue
        if aid in overrides:
            entries[aid] = dict(overrides[aid])
            if entries[aid]["rule"] == "bystander":
                # The ability's own ID can't mark its target: a DoT the hit puts on comes with the hit.
                marks = [m for m in entries[aid].get("auras", ()) if m != aid]
                if marks:
                    entries[aid]["auras"] = marks
                else:
                    entries[aid] = {"rule": "never", "name": entries[aid]["name"], "boss": entries[aid]["boss"]}
            if overrides[aid]["rule"] == "always" and (a.get("median_share") or 0) > MOST_OF_RAID:
                item(aid, f"answered always, but it hits most of the raid ({a['median_share']:.0%})")
        elif a["kind"] == "unavoidable":
            entries[aid] = {"rule": "never", "name": a["name"], "boss": a["boss"]}
    # DoTs take the rule of the answered spell that applies them.
    inherited = defaultdict(set)
    for src, ids in dots.items():
        if src in overrides:
            for d in ids:
                if d != src and d not in overrides and d not in raid_wide:
                    inherited[d].add((overrides[src]["rule"], src))
    for d, rules in inherited.items():
        if len({r for r, _ in rules}) == 1:
            rule, src = min(rules, key=lambda x: x[1])
            name, boss = (abilities.get(d) or {}).get("name", str(d)), (abilities.get(d) or {}).get("boss", "")
            entries[d] = {"rule": rule, "name": name, "boss": boss, "source": src}
        elif d in abilities:
            item(d, "DoT whose sources disagree: " + ", ".join(f"{s} {r}" for r, s in sorted(rules)))
    for aid in abilities:
        if aid not in entries and aid not in raid_wide and not any(r["id"] == aid for r in review):
            item(aid, "needs an answer")
    return entries, review


def gather(token, evidence):
    """{id: ability evidence} for every encounter, reading WarcraftLogs only for encounters not in `evidence`."""
    import boss_spell_text
    from analysis import RAID_ENCOUNTERS
    from avoidable_classify import classify
    from build_defensive_catalog import table
    from build_raid_wide import kills, shares
    effects = defaultdict(list)
    for r in table("SpellEffect"):
        if r["DifficultyID"] == "0":
            effects[int(r["SpellID"])].append(r)
    radius = {r["ID"]: float(r["Radius"]) for r in table("SpellRadius")}
    abilities = {}
    for encounter in sorted(set().union(*RAID_ENCOUNTERS.values())):
        key = str(encounter)
        if key not in evidence:
            boss, sample = kills(token, encounter)
            per, names = defaultdict(list), {}
            for code, fight_id in sample:
                for aid, (name, s) in shares(token, code, fight_id).items():
                    per[aid].append(statistics.median(s))
                    names[aid] = name
            evidence[key] = {"boss": boss, "abilities": {str(a): [names[a], statistics.median(v)]
                                                         for a, v in per.items()}}
        ev = evidence[key]
        for aid_s, (name, share) in ev["abilities"].items():
            aid = int(aid_s)
            kind, reason = classify(aid, effects.get(aid, []), radius)
            abilities[aid] = {"name": name, "boss": ev["boss"], "kind": kind, "reason": reason,
                              "median_share": round(share, 2), "desc": boss_spell_text.text_for(aid) or ""}
    return abilities, effects


def write(entries):
    with open(OUT, "w", newline="\n", encoding="utf-8") as f:
        f.write('"""GENERATED by scripts/build_avoidable.py from wago.tools game data, Mythic kills on '
                'WarcraftLogs and the\nowner\'s answers (avoidable_overrides.py). Boss abilities and how '
                'they are avoidable (avoidable.py)."""\n\nAVOIDABLE = {\n')
        for aid, e in sorted(entries.items(), key=lambda x: (x[1].get("boss", ""), x[1].get("name", ""), x[0])):
            body = {k: e[k] for k in ("rule", "name", "boss", "source") if k in e}
            f.write(f"    {aid}: {body!r},\n")
        f.write("}\n")


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--evidence", required=True, help="JSON file: what was read from WarcraftLogs (reused)")
    p.add_argument("--review", required=True, help="JSON file the open questions are written to")
    args = p.parse_args(argv)
    from avoidable_classify import dot_links
    from avoidable_overrides import OVERRIDES
    from raid_wide_damage import RAID_WIDE
    from warcraftlogs import get_access_token
    evidence = json.load(open(args.evidence, encoding="utf-8")) if os.path.exists(args.evidence) else {}
    token = get_access_token(os.environ["WCL_CLIENT_ID"], os.environ["WCL_CLIENT_SECRET"])
    try:
        abilities, effects = gather(token, evidence)
    finally:
        with open(args.evidence, "w", encoding="utf-8") as f:
            json.dump(evidence, f)
    dots = {aid: dot_links(effects, aid) for aid in set(abilities) | set(OVERRIDES)}
    entries, review = merge(abilities, OVERRIDES, dots, set(RAID_WIDE))
    write(entries)
    with open(args.review, "w", encoding="utf-8") as f:
        json.dump(review, f, indent=1, ensure_ascii=False)
    print(f"Wrote {len(entries)} abilities to {os.path.normpath(OUT)}; {len(review)} need an answer ({args.review})")
    return 1 if review else 0


if __name__ == "__main__":
    sys.exit(main())
