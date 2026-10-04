---
id: deployment
title: Deployment & Environments
domain: deployment
status: documented
summary:
  - "The backend runs on Render as gunicorn with gthread workers, configured by PORT, WEB_CONCURRENCY and GUNICORN_THREADS."
  - "The frontend is a static Create React App build; a _redirects.txt file sends every path to index.html for client-side routing."
  - "The browser picks the API by hostname: localhost talks to localhost:5000, everything else to deathwarcraftlogs-api.onrender.com, unless REACT_APP_API_URL is set at build time."
  - "Supabase migrations are SQL files run by hand in the Supabase dashboard; nothing applies them automatically."
  - "The only CI is a docs sync check; no workflow builds or tests the app."
tagline: How the Flask API and the React site are built, configured and pointed at each other.
anchors:
  gunicorn_bind: backend/gunicorn.conf.py:12
  gunicorn_workers: backend/gunicorn.conf.py:13
  gunicorn_threads: backend/gunicorn.conf.py:15
  gunicorn_timeout: backend/gunicorn.conf.py:18
  requirements: backend/requirements.txt:1
  dev_server: backend/app.py:745
  load_dotenv: backend/app.py:20
  allowed_origins: backend/app.py:64
  health: backend/app.py:735
  supabase_env: backend/supabase_client.py:27
  api_url: frontend/src/api.js:7
  wake_message: frontend/src/api.js:70
  build_script: frontend/package.json:21
  spa_rewrite: frontend/public/_redirects.txt:1
  migration_001: backend/migrations/001_shares_and_rls.sql:2
  migration_002: backend/migrations/002_report_cache.sql:2
  ci_atlas: .github/workflows/atlas-sync.yml:6
  mem_shares: backend/supabase_client.py:195
links:
  - backend
  - frontend
  - auth
  - data-model
  - security
  - feat-share
  - feat-saved
  - operations
  - game-data
  - testing
flows:
  - request-path
invariants:
  - "MUST: SUPABASE_SERVICE_ROLE_KEY be set on the production backend, or saves and shares are blocked by RLS."
  - "MUST: migrations 001 and 002 be run in the Supabase SQL editor before the features that use them are expected to persist."
  - "NEVER: commit backend/.env; it is gitignored and holds the backend's secrets."
  - "NEVER: rely on in-process state (rate limits, memory shares, caches) across workers or restarts."
content_hash: sha256:d3eb953cce1890e10bb94635fc6d398be3547598bf0b6a3d450fe4efed5c996c
---
# Deployment & Environments

## Summary

- Two deployables. The Flask API in `backend/` runs under gunicorn using `backend/gunicorn.conf.py`; the React site in `frontend/` is built with `react-scripts build` (`frontend/package.json:21`) into static files.
- The site finds the API through one constant, `API_URL` (`frontend/src/api.js:7`): `REACT_APP_API_URL` if set at build time, else `http://localhost:5000` on localhost, else `https://deathwarcraftlogs-api.onrender.com`.
- Supabase is shared infrastructure, not deployed from here. Its schema changes live as hand-run SQL in `backend/migrations/` (`backend/migrations/001_shares_and_rls.sql:2`).
- No pipeline builds, tests or deploys the app from this repo. The only workflow verifies the documentation (`.github/workflows/atlas-sync.yml:6`). The repo has no `render.yaml` or `Procfile`, so the Render start command and env vars live in Render's dashboard.

## Diagram

```diagram
lane repo Repository
node be lane=repo color=structural "backend/" "Flask + gunicorn conf"
node fe lane=repo color=structural "frontend/" "CRA source"
node mig lane=repo color=caution "migrations/" "hand-run SQL"
node ci lane=repo color=process "atlas-sync.yml" "docs check only"
lane prod Production
node render lane=prod color=safe "Render web service" "gunicorn gthread"
node static lane=prod color=safe "Static site" "build/ + rewrite"
node supa lane=prod color=structural "Supabase" "auth + tables"
edge be -> render color=process "deploy"
edge fe -> static color=process "npm run build"
edge mig -> supa color=caution "SQL editor"
edge static -> render color=process "API_URL"
edge render -> supa color=process "service key"
edge static -> supa color=process "anon key"
```

## How it works

