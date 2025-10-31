#!/usr/bin/env python3
"""
Flask API for WarcraftLogs Death Tracker - V2 GraphQL API
Optimized for Render.com deployment
Version 2.3 + Cheat-Death bulk scan (Buffs) per report
"""

from flask import Flask, request, jsonify, Response
from flask_cors import CORS
import requests
from collections import defaultdict
from datetime import datetime
import time
import os
import json

app = Flask(__name__)
CORS(app)

# === Existing constants/behavior (kept) ==================================
MASS_DEATH_THRESHOLD = 7
MASS_DEATH_WINDOW = 10000  # ms

# Use your Cloudflare Worker proxy exactly like your working build
GRAPHQL_ENDPOINT = "https://wcl-proxy.catcam-fun.workers.dev/api/v2/client"
OAUTH_TOKEN_URL   = "https://wcl-proxy.catcam-fun.workers.dev/oauth/token"

_token_cache = {"token": None, "expires_at": 0}

def get_access_token(client_id, client_secret):
    global _token_cache
    if _token_cache["token"] and time.time() < _token_cache["expires_at"]:
        return _token_cache["token"]
    data = {"grant_type": "client_credentials","client_id": client_id,"client_secret": client_secret}
    resp = requests.post(OAUTH_TOKEN_URL, data=data, timeout=30)
    resp.raise_for_status()
    tok = resp.json()
    _token_cache["token"] = tok["access_token"]
    _token_cache["expires_at"] = time.time() + tok.get("expires_in", 3600) - 60
    return _token_cache["token"]

def graphql_query(token, query, variables=None):
    headers = {"Authorization": f"Bearer {token}","Content-Type": "application/json"}
    payload = {"query": query}
    if variables: payload["variables"] = variables
    resp = requests.post(GRAPHQL_ENDPOINT, json=payload, headers=headers, timeout=60)
    resp.raise_for_status()
    data = resp.json()
    if "errors" in data:
        raise Exception(f"GraphQL errors: {data['errors']}")
    return data.get("data", {})

def get_main_character(player_name, character_groups):
    for main, alts in character_groups.items():
        if player_name in alts:
            return main
    return player_name

def get_guild_reports(token, guild_name, server, region, zone_id, cutoff_date):
    cutoff_ts = int(datetime.strptime(cutoff_date, "%Y-%m-%d").timestamp() * 1000) + 86400000 - 1
    q = """
    query($guildName: String!, $serverSlug: String!, $serverRegion: String!, $zoneID: Int!) {
      reportData {
        reports(guildName: $guildName, guildServerSlug: $serverSlug, guildServerRegion: $serverRegion, zoneID: $zoneID, limit: 100) {
          data { code startTime endTime zone { id } owner { name } }
        }
      }
    }"""
    v = {"guildName": guild_name,
         "serverSlug": server.lower().replace(" ", "-").replace("'", ""),
         "serverRegion": region.upper(),
         "zoneID": int(zone_id)}
    data = graphql_query(token, q, v)
    rows = data.get("reportData", {}).get("reports", {}).get("data", []) or []
    out = []
    for r in rows:
        if r.get("startTime", 0) > cutoff_ts:  # same cutoff as your build
            continue
        out.append({"id": r["code"], "start": r.get("startTime", 0), "end": r.get("endTime", 0), "owner": r.get("owner", {}).get("name", "")})
    return out

def get_fights(token, report_code):
    q = """
    query($code: String!) {
      reportData {
        report(code: $code) {
          startTime
          fights { id startTime endTime name encounterID difficulty kill gameZone { id } friendlyPlayers }
          masterData { actors(type: "Player") { id name type subType } }
          masterData { abilities { gameID name } }
        }
      }
    }"""
    d = graphql_query(token, q, {"code": report_code})
    rep = d.get("reportData", {}).get("report", {}) or {}
    fights = rep.get("fights", []) or []
    actors = rep.get("masterData", {}).get("actors", []) or []
    abilities = rep.get("masterData", {}).get("abilities", []) or []
    ability_map = {a["gameID"]: a["name"] for a in abilities if a.get("gameID")}
    formatted_fights = []
    for f in fights:
        formatted_fights.append({
            "id": f.get("id"),
            "start_time": f.get("startTime"),
            "end_time": f.get("endTime"),
            "name": f.get("name"),
            "boss": f.get("encounterID"),
            "difficulty": f.get("difficulty"),
            "kill": f.get("kill"),
            "zoneID": f.get("gameZone", {}).get("id") if f.get("gameZone") else None,
            "friendlyPlayers": f.get("friendlyPlayers", [])
        })
    formatted_friendlies = []
    for a in actors:
        if a.get("type") == "Player":
            formatted_friendlies.append({"id": a.get("id"), "name": a.get("name"), "type": a.get("subType")})
    return {"report_start": rep.get("startTime", 0), "fights": formatted_fights, "friendlies": formatted_friendlies, "ability_map": ability_map}

