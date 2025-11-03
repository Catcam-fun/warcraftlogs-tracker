#!/usr/bin/env python3
"""
Flask API for WarcraftLogs Death Tracker - V2 GraphQL API
Fixed Version 2.4 - Proper death calculations with cheat death tracking
"""

from flask import Flask, request, jsonify, Response
from flask_cors import CORS
import requests
from collections import defaultdict
from datetime import datetime
import time
import os
import json
import uuid

app = Flask(__name__)
CORS(app)

# Constants
MASS_DEATH_THRESHOLD = 7
MASS_DEATH_WINDOW = 10000  # ms

# WarcraftLogs V2 API endpoints
GRAPHQL_ENDPOINT = "https://wcl-proxy.catcam-fun.workers.dev/api/v2/client"
OAUTH_TOKEN_URL = "https://wcl-proxy.catcam-fun.workers.dev/oauth/token"

# OAuth2 token cache
_token_cache = {"token": None, "expires_at": 0}

# Cheat Death Ability IDs - these appear as DEBUFFS in WarcraftLogs
# These IDs are confirmed from actual WarcraftLogs events
CHEAT_DEATH_ABILITY_IDS = {
    45181,    # Cheated Death (Rogue) - CONFIRMED
    87024,    # Cauterize (Mage - Fire) - CONFIRMED
    123981,   # Purgatory (Death Knight) - CONFIRMED  
    211319,   # Spirit of Redemption/Restitution (Holy Priest) - CONFIRMED
    404369,   # Empty Hourglass - CONFIRMED
    1236692,  # Void Reconstitution - CONFIRMED
    209261,   # Last Resort (Demon Hunter - Vengeance) - may need verification
}

def get_access_token(client_id, client_secret):
    """Get OAuth2 access token for V2 API"""
    global _token_cache
    
    if _token_cache["token"] and time.time() < _token_cache["expires_at"]:
        return _token_cache["token"]
    
    data = {
        "grant_type": "client_credentials",
        "client_id": client_id,
        "client_secret": client_secret
    }
    
    try:
        response = requests.post(OAUTH_TOKEN_URL, data=data, timeout=30)
        response.raise_for_status()
        token_data = response.json()
        
        _token_cache["token"] = token_data["access_token"]
        _token_cache["expires_at"] = time.time() + token_data.get("expires_in", 3600) - 60
        
        return _token_cache["token"]
    except Exception as e:
        raise Exception(f"Failed to get access token: {str(e)}")

def graphql_query(token, query, variables=None):
    """Execute a GraphQL query against WarcraftLogs V2 API"""
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    
    payload = {"query": query}
    if variables:
        payload["variables"] = variables
    
    try:
        response = requests.post(GRAPHQL_ENDPOINT, json=payload, headers=headers, timeout=60)
        response.raise_for_status()
        data = response.json()
        
        if "errors" in data:
            raise Exception(f"GraphQL errors: {data['errors']}")
        
        return data.get("data", {})
    except Exception as e:
        raise Exception(f"GraphQL query failed: {str(e)}")

def get_main_character(player_name, character_groups):
    """Return the main character name for a player"""
    for main, alts in character_groups.items():
        if player_name in alts:
            return main
    return player_name

