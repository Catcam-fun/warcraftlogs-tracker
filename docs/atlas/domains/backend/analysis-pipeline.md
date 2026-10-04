---
id: backend-analysis-pipeline
title: Analysis Pipeline
domain: backend
status: documented
summary:
  - "POST /api/analyze runs one generator in backend/app.py: sign in, roster, reports, fights, duplicate pulls, deaths, processing, result."
  - "The raid key picks two things in analysis.py: the boss encounter IDs that count (RAID_ENCOUNTERS) and the date window reports are fetched from (RAID_DATE_WINDOWS)."
  - "Each report's deaths come from one bulk GraphQL query (get_report_deaths_bulk), with cheat-death debuffs and save heals in the same request when enabled."
  - "Pulls logged by several raiders are collapsed by time overlap (is_duplicate_pull) before any deaths are fetched."
  - "Every death leaves with a slot and an inWipe flag; only deaths that can count get defensive analysis."
tagline: What /api/analyze does, from the request body to the final result event.
anchors:
  analyze_route: "backend/app.py:82"
  generate: "backend/app.py:95"
  roster_toggle: "backend/app.py:118"
  is_guild_member: "backend/app.py:154"
  report_window: "backend/app.py:162"
  report_finished: "backend/app.py:181"
  fetch_report_meta: "backend/app.py:184"
  dedup_loop: "backend/app.py:243"
  fetch_report_deaths: "backend/app.py:293"
  processing_loop: "backend/app.py:420"
  result: "backend/app.py:574"
  raid_encounters: "backend/analysis.py:196"
  raid_date_windows: "backend/analysis.py:222"
  resolve_report_window: "backend/analysis.py:240"
  analyze_fights: "backend/analysis.py:262"
  is_duplicate_pull: "backend/analysis.py:56"
  deaths_bulk: "backend/analysis.py:317"
  cheat_debuff_ids: "backend/features.py:14"
  cheat_heal_ids: "backend/features.py:26"
links:
  - backend
  - backend-api-endpoints
  - backend-death-counting
  - backend-caching-and-limits
  - backend-defensive-analysis
  - warcraftlogs
  - data-model
  - frontend-results-view
  - feat-analyze
invariants:
  - "MUST: keep only fights whose boss encounter ID is in RAID_ENCOUNTERS for the selected raid; the zone filter is a fallback for unknown raid keys only."
  - "MUST: user dates may only narrow RAID_DATE_WINDOWS, never widen it."
  - "MUST: drop duplicate pulls before fetching deaths, so a pull logged by three raiders is counted once."
  - "NEVER: cache the deaths of a report that failed to load; get_report_deaths_bulk re-raises so the caller records the failure instead."
---

## Summary

- `POST /api/analyze` (`backend/app.py:82`) reads its JSON body, checks the bearer token, then returns a streaming response driven by the inner `generate()` function (`backend/app.py:95`). Everything on this page happens inside that generator. The stream format is on [[backend-api-endpoints]].
- The **raid key** (`selectedRaid`) is the main input. It selects the allowed boss encounter IDs (`RAID_ENCOUNTERS`, `backend/analysis.py:196`) and the tier's date window (`RAID_DATE_WINDOWS`, `backend/analysis.py:222`).
- WarcraftLogs is read in a fixed order: token, roster, report list, each report's fights, then each report's deaths and defensive events. The client functions live in [[warcraftlogs]].
- Finished reports are served from cache instead of WarcraftLogs; see [[backend-caching-and-limits]]. Slot and wipe rules are on [[backend-death-counting]].

## How it works

The generator yields a progress event at each stage. Click each step to see what it does.

