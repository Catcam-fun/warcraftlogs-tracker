---
id: testing
title: Testing & Checks
domain: testing
status: documented
summary:
  - "Two kinds of confidence: offline unit tests (thirteen backend unittest files, two frontend jest files) and real-log check scripts that compare the analysis with live WarcraftLogs data."
  - "Backend tests are unittest.TestCase classes run from backend/ with python -m unittest (pytest also collects them, but it is not in requirements.txt)."
  - "Frontend tests run under Create React App's jest with npm test in frontend/."
  - "The check scripts need WCL_CLIENT_ID and WCL_CLIENT_SECRET and spend that key's WarcraftLogs points; only check_deaths.py sets a failing exit code."
  - "Only the hand-started AWS deploy workflow runs the unit tests; nothing runs them on pull requests."
tagline: What is tested offline, what is checked against real logs, and what is not covered.
anchors:
  test_api: backend/test_api.py:253
  test_api_fetch_order: backend/test_api.py:336
  test_raid_selection: backend/test_raid_selection.py:5
  test_death_slots: backend/test_death_slots.py:14
  test_cache: backend/test_cache.py:18
  test_defensives: backend/test_defensives.py:38
  test_boss_spell_text: backend/test_boss_spell_text.py:24
  analyze_config_test: frontend/src/AnalyzeConfig.test.js:22
  api_test: frontend/src/api.test.js:14
  npm_test: frontend/package.json:22
  check_deaths: backend/scripts/check_deaths.py:24
  check_deaths_exit: backend/scripts/check_deaths.py:55
  check_durations: backend/scripts/check_durations.py:52
  check_mitigation: backend/scripts/check_mitigation.py:30
  check_defensives: backend/scripts/check_defensives.py:18
  only_workflow: .github/workflows/atlas-sync.yml:1
links:
  - backend
  - backend-death-counting
  - backend-defensive-analysis
  - backend-caching-and-limits
  - frontend
  - game-data
  - warcraftlogs
  - operations
content_hash: sha256:9cd14ba730c3e933c703dcac35555ca5f20da4c9da54a565635e69dfbe750f75
---
## Summary

- **Unit tests** run offline. The backend ones mock WarcraftLogs and Supabase, so they need no keys and no network; the frontend ones mock `fetch` and the Supabase client.
- **Real-log checks** are scripts in `backend/scripts/check_*.py`. Each reads one or more real WarcraftLogs reports and compares what the analysis reads or predicts with what the log shows.
- Run the unit tests on every change. Run the checks after a new raid tier, a new patch, or any change to how deaths or defensives are fetched; [[operations]] lists where they fit in the new-tier procedure.
- Little runs automatically. The AWS deploy workflow runs both unit suites before it deploys (`.github/workflows/deploy-aws.yml:54`, `.github/workflows/deploy-aws.yml:60`); it runs on every push to `main` and when started by hand (`.github/workflows/deploy-aws.yml:14`), not on pull requests. The pull-request workflow, `.github/workflows/atlas-sync.yml:1`, only checks that these docs are in sync with their generated HTML. The real-log checks never run automatically.

## Reference

Every test file and check script. Filter by kind.

