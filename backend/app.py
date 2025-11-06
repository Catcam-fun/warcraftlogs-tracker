#!/usr/bin/env python3
"""
Flask API for WarcraftLogs Death Tracker - V2 GraphQL API
Optimized for Render.com deployment
Version 2.3 - Real-time progress updates via SSE
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

# Configure CORS - simplest approach, allow everything
CORS(app)

# Constants
MASS_DEATH_THRESHOLD = 7
MASS_DEATH_WINDOW = 10000  # ms

# Cheat Death Abilities - abilities that prevent actual death
CHEAT_DEATH_ABILITY_IDS = {
    45181,    # Cheated Death (Rogue)
    87024,    # Cauterize (Mage - Fire)
    123981,   # Purgatory (Death Knight)
    211319,   # Spirit of Redemption/Restitution (Holy Priest)
    404369,   # Empty Hourglass
    1236692,  # Void Reconstitution
    209261,   # Last Resort (Demon Hunter - Vengeance)
}

# WarcraftLogs V2 API endpoints (through Cloudflare Worker proxy)
GRAPHQL_ENDPOINT = "https://wcl-proxy.catcam-fun.workers.dev/api/v2/client"
OAUTH_TOKEN_URL = "https://wcl-proxy.catcam-fun.workers.dev/oauth/token"

# OAuth2 token cache
_token_cache = {"token": None, "expires_at": 0}


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


def get_guild_roster(token, guild_name, server, region):
    """Fetch guild roster to identify guild members using pagination"""
    
    query = """
    query($guildName: String!, $serverSlug: String!, $serverRegion: String!, $page: Int!) {
      guildData {
        guild(name: $guildName, serverSlug: $serverSlug, serverRegion: $serverRegion) {
          members(limit: 100, page: $page) {
            data {
              name
            }
            has_more_pages
          }
        }
      }
    }
    """
    
    all_members = set()
    page = 1
    max_pages = 10  # Max 10 pages = 1000 members (safety limit)
    
    try:
        while page <= max_pages:
            variables = {
                "guildName": guild_name,
                "serverSlug": server.lower().replace(" ", "-").replace("'", ""),
                "serverRegion": region.upper(),
                "page": page
            }
            
            data = graphql_query(token, query, variables)
            guild = data.get("guildData", {}).get("guild", {})
            
            if not guild:
                if page == 1:
                    print(f"Warning: Could not fetch guild roster for {guild_name}")
                break
            
            members_response = guild.get("members", {})
            members = members_response.get("data", [])
            has_more = members_response.get("has_more_pages", False)
            
            # Add members from this page
            for member in members:
                name = member.get("name")
                if name:
                    all_members.add(name.lower())
            
            print(f"Fetched page {page}: {len(members)} members (total so far: {len(all_members)})")
            
            # Stop if no more pages
            if not has_more:
                break
            
            page += 1
        
        if not all_members:
            print(f"Warning: Guild {guild_name} has no members or roster not available")
            return set()
        
        print(f"Successfully fetched {len(all_members)} guild members across {page} page(s)")
        return all_members
        
    except Exception as e:
        print(f"Warning: Failed to fetch guild roster: {str(e)}")
        return set()



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
                "zoneID": fight.get("gameZone", {}).get("id") if fight.get("gameZone") else None,
                "friendlyPlayers": fight.get("friendlyPlayers", [])  # IDs of players in THIS fight
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
        
        print(f"Formatted {len(formatted_friendlies)} friendly players")
        if len(formatted_friendlies) > 0:
            print(f"Sample player: {formatted_friendlies[0]}")
        
        return {
            "report_start": report_start,
            "fights": formatted_fights,
            "friendlies": formatted_friendlies
        }
    except Exception as e:
        print(f"Error fetching fights for {report_code}: {e}")
        return {"report_start": 0, "fights": [], "friendlies": []}


def get_abilities_map(token, report_code):
    """Get ability ID to name mapping for a report - ONCE per report"""
    abilities_query = """
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
    
    ability_id_to_name = {}
    try:
        abilities_data = graphql_query(token, abilities_query, {"code": report_code})
        abilities = abilities_data.get("reportData", {}).get("report", {}).get("masterData", {}).get("abilities", [])
        for ability in abilities:
            ability_id = ability.get("gameID")
            ability_name = ability.get("name")
            if ability_id and ability_name:
                ability_id_to_name[ability_id] = ability_name
        print(f"Loaded {len(ability_id_to_name)} abilities for report {report_code}")
    except Exception as e:
        print(f"Warning: Could not fetch ability names: {e}")
    
    return ability_id_to_name


