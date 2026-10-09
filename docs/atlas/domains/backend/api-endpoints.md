---
id: backend-api-endpoints
title: API Endpoints
domain: backend
status: documented
summary:
  - "Eleven Flask routes in backend/app.py; everything under /api/* is CORS-enabled for GET, POST, DELETE and OPTIONS."
  - "POST /api/analyze answers 200 with a text/event-stream body: progress events, then exactly one result or one error event."
  - "Share links are public and expire after 72 hours; saved analyses and account deletion need a Supabase bearer token."
  - "Rate-limited routes answer 429 with {success: false, error} before any work is done."
tagline: Every route, its auth, its limit, and the SSE protocol of /api/analyze.
anchors:
  analyze: backend/app.py:109
  analyze_config_read: backend/app.py:115
  sse_response: backend/app.py:707
  result_payload: backend/app.py:665
  death_event: backend/app.py:576
  share_create: backend/app.py:725
  share_read: backend/app.py:745
  share_id_re: backend/app.py:717
  saved_id_re: backend/app.py:718
  storage_response: backend/app.py:760
  require_user: backend/auth.py:79
  limit_decorator: backend/ratelimit.py:54
  frontend_sse_reader: frontend/src/App.js:754
links:
  - backend
  - backend-analysis-pipeline
  - backend-death-counting
  - backend-caching-and-limits
  - backend-defensive-analysis
  - auth
  - data-model
  - frontend
  - feat-analyze
  - feat-share
  - feat-saved
  - feat-account
invariants:
  - "MUST: an /api/analyze stream ends with exactly one result event or one error event; the client treats the first error as final."
  - "MUST: cheat-death detection runs only for a request with a valid bearer token, whatever enableCheatDeath says."
  - "NEVER: return stored credentials; shares and saves pass config through strip_secrets on the way in and out."
content_hash: sha256:ddda4a0ff4302bb02593ef9333b00aec04abc5835b098e012f55929d1bec0838
---
## Summary

- All routes live in `backend/app.py`. CORS covers `/api/*` with the origins from `ALLOWED_ORIGINS`, headers `Content-Type` and `Authorization`, and methods GET, POST, DELETE, OPTIONS (`backend/app.py:68`).
- Authentication is a Supabase access token in `Authorization: Bearer ...`. `require_user` answers 401 `{"success": false, "error": "Please sign in again."}` when it is missing or invalid, and stores the user id in `g.user_id` (`backend/auth.py:79`). See [[auth]].
- Rate-limited routes use the `limit` decorator, which answers 429 `{"success": false, "error": <message>}` and skips OPTIONS preflights (`backend/ratelimit.py:54`). See [[backend-caching-and-limits]].

## Reference

| Route {analysis} | Auth | Limit | Request | Success response | Errors |
|---|---|---|---|---|---|
| `POST /api/analyze` {analysis} | optional bearer | 60/h/IP | JSON config (below) | 200 `text/event-stream` | 400 `{"error": "Invalid request"}` if the body is not a JSON object (`backend/app.py:116`); 429; everything else as SSE `error` events |
| `POST /api/share` {sharing} | optional bearer (sets `created_by`) | 20/h/IP | `{data, config}`; `data` must have an `events` object (`backend/app.py:721`) | `{success, shareId, expiresAt}` | 400 "Nothing to share"; 413 for any storage error, including too large (`backend/app.py:738`) |
| `GET /api/shared/<share_id>` {sharing} | none | none | `share_id` matches `^[A-Za-z0-9_-]{6,32}$` (`backend/app.py:717`) | `{success, data, config, timestamp}` | 404 if malformed, missing or expired |
| `GET /api/saved` {saved} | required | none | none | `{success, analyses: [id, analysis_name, guild_name, created_at, expires_at, retention_days, size_bytes], limit: 5}` | 500 on storage failure |
| `POST /api/saved` {saved} | required | 30/h/IP | `{name, data, config, retentionDays}`; retention clamped to 1-30 days (`backend/supabase_client.py:93`) | 201 `{success, id, size_bytes}` | 400 "Nothing to save"; 409 at the 5-save limit; 413 too large |
| `GET /api/saved/<id>` {saved} | required | none | `id` is a 36-char UUID (`backend/app.py:718`) | `{success, analysis_name, guild_name, data, config, created_at, expires_at}` | 404 if malformed or not the user's |
| `DELETE /api/saved/<id>` {saved} | required | none | UUID | `{success: true}` | 404 if malformed |
| `DELETE /api/saved` {saved} | required | none | none | `{success: true}` | 500 on storage failure |
| `DELETE /api/account` {account} | required | none | none | `{success: true}`; the token is dropped from the verify cache (`backend/app.py:823`) | 500 if deletion is not configured or partly failed |
| `GET /api/health` {status} | none | none | none | `{status: "healthy", supabase: <bool>}` | none |
| `GET /` {status} | none | none | none | `{service: "Floor Pov API", status: "running"}` | none |

