"""Build the Stats page's data: deaths across every public Mythic kill of the current tier.

    WCL_CLIENT_ID=... WCL_CLIENT_SECRET=... STATS_CACHE=/tmp/tier-stats \\
        python backend/scripts/build_tier_stats.py [raid key] [--max-kills N] [--budget POINTS]

Reads every boss of the raid key (default: CURRENT_TIER) from
analysis.RAID_ENCOUNTERS: its ranked Mythic kills per WCL partition (patch),
then each kill's players and deaths (tier_stats.read_kill). Kills are cached
in STATS_CACHE, so a rerun only reads new kills: a first full run is
about 2 WCL points per kill, a weekly refresh a few hundred points.

--max-kills N: only the first N kills of each boss per patch (a quick preview).
--budget POINTS: WCL points this script may spend per hour (default 2400 of
the key's 3600, so the site's own analyses keep working); past it, the script
waits for WCL's hourly reset.
--max-minutes M: stop reading kills after M minutes and write what's read;
the next run carries on from the cache. The file only ever holds each boss's
kills from the first one up to the first one not read yet.

Writes frontend/public/stats/<raid key>.json.
"""
import argparse
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import boss_spell_text  # noqa: E402
import tier_stats  # noqa: E402
from analysis import RAID_ENCOUNTERS  # noqa: E402
from warcraftlogs import get_access_token, graphql_query  # noqa: E402

CURRENT_TIER = "midnight-s2-all"
OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "frontend", "public", "stats")
WORKERS = 6
BATCH = 60   # kills read between budget checks


class Budget:
    """Pauses until WCL's hourly reset once this hour's spend passes the budget."""

    def __init__(self, token, per_hour):
        self.token, self.per_hour = token, per_hour

    def wait(self, deadline=None):
        """True once there's budget; False if `deadline` (epoch s) comes first."""
        while True:
            rl = graphql_query(self.token, "{ rateLimitData { pointsSpentThisHour pointsResetIn } }")["rateLimitData"]
            if rl["pointsSpentThisHour"] < self.per_hour:
                return True
            if deadline and time.time() + rl["pointsResetIn"] > deadline:
                return False
            print(f"  {rl['pointsSpentThisHour']:.0f} WCL points spent this hour; waiting {rl['pointsResetIn']}s",
                  flush=True)
            time.sleep(rl["pointsResetIn"] + 5)


def dumps_by_line(out):
    """Compact JSON with one kill per line, so a refresh that adds kills is a small git diff."""
    compact = lambda v: json.dumps(v, separators=(",", ":"), ensure_ascii=False)  # noqa: E731
    head = {k: v for k, v in out.items() if k != "patches"}
    lines = [compact(head)[:-1] + ',"patches":[']
    for i, p in enumerate(out["patches"]):
        lines.append(f'{{"name":{compact(p["name"])},"bosses":{{')
        bosses = list(p["bosses"].items())
        for j, (boss, kills) in enumerate(bosses):
            lines.append(f"{compact(boss)}:[")
            lines += [compact(k) + ("," if n < len(kills) - 1 else "") for n, k in enumerate(kills)]
            lines.append("]" + ("," if j < len(bosses) - 1 else ""))
        lines.append("}}" + ("," if i < len(out["patches"]) - 1 else ""))
    lines.append("]}")
    return "\n".join(lines) + "\n"


