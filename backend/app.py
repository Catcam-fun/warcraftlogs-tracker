#!/usr/bin/env python3
"""
Flask API for WarcraftLogs Death Tracker - V2 GraphQL API
Optimized for Render.com deployment
"""

from flask import Flask, request, jsonify
from flask_cors import CORS
import requests
from collections import defaultdict
from datetime import datetime
import time
import os

app = Flask(__name__)

# Configure CORS for production
CORS(app, resources={
    r"/api/*": {
        "origins": ["*"],  # In production, replace with your frontend URL
        "methods": ["GET", "POST", "OPTIONS"],
        "allow_headers": ["Content-Type", "Authorization"]
    }
})

# Constants
MASS_DEATH_THRESHOLD = 7
MASS_DEATH_WINDOW = 10000  # ms
GRAPHQL_ENDPOINT = "https://www.warcraftlogs.com/api/v2/client"

# OAuth2 token cache
_token_cache = {"token": None, "expires_at": 0}


def get_access_token(client_id, client_secret):
    """Get OAuth2 access token for V2 API"""
    global _token_cache
    
    # Check if we have a valid cached token
    if _token_cache["token"] and time.time() < _token_cache["expires_at"]:
        return _token_cache["token"]
    
    # Request new token
    url = "https://www.warcraftlogs.com/oauth/token"
    data = {
        "grant_type": "client_credentials",
        "client_id": client_id,
        "client_secret": client_secret
    }
    
    try:
        response = requests.post(url, data=data, timeout=30)
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
        reports(guildName: $guildName, guildServerSlug: $serverSlug, guildServerRegion: $serverRegion, zoneID: $zoneID, limit: 500) {
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
                "zoneID": fight.get("gameZone", {}).get("id") if fight.get("gameZone") else None,
            })
        
        # Format friendlies
        formatted_friendlies = []
        for actor in actors:
            if actor.get("type") == "Player":
                formatted_friendlies.append({
                    "id": actor.get("id"),
                    "name": actor.get("name"),
                    "type": actor.get("subType")  # Class name
                })
        
        return {
            "report_start": report_start,
            "fights": formatted_fights,
            "friendlies": formatted_friendlies
        }
    except Exception as e:
        print(f"Error fetching fights for {report_code}: {e}")
        return {"report_start": 0, "fights": [], "friendlies": []}


