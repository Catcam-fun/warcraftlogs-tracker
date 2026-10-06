---
id: feat-account
title: Account & Settings
domain: feat-account
status: documented
summary:
  - "Accounts are optional Supabase email-and-password logins; analysis works without one, while saved reports and cheat-death detection need one."
  - "Sign-in, sign-up and password reset happen in the Auth modal, behind a Cloudflare Turnstile check, with a 'Stay logged in' option that ends the session when the browser closes."
  - "WarcraftLogs Client ID and Secret are remembered in the browser's localStorage for everyone, and in the api_credentials table for signed-in users, which the browser reads and writes directly under row-level security."
  - "Settings changes credentials, password and email, and deletes the account through DELETE /api/account, which removes saves, stored credentials, shares and the login itself."
  - "Terms of Service and Privacy Policy are static pages at /terms and /privacy, linked from sign-up and the landing page footer."
tagline: Signing in, the Settings modal, stored credentials and deleting your account.
anchors:
  auth_modal: "frontend/src/Auth.js:8"
  handle_auth: "frontend/src/Auth.js:107"
  turnstile_verify: "frontend/src/Auth.js:72"
  password_reset: "frontend/src/Auth.js:84"
  session_only: "frontend/src/supabaseClient.js:15"
  session_restore: "frontend/src/App.js:268"
  auth_listener: "frontend/src/App.js:291"
  local_credentials: "frontend/src/api.js:20"
  remember_local: "frontend/src/App.js:217"
  load_db_credentials: "frontend/src/App.js:560"
  save_db_credentials: "frontend/src/App.js:586"
  logout: "frontend/src/App.js:614"
  settings_modal: "frontend/src/Settings.js:6"
  settings_save_creds: "frontend/src/Settings.js:60"
  delete_account_ui: "frontend/src/Settings.js:187"
  account_endpoint: "backend/app.py:749"
  delete_user_account: "backend/supabase_client.py:384"
  require_user: "backend/auth.py:79"
  verify_token: "backend/auth.py:36"
  credentials_rls: "backend/migrations/001_shares_and_rls.sql:36"
  terms_route: "frontend/src/App.js:1402"
  privacy_route: "frontend/src/App.js:1411"
links:
  - frontend
  - frontend-pages-and-routing
  - backend
  - backend-api-endpoints
  - data-model
  - auth
  - security
  - feat-analyze
  - feat-saved
  - feat-share
invariants:
  - "MUST: the server identify the account to delete from the verified bearer token, never from the URL or body (backend/app.py:750, backend/auth.py:88)."
  - "MUST: account deletion remove saved_analyses and api_credentials rows and the auth user, and report failure if any of those fail (backend/supabase_client.py:392, backend/supabase_client.py:407)."
  - "NEVER: delete an account without the service-role key; the call refuses instead (backend/supabase_client.py:388)."
  - "MUST: a signed-in user read and write only their own api_credentials row (backend/migrations/001_shares_and_rls.sql:36)."
  - "MUST: cheat-death detection run only for a request with a valid session (backend/app.py:137)."
content_hash: sha256:5c10c122a5d8fdc21136331c3e6292631f34c7826042ac5a241baf2a3ab9a6eb
---
## Summary

- **What it is.** Optional email-and-password accounts on Supabase Auth (`frontend/src/Auth.js:135`, `frontend/src/Auth.js:139`). The header shows Sign In or Settings and Logout depending on `user` (`frontend/src/App.js:1643`).
- **What an account unlocks.** Saved reports, which every `/api/saved` route gates with `require_user` (`backend/app.py:700`), and cheat-death detection, which the server turns off for calls without a valid session (`backend/app.py:114`, `backend/app.py:137`). Credentials also follow the user between browsers.
- **Where credentials live.** Always in this browser's localStorage under `fpx.wclCredentials` (`frontend/src/api.js:20`); for signed-in users also in `api_credentials`, which the browser reaches directly with the public anon key (`frontend/src/App.js:560`).
- **Leaving.** Settings deletes the account through the backend, which uses the service-role key (`frontend/src/Settings.js:199`, `backend/supabase_client.py:384`).

## How it works