def boss_names(token, encounter_ids):
    parts = " ".join(f"e{e}: encounter(id: {e}) {{ name }}" for e in encounter_ids)
    data = graphql_query(token, "{ worldData { %s } }" % parts)["worldData"]
    return {e: (data.get(f"e{e}") or {}).get("name") or str(e) for e in encounter_ids}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("raid", nargs="?", default=CURRENT_TIER)
    ap.add_argument("--max-kills", type=int, default=None)
    ap.add_argument("--budget", type=float, default=2400)
    ap.add_argument("--max-minutes", type=float, default=None,
                    help="stop reading kills after this long and write what's read (the next run continues)")
    args = ap.parse_args()

    cache = os.environ.get("STATS_CACHE") or "/tmp/tier-stats"
    token = get_access_token(os.environ["WCL_CLIENT_ID"], os.environ["WCL_CLIENT_SECRET"])
    budget = Budget(token, args.budget)
    encounters = sorted(RAID_ENCOUNTERS[args.raid])
    names = boss_names(token, encounters)

    # Ranked kills of every boss, per partition (patch).
    by_partition = {}
    partitions = tier_stats.zone_partitions(token, encounters[0])
    for enc in encounters:
        for pid, pname in partitions:
            budget.wait()
            kills = tier_stats.ranked_kills(token, enc, pid, limit=args.max_kills)
            print(f"{names[enc]} ({pname}): {len(kills)} ranked kills with a public log", flush=True)
            by_partition.setdefault(pname, []).extend(kills)

    # Each kill's players and deaths, cached.
    records, todo = {}, []
    for kills in by_partition.values():
        for k in kills:
            rec = tier_stats.load_cached(cache, k["code"], k["fight"])
            if rec is not None:
                records[(k["code"], k["fight"])] = rec
            else:
                todo.append(k)
    # Oldest first across bosses, so every boss's run of kills grows together.
    todo.sort(key=lambda k: k["t"])
    print(f"{len(records)} kills cached, {len(todo)} to read", flush=True)
    failed = 0
    started = time.time()
    for i in range(0, len(todo), BATCH):
        deadline = started + args.max_minutes * 60 if args.max_minutes else None
        if (deadline and time.time() > deadline) or not budget.wait(deadline):
            print(f"  stopping after {args.max_minutes:g} minutes; {len(todo) - i} kills left for the next run")
            break
        with ThreadPoolExecutor(max_workers=WORKERS) as pool:
            futures = {pool.submit(tier_stats.read_kill, token, k): k for k in todo[i:i + BATCH]}
            for fut in as_completed(futures):
                k = futures[fut]
                try:
                    rec = fut.result()
                except Exception as e:
                    failed += 1
                    print(f"  {k['code']}#{k['fight']}: {e}", flush=True)
                    continue
                # An unreadable kill is cached too (as empty), so it isn't retried every run.
                rec = rec or {"specs": [], "deaths": []}
                tier_stats.save_cached(cache, k["code"], k["fight"], rec)
                records[(k["code"], k["fight"])] = rec
        print(f"  read {min(i + BATCH, len(todo))}/{len(todo)}", flush=True)

    # Names and icons of every killing ability, from the master data of a report it killed someone in.
    abilities_path = os.path.join(cache, "abilities.json")
    try:
        with open(abilities_path) as f:
            abilities = {int(a): v for a, v in json.load(f).items()}
    except (OSError, ValueError):
        abilities = {}
    missing = {}
    for kills in by_partition.values():
        for k in kills:
            for _, aid, _ in (records.get((k["code"], k["fight"])) or {}).get("deaths", []):
                if aid and aid not in abilities:
                    missing.setdefault(k["code"], set()).add(aid)
    while missing:
        code = max(missing, key=lambda c: len(missing[c]))
        want = missing.pop(code)
        budget.wait()
        got = tier_stats.ability_names(token, code, want)
        abilities.update(got)
        for c in list(missing):
            missing[c] -= set(got)
            if not missing[c]:
                del missing[c]
    os.makedirs(cache, exist_ok=True)
    with open(abilities_path, "w") as f:
        json.dump({str(a): v for a, v in abilities.items()}, f)

    out = tier_stats.build_output(
        args.raid, [(e, names[e]) for e in encounters], by_partition,
        records,
        {a: [n, icon, boss_spell_text.text_for(a)] for a, (n, icon) in abilities.items()})
    os.makedirs(OUT_DIR, exist_ok=True)
    path = os.path.join(OUT_DIR, f"{args.raid}.json")
    # "Updated" moves only when the stats do, so a run without new kills changes nothing.
    try:
        with open(path) as f:
            old = json.load(f)
    except (OSError, ValueError):
        old = {}
    same = {k: v for k, v in old.items() if k != "updated"} == out
    out["updated"] = old.get("updated") if same and old.get("updated") else int(time.time() * 1000)
    with open(path, "w") as f:
        f.write(dumps_by_line(out))
    kills = sum(len(ks) for p in out["patches"] for ks in p["bosses"].values())
    print(f"Wrote {path}: {kills} kills, {os.path.getsize(path) // 1024} KB" + (f", {failed} failed" if failed else ""))


if __name__ == "__main__":
    main()
