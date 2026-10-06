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
from features import CHEAT_DEATH_DEBUFF_IDS, CHEAT_DEATH_HEAL_IDS

# =============================================================================
# CONSTANTS
# =============================================================================

MASS_DEATH_THRESHOLD = 8
MASS_DEATH_WINDOW = 8000  # ms

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

def is_in_mass_death(death_index, deaths_list):
    """
    Check if a death at the given index is part of a mass death event.
    Returns: (bool, start_timestamp or None)
    - If the death is in a mass death, returns (True, timestamp_of_mass_death_start)
    - Otherwise returns (False, None)
    """
    if len(deaths_list) < MASS_DEATH_THRESHOLD:
        return False, None
    
    death_ts = deaths_list[death_index]["timestamp"]

    # Look for a MASS_DEATH_WINDOW-long window, starting at a death, that
    # contains this death and holds MASS_DEATH_THRESHOLD or more deaths
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


def _in_mass_window(ts, real_ts):
    """Is a moment at `ts` inside a wipe: any 8-second stretch holding 8 real
    deaths? Only real deaths count toward it. Windows start or end at a real
    death, so a cheat death just before a wipe's first death is inside it
    too (a real death always starts its own window)."""
    if len(real_ts) < MASS_DEATH_THRESHOLD:
        return False
    for t0 in real_ts:
        for start, end in ((t0, t0 + MASS_DEATH_WINDOW), (t0 - MASS_DEATH_WINDOW, t0)):
            if start <= ts <= end and sum(1 for t in real_ts if start <= t <= end) >= MASS_DEATH_THRESHOLD:
                return True
    return False


# A save only counts as a cheat death if the player didn't die from it: no real
# death of theirs this soon after. Measured on live Mythic logs: Purgatory that
# isn't healed off kills 3-5s after it triggers, and a second hit right after a
# Cheat Death or Defy Fate lands within a second or two.
CHEAT_DEATH_SURVIVE_MS = 5000


def drop_saves_that_died(deaths):
    """Deaths of one pull, without the cheat deaths whose player died within CHEAT_DEATH_SURVIVE_MS."""
    real = defaultdict(list)
    for d in deaths:
        if not d.get("isCheatDeath"):
            real[d.get("targetID")].append(d["timestamp"])
    return [d for d in deaths if not d.get("isCheatDeath")
            or not any(0 < t - d["timestamp"] <= CHEAT_DEATH_SURVIVE_MS for t in real.get(d.get("targetID"), ()))]


def rank_pull_deaths(deaths_sorted):
    """Where each death in one pull falls for the "first X deaths" count.

    `deaths_sorted`: every death in the pull (all players, cheat deaths
    included) in log order. Returns [(slot, in_wipe)] in the same order:
      - real death: slot = which death of the pull it was (1 = first). A
        player who dies, is battle-rezzed and dies again takes two slots.
        Simultaneous deaths keep the combat log's order.
      - cheat death: slot = real deaths so far + 1. Cheat deaths never take
        a slot from real deaths.
      - in_wipe: inside a mass death. Only real deaths make a wipe.
    A death counts for "first X" when slot <= X and not in_wipe.
    """
    real_ts = [d["timestamp"] for d in deaths_sorted if not d.get("isCheatDeath")]
    real_so_far, out = 0, []
    for d in deaths_sorted:
        if d.get("isCheatDeath"):
            slot = real_so_far + 1
        else:
            real_so_far += 1
            slot = real_so_far
        out.append((slot, _in_mass_window(d["timestamp"], real_ts)))
    return out


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


# Authoritative WCL encounter IDs per raid (from worldData), keyed by the
# frontend's `selectedRaid`. Midnight (Voidspire / Dreamrift / March on
# Quel'Danas) all share WCL reportZone 46, so the only reliable way to
# isolate one Midnight raid — e.g. count *only* March-on-Quel'Danas
# pulls — is by its boss encounter IDs. This allowlist is also what keeps
# Mythic+/dungeon bosses out of the raid charts entirely: a dungeon
# encounter ID is never in any raid's set.
RAID_ENCOUNTERS = {
    # Midnight S2. Instance IDs: Venomous Abyss 3004, Tidebound Grotto 2987.
    # Encounter IDs: BigWigsMods/BigWigs TheVenomousAbyss and MidnightLairs.
    'midnight-s2-all': {3470, 3445, 3497, 3455, 3420, 3421, 3429, 3492, 3379},
    # The War Within
    'manaforge':    {3129, 3131, 3130, 3132, 3122, 3133, 3134, 3135},
    'undermine':    {3009, 3010, 3011, 3012, 3013, 3014, 3015, 3016},
    'nerubar':      {2902, 2917, 2898, 2918, 2919, 2920, 2921, 2922},
    # Midnight S1 — all in WCL zone 46 "VS / DR / MQD"
    'voidspire':    {3176, 3177, 3179, 3178, 3180, 3181},
    'dreamrift':    {3306},
    'queldanas':    {3182, 3183},  # Belo'ren + Midnight Falls (L'ura)
    'midnight-all': {3176, 3177, 3178, 3179, 3180, 3181, 3306, 3182, 3183},
}


