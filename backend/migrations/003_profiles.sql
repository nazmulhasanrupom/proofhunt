-- Phase 10: many profiles. One CV = one profile. Everything you hunt, find and send belongs to one profile.
-- Run this once in Supabase Studio (SQL Editor). Safe to run on a database that already has data:
-- all existing rows are given to the profile they came from, so nothing is lost.
-- If one statement fails, nothing is changed (it runs as one transaction).
begin;

-- ---- names ---------------------------------------------------------------
alter table profiles add column if not exists name text;

-- old profiles get the name of their CV file. Same name twice: "CV", "CV (2)", ...
with base as (
  select id, created_at,
         coalesce(nullif(regexp_replace(coalesce(file_name, ''), '\.[^.]*$', ''), ''), 'Profile') as b
  from profiles where name is null
), numbered as (
  select id, b, row_number() over (partition by lower(b) order by created_at, id) as n from base
)
update profiles p
set name = case when numbered.n = 1 then numbered.b else numbered.b || ' (' || numbered.n || ')' end
from numbered where p.id = numbered.id;

alter table profiles alter column name set not null;
create unique index if not exists profiles_name_key on profiles (lower(name));
comment on column profiles.is_active is 'Not used any more. The browser remembers which profile you picked.';

-- ---- every table that holds work gets its profile ------------------------
alter table runs           add column if not exists profile_id uuid references profiles on delete cascade;
alter table companies      add column if not exists profile_id uuid references profiles on delete cascade;
alter table leads          add column if not exists profile_id uuid references profiles on delete cascade;
alter table messages       add column if not exists profile_id uuid references profiles on delete cascade;
alter table replies        add column if not exists profile_id uuid references profiles on delete cascade;
alter table search_queries add column if not exists profile_id uuid references profiles on delete cascade;
alter table events         add column if not exists profile_id uuid references profiles on delete cascade;  -- null = a message for the whole app

-- fill from what is already linked: campaign -> run -> company -> lead -> message / reply
update runs r set profile_id = c.profile_id from campaigns c where r.campaign_id = c.id and r.profile_id is null;
update companies co set profile_id = r.profile_id from runs r where co.run_id = r.id and co.profile_id is null;
-- the test lead has no run: it goes to the newest profile
update companies set profile_id = (select id from profiles order by is_active desc, created_at desc limit 1) where profile_id is null;
delete from companies where profile_id is null and domain = 'test-lead.invalid';  -- only when no profile exists at all
update leads l set profile_id = co.profile_id from companies co where l.company_id = co.id and l.profile_id is null;
update messages m set profile_id = l.profile_id from leads l where m.lead_id = l.id and m.profile_id is null;
update replies x set profile_id = l.profile_id from leads l where x.lead_id = l.id and x.profile_id is null;
update search_queries s set profile_id = r.profile_id from runs r where s.run_id = r.id and s.profile_id is null;
update search_queries set profile_id = (select id from profiles order by is_active desc, created_at desc limit 1) where profile_id is null;
update events e set profile_id = r.profile_id from runs r where e.run_id = r.id and e.profile_id is null;
update events e set profile_id = l.profile_id from leads l where e.lead_id = l.id and e.profile_id is null;

alter table runs           alter column profile_id set not null;
alter table companies      alter column profile_id set not null;
alter table leads          alter column profile_id set not null;
alter table messages       alter column profile_id set not null;
alter table replies        alter column profile_id set not null;
alter table search_queries alter column profile_id set not null;

-- ---- the same site or search can be used once PER PROFILE, not once in total
alter table companies drop constraint if exists companies_domain_key;
alter table companies drop constraint if exists companies_profile_domain_key;
alter table companies add constraint companies_profile_domain_key unique (profile_id, domain);
alter table search_queries drop constraint if exists search_queries_query_hash_key;
alter table search_queries drop constraint if exists search_queries_profile_hash_key;
alter table search_queries add constraint search_queries_profile_hash_key unique (profile_id, query_hash);

create index if not exists runs_profile_idx on runs (profile_id, created_at desc);
create index if not exists companies_profile_status_idx on companies (profile_id, status);
create index if not exists leads_profile_stage_idx on leads (profile_id, stage);
create index if not exists messages_profile_status_idx on messages (profile_id, status);
create index if not exists replies_profile_idx on replies (profile_id, received_at desc);
create index if not exists events_profile_idx on events (profile_id, id);
create index if not exists pages_url_idx on pages (url);  -- a page saved for one profile is reused by another

-- ---- delete a profile and everything in it (in an order the foreign keys accept)
create or replace function delete_profile(p_id uuid) returns void language plpgsql as $$
begin
  delete from leads where profile_id = p_id;           -- also its assets, messages and replies
  delete from companies where profile_id = p_id;       -- also pages, evidence, people, judgments
  delete from events where profile_id = p_id;
  delete from search_queries where profile_id = p_id;
  delete from runs where profile_id = p_id;
  delete from campaigns where profile_id = p_id;
  delete from offer_rows where profile_id = p_id;      -- also signals
  delete from profiles where id = p_id;
end $$;

commit;
