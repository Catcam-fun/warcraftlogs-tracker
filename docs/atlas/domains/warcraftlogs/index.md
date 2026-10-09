---
id: warcraftlogs
title: WarcraftLogs Integration
domain: warcraftlogs
status: documented
summary:
  - "Every number on the site starts as a WarcraftLogs (WCL) v2 GraphQL query made with the officer's own API client ID and secret."
  - "The backend fetches a token, the guild roster, the guild's reports in the tier window, every report's light fight list, the full fights and players of the reports pulls are kept from, and then per-report event streams (talent loadouts, deaths, defensives, hits before deaths)."
  - "All traffic goes through one Cloudflare Worker proxy URL, not straight to warcraftlogs.com."
  - "Queries are batched and ordered per report and finished reports are cached, because WCL meters each API key by points."
tagline: What the backend asks WarcraftLogs for, in what order, and with whose key.
anchors:
  endpoints: backend/warcraftlogs.py:15
  token: backend/warcraftlogs.py:91
  graphql: backend/warcraftlogs.py:140
  guild_reports: backend/warcraftlogs.py:176
  guild_roster: backend/warcraftlogs.py:252
  light_fights: backend/warcraftlogs.py:333
  fights: backend/warcraftlogs.py:382
  deaths_bulk: backend/analysis.py:357
  combatants: backend/defensives.py:246
  defensive_raw: backend/defensives.py:257
  death_windows: backend/defensives.py:937
  instakills: backend/defensives.py:1010
  analyze_credentials: backend/app.py:125
  analyze_token: backend/app.py:158
  report_fetch: backend/app.py:338
  script_credentials: backend/scripts/build_raid_wide.py:79
links:
  - warcraftlogs-api-client
  - warcraftlogs-point-budget
  - backend
  - backend-defensive-analysis
  - backend-death-descriptions
  - game-data
  - data-model
  - security
  - operations
invariants:
  - "MUST: every analysis authenticates with the client ID and secret sent in that request; tokens are cached per credential pair, never shared."
  - "MUST: fight-level raid membership comes from the encounter-ID allowlist, not WCL's report zone."
  - "NEVER: a guild-reports query filters by zoneID; mixed raid and dungeon reports would be dropped."
flows:
  - request-path
content_hash: sha256:4c2be40c55be0908bd51722da777a8036e171b90e05170c4590c8e8ab2a2fbfa
---
## Summary

- The backend is a **client of WarcraftLogs' v2 GraphQL API**. It owns no game logs; everything is read from WCL at analysis time, or from the cache of an earlier read.
- Credentials are **the officer's own**: the Analyze request carries `clientId` and `clientSecret` (`backend/app.py:125`), and the backend trades them for an OAuth token with the client-credentials grant (`backend/warcraftlogs.py:91`).
- Both endpoints point at a **Cloudflare Worker proxy** (`backend/warcraftlogs.py:15`), and the token request uses Basic auth because that Worker requires it (`backend/warcraftlogs.py:99`).
- The read order is: token, guild roster, guild reports, each report's light fight list, the full read of the reports pulls are kept from, then per-report event queries. The details of each call live in [[warcraftlogs-api-client]]; how the code keeps the cost down lives in [[warcraftlogs-point-budget]].

## How it works

One Analyze request walks through the WCL reads below, in the order `generate()` in `backend/app.py` issues them. Reports are read in parallel, but the event queries for one report run one after another.