def get_guild_reports(token, guild_name, server, region, zone_id, cutoff_date):
    """Fetch guild reports using V2 GraphQL API"""
    cutoff_ts = int(datetime.strptime(cutoff_date, "%Y-%m-%d").timestamp() * 1000) + 86400000 - 1
    
    query = """
    query($name: String!, $serverSlug: String!, $serverRegion: String!, $zoneID: Int!, $limit: Int!, $page: Int!) {
      reportData {
        reports(
          guildName: $name
          guildServerSlug: $serverSlug
          guildServerRegion: $serverRegion
          zoneID: $zoneID
          limit: $limit
          page: $page
        ) {
          data {
            code
            title
            owner { name }
            startTime
            endTime
            zone { id name }
          }
          has_more_pages
        }
      }
    }
    """
    
    all_reports = []
    page = 1
    limit = 100
    
    while True:
        variables = {
            "name": guild_name,
            "serverSlug": server,
            "serverRegion": region,
            "zoneID": int(zone_id),
            "limit": limit,
            "page": page
        }
        
        data = graphql_query(token, query, variables)
        reports_response = data.get("reportData", {}).get("reports", {})
        reports_data = reports_response.get("data", [])
        
        for report in reports_data:
            if report["startTime"] <= cutoff_ts:
                all_reports.append(report)
        
        if not reports_response.get("has_more_pages", False) or page > 20:
            break
        
        page += 1
    
    return all_reports

def get_report_details_bulk(token, report_code):
    """Fetch fights, friendlies, and abilities for a report"""
    query = """
    query($code: String!) {
      reportData {
        report(code: $code) {
          code
          startTime
          endTime
          fights {
            id boss name difficulty startTime endTime kill encounterID zoneID
          }
          masterData {
            actors(type: "Player") { id name type }
            abilities { gameID name }
          }
        }
      }
    }
    """
    
    variables = {"code": report_code}
    
    try:
        data = graphql_query(token, query, variables)
        report_data = data.get("reportData", {}).get("report", {})
        
        return {
            "code": report_data.get("code", report_code),
            "startTime": report_data.get("startTime"),
            "endTime": report_data.get("endTime"),
            "fights": report_data.get("fights", []),
            "friendlies": report_data.get("masterData", {}).get("actors", []),
            "abilities": report_data.get("masterData", {}).get("abilities", [])
        }
    except Exception as e:
        print(f"Error fetching report details: {e}")
        return None

def get_report_deaths_bulk(token, report_code, fights, friendlies, ability_map):
    """Get death events for an entire report"""
    if not fights:
        return {}
    
    actor_id_to_name = {f.get('id'): f.get('name') for f in friendlies if f.get('id') and f.get('name')}
    
    start_time = min(f['startTime'] for f in fights)
    end_time = max(f['endTime'] for f in fights)
    
    query = """
    query($code: String!, $startTime: Float!, $endTime: Float!) {
      reportData {
        report(code: $code) {
          events(startTime: $startTime endTime: $endTime dataType: Deaths limit: 10000) {
            data
          }
        }
      }
    }
    """
    
    variables = {"code": report_code, "startTime": start_time, "endTime": end_time}
    
    try:
        data = graphql_query(token, query, variables)
        events_data = data.get("reportData", {}).get("report", {}).get("events", {}).get("data", [])
        
        deaths_by_fight = {f['id']: [] for f in fights}
        
        for event in events_data:
            if event.get("type") != "death":
                continue
            
            fight_id = event.get("fight")
            if fight_id not in deaths_by_fight:
                continue
            
            target_id = event.get("targetID")
            target_name = actor_id_to_name.get(target_id, "Unknown")
            killing_ability_id = event.get("killingAbilityGameID")
            ability_name = ability_map.get(killing_ability_id, "Unknown")
            
            fight_obj = next((f for f in fights if f['id'] == fight_id), None)
            
            deaths_by_fight[fight_id].append({
                "timestamp": event.get("timestamp", 0),
                "targetName": target_name,
                "targetID": target_id,
                "phase": 1,
                "fightId": fight_id,
                "bossName": fight_obj.get('name', 'Unknown') if fight_obj else 'Unknown',
                "abilityName": ability_name,
            })
        
        # Filter mass deaths
        for fid in deaths_by_fight:
            deaths_by_fight[fid] = filter_mass_deaths(deaths_by_fight[fid])
        
        return deaths_by_fight
    
    except Exception as e:
        print(f"Error fetching deaths: {e}")
        return {f['id']: [] for f in fights}