# === Existing deaths-in-bulk (kept as-is) ===============================
def get_report_deaths_bulk(token, report_code, fights, friendlies, ability_map):
    if not fights: return {}
    actor_id_to_name = {fr.get("id"): fr.get("name") for fr in friendlies if fr.get("id") and fr.get("name")}
    start_time = min(f['start_time'] for f in fights)
    end_time   = max(f['end_time'] for f in fights)
    q = """
    query($code: String!, $startTime: Float!, $endTime: Float!) {
      reportData { report(code: $code) {
        events(startTime: $startTime, endTime: $endTime, dataType: Deaths, limit: 10000) { data }
      }}}"""
    d = graphql_query(token, q, {"code": report_code, "startTime": start_time, "endTime": end_time})
    events = d.get("reportData", {}).get("report", {}).get("events", {}).get("data", []) or []
    deaths_by_fight = {f['id']: [] for f in fights}
    for ev in events:
        if ev.get("type") != "death": continue
        fid = ev.get("fight")
        if fid not in deaths_by_fight: continue
        tid = ev.get("targetID")
        name = actor_id_to_name.get(tid, "Unknown")
        kill_id = ev.get("killingAbilityGameID")
        ability_name = ability_map.get(kill_id, "Unknown")
        fight_obj = next((f for f in fights if f['id'] == fid), None)
        deaths_by_fight[fid].append({
            "timestamp": ev.get("timestamp", 0),
            "targetName": name, "targetID": tid, "phase": 1,
            "fightId": fid, "bossName": fight_obj.get('name', 'Unknown') if fight_obj else 'Unknown',
            "abilityName": ability_name
        })
    for fid in deaths_by_fight:
        deaths_by_fight[fid] = filter_mass_deaths(deaths_by_fight[fid])
    return deaths_by_fight

# === NEW: cheat-death in bulk (single Buffs scan per report) ============
CHEAT_ABILITY_NAMES = [
    "Cheat Death",          # Rogue
    "Purgatory",            # DK
    "Ardent Defender",      # Prot Paladin (death prevention)
    "Cauterize",            # Fire Mage
    "Guardian Spirit",      # Holy Priest (death-prevent)
    "Spirit of Redemption", # Holy Priest (trigger on death)
    "Reincarnation",        # Shaman self-res
]
# You asked to exclude Warlock Soulstone.

def _ability_ids_for(names, ability_map):
    names_lower = {n.lower() for n in (names or [])}
    idset = set()
    for aid, nm in (ability_map or {}).items():
        if nm and nm.lower() in names_lower:
            idset.add(int(aid))
    return sorted(idset)

def get_report_cheats_bulk(token, report_code, fights, friendlies, ability_map, names=CHEAT_ABILITY_NAMES):
    """Single Buffs query over the whole time window with a filter on cheat-death abilities."""
    if not fights: return {}
    ids = _ability_ids_for(names, ability_map)
    if not ids: return {f['id']: [] for f in fights}
    actor_id_to_name = {fr.get("id"): fr.get("name") for fr in friendlies if fr.get("id") and fr.get("name")}
    start_time = min(f['start_time'] for f in fights)
    end_time   = max(f['end_time'] for f in fights)
    # Filter to only the cheat-death ability ids + buff-type events
    filter_expr = '(type in ("applybuff","refreshbuff","removebuff","applybuffstack")) and (' + " or ".join([f"ability.id={aid}" for aid in ids]) + ")"
    q = """
    query($code: String!, $startTime: Float!, $endTime: Float!, $expr: String) {
      reportData { report(code: $code) {
        events(startTime: $startTime, endTime: $endTime, dataType: Buffs, limit: 10000, filterExpression: $expr) { data }
      }}}"""
    d = graphql_query(token, q, {"code": report_code, "startTime": start_time, "endTime": end_time, "expr": filter_expr})
    events = d.get("reportData", {}).get("report", {}).get("events", {}).get("data", []) or []
    cheats_by_fight = {f['id']: [] for f in fights}
    for ev in events:
        fid = ev.get("fight")
        if fid not in cheats_by_fight: continue
        ability_id = ev.get("abilityGameID") or (ev.get("ability") or {}).get("gameID")
        target_id = ev.get("targetID")
        if target_id is None: continue
        cheats_by_fight[fid].append({
            "timestamp": ev.get("timestamp", 0),
            "targetName": actor_id_to_name.get(target_id, "Unknown"),
            "targetID": target_id,
            "fightId": fid,
            "abilityName": ability_map.get(ability_id, "Unknown"),
            "eventType": ev.get("type", "applybuff")
        })
    return cheats_by_fight

