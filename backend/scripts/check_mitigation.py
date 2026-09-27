"""Check the catalog's damage reductions against real hits in a WarcraftLogs report.

    WCL_CLIENT_ID=... WCL_CLIENT_SECRET=... python backend/scripts/check_mitigation.py <reportCode> [fightID,...]

For every player and defensive with a damage reduction, it compares hits from
the same boss ability taken with that defensive up against hits taken with no
tracked defensive up. The share of damage that got through (after armor,
versatility and everything else) differs only by the defensive, so
1 - with/without is its real reduction. That's printed next to what the
catalog predicts for the player's talents (from the report's patch).

Costs WCL points (it reads all damage taken in the chosen pulls), so pass a
few fight IDs on a big report.
"""
import os
import statistics
import sys
from collections import defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import defensives  # noqa: E402
from warcraftlogs import get_access_token, get_fights  # noqa: E402

MIN_HITS = 3
FLAG_AT = 0.03
MIN_FLAG_HITS = 20            # fewer hits than this are too noisy to flag


def main():
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    code = sys.argv[1]
    token = get_access_token(os.environ["WCL_CLIENT_ID"], os.environ["WCL_CLIENT_SECRET"])
    meta = get_fights(token, code)
    wanted = {int(x) for x in sys.argv[2].split(",")} if len(sys.argv) > 2 else None
    fights = [f["id"] for f in meta["fights"] if f.get("boss") and (wanted is None or f["id"] in wanted)]
    cat = defensives.catalog_for(meta.get("report_start"))
    names = meta["abilities"]
    players = {f["id"]: f for f in meta["friendlies"]}
    print(f"Patch {cat.patch}; {len(fights)} pulls")

    hits = defensives._paged(token, code, "DamageTaken", None, fight_ids=fights)
    combatants = defensives._paged(token, code, "CombatantInfo", None, fight_ids=fights)
    # Talents can change between pulls, so each hit is judged by its own pull's loadout.
    loadout = {(e["fight"], e["sourceID"]): {t["id"]: t.get("rank") or 1 for t in e.get("talentTree") or []
                                             if t["id"] in cat.relevant_talent_entries} for e in combatants}
    spec = {pid: (meta["player_details"].get(pid) or {}).get("spec") for pid in players}

    dr_names = {d["name"]: d for d in cat.all.values()
                if d["kind"] in ("personal", "external") and any("dr" in c for c in d.get("mitigation") or [])}
    tracked = set(cat.name_to_id)
    # (player, ability) -> {defensive name or None: [share of damage that got through]}
    shares = defaultdict(lambda: defaultdict(list))
    sample = {}                            # (player, ability) -> one hit (for school / AoE checks)
    for e in hits:
        if e.get("type") != "damage" or e.get("targetID") not in players or not e.get("unmitigatedAmount"):
            continue
        if not e.get("mitigated"):
            continue                       # ignored reductions entirely
        up = {names.get(a) for a in defensives._auras(e)} & tracked
        if len(up) > 1:
            continue
        which = next(iter(up), None)
        if which is not None and which not in dr_names:
            continue
        through = defensives._full_hit(e) / e["unmitigatedAmount"]
        talents = loadout.get((e.get("fight"), e["targetID"]))
        key = (e["targetID"], e.get("abilityGameID"), tuple(sorted((talents or {}).items())))
        shares[key][which].append(through)
        sample[key] = e

    schools = meta.get("ability_schools", {})
    # (player, defensive) -> [(hits with it, measured, predicted)] per boss ability
    rows = defaultdict(list)
    for (pid, ability, talents), groups in shares.items():
        base = groups.get(None, [])
        if len(base) < MIN_HITS:
            continue
        for name, got in groups.items():
            if not name or len(got) < MIN_HITS:
                continue
            comps, _ = defensives._resolve(dr_names[name], dict(talents), {}, spec.get(pid))
            keep = 1.0
            for c in comps or []:
                if c.get("dr") and defensives._school_applies(c.get("school"), sample[(pid, ability, talents)], schools):
                    keep *= 1 - c["dr"]
            rows[(pid, name)].append((len(got), 1 - statistics.median(got) / statistics.median(base), 1 - keep))

    # Each ability's gap between measured and predicted, weighted by hits:
    # a handful of hits is noisy, a few hundred is not.
    print(f"{'player':16} {'defensive':28} {'hits':>5} {'measured':>9} {'catalog':>8}")
    for (pid, name), per in sorted(rows.items(), key=lambda kv: (kv[0][1], players[kv[0][0]]["name"])):
        hits = sum(n for n, _, _ in per)
        real = sum(n * m for n, m, _ in per) / hits
        predicted = sum(n * p for n, _, p in per) / hits
        flag = "  <-- check" if hits >= MIN_FLAG_HITS and abs(real - predicted) > FLAG_AT else ""
        print(f"{players[pid]['name']:16} {name:28} {hits:5} {real:9.3f} {predicted:8.3f}{flag}")


if __name__ == "__main__":
    main()
