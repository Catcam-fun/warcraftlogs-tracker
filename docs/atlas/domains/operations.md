---
id: operations
title: Operations & New Tier
domain: operations
status: documented
summary:
  - "Running Floor Pov comes down to a few environment variables, one health route, plain stdout logging, and caches that clean up after themselves."
  - "Failures degrade instead of stopping an analysis where they can: a missing roster counts everyone, a failed report is listed in meta.failedReports, and missing defensive data leaves the deaths counted."
  - "Supabase is optional at runtime: without it saves fail, shares live in process memory, the shared report cache is skipped and sign-in features are off."
  - "A new raid tier touches the backend raid tables, a frontend raid entry, the landing art, then the game-data build scripts in dependency order, then the real-log checks."
tagline: Running the site from the code's point of view, and the steps to add a raid tier.
anchors:
  raid_encounters: backend/analysis.py:196
  raid_date_windows: backend/analysis.py:224
  season_two_entry: frontend/src/seasonTwoRaids.js:6
  raid_cards_spread: frontend/src/AnalyzeConfig.js:21
  raid_zones_spread: frontend/src/App.js:31
  boss_order_spread: frontend/src/App.js:74
  health_route: backend/app.py:742
  dev_server: backend/app.py:752
  supabase_client: backend/supabase_client.py:39
  supabase_startup_log: backend/supabase_client.py:40
  report_cache_budget: backend/supabase_client.py:273
  report_cache_eviction: backend/supabase_client.py:362
  report_cache_backoff: backend/supabase_client.py:315
  memory_caches: backend/cache.py:91
  cache_version: backend/cache.py:85
  wcl_retry: backend/warcraftlogs.py:30
  wcl_endpoints: backend/warcraftlogs.py:15
  report_failure: backend/app.py:375
  analyze_error_event: backend/app.py:612
  catalog_build: backend/scripts/build_defensive_catalog.py:1025
  wago_cache: backend/scripts/build_defensive_catalog.py:406
links:
  - testing
  - game-data
  - backend
  - frontend-landing-and-art
  - deployment
  - backend-caching-and-limits
  - warcraftlogs
  - data-model
  - overview
invariants:
  - "MUST: add a new raid key to RAID_ENCOUNTERS before running build_boss_spell_flags.py, build_boss_spell_text.py, build_armor_constants.py or build_raid_wide.py; all four read their bosses from it."
  - "MUST: rebuild spell_icons.py after rebuilding defensive_catalog.py; the icon script reads every catalog ability."
  - "MUST: bump CACHE_VERSION in cache.py when what gets fetched or how it is indexed changes, so old shared-cache rows are never served to new code."
  - "NEVER: hand-edit the generated modules (defensive_catalog.py, boss_spell_flags.py, boss_spell_text.py, spell_icons.py, armor_constants.py, raid_wide_damage.py); edit the script and rerun it."
content_hash: sha256:13dd45916d8a490a01b449beed739ad80fc250acb4886819f17fa3033be47f5b
---
## Summary

- **Config is small.** The API reads seven environment variables; the build and check scripts read three more. No WarcraftLogs key lives on the server.
- **Health** is `GET /api/health`, which returns `{"status": "healthy", "supabase": <bool>}` (`backend/app.py:742`). The site calls it as soon as it opens to wake a sleeping instance (`frontend/src/App.js:263`).
- **Logging** is `print` to standard output with bracketed prefixes; there is no `logging` setup and no log levels.
- **Caches evict themselves**: in-process LRUs drop the oldest entry, and the shared Supabase cache keeps itself under 200 MB.
- **A new raid tier** is mostly data: encounter IDs and a date window in the backend, one raid entry in the frontend, art, then a fixed order of build scripts. The steps are below; `git show --stat 0e825bb` is the Season 2 example (backend raid tables, a raid-selection test, `seasonTwoRaids.js`, `AnalyzeConfig.js` and its test, `App.js`, `fp-design.css`).

## How it works

Adding a raid tier, in the order the code's dependencies require. Click each step. Every build script names its own inputs in its docstring.

