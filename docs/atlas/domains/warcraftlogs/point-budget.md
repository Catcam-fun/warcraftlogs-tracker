---
id: warcraftlogs-point-budget
title: WCL Point Budget
domain: warcraftlogs
status: documented
summary:
  - "WarcraftLogs meters each API key in points, charged per page of events and at least once per event block, so the backend asks for as few pages and blocks as it can."
  - "Every report's light fight list (1 point) is read first; duplicate pulls are dropped, and only the reports pulls are kept from are read in full (3 points)."
  - "Per report, talent loadouts are read first and alone, then deaths; a report with no death that can count stops there. Otherwise the defensive, instant-kill and death-window queries run one at a time."
  - "Event queries are narrowed by ability, by player name, by time and by pull; any query scoped by fightIDs also carries an endTime."
  - "Reports that ended more than two hours ago are cached in memory and in Supabase, so they are read from WCL once."
  - "The code does not query rateLimitData; cost is controlled by query shape, query order and caching, not measured at run time."
tagline: How the backend keeps the cost of one analysis on the officer's WCL key down.
anchors:
  report_cache_age: backend/app.py:46
  report_workers: backend/app.py:50
  light_fights: backend/app.py:214
  report_meta: backend/app.py:225
  dedup_loop: backend/app.py:265
  report_deaths: backend/app.py:340
  deaths_cache_key: backend/app.py:357
  combatants_first: backend/app.py:375
  no_counted_death: backend/app.py:390
  window_cache_key: backend/app.py:398
  one_at_a_time: backend/app.py:402
  deaths_pool: backend/app.py:468
  get_report_fights: backend/warcraftlogs.py:333
  deaths_bulk: backend/analysis.py:357
  remaining_events: backend/analysis.py:329
  fetch_combatants: backend/defensives.py:246
  defensive_raw: backend/defensives.py:257
  paged: backend/defensives.py:208
  fetch_blocks: backend/defensives.py:934
  death_windows: backend/defensives.py:965
  instakills: backend/defensives.py:1069
  block_span: backend/defensives.py:877
  blocks_per_request: backend/defensives.py:879
  catalog_fingerprint: backend/defensives.py:192
  shared_cache: backend/cache.py:42
  cache_version: backend/cache.py:88
  fights_cache: backend/cache.py:112
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
  - "MUST: only reports that pulls are kept from are read in full; every other report costs one light fight-list query."
  - "MUST: a report's talent loadouts are its first event query, sent alone; its defensive, instant-kill and death-window queries follow one at a time."
  - "MUST: hits before deaths are fetched only for the deaths that can count; a report with none reads no defensives, instant kills or hits."
  - "MUST: only reports whose last event is more than two hours old are cached; a report still being logged is always refetched."
  - "NEVER: change the death-window block shapes or the Healing query's scope; WCL computes each hit's aura list from the query's own start and pages."
  - "NEVER: filter a WCL event query by target.id or by timestamp; filter by target.name with the raw log spelling."
  - "NEVER: serve a cached defensive entry built with a different catalog; the key carries the catalog fingerprint."
flows:
  - request-path
content_hash: sha256:a3e0814726d171d39506984cdec495ab5a7a215dfe93c899fd8fa6b146ed11f3
---
## Summary

- WarcraftLogs (WCL) charges each API key **points**. The code's own comment states the rule it is built around: about one point per page of events, and at least one per event block (`backend/defensives.py:970-971`). Fewer pages and fewer blocks mean a cheaper analysis.
- Every Analyze run spends the **officer's own key** (see [[warcraftlogs]]), so cost is a user-facing concern, not only a server one.
- The backend keeps cost down five ways: a **cheap fight list before the full read**, **query order per report**, **narrow filters**, **tight time and pull scopes**, and a **cache of finished reports**.
- There is no runtime cost meter. `rateLimitData` is not queried anywhere in `backend/` or `frontend/src/`; cost is controlled by how queries are shaped and ordered.

## How it works

One analysis reads guild-level data once, then each report's fight list, then a short, ordered set of queries per kept report. Each step below names how it limits cost.

