#!/usr/bin/env python3
"""
Flask API for WarcraftLogs Death Tracker - V2 GraphQL API
Optimized for Render/Cloud Run + Cloudflare Worker proxy
Version 2.4 – parallel fetch + robust retries + per-fight filtered cheat-death scan
"""

from flask import Flask, request, jsonify, Response
from flask_cors import CORS
import requests
from collections import defaultdict
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
import time
import os
import json
import math

app = Flask(__name__)
CORS(app)

# ---------------------------- CONFIG ------------------------------------
OAUTH_TOKEN_URL = "https://www.warcraftlogs.com/oauth/token"

# If you use a Cloudflare Worker proxy, set this env var:
#   WCL_GRAPHQL_URL=https://wcl-proxy.<your>.workers.dev/api/v2/client
WCL_GRAPHQL_URL = os.environ.get(
    "WCL_GRAPHQL_URL",
    "https://www.warcraftlogs.com/api/v2/client"
)

HTTP_TIMEOUT = 18          # shorter to avoid long stalls
HTTP_MAX_RETRIES = 4
THREADS = int(os.environ.get("WCL_THREADS", "4"))  # per-report parallelism

CHEAT_ABILITY_DEFAULTS = [
    "Cheat Death",            # Rogue
    "Purgatory",              # DK
    "Ardent Defender",        # Prot Paladin
    "Cauterize",              # Fire Mage
    "Guardian Spirit",        # Holy Priest
    "Spirit of Redemption",   # Holy Priest passive
    "Reincarnation",          # Shaman (self-res, optional but requested)
]

# --------------------- Utility: SSE writer ------------------------------
def _sse(obj):
    return f"data: {json.dumps(obj)}\n\n"

# --------------------- OAuth token cache --------------------------------
_token_cache = {"token": None, "expires": 0}

def get_token(client_id, client_secret):
    now = time.time()
    if _token_cache["token"] and now < _token_cache["expires"] - 60:
        return _token_cache["token"]

    data = {
        "grant_type": "client_credentials",
        "client_id": client_id,
        "client_secret": client_secret
    }
    resp = requests.post(OAUTH_TOKEN_URL, data=data, timeout=HTTP_TIMEOUT)
    resp.raise_for_status()
    token_data = resp.json()
    _token_cache["token"] = token_data["access_token"]
    # WCL tokens usually last for hours; store a conservative 1 hr
    _token_cache["expires"] = now + 3600
    return _token_cache["token"]

# --------------------- GraphQL helper (proxy aware) ---------------------
def graphql_query(token, query, variables, attempt=1):
    headers = {"Authorization": f"Bearer {token}"}
    try:
        r = requests.post(
            WCL_GRAPHQL_URL,
            json={"query": query, "variables": variables},
            headers=headers,
            timeout=HTTP_TIMEOUT,
        )
        # 429 = throttled, 5xx = transient => retry with backoff
        if r.status_code in (429, 502, 503, 504):
            if attempt < HTTP_MAX_RETRIES:
                time.sleep(min(2 ** attempt, 10))
                return graphql_query(token, query, variables, attempt + 1)
        r.raise_for_status()
        data = r.json()
        if data.get("errors"):
            # Retry only for server-ish errors visible in payload
            if attempt < HTTP_MAX_RETRIES:
                time.sleep(min(2 ** attempt, 10))
                return graphql_query(token, query, variables, attempt + 1)
        return data
    except requests.Timeout:
        if attempt < HTTP_MAX_RETRIES:
            time.sleep(min(2 ** attempt, 10))
            return graphql_query(token, query, variables, attempt + 1)
        raise

# --------------------- WCL primitive queries ----------------------------
def get_guild_reports(token, guild, server, region, zone_id, cutoff_iso, author_filters):
    # reports list (basic)
    q = """
    query($guildName:String!, $server:String!, $region:String!, $zone:Int!, $cutoff:Float!) {
      reportData {
        reports(guildName:$guildName, guildServerSlug:$server, guildServerRegion:$region, zoneID:$zone) {
          data {
            code
            startTime
            endTime
            title
            owner { name }
          }
        }
      }
    }"""
    v = {"guildName": guild, "server": server, "region": region, "zone": int(zone_id), "cutoff": 0.0}
    data = graphql_query(token, q, v)
    reports = data.get("reportData", {}).get("reports", {}).get("data", []) or []
    # apply cutoff + optional authors
    cutoff_ts = int(datetime.fromisoformat(cutoff_iso).timestamp() * 1000) if cutoff_iso else None
    out = []
    for r in reports:
        if cutoff_ts and r["startTime"] > cutoff_ts:
            continue
        if author_filters and r.get("owner", {}).get("name") not in author_filters:
            continue
        out.append({"id": r["code"], "start": r["startTime"], "end": r["endTime"], "owner": r.get("owner", {}).get("name")})
    return out

