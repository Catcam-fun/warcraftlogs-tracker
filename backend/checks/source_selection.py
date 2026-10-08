"""Source check: the pulls and kills the site kept, against an independent walk of the guild's reports."""
from datetime import datetime, timezone

import analysis
from checks.common import raid_week
from checks.verdict import PASS, fail, skip
from warcraftlogs import get_guild_reports, get_report_fights


def cluster(pulls):
    """Group pulls of one boss whose intervals overlap, transitively."""
    out = []
    by_boss = {}
    for p in pulls:
        by_boss.setdefault(p["boss"], []).append(p)
    for group in by_boss.values():
        group = sorted(group, key=lambda p: (p["start"], p["end"]))
        current, reach = [], None
        for p in group:
            if current and p["start"] <= reach:
                current.append(p)
                reach = max(reach, p["end"])
            else:
                if current:
                    out.append(current)
                current, reach = [p], p["end"]
        if current:
            out.append(current)
    return out


def walk(run, start, end):
    """Every Mythic pull of the raid in the guild's reports over [start, end], with absolute times."""
    name, server, region = run.guild
    wanted = analysis.RAID_ENCOUNTERS[run.raid]
    pulls = []
    for rep in get_guild_reports(run.token, name, server, region, start, end):
        data = get_report_fights(run.token, rep["id"])
        base = data.get("report_start") or 0
        for f in data.get("fights") or []:
            if f.get("boss") not in wanted or f.get("difficulty") != 5:
                continue
            pulls.append({"key": f"{rep['id']}_{f['id']}", "boss": f["boss"], "name": f.get("name"),
                          "start": base + f["start_time"], "end": base + f["end_time"],
                          "kill": bool(f.get("kill"))})
    return pulls


def _iso(ms):
    return datetime.fromtimestamp(ms / 1000, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def check(run):
    """The pulls and kills the site kept match the guild's reports on WCL"""
    if run.guild is None:
        return skip("no guild for this report")
    kept = {key for players in run.result["bossParticipation"].values()
            for keys in players.values() for key in keys}
    pulls = walk(run, *raid_week(run.meta["report_start"]))
    clusters = cluster(pulls)
    by_key = {p["key"]: p for p in pulls}
    label = lambda p: p.get("name") or str(p["boss"])
    items = []
    for c in sorted(clusters, key=lambda c: (min(p["start"] for p in c), c[0]["boss"])):
        first = min(c, key=lambda p: p["start"])
        got = sorted(p["key"] for p in c if p["key"] in kept)
        head = f"cluster {label(first)} {_iso(first['start'])}"
        if not got:
            items.append(f"{head}: no kept pull")
        elif len(got) > 1:
            items.append(f"{head}: {len(got)} kept pulls {got}")
    in_cluster = {p["key"] for c in clusters for p in c}
    items += [f"kept pull {k}: not in any cluster" for k in sorted(kept - in_cluster)]
    bosses = {}
    for c in clusters:
        b = bosses.setdefault(c[0]["boss"], [label(c[0]), 0, 0])
        b[2] += any(p["kill"] for p in c)
    for key in kept & set(by_key):
        if by_key[key]["kill"]:
            bosses[by_key[key]["boss"]][1] += 1
    for name, site, wcl in sorted(bosses.values()):
        if site != wcl:
            items.append(f"{name}: site kills {site}, wcl kills {wcl}")
    return fail(items) if items else PASS