# === Helpers you already have ===========================================
def analyze_fights(fights, fight_zone, difficulty):
    out = []
    for f in fights:
        if (f.get("boss") or 0) <= 0: continue
        if f.get("zoneID") != int(fight_zone): continue
        if f.get("difficulty") != int(difficulty): continue
        out.append(f)
    return out

def filter_mass_deaths(deaths):
    if len(deaths) < MASS_DEATH_THRESHOLD: return deaths
    sd = sorted(deaths, key=lambda d: d['timestamp'])
    for i in range(len(sd) - MASS_DEATH_THRESHOLD + 1):
        win_start = sd[i]['timestamp']; win_end = win_start + MASS_DEATH_WINDOW
        cnt = sum(1 for j in range(i, len(sd)) if sd[j]['timestamp'] <= win_end)
        if cnt >= MASS_DEATH_THRESHOLD: return sd[:i]
    return sd

def interval_overlap(a_start, a_end, b_start, b_end):
    inter = max(0, min(a_end, b_end) - max(a_start, b_start))
    if inter == 0: return 0, 0.0
    union = (a_end - a_start) + (b_end - b_start) - inter
    return inter, (inter/union if union > 0 else 0.0)

def is_duplicate_pull(seen_by_boss, boss_id, abs_start, abs_end, is_kill=None):
    MIN_ABS_OVERLAP_MS = 15000
    MIN_IOU_FOR_DUP = 0.50
    lst = seen_by_boss.setdefault(boss_id, [])
    for s_start, s_end, s_kill in lst:
        inter, iou = interval_overlap(abs_start, abs_end, s_start, s_end)
        if inter >= MIN_ABS_OVERLAP_MS or iou >= MIN_IOU_FOR_DUP:
            return True
    lst.append((abs_start, abs_end, is_kill))
    return False