```steps
- title: Install the backend | short: Backend deps | sub: requirements.txt
  body: backend/requirements.txt pins Flask 3.0.0, flask-cors 4.0.0, requests 2.31.0, gunicorn 21.2.0, brotli 1.1.0 and python-dotenv 1.0.0, and allows supabase from 2.0 up to but not including 2.5 (backend/requirements.txt:6). No Python version file is committed.
- title: Start gunicorn | short: gunicorn | sub: gthread, 1 worker x 16 threads
  body: gunicorn reads backend/gunicorn.conf.py when started in backend/ (backend/gunicorn.conf.py:2). It binds 0.0.0.0 on PORT (default 5000), runs WEB_CONCURRENCY workers (default 1) of class gthread with GUNICORN_THREADS threads (default 16), with timeout 120, graceful_timeout 30 and keepalive 5 (backend/gunicorn.conf.py:12-20). Threads let one long streaming analysis run without blocking other requests.
  gotcha: With gthread the 120 second timeout is a worker heartbeat, not a cap on a request (backend/gunicorn.conf.py:16), so an analysis can stream for longer.
- title: Load configuration | short: Env vars | sub: dotenv locally, host env in production
  body: app.py calls load_dotenv() before importing anything that reads env (backend/app.py:20), and supabase_client.py calls it again (backend/supabase_client.py:25). Locally that reads backend/.env; in production the variables come from the host. At startup the backend logs whether Supabase storage and the service role are configured (backend/supabase_client.py:40).
- title: Apply migrations | short: Migrations | sub: by hand, re-runnable
  body: Each file says to run it once in the Supabase dashboard SQL editor and that it is safe to re-run (backend/migrations/001_shares_and_rls.sql:2, backend/migrations/002_report_cache.sql:2). 001 creates shared_results and turns on RLS and credential policies; 002 creates report_cache. Both use create if not exists and drop policy if exists.
  gotcha: Missing tables fail soft. Without 001 shares fall back to process memory (backend/supabase_client.py:232); without 002 the shared report cache is skipped. The app looks healthy while not persisting.
- title: Build the frontend | short: Static build | sub: react-scripts build
  body: npm run build runs react-scripts build (frontend/package.json:21). REACT_APP_API_URL, if set, is baked into the bundle at this point (frontend/src/api.js:7). Everything in frontend/public, including art and _redirects.txt, is copied into build/. The Supabase URL and anon key are constants in the source (frontend/src/supabaseClient.js:3), not build variables.
- title: Route every path to the app | short: SPA rewrite | sub: /* to /index.html 200
  body: The app uses BrowserRouter (frontend/src/index.js:11) with paths like /analyze, /results and /saved (frontend/src/App.js:1548, :1566, :2205). frontend/public/_redirects.txt holds one rule, /* /index.html 200, so a direct visit or refresh on those paths serves the app instead of a 404.
- title: Point the site at the API | short: API base URL | sub: by hostname
  body: API_URL is the only place the backend address appears (frontend/src/api.js:3). The backend in turn must allow the site's origin in ALLOWED_ORIGINS, or leave it unset to allow any origin (backend/app.py:64).
```

## Standing it up

| Concern | This domain | Source |
|---|---|---|
| Backend runs on | gunicorn `gthread`, `WEB_CONCURRENCY` x `GUNICORN_THREADS` (1 x 16 by default) on Render | `backend/gunicorn.conf.py:13`, `:15`; host from `frontend/src/api.js:8` |
| Backend start command | not in the repo (no `render.yaml`, no `Procfile`) | Render dashboard |
| Backend dependencies | `backend/requirements.txt` | pip |
| Backend config | `PORT`, `WEB_CONCURRENCY`, `GUNICORN_THREADS`, `ALLOWED_ORIGINS`, `SUPABASE_URL` | host env; `backend/.env` locally |
| Backend secrets | `SUPABASE_KEY` (anon), `SUPABASE_SERVICE_ROLE_KEY` | host env; `backend/.env` locally (gitignored, `.gitignore:2`) |
| Health check | `GET /api/health` returns status and whether Supabase is configured | `backend/app.py:735` |
| Frontend build | `react-scripts build` to `frontend/build/` (gitignored) | `frontend/package.json:21`, `frontend/.gitignore:12` |
| Frontend config | `REACT_APP_API_URL` (optional, build time) | build env |
| Frontend public values | Supabase URL and anon key | constants in `frontend/src/supabaseClient.js:3` |
| Database schema | `backend/migrations/*.sql` | pasted into the Supabase SQL editor by hand |
| Generated data | `defensive_catalog.py`, `boss_spell_text.py`, `spell_icons.py` and others, committed | built offline by `backend/scripts/`, see [[game-data]] |
| CI | `atlas-sync.yml`: runs `verify-atlas.mjs` on PRs touching `docs/atlas/**` | `.github/workflows/atlas-sync.yml:25` |

