---
id: feat-saved
title: Saved Reports
domain: feat-saved
status: documented
summary:
  - "A signed-in user can keep up to 5 analyses on their account, each for 7, 14 or 30 days, and reopen them from any device on the /saved page."
  - "Saving POSTs the loaded result and a credential-free config to /api/saved; the server stores it brotli-compressed in the saved_analyses table under the verified user id."
  - "Every /api/saved call requires a Supabase session; the server takes the user id from the verified token, never from the request."
  - "Expired saves are removed lazily, whenever the same user lists or saves; the server refuses a 6th save (409) and anything over 3 MB compressed (413)."
  - "Opening a save puts it back into app state and routes to /results, the same page a fresh analysis uses."
tagline: Keep up to five analyses on your account and reopen them later.
anchors:
  save_button: "frontend/src/App.js:1642"
  save_dialog: "frontend/src/SaveReportDialog.js:7"
  save_post: "frontend/src/SaveReportDialog.js:24"
  saved_route: "frontend/src/App.js:2237"
  saved_list: "frontend/src/SavedReports.js:10"
  open_saved: "frontend/src/SavedReports.js:35"
  load_into_state: "frontend/src/App.js:337"
  list_endpoint: "backend/app.py:779"
  create_endpoint: "backend/app.py:785"
  get_endpoint: "backend/app.py:803"
  delete_endpoint: "backend/app.py:811"
  delete_all_endpoint: "backend/app.py:819"
  status_map: "backend/app.py:772"
  save_limiter: "backend/app.py:54"
  limits: "backend/supabase_client.py:31"
  save_analysis: "backend/supabase_client.py:89"
  purge_expired: "backend/supabase_client.py:85"
  load_analysis: "backend/supabase_client.py:143"
  strip_secrets: "backend/supabase_client.py:61"
  require_user: "backend/auth.py:79"
links:
  - frontend
  - frontend-pages-and-routing
  - backend
  - backend-api-endpoints
  - backend-caching-and-limits
  - data-model
  - auth
  - security
  - feat-results
  - feat-share
  - feat-account
flows:
  - share-path
invariants:
  - "MUST: every /api/saved route run behind require_user and use g.user_id from the verified token (backend/app.py:780, backend/auth.py:88)."
  - "MUST: every saved_analyses read and delete filter on both id and user_id (backend/supabase_client.py:148, backend/supabase_client.py:176)."
  - "NEVER: store or return WarcraftLogs credentials in a save; the config is stripped in the browser and again on write and read (frontend/src/SaveReportDialog.js:28, backend/supabase_client.py:101, backend/supabase_client.py:163)."
  - "MUST: keep at most MAX_SAVED_PER_USER (5) saves per user and clamp retention to 1-30 days (backend/supabase_client.py:93, backend/supabase_client.py:97)."
content_hash: sha256:bf35fda59fd9c2fc13321a9c9a6c7e215b97fd1b82fe7db69bcfcc8079ad55e1
---
## Summary

- **What it is.** A per-account shelf of up to 5 analyses (`MAX_SAVED_PER_USER`, `backend/supabase_client.py:31`). Saving happens from the Results page; reopening happens on `/saved` (`frontend/src/App.js:2237`).
- **Who can use it.** Only signed-in users. The Save button renders only when `user` is set (`frontend/src/App.js:1642`), and every `/api/saved` route is wrapped in `require_user` (`backend/app.py:780`).
- **What is stored.** The full result object plus the analysis config without credentials, packed as `br64:` brotli + base64 (`backend/supabase_client.py:68`, `backend/supabase_client.py:101`).
- **How long.** 7, 14 or 30 days, chosen in the dialog (`frontend/src/SaveReportDialog.js:56`) and clamped server-side to 1-30 (`backend/supabase_client.py:93`).

## How it works

