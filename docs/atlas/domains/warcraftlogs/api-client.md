---
id: warcraftlogs-api-client
title: WCL API Client
domain: warcraftlogs
status: documented
summary:
  - "make_request_with_retry is the single HTTP path: client errors fail at once, 429 and 5xx back off exponentially and honor Retry-After."
  - "get_access_token caches one token per client ID and secret pair; graphql_query turns a GraphQL errors array into an exception."
  - "Every paged event query follows nextPageTimestamp, capped at 50 pages."
  - "Character names are accent-stripped for matching, but the raw log spelling is kept for WCL filters."
tagline: The request functions in warcraftlogs.py and the event fetchers built on them.
anchors:
  retry: backend/warcraftlogs.py:30
  client_error_break: backend/warcraftlogs.py:48
  retry_after: backend/warcraftlogs.py:51
  normalize: backend/warcraftlogs.py:65
  token: backend/warcraftlogs.py:91
  token_expiry: backend/warcraftlogs.py:130
  graphql: backend/warcraftlogs.py:140
  graphql_errors: backend/warcraftlogs.py:169
  reports: backend/warcraftlogs.py:176
  roster: backend/warcraftlogs.py:252
  light_fights: backend/warcraftlogs.py:333
  fights: backend/warcraftlogs.py:382
  remaining_events: backend/analysis.py:329
  deaths_bulk: backend/analysis.py:357
  paged: backend/defensives.py:208
  fetch_blocks: backend/defensives.py:906
  token_test: backend/test_api.py:225
links:
  - warcraftlogs
  - warcraftlogs-point-budget
  - backend
  - backend-defensive-analysis
  - testing
invariants:
  - "MUST: 4xx responses other than 429 fail without retrying; retrying cannot fix bad credentials or a bad query."
  - "MUST: a GraphQL response with an errors array raises, never returns partial data silently."
  - "MUST: every event fetch follows nextPageTimestamp so long reports don't lose events past the first page."
  - "NEVER: use an accent-stripped name in a WCL filter expression; it matches nobody."
content_hash: sha256:70bb4dae5d831cc6a2815e05950190e218e384d83d63934681ca589a83756ea9
---
## Summary

- All WCL traffic goes through two helpers in `backend/warcraftlogs.py`: `make_request_with_retry` (HTTP with backoff) and `graphql_query` (POST a query with a bearer token).
- Six query functions sit on top: `get_access_token`, `get_guild_reports`, `get_guild_roster`, `get_report_fights`, `get_fights` in `warcraftlogs.py`, and `get_report_deaths_bulk` in `backend/analysis.py`. The defensive event fetchers in `backend/defensives.py` reuse `graphql_query`.
- Paging is handled in three places with the same rule: keep asking from `nextPageTimestamp` until WCL stops returning one, at most 50 times.

## How it works

#### Retries: `make_request_with_retry`

`make_request_with_retry(method, url, max_retries=3, timeout=120)` (`backend/warcraftlogs.py:30`) makes up to `max_retries + 1` attempts.

- On an HTTP error with a status from 400 to 499, other than 429, it **stops at once** (`backend/warcraftlogs.py:48-49`). Bad credentials, a bad query or an unknown guild will not succeed on a second try.
- On 429 or 5xx it sleeps, using the `Retry-After` header when present (capped at 30 seconds, `RETRY_BACKOFF_MAX * 3`), otherwise `1 * 2^attempt` seconds capped at 10 (`backend/warcraftlogs.py:50-56`).
- On a network error (timeout, connection reset) it backs off the same way and logs `[Retry]` (`backend/warcraftlogs.py:57-62`).
- When it gives up it raises `Request failed after N attempt(s)` with the last error (`backend/warcraftlogs.py:63`).

#### Token: `get_access_token`

`get_access_token(client_id, client_secret)` (`backend/warcraftlogs.py:91`):

