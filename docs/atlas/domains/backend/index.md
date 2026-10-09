---
id: backend
title: Backend API
domain: backend
status: documented
summary:
  - "A single Flask app (backend/app.py) that turns a guild's WarcraftLogs reports into a per-player death breakdown, streamed back as Server-Sent Events."
  - "Eleven routes: one long-running analysis stream, share links, saved analyses, account deletion, and health checks."
  - "Finished reports are cached twice: an in-process LRU and a shared Supabase report_cache table, so a report is downloaded from WarcraftLogs about once."
  - "Writes and analyses are rate-limited per client IP in memory; signed-in routes check a Supabase bearer token."
  - "Runs under gunicorn with threaded workers (gthread) so one streaming analysis never blocks other requests."
tagline: The Flask service that fetches, counts and explains raid deaths.
anchors:
  flask_app: backend/app.py:60
  cors: backend/app.py:67
  analyze_route: backend/app.py:109
  limiters: backend/app.py:52
  gunicorn_worker_class: backend/gunicorn.conf.py:14
  gunicorn_threads: backend/gunicorn.conf.py:15
  supabase_env: backend/supabase_client.py:27
  auth_env: backend/auth.py:20
  dev_server: backend/app.py:807
  frontend_api_url: frontend/src/api.js:9
links:
  - backend-api-endpoints
  - backend-analysis-pipeline
  - backend-death-counting
  - backend-caching-and-limits
  - backend-defensive-analysis
  - backend-death-descriptions
  - warcraftlogs
  - data-model
  - auth
  - frontend
  - feat-analyze
invariants:
  - "MUST: run under a threaded worker (gthread); a sync worker lets one analysis stream block every other request."
  - "MUST: keep WEB_CONCURRENCY at 1 unless shared state moves out of process; caches and rate limits live in process memory."
  - "NEVER: hard-code a WarcraftLogs API key on the server; each analysis brings the caller's own clientId and clientSecret."
content_hash: sha256:72cf361263cd2761a9408655d4c8fc601bb75bcd25befd6cfbb3b10e44de4aa7
---
## Summary

- The **backend** is one Flask application, `backend/app.py:60`. Its main job is `POST /api/analyze` (`backend/app.py:109`): it signs in to WarcraftLogs with the caller's own API client, reads the guild's reports for one raid tier, counts each pull's early deaths, attaches defensive analysis, and streams progress plus the final result as Server-Sent Events.
- The rest is small storage plumbing on top of Supabase: 72-hour share links, up to five saved analyses per signed-in user, and account deletion.
- It deliberately keeps no WarcraftLogs credentials of its own. Every analysis request carries `clientId` and `clientSecret` (`backend/app.py:125`), so WarcraftLogs' points budget is the caller's key, not a shared one.
- State that must be fast lives in process memory (LRU caches, rate-limit windows, token cache). State that must survive restarts lives in Supabase.

## Diagram

How the modules depend on each other. `app.py` is the only entry point; everything else is a library it imports.

```diagram
lane entry Entry
node gunicorn lane=entry color=structural "gunicorn gthread" "gunicorn.conf.py"
node app lane=entry color=process "app.py" "Flask routes + SSE"
lane core Analysis core
node analysis lane=core color=process "analysis.py" "raids, deaths, slots"
node features lane=core color=process "features.py" "cheat-death IDs"
node defensives lane=core color=process "defensives.py" "per-death verdicts"
node spelltext lane=core color=process "boss_spell_text.py" "tooltip text"
lane infra Shared plumbing
node cache lane=infra color=structural "cache.py" "LRU + shared cache"
node ratelimit lane=infra color=structural "ratelimit.py" "per-IP windows"
node auth lane=infra color=structural "auth.py" "bearer tokens"
node supa lane=infra color=structural "supabase_client.py" "storage + cache rows"
lane ext External
node wcl lane=ext color=caution "WarcraftLogs API" "warcraftlogs.py"
node supabase lane=ext color=structural "Supabase" "Postgres + Auth"
edge gunicorn -> app color=structural "serves"
edge app -> analysis "pipeline"
edge app -> defensives "analyze_death"
edge app -> spelltext "abilityText"
edge analysis -> features "cheat IDs"
edge app -> cache "report data"
edge app -> ratelimit "limit()"
edge app -> auth "verify_token"
edge cache -> supa color=structural "report_cache"
edge analysis -> wcl color=caution "GraphQL"
edge supa -> supabase color=structural
edge auth -> supabase color=structural "/auth/v1/user"
```

