"""Run the defensive analysis on one real WarcraftLogs report and print it.

    WCL_CLIENT_ID=... WCL_CLIENT_SECRET=... python backend/scripts/check_defensives.py <reportCode> [fightID]

Checks that the talent loadouts WCL returns look the way defensives.py
expects, then prints each boss-pull death with its defensive picture.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from analysis import _fetch_remaining_events, get_report_deaths_bulk  # noqa: E402
from defensive_catalog import CATALOG  # noqa: E402
import defensives  # noqa: E402
from warcraftlogs import get_access_token, get_fights  # noqa: E402


def main():
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    code, only_fight = sys.argv[1], (int(sys.argv[2]) if len(sys.argv) > 2 else None)
    token = get_access_token(os.environ["WCL_CLIENT_ID"], os.environ["WCL_CLIENT_SECRET"])
    meta = get_fights(token, code)
    fights = [f for f in meta["fights"] if f.get("boss") and (only_fight is None or f["id"] == only_fight)]
    if not fights:
        raise SystemExit("No boss fights found in that report.")
    start, end = min(f["start_time"] for f in fights), max(f["end_time"] for f in fights)
    indexed = defensives.fetch_defensive_events(
        token, code, max(0, start - defensives.ENCOUNTER_RESET_MS), end, _fetch_remaining_events)

    talents = indexed["talents"]
    all_entries = {e for d in CATALOG.values() for e in d["talent_entries"]}
    matched = sum(1 for s in talents.values() if s & all_entries)
    print(f"Talent loadouts: {len(talents)} player-pulls, {matched} contain catalog defensives")
    if talents and not matched:
        print("  !! Talent entry IDs never match the catalog: check the CombatantInfo talentTree format")
    print(f"Defensive casts: {sum(len(v) for v in indexed['casts'].values())}, "
          f"buff events: {sum(len(v) for v in indexed['buffs'].values())}\n")

    deaths = get_report_deaths_bulk(token, code, fights, meta["friendlies"], meta["abilities"])
    cls = {f["id"]: f["type"] for f in meta["friendlies"]}
    names = {f["id"]: f["name"] for f in meta["friendlies"]}
    for f in fights:
        for d in sorted(deaths.get(f["id"], []), key=lambda d: d["timestamp"]):
            pid = d.get("targetID")
            spec = (meta["player_details"].get(pid) or {}).get("spec")
            r = defensives.analyze_death(pid, cls.get(pid), spec, f["id"], f["start_time"], d["timestamp"],
                                         indexed, meta["abilities"], names)
            t = (d["timestamp"] - f["start_time"]) / 1000
            print(f"[{f['name']} #{f['id']} +{t:.0f}s] {names.get(pid)} ({spec} {cls.get(pid)}) "
                  f"- {d.get('abilityName')}{'' if r['talentsKnown'] else '  (no talent data)'}")
            print("   active:   ", ", ".join(a["name"] + (f" ({a['by']})" if a.get("by") else "") for a in r["active"]) or "-")
            print("   available:", ", ".join(a["name"] for a in r["available"]) or "-")
            print("   cooldown: ", ", ".join(f"{a['name']} (used {a['usedAgo']}s ago)" for a in r["cooldown"]) or "-")
            print(f"   healthstone: {r['healthstone']['usedAgo']}  potion: {r['potion']['usedAgo']}")


if __name__ == "__main__":
    main()
