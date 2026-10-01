"""Run the defensive analysis on one real WarcraftLogs report and print it.

    WCL_CLIENT_ID=... WCL_CLIENT_SECRET=... python backend/scripts/check_defensives.py <reportCode> [fightID]

Checks that the talent loadouts WCL returns look the way defensives.py
expects, then prints each boss-pull death with its defensive picture.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from analysis import get_report_deaths_bulk  # noqa: E402
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
    deaths = get_report_deaths_bulk(token, code, fights, meta["friendlies"], meta["abilities"])
    dead = {d["targetID"] for ds in deaths.values() for d in ds if d.get("targetID")}
    cat = defensives.catalog_for(meta.get("report_start"))
    print(f"Patch {cat.patch}")
    indexed = defensives.fetch_defensive_events(token, code, [f["id"] for f in fights], start, end, dead, cat)
    log_names = {f["id"]: f.get("logName") or f["name"] for f in meta["friendlies"]}
    windows = defensives.fetch_death_windows(token, code, [
        (f["id"], [(d["timestamp"], log_names.get(d.get("targetID"))) for d in deaths.get(f["id"], [])])
        for f in fights])
    hits = defensives.merge_hits(windows, defensives.fetch_instakills(token, code, [f["id"] for f in fights],
                                                                      start, end))

    talents = indexed["talents"]
    all_entries = {e for d in cat.all.values() for e in d["talent_entries"]}
    matched = sum(1 for s in talents.values() if set(s) & all_entries)
    print(f"Talent loadouts: {len(talents)} player-pulls, {matched} contain catalog defensives")
    if talents and not matched:
        print("  !! Talent entry IDs never match the catalog: check the CombatantInfo talentTree format")
    print(f"Defensive casts: {sum(len(v) for v in indexed['casts'].values())}, "
          f"buff events: {sum(len(v) for v in indexed['buffs'].values())}\n")

    cls = {f["id"]: f["type"] for f in meta["friendlies"]}
    names = {f["id"]: f["name"] for f in meta["friendlies"]}
    for f in fights:
        for d in sorted(deaths.get(f["id"], []), key=lambda d: d["timestamp"]):
            pid = d.get("targetID")
            spec = (meta["player_details"].get(pid) or {}).get("spec")
            r = defensives.analyze_death(pid, cls.get(pid), spec, f["id"], f["start_time"], d["timestamp"],
                                         indexed, meta["abilities"], names, hits=hits.get(pid, []),
                                         ability_schools=meta.get("ability_schools", {}), cat=cat,
                                         aoe_known=defensives.logs_mark_aoe(hits),
                                         armor_k=defensives.armor_constant(f.get("boss"), f.get("difficulty")))
            t = (d["timestamp"] - f["start_time"]) / 1000
            print(f"[{f['name']} #{f['id']} +{t:.0f}s] {names.get(pid)} ({spec} {cls.get(pid)}) "
                  f"- {d.get('abilityName')}{'' if r['talentsKnown'] else '  (no talent data)'}")
            print("   active:   ", ", ".join(a["name"] + (f" ({a['by']})" if a.get("by") else "") for a in r["active"]) or "-")
            print("   available:", ", ".join(a["name"] + (f" (with {a['withForm']})" if a.get("withForm") else "")
                                         for a in r["available"]) or "-")
            print("   cooldown: ", ", ".join(f"{a['name']} (used {a['usedAgo']}s ago)" for a in r["cooldown"]) or "-")
            print(f"   healthstone: {r['healthstone']['usedAgo']}  potion: {r['potion']['usedAgo']}"
                  + (f" (rank {r['potion']['rank'].get('rank', 'too close to tell')})" if r["potion"].get("rank") else ""))
            if r.get("survival"):
                sv = r["survival"]
                if sv.get("deathType") == "instakill":
                    print(f"   instant kill: {sv['killingHit']['name']}")
                    continue
                print(f"   killing blow: {sv['killingHit']['name']} {sv['killingHit']['pctOfMax']}% of max, "
                      f"overkill {sv['overkill']:,}; {sv['deathType']}, {sv['window']['hits']} hits over "
                      f"{sv['window']['fromAgo']}s; would save: {sv['wouldSave']}")
                if sv.get("biggestHit"):
                    b = sv["biggestHit"]
                    print(f"   biggest hit before it: {b['name']} {b['pctOfMax']}% of max, {b['ago']}s before")
                for name, det in sv["details"].items():
                    extra = []
                    if det.get("talents"):
                        extra.append("talents " + ", ".join(x["talent"] for x in det["talents"]))
                    if det.get("rank"):
                        extra.append(f"rank {det['rank'].get('rank', 'too close to tell')} (base {det['rank']['base']:,} vs "
                                     + ", ".join(f"{x['rank']} {x['heal']:,}" for x in det['rank']['ranks']) + ")")
                    if det.get("why"):
                        extra.append("why " + det["why"])
                    if det.get("pressAgo") is not None:
                        extra.append(f"pressed {det['pressAgo']}s before")
                    print(f"      {name}: {det['amount']:,}" + (" | " + "; ".join(extra) if extra else ""))


if __name__ == "__main__":
    main()