| File {backend} | What it covers | Key cases |
|---|---|---|
| `backend/test_api.py` {backend} | Storage, endpoint auth, token cache, rate limiter, and full `/api/analyze` runs with WarcraftLogs mocked out (`backend/test_api.py:253`) | five saves per user; saves and shares strip `clientId` / `clientSecret`; legacy plain-JSON rows still load; shares fall back to memory without a database (`backend/test_api.py:151`); signed-in routes reject anonymous calls; tokens cached per credential; finished reports are served from cache on a second run (`backend/test_api.py:314`); talent loadouts are read first, once per report, and handed to the defensive fetch instead of read again (`backend/test_api.py:336`); a report with no death that can count reads no defensives and no death windows (`backend/test_api.py:344`); of two logs of the same pull only the kept one is read in full (`backend/test_api.py:353`); a pull moves to the other log when its own log can't be read in full (`backend/test_api.py:362`); a report whose deaths fail adds no pulls (`backend/test_api.py:390`); roster filter off skips the roster fetch (`backend/test_api.py:375`); cheat deaths need sign-in (`backend/test_api.py:406`) |
| `backend/test_raid_selection.py` {backend} | `analyze_fights` and `resolve_report_window` for raid tiers (`backend/test_raid_selection.py:5`) | Season 2 keeps its 9 encounters at each difficulty; earlier raid keys exclude Season 2 fights; an unknown raid key falls back to the zone filter; Season 2 date window clamps user dates (`backend/test_raid_selection.py:51`) |
| `backend/test_death_slots.py` {backend} | `rank_pull_deaths` and `drop_saves_that_died` (`backend/test_death_slots.py:14`) | cheat deaths never push real deaths out; simultaneous deaths take one slot each; a rezzed player takes two slots; wipe deaths never count and cheat deaths do not make a wipe; a save only counts if the player survived it |
| `backend/test_dedup.py` {backend} | `dedup_pulls` (`backend/test_dedup.py:11`) | the earliest copy of a pull is kept; a pull only one log has is kept; another boss is never a copy; a copy cut short by more than 5 s gives way to the full one; clock jitter keeps the earliest; same-start ties go by report code |
| `backend/test_cache.py` {backend} | `SharedReportCache` and the Supabase encoding (`backend/test_cache.py:18`) | int and tuple keys survive the round trip; memory first, then the shared store; keys carry namespace and `CACHE_VERSION`; a missing database is a cache miss |
| `backend/test_defensives.py` {backend} | `defensives.py` against the committed catalog (`backend/test_defensives.py:38`) | talents decide which abilities a player has; cooldowns, charges and resets between pulls; would-it-have-saved replays (immunities, school-limited reductions, combined defensives, shields); consumable estimates; per-patch catalog choice (`backend/test_defensives.py:400`); per-pull spec; lethal-window hits, set-up hit and rot labels; armor and Bear Form |
| `backend/test_boss_spell_text.py` {backend} | `render` in `scripts/build_boss_spell_text.py` and the generated `boss_spell_text.py` (`backend/test_boss_spell_text.py:24`) | description templates filled only where game data is exact; the generated file has Sever's text |
| `backend/test_bodies.py` {backend} | `json_body`, the gzip-aware request reader (`backend/test_bodies.py:12`) | plain JSON still works; gzip bodies are read; bad bodies give `None`; a compressed body cannot expand past the size cap |
| `backend/test_ratelimit.py` {backend} | `client_ip()`, the rate limiter's key (`backend/test_ratelimit.py:12`) | Cloudflare's `CF-Connecting-IP` is used; a forged `X-Forwarded-For` does not change the key; on AWS `X-Viewer-Ip` is trusted only with the origin secret (`backend/test_ratelimit.py:33`) |
| `backend/test_origin_lock.py` {backend} | The CloudFront-only lock on AWS (`backend/test_origin_lock.py:8`) | without a secret everything is open; requests without it get 403; health check and warm-up ping stay open |
| `backend/test_streaming.py` {backend} | The SSE keepalive wrapper (`backend/test_streaming.py:7`) | messages pass through in order; keepalives while the source is quiet; source errors reach the caller |
| `backend/test_wago_cache.py` {backend} | `WAGO_CACHE` in the catalog build script (`backend/test_wago_cache.py:11`) | live tables are never served from the cache; pinned builds are |
| `backend/test_armor_build.py` {backend} | `build_armor_constants.py` event reading (`backend/test_armor_build.py:33`) | every page of a fight is read |
| `frontend/src/AnalyzeConfig.test.js` {frontend} | The raid picker (`frontend/src/AnalyzeConfig.test.js:22`) | five raid cards; Season 2 is one combined card; clicking sends `selectedRaid` and shows the right lineup (9, 9 and 8 bosses) |
| `frontend/src/api.test.js` {frontend} | `api.js` helpers (`frontend/src/api.test.js:14`) | `stripSecrets`; bearer token on signed-in calls; fail fast without a session; network failure gives a readable error; credentials remembered in `localStorage` and cleared when emptied |
| `backend/scripts/check_deaths.py` {check} | Deaths the site reads vs WarcraftLogs' own Deaths table (`backend/scripts/check_deaths.py:24`) | Mythic pulls of the raid key only (`backend/scripts/check_deaths.py:32`); compares player, pull, timestamp and killing-blow name |
| `backend/scripts/check_durations.py` {check} | How long personal defensives with duration talents last, predicted vs real aura uses (`backend/scripts/check_durations.py:52`) | Mythic pulls; within 350 ms is exact (`backend/scripts/check_durations.py:32`) |
| `backend/scripts/check_mitigation.py` {check} | Catalog damage reductions vs real hits with and without the defensive up (`backend/scripts/check_mitigation.py:30`) | boss pulls, optionally a list of fight IDs |
| `backend/scripts/check_defensives.py` {check} | Prints one report's full defensive picture per death (`backend/scripts/check_defensives.py:18`) | warns if talent entry IDs never match the catalog (`backend/scripts/check_defensives.py:45`) |

What each check takes and what passing looks like:

| Script {check} | Arguments | Passing looks like |
|---|---|---|
| `check_deaths.py` {check} | `<reportCode>:<raid key> ...` | `missing 0, extra 0, different killing blow 0` for every report; exit code 1 otherwise (`backend/scripts/check_deaths.py:55`). Stops if a pull has 200 deaths, the table's cap (`backend/scripts/check_deaths.py:42`). |
| `check_durations.py` {check} | `<reportCode>:<raid key> ...` | no `<-- LONGER` flag; a defensive is flagged when more than a tenth of its uses outlast the prediction (`backend/scripts/check_durations.py:110`). "Ended early" is normal. A press while the aura is up (a refresh) starts a new use that keeps up to 30% of the time left (`carried_over`, `backend/scripts/check_durations.py:42`). Each aura ID is timed on its own, except The War Within's Renewing Blaze heal-back (`NOT_THE_BUTTON`, `backend/scripts/check_durations.py:36`). Uses stretched by a mastery or by Smoke Screen's Exhilaration (`EXTENDED_BY`, `backend/scripts/check_durations.py:39`) count as "extended", not longer. Raid cooldowns other players cast, Dancing Rune Weapon and Metamorphosis can read longer without affecting a verdict (docstring, `backend/scripts/check_durations.py:18`). |
| `check_mitigation.py` {check} | `<reportCode> [fightID,...]` | no `<-- check` flag: measured and catalog reduction within 0.03 for any defensive with 20 or more hits (`backend/scripts/check_mitigation.py:26`, `backend/scripts/check_mitigation.py:97`). Reads all damage taken, so pass a few fight IDs on a big report. |
| `check_defensives.py` {check} | `<reportCode> [fightID]` | no pass/fail; read the printed deaths. A `!! Talent entry IDs never match` line means the talent format changed. |

## Standing it up

| Concern | This domain | Source |
|---|---|---|
| Backend runner | `cd backend && python -m unittest` (every test is a `unittest.TestCase`; imports such as `import app` need `backend/` as the working directory) | `backend/test_*.py` |
| Backend dependencies | `pip install -r backend/requirements.txt` first: tests import `supabase_client`, which needs `brotli` and `supabase` | `backend/requirements.txt` |
| pytest | not listed in `requirements.txt`; install it separately if you prefer it | `backend/requirements.txt` |
| Frontend runner | `cd frontend && npm test` (`react-scripts test`, watch mode; `CI=true` runs once) | `frontend/package.json:22` |
| Check scripts | `WCL_CLIENT_ID` and `WCL_CLIENT_SECRET` in the environment (`backend/scripts/check_deaths.py:27`) | your own WarcraftLogs API client |
| Check cost | each check spends the key's WarcraftLogs points; `check_mitigation.py` reads all damage taken in the chosen pulls | script docstrings |
| CI | unit tests run only in the AWS deploy, on pushes to `main` or by hand (`.github/workflows/deploy-aws.yml:54`); `.github/workflows/atlas-sync.yml` only verifies the Atlas on pull requests | `.github/workflows/` |

## Invariants

- **MUST** keep `check_deaths.py` at zero missing, zero extra and zero different killing blows on a Mythic log of every raid key after any change to how deaths are fetched; its exit code is the only automated pass/fail among the checks (`backend/scripts/check_deaths.py:55`).
- **NEVER** let the unit tests reach WarcraftLogs or Supabase: they patch `get_access_token`, `get_report_fights`, `get_fights`, `get_report_deaths_bulk` and the `defensives` fetchers (`backend/test_api.py:288`), and swap `supabase_client.db` for a fake (`backend/test_api.py:83`), so they run without keys.

## Gotchas

- **No test runs on a pull request**: the unit suites run only when someone starts the AWS deploy workflow. A broken test is otherwise found only when someone runs it locally.
- **Frontend death counting has no test**: `frontend/src/deathCounting.js` decides what counts when you change "first X" on the Results page, including the fallback for results saved before slots existed. Only the backend half (`rank_pull_deaths`) is tested.
- **The WarcraftLogs retry path is untested**: `make_request_with_retry` (`backend/warcraftlogs.py:30`), with its 4xx-no-retry rule and `Retry-After` handling, has no test. Only the token cache is (`backend/test_api.py:225`).
- **Report-cache eviction is untested**: `evict_report_cache` (`backend/supabase_client.py:395`) and the five-minute back-off after an error have no test; `test_cache.py` covers only the retry of a reset connection (`backend/test_cache.py:60`).
- **Date windows are tested for one raid**: `test_season_two_default_and_custom_date_windows` covers `midnight-s2-all` only. The other seven windows in `RAID_DATE_WINDOWS` are not asserted.
- **Some tests read generated data**: `test_defensives.py` runs against the committed `defensive_catalog.py`, and `test_generated_file` expects Sever's text in `boss_spell_text.py` (`backend/test_boss_spell_text.py:34`). Rebuilding those modules can change what these tests see.
- **The checks only look at Mythic**: `check_deaths.py` and `check_durations.py` pass difficulty 5 to `analyze_fights`. They also pass `None` as the zone, so a raid key missing from `RAID_ENCOUNTERS` fails with a type error rather than a clear message.
- **The Analyze form test is pinned to today's raid list**: it expects exactly five raid cards (`frontend/src/AnalyzeConfig.test.js:28`), so adding a tier means updating it.

## Related

- [[backend]] — the code most tests exercise
- [[backend-death-counting]] — the slot and wipe rules `test_death_slots.py` pins down
- [[backend-defensive-analysis]] — what `test_defensives.py` and the defensive checks verify
- [[backend-caching-and-limits]] — the caches and limiter `test_cache.py` and `test_api.py` cover
- [[frontend]] — where the two jest files live
- [[game-data]] — the generated modules the tests and checks read
- [[warcraftlogs]] — the API the check scripts call
- [[operations]] — when to run the checks during a new raid tier