```steps
- title: Get a token | short: Token | sub: OAuth client credentials
  body: get_access_token posts grant_type=client_credentials with the client ID and secret as a Basic auth header (backend/warcraftlogs.py:99-121). The token is cached per sha256(client_id:client_secret) until 60 seconds before WCL's expiry (backend/warcraftlogs.py:93, 130-134). The Analyze stream calls it once per request (backend/app.py:158).
  gotcha: A cache slot per credential pair is deliberate. A single shared slot would hand one officer's token, and their rate-limit quota, to the next (comment at backend/warcraftlogs.py:23-25).
- title: Guild roster | short: Roster | sub: only when the toggle is on
  body: With rosterOnly on, get_guild_roster reads guildData.guild.members 100 at a time, the first 3 pages at once, then any remaining pages up to last_page (backend/warcraftlogs.py:321-323). Names are accent-stripped and lowercased into a set (backend/warcraftlogs.py:317-319). With the toggle off, the roster is not fetched at all (backend/app.py:165-166).
  gotcha: The roster is best-effort. A failed page is skipped, and an empty roster means everyone counts (backend/app.py:181-184).
- title: Guild reports | short: Reports | sub: scoped to the tier window
  body: get_guild_reports pages reportData.reports 100 at a time with startTime and endTime pushed into the query, up to 50 pages (backend/warcraftlogs.py:200-246). The window is the tier's RAID_DATE_WINDOWS entry, which the user's dates can only narrow (backend/analysis.py:280, backend/app.py:189-191).
  gotcha: There is no zoneID filter on purpose. WCL gives a report one zone, so a night that mixes a raid and Mythic+ would be classified as the dungeon and dropped (docstring at backend/warcraftlogs.py:177-186).
- title: Fight lists | short: Fight lists | sub: every report, light
  body: get_report_fights reads only the report start and its fights, no players or abilities (backend/warcraftlogs.py:333-381). analyze_fights keeps only pulls whose encounter ID is in the raid's RAID_ENCOUNTERS set at the chosen difficulty (backend/analysis.py:302-316, called at backend/app.py:248). Pulls are sorted by start, report code and fight ID, and duplicates across logs are dropped (backend/app.py:260-278).
- title: Fights and players | short: Full read | sub: kept reports only
  body: get_fights reads fights, Player actors, ability names, school bitmasks and icons, and playerDetails (spec per player) in one GraphQL round trip (backend/warcraftlogs.py:390-426), only for the reports that pulls were kept from (backend/app.py:270-278).
  gotcha: A report whose full read comes back empty is dropped and dedup runs again, so its pulls go to another log's copy of the same pull (backend/app.py:262-278).
- title: Talent loadouts | short: Loadouts | sub: first, alone
  body: When a report's deaths aren't cached, fetch_combatants reads CombatantInfo for the kept pulls before anything else, because it is the cheapest first query on a report WCL hasn't read recently (backend/app.py:373-380, backend/defensives.py:246-254).
- title: Deaths | short: Deaths | sub: whole report, one call
  body: get_report_deaths_bulk asks for Deaths events from the first kept pull's start to the last one's end, plus (signed-in, cheat-death on) Debuffs and Healing filtered to cheat-death ability IDs, all as aliases of one query (backend/analysis.py:395-470). Extra pages are followed with nextPageTimestamp (backend/analysis.py:475-484).
- title: Defensive data | short: Defensives | sub: three queries, one at a time
  body: Only when at least one death in the report can count (backend/app.py:387-390). fetch_defensive_raw then runs Casts, Buffs and Healing one after another, reusing the loadouts already read (backend/defensives.py:293-307). Casts cover the time range from cast_lookback (3 minutes before the first pull, or back to the last boss encounter's end for long cooldowns, at most the longest tracked cooldown), buffs from 3 minutes before it; heals are scoped to the boss pulls.
- title: Hits before deaths | short: Death windows | sub: DamageTaken by name
  body: For the deaths that can count, fetch_death_windows asks for DamageTaken events filtered by target.name, one block per group of pulls within 15 minutes, many blocks per request (backend/defensives.py:937-1001). fetch_instakills adds instant-kill events from the All stream (backend/defensives.py:1010-1015). One more block in the same request, from the All stream over all those pulls, reads on the players who died the heals a killing hit can set off (features.KILLING_HIT_HEAL_IDS: Defy Fate, Cauterize, Guardian Spirit, Ardent Defender, Embrace the Shadow, Void Reconstitution; Last Resort's absorb and Metamorphosis heal) and the stack changes of stacking max-health auras (Sentinel): measured 15.0 -> 19.4 points on a 27-pull report, warm cache. The All stream can't replace DamageTaken: it leaves the aura list off damage events. The windows' cache key (app.py) carries those ID lists, so windows cached without them are not reused; CACHE_VERSION is unchanged, so a report's other cached data stays valid.
```

## Diagram

The read path for one Analyze request. Everything goes through the proxy; finished reports may be answered from the cache instead.

```diagram
lane app Backend (app.py)
lane wcl WarcraftLogs via proxy
lane store Cache
node analyze lane=app color=process "Analyze stream" "generate()"
node token lane=wcl color=process "OAuth token" "client credentials"
node roster lane=wcl color=process "Guild roster" "100 per page"
node reports lane=wcl color=process "Guild reports" "tier window"
node light lane=wcl color=process "Fight lists" "1 query / report"
node fights lane=wcl color=process "Fights + players" "kept reports only"
node events lane=wcl color=process "Event queries" "deaths, defensives, hits"
node cache lane=store color=structural "Report cache" "memory + Supabase"
edge analyze -> token "auth"
edge token -> roster "if rosterOnly"
edge roster -> reports "list"
edge reports -> light "per report"
edge light -> fights "after dedup"
edge light -> cache color=safe "finished only"
edge fights -> events "per report"
edge fights -> cache color=safe "finished only"
edge events -> cache color=safe "finished only"
band structural "Cloudflare Worker proxy"
```

