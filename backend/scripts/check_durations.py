"""Check how long defensives last (catalog + each player's talents) against real uses in a log.

    WCL_CLIENT_ID=... WCL_CLIENT_SECRET=... python backend/scripts/check_durations.py <reportCode>:<raid> [...]

For every personal defensive with duration talents, each use in the raid's
Mythic pulls (aura applied -> removed) is compared with the duration the
analysis predicts from that player's own talents that pull. A press while the
aura is still up (a "refreshbuff": a second charge, or Smoke Screen granting
Survival of the Fittest) starts a new use from that moment, which keeps up to
30% of the old one's remaining time (the game's pandemic rule). Each aura ID
is timed on its own, except same-named auras that aren't the defensive
(NOT_THE_BUTTON). Uses stretched by something with no fixed size are counted
under "extended": a duration that scales with a spec's mastery (Augmentation's
Mastery: Timewalker), or another press that adds time to the running aura
(EXTENDED_BY). "Ended early" is normal (a shield broke, it was cancelled, they
died); "LONGER" means the catalog is missing something: fix it in
scripts/build_defensive_catalog.py.
Raid cooldowns other players cast (Rallying Cry...) follow the caster's
talents, and some auras are extended mid-fight (Dancing Rune Weapon,
Metamorphosis): those can read longer without affecting any verdict.
"""
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import analysis  # noqa: E402
import defensives  # noqa: E402
from warcraftlogs import get_access_token, get_fights  # noqa: E402

TOLERANCE_MS = 350
PANDEMIC = 0.3          # share of a use's duration a refresh can carry over
# Same-named auras that aren't the defensive's window: The War Within's Renewing
# Blaze heal-back (374349), which runs on after the 8s window (374348).
NOT_THE_BUTTON = {374349}
# Presses that add time to a running aura without logging a refresh: with Smoke
# Screen, Exhilaration adds 3s to an active Survival of the Fittest.
EXTENDED_BY = {"Survival of the Fittest": "Exhilaration"}


def carried_over(presses, want):
    """How much of the earlier presses' time the last press (a refresh) can keep, in ms:
    each refresh restarts the aura with up to PANDEMIC of the time that was left."""
    end, carried = presses[0] + want, 0
    for t in presses[1:]:
        carried = min(max(end - t, 0), want * PANDEMIC)
        end = t + want + carried
    return carried


def main():
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    token = get_access_token(os.environ["WCL_CLIENT_ID"], os.environ["WCL_CLIENT_SECRET"])
    res = defaultdict(lambda: {"n": 0, "exact": 0, "early": 0, "extended": 0, "longer": []})
    for arg in sys.argv[1:]:
        code, raid = arg.split(":")
        meta = get_fights(token, code)
        fights = analysis.analyze_fights(meta["fights"], None, 5, raid)
        ids = sorted(f["id"] for f in fights)
        cat = defensives.catalog_for(meta["report_start"])
        raw = defensives.fetch_defensive_raw(token, code, ids, min(f["start_time"] for f in fights),
                                             max(f["end_time"] for f in fights), cat)
        idx = defensives.filter_defensive_raw(raw, {e["sourceID"] for e in raw["combatants"]}, cat)
        spans = [(f["start_time"], f["end_time"], f["id"]) for f in fights]
        casts = defaultdict(list)
        for e in raw["casts"]:
            casts[(e.get("sourceID"), meta["abilities"].get(e.get("abilityGameID")))].append(e["timestamp"])
        up = {}
        for e in sorted(raw["buffs"], key=lambda e: e["timestamp"]):
            aid = e.get("abilityGameID")
            name = meta["abilities"].get(aid)
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
                if want - TOLERANCE_MS <= got <= want + carried + TOLERANCE_MS:
                    r["exact"] += 1
                elif got < want:
                    r["early"] += 1
                elif any(m.get("mastery") and defensives._mod_rank(m, talents, spec)
                         for m in entry["duration_mods"]) or \
                        any(presses[-1] < t < e["timestamp"] for t in casts[(pid, EXTENDED_BY.get(name))]):
                    r["extended"] += 1
                else:
                    r["longer"].append((round(got / 1000, 1), round((want + carried) / 1000, 1)))
    print(f"{'defensive':26s} uses  exact  ended early  extended  longer")
    for name, r in sorted(res.items()):
        flag = "  <-- LONGER" if len(r["longer"]) > r["n"] // 10 else ""
        print(f"{name:26s} {r['n']:4d} {r['exact']:6d} {r['early']:12d} {r['extended']:9d} "
              f"{len(r['longer']):7d}{flag}  {r['longer'][:3]}")


if __name__ == "__main__":
    main()
