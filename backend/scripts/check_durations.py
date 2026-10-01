"""Check how long defensives last (catalog + each player's talents) against real uses in a log.

    WCL_CLIENT_ID=... WCL_CLIENT_SECRET=... python backend/scripts/check_durations.py <reportCode>:<raid> [...]

For every personal defensive with duration talents, each use in the raid's
Mythic pulls (aura applied -> removed) is compared with the duration the
analysis predicts from that player's own talents that pull. "Ended early" is
normal (a shield broke, it was cancelled, they died); "LONGER" means the
catalog is missing something: fix it in scripts/build_defensive_catalog.py.
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


def main():
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    token = get_access_token(os.environ["WCL_CLIENT_ID"], os.environ["WCL_CLIENT_SECRET"])
    res = defaultdict(lambda: {"n": 0, "exact": 0, "early": 0, "longer": []})
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
        up = {}
        for e in sorted(raw["buffs"], key=lambda e: e["timestamp"]):
            name = meta["abilities"].get(e.get("abilityGameID"))
            sid = cat.name_to_id.get(name)
            if not sid or cat.all[sid]["kind"] != "personal" or not cat.all[sid].get("duration_mods"):
                continue
            key = (e.get("targetID"), name)
            if e["type"] == "applybuff":
                up[key] = e["timestamp"]
            elif e["type"] == "removebuff" and key in up:
                start = up.pop(key)
                fid = next((i for s, t, i in spans if s <= start <= t), None)
                pid = e["targetID"]
                talents = idx["talents"].get((fid, pid))
                if fid is None or talents is None:
                    continue
                spec = defensives.pull_spec(idx, fid, pid, (meta["player_details"].get(pid) or {}).get("spec"))
                want, got = defensives._talented_duration(cat.all[sid], talents, spec), e["timestamp"] - start
                r = res[name]
                r["n"] += 1
                if abs(got - want) <= TOLERANCE_MS:
                    r["exact"] += 1
                elif got < want:
                    r["early"] += 1
                else:
                    r["longer"].append((round(got / 1000, 1), round(want / 1000, 1)))
    print(f"{'defensive':26s} uses  exact  ended early  longer")
    for name, r in sorted(res.items()):
        flag = "  <-- LONGER" if len(r["longer"]) > r["n"] // 10 else ""
        print(f"{name:26s} {r['n']:4d} {r['exact']:6d} {r['early']:12d} {len(r['longer']):7d}{flag}  {r['longer'][:3]}")


if __name__ == "__main__":
    main()
