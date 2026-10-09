#!/usr/bin/env python3
"""
app.py - Flask API routes for Floor Pov Death Tracker
Imports from: warcraftlogs, analysis, features, supabase_client, auth
"""

from flask import Flask, request, jsonify, Response, g
from flask_cors import CORS
from collections import defaultdict
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import os
import re
import secrets
import time
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Import from modules
from warcraftlogs import (
    get_access_token, get_guild_reports, get_guild_roster,
    get_fights, get_report_fights, normalize_character_name
)
from analysis import (
    get_report_deaths_bulk, get_main_character,
    analyze_fights, dedup_pulls,
    find_mass_death_start, rank_pull_deaths, resolve_report_window, drop_saves_that_died
)
import defensives
import boss_spell_text
from features import CHEAT_DEATH_ABILITY_IDS
from auth import require_user, verify_token, forget_token, _bearer_token
from cache import (report_meta_cache, report_fights_cache, report_deaths_cache as deaths_lru,
                   report_defensive_cache as defensive_lru, report_recap_cache as recap_lru, flush_writes)
from ratelimit import RateLimiter, limit
import supabase_client
import origin
from streaming import with_heartbeat
from bodies import BodyTooLarge, json_body

# A report whose last event is older than this is treated as finished and
# its fights/deaths are cached; anything newer may still be live-logging.
REPORT_CACHE_MIN_AGE_MS = 2 * 60 * 60 * 1000

# Reports read at once per analysis (each runs its own few queries at once).
# WCL's own rate limit is per API key, so this stays modest.
REPORT_FETCH_WORKERS = 6

share_limiter = RateLimiter(max_calls=20, per_seconds=3600)
analyze_limiter = RateLimiter(max_calls=60, per_seconds=3600)
save_limiter = RateLimiter(max_calls=30, per_seconds=3600)

# =============================================================================
# FLASK SETUP
# =============================================================================

app = Flask(__name__)
# Bodies are compressed analyses; anything larger than this is abuse.
app.config['MAX_CONTENT_LENGTH'] = 25 * 1024 * 1024

# Comma-separated list of allowed site origins, e.g.
# "https://floorpov.com,https://www.floorpov.com". Defaults to any origin
# (requests are authenticated with bearer tokens, not cookies).
_origins = [o.strip() for o in os.environ.get('ALLOWED_ORIGINS', '*').split(',') if o.strip()]
CORS(app,
     resources={r"/api/*": {"origins": _origins}},
     allow_headers=["Content-Type", "Authorization"],
     methods=["GET", "POST", "DELETE", "OPTIONS"])


# Paths the Lambda Web Adapter calls itself, from inside the function: its
# readiness check and the pass-through path for scheduled warm-up events.
_UNLOCKED = {('GET', '/api/health'), ('POST', '/events')}


@app.before_request
def _only_from_cloudfront():
    """On AWS, refuse requests that didn't come through our CloudFront."""
    if origin.secret() and (request.method, request.path) not in _UNLOCKED \
            and not origin.from_cloudfront():
        return jsonify({"success": False, "error": "Forbidden"}), 403


@app.errorhandler(BodyTooLarge)
def _body_too_large(_e):
    return jsonify({"success": False, "error": "This analysis is too large to send."}), 413


@app.route('/events', methods=['POST'])
def warm_event():
    """Scheduled warm-up ping (EventBridge, via the adapter). Starting the function is the point."""
    return '', 204


# =============================================================================
# MAIN ANALYSIS ENDPOINT
# =============================================================================

# Killing blows with no description in the game data.
BASIC_ABILITY_TEXT = {
    "Melee": "A melee attack from an enemy.",
    "Falling": "Fall damage.",
}


