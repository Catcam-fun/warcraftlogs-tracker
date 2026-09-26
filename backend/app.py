#!/usr/bin/env python3
"""
app.py - Flask API routes for Floor Pov Death Tracker
Imports from: warcraftlogs, analysis, features, supabase_client, auth
"""

from flask import Flask, request, jsonify, Response, g
from flask_cors import CORS
from collections import defaultdict
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import os
import re
import secrets
import time
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Import from modules
from warcraftlogs import (
    get_access_token, get_guild_reports, get_guild_roster,
    get_fights, normalize_character_name
)
from analysis import (
    get_report_deaths_bulk, get_main_character,
    analyze_fights, is_duplicate_pull,
    find_mass_death_start, resolve_report_window
)
import defensives
from auth import require_user, verify_token, forget_token, _bearer_token
from cache import (report_meta_cache, report_deaths_cache as deaths_lru,
                   report_defensive_cache as defensive_lru, report_recap_cache as recap_lru)
from ratelimit import RateLimiter, limit
import supabase_client

# A report whose last event is older than this is treated as finished and
# its fights/deaths are cached; anything newer may still be live-logging.
REPORT_CACHE_MIN_AGE_MS = 2 * 60 * 60 * 1000

# Parallel WCL requests per analysis. WCL's own rate limit is per API key,
# so this stays modest.
REPORT_FETCH_WORKERS = 6

share_limiter = RateLimiter(max_calls=20, per_seconds=3600)
analyze_limiter = RateLimiter(max_calls=60, per_seconds=3600)
save_limiter = RateLimiter(max_calls=30, per_seconds=3600)

# =============================================================================
# FLASK SETUP
# =============================================================================

app = Flask(__name__)
# Bodies are compressed analyses; anything larger than this is abuse.
app.config['MAX_CONTENT_LENGTH'] = 25 * 1024 * 1024

# Comma-separated list of allowed site origins, e.g.
# "https://floorpov.com,https://www.floorpov.com". Defaults to any origin
# (requests are authenticated with bearer tokens, not cookies).
_origins = [o.strip() for o in os.environ.get('ALLOWED_ORIGINS', '*').split(',') if o.strip()]
CORS(app,
     resources={r"/api/*": {"origins": _origins}},
     allow_headers=["Content-Type", "Authorization"],
     methods=["GET", "POST", "DELETE", "OPTIONS"])


# =============================================================================
# MAIN ANALYSIS ENDPOINT
# =============================================================================