```steps
- title: Open Sign In | short: Auth modal | sub: sign in, sign up, reset
  body: Sign In buttons open the Auth modal (frontend/src/App.js:2270). It loads Cloudflare Turnstile explicitly so the widget renders every time the modal opens (frontend/src/Auth.js:26).
- title: Sign up | short: Sign up | sub: age, terms, CAPTCHA
  body: Sign-up requires the "at least 13" box and the Terms and Privacy box (frontend/src/Auth.js:111), a Turnstile token (frontend/src/Auth.js:123) and a password of at least 6 characters (frontend/src/Auth.js:202). The token is verified by a separate Cloudflare Worker before supabase.auth.signUp runs (frontend/src/Auth.js:72, frontend/src/Auth.js:135). Supabase then sends a confirmation email.
  gotcha: The CAPTCHA check happens in the browser against the Worker; the token is not passed to Supabase, so it does not guard direct Supabase Auth calls.
- title: Sign in | short: Sign in | sub: stay logged in or not
  body: signInWithPassword, then setSessionOnly(!stayLoggedIn) (frontend/src/Auth.js:139). Unchecked, a localStorage flag plus a session cookie mark the login; on the next visit, flag set and cookie gone means the browser was closed, and the app signs out locally (frontend/src/supabaseClient.js:15, frontend/src/App.js:276).
- title: Forgot password | short: Reset | sub: email link
  body: After the CAPTCHA, resetPasswordForEmail sends a link back to the site origin (frontend/src/Auth.js:94). Arriving from it fires PASSWORD_RECOVERY, which opens Settings to set a new password (frontend/src/App.js:294).
- title: Credentials follow you | short: Credentials | sub: localStorage and Supabase
  body: The form starts from localStorage (frontend/src/App.js:199) and every change is written back (frontend/src/App.js:217). On sign-in the api_credentials row, if any, fills the form (frontend/src/App.js:304). Each analysis by a signed-in user writes changed credentials back to the row without waiting (frontend/src/App.js:686, frontend/src/App.js:586).
- title: Settings | short: Settings modal | sub: credentials, password, email
  body: Shown only when signed in (frontend/src/App.js:2285). It loads and saves the user's own api_credentials row (frontend/src/Settings.js:38, frontend/src/Settings.js:60), changes the password with updateUser after a 6-character and match check (frontend/src/Settings.js:119), and requests an email change that Supabase confirms by email (frontend/src/Settings.js:156).
- title: Delete the account | short: Delete | sub: type DELETE
  body: The confirm button stays disabled until the box reads DELETE (frontend/src/Settings.js:413). It calls DELETE /api/account with the session token (frontend/src/Settings.js:199). The server deletes saved_analyses and api_credentials rows, the user's shared_results rows, then the auth user (backend/supabase_client.py:392). On success it drops the token from its verification cache (backend/app.py:755); the browser signs out locally and reloads at / (frontend/src/Settings.js:204).
- title: Log out | short: Logout | sub: clear session and data
  body: handleLogout signs out, clears the session-only flag, forgets the stored-credentials snapshot, clears the loaded result and turns cheat-death off in the form (frontend/src/App.js:614).
- title: Read the terms | short: /terms, /privacy | sub: static pages
  body: TermsOfService and PrivacyPolicy are full routes (frontend/src/App.js:1402, frontend/src/App.js:1411), linked from the sign-up checkbox (frontend/src/Auth.js:241) and the landing footer (frontend/src/LandingPage.js:269).
```

## Diagram

```diagram
lane web Browser
lane sb Supabase
lane api Flask API
node modal lane=web color=process "Auth modal" "Turnstile first"
node settings lane=web color=process "Settings" "creds, pw, email"
node ls lane=web color=caution "localStorage" "fpx.wclCredentials"
node sbauth lane=sb color=safe "Supabase Auth" "sessions"
node creds lane=sb color=structural "api_credentials" "own row via RLS"
node del lane=api color=process "DELETE /api/account" "require_user"
node svc lane=api color=caution "delete_user_account" "service role"
edge modal -> sbauth "sign in"
edge settings -> creds "anon key"
edge settings -> ls "via form"
edge settings -> del "token"
edge del -> svc "user_id"
edge svc -> creds "delete"
edge svc -> sbauth "admin delete"
```

## Context map

```context
depends-on: [[auth]] — Supabase sessions, verify_token and require_user
depends-on: [[security]] — RLS on api_credentials, service-role use, token cache
depends-on: [[data-model]] — api_credentials, saved_analyses and shared_results
depends-on: [[backend-api-endpoints]] — DELETE /api/account
depends-on: [[frontend-pages-and-routing]] — modals, /terms and /privacy routes
depends-on: [[frontend]] — supabaseClient and api.js credential helpers
depends-on: [[backend]] — supabase_client.delete_user_account
provides: a signed-in identity for saves, cheat-death detection and share ownership
provides: WarcraftLogs credentials pre-filled on every analysis
provides: self-service account deletion
relied-on-by: [[feat-saved]] — every save needs a session
relied-on-by: [[feat-share]] — a signed-in share is recorded as created_by
relied-on-by: [[feat-analyze]] — credentials pre-fill and the cheat-death gate
```

