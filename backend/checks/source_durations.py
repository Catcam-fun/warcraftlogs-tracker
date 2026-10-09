"""Source check: defensive durations against real aura uses in the log."""
from collections import defaultdict

import defensives
from checks.verdict import PASS, fail, skip

TOLERANCE_MS = 350
PANDEMIC = 0.3          # share of a use's duration a refresh can carry over
# Same-named auras that aren't the defensive's window: The War Within's Renewing
# Blaze heal-back (374349), which runs on after the 8s window (374348).
NOT_THE_BUTTON = {374349}
# Presses that add time to a running aura without logging a refresh: with Smoke
# Screen, Exhilaration adds 3s to an active Survival of the Fittest.
EXTENDED_BY = {"Survival of the Fittest": "Exhilaration"}
# Auras the spec extends mid-fight by playing (the owner's rule: Dancing Rune Weapon and
# Metamorphosis can read longer without affecting verdicts), so a longer use is not a missing talent.
EXTENDED_MID_FIGHT = {"Dancing Rune Weapon", "Metamorphosis"}
# Auras that last while a pet is out end when it despawns, a moment after its time: Earth Elemental's +15% max
# health (381755) ran 30.2-30.6 s on a Shaman without Everlasting Elements and 36.2-36.7 s on one with it
# (30 s, x1.2) in P6CwHkgFR9Krf1Bz (12.0.7). Extra ms allowed past the predicted end:
DESPAWN_LAG_MS = {"Earth Elemental": 1_000}


def carried_over(presses, want):
    """How much of the earlier presses' time the last press (a refresh) can keep, in ms:
    each refresh restarts the aura with up to PANDEMIC of the time that was left."""
    end, carried = presses[0] + want, 0
    for t in presses[1:]:
        carried = min(max(end - t, 0), want * PANDEMIC)
        end = t + want + carried
    return carried


def check(run):
    """Defensive durations (catalog + talents) match real aura uses"""
    fights = run.pulls
    if not fights:
        return skip(f"no Mythic pulls of {run.raid} in {run.code}")
    meta, cat = run.meta, run.cat
    ids = sorted(f["id"] for f in fights)
    raw = defensives.fetch_defensive_raw(run.token, run.code, ids, min(f["start_time"] for f in fights),
                                         max(f["end_time"] for f in fights), cat)
    idx = defensives.filter_defensive_raw(raw, {e["sourceID"] for e in raw["combatants"]}, cat)
    spans = [(f["start_time"], f["end_time"], f["id"]) for f in fights]
    casts = defaultdict(list)
    for e in raw["casts"]:
        casts[(e.get("sourceID"), meta["abilities"].get(e.get("abilityGameID")))].append(e["timestamp"])
    res = defaultdict(lambda: {"n": 0, "exact": 0, "early": 0, "extended": 0, "longer": []})
    up = {}
    for e in sorted(raw["buffs"], key=lambda e: e["timestamp"]):
        aid = e.get("abilityGameID")
        name = defensives.aura_name(cat, aid, meta["abilities"])      # the aura carrying the effect
        sid = cat.name_to_id.get(name)
        entry = cat.all.get(sid) if sid else None
        if not entry or entry["kind"] != "personal" or not entry.get("duration_mods"):
            continue
        if aid in NOT_THE_BUTTON:
            continue
        key = (e.get("targetID"), aid)
        if e["type"] == "applybuff" or (e["type"] == "refreshbuff" and key not in up):
            up[key] = [e["timestamp"]]
        elif e["type"] == "refreshbuff":
            up[key].append(e["timestamp"])
        elif e["type"] == "removebuff" and key in up:
            presses = up.pop(key)
            fid = next((i for s, t, i in spans if s <= presses[0] <= t), None)
            pid = e["targetID"]
            talents = idx["talents"].get((fid, pid))
            if fid is None or talents is None:
                continue
            spec = defensives.pull_spec(idx, fid, pid, (meta["player_details"].get(pid) or {}).get("spec"))
            want = defensives._talented_duration(entry, talents, spec)
            carried = carried_over(presses, want)
            got = e["timestamp"] - presses[-1]
            r = res[name]
            r["n"] += 1
            if want - TOLERANCE_MS <= got <= want + carried + TOLERANCE_MS + DESPAWN_LAG_MS.get(name, 0):
                r["exact"] += 1
            elif got < want:
                r["early"] += 1
            elif name in EXTENDED_MID_FIGHT or any(m.get("mastery") and defensives._mod_rank(m, talents, spec)
                     for m in entry["duration_mods"]) or \
                    any(presses[-1] < t < e["timestamp"] for t in casts[(pid, EXTENDED_BY.get(name))]):
                r["extended"] += 1
            else:
                r["longer"].append((round(got / 1000, 1), round((want + carried) / 1000, 1)))
    if not any(r["n"] for r in res.values()):
        return skip("no duration-talent defensive uses measured")
    items = []
    for name, r in sorted(res.items()):
        if len(r["longer"]) > r["n"] // 10:
            got, want = r["longer"][0]
            items.append(f"{name}: {len(r['longer'])} of {r['n']} uses longer than predicted, "
                         f"e.g. {got}s vs {want}s")
    return fail(items) if items else PASS
