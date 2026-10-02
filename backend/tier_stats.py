"""
tier_stats.py - Death statistics across every Mythic kill of the current tier.

For the Stats page: which boss abilities kill raiders, and how often each spec
dies, read from public WarcraftLogs kills rather than from one guild's analysis.

Kills come from WCL's "progress" fight rankings: every guild's first Mythic
kill of a boss in a ranking partition (WCL splits rankings by patch), in kill
order. WCL serves at most 1000 rankings per query, so they're read per region,
and per server for a region past that cap.

Each kill's deaths are slotted with the analysis's own rule
(analysis.rank_pull_deaths), so "first X deaths" means the same here as in an
analysis. Kills are read once and cached as JSON files (they never change);
scripts/build_tier_stats.py turns the cache into the file the Stats page loads.
"""

import json
import os

import defensives
from analysis import rank_pull_deaths
from warcraftlogs import graphql_query

MYTHIC = 5
# The Stats page counts up to the first 20 deaths of a kill.
MAX_SLOT = 20
REGIONS = ("US", "EU", "KR", "TW", "CN")
REGION_IDS = {"US": 1, "EU": 2, "KR": 3, "TW": 4, "CN": 5}
# WCL's rankings API: 50 per page, page 20 at most.
RANKINGS_PER_PAGE = 50
MAX_RANKING_PAGE = 20
# Bump when a kill record's shape or the way it's read changes: cached kills are reread.
KILL_SHAPE = 2


def zone_partitions(token, encounter_id):
    """[(partition id, name)] of the encounter's zone, oldest first ("12.1")."""
    data = graphql_query(token, """query($e: Int!) { worldData { encounter(id: $e) {
        zone { partitions { id name } } } } }""", {"e": encounter_id})
    zone = (((data.get("worldData") or {}).get("encounter") or {}).get("zone")) or {}
    return sorted((p["id"], p["name"]) for p in zone.get("partitions") or [])


def _rankings_page(token, encounter_id, partition, page, region=None, server=None):
    data = graphql_query(token, """query($e: Int!, $p: Int!, $part: Int, $r: String, $s: String) {
        worldData { encounter(id: $e) { fightRankings(difficulty: 5, metric: progress, partition: $part,
            page: $p, serverRegion: $r, serverSlug: $s) } } }""",
                         {"e": encounter_id, "p": page, "part": partition, "r": region, "s": server})
    block = (((data.get("worldData") or {}).get("encounter") or {}).get("fightRankings")) or {}
    if block.get("error"):
        raise Exception(f"WCL rankings: {block['error']}")
    return block.get("rankings") or [], bool(block.get("hasMorePages"))


def _all_pages(token, encounter_id, partition, region=None, server=None, limit=None):
    """Every ranking of one query (the first `limit` if given); capped is True
    when WCL had more than it serves."""
    out = []
    for page in range(1, MAX_RANKING_PAGE + 1):
        rows, more = _rankings_page(token, encounter_id, partition, page, region, server)
        out += rows
        if not more:
            return out, False
        if limit and len(out) >= limit:
            return out, False
    return out, True


def region_servers(token, region):
    """Slugs of every server in a region."""
    out = []
    for page in range(1, 20):
        data = graphql_query(token, """query($r: Int!, $p: Int!) { worldData { region(id: $r) {
            servers(limit: 100, page: $p) { has_more_pages data { slug } } } } }""",
                             {"r": REGION_IDS[region], "p": page})
        block = ((((data.get("worldData") or {}).get("region")) or {}).get("servers")) or {}
        out += [s["slug"] for s in block.get("data") or []]
        if not block.get("has_more_pages"):
            break
    return out


