#!/usr/bin/env python3
"""
app.py - Flask API routes for Floor Pov Death Tracker
Imports from: warcraftlogs, analysis, features, supabase_client
VERSION: 3.1 COMPLETE - All endpoints + delete account
"""

from flask import Flask, request, jsonify, Response
from flask_cors import CORS
from collections import defaultdict
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import uuid
import brotli
import base64
import os
from dotenv import load_dotenv
from supabase import create_client, Client

# Load environment variables
load_dotenv()

# Import from modules
from warcraftlogs import (
    get_access_token, get_guild_reports, get_guild_roster,
    get_fights, get_abilities_map, normalize_character_name
)
from analysis import (
    get_report_deaths_bulk, get_main_character, get_raid_participants,
    analyze_fights, filter_mass_deaths, is_duplicate_pull,
    interval_overlap, WOW_CLASS_COLORS, MASS_DEATH_THRESHOLD,
    find_mass_death_start
)
from features import (
    CHEAT_DEATH_ABILITY_IDS, ALL_DEFENSIVE_ABILITY_IDS,
    get_all_healing_for_report_paginated, get_all_defensive_buffs_paginated,
    calculate_defensive_data_from_bulk
)
import supabase_client

# =============================================================================
# SUPABASE INITIALIZATION
# =============================================================================

SUPABASE_URL = os.environ.get('SUPABASE_URL')
SUPABASE_KEY = os.environ.get('SUPABASE_KEY')
SUPABASE_SERVICE_ROLE_KEY = os.environ.get('SUPABASE_SERVICE_ROLE_KEY')

# Regular client (anon key)
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY) if SUPABASE_URL and SUPABASE_KEY else None

# Admin client (service role key - bypasses RLS)
supabase_admin: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY) if SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY else None

print(f"[Startup] Supabase configured: {supabase is not None}")
print(f"[Startup] Supabase Admin configured: {supabase_admin is not None}")

# =============================================================================
# FLASK SETUP
# =============================================================================

app = Flask(__name__)
CORS(app, 
     resources={r"/api/*": {"origins": "*"}},
     supports_credentials=True,
     allow_headers=["Content-Type", "Authorization"],
     methods=["GET", "POST", "DELETE", "OPTIONS", "PUT"])


# =============================================================================
# MAIN ANALYSIS ENDPOINT (COMPLETE FROM GITHUB)
# =============================================================================