@app.route('/api/analyze', methods=['POST'])
@limit(analyze_limiter, "Too many analyses from this network in the last hour. Please wait a bit.")
def analyze():
    """Main API endpoint for analyzing WarcraftLogs data using V2 API with SSE progress"""

    # Extract config BEFORE the generator to avoid request context issues
    config = request.get_json(silent=True)
    if not isinstance(config, dict):
        return jsonify({"error": "Invalid request"}), 400
    # Cheat-death detection is a signed-in feature; the checkbox in the UI
    # isn't enough, since a shared config or a direct call can set the flag.
    signed_in = bool(verify_token(_bearer_token()))

    def generate():
        try:
            # Extract configuration
            client_id = config.get('clientId')
            client_secret = config.get('clientSecret')
            guild_name = config.get('guildName')
            server = config.get('server')
            region = config.get('region')
            fight_zone = config.get('fightZone')
            selected_raid = config.get('selectedRaid')
            difficulty = config.get('difficulty')
            # Deaths per pull that count.
            max_cutoff = min(max(int(config.get('maxCutoff', 5) or 5), 1), 10)
            start_date = config.get('startDate')
            if start_date == "" or start_date is None:
                start_date = None
            end_date = config.get('endDate')
            if end_date == "" or end_date is None:
                end_date = None
            author_filters = config.get('authorFilters', [])
            character_groups = config.get('characterGroups', {})
            enable_cheat_death = bool(config.get('enableCheatDeath', False)) and signed_in
            
            # Validate required fields
            if not all([client_id, client_secret, guild_name, server, region]):
                yield f"data: {json.dumps({'error': 'Missing required fields'})}\n\n"
                return
            
            if config.get('enableCheatDeath') and not signed_in:
                yield f"data: {json.dumps({'stage': 'auth', 'message': 'Cheat-death detection needs a signed-in account; skipping it'})}\n\n"

            # Get OAuth2 token
            yield f"data: {json.dumps({'stage': 'auth', 'message': 'Authenticating with WarcraftLogs...'})}\n\n"
            try:
                token = get_access_token(client_id, client_secret)
            except Exception as e:
                yield f"data: {json.dumps({'error': f'Authentication failed: {str(e)}'})}\n\n"
                return
            
            # Get guild roster for filtering
            guild_roster = set()
            try:
                yield f"data: {json.dumps({'stage': 'roster', 'message': 'Fetching guild roster...'})}\n\n"
                guild_roster = get_guild_roster(token, guild_name, server, region)
                if guild_roster:
                    yield f"data: {json.dumps({'stage': 'roster', 'message': f'Found {len(guild_roster)} guild members'})}\n\n"
                else:
                    yield f"data: {json.dumps({'stage': 'roster', 'message': 'Guild roster unavailable - processing all reports'})}\n\n"
            except Exception as e:
                print(f"Guild roster fetch error: {str(e)}")
                yield f"data: {json.dumps({'stage': 'roster', 'message': 'Could not fetch guild roster - processing all reports'})}\n\n"

            # Only count players who are on the guild roster. If the roster
            # couldn't be fetched, fall back to counting everyone.
            def is_guild_member(nm):
                if not guild_roster:
                    return True
                return normalize_character_name(nm or "").lower() in guild_roster

            # Get guild reports. The tier's hard date window scopes the fetch
            # (user dates may narrow it but never widen past the tier); we no
            # longer filter by zoneID, which dropped mixed raid+dungeon reports.
            win_start, win_end = resolve_report_window(selected_raid, start_date, end_date)
            yield f"data: {json.dumps({'stage': 'reports', 'message': 'Fetching guild reports...'})}\n\n"
            reports = get_guild_reports(token, guild_name, server, region, win_start, win_end)
            yield f"data: {json.dumps({'stage': 'reports', 'message': f'Found {len(reports)} reports'})}\n\n"
            
            # Filter by author
            if author_filters:
                reports = [r for r in reports if r.get('owner') in author_filters]
                yield f"data: {json.dumps({'stage': 'reports', 'message': f'After author filter: {len(reports)} reports'})}\n\n"
            
            if not reports:
                yield f"data: {json.dumps({'error': 'No reports found matching criteria'})}\n\n"
                return
            
            # Collect all fights. Reports are fetched in parallel (one
            # GraphQL call each); finished reports come from the cache.
            yield f"data: {json.dumps({'stage': 'fights', 'message': 'Collecting fights from reports...'})}\n\n"
            all_fights_raw = []
            finished_before = int(time.time() * 1000) - REPORT_CACHE_MIN_AGE_MS
            report_finished = {rep["id"]: bool(rep.get("end")) and rep["end"] < finished_before
                               for rep in reports}

            def fetch_report_meta(rep):
                rid = rep["id"]
                if report_finished[rid]:
                    cached = report_meta_cache.get(rid)
                    if cached is not None:
                        return rep, cached
                meta = get_fights(token, rid)
                if report_finished[rid] and meta.get("fights"):
                    report_meta_cache.set(rid, meta)
                return rep, meta

            with ThreadPoolExecutor(max_workers=REPORT_FETCH_WORKERS) as executor:
                futures = [executor.submit(fetch_report_meta, rep) for rep in reports]
                for done, future in enumerate(as_completed(futures), 1):
                    rep, fights_data = future.result()
                    rid = rep["id"]
                    yield f"data: {json.dumps({'stage': 'fights', 'message': f'Read report {done}/{len(reports)}'})}\n\n"

                    fights = fights_data.get("fights", [])
                    if not fights:
                        continue
                    report_abs_start = fights_data.get("report_start") or rep["start"]
                    friendlies = fights_data.get("friendlies", [])
                    player_details = fights_data.get("player_details", {})
                    ability_map = fights_data.get("abilities", {})

                    # Non-guild members in the raid are filtered out
                    # per-player below (only roster members count).
                    for fight in analyze_fights(fights, fight_zone, difficulty, selected_raid):
                        all_fights_raw.append({
                            'reportId': rid,
                            'fight': fight,
                            'boss_name': fight.get('name', 'Unknown'),
                            'boss_id': fight.get('boss', 0),
                            'is_kill': bool(fight.get('kill')),
                            'abs_start': report_abs_start + fight['start_time'],
                            'abs_end': report_abs_start + fight['end_time'],
                            'report_abs_start': report_abs_start,
                            'friendlies': friendlies,
                            'ability_map': ability_map,
                            'ability_schools': fights_data.get("ability_schools", {}),
                            'player_details': player_details
                        })

            all_fights_raw.sort(key=lambda x: x['abs_start'])
            yield f"data: {json.dumps({'stage': 'fights', 'message': f'Collected {len(all_fights_raw)} total fights'})}\n\n"
            
            if not all_fights_raw:
                diff_names = {'3': 'Normal', '4': 'Heroic', '5': 'Mythic'}
                diff_label = diff_names.get(str(difficulty), f'difficulty {difficulty}')
                yield f"data: {json.dumps({'error': f'No {diff_label} fights found in the reports. Check that the selected difficulty is available for this raid.'})}\n\n"
                return
            
            # Deduplicate
            yield f"data: {json.dumps({'stage': 'dedup', 'message': 'Removing duplicate pulls...'})}\n\n"
            seen_pulls_by_boss = {}
            all_fights_deduped = []
            
            for fight_data in all_fights_raw:
                boss_id = fight_data['boss_id']
                abs_start = fight_data['abs_start']
                abs_end = fight_data['abs_end']
                is_kill = fight_data['is_kill']
                
                if is_duplicate_pull(seen_pulls_by_boss, boss_id, abs_start, abs_end, is_kill):
                    continue
                
                all_fights_deduped.append(fight_data)
            
            yield f"data: {json.dumps({'stage': 'dedup', 'message': f'After deduplication: {len(all_fights_deduped)} unique fights'})}\n\n"
            
            # Process deaths
            yield f"data: {json.dumps({'stage': 'deaths', 'message': 'Processing death events...'})}\n\n"
            counted_death_events = defaultdict(list)
            pull_participation = defaultdict(set)
            boss_participation = defaultdict(lambda: defaultdict(set))
            pull_counter_by_boss = defaultdict(int)
            
            # Group fights by report
            fights_by_report = defaultdict(list)
            for fight_data in all_fights_deduped:
                fights_by_report[fight_data['reportId']].append(fight_data)
            
            # Fetch deaths in parallel
            yield f"data: {json.dumps({'stage': 'deaths', 'message': f'Fetching deaths for {len(fights_by_report)} reports...'})}\n\n"
            report_deaths_cache = {}
            
            def fetch_report_deaths(rid, report_fights):
                """Fetch deaths and defensive data (casts, buffs, talents) for one report"""
                try:
                    sample_fight_data = report_fights[0]
                    friendlies = sample_fight_data['friendlies']
                    ability_map = sample_fight_data['ability_map']
                    fights_list = [fd['fight'] for fd in report_fights]
                    
                    cache_key = (rid, tuple(sorted(f['id'] for f in fights_list)), bool(enable_cheat_death))
                    deaths = deaths_lru.get(cache_key) if report_finished.get(rid) else None
                    if deaths is None:
                        deaths = get_report_deaths_bulk(token, rid, fights_list, friendlies, ability_map, enable_cheat_death)
                        if report_finished.get(rid):
                            deaths_lru.set(cache_key, deaths)
                    
                    # Defensive casts, auras and talents for the players who died.
                    dead = {d.get("targetID") for ds in deaths.values() for d in ds if d.get("targetID")}
                    def_key = (rid, tuple(sorted(f['id'] for f in fights_list)), tuple(sorted(dead)))
                    def_data = defensive_lru.get(def_key) if report_finished.get(rid) else None
                    if def_data is None:
                        try:
                            def_data = defensives.fetch_defensive_events(
                                token, rid, sorted(f['id'] for f in fights_list),
                                min(f['start_time'] for f in fights_list),
                                max(f['end_time'] for f in fights_list), dead)
                            if report_finished.get(rid):
                                defensive_lru.set(def_key, def_data)
                        except Exception as e:
                            # Deaths still count; this report just lacks defensive detail.
                            print(f"[WARN] Defensive data unavailable for report {rid}: {e}")
                            def_data = None

                    # Killing blows (one cheap request per report), for "would it have saved them".
                    fight_ids = sorted(f['id'] for f in fights_list)
                    kb_key = (rid, tuple(fight_ids))
                    recaps = recap_lru.get(kb_key) if report_finished.get(rid) else None
                    if recaps is None:
                        try:
                            recaps = defensives.fetch_killing_blows(token, rid, fight_ids)
                            if report_finished.get(rid):
                                recap_lru.set(kb_key, recaps)
                        except Exception as e:
                            print(f"[WARN] Killing blows unavailable for report {rid}: {e}")
                            recaps = None

                    return rid, deaths, def_data, recaps, None
                except Exception as e:
                    print(f"[ERROR] Error fetching data for report {rid}: {str(e)}")
                    fights_list = [fd['fight'] for fd in report_fights]
                    return rid, {f['id']: [] for f in fights_list}, None, None, str(e)
            
            total_reports = len(fights_by_report)
            completed = 0
            failed_reports = []
            
            report_defensive_data = {}
            report_recaps = {}
            
            with ThreadPoolExecutor(max_workers=8) as executor:
                future_to_rid = {
                    executor.submit(fetch_report_deaths, rid, report_fights): rid
                    for rid, report_fights in fights_by_report.items()
                }
                
                for future in as_completed(future_to_rid):
                    rid, deaths, def_data, recaps, error = future.result()
                    if error:
                        failed_reports.append(rid)
                    report_deaths_cache[rid] = deaths
                    report_defensive_data[rid] = def_data
                    report_recaps[rid] = recaps
                    completed += 1
                    
                    if completed % 5 == 0 or completed == total_reports:
                        yield f"data: {json.dumps({'stage': 'deaths', 'message': f'Fetching deaths from report {completed}/{total_reports}'})}\n\n"
            
            if failed_reports:
                yield f"data: {json.dumps({'stage': 'deaths', 'message': f'Warning: {len(failed_reports)} report(s) could not be read; results may be incomplete'})}\n\n"
            partial = [r for r in fights_by_report
                       if r not in failed_reports and (report_defensive_data.get(r) is None or report_recaps.get(r) is None)]
            if partial:
                msg = (f'Warning: defensive details missing for {len(partial)} report(s); '
                       'WarcraftLogs may be rate-limiting this API key. Try again in a while.')
                yield f"data: {json.dumps({'stage': 'deaths', 'message': msg})}\n\n"
            yield f"data: {json.dumps({'stage': 'processing', 'message': f'Processing {len(all_fights_deduped)} fights...'})}\n\n"
            
            total_deaths = 0
            pullCutoffTimestamps = {}
            
            for fight_idx, fight_data in enumerate(all_fights_deduped, 1):
                if fight_idx % 10 == 0:
                    yield f"data: {json.dumps({'stage': 'processing', 'message': f'Processing fight {fight_idx}/{len(all_fights_deduped)} - {total_deaths} deaths found'})}\n\n"
                
                rid = fight_data['reportId']
                fight = fight_data['fight']
                boss_name = fight_data['boss_name']
                boss_id = fight_data['boss_id']
                is_kill = fight_data['is_kill']
                report_abs_start = fight_data['report_abs_start']
                friendlies = fight_data['friendlies']
                player_details = fight_data.get("player_details", {})
                friendly_class = {f.get("id"): f.get("type") for f in friendlies}
                friendly_names_by_id = {f.get("id"): f.get("name") for f in friendlies}
                
                pull_counter_by_boss[boss_id] += 1
                seq_no = pull_counter_by_boss[boss_id]
                fid = fight['id']
                
                # FIXED: Only count players who were ACTUALLY in this fight
                fight_parts = set()
                friendly_player_ids = set(fight.get('friendlyPlayers', []))
                
                if friendly_player_ids:
                    # Use the specific player IDs from this fight
                    for friendly in friendlies:
                        if friendly.get('id') in friendly_player_ids:
                            name = friendly.get('name')
                            if name:
                                fight_parts.add(name)
                else:
                    # Fallback: if friendlyPlayers not available, use all friendlies
                    for friendly in friendlies:
                        name = friendly.get('name')
                        if name:
                            fight_parts.add(name)
                
                for p in fight_parts:
                    if not is_guild_member(p):
                        continue
                    main_char = get_main_character(p, character_groups)
                    pull_key = f"{rid}_{fid}"
                    pull_participation[main_char].add(pull_key)
                    boss_participation[boss_name][main_char].add(pull_key)
                
                deaths_for_fight = report_deaths_cache.get(rid, {}).get(fid, [])
                deaths_sorted_all = sorted(deaths_for_fight, key=lambda d: d["timestamp"])
                
                for ev in deaths_sorted_all:
                    target_name = normalize_character_name(ev.get("targetName", "Unknown"))
                    if not is_guild_member(target_name):
                        continue
                    original_char = target_name
                    main_char = get_main_character(target_name, character_groups)
                    target_id = ev.get("targetID")
                    
                    player_class = None
                    player_spec = None
                    if target_id and target_id in player_details:
                        player_class = player_details[target_id].get("class", None)
                        player_spec = player_details[target_id].get("spec", None)
                    
                    death_event = {
                        "player": main_char,
                        "originalCharacter": original_char,
                        "boss": boss_name,
                        "bossId": boss_id,
                        "phase": ev.get("phase", 1),
                        "reportId": rid,
                        "fightId": fid,
                        "isKill": is_kill,
                        "pullNo": seq_no,
                        "absTs": report_abs_start + ev["timestamp"],
                        "timestamp": ev["timestamp"] - fight['start_time'],
                        "abilityName": ev.get("abilityName", "Unknown"),
                        "isCheatDeath": ev.get("isCheatDeath", False),
                        "class": player_class,
                        "spec": player_spec
                    }
                    
                    def_data = report_defensive_data.get(rid)
                    if def_data and target_id and not death_event["isCheatDeath"]:
                        death_event['defensives'] = defensives.analyze_death(
                            player_id=target_id,
                            player_class=friendly_class.get(target_id),
                            spec=player_spec,
                            fight_id=fid,
                            fight_start=fight['start_time'],
                            death_ts=ev["timestamp"],
                            indexed=def_data,
                            ability_names=fight_data['ability_map'],
                            actor_names=friendly_names_by_id,
                            killing_blows=(report_recaps.get(rid) or {}).get(target_id, [])
                            if report_recaps.get(rid) is not None else None,
                            ability_schools=fight_data.get('ability_schools', {}),
                        )

                    counted_death_events[main_char].append(death_event)
                    total_deaths += 1
                
                pull_key = f"{rid}_{fid}"
                pullCutoffTimestamps[pull_key] = {}
                
                fight_start = fight['start_time']
                real_deaths_only = [
                    {**d, "timestamp": d["timestamp"] - fight_start}
                    for d in deaths_sorted_all 
                    if not d.get("isCheatDeath", False)
                ]
                
                for cutoff_val in range(1, len(real_deaths_only) + 1):
                    cutoff_idx = cutoff_val - 1
                    mass_death_start = find_mass_death_start(cutoff_idx, real_deaths_only)
                    
                    if mass_death_start is not None:
                        pullCutoffTimestamps[pull_key][cutoff_val] = mass_death_start
                    else:
                        pullCutoffTimestamps[pull_key][cutoff_val] = real_deaths_only[cutoff_idx]["timestamp"]
            
            yield f"data: {json.dumps({'stage': 'complete', 'message': f'Analysis complete! Tracked {total_deaths} deaths across {len(counted_death_events)} players'})}\n\n"
            
            pull_participation_json = {p: list(s) for p, s in pull_participation.items()}
            boss_participation_json = {
                b: {p: list(s2) for p, s2 in players.items()}
                for b, players in boss_participation.items()
            }
            
            response = {
                "meta": {
                    "guild_name": guild_name,
                    "maxCutoff": max_cutoff,
                    "authorFilters": author_filters,
                    "startDate": start_date,
                    "endDate": end_date,
                    "zone": fight_zone,
                    "difficulty": difficulty,
                    "generatedAt": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "characterGroups": character_groups,
                    "reportCount": len(reports),
                    "cheatDeathEnabled": enable_cheat_death,
                    "failedReports": failed_reports,
                },
                "events": counted_death_events,
                "pullParticipation": pull_participation_json,
                "bossParticipation": boss_participation_json,
                "pullCutoffTimestamps": pullCutoffTimestamps,
            }
            
            yield f"data: {json.dumps({'result': response})}\n\n"
        
        except Exception as e:
            print(f"Error in analyze: {str(e)}")
            import traceback
            traceback.print_exc()
            yield f"data: {json.dumps({'error': str(e)})}\n\n"
    
    return Response(generate(), mimetype='text/event-stream', headers={
        'Cache-Control': 'no-cache',
        'X-Accel-Buffering': 'no'
    })