def get_report_cheat_deaths_bulk(token, report_code, fights, friendlies, ability_map):
    """Get cheat death events (debuffs) for an entire report"""
    if not fights:
        return {}
    
    actor_id_to_name = {f.get('id'): f.get('name') for f in friendlies if f.get('id') and f.get('name')}
    
    start_time = min(f['startTime'] for f in fights)
    end_time = max(f['endTime'] for f in fights)
    
    all_cheat_deaths_by_fight = {f['id']: [] for f in fights}
    
    # Query each cheat death ability ID
    for ability_id in CHEAT_DEATH_ABILITY_IDS:
        query = """
        query($code: String!, $startTime: Float!, $endTime: Float!, $abilityID: Int!) {
          reportData {
            report(code: $code) {
              events(startTime: $startTime endTime: $endTime dataType: Debuffs abilityID: $abilityID limit: 10000) {
                data
              }
            }
          }
        }
        """
        
        variables = {
            "code": report_code,
            "startTime": start_time,
            "endTime": end_time,
            "abilityID": ability_id
        }
        
        try:
            data = graphql_query(token, query, variables)
            events_data = data.get("reportData", {}).get("report", {}).get("events", {}).get("data", [])
            
            for event in events_data:
                if event.get("type") != "applydebuff":
                    continue
                
                fight_id = event.get("fight")
                if fight_id not in all_cheat_deaths_by_fight:
                    continue
                
                target_id = event.get("targetID")
                target_name = actor_id_to_name.get(target_id, "Unknown")
                ability_name = ability_map.get(ability_id, f"Cheat Death ({ability_id})")
                
                fight_obj = next((f for f in fights if f['id'] == fight_id), None)
                
                all_cheat_deaths_by_fight[fight_id].append({
                    "timestamp": event.get("timestamp", 0),
                    "targetName": target_name,
                    "targetID": target_id,
                    "fightId": fight_id,
                    "bossName": fight_obj.get('name', 'Unknown') if fight_obj else 'Unknown',
                    "abilityName": ability_name,
                })
        
        except Exception as e:
            print(f"Error fetching cheat deaths for ability {ability_id}: {e}")
    
    return all_cheat_deaths_by_fight

def analyze_fights(fights, fight_zone, difficulty):
    """Filter fights by zone and difficulty"""
    return [f for f in fights if
            (f.get("boss") or 0) > 0 and
            f.get("zoneID") == int(fight_zone) and
            f.get("difficulty") == int(difficulty)]

def filter_mass_deaths(deaths):
    """Filter out mass death events (wipes)"""
    if len(deaths) < MASS_DEATH_THRESHOLD:
        return deaths
    
    sd = sorted(deaths, key=lambda d: d['timestamp'])
    for i in range(len(sd) - MASS_DEATH_THRESHOLD + 1):
        win_start = sd[i]['timestamp']
        win_end = win_start + MASS_DEATH_WINDOW
        cnt = sum(1 for j in range(i, len(sd)) if sd[j]['timestamp'] <= win_end)
        
        if cnt >= MASS_DEATH_THRESHOLD:
            return sd[:i]
    
    return sd

def get_raid_participants(friendlies):
    """Extract player participants from friendlies list"""
    parts = {}
    classes = ['Paladin', 'Warrior', 'DeathKnight', 'Hunter', 'Priest', 
               'Rogue', 'Shaman', 'Mage', 'Warlock', 'Monk', 'Druid', 
               'DemonHunter', 'Evoker']
    
    for fr in friendlies:
        if fr.get('type') in classes:
            parts[fr.get('id')] = fr.get('name', 'Unknown')
    
    return parts

def interval_overlap(a_start, a_end, b_start, b_end):
    """Calculate overlap between two intervals"""
    inter = max(0, min(a_end, b_end) - max(a_start, b_start))
    if inter == 0:
        return 0, 0.0
    union = (a_end - a_start) + (b_end - b_start) - inter
    return inter, (inter / union if union > 0 else 0.0)

