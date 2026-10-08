---
id: feat-share
title: Share Links
domain: feat-share
status: documented
summary:
  - "Share on the Results page turns the loaded analysis into a link of the form /results?share=<id> that anyone can open, signed in or not."
  - "POST /api/share packs the result and a credential-free config, stores it in the shared_results table for 72 hours, and returns a random 12-character id."
  - "Opening the link calls GET /api/shared/<id>; the browser drops the result into app state and shows it on /results without re-running anything."
  - "If the Supabase insert fails, the share is kept in the API process's memory instead, and it disappears on restart."
  - "Shares are rate limited to 20 per hour per client IP and capped at 2 MB compressed."
tagline: Send one analysis to anyone with a link that lasts 72 hours.
anchors:
  share_button: "frontend/src/App.js:1647"
  handle_share: "frontend/src/App.js:624"
  share_link: "frontend/src/App.js:641"
  share_modal: "frontend/src/App.js:1434"
  share_param_effect: "frontend/src/App.js:349"
  load_shared: "frontend/src/App.js:312"
  idb_restore_skip: "frontend/src/App.js:532"
  share_endpoint: "backend/app.py:698"
  shared_endpoint: "backend/app.py:718"
  share_id_re: "backend/app.py:690"
  share_limiter: "backend/app.py:52"
  share_limits: "backend/supabase_client.py:33"
  store_share: "backend/supabase_client.py:222"
  get_share: "backend/supabase_client.py:245"
  mem_fallback: "backend/supabase_client.py:202"
  shares_table: "backend/migrations/001_shares_and_rls.sql:13"
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
  - feat-saved
  - feat-account
flows:
  - share-path
invariants:
  - "NEVER: put WarcraftLogs credentials in a share; they are stripped in the browser, on write and on read (frontend/src/App.js:635, backend/supabase_client.py:223, backend/supabase_client.py:259)."
  - "NEVER: let a shared config overwrite the viewer's own credentials (frontend/src/App.js:325)."
  - "MUST: serve a share only before its expires_at; Supabase rows are filtered on expires_at and memory entries on their own deadline (backend/supabase_client.py:250, backend/supabase_client.py:217)."
  - "MUST: reject share ids outside [A-Za-z0-9_-]{6,32} before any lookup (backend/app.py:720)."
  - "MUST: try each ?share= id once per page; a failed load must not loop (frontend/src/App.js:351)."
content_hash: sha256:6aececd7cc1101827839f6a0e67af61820ee4f605b0b987ff7634863593c80b3
---
## Summary

- **What it is.** A short, unguessable link to one analysis result. The id is `secrets.token_urlsafe(9)`, 12 URL-safe characters (`backend/app.py:708`), and the link is `<origin>/results?share=<id>` (`frontend/src/App.js:641`).
- **Who can use it.** Anyone. Creating a share needs no account (`frontend/src/App.js:632`); if a session is present the server records its user id as `created_by` so account deletion can remove it (`backend/app.py:707`).
- **How long.** 72 hours (`SHARE_TTL_HOURS`, `backend/supabase_client.py:34`).
- **What it carries.** The result object and the analysis config with credentials removed, packed `br64:` (`backend/supabase_client.py:223`).

## How it works

```steps
- title: Press Share | short: Share | sub: Results header
  body: The Share button on /results calls handleShare (frontend/src/App.js:1647). It POSTs { data, config } to /api/share with config passed through stripSecrets; a signed-in user's token is attached as optional auth (frontend/src/App.js:630).
- title: Server stores it | short: POST /api/share | sub: check, pack, insert
  body: The route is limited to 20 per hour per client IP (backend/app.py:52, backend/app.py:699) and rejects a body without an events object (backend/app.py:704). store_share strips secrets, packs, refuses over 2 MB compressed, deletes every expired share in the table, then inserts id, payload, size_bytes, created_by and expires_at (backend/supabase_client.py:222). The response carries shareId and expiresAt (backend/app.py:714).
  gotcha: A store error is answered through _storage_response (backend/app.py:711): too_large is 413, anything else 500.
- title: Fallback to memory | short: Memory fallback | sub: table missing or insert fails
  body: If the insert throws (for example, the table was never created), the blob goes into the _mem_shares dict with the same 72-hour deadline, and the call still succeeds with ephemeral true (backend/supabase_client.py:241). The route passes ephemeral to the browser (backend/app.py:714), and the share dialog warns that this link stops working when the server restarts or sleeps (frontend/src/App.js:1467, frontend/src/shareNote.js).
  gotcha: Memory shares vanish on restart and are only visible to the process that stored them.
- title: Copy the link | short: Share modal | sub: copy to clipboard
  body: The modal shows the link in a read-only field with a Copy button (frontend/src/App.js:1434, frontend/src/App.js:651). It does not show the expiry.
- title: Open the link | short: ?share= | sub: once per id
  body: An effect on location.search reads the share param and calls loadSharedResults once per id, tracked by attemptedShareRef (frontend/src/App.js:349). The mount-time IndexedDB restore is skipped while a share param is present (frontend/src/App.js:532).
- title: Server returns it | short: GET /api/shared/<id> | sub: memory, then Supabase
  body: The id must match SHARE_ID_RE or the route answers 404 (backend/app.py:720). get_share checks memory first, then selects the row only if expires_at is still in the future, unpacks it and strips secrets from the config again (backend/supabase_client.py:245). A missing or expired share is 404 "links last 72 hours" (backend/app.py:724).
- title: Render it | short: /results | sub: same page as any result
  body: loadSharedResults sets data, merges the shared config through stripSecrets so the viewer's own credentials stay, and moves to /results keeping the query string (frontend/src/App.js:322). From here the Results page works as usual, and the result is persisted to IndexedDB like any other (frontend/src/App.js:552).
```

