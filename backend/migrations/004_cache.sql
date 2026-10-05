-- Phase 11: a 2-month cache, shared by all profiles, so the same company site is read only once.
-- Run this once in Supabase Studio (SQL Editor). Safe to run again.
-- It caches only facts: pages and what the AI read out of them (company facts, people, evidence quotes).
-- It never caches anything made for a freelancer: judgments, reports, demo specs and emails stay per profile.
-- Anything older than 60 days is ignored and deleted by the worker (once a day), so the data stays fresh.
begin;

create table if not exists page_cache (
  url text primary key,
  kind text,
  markdown text,
  raw_html text,                       -- home page only
  cached_at timestamptz not null default now()
);

create table if not exists extract_cache (
  domain text not null,
  sig text not null,                   -- the AI signals it looked for. Another profile with other signals gets its own row
  payload jsonb not null,              -- what the AI read from the pages: facts, people, evidence quotes
  cached_at timestamptz not null default now(),
  primary key (domain, sig)
);

create index if not exists page_cache_age_idx on page_cache (cached_at);
create index if not exists extract_cache_age_idx on extract_cache (cached_at);

-- start with the pages you already have (only the good ones, only the last 60 days)
insert into page_cache (url, kind, markdown, raw_html, cached_at)
select distinct on (url) url, kind, markdown, raw_html, fetched_at
from pages
where fetched_at > now() - interval '60 days' and length(trim(coalesce(markdown, ''))) >= 100
order by url, fetched_at desc
on conflict (url) do nothing;

commit;