## Environments

| Aspect | Local | Production |
|---|---|---|
| Frontend | `react-scripts start` (`frontend/package.json:20`) on localhost | static build of `frontend/` |
| API the site calls | `http://localhost:5000` (`frontend/src/api.js:8`) | `https://deathwarcraftlogs-api.onrender.com` (`frontend/src/api.js:8`) |
| Override | `REACT_APP_API_URL` | same, at build time |
| Backend server | `python app.py`: Flask dev server, threaded, debug off (`backend/app.py:745`), or gunicorn | gunicorn with `backend/gunicorn.conf.py` |
| Backend env | `backend/.env` via `load_dotenv()` | host environment variables |
| Supabase | same project: the frontend URL and anon key are hard-coded (`frontend/src/supabaseClient.js:3`) | same |
| CORS | `ALLOWED_ORIGINS` usually unset, so `*` | `ALLOWED_ORIGINS` if set, else `*` |
| Cold start | none | the site tells users the server "may be waking up" when a request cannot connect (`frontend/src/api.js:70`) |

## Invariants

- **MUST** `SUPABASE_SERVICE_ROLE_KEY` be set on the production backend. Without it the client falls back to the anon key (`backend/supabase_client.py:38`) and RLS blocks saves and shares; migration 001 says so in its header (`backend/migrations/001_shares_and_rls.sql:11`).
- **MUST** migrations 001 and 002 be run in the Supabase SQL editor before shares and the shared report cache are expected to persist (`backend/migrations/001_shares_and_rls.sql:2`, `backend/migrations/002_report_cache.sql:2`).
- **NEVER** commit `backend/.env`; it is gitignored (`.gitignore:2`) and holds the backend's Supabase keys.
- **NEVER** rely on in-process state across workers or restarts: rate limits (`backend/ratelimit.py:29`), memory shares (`backend/supabase_client.py:195`), the token cache (`backend/auth.py:25`) and the memory layer of the report caches all live in one process.

## Gotchas

- **More workers change behavior, not just capacity**: raising `WEB_CONCURRENCY` above 1 gives each worker its own rate-limit counters and memory caches. The config's docstring chooses threads over workers to keep that state shared (`backend/gunicorn.conf.py:6`).
- **The rewrite file is named `_redirects.txt`**: CRA copies it to `build/_redirects.txt` unchanged, and nothing in the repo renames it. Static hosts that read a rewrite file conventionally look for `_redirects` with no extension, so whether the rule takes effect depends on how the host is configured outside the repo. If deep links like `/results?share=...` 404 on refresh, check this first.
- **No build or test CI**: backend `unittest` suites (`backend/test_api.py:1`) and frontend Jest tests (`frontend/package.json:22`) only run when someone runs them; see [[testing]]. Nothing in the repo checks that the app builds or that tests pass before a merge.
- **Production API host is a fallback, not config**: a build without `REACT_APP_API_URL` served from any host other than localhost calls the Render URL (`frontend/src/api.js:8`), so any such deploy talks to the production API.
- **Migrations are not tracked**: there is no migrations table or runner, so which files have been applied is known only by looking in Supabase. Both files are written to be safe to re-run.
- **Two tables are not created by any migration**: `saved_analyses` and `api_credentials` already existed; migration 001 only turns on RLS for them (`backend/migrations/001_shares_and_rls.sql:24`). A fresh Supabase project needs them created by hand; see [[data-model]] for the columns the code uses.

## Glossary

- **gthread**: gunicorn's threaded worker class; each worker process serves many requests at once on a thread pool.
- **SPA rewrite**: a host rule that serves `index.html` for every path so the React router, not the server, decides what to show.
- **Migration**: a SQL file in `backend/migrations/` that changes the Supabase schema, applied by pasting it into the SQL editor.
- **Cold start**: the delay while a sleeping Render instance starts up on the first request.

## Related

- [[backend]] — the Flask app gunicorn serves
- [[frontend]] — the React app the static build ships
- [[auth]] — the Supabase keys both sides need
- [[data-model]] — the tables the migrations create or secure
- [[security]] — CORS, rate limits and how worker count affects them
- [[feat-share]] — falls back to memory shares if migration 001 is missing
- [[feat-saved]] — needs the service-role key in production
- [[operations]] — running and watching the deployed service
- [[game-data]] — the generated modules shipped with every deploy
- [[testing]] — the suites no CI runs
