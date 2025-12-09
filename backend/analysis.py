"""
analysis.py - Core death analysis logic (no optional features)
Contains: get_report_deaths_bulk, fight analysis helpers, main analysis orchestration
"""

import unicodedata
from datetime import datetime
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed

# Import from other modules
from warcraftlogs import graphql_query, normalize_character_name
from features import (
    CHEAT_DEATH_ABILITY_IDS, ALL_DEFENSIVE_ABILITY_IDS, DEFENSIVE_ABILITY_INFO,
    get_all_healing_for_report_paginated, get_all_defensive_buffs_paginated,
    calculate_defensive_data_from_bulk
)

# =============================================================================
# CONSTANTS
# =============================================================================

MASS_DEATH_THRESHOLD = 7
MASS_DEATH_WINDOW = 10000  # ms

WOW_CLASS_COLORS = {
    "DeathKnight": "#C41E3A", "DemonHunter": "#A330C9", "Druid": "#FF7C0A",
    "Evoker": "#33937F", "Hunter": "#AAD372", "Mage": "#3FC7EB",
    "Monk": "#00FF98", "Paladin": "#F48CBA", "Priest": "#FFFFFF",
    "Rogue": "#FFF468", "Shaman": "#0070DD", "Warlock": "#8788EE",
    "Warrior": "#C69B6D",
}

# =============================================================================
# UTILITY FUNCTIONS
# =============================================================================

def get_main_character(player_name, character_groups):
    """Return main character name for grouped alts."""
    for main, alts in character_groups.items():
        if player_name in alts:
            return main
    return player_name


def get_raid_participants(friendlies):
    """Get normalized participant names."""
    return [normalize_character_name(f["name"]) for f in friendlies]


def interval_overlap(a_start, a_end, b_start, b_end):
    """Calculate interval overlap and intersection-over-union."""
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


# =============================================================================
# MASS DEATH DETECTION
# =============================================================================

def filter_mass_deaths(deaths):
    """Mark deaths during mass death events (wipes)."""
    for i, death in enumerate(deaths):
        in_mass, _ = is_in_mass_death(i, deaths)
        death["isInMassDeath"] = in_mass
    return deaths


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


def analyze_fights(fights, fight_zone, difficulty):
    """Filter fights by zone and difficulty."""
    return [f for f in fights if f.get("boss") and 
            f.get("zoneID") == int(fight_zone) and f.get("difficulty") == int(difficulty)]


# =============================================================================
# CORE DEATH ANALYSIS
# =============================================================================

