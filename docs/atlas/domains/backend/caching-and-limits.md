---
id: backend-caching-and-limits
title: Caching and Rate Limits
domain: backend
status: documented
summary:
  - "Finished WarcraftLogs reports never change, so their fights, deaths, defensive events and pre-death hits are cached and reused across analyses and users."
  - "Each of the four report caches is a SharedReportCache: an in-process LRU in front of the Supabase report_cache table."
  - "Only reports whose last event is more than two hours old (REPORT_CACHE_MIN_AGE_MS) are read from or written to the cache."
  - "The Supabase table is best-effort and kept under 200 MB by deleting the least recently used rows; any error is a cache miss and pauses the shared cache for 5 minutes."
  - "Analyze, share and save are rate-limited per client IP with in-memory sliding windows: 60, 20 and 30 calls per hour."
tagline: The report caches that keep WarcraftLogs costs down, and the per-IP limits on expensive routes.
anchors:
  min_age: "backend/app.py:46"
  limiters: "backend/app.py:52"
  lru_cache: "backend/cache.py:17"
  shared_cache: "backend/cache.py:42"
  shared_get: "backend/cache.py:69"
  shared_set: "backend/cache.py:77"
  cache_version: "backend/cache.py:85"
  writer_pool: "backend/cache.py:86"
  report_caches: "backend/cache.py:91"
  budget: "backend/supabase_client.py:273"
  enc: "backend/supabase_client.py:281"
  cache_get: "backend/supabase_client.py:321"
  cache_put: "backend/supabase_client.py:340"
  evict: "backend/supabase_client.py:362"
  report_cache_table: "backend/migrations/002_report_cache.sql:12"
  client_ip: "backend/ratelimit.py:18"
  rate_limiter: "backend/ratelimit.py:34"
  limit: "backend/ratelimit.py:56"
links:
  - backend
  - backend-analysis-pipeline
  - backend-api-endpoints
  - backend-defensive-analysis
  - warcraftlogs
  - data-model
  - frontend-results-view
  - feat-analyze
invariants:
  - "MUST: read or write the report caches only for finished reports (end time more than REPORT_CACHE_MIN_AGE_MS ago); a live-logged report is always fetched."
  - "MUST: bump CACHE_VERSION when what is fetched or how it is indexed changes, so old rows are never served to new code."
  - "MUST: treat every shared-cache failure as a miss; an analysis never fails because Supabase is down."
  - "NEVER: make an analysis wait on a Supabase cache write; writes run on a background pool."
  - "NEVER: give the anon or authenticated roles access to report_cache; only the service role reads and writes it."
content_hash: sha256:f69d2a8f868f9563f6dbc38635747d09351b2843b1c6ba22c05f0b6c585b7d00
---
## Summary

- An analysis can touch dozens of reports. The caches make a second analysis of the same guild, or another officer's analysis, cost few or no WarcraftLogs API points. The module docstring states the idea: a finished report never changes (`backend/cache.py:4`).
- There are four caches, one per kind of report data (`backend/cache.py:91`). Each is a **SharedReportCache**: memory first, then the shared Supabase table `report_cache` ([[data-model]]).
- "Finished" means the report's end time is more than two hours old (`REPORT_CACHE_MIN_AGE_MS`, `backend/app.py:46`, `backend/app.py:208`). Anything newer may still be live-logging, so it is always fetched.
- Rate limits are separate: `RateLimiter` windows in process memory, keyed by client IP (`backend/ratelimit.py:34`), applied by the `limit` decorator (`backend/ratelimit.py:56`).

## How it works

A cache read and write, for one finished report.

```steps
- title: Check memory | short: Memory | sub: LRUCache.get
  body: `SharedReportCache.get` first asks its in-process `LRUCache` (`backend/cache.py:69`). A hit moves the key to the most recently used end (`backend/cache.py:27`). The LRU is guarded by a lock, because the analysis fetches reports on several threads.
- title: Check Supabase | short: Shared table | sub: cache_get
  body: On a memory miss it calls `supabase_client.cache_get` with a namespaced, versioned key such as `v2:deaths:<repr of key>` (`backend/cache.py:60`, `backend/cache.py:72`). A row found is unpacked, decoded and copied into memory (`backend/cache.py:74`); its `last_used_at` is bumped (`backend/supabase_client.py:334`).
  gotcha: The key is Python's `repr()` of the tuple key. Changing the shape of a key changes its text, which is a miss, not a wrong hit.
- title: Fetch on a miss | short: WarcraftLogs | sub: only when both miss
  body: Only when both layers miss does the pipeline query WarcraftLogs (`backend/app.py:217`, `backend/app.py:353`). See [[backend-analysis-pipeline]].
- title: Write both layers | short: Store | sub: memory now, Supabase later
  body: `SharedReportCache.set` writes memory at once and submits `cache_put` to a two-thread background pool (`backend/cache.py:77`, `backend/cache.py:86`), so the analysis never waits on Supabase. `cache_put` skips rows over 4 MB compressed (`backend/supabase_client.py:347`) and upserts the rest.
- title: Evict | short: Evict | sub: every 20 writes
  body: Every 20th successful write in the process (`_EVICT_EVERY`) runs `evict_report_cache` (`backend/supabase_client.py:275`, `backend/supabase_client.py:355`). It reads every row's size, newest use first, and deletes rows past the 200 MB running total, in batches of 100 (`backend/supabase_client.py:362`).
```

