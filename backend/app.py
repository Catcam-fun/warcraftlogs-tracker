#!/usr/bin/env python3
"""
Flask API for WarcraftLogs Death Tracker - V2 GraphQL API
Optimized for Render.com deployment
Version 2.6.0 - Parallel death fetching (5min → 1min analysis time)
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
from concurrent.futures import ThreadPoolExecutor, as_completed
import brotli
import base64
from supabase import create_client, Client
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

app = Flask(__name__)

# Configure CORS - simplest approach, allow everything
CORS(app, 
     resources={r"/api/*": {"origins": "*"}},
     supports_credentials=True,
     allow_headers=["Content-Type", "Authorization"],
     methods=["GET", "POST", "DELETE", "OPTIONS", "PUT"])

# Initialize Supabase client
SUPABASE_URL = os.environ.get('SUPABASE_URL')
SUPABASE_KEY = os.environ.get('SUPABASE_KEY')
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY) if SUPABASE_URL and SUPABASE_KEY else None

# Debug: Verify Supabase configuration
print(f"[Startup] Supabase configured: {supabase is not None}")
if not supabase:
    print(f"[Startup] SUPABASE_URL found: {'SUPABASE_URL' in os.environ}")
    print(f"[Startup] SUPABASE_KEY found: {'SUPABASE_KEY' in os.environ}")
else:
    print(f"[Startup] Supabase client successfully initialized")


# Retry configuration for network requests
MAX_RETRIES = 3
RETRY_BACKOFF_BASE = 1  # seconds
RETRY_BACKOFF_MAX = 10  # seconds


def make_request_with_retry(method, url, max_retries=MAX_RETRIES, timeout=120, **kwargs):
    """
    Make an HTTP request with exponential backoff retry logic.
    
    Args:
        method: 'get' or 'post'
        url: URL to request
        max_retries: Maximum number of retry attempts
        timeout: Request timeout in seconds
        **kwargs: Additional arguments to pass to requests
    
    Returns:
        Response object
    
    Raises:
        Exception: If all retries fail
    """
    last_exception = None
    
    for attempt in range(max_retries + 1):
        try:
            if method.lower() == 'post':
                response = requests.post(url, timeout=timeout, **kwargs)
            else:
                response = requests.get(url, timeout=timeout, **kwargs)
            
            response.raise_for_status()
            return response
            
        except requests.exceptions.Timeout as e:
            last_exception = e
            if attempt < max_retries:
                # Calculate backoff time with exponential increase
                backoff_time = min(RETRY_BACKOFF_BASE * (2 ** attempt), RETRY_BACKOFF_MAX)
                print(f"[Retry] Request timeout (attempt {attempt + 1}/{max_retries + 1}). Retrying in {backoff_time}s... URL: {url}")
                time.sleep(backoff_time)
            else:
                print(f"[Retry] Request failed after {max_retries + 1} attempts. URL: {url}")
                
        except requests.exceptions.RequestException as e:
            last_exception = e
            # For non-timeout errors, retry with shorter backoff
            if attempt < max_retries:
                backoff_time = min(RETRY_BACKOFF_BASE * (1.5 ** attempt), RETRY_BACKOFF_MAX)
                print(f"[Retry] Request error: {str(e)} (attempt {attempt + 1}/{max_retries + 1}). Retrying in {backoff_time}s... URL: {url}")
                time.sleep(backoff_time)
            else:
                print(f"[Retry] Request failed after {max_retries + 1} attempts. URL: {url}")
    
    # If we get here, all retries failed
    raise Exception(f"Request failed after {max_retries + 1} attempts: {str(last_exception)}")

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

# ALL-CLASS DEFENSIVE ABILITIES
# These are active defensive cooldowns (not cheat deaths or passive procs)
ALL_DEFENSIVE_ABILITY_IDS = {
    # Death Knight
    48707, 48792, 55233, 49028, 81256, 219809, 194679,
    # Demon Hunter
    196555, 187827, 203720, 212800, 198589,
    # Druid
    108238, 22842, 192081, 22812, 61336, 5487,
    # Evoker
    363916, 357170, 374348,
    # Hunter
    186265, 53480, 272682,
    # Mage
    45438, 86949, 113862, 110960, 235313, 11426, 235450,
    # Monk
    122278, 122783, 115203, 122470, 116849, 243435, 120954,
    # Paladin
    642, 498, 86659, 31850, 184662, 205191,
    # Priest
    47585, 47788, 33206, 27827, 81782, 62618,
    # Rogue
    31224, 5277, 1966, 45182,
    # Shaman
    108271, 98008, 204288, 974,
    # Warlock
    104773, 108416, 212295,
    # Warrior
    871, 12975, 97463, 184364, 118038, 23920
}

DEFENSIVE_ABILITY_INFO = {
    # Death Knight
    48707: {"name": "Anti-Magic Shell", "class": "DeathKnight"},
    48792: {"name": "Icebound Fortitude", "class": "DeathKnight"},
    55233: {"name": "Vampiric Blood", "class": "DeathKnight"},
    49028: {"name": "Dancing Rune Weapon", "class": "DeathKnight"},
    81256: {"name": "Dancing Rune Weapon", "class": "DeathKnight"},
    219809: {"name": "Tombstone", "class": "DeathKnight"},
    194679: {"name": "Rune Tap", "class": "DeathKnight"},
    # Demon Hunter
    196555: {"name": "Netherwalk", "class": "DemonHunter"},
    187827: {"name": "Metamorphosis", "class": "DemonHunter"},
    203720: {"name": "Demon Spikes", "class": "DemonHunter"},
    212800: {"name": "Blur", "class": "DemonHunter"},
    198589: {"name": "Blur", "class": "DemonHunter"},
    # Druid
    108238: {"name": "Renewal", "class": "Druid"},
    22842: {"name": "Frenzied Regeneration", "class": "Druid"},
    192081: {"name": "Ironfur", "class": "Druid"},
    22812: {"name": "Barkskin", "class": "Druid"},
    61336: {"name": "Survival Instincts", "class": "Druid"},
    5487: {"name": "Bear Form", "class": "Druid"},
    # Evoker
    363916: {"name": "Obsidian Scales", "class": "Evoker"},
    357170: {"name": "Time Dilation", "class": "Evoker"},
    374348: {"name": "Renewing Blaze", "class": "Evoker"},
    # Hunter
    186265: {"name": "Aspect of the Turtle", "class": "Hunter"},
    53480: {"name": "Roar of Sacrifice", "class": "Hunter"},
    272682: {"name": "Master's Call", "class": "Hunter"},
    # Mage
    45438: {"name": "Ice Block", "class": "Mage"},
    86949: {"name": "Cauterize", "class": "Mage"},
    113862: {"name": "Greater Invisibility", "class": "Mage"},
    110960: {"name": "Greater Invisibility", "class": "Mage"},
    235313: {"name": "Blazing Barrier", "class": "Mage"},
    11426: {"name": "Ice Barrier", "class": "Mage"},
    235450: {"name": "Prismatic Barrier", "class": "Mage"},
    # Monk
    122278: {"name": "Dampen Harm", "class": "Monk"},
    122783: {"name": "Diffuse Magic", "class": "Monk"},
    115203: {"name": "Fortifying Brew", "class": "Monk"},
    122470: {"name": "Touch of Karma", "class": "Monk"},
    116849: {"name": "Life Cocoon", "class": "Monk"},
    243435: {"name": "Fortifying Brew", "class": "Monk"},
    120954: {"name": "Fortifying Brew", "class": "Monk"},
    # Paladin
    642: {"name": "Divine Shield", "class": "Paladin"},
    498: {"name": "Divine Protection", "class": "Paladin"},
    86659: {"name": "Guardian of Ancient Kings", "class": "Paladin"},
    31850: {"name": "Ardent Defender", "class": "Paladin"},
    184662: {"name": "Shield of Vengeance", "class": "Paladin"},
    205191: {"name": "Eye for an Eye", "class": "Paladin"},
    # Priest
    47585: {"name": "Dispersion", "class": "Priest"},
    47788: {"name": "Guardian Spirit", "class": "Priest"},
    33206: {"name": "Pain Suppression", "class": "Priest"},
    27827: {"name": "Spirit of Redemption", "class": "Priest"},
    81782: {"name": "Power Word: Barrier", "class": "Priest"},
    62618: {"name": "Power Word: Barrier", "class": "Priest"},
    # Rogue
    31224: {"name": "Cloak of Shadows", "class": "Rogue"},
    5277: {"name": "Evasion", "class": "Rogue"},
    1966: {"name": "Feint", "class": "Rogue"},
    45182: {"name": "Cheating Death", "class": "Rogue"},
    # Shaman
    108271: {"name": "Astral Shift", "class": "Shaman"},
    98008: {"name": "Spirit Link Totem", "class": "Shaman"},
    204288: {"name": "Earth Shield", "class": "Shaman"},
    974: {"name": "Earth Shield", "class": "Shaman"},
    # Warlock
    104773: {"name": "Unending Resolve", "class": "Warlock"},
    108416: {"name": "Dark Pact", "class": "Warlock"},
    212295: {"name": "Nether Ward", "class": "Warlock"},
    # Warrior
    871: {"name": "Shield Wall", "class": "Warrior"},
    12975: {"name": "Last Stand", "class": "Warrior"},
    97463: {"name": "Rallying Cry", "class": "Warrior"},
    184364: {"name": "Enraged Regeneration", "class": "Warrior"},
    118038: {"name": "Die by the Sword", "class": "Warrior"},
    23920: {"name": "Spell Reflection", "class": "Warrior"},
}

# WoW Class Colors (standard across all WoW sites/addons)
WOW_CLASS_COLORS = {
    "DeathKnight": "#C41E3A",
    "DemonHunter": "#A330C9",
    "Druid": "#FF7C0A",
    "Evoker": "#33937F",
    "Hunter": "#AAD372",
    "Mage": "#3FC7EB",
    "Monk": "#00FF98",
    "Paladin": "#F48CBA",
    "Priest": "#FFFFFF",
    "Rogue": "#FFF468",
    "Shaman": "#0070DD",
    "Warlock": "#8788EE",
    "Warrior": "#C69B6D",
}

# WarcraftLogs V2 API endpoints (through Cloudflare Worker proxy)
GRAPHQL_ENDPOINT = "https://wcl-proxy.catcam-fun.workers.dev/api/v2/client"
OAUTH_TOKEN_URL = "https://wcl-proxy.catcam-fun.workers.dev/oauth/token"

# OAuth2 token cache
_token_cache = {"token": None, "expires_at": 0}


def normalize_character_name(name):
    """
    Normalize character names to handle UTF-8 encoding issues.
    Removes accents and diacritics to ensure consistent character matching.
    
    Examples:
        "Fîshy" → "Fishy"
        "Tîtus" → "Titus"
        "Gawrguirâ" → "Gawrguira"
        "Sarenaí" → "Sarenai"
    """
    if not name:
        return name
    
    # Normalize to NFD (Canonical Decomposition)
    nfd = unicodedata.normalize('NFD', name)
    
    # Remove combining marks (accents, diacritics)
    ascii_name = ''.join(
        char for char in nfd 
        if unicodedata.category(char) != 'Mn'
    )
    
    return ascii_name if ascii_name else name


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
        # Use retry logic with increased timeout
        response = make_request_with_retry(
            'post',
            OAUTH_TOKEN_URL,
            data=data,
            timeout=60,  # Increased from 30 to 60 seconds
            max_retries=2  # Fewer retries for OAuth (it's usually fast)
        )
        
        token_data = response.json()
        
        _token_cache["token"] = token_data["access_token"]
        # Cache expires 60 seconds before actual expiry for safety
        _token_cache["expires_at"] = time.time() + token_data.get("expires_in", 3600) - 60
        
        return _token_cache["token"]
    except Exception as e:
        raise Exception(f"Failed to get access token: {str(e)}")


def graphql_query(token, query, variables=None):
    """Execute a GraphQL query against WarcraftLogs V2 API with retry logic"""
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    
    payload = {"query": query}
    if variables:
        payload["variables"] = variables
    
    try:
        # Use retry logic with increased timeout
        response = make_request_with_retry(
            'post',
            GRAPHQL_ENDPOINT,
            json=payload,
            headers=headers,
            timeout=120,  # Increased from 60 to 120 seconds
            max_retries=3  # Retry up to 3 times with backoff
        )
        
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


def get_guild_reports(token, guild_name, server, region, zone_id, start_date=None, end_date=None):
    """Fetch guild reports using V2 GraphQL API with optional date range filtering"""
    
    # Convert dates to timestamps if provided (handle empty strings as None)
    start_ts = None
    end_ts = None
    
    # Convert empty strings to None
    if start_date == "":
        start_date = None
    if end_date == "":
        end_date = None
    
    if start_date:
        # Start of the start_date (00:00:00)
        start_ts = int(datetime.strptime(start_date, "%Y-%m-%d").timestamp() * 1000)
    
    if end_date:
        # End of the end_date (23:59:59)
        end_ts = int(datetime.strptime(end_date, "%Y-%m-%d").timestamp() * 1000) + 86400000 - 1
    
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
            report_start_time = rep.get("startTime", 0)
            
            # Filter by start date if provided
            if start_ts is not None and report_start_time < start_ts:
                continue
            
            # Filter by end date if provided
            if end_ts is not None and report_start_time > end_ts:
                continue
            
            out.append({
                "id": rep["code"],
                "start": report_start_time,
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
                name = normalize_character_name(member.get("name"))
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
    """Fetch fights for a report using V2 GraphQL API, including player class/spec info"""
    
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
          playerDetails(startTime: 0, endTime: 999999999999)
        }
      }
    }
    """
    
    variables = {"code": report_code}
    
    try:
        data = graphql_query(token, query, variables)
        report = data.get("reportData", {}).get("report", {})
        
        if not report:
            return {"report_start": 0, "fights": [], "friendlies": [], "player_details": {}}
        
        fights = report.get("fights", [])
        actors = report.get("masterData", {}).get("actors", [])
        report_start = report.get("startTime", 0)
        player_details_data = report.get("playerDetails", {})
        
        # DEBUG: Check if playerDetails was returned and show its structure
        print(f"Report {report_code}: Found {len(fights)} fights, {len(actors)} actors")
        print(f"  DEBUG: playerDetails type: {type(player_details_data)}")
        if player_details_data:
            if isinstance(player_details_data, dict):
                print(f"  DEBUG: playerDetails keys: {list(player_details_data.keys())}")
                # Show first few characters of the data
                import json
                preview = json.dumps(player_details_data)[:500]
                print(f"  DEBUG: playerDetails preview: {preview}...")
            else:
                print(f"  DEBUG: playerDetails is not a dict: {player_details_data}")
        else:
            print(f"  [WARN] playerDetails is empty/None!")
        
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
                    "name": normalize_character_name(actor.get("name")),
                    "type": actor.get("subType")  # Class name
                })
        
        # Parse player details to get class/spec info
        # playerDetails structure: { data: { playerDetails: { tanks: [], healers: [], dps: [] } } }
        player_spec_map = {}  # actor_id -> {class, spec, role}
        
        if player_details_data and isinstance(player_details_data, dict):
            # Navigate through the nested structure: data -> playerDetails -> roles
            data_section = player_details_data.get("data", {})
            player_details_section = data_section.get("playerDetails", {})
            
            if not player_details_section:
                print(f"  [WARN] playerDetails.data.playerDetails is empty or missing!")
            
            # Combine all roles
            all_players = []
            tanks = player_details_section.get("tanks", [])
            healers = player_details_section.get("healers", [])
            dps = player_details_section.get("dps", [])
            
            print(f"  Player counts - Tanks: {len(tanks)}, Healers: {len(healers)}, DPS: {len(dps)}")
            
            all_players.extend(tanks)
            all_players.extend(healers)
            all_players.extend(dps)
            
            for player in all_players:
                actor_id = player.get("id")
                player_name = normalize_character_name(player.get("name", ""))
                player_type = player.get("type", "")  # Class name like "Druid", "Mage"
                
                # Get the first spec (most commonly used spec)
                specs = player.get("specs", [])
                # specs is a list of dicts like [{"spec": "Brewmaster", "count": 31}]
                # Extract just the spec name from the first entry
                player_spec = specs[0].get("spec", "Unknown") if specs else "Unknown"
                
                if actor_id:
                    player_spec_map[actor_id] = {
                        "class": player_type,
                        "spec": player_spec,
                        "name": player_name
                    }
            
            print(f"  [OK] Extracted class/spec info for {len(player_spec_map)} players")
            if player_spec_map:
                # Show sample
                sample_id = next(iter(player_spec_map))
                sample = player_spec_map[sample_id]
                print(f"    Sample: {sample['name']} (ID: {sample_id}) - {sample['spec']} {sample['class']}")
        else:
            print(f"  [WARN] playerDetails is None or not a dict: {type(player_details_data)}")
        
        print(f"Formatted {len(formatted_friendlies)} friendly players")
        if len(formatted_friendlies) > 0:
            print(f"Sample player: {formatted_friendlies[0]}")
        
        return {
            "report_start": report_start,
            "fights": formatted_fights,
            "friendlies": formatted_friendlies,
            "player_details": player_spec_map
        }
    except Exception as e:
        print(f"Error fetching fights for {report_code}: {e}")
        import traceback
        traceback.print_exc()
        return {"report_start": 0, "fights": [], "friendlies": [], "player_details": {}}


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
        
        url = "https://www.warcraftlogs.com/api/v2/client"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}"
        }
        
        try:
            response = make_request_with_retry('post', url, json={'query': query, 'variables': variables}, headers=headers)
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
        
        url = "https://www.warcraftlogs.com/api/v2/client"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}"
        }
        
        try:
            response = make_request_with_retry('post', url, json={'query': query, 'variables': variables}, headers=headers)
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
    
    url = "https://www.warcraftlogs.com/api/v2/client"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}"
    }
    
    try:
        response = make_request_with_retry('post', url, json={'query': query, 'variables': variables}, headers=headers)
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
                player_details = fight_data.get("player_details", {})
                
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