# =============================================================================
# SHARING (72h links, stored compressed in Supabase)
# =============================================================================

SHARE_ID_RE = re.compile(r'^[A-Za-z0-9_-]{6,32}$')
SAVED_ID_RE = re.compile(r'^[0-9a-fA-F-]{36}$')


def _looks_like_analysis(data):
    return isinstance(data, dict) and isinstance(data.get('events'), dict)


@app.route('/api/share', methods=['POST'])
@limit(share_limiter, "Too many share links from this network in the last hour. Please wait a bit.")
def share_results():
    """Create a short share link. Credentials are stripped server-side."""
    body = request.get_json(silent=True) or {}
    data = body.get('data')
    if not _looks_like_analysis(data):
        return jsonify({"success": False, "error": "Nothing to share"}), 400

    user_id = verify_token(_bearer_token())  # optional: lets account deletion remove it
    share_id = secrets.token_urlsafe(9)
    result = supabase_client.store_share(share_id, data, body.get('config'), user_id)
    if "error" in result:
        return jsonify({"success": False, "error": result["error"]}), 413
    return jsonify({"success": True, "shareId": share_id, "expiresAt": result["expires_at"]})


@app.route('/api/shared/<share_id>', methods=['GET'])
def get_shared(share_id):
    if not SHARE_ID_RE.match(share_id or ''):
        return jsonify({"success": False, "error": "Share not found or expired"}), 404
    share = supabase_client.get_share(share_id)
    if not share:
        return jsonify({"success": False, "error": "Share not found or expired (links last 72 hours)"}), 404
    return jsonify({"success": True, "data": share["data"], "config": share["config"],
                    "timestamp": share["created_at"]})


