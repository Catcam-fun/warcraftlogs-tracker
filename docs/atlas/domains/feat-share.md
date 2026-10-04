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
  share_button: "frontend/src/App.js:1619"
  handle_share: "frontend/src/App.js:609"
  share_link: "frontend/src/App.js:624"
  share_modal: "frontend/src/App.js:1409"
  share_param_effect: "frontend/src/App.js:334"
  load_shared: "frontend/src/App.js:297"
  idb_restore_skip: "frontend/src/App.js:517"
  share_endpoint: "backend/app.py:636"
  shared_endpoint: "backend/app.py:653"
  share_id_re: "backend/app.py:628"
  share_limiter: "backend/app.py:49"
  share_limits: "backend/supabase_client.py:33"
  store_share: "backend/supabase_client.py:215"
  get_share: "backend/supabase_client.py:238"
  mem_fallback: "backend/supabase_client.py:195"
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
  - "NEVER: put WarcraftLogs credentials in a share; they are stripped in the browser, on write and on read (frontend/src/App.js:618, backend/supabase_client.py:216, backend/supabase_client.py:252)."
  - "NEVER: let a shared config overwrite the viewer's own credentials (frontend/src/App.js:310)."
  - "MUST: serve a share only before its expires_at; Supabase rows are filtered on expires_at and memory entries on their own deadline (backend/supabase_client.py:243, backend/supabase_client.py:210)."
  - "MUST: reject share ids outside [A-Za-z0-9_-]{6,32} before any lookup (backend/app.py:655)."
  - "MUST: try each ?share= id once per page; a failed load must not loop (frontend/src/App.js:336)."
content_hash: sha256:386512a0a1438b0b90247f49393ce5a298a03844cfac76287bb57ef93db7b415
---
## Summary

- **What it is.** A short, unguessable link to one analysis result. The id is `secrets.token_urlsafe(9)`, 12 URL-safe characters (`backend/app.py:646`), and the link is `<origin>/results?share=<id>` (`frontend/src/App.js:624`).
- **Who can use it.** Anyone. Creating a share needs no account (`frontend/src/App.js:616`); if a session is present the server records its user id as `created_by` so account deletion can remove it (`backend/app.py:645`).
- **How long.** 72 hours (`SHARE_TTL_HOURS`, `backend/supabase_client.py:34`).
- **What it carries.** The result object and the analysis config with credentials removed, packed `br64:` (`backend/supabase_client.py:216`).

## How it works

