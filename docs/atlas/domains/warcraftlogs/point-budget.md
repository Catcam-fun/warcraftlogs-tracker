---
id: warcraftlogs-point-budget
title: WCL Point Budget
domain: warcraftlogs
status: documented
summary:
  - "WarcraftLogs meters each API key in points, charged per page of events and at least once per event block, so the backend asks for as few pages and blocks as it can."
  - "Each report costs a fixed handful of queries: one for fights, one aliased query for deaths, four filtered defensive queries, one for instant kills and one for the hits before deaths."
  - "Event queries are narrowed by ability, by player name, by time and by pull; any query scoped by fightIDs also carries an endTime."
  - "Reports that ended more than two hours ago are cached in memory and in Supabase, so they are read from WCL once."
  - "The code does not query rateLimitData; cost is controlled by query shape and caching, not measured at run time."
tagline: How the backend keeps the cost of one analysis on the officer's WCL key down.
anchors:
  report_cache_age: backend/app.py:45
  report_workers: backend/app.py:49
  report_meta: backend/app.py:205
  report_deaths: backend/app.py:314
  deaths_cache_key: backend/app.py:331
  window_cache_key: backend/app.py:380
  deaths_pool: backend/app.py:408
  deaths_bulk: backend/analysis.py:311
  remaining_events: backend/analysis.py:283
  defensive_raw: backend/defensives.py:207
  paged: backend/defensives.py:180
  fetch_blocks: backend/defensives.py:742
  death_windows: backend/defensives.py:768
  instakills: backend/defensives.py:811
  block_span: backend/defensives.py:721
  blocks_per_request: backend/defensives.py:723
  catalog_fingerprint: backend/defensives.py:166
  shared_cache: backend/cache.py:42
  cache_version: backend/cache.py:85
  armor_events: backend/scripts/build_armor_constants.py:46
links:
  - warcraftlogs
  - warcraftlogs-api-client
  - backend
  - backend-defensive-analysis
  - backend-death-descriptions
  - data-model
  - game-data
  - operations
invariants:
  - "MUST: an event query scoped by fightIDs also carries an endTime; without one WCL returns an empty second page."
  - "MUST: hits before deaths are fetched only for the deaths that can count, as one request per report."
  - "MUST: only reports whose last event is more than two hours old are cached; a report still being logged is always refetched."
  - "NEVER: filter a WCL event query by target.id or by timestamp; filter by target.name with the raw log spelling."
  - "NEVER: serve a cached defensive entry built with a different catalog; the key carries the catalog fingerprint."
flows:
  - request-path
content_hash: sha256:9bf78ee63acb115417637e77992da1f3b8cae463764ec07a4f15f3eac35543ad
---
## Summary

- WarcraftLogs (WCL) charges each API key **points**. The code's own comment states the rule it is built around: about one point per page of events, and at least one per event block (`backend/defensives.py:771-772`). Fewer pages and fewer blocks mean a cheaper analysis.
- Every Analyze run spends the **officer's own key** (see [[warcraftlogs]]), so cost is a user-facing concern, not only a server one.
- The backend keeps cost down four ways: **batching per report**, **narrow filters**, **tight time and pull scopes**, and a **cache of finished reports**.
- There is no runtime cost meter. `rateLimitData` is not queried anywhere in `backend/` or `frontend/src/`; cost is controlled by how queries are shaped.

## How it works

One analysis reads guild-level data once, then a fixed set of queries per report. Each step below names how it limits cost.

