---
id: backend-caching-and-limits
title: Caching and Rate Limits
domain: backend
status: documented
summary:
  - "Finished WarcraftLogs reports never change, so their fight lists, full fights, deaths, defensive events and pre-death hits are cached and reused across analyses and users."
  - "Each of the five report caches is a SharedReportCache: an in-process LRU in front of the Supabase report_cache table."
  - "Only reports whose last event is more than two hours old (REPORT_CACHE_MIN_AGE_MS) are read from or written to the cache."
  - "The Supabase table is best-effort and kept under 200 MB by deleting the least recently used rows; each call is tried up to three times on a fresh connection, and one that still fails is a cache miss and pauses the shared cache for 5 minutes."
  - "Analyze, share and save are rate-limited per client IP with in-memory sliding windows: 60, 20 and 30 calls per hour."
tagline: The report caches that keep WarcraftLogs costs down, and the per-IP limits on expensive routes.
anchors:
  min_age: "backend/app.py:46"
  limiters: "backend/app.py:52"
  lru_cache: "backend/cache.py:17"
  shared_cache: "backend/cache.py:42"
  shared_get: "backend/cache.py:69"
  shared_set: "backend/cache.py:77"
  cache_version: "backend/cache.py:88"
  writer_pool: "backend/cache.py:89"
  report_caches: "backend/cache.py:111"
  budget: "backend/supabase_client.py:273"
  enc: "backend/supabase_client.py:281"
  cache_get: "backend/supabase_client.py:354"
  cache_put: "backend/supabase_client.py:373"
  evict: "backend/supabase_client.py:395"
  report_cache_table: "backend/migrations/002_report_cache.sql:12"
  client_ip: "backend/ratelimit.py:18"
  rate_limiter: "backend/ratelimit.py:32"
  limit: "backend/ratelimit.py:54"
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
content_hash: sha256:bb45ee63797e3dc8d10e70203ecefb4a2d0cf5fdfee23ee1756dd4e6249d21cc
---
## Summary

- An analysis can touch dozens of reports. The caches make a second analysis of the same guild, or another officer's analysis, cost few or no WarcraftLogs API points. The module docstring states the idea: a finished report never changes (`backend/cache.py:4`).
- There are five caches, one per kind of report data (`backend/cache.py:111`). Each is a **SharedReportCache**: memory first, then the shared Supabase table `report_cache` ([[data-model]]).
- "Finished" means the report's end time is more than two hours old (`REPORT_CACHE_MIN_AGE_MS`, `backend/app.py:46`, `backend/app.py:211`). Anything newer may still be live-logging, so it is always fetched.
- Rate limits are separate: `RateLimiter` windows in process memory, keyed by client IP (`backend/ratelimit.py:32`), applied by the `limit` decorator (`backend/ratelimit.py:54`).

## How it works

A cache read and write, for one finished report.

```steps
- title: Check memory | short: Memory | sub: LRUCache.get
  body: `SharedReportCache.get` first asks its in-process `LRUCache` (`backend/cache.py:69`). A hit moves the key to the most recently used end (`backend/cache.py:27`). The LRU is guarded by a lock, because the analysis fetches reports on several threads.
- title: Check Supabase | short: Shared table | sub: cache_get
  body: On a memory miss it calls `supabase_client.cache_get` with a namespaced, versioned key such as `v2:deaths:<repr of key>` (`backend/cache.py:60`, `backend/cache.py:72`). A row found is unpacked, decoded and copied into memory (`backend/cache.py:74`); its `last_used_at` is bumped (`backend/supabase_client.py:367`).
  gotcha: The key is Python's `repr()` of the tuple key. Changing the shape of a key changes its text, which is a miss, not a wrong hit.
- title: Fetch on a miss | short: WarcraftLogs | sub: only when both miss
  body: Only when both layers miss does the pipeline query WarcraftLogs (`backend/app.py:220`, `backend/app.py:230`, `backend/app.py:378`). See [[backend-analysis-pipeline]].
- title: Write both layers | short: Store | sub: memory now, Supabase later
  body: `SharedReportCache.set` writes memory at once and submits `cache_put` to a four-thread background pool (`backend/cache.py:77`, `backend/cache.py:89`), so the analysis never waits on Supabase. `cache_put` skips rows over 4 MB compressed (`backend/supabase_client.py:380`) and upserts the rest. At the end of an analysis, `flush_writes` waits for the queued writes, because Lambda freezes the function once the response ends (`backend/cache.py:99`, `backend/app.py:681`).
- title: Evict | short: Evict | sub: every 20 writes
  body: Every 20th successful write in the process (`_EVICT_EVERY`) runs `evict_report_cache` (`backend/supabase_client.py:275`, `backend/supabase_client.py:391`). It reads every row's size, newest use first, and deletes rows past the 200 MB running total, in batches of 100 (`backend/supabase_client.py:395`).
```