```steps
- title: Read the config | short: Config | sub: body, sign-in, defaults
  body: Before the generator starts, the route reads the JSON body and checks the bearer token (`backend/app.py:88`, `backend/app.py:93`). Inside it, `maxCutoff` defaults to 5 and is clamped to 1-10 (`backend/app.py:107`); empty start or end dates become None (`backend/app.py:109`); cheat deaths are on only when asked for and signed in (`backend/app.py:116`); `rosterOnly` is on unless it is exactly `false` (`backend/app.py:118`). Missing `clientId`, `clientSecret`, `guildName`, `server` or `region` ends the stream (`backend/app.py:121`).
  gotcha: The body is read outside the generator on purpose. The generator runs after Flask's request context is gone.
- title: Sign in to WarcraftLogs | short: Auth | sub: caller's own API client
  body: `get_access_token(client_id, client_secret)` exchanges the caller's WarcraftLogs client for a token (`backend/app.py:131`). A failure ends the stream with "Authentication failed".
- title: Fetch the guild roster | short: Roster | sub: who counts
  body: With the roster toggle on, `get_guild_roster` returns the set of member names (`backend/app.py:143`). `is_guild_member` checks a normalized, lowercased name against it (`backend/app.py:154`). With the toggle off the roster is not fetched, and everyone in the reports counts (`backend/app.py:138`).
  gotcha: If the roster comes back empty or the fetch fails, the analysis carries on and everyone counts (`backend/app.py:147`, `backend/app.py:150`). The user sees only a progress message.
- title: List the guild's reports | short: Reports | sub: tier date window
  body: `resolve_report_window` intersects the user's dates with the tier window (`backend/app.py:162`), then `get_guild_reports` pages through the guild's reports in that window (`backend/app.py:164`). An `authorFilters` list keeps only reports whose owner name is in it (`backend/app.py:168`). No reports ends the stream (`backend/app.py:172`).
- title: Read each report's fights | short: Fights | sub: six reports at once
  body: Up to `REPORT_FETCH_WORKERS` (6) reports are read at once (`backend/app.py:47`, `backend/app.py:195`). A report whose end time is more than two hours old counts as finished (`backend/app.py:180`) and its fights come from `report_meta_cache` when present (`backend/app.py:186`). `analyze_fights` keeps only this raid's boss pulls at the chosen difficulty (`backend/app.py:212`). Each kept pull records its absolute start and end, the report's actors, ability names, schools and icons (`backend/app.py:213`). No pulls at all ends the stream with a difficulty message (`backend/app.py:232`).
- title: Drop duplicate pulls | short: Dedup | sub: same pull, several logs
  body: Pulls are sorted by absolute start time (`backend/app.py:229`) and passed one by one to `is_duplicate_pull` (`backend/app.py:249`). The first log of a pull wins; any later pull of the same boss that overlaps it is skipped before its deaths are fetched.
- title: Fetch deaths per report | short: Deaths | sub: eight reports at once
  body: Kept pulls are grouped by report (`backend/app.py:272`) and `fetch_report_deaths` runs for up to eight reports at once (`backend/app.py:387`). Per report it runs up to three queries in parallel: the bulk death query, raw defensive events, and instant kills (`backend/app.py:325`). It then asks for the hits before each death that can count (`backend/app.py:364`). Finished reports read and write the four report caches.
  gotcha: A report that throws is returned with empty death lists and its id is added to `failedReports` (`backend/app.py:378`, `backend/app.py:396`). Its pulls stay in the pull list, so they still count as pulls each player attended, with no deaths.
- title: Rank and enrich each pull | short: Processing | sub: slots, defensives, cutoffs
  body: For each pull, in time order, the pull number per boss goes up by one (`backend/app.py:435`), guild members present are added to `pullParticipation` and `bossParticipation` (`backend/app.py:461`), saves the player died from anyway are dropped, and `rank_pull_deaths` assigns `slot` and `inWipe` (`backend/app.py:473`). Each guild member's death becomes a death event (`backend/app.py:490`). A real death with `slot <= maxCutoff` outside a wipe also gets `defensives.analyze_death` (`backend/app.py:514`). The legacy `pullCutoffTimestamps` are computed last (`backend/app.py:557`).
- title: Send the result | short: Result | sub: one final event
  body: The generator builds `meta`, `events`, participation maps, cutoffs and the icon and text lookups (`backend/app.py:574`), then yields one `{"result": ...}` event (`backend/app.py:606`). Any exception anywhere becomes one `{"error": ...}` event instead (`backend/app.py:608`).
```

#### Raid selection

`analyze_fights` (`backend/analysis.py:262`) is the gate that decides which pulls exist at all. When the raid key is in `RAID_ENCOUNTERS`, a fight is kept only if its `boss` encounter ID is in that raid's set and its `difficulty` equals the requested one (`backend/analysis.py:273`). This is what isolates one Midnight raid from the others that share a WarcraftLogs zone, and what keeps Mythic+ dungeon bosses out of mixed reports (comment at `backend/analysis.py:189`). Only an unknown raid key falls back to filtering by `fightZone` and difficulty (`backend/analysis.py:278`).

`resolve_report_window` (`backend/analysis.py:240`) treats the tier window as the outer bound. A user start date is used only if it is later than the tier start, and a user end date only if it is earlier than the tier end (`backend/analysis.py:249`). A `None` tier end means the tier is still open, so the user's end date (or none) is used. An unknown raid key passes the user's dates through unchanged (`backend/analysis.py:247`).

#### Duplicate pulls