#### What is cached, and under which key

| Cache {cache} | Namespace | Memory items | Key | Value | Written at |
|---|---|---|---|---|---|
| `report_meta_cache` {cache} | `meta` | 200 | report code | fights, actors, abilities, icons; only if it has fights | `backend/app.py:219` |
| `report_deaths_cache` {cache} | `deaths` | 400 | report, fight ids, cheat-deaths flag, cheat-death spell ids | deaths by fight | `backend/app.py:337`, `backend/app.py:362` |
| `report_defensive_cache` {cache} | `defensives` | 200 | report, fight ids, dead players, catalog patch and fingerprint | filtered defensive events | `backend/app.py:344`, `backend/app.py:368` |
| `report_recap_cache` {cache} | `killing-blows` | 400 | report, fight ids, `instakills`; or report, counted deaths, `lethal-window`, window length | instant kills; hits before deaths | `backend/app.py:377`, `backend/app.py:393` |

The keys carry everything that changes the answer. The deaths key includes the list of cheat-death spells when cheat deaths are on, so adding a spell refetches (`backend/app.py:336`). The defensive key includes the catalog's patch and `CATALOG_FINGERPRINT`, so a rebuilt catalog refetches. See [[backend-defensive-analysis]].

#### Encoding

Cached values are Python structures with integer and tuple keys, tuples and sets, which JSON cannot hold. `_enc` wraps them in tagged objects (`__d` for a dict with non-string keys, `__t` for a tuple, `__s` for a set) and `_dec` reverses it exactly (`backend/supabase_client.py:281`, `backend/supabase_client.py:295`). The result is then compressed the same way as saved analyses: brotli, base64, `br64:` prefix (`backend/supabase_client.py:68`).

#### Failure handling

`_cache_available` is false when Supabase is not configured or after a recent failure (`backend/supabase_client.py:311`). Any read or write error calls `_cache_failed`, which logs and turns the shared cache off for 300 seconds (`backend/supabase_client.py:315`). In that time `cache_get` returns None and `cache_put` does nothing, and the in-memory LRU keeps working.

#### Rate limits

`RateLimiter.allow(key)` keeps a deque of hit times per key (`backend/ratelimit.py:41`). It drops hits older than the window, refuses when the window already holds `max_calls` hits, and otherwise records the hit. When more than 10,000 keys are tracked, keys with no hits left are deleted so memory stays bounded (`backend/ratelimit.py:50`).

`limit(limiter, message)` wraps a route: a non-OPTIONS request over the limit gets 429 `{"success": false, "error": message}` before the route runs (`backend/ratelimit.py:56`, `backend/ratelimit.py:60`). The key is `client_ip()`: the first entry of `X-Forwarded-For`, else the socket address, else `unknown` (`backend/ratelimit.py:18`).

## Diagram

The two cache layers and the background writer.

```diagram
lane app Analysis threads
node pipe lane=app color=process "Pipeline" "finished reports"
lane mem Process memory
node lru lane=mem color=safe "LRUCache" "per namespace"
node writer lane=mem color=structural "Writer pool" "2 threads"
lane ext Supabase
node table lane=ext color=structural "report_cache" "200 MB budget"
node evict lane=ext color=caution "Evict LRU rows" "every 20 writes"
lane src Source
node wcl lane=src color=caution "WarcraftLogs" "on full miss"
edge pipe -> lru color=safe "get / set"
edge lru -> table color=structural "miss: cache_get"
edge lru -> writer color=structural "set"
edge writer -> table color=structural "cache_put"
edge table -> evict color=caution "over budget"
edge pipe -> wcl color=caution "both miss"
```

## Reference