def get_report_deaths_bulk(token, report_code, fights, friendlies, ability_map, enable_cheat_death=False):
    """
    Get ALL player deaths for an entire report at once - MUCH faster than per-fight queries
    Optionally detect cheat deaths in the SAME query using GraphQL aliases
    
    OPTIMIZATION STRATEGY:
    - 1 API call per report gets both deaths AND debuffs (if cheat death enabled)
    - Uses GraphQL aliases to fetch multiple event types simultaneously
    - Uses filterExpression for debuffs to avoid hitting 10k event limit
    - This is ~100x faster than querying each fight individually
    
    For 35 reports with cheat death enabled: ~35 API calls total (1 per report, down from 70!)
    """
    
    if not fights:
        return {}
    
    # Build actor ID -> name lookup from friendlies
    actor_id_to_name = {}
    for friendly in friendlies:
        actor_id = friendly.get('id')
        name = friendly.get('name')
        if actor_id and name:
            actor_id_to_name[actor_id] = name
    
    # Get the time range for ALL fights we care about
    start_time = min(f['start_time'] for f in fights)
    end_time = max(f['end_time'] for f in fights)
    
    # Build query that gets BOTH deaths and debuffs in a single API call
    # Use GraphQL aliases to fetch multiple event types at once
    cheat_death_ids = ", ".join(str(id) for id in CHEAT_DEATH_ABILITY_IDS)
    filter_expr = f"ability.id in ({cheat_death_ids})"
    
    if enable_cheat_death:
        print(f"⚡ Cheat death detection ENABLED - querying deaths AND debuffs in one call...")
        # Combined query: deaths + filtered debuffs (cheat deaths)
        combined_query = """
        query($code: String!, $startTime: Float!, $endTime: Float!, $filterExpression: String) {
          reportData {
            report(code: $code) {
              deaths: events(
                startTime: $startTime
                endTime: $endTime
                dataType: Deaths
                limit: 10000
              ) {
                data
              }
              debuffs: events(
                startTime: $startTime
                endTime: $endTime
                dataType: Debuffs
                filterExpression: $filterExpression
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
            "startTime": start_time,
            "endTime": end_time,
            "filterExpression": filter_expr
        }
    else:
        # Just deaths (no cheat death detection)
        combined_query = """
        query($code: String!, $startTime: Float!, $endTime: Float!) {
          reportData {
            report(code: $code) {
              deaths: events(
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
            "startTime": start_time,
            "endTime": end_time
        }
    
    try:
        # Single API call gets both deaths and debuffs (if enabled)
        combined_data = graphql_query(token, combined_query, variables)
        report_data = combined_data.get("reportData", {}).get("report", {})
        
        # Extract death events
        events_data = report_data.get("deaths", {}).get("data", [])
        
        # Build a map of fightId -> list of deaths
        deaths_by_fight = {f['id']: [] for f in fights}
        
        # Extract debuff events (if cheat death enabled)
        cheat_death_events = []
        if enable_cheat_death:
            debuff_events = report_data.get("debuffs", {}).get("data", [])
            
            print(f"  Found {len(debuff_events)} cheat death debuff events (filtered query)")
            
            # DEBUG: Show which cheat death IDs were found
            unique_debuff_abilities = {}
            for event in debuff_events:
                ability_id = event.get("abilityGameID")
                if ability_id not in unique_debuff_abilities:
                    unique_debuff_abilities[ability_id] = 0
                unique_debuff_abilities[ability_id] += 1
            
            if unique_debuff_abilities:
                print(f"  DEBUG: Found cheat death ability IDs:")
                for ability_id, count in sorted(unique_debuff_abilities.items()):
                    ability_name = ability_map.get(ability_id, "Unknown")
                    print(f"    - {ability_id} ({ability_name}): {count} occurrences")
            else:
                print(f"  DEBUG: No cheat death debuffs found in this report")
            
            # Process debuff events - each applydebuff is a cheat death
            # Only track when the debuff is APPLIED (when cheat death procs)
            for event in debuff_events:
                ability_id = event.get("abilityGameID")
                event_type = event.get("type")
                
                if event_type == "applydebuff":
                    target_id = event.get("targetID")
                    timestamp = event.get("timestamp")
                    fight_id = event.get("fight")
                    target_name = actor_id_to_name.get(target_id, "Unknown")
                    ability_name = ability_map.get(ability_id, "Unknown")
                    
                    if target_id and timestamp and fight_id in deaths_by_fight:
                        cheat_death_events.append({
                            "timestamp": timestamp,
                            "targetName": target_name,
                            "targetID": target_id,
                            "fightId": fight_id,
                            "abilityGameID": ability_id,
                            "abilityName": ability_name,
                            "isCheatDeath": True
                        })
            
            print(f"  Found {len(cheat_death_events)} cheat death events to add")
        else:
            print(f"💨 Cheat death detection DISABLED - skipping debuff queries (faster)")
        
        # STEP 3: Process regular death events
        for event in events_data:
            if event.get("type") != "death":
                continue
            
            event_timestamp = event.get("timestamp", 0)
            fight_id = event.get("fight")
            
            # Find which fight this death belongs to
            if fight_id not in deaths_by_fight:
                continue
            
            # V2 API returns targetID, not target.name
            target_id = event.get("targetID")
            target_name = actor_id_to_name.get(target_id, "Unknown")
            
            # Get ability name from killingAbilityGameID using the pre-loaded map
            killing_ability_id = event.get("killingAbilityGameID")
            ability_name = ability_map.get(killing_ability_id, "Unknown")
            
            # Find the fight object to get its name
            fight_obj = next((f for f in fights if f['id'] == fight_id), None)
            
            deaths_by_fight[fight_id].append({
                "timestamp": event_timestamp,
                "targetName": target_name,
                "targetID": target_id,
                "phase": 1,
                "fightId": fight_id,
                "bossName": fight_obj.get('name', 'Unknown') if fight_obj else 'Unknown',
                "abilityName": ability_name,
                "isCheatDeath": False,
            })
        
        # STEP 4: Add cheat death events to the appropriate fights
        for cheat_event in cheat_death_events:
            fight_id = cheat_event["fightId"]
            if fight_id in deaths_by_fight:
                # Find the fight object to get its name
                fight_obj = next((f for f in fights if f['id'] == fight_id), None)
                
                deaths_by_fight[fight_id].append({
                    "timestamp": cheat_event["timestamp"],
                    "targetName": cheat_event["targetName"],
                    "targetID": cheat_event["targetID"],
                    "phase": 1,
                    "fightId": fight_id,
                    "bossName": fight_obj.get('name', 'Unknown') if fight_obj else 'Unknown',
                    "abilityName": cheat_event["abilityName"],
                    "isCheatDeath": True,
                })
        
        if enable_cheat_death:
            total_deaths = sum(len(deaths) for deaths in deaths_by_fight.values())
            real_deaths = sum(1 for fight_deaths in deaths_by_fight.values() for d in fight_deaths if not d.get("isCheatDeath", False))
            cheat_deaths = total_deaths - real_deaths
            print(f"  Death Summary:")
            print(f"    - Total death events: {total_deaths}")
            print(f"    - Real deaths: {real_deaths}")
            print(f"    - Cheat deaths: {cheat_deaths}")
        
        # DO NOT filter mass deaths here - the new cutoff timestamp approach handles wipes correctly
        # The old filter_mass_deaths logic was removing ALL deaths from wipes, causing missing data
        # Now we detect mass deaths and adjust the cutoff timestamp instead
        
        return deaths_by_fight
    
    except Exception as e:
        print(f"Error fetching deaths for report: {e}")
        return {f['id']: [] for f in fights}


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


def is_in_mass_death(death_index, deaths_list):
    """
    Check if a death at the given index is part of a mass death event.
    Returns: (bool, start_timestamp or None)
    - If the death is in a mass death, returns (True, timestamp_of_mass_death_start)
    - Otherwise returns (False, None)
    """
    if len(deaths_list) < MASS_DEATH_THRESHOLD:
        return False, None
    
    # Count deaths within 10 seconds of this death (both before and after)
    death_ts = deaths_list[death_index]["timestamp"]
    
    # Look for a window that contains this death and has 7+ deaths total
    # We need to find if there's ANY window containing this death that qualifies as mass death
    for i in range(len(deaths_list)):
        window_start_ts = deaths_list[i]["timestamp"]
        window_end_ts = window_start_ts + MASS_DEATH_WINDOW
        
        # Check if our death falls within this window
        if death_ts < window_start_ts or death_ts > window_end_ts:
            continue
        
        # Count how many deaths are in this window
        deaths_in_window = sum(
            1 for j in range(len(deaths_list))
            if window_start_ts <= deaths_list[j]["timestamp"] <= window_end_ts
        )
        
        # If this window qualifies as a mass death, return the start timestamp
        if deaths_in_window >= MASS_DEATH_THRESHOLD:
            return True, window_start_ts
    
    return False, None


def find_mass_death_start(cutoff_idx, deaths_list):
    """
    Find the start timestamp of the mass death window that contains the death at cutoff_idx.
    Returns a timestamp BEFORE the first death in the mass death sequence.
    This ensures that all deaths in the mass wipe are excluded when using <= comparison.
    """
    in_mass, start_ts = is_in_mass_death(cutoff_idx, deaths_list)
    if in_mass:
        # Return timestamp 1ms before the first death in the wipe
        # This ensures all wipe deaths are excluded with <= comparison
        return max(0, start_ts - 1)
    return None


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
            cutoff_date = config.get('cutoffDate')
            author_filters = config.get('authorFilters', [])
            character_groups = config.get('characterGroups', {})
            enable_cheat_death = config.get('enableCheatDeath', False)  # Optional cheat death detection
            
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
            reports = get_guild_reports(token, guild_name, server, region, report_zone, cutoff_date)
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
                
                report_deaths_cache[rid] = get_report_deaths_bulk(token, rid, fights_list, friendlies, ability_map, enable_cheat_death)
            
            yield f"data: {json.dumps({'stage': 'processing', 'message': f'Processing {len(all_fights_deduped)} fights...'})}\n\n"
            
            total_deaths = 0
            pullCutoffTimestamps = {}  # Store cutoff timestamps for each pull
            
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
                
                # Get all deaths for this fight (real + cheat if enabled)
                deaths = report_deaths_cache[rid].get(fid, [])
                deaths_sorted_all = sorted(deaths, key=lambda e: e["timestamp"])
                
                # Don't limit deaths artificially - send all deaths
                # The frontend will filter based on rankWithinPull and pullCutoffTimestamps
                deaths_sorted = deaths_sorted_all
                
                # DEBUG: Log if fight has many deaths
                if len(deaths_sorted_all) > 15:
                    print(f"  ⚠️ Fight {fid} ({boss_name}) has {len(deaths_sorted_all)} deaths (sending all)")
                
                # Assign TWO ranks to each death event:
                # 1. rankWithinPull - rank among REAL deaths only (ignoring cheat deaths)
                # 2. rankWithinPullTotal - rank among ALL deaths (including cheat deaths)
                real_death_rank = 0
                total_death_rank = 0
                
                for ev in deaths_sorted:
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
                        "rankWithinPull": real_death_rank,  # Rank among real deaths only
                        "rankWithinPullTotal": total_death_rank,  # Rank among all deaths
                        "absTs": report_abs_start + ev["timestamp"],
                        "timestamp": ev["timestamp"] - fight['start_time'],  # Make relative to fight start (for cutoff comparison)
                        "abilityName": ev.get("abilityName", "Unknown"),
                        "isCheatDeath": is_cheat
                    }
                    counted_death_events[main_char].append(death_event)
                    character_breakdown[main_char][original_char].append(death_event)
                    total_deaths += 1
                
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
        
        # Generate a unique ID
        share_id = str(uuid.uuid4())[:8]
        
        # Create shared_results directory if it doesn't exist
        shared_dir = os.path.join(os.path.dirname(__file__), 'shared_results')
        os.makedirs(shared_dir, exist_ok=True)
        
        # Save the results
        filepath = os.path.join(shared_dir, f"{share_id}.json")
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
        shared_dir = os.path.join(os.path.dirname(__file__), 'shared_results')
        filepath = os.path.join(shared_dir, f"{share_id}.json")
        
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