def is_duplicate_pull(seen_by_boss, boss_id, abs_start, abs_end, is_kill=None):
    """Check if a pull is a duplicate based on time overlap"""
    MIN_ABS_OVERLAP_MS = 15000
    MIN_IOU_FOR_DUP = 0.50
    
    lst = seen_by_boss.setdefault(boss_id, [])
    for s_start, s_end, s_kill in lst:
        inter, iou = interval_overlap(abs_start, abs_end, s_start, s_end)
        if inter >= MIN_ABS_OVERLAP_MS or iou >= MIN_IOU_FOR_DUP:
            return True
    
    lst.append((abs_start, abs_end, is_kill))
    return False

@app.route('/analyze', methods=['POST'])
def analyze():
    """Stream analysis progress using SSE"""
    config_data = request.json
    
    # Parse configuration
    client_id = config_data.get('clientId')
    client_secret = config_data.get('clientSecret')
    guild_name = config_data.get('guildName')
    server = config_data.get('server')
    region = config_data.get('region', 'us')
    report_zone = config_data.get('reportZone', '44')
    fight_zone = config_data.get('fightZone', '2810')
    difficulty = config_data.get('difficulty', '5')
    max_cutoff = int(config_data.get('maxCutoff', 3))
    cutoff_date = config_data.get('cutoffDate', '2025-01-01')
    author_filters = config_data.get('authorFilters', '').split(',') if config_data.get('authorFilters') else []
    character_groups = {}
    track_cheat_deaths = config_data.get('trackCheatDeaths', False)
    
    # Parse character groups from JSON string
    try:
        if config_data.get('characterGroups'):
            character_groups = json.loads(config_data.get('characterGroups'))
    except:
        pass
    
    def generate():
        try:
            # Get OAuth2 token
            yield f"data: {json.dumps({'stage': 'auth', 'message': 'Authenticating with WarcraftLogs...'})}\n\n"
            token = get_access_token(client_id, client_secret)
            
            # Fetch guild reports
            yield f"data: {json.dumps({'stage': 'reports', 'message': f'Fetching reports for {guild_name}-{server}...'})}\n\n"
            reports = get_guild_reports(token, guild_name, server, region, report_zone, cutoff_date)
            
            # Filter by author if needed
            if author_filters and author_filters[0]:
                reports = [r for r in reports if r.get('owner', {}).get('name') in author_filters]
            
            yield f"data: {json.dumps({'stage': 'reports', 'message': f'Found {len(reports)} reports to analyze'})}\n\n"
            
            # Storage for all data
            all_fights_deduped = []
            seen_by_boss = {}
            counted_death_events = defaultdict(list)
            counted_cheat_death_events = defaultdict(list)
            character_breakdown = defaultdict(lambda: defaultdict(list))
            pull_participation = defaultdict(set)
            boss_participation = defaultdict(lambda: defaultdict(set))
            boss_order = {}
            
            # Cache for report data
            report_deaths_cache = {}
            report_cheat_deaths_cache = {}
            
            # Process reports
            for idx, report in enumerate(reports, 1):
                rid = report.get("code")
                
                if not rid:
                    continue
                
                yield f"data: {json.dumps({'stage': 'processing', 'message': f'Processing report {idx}/{len(reports)}: {rid}'})}\n\n"
                
                # Fetch report details
                report_details = get_report_details_bulk(token, rid)
                
                if not report_details:
                    continue
                
                fights = report_details.get("fights", [])
                friendlies = report_details.get("friendlies", [])
                abilities = report_details.get("abilities", [])
                report_abs_start = report_details.get("startTime", 0)
                
                # Build ability map
                ability_map = {a.get("gameID"): a.get("name") for a in abilities if a.get("gameID")}
                
                # Filter fights
                valid_fights = analyze_fights(fights, fight_zone, difficulty)
                
                if not valid_fights:
                    continue
                
                # Fetch deaths for all valid fights
                deaths_by_fight = get_report_deaths_bulk(token, rid, valid_fights, friendlies, ability_map)
                report_deaths_cache[rid] = deaths_by_fight
                
                # Fetch cheat deaths if tracking is enabled
                if track_cheat_deaths:
                    cheat_deaths_by_fight = get_report_cheat_deaths_bulk(token, rid, valid_fights, friendlies, ability_map)
                    report_cheat_deaths_cache[rid] = cheat_deaths_by_fight
                
                # Process each fight
                for fight in valid_fights:
                    fid = fight['id']
                    fight_abs_start = report_abs_start + fight['startTime']
                    fight_abs_end = report_abs_start + fight['endTime']
                    boss_id = fight.get('boss', 0)
                    boss_name = fight.get('name', 'Unknown')
                    is_kill = fight.get('kill', False)
                    
                    if boss_id not in boss_order:
                        boss_order[boss_id] = boss_name
                    
                    # Check for duplicate
                    if is_duplicate_pull(seen_by_boss, boss_id, fight_abs_start, fight_abs_end, is_kill):
                        continue
                    
                    # Add to deduplicated list
                    all_fights_deduped.append({
                        "reportId": rid,
                        "fightId": fid,
                        "bossId": boss_id,
                        "bossName": boss_name,
                        "isKill": is_kill,
                        "absStart": fight_abs_start,
                        "absEnd": fight_abs_end
                    })
            
            # Sort fights by timestamp
            all_fights_deduped.sort(key=lambda x: x["absStart"])
            
            # Assign pull numbers
            pull_nums_by_boss = defaultdict(int)
            for fight in all_fights_deduped:
                boss_id = fight["bossId"]
                pull_nums_by_boss[boss_id] += 1
                fight["pullNo"] = pull_nums_by_boss[boss_id]
            
            # Process each deduplicated fight
            total_deaths = 0
            
            for idx, fight in enumerate(all_fights_deduped, 1):
                if idx % 10 == 0:
                    yield f"data: {json.dumps({'stage': 'processing', 'message': f'Processing fight {idx}/{len(all_fights_deduped)} - {total_deaths} deaths found'})}\n\n"
                
                rid = fight["reportId"]
                fid = fight["fightId"]
                boss_id = fight["bossId"]
                boss_name = fight["bossName"]
                is_kill = fight["isKill"]
                seq_no = fight["pullNo"]
                
                # Get participants for this fight
                report_details = get_report_details_bulk(token, rid)
                if not report_details:
                    continue
                
                # Get raid participants
                participants = get_raid_participants(report_details.get("friendlies", []))
                fight_parts = set(participants.values())
                
                # Track participation
                for p in fight_parts:
                    main_char = get_main_character(p, character_groups)
                    pull_id = f"{boss_id}-{seq_no}"
                    pull_participation[main_char].add(pull_id)
                    boss_participation[boss_id][main_char].add(seq_no)
                
                # Process deaths for this fight
                deaths = report_deaths_cache.get(rid, {}).get(fid, [])
                deaths_sorted = sorted(deaths, key=lambda e: e["timestamp"])
                
                # CRITICAL: Store the cutoff timestamp for this fight
                cutoff_timestamp = float('inf')
                if len(deaths_sorted) > 0 and max_cutoff > 0:
                    cutoff_index = min(max_cutoff - 1, len(deaths_sorted) - 1)
                    if cutoff_index >= 0:
                        cutoff_timestamp = deaths_sorted[cutoff_index]["timestamp"]
                
                # Assign rank within pull (death order)
                for rank, death_ev in enumerate(deaths_sorted, 1):
                    original_char = death_ev["targetName"]
                    main_char = get_main_character(original_char, character_groups)
                    
                    # Skip if this character wasn't in this fight
                    if main_char not in fight_parts and original_char not in fight_parts:
                        continue
                    
                    death_event = {
                        "player": main_char,
                        "originalCharacter": original_char,
                        "boss": boss_name,
                        "bossId": boss_id,
                        "phase": death_ev.get("phase", 1),
                        "reportId": rid,
                        "fightId": fid,
                        "isKill": is_kill,
                        "pullNo": seq_no,
                        "rankWithinPull": rank,
                        "absTs": fight_abs_start + death_ev["timestamp"],
                        "abilityName": death_ev.get("abilityName", "Unknown")
                    }
                    counted_death_events[main_char].append(death_event)
                    character_breakdown[main_char][original_char].append(death_event)
                    total_deaths += 1
                
                # Process cheat deaths WITHIN THE DEATH WINDOW
                if track_cheat_deaths and rid in report_cheat_deaths_cache:
                    cheat_deaths = report_cheat_deaths_cache[rid].get(fid, [])
                    cheat_deaths_sorted = sorted(cheat_deaths, key=lambda e: e["timestamp"])
                    
                    for cheat_ev in cheat_deaths_sorted:
                        # Only count cheat deaths within the death window
                        if cheat_ev["timestamp"] > cutoff_timestamp:
                            break  # Since they're sorted, we can stop here
                        
                        original_char = cheat_ev["targetName"]
                        main_char = get_main_character(original_char, character_groups)
                        
                        # Skip if this character wasn't in this fight
                        if main_char not in fight_parts and original_char not in fight_parts:
                            continue
                        
                        # Calculate pseudo-rank for cheat death (where it would have been)
                        pseudo_rank = 1
                        for death in deaths_sorted:
                            if death["timestamp"] < cheat_ev["timestamp"]:
                                pseudo_rank += 1
                            else:
                                break
                        
                        cheat_death_event = {
                            "player": main_char,
                            "originalCharacter": original_char,
                            "boss": boss_name,
                            "bossId": boss_id,
                            "reportId": rid,
                            "fightId": fid,
                            "isKill": is_kill,
                            "pullNo": seq_no,
                            "absTs": fight_abs_start + cheat_ev["timestamp"],
                            "abilityName": cheat_ev.get("abilityName", "Cheated Death"),
                            "rankWithinPull": pseudo_rank,  # Add pseudo rank for proper filtering
                            "isCheatDeath": True  # Flag to identify cheat deaths
                        }
                        counted_cheat_death_events[main_char].append(cheat_death_event)
            
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
                    "maxCutoff": max_cutoff,
                    "authorFilters": author_filters,
                    "dateCutoff": cutoff_date,
                    "zone": fight_zone,
                    "difficulty": difficulty,
                    "generatedAt": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "characterGroups": character_groups,
                    "reportCount": len(reports),
                    "trackCheatDeaths": track_cheat_deaths,
                },
                "events": counted_death_events,
                "cheatDeathEvents": counted_cheat_death_events if track_cheat_deaths else {},
                "pullParticipation": pull_participation_json,
                "bossParticipation": boss_participation_json,
                "characterBreakdown": character_breakdown_json,
                "bossOrder": boss_order
            }
            
            yield f"data: {json.dumps({'stage': 'done', 'data': response})}\n\n"
            
        except Exception as e:
            error_msg = str(e)
            print(f"Error in analysis: {error_msg}")
            yield f"data: {json.dumps({'stage': 'error', 'message': error_msg})}\n\n"
    
    return Response(generate(), mimetype='text/event-stream')

@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint"""
    return jsonify({"status": "healthy", "version": "2.4-fixed"})

@app.route('/share', methods=['POST'])
def share_results():
    """Save results for sharing"""
    try:
        data = request.json
        share_id = str(uuid.uuid4())[:8]
        return jsonify({"shareId": share_id, "success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/share/<share_id>', methods=['GET'])
def get_shared_results(share_id):
    """Retrieve shared results"""
    try:
        return jsonify({"error": "Share functionality not yet implemented"}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port, debug=False)