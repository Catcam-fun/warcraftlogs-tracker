---
id: auth
title: Accounts & Auth
domain: auth
status: documented
summary:
  - "Accounts are Supabase Auth email-and-password users; the browser signs in directly against Supabase."
  - "The backend never trusts a user id from the request: it sends the bearer token to Supabase's /auth/v1/user and uses the id that comes back."
  - "Verified tokens are cached in memory for 60 seconds, keyed by a SHA-256 of the token."
  - "Saved-analysis and account endpoints require a session; analyze and share accept one optionally."
  - "Deleting an account removes saves, stored credentials, shares and the auth user, then signs the browser out."
tagline: How a Supabase session is created in the browser and verified on every protected backend call.
anchors:
  supabase_client: frontend/src/supabaseClient.js:6
  session_only: frontend/src/supabaseClient.js:15
  sign_in: frontend/src/Auth.js:139
  captcha: frontend/src/Auth.js:72
  api_fetch: frontend/src/api.js:55
  analyze_header: frontend/src/App.js:720
  session_restore: frontend/src/App.js:277
  bearer: backend/auth.py:29
  verify_token: backend/auth.py:36
  cache_ttl: backend/auth.py:23
  require_user: backend/auth.py:79
  delete_route: backend/app.py:783
  delete_impl: backend/supabase_client.py:417
  delete_client: frontend/src/Settings.js:187
links:
  - frontend
  - backend
  - data-model
  - security
  - feat-account
  - feat-saved
  - feat-share
flows:
  - share-path
  - request-path
invariants:
  - "MUST: protected routes take the user id only from verify_token, exposed as g.user_id."
  - "MUST: verify_token return None on any non-200 or network failure, so the route answers 401."
  - "NEVER: store raw tokens in the verification cache; keys are SHA-256 hashes."
  - "NEVER: honor enableCheatDeath without a verified session."
content_hash: sha256:4965a8c49fe84978a9fadd07b5cf46e82eaa5c2e40943cce3b027b818bcd320d
---
# Accounts & Auth

## Summary

- Sign-up, sign-in, password reset, email change and password change all run in the browser against Supabase Auth with the public anon key (`frontend/src/Auth.js:135`, `:139`, `:94`; `frontend/src/Settings.js:136`, `:168`).
- When the browser calls the backend it attaches `Authorization: Bearer <access token>` (`frontend/src/api.js:92`). The backend turns that into a user id by asking Supabase (`backend/auth.py:49`), never by reading an id from the URL or body.
- The `@require_user` decorator (`backend/auth.py:79`) guards every saved-analysis route and account deletion. Analyze and share check the token without requiring it.

## Diagram

```diagram
lane browser Browser
node form lane=browser color=process "Sign-in modal" "Auth.js"
node sdk lane=browser color=process "supabase-js" "session in storage"
node apifetch lane=browser color=process "apiFetch" "adds Bearer"
lane server Flask backend
node req lane=server color=process "require_user" "auth.py"
node cache lane=server color=structural "Token cache" "sha256, 60s"
node route lane=server color=safe "Route handler" "g.user_id"
lane supa Supabase
node gotrue lane=supa color=structural "Supabase Auth" "/auth/v1/user"
edge form -> sdk color=process "signIn"
edge sdk -> gotrue color=process "password"
edge sdk -> apifetch color=process "access token"
edge apifetch -> req color=process "Bearer"
edge req -> cache color=structural "lookup"
edge req -> gotrue color=process "verify"
edge req -> route color=safe "user id"
edge req -> apifetch color=never "401"
```

## How it works

```steps
- title: Sign in or sign up | short: Sign in | sub: browser to Supabase
  body: The modal requires a Cloudflare Turnstile token, posts it to a verify-turnstile worker (frontend/src/Auth.js:73), then calls supabase.auth.signUp or signInWithPassword directly (frontend/src/Auth.js:135, :139). Sign-up also requires the age and terms checkboxes (frontend/src/Auth.js:111).
  gotcha: The CAPTCHA check happens in the browser before the Supabase call. Nothing in this repo makes Supabase itself demand the CAPTCHA, so a script calling Supabase directly skips it unless the Supabase project enforces one.
- title: Stay logged in | short: Session length | sub: localStorage flag + cookie
  body: Supabase always persists the session. Unchecking "Stay logged in" sets a localStorage flag and a session cookie (frontend/src/supabaseClient.js:15). On the next load, flag set and cookie gone means the browser was closed, and App.js signs out locally (frontend/src/App.js:277).
- title: Call the backend | short: Send token | sub: apiFetch
  body: apiFetch with auth true reads the current session and adds the Bearer header; with no session it returns a local 401 without a network call. auth 'optional' attaches a token only if there is one (frontend/src/api.js:55). The analyze stream uses fetch directly and adds the same header when signed in (frontend/src/App.js:720).
- title: Verify the token | short: Verify | sub: GET /auth/v1/user
  body: verify_token (backend/auth.py:36) hashes the token, returns a cached user id if it is under 60 seconds old, otherwise calls SUPABASE_URL/auth/v1/user with the anon key as apikey and a 10 second timeout. Only a 200 with an id counts.
  gotcha: The cache holds up to 1000 entries; when full it drops expired ones, or half the cache if none have expired (backend/auth.py:65).
- title: Guard the route | short: require_user | sub: 401 or g.user_id
  body: require_user lets OPTIONS through with 204, otherwise returns 401 "Please sign in again." or sets g.user_id and calls the handler (backend/auth.py:84).
- title: Delete the account | short: Delete account | sub: DELETE /api/account
  body: Settings asks the user to type DELETE, then calls DELETE /api/account with the session (frontend/src/Settings.js:199). The backend deletes saved_analyses, api_credentials and shares for g.user_id, then the auth user via the admin API (backend/supabase_client.py:392, :394), drops the token from the cache (backend/app.py:789), and the browser signs out locally and goes home (frontend/src/Settings.js:204).
  gotcha: Only the token used for the delete is forgotten. Another tab's token for the same user stays cached for up to 60 seconds and would still pass require_user.
```

