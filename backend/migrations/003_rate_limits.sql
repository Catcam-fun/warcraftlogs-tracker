-- 003_rate_limits.sql
-- Run once in the Supabase dashboard: SQL Editor -> New query -> paste -> Run.
-- Safe to re-run.
--
-- Hourly limits on analyses, saves and share links, counted in one place.
-- On AWS Lambda each concurrent request can run on a separate copy of the
-- server, so limits kept in each copy's memory are easy to get around.
-- Clients are stored as a SHA-256 hash of their IP address, never the
-- address itself. Until this exists the backend counts in memory only.

create table if not exists public.rate_limit_hits (
  id      bigserial   primary key,
  bucket  text        not null,
  client  text        not null,
  hit_at  timestamptz not null default now()
);
create index if not exists rate_limit_hits_lookup_idx on public.rate_limit_hits (bucket, client, hit_at);
create index if not exists rate_limit_hits_age_idx on public.rate_limit_hits (hit_at);

-- No anon or authenticated policies on purpose: only the backend uses it.
alter table public.rate_limit_hits enable row level security;

-- Counts one request and returns whether it's within p_max per window.
create or replace function public.rate_limit_hit(p_bucket text, p_client text, p_max int, p_window_seconds int)
returns boolean
language plpgsql
security definer
set search_path = public
as $$
declare
  recent int;
begin
  -- One request per client and bucket at a time, so two at once can't both
  -- squeeze in under the limit.
  perform pg_advisory_xact_lock(hashtext(p_bucket || ':' || p_client));
  delete from rate_limit_hits
   where bucket = p_bucket and client = p_client
     and hit_at < now() - make_interval(secs => p_window_seconds);
  select count(*) into recent from rate_limit_hits where bucket = p_bucket and client = p_client;
  if recent >= p_max then
    return false;
  end if;
  insert into rate_limit_hits (bucket, client) values (p_bucket, p_client);
  -- Now and then, clear out clients who haven't been back for a day.
  if random() < 0.01 then
    delete from rate_limit_hits where hit_at < now() - interval '1 day';
  end if;
  return true;
end;
$$;

revoke all on function public.rate_limit_hit(text, text, int, int) from public, anon, authenticated;
grant execute on function public.rate_limit_hit(text, text, int, int) to service_role;