def get_fights(token, report_code):
    q = """
    query($code:String!) {
      reportData {
        report(code:$code) {
          startTime
          endTime
          fights { id startTime endTime encounterID name boss kill }
          friendlies { id name type }
          masterData { abilities { gameID name } }
        }
      }
    }"""
    v = {"code": report_code}
    d = graphql_query(token, q, v)
    rep = d.get("reportData", {}).get("report", {}) or {}
    abilities = rep.get("masterData", {}).get("abilities", []) or []
    ability_map = {a["gameID"]: a["name"] for a in abilities if a.get("gameID")}
    return {
        "report_start": rep.get("startTime", 0),
        "fights": rep.get("fights", []) or [],
        "friendlies": rep.get("friendlies", []) or [],
        "ability_map": ability_map,
    }

# --------------------- Event pagination (generic) -----------------------
def fetch_events_paginated(token, code, start_time, end_time, data_type,
                           page_limit=8000, max_pages=200, filter_expression=None,
                           on_progress=None):
    q = """
    query($code:String!, $start:Float!, $end:Float!, $after:Float, $limit:Int!, $type:EventDataType!, $expr:String) {
      reportData {
        report(code:$code) {
          events(
            startTime:$start
            endTime:$end
            page:$after
            limit:$limit
            dataType:$type
            filterExpression:$expr
          ) {
            data
            nextPageTimestamp
          }
        }
      }
    }"""
    v = {"code": code, "start": start_time, "end": end_time, "after": None, "limit": int(page_limit), "type": data_type, "expr": filter_expression}
    out, page = [], 0
    while True:
        page += 1
        d = graphql_query(token, q, v)
        rep = d.get("reportData", {}).get("report", {}) or {}
        evs = rep.get("events", {}) or {}
        out.extend(evs.get("data", []) or [])
        nxt = evs.get("nextPageTimestamp")
        if on_progress:
            try:
                on_progress(page, bool(nxt))
            except Exception:
                pass
        if not nxt or page >= max_pages:
            break
        v["after"] = nxt
    return out

# --------------------- Deaths + Cheat-death collectors ------------------
def get_report_deaths_bulk(token, report_code, fights, friendlies, ability_map):
    deaths_by_fight = {f["id"]: [] for f in fights}
    for f in fights:
        evs = fetch_events_paginated(
            token, report_code,
            f["start_time"], f["end_time"],
            data_type="Deaths",
            page_limit=8000,
            max_pages=50,
        )
        for ev in evs:
            if ev.get("type") != "death":
                continue
            # Attach what we need; ability names may be on killing blow
            kd = ev.get("killingAbility") or {}
            ability_name = kd.get("name") or ability_map.get(kd.get("gameID", -1), "Unknown")
            deaths_by_fight[f["id"]].append({
                "timestamp": ev.get("timestamp", 0),
                "targetName": ev.get("target", {}).get("name") or "Unknown",
                "targetID": ev.get("targetID"),
                "fightId": f["id"],
                "abilityName": ability_name,
            })
    return deaths_by_fight

def invert_ability_map(ability_id_to_name):
    name_to_ids = {}
    for aid, nm in (ability_id_to_name or {}).items():
        if not nm:
            continue
        name_to_ids.setdefault(str(nm).lower(), set()).add(int(aid))
    return name_to_ids

def fetch_cheat_buffs_for_fight(token, report_code, fight, ability_ids, on_progress=None):
    if not ability_ids:
        return []
    expr = '(type in ("applybuff","refreshbuff","removebuff","applybuffstack")) and (' + ' or '.join([f"ability.id={aid}" for aid in ability_ids]) + ')'
    return fetch_events_paginated(
        token=token,
        code=report_code,
        start_time=fight["start_time"],
        end_time=fight["end_time"],
        data_type="Buffs",
        page_limit=8000,
        max_pages=30,
        filter_expression=expr,
        on_progress=on_progress,
    )

