"""
warcraftlogs.py - WarcraftLogs API interactions (token, GraphQL, reports, fights)
"""

import time
import requests
import unicodedata
import base64
import hashlib
import threading
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

# API Endpoints
GRAPHQL_ENDPOINT = "https://wcl-proxy.catcam-fun.workers.dev/api/v2/client"
OAUTH_TOKEN_URL = "https://wcl-proxy.catcam-fun.workers.dev/oauth/token"

# Retry config
MAX_RETRIES = 3
RETRY_BACKOFF_BASE = 1
RETRY_BACKOFF_MAX = 10

# Token cache, keyed per client credential. A single shared slot would hand
# one user's token (and WCL rate-limit quota) to the next user, and let
# wrong credentials "work" as long as someone else's token was cached.
_token_cache = {}  # sha256(client_id:client_secret) -> {"token", "expires_at"}
_token_lock = threading.Lock()


def make_request_with_retry(method, url, max_retries=MAX_RETRIES, timeout=120, **kwargs):
    """Make HTTP request with exponential backoff retry.

    Client errors (bad credentials, bad query, unknown guild) fail straight
    away since retrying can't fix them; 429 and 5xx/network errors back off.
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
        except requests.exceptions.HTTPError as e:
            last_exception = e
            status = e.response.status_code if e.response is not None else 0
            if 400 <= status < 500 and status != 429:
                break
            if attempt < max_retries:
                retry_after = e.response.headers.get('Retry-After') if e.response is not None else None
                try:
                    backoff = min(float(retry_after), RETRY_BACKOFF_MAX * 3) if retry_after else None
                except ValueError:
                    backoff = None
                time.sleep(backoff or min(RETRY_BACKOFF_BASE * (2 ** attempt), RETRY_BACKOFF_MAX))
        except requests.exceptions.RequestException as e:
            last_exception = e
            if attempt < max_retries:
                backoff = min(RETRY_BACKOFF_BASE * (2 ** attempt), RETRY_BACKOFF_MAX)
                print(f"[Retry] {type(e).__name__} attempt {attempt + 1}, waiting {backoff}s")
                time.sleep(backoff)
    raise Exception(f"Request failed after {attempt + 1} attempt(s): {last_exception}")

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
    cache_key = hashlib.sha256(f"{client_id}:{client_secret}".encode()).hexdigest()
    with _token_lock:
        cached = _token_cache.get(cache_key)
        if cached and time.time() < cached["expires_at"]:
            return cached["token"]

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
        
        token = token_data["access_token"]
        with _token_lock:
            now = time.time()
            for k in [k for k, v in _token_cache.items() if v["expires_at"] <= now]:
                del _token_cache[k]
            # Expire 60 seconds before WCL does, for safety
            _token_cache[cache_key] = {
                "token": token,
                "expires_at": now + token_data.get("expires_in", 3600) - 60,
            }
        return token
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

def get_guild_reports(token, guild_name, server, region, start_date=None, end_date=None):
    """Fetch guild reports via V2 GraphQL, scoped server-side by a date window.

    We deliberately do NOT filter by zoneID. WCL assigns each report a single
    primary zone, so a report that mixes a raid night with Mythic+ dungeons
    gets classified under the dungeon zone and a zoneID filter silently drops
    it along with all its raid pulls. The fight-level RAID_ENCOUNTERS allowlist
    in analyze_fights is the authoritative raid/dungeon separator, so the zone
    filter was redundant and lossy. Date bounds are pushed into the query so we
    only page through one tier's window, not the guild's entire history.
    """
    if start_date == "":
        start_date = None
    if end_date == "":
        end_date = None

    start_ts = None
    end_ts = None
    if start_date:
        start_ts = int(datetime.strptime(start_date, "%Y-%m-%d").timestamp() * 1000)
    if end_date:
        # Inclusive end-of-day for the end date.
        end_ts = int(datetime.strptime(end_date, "%Y-%m-%d").timestamp() * 1000) + 86400000 - 1

    query = """
    query($guildName: String!, $serverSlug: String!, $serverRegion: String!,
          $startTime: Float, $endTime: Float, $page: Int!) {
      reportData {
        reports(guildName: $guildName, guildServerSlug: $serverSlug,
                guildServerRegion: $serverRegion, startTime: $startTime,
                endTime: $endTime, limit: 100, page: $page) {
          data {
            code
            startTime
            endTime
            owner {
              name
            }
          }
        }
      }
    }
    """

    base_vars = {
        "guildName": guild_name,
        "serverSlug": server.lower().replace(" ", "-").replace("'", ""),
        "serverRegion": region.upper(),
        "startTime": start_ts,
        "endTime": end_ts,
    }

    try:
        out = []
        page = 1
        # Cap pages so an unexpected always-full response can't loop forever.
        # A single tier window is realistically a few pages of 100.
        while page <= 50:
            data = graphql_query(token, query, {**base_vars, "page": page})
            rows = (((data.get("reportData") or {}).get("reports") or {})
                    .get("data")) or []
            for rep in rows:
                out.append({
                    "id": rep["code"],
                    "start": rep.get("startTime", 0),
                    "end": rep.get("endTime", 0),
                    "owner": (rep.get("owner") or {}).get("name", ""),
                })
            if len(rows) < 100:
                break
            page += 1
        return out
    except Exception as e:
        raise Exception(f"Failed to fetch guild reports: {str(e)}")


def get_guild_roster(token, guild_name, server, region):
    """Fetch the full guild roster.

    WoW caps guilds at 1000 members and WCL serves 100/page, so the
    roster is at most ~10 pages. WCL's guild.members endpoint is slow
    through the proxy, so we fetch every possible page CONCURRENTLY —
    total wall time is the slowest single page, not the sum. Best-effort:
    a page that fails is skipped (analysis falls back to counting
    everyone if the whole thing comes back empty).
    """
    query = """
    query($guildName: String!, $serverSlug: String!, $serverRegion: String!, $page: Int!) {
      guildData {
        guild(name: $guildName, serverSlug: $serverSlug, serverRegion: $serverRegion) {
          members(limit: 100, page: $page) {
            data { name }
          }
        }
      }
    }
    """

    MAX_PAGES = 12  # 1000-member cap / 100 per page = 10, + margin
    base_vars = {
        "guildName": guild_name,
        "serverSlug": server.lower().replace(" ", "-").replace("'", ""),
        "serverRegion": region.upper(),
    }

    def fetch_page(page):
        try:
            # Bounded per request so one stuck page can't hold the whole
            # (parallel) batch hostage beyond its own timeout.
            data = graphql_query(token, query, {**base_vars, "page": page},
                                  timeout=40, max_retries=1)
            guild = (data.get("guildData") or {}).get("guild") or {}
            members = ((guild.get("members") or {}).get("data")) or []
            return page, members, None
        except Exception as e:
            return page, None, str(e)

    all_members = set()
    pages_fetched = 0
    with ThreadPoolExecutor(max_workers=MAX_PAGES) as executor:
        futures = {executor.submit(fetch_page, p): p for p in range(1, MAX_PAGES + 1)}
        for fut in as_completed(futures):
            page, members, err = fut.result()
            if err:
                print(f"Warning: roster page {page} failed ({err})")
                continue
            if members:
                pages_fetched += 1
                for member in members:
                    name = normalize_character_name(member.get("name"))
                    if name:
                        all_members.add(name.lower())

    if not all_members:
        print(f"Warning: Guild {guild_name} has no members or roster not available")
        return set()

    print(f"Successfully fetched {len(all_members)} guild members across {pages_fetched} page(s)")
    return all_members
def get_fights(token, report_code):
    """Fetch a report's fights, players (with class/spec), and ability names.

    One GraphQL round-trip per report: ability names used to be a second,
    separate query. Returns
      {"report_start", "fights", "friendlies", "player_details", "abilities"}
    or the same shape with empty values if the report can't be read.
    """
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
            abilities {
              gameID
              name
              type
              icon
            }
          }
          playerDetails(startTime: 0, endTime: 999999999999)
        }
      }
    }
    """
    empty = {"report_start": 0, "fights": [], "friendlies": [], "player_details": {}, "abilities": {},
             "ability_schools": {}, "ability_icons": {}}

    try:
        data = graphql_query(token, query, {"code": report_code})
        report = (data.get("reportData") or {}).get("report") or {}
        if not report:
            return empty

        master = report.get("masterData") or {}
        fights = [{
            "id": f.get("id"),
            "start_time": f.get("startTime"),
            "end_time": f.get("endTime"),
            "name": f.get("name"),
            "boss": f.get("encounterID"),
            "difficulty": f.get("difficulty"),
            "kill": f.get("kill"),
            "zoneID": (f.get("gameZone") or {}).get("id"),
            "friendlyPlayers": f.get("friendlyPlayers") or [],  # IDs of players in THIS fight
        } for f in report.get("fights") or []]

        friendlies = [{
            "id": a.get("id"),
            "name": normalize_character_name(a.get("name")),
            "type": a.get("subType"),  # class name
        } for a in master.get("actors") or [] if a.get("type") == "Player"]

        abilities = {a["gameID"]: a["name"] for a in master.get("abilities") or []
                     if a.get("gameID") and a.get("name")}
        # Spell school bitmask (1 = physical, anything else includes magic).
        ability_schools = {}
        for a in master.get("abilities") or []:
            try:
                ability_schools[a["gameID"]] = int(a.get("type") or 0)
            except (TypeError, ValueError):
                pass

        # Icon file names ("spell_shadow_nethercloak.jpg"), for the results page.
        ability_icons = {a["gameID"]: a["icon"] for a in master.get("abilities") or []
                         if a.get("gameID") and a.get("icon")}

        # playerDetails: { data: { playerDetails: { tanks: [], healers: [], dps: [] } } }
        player_spec_map = {}
        details = ((report.get("playerDetails") or {}).get("data") or {}).get("playerDetails") or {}
        for role in ("tanks", "healers", "dps"):
            for player in details.get(role) or []:
                actor_id = player.get("id")
                if not actor_id:
                    continue
                specs = player.get("specs") or []  # [{"spec": "Brewmaster", "count": 31}]
                player_spec_map[actor_id] = {
                    "class": player.get("type", ""),
                    "spec": specs[0].get("spec", "Unknown") if specs else "Unknown",
                    "name": normalize_character_name(player.get("name", "")),
                }

        return {
            "report_start": report.get("startTime", 0),
            "fights": fights,
            "friendlies": friendlies,
            "player_details": player_spec_map,
            "abilities": abilities,
            "ability_schools": ability_schools,
            "ability_icons": ability_icons,
        }
    except Exception as e:
        print(f"Error fetching fights for {report_code}: {e}")
        return empty