## Reference

| Item {kind} | Where | Meaning |
|---|---|---|
| `DELETE /api/account` {route} | `backend/app.py:749` | delete the caller's data and login |
| `delete_user_account` {code} | `backend/supabase_client.py:384` | rows, shares, then auth user |
| `verify_token` {code} | `backend/auth.py:36` | asks Supabase `/auth/v1/user`; caches 60 s by token hash |
| `forget_token` {code} | `backend/auth.py:72` | drop a token from that cache |
| `fpx.wclCredentials` {localStorage} | `frontend/src/api.js:20` | Client ID and Secret, any visitor |
| `fp.sessionOnly` {localStorage} | `frontend/src/supabaseClient.js:12` | "Stay logged in" unchecked |
| `fp_session_alive` {cookie} | `frontend/src/supabaseClient.js:13` | session cookie paired with the flag |
| `api_credentials` {table} | `backend/migrations/001_shares_and_rls.sql:36` | client_id, client_secret per user; own-row policies |
| `SUPABASE_SERVICE_ROLE_KEY` {env} | `backend/supabase_client.py:29` | required for account deletion |
| `SUPABASE_URL`, `SUPABASE_KEY` {env} | `backend/auth.py:20` | used to verify tokens |
| `TURNSTILE_SITE_KEY` {const} | `frontend/src/Auth.js:6` | public Turnstile site key |
| `Settings` {component} | `frontend/src/Settings.js:6` | the Settings modal |
| `Auth` {component} | `frontend/src/Auth.js:8` | the sign-in modal |

## Invariants

- **MUST** the server identify the account to delete from the verified bearer token, never from the URL or body (`backend/app.py:750`, `backend/auth.py:88`). A test confirms an old `/api/delete-user-account/<id>` path is gone (`backend/test_api.py:157`).
- **MUST** account deletion remove `saved_analyses` and `api_credentials` rows and the auth user, and answer with an error if any of those fail (`backend/supabase_client.py:392`, `backend/supabase_client.py:407`). Share cleanup failures are logged but do not fail the call (`backend/supabase_client.py:400`).
- **NEVER** delete an account without the service-role key; the function refuses (`backend/supabase_client.py:388`).
- **MUST** a signed-in user reach only their own `api_credentials` row (`backend/migrations/001_shares_and_rls.sql:36`).
- **MUST** cheat-death detection run only for a request with a valid session (`backend/app.py:137`).

## Gotchas

- **Credentials outlive logout, not account deletion.** Logging out keeps `fpx.wclCredentials` on purpose: the browser remembers the key signed in or not (`frontend/src/api.js:16-20`, `frontend/src/App.js:614`). Deleting the account clears it (`frontend/src/Settings.js:206`, `frontend/src/accountDeletion.test.js`).
- **Saved credentials are protected by the database, not the app.** The browser writes `client_secret` to the row as plain text (`frontend/src/Settings.js:96`); row-level security keeps other accounts from reading it (`backend/migrations/001_shares_and_rls.sql:36-43`) and Supabase encrypts its storage at rest. Settings and the Privacy Policy say exactly that (`frontend/src/Settings.js:239-240`, `frontend/src/PrivacyPolicy.js:70`), and `frontend/src/credentialsCopy.test.js` fails if either promises more.
- **Privacy Policy retention matches the code.** It says saved analyses are kept for the chosen 7, 14 or 30 days and share links expire after 72 hours (`frontend/src/PrivacyPolicy.js:142-143`), as `save_analysis` clamps retention to 30 days (`backend/supabase_client.py:93`) and shares last `SHARE_TTL_HOURS` (`backend/supabase_client.py:34`); `frontend/src/credentialsCopy.test.js` checks the wording.
- **Deleted tokens can linger up to a minute elsewhere.** `forget_token` clears only the token used for the delete, in the process that handled it (`backend/auth.py:72`); the cache TTL is 60 s (`backend/auth.py:23`).

## Related

- [[auth]] — sessions and token verification in depth
- [[security]] — RLS, service role and secret handling
- [[data-model]] — the tables an account owns
- [[feat-saved]] — what an account unlocks
- [[feat-share]] — shares tied to an account
- [[feat-analyze]] — where stored credentials are used
- [[backend-api-endpoints]] — the account route
- [[frontend-pages-and-routing]] — modals and legal routes
- [[frontend]] — the React app
- [[backend]] — the Flask API