@app.route('/api/analyze', methods=['POST'])
@limit(analyze_limiter, "Too many analyses from this network in the last hour. Please wait a bit.")
def analyze():
    """Main API endpoint for analyzing WarcraftLogs data using V2 API with SSE progress"""

    # Extract config BEFORE the generator to avoid request context issues
    config = request.get_json(silent=True)
    if not isinstance(config, dict):
        return jsonify({"error": "Invalid request"}), 400
    # Cheat-death detection is a signed-in feature; the checkbox in the UI
    # isn't enough, since a shared config or a direct call can set the flag.
    signed_in = bool(verify_token(_bearer_token()))

    def generate():
        try:
            # Extract configuration
            client_id = config.get('clientId')
            client_secret = config.get('clientSecret')
            guild_name = config.get('guildName')
            server = config.get('server')
            region = config.get('region')
            fight_zone = config.get('fightZone')
            selected_raid = config.get('selectedRaid')
            difficulty = config.get('difficulty')
            # Deaths per pull that count.
            max_cutoff = min(max(int(config.get('maxCutoff', 5) or 5), 1), 10)
            start_date = config.get('startDate')
            if start_date == "" or start_date is None:
                start_date = None
            end_date = config.get('endDate')
            if end_date == "" or end_date is None:
                end_date = None
            author_filters = config.get('authorFilters', [])
            character_groups = config.get('characterGroups', {})
            enable_cheat_death = bool(config.get('enableCheatDeath', False)) and signed_in
            # Only players on the guild roster count (configs from before the toggle: on).
            roster_only = config.get('rosterOnly', True) is not False
            
            # Validate required fields
            if not all([client_id, client_secret, guild_name, server, region]):
                yield f"data: {json.dumps({'error': 'Missing required fields'})}\n\n"
                return
            
            if config.get('enableCheatDeath') and not signed_in:
                yield f"data: {json.dumps({'stage': 'auth', 'message': 'Cheat-death detection needs a signed-in account; skipping it'})}\n\n"

            # Get OAuth2 token
            yield f"data: {json.dumps({'stage': 'auth', 'message': 'Authenticating with WarcraftLogs...'})}\n\n"
            try:
                token = get_access_token(client_id, client_secret)
            except Exception as e:
                yield f"data: {json.dumps({'error': f'Authentication failed: {str(e)}'})}\n\n"
                return
            
            # Get guild roster for filtering (skipped when the roster filter is off)
            guild_roster = set()
            if not roster_only:
                yield f"data: {json.dumps({'stage': 'roster', 'message': 'Counting everyone in the reports (guild roster filter off)'})}\n\n"
            else:
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

            # Only count players who are on the guild roster. With the filter
            # off, or if the roster couldn't be fetched, everyone counts.
            def is_guild_member(nm):
                if not guild_roster:
                    return True
                return normalize_character_name(nm or "").lower() in guild_roster

            # Get guild reports. The tier's hard date window scopes the fetch
            # (user dates may narrow it but never widen past the tier); we no
            # longer filter by zoneID, which dropped mixed raid+dungeon reports.
            win_start, win_end = resolve_report_window(selected_raid, start_date, end_date)
            yield f"data: {json.dumps({'stage': 'reports', 'message': 'Fetching guild reports...'})}\n\n"
            reports = get_guild_reports(token, guild_name, server, region, win_start, win_end)
            yield f"data: {json.dumps({'stage': 'reports', 'message': f'Found {len(reports)} reports'})}\n\n"
            
            # Filter by author
            if author_filters:
                reports = [r for r in reports if r.get('owner') in author_filters]
                yield f"data: {json.dumps({'stage': 'reports', 'message': f'After author filter: {len(reports)} reports'})}\n\n"
            
            if not reports:
                yield f"data: {json.dumps({'error': 'No reports found matching criteria'})}\n\n"
                return
            
            # Collect all fights. Every report's light fight list (fights only) is read
            # in parallel, duplicate pulls are dropped, and only the reports pulls are
            # kept from are read in full (players, specs, abilities). Finished reports
            # come from the cache.
            yield f"data: {json.dumps({'stage': 'fights', 'message': 'Collecting fights from reports...'})}\n\n"
            all_fights_raw = []
            report_encounters = {}
            finished_before = int(time.time() * 1000) - REPORT_CACHE_MIN_AGE_MS
            report_finished = {rep["id"]: bool(rep.get("end")) and rep["end"] < finished_before
                               for rep in reports}

            def fetch_light_fights(rep):
                rid = rep["id"]
                if report_finished[rid]:
                    cached = report_fights_cache.get(rid)
                    if cached is not None:
                        return rep, cached
                light = get_report_fights(token, rid)
                if report_finished[rid] and light.get("fights"):
                    report_fights_cache.set(rid, light)
                return rep, light

            def fetch_report_meta(rid):
                if report_finished[rid]:
                    cached = report_meta_cache.get(rid)
                    if cached is not None:
                        return rid, cached
                meta = get_fights(token, rid)
                if report_finished[rid] and meta.get("fights"):
                    report_meta_cache.set(rid, meta)
                return rid, meta

            with ThreadPoolExecutor(max_workers=REPORT_FETCH_WORKERS) as executor:
                futures = [executor.submit(fetch_light_fights, rep) for rep in reports]
                for done, future in enumerate(as_completed(futures), 1):
                    rep, light = future.result()
                    rid = rep["id"]
                    yield f"data: {json.dumps({'stage': 'fights', 'message': f'Read report {done}/{len(reports)}'})}\n\n"

                    fights = light.get("fights", [])
                    if not fights:
                        continue
                    # Every boss encounter of the report, kept or not: each one resets long cooldowns.
                    report_encounters[rid] = [(f['start_time'], f['end_time']) for f in fights if f.get('boss')]
                    report_abs_start = light.get("report_start") or rep["start"]
                    for fight in analyze_fights(fights, fight_zone, difficulty, selected_raid):
                        all_fights_raw.append({
                            'reportId': rid,
                            'fight': fight,
                            'boss_name': fight.get('name', 'Unknown'),
                            'boss_id': fight.get('boss', 0),
                            'is_kill': bool(fight.get('kill')),
                            'abs_start': report_abs_start + fight['start_time'],
                            'abs_end': report_abs_start + fight['end_time'],
                            'report_abs_start': report_abs_start,
                        })

            all_fights_raw.sort(key=lambda x: (x['abs_start'], x['reportId'], x['fight']['id']))

            # Deduplicate, then read the kept pulls' reports in full. A report that can't
            # be read in full gives its pulls to another log's copy, as if it weren't listed.
            yield f"data: {json.dumps({'stage': 'dedup', 'message': 'Removing duplicate pulls...'})}\n\n"
            metas, unreadable = {}, set()
            while True:
                # The earliest copy of each pull (ties by report code, so the copy kept never
                # depends on which report was read first), unless it was cut short.
                all_fights_deduped = dedup_pulls([fd for fd in all_fights_raw if fd['reportId'] not in unreadable])
                missing = sorted({fd['reportId'] for fd in all_fights_deduped} - set(metas))
                if not missing:
                    break
                with ThreadPoolExecutor(max_workers=REPORT_FETCH_WORKERS) as executor:
                    for rid, meta in executor.map(fetch_report_meta, missing):
                        if meta.get("fights"):
                            metas[rid] = meta
                        else:
                            unreadable.add(rid)
            yield f"data: {json.dumps({'stage': 'fights', 'message': f'Collected {len(all_fights_raw)} total fights'})}\n\n"

            if not all_fights_deduped:
                diff_names = {'3': 'Normal', '4': 'Heroic', '5': 'Mythic'}
                diff_label = diff_names.get(str(difficulty), f'difficulty {difficulty}')
                yield f"data: {json.dumps({'error': f'No {diff_label} fights found in the reports. Check that the selected difficulty is available for this raid.'})}\n\n"
                return

            for fd in all_fights_deduped:
                meta = metas[fd['reportId']]
                full = {f['id']: f for f in meta.get("fights", [])}
                fd.update({
                    'fight': full.get(fd['fight']['id'], fd['fight']),
                    'friendlies': meta.get("friendlies", []),
                    'ability_map': meta.get("abilities", {}),
                    'ability_schools': meta.get("ability_schools", {}),
                    'ability_icons': meta.get("ability_icons", {}),
                    'player_details': meta.get("player_details", {}),
                })

            yield f"data: {json.dumps({'stage': 'dedup', 'message': f'After deduplication: {len(all_fights_deduped)} unique fights'})}\n\n"
            
            # Process deaths
            yield f"data: {json.dumps({'stage': 'deaths', 'message': 'Processing death events...'})}\n\n"
            counted_death_events = defaultdict(list)
            # For the results page: icon of every killing blow's spell, by spell
            # ID (names aren't unique: a boss's Tempest isn't the Shaman's), and
            # what each defensive does (from the catalog of the report's patch).
            report_icons_by_id = {}
            ability_info = {}
            for fd in all_fights_deduped:
                for aid, icon in fd.get('ability_icons', {}).items():
                    report_icons_by_id.setdefault(str(aid), icon)
            pull_participation = defaultdict(set)
            boss_participation = defaultdict(lambda: defaultdict(set))
            pull_counter_by_boss = defaultdict(int)
            
            # Group fights by report
            fights_by_report = defaultdict(list)
            for fight_data in all_fights_deduped:
                fights_by_report[fight_data['reportId']].append(fight_data)
            
            # Fetch deaths in parallel
            yield f"data: {json.dumps({'stage': 'deaths', 'message': f'Fetching deaths for {len(fights_by_report)} reports...'})}\n\n"
            report_deaths_cache = {}
            
            def counted_by_fight(deaths, friendlies):
                """{fightID: [(death ts, log name)]}: the deaths that can count (within the deaths
                tracked, not in a wipe, guild members), the only ones whose defensives are shown."""
                log_names = {f.get("id"): f.get("logName") or f.get("name") for f in friendlies}
                out = {}
                for fid, ds in deaths.items():
                    ds = sorted(drop_saves_that_died(ds), key=lambda d: d["timestamp"])
                    out[fid] = [(d["timestamp"], log_names.get(d.get("targetID")))
                                for d, (slot, in_wipe) in zip(ds, rank_pull_deaths(ds))
                                if slot <= max_cutoff and not in_wipe and not d.get("isCheatDeath")
                                and is_guild_member(normalize_character_name(d.get("targetName") or ""))]
                return out

            def fetch_report_deaths(rid, report_fights):
                """Deaths, defensive data (casts, buffs, talents) and the hits before the deaths that
                can count, for one report. Independent queries run at once; finished reports are cached."""
                try:
                    sample_fight_data = report_fights[0]
                    friendlies = sample_fight_data['friendlies']
                    ability_map = sample_fight_data['ability_map']
                    fights_list = [fd['fight'] for fd in report_fights]
                    fight_ids = sorted(f['id'] for f in fights_list)
                    first_start = min(f['start_time'] for f in fights_list)
                    last_end = max(f['end_time'] for f in fights_list)
                    finished = report_finished.get(rid)
                    # Defensive casts, auras, talents and consumable heals, judged by
                    # the patch live when it was logged.
                    cat = defensives.catalog_for(sample_fight_data.get('report_abs_start'))

                    # With cheat deaths on, the list of effects is part of the key, so adding one refetches.
                    cache_key = (rid, tuple(fight_ids), bool(enable_cheat_death),
                                 tuple(sorted(CHEAT_DEATH_ABILITY_IDS)) if enable_cheat_death else None)
                    deaths = deaths_lru.get(cache_key) if finished else None
                    ik_key = (rid, tuple(fight_ids), "instakills")
                    instakills = recap_lru.get(ik_key) if finished else None

                    def def_key(dead):
                        # "since-last-encounter": casts now reach back to the last boss encounter's
                        # end (cast_lookback), so rows cached over the shorter span aren't reused.
                        return (rid, tuple(fight_ids), tuple(sorted(dead)), cat.patch, defensives.CATALOG_FINGERPRINT,
                                "pull-specs", "since-last-encounter")

                    def dead_in(ds):
                        return {d.get("targetID") for dl in ds.values() for d in dl if d.get("targetID")}

                    def_data = defensive_lru.get(def_key(dead_in(deaths))) if finished and deaths is not None else None
                    def_error = hits_error = None
                    combatants = None
                    if deaths is None:
                        # Talent loadouts first, alone: the cheapest first query on a cold report (~2
                        # points; Deaths or Casts first cost 4-17). The report then stays warm 10-30 s,
                        # so the queries sent right after it cost about 1-3.
                        try:
                            combatants = defensives.fetch_combatants(token, rid, fight_ids, first_start, last_end)
                        except Exception as e:
                            def_error = e
                        deaths = get_report_deaths_bulk(token, rid, fights_list, friendlies, ability_map,
                                                        enable_cheat_death)
                        if finished:
                            deaths_lru.set(cache_key, deaths)
                        def_data = defensive_lru.get(def_key(dead_in(deaths))) if finished else None

                    counted = counted_by_fight(deaths, friendlies)
                    if not any(counted.values()):
                        # No death here can count, so nothing reads this report's defensives or hits.
                        return rid, deaths, defensives.filter_defensive_raw({}, ()), {}, None

                    # The windows carry the heals a killing hit can set off and the aura events of the
                    # max-health auras the hits list: rows cached before them (or with other lists of those
                    # IDs) are not reused. Only this key changes, so the report's other cached data (meta,
                    # fights, deaths, defensives) stays valid.
                    win_key = (rid, tuple((fid, tuple(c)) for fid, c in sorted(counted.items()) if c),
                               "lethal-window", defensives.LETHAL_WINDOW_MS,
                               "window-extras", defensives.WINDOW_EXTRAS_KEY)
                    windows = recap_lru.get(win_key) if finished else None
                    # One query at a time: after the first one on a report, WCL charges about a
                    # quarter less for the rest sent one by one than all at once.
                    if def_data is None and def_error is None:
                        try:
                            dead = dead_in(deaths)
                            def_data = defensives.filter_defensive_raw(defensives.fetch_defensive_raw(
                                token, rid, fight_ids, first_start, last_end, cat, combatants,
                                prev_end=max([end for _, end in report_encounters.get(rid, []) if end <= first_start],
                                             default=0)), dead, cat)
                            if finished:
                                defensive_lru.set(def_key(dead), def_data)
                        except Exception as e:
                            # Deaths still count; this report just lacks defensive detail.
                            def_error = e
                            def_data = None
                    if instakills is None:
                        try:
                            instakills = defensives.fetch_instakills(token, rid, fight_ids, first_start, last_end)
                            if finished:
                                recap_lru.set(ik_key, instakills)
                        except Exception as e:
                            hits_error = e
                    # The seconds before each death that can count: one request, one block per pull.
                    if windows is None and hits_error is None:
                        try:
                            windows = defensives.fetch_death_windows(token, rid, sorted(counted.items()))
                            if finished:
                                recap_lru.set(win_key, windows)
                        except Exception as e:
                            hits_error = e
                    if def_error:
                        print(f"[WARN] Defensive data unavailable for report {rid}: {def_error}")

                    hits = None
                    if hits_error is None:
                        hits = defensives.merge_hits(windows, instakills)
                    else:
                        print(f"[WARN] Hits before deaths unavailable for report {rid}: {hits_error}")

                    return rid, deaths, def_data, hits, None
                except Exception as e:
                    print(f"[ERROR] Error fetching data for report {rid}: {str(e)}")
                    fights_list = [fd['fight'] for fd in report_fights]
                    return rid, {f['id']: [] for f in fights_list}, None, None, str(e)
            
            total_reports = len(fights_by_report)
            completed = 0
            failed_reports = []
            
            report_defensive_data = {}
            report_hits = {}
            
            with ThreadPoolExecutor(max_workers=8) as executor:
                future_to_rid = {
                    executor.submit(fetch_report_deaths, rid, report_fights): rid
                    for rid, report_fights in fights_by_report.items()
                }
                
                for future in as_completed(future_to_rid):
                    rid, deaths, def_data, hits, error = future.result()
                    if error:
                        failed_reports.append(rid)
                    report_deaths_cache[rid] = deaths
                    report_defensive_data[rid] = def_data
                    report_hits[rid] = hits
                    completed += 1
                    
                    if completed % 5 == 0 or completed == total_reports:
                        yield f"data: {json.dumps({'stage': 'deaths', 'message': f'Fetching deaths from report {completed}/{total_reports}'})}\n\n"
            
            if failed_reports:
                yield f"data: {json.dumps({'stage': 'deaths', 'message': f'Warning: {len(failed_reports)} report(s) could not be read; results may be incomplete'})}\n\n"
            partial = [r for r in fights_by_report
                       if r not in failed_reports and (report_defensive_data.get(r) is None or report_hits.get(r) is None)]
            if partial:
                msg = (f'Warning: defensive details missing for {len(partial)} report(s); '
                       'WarcraftLogs may be rate-limiting this API key. Try again in a while.')
                yield f"data: {json.dumps({'stage': 'deaths', 'message': msg})}\n\n"
            yield f"data: {json.dumps({'stage': 'processing', 'message': f'Processing {len(all_fights_deduped)} fights...'})}\n\n"
            
            # Whether each report marks AoE hits at all (older logs don't).
            aoe_known = {rid: defensives.logs_mark_aoe(h) for rid, h in report_hits.items() if h is not None}
            total_deaths = 0
            pullCutoffTimestamps = {}
            
            for fight_idx, fight_data in enumerate(all_fights_deduped, 1):
                if fight_idx % 10 == 0:
                    yield f"data: {json.dumps({'stage': 'processing', 'message': f'Processing fight {fight_idx}/{len(all_fights_deduped)} - {total_deaths} deaths found'})}\n\n"
                
                rid = fight_data['reportId']
                fight = fight_data['fight']
                boss_name = fight_data['boss_name']
                boss_id = fight_data['boss_id']
                is_kill = fight_data['is_kill']
                report_abs_start = fight_data['report_abs_start']
                friendlies = fight_data['friendlies']
                player_details = fight_data.get("player_details", {})
                friendly_class = {f.get("id"): f.get("type") for f in friendlies}
                friendly_names_by_id = {f.get("id"): f.get("name") for f in friendlies}
                
                pull_counter_by_boss[boss_id] += 1
                seq_no = pull_counter_by_boss[boss_id]
                fid = fight['id']
                # A report we couldn't read has unknown deaths, not zero:
                # leave its pulls out rather than count them as deathless.
                if rid in failed_reports:
                    continue
                
                # FIXED: Only count players who were ACTUALLY in this fight
                fight_parts = set()
                friendly_player_ids = set(fight.get('friendlyPlayers', []))
                
                if friendly_player_ids:
                    # Use the specific player IDs from this fight
                    for friendly in friendlies:
                        if friendly.get('id') in friendly_player_ids:
                            name = friendly.get('name')
                            if name:
                                fight_parts.add(name)
                else:
                    # Fallback: if friendlyPlayers not available, use all friendlies
                    for friendly in friendlies:
                        name = friendly.get('name')
                        if name:
                            fight_parts.add(name)
                
                # A Warlock in the pull means a Soulwell's Healthstones for everyone.
                soulwell = any(f.get("type") == "Warlock" and (not friendly_player_ids or f.get("id") in friendly_player_ids)
                               for f in friendlies)

                for p in fight_parts:
                    if not is_guild_member(p):
                        continue
                    main_char = get_main_character(p, character_groups)
                    pull_key = f"{rid}_{fid}"
                    pull_participation[main_char].add(pull_key)
                    boss_participation[boss_name][main_char].add(pull_key)
                
                # Cheat deaths cached before they carried their spell ID: find it by name.
                cheat_ids = {n: aid for aid in CHEAT_DEATH_ABILITY_IDS
                             if (n := fight_data['ability_map'].get(aid) or fight_data['ability_map'].get(str(aid)))}
                deaths_for_fight = report_deaths_cache.get(rid, {}).get(fid, [])
                deaths_sorted_all = sorted(drop_saves_that_died(deaths_for_fight), key=lambda d: d["timestamp"])
                slots = rank_pull_deaths(deaths_sorted_all)
                
                for ev, (slot, in_wipe) in zip(deaths_sorted_all, slots):
                    target_name = normalize_character_name(ev.get("targetName", "Unknown"))
                    if not is_guild_member(target_name):
                        continue
                    original_char = target_name
                    main_char = get_main_character(target_name, character_groups)
                    target_id = ev.get("targetID")
                    
                    player_class = None
                    player_spec = None
                    if target_id and target_id in player_details:
                        player_class = player_details[target_id].get("class", None)
                        player_spec = player_details[target_id].get("spec", None)
                    
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
                        "absTs": report_abs_start + ev["timestamp"],
                        "timestamp": ev["timestamp"] - fight['start_time'],
                        "abilityName": ev.get("abilityName", "Unknown"),
                        "abilityId": ev.get("abilityId") or ev.get("abilityGameID")
                        or (cheat_ids.get(ev.get("abilityName")) if ev.get("isCheatDeath") else None),
                        "isCheatDeath": ev.get("isCheatDeath", False),
                        "slot": slot,
                        "inWipe": in_wipe,
                        "class": player_class,
                        "spec": player_spec
                    }
                    
                    def_data = report_defensive_data.get(rid)
                    # Defensives are shown only for deaths that can count.
                    if def_data and target_id and not death_event["isCheatDeath"] and slot <= max_cutoff \
                            and not in_wipe:
                        death_args = dict(
                            player_id=target_id,
                            player_class=friendly_class.get(target_id),
                            # The spec they played in this pull, not the report's main one.
                            spec=defensives.pull_spec(def_data, fid, target_id, player_spec),
                            fight_id=fid,
                            fight_start=fight['start_time'],
                            death_ts=ev["timestamp"],
                            indexed=def_data,
                            ability_names=fight_data['ability_map'],
                            actor_names=friendly_names_by_id,
                            hits=(report_hits.get(rid) or {}).get(target_id, [])
                            if report_hits.get(rid) is not None else None,
                            ability_schools=fight_data.get('ability_schools', {}),
                            cat=defensives.catalog_for(report_abs_start),
                            aoe_known=aoe_known.get(rid, True),
                            armor_k=defensives.armor_constant(fight.get('boss'), fight.get('difficulty')),
                            soulwell=soulwell,
                            # Presses in the report's other pulls count with that pull's talents.
                            pull_starts={fd['fight']['id']: fd['fight']['start_time']
                                         for fd in fights_by_report.get(rid, [])},
                            encounters=report_encounters.get(rid),
                        )
                        death_event['defensives'] = defensives.analyze_death(**death_args)
                        cat = defensives.catalog_for(report_abs_start)
                        d = death_event['defensives']
                        for name in ([x["name"] for k in ("active", "available", "cooldown") for x in d[k]]
                                     + list((d.get("survival") or {}).get("wouldSave", {}))
                                     + [d[k]["name"] for k in ("healthstone", "potion") if d.get(k, {}).get("name")]):
                            if name not in ability_info:
                                ability_info[name] = defensives.ability_info(cat, name)

                    counted_death_events[main_char].append(death_event)
                    total_deaths += 1
                
                pull_key = f"{rid}_{fid}"
                pullCutoffTimestamps[pull_key] = {}
                
                fight_start = fight['start_time']
                real_deaths_only = [
                    {**d, "timestamp": d["timestamp"] - fight_start}
                    for d in deaths_sorted_all 
                    if not d.get("isCheatDeath", False)
                ]
                
                for cutoff_val in range(1, len(real_deaths_only) + 1):
                    cutoff_idx = cutoff_val - 1
                    mass_death_start = find_mass_death_start(cutoff_idx, real_deaths_only)
                    
                    if mass_death_start is not None:
                        pullCutoffTimestamps[pull_key][cutoff_val] = mass_death_start
                    else:
                        pullCutoffTimestamps[pull_key][cutoff_val] = real_deaths_only[cutoff_idx]["timestamp"]
            
            yield f"data: {json.dumps({'stage': 'complete', 'message': f'Analysis complete! Tracked {total_deaths} deaths across {len(counted_death_events)} players'})}\n\n"
            
            pull_participation_json = {p: list(s) for p, s in pull_participation.items()}
            boss_participation_json = {
                b: {p: list(s2) for p, s2 in players.items()}
                for b, players in boss_participation.items()
            }
            
            response = {
                "meta": {
                    "guild_name": guild_name,
                    "maxCutoff": max_cutoff,
                    "authorFilters": author_filters,
                    "startDate": start_date,
                    "endDate": end_date,
                    "zone": fight_zone,
                    "difficulty": difficulty,
                    "generatedAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "characterGroups": character_groups,
                    "reportCount": len(reports),
                    "cheatDeathEnabled": enable_cheat_death,
                    "rosterOnly": roster_only,
                    "failedReports": failed_reports,
                },
                "events": counted_death_events,
                "pullParticipation": pull_participation_json,
                "bossParticipation": boss_participation_json,
                "pullCutoffTimestamps": pullCutoffTimestamps,
                # Defensives, externals and consumables, by name (game data).
                "icons": {n: i for n in ability_info if (i := defensives.icon_name(n))},
                # Killing blows, by spell ID (the report's own icon for that spell).
                "abilityIcons": {str(e["abilityId"]): i for evs in counted_death_events.values() for e in evs
                                 if e.get("abilityId") and (i := defensives.clean_icon(report_icons_by_id.get(str(e["abilityId"]))))},
                "abilityInfo": {n: v for n, v in ability_info.items() if v},
                # In-game description of each killing blow's spell, by spell ID.
                "abilityText": {str(e["abilityId"]): t for evs in counted_death_events.values() for e in evs
                                if e.get("abilityId") and (t := boss_spell_text.text_for(e["abilityId"])
                                                           or BASIC_ABILITY_TEXT.get(e["abilityName"]))},
            }
            
            yield f"data: {json.dumps({'result': response})}\n\n"
            # Lambda freezes the function once the response ends: finish the cache writes first.
            flush_writes()
        
        except Exception as e:
            print(f"Error in analyze: {str(e)}")
            import traceback
            traceback.print_exc()
            yield f"data: {json.dumps({'error': str(e)})}\n\n"
    
    return Response(with_heartbeat(generate()), mimetype='text/event-stream', headers={
        'Cache-Control': 'no-cache',
        'X-Accel-Buffering': 'no'
    })