## Diagram

```diagram
lane web Browser
lane api Flask API
lane store Storage
node btn lane=web color=process "Share button" "handleShare"
node open lane=web color=process "?share= link" "loadSharedResults"
node res lane=web color=safe "Results" "/results"
node post lane=api color=process "POST /api/share" "20/h per IP"
node get lane=api color=safe "GET /api/shared" "id regex"
node tbl lane=store color=structural "shared_results" "72h rows"
node mem lane=store color=caution "_mem_shares" "process memory"
edge btn -> post "data, config"
edge post -> tbl "insert"
edge post -> mem "on failure"
edge open -> get "id"
edge get -> mem "first"
edge get -> tbl "then"
edge get -> res "data"
```

## Context map

```context
depends-on: [[backend-api-endpoints]] — POST /api/share and GET /api/shared/<id>
depends-on: [[backend-caching-and-limits]] — the 20-per-hour share limiter and body cap
depends-on: [[data-model]] — the shared_results table
depends-on: [[security]] — secret stripping and RLS with no anon policies
depends-on: [[auth]] — optional token, recorded as created_by
depends-on: [[frontend-pages-and-routing]] — the ?share= effect and /results route
depends-on: [[frontend]] — apiFetch and stripSecrets
depends-on: [[backend]] — supabase_client share helpers
depends-on: [[feat-results]] — the Share button and the page a link opens into
provides: a 72-hour public link to one analysis, no account needed
relied-on-by: [[feat-account]] — account deletion removes shares the user created
```

## Reference

| Item {kind} | Where | Meaning |
|---|---|---|
| `POST /api/share` {route} | `backend/app.py:698` | create a share; returns shareId, expiresAt |
| `GET /api/shared/<id>` {route} | `backend/app.py:718` | read a share; returns data, config, timestamp |
| `SHARE_ID_RE` {const} | `backend/app.py:690` | `^[A-Za-z0-9_-]{6,32}$` |
| `share_limiter` {const} | `backend/app.py:52` | 20 calls per 3600 s per client IP |
| `MAX_SHARE_BYTES` {const} | `backend/supabase_client.py:33` | 2 MB, compressed |
| `SHARE_TTL_HOURS` {const} | `backend/supabase_client.py:34` | 72 |
| `_mem_shares` {code} | `backend/supabase_client.py:202` | id to (blob, deadline); expired entries pruned on each put |
| `store_share` {code} | `backend/supabase_client.py:222` | strip, pack, size check, insert or memory |
| `get_share` {code} | `backend/supabase_client.py:245` | memory first, then unexpired row |
| `shared_results` {table} | `backend/migrations/001_shares_and_rls.sql:13` | id, payload, size_bytes, created_by, created_at, expires_at |
| `created_by` {column} | `backend/migrations/001_shares_and_rls.sql:17` | references auth.users, on delete set null |
| `loadSharedResults` {code} | `frontend/src/App.js:312` | fetch and load a share |
| `handleShare` {code} | `frontend/src/App.js:624` | create a share |

## Invariants

- **NEVER** put WarcraftLogs credentials in a share: the browser strips them (`frontend/src/App.js:635`), the server strips on write (`backend/supabase_client.py:223`) and again on read (`backend/supabase_client.py:259`). A test checks the secret never reaches the stored payload (`backend/test_api.py:116`).
- **NEVER** let a shared config overwrite the viewer's own credentials (`frontend/src/App.js:325`).
- **MUST** serve a share only before its deadline: rows are filtered with `expires_at > now` (`backend/supabase_client.py:250`), memory entries by their stored deadline (`backend/supabase_client.py:217`).
- **MUST** reject ids that do not match `SHARE_ID_RE` before any lookup (`backend/app.py:720`).
- **MUST** try each `?share=` id once; a failed load must not loop (`frontend/src/App.js:351`).

## Gotchas

- **Big analyses are sent compressed**: on AWS, Lambda refuses request bodies over 6 MB, and a big guild's full-season result is larger. Share and Save gzip the body in the browser (`apiFetch(..., {compress: true})`, `frontend/src/api.js`) and the API inflates it with a 64 MB cap (`backend/bodies.py`); an oversized body answers 413. Browsers without `CompressionStream` send plain JSON.
- **Memory fallback is per process.** `_mem_shares` is a module dict (`backend/supabase_client.py:202`). Gunicorn runs `WEB_CONCURRENCY` workers, default 1 (`backend/gunicorn.conf.py:13`); with more than one, a memory share is only found by the worker that stored it.
- **Memory is checked before Supabase.** `get_share` returns a memory hit without consulting the table (`backend/supabase_client.py:246`), and memory hits carry no `created_at`, so `timestamp` is null.
- **Housekeeping rides on new shares.** Expired rows are deleted only when someone creates a share (`backend/supabase_client.py:230`); reads just filter them out.
- **The browser ignores `expiresAt` and `timestamp`.** Neither is shown (`frontend/src/App.js:641`, `frontend/src/App.js:322`).
- **A share is a snapshot.** It stores the result as it was; nothing re-fetches WarcraftLogs when the link opens.

## Related

- [[feat-results]] — where Share lives and where links open
- [[feat-saved]] — the signed-in, longer-lived alternative
- [[feat-account]] — deletion removes the user's shares
- [[backend-api-endpoints]] — the route table
- [[backend-caching-and-limits]] — rate limits and size caps
- [[data-model]] — the shared_results table
- [[security]] — credential stripping and RLS
- [[auth]] — optional token on create
- [[frontend-pages-and-routing]] — the ?share= handling
- [[frontend]] — the React app
- [[backend]] — the Flask API
