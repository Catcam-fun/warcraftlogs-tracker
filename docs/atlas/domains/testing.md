---
id: testing
title: Testing & Checks
domain: testing
status: documented
summary:
  - "Two kinds of confidence: offline unit tests (backend unittest files, two frontend jest files) and the backend/checks package, which compares the analysis with live WarcraftLogs data."
  - "Backend tests are unittest.TestCase classes run from backend/ with python -m unittest (pytest also collects them, but it is not in requirements.txt)."
  - "Frontend tests run under Create React App's jest with npm test in frontend/."
  - "The checks need WCL_CLIENT_ID and WCL_CLIENT_SECRET and spend that key's WarcraftLogs points; python -m checks exits non-zero when any check fails."
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
  check_deaths: backend/checks/source_deaths.py:9
  check_selection: backend/checks/source_selection.py:57
  check_participation: backend/checks/source_participation.py:24
  check_state: backend/checks/source_state.py:281
  check_durations: backend/checks/source_durations.py:30
  check_mitigation: backend/checks/source_mitigation.py:127
  check_slots: backend/checks/rules_slots.py:40
  check_counting: backend/checks/rules_counting.py:27
  check_labels: backend/checks/rules_labels.py:429
  check_verdicts: backend/checks/rules_verdicts.py:168
  check_defensives: backend/checks/rules_defensives.py:5
  checks_registry: backend/checks/registry.py:6
  checks_target: backend/checks/common.py:36
  checks_unit_tests: backend/test_checks.py:1
  carried_over: backend/checks/source_durations.py:20
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
content_hash: sha256:f8f84ac1eb1fb223ae823de04c18b09b431a3e4937bb434c7c97ffd2d96a0da0
---
## Summary