def get_report_cheat_events_bulk(token, report_code, fights, friendlies, ability_map,
                                 cheat_names=None, send_progress=None):
    cheat_names = cheat_names or CHEAT_ABILITY_DEFAULTS
    cheat_names_lower = {n.lower() for n in cheat_names}
    name_to_ids = invert_ability_map(ability_map)

    ability_ids = set()
    for nm in cheat_names_lower:
        ability_ids |= name_to_ids.get(nm, set())

    if not fights or not ability_ids:
        return {f['id']: [] for f in fights} if fights else {}

    actor_id_to_name = {fr["id"]: fr["name"] for fr in (friendlies or []) if fr.get("id") and fr.get("name")}
    cheat_by_fight = {f['id']: [] for f in fights}

    for idx, f in enumerate(fights, start=1):
        if send_progress:
            send_progress(f"Cheat scan {idx}/{len(fights)}: {f.get('name','Fight')}")
        events = fetch_cheat_buffs_for_fight(
            token, report_code, f, sorted(ability_ids),
            on_progress=lambda p, more: send_progress and send_progress(f"  p.{p}{'…' if more else ''}")
        )
        for ev in events:
            ability_id = ev.get("abilityGameID") or (ev.get("ability") or {}).get("gameID")
            if ability_id not in ability_ids:
                continue
            target_id = ev.get("targetID")
            if target_id is None:
                continue
            cheat_by_fight[f['id']].append({
                "timestamp": ev.get("timestamp", 0),
                "targetName": actor_id_to_name.get(target_id, "Unknown"),
                "targetID": target_id,
                "fightId": f['id'],
                "abilityName": ability_map.get(ability_id, "Unknown"),
                "eventType": ev.get("type", "applybuff"),
            })
    return cheat_by_fight

# ------------------------- Fight filtering ------------------------------
def analyze_fights(fights, fight_zone, difficulty):
    out = []
    for f in fights or []:
        if not f.get("encounterID"):
            continue
        # Optional: match difficulty if present (WCL doesn't always surface)
        out.append({
            "id": f["id"],
            "boss": f.get("encounterID"),
            "name": f.get("name") or "Unknown",
            "kill": bool(f.get("kill")),
            "start_time": f.get("startTime", 0),
            "end_time": f.get("endTime", 0),
        })
    return out

# ----------------------- Dedup helper (per boss) -----------------------
def is_duplicate_pull(seen, boss_id, abs_start, abs_end, is_kill, window=35000):
    key = (boss_id, is_kill)
    prev = seen.get(key)
    if not prev:
        seen[key] = (abs_start, abs_end)
        return False
    ps, pe = prev
    # overlap within ~35s is a dup
    if abs(abs_start - ps) < window:
        return True
    seen[key] = (abs_start, abs_end)
    return False

# ---------------------------- API: health --------------------------------
@app.route('/api/health')
def health():
    return jsonify({"status": "ok", "ts": int(time.time())})