```steps
- title: Guild-level reads | short: Guild | sub: roster and report list
  body: The roster is skipped entirely when the roster toggle is off (backend/app.py:165). The report list pushes the tier's date window into the WCL query itself (startTime and endTime, backend/warcraftlogs.py:204-206), so out-of-tier reports are never listed; the window comes from resolve_report_window (backend/app.py:189).
- title: Light fight lists | short: Fight lists | sub: 1 point per report
  body: get_report_fights reads only the report start and its fights (times, name, encounter, difficulty, kill, zone), no players or abilities (backend/warcraftlogs.py:333-381). Its docstring records the cost, 1 point against 3 for get_fights (backend/warcraftlogs.py:334-336). fetch_light_fights reads every report this way, REPORT_FETCH_WORKERS = 6 at a time, and answers finished reports from report_fights_cache (backend/app.py:214-223, 234-235).
  gotcha: Asking for fights inside the guild report-list query does not save anything. WCL charges about 1 point per report for them there too.
- title: Dedup, then the full read | short: Full read | sub: kept reports only
  body: dedup_pulls keeps the earliest copy of each pull (start time, then report code, then fight ID, so the copy kept never depends on which report was read first), or the longest when the earliest was cut short by more than 5 s (backend/analysis.py:84, called at backend/app.py:269). Duplicates are dropped, and only the reports that kept a pull are read in full with get_fights (3 points), cached in report_meta_cache (backend/app.py:225-233, 262-275). A report whose full read comes back empty is marked unreadable and dedup runs again, so its pulls go to another log's copy (backend/app.py:275-278).
- title: Loadouts first | short: Loadouts | sub: the warm-up query
  body: When a report's deaths are not cached, fetch_report_deaths reads CombatantInfo first and alone with fetch_combatants (backend/app.py:375-382). A report's first event query pays a "cold" price, and the report stays warm for only 10-30 seconds after a query. CombatantInfo over the kept pulls is the cheapest warm-up, about 2 points; Deaths or Casts sent first cost 4-17 (backend/defensives.py:246-254). _loadout trims each event to who, which pull, spec and talent picks as each page arrives (backend/defensives.py:237-243).
- title: Deaths | short: Deaths | sub: one aliased query
  body: get_report_deaths_bulk asks for the whole report's Deaths, plus cheat-death Debuffs and Healing when that option is on, as three aliases of a single query over the span from the first kept pull's start to the last one's end (backend/analysis.py:384-470). The debuff and heal aliases carry an ability.id filter so they stay small (backend/analysis.py:388-391). Extra pages are only fetched for an alias that returned nextPageTimestamp (backend/analysis.py:475-484).
- title: Stop if nothing counts | short: Short-circuit | sub: no counted death, no more queries
  body: counted_by_fight keeps only deaths within the deaths tracked, not in a wipe, of guild members (backend/app.py:325-336). If no death in the report can count, fetch_report_deaths returns without the defensive, instant-kill and death-window queries, since nothing would read them (backend/app.py:389-392).
- title: Defensive data | short: Defensives | sub: three queries, one at a time
  body: fetch_defensive_raw runs Casts, Buffs and Healing one after another, and reuses the loadouts already read, passed in as combatants= (backend/defensives.py:293-307; call at backend/app.py:407-408). Casts are filtered to the catalog's cast IDs, Buffs to the catalog's buff names, Healing to consumable ability IDs (backend/defensives.py:290-292). Healing is scoped to the boss pulls by fightIDs, which costs least (docstring, backend/defensives.py:282-284).
  gotcha: Casts and Buffs are not filtered by player in the query. WCL returns nothing for source.id in (...) on those data types, and the unfiltered query costs fewer points anyway; players are filtered afterwards in filter_defensive_raw (backend/defensives.py:274-279, 270).
- title: Instant kills | short: Instakills | sub: All stream, filtered
  body: Instant kills deal no damage, so they are only in the All stream. fetch_instakills reads it with the filter type = 'instakill', scoped to the kept pulls with an endTime: about 1 point per report (backend/defensives.py:1069-1074, 734).
- title: Hits before deaths | short: Death windows | sub: counted deaths only
  body: fetch_death_windows groups pulls whose windows fall within WINDOW_BLOCK_SPAN_MS (15 minutes) into one block, filters each block by target.name, and sends up to WINDOW_BLOCKS_PER_REQUEST = 20 blocks in one request (backend/defensives.py:877-879, 820-838, 793-794). Each page is filtered as it arrives, keeping a damage event only if it falls inside a counted death's window (backend/defensives.py:1021-1036). Its docstring records the measured effect, 19 to 8 and 11 to 5 points for a night's reports (backend/defensives.py:974-975). One more block in the same request, from the All stream over all those pulls, reads on the players who died the heals a killing hit can set off with their cheat-death auras' absorbs and removals (features.KILLING_HIT_HEALS: Defy Fate, Cauterize, Guardian Spirit, Ardent Defender, Embrace the Shadow, Void Reconstitution; Last Resort's absorb and Metamorphosis heal), the stack changes of stacking max-health auras (Sentinel, Bone Shield) and the casters of auras sized by a loadout (Rallying Cry): measured 15.0 -> 19.4 points on a 27-pull report, warm cache. Reading only the auras the dying players' hits list, in a second request after the hits, saved nothing (25 pulls, 116 deaths, alternating: 16.5-16.9 points before, 17.2-20.5 after either way); most of the block's events are heals. The All stream can't replace DamageTaken: it leaves the aura list off damage events. The windows' cache key (app.py) carries those ID lists, so windows cached without them are not reused; CACHE_VERSION is unchanged, so a report's other cached data stays valid.
```

