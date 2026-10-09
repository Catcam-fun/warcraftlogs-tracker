---
id: data-model
title: Data Model
domain: data-model
status: documented
summary:
  - "Supabase holds four app tables: saved_analyses, shared_results, report_cache and api_credentials."
  - "Row-level security is on for all four; only api_credentials has policies, and only for the row's own user."
  - "The backend reaches saves, shares and the report cache with the service-role key, always scoped to a verified user id."
  - "Payloads are stored brotli-compressed as br64 text, with credentials stripped before anything is stored."
  - "Nothing lives forever: saves expire in 1-30 days, shares in 72 hours, and the report cache is trimmed to 200 MB."
tagline: The Supabase tables behind saves, share links, the shared report cache and stored credentials.
anchors:
  shares_table: backend/migrations/001_shares_and_rls.sql:13
  rls_on: backend/migrations/001_shares_and_rls.sql:23
  creds_policies: backend/migrations/001_shares_and_rls.sql:36
  report_cache_table: backend/migrations/002_report_cache.sql:12
  limits: backend/supabase_client.py:31
  service_key_choice: backend/supabase_client.py:38
  strip_secrets: backend/supabase_client.py:61
  pack: backend/supabase_client.py:68
  unpack: backend/supabase_client.py:73
  save_analysis: backend/supabase_client.py:89
  store_share: backend/supabase_client.py:222
  mem_fallback: backend/supabase_client.py:202
  cache_budget: backend/supabase_client.py:273
  evict: backend/supabase_client.py:395
  delete_account: backend/supabase_client.py:417
  creds_client_write: frontend/src/App.js:600
links:
  - backend
  - auth
  - security
  - deployment
  - feat-saved
  - feat-share
  - feat-account
flows:
  - share-path
  - request-path
invariants:
  - "MUST: every saved_analyses query filters on the verified user_id."
  - "MUST: configs pass through strip_secrets before they are stored or returned."
  - "MUST: retention_days is clamped to 1-30 before a save is written."
  - "NEVER: the browser reads saved_analyses, shared_results or report_cache directly; they have RLS on and no policies."
  - "NEVER: a report_cache failure breaks an analysis; every cache call is best-effort."
content_hash: sha256:30aea78428378699bdcf5e68a40d1e54df3cd31e27cef175973d8946a5d3db8d
---
# Data Model

## Summary

- Four Supabase tables back the site. Two are created by the migrations in `backend/migrations/` (`shared_results`, `report_cache`); two already existed and only get row-level security switched on there (`saved_analyses`, `api_credentials`), see `backend/migrations/001_shares_and_rls.sql:23`.
- The backend talks to Supabase through `backend/supabase_client.py`. It prefers the service-role key (`backend/supabase_client.py:38`) and scopes every per-user query by a user id that `backend/auth.py` has verified.
- The browser talks to exactly one table directly: `api_credentials`, through the public anon key and the per-user RLS policies at `backend/migrations/001_shares_and_rls.sql:36`.
- Stored analyses are compressed with brotli and base64 into a text column prefixed `br64:` (`backend/supabase_client.py:68`). Credentials are removed before storage by `strip_secrets` (`backend/supabase_client.py:61`).

## Diagram

The tables and what points at them. `auth.users` is Supabase's own user table.

```diagram
lane users Supabase Auth
node authusers lane=users color=structural "auth.users" "Supabase managed"
lane app App tables (RLS on)
node saved lane=app color=structural "saved_analyses" "max 5 per user"
node shares lane=app color=structural "shared_results" "72h links"
node creds lane=app color=caution "api_credentials" "own-row policies"
node rcache lane=app color=structural "report_cache" "LRU, 200 MB"
lane access Who reads it
node backend lane=access color=process "Flask backend" "service-role key"
node browser lane=access color=caution "Browser" "anon key + JWT"
edge saved -> authusers color=structural "user_id"
edge shares -> authusers color=structural "created_by"
edge creds -> authusers color=structural "user_id"
edge backend -> saved color=process "scoped CRUD"
edge backend -> shares color=process "insert, read"
edge backend -> rcache color=process "get, put"
edge browser -> creds color=caution "own row"
band structural "Supabase Postgres"
```

## Reference

Columns as defined by the migrations, or, for tables created outside this repo, as read and written by the code.