```steps
- title: Press Save on a result | short: Save | sub: signed-in only
  body: The Results header shows Save only for a signed-in user (frontend/src/App.js:1642). It opens SaveReportDialog, which needs both a user and loaded data (frontend/src/App.js:2313). The name defaults to "<guild> · <today>" (frontend/src/SaveReportDialog.js:8) and the keep-for select offers 7, 14 or 30 days, default 30 (frontend/src/SaveReportDialog.js:11).
- title: Send it | short: POST /api/saved | sub: name, data, config, retentionDays
  body: The dialog POSTs with the session token attached (auth true) and the config passed through stripSecrets, which drops clientId and clientSecret (frontend/src/SaveReportDialog.js:24, frontend/src/api.js:43). The route is rate limited to 30 saves per hour per client IP (backend/app.py:54, backend/app.py:787) and rejects a body that has no events object (backend/app.py:733, backend/app.py:791).
- title: Server checks and stores | short: save_analysis | sub: purge, count, size
  body: save_analysis clamps retention, deletes this user's expired rows, counts what is left, refuses a 6th save, packs the payload, refuses over 3 MB compressed, then inserts a row with a fresh UUID, the name and guild cut to 100 characters, size_bytes and expires_at (backend/supabase_client.py:89).
  gotcha: The count check and the insert are separate calls, so save_analysis recounts after inserting; if two saves at once went over the limit, the one that went over deletes its own row and answers limit (backend/supabase_client.py:118).
- title: See why it failed | short: Errors | sub: 409, 413, 429
  body: _storage_response maps code limit to 409, too_large to 413 and not_found to 404 (backend/app.py:772). On 409 the dialog adds a "Manage saved reports" link to /saved (frontend/src/SaveReportDialog.js:35, frontend/src/App.js:2319).
- title: Open the Saved page | short: /saved | sub: list, expiry, size
  body: SavedReports fetches GET /api/saved when a user is present (frontend/src/SavedReports.js:30). The server purges expired rows first, then returns id, name, guild, created_at, expires_at, retention_days and size_bytes, newest first, plus the limit (backend/supabase_client.py:129). Each card reads "Saved <date> · expires in Nd · <size>" (frontend/src/SavedReports.js:91). Signed out, the page shows a Sign in prompt instead (frontend/src/SavedReports.js:59).
- title: Reopen one | short: Open | sub: GET /api/saved/<id>
  body: openReport fetches the full row (frontend/src/SavedReports.js:35). The id must look like a UUID (backend/app.py:730). load_analysis selects by id and user_id, unpacks it, wraps rows from older versions that stored the bare analysis, and strips secrets from the config again (backend/supabase_client.py:143). handleLoadSavedReport merges that config into the form, sets data and navigates to /results (frontend/src/App.js:337).
- title: Delete one | short: Delete | sub: confirm, then DELETE
  body: The trash button asks window.confirm, then calls DELETE /api/saved/<id> and drops the card locally (frontend/src/SavedReports.js:47). The server deletes by id and user_id (backend/supabase_client.py:172).
```

## Diagram

```diagram
lane web Browser
lane api Flask API
lane db Supabase
node dlg lane=web color=process "SaveReportDialog" "name, keep for"
node page lane=web color=process "SavedReports" "/saved"
node res lane=web color=safe "Results" "/results"
node gate lane=api color=safe "require_user" "verified token"
node svc lane=api color=process "save_analysis" "purge, count, pack"
node load lane=api color=process "load_analysis" "id + user_id"
node tbl lane=db color=structural "saved_analyses" "br64 rows"
edge dlg -> gate "POST"
edge gate -> svc "user_id"
edge svc -> tbl "insert"
edge page -> gate "GET"
edge gate -> load "user_id"
edge load -> tbl "select"
edge load -> res "data, config"
```

## Context map

```context
depends-on: [[auth]] — require_user and the Supabase session token
depends-on: [[backend-api-endpoints]] — the five /api/saved routes
depends-on: [[backend-caching-and-limits]] — the 30-per-hour save limiter and the 25 MB body cap
depends-on: [[data-model]] — the saved_analyses table and its br64 payload
depends-on: [[security]] — row-level security and secret stripping
depends-on: [[frontend-pages-and-routing]] — the /saved route and handleLoadSavedReport
depends-on: [[frontend]] — apiFetch and stripSecrets in api.js
depends-on: [[backend]] — supabase_client storage helpers
depends-on: [[feat-results]] — the Save button and the page a save reopens into
provides: up to 5 analyses per account, kept 7, 14 or 30 days
provides: reopen a past analysis on any device without re-running it
relied-on-by: [[feat-account]] — account deletion removes every save
```

## Reference