# Hard date window per raid tier, used to scope guild-report fetching so we
# don't paginate a guild's entire multi-year history. start = tier release
# minus 5 days; end = the day the *next* tier's first raid opened (which
# already covers the prepatch tail) plus 5 days. The +/-5d margin absorbs
# the NA/EU regional release split. A None end means "current tier, still
# open". Midnight Season 1's three raids opened on different days
# (Voidspire/Dreamrift 2026-03-17, March on Quel'Danas 2026-03-31); per spec
# its window uses the earliest (2026-03-17). It ends 2026-08-23: Season 2's
# raids opened 2026-08-18 (patch 12.1 had ended the season on 2026-08-11,
# but there was no new raid until the 18th).
# These bounds are authoritative: user-supplied dates may narrow the window
# but never widen it past the tier.
RAID_DATE_WINDOWS = {
    # Both opened Normal/Heroic/Mythic on 2026-08-18; include the 5-day margin.
    # https://worldofwarcraft.blizzard.com/en-us/news/24294369
    'midnight-s2-all': ('2026-08-13', None),
    'nerubar':      ('2024-09-05', '2025-03-09'),  # Nerub-ar Palace, TWW S1
    'undermine':    ('2025-02-27', '2025-08-17'),  # Liberation of Undermine, S2
    'manaforge':    ('2025-08-07', '2026-03-22'),  # Manaforge Omega, S3
    'voidspire':    ('2026-03-12', '2026-08-23'),  # Midnight S1
    'dreamrift':    ('2026-03-12', '2026-08-23'),
    'queldanas':    ('2026-03-12', '2026-08-23'),
    'midnight-all': ('2026-03-12', '2026-08-23'),
}


def _parse_iso(d):
    return datetime.strptime(d, "%Y-%m-%d") if d else None


def resolve_report_window(selected_raid, user_start, user_end):
    """Intersect any user-supplied date range with the tier's hard window.

    Returns (start, end) as 'YYYY-MM-DD' strings (or None). The tier window
    is the outer bound; user dates can only tighten it. If the raid key has
    no known window, fall back to the user's dates unchanged.
    """
    tier_start, tier_end = RAID_DATE_WINDOWS.get(selected_raid, (None, None))

    def clamp(user, tier, pick_later):
        u, t = _parse_iso(user), _parse_iso(tier)
        if u is None:
            return tier
        if t is None:
            return user
        return (max if pick_later else min)(u, t).strftime("%Y-%m-%d")

    start = clamp(user_start, tier_start, pick_later=True)
    end = clamp(user_end, tier_end, pick_later=False)
    return start, end


def analyze_fights(fights, fight_zone, difficulty, selected_raid=None):
    """Keep only this raid's boss pulls at the chosen difficulty.

    Primary guard is an explicit encounter-ID allowlist per raid
    (`selected_raid`). This both isolates the chosen raid (critical for
    Midnight, where 3 raids share one WCL zone) and excludes Mythic+/
    dungeon bosses outright even when one log mixes raid + dungeons.
    If the raid key is unknown, fall back to the older zone/difficulty
    heuristic so nothing regresses.
    """
    diff = int(difficulty)
    allowed = RAID_ENCOUNTERS.get(selected_raid)
    if allowed is not None:
        return [f for f in fights
                if f.get("boss") in allowed and f.get("difficulty") == diff]

    zone_filter = int(fight_zone)
    if zone_filter == 0:
        return [f for f in fights if f.get("boss") and f.get("difficulty") == diff]
    return [f for f in fights if f.get("boss") and
            f.get("zoneID") == zone_filter and f.get("difficulty") == diff]


# =============================================================================
# CORE DEATH ANALYSIS
# =============================================================================

def _fetch_remaining_events(token, report_code, data_type, filter_expr, start_time, end_time, max_pages=50):
    """Follow WCL's nextPageTimestamp for one event type and return the extra events."""
    query = """
    query($code: String!, $startTime: Float!, $endTime: Float!, $filter: String) {
      reportData {
        report(code: $code) {
          events(startTime: $startTime, endTime: $endTime, dataType: %s,
                 filterExpression: $filter, limit: 10000) {
            data
            nextPageTimestamp
          }
        }
      }
    }
    """ % data_type
    events = []
    next_ts = start_time
    for _ in range(max_pages):
        data = graphql_query(token, query, {"code": report_code, "startTime": next_ts,
                                            "endTime": end_time, "filter": filter_expr})
        block = ((data.get("reportData") or {}).get("report") or {}).get("events") or {}
        events.extend(block.get("data") or [])
        next_ts = block.get("nextPageTimestamp")
        if not next_ts:
            break
    return events


