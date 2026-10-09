"""find-logs: pick one finished Mythic log per raid key, from WCL's fight rankings of the raid's first boss."""
import os
import time

from analysis import RAID_ENCOUNTERS
from warcraftlogs import get_access_token, get_report_fights, graphql_query

MIN_WIPES, FINISHED_MS, REGIONS = 3, 2 * 3600 * 1000, ("US", "EU")
MYTHIC = 5
PAGES = (1, 2)
MAX_TRIES = 12   # reports looked at per raid (1 point each)

_QUERY = """
query($id: Int!, $page: Int!) {
  worldData { encounter(id: $id) { fightRankings(difficulty: %d, page: $page) } }
}
""" % MYTHIC


def candidates(token, raid, page=1):
    """Ranked reports for the raid's first boss: US and EU guilds first, one report per guild."""
    data = graphql_query(token, _QUERY, {"id": min(RAID_ENCOUNTERS[raid]), "page": page})
    rankings = ((data.get("worldData") or {}).get("encounter") or {}).get("fightRankings") or {}
    seen, out = set(), []
    for r in rankings.get("rankings") or []:
        guild, server, report = r.get("guild") or {}, r.get("server") or {}, r.get("report") or {}
        if not report.get("code") or not guild.get("name"):
            continue
        key = (guild["name"], server.get("name"), server.get("region"))
        if key in seen:
            continue
        seen.add(key)
        out.append({"code": report["code"], "guild": key, "region": server.get("region")})
    out.sort(key=lambda c: c["region"] not in REGIONS)   # stable: ranking order kept inside each group
    return out


def good_log(token, raid, cand, now_ms):
    """The target string if the report holds enough Mythic wipes of the raid and is long finished, else None."""
    light = get_report_fights(token, cand["code"])
    fights = light.get("fights") or []
    bosses = RAID_ENCOUNTERS[raid]
    wipes = [f for f in fights if f.get("boss") in bosses and f.get("difficulty") == MYTHIC and not f.get("kill")]
    if len(wipes) < MIN_WIPES:
        return None
    if light.get("report_start", 0) + max(f.get("end_time", 0) for f in fights) >= now_ms - FINISHED_MS:
        return None
    return f"{cand['code']}:{raid}:{'/'.join(cand['guild'])}"


def main(raid_keys):
    bad = [k for k in raid_keys if k not in RAID_ENCOUNTERS]
    if bad:
        print(f"Unknown raid key {', '.join(bad)}; one of: {', '.join(RAID_ENCOUNTERS)}")
        return 2
    token = get_access_token(os.environ["WCL_CLIENT_ID"], os.environ["WCL_CLIENT_SECRET"])
    now_ms = int(time.time() * 1000)
    for raid in raid_keys or list(RAID_ENCOUNTERS):
        found, tried = None, 0
        for page in PAGES:
            try:
                cands = candidates(token, raid, page)
            except Exception as e:
                print(f"{raid}: ranking lookup failed ({type(e).__name__}: {e})")
                break
            for cand in cands:
                if tried >= MAX_TRIES:
                    break
                tried += 1
                try:
                    found = good_log(token, raid, cand, now_ms)
                except Exception:
                    found = None
                if found:
                    break
            if found or tried >= MAX_TRIES:
                break
        print(found or f"{raid}: no log found")
    return 0
