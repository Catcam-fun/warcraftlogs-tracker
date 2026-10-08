"""Slots and wipes recomputed from WarcraftLogs' own Deaths table under the owner's rules.

The rule: real deaths take slots 1, 2, 3... in log order, same-millisecond deaths one each, a rezzed
player twice. A cheat death's slot is the real deaths so far + 1 and never takes a real death's slot.
A death is in a wipe when some 8000 ms stretch that starts or ends at a real death holds 8 or more
real deaths and contains it.
"""
from checks.common import TableCapped
from checks.verdict import PASS, fail, skip

WIPE_DEATHS, WIPE_MS = 8, 8000


def rank(deaths):
    """deaths: (timestamp, player id, is cheat death) in combat-log order; returns (slot, in_wipe) per death."""
    real_ts = [ts for ts, _, cheat in deaths if not cheat]
    stretches = []
    for t in real_ts:
        stretches.append((t, t + WIPE_MS))
        stretches.append((t - WIPE_MS, t))
    wipes = [(lo, hi) for lo, hi in stretches
             if sum(1 for x in real_ts if lo <= x <= hi) >= WIPE_DEATHS]
    out, real_so_far = [], 0
    for ts, _, cheat in deaths:
        if cheat:
            slot = real_so_far + 1
        else:
            real_so_far += 1
            slot = real_so_far
        out.append((slot, any(lo <= ts <= hi for lo, hi in wipes)))
    return out


def _site_events(run):
    for value in run.result["events"].values():
        for e in (value if isinstance(value, list) else [value]):
            yield e


def check(run):
    """Slots and wipes follow the owner's rules"""
    events = list(_site_events(run))
    if not events:
        return skip("no death events in the result")
    pulls = {}
    for e in events:
        if e.get("isCheatDeath"):
            continue  # WCL's Deaths table has no cheat deaths
        pulls.setdefault((e["reportId"], e["fightId"]), []).append(e)
    items = []
    for (rid, fid), evs in pulls.items():
        try:
            entries = run.deaths_table(rid, fid)
        except TableCapped:
            items.append(f"pull {fid}: 200+ deaths, table capped")
            continue
        entries = sorted(entries, key=lambda x: x["timestamp"])  # stable: ties keep the table's order
        ranked = rank([(x["timestamp"], x["id"], False) for x in entries])
        start = run.fight(rid, fid)["start_time"]
        lookup = {}
        for x, r in zip(entries, ranked):
            lookup.setdefault((x["id"], x["timestamp"]), []).append(r)
        # A player WCL lists twice on one millisecond died twice: each site death takes the next one.
        for e in sorted(evs, key=lambda e: (e["timestamp"], e.get("slot") or 0)):
            ts = e["timestamp"] + start
            who = e.get("originalCharacter")
            cands = lookup.get((run.actor_id(rid, who), ts))
            if not cands:
                items.append(f"pull {fid} {who} {e['timestamp']}: not in WCL's Deaths table")
                continue
            slot, wipe = cands.pop(0)
            if slot != e.get("slot") or bool(wipe) != bool(e.get("inWipe")):
                items.append(f"pull {fid} {who} {e['timestamp']}: site slot {e.get('slot')} "
                             f"inWipe {bool(e.get('inWipe'))}, rule slot {slot} inWipe {wipe}")
    return fail(items) if items else PASS
