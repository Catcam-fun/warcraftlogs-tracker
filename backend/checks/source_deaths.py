"""Source check: the deaths the site reads against WarcraftLogs' own Deaths table."""
from collections import Counter

from analysis import get_report_deaths_bulk
from checks.common import TableCapped
from checks.verdict import PASS, fail, skip


def check(run):
    """Deaths the site reads match WCL's Deaths table"""
    if not run.pulls:
        return skip(f"no Mythic pulls of {run.raid} in {run.code}")
    ids = sorted(f["id"] for f in run.pulls)
    ours = get_report_deaths_bulk(run.token, run.code, run.pulls, run.meta["friendlies"], run.meta["abilities"])
    wcl = []
    for fid in ids:
        try:
            wcl += run.deaths_table(run.code, fid)
        except TableCapped:
            return skip(f"pull {fid} has 200+ deaths; WCL's table is capped")
    mine = {(fid, d["targetID"], d["timestamp"]): d.get("abilityName")
            for fid, ds in ours.items() for d in ds if not d.get("isCheatDeath")}
    theirs = {(e["fight"], e["id"], e["timestamp"]): (e.get("killingBlow") or {}).get("name", "Unknown")
              for e in wcl}
    missing = Counter(theirs.keys()) - Counter(mine.keys())
    extra = Counter(mine.keys()) - Counter(theirs.keys())
    kb = [k for k in theirs if k in mine and mine[k] != theirs[k]]
    items = [f"missing {k}" for k in missing] + [f"extra {k}" for k in extra]
    items += [f"killing blow {k}: site {mine[k]}, wcl {theirs[k]}" for k in kb]
    return fail(items) if items else PASS