| Table / column {saved} | Type / source | Notes |
|---|---|---|
| `saved_analyses` {saved} | created outside the repo; RLS enabled at `001_shares_and_rls.sql:24` | Columns below come from the insert at `backend/supabase_client.py:106` |
| `id` {saved} | uuid4 string | Set by the backend (`backend/supabase_client.py:105`) |
| `user_id` {saved} | verified Supabase user id | Every query filters on it (`backend/supabase_client.py:96`, `:140`, `:167`) |
| `analysis_name`, `guild_name` {saved} | text, cut to 100 chars | `backend/supabase_client.py:109` |
| `analysis_data` {saved} | `br64:` text of `{data, config}` | Max 3 MB compressed (`MAX_SAVED_BYTES`, `backend/supabase_client.py:32`) |
| `retention_days`, `expires_at` {saved} | int 1-30; timestamp | Clamped at `backend/supabase_client.py:93` |
| `size_bytes`, `created_at` {saved} | int; timestamp | Listing returns these without the payload (`backend/supabase_client.py:135`) |
| `shared_results` {share} | `001_shares_and_rls.sql:13` | No policies; backend only |
| `id` {share} | text PK | `secrets.token_urlsafe(9)` from `backend/app.py:735` |
| `payload`, `size_bytes` {share} | `br64:` text; int | Max 2 MB compressed (`backend/supabase_client.py:33`) |
| `created_by` {share} | uuid FK `auth.users`, `on delete set null` | Only set when the sharer was signed in (`backend/app.py:734`) |
| `created_at`, `expires_at` {share} | timestamps; index on `expires_at` | `expires_at` = now + 72h (`SHARE_TTL_HOURS`, `backend/supabase_client.py:34`) |
| `report_cache` {cache} | `002_report_cache.sql:12` | No policies; backend only |
| `key` {cache} | text PK, `v2:<namespace>:<repr(key)>` | Built in `backend/cache.py:61` |
| `payload`, `size_bytes` {cache} | `br64:` text of tagged JSON; int | Rows over 4 MB are skipped (`backend/supabase_client.py:274`) |
| `created_at`, `last_used_at` {cache} | timestamps; index on `last_used_at` | `last_used_at` bumped on every hit (`backend/supabase_client.py:367`) |
| `api_credentials` {creds} | created outside the repo; RLS + 4 policies at `001_shares_and_rls.sql:36` | Read and written by the browser |
| `id`, `user_id` {creds} | ids | Policies require `auth.uid() = user_id` |
| `client_id`, `client_secret`, `last_used` {creds} | text; timestamp | Written by `frontend/src/App.js:603` and `frontend/src/Settings.js:81` |

## How it works

Each table has its own write path and its own way of getting rid of old rows.

```steps
- title: Saving an analysis | short: Save | sub: 5 per user, 1-30 days
  body: save_analysis (backend/supabase_client.py:89) clamps retention_days to 1-30, deletes this user's expired rows, refuses a sixth save with code "limit", packs {data, config} after strip_secrets, refuses blobs over 3 MB with code "too_large", then inserts with expires_at = now + retention_days.
  gotcha: Expired saves are purged only when that same user saves, lists or loads (backend/supabase_client.py:85); load_analysis purges first (backend/supabase_client.py:148), so an expired row is never returned, but it stays in the table until that user comes back.
- title: Loading a save | short: Load | sub: owner only, old rows too
  body: load_analysis filters on id and user_id together, unpacks the payload and strips secrets again on the way out. Rows written by older versions held the bare analysis; those are wrapped as {data, config None} (backend/supabase_client.py:156).
- title: Creating a share | short: Share | sub: 72h, memory fallback
  body: store_share (backend/supabase_client.py:222) packs and size-checks the payload, deletes every expired share in the table, and inserts the new row. If the insert fails, for example because migration 001 was never run, the blob goes into an in-process dict instead and the response carries ephemeral true (backend/supabase_client.py:241).
  gotcha: Memory shares live only in the process that created them. They vanish on restart and are not visible to a second gunicorn worker.
- title: Reading a share | short: Read share | sub: memory first, then table
  body: get_share checks the in-memory dict first, then the table with expires_at greater than now (backend/supabase_client.py:250). Expired rows are never served even before they are purged.
- title: Report cache write | short: Cache put | sub: background, best-effort
  body: SharedReportCache.set writes memory and submits cache_put to a 4-thread background pool (backend/cache.py:79). cache_put encodes dict keys, tuples and sets with __d, __t, __s tags (backend/supabase_client.py:281), packs, upserts, and every 20th write runs evict_report_cache.
  gotcha: Any read or write error disables the shared cache for 5 minutes (backend/supabase_client.py:317), so a missing table costs nothing but a log line.
- title: Report cache eviction | short: Evict | sub: LRU under 200 MB
  body: evict_report_cache (backend/supabase_client.py:395) reads every key and size ordered by last_used_at newest first, keeps a running total, and deletes in batches of 100 every row past the 200 MB budget.
- title: Account deletion | short: Delete account | sub: rows, then auth user
  body: delete_user_account (backend/supabase_client.py:417) deletes the user's saved_analyses and api_credentials, then their shares by created_by, then the auth user through the admin API. It refuses to run without the service-role key.
```

