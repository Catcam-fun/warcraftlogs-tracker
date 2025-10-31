#!/usr/bin/env python3
"""
Flask API for WarcraftLogs Death Tracker - V2 GraphQL API
Optimized for Render.com deployment
Version 2.4 - Added shareable results functionality
"""

from flask import Flask, request, jsonify, Response
from flask_cors import CORS
import requests
from collections import defaultdict
from datetime import datetime
import time
import os
import json
import hashlib
import uuid

app = Flask(__name__)

# Configure CORS - simplest approach, allow everything
CORS(app)

# Constants
MASS_DEATH_THRESHOLD = 7
MASS_DEATH_WINDOW = 10000  # ms

# WarcraftLogs V2 API endpoints (through Cloudflare Worker proxy)
GRAPHQL_ENDPOINT = "https://wcl-proxy.catcam-fun.workers.dev/api/v2/client"
OAUTH_TOKEN_URL = "https://wcl-proxy.catcam-fun.workers.dev/oauth/token"

# OAuth2 token cache
_token_cache = {"token": None, "expires_at": 0}

# Shared results storage directory
SHARED_RESULTS_DIR = os.path.join(os.path.dirname(__file__), 'shared_results')
os.makedirs(SHARED_RESULTS_DIR, exist_ok=True)


def get_access_token(client_id, client_secret):
    """Get OAuth2 access token for V2 API"""
    global _token_cache
    
    # Check if we have a valid cached token
    if _token_cache["token"] and time.time() < _token_cache["expires_at"]:
        return _token_cache["token"]
    
    # Request new token
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
        # Cache expires 60 seconds before actual expiry for safety
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
    """Return the main character name for a player, or the player name if not grouped."""
    for main, alts in character_groups.items():
        if player_name in alts:
            return main
    return player_name


