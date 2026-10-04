---
id: security
title: Security & Trust Boundaries
domain: security
status: documented
summary:
  - "Four parties hold something worth protecting: the browser, the Flask API, Supabase and the WarcraftLogs proxy."
  - "The officer's own WarcraftLogs client ID and secret are kept in browser localStorage and sent with every analysis; they are stripped from every save and share on both sides."
  - "Supabase tables have row-level security on; the backend reaches them with the service-role key and scopes every query by a verified user id."
  - "Writes are rate-limited per client IP with in-memory sliding windows: 60 analyses, 30 saves and 20 shares an hour."
  - "Known residual risks: limits are per process and keyed on a spoofable header, and CORS allows any origin unless ALLOWED_ORIGINS is set."
tagline: Who holds which secret, what each boundary checks, and what is still open.
anchors:
  allowed_origins: backend/app.py:64
  cors: backend/app.py:65
  max_content_length: backend/app.py:59
  limiters: backend/app.py:49
  analyze_limit: backend/app.py:83
  looks_like_analysis: backend/app.py:628
  share_id_re: backend/app.py:624
  cheat_death_gate: backend/app.py:116
  client_ip: backend/ratelimit.py:16
  rate_limiter: backend/ratelimit.py:25
  limit_decorator: backend/ratelimit.py:47
  verify_token: backend/auth.py:36
  require_user: backend/auth.py:79
  strip_secrets_py: backend/supabase_client.py:61
  service_key_choice: backend/supabase_client.py:38
  rls: backend/migrations/001_shares_and_rls.sql:23
  creds_policies: backend/migrations/001_shares_and_rls.sql:36
  report_cache_rls: backend/migrations/002_report_cache.sql:23
  strip_secrets_js: frontend/src/api.js:40
  local_creds: frontend/src/api.js:18
  wcl_token_cache: backend/warcraftlogs.py:93
  wcl_proxy: backend/warcraftlogs.py:16
links:
  - auth
  - data-model
  - backend
  - frontend
  - deployment
  - feat-share
  - feat-saved
  - operations
flows:
  - request-path
  - share-path
invariants:
  - "MUST: configs pass through strip_secrets in the browser before any save, share or local history write, and again on the server before storage."
  - "MUST: saved-analysis and account routes take the user id only from require_user."
  - "MUST: share and save bodies pass _looks_like_analysis before anything is stored."
  - "NEVER: the browser reads saved_analyses, shared_results or report_cache; RLS is on and no policies grant it."
  - "NEVER: a WarcraftLogs secret is used as a cache key in plain form; the token cache keys on a SHA-256 of id and secret."
content_hash: sha256:72d6493449acc0c3a87a38825498683ef183ec380ec7f2bf3ba073235f408695
---
# Security & Trust Boundaries

## Summary

- There is no shared server-side WarcraftLogs key. Each officer brings their own WarcraftLogs API client ID and secret; the browser keeps them in `localStorage` under `fpx.wclCredentials` (`frontend/src/api.js:18`) and sends them in the body of every `POST /api/analyze` (`frontend/src/App.js:693`). Signed-in users can also store them in Supabase `api_credentials` (`frontend/src/App.js:587`).
- The backend uses those credentials only for the length of one analysis. It exchanges them for a WarcraftLogs token through a Cloudflare Worker proxy (`backend/warcraftlogs.py:16`) and caches the token keyed by a SHA-256 of `id:secret` (`backend/warcraftlogs.py:93`).
- Everything that persists an analysis (saves, shares, local recent runs) removes `clientId` and `clientSecret` first, in the browser (`frontend/src/api.js:40`) and again on the server (`backend/supabase_client.py:61`).
- Supabase is the data and identity store. The browser holds only the public anon key; the backend holds the service-role key and the anon key. Row-level security keeps the anon key away from every table except the user's own credentials row (`backend/migrations/001_shares_and_rls.sql:23`, `:36`).

## Diagram

Each lane is a trust zone. Arrows show what crosses the boundary.

```diagram
lane browser Browser (untrusted)
node ls lane=browser color=caution "localStorage" "WCL id + secret"
node spa lane=browser color=process "React app" "anon key, JWT"
lane api Flask API on Render
node cors lane=api color=structural "CORS + 25 MB cap" "ALLOWED_ORIGINS"
node rl lane=api color=caution "Rate limiter" "per IP, per process"
node guard lane=api color=safe "require_user" "verify JWT"
node strip lane=api color=safe "strip_secrets" "before storage"
lane supa Supabase
node gotrue lane=supa color=structural "Supabase Auth" "/auth/v1/user"
node tables lane=supa color=structural "App tables" "RLS on"
node creds lane=supa color=caution "api_credentials" "own-row policies"
lane wcl WarcraftLogs side
node proxy lane=wcl color=caution "WCL proxy" "Cloudflare Worker"
edge ls -> spa color=process "read"
edge spa -> cors color=process "Bearer + body"
edge cors -> rl color=process "write routes"
edge rl -> guard color=process "saved, account"
edge guard -> gotrue color=process "verify"
edge guard -> strip color=safe "user id"
edge strip -> tables color=safe "service role"
edge spa -> creds color=caution "anon + JWT"
edge rl -> proxy color=caution "id + secret"
edge rl -> spa color=never "429"
band structural "Supabase project"
```

