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
    # A hit with the defensive up is compared only with hits carrying the same other auras:
    # players press defensives together with untracked reductions and versatility buffs
    # (Protective Light, Shifting Sands), which alone read as several points of extra reduction.
    # (player, ability, talents, other auras) -> [share of damage that got through, no defensive up]
    base = defaultdict(list)
    # (player, ability, talents) -> {defensive name: [(share that got through, other auras, the hit)]}
    shares = defaultdict(lambda: defaultdict(list))
    # Logs from before Midnight never mark AoE hits: there an AoE-only reduction can't be predicted.
    aoe_known = any(e.get("isAoE") for e in hits)
    for e in hits:
        if e.get("type") != "damage" or e.get("targetID") not in players or not e.get("unmitigatedAmount"):
            continue
        if not e.get("mitigated"):
            continue                       # ignored reductions entirely
        if e.get("blocked"):
            continue                       # a block takes a random cut that _full_hit doesn't add back
        auras = {names.get(a) for a in defensives._auras(e)}
        up = auras & tracked
        if len(up) > 1:
            continue
        which = next(iter(up), None)
        if which is not None and which not in dr_names:
            continue
        # A personal defensive shared onto another class (an Evoker's Obsidian Scales on an ally)
        # is not the catalog's button, and the site never reads it for that player.
        if which is not None and dr_names[which]["kind"] == "personal" \
                and dr_names[which].get("class") != players[e["targetID"]].get("type"):
            continue
        through = defensives._full_hit(e) / e["unmitigatedAmount"]
        talents = loadout.get((e.get("fight"), e["targetID"]))
        key = (e["targetID"], e.get("abilityGameID"), tuple(sorted((talents or {}).items())))
        others = frozenset(auras - {which})
        if which is None:
            base[key + (others,)].append(through)
        else:
            shares[key][which].append((through, others, e))

    schools = meta.get("ability_schools", {})
    # (player, defensive) -> [(hits with it, measured, predicted)] per boss ability
    rows = defaultdict(list)
    for (pid, ability, talents), groups in shares.items():
        for name, with_up in groups.items():
            comps, _ = defensives._resolve(dr_names[name], dict(talents), {}, spec.get(pid))
            # Each hit's own prediction: one ability's hits are not all marked AoE alike.
            by_predicted = defaultdict(list)
            for through, others, e in with_up:
                same = base.get((pid, ability, talents, others), [])
                if len(same) < MIN_HITS:
                    continue
                keep = 1.0
                for c in comps or []:
                    applies = defensives._school_applies(c.get("school"), dict(e, aoeKnown=aoe_known), schools)
                    if c.get("dr") and applies is None:
                        keep = None
                        break
                    if c.get("dr") and applies:
                        keep *= 1 - c["dr"]
                if keep is not None:
                    by_predicted[round(1 - keep, 4)].append(1 - through / statistics.median(same))
            for predicted, got in by_predicted.items():
                if len(got) >= MIN_HITS:
                    rows[(pid, name)].append((len(got), statistics.median(got), predicted))

    # Each ability's gap between measured and predicted, weighted by hits:
    # a handful of hits is noisy, a few hundred is not.
    items, measured = [], 0
    for (pid, name), per in sorted(rows.items(), key=lambda kv: (kv[0][1], players[kv[0][0]]["name"])):
        n = sum(h for h, _, _ in per)
        if n < MIN_FLAG_HITS:
            continue
        measured += 1
        real = sum(h * m for h, m, _ in per) / n
        predicted = sum(h * p for h, _, p in per) / n
        if abs(real - predicted) > FLAG_AT:
            items.append(f"{players[pid]['name']} {name}: measured {real:.2f}, catalog {predicted:.2f} over {n} hits")
    if not measured:
        return skip(f"no defensive had enough matched hits to measure ({len(rows)} rows compared)")
    return fail(items) if items else PASS
