"""Check the deaths the site reads against WarcraftLogs' own Deaths table.

    WCL_CLIENT_ID=... WCL_CLIENT_SECRET=... python backend/scripts/check_deaths.py <reportCode>:<raid> [...]

<raid> is a RAID_ENCOUNTERS key (e.g. midnight-s2-all). For each report's
Mythic pulls of that raid, every death the analysis reads (player, pull,
timestamp, killing ability) is compared with WCL's Deaths table, one pull at a
time (the table stops at 200 entries). Run it on a log from each raid after a
new tier or any change to how deaths are fetched: it should print 0 missing,
0 extra, 0 different killing blows.
"""
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import analysis  # noqa: E402
from warcraftlogs import get_access_token, get_fights, graphql_query  # noqa: E402

PULLS_PER_REQUEST = 15


def main():
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    token = get_access_token(os.environ["WCL_CLIENT_ID"], os.environ["WCL_CLIENT_SECRET"])
    bad = 0
    for arg in sys.argv[1:]:
        code, raid = arg.split(":")
        meta = get_fights(token, code)
        ids = sorted(f["id"] for f in analysis.analyze_fights(meta["fights"], None, 5, raid))
        fights = [f for f in meta["fights"] if f["id"] in ids]
        ours = analysis.get_report_deaths_bulk(token, code, fights, meta["friendlies"], meta["abilities"])
        wcl = []
        for i in range(0, len(ids), PULLS_PER_REQUEST):
            q = "query($c: String!) { reportData { report(code: $c) { " + " ".join(
                f"f{f}: table(dataType: Deaths, fightIDs: [{f}])" for f in ids[i:i + PULLS_PER_REQUEST]) + " } } }"
            for block in graphql_query(token, q, {"c": code})["reportData"]["report"].values():
                entries = block["data"]["entries"]
                if len(entries) >= 200:
                    raise SystemExit("A pull reached the table's 200-entry cap: can't check it this way.")
                wcl += entries
        mine = {(fid, d["targetID"], d["timestamp"]): d.get("abilityName")
                for fid, ds in ours.items() for d in ds if not d.get("isCheatDeath")}
        theirs = {(e["fight"], e["id"], e["timestamp"]): (e.get("killingBlow") or {}).get("name", "Unknown")
                  for e in wcl}
        missing, extra = Counter(theirs.keys()) - Counter(mine.keys()), Counter(mine.keys()) - Counter(theirs.keys())
        kb = [k for k in theirs if k in mine and mine[k] != theirs[k]]
        print(f"{raid} {code}: WCL {len(theirs)} deaths, read {len(mine)}; missing {len(missing)}, "
              f"extra {len(extra)}, different killing blow {len(kb)}")
        for k in list(missing)[:5] + list(extra)[:5] + kb[:5]:
            print("   ", k)
        bad += len(missing) + len(extra) + len(kb)
    raise SystemExit(1 if bad else 0)


if __name__ == "__main__":
    main()