# === Main endpoint (kept; add includeCheatEvents support) ===============
@app.route('/api/analyze', methods=['POST', 'OPTIONS'])
def analyze():
    if request.method == 'OPTIONS':
        r = jsonify({'status': 'ok'})
        r.headers.add('Access-Control-Allow-Origin', '*')
        r.headers.add('Access-Control-Allow-Headers', 'Content-Type')
        r.headers.add('Access-Control-Allow-Methods', 'POST, OPTIONS')
        return r, 200

    try:
        config = request.json
    except Exception as e:
        resp = jsonify({"error": f"Invalid request: {str(e)}"})
        resp.headers.add('Access-Control-Allow-Origin', '*')
        return resp, 400

    def sse(obj): return f"data: {json.dumps(obj)}\n\n"

    def generate():
        try:
            client_id = config.get('clientId')
            client_secret = config.get('clientSecret')
            guild_name = config.get('guildName')
            server = config.get('server')
            region = config.get('region')
            report_zone = config.get('reportZone')
            fight_zone = config.get('fightZone')
            difficulty = config.get('difficulty')
            max_cutoff = int(config.get('maxCutoff', 5))
            cutoff_date = config.get('cutoffDate')
            author_filters = config.get('authorFilters', [])
            character_groups = config.get('characterGroups', {})
            include_cheats = bool(config.get('includeCheatEvents', False))
            cheat_names = config.get('cheatAbilityNames', CHEAT_ABILITY_NAMES)

            if not all([client_id, client_secret, guild_name, server, region]):
                yield sse({'error': 'Missing required fields'}); return

            yield sse({'stage': 'auth', 'message': 'Authenticating with WarcraftLogs...'})
            token = get_access_token(client_id, client_secret)

            yield sse({'stage': 'reports', 'message': 'Fetching guild reports...'})
            reports = get_guild_reports(token, guild_name, server, region, report_zone, cutoff_date)
            yield sse({'stage': 'reports', 'message': f'Found {len(reports)} reports'})

            if author_filters:
                reports = [r for r in reports if r.get('owner') in author_filters]
                yield sse({'stage': 'reports', 'message': f'After author filter: {len(reports)} reports'})

            if not reports:
                yield sse({'error': 'No reports found matching criteria'}); return

            yield sse({'stage': 'fights', 'message': 'Collecting fights from reports...'})

            all_fights_raw = []
            report_friendlies = {}
            report_ability_maps = {}
            for i, rep in enumerate(reports, 1):
                rid = rep["id"]
                yield sse({'stage': 'fights', 'message': f'Processing report {i}/{len(reports)}: {rid}'})
                meta = get_fights(token, rid)
                fights = meta["fights"]; report_abs_start = meta["report_start"]; friendlies = meta["friendlies"]
                ability_map = meta["ability_map"]
                report_friendlies[rid] = friendlies
                report_ability_maps[rid] = ability_map
                if not fights: continue
                matching = analyze_fights(fights, fight_zone, difficulty)
                for f in matching:
                    fid = f['id']; boss_id = f.get('boss', 0); is_kill = bool(f.get('kill'))
                    rel_start, rel_end = f['start_time'], f['end_time']
                    abs_start, abs_end = report_abs_start + rel_start, report_abs_start + rel_end
                    all_fights_raw.append({
                        'reportId': rid,'fight': f,'boss_name': f.get('name','Unknown'),
                        'boss_id': boss_id,'is_kill': is_kill,'abs_start': abs_start,'abs_end': abs_end,
                        'report_abs_start': report_abs_start
                    })

            all_fights_raw.sort(key=lambda x: x['abs_start'])
            yield sse({'stage': 'fights', 'message': f'Collected {len(all_fights_raw)} total fights'})

            yield sse({'stage': 'dedup', 'message': 'Removing duplicate pulls...'})
            seen = {}; dedup = []
            for fd in all_fights_raw:
                if not is_duplicate_pull(seen, fd['boss_id'], fd['abs_start'], fd['abs_end'], fd['is_kill']):
                    dedup.append(fd)
            yield sse({'stage': 'dedup', 'message': f'After deduplication: {len(dedup)} unique fights'})

            # Group by report
            fights_by_report = defaultdict(list)
            for fd in dedup:
                fights_by_report[fd['reportId']].append(fd)

            # Bulk deaths for each report (as before)
            yield sse({'stage': 'deaths', 'message': f'Fetching deaths for {len(fights_by_report)} reports...' })
            report_deaths_cache = {}
            for idx, (rid, rfs) in enumerate(fights_by_report.items(), 1):
                yield sse({'stage': 'deaths', 'message': f'Fetching deaths from report {idx}/{len(fights_by_report)}'})
                sample = rfs[0]; friendlies = report_friendlies[rid]; ability_map = report_ability_maps[rid]
                fights_list = [x['fight'] for x in rfs]
                report_deaths_cache[rid] = get_report_deaths_bulk(token, rid, fights_list, friendlies, ability_map)

            # Optional: bulk cheat-death scan per report (single Buffs scan)
            report_cheats_cache = {}
            if include_cheats:
                yield sse({'stage': 'cheats', 'message': f'Fetching cheat-death events for {len(fights_by_report)} reports...' })
                for idx, (rid, rfs) in enumerate(fights_by_report.items(), 1):
                    yield sse({'stage': 'cheats', 'message': f'Fetching cheats from report {idx}/{len(fights_by_report)}'})
                    friendlies = report_friendlies[rid]; ability_map = report_ability_maps[rid]
                    fights_list = [x['fight'] for x in rfs]
                    report_cheats_cache[rid] = get_report_cheats_bulk(token, rid, fights_list, friendlies, ability_map, names=cheat_names)

            # Build final structures (unchanged logic for deaths)
            yield sse({'stage': 'processing', 'message': f'Processing {len(dedup)} fights...' })
            counted_death_events = defaultdict(list)
            pull_participation = defaultdict(set)
            boss_participation = defaultdict(lambda: defaultdict(set))
            character_breakdown = defaultdict(lambda: defaultdict(list))
            cheat_events_by_player = defaultdict(list) if include_cheats else {}

            pull_counter_by_boss = defaultdict(int)

            def players_in_fight(fight, friendlies):
                out = set()
                ids = set(fight.get('friendlyPlayers', []) or [])
                if ids:
                    for fr in friendlies:
                        if fr.get('id') in ids and fr.get('name'):
                            out.add(fr.get('name'))
                else:
                    for fr in friendlies:
                        if fr.get('name'):
                            out.add(fr.get('name'))
                return out

            for idx, fd in enumerate(dedup, 1):
                rid = fd['reportId']; fight = fd['fight']; fid = fight['id']
                boss_name = fd['boss_name']; boss_id = fd['boss_id']; is_kill = fd['is_kill']
                report_abs_start = fd['report_abs_start']
                friendlies = report_friendlies[rid]

                pull_counter_by_boss[boss_id] += 1
                seq_no = pull_counter_by_boss[boss_id]

                # participation
                for p in players_in_fight(fight, friendlies):
                    main = get_main_character(p, character_groups)
                    key = f"{rid}_{fid}"
                    pull_participation[main].add(key)
                    boss_participation[boss_name][main].add(key)

                # deaths (first X)
                deaths = report_deaths_cache.get(rid, {}).get(fid, [])
                for rank, ev in enumerate(sorted(deaths, key=lambda e: e["timestamp"])[:max_cutoff], start=1):
                    original = ev["targetName"]; main = get_main_character(original, character_groups)
                    counted_death_events[main].append({
                        "player": main,"originalCharacter": original,"boss": boss_name,"bossId": boss_id,
                        "phase": ev.get("phase", 1),"reportId": rid,"fightId": fid,"isKill": is_kill,
                        "pullNo": seq_no,"rankWithinPull": rank,"absTs": report_abs_start + ev["timestamp"],
                        "abilityName": ev.get("abilityName", "Unknown")
                    })
                    character_breakdown[main][original].append(counted_death_events[main][-1])

                # cheat events (list all, ordered), kept separate
                if include_cheats:
                    cheats = report_cheats_cache.get(rid, {}).get(fid, [])
                    for cev in sorted(cheats, key=lambda e: e.get("timestamp", 0)):
                        original = cev["targetName"]; main = get_main_character(original, character_groups)
                        cheat_events_by_player[main].append({
                            "player": main,"originalCharacter": original,"boss": boss_name,"bossId": boss_id,
                            "reportId": rid,"fightId": fid,"isKill": is_kill,"pullNo": seq_no,
                            "absTs": report_abs_start + cev.get("timestamp", 0),
                            "abilityName": cev.get("abilityName", "Unknown"),
                            "eventType": cev.get("eventType", "applybuff")
                        })

            # finalize (convert sets)
            pull_participation_json = {p: list(s) for p, s in pull_participation.items()}
            boss_participation_json = {b: {p: list(s2) for p, s2 in players.items()} for b, players in boss_participation.items()}
            character_breakdown_json = {m: {c: evs for c, evs in chars.items()} for m, chars in character_breakdown.items()}

            response = {
                "meta": {
                    "maxCutoff": max_cutoff,"authorFilters": author_filters,"dateCutoff": cutoff_date,
                    "zone": fight_zone,"difficulty": difficulty,"generatedAt": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "characterGroups": character_groups,"reportCount": len(reports),
                    "includeCheatEvents": include_cheats, "cheatAbilityNames": cheat_names
                },
                "events": counted_death_events,
                "pullParticipation": pull_participation_json,
                "bossParticipation": boss_participation_json,
                "characterBreakdown": character_breakdown_json,
                "cheatEvents": (cheat_events_by_player if include_cheats else {})
            }
            yield sse({'result': response})

        except Exception as e:
            yield sse({'error': str(e)})

    return Response(generate(), mimetype='text/event-stream',
                    headers={'Access-Control-Allow-Origin': '*','Cache-Control': 'no-cache','X-Accel-Buffering': 'no'})

@app.route('/api/health', methods=['GET'])
def health():
    return jsonify({"status": "ok", "message": "WarcraftLogs API is running"})

@app.route('/', methods=['GET'])
def root():
    return jsonify({"service": "WarcraftLogs Death Tracker API","version": "2.3+cheats","status": "running"})