## Invariants

- **MUST** every `saved_analyses` query filter on the verified `user_id` (`backend/supabase_client.py:96`, `:140`, `:167`, `:178`); the service-role key bypasses RLS, so this filter is the only thing keeping users apart.
- **MUST** configs pass through `strip_secrets` before they are stored and again when they are returned (`backend/supabase_client.py:101`, `:154`, `:214`, `:250`); a stored WarcraftLogs secret would leak through every share.
- **MUST** `retention_days` be clamped to 1-30 before a save is written (`backend/supabase_client.py:93`).
- **NEVER** the browser reads `saved_analyses`, `shared_results` or `report_cache` directly: RLS is on and no anon or authenticated policies exist (`backend/migrations/001_shares_and_rls.sql:27`, `backend/migrations/002_report_cache.sql:21`).
- **NEVER** a `report_cache` failure breaks an analysis; every cache call catches and treats errors as a miss (`backend/supabase_client.py:354`, `:343`).

## Gotchas

- **Two tables have no CREATE in the repo**: `saved_analyses` and `api_credentials` only appear in `ALTER TABLE ... ENABLE ROW LEVEL SECURITY` (`backend/migrations/001_shares_and_rls.sql:24`). Their full schema lives only in the Supabase project; the columns above are what the code uses.
- **Service-role fallback to the anon key**: if `SUPABASE_SERVICE_ROLE_KEY` is unset the client is built with `SUPABASE_KEY` (`backend/supabase_client.py:38`). RLS then blocks saves and shares, which surface as generic errors or the memory share fallback rather than a clear "not configured".
- **Eviction reads all rows in one select**: `evict_report_cache` does not page its `select` (`backend/supabase_client.py:399`). If the PostgREST row cap is lower than the table's row count, the oldest rows never enter the running total and are never evicted.
- **Plain JSON rows still load**: `unpack` accepts text without the `br64:` prefix (`backend/supabase_client.py:78`), so rows from older versions keep working.
- **Bumping CACHE_VERSION orphans rows**: keys start with `CACHE_VERSION` (`backend/cache.py:88`), so a bump leaves old rows unread until LRU eviction removes them.
- **Credentials are stored as entered**: `api_credentials.client_secret` holds the WarcraftLogs secret as text, protected by RLS only (`frontend/src/App.js:607`).

## Glossary

- **br64**: the storage format for payloads: the string `br64:` followed by base64 of brotli-compressed compact JSON.
- **Service-role key**: the Supabase key that bypasses row-level security. Only the backend holds it.
- **RLS**: Postgres row-level security. With RLS on and no policy, the anon and authenticated roles can read nothing.
- **Memory share**: a share kept in the backend process's dict when the `shared_results` insert fails; marked `ephemeral`.

## Related

- [[backend]] — the Flask routes that call these storage functions
- [[auth]] — where the verified `user_id` that scopes every query comes from
- [[security]] — RLS, secret stripping and the trust boundaries around this data
- [[deployment]] — migrations are applied by hand in the Supabase dashboard
- [[feat-saved]] — the user-facing saved analyses built on `saved_analyses`
- [[feat-share]] — share links built on `shared_results`
- [[feat-account]] — account deletion and stored credentials