| Item {kind} | Where | Meaning |
|---|---|---|
| `GET /api/saved` {route} | `backend/app.py:779` | list the caller's saves and the limit |
| `POST /api/saved` {route} | `backend/app.py:785` | create a save; 201 on success |
| `GET /api/saved/<id>` {route} | `backend/app.py:803` | load one save |
| `DELETE /api/saved/<id>` {route} | `backend/app.py:811` | delete one save |
| `DELETE /api/saved` {route} | `backend/app.py:819` | delete all the caller's saves; no frontend caller |
| `MAX_SAVED_PER_USER` {const} | `backend/supabase_client.py:31` | 5 |
| `MAX_SAVED_BYTES` {const} | `backend/supabase_client.py:32` | 3 MB, measured on the compressed blob |
| `save_limiter` {const} | `backend/app.py:54` | 30 calls per 3600 s per client IP |
| `SAVED_ID_RE` {const} | `backend/app.py:730` | 36 hex digits and dashes |
| `retention_days` {column} | `backend/supabase_client.py:112` | 1-30, default 30 |
| `expires_at` {column} | `backend/supabase_client.py:114` | now + retention_days |
| `analysis_data` {column} | `backend/supabase_client.py:111` | `br64:` packed `{data, config}` |
| `_storage_response` {code} | `backend/app.py:772` | limit 409, too_large 413, not_found 404, else 500 |
| `SaveReportDialog` {component} | `frontend/src/SaveReportDialog.js:7` | the save form |
| `SavedReports` {component} | `frontend/src/SavedReports.js:10` | the /saved list |

## Invariants

- **MUST** every `/api/saved` route run behind `require_user` and act on `g.user_id` from the verified token (`backend/app.py:780`, `backend/auth.py:88`). A test sends `?user_id=victim` and checks it is ignored (`backend/test_api.py:141`).
- **MUST** every `saved_analyses` read and delete filter on both `id` and `user_id` (`backend/supabase_client.py:148`, `backend/supabase_client.py:176`).
- **NEVER** store or return WarcraftLogs credentials in a save: the browser strips them (`frontend/src/SaveReportDialog.js:28`), the server strips them on write (`backend/supabase_client.py:101`) and again on read (`backend/supabase_client.py:163`).
- **MUST** keep at most 5 saves per user and clamp retention to 1-30 days (`backend/supabase_client.py:93`, `backend/supabase_client.py:97`).

## Gotchas

- **Big analyses are sent compressed**: on AWS, Lambda refuses request bodies over 6 MB, and a big guild's full-season result is larger. Share and Save gzip the body in the browser (`apiFetch(..., {compress: true})`, `frontend/src/api.js`) and the API inflates it with a 64 MB cap (`backend/bodies.py`); an oversized body answers 413. Browsers without `CompressionStream` send plain JSON.
- **Expiry is lazy but never visible.** Expired rows stay in the table until that user lists, saves or opens a save; each of those first deletes the user's expired rows (`backend/supabase_client.py:94`, `backend/supabase_client.py:133`, `backend/supabase_client.py:148`), so an expired save opened by id answers 404 (`backend/test_api.py`, `test_expired_saves_do_not_load`).
- **The limiter is per IP and per process.** It keys on the visitor's IP: on AWS the `X-Viewer-Ip` CloudFront writes, otherwise the socket address (`backend/ratelimit.py:18`), and lives in memory (`backend/ratelimit.py:36`).
- **Alt groups are not saved with the result.** Grouping made on the Results page lives in page state; a save carries `data` and the analysis config only (`frontend/src/SaveReportDialog.js:28`).
- **No schema migration creates `saved_analyses`.** The migrations only enable RLS on it (`backend/migrations/001_shares_and_rls.sql:24`); the table predates them.

## Related

- [[feat-results]] — where Save lives and where a save reopens
- [[feat-share]] — the anonymous, 72-hour alternative
- [[feat-account]] — deleting the account deletes the saves
- [[auth]] — how the session is verified
- [[backend-api-endpoints]] — the route table
- [[backend-caching-and-limits]] — rate limits and size caps
- [[data-model]] — the saved_analyses table
- [[security]] — RLS and credential stripping
- [[frontend-pages-and-routing]] — the /saved route
- [[frontend]] — the React app
- [[backend]] — the Flask API