- **Unit tests** run offline. The backend ones mock WarcraftLogs and Supabase, so they need no keys and no network; the frontend ones mock `fetch` and the Supabase client.
- **Real-log checks** are the `backend/checks` package, run as `python -m checks <subcommand> <target>` from `backend/`. Eleven checks read a real WarcraftLogs report, run the site's own analysis on it and compare the two. Its offline unit tests are in `backend/test_checks.py`.
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
| `backend/test_defensives.py` {backend} | `defensives.py` against the committed catalog (`backend/test_defensives.py:38`) | talents decide which abilities a player has; cooldowns, charges and resets between pulls; would-it-have-saved replays (immunities, school-limited reductions, combined defensives, shields); consumable estimates; per-patch catalog choice (`backend/test_defensives.py:424`); per-pull spec; lethal-window hits, set-up hit and rot labels; armor and Bear Form |
| `backend/test_boss_spell_text.py` {backend} | `render` in `scripts/build_boss_spell_text.py` and the generated `boss_spell_text.py` (`backend/test_boss_spell_text.py:24`) | description templates filled only where game data is exact; the generated file has Sever's text |
| `backend/test_bodies.py` {backend} | `json_body`, the gzip-aware request reader (`backend/test_bodies.py:12`) | plain JSON still works; gzip bodies are read; bad bodies give `None`; a compressed body cannot expand past the size cap |
| `backend/test_ratelimit.py` {backend} | `client_ip()`, the rate limiter's key (`backend/test_ratelimit.py:12`) | headers a client can set (`X-Forwarded-For`, `CF-Connecting-IP`, `X-Viewer-Ip` without the secret) do not change the key; `X-Viewer-Ip` is trusted only with the origin secret (`backend/test_ratelimit.py:24`) |
| `backend/test_origin_lock.py` {backend} | The CloudFront-only lock on AWS (`backend/test_origin_lock.py:8`) | without a secret everything is open; requests without it get 403; health check and warm-up ping stay open |
| `backend/test_streaming.py` {backend} | The SSE keepalive wrapper (`backend/test_streaming.py:7`) | messages pass through in order; keepalives while the source is quiet; source errors reach the caller |
| `backend/test_wago_cache.py` {backend} | `WAGO_CACHE` in the catalog build script (`backend/test_wago_cache.py:11`) | live tables are never served from the cache; pinned builds are |
| `backend/test_armor_build.py` {backend} | `build_armor_constants.py` event reading (`backend/test_armor_build.py:33`) | every page of a fight is read |
| `frontend/src/AnalyzeConfig.test.js` {frontend} | The raid picker (`frontend/src/AnalyzeConfig.test.js:22`) | five raid cards; Season 2 is one combined card; clicking sends `selectedRaid` and shows the right lineup (9, 9 and 8 bosses) |
| `frontend/src/api.test.js` {frontend} | `api.js` helpers (`frontend/src/api.test.js:14`) | `stripSecrets`; bearer token on signed-in calls; fail fast without a session; network failure gives a readable error; credentials remembered in `localStorage` and cleared when emptied |
| `backend/checks/source_deaths.py` {check} | `deaths` (source): Deaths the site reads match WCL's Deaths table (`backend/checks/source_deaths.py:9`) | run with `python -m checks deaths <target>` |
| `backend/checks/source_selection.py` {check} | `selection` (source): The pulls and kills the site kept match the guild's reports on WCL (`backend/checks/source_selection.py:57`) | run with `python -m checks selection <target>` |
| `backend/checks/source_participation.py` {check} | `participation` (source): Who was in each kept pull, and who counts as roster, match WCL (`backend/checks/source_participation.py:24`) | run with `python -m checks participation <target>` |
| `backend/checks/source_state.py` {check} | `state` (source): Active, ready and health at death match WCL's auras, casts and Deaths table (`backend/checks/source_state.py:281`) | run with `python -m checks state <target>` |
| `backend/checks/source_durations.py` {check} | `durations` (source): Defensive durations (catalog + talents) match real aura uses (`backend/checks/source_durations.py:30`) | run with `python -m checks durations <target>` |
| `backend/checks/source_mitigation.py` {check} | `mitigation` (source): Catalog damage reductions match real hits with and without the defensive (`backend/checks/source_mitigation.py:127`) | run with `python -m checks mitigation <target>` |
| `backend/checks/rules_slots.py` {check} | `slots` (rules): Slots and wipes follow the owner's rules (`backend/checks/rules_slots.py:40`) | run with `python -m checks slots <target>` |
| `backend/checks/rules_counting.py` {check} | `counting` (rules): A death counts when slot <= X and not in a wipe; defensives exist exactly on deaths that can count (`backend/checks/rules_counting.py:27`) | run with `python -m checks counting <target>` |
| `backend/checks/rules_labels.py` {check} | `labels` (rules): Death labels follow the rules: one-shot, burst, rot (raid-wide only) or set up by (`backend/checks/rules_labels.py:429`) | run with `python -m checks labels <target>` |
| `backend/checks/rules_verdicts.py` {check} | `verdicts` (rules): Would-save verdicts obey the press, overkill, immunity and instant-kill rules (`backend/checks/rules_verdicts.py:168`) | run with `python -m checks verdicts <target>` |
| `backend/checks/rules_defensives.py` {check} | `defensives` (rules): Talent entry IDs in the log match the catalog (`backend/checks/rules_defensives.py:5`) | run with `python -m checks defensives <target>` |
| `backend/test_checks.py` {backend} | Unit tests of the checks package with WarcraftLogs mocked (`backend/test_checks.py:1`) | `test_defensives.py` imports `carried_over` from `checks.source_durations` (`backend/checks/source_durations.py:20`) |

What each check takes and what passing looks like:

| Command {check} | Target | Passing looks like |
|---|---|---|
| `python -m checks all <target> ...` {check} | `<reportCode>:<raid key>` or `<reportCode>:<raid key>:<Guild>/<Server>/<REGION>` (`backend/checks/common.py:36`) | every check prints pass; exit code non-zero if any fails. Use `source`, `rules` or one check name (`deaths`, `state`, `mitigation`, ...) instead of `all` to run fewer (`backend/checks/registry.py:6`). `find-logs` prints one finished Mythic target per raid. `--json <file>` saves the results. |
| A skip | none | the check could not run on this log and says why; a skip is not a pass |

## Standing it up

