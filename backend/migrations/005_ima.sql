-- Phase 12: IMA profiles (influencer marketing agency). Run this once in Supabase Studio (SQL Editor). Safe to run again.
-- Every profile you have now stays a freelancer profile. An IMA profile hunts brands that pay YouTube creators.
-- It stops at "qualified": no judge, no report, no demo, no emails. Each qualified brand is one row in brand_leads.
begin;

-- ---- profile type --------------------------------------------------------
alter table profiles add column if not exists kind text not null default 'freelancer';
alter table profiles drop constraint if exists profiles_kind_check;
alter table profiles add constraint profiles_kind_check check (kind in ('freelancer', 'ima'));

-- ---- where a brand was found (the page of the search result). Only IMA runs fill it
alter table companies add column if not exists source_url text;

-- ---- the lead list of an IMA profile: one row per brand --------------------
create table if not exists brand_leads (
  id uuid primary key default gen_random_uuid(),
  company_id uuid not null unique references companies on delete cascade,   -- deleting the company (or the profile) deletes its row
  profile_id uuid not null references profiles on delete cascade,
  campaign_id uuid references campaigns on delete set null,

  -- the columns of the lead sheet
  website_url text,          -- the page where the brand was found
  brand text,                -- brand name
  brand_url text,            -- the brand's own site
  category text,             -- what the brand sells
  sponsorships text,         -- the proof: quotes from the brand's site that show it pays creators, each with its page
  creators text,             -- which creator-spend signals were found (creator program, affiliate program, ...)
  emails text,               -- every email published on the brand's site, the contact's first. Empty when none
  employees text,            -- company size when the site says it
  type text not null default 'do manually' check (type in ('good to go', 'do manually')),   -- 'good to go' = an email was found

  -- extras that come with it
  country text,
  contact_name text,
  contact_title text,
  email_source text,         -- the page where the first email was published
  proof_count int not null default 0,   -- how many verified quotes back this brand
  keyword_hits text[],
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists brand_leads_profile_type_idx on brand_leads (profile_id, type);
create index if not exists brand_leads_profile_proof_idx on brand_leads (profile_id, proof_count desc);

-- delete_profile() needs no change: brand_leads goes with the companies and the profile (on delete cascade)

commit;