@app.route('/api/analyze', methods=['POST', 'OPTIONS'])
def analyze():
    """Main API endpoint for analyzing WarcraftLogs data using V2 API with SSE progress"""
    
    # Handle preflight CORS
    if request.method == 'OPTIONS':
        response = jsonify({'status': 'ok'})
        response.headers.add('Access-Control-Allow-Origin', '*')
        response.headers.add('Access-Control-Allow-Headers', 'Content-Type')
        response.headers.add('Access-Control-Allow-Methods', 'POST, OPTIONS')
        return response, 200
    
    # Extract config BEFORE the generator to avoid request context issues
    try:
        config = request.json
    except Exception as e:
        resp = jsonify({"error": f"Invalid request: {str(e)}"})
        resp.headers.add('Access-Control-Allow-Origin', '*')
        return resp, 400
    
    def generate():
        try:
            print("\n" + "="*70)
            print("FLOOR POV BACKEND - VERSION 3.1 (COMPLETE)")
            print("="*70 + "\n")
            
            # Extract configuration
            client_id = config.get('clientId')
            client_secret = config.get('clientSecret')
            guild_name = config.get('guildName')
            server = config.get('server')
            region = config.get('region')
            report_zone = config.get('reportZone')
            fight_zone = config.get('fightZone')
            difficulty = config.get('difficulty')
            max_cutoff = int(config.get('maxCutoff', 5))
            start_date = config.get('startDate')
            if start_date == "" or start_date is None:
                start_date = None
            end_date = config.get('endDate')
            if end_date == "" or end_date is None:
                end_date = None
            author_filters = config.get('authorFilters', [])
            character_groups = config.get('characterGroups', {})
            enable_cheat_death = config.get('enableCheatDeath', False)
            enable_defensive_tracking = config.get('enableDefensiveTracking', False)
            
            # Validate required fields
            if not all([client_id, client_secret, guild_name, server, region]):
                yield f"data: {json.dumps({'error': 'Missing required fields'})}\n\n"
                return
            
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
            
            # Get guild reports
            yield f"data: {json.dumps({'stage': 'reports', 'message': 'Fetching guild reports...'})}\n\n"
            reports = get_guild_reports(token, guild_name, server, region, report_zone, start_date, end_date)
            yield f"data: {json.dumps({'stage': 'reports', 'message': f'Found {len(reports)} reports'})}\n\n"
            
            # Filter by author
            if author_filters:
                reports = [r for r in reports if r.get('owner') in author_filters]
                yield f"data: {json.dumps({'stage': 'reports', 'message': f'After author filter: {len(reports)} reports'})}\n\n"
            
            if not reports:
                yield f"data: {json.dumps({'error': 'No reports found matching criteria'})}\n\n"
                return
            
            # Collect all fights
            yield f"data: {json.dumps({'stage': 'fights', 'message': 'Collecting fights from reports...'})}\n\n"
            all_fights_raw = []
            report_ability_maps = {}
            
            for i, rep in enumerate(reports, 1):
                rid = rep["id"]
                yield f"data: {json.dumps({'stage': 'fights', 'message': f'Processing report {i}/{len(reports)}: {rid}'})}\n\n"
                
                if rid not in report_ability_maps:
                    report_ability_maps[rid] = get_abilities_map(token, rid)
                
                fights_data = get_fights(token, rid)
                fights = fights_data.get("fights", [])
                report_abs_start = fights_data.get("report_start", rep["start"])
                friendlies = fights_data.get("friendlies", [])
                player_details = fights_data.get("player_details", {})
                
                # Check if report has enough guild members (15+)
                if guild_roster:
                    friendly_names = {f.get("name", "").lower() for f in friendlies if f.get("name")}
                    guild_members_in_report = len(friendly_names & guild_roster)
                    
                    if guild_members_in_report < 15:
                        msg = f'Report {rid}: Only {guild_members_in_report} guild members - SKIPPED'
                        yield f"data: {json.dumps({'stage': 'fights', 'message': msg})}\n\n"
                        continue
                    else:
                        msg = f'Report {rid}: {guild_members_in_report} guild members - processing'
                        yield f"data: {json.dumps({'stage': 'fights', 'message': msg})}\n\n"
                
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
                        'reportId': rid,
                        'fight': fight,
                        'boss_name': boss_name,
                        'boss_id': boss_id,
                        'is_kill': is_kill,
                        'abs_start': abs_start,
                        'abs_end': abs_end,
                        'report_abs_start': report_abs_start,
                        'friendlies': friendlies,
                        'ability_map': report_ability_maps[rid],
                        'player_details': player_details
                    })
            
            all_fights_raw.sort(key=lambda x: x['abs_start'])
            yield f"data: {json.dumps({'stage': 'fights', 'message': f'Collected {len(all_fights_raw)} total fights'})}\n\n"
            
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
            character_breakdown = defaultdict(lambda: defaultdict(list))
            pull_counter_by_boss = defaultdict(int)
            
            # Group fights by report
            fights_by_report = defaultdict(list)
            for fight_data in all_fights_deduped:
                fights_by_report[fight_data['reportId']].append(fight_data)
            
            # Fetch deaths in parallel
            yield f"data: {json.dumps({'stage': 'deaths', 'message': f'Fetching deaths for {len(fights_by_report)} reports...'})}\n\n"
            report_deaths_cache = {}
            
            def fetch_report_deaths(rid, report_fights):
                """Fetch deaths AND bulk defensive/healing data for a single report"""
                try:
                    sample_fight_data = report_fights[0]
                    friendlies = sample_fight_data['friendlies']
                    ability_map = sample_fight_data['ability_map']
                    fights_list = [fd['fight'] for fd in report_fights]
                    
                    start_time = min(f['start_time'] for f in fights_list)
                    end_time = max(f['end_time'] for f in fights_list)
                    
                    deaths = get_report_deaths_bulk(token, rid, fights_list, friendlies, ability_map, enable_cheat_death, False)
                    
                    healing_data = []
                    defensive_buffs_data = []
                    
                    if enable_defensive_tracking:
                        defensive_buffs_data = get_all_defensive_buffs_paginated(token, rid, start_time, end_time)
                        healing_data = get_all_healing_for_report_paginated(token, rid, start_time, end_time)
                    
                    return rid, deaths, healing_data, defensive_buffs_data, None
                except Exception as e:
                    print(f"[ERROR] Error fetching data for report {rid}: {str(e)}")
                    import traceback
                    traceback.print_exc()
                    fights_list = [fd['fight'] for fd in report_fights]
                    return rid, {f['id']: [] for f in fights_list}, [], [], str(e)
            
            total_reports = len(fights_by_report)
            completed = 0
            
            report_healing_cache = {}
            report_defensive_cache = {}
            
            with ThreadPoolExecutor(max_workers=8) as executor:
                future_to_rid = {
                    executor.submit(fetch_report_deaths, rid, report_fights): rid
                    for rid, report_fights in fights_by_report.items()
                }
                
                for future in as_completed(future_to_rid):
                    rid, deaths, healing_data, defensive_data, error = future.result()
                    report_deaths_cache[rid] = deaths
                    report_healing_cache[rid] = healing_data
                    report_defensive_cache[rid] = defensive_data
                    completed += 1
                    
                    if completed % 5 == 0 or completed == total_reports:
                        yield f"data: {json.dumps({'stage': 'deaths', 'message': f'Fetching deaths from report {completed}/{total_reports}'})}\n\n"
            
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
                    main_char = get_main_character(p, character_groups)
                    pull_key = f"{rid}_{fid}"
                    pull_participation[main_char].add(pull_key)
                    boss_participation[boss_name][main_char].add(pull_key)
                
                deaths_for_fight = report_deaths_cache.get(rid, {}).get(fid, [])
                deaths_sorted_all = sorted(deaths_for_fight, key=lambda d: d["timestamp"])
                
                for ev in deaths_sorted_all:
                    target_name = normalize_character_name(ev.get("targetName", "Unknown"))
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
                    
                    if enable_defensive_tracking and target_id:
                        healing_data = report_healing_cache.get(rid, [])
                        defensive_data = report_defensive_cache.get(rid, [])
                        
                        if healing_data or defensive_data:
                            death_event['defensives'] = calculate_defensive_data_from_bulk(
                                ev["timestamp"],
                                target_id,
                                defensive_data,
                                healing_data
                            )
                    
                    counted_death_events[main_char].append(death_event)
                    character_breakdown[main_char][original_char].append(death_event)
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
            character_breakdown_json = {
                main: {char: evs for char, evs in chars.items()}
                for main, chars in character_breakdown.items()
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
                },
                "events": counted_death_events,
                "pullParticipation": pull_participation_json,
                "bossParticipation": boss_participation_json,
                "characterBreakdown": character_breakdown_json,
                "pullCutoffTimestamps": pullCutoffTimestamps,
            }
            
            yield f"data: {json.dumps({'result': response})}\n\n"
        
        except Exception as e:
            print(f"Error in analyze: {str(e)}")
            import traceback
            traceback.print_exc()
            yield f"data: {json.dumps({'error': str(e)})}\n\n"
    
    return Response(generate(), mimetype='text/event-stream', headers={
        'Access-Control-Allow-Origin': '*',
        'Cache-Control': 'no-cache',
        'X-Accel-Buffering': 'no'
    })