def get_player_deaths(token, report_code, fight):
    """Get player deaths using V2 GraphQL API"""
    
    fid = fight['id']
    start = fight['start_time']
    end = fight['end_time']
    
    query = """
    query($code: String!, $fightIDs: [Int]!, $startTime: Float!, $endTime: Float!) {
      reportData {
        report(code: $code) {
          events(
            fightIDs: $fightIDs
            startTime: $startTime
            endTime: $endTime
            dataType: Deaths
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
        "fightIDs": [fid],
        "startTime": start,
        "endTime": end
    }
    
    try:
        data = graphql_query(token, query, variables)
        events_data = data.get("reportData", {}).get("report", {}).get("events", {}).get("data", [])
        
        deaths = []
        for event in events_data:
            if event.get("type") != "death":
                continue
            
            target = event.get("target", {})
            killing_ability = event.get("killingAbility", {})
            
            deaths.append({
                "timestamp": event.get("timestamp", 0),
                "targetName": target.get("name", "Unknown"),
                "targetID": target.get("id"),
                "phase": 1,  # V2 API doesn't provide phase info in events
                "fightId": fid,
                "bossName": fight.get('name', 'Unknown'),
                "abilityName": killing_ability.get("name", "Unknown"),
            })
        
        return filter_mass_deaths(deaths)
    
    except Exception as e:
        print(f"Error fetching deaths: {e}")
        return []


def analyze_fights(fights, fight_zone, difficulty):
    """Filter fights by zone and difficulty"""
    out = []
    
    for f in fights:
        if (f.get("boss") or 0) <= 0:
            continue
        if f.get("zoneID") != int(fight_zone):
            continue
        if f.get("difficulty") != int(difficulty):
            continue
        out.append(f)
    
    return out


def get_fight_participants(token, report_code, fight):
    """Get participants for a specific fight using V2 GraphQL API"""
    
    fid = fight['id']
    
    query = """
    query($code: String!, $fightIDs: [Int]!) {
      reportData {
        report(code: $code) {
          table(fightIDs: $fightIDs, dataType: DamageDone)
        }
      }
    }
    """
    
    variables = {
        "code": report_code,
        "fightIDs": [fid]
    }
    
    try:
        data = graphql_query(token, query, variables)
        table_data = data.get("reportData", {}).get("report", {}).get("table", {})
        
        participants = set()
        
        # Extract player names from damage done table
        if table_data and "data" in table_data:
            entries = table_data.get("data", {}).get("entries", [])
            for entry in entries:
                name = entry.get("name")
                if name:
                    participants.add(name)
        
        return participants
    except Exception as e:
        print(f"Error getting fight participants: {e}")
        return set()


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


@app.route('/api/analyze', methods=['POST', 'OPTIONS'])
def analyze():
    """Main API endpoint for analyzing WarcraftLogs data using V2 API"""
    
    # Handle preflight CORS
    if request.method == 'OPTIONS':
        return '', 204
    
    try:
        config = request.json
        
        # Extract configuration - V2 uses client_id and client_secret
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
        
        # Validate required fields
        if not all([client_id, client_secret, guild_name, server, region]):
            return jsonify({"error": "Missing required fields (clientId, clientSecret, guildName, server, region)"}), 400
        
        # Get OAuth2 token
        try:
            token = get_access_token(client_id, client_secret)
        except Exception as e:
            return jsonify({"error": f"Authentication failed: {str(e)}"}), 401
        
        # Get guild reports
        reports = get_guild_reports(
            token, guild_name, server, region, 
            report_zone, cutoff_date
        )
        
        # Filter by author if specified
        if author_filters:
            reports = [r for r in reports if r.get('owner') in author_filters]
        
        if not reports:
            return jsonify({"error": "No reports found matching criteria"}), 404
        
        # Collect all fights
        all_fights_raw = []
        
        for rep in reports:
            rid = rep["id"]
            fights_data = get_fights(token, rid)
            fights = fights_data.get("fights", [])
            report_abs_start = fights_data.get("report_start", rep["start"])
            friendlies = fights_data.get("friendlies", [])
            
            if not fights:
                continue
            
            participants = get_raid_participants(friendlies)
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
                    'participants': participants,
                    'friendlies': friendlies
                })
        
        # Sort chronologically
        all_fights_raw.sort(key=lambda x: x['abs_start'])
        
        # Deduplicate
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
        
        # Process pulls and deaths
        counted_death_events = defaultdict(list)
        pull_participation = defaultdict(set)
        boss_participation = defaultdict(lambda: defaultdict(set))
        character_breakdown = defaultdict(lambda: defaultdict(list))
        pull_counter_by_boss = defaultdict(int)
        
        for fight_data in all_fights_deduped:
            rid = fight_data['reportId']
            fight = fight_data['fight']
            boss_name = fight_data['boss_name']
            boss_id = fight_data['boss_id']
            is_kill = fight_data['is_kill']
            report_abs_start = fight_data['report_abs_start']
            participants = fight_data['participants']
            
            pull_counter_by_boss[boss_id] += 1
            seq_no = pull_counter_by_boss[boss_id]
            fid = fight['id']
            
            # Get fight participants
            fight_parts = get_fight_participants(token, rid, fight)
            
            # If no participants found, use all raid members
            if not fight_parts:
                fight_parts = set(participants.values())
            
            # Track participation
            for p in fight_parts:
                main_char = get_main_character(p, character_groups)
                pull_key = f"{rid}_{fid}"
                pull_participation[main_char].add(pull_key)
                boss_participation[boss_name][main_char].add(pull_key)
            
            # Process deaths
            deaths = get_player_deaths(token, rid, fight)
            deaths_sorted = sorted(deaths, key=lambda e: e["timestamp"])[:max_cutoff]
            
            for idx, ev in enumerate(deaths_sorted, start=1):
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
                    "rankWithinPull": idx,
                    "absTs": report_abs_start + ev["timestamp"],
                    "abilityName": ev.get("abilityName", "Unknown")
                }
                counted_death_events[main_char].append(death_event)
                character_breakdown[main_char][original_char].append(death_event)
            
            time.sleep(0.1)  # Rate limiting for GraphQL API
        
        # Convert sets to lists for JSON serialization
        pull_participation_json = {p: list(s) for p, s in pull_participation.items()}
        boss_participation_json = {
            b: {p: list(s2) for p, s2 in players.items()}
            for b, players in boss_participation.items()
        }
        character_breakdown_json = {
            main: {char: evs for char, evs in chars.items()}
            for main, chars in character_breakdown.items()
        }
        
        # Build response
        response = {
            "meta": {
                "maxCutoff": max_cutoff,
                "authorFilters": author_filters,
                "dateCutoff": cutoff_date,
                "zone": fight_zone,
                "difficulty": difficulty,
                "generatedAt": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "characterGroups": character_groups,
            },
            "events": counted_death_events,
            "pullParticipation": pull_participation_json,
            "bossParticipation": boss_participation_json,
            "characterBreakdown": character_breakdown_json,
        }
        
        return jsonify(response)
    
    except Exception as e:
        print(f"Error in analyze: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.route('/api/health', methods=['GET'])
def health():
    """Health check endpoint"""
    return jsonify({"status": "ok", "message": "WarcraftLogs API is running"})


@app.route('/', methods=['GET'])
def root():
    """Root endpoint"""
    return jsonify({
        "service": "WarcraftLogs Death Tracker API",
        "version": "2.0",
        "status": "running",
        "endpoints": {
            "health": "/api/health",
            "analyze": "/api/analyze (POST)"
        }
    })


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    print(f"Starting WarcraftLogs Death Tracker API on port {port}...")
    app.run(debug=False, host='0.0.0.0', port=port)
