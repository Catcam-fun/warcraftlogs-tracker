---
id: hub
title: Floor Pov Atlas
status: documented
tagline: How a raid officer's request becomes a per-player death breakdown, and where every part of that lives.
summary:
  - "Floor Pov reads a guild's WarcraftLogs reports and counts who died first on each boss pull, with a per-death analysis of what killed them and which defensive could have saved them."
  - "The React site streams one analysis request to a Flask API; the API calls WarcraftLogs with the officer's own API credentials and streams progress back."
  - "Finished WarcraftLogs reports are cached in memory and in Supabase, so each one is downloaded once."
  - "Supabase also holds accounts, saved analyses and share links."
  - "Game data (defensive spells, boss abilities, armor) is pre-built into Python modules by scripts, not fetched at request time."
anchors:
  analyze_route: backend/app.py:109
  analyze_stream_client: frontend/src/App.js:723
  api_base_url: frontend/src/api.js:8
  wcl_token: backend/app.py:158
  shared_report_cache: backend/cache.py:42
  deaths_fetch: backend/app.py:376
  defensive_analysis: backend/app.py:592
  final_result: backend/app.py:663
links: [overview, frontend, backend, warcraftlogs, data-model, auth, game-data, feat-analyze, feat-results]
flows: [request-path, share-path, data-build-path]
content_hash: sha256:97843299588fc7f005c4da9769dbba97029c25b33d06cd37be23b6cc4d0435f3
---
## Summary

Floor Pov is a death-analysis site for World of Warcraft raid guilds. You give it a guild, a raid and a date range. It reads the guild's WarcraftLogs reports, finds every boss pull, and counts the first deaths of each pull per player. Each counted death also gets an analysis: what wore the player down, what landed the killing blow, and whether a defensive they had available would have kept them alive.

Start with [[overview]] for the vocabulary (pull, slot, wipe, cheat death), then follow the request path below. The domain cards underneath take you to each part.

## Diagram

One analysis, end to end. The browser opens a single streaming request (`frontend/src/App.js:723`). The Flask route (`backend/app.py:109`) exchanges the officer's WarcraftLogs client ID and secret for a token (`backend/app.py:158`). It reads the guild's reports and each report's short fight list, drops duplicate pulls, and reads in full only the reports it keeps pulls from, checking the report cache first (`backend/app.py:216`, `backend/app.py:226`, `backend/cache.py:42`). Then, per report, it reads talent loadouts and deaths (`backend/app.py:376`), analyzes each counted death against the pre-built game data (`backend/app.py:592`), and streams progress messages followed by one final result (`backend/app.py:663`).

```diagram
lane client Browser
node user lane=client color=process "Raid officer" "Analyze form"
node site lane=client color=process "React site" "App.js · api.js"
lane api Flask API on Render
node route lane=api color=process "POST /api/analyze" "rate limited · SSE"
node pipeline lane=api color=safe "Analysis pipeline" "pulls · slots · wipes"
node defs lane=api color=safe "Defensive analysis" "per counted death"
lane ext Data sources
node wcl lane=ext color=structural "WarcraftLogs API" "OAuth · GraphQL v2"
node cache lane=ext color=structural "Report cache" "memory + Supabase"
node catalog lane=ext color=structural "Game data modules" "built by scripts"
node supa lane=ext color=structural "Supabase" "auth · saves · shares"
edge user -> site "submit"
edge site -> route "stream request"
edge route -> wcl "token + reports"
edge route -> cache "finished reports"
edge route -> pipeline "fights, deaths"
edge pipeline -> defs color=safe "counted deaths"
edge defs -> catalog color=structural "spell data"
edge defs -> site color=safe "progress + result"
edge site -> supa color=caution "save / share"
band structural "Substrate · Render + Supabase + static site"
```

## How it works

```steps
- title: The officer fills in the Analyze form | short: Analyze form | sub: guild, raid, deaths tracked
  body: The Analyze page collects the guild, server, region, raid, difficulty, date range and how many deaths per pull to count. It also takes the officer's own WarcraftLogs client ID and secret, which stay in the browser except for the analyze call itself (frontend/src/api.js:12). See [[feat-analyze]].
- title: One streaming request | short: Stream opens | sub: POST /api/analyze
  body: The site POSTs the form to /api/analyze and reads the response as a stream of server-sent events (frontend/src/App.js:723, frontend/src/App.js:736). The route is rate limited per network (backend/app.py:110).
- title: Reports and fights | short: Reports | sub: WarcraftLogs + cache
  body: The API gets a WarcraftLogs token, optionally the guild roster, then the guild's reports in the raid's date window. It reads every report's short fight list, removes duplicate pulls, and reads players and abilities only for the reports it keeps pulls from. Finished reports come from the shared cache instead of WarcraftLogs (backend/app.py:216, backend/app.py:226). See [[warcraftlogs]] and [[backend-caching-and-limits]].
- title: Deaths and slots | short: Deaths | sub: first X per pull
  body: Deaths are fetched per report, after its talent loadouts, and each death gets a slot (which death of the pull it was) and a wipe flag. A report with no death that can count stops there; the others also get their defensive and hit data. See [[backend-analysis-pipeline]] and [[backend-death-counting]].
- title: Per-death analysis | short: Analysis | sub: what killed them
  body: Each counted death is replayed against the pre-built defensive catalog and boss data to describe the death and test which defensives would have saved it (backend/app.py:592). See [[backend-defensive-analysis]] and [[game-data]].
- title: Result, then save or share | short: Result | sub: Results page
  body: The final event carries the whole result (backend/app.py:663). The Results page renders it; a signed-in officer can save it or create a share link, both stored in Supabase. See [[feat-results]], [[feat-saved]] and [[feat-share]].
```

## Environments

| Aspect | Local | Production |
|---|---|---|
| Frontend | `npm start` on localhost | static build of `frontend/` |
| API base URL | `http://localhost:5000` when the page is on localhost | `https://deathwarcraftlogs-api.onrender.com`, unless `REACT_APP_API_URL` is set at build time (`frontend/src/api.js:8`) |
| Backend | Flask on port 5000 | gunicorn `gthread` on Render (`backend/gunicorn.conf.py`) |
| Storage | Supabase if configured, otherwise in-memory fallbacks | Supabase |

See [[deployment]] for detail.

## Related

- [[overview]] — the vocabulary and the supported raids
- [[feat-analyze]] — the request path as the officer experiences it
- [[backend]] — the Flask service that runs the analysis
- [[warcraftlogs]] — the external API every analysis depends on
- [[data-model]] — what Supabase stores
- [[game-data]] — the pre-built spell and boss data