# =============================================================================
# SHARING ENDPOINTS
# =============================================================================

@app.route('/api/share', methods=['POST'])
def share_results():
    """Create a shareable link for analysis results."""
    try:
        data = request.json
        share_id = str(uuid.uuid4())[:8]
        json_str = json.dumps(data)
        compressed = brotli.compress(json_str.encode('utf-8'))
        encoded = base64.b64encode(compressed).decode('utf-8')
        supabase_client.store_shared_result(share_id, encoded)
        return jsonify({"shareId": share_id})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/shared/<share_id>', methods=['GET'])
def get_shared_results(share_id):
    """Get shared analysis results."""
    try:
        encoded = supabase_client.get_shared_result(share_id)
        if not encoded:
            return jsonify({"error": "Share link not found or expired"}), 404
        compressed = base64.b64decode(encoded)
        json_str = brotli.decompress(compressed).decode('utf-8')
        data = json.loads(json_str)
        return jsonify(data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# =============================================================================
# ANALYSIS STORAGE ENDPOINTS
# =============================================================================

@app.route('/api/save-analysis', methods=['POST'])
def save_analysis():
    if not supabase_client.is_configured():
        return jsonify({"error": "Database not configured"}), 500
    try:
        data = request.json
        result = supabase_client.save_analysis(
            user_id=data.get('userId'),
            analysis_name=data.get('analysisName'),
            guild_name=data.get('guildName'),
            analysis_data=data.get('analysisData'),
            retention_days=data.get('retentionDays', 30)
        )
        if "error" in result:
            return jsonify(result), 500
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/load-analysis/<analysis_id>', methods=['GET'])
def load_analysis(analysis_id):
    result = supabase_client.load_analysis(analysis_id)
    if "error" in result:
        return jsonify(result), 404 if "not found" in result["error"].lower() else 500
    return jsonify(result)


@app.route('/api/user-analyses/<user_id>', methods=['GET'])
def get_user_analyses(user_id):
    result = supabase_client.get_user_analyses(user_id)
    if "error" in result:
        return jsonify(result), 500
    return jsonify(result)


@app.route('/api/delete-analysis/<analysis_id>', methods=['DELETE'])
def delete_analysis(analysis_id):
    result = supabase_client.delete_analysis(analysis_id)
    if "error" in result:
        return jsonify(result), 500
    return jsonify(result)


@app.route('/api/delete-all-analyses/<user_id>', methods=['DELETE'])
def delete_all_analyses(user_id):
    result = supabase_client.delete_all_analyses(user_id)
    if "error" in result:
        return jsonify(result), 500
    return jsonify(result)


# =============================================================================
# USER ACCOUNT ENDPOINTS
# =============================================================================

@app.route('/api/delete-user-account/<user_id>', methods=['DELETE', 'OPTIONS'])
def delete_user_account(user_id):
    """Delete user account and all associated data"""
    
    # Handle preflight OPTIONS request
    if request.method == 'OPTIONS':
        response = jsonify({'status': 'ok'})
        response.headers.add('Access-Control-Allow-Origin', '*')
        response.headers.add('Access-Control-Allow-Methods', 'DELETE, OPTIONS')
        response.headers.add('Access-Control-Allow-Headers', 'Content-Type, Authorization')
        return response, 204
    
    if not supabase_admin:
        return jsonify({'error': 'Admin database client not configured'}), 500
    
    try:
        print(f"[Delete Account] Starting deletion for user_id: {user_id}")
        
        try:
            saved_result = supabase_admin.table('saved_analyses').delete().eq('user_id', user_id).execute()
            print(f"[Delete Account] Deleted {len(saved_result.data) if saved_result.data else 0} saved analyses")
        except Exception as e:
            print(f"[Delete Account] Error deleting saved analyses: {str(e)}")
        
        try:
            shared_result = supabase_admin.table('shared_analyses').delete().eq('user_id', user_id).execute()
            print(f"[Delete Account] Deleted {len(shared_result.data) if shared_result.data else 0} shared analyses")
        except Exception as e:
            print(f"[Delete Account] Note: Could not delete shared analyses: {str(e)}")
        
        try:
            creds_result = supabase_admin.table('api_credentials').delete().eq('user_id', user_id).execute()
            print(f"[Delete Account] Deleted {len(creds_result.data) if creds_result.data else 0} API credentials")
        except Exception as e:
            print(f"[Delete Account] Error deleting API credentials: {str(e)}")
        
        try:
            supabase_admin.auth.admin.delete_user(user_id)
            print(f"[Delete Account] Deleted auth user account")
        except Exception as e:
            print(f"[Delete Account] Error deleting auth user: {str(e)}")
        
        print(f"[Delete Account] Successfully completed deletion")
        
        return jsonify({'success': True, 'message': 'User data deleted successfully'}), 200
        
    except Exception as e:
        print(f"[Delete Account] Fatal error: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


# =============================================================================
# HEALTH & STATUS
# =============================================================================

@app.route('/api/health', methods=['GET'])
def health():
    return jsonify({"status": "healthy", "supabase": supabase_client.is_configured()})


@app.route('/', methods=['GET'])
def root():
    return jsonify({"service": "Floor Pov API", "version": "3.1.0-complete", "status": "running"})


# =============================================================================
# MAIN
# =============================================================================

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    print(f"Starting Floor Pov API v3.1.0 (complete) on port {port}...")
    app.run(host='0.0.0.0', port=port, debug=False)