#### Measured costs the code is built around

These were measured on fresh Mythic logs. The code does not read them at run time; they explain why the queries have the shape and order they do.

| Fact {measured} | Where the code relies on it |
|---|---|
| A light fight list costs 1 point; a full `get_fights` costs 3 | read every report light, only kept reports in full (`backend/app.py:203-206`, `backend/warcraftlogs.py:334-336`) |
| A report's first event query pays a "cold" price (Deaths 2-17 points, about 4 per hour of report span). For 10-30 seconds after a query the report is warm, and a query then costs about 1; after 2 minutes the price is back up. Separately, WCL answers an identical repeat query from its own cache for 45-60 minutes, for about 1 point | loadouts go first (`backend/app.py:376-378`) |
| CombatantInfo over the kept pulls is the cheapest warm-up, 1.4-3 points; a one-pull query does not warm the report | `fetch_combatants` spans every kept pull (`backend/defensives.py:246-254`) |
| After the warm-up, queries sent one at a time cost about a quarter less than sent together (3.5 vs 4.8 points per hour of raid) | `backend/app.py:402-403`, `backend/defensives.py:298-299` |
| A death-window block costs exactly 1 point (+1 per extra page) whatever its size. Neither `includeResources` nor a type filter changes it. Per-pull or exact-window blocks cost 2-4x more; one block per report costs 1.3-2x more | 15-minute blocks (`backend/defensives.py:877`, `backend/defensives.py:993-1006`) |
| WCL computes each hit's `buffs` (aura list) from the query's own start and page boundaries | the death-window block shapes and the Healing query must stay as they are, or verdicts change (`backend/defensives.py:1003-1006`, `backend/defensives.py:296`) |

On a cold run of a large guild (98 logs, 603 unique pulls), this design spent 884 points with an 807 MB memory peak, against 1199 points and 1773 MB for the earlier per-report fetch, with the same result.

#### Paging

Every event query asks for `limit: 10000` events per page (`backend/defensives.py:226`, `backend/defensives.py:930`, `backend/analysis.py:336`) and follows `nextPageTimestamp` only while WCL returns one, at most 50 times (`backend/defensives.py:213`, `backend/defensives.py:944`). `_fetch_blocks` follows up only the blocks that overflowed, not the whole request (`backend/defensives.py:959-960`).

#### The endTime rule

`_fetch_blocks` always sends an `endTime`, because WCL returns an empty second page for a block scoped by `fightIDs` without one (docstring, `backend/defensives.py:939-940`). `fetch_combatants` and every `fetch_defensive_raw` query pass `end_time + 1` (`backend/defensives.py:254`, `backend/defensives.py:304`), and `fetch_instakills` passes `end_time + 1` too (`backend/defensives.py:1073`).

