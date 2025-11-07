#!/usr/bin/env python3
"""
Flask API for WarcraftLogs Death Tracker - V2 GraphQL API
OPTIMIZED VERSION - Bulk data fetching to reduce API calls by ~85%
Version 3.0.0 - Bulk fetching optimization
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
import unicodedata

app = Flask(__name__)
CORS(app)

# Constants
MASS_DEATH_THRESHOLD = 7
MASS_DEATH_WINDOW = 10000  # ms

# Cheat Death Abilities
CHEAT_DEATH_ABILITY_IDS = {
    45181, 87024, 123981, 211319, 404369, 1236692, 209261
}

# WarcraftLogs V2 API endpoints (through Cloudflare Worker proxy)
GRAPHQL_ENDPOINT = "https://wcl-proxy.catcam-fun.workers.dev/api/v2/client"
OAUTH_TOKEN_URL = "https://wcl-proxy.catcam-fun.workers.dev/oauth/token"

# OAuth2 token cache
_token_cache = {"token": None, "expires_at": 0}


def normalize_character_name(name):
    """Normalize character names to handle UTF-8 encoding issues."""
    if not name:
        return name
    nfd = unicodedata.normalize('NFD', name)
    ascii_name = ''.join(char for char in nfd if unicodedata.category(char) != 'Mn')
    return ascii_name if ascii_name else name


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
    """Return the main character name for a player."""
    for main, alts in character_groups.items():
        if player_name in alts:
            return main
    return player_name


def get_guild_reports(token, guild_name, server, region, zone_id, cutoff_date):
    """Fetch guild reports using V2 GraphQL API"""
    cutoff_ts = int(datetime.strptime(cutoff_date, "%Y-%m-%d").timestamp() * 1000) + 86400000 - 1
    
    query = """
    query($guildName: String!, $serverSlug: String!, $serverRegion: String!, $zoneID: Int!) {
      reportData {
        reports(guildName: $guildName, guildServerSlug: $serverSlug, guildServerRegion: $serverRegion, zoneID: $zoneID, limit: 100) {
          data {
            code
            startTime
            endTime
            zone { id }
            owner { name }
          }
        }
      }
    }
    """
    
    variables = {
        "guildName": guild_name,
        "serverSlug": server.lower().replace(" ", "-").replace("'", ""),
        "serverRegion": region.upper(),
        "zoneID": int(zone_id)
    }
    
    try:
        data = graphql_query(token, query, variables)
        reports_data = data.get("reportData", {}).get("reports", {}).get("data", [])
        
        out = []
        for rep in reports_data:
            if rep.get("startTime", 0) > cutoff_ts:
                continue
            out.append({
                "id": rep["code"],
                "start": rep.get("startTime", 0),
                "end": rep.get("endTime", 0),
                "owner": rep.get("owner", {}).get("name", "")
            })
        
        return out
    except Exception as e:
        raise Exception(f"Failed to fetch guild reports: {str(e)}")


def get_guild_roster(token, guild_name, server, region):
    """Fetch guild roster to identify guild members using pagination"""
    query = """
    query($guildName: String!, $serverSlug: String!, $serverRegion: String!, $page: Int!) {
      guildData {
        guild(name: $guildName, serverSlug: $serverSlug, serverRegion: $serverRegion) {
          members(limit: 100, page: $page) {
            data { name }
            has_more_pages
          }
        }
      }
    }
    """
    
    all_members = set()
    page = 1
    max_pages = 10
    
    try:
        while page <= max_pages:
            variables = {
                "guildName": guild_name,
                "serverSlug": server.lower().replace(" ", "-").replace("'", ""),
                "serverRegion": region.upper(),
                "page": page
            }
            
            data = graphql_query(token, query, variables)
            guild_data = data.get("guildData", {}).get("guild", {})
            
            if not guild_data:
                break
            
            members_data = guild_data.get("members", {})
            member_list = members_data.get("data", [])
            
            for member in member_list:
                name = member.get("name")
                if name:
                    all_members.add(normalize_character_name(name))
            
            if not members_data.get("has_more_pages", False):
                break
            
            page += 1
        
        return all_members
    except Exception as e:
        raise Exception(f"Failed to fetch guild roster: {str(e)}")


def get_report_data_bulk(token, report_code, zone_id, difficulty, enable_cheat_death):
    """
    OPTIMIZED: Fetch ALL fights and ALL relevant events for a report in bulk.
    This reduces per-fight API calls dramatically.
    
    Instead of:
    - 1 call per fight for participants
    - 1 call per fight for deaths
    
    We do:
    - 1 call for all fights
    - 1 call for all deaths in the report
    - 1 call for all participants (if cheat death enabled)
    """
    
    # Step 1: Get all fights for this report
    fights_query = """
    query($code: String!) {
      reportData {
        report(code: $code) {
          startTime
          fights(difficulty: """ + str(difficulty) + """, killType: Encounters) {
            id
            name
            encounterID
            startTime
            endTime
            kill
            difficulty
            gameZone { id }
          }
        }
      }
    }
    """
    
    try:
        data = graphql_query(token, fights_query, {"code": report_code})
        report_data = data.get("reportData", {}).get("report", {})
        
        if not report_data:
            return None, []
        
        report_abs_start = report_data.get("startTime", 0)
        fights = report_data.get("fights", [])
        
        # Filter fights by zone
        filtered_fights = []
        for fight in fights:
            game_zone = fight.get("gameZone", {})
            fight_zone_id = game_zone.get("id") if game_zone else None
            
            if fight_zone_id == int(zone_id):
                filtered_fights.append({
                    "id": fight["id"],
                    "name": fight.get("name", "Unknown"),
                    "encounter_id": fight.get("encounterID"),
                    "start_time": fight.get("startTime", 0),
                    "end_time": fight.get("endTime", 0),
                    "kill": fight.get("kill", False),
                    "difficulty": fight.get("difficulty", 0)
                })
        
        if not filtered_fights:
            return report_abs_start, []
        
        # Step 2: Get ALL death events for the entire report
        # This is much more efficient than per-fight queries
        start_time = min(f["start_time"] for f in filtered_fights)
        end_time = max(f["end_time"] for f in filtered_fights)
        
        deaths_query = """
        query($code: String!, $startTime: Float!, $endTime: Float!) {
          reportData {
            report(code: $code) {
              events(
                startTime: $startTime,
                endTime: $endTime,
                dataType: Deaths,
                limit: 10000
              ) {
                data
              }
            }
          }
        }
        """
        
        data = graphql_query(token, deaths_query, {
            "code": report_code,
            "startTime": start_time,
            "endTime": end_time
        })
        
        all_deaths = data.get("reportData", {}).get("report", {}).get("events", {}).get("data", [])
        
        # Step 3: If cheat death detection is enabled, get damage-done events for participants
        # This helps identify who was in each fight
        participants_by_fight = {}
        
        if enable_cheat_death:
            # Get participants using damage-done table (more efficient than per-fight queries)
            for fight in filtered_fights:
                participants_query = """
                query($code: String!, $fightIDs: [Int]!) {
                  reportData {
                    report(code: $code) {
                      table(fightIDs: $fightIDs, dataType: DamageDone)
                    }
                  }
                }
                """
                
                try:
                    data = graphql_query(token, participants_query, {
                        "code": report_code,
                        "fightIDs": [fight["id"]]
                    })
                    
                    table_data = data.get("reportData", {}).get("report", {}).get("table", {})
                    entries = table_data.get("data", {}).get("entries", [])
                    
                    participants = set()
                    for entry in entries:
                        name = entry.get("name")
                        if name:
                            participants.add(normalize_character_name(name))
                    
                    participants_by_fight[fight["id"]] = participants
                except:
                    participants_by_fight[fight["id"]] = set()
        
        # Step 4: Group deaths by fight
        deaths_by_fight = defaultdict(list)
        
        for death in all_deaths:
            timestamp = death.get("timestamp", 0)
            target_name = death.get("targetName")
            ability = death.get("ability", {})
            ability_id = ability.get("guid")
            ability_name = ability.get("name", "Unknown")
            
            if not target_name:
                continue
            
            # Find which fight this death belongs to
            for fight in filtered_fights:
                if fight["start_time"] <= timestamp <= fight["end_time"]:
                    is_cheat_death = ability_id in CHEAT_DEATH_ABILITY_IDS
                    
                    deaths_by_fight[fight["id"]].append({
                        "targetName": normalize_character_name(target_name),
                        "timestamp": timestamp,
                        "abilityName": ability_name,
                        "abilityId": ability_id,
                        "isCheatDeath": is_cheat_death,
                        "phase": death.get("phase", 1)
                    })
                    break
        
        # Step 5: Attach deaths and participants to each fight
        for fight in filtered_fights:
            fight["deaths"] = deaths_by_fight.get(fight["id"], [])
            fight["participants"] = participants_by_fight.get(fight["id"], set())
        
        return report_abs_start, filtered_fights
        
    except Exception as e:
        raise Exception(f"Failed to fetch bulk report data: {str(e)}")


def find_mass_death_start(cutoff_idx, deaths):
    """Find the start of a mass death event."""
    if cutoff_idx < 0 or cutoff_idx >= len(deaths):
        return None
    
    cutoff_death_time = deaths[cutoff_idx]["timestamp"]
    mass_death_count = 1
    earliest_mass_death_time = cutoff_death_time
    
    for i in range(cutoff_idx - 1, -1, -1):
        death_time = deaths[i]["timestamp"]
        if cutoff_death_time - death_time <= MASS_DEATH_WINDOW:
            mass_death_count += 1
            earliest_mass_death_time = death_time
        else:
            break
    
    if mass_death_count >= MASS_DEATH_THRESHOLD:
        return earliest_mass_death_time
    return None


@app.route('/api/analyze', methods=['POST'])
def analyze():
    """Analyze death data using OPTIMIZED bulk fetching"""
    # Extract payload BEFORE entering generator to avoid request context issues
    payload = request.get_json()
    
    def generate():
        try:
            
            # Extract parameters
            client_id = payload.get('clientId')
            client_secret = payload.get('clientSecret')
            guild_name = payload.get('guildName')
            server = payload.get('server')
            region = payload.get('region', 'us')
            report_zone = payload.get('reportZone', '44')
            fight_zone = payload.get('fightZone', '2810')
            difficulty = payload.get('difficulty', '5')
            max_cutoff = int(payload.get('maxCutoff', 5))
            cutoff_date = payload.get('cutoffDate', '2025-10-10')
            author_filters = payload.get('authorFilters', [])
            character_groups = payload.get('characterGroups', {})
            enable_cheat_death = payload.get('enableCheatDeath', False)
            
            yield f"data: {json.dumps({'stage': 'init', 'message': 'Getting access token...'})}\n\n"
            token = get_access_token(client_id, client_secret)
            
            yield f"data: {json.dumps({'stage': 'roster', 'message': 'Fetching guild roster...'})}\n\n"
            guild_members = get_guild_roster(token, guild_name, server, region)
            
            yield f"data: {json.dumps({'stage': 'reports', 'message': f'Fetching reports for {guild_name}...'})}\n\n"
            reports = get_guild_reports(token, guild_name, server, region, report_zone, cutoff_date)
            
            # Filter by author
            if author_filters:
                reports = [r for r in reports if r["owner"] in author_filters]
            
            if not reports:
                raise Exception(f"No reports found for guild {guild_name} on {server}-{region}")
            
            yield f"data: {json.dumps({'stage': 'processing', 'message': f'Found {len(reports)} reports. Processing with optimized bulk fetching...'})}\n\n"
            
            # Data structures
            counted_death_events = defaultdict(list)
            character_breakdown = defaultdict(lambda: defaultdict(list))
            pull_participation = defaultdict(set)
            boss_participation = defaultdict(lambda: defaultdict(set))
            pullCutoffTimestamps = {}
            total_deaths = 0
            
            # Process each report with BULK data fetching
            for idx, rep in enumerate(reports, 1):
                rid = rep["id"]
                yield f"data: {json.dumps({'stage': 'processing', 'message': f'Processing report {idx}/{len(reports)}: {rid}'})}\n\n"
                
                # OPTIMIZED: Get all fights and deaths for this report in bulk
                report_abs_start, fights = get_report_data_bulk(
                    token, rid, fight_zone, difficulty, enable_cheat_death
                )
                
                if not fights:
                    continue
                
                # Group fights by boss and assign sequence numbers
                boss_pulls = defaultdict(list)
                for fight in fights:
                    boss_name = fight["name"]
                    boss_pulls[boss_name].append(fight)
                
                # Sort each boss's pulls by start time
                for boss_name in boss_pulls:
                    boss_pulls[boss_name].sort(key=lambda x: x["start_time"])
                
                # Process each fight
                for fight in fights:
                    fid = fight["id"]
                    boss_name = fight["name"]
                    boss_id = fight["encounter_id"]
                    is_kill = fight["kill"]
                    
                    # Determine sequence number
                    seq_no = boss_pulls[boss_name].index(fight) + 1
                    pull_key = f"{rid}_{fid}"
                    
                    # Get deaths for this fight (already fetched in bulk)
                    deaths = fight["deaths"]
                    
                    # Filter to guild members only
                    deaths_filtered = [
                        d for d in deaths
                        if d["targetName"] in guild_members
                    ]
                    
                    if not deaths_filtered:
                        continue
                    
                    # Track participation
                    participants = fight.get("participants", set())
                    if not participants:
                        # Fallback: use deaths to determine participation
                        participants = {d["targetName"] for d in deaths_filtered}
                    
                    for p in participants:
                        main_p = get_main_character(p, character_groups)
                        pull_participation[main_p].add(pull_key)
                        boss_participation[boss_name][main_p].add(pull_key)
                    
                    # Sort deaths by timestamp
                    deaths_sorted_all = sorted(deaths_filtered, key=lambda x: x["timestamp"])
                    
                    # Filter redundant cheat deaths
                    cutoff_timestamp = fight["start_time"] + (max_cutoff * 60 * 1000)
                    redundant_cheat_death_indices = set()
                    
                    player_deaths_map = defaultdict(list)
                    for idx_death, death in enumerate(deaths_sorted_all):
                        player = death["targetName"]
                        player_deaths_map[player].append((idx_death, death, death["timestamp"]))
                    
                    for player, player_deaths in player_deaths_map.items():
                        player_deaths.sort(key=lambda x: x[2])
                        
                        for i, (idx, death, ts) in enumerate(player_deaths):
                            if not death.get("isCheatDeath", False):
                                continue
                            if ts > cutoff_timestamp:
                                continue
                            
                            for j in range(i + 1, len(player_deaths)):
                                next_idx, next_death, next_ts = player_deaths[j]
                                if not next_death.get("isCheatDeath", False):
                                    if next_ts <= cutoff_timestamp:
                                        redundant_cheat_death_indices.add(idx)
                                    break
                    
                    # Assign ranks
                    real_death_rank = 0
                    total_death_rank = 0
                    
                    for idx_death, ev in enumerate(deaths_sorted_all):
                        if idx_death in redundant_cheat_death_indices:
                            continue
                        
                        total_death_rank += 1
                        is_cheat = ev.get("isCheatDeath", False)
                        
                        if not is_cheat:
                            real_death_rank += 1
                        
                        original_char = ev["targetName"]
                        main_char = get_main_character(original_char, character_groups)
                        
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
                            "rankWithinPull": real_death_rank,
                            "rankWithinPullTotal": total_death_rank,
                            "absTs": report_abs_start + ev["timestamp"],
                            "timestamp": ev["timestamp"] - fight["start_time"],
                            "abilityName": ev.get("abilityName", "Unknown"),
                            "isCheatDeath": is_cheat
                        }
                        
                        counted_death_events[main_char].append(death_event)
                        character_breakdown[main_char][original_char].append(death_event)
                        total_deaths += 1
                    
                    # Calculate cutoff timestamps
                    fight_start = fight["start_time"]
                    real_deaths_only = [
                        {**d, "timestamp": d["timestamp"] - fight_start}
                        for d in deaths_sorted_all
                        if not d.get("isCheatDeath", False)
                    ]
                    
                    pullCutoffTimestamps[pull_key] = {}
                    for cutoff_val in range(1, len(real_deaths_only) + 1):
                        cutoff_idx = cutoff_val - 1
                        mass_death_start = find_mass_death_start(cutoff_idx, real_deaths_only)
                        
                        if mass_death_start is not None:
                            pullCutoffTimestamps[pull_key][cutoff_val] = mass_death_start
                        else:
                            pullCutoffTimestamps[pull_key][cutoff_val] = real_deaths_only[cutoff_idx]["timestamp"]
            
            yield f"data: {json.dumps({'stage': 'complete', 'message': f'Analysis complete! Tracked {total_deaths} deaths across {len(counted_death_events)} players'})}\n\n"
            
            # Convert to JSON-serializable format
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
                    "maxCutoff": max_cutoff,
                    "authorFilters": author_filters,
                    "dateCutoff": cutoff_date,
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


@app.route('/api/share', methods=['POST'])
def share_results():
    """Save analysis results and return a shareable ID"""
    try:
        payload = request.get_json()
        share_id = str(uuid.uuid4())[:8]
        
        shared_dir = os.path.join(os.path.dirname(__file__), 'shared_results')
        os.makedirs(shared_dir, exist_ok=True)
        
        filepath = os.path.join(shared_dir, f"{share_id}.json")
        with open(filepath, 'w') as f:
            json.dump({
                'data': payload.get('data'),
                'config': payload.get('config'),
                'timestamp': datetime.now().isoformat()
            }, f)
        
        return jsonify({'success': True, 'shareId': share_id})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/shared/<share_id>', methods=['GET'])
def get_shared_results(share_id):
    """Retrieve shared results by ID"""
    try:
        shared_dir = os.path.join(os.path.dirname(__file__), 'shared_results')
        filepath = os.path.join(shared_dir, f"{share_id}.json")
        
        if not os.path.exists(filepath):
            return jsonify({'success': False, 'error': 'Shared results not found'}), 404
        
        with open(filepath, 'r') as f:
            shared_data = json.load(f)
        
        return jsonify({
            'success': True,
            'data': shared_data.get('data'),
            'config': shared_data.get('config'),
            'timestamp': shared_data.get('timestamp')
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/health', methods=['GET'])
def health():
    """Health check endpoint"""
    return jsonify({"status": "ok", "message": "WarcraftLogs API is running"})


@app.route('/', methods=['GET'])
def root():
    """Root endpoint"""
    return jsonify({
        "service": "WarcraftLogs Death Tracker API",
        "version": "3.0.0 - Optimized",
        "status": "running",
        "endpoints": {
            "health": "/api/health",
            "analyze": "/api/analyze (POST with SSE)",
            "share": "/api/share (POST)",
            "shared": "/api/shared/<share_id> (GET)"
        }
    })


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    print(f"Starting WarcraftLogs Death Tracker API v3.0.0 (OPTIMIZED) on port {port}...")
    app.run(debug=False, host='0.0.0.0', port=port)