Storage routes share one mapper, `_storage_response` (`backend/app.py:760`): a result without `error` passes through; otherwise the `code` picks the status (`limit` 409, `too_large` 413, `not_found` 404, anything else 500) and the body is `{"success": false, "error", "code"?}`.

#### The analysis request body

| Field {config} | Meaning | Handling |
|---|---|---|
| `clientId`, `clientSecret` {config} | The caller's WarcraftLogs API client | required (`backend/app.py:148`) |
| `guildName`, `server`, `region` {config} | Which guild | required |
| `selectedRaid` {config} | Key into `RAID_ENCOUNTERS` / `RAID_DATE_WINDOWS` | see [[backend-analysis-pipeline]] |
| `difficulty` {config} | 3 Normal, 4 Heroic, 5 Mythic (`backend/app.py:282`) | compared to each fight's `difficulty` |
| `fightZone` {config} | WCL zone id, used only when the raid key is unknown | fallback filter |
| `maxCutoff` {config} | Deaths per pull that count | default 5, clamped to 1-10 (`backend/app.py:134`) |
| `startDate`, `endDate` {config} | `YYYY-MM-DD`, may only narrow the tier window | empty string means none |
| `authorFilters` {config} | Report owner names to keep | optional list |
| `characterGroups` {config} | `{main: [alts]}` merging alts into one player | optional |
| `enableCheatDeath` {config} | Detect cheat deaths | honored only when signed in (`backend/app.py:143`) |
| `rosterOnly` {config} | Count only guild-roster players | default true; only an explicit `false` turns it off (`backend/app.py:145`) |

## How it works

#### The /api/analyze SSE protocol

The route returns `Response(generate(), mimetype='text/event-stream')` with `Cache-Control: no-cache` and `X-Accel-Buffering: no` so proxies do not buffer the stream (`backend/app.py:707`). Each event is a single `data: <json>` line followed by a blank line. There are no `event:` names or ids; the JSON keys say what the event is. The frontend splits on blank lines and dispatches on `error`, then `message`, then `result` (`frontend/src/App.js:754`).

| Event {sse} | Shape | When |
|---|---|---|
| progress {sse} | `{"stage": <stage>, "message": <text>}` | many times; only for display |
| error {sse} | `{"error": <text>}` | at most once, then the stream ends (`backend/app.py:705`) |
| result {sse} | `{"result": <analysis>}` | once, last (`backend/app.py:697`) |

The stages, in order: `auth` (signing in, or the "needs a signed-in account" notice for cheat deaths, `backend/app.py:153`), `roster`, `reports`, `fights`, `dedup`, `deaths`, `processing`, `complete`. One exception: the "Collected N total fights" `fights` line comes after the first `dedup` line, since deduplication runs while the kept reports are read in full (`backend/app.py:264`, `backend/app.py:279`). Warnings about unreadable reports or missing defensive detail arrive as ordinary `deaths` progress events (`backend/app.py:488`, `backend/app.py:494`), not as errors.

Errors that end the stream early: missing required fields, WarcraftLogs authentication failure, no reports after filtering, no fights at the chosen difficulty, or any unexpected exception (`backend/app.py:149`, `backend/app.py:160`, `backend/app.py:200`, `backend/app.py:284`, `backend/app.py:701`).

#### The result object

Built at `backend/app.py:665`:

| Key {result} | Contents |
|---|---|
| `meta` {result} | `guild_name`, `maxCutoff`, `authorFilters`, `startDate`, `endDate`, `zone`, `difficulty`, `generatedAt`, `characterGroups`, `reportCount`, `cheatDeathEnabled`, `rosterOnly`, `failedReports` |
| `events` {result} | `{mainCharacter: [deathEvent]}`; every guild member death and cheat death, counted or not |
| `pullParticipation` {result} | `{mainCharacter: ["<reportId>_<fightId>", ...]}` |
| `bossParticipation` {result} | `{bossName: {mainCharacter: [pullKey]}}` |
| `pullCutoffTimestamps` {result} | `{pullKey: {cutoff: ms from pull start}}`; see [[backend-death-counting]] |
| `icons` {result} | defensive and consumable icon names, by ability name |
| `abilityIcons` {result} | killing-blow icon, by spell id (`backend/app.py:688`) |
| `abilityInfo` {result} | what each defensive shown does, by name |
| `abilityText` {result} | in-game text of each killing blow, by spell id; `Melee` and `Falling` use fixed text (`backend/app.py:103`) |

A death event (`backend/app.py:576`) carries `player` (the main character), `originalCharacter`, `boss`, `bossId`, `phase` (always 1 today), `reportId`, `fightId`, `isKill`, `pullNo` (pull number for that boss, oldest first), `absTs`, `timestamp` (ms from pull start), `abilityName`, `abilityId`, `isCheatDeath`, `slot`, `inWipe`, `class`, `spec`, and, only for a death that can count, `defensives` ([[backend-defensive-analysis]]).

## Context map

```context
depends-on: [[backend-analysis-pipeline]] — produces everything the analyze stream sends
depends-on: [[auth]] — verify_token and require_user decide who is signed in
depends-on: [[data-model]] — shared_results and saved_analyses back the storage routes
depends-on: [[backend-caching-and-limits]] — the limit decorator and per-IP windows
provides: the HTTP and SSE contract the React site calls
relied-on-by: [[frontend]] — App.js reads the stream; api.js calls the storage routes
relied-on-by: [[feat-analyze]] — the Analyze button
relied-on-by: [[feat-share]] — share links
relied-on-by: [[feat-saved]] — saved analyses
relied-on-by: [[feat-account]] — account deletion
```

## Invariants

- **MUST** end an `/api/analyze` stream with exactly one `result` event or one `error` event; the client throws on the first `error` (`frontend/src/App.js:757`).
- **MUST** gate cheat-death detection on a valid bearer token, whatever `enableCheatDeath` says, since a shared config or a direct call can set the flag (`backend/app.py:118`).
- **NEVER** return stored credentials: shares and saves pass `config` through `strip_secrets` when stored and when read (`backend/supabase_client.py:223`, `backend/supabase_client.py:259`).

## Gotchas

- **A 200 does not mean success**: `/api/analyze` commits to 200 before any work. Read the stream for an `error` event.
- **Share errors use the shared status mapper**: `share_results` answers a storage error through `_storage_response` (`backend/app.py:738`), so too large is 413 and anything else 500.
- **Shares can live only in memory**: if the Supabase insert fails, the share is kept in process memory (`backend/supabase_client.py:241`) and the route passes `ephemeral: true` to the browser (`backend/app.py:741`), which warns that the link stops working when the server restarts (`frontend/src/App.js:1467`, `frontend/src/shareNote.js`).
- **Cutoff keys become strings**: `pullCutoffTimestamps` uses integer keys in Python, which JSON turns into strings.

## Related

- [[backend]] — the service landing page
- [[backend-analysis-pipeline]] — how the analyze stream is produced
- [[backend-death-counting]] — `slot`, `inWipe` and `pullCutoffTimestamps`
- [[backend-caching-and-limits]] — the 429 limits on these routes
- [[backend-defensive-analysis]] — the `defensives` block on a death event
- [[auth]] — bearer tokens
- [[data-model]] — the tables behind shares and saves
- [[frontend]] — the caller
- [[feat-analyze]] — the analyze flow from the user's side
- [[feat-share]] — share links from the user's side
- [[feat-saved]] — saved analyses from the user's side
- [[feat-account]] — account deletion from the user's side