When several raiders log the same night, each report contains the same pulls. `is_duplicate_pull` (`backend/analysis.py:56`) keeps, per boss ID, a list of the pulls already accepted. A new pull is a duplicate when it overlaps an accepted one by at least 15 seconds, or by at least 50% intersection-over-union (`backend/analysis.py:58`, `backend/analysis.py:64`). Overlap uses absolute times (report start plus fight offset, `backend/app.py:219`), so it works across reports.

#### The bulk death query

`get_report_deaths_bulk` (`backend/analysis.py:317`) asks for every `Deaths` event between the first kept pull's start and the last one's end in one GraphQL request (`backend/analysis.py:343`). With cheat deaths on, the same request uses GraphQL aliases to also fetch `Debuffs` filtered to `CHEAT_DEATH_DEBUFF_IDS` and `Healing` filtered to `CHEAT_DEATH_HEAL_IDS` (`backend/analysis.py:348`, `backend/analysis.py:355`). Each block that has a `nextPageTimestamp` is followed page by page (`backend/analysis.py:435`, `backend/analysis.py:289`).

Deaths are grouped by fight id, but only for fights that survived filtering and dedup (`backend/analysis.py:450`, `backend/analysis.py:603`). Each death records its timestamp, `targetID`, the player name from the report's actors, and the killing ability's id and name (`backend/analysis.py:617`).

#### Cheat deaths

A **cheat death** is a lethal hit the player survived because of an effect such as Cheat Death or Cauterize. `backend/features.py` lists the effects: debuffs left on the saved player (`backend/features.py:14`) and two saves that show only as a heal on them, Guardian Spirit and Ardent Defender (`backend/features.py:26`). An `applydebuff` of a listed debuff, or a `heal` from a listed heal spell, becomes a cheat-death event (`backend/analysis.py:491`).

Two cleanup passes follow. First, only the earliest cheat death per player per fight is kept (`backend/analysis.py:519`). Second, events for the same player and ability within 100 ms of each other are merged (`backend/analysis.py:552`). Later, `drop_saves_that_died` removes saves the player died from within 5 seconds; see [[backend-death-counting]].

#### What the result carries

The result shape is listed on [[backend-api-endpoints]]. Two parts come straight from this pipeline: `events` holds every guild member's death and cheat death with its `slot` and `inWipe`, counted or not, and `pullParticipation` holds every pull each main character was present for, keyed `"<reportId>_<fightId>"` (`backend/app.py:465`). The results page counts deaths against those pulls; see [[frontend-results-view]].

## Diagram

The stages in order, with where each one reads its data.

```diagram
lane flow Generator stages
node cfg lane=flow color=process "Config" "body + sign-in"
node roster lane=flow color=process "Roster" "optional"
node reports lane=flow color=process "Reports" "tier window"
node fights lane=flow color=process "Fights" "analyze_fights"
node dedup lane=flow color=process "Dedup" "is_duplicate_pull"
node deaths lane=flow color=process "Deaths" "bulk per report"
node proc lane=flow color=safe "Processing" "slots + defensives"
node result lane=flow color=safe "Result event" "one SSE event"
lane data Data sources
node wcl lane=data color=caution "WarcraftLogs" "GraphQL"
node cache lane=data color=structural "Report caches" "memory + Supabase"
node tables lane=data color=structural "Raid tables" "analysis.py"
edge cfg -> roster
edge roster -> reports
edge reports -> fights
edge fights -> dedup
edge dedup -> deaths
edge deaths -> proc
edge proc -> result color=safe "yield"
edge tables -> reports color=structural "date window"
edge tables -> fights color=structural "encounter IDs"
edge cache -> fights color=structural "finished"
edge cache -> deaths color=structural "finished"
edge wcl -> deaths color=caution "live reports"
```

## Reference

The raid keys the backend knows, from `backend/analysis.py:196` and `backend/analysis.py:222`.

| Raid key {midnight} | Encounter IDs | Date window |
|---|---|---|
| `midnight-s2-all` {midnight} | 9 IDs (Venomous Abyss and lairs) | 2026-08-13 to open |
| `voidspire` {midnight} | 3176-3181 | 2026-03-12 to open |
| `dreamrift` {midnight} | 3306 | 2026-03-12 to open |
| `queldanas` {midnight} | 3182, 3183 | 2026-03-12 to open |
| `midnight-all` {midnight} | the 9 Midnight Season 1 IDs | 2026-03-12 to open |
| `manaforge` {tww} | 3122, 3129-3135 | 2025-08-07 to 2026-03-22 |
| `undermine` {tww} | 3009-3016 | 2025-02-27 to 2025-08-17 |
| `nerubar` {tww} | 2898, 2902, 2917-2922 | 2024-09-05 to 2025-03-09 |