```steps
- title: Add the raid to the backend tables | short: Backend tables | sub: RAID_ENCOUNTERS, RAID_DATE_WINDOWS
  body: Add a raid key with its encounter IDs to RAID_ENCOUNTERS (backend/analysis.py:196). analyze_fights keeps only fights whose encounter ID is in the set and whose difficulty matches (backend/analysis.py:275), which is also what keeps dungeon bosses out. Add the same key to RAID_DATE_WINDOWS (backend/analysis.py:224) as (start, end); the comment above it sets start at release minus 5 days and end at the next tier's opening plus 5 days, with None for a tier still open. Close the previous tier's window at the same time.
  gotcha: The source comment for Season 2's encounter IDs is BigWigs' raid folders (backend/analysis.py:198). When the new tier opens, give the previous tier's windows an end date (new raid's opening plus 5 days); test_only_the_newest_tier_is_open_ended fails otherwise (backend/test_raid_selection.py).
- title: Test the selection | short: Raid test | sub: test_raid_selection.py
  body: Extend backend/test_raid_selection.py the way Season 2 did. It checks the new key keeps exactly its encounters at each difficulty, that every other key excludes the new fights, and that the date window clamps user dates (backend/test_raid_selection.py:6, backend/test_raid_selection.py:32, backend/test_raid_selection.py:51).
- title: Add a frontend raid entry | short: Raid entry | sub: seasonTwoRaids.js pattern
  body: SEASON_TWO_RAIDS (frontend/src/seasonTwoRaids.js:6) holds key, name, exp, reportZone, fightZone, final (the raid card art) and bosses (the lineup and the Results page boss order). One array feeds three places by spreading it in: RAIDS on the Analyze page (frontend/src/AnalyzeConfig.js:21), RAID_ZONES (frontend/src/App.js:31) and BOSS_ORDER (frontend/src/App.js:74). The key must equal the backend raid key. Add multi-boss encounters to COUNCIL (frontend/src/AnalyzeConfig.js:23).
  gotcha: frontend/src/AnalyzeConfig.test.js expects an exact number of raid cards; update it with the new entry.
- title: Landing page and art | short: Landing + art | sub: strip, backgrounds, loader
  body: Add the bosses to BOSS_STRIP with their zone label (frontend/src/LandingPage.js:11) and multi-boss slugs to its COUNCIL (frontend/src/LandingPage.js:64). Boss tiles are fetched by frontend/scripts/fetch-boss-renders.py into frontend/public/art/bosses; add the names to its BOSSES list (frontend/scripts/fetch-boss-renders.py:14), and its COUNCIL and DISPLAY_OVERRIDE if needed. Put the new tier's backgrounds in CURRENT_TIER_BACKGROUNDS and move the previous ones into BACKGROUNDS (frontend/src/LandingPage.js:84). The analysis loader video is referenced by path in App.js (frontend/src/App.js:1541). Add a line to UPDATES (frontend/src/LandingPage.js:97). See [[frontend-landing-and-art]].
- title: Rebuild the defensive catalog | short: Catalog | sub: wago.tools, every patch
  body: python backend/scripts/build_defensive_catalog.py builds one catalog per retail patch from 11.0.2 on, each from that patch's last build (backend/scripts/build_defensive_catalog.py:401). Set WAGO_CACHE to a folder to keep downloaded tables between runs (backend/scripts/build_defensive_catalog.py:406). Patch names as arguments do a dry run that writes nothing (backend/scripts/build_defensive_catalog.py:1046). New potions need a typical heal in POTION_TYPICAL (backend/scripts/build_defensive_catalog.py:343); the per-tier STANDARD_POTION and DEMONIC_HEALTHSTONE_MEASURED tables in backend/defensives.py:53 and backend/defensives.py:58 are maintained by hand from real logs.
  gotcha: If the newest patch's spell data no longer matches the curated list, the script stops with "spell data changed; update CURATED / EFFECTS" (backend/scripts/build_defensive_catalog.py:1037). Older patches only print a note.
- title: Rebuild the icons | short: Icons | sub: after the catalog
  body: python backend/scripts/build_spell_icons.py writes backend/spell_icons.py, the icon and description of every catalog ability. Its docstring says to rerun it after rebuilding the catalog (backend/scripts/build_spell_icons.py:10); it imports the catalog it just rebuilt.
- title: Boss spell flags and text | short: Boss spells | sub: reads RAID_ENCOUNTERS
  body: python backend/scripts/build_boss_spell_flags.py lists boss spells that ignore immunities, so an immunity is never judged to save against them (backend/scripts/build_boss_spell_flags.py:1). python backend/scripts/build_boss_spell_text.py writes the in-game descriptions shown in the killing-blow tooltip (backend/scripts/build_boss_spell_text.py:1). Both take the raids' Dungeon Journal from wago.tools for the encounters in RAID_ENCOUNTERS (backend/scripts/build_boss_spell_flags.py:39).
- title: Armor constants | short: Armor | sub: WCL credentials
  body: WCL_CLIENT_ID=... WCL_CLIENT_SECRET=... python backend/scripts/build_armor_constants.py measures each boss's armor constant per difficulty from top-ranked kills (backend/scripts/build_armor_constants.py:21). It reads the bosses from RAID_ENCOUNTERS; a boss with too few samples uses its raid's value.
- title: Raid-wide damage | short: Raid-wide | sub: WCL credentials
  body: WCL_CLIENT_ID=... WCL_CLIENT_SECRET=... python backend/scripts/build_raid_wide.py writes backend/raid_wide_damage.py, the boss abilities whose median occurrence hits at least half the raid (backend/scripts/build_raid_wide.py:29). Only those can make a death read as worn down by rot. It costs about 10 WarcraftLogs points per encounter (backend/scripts/build_raid_wide.py:12).
- title: Check against real logs | short: Real-log checks | sub: every raid key
  body: Run check_deaths.py and check_durations.py with reportCode:raidKey arguments, a Mythic log for each raid key, and check_mitigation.py on a report from the new tier. Passing output is described on [[testing]]. If WarcraftLogs reports a spec the code does not know, the API prints "[WARN] Unknown specID" until it is added to SPEC_NAMES (backend/defensives.py:265, backend/defensives.py:318).
```

