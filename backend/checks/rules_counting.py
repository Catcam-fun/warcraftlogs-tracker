"""A death counts when slot <= X and not in a wipe; defensives exist exactly on deaths that can count"""
from checks.verdict import PASS, fail, skip


def is_counted(ev, x):
    """Mirror of frontend/src/deathCounting.js: ev["slot"] <= x and not ev["inWipe"]."""
    return ev["slot"] <= x and not ev["inWipe"]


def counts(result, x):
    """player -> (real deaths counted, cheat deaths counted) for the first x deaths of each pull."""
    out = {}
    for player, evs in result["events"].items():
        real = sum(1 for ev in evs if is_counted(ev, x) and not ev["isCheatDeath"])
        cheat = sum(1 for ev in evs if is_counted(ev, x) and ev["isCheatDeath"])
        out[player] = (real, cheat)
    return out


def check(run):
    """A death counts when slot <= X and not in a wipe; defensives exist exactly on deaths that can count"""
    result = run.result
    events = result.get("events") or {}
    if not any(events.values()):
        return skip("no death events in the result")
    max_cut = result["meta"]["maxCutoff"]
    items = []
    for x in range(1, max_cut + 1):
        got = counts(result, x)
        for player, evs in events.items():
            real = sum(1 for ev in evs if ev["slot"] <= x and not ev["inWipe"] and not ev["isCheatDeath"])
            if got[player][0] != real:
                items.append(f"{player} first {x}: counted {got[player][0]}, recount {real}")
    for player, evs in events.items():
        for ev in evs:
            should = is_counted(ev, max_cut) and not ev["isCheatDeath"]
            has = "defensives" in ev
            where = f"{player} pull {ev['fightId']} {ev['timestamp']}"
            if has and not should:
                items.append(f"{where}: defensives present but death cannot count")
            elif should and not has:
                items.append(f"{where}: death can count but has no defensives")
    return fail(items) if items else PASS
