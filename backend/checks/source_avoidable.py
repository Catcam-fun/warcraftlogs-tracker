"""Abilities listed "always" avoidable hit only part of the raid at once, on WarcraftLogs

A pool, a frontal or a wave catches a few players; one that hits most of the raid per cast is raid
damage, and listing it would make deaths "avoidable" that weren't. For up to PULLS_PER_RUN kept pulls,
each "always" ability of that boss is read from the pull's damage taken (one query per pull, filtered
to those abilities), its hits grouped into casts (hits within OCCURRENCE_MS), and the median cast must
hit at most MOST_OF_RAID of the pull's players.
"""
import statistics
from collections import defaultdict

from avoidable_damage import AVOIDABLE
from avoidable_overrides import OVERRIDES
from checks.verdict import PASS, fail, skip

PULLS_PER_RUN, OCCURRENCE_MS, MOST_OF_RAID = 3, 1_000, 0.5


def always_for(boss):
    entries = {**AVOIDABLE, **OVERRIDES}
    return {aid: e for aid, e in entries.items() if e.get("rule") == "always" and e.get("boss") == boss}


def check(run):
    """Abilities listed "always" avoidable hit only part of the raid at once, on WarcraftLogs"""
    keys = sorted({k for ks in (run.result.get("pullParticipation") or {}).values() for k in ks})[:PULLS_PER_RUN]
    if not keys:
        return skip("no kept pulls")
    items, measured = [], 0
    for key in keys:
        rid, fid = key.rsplit("_", 1)
        fight = run.fight(rid, int(fid))
        listed = always_for(fight.get("name"))
        players = set(fight.get("friendlyPlayers") or [])
        if not listed or not players:
            continue
        by_ability = defaultdict(list)
        for h in run.ability_hits(rid, int(fid), sorted(listed)):
            if h.get("type") == "damage" and h.get("targetID") in players:
                by_ability[h["abilityGameID"]].append((h["timestamp"], h["targetID"]))
        for aid, hs in by_ability.items():
            hs.sort()
            casts, cur = [], []
            for t, p in hs:
                if cur and t - cur[0][0] > OCCURRENCE_MS:
                    casts.append(cur)
                    cur = []
                cur.append((t, p))
            casts.append(cur)
            share = statistics.median(len({p for _, p in c}) / len(players) for c in casts)
            measured += 1
            if share > MOST_OF_RAID:
                items.append(f"{listed[aid]['name']} ({aid}) on {fight.get('name')} pull {fid}: "
                             f"a cast hits {share:.0%} of the raid")
    if not measured:
        return skip("no listed avoidable ability hit anyone in the pulls read")
    return fail(items) if items else PASS