# =============================================================================
# SAVED ANALYSES (signed-in users, max 5 each)
# =============================================================================

def _storage_response(result, ok_status=200):
    if "error" not in result:
        return jsonify(result), ok_status
    status = {"limit": 409, "too_large": 413, "not_found": 404}.get(result.get("code"), 500)
    return jsonify({"success": False, **result}), status


@app.route('/api/saved', methods=['GET'])
@require_user
def list_saved():
    return _storage_response(supabase_client.get_user_analyses(g.user_id))


@app.route('/api/saved', methods=['POST'])
@require_user
@limit(save_limiter, "Too many saves in the last hour. Please wait a bit.")
def create_saved():
    body = request.get_json(silent=True) or {}
    data = body.get('data')
    if not _looks_like_analysis(data):
        return jsonify({"success": False, "error": "Nothing to save"}), 400
    return _storage_response(supabase_client.save_analysis(
        user_id=g.user_id,
        analysis_name=body.get('name'),
        guild_name=(data.get('meta') or {}).get('guild_name'),
        analysis_data=data,
        config=body.get('config'),
        retention_days=body.get('retentionDays', 30),
    ), 201)


@app.route('/api/saved/<analysis_id>', methods=['GET'])
@require_user
def get_saved(analysis_id):
    if not SAVED_ID_RE.match(analysis_id or ''):
        return jsonify({"success": False, "error": "Report not found"}), 404
    return _storage_response(supabase_client.load_analysis(analysis_id, g.user_id))


