-- 001_shares_and_rls.sql
-- Run once in the Supabase dashboard: SQL Editor -> New query -> paste -> Run.
-- Safe to re-run.
--
-- 1. Creates `shared_results`, where share links now live (72h, compressed),
--    so they survive backend restarts.
-- 2. Turns on row-level security so the public anon key that ships inside the
--    website can only touch a user's *own* API credentials, and can't read
--    saved reports or shares directly at all. The backend reaches those
--    tables with the service-role key after verifying who is asking, so
--    SUPABASE_SERVICE_ROLE_KEY must be set on the backend host.

create table if not exists public.shared_results (
  id          text primary key,
  payload     text        not null,
  size_bytes  integer     not null default 0,
  created_by  uuid        references auth.users (id) on delete set null,
  created_at  timestamptz not null default now(),
  expires_at  timestamptz not null
);
create index if not exists shared_results_expires_at_idx on public.shared_results (expires_at);

alter table public.shared_results  enable row level security;
alter table public.saved_analyses  enable row level security;
alter table public.api_credentials enable row level security;

-- saved_analyses / shared_results: no anon or authenticated policies on
-- purpose; only the backend (service role) reads and writes them.

-- api_credentials: the website reads and writes these directly, so each
-- signed-in user gets access to their own row and nothing else.
drop policy if exists "fp own credentials select" on public.api_credentials;
drop policy if exists "fp own credentials insert" on public.api_credentials;
drop policy if exists "fp own credentials update" on public.api_credentials;
drop policy if exists "fp own credentials delete" on public.api_credentials;
create policy "fp own credentials select" on public.api_credentials
  for select to authenticated using (auth.uid() = user_id);
create policy "fp own credentials insert" on public.api_credentials
  for insert to authenticated with check (auth.uid() = user_id);
create policy "fp own credentials update" on public.api_credentials
  for update to authenticated using (auth.uid() = user_id) with check (auth.uid() = user_id);
create policy "fp own credentials delete" on public.api_credentials
  for delete to authenticated using (auth.uid() = user_id);

-- Optional check afterwards: every row should say rowsecurity = true.
-- select tablename, rowsecurity from pg_tables
--  where schemaname = 'public'
--    and tablename in ('shared_results', 'saved_analyses', 'api_credentials');