#### What is cached, and under which key

| Cache {cache} | Namespace | Memory items | Key | Value | Written at |
|---|---|---|---|---|---|
| `report_fights_cache` {cache} | `fights` | 400 | report code | light fight list: report start and fights, no players; only if it has fights | `backend/app.py:222` |
| `report_meta_cache` {cache} | `meta` | 200 | report code | full fights, actors, abilities, icons; only reports that keep pulls; only if it has fights | `backend/app.py:232` |
| `report_deaths_cache` {cache} | `deaths` | 400 | report, fight ids, cheat-deaths flag, cheat-death spell ids | deaths by fight | `backend/app.py:355`, `backend/app.py:384` |
| `report_defensive_cache` {cache} | `defensives` | 200 | report, fight ids, dead players, catalog patch and fingerprint | filtered defensive events | `backend/app.py:364`, `backend/app.py:410` |
| `report_recap_cache` {cache} | `killing-blows` | 400 | report, fight ids, `instakills`; or report, counted deaths, `lethal-window`, window length | instant kills; hits before deaths | `backend/app.py:419`, `backend/app.py:427` |

The keys carry everything that changes the answer. The deaths key includes the list of cheat-death spells when cheat deaths are on, so adding a spell refetches (`backend/app.py:354`). The defensive key includes the catalog's patch and `CATALOG_FINGERPRINT`, so a rebuilt catalog refetches. See [[backend-defensive-analysis]].

#### Encoding

Cached values are Python structures with integer and tuple keys, tuples and sets, which JSON cannot hold. `_enc` wraps them in tagged objects (`__d` for a dict with non-string keys, `__t` for a tuple, `__s` for a set) and `_dec` reverses it exactly (`backend/supabase_client.py:281`, `backend/supabase_client.py:295`). The result is then compressed the same way as saved analyses: brotli, base64, `br64:` prefix (`backend/supabase_client.py:68`).

#### Failure handling

Report-cache calls go through `_cache_db`, which gives each thread its own Supabase client (`backend/supabase_client.py:326`). supabase-py sends all of one client's requests over a single HTTP/2 connection, and an analysis reads and writes the cache from many threads at once; on a fresh Lambda that burst got the shared connection reset. `_retrying` tries a read or write up to `CACHE_ATTEMPTS` = 3 times, each retry on a new connection after a short pause (`backend/supabase_client.py:340`).

`_cache_available` is false when Supabase is not configured or after a recent failure (`backend/supabase_client.py:311`). A read or write that still fails after its tries calls `_cache_failed`, which logs and turns the shared cache off for 300 seconds (`backend/supabase_client.py:315`). In that time `cache_get` returns None and `cache_put` does nothing, and the in-memory LRU keeps working. The `last_used_at` bump after a hit is tried once and only logged if it fails (`backend/supabase_client.py:367`).

#### Rate limits

`RateLimiter.allow(key)` keeps a deque of hit times per key (`backend/ratelimit.py:39`). It drops hits older than the window, refuses when the window already holds `max_calls` hits, and otherwise records the hit. When more than 10,000 keys are tracked, keys with no hits left are deleted so memory stays bounded (`backend/ratelimit.py:48`).

`limit(limiter, message)` wraps a route: a non-OPTIONS request over the limit gets 429 `{"success": false, "error": message}` before the route runs (`backend/ratelimit.py:54`, `backend/ratelimit.py:58`). The key is `client_ip()` (`backend/ratelimit.py:18`): on AWS, the `X-Viewer-Ip` header a CloudFront Function writes, trusted only on requests that carry the origin secret (`backend/ratelimit.py:25`); else the socket address; else `unknown` (`backend/ratelimit.py:29`).