```steps
- title: Guild-level reads | short: Guild | sub: roster and report list
  body: The roster is skipped entirely when the roster toggle is off (backend/app.py:159). The report list pushes the tier's date window into the WCL query itself (startTime and endTime, backend/warcraftlogs.py:204-206), so out-of-tier reports are never listed; the window comes from resolve_report_window (backend/app.py:183).
- title: Fights per report | short: Fights | sub: 1 query, cached
  body: get_fights reads fights, actors, abilities and specs for a report in one GraphQL round trip (backend/warcraftlogs.py:333). fetch_report_meta answers finished reports from report_meta_cache and only stores a result that has fights (backend/app.py:205-214). Reports are read REPORT_FETCH_WORKERS = 6 at a time (backend/app.py:49, 195).
  gotcha: The comment on REPORT_FETCH_WORKERS says WCL's rate limit is per API key, so concurrency stays modest (backend/app.py:47-48).
- title: Deaths | short: Deaths | sub: one aliased query
  body: get_report_deaths_bulk asks for the whole report's Deaths, plus cheat-death Debuffs and Healing when that option is on, as three aliases of a single query over the span from the first kept pull's start to the last one's end (backend/analysis.py:338-424). The debuff and heal aliases carry an ability.id filter so they stay small (backend/analysis.py:342-345). Extra pages are only fetched for an alias that returned nextPageTimestamp (backend/analysis.py:429-438).
- title: Defensive data | short: Defensives | sub: four filtered queries
  body: fetch_defensive_raw runs Casts, Buffs, Healing and CombatantInfo side by side (backend/defensives.py:229-239). Casts are filtered to the catalog's cast IDs, Buffs to the catalog's buff names, Healing to consumable ability IDs (backend/defensives.py:226-228). Healing and talent loadouts are scoped to the boss pulls by fightIDs, which costs least (docstring, backend/defensives.py:218-222).
  gotcha: Casts and Buffs are not filtered by player in the query. WCL returns nothing for source.id in (...) on those data types, and the unfiltered query costs fewer points anyway; players are filtered afterwards in filter_defensive_raw (backend/defensives.py:212-217, 242).
- title: Instant kills | short: Instakills | sub: All stream, filtered
  body: Instant kills deal no damage, so they are only in the All stream. fetch_instakills reads it with the filter type = 'instakill', scoped to the kept pulls with an endTime: about 1 point per report (backend/defensives.py:811-816, 699).
- title: Hits before deaths | short: Death windows | sub: counted deaths only
  body: counted_by_fight keeps only deaths within the deaths tracked, not in a wipe, of guild members (backend/app.py:301-312). fetch_death_windows groups pulls whose windows fall within WINDOW_BLOCK_SPAN_MS (15 minutes) into one block, filters each block by target.name, and sends up to WINDOW_BLOCKS_PER_REQUEST = 20 blocks in one request (backend/defensives.py:721-723, 781-796, 755). Its docstring records the measured effect, 19 to 8 and 11 to 5 points for a night's reports (backend/defensives.py:776-777).
```

#### Paging

Every event query asks for `limit: 10000` events per page (`backend/defensives.py:197`, `backend/defensives.py:738`, `backend/analysis.py:290`) and follows `nextPageTimestamp` only while WCL returns one, at most 50 times (`backend/defensives.py:184`, `backend/defensives.py:752`). `_fetch_blocks` follows up only the blocks that overflowed, not the whole request (`backend/defensives.py:762-764`).

#### The endTime rule

`_fetch_blocks` always sends an `endTime`, because WCL returns an empty second page for a block scoped by `fightIDs` without one (docstring, `backend/defensives.py:745-746`). `_paged` passes `end_time + 1` on all four defensive queries (`backend/defensives.py:236-237`), and `fetch_instakills` passes `end_time + 1` too (`backend/defensives.py:815`).

#### Caching finished reports

A report counts as finished when its `end` is more than `REPORT_CACHE_MIN_AGE_MS` (2 hours) in the past (`backend/app.py:45`, `backend/app.py:201-203`). Only finished reports are read from or written to the four caches in `backend/cache.py:91-97`:

| Cache {cache} | Holds | Key includes |
|---|---|---|
| `report_meta_cache` {cache} | `get_fights` result | report code (`backend/app.py:208`) |
| `report_deaths_cache` {cache} | deaths and cheat deaths | report, pulls, cheat-death flag and its ability IDs (`backend/app.py:331-332`) |
| `report_defensive_cache` {cache} | casts, buffs, talents, consumable heals of the dead | report, pulls, players, patch, `CATALOG_FINGERPRINT` (`backend/app.py:337-339`) |
| `report_recap_cache` {cache} | instant kills and death windows | report, pulls, counted deaths, `LETHAL_WINDOW_MS` (`backend/app.py:334`, `backend/app.py:380-381`) |

Each is a `SharedReportCache`: an in-memory LRU in front of the Supabase `report_cache` table, written in the background (`backend/cache.py:42-79`). Keys are prefixed with `CACHE_VERSION` (`backend/cache.py:61`, `backend/cache.py:85`), and `CATALOG_FINGERPRINT` changes whenever what is fetched for defensives changes (`backend/defensives.py:163-168`), so stale rows are never served to new code.

## Diagram

Where the cost goes for one report, and what short-circuits it.

```diagram
lane app Backend
lane cache Cache
lane wcl WCL (points)
node report lane=app color=process "Report" "fetch_report_deaths"
node finished lane=app color=process "Finished?" "ended > 2h ago"
node hit lane=cache color=safe "Cache hit" "memory, then Supabase"
node meta lane=wcl color=process "Fights" "1 query"
node deaths lane=wcl color=process "Deaths" "1 aliased query"
node defs lane=wcl color=process "Defensives" "4 filtered queries"
node ik lane=wcl color=process "Instakills" "~1 point"
node win lane=wcl color=process "Death windows" "15 min blocks"
edge report -> finished
edge finished -> hit color=safe "yes"
edge finished -> meta "no / miss"
edge meta -> deaths "then"
edge deaths -> defs "in parallel"
edge deaths -> ik "in parallel"
edge deaths -> win color=caution "counted only"
band structural "Officer's WCL key"
```

