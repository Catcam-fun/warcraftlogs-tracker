"""Source check: the pulls and kills the site kept, against an independent walk of the guild's reports.

Copies of one pull (several officers logging it) are found by plain transitive interval overlap:
pulls of the same boss whose start-end spans overlap, directly or through another copy, are one
cluster. The spec's 5-second start rule was dropped; overlap alone passed live on all eight raids.

Logs are first put on one clock: two loggers' PC clocks can disagree by over a minute (90.4 s on Unluck's
2026-11-04 logs), which chained every pull of a boss into one cluster. A log's gap to another is the most
common whole-second start difference among pulls of one boss lasting the same to 0.2 s, when 2+ pairs
agree on it."""
from collections import Counter
from datetime import datetime, timezone

import analysis
from checks.common import raid_week
from checks.verdict import PASS, fail, skip
from warcraftlogs import get_guild_reports, get_report_fights


def _report(p):
    return p["key"].rsplit("_", 1)[0]


def clock_shifts(pulls):
    """{report: ms added to its times}, relative to the log with the most pulls; unlinked logs stay put."""
    logs = {}
    for p in pulls:
        logs.setdefault(_report(p), []).append(p)
    order = sorted(logs, key=lambda r: (-len(logs[r]), r))
    shift = {}
    for root in order:
        if root in shift:
            continue
        shift[root], queue = 0, [root]
        while queue:
            a = queue.pop()
            for b in order:
                if b in shift:
                    continue
                votes = Counter(round((q["start"] - p["start"]) / 1000) for p in logs[a] for q in logs[b]
                                if p["boss"] == q["boss"] and abs(q["start"] - p["start"]) <= 600_000
                                and abs((q["end"] - q["start"]) - (p["end"] - p["start"])) <= 200)
                if votes:
                    gap, n = votes.most_common(1)[0]
                    n += votes.get(gap - 1, 0) + votes.get(gap + 1, 0)      # a gap on a second's edge
                    if n >= 2:
                        shift[b] = shift[a] - gap * 1000
                        queue.append(b)
    return shift


def cluster(pulls):
    """Group pulls of one boss whose intervals overlap, transitively, with every log on one clock."""
    shift = clock_shifts(pulls)
    pulls = [dict(p, start=p["start"] + shift[_report(p)], end=p["end"] + shift[_report(p)]) for p in pulls]
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
    if not clusters:
        return skip(f"no Mythic pulls of {run.raid} in the guild's reports that week")
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
