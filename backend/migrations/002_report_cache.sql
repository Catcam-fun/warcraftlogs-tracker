-- 002_report_cache.sql
-- Run once in the Supabase dashboard: SQL Editor -> New query -> paste -> Run.
-- Safe to re-run.
--
-- A shared cache of WarcraftLogs data for finished reports (fights, deaths,
-- defensive events, killing blows). A finished report never changes, so once
-- anyone has analyzed it, later analyses of it cost 0 WarcraftLogs API points.
-- Payloads are compressed; the backend keeps the table under a size budget by
-- deleting the least recently used rows. Until this table exists the backend
-- simply skips the shared cache.

create table if not exists public.report_cache (
  key          text primary key,
  payload      text        not null,
  size_bytes   integer     not null default 0,
  created_at   timestamptz not null default now(),
  last_used_at timestamptz not null default now()
);
create index if not exists report_cache_last_used_idx on public.report_cache (last_used_at);

-- No anon or authenticated policies on purpose: only the backend (service
-- role) reads and writes this table.
alter table public.report_cache enable row level security;
