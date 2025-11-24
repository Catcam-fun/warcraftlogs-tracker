"""
features.py - Optional features: cheat death detection, defensive tracking, healing tracking
"""

from collections import defaultdict
import requests

# Import from warcraftlogs
from warcraftlogs import make_request_with_retry, graphql_query, GRAPHQL_ENDPOINT

# =============================================================================
# FEATURE CONSTANTS
# =============================================================================

CHEAT_DEATH_ABILITY_IDS = {
    45181,    # Cheated Death (Rogue)
    87024,    # Cauterize (Mage - Fire)
    123981,   # Purgatory (Death Knight)
    211319,   # Spirit of Redemption/Restitution (Holy Priest)
    404369,   # Empty Hourglass
    1236692,  # Void Reconstitution
    209261,   # Last Resort (Demon Hunter - Vengeance)
}

ALL_DEFENSIVE_ABILITY_IDS = {
    48707, 48792, 55233, 49028, 81256, 219809, 194679,  # DK
    196555, 187827, 203720, 212800, 198589,  # DH
    108238, 22842, 192081, 22812, 61336, 5487,  # Druid
    363916, 357170, 374348,  # Evoker
    186265, 53480, 272682,  # Hunter
    45438, 86949, 113862, 110960, 235313, 11426, 235450,  # Mage
    122278, 122783, 115203, 122470, 116849, 243435, 120954,  # Monk
    642, 498, 86659, 31850, 184662, 205191,  # Paladin
    47585, 47788, 33206, 27827, 81782, 62618,  # Priest
    31224, 5277, 1966, 45182,  # Rogue
    108271, 98008, 204288, 974,  # Shaman
    104773, 108416, 212295,  # Warlock
    871, 12975, 97463, 184364, 118038, 23920  # Warrior
}

DEFENSIVE_ABILITY_INFO = {
    48707: {"name": "Anti-Magic Shell", "class": "DeathKnight"},
    48792: {"name": "Icebound Fortitude", "class": "DeathKnight"},
    55233: {"name": "Vampiric Blood", "class": "DeathKnight"},
    49028: {"name": "Dancing Rune Weapon", "class": "DeathKnight"},
    81256: {"name": "Dancing Rune Weapon", "class": "DeathKnight"},
    219809: {"name": "Tombstone", "class": "DeathKnight"},
    194679: {"name": "Rune Tap", "class": "DeathKnight"},
    196555: {"name": "Netherwalk", "class": "DemonHunter"},
    187827: {"name": "Metamorphosis", "class": "DemonHunter"},
    203720: {"name": "Demon Spikes", "class": "DemonHunter"},
    212800: {"name": "Blur", "class": "DemonHunter"},
    198589: {"name": "Blur", "class": "DemonHunter"},
    108238: {"name": "Renewal", "class": "Druid"},
    22842: {"name": "Frenzied Regeneration", "class": "Druid"},
    192081: {"name": "Ironfur", "class": "Druid"},
    22812: {"name": "Barkskin", "class": "Druid"},
    61336: {"name": "Survival Instincts", "class": "Druid"},
    5487: {"name": "Bear Form", "class": "Druid"},
    363916: {"name": "Obsidian Scales", "class": "Evoker"},
    357170: {"name": "Time Dilation", "class": "Evoker"},
    374348: {"name": "Renewing Blaze", "class": "Evoker"},
    186265: {"name": "Aspect of the Turtle", "class": "Hunter"},
    53480: {"name": "Roar of Sacrifice", "class": "Hunter"},
    272682: {"name": "Master's Call", "class": "Hunter"},
    45438: {"name": "Ice Block", "class": "Mage"},
    86949: {"name": "Cauterize", "class": "Mage"},
    113862: {"name": "Greater Invisibility", "class": "Mage"},
    110960: {"name": "Greater Invisibility", "class": "Mage"},
    235313: {"name": "Blazing Barrier", "class": "Mage"},
    11426: {"name": "Ice Barrier", "class": "Mage"},
    235450: {"name": "Prismatic Barrier", "class": "Mage"},
    122278: {"name": "Dampen Harm", "class": "Monk"},
    122783: {"name": "Diffuse Magic", "class": "Monk"},
    115203: {"name": "Fortifying Brew", "class": "Monk"},
    122470: {"name": "Touch of Karma", "class": "Monk"},
    116849: {"name": "Life Cocoon", "class": "Monk"},
    243435: {"name": "Fortifying Brew", "class": "Monk"},
    120954: {"name": "Fortifying Brew", "class": "Monk"},
    642: {"name": "Divine Shield", "class": "Paladin"},
    498: {"name": "Divine Protection", "class": "Paladin"},
    86659: {"name": "Guardian of Ancient Kings", "class": "Paladin"},
    31850: {"name": "Ardent Defender", "class": "Paladin"},
    184662: {"name": "Shield of Vengeance", "class": "Paladin"},
    205191: {"name": "Eye for an Eye", "class": "Paladin"},
    47585: {"name": "Dispersion", "class": "Priest"},
    47788: {"name": "Guardian Spirit", "class": "Priest"},
    33206: {"name": "Pain Suppression", "class": "Priest"},
    27827: {"name": "Spirit of Redemption", "class": "Priest"},
    81782: {"name": "Power Word: Barrier", "class": "Priest"},
    62618: {"name": "Power Word: Barrier", "class": "Priest"},
    31224: {"name": "Cloak of Shadows", "class": "Rogue"},
    5277: {"name": "Evasion", "class": "Rogue"},
    1966: {"name": "Feint", "class": "Rogue"},
    45182: {"name": "Cheating Death", "class": "Rogue"},
    108271: {"name": "Astral Shift", "class": "Shaman"},
    98008: {"name": "Spirit Link Totem", "class": "Shaman"},
    204288: {"name": "Earth Shield", "class": "Shaman"},
    974: {"name": "Earth Shield", "class": "Shaman"},
    104773: {"name": "Unending Resolve", "class": "Warlock"},
    108416: {"name": "Dark Pact", "class": "Warlock"},
    212295: {"name": "Nether Ward", "class": "Warlock"},
    871: {"name": "Shield Wall", "class": "Warrior"},
    12975: {"name": "Last Stand", "class": "Warrior"},
    97463: {"name": "Rallying Cry", "class": "Warrior"},
    184364: {"name": "Enraged Regeneration", "class": "Warrior"},
    118038: {"name": "Die by the Sword", "class": "Warrior"},
    23920: {"name": "Spell Reflection", "class": "Warrior"},
}