| Concern | This domain | Source |
|---|---|---|
| Backend runner | `cd backend && python -m unittest` (every test is a `unittest.TestCase`; imports such as `import app` need `backend/` as the working directory) | `backend/test_*.py` |
| Backend dependencies | `pip install -r backend/requirements.txt` first: tests import `supabase_client`, which needs `brotli` and `supabase` | `backend/requirements.txt` |
| pytest | not listed in `requirements.txt`; install it separately if you prefer it | `backend/requirements.txt` |
| Frontend runner | `cd frontend && npm test` (`react-scripts test`, watch mode; `CI=true` runs once) | `frontend/package.json:22` |
| Checks | `WCL_CLIENT_ID` and `WCL_CLIENT_SECRET` in the environment (`backend/checks/common.py:95`) | your own WarcraftLogs API client |
| Check cost | each run prints the WarcraftLogs points it spent; a whole `all` run costs about 200-500 | `backend/checks/README.md` |
| CI | unit tests run only in the AWS deploy, on pushes to `main` or by hand (`.github/workflows/deploy-aws.yml:54`); `.github/workflows/atlas-sync.yml` only verifies the Atlas on pull requests | `.github/workflows/` |

## Invariants

- **MUST** aim for `python -m checks all` at zero fails on a Mythic log of every raid key after any change to fetching or to a rule; its exit code is the automated pass/fail (`backend/checks/verdict.py:70`). Today `all` exits 1 on every raid because of open findings against the site, so zero fails is the target, not the current state.
- **NEVER** let the unit tests reach WarcraftLogs or Supabase: they patch `get_access_token`, `get_report_fights`, `get_fights`, `get_report_deaths_bulk` and the `defensives` fetchers (`backend/test_api.py:288`), and swap `supabase_client.db` for a fake (`backend/test_api.py:83`), so they run without keys.

## Gotchas

- **No test runs on a pull request**: the unit suites run only when someone starts the AWS deploy workflow. A broken test is otherwise found only when someone runs it locally.
- **Frontend death counting has no test**: `frontend/src/deathCounting.js` decides what counts when you change "first X" on the Results page, including the fallback for results saved before slots existed. Only the backend half (`rank_pull_deaths`) is tested.
- **The WarcraftLogs retry path is untested**: `make_request_with_retry` (`backend/warcraftlogs.py:30`), with its 4xx-no-retry rule and `Retry-After` handling, has no test. Only the token cache is (`backend/test_api.py:225`).
- **Report-cache eviction is untested**: `evict_report_cache` (`backend/supabase_client.py:395`) and the five-minute back-off after an error have no test; `test_cache.py` covers only the retry of a reset connection (`backend/test_cache.py:60`).
- **Date windows are tested for one raid**: `test_season_two_default_and_custom_date_windows` covers `midnight-s2-all` only. The other seven windows in `RAID_DATE_WINDOWS` are not asserted.
- **Some tests read generated data**: `test_defensives.py` runs against the committed `defensive_catalog.py`, and `test_generated_file` expects Sever's text in `boss_spell_text.py` (`backend/test_boss_spell_text.py:34`). Rebuilding those modules can change what these tests see.
- **The checks only look at Mythic**: the package passes difficulty 5 everywhere (`backend/checks/common.py:97`). The raid key must be a key of `RAID_ENCOUNTERS`.
- **The checks' analysis never touches the shared report cache**: they run `/api/analyze` in process, and `import app` loads `backend/.env` with the real Supabase key, so for that run the shared cache reads as empty and writes go nowhere, and the in-memory caches are cleared before and after (`backend/checks/common.py:71`).
- **The end-to-end run needs the report's guild**: pass it in the target (`<code>:<raid>:<Guild>/<Server>/<REGION>`) when WarcraftLogs has none attached to the report.
- **The Analyze form test is pinned to today's raid list**: it expects exactly five raid cards (`frontend/src/AnalyzeConfig.test.js:28`), so adding a tier means updating it.

## Related

- [[backend]] — the code most tests exercise
- [[backend-death-counting]] — the slot and wipe rules `test_death_slots.py` pins down
- [[backend-defensive-analysis]] — what `test_defensives.py` and the checks verify
- [[backend-caching-and-limits]] — the caches and limiter `test_cache.py` and `test_api.py` cover
- [[frontend]] — where the two jest files live
- [[game-data]] — the generated modules the tests and checks read
- [[warcraftlogs]] — the API the checks call
- [[operations]] — when to run the checks during a new raid tier