## Reference

| Lever {lever} | Where | Effect |
|---|---|---|
| Date window in the query {scope} | `backend/warcraftlogs.py:204-206` | out-of-tier reports are never listed |
| Roster skipped when off {scope} | `backend/app.py:159` | no roster pages at all |
| One aliased deaths query {batch} | `backend/analysis.py:349-422` | deaths and cheat-death events in one call |
| Ability filters on defensive queries {filter} | `backend/defensives.py:226-228` | only catalog abilities come back |
| `fightIDs` on Healing and CombatantInfo {scope} | `backend/defensives.py:232-233` | boss pulls only |
| `target.name` filter on death windows {filter} | `backend/defensives.py:791-793` | only the players who died |
| `WINDOW_BLOCK_SPAN_MS` = 900,000 {batch} | `backend/defensives.py:721` | pulls 15 minutes apart share a block |
| `WINDOW_BLOCKS_PER_REQUEST` = 20 {batch} | `backend/defensives.py:723` | many blocks in one request |
| `REPORT_CACHE_MIN_AGE_MS` = 2 h {cache} | `backend/app.py:45` | finished reports read once |
| `REPORT_FETCH_WORKERS` = 6 {concurrency} | `backend/app.py:49` | fights phase concurrency |
| Deaths phase pool = 8 {concurrency} | `backend/app.py:408` | per-report event phase concurrency |

## Invariants

- **MUST** send an `endTime` with any event query scoped by `fightIDs`; WCL returns an empty second page without one (`backend/defensives.py:745-746`).
- **MUST** fetch hits before deaths only for deaths that can count, as one request per report (`backend/app.py:301-312`, `backend/app.py:385`).
- **MUST** cache only reports whose last event is more than two hours old; a report still being logged is always refetched (`backend/app.py:43-45`).
- **NEVER** filter a WCL event query by `target.id` or by timestamp; filter by `target.name` with the raw log spelling (`backend/defensives.py:774-775`, `backend/defensives.py:791-792`).
- **NEVER** serve a cached defensive entry built with a different catalog; the key carries `CATALOG_FINGERPRINT` (`backend/app.py:337-339`).

## Gotchas

- **Two different concurrency limits**: the fights phase uses `REPORT_FETCH_WORKERS = 6` (`backend/app.py:216`), but the deaths phase hard-codes `max_workers=8` (`backend/app.py:408`). Each of those report jobs opens a pool of 3 (`backend/app.py:346`), and the defensive job opens 4 more (`backend/defensives.py:235`), so many requests can be in flight on one key at once.
- **Casts and Buffs cover more than the pulls**: they start 3 minutes (`ENCOUNTER_RESET_MS`) before the first pull and run to the last pull's end, trash included (`backend/defensives.py:34`, `backend/defensives.py:225`). This costs more pages than a pull-scoped query but catches a defensive pressed just before a pull.
- **Deaths are scoped by time, not by pull**: `get_report_deaths_bulk` sends `startTime` and `endTime` but no `fightIDs` (`backend/analysis.py:349-422`), so trash deaths between kept pulls come back too and are dropped in code.
- **Build scripts follow the endTime rule too**: `_events` in `backend/scripts/build_armor_constants.py:46-61` costs one extra small query per fight to fetch its `endTime`, because a `fightIDs`-scoped events query without one gets an empty second page (`backend/defensives.py:745-746`).
- **No live cost reading**: nothing reads `rateLimitData`, so the site cannot tell an officer how many points an analysis used or how many are left.

## Context map

```context
depends-on: [[warcraftlogs-api-client]] — graphql_query and the paging helpers every query goes through
depends-on: [[data-model]] — the Supabase report_cache table behind the shared caches
provides: a bounded number of WCL queries per report
provides: cached fights, deaths, defensive data and hits for finished reports
relied-on-by: [[backend]] — the Analyze stream issues these queries
relied-on-by: [[backend-defensive-analysis]] — reads the defensive events and death windows
relied-on-by: [[backend-death-descriptions]] — reads the hits before each death
```

## Related

- [[warcraftlogs]] — the overall read path these limits apply to
- [[warcraftlogs-api-client]] — retries, paging and the request functions
- [[backend]] — the Analyze stream and its report workers
- [[backend-defensive-analysis]] — why the defensive queries fetch what they fetch
- [[backend-death-descriptions]] — uses the death windows fetched here
- [[data-model]] — the `report_cache` table
- [[game-data]] — the build scripts that also spend WCL points
- [[operations]] — running those scripts with `WCL_CLIENT_ID` and `WCL_CLIENT_SECRET`