## Reference

Every route, at a glance. Full request and response shapes are on [[backend-api-endpoints]].

| Route {analysis} | Auth | Rate limit | Purpose |
|---|---|---|---|
| `POST /api/analyze` {analysis} | optional (unlocks cheat deaths) | 60 / hour / IP | Stream an analysis as SSE (`backend/app.py:109`) |
| `POST /api/share` {sharing} | optional (links share to account) | 20 / hour / IP | Create a 72-hour share link (`backend/app.py:691`) |
| `GET /api/shared/<share_id>` {sharing} | none | none | Read a share link (`backend/app.py:711`) |
| `GET /api/saved` {saved} | required | none | List the user's saved analyses (`backend/app.py:733`) |
| `POST /api/saved` {saved} | required | 30 / hour / IP | Save an analysis (`backend/app.py:739`) |
| `GET /api/saved/<id>` {saved} | required | none | Load one saved analysis (`backend/app.py:757`) |
| `DELETE /api/saved/<id>` {saved} | required | none | Delete one (`backend/app.py:765`) |
| `DELETE /api/saved` {saved} | required | none | Delete all of the user's saves (`backend/app.py:773`) |
| `DELETE /api/account` {account} | required | none | Delete the user's data and auth account (`backend/app.py:783`) |
| `GET /api/health` {status} | none | none | Liveness plus whether Supabase is configured (`backend/app.py:797`) |
| `GET /` {status} | none | none | Service banner (`backend/app.py:802`) |

The module map, for finding code:

| Module {core} | What it holds |
|---|---|
| `backend/app.py` {core} | Flask app, CORS, all routes, the analysis generator |
| `backend/analysis.py` {core} | Raid tables, date windows, fight filtering, duplicate pulls, bulk death fetch, death slots |
| `backend/features.py` {core} | Spell IDs that mark a cheat death (`backend/features.py:14`, `backend/features.py:26`) |
| `backend/cache.py` {plumbing} | `LRUCache` and `SharedReportCache` and the five report caches |
| `backend/ratelimit.py` {plumbing} | `RateLimiter`, the `limit` decorator, `client_ip` |
| `backend/gunicorn.conf.py` {plumbing} | Production server settings |
| `backend/defensives.py` {analysis} | Defensive analysis per death; see [[backend-defensive-analysis]] and [[backend-death-descriptions]] |

## Standing it up

`backend/gunicorn.conf.py` is read automatically when gunicorn starts in `backend/` (its own docstring, `backend/gunicorn.conf.py:1`). It uses the `gthread` worker class (`backend/gunicorn.conf.py:14`) because an analysis is a long streaming request: with gunicorn's default sync worker, one running analysis would block page data, shares and saves until it finished. With `gthread`, `timeout = 120` (`backend/gunicorn.conf.py:18`) is a worker heartbeat, not a per-request cap, so long analyses keep streaming.