def ranked_kills(token, encounter_id, partition, limit=None, log=print):
    """Every ranked Mythic kill of the encounter in one partition, by kill time
    (the first `limit` if given).

    One per guild (its first kill in the partition). Kills whose log is private
    have no report and are left out: they can't be read.
    """
    rows = []
    for region in REGIONS:
        # Rankings come in kill order, so a region's first `limit` public kills cover the first
        # `limit` overall (with headroom for private logs, which are skipped).
        got, capped = _all_pages(token, encounter_id, partition, region,
                                 limit=limit * 3 // 2 + RANKINGS_PER_PAGE if limit else None)
        if capped:
            log(f"    {region}: past WCL's {MAX_RANKING_PAGE * RANKINGS_PER_PAGE} cap, reading per server")
            got = []
            for slug in region_servers(token, region):
                part, capped = _all_pages(token, encounter_id, partition, region, slug)
                if capped:
                    log(f"    WARNING {region}/{slug}: still capped at {len(part)} kills")
                got += part
        rows += got
    kills, seen = [], set()
    for r in rows:
        rep = r.get("report") or {}
        key = (rep.get("code"), rep.get("fightID"))
        if not rep.get("code") or key in seen:
            continue
        seen.add(key)
        # A ranking's startTime is when the boss died; events are report-relative.
        end = r["startTime"] - rep["startTime"]
        kills.append({"boss": encounter_id, "code": rep["code"], "fight": rep["fightID"],
                      "t": r["startTime"], "report_start": rep["startTime"],
                      "start": end - (r.get("duration") or 0), "end": end, "deaths": r.get("deaths"),
                      "region": (r.get("server") or {}).get("region")})
    kills.sort(key=lambda k: k["t"])
    return kills[:limit] if limit else kills


def _spec_key(cls, spec):
    return f"{cls}-{spec}" if cls and spec else None


def read_kill(token, kill):
    """One kill: who was in it (by spec) and its deaths that can count.

    `kill`: a ranked_kills entry (report code, fight ID, the fight's
    report-relative start and end, and WCL's death count for it).
    Returns {"specs": [spec key per player], "deaths": [[slot, abilityID, spec key]]},
    or None if the fight isn't readable. slot: which real death of the pull it
    was (analysis.rank_pull_deaths); deaths in a wipe are left out (they never
    count). One request: about 1 WCL point, 2 if anyone died.
    """
    code, fight_id, start, end = kill["code"], kill["fight"], kill["start"], kill["end"]
    with_deaths = kill.get("deaths") != 0
    deaths_part = """deaths: events(fightIDs: $f, startTime: $s, endTime: $e, dataType: Deaths, limit: 10000) {
                data nextPageTimestamp }""" if with_deaths else ""
    data = graphql_query(token, """query($c: String!, $f: [Int]!, $s: Float!, $e: Float!) { reportData {
        report(code: $c) { playerDetails(fightIDs: $f, startTime: $s, endTime: $e) %s } } }""" % deaths_part,
                         {"c": code, "f": [fight_id], "s": start, "e": end + 1})
    report = (data.get("reportData") or {}).get("report") or {}
    details = ((report.get("playerDetails") or {}).get("data") or {}).get("playerDetails") or {}
    spec_of = {}
    for role in ("tanks", "healers", "dps"):
        for p in details.get(role) or []:
            key = _spec_key(p.get("type"), (p.get("specs") or [{}])[0].get("spec"))
            if p.get("id") and key:
                spec_of[p["id"]] = key
    if not spec_of:
        return None

    block = report.get("deaths") or {}
    events = block.get("data") or []
    if block.get("nextPageTimestamp"):
        events += defensives._paged(token, code, "Deaths", None, fight_ids=[fight_id],
                                    start_time=block["nextPageTimestamp"], end_time=end + 1)
    deaths = sorted((e for e in events if e.get("type") == "death" and e.get("fight") == fight_id
                     and e.get("targetID") in spec_of), key=lambda e: e["timestamp"])
    # The analysis's slot rule, on real deaths (cheat deaths aren't fetched: they never take a slot).
    slots = rank_pull_deaths([{"timestamp": d["timestamp"]} for d in deaths])
    return {
        "specs": sorted(spec_of.values()),
        "deaths": [[slot, d.get("killingAbilityGameID") or 0, spec_of[d["targetID"]]]
                   for d, (slot, in_wipe) in zip(deaths, slots) if slot <= MAX_SLOT and not in_wipe],
    }


def ability_names(token, code, ability_ids):
    """{abilityID: [name, icon]} for the given abilities, from one report's master data (1 WCL point)."""
    data = graphql_query(token, """query($c: String!) { reportData { report(code: $c) {
        masterData { abilities { gameID name icon } } } } }""", {"c": code})
    master = (((data.get("reportData") or {}).get("report") or {}).get("masterData")) or {}
    want = set(ability_ids)
    return {a["gameID"]: [a.get("name") or "Unknown", defensives.clean_icon(a.get("icon"))]
            for a in master.get("abilities") or [] if a.get("gameID") in want}


def cache_path(cache_dir, code, fight_id):
    return os.path.join(cache_dir, f"{code}-{fight_id}.json")


def load_cached(cache_dir, code, fight_id):
    try:
        with open(cache_path(cache_dir, code, fight_id)) as f:
            rec = json.load(f)
        return rec if rec.get("shape") == KILL_SHAPE else None
    except (OSError, ValueError):
        return None


def save_cached(cache_dir, code, fight_id, rec):
    os.makedirs(cache_dir, exist_ok=True)
    tmp = cache_path(cache_dir, code, fight_id) + ".tmp"
    with open(tmp, "w") as f:
        json.dump({"shape": KILL_SHAPE, **rec}, f, separators=(",", ":"))
    os.replace(tmp, cache_path(cache_dir, code, fight_id))


def build_output(raid_key, boss_names, kills_by_partition, records, abilities):
    """The Stats page's data file.

    kills_by_partition: {partition name: [ranked kill dicts]} (ranked_kills);
    records: {(code, fight): read_kill result}; each boss's kills are kept up
    to its first kill that hasn't been read yet.
    abilities: {abilityID: [name, icon, in-game description or None]}.

    Specs and abilities are listed once and referred to by index to keep the
    file small. Per patch and boss, kills in kill order, each
    [[spec index of every player], [slot, ability index, spec index, ...]].
    """
    spec_idx, specs = {}, []
    ab_idx, ab_list = {}, []

    def index(key, idx, lst):
        if key not in idx:
            idx[key] = len(lst)
            lst.append(key)
        return idx[key]

    patches = []
    for name, kills in kills_by_partition.items():
        bosses, stopped = {}, set()
        for k in sorted(kills, key=lambda k: k["t"]):
            if k["boss"] in stopped:
                continue
            rec = records.get((k["code"], k["fight"]))
            if rec is None:
                # Not read yet: each boss keeps an unbroken run from its first kill, so "first X" stays right.
                stopped.add(k["boss"])
                continue
            if not rec.get("specs"):
                continue    # unreadable log
            deaths = []
            for slot, aid, spec in rec["deaths"]:
                deaths += [slot, index(aid, ab_idx, ab_list), index(spec, spec_idx, specs)]
            bosses.setdefault(str(k["boss"]), []).append(
                [sorted(index(sp, spec_idx, specs) for sp in rec["specs"]), deaths])
        patches.append({"name": name, "bosses": bosses})
    return {
        "raid": raid_key,
        "bosses": [{"id": b, "name": n} for b, n in boss_names],
        "specs": specs,
        # [ability ID, name, icon, in-game description]
        "abilities": [[a] + list(abilities.get(a) or ["Unknown", None, None]) for a in ab_list],
        "patches": patches,
    }
