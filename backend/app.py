#!/usr/bin/env python3
"""
app.py - Flask API routes for Floor Pov Death Tracker
Imports from: warcraftlogs, analysis, features, supabase_client
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
# FLASK SETUP
# =============================================================================

app = Flask(__name__)
CORS(app, 
     resources={r"/api/*": {"origins": "*"}},
     supports_credentials=True,
     allow_headers=["Content-Type", "Authorization"],
     methods=["GET", "POST", "DELETE", "OPTIONS", "PUT"])


# =============================================================================
# MAIN ANALYSIS ENDPOINT
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
            print("FLOOR POV BACKEND - VERSION 3.0 (Bulk Fetch + Pagination)")
            print("If you see this message, the NEW code is running!")
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
            # Convert empty strings to None for optional dates
            start_date = config.get('startDate')
            if start_date == "" or start_date is None:
                start_date = None
            end_date = config.get('endDate')
            if end_date == "" or end_date is None:
                end_date = None
            author_filters = config.get('authorFilters', [])
            character_groups = config.get('characterGroups', {})
            enable_cheat_death = config.get('enableCheatDeath', False)  # Optional cheat death detection
            enable_defensive_tracking = config.get('enableDefensiveTracking', False)  # Optional defensive tracking (Druid only)
            
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
            
            # Fetch deaths in parallel - MASSIVE speedup!
            yield f"data: {json.dumps({'stage': 'deaths', 'message': f'Fetching deaths for {len(fights_by_report)} reports...'})}\n\n"
            report_deaths_cache = {}
            
            def fetch_report_deaths(rid, report_fights):
                """Fetch deaths AND bulk defensive/healing data for a single report - used in parallel execution"""
                try:
                    sample_fight_data = report_fights[0]
                    friendlies = sample_fight_data['friendlies']
                    ability_map = sample_fight_data['ability_map']
                    fights_list = [fd['fight'] for fd in report_fights]
                    
                    # Get time range for all fights in this report
                    start_time = min(f['start_time'] for f in fights_list)
                    end_time = max(f['end_time'] for f in fights_list)
                    
                    # Fetch deaths (no pagination needed - deaths are usually < 10k)
                    deaths = get_report_deaths_bulk(token, rid, fights_list, friendlies, ability_map, enable_cheat_death, False)  # Don't fetch defensives here
                    
                    # If defensive tracking enabled, fetch ALL healing and defensive buffs with pagination
                    healing_data = []
                    defensive_buffs_data = []
                    
                    print(f"[DEBUG] enable_defensive_tracking = {enable_defensive_tracking}")
                    
                    if enable_defensive_tracking:
                        print(f"[BULK] Fetching defensive/healing data for report {rid}...")
                        print(f"[BULK] Time range: {start_time} to {end_time}")
                        defensive_buffs_data = get_all_defensive_buffs_paginated(token, rid, start_time, end_time)
                        healing_data = get_all_healing_for_report_paginated(token, rid, start_time, end_time)
                        print(f"[BULK] Fetch complete - Healing: {len(healing_data)} events, Defensive buffs: {len(defensive_buffs_data)} events")
                    else:
                        print(f"[DEBUG] Skipping bulk fetch - defensive tracking disabled")
                    
                    print(f"[OK] Completed report {rid} - {len(healing_data)} healing events, {len(defensive_buffs_data)} defensive buffs")
                    return rid, deaths, healing_data, defensive_buffs_data, None
                except Exception as e:
                    print(f"[ERROR] Error fetching data for report {rid}: {str(e)}")
                    import traceback
                    traceback.print_exc()
                    # Return empty data for this report
                    fights_list = [fd['fight'] for fd in report_fights]
                    return rid, {f['id']: [] for f in fights_list}, [], [], str(e)
            
            # Process reports in parallel batches of 8
            # This stays well under Cloudflare rate limits (30 RPS) while providing massive speedup
            total_reports = len(fights_by_report)
            completed = 0
            
            # Storage for bulk defensive/healing data per report
            report_healing_cache = {}
            report_defensive_cache = {}
            
            with ThreadPoolExecutor(max_workers=8) as executor:
                # Submit all report fetching jobs
                future_to_rid = {
                    executor.submit(fetch_report_deaths, rid, report_fights): rid
                    for rid, report_fights in fights_by_report.items()
                }
                
                # Process results as they complete
                for future in as_completed(future_to_rid):
                    rid, deaths, healing_data, defensive_data, error = future.result()
                    report_deaths_cache[rid] = deaths
                    report_healing_cache[rid] = healing_data
                    report_defensive_cache[rid] = defensive_data
                    completed += 1
                    
                    # Update progress every report
                    if completed % 5 == 0 or completed == total_reports:
                        yield f"data: {json.dumps({'stage': 'deaths', 'message': f'Fetching deaths from report {completed}/{total_reports}'})}\n\n"
            
            print(f"[PARALLEL] Completed all {total_reports} reports in parallel")

            yield f"data: {json.dumps({'stage': 'processing', 'message': f'Processing {len(all_fights_deduped)} fights...'})}\n\n"
            
            total_deaths = 0
            pullCutoffTimestamps = {}  # Store cutoff timestamps for each pull
            
            # DEBUG: Track deaths per report
            debug_deaths_per_report = {}
            
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
                
                # DEBUG: Log cache lookup
                if rid not in debug_deaths_per_report:
                    debug_deaths_per_report[rid] = 0
                    cached_fights = list(report_deaths_cache.get(rid, {}).keys())
                    print(f"[DEBUG] Report {rid} cache has fight IDs: {cached_fights[:5]}..." if len(cached_fights) > 5 else f"[DEBUG] Report {rid} cache has fight IDs: {cached_fights}")
                    print(f"[DEBUG] Looking for fid={fid} (type: {type(fid)})")
                
                fight_parts = set()
                friendly_player_ids = set(fight.get('friendlyPlayers', []))
                
                if friendly_player_ids:
                    for friendly in friendlies:
                        if friendly.get('id') in friendly_player_ids:
                            name = friendly.get('name')
                            if name:
                                fight_parts.add(name)
                else:
                    for friendly in friendlies:
                        name = friendly.get('name')
                        if name:
                            fight_parts.add(name)
                
                for p in fight_parts:
                    main_char = get_main_character(p, character_groups)
                    pull_key = f"{rid}_{fid}"
                    pull_participation[main_char].add(pull_key)
                    boss_participation[boss_name][main_char].add(pull_key)
                
                # Get all deaths for this fight (real + cheat if enabled)
                deaths = report_deaths_cache[rid].get(fid, [])
                deaths_sorted_all = sorted(deaths, key=lambda e: e["timestamp"])
                
                # DEBUG: Log death counts for first few fights
                if fight_idx <= 3:
                    print(f"  [DEBUG] Fight {fid} ({boss_name}): {len(deaths)} deaths in cache, {len(deaths_sorted_all)} after sort")
                    if rid in report_deaths_cache:
                        print(f"  [DEBUG]   report_deaths_cache[{rid}] has keys: {list(report_deaths_cache[rid].keys())[:5]}...")
                    else:
                        print(f"  [DEBUG]   WARNING: rid {rid} NOT in report_deaths_cache!")
                
                # Don't limit deaths artificially - send all deaths
                # The frontend will filter based on rankWithinPull and pullCutoffTimestamps
                deaths_sorted = deaths_sorted_all
                
                # DEBUG: Log if fight has many deaths
                if len(deaths_sorted_all) > 15:
                    print(f"  [WARN] Fight {fid} ({boss_name}) has {len(deaths_sorted_all)} deaths (sending all)")
                
                # Pre-calculate cutoff timestamp for the maxCutoff value
                # We need this to determine if a real death is "within cutoff"
                fight_start = fight['start_time']
                real_deaths_for_cutoff = [
                    d for d in deaths_sorted_all 
                    if not d.get("isCheatDeath", False)
                ]
                
                # Calculate the cutoff timestamp based on maxCutoff
                cutoff_timestamp = None
                if len(real_deaths_for_cutoff) >= max_cutoff:
                    # Get the timestamp of the Nth real death (relative to fight start)
                    nth_death = real_deaths_for_cutoff[max_cutoff - 1]
                    cutoff_timestamp = nth_death["timestamp"] - fight_start
                elif len(real_deaths_for_cutoff) > 0:
                    # Fewer deaths than maxCutoff, use the last death's timestamp
                    last_death = real_deaths_for_cutoff[-1]
                    cutoff_timestamp = last_death["timestamp"] - fight_start
                
                # Filter out redundant cheat deaths
                # A cheat death is redundant if:
                # 1. The same player has a real death after it
                # 2. BOTH the cheat death AND the real death are within the cutoff window
                redundant_cheat_death_indices = set()
                
                if cutoff_timestamp is not None:
                    # Group deaths by player (using normalized names for grouping)
                    deaths_by_player = defaultdict(list)
                    for idx, ev in enumerate(deaths_sorted):
                        player_name = normalize_character_name(ev["targetName"])
                        main_char = get_main_character(player_name, character_groups)
                        # Store with relative timestamp for cutoff comparison
                        relative_ts = ev["timestamp"] - fight_start
                        deaths_by_player[main_char].append((idx, ev, relative_ts))
                    
                    # For each player, mark redundant cheat deaths
                    for main_char, player_deaths in deaths_by_player.items():
                        # Already sorted by timestamp
                        for i, (idx, death, death_ts) in enumerate(player_deaths):
                            if death.get("isCheatDeath", False):
                                # This is a cheat death - check if it's within cutoff
                                if death_ts <= cutoff_timestamp:
                                    # Cheat death is within cutoff
                                    # Check if this player has a real death CLOSE IN TIME to this cheat death
                                    # "Close" = within 5 seconds (handles both normal failures and boss mechanics)
                                    # This prevents filtering cheat deaths from earlier death/rez cycles
                                    CLOSE_DEATH_WINDOW_MS = 5000  # 5 seconds
                                    
                                    closest_real_death = None
                                    closest_time_diff = float('inf')
                                    
                                    for j in range(len(player_deaths)):
                                        if j == i:
                                            continue  # Skip self
                                        
                                        other_idx, other_death, other_ts = player_deaths[j]
                                        
                                        # Check if it's a real death
                                        if not other_death.get("isCheatDeath", False):
                                            # Calculate time difference (absolute value)
                                            time_diff = abs(other_ts - death_ts)
                                            
                                            # Keep track of the closest real death
                                            if time_diff < closest_time_diff:
                                                closest_time_diff = time_diff
                                                closest_real_death = (other_idx, other_ts)
                                    
                                    # If there's a real death within 5 seconds AND within cutoff, filter the cheat death
                                    if closest_real_death is not None and closest_time_diff <= CLOSE_DEATH_WINDOW_MS:
                                        closest_idx, closest_ts = closest_real_death
                                        if closest_ts <= cutoff_timestamp:
                                            # Both are within cutoff AND close in time → mark cheat death as redundant
                                            redundant_cheat_death_indices.add(idx)
                
                # Assign TWO ranks to each death event:
                # 1. rankWithinPull - rank among REAL deaths only (ignoring cheat deaths)
                # 2. rankWithinPullTotal - rank among ALL deaths (including cheat deaths)
                real_death_rank = 0
                total_death_rank = 0
                deaths_added_this_fight = 0
                
                for idx, ev in enumerate(deaths_sorted):
                    # Skip redundant cheat deaths
                    if idx in redundant_cheat_death_indices:
                        continue
                    total_death_rank += 1
                    is_cheat = ev.get("isCheatDeath", False)
                    
                    # Skip cheat deaths that are outside the cutoff window
                    if is_cheat and cutoff_timestamp is not None:
                        death_relative_ts = ev["timestamp"] - fight_start
                        if death_relative_ts > cutoff_timestamp:
                            continue  # Don't send cheat deaths outside cutoff to frontend
                    
                    
                    if not is_cheat:
                        real_death_rank += 1
                    
                    original_char = ev["targetName"]
                    main_char = get_main_character(original_char, character_groups)
                    
                    # Look up class/spec info from player_details
                    target_id = ev.get("targetID")
                    player_class = "Unknown"
                    player_spec = "Unknown"
                    
                    # DEBUG: Log player_details availability
                    if idx == 1 and total_death_rank == 1:  # First death of first processed fight
                        print(f"\n[DEBUG] DEBUG player_details lookup:")
                        print(f"  - player_details has {len(player_details)} entries")
                        if player_details:
                            sample_id = next(iter(player_details))
                            print(f"  - Sample ID in player_details: {sample_id} -> {player_details[sample_id]}")
                        print(f"  - Current death targetID: {target_id}")
                        print(f"  - Target name: {original_char}")
                        print(f"  - targetID in player_details? {target_id in player_details if target_id else 'targetID is None'}\n")
                    
                    if target_id and target_id in player_details:
                        player_class = player_details[target_id].get("class", "Unknown")
                        player_spec = player_details[target_id].get("spec", "Unknown")
                    elif target_id and total_death_rank <= 3:  # Log first few misses
                        print(f"[WARN]  Could not find class/spec for {original_char} (ID: {target_id})")
                    
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
                        "rankWithinPull": real_death_rank,  # Rank among real deaths only
                        "rankWithinPullTotal": total_death_rank,  # Rank among all deaths
                        "absTs": report_abs_start + ev["timestamp"],
                        "timestamp": ev["timestamp"] - fight['start_time'],  # Make relative to fight start (for cutoff comparison)
                        "abilityName": ev.get("abilityName", "Unknown"),
                        "isCheatDeath": is_cheat,
                        "class": player_class,
                        "spec": player_spec,
                        "targetID": ev.get("targetID")  # Store targetID for on-demand fetching
                    }
                    
                    # If defensive tracking enabled, calculate from bulk cached data (NO API CALLS!)
                    if enable_defensive_tracking and target_id:
                        healing_data = report_healing_cache.get(rid, [])
                        defensive_data = report_defensive_cache.get(rid, [])
                        
                        # Debug logging for first death only
                        if total_deaths == 0:
                            print(f"[DEBUG] First death - Cached healing events: {len(healing_data)}, Cached defensive buffs: {len(defensive_data)}")
                        
                        if healing_data or defensive_data:
                            death_event['defensives'] = calculate_defensive_data_from_bulk(
                                ev["timestamp"],
                                target_id,
                                defensive_data,
                                healing_data
                            )
                        elif total_deaths == 0:
                            print(f"[DEBUG] No cached data available for report {rid}")
                    
                    counted_death_events[main_char].append(death_event)
                    character_breakdown[main_char][original_char].append(death_event)
                    total_deaths += 1
                    deaths_added_this_fight += 1
                
                # DEBUG: Log if we added any deaths
                if deaths_added_this_fight > 0 and fight_idx <= 5:
                    print(f"  [DEBUG] Added {deaths_added_this_fight} deaths from fight {fid} ({boss_name})")
                
                # Calculate cutoff timestamps for this pull
                pull_key = f"{rid}_{fid}"
                pullCutoffTimestamps[pull_key] = {}
                
                # Get only REAL deaths (no cheat deaths) with timestamps relative to fight start
                fight_start = fight['start_time']
                real_deaths_only = [
                    {**d, "timestamp": d["timestamp"] - fight_start}
                    for d in deaths_sorted_all 
                    if not d.get("isCheatDeath", False)
                ]
                
                # Calculate cutoff timestamp for ALL possible cutoff values
                # (up to the number of real deaths in this pull)
                # This lets the frontend use any cutoff value without re-running the analysis
                for cutoff_val in range(1, len(real_deaths_only) + 1):
                    # Get the index of the cutoff-th death (0-indexed)
                    cutoff_idx = cutoff_val - 1
                    
                    # Check if this death is in a mass death event
                    mass_death_start = find_mass_death_start(cutoff_idx, real_deaths_only)
                    
                    if mass_death_start is not None:
                        # Use the start of the mass death window as the cutoff
                        pullCutoffTimestamps[pull_key][cutoff_val] = mass_death_start
                    else:
                        # Use the timestamp of the cutoff-th death normally
                        pullCutoffTimestamps[pull_key][cutoff_val] = real_deaths_only[cutoff_idx]["timestamp"]
            
            # DEBUG: Log final counts before sending
            print(f"[DEBUG] Final death counts:")
            print(f"  - total_deaths: {total_deaths}")
            print(f"  - Players with deaths: {len(counted_death_events)}")
            for player, deaths_list in list(counted_death_events.items())[:3]:
                print(f"  - {player}: {len(deaths_list)} deaths")
            
            yield f"data: {json.dumps({'stage': 'complete', 'message': f'Analysis complete! Tracked {total_deaths} deaths across {len(counted_death_events)} players'})}\n\n"
            
            # Convert sets to lists
            pull_participation_json = {p: list(s) for p, s in pull_participation.items()}
            boss_participation_json = {
                b: {p: list(s2) for p, s2 in players.items()}
                for b, players in boss_participation.items()
            }
            character_breakdown_json = {
                main: {char: evs for char, evs in chars.items()}
                for main, chars in character_breakdown.items()
            }
            
            # Build final response
            response = {
                "meta": {
                    "guild_name": guild_name,
                    "maxCutoff": max_cutoff,
                    "authorFilters": author_filters,
                    "startDate": start_date,  # Optional start date filter
                    "endDate": end_date,  # Optional end date filter
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

@app.route('/api/delete-user-account/<user_id>', methods=['DELETE'])
def delete_user_account(user_id):
    result = supabase_client.delete_user_account(user_id)
    if "error" in result:
        return jsonify(result), 500
    return jsonify(result)


# =============================================================================
# HEALTH & STATUS
# =============================================================================

@app.route('/api/health', methods=['GET'])
def health():
    return jsonify({"status": "healthy", "supabase": supabase_client.is_configured()})


@app.route('/', methods=['GET'])
def root():
    return jsonify({"service": "Floor Pov API", "version": "3.0.0-modular", "status": "running"})


# =============================================================================
# MAIN
# =============================================================================

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    print(f"Starting Floor Pov API v3.0.0 (modular) on port {port}...")
    app.run(host='0.0.0.0', port=port, debug=False)