#### Caching finished reports

A report counts as finished when its `end` is more than `REPORT_CACHE_MIN_AGE_MS` (2 hours) in the past (`backend/app.py:46`, `backend/app.py:210-212`). Only finished reports are read from or written to the five caches in `backend/cache.py:110-118`:

| Cache {cache} | Holds | Key includes |
|---|---|---|
| `report_fights_cache` {cache} | `get_report_fights` result (light fight list) | report code (`backend/app.py:217`) |
| `report_meta_cache` {cache} | `get_fights` result | report code (`backend/app.py:227`) |
| `report_deaths_cache` {cache} | deaths and cheat deaths | report, pulls, cheat-death flag and its ability IDs (`backend/app.py:357-358`) |
| `report_defensive_cache` {cache} | casts, buffs, talents, consumable heals of the dead | report, pulls, players, patch, `CATALOG_FINGERPRINT` (`backend/app.py:363-367`) |
| `report_recap_cache` {cache} | instant kills and death windows | report, pulls, counted deaths, `LETHAL_WINDOW_MS` (`backend/app.py:360`, `backend/app.py:398-399`) |

Each is a `SharedReportCache`: an in-memory LRU in front of the Supabase `report_cache` table, written in the background (`backend/cache.py:42-82`). Keys are prefixed with `CACHE_VERSION` (`backend/cache.py:61`, `backend/cache.py:88`), and `CATALOG_FINGERPRINT` changes whenever what is fetched for defensives changes (`backend/defensives.py:188-194`), so stale rows are never served to new code.

## Diagram

Where the cost goes, and what short-circuits it.

```diagram
lane app Backend
lane cache Cache
lane wcl WCL (points)
node light lane=wcl color=process "Fight lists" "1 pt / report"
node dedup lane=app color=process "Dedup pulls" "sorted, deterministic"
node full lane=wcl color=process "Full read" "3 pts, kept reports"
node finished lane=app color=process "Finished?" "ended > 2h ago"
node hit lane=cache color=safe "Cache hit" "memory, then Supabase"
node loadouts lane=wcl color=process "Loadouts" "first, alone"
node deaths lane=wcl color=process "Deaths" "1 aliased query"
node counted lane=app color=caution "Counted death?" "none: stop"
node defs lane=wcl color=process "Defensives" "3 queries"
node ik lane=wcl color=process "Instakills" "~1 point"
node win lane=wcl color=process "Death windows" "15 min blocks"
edge light -> dedup
edge dedup -> full "kept only"
edge full -> finished
edge finished -> hit color=safe "yes"
edge finished -> loadouts "no / miss"
edge loadouts -> deaths "then"
edge deaths -> counted
edge counted -> defs "then"
edge defs -> ik "then"
edge ik -> win "then"
band structural "Officer's WCL key"
```

## Reference

| Lever {lever} | Where | Effect |
|---|---|---|
| Date window in the query {scope} | `backend/warcraftlogs.py:204-206` | out-of-tier reports are never listed |
| Roster skipped when off {scope} | `backend/app.py:165` | no roster pages at all |
| Light fight list for every report {scope} | `backend/app.py:214-223` | 1 point per report instead of 3 |
| Full read for kept reports only {scope} | `backend/app.py:265-278` | duplicate logs cost 1 point, not 3 |
| Loadouts as the first query {order} | `backend/app.py:375-382` | cheapest cold-report warm-up |
| One aliased deaths query {batch} | `backend/analysis.py:395-468` | deaths and cheat-death events in one call |
| No counted death, no more queries {scope} | `backend/app.py:389-392` | skips defensives, instakills and hits |
| One query at a time after the warm-up {order} | `backend/app.py:402-403`, `backend/defensives.py:298-305` | about a quarter cheaper than all at once |
| Ability filters on defensive queries {filter} | `backend/defensives.py:290-292` | only catalog abilities come back |
| `fightIDs` on Healing and CombatantInfo {scope} | `backend/defensives.py:254`, `backend/defensives.py:296` | boss pulls only |
| `target.name` filter on death windows {filter} | `backend/defensives.py:1001-1002` | only the players who died |
| `WINDOW_BLOCK_SPAN_MS` = 900,000 {batch} | `backend/defensives.py:877` | pulls 15 minutes apart share a block |
| `WINDOW_BLOCKS_PER_REQUEST` = 20 {batch} | `backend/defensives.py:879` | many blocks in one request |
| `REPORT_CACHE_MIN_AGE_MS` = 2 h {cache} | `backend/app.py:46` | finished reports read once |
| `REPORT_FETCH_WORKERS` = 6 {concurrency} | `backend/app.py:50` | fight-list and full-read concurrency |
| Report pool = 8 {concurrency} | `backend/app.py:468` | reports whose events are read at once |