# =============================================================================
# SHARING (72h links, stored compressed in Supabase)
# =============================================================================

SHARE_ID_RE = re.compile(r'^[A-Za-z0-9_-]{6,32}$')
SAVED_ID_RE = re.compile(r'^[0-9a-fA-F-]{36}$')


def _looks_like_analysis(data):
    return isinstance(data, dict) and isinstance(data.get('events'), dict)


@app.route('/api/share', methods=['POST'])
@limit(share_limiter, "Too many share links from this network in the last hour. Please wait a bit.")
def share_results():
    """Create a short share link. Credentials are stripped server-side."""
    body = json_body() or {}
    data = body.get('data')
    if not _looks_like_analysis(data):
        return jsonify({"success": False, "error": "Nothing to share"}), 400

    user_id = verify_token(_bearer_token())  # optional: lets account deletion remove it
    share_id = secrets.token_urlsafe(9)
    result = supabase_client.store_share(share_id, data, body.get('config'), user_id)
    if "error" in result:
        return _storage_response(result)
    # `ephemeral`: kept only in this server's memory (database unavailable),
    # so the link stops working when the server restarts or sleeps.
    return jsonify({"success": True, "shareId": share_id, "expiresAt": result["expires_at"],
                    "ephemeral": bool(result.get("ephemeral"))})