def get_report_deaths_bulk(token, report_code, fights, friendlies, ability_map, enable_cheat_death=False, enable_defensive_tracking=False):
    """
    Get ALL player deaths for an entire report at once - MUCH faster than per-fight queries
    Optionally detect cheat deaths AND defensive usage in the SAME query using GraphQL aliases
    
    OPTIMIZATION STRATEGY:
    - 1 API call per report gets deaths + debuffs + defensives + healing (all optional)
    - Uses GraphQL aliases to fetch multiple event types simultaneously
    - Uses filterExpression for debuffs/defensives to avoid hitting 10k event limit
    - This is ~100x faster than querying each fight individually
    
    For 35 reports with cheat death + defensive tracking: still just ~35 API calls total!
    """
    
    if not fights:
        return {}
    
    # Build actor ID -> name lookup from friendlies
    actor_id_to_name = {}
    for friendly in friendlies:
        actor_id = friendly.get('id')
        name = friendly.get('name')
        if actor_id and name:
            actor_id_to_name[actor_id] = normalize_character_name(name)
    
    # Get the time range for ALL fights we care about
    start_time = min(f['start_time'] for f in fights)
    end_time = max(f['end_time'] for f in fights)
    
    # Build query that gets deaths + optionally debuffs + optionally defensives/healing
    # Use GraphQL aliases to fetch multiple event types at once
    cheat_death_ids = ", ".join(str(id) for id in CHEAT_DEATH_ABILITY_IDS)
    cheat_filter = f"ability.id in ({cheat_death_ids})"
    
    defensive_ids = ", ".join(str(id) for id in ALL_DEFENSIVE_ABILITY_IDS)
    defensive_filter = f"ability.id in ({defensive_ids})"
    
    # Build query based on what's enabled
    if enable_defensive_tracking and enable_cheat_death:
        print(f"[ENABLED] Cheat death + defensive tracking ENABLED - querying deaths + debuffs + defensives...")
        combined_query = """
        query($code: String!, $startTime: Float!, $endTime: Float!, $cheatFilter: String, $defensiveFilter: String) {
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
                filterExpression: $cheatFilter
                limit: 10000
              ) {
                data
              }
              defensiveCasts: events(
                startTime: $startTime
                endTime: $endTime
                dataType: Casts
                filterExpression: $defensiveFilter
                limit: 10000
              ) {
                data
              }
              defensiveBuffs: events(
                startTime: $startTime
                endTime: $endTime
                dataType: Buffs
                filterExpression: $defensiveFilter
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
            "cheatFilter": cheat_filter,
            "defensiveFilter": defensive_filter
        }
    elif enable_defensive_tracking:
        print(f"[ENABLED] Defensive tracking ENABLED - querying deaths + defensives...")
        combined_query = """
        query($code: String!, $startTime: Float!, $endTime: Float!, $defensiveFilter: String) {
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
              defensiveCasts: events(
                startTime: $startTime
                endTime: $endTime
                dataType: Casts
                filterExpression: $defensiveFilter
                limit: 10000
              ) {
                data
              }
              defensiveBuffs: events(
                startTime: $startTime
                endTime: $endTime
                dataType: Buffs
                filterExpression: $defensiveFilter
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
            "defensiveFilter": defensive_filter
        }
    elif enable_cheat_death:
        print(f"[ENABLED] Cheat death detection ENABLED - querying deaths AND debuffs in one call...")
        combined_query = """
        query($code: String!, $startTime: Float!, $endTime: Float!, $cheatFilter: String) {
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
                filterExpression: $cheatFilter
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
            "cheatFilter": cheat_filter
        }
    else:
        # Just deaths (no cheat death detection or defensive tracking)
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
        
        # DEBUG: Log death event info
        expected_fight_ids = set(deaths_by_fight.keys())
        actual_death_fight_ids = set(e.get("fight") for e in events_data if e.get("type") == "death")
        print(f"  [DEBUG] Raw death events: {len(events_data)}")
        print(f"  [DEBUG] Expected fight IDs (from fights param): {sorted(expected_fight_ids)[:5]}...")
        print(f"  [DEBUG] Actual fight IDs in death events: {sorted(actual_death_fight_ids)[:5]}...")
        matching_fight_ids = expected_fight_ids & actual_death_fight_ids
        print(f"  [DEBUG] Matching fight IDs: {len(matching_fight_ids)} of {len(expected_fight_ids)}")
        
        # Extract defensive events (if defensive tracking enabled)
        defensive_casts = []
        defensive_buffs = []
        if enable_defensive_tracking:
            defensive_casts = report_data.get("defensiveCasts", {}).get("data", [])
            defensive_buffs = report_data.get("defensiveBuffs", {}).get("data", [])
            
            print(f"  Found {len(defensive_casts)} defensive casts")
            print(f"  Found {len(defensive_buffs)} defensive buff applications")
        
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
            
            # STEP 3.5: Deduplicate cheat death events
            # Issue 1: Same fight logged by multiple people → duplicate cheat deaths across reports
            # Issue 2: WarcraftLogs bug → same player shows multiple cheat deaths in one fight
            # Solution: Deduplicate by (player, fight) first, then by (player, timestamp) across reports
            
            print(f"  [DEDUP] Deduplicating cheat deaths...")
            print(f"  [DEDUP] Before deduplication: {len(cheat_death_events)} cheat death events")
            
            # PHASE 1: Per-fight per-player deduplication (keep only FIRST cheat death per player per fight)
            # This handles the WarcraftLogs bug where same player shows multiple cheat deaths in one fight
            fight_player_first_cheat = {}  # Key: (fightId, normalized_player_name) -> earliest cheat death event
            
            for event in cheat_death_events:
                fight_id = event['fightId']
                player_name = normalize_character_name(event['targetName'])
                key = (fight_id, player_name)
                
                # Keep only the earliest cheat death for this player in this fight
                if key not in fight_player_first_cheat:
                    fight_player_first_cheat[key] = event
                else:
                    # Already have a cheat death for this player in this fight
                    # Keep whichever happened first
                    existing_timestamp = fight_player_first_cheat[key]['timestamp']
                    if event['timestamp'] < existing_timestamp:
                        fight_player_first_cheat[key] = event
            
            # Replace list with per-fight deduplicated events
            cheat_death_events = list(fight_player_first_cheat.values())
            
            per_fight_removed = len(cheat_death_events)
            print(f"  [DEDUP] After per-fight per-player filtering: {len(cheat_death_events)} events")
            
            # PHASE 2: Cross-report deduplication (same fight logged by multiple people)
            # When 3 people log the same fight, each report has the same cheat death
            # Deduplicate based on: same player + similar timestamp (within 100ms) + same ability
            
            # Sort by player name and timestamp for efficient deduplication
            cheat_death_events.sort(key=lambda x: (normalize_character_name(x['targetName']), x['timestamp']))
            
            deduplicated_events = []
            TIMESTAMP_WINDOW_MS = 100  # Consider events within 100ms as duplicates
            
            for event in cheat_death_events:
                is_duplicate = False
                target_name = normalize_character_name(event['targetName'])
                timestamp = event['timestamp']
                ability_id = event['abilityGameID']
                
                # Check against already added events
                for existing in deduplicated_events:
                    existing_name = normalize_character_name(existing['targetName'])
                    existing_timestamp = existing['timestamp']
                    existing_ability = existing['abilityGameID']
                    
                    # Same player, same ability, timestamps within 100ms → duplicate
                    if (existing_name == target_name and 
                        existing_ability == ability_id and
                        abs(existing_timestamp - timestamp) <= TIMESTAMP_WINDOW_MS):
                        is_duplicate = True
                        break
                
                if not is_duplicate:
                    deduplicated_events.append(event)
            
            cross_report_removed = len(cheat_death_events) - len(deduplicated_events)
            
            print(f"  [DEDUP] After cross-report deduplication: {len(deduplicated_events)} unique cheat death events")
            
            if per_fight_removed > 0 or cross_report_removed > 0:
                total_removed = (len(list(fight_player_first_cheat.values())) - len(cheat_death_events)) + cross_report_removed
                print(f"  [DEDUP] Summary:")
                if len(list(fight_player_first_cheat.values())) - len(cheat_death_events) > 0:
                    print(f"    - Removed {len(list(fight_player_first_cheat.values())) - len(cheat_death_events)} duplicate cheat deaths (same player, same fight)")
                if cross_report_removed > 0:
                    print(f"    - Removed {cross_report_removed} duplicate cheat deaths (multiple loggers)")
                print(f"    - Total removed: {total_removed}")
            
            # Replace the original list with fully deduplicated list
            cheat_death_events = deduplicated_events
        else:
            print(f"[DISABLED] Cheat death detection DISABLED - skipping debuff queries (faster)")
        
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
            
            death_obj = {
                "timestamp": event_timestamp,
                "targetName": target_name,
                "targetID": target_id,
                "phase": 1,
                "fightId": fight_id,
                "bossName": fight_obj.get('name', 'Unknown') if fight_obj else 'Unknown',
                "abilityName": ability_name,
                "isCheatDeath": False,
            }
            
            # Don't fetch defensive/healing data here - will be added later after filtering
            
            deaths_by_fight[fight_id].append(death_obj)
        
        # STEP 4: Add cheat death events to the appropriate fights
        for cheat_event in cheat_death_events:
            fight_id = cheat_event["fightId"]
            if fight_id in deaths_by_fight:
                # Find the fight object to get its name
                fight_obj = next((f for f in fights if f['id'] == fight_id), None)
                
                death_obj = {
                    "timestamp": cheat_event["timestamp"],
                    "targetName": cheat_event["targetName"],
                    "targetID": cheat_event["targetID"],
                    "phase": 1,
                    "fightId": fight_id,
                    "bossName": fight_obj.get('name', 'Unknown') if fight_obj else 'Unknown',
                    "abilityName": cheat_event["abilityName"],
                    "isCheatDeath": True,
                }
                
                # Don't fetch defensive/healing data here - will be added later after filtering
                
                deaths_by_fight[fight_id].append(death_obj)
        
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