# ---------------------------- API: analyze --------------------------------
@app.route('/api/analyze', methods=['POST', 'OPTIONS'])
def analyze():
    if request.method == 'OPTIONS':
        resp = jsonify({'ok': True})
        resp.headers.add('Access-Control-Allow-Origin', '*')
        resp.headers.add('Access-Control-Allow-Headers', 'Content-Type')
        resp.headers.add('Access-Control-Allow-Methods', 'POST, OPTIONS')
        return resp

    try:
        config = request.json or {}
    except Exception as e:
        resp = jsonify({"error": f"Invalid request: {e}"})
        resp.headers.add('Access-Control-Allow-Origin', '*')
        return resp, 400

    def generate():
        try:
            client_id = config.get('clientId')
            client_secret = config.get('clientSecret')
            guild_name = config.get('guildName')
            server = config.get('server')
            region = config.get('region', 'us')
            report_zone = config.get('reportZone')
            fight_zone = config.get('fightZone')
            difficulty = config.get('difficulty', '5')
            max_cutoff = int(config.get('maxCutoff', 5))
            cutoff_date = config.get('cutoffDate')
            author_filters = config.get('authorFilters', [])
            character_groups = config.get('characterGroups', {})
            include_cheat = bool(config.get('includeCheatEvents', False))
            cheatAbilityNames = config.get('cheatAbilityNames', CHEAT_ABILITY_DEFAULTS)

            # Stage: OAuth
            yield _sse({"stage": "init", "message": "Requesting token..."})
            token = get_token(client_id, client_secret)
            yield _sse({"stage": "init", "message": "Token ok. Fetching reports..."})

            reports = get_guild_reports(
                token, guild_name, server, region, report_zone, cutoff_date, author_filters
            )
            if not reports:
                yield _sse({"result": {
                    "meta": {"maxCutoff": max_cutoff, "authorFilters": author_filters, "dateCutoff": cutoff_date,
                             "zone": fight_zone, "difficulty": difficulty, "generatedAt": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                             "characterGroups": character_groups, "reportCount": 0, "includeCheatEvents": include_cheat,
                             "cheatAbilityNames": cheatAbilityNames},
                    "events": {}, "pullParticipation": {}, "bossParticipation": {}, "characterBreakdown": {},
                    "cheatEvents": {}
                }})
                return

            yield _sse({"stage": "fights", "message": f"Found {len(reports)} reports. Collecting fights..."})

            # Fetch fights + abilities per report (parallel)
            all_fights_raw = []
            report_ability_maps = {}
            with ThreadPoolExecutor(max_workers=THREADS) as ex:
                futures = {}
                for i, rep in enumerate(reports, 1):
                    rid = rep["id"]
                    futures[ex.submit(get_fights, token, rid)] = (i, rid, rep)

                for fut in as_completed(futures):
                    i, rid, rep = futures[fut]
                    try:
                        fights_data = fut.result()
                    except Exception as e:
                        yield _sse({"stage": "warn", "message": f"Failed fights for report {rid}: {e}"})
                        continue

                    yield _sse({"stage": "fights", "message": f"Report {i}/{len(reports)}: {rid}"})
                    report_ability_maps[rid] = fights_data["ability_map"]
                    fights = fights_data["fights"]
                    friendlies = fights_data["friendlies"]
                    report_abs_start = rep["start"]

                    if not fights:
                        continue

                    matching = analyze_fights(fights, fight_zone, difficulty)
                    for fight in matching:
                        fid = fight['id']
                        boss_name = fight.get('name', 'Unknown')
                        boss_id = fight.get('boss', 0)
                        is_kill = bool(fight.get('kill'))
                        rel_start, rel_end = fight['start_time'], fight['end_time']
                        abs_start, abs_end = report_abs_start + rel_start, report_abs_start + rel_end

                        all_fights_raw.append({
                            "report": rid,
                            "fight": {
                                "id": fid, "boss": boss_id, "name": boss_name,
                                "start_time": rel_start, "end_time": rel_end, "kill": is_kill,
                            },
                            "boss_id": boss_id,
                            "boss_name": boss_name,
                            "is_kill": is_kill,
                            "abs_start": abs_start,
                            "abs_end": abs_end,
                            "friendlies": friendlies,
                            "ability_map": report_ability_maps[rid],
                            "report_abs_start": report_abs_start
                        })

            # Deduplicate pulls
            yield _sse({"stage": "dedup", "message": "Removing duplicate pulls..."})
            seen_pulls_by_boss = {}
            all_fights_deduped = []
            for fight_data in sorted(all_fights_raw, key=lambda x: (x['report'], x['abs_start'])):
                boss_id = fight_data['boss_id']
                if is_duplicate_pull(seen_pulls_by_boss, boss_id, fight_data['abs_start'], fight_data['abs_end'], fight_data['is_kill']):
                    continue
                all_fights_deduped.append(fight_data)
            yield _sse({"stage": "dedup", "message": f"After dedup: {len(all_fights_deduped)} unique fights"})

            # Group by report
            fights_by_report = defaultdict(list)
            for fd in all_fights_deduped:
                fights_by_report[fd["report"]].append(fd)

            # Fetch Deaths (and optional cheat scans) per report in parallel
            yield _sse({"stage": "deaths", "message": "Fetching death events..."} )
            report_deaths_cache = {}
            report_cheats_cache = {} if include_cheat else None

            def _fetch_report_pair(rid, report_fights):
                sample = report_fights[0]
                friendlies = sample['friendlies']
                ability_map = sample['ability_map']
                fights_list = [fd['fight'] for fd in report_fights]
                deaths = get_report_deaths_bulk(token, rid, fights_list, friendlies, ability_map)
                cheats = None
                if include_cheat:
                    cheats = get_report_cheat_events_bulk(
                        token, rid, fights_list, friendlies, ability_map,
                        cheat_names=cheatAbilityNames,
                        send_progress=lambda msg: None
                    )
                return rid, deaths, cheats

            with ThreadPoolExecutor(max_workers=THREADS) as ex:
                futures = {ex.submit(_fetch_report_pair, rid, rfs): rid for rid, rfs in fights_by_report.items()}
                done_count = 0
                for fut in as_completed(futures):
                    rid = futures[fut]
                    try:
                        rid_out, deaths, cheats = fut.result()
                        report_deaths_cache[rid_out] = deaths
                        if include_cheat:
                            report_cheats_cache[rid_out] = cheats or {}
                    except Exception as e:
                        yield _sse({"stage": "warn", "message": f"Failed events for report {rid}: {e}"})
                    done_count += 1
                    yield _sse({"stage": "deaths", "message": f"Processed {done_count}/{len(fights_by_report)} reports"})

            # Aggregate by player
            yield _sse({"stage": "processing", "message": f"Processing {len(all_fights_deduped)} fights..."})
            counted_death_events = {}
            pull_participation = defaultdict(list)
            boss_participation = defaultdict(lambda: defaultdict(list))
            character_breakdown = defaultdict(lambda: defaultdict(int))
            cheat_events_by_player = defaultdict(list) if include_cheat else {}

            # main <-> alt grouping
            def get_main_character(name, groups):
                for main, alts in groups.items():
                    if name == main or name in alts:
                        return main
                return name

            for idx, fight_data in enumerate(all_fights_deduped, 1):
                if idx % 12 == 0:
                    yield _sse({"stage": "processing", "message": f"Processing fight {idx}/{len(all_fights_deduped)}"})

                rid = fight_data["report"]
                fight = fight_data["fight"]
                fid = fight["id"]
                boss_id = fight_data["boss_id"]
                boss_name = fight_data["boss_name"]
                is_kill = fight["kill"]
                report_abs_start = fight_data["report_abs_start"]

                # Deaths
                for ev in report_deaths_cache.get(rid, {}).get(fid, []):
                    original_char = ev["targetName"]
                    main_char = get_main_character(original_char, character_groups)
                    seq_no = 1  # rank within pull here refers to ordering among first N deaths
                    death_event = {
                        "player": main_char,
                        "originalCharacter": original_char,
                        "boss": boss_name,
                        "bossId": boss_id,
                        "phase": 1,
                        "reportId": rid,
                        "fightId": fid,
                        "isKill": is_kill,
                        "pullNo": 0,  # filled below by participation calc if you track pulls
                        "rankWithinPull": seq_no,
                        "absTs": report_abs_start + ev["timestamp"],
                        "abilityName": ev.get("abilityName", "Unknown"),
                        "isCheat": False
                    }
                    counted_death_events.setdefault(main_char, []).append(death_event)
                    pull_participation[main_char].append(fid)
                    boss_participation[boss_name][main_char].append(fid)
                    character_breakdown[main_char][boss_name] += 1

                # Cheat events
                if include_cheat:
                    cheats = report_cheats_cache.get(rid, {}).get(fid, [])
                    cheats_sorted = sorted(cheats, key=lambda e: e.get("timestamp", 0))[:max_cutoff]
                    for rank, cev in enumerate(cheats_sorted, start=1):
                        original_char = cev["targetName"]
                        main_char = get_main_character(original_char, character_groups)
                        cheat_events_by_player[main_char].append({
                            "player": main_char,
                            "originalCharacter": original_char,
                            "boss": boss_name,
                            "bossId": boss_id,
                            "phase": 1,
                            "reportId": rid,
                            "fightId": fid,
                            "isKill": is_kill,
                            "pullNo": 0,
                            "rankWithinPull": rank,
                            "absTs": report_abs_start + cev.get("timestamp", 0),
                            "abilityName": cev.get("abilityName", "Unknown"),
                            "isCheat": True,
                            "eventType": cev.get("eventType", "applybuff")
                        })

            # Final response
            response = {
                "meta": {
                    "maxCutoff": max_cutoff,
                    "authorFilters": author_filters,
                    "dateCutoff": cutoff_date,
                    "zone": fight_zone,
                    "difficulty": difficulty,
                    "generatedAt": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "characterGroups": character_groups,
                    "reportCount": len(reports),
                    "includeCheatEvents": include_cheat,
                    "cheatAbilityNames": cheatAbilityNames
                },
                "events": counted_death_events,
                "pullParticipation": pull_participation,
                "bossParticipation": boss_participation,
                "characterBreakdown": character_breakdown,
                "cheatEvents": (cheat_events_by_player if include_cheat else {})
            }
            yield _sse({"result": response})

        except Exception as e:
            yield _sse({"error": str(e)})

    resp = Response(generate(), mimetype='text/event-stream')
    resp.headers.add('Access-Control-Allow-Origin', '*')
    return resp

# ---------------------------- root info ---------------------------------
@app.route('/')
def root():
    return jsonify({
        "service": "WarcraftLogs Death Tracker API",
        "version": "2.4",
        "graphql_url": WCL_GRAPHQL_URL,
        "threads": THREADS,
        "endpoints": {"health": "/api/health", "analyze": "POST /api/analyze (SSE)"},
    })

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    print(f"Starting WarcraftLogs Death Tracker API v2.4 on port {port}…")
    app.run(debug=False, host='0.0.0.0', port=port)