## Reference

Environment variables, from every `os.environ` lookup in the code.

| Variable {runtime} | Read by | Default | Purpose |
|---|---|---|---|
| `SUPABASE_URL` {runtime} | `backend/supabase_client.py:27`, `backend/auth.py:20` | none | Supabase project URL |
| `SUPABASE_KEY` {runtime} | `backend/supabase_client.py:28`, `backend/auth.py:21` | none | Supabase key; used for token checks, and for storage when no service-role key is set |
| `SUPABASE_SERVICE_ROLE_KEY` {runtime} | `backend/supabase_client.py:29` | none | preferred storage key (`backend/supabase_client.py:38`); account deletion requires it (`backend/supabase_client.py:388`) |
| `ALLOWED_ORIGINS` {runtime} | `backend/app.py:64` | `*` | comma list of site origins for CORS |
| `PORT` {runtime} | `backend/gunicorn.conf.py:12`, `backend/app.py:753` | `5000` | listen port |
| `WEB_CONCURRENCY` {runtime} | `backend/gunicorn.conf.py:13` | `1` | gunicorn worker processes |
| `GUNICORN_THREADS` {runtime} | `backend/gunicorn.conf.py:15` | `16` | threads per worker |
| `REACT_APP_API_URL` {build} | `frontend/src/api.js:7` | localhost:5000 on localhost, else the Render URL | API base URL baked in at build time |
| `WCL_CLIENT_ID`, `WCL_CLIENT_SECRET` {scripts} | `backend/scripts/check_deaths.py:27` and every `check_*` / `build_armor_constants.py` / `build_raid_wide.py` | none, required | the operator's own WarcraftLogs API client |
| `WAGO_CACHE` {scripts} | `backend/scripts/build_defensive_catalog.py:406` | unset (no cache) | folder for downloaded wago.tools tables; the other wago scripts import `table` from this script, so they use it too |

The frontend's Supabase project URL and public anon key are constants in `frontend/src/supabaseClient.js:3`, not environment variables.

Failure modes visible in the code, and what the user sees:

| Failure {wcl} | Code | Behavior |
|---|---|---|
| Bad WarcraftLogs credentials or query {wcl} | `backend/warcraftlogs.py:48`, `backend/app.py:133` | a 4xx other than 429 is not retried; the stream ends with `Authentication failed: ...` |
| WarcraftLogs 429, 5xx or network error {wcl} | `backend/warcraftlogs.py:19`, `backend/warcraftlogs.py:51` | up to 3 retries with backoff 1, 2, 4 s (cap 10 s), or the `Retry-After` header capped at 30 s; token requests retry twice (`backend/warcraftlogs.py:120`) |
| Roster query slow or failing {wcl} | `backend/warcraftlogs.py:290`, `backend/app.py:148` | 40 s timeout, one retry; on failure everyone in the reports counts and the stream says so |
| One report cannot be read {wcl} | `backend/app.py:375`, `backend/app.py:405` | its pulls get no deaths, its code goes in `meta.failedReports`, and a warning line is streamed |
| Defensive or hit data fails {wcl} | `backend/app.py:342`, `backend/app.py:409` | deaths still count; a warning says WarcraftLogs may be rate-limiting the key |
| No reports, or no fights at that difficulty {wcl} | `backend/app.py:173`, `backend/app.py:233` | the stream ends with an error message |
| Anything else inside the analysis {wcl} | `backend/app.py:612` | traceback printed; the stream ends with `{"error": ...}`, HTTP status stays 200 |
| Supabase not configured {supabase} | `backend/supabase_client.py:39` | `db` is `None`; saves return "Database not configured" as HTTP 500 (`backend/app.py:674`); shares are kept in process memory for 72 h (`backend/supabase_client.py:222`); the report cache is skipped |
| Supabase insert for a share fails {supabase} | `backend/supabase_client.py:240` | falls back to memory; the response carries `ephemeral: true` |
| Shared report cache errors {supabase} | `backend/supabase_client.py:315` | treated as a miss, and the shared cache is skipped for 5 minutes |
| Sign-in check unreachable {supabase} | `backend/auth.py:38` | treated as signed out: cheat-death detection is off and signed-in routes refuse |
| Too many requests from one IP {limits} | `backend/ratelimit.py:52`, `backend/app.py:49` | HTTP 429; 60 analyses, 20 shares and 30 saves per hour per IP |