| Concern | This domain | Source |
|---|---|---|
| Runs on | gunicorn, `gthread` worker, `threads` default 16, `workers` default 1 (`backend/gunicorn.conf.py:13`) | `backend/gunicorn.conf.py` |
| Bind | `0.0.0.0:$PORT`, default 5000 (`backend/gunicorn.conf.py:12`) | host env |
| Timeouts | `timeout` 120 s, `graceful_timeout` 30 s, `keepalive` 5 s (`backend/gunicorn.conf.py:18`) | `backend/gunicorn.conf.py` |
| Depends on | WarcraftLogs v2 GraphQL API ([[warcraftlogs]]); Supabase Postgres and Auth ([[data-model]], [[auth]]) | network |
| Config | `PORT`, `WEB_CONCURRENCY`, `GUNICORN_THREADS`, `ALLOWED_ORIGINS` (comma list, default `*`, `backend/app.py:67`) | host env; `.env` via `python-dotenv` (`backend/app.py:20`) |
| Secrets | `SUPABASE_URL`, `SUPABASE_KEY`, `SUPABASE_SERVICE_ROLE_KEY` (`backend/supabase_client.py:27`); `auth.py` reads the first two (`backend/auth.py:20`) | host env; local `backend/.env` (gitignored) |
| WarcraftLogs keys | none on the server; sent per request as `clientId` / `clientSecret` | the caller |
| Request size | bodies over 25 MB are rejected (`backend/app.py:62`) | code |
| Dependencies | Flask 3.0, flask-cors, requests, gunicorn 21.2, brotli, supabase, python-dotenv | `backend/requirements.txt` |

In production the API runs on AWS Lambda: `backend/run.sh` starts gunicorn, and the env values are set on the Lambda function (see [[deployment]]).

## Environments

| Aspect | Local | Production |
|---|---|---|
| Server | `python app.py`: Flask's threaded dev server on `PORT` or 5000 (`backend/app.py:807`) | gunicorn with `backend/gunicorn.conf.py` on AWS Lambda, started by `backend/run.sh` |
| URL the frontend uses | `http://localhost:5000` when the site runs on localhost (`frontend/src/api.js:10`) | `/api` on the site's own host (CloudFront sends it to Lambda) (`frontend/src/api.js:10`), unless `REACT_APP_API_URL` overrides it at build time (`frontend/src/api.js:9`) |
| Env source | `backend/.env` loaded by `load_dotenv()` | Lambda environment variables |
| Supabase | optional: without it, saves fail, shares fall back to process memory, the shared report cache is skipped | configured; service-role key preferred (`backend/supabase_client.py:38`) |
| CORS | `ALLOWED_ORIGINS` unset means any origin | same mechanism; set to the site origins if restricted |

## Invariants

- **MUST** run under a threaded worker (`gthread`); a sync worker lets one analysis stream block every other request (`backend/gunicorn.conf.py:14`).
- **MUST** keep `WEB_CONCURRENCY` at 1 unless shared state moves out of process; the report LRU caches, rate-limit windows and token cache are per process, so more processes multiply the limits and split the caches.
- **NEVER** hard-code a WarcraftLogs API key on the server; each analysis brings the caller's own `clientId` and `clientSecret` (`backend/app.py:125`).

## Gotchas

- **The analysis body is read before streaming starts**: `request.get_json` and the sign-in check run before the generator (`backend/app.py:115`, `backend/app.py:120`), because the generator runs after Flask's request context is gone.
- **Errors after the stream starts are not HTTP errors**: once `/api/analyze` returns 200, a failure arrives as a `data: {"error": ...}` event. Only a bad JSON body (400) and the rate limit (429) are real HTTP errors.
- **Cold starts**: a schedule keeps one Lambda copy warm, but AWS can recycle it. The frontend pings `/api/health` on load (`frontend/src/App.js:263`), which, per the comment at `frontend/src/App.js:259`, starts a cold copy while the user is still filling in the form.

## Related

- [[backend-api-endpoints]] — every route with its request, response and SSE protocol
- [[backend-analysis-pipeline]] — what `/api/analyze` does, step by step
- [[backend-death-counting]] — slots, wipes and the "first X deaths" rule
- [[backend-caching-and-limits]] — report caches and rate limits
- [[backend-defensive-analysis]] — whether a defensive would have saved the player
- [[backend-death-descriptions]] — one-shot, burst, rot and set-up labels
- [[warcraftlogs]] — the GraphQL client every analysis uses
- [[data-model]] — the Supabase tables behind shares, saves and the report cache
- [[auth]] — Supabase bearer tokens and `require_user`
- [[frontend]] — the React site that calls this API
- [[feat-analyze]] — the user-facing Analyze flow end to end