1. Hashes `client_id:client_secret` with SHA-256 and returns the cached token for that key if it hasn't expired (`backend/warcraftlogs.py:93-97`).
2. Otherwise posts `grant_type=client_credentials` to `OAUTH_TOKEN_URL`, with the pair as a Basic auth header, a 60 second timeout and 2 retries (`backend/warcraftlogs.py:101-121`).
3. Drops expired entries and stores the new token to expire 60 seconds before `expires_in` (default 3600) (`backend/warcraftlogs.py:126-134`).

The cache is a module-level dict guarded by a lock (`backend/warcraftlogs.py:26-27`). `backend/test_api.py:225-240` checks that two credential pairs get two tokens and that a repeat call is served from cache.

#### Queries: `graphql_query`

`graphql_query(token, query, variables=None, timeout=120, max_retries=3)` (`backend/warcraftlogs.py:140`) posts `{"query", "variables"}` with a bearer token. If the response has an `errors` key it raises (`backend/warcraftlogs.py:169-170`); otherwise it returns `data`. Callers that must not stall pass a tighter budget: the roster uses `timeout=40, max_retries=1` (`backend/warcraftlogs.py:289-290`).

#### Name normalization: `normalize_character_name`

`normalize_character_name` (`backend/warcraftlogs.py:65`) decomposes to NFD and drops combining marks, so "Fîshy" becomes "Fishy" (`backend/warcraftlogs.py:80-88`). It is used for roster names, actor names, spec names and death targets. The raw spelling survives as `logName` on each friendly (`backend/warcraftlogs.py:452`) because WCL filters need it (`backend/defensives.py:973-974`).

#### The query functions

```steps
- title: get_guild_reports | short: Reports | sub: 100 per page, max 50
  body: Converts the YYYY-MM-DD window to epoch ms (the end date is inclusive to 23:59:59.999), slugifies the server (lowercase, spaces to hyphens, apostrophes removed) and uppercases the region (backend/warcraftlogs.py:192-226). Pages until a page returns fewer than 100 rows. Returns [{id, start, end, owner}].
  gotcha: A report with exactly 100 rows on its last page costs one extra empty page; harmless.
- title: get_guild_roster | short: Roster | sub: parallel pages
  body: Fetches pages 1-3 at once, reads last_page, then fetches pages 4 to min(last_page, 12) at once (backend/warcraftlogs.py:277-323). Failed pages are logged and skipped. Returns a set of lowercase, accent-stripped names, or an empty set.
  gotcha: If last_page can't be read from any of the first pages, it fetches up to MAX_PAGES (12).
- title: get_report_fights | short: Fight list | sub: light, 1 point
  body: One query for the report's startTime and its fights (id, times, name, encounterID, difficulty, kill, gameZone), with no players or abilities (backend/warcraftlogs.py:340-360). Fights come back in get_fights' shape, without friendlyPlayers. Its docstring records the cost: 1 WCL point, against 3 for get_fights (backend/warcraftlogs.py:334-336). Read for every report so duplicate pulls can be dropped before the full read.
  gotcha: Any error returns empty values (backend/warcraftlogs.py:361-366), so an unreadable report just contributes no pulls.
- title: get_fights | short: Fights | sub: one round trip
  body: One query for fights (id, times, name, encounterID, difficulty, kill, gameZone, friendlyPlayers), Player actors, abilities (name, school bitmask, icon) and playerDetails (backend/warcraftlogs.py:390-426). Returns report_start, fights, friendlies, player_details, abilities, ability_schools and ability_icons. Only the reports that pulls are kept from are read this way.
  gotcha: Any error returns the same shape with empty values (backend/warcraftlogs.py:494-496). The Analyze stream then drops that report and re-runs dedup, so its pulls go to another log's copy (backend/app.py:275-278).
- title: get_report_deaths_bulk | short: Deaths | sub: one query per report
  body: Queries Deaths events over the span of the kept pulls; with cheat-death detection it adds Debuffs and Healing blocks filtered by ability.id in the same query via aliases (backend/analysis.py:395-470). Deaths are grouped by fight, named from the actor map and the ability map (backend/analysis.py:626-662).
  gotcha: On failure it re-raises (backend/analysis.py:705) so the caller records the report as failed and does not cache an empty result.
```