@app.route('/api/shared/<share_id>', methods=['GET'])
def get_shared(share_id):
    if not SHARE_ID_RE.match(share_id or ''):
        return jsonify({"success": False, "error": "Share not found or expired"}), 404
    share = supabase_client.get_share(share_id)
    if not share:
        return jsonify({"success": False, "error": "Share not found or expired (links last 72 hours)"}), 404
    return jsonify({"success": True, "data": share["data"], "config": share["config"],
                    "timestamp": share["created_at"]})


# =============================================================================
# SAVED ANALYSES (signed-in users, max 5 each)
# =============================================================================

def _storage_response(result, ok_status=200):
    if "error" not in result:
        return jsonify(result), ok_status
    status = {"limit": 409, "too_large": 413, "not_found": 404}.get(result.get("code"), 500)
    return jsonify({"success": False, **result}), status


@app.route('/api/saved', methods=['GET'])
@require_user
def list_saved():
    return _storage_response(supabase_client.get_user_analyses(g.user_id))


@app.route('/api/saved', methods=['POST'])
@require_user
@limit(save_limiter, "Too many saves in the last hour. Please wait a bit.")
def create_saved():
    body = json_body() or {}
    data = body.get('data')
    if not _looks_like_analysis(data):
        return jsonify({"success": False, "error": "Nothing to save"}), 400
    return _storage_response(supabase_client.save_analysis(
        user_id=g.user_id,
        analysis_name=body.get('name'),
        guild_name=(data.get('meta') or {}).get('guild_name'),
        analysis_data=data,
        config=body.get('config'),
        retention_days=body.get('retentionDays', 30),
    ), 201)