## How it works

A request crosses the same gates in the same order. The steps follow one analysis, then a share.

```steps
- title: Credentials in the browser | short: Browser creds | sub: localStorage, signed in or not
  body: The analyze form's client ID and secret are written to localStorage on every change (frontend/src/App.js:213 calling frontend/src/api.js:30) and read back on load (frontend/src/api.js:20). Every access is wrapped in try/catch so a blocked storage just starts the form empty. Signed-in users also get a copy in Supabase api_credentials, written only when the values changed (frontend/src/App.js:571).
  gotcha: The secret sits in plain text in localStorage and in the api_credentials.client_secret column. Any script running on the site's origin can read the localStorage copy; RLS is the only guard on the column.
- title: CORS and body size | short: CORS | sub: before any route
  body: flask-cors allows the origins listed in ALLOWED_ORIGINS for /api/* paths, with only the Content-Type and Authorization headers and the GET, POST, DELETE and OPTIONS methods (backend/app.py:64). Flask rejects any body over 25 MB with 413 before a route runs (backend/app.py:59).
  gotcha: With ALLOWED_ORIGINS unset the default is '*'. The comment at backend/app.py:62 explains why that is tolerable: requests use bearer tokens, not cookies, so a foreign page cannot ride a user's session.
- title: Rate limit | short: Rate limit | sub: sliding window per IP
  body: Each write route is wrapped by limit(), which keys a RateLimiter on client_ip() and returns 429 when the window is full (backend/ratelimit.py:47). OPTIONS preflights are never counted. The limiter drops idle keys once it tracks more than 10,000 clients (backend/ratelimit.py:41).
- title: Validate input | short: Validate | sub: shape checks, id patterns
  body: /api/analyze rejects a non-object body with 400 (backend/app.py:89) and clamps maxCutoff to 1-10 (backend/app.py:107). Share and save bodies must have data.events as an object (_looks_like_analysis, backend/app.py:628). Share ids must match ^[A-Za-z0-9_-]{6,32}$ and saved ids a 36-character UUID pattern before any lookup (backend/app.py:624, :625).
- title: Identify the caller | short: Auth | sub: Supabase decides
  body: require_user (backend/auth.py:79) verifies the bearer token with Supabase and exposes the id as g.user_id. Analyze and share check the token optionally. Cheat-death detection is ANDed with a verified session on the server (backend/app.py:116), so a crafted config cannot turn it on. Details are on the [[auth]] page.
- title: Use WCL credentials | short: WCL token | sub: through the proxy
  body: get_access_token sends the id and secret as HTTP Basic auth to the proxy's /oauth/token (backend/warcraftlogs.py:101) and caches the token per credential pair until 60 seconds before it expires (backend/warcraftlogs.py:130). The credentials are not written anywhere by the backend.
- title: Store without secrets | short: Strip + store | sub: both sides, then RLS
  body: The browser strips clientId and clientSecret before a share, a save and a recent-run write (frontend/src/App.js:617, frontend/src/SaveReportDialog.js:27, frontend/src/App.js:465). The server strips a wider key set (client ids, secrets, password, token, access tokens) before packing and again when returning (backend/supabase_client.py:57, :101, :214, :250). Rows go in with the service-role key into tables that have RLS on and no policies.
```

## Reference

Rate limits and guards per endpoint (`backend/app.py`). Limits are per client IP, per hour, per process.

| Endpoint {write} | Limit | Session | Input checks |
|---|---|---|---|
| `POST /api/analyze` {write} | 60 / hour (`backend/app.py:50`, `:83`) | optional | body is an object; `maxCutoff` clamped 1-10 |
| `POST /api/share` {write} | 20 / hour (`backend/app.py:49`, `:633`) | optional | `_looks_like_analysis`; 2 MB compressed cap (`backend/supabase_client.py:33`) |
| `POST /api/saved` {write} | 30 / hour (`backend/app.py:51`, `:679`) | required | `_looks_like_analysis`; 3 MB compressed cap; 5 saves per user (`backend/supabase_client.py:31`) |
| `GET /api/shared/<id>` {read} | none | none | `SHARE_ID_RE` (`backend/app.py:624`) |
| `GET`/`DELETE /api/saved/<id>` {read} | none | required | `SAVED_ID_RE` (`backend/app.py:625`) |
| `GET`/`DELETE /api/saved`, `DELETE /api/account` {read} | none | required | none |
| all routes {all} | 25 MB request body (`backend/app.py:59`) | - | Flask returns 413 |

Who holds which secret.

