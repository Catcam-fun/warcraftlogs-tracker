"""
warcraftlogs.py - WarcraftLogs API interactions (token, GraphQL, reports, fights)
"""

import time
import json
import requests
import unicodedata
import base64
from datetime import datetime

# API Endpoints
GRAPHQL_ENDPOINT = "https://wcl-proxy.catcam-fun.workers.dev/api/v2/client"
OAUTH_TOKEN_URL = "https://wcl-proxy.catcam-fun.workers.dev/oauth/token"

# Retry config
MAX_RETRIES = 3
RETRY_BACKOFF_BASE = 1
RETRY_BACKOFF_MAX = 10

# Token cache
_token_cache = {"token": None, "expires_at": 0}


def make_request_with_retry(method, url, max_retries=MAX_RETRIES, timeout=120, **kwargs):
    """Make HTTP request with exponential backoff retry."""
    import time
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
                backoff = min(RETRY_BACKOFF_BASE * (2 ** attempt), RETRY_BACKOFF_MAX)
                print(f"[Retry] Timeout attempt {attempt + 1}, waiting {backoff}s")
                time.sleep(backoff)
        except requests.exceptions.RequestException as e:
            last_exception = e
            if attempt < max_retries:
                backoff = min(RETRY_BACKOFF_BASE * (1.5 ** attempt), RETRY_BACKOFF_MAX)
                time.sleep(backoff)
    raise Exception(f"Request failed after {max_retries + 1} attempts: {last_exception}")

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
    
    # Request new token using Authorization header (required by Cloudflare Worker)
    # Encode credentials as Basic auth
    credentials = f"{client_id}:{client_secret}"
    encoded_credentials = base64.b64encode(credentials.encode()).decode()
    
    headers = {
        'Authorization': f'Basic {encoded_credentials}',
        'Content-Type': 'application/x-www-form-urlencoded'
    }
    
    # Body only contains grant_type
    data = 'grant_type=client_credentials'
    
    try:
        # Use retry logic with increased timeout
        response = make_request_with_retry(
            'post',
            OAUTH_TOKEN_URL,
            data=data,
            headers=headers,
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


def graphql_query(token, query, variables=None, timeout=120, max_retries=3):
    """Execute a GraphQL query against WarcraftLogs V2 API with retry logic.

    timeout/max_retries default to the original generous values (heavy
    reports/fights/deaths queries need them); callers that are best-effort
    and must not stall analysis (e.g. the guild roster) pass a tight
    budget so a slow WCL endpoint degrades instead of hanging for minutes.
    """
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }

    payload = {"query": query}
    if variables:
        payload["variables"] = variables

    try:
        response = make_request_with_retry(
            'post',
            GRAPHQL_ENDPOINT,
            json=payload,
            headers=headers,
            timeout=timeout,
            max_retries=max_retries
        )
        
        data = response.json()
        
        if "errors" in data:
            raise Exception(f"GraphQL errors: {data['errors']}")
        
        return data.get("data", {})
    except Exception as e:
        raise Exception(f"GraphQL query failed: {str(e)}")

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
    PAGE_LIMIT = 100          # matches `members(limit: 100, ...)` in the query
    MAX_PAGES = 25            # 2500-member safety cap
    serverSlug = server.lower().replace(" ", "-").replace("'", "")

    while page <= MAX_PAGES:
        variables = {
            "guildName": guild_name,
            "serverSlug": serverSlug,
            "serverRegion": region.upper(),
            "page": page,
        }

        try:
            # Tight budget: WCL's guild.members endpoint is frequently
            # very slow through the proxy. The roster is best-effort
            # (analysis falls back to counting everyone), so never let it
            # stall for minutes on the default 3x120s retry stack.
            data = graphql_query(token, query, variables, timeout=40, max_retries=1)
        except Exception as e:
            # Don't nuke the roster we've collected — a partial roster
            # still filters
            # correctly for everyone we did fetch; just stop here.
            print(f"Warning: roster page {page} failed ({e}); using {len(all_members)} members fetched so far")
            break

        guild = (data.get("guildData") or {}).get("guild") or {}
        if not guild:
            if page == 1:
                print(f"Warning: Could not fetch guild roster for {guild_name}")
            break

        members_response = guild.get("members") or {}
        members = members_response.get("data") or []
        has_more = members_response.get("has_more_pages", False)

        for member in members:
            name = normalize_character_name(member.get("name"))
            if name:
                all_members.add(name.lower())

        print(f"Fetched page {page}: {len(members)} members (total so far: {len(all_members)})")

        # Keep going while WCL says there's more OR the page came back
        # full (a full page almost always means another page exists —
        # this is the backstop for when has_more_pages is unreliable,
        # which was the original "can't get all pages" bug).
        if not members:
            break
        if not has_more and len(members) < PAGE_LIMIT:
            break
        page += 1

    if not all_members:
        print(f"Warning: Guild {guild_name} has no members or roster not available")
        return set()

    print(f"Successfully fetched {len(all_members)} guild members across {page} page(s)")
    return all_members
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