## Invariants

- **MUST** send an `endTime` with any event query scoped by `fightIDs`; WCL returns an empty second page without one (`backend/defensives.py:939-940`).
- **MUST** read in full only the reports that pulls are kept from; every other report costs one light fight-list query (`backend/app.py:265-278`).
- **MUST** send a report's talent loadouts as its first event query, alone, and its defensive, instant-kill and death-window queries one at a time after deaths (`backend/app.py:375-431`).
- **MUST** fetch hits before deaths only for deaths that can count; a report with none reads no defensives, instant kills or hits (`backend/app.py:389-392`, `backend/app.py:427`).
- **MUST** cache only reports whose last event is more than two hours old; a report still being logged is always refetched (`backend/app.py:44-46`).
- **NEVER** change the death-window block shapes or the Healing query's scope: WCL computes each hit's aura list from the query's own start and page boundaries, so a different shape changes verdicts (`backend/defensives.py:1003-1006`, `backend/defensives.py:296`).
- **NEVER** filter a WCL event query by `target.id` or by timestamp; filter by `target.name` with the raw log spelling (`backend/defensives.py:971-972`, `backend/defensives.py:1001-1002`).
- **NEVER** serve a cached defensive entry built with a different catalog; the key carries `CATALOG_FINGERPRINT` (`backend/app.py:363-367`).

## Gotchas

- **Concurrency is across reports, not within one**: the fight-list and full-read phases use `REPORT_FETCH_WORKERS = 6` (`backend/app.py:235`, `backend/app.py:273`), and the event phase reads 8 reports at once (`backend/app.py:468`). Inside one report the queries run one after another, so at most about 8 event requests are in flight on one key.
- **A report's first query is the expensive one**: the same query costs several times more on a report WCL hasn't read in the last 10-30 seconds, so a report's queries are sent back to back. Moving a different query ahead of `fetch_combatants` raises the cost of every cold report (`backend/app.py:376-378`).
- **A failed loadout read skips defensives**: if `fetch_combatants` raises, the error is kept and the defensive query is not sent; deaths still count (`backend/app.py:379-382`, `backend/app.py:404`).
- **Casts and Buffs cover more than the pulls**: buffs start 3 minutes (`ENCOUNTER_RESET_MS`) before the first pull and casts at `cast_lookback` (`backend/defensives.py:257`: as far back as the last boss encounter's end, at most the longest tracked cooldown, for presses that carry into a pull), and both run to the last pull's end, trash included (`backend/defensives.py:36`, `backend/defensives.py:288`). This costs more pages than a pull-scoped query but catches a defensive pressed just before a pull.
- **Deaths are scoped by time, not by pull**: `get_report_deaths_bulk` sends `startTime` and `endTime` but no `fightIDs` (`backend/analysis.py:395-468`), so trash deaths between kept pulls come back too and are dropped in code.
- **Build scripts follow the endTime rule too**: `_events` in `backend/scripts/build_armor_constants.py:46-61` costs one extra small query per fight to fetch its `endTime`, because a `fightIDs`-scoped events query without one gets an empty second page (`backend/defensives.py:939-940`).
- **No live cost reading**: nothing reads `rateLimitData`, so the site cannot tell an officer how many points an analysis used or how many are left.

## Context map

```context
depends-on: [[warcraftlogs-api-client]] — graphql_query and the paging helpers every query goes through
depends-on: [[data-model]] — the Supabase report_cache table behind the shared caches
provides: a bounded, ordered set of WCL queries per report
provides: cached fight lists, fights, deaths, defensive data and hits for finished reports
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