#### Pagination

WCL returns at most `limit: 10000` events and a `nextPageTimestamp` when more remain. Three helpers follow it:

| Helper {paging} | Used by | Shape |
|---|---|---|
| `_fetch_remaining_events` {paging} | death, debuff and save-heal blocks | one event type, startTime/endTime, optional filter, max 50 pages (`backend/analysis.py:329-354`) |
| `_paged` {paging} | `fetch_combatants`, `fetch_defensive_raw` | builds the query from optional `fightIDs`, `startTime`, `endTime`, filter and `includeResources`, max 50 pages; an optional `shape` trims each event as its page arrives (`backend/defensives.py:208-234`) |
| `_fetch_blocks` {paging} | `fetch_death_windows`, `fetch_instakills`, `build_raid_wide.py` | many aliased blocks per request, 20 per request; only blocks with a next page are asked again, max 50 rounds; an optional `keep` drops events as each page arrives (`backend/defensives.py:906-934`) |

## Context map

```context
depends-on: the WCL Cloudflare Worker proxy (GraphQL and OAuth URLs)
depends-on: requests, for HTTP
provides: get_access_token, graphql_query, get_guild_reports, get_guild_roster, get_report_fights, get_fights
provides: get_report_deaths_bulk and the paged event helpers
relied-on-by: [[backend]] — the Analyze stream calls each function in turn
relied-on-by: [[backend-defensive-analysis]] — defensives.py builds its event queries on graphql_query
relied-on-by: the build and check scripts in backend/scripts
```

## Invariants

- **MUST** fail 4xx responses other than 429 without retrying (`backend/warcraftlogs.py:48`); retrying cannot fix bad credentials or a bad query, and would only burn time.
- **MUST** raise when the GraphQL response carries `errors` (`backend/warcraftlogs.py:169`), so partial data is never treated as complete.
- **MUST** follow `nextPageTimestamp` on every event fetch, so long reports don't silently lose events past the first page (`backend/analysis.py:473-484`).
- **NEVER** put an accent-stripped name into a WCL filter: filters use the raw `logName` (`backend/defensives.py:973-974`).

## Gotchas

- **Two retry layers can stack**: `graphql_query` itself does not retry, but `make_request_with_retry` does, up to 4 attempts with backoff. A caller that loops (the roster's parallel pages) multiplies the wait unless it passes a small `max_retries`.
- **The fight readers swallow errors**: `get_report_fights` and `get_fights` return empty values for an unreadable report (`backend/warcraftlogs.py:361-366`, `backend/warcraftlogs.py:494-496`), while `get_report_deaths_bulk` raises. A report can therefore be silently absent at the fights step but loudly failed at the deaths step.
- **Events are matched by ID after the fact**: casts and buffs come back for every player, then `filter_defensive_raw` keeps only the dead players' events (and every player's loadout, for auras they cast on someone who died) (`backend/defensives.py:311-323`), because WCL returns nothing for `source.id in (...)` filters on those types (docstring at `backend/defensives.py:274-279`).

## Glossary

- **nextPageTimestamp**: the timestamp WCL returns when an events query hit its limit; the next request starts there.
- **Alias**: a GraphQL name like `deaths:` or `p12:` that lets one request ask for several `events` blocks at once.
- **logName**: a player's name exactly as written in the log, accents included; used only in WCL filter expressions.

## Related

- [[warcraftlogs]] — the order these calls happen in during one analysis
- [[warcraftlogs-point-budget]] — why the queries are shaped the way they are
- [[backend]] — the Analyze stream that calls them
- [[backend-defensive-analysis]] — the defensive and death-window fetchers built on graphql_query
- [[testing]] — `test_api.py` covers the per-credential token cache