## Diagram

The two cache layers and the background writer.

```diagram
lane app Analysis threads
node pipe lane=app color=process "Pipeline" "finished reports"
lane mem Process memory
node lru lane=mem color=safe "LRUCache" "per namespace"
node writer lane=mem color=structural "Writer pool" "4 threads"
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
| `CACHE_VERSION` {cache} | `v2` | `backend/cache.py:88` |
| Writer pool {cache} | 4 threads, `report-cache` | `backend/cache.py:89` |
| `REPORT_CACHE_BUDGET_BYTES` {table} | 200 MB | `backend/supabase_client.py:273` |
| `REPORT_CACHE_MAX_ROW_BYTES` {table} | 4 MB compressed | `backend/supabase_client.py:274` |
| `_EVICT_EVERY` {table} | 20 writes | `backend/supabase_client.py:275` |
| Back-off after an error {table} | 300 s | `backend/supabase_client.py:317` |
| `analyze_limiter` {limit} | 60 per hour per IP | `backend/app.py:53` |
| `share_limiter` {limit} | 20 per hour per IP | `backend/app.py:52` |
| `save_limiter` {limit} | 30 per hour per IP | `backend/app.py:54` |
| Tracked-key cleanup {limit} | above 10,000 keys | `backend/ratelimit.py:48` |

The `report_cache` table (`backend/migrations/002_report_cache.sql:12`): `key` text primary key, `payload` text, `size_bytes` integer, `created_at` and `last_used_at` timestamps, an index on `last_used_at`, and row-level security on with no policies, so only the service role can use it (`backend/migrations/002_report_cache.sql:21`).

## Context map

```context
depends-on: [[data-model]] — the report_cache table and the Supabase client
depends-on: [[warcraftlogs]] — the source the caches stand in front of
provides: memory-plus-Supabase caches for fight lists, meta, deaths, defensives and pre-death hits
provides: per-IP rate limits and client_ip
relied-on-by: [[backend-analysis-pipeline]] — reads and writes the caches for finished reports
relied-on-by: [[backend-api-endpoints]] — analyze, share and save use the limit decorator
relied-on-by: [[backend-defensive-analysis]] — its data is cached under catalog-aware keys
relied-on-by: [[feat-analyze]] — repeat analyses come back faster and cheaper
```

## Invariants

- **MUST** read or write the report caches only for finished reports; a live-logged report is always fetched (`backend/app.py:216`, `backend/app.py:226`, `backend/app.py:357`).
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
| `client_ip` | the socket address, usually `127.0.0.1` | `X-Viewer-Ip` from CloudFront on AWS |

## Gotchas

- **Memory caches and limits are per process**: with more than one gunicorn worker, each has its own LRU and its own rate-limit windows, so the effective limit multiplies (see [[backend]]).
- **The key is never a header the client can set**: `X-Forwarded-For` and `CF-Connecting-IP` can be forged, so they are ignored. CloudFront overwrites `X-Viewer-Ip` and is the only one that sends the origin secret, so only that header is trusted (`backend/ratelimit.py:19-29`). Without it, every client would share the proxy's address and one limit.
- **The defensive cache waits for the deaths**: its key needs the set of dead players, so it is looked up after the deaths are known, from the deaths cache (`backend/app.py:370`) or right after the deaths query (`backend/app.py:385`).
- **A report with no death that can count writes no defensive or hit cache**: it returns after its deaths (`backend/app.py:388`), so only its fight lists, full fights and deaths are cached.
- **The 2-hour rule uses the report's end time**: a report still being logged tonight is fetched in full on every analysis until two hours after its last event (`backend/app.py:210`).
- **Eviction reads every row's key and size**: `evict_report_cache` selects the whole table's `key, size_bytes` each time it runs (`backend/supabase_client.py:399`). That is cheap at 200 MB of large rows but grows with row count.

## Glossary

- **Finished report**: a report whose `end` is older than `REPORT_CACHE_MIN_AGE_MS`.
- **Namespace**: the cache's kind (`fights`, `meta`, `deaths`, `defensives`, `killing-blows`), part of every Supabase key.
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
