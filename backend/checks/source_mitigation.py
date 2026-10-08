"""Source check: the catalog's damage reductions against real hits."""
import statistics
from collections import defaultdict

import defensives
from checks.verdict import PASS, fail, skip

MIN_HITS = 3
FLAG_AT = 0.03
MIN_FLAG_HITS = 20            # fewer hits than this are too noisy to flag


def check(run):
    """Catalog damage reductions match real hits with and without the defensive"""
    if not run.pulls:
        return skip(f"no Mythic pulls of {run.raid} in {run.code}")
    meta, cat = run.meta, run.cat
    fights = [p["id"] for p in run.pulls]
    names = meta["abilities"]
    players = {f["id"]: f for f in meta["friendlies"]}

    # A WCL event query scoped by fightIDs must also carry an endTime, or it drops events.
    start = min(p["start_time"] for p in run.pulls)
    end = max(p["end_time"] for p in run.pulls) + 1
    hits = defensives._paged(run.token, run.code, "DamageTaken", None, fight_ids=fights,
                             start_time=start, end_time=end)
    combatants = [c for fid in fights for c in run.combatants(run.code, fid)]
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
    items = []
    for (pid, name), per in sorted(rows.items(), key=lambda kv: (kv[0][1], players[kv[0][0]]["name"])):
        n = sum(h for h, _, _ in per)
        real = sum(h * m for h, m, _ in per) / n
        predicted = sum(h * p for h, _, p in per) / n
        if n >= MIN_FLAG_HITS and abs(real - predicted) > FLAG_AT:
            items.append(f"{players[pid]['name']} {name}: measured {real:.2f}, catalog {predicted:.2f} over {n} hits")
    return fail(items) if items else PASS