@app.route('/api/saved/<analysis_id>', methods=['GET'])
@require_user
def get_saved(analysis_id):
    if not SAVED_ID_RE.match(analysis_id or ''):
        return jsonify({"success": False, "error": "Report not found"}), 404
    return _storage_response(supabase_client.load_analysis(analysis_id, g.user_id))


@app.route('/api/saved/<analysis_id>', methods=['DELETE'])
@require_user
def delete_saved(analysis_id):
    if not SAVED_ID_RE.match(analysis_id or ''):
        return jsonify({"success": False, "error": "Report not found"}), 404
    return _storage_response(supabase_client.delete_analysis(analysis_id, g.user_id))


@app.route('/api/saved', methods=['DELETE'])
@require_user
def delete_all_saved():
    return _storage_response(supabase_client.delete_all_analyses(g.user_id))


# =============================================================================
# ACCOUNT
# =============================================================================

@app.route('/api/account', methods=['DELETE'])
@require_user
def delete_account():
    """Delete the signed-in user's data and auth account."""
    result = supabase_client.delete_user_account(g.user_id)
    if "error" not in result:
        forget_token(_bearer_token())
    return _storage_response(result)


# =============================================================================
# HEALTH & STATUS
# =============================================================================

@app.route('/api/health', methods=['GET'])
def health():
    return jsonify({"status": "healthy", "supabase": supabase_client.is_configured()})


@app.route('/', methods=['GET'])
def root():
    return jsonify({"service": "Floor Pov API", "status": "running"})


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    print(f"Starting Floor Pov API on port {port}...")
    app.run(host='0.0.0.0', port=port, debug=False, threaded=True)