```steps
- title: Press Share | short: Share | sub: Results header
  body: The Share button on /results calls handleShare (frontend/src/App.js:1619). It POSTs { data, config } to /api/share with config passed through stripSecrets; a signed-in user's token is attached as optional auth (frontend/src/App.js:614).
- title: Server stores it | short: POST /api/share | sub: check, pack, insert
  body: The route is limited to 20 per hour per client IP (backend/app.py:49, backend/app.py:637) and rejects a body without an events object (backend/app.py:642). store_share strips secrets, packs, refuses over 2 MB compressed, deletes every expired share in the table, then inserts id, payload, size_bytes, created_by and expires_at (backend/supabase_client.py:215). The response carries shareId and expiresAt (backend/app.py:650).
  gotcha: Any store error comes back as 413, but the only error store_share returns is too_large (backend/app.py:649).
- title: Fallback to memory | short: Memory fallback | sub: table missing or insert fails
  body: If the insert throws (for example, the table was never created), the blob goes into the _mem_shares dict with the same 72-hour deadline, and the call still succeeds with ephemeral true (backend/supabase_client.py:232). The route does not pass ephemeral on to the browser (backend/app.py:650).
  gotcha: Memory shares vanish on restart and are only visible to the process that stored them.
- title: Copy the link | short: Share modal | sub: copy to clipboard
  body: The modal shows the link in a read-only field with a Copy button (frontend/src/App.js:1409, frontend/src/App.js:633). It does not show the expiry.
- title: Open the link | short: ?share= | sub: once per id
  body: An effect on location.search reads the share param and calls loadSharedResults once per id, tracked by attemptedShareRef (frontend/src/App.js:334). The mount-time IndexedDB restore is skipped while a share param is present (frontend/src/App.js:517).
- title: Server returns it | short: GET /api/shared/<id> | sub: memory, then Supabase
  body: The id must match SHARE_ID_RE or the route answers 404 (backend/app.py:655). get_share checks memory first, then selects the row only if expires_at is still in the future, unpacks it and strips secrets from the config again (backend/supabase_client.py:238). A missing or expired share is 404 "links last 72 hours" (backend/app.py:659).
- title: Render it | short: /results | sub: same page as any result
  body: loadSharedResults sets data, merges the shared config through stripSecrets so the viewer's own credentials stay, and moves to /results keeping the query string (frontend/src/App.js:307). From here the Results page works as usual, and the result is persisted to IndexedDB like any other (frontend/src/App.js:537).
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
| `POST /api/share` {route} | `backend/app.py:636` | create a share; returns shareId, expiresAt |
| `GET /api/shared/<id>` {route} | `backend/app.py:653` | read a share; returns data, config, timestamp |
| `SHARE_ID_RE` {const} | `backend/app.py:628` | `^[A-Za-z0-9_-]{6,32}$` |
| `share_limiter` {const} | `backend/app.py:49` | 20 calls per 3600 s per client IP |
| `MAX_SHARE_BYTES` {const} | `backend/supabase_client.py:33` | 2 MB, compressed |
| `SHARE_TTL_HOURS` {const} | `backend/supabase_client.py:34` | 72 |
| `_mem_shares` {code} | `backend/supabase_client.py:195` | id to (blob, deadline); expired entries pruned on each put |
| `store_share` {code} | `backend/supabase_client.py:215` | strip, pack, size check, insert or memory |
| `get_share` {code} | `backend/supabase_client.py:238` | memory first, then unexpired row |
| `shared_results` {table} | `backend/migrations/001_shares_and_rls.sql:13` | id, payload, size_bytes, created_by, created_at, expires_at |
| `created_by` {column} | `backend/migrations/001_shares_and_rls.sql:17` | references auth.users, on delete set null |
| `loadSharedResults` {code} | `frontend/src/App.js:297` | fetch and load a share |
| `handleShare` {code} | `frontend/src/App.js:609` | create a share |

## Invariants

- **NEVER** put WarcraftLogs credentials in a share: the browser strips them (`frontend/src/App.js:618`), the server strips on write (`backend/supabase_client.py:216`) and again on read (`backend/supabase_client.py:252`). A test checks the secret never reaches the stored payload (`backend/test_api.py:116`).
- **NEVER** let a shared config overwrite the viewer's own credentials (`frontend/src/App.js:310`).
- **MUST** serve a share only before its deadline: rows are filtered with `expires_at > now` (`backend/supabase_client.py:243`), memory entries by their stored deadline (`backend/supabase_client.py:210`).
- **MUST** reject ids that do not match `SHARE_ID_RE` before any lookup (`backend/app.py:655`).
- **MUST** try each `?share=` id once; a failed load must not loop (`frontend/src/App.js:336`).

## Gotchas

- **Memory fallback is per process.** `_mem_shares` is a module dict (`backend/supabase_client.py:195`). Gunicorn runs `WEB_CONCURRENCY` workers, default 1 (`backend/gunicorn.conf.py:13`); with more than one, a memory share is only found by the worker that stored it.
- **Memory is checked before Supabase.** `get_share` returns a memory hit without consulting the table (`backend/supabase_client.py:239`), and memory hits carry no `created_at`, so `timestamp` is null.
- **Housekeeping rides on new shares.** Expired rows are deleted only when someone creates a share (`backend/supabase_client.py:223`); reads just filter them out.
- **The browser ignores `expiresAt` and `timestamp`.** Neither is shown (`frontend/src/App.js:624`, `frontend/src/App.js:307`).
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