def get_report_deaths_bulk(token, report_code, fights, friendlies, ability_map, enable_cheat_death=False):
    """
    Get ALL player deaths for an entire report at once - MUCH faster than per-fight queries
    Optionally detect cheat deaths in the SAME query using GraphQL aliases
    
    OPTIMIZATION STRATEGY:
    - 1 API call per report gets deaths (+ cheat-death debuffs when enabled)
    - Uses GraphQL aliases to fetch multiple event types simultaneously
    - Uses filterExpression for debuffs to avoid hitting 10k event limit
    - This is ~100x faster than querying each fight individually
    
    Defensive tracking is fetched separately by defensives.py.
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
    
    # Build query that gets deaths + optionally cheat-death debuffs
    # Use GraphQL aliases to fetch multiple event types at once
    cheat_filter = f"ability.id in ({', '.join(map(str, sorted(CHEAT_DEATH_DEBUFF_IDS)))})"
    # Saves that show only as a heal on the saved player (Guardian Spirit, Ardent Defender).
    cheat_heal_filter = (f"type = \"heal\" and ability.id in "
                         f"({', '.join(map(str, sorted(CHEAT_DEATH_HEAL_IDS)))})")
    
    
    # Build query based on what's enabled
    if enable_cheat_death:
        print(f"[ENABLED] Cheat death detection ENABLED - querying deaths AND debuffs in one call...")
        combined_query = """
        query($code: String!, $startTime: Float!, $endTime: Float!, $cheatFilter: String, $cheatHealFilter: String) {
          reportData {
            report(code: $code) {
              deaths: events(
                startTime: $startTime
                endTime: $endTime
                dataType: Deaths
                limit: 10000
              ) {
                data
                nextPageTimestamp
              }
              debuffs: events(
                startTime: $startTime
                endTime: $endTime
                dataType: Debuffs
                filterExpression: $cheatFilter
                limit: 10000
              ) {
                data
                nextPageTimestamp
              }
              saveHeals: events(
                startTime: $startTime
                endTime: $endTime
                dataType: Healing
                filterExpression: $cheatHealFilter
                limit: 10000
              ) {
                data
                nextPageTimestamp
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
            "cheatHealFilter": cheat_heal_filter,
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
                nextPageTimestamp
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
        report_data = combined_data.get("reportData", {}).get("report", {}) or {}

        # WCL pages event lists; follow nextPageTimestamp so long reports
        # don't silently lose events past the first page.
        for alias, data_type, filter_expr in (
            ("deaths", "Deaths", None),
            ("debuffs", "Debuffs", cheat_filter),
            ("saveHeals", "Healing", cheat_heal_filter),
        ):
            block = report_data.get(alias)
            if block and block.get("nextPageTimestamp"):
                block["data"] = (block.get("data") or []) + _fetch_remaining_events(
                    token, report_code, data_type, filter_expr,
                    block["nextPageTimestamp"], end_time)
        
        # Extract death events
        events_data = report_data.get("deaths", {}).get("data", [])
        
        # Build a map of fightId -> list of deaths
        deaths_by_fight = {f['id']: [] for f in fights}
        
        # Extract debuff events (if cheat death enabled)
        cheat_death_events = []
        if enable_cheat_death:
            debuff_events = (report_data.get("debuffs") or {}).get("data", []) + \
                (report_data.get("saveHeals") or {}).get("data", [])
            
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
                
                if event_type == "applydebuff" or (event_type == "heal" and ability_id in CHEAT_DEATH_HEAL_IDS):
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
            
            # STEP 3.5: Deduplicate cheat death events (all from this one report;
            # the same pull logged in several reports is dropped earlier, by
            # is_duplicate_pull). WarcraftLogs can show the same player's cheat
            # death more than once in a fight: keep the first per player per
            # fight, then drop near-identical events (same player and ability
            # within 100ms).
            
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
            
            # PHASE 2: same player + same ability within 100ms is one event
            
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
                "abilityId": killing_ability_id,
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
                    "abilityId": cheat_event["abilityGameID"],
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
        
        # Wipes are not filtered here: every death is returned, and
        # rank_pull_deaths marks the ones inside a wipe (inWipe).
        
        return deaths_by_fight
    
    except Exception as e:
        # Let the caller decide: it records the failure and, crucially,
        # doesn't cache an empty result for a report that does have deaths.
        print(f"Error fetching deaths for report {report_code}: {e}")
        raise