def get_guild_reports(token, guild_name, server, region, zone_id, cutoff_date):
    """Fetch guild reports using V2 GraphQL API"""
    
    # Convert cutoff date to timestamp
    cutoff_ts = int(datetime.strptime(cutoff_date, "%Y-%m-%d").timestamp() * 1000) + 86400000 - 1
    
    query = """
    query($guildName: String!, $serverSlug: String!, $serverRegion: String!, $zoneID: Int!) {
      reportData {
        reports(guildName: $guildName, guildServerSlug: $serverSlug, guildServerRegion: $serverRegion, zoneID: $zoneID, limit: 100) {
          data {
            code
            startTime
            endTime
            zone {
              id
            }
            owner {
              name
            }
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


def get_fights(token, report_code):
    """Fetch fights for a report using V2 GraphQL API"""
    
    query = """
    query($code: String!) {
      reportData {
        report(code: $code) {
          startTime
          fights {
            id
            startTime
            endTime
            name
            encounterID
            difficulty
            kill
            gameZone {
              id
            }
            friendlyPlayers
          }
          masterData {
            actors(type: "Player") {
              id
              name
              type
              subType
            }
          }
        }
      }
    }
    """
    
    variables = {"code": report_code}
    
    try:
        data = graphql_query(token, query, variables)
        report = data.get("reportData", {}).get("report", {})
        
        if not report:
            return {"report_start": 0, "fights": [], "friendlies": []}
        
        fights = report.get("fights", [])
        actors = report.get("masterData", {}).get("actors", [])
        report_start = report.get("startTime", 0)
        
        print(f"Report {report_code}: Found {len(fights)} fights, {len(actors)} actors")
        
        # Convert to format compatible with existing code
        formatted_fights = []
        for fight in fights:
            formatted_fights.append({
                "id": fight.get("id"),
                "start_time": fight.get("startTime"),
                "end_time": fight.get("endTime"),
                "name": fight.get("name"),
                "boss": fight.get("encounterID"),
                "difficulty": fight.get("difficulty"),
                "kill": fight.get("kill"),
                "zoneID": fight.get("gameZone", {}).get("id"),
                "friendlyPlayers": fight.get("friendlyPlayers", [])
            })
        
        return {
            "report_start": report_start,
            "fights": formatted_fights,
            "friendlies": actors
        }
    except Exception as e:
        raise Exception(f"Failed to get fights for report {report_code}: {str(e)}")


def get_ability_name_map(token, report_code):
    """Get ability ID to name mapping for a report"""
    query = """
    query($code: String!) {
      reportData {
        report(code: $code) {
          masterData {
            abilities {
              gameID
              name
            }
          }
        }
      }
    }
    """
    
    variables = {"code": report_code}
    
    try:
        data = graphql_query(token, query, variables)
        abilities = data.get("reportData", {}).get("report", {}).get("masterData", {}).get("abilities", [])
        
        ability_map = {}
        for ability in abilities:
            ability_map[ability.get("gameID")] = ability.get("name", "Unknown")
        
        return ability_map
    except Exception as e:
        print(f"Warning: Failed to get ability map for report {report_code}: {str(e)}")
        return {}


def get_report_deaths_bulk(token, report_code, fights, friendlies, ability_map):
    """Fetch deaths for multiple fights in a report using bulk query"""
    if not fights:
        return {}
    
    fight_ids = [f['id'] for f in fights]
    
    query = """
    query($code: String!, $fightIDs: [Int]!) {
      reportData {
        report(code: $code) {
          events(
            fightIDs: $fightIDs,
            dataType: Deaths,
            limit: 10000
          ) {
            data
          }
        }
      }
    }
    """
    
    variables = {
        "code": report_code,
        "fightIDs": fight_ids
    }
    
    try:
        data = graphql_query(token, query, variables)
        events = data.get("reportData", {}).get("report", {}).get("events", {}).get("data", [])
        
        deaths_by_fight = defaultdict(list)
        friendly_ids = {f.get('id') for f in friendlies}
        friendly_names = {f.get('id'): f.get('name') for f in friendlies}
        
        for event in events:
            target_id = event.get("targetID")
            if target_id not in friendly_ids:
                continue
            
            fight_id = event.get("fight")
            ability_id = event.get("abilityGameID")
            ability_name = ability_map.get(ability_id, "Unknown")
            
            deaths_by_fight[fight_id].append({
                "timestamp": event.get("timestamp", 0),
                "targetID": target_id,
                "targetName": friendly_names.get(target_id, "Unknown"),
                "abilityGameID": ability_id,
                "abilityName": ability_name,
                "phase": event.get("fightPercentage", {}).get("phase", 1)
            })
        
        return dict(deaths_by_fight)
    except Exception as e:
        print(f"Warning: Failed to get deaths for report {report_code}: {str(e)}")
        return {}


def analyze_fights(fights, filter_zone, filter_difficulty):
    """Filter fights by zone and difficulty"""
    out = []
    for f in fights:
        zone_id = f.get('zoneID')
        difficulty = f.get('difficulty')
        
        if filter_zone and zone_id != int(filter_zone):
            continue
        if filter_difficulty and difficulty != int(filter_difficulty):
            continue
        
        out.append(f)
    
    return out


def is_duplicate_pull(seen_pulls_by_boss, boss_id, abs_start, abs_end, is_kill):
    """Check if a pull is a duplicate based on timing"""
    if boss_id not in seen_pulls_by_boss:
        seen_pulls_by_boss[boss_id] = []
        return False
    
    for existing in seen_pulls_by_boss[boss_id]:
        existing_start = existing['start']
        existing_end = existing['end']
        existing_kill = existing['kill']
        
        overlap_start = max(abs_start, existing_start)
        overlap_end = min(abs_end, existing_end)
        overlap = max(0, overlap_end - overlap_start)
        
        this_duration = abs_end - abs_start
        existing_duration = existing_end - existing_start
        
        if this_duration > 0:
            this_overlap_pct = (overlap / this_duration) * 100
        else:
            this_overlap_pct = 0
        
        if existing_duration > 0:
            existing_overlap_pct = (overlap / existing_duration) * 100
        else:
            existing_overlap_pct = 0
        
        if this_overlap_pct > 80 or existing_overlap_pct > 80:
            if is_kill and not existing_kill:
                seen_pulls_by_boss[boss_id].remove(existing)
                seen_pulls_by_boss[boss_id].append({'start': abs_start, 'end': abs_end, 'kill': is_kill})
                return False
            return True
    
    seen_pulls_by_boss[boss_id].append({'start': abs_start, 'end': abs_end, 'kill': is_kill})
    return False


@app.route('/api/analyze', methods=['POST'])
def analyze():
    """Analyze deaths with real-time progress updates via SSE"""
    
    def generate():
        try:
            payload = request.get_json()
            
            # Extract parameters
            client_id = payload.get('clientId')
            client_secret = payload.get('clientSecret')
            guild_name = payload.get('guildName')
            server = payload.get('server')
            region = payload.get('region', 'us')
            report_zone = payload.get('reportZone')
            fight_zone = payload.get('fightZone')
            difficulty = payload.get('difficulty')
            max_cutoff = int(payload.get('maxCutoff', 5))
            cutoff_date = payload.get('cutoffDate', '2025-10-10')
            author_filters = payload.get('authorFilters', [])
            character_groups = payload.get('characterGroups', {})
            
            yield f"data: {json.dumps({'stage': 'auth', 'message': 'Authenticating with WarcraftLogs...'})}\n\n"
            token = get_access_token(client_id, client_secret)
            
            yield f"data: {json.dumps({'stage': 'reports', 'message': 'Fetching guild reports...'})}\n\n"
            reports = get_guild_reports(token, guild_name, server, region, report_zone, cutoff_date)
            
            if author_filters:
                reports = [r for r in reports if r.get('owner') in author_filters]
            
            yield f"data: {json.dumps({'stage': 'reports', 'message': f'Found {len(reports)} reports to analyze'})}\n\n"
            
            if not reports:
                yield f"data: {json.dumps({'error': 'No reports found matching the criteria'})}\n\n"
                return
            
            # Fetch fights and abilities
            yield f"data: {json.dumps({'stage': 'fights', 'message': 'Fetching fight data...'})}\n\n"
            all_fights_raw = []
            report_ability_maps = {}
            
            for idx, rep in enumerate(reports, 1):
                rid = rep['id']
                report_abs_start = rep['start']
                
                yield f"data: {json.dumps({'stage': 'fights', 'message': f'Processing report {idx}/{len(reports)}'})}\n\n"
                
                fight_info = get_fights(token, rid)
                fights = fight_info['fights']
                friendlies = fight_info['friendlies']
                
                ability_map = get_ability_name_map(token, rid)
                report_ability_maps[rid] = ability_map
                
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
                        'ability_map': report_ability_maps[rid]
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
            
            # Fetch deaths in bulk
            yield f"data: {json.dumps({'stage': 'deaths', 'message': f'Fetching deaths for {len(fights_by_report)} reports...'})}\n\n"
            report_deaths_cache = {}
            for report_idx, (rid, report_fights) in enumerate(fights_by_report.items(), 1):
                yield f"data: {json.dumps({'stage': 'deaths', 'message': f'Fetching deaths from report {report_idx}/{len(fights_by_report)}'})}\n\n"
                sample_fight_data = report_fights[0]
                friendlies = sample_fight_data['friendlies']
                ability_map = sample_fight_data['ability_map']
                fights_list = [fd['fight'] for fd in report_fights]
                
                report_deaths_cache[rid] = get_report_deaths_bulk(token, rid, fights_list, friendlies, ability_map)
            
            yield f"data: {json.dumps({'stage': 'processing', 'message': f'Processing {len(all_fights_deduped)} fights...'})}\n\n"
            
            total_deaths = 0
            for idx, fight_data in enumerate(all_fights_deduped, 1):
                if idx % 10 == 0:
                    yield f"data: {json.dumps({'stage': 'processing', 'message': f'Processing fight {idx}/{len(all_fights_deduped)} - {total_deaths} deaths found'})}\n\n"
                
                rid = fight_data['reportId']
                fight = fight_data['fight']
                boss_name = fight_data['boss_name']
                boss_id = fight_data['boss_id']
                is_kill = fight_data['is_kill']
                report_abs_start = fight_data['report_abs_start']
                friendlies = fight_data['friendlies']
                
                pull_counter_by_boss[boss_id] += 1
                seq_no = pull_counter_by_boss[boss_id]
                fid = fight['id']
                
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
                
                deaths = report_deaths_cache[rid].get(fid, [])
                deaths_sorted = sorted(deaths, key=lambda e: e["timestamp"])[:max_cutoff]
                
                for rank, ev in enumerate(deaths_sorted, start=1):
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
                        "rankWithinPull": rank,
                        "absTs": report_abs_start + ev["timestamp"],
                        "abilityName": ev.get("abilityName", "Unknown")
                    }
                    counted_death_events[main_char].append(death_event)
                    character_breakdown[main_char][original_char].append(death_event)
                    total_deaths += 1
            
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
                    "guildName": guild_name,
                    "server": server,
                    "region": region
                },
                "events": counted_death_events,
                "pullParticipation": pull_participation_json,
                "bossParticipation": boss_participation_json,
                "characterBreakdown": character_breakdown_json,
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
        
        # Generate a unique ID
        share_id = str(uuid.uuid4())[:8]
        
        # Save the results
        filepath = os.path.join(SHARED_RESULTS_DIR, f"{share_id}.json")
        with open(filepath, 'w') as f:
            json.dump({
                'data': payload.get('data'),
                'config': payload.get('config'),
                'timestamp': datetime.now().isoformat()
            }, f)
        
        return jsonify({
            'success': True,
            'shareId': share_id
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/shared/<share_id>', methods=['GET'])
def get_shared_results(share_id):
    """Retrieve shared results by ID"""
    try:
        filepath = os.path.join(SHARED_RESULTS_DIR, f"{share_id}.json")
        
        if not os.path.exists(filepath):
            return jsonify({
                'success': False,
                'error': 'Shared results not found'
            }), 404
        
        with open(filepath, 'r') as f:
            shared_data = json.load(f)
        
        return jsonify({
            'success': True,
            'data': shared_data.get('data'),
            'config': shared_data.get('config'),
            'timestamp': shared_data.get('timestamp')
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/health', methods=['GET'])
def health():
    """Health check endpoint"""
    return jsonify({"status": "ok", "message": "WarcraftLogs API is running"})


@app.route('/', methods=['GET'])
def root():
    """Root endpoint"""
    return jsonify({
        "service": "WarcraftLogs Death Tracker API",
        "version": "2.4",
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
    print(f"Starting WarcraftLogs Death Tracker API v2.4 on port {port}...")
    app.run(debug=False, host='0.0.0.0', port=port)