| Setting {cache} | Value | Where |
|---|---|---|
| `REPORT_CACHE_MIN_AGE_MS` {cache} | 2 hours | `backend/app.py:46` |
| `CACHE_VERSION` {cache} | `v2` | `backend/cache.py:85` |
| Writer pool {cache} | 2 threads, `report-cache` | `backend/cache.py:86` |
| `REPORT_CACHE_BUDGET_BYTES` {table} | 200 MB | `backend/supabase_client.py:273` |
| `REPORT_CACHE_MAX_ROW_BYTES` {table} | 4 MB compressed | `backend/supabase_client.py:274` |
| `_EVICT_EVERY` {table} | 20 writes | `backend/supabase_client.py:275` |
| Back-off after an error {table} | 300 s | `backend/supabase_client.py:317` |
| `analyze_limiter` {limit} | 60 per hour per IP | `backend/app.py:53` |
| `share_limiter` {limit} | 20 per hour per IP | `backend/app.py:52` |
| `save_limiter` {limit} | 30 per hour per IP | `backend/app.py:54` |
| Tracked-key cleanup {limit} | above 10,000 keys | `backend/ratelimit.py:50` |

The `report_cache` table (`backend/migrations/002_report_cache.sql:12`): `key` text primary key, `payload` text, `size_bytes` integer, `created_at` and `last_used_at` timestamps, an index on `last_used_at`, and row-level security on with no policies, so only the service role can use it (`backend/migrations/002_report_cache.sql:21`).

## Context map

```context
depends-on: [[data-model]] — the report_cache table and the Supabase client
depends-on: [[warcraftlogs]] — the source the caches stand in front of
provides: memory-plus-Supabase caches for meta, deaths, defensives and pre-death hits
provides: per-IP rate limits and client_ip
relied-on-by: [[backend-analysis-pipeline]] — reads and writes the caches for finished reports
relied-on-by: [[backend-api-endpoints]] — analyze, share and save use the limit decorator
relied-on-by: [[backend-defensive-analysis]] — its data is cached under catalog-aware keys
relied-on-by: [[feat-analyze]] — repeat analyses come back faster and cheaper
```

## Invariants

- **MUST** read or write the report caches only for finished reports; a live-logged report is always fetched (`backend/app.py:213`, `backend/app.py:339`).
- **MUST** bump `CACHE_VERSION` when what is fetched or how it is indexed changes, so old rows are never served to new code (`backend/cache.py:46`).
- **MUST** treat every shared-cache failure as a miss; an analysis never fails because Supabase is down (`backend/supabase_client.py:271`).
- **NEVER** make an analysis wait on a Supabase cache write; writes run on a background pool (`backend/cache.py:79`).
- **NEVER** give the anon or authenticated roles access to `report_cache`; only the service role reads and writes it (`backend/migrations/002_report_cache.sql:21`).

## Environments

| Aspect | Local | Production |
|---|---|---|
| Shared cache | used only if `SUPABASE_URL` and a key are set (`backend/supabase_client.py:39`); otherwise memory only | on, through the service-role key |
| Table missing | first error pauses the shared cache for 5 minutes, repeatedly | same; run `backend/migrations/002_report_cache.sql` once |
| Rate limits | same numbers, per process | same; per gunicorn process |
| `client_ip` | the socket address, usually `127.0.0.1` | `CF-Connecting-IP` set by Cloudflare in front of Render |

## Gotchas

- **Memory caches and limits are per process**: with more than one gunicorn worker, each has its own LRU and its own rate-limit windows, so the effective limit multiplies (see [[backend]]).
- **The key is `CF-Connecting-IP`, not `X-Forwarded-For`**: Render appends to a client-supplied `X-Forwarded-For`, so its first entry can be forged; Cloudflare sets `CF-Connecting-IP` itself (`backend/ratelimit.py:19-31`). Without Cloudflare in front, every client would share the proxy's address and one limit.
- **A memory hit for a deaths entry decides whether defensives are looked up**: the defensive cache is consulted only when the deaths came from cache, because its key needs the set of dead players (`backend/app.py:350`).
- **The 2-hour rule uses the report's end time**: a report still being logged tonight is fetched in full on every analysis until two hours after its last event (`backend/app.py:207`).
- **Eviction reads every row's key and size**: `evict_report_cache` selects the whole table's `key, size_bytes` each time it runs (`backend/supabase_client.py:366`). That is cheap at 200 MB of large rows but grows with row count.

## Glossary

- **Finished report**: a report whose `end` is older than `REPORT_CACHE_MIN_AGE_MS`.
- **Namespace**: the cache's kind (`meta`, `deaths`, `defensives`, `killing-blows`), part of every Supabase key.
- **Sliding window**: the last hour of hit times per client IP; a hit is refused once the window holds `max_calls`.

## Related

- [[backend]] — the service landing page and its single-worker rule
- [[backend-analysis-pipeline]] — where the caches are read and written
- [[backend-api-endpoints]] — the routes behind the 429 limits
- [[backend-defensive-analysis]] — why the defensive key includes the catalog
- [[warcraftlogs]] — the API points the caches save
- [[data-model]] — the report_cache table
- [[frontend-results-view]] — renders results that may come from cached data
- [[feat-analyze]] — the analysis a user waits on