| Secret {secret} | Held by | Where it comes from |
|---|---|---|
| WarcraftLogs client ID and secret {secret} | browser localStorage; `api_credentials` row; backend memory during an analysis | typed by the officer (`frontend/src/AnalyzeConfig.js:152`) |
| Supabase anon key {secret} | frontend bundle (public by design) and backend env `SUPABASE_KEY` | `frontend/src/supabaseClient.js:4`; `backend/auth.py:21` |
| Supabase service-role key {secret} | backend env only | `SUPABASE_SERVICE_ROLE_KEY` (`backend/supabase_client.py:29`) |
| Supabase access token (JWT) {secret} | browser session; backend cache as a SHA-256 key only | `backend/auth.py:41` |
| WarcraftLogs access token {secret} | backend memory | `backend/warcraftlogs.py:125` |

## Invariants

- **MUST** configs pass through `stripSecrets` in the browser before any save, share or recent-run write (`frontend/src/api.js:40`), and through `strip_secrets` on the server before storage and on the way out (`backend/supabase_client.py:101`, `:154`, `:214`, `:250`). Tests check the secret never reaches the stored payload (`backend/test_api.py:106`, `:121`).
- **MUST** saved-analysis and account routes take the user id only from `require_user` (`backend/auth.py:91`); the service-role key bypasses RLS, so this is the only thing separating users' saves.
- **MUST** share and save bodies pass `_looks_like_analysis` before anything is stored (`backend/app.py:638`, `:683`).
- **NEVER** the browser reads `saved_analyses`, `shared_results` or `report_cache`: RLS is on and no policy grants the anon or authenticated role (`backend/migrations/001_shares_and_rls.sql:27`, `backend/migrations/002_report_cache.sql:21`).
- **NEVER** a WarcraftLogs secret is used as a cache key in plain form; the token cache keys on a SHA-256 of `id:secret` (`backend/warcraftlogs.py:93`).

## Gotchas

- **Rate limits are per process**: each `RateLimiter` is an in-memory dict (`backend/ratelimit.py:29`). A restart clears it, and with `WEB_CONCURRENCY` above 1 every gunicorn worker keeps its own count, so the effective limit multiplies (see [[deployment]]).
- **The limiter keys on Cloudflare's client address**: `client_ip()` reads `CF-Connecting-IP`, which Cloudflare (in front of Render) sets and overwrites, and falls back to the socket address (`backend/ratelimit.py:17-22`). `X-Forwarded-For` is ignored because Render appends to a client-sent value, so its first entry can be forged. `backend/test_ratelimit.py` checks that a forged header doesn't change the key. If the API ever stops being served through Cloudflare, every client would share the proxy's address and one limit.
- **Reads and failed sign-ins are not rate-limited**: `GET /api/shared/<id>` and the `require_user` routes have no limiter, and `POST /api/saved` checks the session before the limiter (`backend/app.py:678`). Only successful token checks are cached (`backend/auth.py:68`), so each request with a bad bearer token costs one call to Supabase.
- **CORS defaults to any origin**: `ALLOWED_ORIGINS` falls back to `'*'` (`backend/app.py:64`). This is safe for session theft because auth is a bearer header, but any site can call the API from a visitor's browser and spend that visitor's IP's rate-limit budget.
- **WarcraftLogs traffic goes through a Cloudflare Worker outside this repo**: both the OAuth exchange and every GraphQL query use `wcl-proxy.catcam-fun.workers.dev` (`backend/warcraftlogs.py:15`, `:16`), and the sign-in CAPTCHA check uses the same host (`frontend/src/Auth.js:73`). The Worker's code is not in this repo, so its behavior can't be reviewed here, and it sees every officer's client ID and secret.
- **The server strips more keys than the browser**: the browser removes only `clientId` and `clientSecret` (`frontend/src/api.js:12`); the server also removes `password`, `token` and access-token keys (`backend/supabase_client.py:57`). Both strip only top-level keys of the config, not nested objects.
- **Analysis errors are echoed to the client**: an unexpected exception in `/api/analyze` is sent as `str(e)` in the event stream (`backend/app.py:612`), and a failed WarcraftLogs login includes the request error text (`backend/app.py:133`).
- **The shared report cache is not scoped per API key**: finished reports' fights and deaths are cached by report code for every caller (`backend/app.py:187`). A caller only reaches a report that their own key listed through `get_guild_reports` (`backend/app.py:163`), which is what keeps one guild's private reports away from another key.

## Glossary

- **Trust boundary**: a line between two parties where data must be checked because the receiving side does not control the sending side.
- **RLS**: Postgres row-level security. With RLS on and no policy, the anon and authenticated roles see nothing in that table.
- **Service-role key**: the Supabase key that bypasses RLS. Only the backend holds it.
- **Sliding window**: the rate limiter keeps each client's request times from the last hour and refuses a request once the count reaches the limit.
- **WCL proxy**: the Cloudflare Worker the backend calls instead of WarcraftLogs directly, for OAuth tokens and GraphQL.

## Related

- [[auth]] — how a bearer token becomes a verified user id
- [[data-model]] — the tables, RLS policies and secret stripping in storage
- [[backend]] — the Flask routes these guards wrap
- [[frontend]] — localStorage credentials and browser-side stripping
- [[deployment]] — how worker count and env vars change these guarantees
- [[feat-share]] — public share links, the main path where data leaves an account
- [[feat-saved]] — per-user saves guarded by `require_user`
- [[operations]] — watching rate-limit and auth failures in production