Pipeline constants:

| Constant {const} | Value | Where |
|---|---|---|
| `REPORT_FETCH_WORKERS` {const} | 6 reports read at once for fights | `backend/app.py:47` |
| death fetch pool {const} | 8 reports at once, 3 queries each | `backend/app.py:387`, `backend/app.py:325` |
| `REPORT_CACHE_MIN_AGE_MS` {const} | 2 hours; older reports count as finished | `backend/app.py:43` |
| `MIN_ABS_OVERLAP_MS` {dedup} | 15000 ms | `backend/analysis.py:58` |
| `MIN_IOU_FOR_DUP` {dedup} | 0.50 | `backend/analysis.py:59` |
| cheat-death merge window {cheat} | 100 ms, same player and ability | `backend/analysis.py:552` |
| `max_pages` {const} | 50 pages per event type | `backend/analysis.py:289` |

## Context map

```context
depends-on: [[warcraftlogs]] — token, roster, report list, fights and event queries
depends-on: [[backend-caching-and-limits]] — finished reports come from the report caches
depends-on: [[backend-death-counting]] — slot, inWipe and the save filter
depends-on: [[backend-defensive-analysis]] — analyze_death for each death that can count
provides: the result object the analyze stream ends with
relied-on-by: [[backend-api-endpoints]] — streams this generator's events
relied-on-by: [[frontend-results-view]] — renders events and participation
relied-on-by: [[feat-analyze]] — the Analyze button runs this pipeline
```

## Invariants

- **MUST** keep only fights whose boss encounter ID is in `RAID_ENCOUNTERS` for the selected raid; the zone filter is a fallback for unknown raid keys only (`backend/analysis.py:273`).
- **MUST** let user dates only narrow `RAID_DATE_WINDOWS`, never widen it (`backend/analysis.py:240`).
- **MUST** drop duplicate pulls before fetching deaths, so a pull logged by three raiders is counted once (`backend/app.py:249`).
- **NEVER** cache the deaths of a report that failed to load; `get_report_deaths_bulk` re-raises (`backend/analysis.py:675`) and the cache write happens only after a successful result (`backend/app.py:333`).

## Gotchas

- **Reports are not filtered by zone**: `get_guild_reports` fetches by date only, because WarcraftLogs gives each report one zone and a raid night mixed with dungeons can be filed under the dungeon zone (`backend/warcraftlogs.py:176`). The encounter allowlist does the filtering.
- **Open tiers page through everything since their start**: a `None` end date means no upper bound. Midnight Season 1 keys still have no end date (`backend/analysis.py:229`), although Season 2 has opened (`backend/analysis.py:225`).
- **The first log of a pull wins**: dedup keeps whichever report's pull starts earliest (`backend/app.py:229`). It does not pick the most complete log.
- **"Cross-report" cheat-death dedup is per report**: `get_report_deaths_bulk` runs once per report, so its second pass (`backend/analysis.py:544`) only merges events within one report. Duplicates across reports are removed earlier, by pull dedup.
- **One save per player per pull**: the first cleanup pass keeps only the earliest cheat death per player per fight (`backend/analysis.py:519`), so a player saved twice in one pull shows one cheat death.
- **Failed reports still count as attended pulls**: a report that throws returns empty death lists (`backend/app.py:378`) while its pulls remain in the processing loop, which adds them to `pullParticipation` (`backend/app.py:466`).
- **Unreadable defensive data is a warning, not an error**: deaths still count; the stream sends a progress message naming how many reports lack detail (`backend/app.py:407`).

## Glossary

- **Raid key**: the `selectedRaid` string, such as `manaforge`, that indexes `RAID_ENCOUNTERS` and `RAID_DATE_WINDOWS`.
- **Finished report**: a report whose end time is more than two hours ago; only these are read from or written to the caches.
- **Duplicate pull**: the same boss pull in another raider's log, found by time overlap.
- **Cheat death**: a lethal hit the player survived because a listed effect fired.

## Related

- [[backend]] — the service landing page
- [[backend-api-endpoints]] — the stream and result shape this pipeline fills
- [[backend-death-counting]] — slots, wipes and the save filter used in processing
- [[backend-caching-and-limits]] — the report caches and the analyze rate limit
- [[backend-defensive-analysis]] — the defensives block attached to deaths that can count
- [[warcraftlogs]] — every GraphQL call the pipeline makes
- [[data-model]] — the report_cache table behind the shared cache
- [[frontend-results-view]] — where events and participation are rendered
- [[feat-analyze]] — the analyze flow from the user's side