## Reference

What is read from WCL, and where.

| Data {query} | GraphQL root | Function |
|---|---|---|
| OAuth token {auth} | `POST /oauth/token` | `get_access_token` (`backend/warcraftlogs.py:91`) |
| Guild roster {query} | `guildData.guild.members` | `get_guild_roster` (`backend/warcraftlogs.py:252`) |
| Guild reports {query} | `reportData.reports` | `get_guild_reports` (`backend/warcraftlogs.py:176`) |
| Light fight list {query} | `reportData.report` (`startTime`, `fights`) | `get_report_fights` (`backend/warcraftlogs.py:333`) |
| Fights, actors, abilities, specs {query} | `reportData.report` (`fights`, `masterData`, `playerDetails`) | `get_fights` (`backend/warcraftlogs.py:382`) |
| Deaths and cheat deaths {events} | `report.events` (Deaths, Debuffs, Healing) | `get_report_deaths_bulk` (`backend/analysis.py:357`) |
| Talent loadouts {events} | `report.events` (CombatantInfo) | `fetch_combatants` (`backend/defensives.py:246`) |
| Defensive casts, buffs, heals {events} | `report.events` (Casts, Buffs, Healing) | `fetch_defensive_raw` (`backend/defensives.py:257`) |
| Hits before deaths {events} | `report.events` (DamageTaken; All for killing-hit heals and max-health stacks) | `fetch_death_windows` (`backend/defensives.py:937`) |
| Instant kills {events} | `report.events` (All, `type = 'instakill'`) | `fetch_instakills` (`backend/defensives.py:1010`) |
| Top kills per boss {scripts} | `worldData.encounter.fightRankings` | `build_armor_constants.py:118`, `build_raid_wide.py:33` |

## Standing it up

| Concern | This domain | Source |
|---|---|---|
| Runs on | Inside the Flask backend process; no separate service | `backend/app.py` |
| Depends on | The WCL proxy at `wcl-proxy.catcam-fun.workers.dev` for both GraphQL and OAuth | hard-coded constants, `backend/warcraftlogs.py:15-16` |
| Credentials (site) | `clientId`, `clientSecret` in each Analyze request body | the officer's own WCL API client, `backend/app.py:125-126` |
| Credentials (scripts) | `WCL_CLIENT_ID`, `WCL_CLIENT_SECRET` | shell environment, e.g. `backend/scripts/build_raid_wide.py:79`, `backend/checks/common.py:95` |
| Cache for finished reports | Supabase `report_cache` table behind an in-memory LRU | `backend/cache.py:42`; Supabase env vars in `backend/supabase_client.py:27-29` |

## Invariants

- **MUST** authenticate each analysis with the client ID and secret sent in that request; tokens are cached per credential pair (`backend/warcraftlogs.py:93`), so one officer never spends another's quota.
- **MUST** decide which pulls belong to a raid by encounter ID (`RAID_ENCOUNTERS`, `backend/analysis.py:234`), because several raids can share one WCL zone.
- **NEVER** filter guild reports by zoneID: a report mixing a raid with dungeons is filed under the dungeon zone and would vanish with all its raid pulls (`backend/warcraftlogs.py:179-184`).

## Gotchas

- **The endpoints are a proxy, not WCL**: `GRAPHQL_ENDPOINT` and `OAUTH_TOKEN_URL` both point at a Cloudflare Worker (`backend/warcraftlogs.py:15-16`). If that Worker is down, every analysis fails at the token step, even when warcraftlogs.com is up.
- **Names are stored two ways**: `get_fights` keeps an accent-stripped `name` for matching and the raw `logName` for WCL filter expressions (`backend/warcraftlogs.py:449-454`). Filters need the raw spelling; matching uses the stripped one.
- **Specs are read twice**: `playerDetails` gives a report-level spec (`backend/warcraftlogs.py:470-483`), while CombatantInfo gives the spec per pull, which the defensive analysis prefers (`backend/defensives.py:356-358`).

## Related

- [[warcraftlogs-api-client]] — each request function, retries and pagination in detail
- [[warcraftlogs-point-budget]] — how the code keeps WCL point cost down
- [[backend]] — the Analyze stream that drives these calls
- [[backend-defensive-analysis]] — consumes the defensive events and the hits before deaths
- [[backend-death-descriptions]] — consumes the hits to describe each death
- [[game-data]] — two of the generated catalogs are measured from WCL logs
- [[data-model]] — the Supabase `report_cache` table that holds finished reports
- [[security]] — credentials travel through the proxy
- [[operations]] — the scripts that use `WCL_CLIENT_ID` and `WCL_CLIENT_SECRET`
