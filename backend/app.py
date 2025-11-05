#!/usr/bin/env python3
"""
Flask API for WarcraftLogs Death Tracker - V2 GraphQL API
Optimized for Render.com deployment
Version 2.5 - Fixed pull-centric cheat death filtering
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
            print("Warning: No guild members found. Proceeding without roster filter.")
        else:
            print(f"Total guild roster size: {len(all_members)} members")
        
        return all_members
    except Exception as e:
        print(f"Warning: Failed to fetch guild roster: {str(e)}")
        return set()


def get_report_fights(token, report_id, fight_zone):
    """Fetch fights from a report using V2 GraphQL"""
    
    query = """
    query($code: String!) {
      reportData {
        report(code: $code) {
          startTime
          fights {
            id
            name
            encounterID
            startTime
            endTime
            difficulty
            kill
            friendlyPlayers
          }
          masterData {
            actors(type: "player") {
              id
              name
              subType
            }
          }
        }
      }
    }
    """
    
    variables = {"code": report_id}
    
    try:
        data = graphql_query(token, query, variables)
        report = data.get("reportData", {}).get("report", {})
        
        if not report:
            return None, None
        
        fights = report.get("fights", [])
        actors = report.get("masterData", {}).get("actors", [])
        report_abs_start = report.get("startTime", 0)
        
        # Filter fights by zone
        filtered_fights = [
            f for f in fights 
            if f.get("encounterID") is not None 
            and str(f["encounterID"]) in fight_zone.split(',')
        ]
        
        return filtered_fights, actors, report_abs_start
    except Exception as e:
        raise Exception(f"Failed to fetch fights for report {report_id}: {str(e)}")


def get_deaths_for_fight_bulk(token, report_id, fight_ids, enable_cheat_death=False):
    """
    Fetch deaths for multiple fights in a single query.
    Returns a dict: {fight_id: [death_events]}
    Each death event has: {timestamp, targetID, targetName, abilityName, isCheatDeath}
    """
    
    if not fight_ids:
        return {}
    
    # Build multiple fight queries
    fight_queries = []
    for idx, fid in enumerate(fight_ids):
        fight_queries.append(f"""
        fight{idx}: events(
          fightIDs: [{fid}],
          dataType: Deaths,
          useActorIDs: true
        ) {{
          data
        }}
        """)
    
    # Add cheat death query if enabled (from Debuffs table)
    cheat_queries = []
    if enable_cheat_death:
        for idx, fid in enumerate(fight_ids):
            ability_list = ", ".join(str(aid) for aid in CHEAT_DEATH_ABILITY_IDS)
            cheat_queries.append(f"""
            cheat{idx}: table(
              fightIDs: [{fid}],
              dataType: Debuffs,
              abilityID: [{ability_list}]
            )
            """)
    
    query = f"""
    query {{
      reportData {{
        report(code: "{report_id}") {{
          {chr(10).join(fight_queries)}
          {chr(10).join(cheat_queries) if cheat_queries else ""}
        }}
      }}
    }}
    """
    
    try:
        data = graphql_query(token, query)
        report = data.get("reportData", {}).get("report", {})
        
        result = {}
        
        # Parse real deaths
        for idx, fid in enumerate(fight_ids):
            deaths_data = report.get(f"fight{idx}", {}).get("data", [])
            death_events = []
            
            for ev in deaths_data:
                death_events.append({
                    "timestamp": ev.get("timestamp", 0),
                    "targetID": ev.get("targetID"),
                    "targetName": ev.get("targetName", "Unknown"),
                    "abilityName": ev.get("ability", {}).get("name", "Unknown"),
                    "phase": ev.get("fight", 1),
                    "isCheatDeath": False
                })
            
            result[fid] = death_events
        
        # Parse cheat deaths if enabled
        if enable_cheat_death:
            for idx, fid in enumerate(fight_ids):
                cheat_table = report.get(f"cheat{idx}")
                if not cheat_table:
                    continue
                
                # WCL table format: {totalTime, entries: [{id, icon, name, guid, type, abilityIcon, ...}], auras: [{...}]}
                auras = cheat_table.get("auras", [])
                
                for aura in auras:
                    ability_id = aura.get("guid")
                    ability_name = aura.get("name", "Unknown")
                    ability_icon = aura.get("icon", "")
                    
                    # Get bands (time windows when this aura was active)
                    bands = aura.get("bands", [])
                    
                    for band in bands:
                        start_time = band.get("startTime")
                        end_time = band.get("endTime")
                        
                        if start_time is None:
                            continue
                        
                        # Use startTime as the cheat death timestamp
                        result[fid].append({
                            "timestamp": start_time,
                            "targetID": None,  # Not provided in Debuffs table
                            "targetName": "Unknown",  # Will be filled from entries if available
                            "abilityName": ability_name,
                            "phase": 1,
                            "isCheatDeath": True,
                            "abilityIcon": ability_icon
                        })
                
                # Try to match cheat deaths to players using the entries
                entries = cheat_table.get("entries", [])
                cheat_deaths = [d for d in result[fid] if d.get("isCheatDeath")]
                
                # Build a map of ability → player names from entries
                for entry in entries:
                    entry_name = entry.get("name")
                    if not entry_name:
                        continue
                    
                    # Find cheat deaths that don't have a player name yet
                    for cheat in cheat_deaths:
                        if cheat["targetName"] == "Unknown":
                            cheat["targetName"] = entry_name
                            break
        
        return result
        
    except Exception as e:
        raise Exception(f"Failed to fetch deaths for fights {fight_ids}: {str(e)}")


def check_report_has_guild_members(token, report_id, guild_roster, min_guild_count=15):
    """
    Check if a report has at least min_guild_count guild members.
    Returns True if it's a guild run, False otherwise.
    """
    if not guild_roster:
        # If we don't have a roster, assume all reports are valid
        return True
    
    try:
        # Fetch the report's master data to get all players
        query = """
        query($code: String!) {
          reportData {
            report(code: $code) {
              masterData {
                actors(type: "player") {
                  name
                }
              }
            }
          }
        }
        """
        
        variables = {"code": report_id}
        data = graphql_query(token, query, variables)
        
        report = data.get("reportData", {}).get("report", {})
        actors = report.get("masterData", {}).get("actors", [])
        
        # Count how many players are in the guild
        guild_count = 0
        for actor in actors:
            name = actor.get("name", "").lower()
            if name in guild_roster:
                guild_count += 1
        
        return guild_count >= min_guild_count
        
    except Exception as e:
        print(f"Warning: Could not check guild members for report {report_id}: {str(e)}")
        return True  # Allow the report on error


def calculate_iou(event1, event2, window=5000):
    """Calculate Intersection over Union for two death events"""
    t1_start = event1["timestamp"]
    t1_end = t1_start + window
    t2_start = event2["timestamp"]
    t2_end = t2_start + window
    
    intersection_start = max(t1_start, t2_start)
    intersection_end = min(t1_end, t2_end)
    intersection = max(0, intersection_end - intersection_start)
    
    union_start = min(t1_start, t2_start)
    union_end = max(t1_end, t2_end)
    union = union_end - union_start
    
    return intersection / union if union > 0 else 0


def find_matching_fight(candidate, known_fights, iou_threshold=0.6):
    """Find if candidate fight matches any known fight"""
    for known in known_fights:
        if candidate["boss_id"] != known["boss_id"]:
            continue
        
        if candidate["is_kill"] != known["is_kill"]:
            continue
        
        if candidate["deaths"]:
            for c_death in candidate["deaths"]:
                for k_death in known["deaths"]:
                    if c_death["player"] == k_death["player"]:
                        iou = calculate_iou(c_death, k_death)
                        if iou >= iou_threshold:
                            return known
    
    return None


@app.route('/api/analyze', methods=['POST', 'OPTIONS'])
def analyze():
    """Main analysis endpoint with Server-Sent Events for real-time progress"""
    
    if request.method == 'OPTIONS':
        response = Response()
        response.headers['Access-Control-Allow-Origin'] = '*'
        response.headers['Access-Control-Allow-Methods'] = 'POST, OPTIONS'
        response.headers['Access-Control-Allow-Headers'] = 'Content-Type'
        return response
    
    # Extract payload BEFORE the generator function to avoid request context issues
    payload = request.get_json()
    
    def generate():
        try:
            # Use the payload from the outer scope
            client_id = payload.get("clientId", "").strip()
            client_secret = payload.get("clientSecret", "").strip()
            guild_name = payload.get("guildName", "").strip()
            server = payload.get("server", "").strip()
            region = payload.get("region", "us").strip()
            report_zone = payload.get("reportZone", "44").strip()
            fight_zone = payload.get("fightZone", "2810").strip()
            difficulty = int(payload.get("difficulty", 5))
            max_cutoff = int(payload.get("maxCutoff", 5))
            cutoff_date = payload.get("cutoffDate", "2025-10-10").strip()
            author_filters = payload.get("authorFilters", [])
            character_groups = payload.get("characterGroups", {})
            enable_cheat_death = payload.get("enableCheatDeath", False)
            
            yield f"data: {json.dumps({'stage': 'auth', 'message': 'Authenticating with WarcraftLogs...'})}\n\n"
            token = get_access_token(client_id, client_secret)
            
            yield f"data: {json.dumps({'stage': 'roster', 'message': 'Fetching guild roster...'})}\n\n"
            guild_roster = get_guild_roster(token, guild_name, server, region)
            
            yield f"data: {json.dumps({'stage': 'reports', 'message': 'Fetching guild reports...'})}\n\n"
            reports = get_guild_reports(token, guild_name, server, region, report_zone, cutoff_date)
            
            if author_filters:
                reports = [r for r in reports if r["owner"] in author_filters]
            
            # Filter reports to only include those with 15+ guild members
            yield f"data: {json.dumps({'stage': 'filtering', 'message': f'Filtering {len(reports)} reports for guild runs...'})}\n\n"
            guild_reports = []
            for idx, rep in enumerate(reports, 1):
                if idx % 5 == 0:
                    yield f"data: {json.dumps({'stage': 'filtering', 'message': f'Checking report {idx}/{len(reports)}...'})}\n\n"
                
                if check_report_has_guild_members(token, rep["id"], guild_roster):
                    guild_reports.append(rep)
            
            reports = guild_reports
            yield f"data: {json.dumps({'stage': 'filtering', 'message': f'Found {len(reports)} guild reports'})}\n\n"
            
            if not reports:
                yield f"data: {json.dumps({'error': 'No reports found matching the criteria'})}\n\n"
                return
            
            yield f"data: {json.dumps({'stage': 'fights', 'message': f'Fetching fights from {len(reports)} reports...'})}\n\n"
            
            all_fights = []
            for idx, rep in enumerate(reports, 1):
                if idx % 3 == 0:
                    yield f"data: {json.dumps({'stage': 'fights', 'message': f'Processing report {idx}/{len(reports)}'})}\n\n"
                
                try:
                    fights, friendlies, report_abs_start = get_report_fights(token, rep["id"], fight_zone)
                    if not fights:
                        continue
                    
                    for fight in fights:
                        if fight.get("difficulty") != difficulty:
                            continue
                        
                        all_fights.append({
                            "reportId": rep["id"],
                            "fight": fight,
                            "boss_name": fight.get("name", "Unknown"),
                            "boss_id": fight.get("encounterID"),
                            "is_kill": fight.get("kill", False),
                            "friendlies": friendlies,
                            "report_abs_start": report_abs_start
                        })
                
                except Exception as e:
                    print(f"Error fetching fights from report {rep['id']}: {str(e)}")
                    continue
            
            yield f"data: {json.dumps({'stage': 'deaths', 'message': f'Fetching death events from {len(all_fights)} fights...'})}\n\n"
            
            # Fetch deaths in bulk (group by report)
            report_deaths_cache = {}
            fights_by_report = defaultdict(list)
            for fight_data in all_fights:
                fights_by_report[fight_data["reportId"]].append(fight_data["fight"]["id"])
            
            for idx, (rid, fight_ids) in enumerate(fights_by_report.items(), 1):
                if idx % 2 == 0:
                    yield f"data: {json.dumps({'stage': 'deaths', 'message': f'Fetching deaths from report {idx}/{len(fights_by_report)}'})}\n\n"
                
                try:
                    deaths_dict = get_deaths_for_fight_bulk(token, rid, fight_ids, enable_cheat_death)
                    report_deaths_cache[rid] = deaths_dict
                except Exception as e:
                    print(f"Error fetching deaths from report {rid}: {str(e)}")
                    report_deaths_cache[rid] = {}
            
            if enable_cheat_death:
                yield f"data: {json.dumps({'stage': 'deaths', 'message': f'Cheat death detection enabled - processing {len(all_fights)} fights'})}\n\n"
            
            yield f"data: {json.dumps({'stage': 'dedup', 'message': 'Removing duplicate pulls from multiple loggers...'})}\n\n"
            
            # Build candidates with death patterns
            candidates = []
            for fight_data in all_fights:
                rid = fight_data["reportId"]
                fid = fight_data["fight"]["id"]
                deaths = report_deaths_cache[rid].get(fid, [])
                
                death_patterns = []
                for d in deaths:
                    player_name = d.get("targetName", "Unknown")
                    main_char = get_main_character(player_name, character_groups)
                    death_patterns.append({
                        "player": main_char,
                        "timestamp": d["timestamp"],
                        "isCheatDeath": d.get("isCheatDeath", False)
                    })
                
                candidates.append({
                    "reportId": rid,
                    "fight": fight_data["fight"],
                    "boss_name": fight_data["boss_name"],
                    "boss_id": fight_data["boss_id"],
                    "is_kill": fight_data["is_kill"],
                    "friendlies": fight_data["friendlies"],
                    "report_abs_start": fight_data["report_abs_start"],
                    "deaths": death_patterns
                })
            
            # Deduplicate
            unique_fights = []
            for candidate in candidates:
                existing = find_matching_fight(candidate, unique_fights)
                if existing:
                    # Update existing with more deaths if candidate has more
                    if len(candidate["deaths"]) > len(existing["deaths"]):
                        existing.update(candidate)
                else:
                    unique_fights.append(candidate)
            
            all_fights_deduped = unique_fights
            
            yield f"data: {json.dumps({'stage': 'processing', 'message': f'Processing {len(all_fights_deduped)} unique fights...'})}\n\n"
            
            # Process death events
            counted_death_events = defaultdict(list)
            pull_participation = defaultdict(set)
            boss_participation = defaultdict(lambda: defaultdict(set))
            character_breakdown = defaultdict(lambda: defaultdict(list))
            pull_counter_by_boss = defaultdict(int)
            
            # NEW: Store global cutoff timestamps for each pull (for frontend filtering)
            pull_cutoff_timestamps = {}
            
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
                pull_key = f"{rid}_{fid}"
                
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
                    pull_participation[main_char].add(pull_key)
                    boss_participation[boss_name][main_char].add(pull_key)
                
                # Get all deaths for this fight
                deaths = report_deaths_cache[rid].get(fid, [])
                deaths_sorted_all = sorted(deaths, key=lambda e: e["timestamp"])
                deaths_sorted = deaths_sorted_all[:max_cutoff * 3]
                
                # Calculate global cutoff timestamps for different cutoff values
                # This is the key fix: we calculate GLOBAL Xth death timestamps per pull
                real_deaths_sorted = sorted([d for d in deaths_sorted if not d.get("isCheatDeath", False)], 
                                           key=lambda e: e["timestamp"])
                
                # Detect mass death windows (7+ deaths within 10 seconds)
                def is_in_mass_death(death_index, deaths_list):
                    """Check if a death at given index is part of a mass death event"""
                    if death_index >= len(deaths_list):
                        return False
                    
                    death_ts = deaths_list[death_index]["timestamp"]
                    
                    # Count deaths within MASS_DEATH_WINDOW of this death
                    deaths_in_window = 0
                    for d in deaths_list:
                        if abs(d["timestamp"] - death_ts) <= MASS_DEATH_WINDOW:
                            deaths_in_window += 1
                    
                    return deaths_in_window >= MASS_DEATH_THRESHOLD
                
                def find_mass_death_start(cutoff_idx, deaths_list):
                    """Find the timestamp where the mass death window starts"""
                    if cutoff_idx >= len(deaths_list):
                        return None
                    
                    cutoff_death_ts = deaths_list[cutoff_idx]["timestamp"]
                    
                    # Work backwards to find the FIRST death in the mass death window
                    # (earliest death that's within MASS_DEATH_WINDOW of our cutoff death)
                    mass_death_start_idx = cutoff_idx
                    for i in range(cutoff_idx - 1, -1, -1):
                        if cutoff_death_ts - deaths_list[i]["timestamp"] <= MASS_DEATH_WINDOW:
                            mass_death_start_idx = i
                        else:
                            break
                    
                    # Return the timestamp where mass death starts (first death in the window)
                    return deaths_list[mass_death_start_idx]["timestamp"]
                
                cutoff_timestamps = {}
                for cutoff_val in range(1, max_cutoff + 1):
                    if len(real_deaths_sorted) >= cutoff_val:
                        cutoff_idx = cutoff_val - 1  # 0-indexed
                        
                        # Check if the Xth death is part of a mass death
                        if is_in_mass_death(cutoff_idx, real_deaths_sorted):
                            # Use the START of the mass death window (not last death before it)
                            # This includes cheat deaths before the wipe started
                            cutoff_timestamps[cutoff_val] = find_mass_death_start(cutoff_idx, real_deaths_sorted)
                        else:
                            # Normal case: use the Xth death timestamp
                            cutoff_timestamps[cutoff_val] = real_deaths_sorted[cutoff_idx]["timestamp"]
                    else:
                        # If fewer than cutoff_val deaths, use the last death's timestamp
                        if real_deaths_sorted:
                            cutoff_timestamps[cutoff_val] = real_deaths_sorted[-1]["timestamp"]
                        else:
                            cutoff_timestamps[cutoff_val] = None
                
                pull_cutoff_timestamps[pull_key] = cutoff_timestamps
                
                # Assign ranks to each death event
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
                        "pullKey": pull_key,
                        "isKill": is_kill,
                        "pullNo": seq_no,
                        "rankWithinPull": real_death_rank,
                        "rankWithinPullTotal": total_death_rank,
                        "absTs": report_abs_start + ev["timestamp"],
                        "timestamp": ev["timestamp"],  # Relative timestamp within fight
                        "abilityName": ev.get("abilityName", "Unknown"),
                        "isCheatDeath": is_cheat
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
                },
                "events": counted_death_events,
                "pullParticipation": pull_participation_json,
                "bossParticipation": boss_participation_json,
                "characterBreakdown": character_breakdown_json,
                "pullCutoffTimestamps": pull_cutoff_timestamps,  # NEW: Global cutoff timestamps
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
        "version": "2.5",
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
    print(f"Starting WarcraftLogs Death Tracker API v2.5 on port {port}...")
    app.run(debug=False, host='0.0.0.0', port=port)