## Standing it up

| Concern | This domain | Source |
|---|---|---|
| Health | `GET /api/health` returns status and whether Supabase is configured (`backend/app.py:742`) | code |
| Startup log | `[Startup] Supabase storage configured: <bool> (service role: <bool>)` (`backend/supabase_client.py:40`) | stdout |
| Log prefixes | `[Retry]`, `[WARN]`, `[ERROR]`, `[ReportCache]`, `[Share]`, `[Saved]`, `[Auth]`, `[Delete Account]`; `analysis.py` also prints per-report `[DEBUG]` lines (`backend/analysis.py:457`) | stdout via `print` |
| Finished reports | a report whose last event is over 2 hours old is treated as finished and cached (`backend/app.py:43`) | code |
| In-memory caches | LRU per process: 200 report metas, 400 death sets, 200 defensive sets, 400 hit windows (`backend/cache.py:91`) | code |
| Shared cache | Supabase `report_cache`: rows over 4 MB are not stored; every 20th write deletes least-recently-used rows past 200 MB (`backend/supabase_client.py:273`, `backend/supabase_client.py:362`) | code |
| Shares | expired rows are deleted whenever a new share is stored (`backend/supabase_client.py:230`) | code |
| WarcraftLogs host | the API calls a Cloudflare Worker proxy for both OAuth and GraphQL (`backend/warcraftlogs.py:15`) | code |
| Game data host | `wago.tools` for catalog, icons and boss spells (`backend/scripts/build_defensive_catalog.py:404`) | build scripts |
| Boss art hosts | `wago.tools` and `render.worldofwarcraft.com` (`frontend/scripts/fetch-boss-renders.py:97`, `frontend/scripts/fetch-boss-renders.py:123`) | art script |

## Invariants

- **MUST** add a new raid key to `RAID_ENCOUNTERS` before running `build_boss_spell_flags.py`, `build_boss_spell_text.py`, `build_armor_constants.py` or `build_raid_wide.py`; all four read their bosses from it, so a missing key leaves the new bosses out of every generated file.
- **MUST** rebuild `spell_icons.py` after rebuilding `defensive_catalog.py` (`backend/scripts/build_spell_icons.py:10`); a new catalog ability without an icon fails `test_every_catalog_ability_has_an_icon`.
- **MUST** bump `CACHE_VERSION` (`backend/cache.py:85`) when what gets fetched or how it is indexed changes; otherwise shared-cache rows written by old code are served to new code.
- **NEVER** hand-edit the generated modules (`defensive_catalog.py`, `boss_spell_flags.py`, `boss_spell_text.py`, `spell_icons.py`, `armor_constants.py`, `raid_wide_damage.py`); each opens with a "GENERATED by" line naming its script, and the next run overwrites edits.

## Gotchas

- **Errors after streaming starts are HTTP 200**: once `/api/analyze` begins, every failure is a `data: {"error": ...}` event. Uptime checks that only look at status codes will not see them.
- **The memory share fallback is per process**: with Supabase missing, a share created on one gunicorn worker is invisible to another and vanishes on restart.
- **Debug output is unconditional**: the `[DEBUG]` prints in `get_report_deaths_bulk` (`backend/analysis.py:457`) run for every report that is not served from cache, and the `[DEDUP]` lines add more when cheat-death detection is on, so logs grow with every analysis.
- **The current-tier windows have no end**: `None` in `RAID_DATE_WINDOWS` means "up to today". When a tier closes, set its end date, or its analyses keep listing every newer report.
- **Unknown raid keys do not fail**: a key missing from `RAID_ENCOUNTERS` silently falls back to the zone filter (`backend/analysis.py:280`), so a typo in the frontend key returns plausible but wrong pulls.

## Related

- [[testing]] — what the real-log checks print and what passing looks like
- [[game-data]] — the generated modules the build scripts write
- [[backend]] — the Flask app these settings configure
- [[backend-caching-and-limits]] — the caches and rate limits in detail
- [[frontend-landing-and-art]] — boss strip, backgrounds and loader for a new tier
- [[deployment]] — where the env values are set and how releases go out
- [[warcraftlogs]] — the API client and its retries
- [[data-model]] — the Supabase tables behind saves, shares and the cache
- [[overview]] — the supported raids and the vocabulary