# =============================================================================
# HEALING & DEFENSIVE FUNCTIONS
# =============================================================================

def get_all_healing_for_report_paginated(token, report_code, start_time, end_time):
    """
    Fetch ALL healing events for an entire report using pagination.
    WarcraftLogs returns max 10k events per query, so we paginate if needed.
    
    Args:
        token: WarcraftLogs API token
        report_code: Report code
        start_time: Start time for the report
        end_time: End time for the report
    
    Returns:
        List of all healing events in the report
    """
    all_healing = []
    current_start = start_time
    page_count = 0
    
    while True:
        page_count += 1
        
        query = """
        query($code: String!, $startTime: Float!, $endTime: Float!) {
          reportData {
            report(code: $code) {
              healing: events(
                startTime: $startTime
                endTime: $endTime
                dataType: Healing
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
            "startTime": current_start,
            "endTime": end_time
        }
        
        # Using inline API call
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}"
        }
        
        try:
            response = make_request_with_retry('post', GRAPHQL_ENDPOINT, json={'query': query, 'variables': variables}, headers=headers)
            result = response.json()
            
            if "errors" in result:
                print(f"  [WARNING] Healing query page {page_count} error: {result['errors']}")
                break
            
            if result.get("data") is None:
                print(f"  [DEBUG] No data in healing response page {page_count}")
                break
            
            healing_data = result.get("data", {}).get("reportData", {}).get("report", {}).get("healing", {})
            page_events = healing_data.get("data", [])
            next_page = healing_data.get("nextPageTimestamp")
            
            all_healing.extend(page_events)
            print(f"  [OK] Fetched healing page {page_count}: {len(page_events)} events (total: {len(all_healing)})")
            
            # Check if there's another page
            if next_page is None or next_page >= end_time:
                break
            
            current_start = next_page
            
            # Safety: don't fetch more than 10 pages (100k events should be enough)
            if page_count >= 10:
                print(f"  [WARNING] Hit 10-page limit for healing (fetched {len(all_healing)} events)")
                break
                
        except Exception as e:
            print(f"  [WARNING] Failed to fetch healing page {page_count}: {e}")
            break
    
    return all_healing


def get_all_defensive_buffs_paginated(token, report_code, start_time, end_time):
    """
    Fetch ALL defensive buff events for an entire report using pagination.
    
    Args:
        token: WarcraftLogs API token
        report_code: Report code
        start_time: Start time for the report
        end_time: End time for the report
    
    Returns:
        List of all defensive buff events in the report
    """
    all_buffs = []
    current_start = start_time
    page_count = 0
    
    defensive_ids = ", ".join(str(id) for id in ALL_DEFENSIVE_ABILITY_IDS)
    defensive_filter = f"ability.id in ({defensive_ids})"
    
    while True:
        page_count += 1
        
        query = f"""
        query($code: String!, $startTime: Float!, $endTime: Float!) {{
          reportData {{
            report(code: $code) {{
              defensiveBuffs: events(
                startTime: $startTime
                endTime: $endTime
                dataType: Buffs
                filterExpression: "{defensive_filter}"
                limit: 10000
              ) {{
                data
                nextPageTimestamp
              }}
            }}
          }}
        }}
        """
        
        variables = {
            "code": report_code,
            "startTime": current_start,
            "endTime": end_time
        }
        
        # Using inline API call
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}"
        }
        
        try:
            response = make_request_with_retry('post', GRAPHQL_ENDPOINT, json={'query': query, 'variables': variables}, headers=headers)
            result = response.json()
            
            if "errors" in result:
                print(f"  [WARNING] Defensive buffs page {page_count} error: {result['errors']}")
                break
            
            if result.get("data") is None:
                print(f"  [DEBUG] No data in defensive buffs page {page_count}")
                break
            
            buff_data = result.get("data", {}).get("reportData", {}).get("report", {}).get("defensiveBuffs", {})
            page_events = buff_data.get("data", [])
            next_page = buff_data.get("nextPageTimestamp")
            
            all_buffs.extend(page_events)
            print(f"  [OK] Fetched defensive buffs page {page_count}: {len(page_events)} events (total: {len(all_buffs)})")
            
            # Check if there's another page
            if next_page is None or next_page >= end_time:
                break
            
            current_start = next_page
            
            # Safety: don't fetch more than 5 pages (defensive buffs are rarer)
            if page_count >= 5:
                print(f"  [WARNING] Hit 5-page limit for defensive buffs (fetched {len(all_buffs)} events)")
                break
                
        except Exception as e:
            print(f"  [WARNING] Failed to fetch defensive buffs page {page_count}: {e}")
            break
    
    return all_buffs


def calculate_defensive_data_from_bulk(death_timestamp, target_id, defensive_buffs, all_healing_events):
    """
    Calculate defensive/healing data for a death using PRE-FETCHED bulk data.
    No API calls - just filters the data we already have in memory.
    
    Args:
        death_timestamp: When the player died (milliseconds)
        target_id: The player's actor ID
        defensive_buffs: ALL defensive buff events from the report (already fetched)
        all_healing_events: ALL healing events from the report (already fetched)
    
    Returns:
        dict with defensive analysis
    """
    # Window: 5 seconds before death for healing
    window_start = death_timestamp - 5000
    
    # Filter healing for this specific death
    healing_for_death = [
        h for h in all_healing_events
        if h.get('targetID') == target_id and window_start <= h.get('timestamp', 0) <= death_timestamp
    ]
    
    # Calculate total healing received (effective + overheal)
    total_healing = sum(h.get('amount', 0) + h.get('overheal', 0) for h in healing_for_death)
    
    # Debug: Log if no healing found
    if total_healing == 0 and len(all_healing_events) > 0:
        # Check if there's ANY healing for this targetID in the entire dataset
        all_for_target = [h for h in all_healing_events if h.get('targetID') == target_id]
        print(f"[DEBUG] No healing found for death:")
        print(f"  death_timestamp={death_timestamp}, target_id={target_id}, window={window_start} to {death_timestamp}")
        print(f"  Total healing in cache for this target: {len(all_for_target)} events")
        if all_for_target:
            # Sort by timestamp to see the range
            sorted_healing = sorted(all_for_target, key=lambda h: h.get('timestamp', 0))
            print(f"  First healing event: timestamp={sorted_healing[0].get('timestamp')}, amount={sorted_healing[0].get('amount')}")
            print(f"  Last healing event: timestamp={sorted_healing[-1].get('timestamp')}, amount={sorted_healing[-1].get('amount')}")
            # Find healing events closest to the death
            events_near_death = [h for h in all_for_target if abs(h.get('timestamp', 0) - death_timestamp) < 30000]  # Within 30 seconds
            if events_near_death:
                closest = min(events_near_death, key=lambda h: abs(h.get('timestamp', 0) - death_timestamp))
                time_diff = closest.get('timestamp', 0) - death_timestamp
                print(f"  Closest healing within 30s: timestamp={closest.get('timestamp')}, amount={closest.get('amount')}, diff={time_diff}ms")
            else:
                print(f"  No healing events within 30 seconds of death")
        if len(all_healing_events) > 0:
            # Show sample from entire cache to check timestamp range
            all_timestamps = [h.get('timestamp', 0) for h in all_healing_events[:100]]  # First 100 events
            if all_timestamps:
                print(f"  Cache timestamp range (first 100): min={min(all_timestamps)}, max={max(all_timestamps)}")
    
    
    # Track active defensive buffs
    buff_window_start = death_timestamp - 30000
    active_defensives = {}
    
    # Filter and sort buff events for this player
    relevant_buffs = sorted(
        [
            {'timestamp': e.get('timestamp'), 'type': e.get('type'), 'ability_id': e.get('abilityGameID')}
            for e in defensive_buffs
            if e.get('targetID') == target_id 
            and buff_window_start <= e.get('timestamp', 0) <= death_timestamp
            and e.get('abilityGameID') in DEFENSIVE_ABILITY_INFO
        ],
        key=lambda x: x['timestamp']
    )
    
    # Track buff applications/removals
    for buff_event in relevant_buffs:
        ability_id = buff_event['ability_id']
        event_type = buff_event['type']
        
        if event_type in ('applybuff', 'applybuffstack', 'refreshbuff'):
            active_defensives[ability_id] = {
                'name': DEFENSIVE_ABILITY_INFO[ability_id]['name'],
                'applied_at': buff_event['timestamp'],
                'removed_at': None
            }
        elif event_type in ('removebuff', 'removebuffstack'):
            if ability_id in active_defensives:
                active_defensives[ability_id]['removed_at'] = buff_event['timestamp']
    
    # Filter to defensives that were active or recently removed
    recently_active_window = 3000
    active_at_death = {}
    
    for ability_id, buff_info in active_defensives.items():
        removed_at = buff_info['removed_at']
        
        if removed_at is None:
            # Still active at death
            active_at_death[ability_id] = buff_info
        elif (death_timestamp - removed_at) <= recently_active_window:
            # Removed recently before death
            active_at_death[ability_id] = buff_info
    
    # Group by ability name and count stacks
    ability_counts = {}
    for buff_info in active_at_death.values():
        name = buff_info['name']
        ability_counts[name] = ability_counts.get(name, 0) + 1
    
    abilities_list = [
        {'name': name, 'count': count}
        for name, count in ability_counts.items()
    ]
    
    return {
        'abilities': abilities_list,
        'healing': total_healing
    }


def get_healing_for_death(token, report_code, death_timestamp, target_id):
    """
    DEPRECATED: Old per-death fetching function.
    Use get_all_healing_for_report_paginated() + calculate_defensive_data_from_bulk() instead.
    """
    print(f"  [WARNING] Using deprecated per-death healing fetch - this is slow!")
    # Window: 5 seconds before death
    window_start = death_timestamp - 5000
    window_end = death_timestamp
    
    query = f"""
    query($code: String!, $startTime: Float!, $endTime: Float!) {{
      reportData {{
        report(code: $code) {{
          healing: events(
            startTime: $startTime
            endTime: $endTime
            dataType: Healing
            filterExpression: "targetID = {target_id}"
            limit: 1000
          ) {{
            data
          }}
        }}
      }}
    }}
    """
    
    variables = {
        "code": report_code,
        "startTime": window_start,
        "endTime": window_end
    }
    
    # Using inline API call
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}"
    }
    
    try:
        response = make_request_with_retry('post', GRAPHQL_ENDPOINT, json={'query': query, 'variables': variables}, headers=headers)
        result = response.json()
        
        if "errors" in result:
            print(f"  [WARNING] Healing query error for target {target_id}: {result['errors']}")
            return []
        
        if result.get("data") is None:
            print(f"  [DEBUG] No data in healing response for target {target_id}")
            return []
        
        healing_data = result.get("data", {}).get("reportData", {}).get("report", {}).get("healing", {})
        healing_events = healing_data.get("data", [])
        
        return healing_events
    except Exception as e:
        print(f"  [WARNING] Failed to fetch healing for target {target_id}: {e}")
        return []


def calculate_defensive_data_for_death(death_timestamp, target_id, defensive_casts, defensive_buffs, token, report_code):
    """
    DEPRECATED: Old per-death calculation that makes API calls.
    Use calculate_defensive_data_from_bulk() instead.
    """
    print(f"  [WARNING] Using deprecated per-death defensive calculation - this makes extra API calls!")
    healing_events_all = get_healing_for_death(token, report_code, death_timestamp, target_id)
    
    # Track which defensive buffs were ACTIVE at the moment of death
    # We need to track applybuff and removebuff events to know what was active
    active_defensives = {}  # ability_id -> {'name': str, 'applied_at': timestamp}
    
    # Process buff events chronologically to track what was active
    # Filter events for this player only and within a reasonable window (30s before death to catch long buffs)
    buff_window_start = death_timestamp - 30000  # Look back 30s to catch long-duration buffs
    
    relevant_buffs = []
    for event in defensive_buffs:
        if event.get('targetID') == target_id:
            timestamp = event.get('timestamp')
            if buff_window_start <= timestamp <= death_timestamp:
                ability_id = event.get('abilityGameID')
                if ability_id in DEFENSIVE_ABILITY_INFO:
                    relevant_buffs.append({
                        'timestamp': timestamp,
                        'type': event.get('type'),
                        'ability_id': ability_id
                    })
    
    # DEBUG: Log relevant buffs found (only if there are issues)
    # Commented out to reduce log noise
    # if len(relevant_buffs) > 0:
    #     print(f"  [DEBUG] Found {len(relevant_buffs)} relevant defensive buffs for target {target_id} around death at {death_timestamp}")
    #     event_types = [b['type'] for b in relevant_buffs]
    #     print(f"  [DEBUG] Buff event types: {event_types}")
    
    # Sort by timestamp
    relevant_buffs.sort(key=lambda x: x['timestamp'])
    
    # Track active buffs up to death timestamp
    # We want to know what defensives were RECENTLY active, not just at the exact millisecond
    recently_active_window = 3000  # Show defensives active within 3 seconds of death
    
    for buff_event in relevant_buffs:
        ability_id = buff_event['ability_id']
        event_type = buff_event['type']
        
        # Handle all types of buff application events
        if event_type in ('applybuff', 'applybuffstack', 'refreshbuff'):
            # Buff was applied or refreshed
            active_defensives[ability_id] = {
                'name': DEFENSIVE_ABILITY_INFO[ability_id]['name'],
                'applied_at': buff_event['timestamp'],
                'removed_at': None  # Track when it was removed
            }
        # Handle all types of buff removal events
        elif event_type in ('removebuff', 'removebuffstack'):
            # Mark when buff was removed
            if ability_id in active_defensives:
                active_defensives[ability_id]['removed_at'] = buff_event['timestamp']
    
    # Filter to only include defensives that were:
    # 1. Still active at death, OR
    # 2. Removed within the last 3 seconds before death
    final_active_defensives = {}
    for ability_id, info in active_defensives.items():
        removed_at = info['removed_at']
        if removed_at is None:
            # Still active at death
            final_active_defensives[ability_id] = info
        elif (death_timestamp - removed_at) <= recently_active_window:
            # Was removed recently before death (within 3 seconds)
            final_active_defensives[ability_id] = info
    
    # Convert to frontend format: array of {name, count}
    # Count=1 for each unique buff that was active
    abilities = [
        {'name': info['name'], 'count': 1}
        for info in final_active_defensives.values()
    ]
    
    # Sort by name for consistent display
    abilities.sort(key=lambda x: x['name'])
    
    # Calculate healing received in the 5 seconds before death
    window_start = death_timestamp - 5000
    window_end = death_timestamp
    total_healing = 0
    total_overheal = 0
    healing_event_count = 0
    
    for event in healing_events_all:
        if (event.get('targetID') == target_id and
            window_start <= event.get('timestamp') <= window_end):
            
            # WarcraftLogs separates effective healing ('amount') from overheal
            # We want to show total healing done, not just effective
            amount = event.get('amount', 0)
            overheal = event.get('overheal', 0)
            total_healing += amount
            total_overheal += overheal
            healing_event_count += 1
    
    # Total healing = effective + overheal
    combined_healing = total_healing + total_overheal
    
    return {
        'abilities': abilities,  # Frontend expects this key - shows ACTIVE buffs
        'healing': combined_healing,  # Total healing (effective + overheal) in last 5 seconds
        'healing_event_count': healing_event_count,
        'query_window_ms': 5000  # Updated to 5 seconds
    }