@app.route('/api/saved/<analysis_id>', methods=['DELETE'])
@require_user
def delete_saved(analysis_id):
    if not SAVED_ID_RE.match(analysis_id or ''):
        return jsonify({"success": False, "error": "Report not found"}), 404
    return _storage_response(supabase_client.delete_analysis(analysis_id, g.user_id))


@app.route('/api/saved', methods=['DELETE'])
@require_user
def delete_all_saved():
    return _storage_response(supabase_client.delete_all_analyses(g.user_id))


# =============================================================================
# ACCOUNT
# =============================================================================

@app.route('/api/account', methods=['DELETE'])
@require_user
def delete_account():
    """Delete the signed-in user's data and auth account."""
    result = supabase_client.delete_user_account(g.user_id)
    if "error" not in result:
        forget_token(_bearer_token())
    return _storage_response(result)


# =============================================================================
# HEALTH & STATUS
# =============================================================================

@app.route('/api/health', methods=['GET'])
def health():
    return jsonify({"status": "healthy", "supabase": supabase_client.is_configured()})


@app.route('/', methods=['GET'])
def root():
    return jsonify({"service": "Floor Pov API", "status": "running"})


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    print(f"Starting Floor Pov API on port {port}...")
    app.run(host='0.0.0.0', port=port, debug=False, threaded=True)