## Reference

Which backend endpoints use a session (`backend/app.py`).

| Endpoint {required} | Session | What the user id is used for |
|---|---|---|
| `GET /api/saved` {required} | required (`backend/app.py:734`) | list only this user's saves |
| `POST /api/saved` {required} | required (`backend/app.py:740`) | owner of the new save |
| `GET /api/saved/<id>` {required} | required (`backend/app.py:758`) | load only if owned |
| `DELETE /api/saved/<id>` {required} | required (`backend/app.py:766`) | delete only if owned |
| `DELETE /api/saved` {required} | required (`backend/app.py:774`) | delete all of this user's saves |
| `DELETE /api/account` {required} | required (`backend/app.py:784`) | delete the account |
| `POST /api/analyze` {optional} | optional (`backend/app.py:120`) | enables cheat-death detection (`backend/app.py:143`) |
| `POST /api/share` {optional} | optional (`backend/app.py:700`) | sets `created_by` so account deletion removes the share |
| `GET /api/shared/<id>` {public} | none | shares are public by link |
| `GET /api/health`, `GET /` {public} | none | status only |

The browser also reads and writes its own `api_credentials` row directly with the Supabase client (`frontend/src/App.js:563`, `frontend/src/Settings.js:40`); RLS limits that to `auth.uid() = user_id` (`backend/migrations/001_shares_and_rls.sql:36`).

## Invariants

- **MUST** protected routes take the user id only from `verify_token`, exposed as `g.user_id` (`backend/auth.py:91`); a test sends `?user_id=victim` and checks it is ignored (`backend/test_api.py:141`).
- **MUST** `verify_token` return `None` on a non-200, a missing id or a network error (`backend/auth.py:54`, `:57`, `:61`), so the route answers 401 rather than guessing.
- **NEVER** store raw tokens in the verification cache; keys are SHA-256 hex digests (`backend/auth.py:41`).
- **NEVER** honor `enableCheatDeath` without a verified session; the flag is ANDed with `signed_in` on the server (`backend/app.py:143`).

## Gotchas

- **Missing env disables all sign-in checks**: `verify_token` returns `None` when `SUPABASE_URL` or `SUPABASE_KEY` is unset (`backend/auth.py:38`), so every protected route returns 401.
- **auth.py does not load .env itself**: it reads `os.environ` at import (`backend/auth.py:20`); it works because `backend/app.py:20` calls `load_dotenv()` before importing it.
- **Account deletion needs the service-role key**: without `SUPABASE_SERVICE_ROLE_KEY` the backend refuses with "Account deletion isn't configured on the server." (`backend/supabase_client.py:422`).
- **Partial deletion reports an error**: if any table or the auth delete fails, the response is an error asking to retry (`backend/supabase_client.py:442`); share cleanup failures are only logged.
- **Password reset lands back on the site**: the reset link redirects to `window.location.origin` (`frontend/src/Auth.js:95`), and the `PASSWORD_RECOVERY` event opens Settings (`frontend/src/App.js:295`).

## Glossary

- **Access token**: the short-lived Supabase JWT in the browser session, sent as the Bearer token.
- **Anon key**: Supabase's public key, shipped in the frontend bundle (`frontend/src/supabaseClient.js:4`); RLS decides what it can reach.
- **require_user**: the Flask decorator that turns a valid Bearer token into `g.user_id` or returns 401.

## Related

- [[frontend]] — the sign-in modal, Settings page and `apiFetch`
- [[backend]] — the routes guarded by `require_user`
- [[data-model]] — the tables scoped by the verified user id
- [[security]] — trust boundaries and residual risks around sessions
- [[feat-account]] — the Settings page flows: credentials, password, email, deletion
- [[feat-saved]] — every saved-analysis call requires a session
- [[feat-share]] — sharing works signed out; signed in, the share is tied to the account