@app.route('/api/save-analysis', methods=['POST'])
def save_analysis():
    """Save compressed analysis to Supabase"""
    if not supabase:
        return jsonify({'error': 'Database not configured'}), 500
    
    try:
        data = request.json
        user_id = data.get('user_id')
        analysis_name = data.get('analysis_name')
        analysis_data = data.get('analysis_data')
        retention_days = min(int(data.get('retention_days', 7)), 30)  # Max 30 days
        
        # Compress with Brotli (quality 11 = max compression)
        json_str = json.dumps(analysis_data)
        compressed = brotli.compress(json_str.encode('utf-8'), quality=11)
        compressed_b64 = base64.b64encode(compressed).decode('utf-8')
        
        # Calculate size
        size_bytes = len(compressed_b64.encode('utf-8'))
        
        # Insert into Supabase
        result = supabase.table('saved_analyses').insert({
            'user_id': user_id,
            'analysis_name': analysis_name,
            'guild_name': analysis_data.get('meta', {}).get('guild_name', 'Unknown'),
            'analysis_data': compressed_b64,
            'retention_days': retention_days,
            'size_bytes': size_bytes
        }).execute()
        
        return jsonify({
            'success': True, 
            'id': result.data[0]['id'],
            'compressed_size': size_bytes,
            'original_size': len(json_str)
        })
        
    except Exception as e:
        print(f"Error saving analysis: {str(e)}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/load-analysis/<analysis_id>', methods=['GET'])
def load_analysis(analysis_id):
    """Load and decompress analysis from Supabase"""
    if not supabase:
        return jsonify({'error': 'Database not configured'}), 500
    
    try:
        # Get from Supabase
        result = supabase.table('saved_analyses').select('*').eq('id', analysis_id).single().execute()
        
        # Decompress
        compressed_b64 = result.data['analysis_data']
        compressed = base64.b64decode(compressed_b64)
        json_str = brotli.decompress(compressed).decode('utf-8')
        analysis_data = json.loads(json_str)
        
        return jsonify(analysis_data)
        
    except Exception as e:
        print(f"Error loading analysis: {str(e)}")
        return jsonify({'error': str(e)}), 404


@app.route('/api/user-analyses/<user_id>', methods=['GET'])
def get_user_analyses(user_id):
    """Get all saved analyses for a user"""
    if not supabase:
        return jsonify({'error': 'Database not configured'}), 500
    
    try:
        result = supabase.table('saved_analyses')\
            .select('id, analysis_name, guild_name, created_at, expires_at, retention_days, size_bytes')\
            .eq('user_id', user_id)\
            .order('created_at', desc=True)\
            .execute()
        
        return jsonify(result.data)
        
    except Exception as e:
        print(f"Error getting user analyses: {str(e)}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/delete-analysis/<analysis_id>', methods=['DELETE'])
def delete_analysis(analysis_id):
    """Delete a saved analysis"""
    if not supabase:
        return jsonify({'error': 'Database not configured'}), 500
    
    try:
        supabase.table('saved_analyses').delete().eq('id', analysis_id).execute()
        return jsonify({'success': True})
        
    except Exception as e:
        print(f"Error deleting analysis: {str(e)}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/delete-all-analyses/<user_id>', methods=['DELETE'])
def delete_all_analyses(user_id):
    """Delete all saved analyses for a user"""
    if not supabase:
        return jsonify({'error': 'Database not configured'}), 500
    
    try:
        supabase.table('saved_analyses').delete().eq('user_id', user_id).execute()
        return jsonify({'success': True})
        
    except Exception as e:
        print(f"Error deleting all analyses: {str(e)}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/delete-user-account/<user_id>', methods=['DELETE'])
def delete_user_account(user_id):
    """
    Delete a user account and all associated data.
    This uses the Supabase Admin API to delete the auth user.
    REQUIRES: SUPABASE_SERVICE_ROLE_KEY environment variable
    """
    if not supabase:
        return jsonify({'error': 'Database not configured'}), 500
    
    # Check if we have the service role key
    service_role_key = os.environ.get('SUPABASE_SERVICE_ROLE_KEY')
    if not service_role_key:
        print("[ERROR] SUPABASE_SERVICE_ROLE_KEY not set - cannot delete users!")
        return jsonify({
            'error': 'Server configuration error: Missing admin privileges',
            'details': 'SUPABASE_SERVICE_ROLE_KEY environment variable not set'
        }), 500
    
    deletion_errors = []
    
    # Headers for all admin operations - must use service_role key
    admin_headers = {
        'apikey': service_role_key,
        'Authorization': f'Bearer {service_role_key}',
        'Content-Type': 'application/json',
        'Prefer': 'return=minimal'
    }
    
    try:
        # Step 1: Delete all saved analyses (using service_role key via REST API)
        try:
            url = f"{SUPABASE_URL}/rest/v1/saved_analyses?user_id=eq.{user_id}"
            response = requests.delete(url, headers=admin_headers, timeout=10)
            print(f"[DEBUG] saved_analyses deletion: status={response.status_code}")
            if response.status_code in [200, 204]:
                print(f"[OK] Deleted saved analyses for user {user_id}")
            else:
                error_msg = f"Failed to delete analyses: {response.status_code} - {response.text}"
                print(f"[ERROR] {error_msg}")
                deletion_errors.append(error_msg)
        except Exception as e:
            error_msg = f"Failed to delete analyses: {str(e)}"
            print(f"[ERROR] {error_msg}")
            deletion_errors.append(error_msg)
        
        # Step 2: Delete API credentials (using service_role key via REST API)
        try:
            url = f"{SUPABASE_URL}/rest/v1/api_credentials?user_id=eq.{user_id}"
            response = requests.delete(url, headers=admin_headers, timeout=10)
            print(f"[DEBUG] api_credentials deletion: status={response.status_code}")
            if response.status_code in [200, 204]:
                print(f"[OK] Deleted API credentials for user {user_id}")
            else:
                error_msg = f"Failed to delete credentials: {response.status_code} - {response.text}"
                print(f"[ERROR] {error_msg}")
                deletion_errors.append(error_msg)
        except Exception as e:
            error_msg = f"Failed to delete credentials: {str(e)}"
            print(f"[ERROR] {error_msg}")
            deletion_errors.append(error_msg)
        
        # Step 3: Delete the auth user using Admin API
        try:
            admin_url = f"{SUPABASE_URL}/auth/v1/admin/users/{user_id}"
            response = requests.delete(admin_url, headers=admin_headers, timeout=10)
            
            print(f"[DEBUG] Auth deletion response: status={response.status_code}, body={response.text[:200] if response.text else 'empty'}")
            
            if response.status_code in [200, 204]:
                print(f"[OK] Deleted auth user {user_id}")
            else:
                error_msg = f"Auth API returned {response.status_code}: {response.text}"
                print(f"[ERROR] {error_msg}")
                deletion_errors.append(error_msg)
                
        except Exception as e:
            error_msg = f"Failed to delete auth user: {str(e)}"
            print(f"[ERROR] {error_msg}")
            deletion_errors.append(error_msg)
        
        # If there were any errors, return them
        if deletion_errors:
            return jsonify({
                'success': False,
                'error': 'Partial deletion failure',
                'details': deletion_errors
            }), 500
        
        return jsonify({
            'success': True,
            'message': 'Account and all associated data have been deleted'
        })
        
    except Exception as e:
        print(f"[ERROR] Unexpected error in delete_user_account: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

    except Exception as e:
        print(f"Error deleting user account: {str(e)}")
        return jsonify({'error': str(e)}), 500


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