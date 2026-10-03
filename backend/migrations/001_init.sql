create extension if not exists pgcrypto;

-- one row only
create table settings (
  id int primary key default 1 check (id = 1),
  sender_name text,
  sender_title text,
  signature text,
  postal_address text,                 -- needed for US/UK email rules
  gmail_address text,
  gmail_refresh_token_enc text,        -- Fernet-encrypted
  daily_send_cap int default 20,
  warmup_enabled boolean default true,
  send_window_start time default '09:00',
  send_window_end time default '16:30',
  min_gap_seconds int default 180,
  max_gap_seconds int default 540,
  auto_send boolean default false,
  followup_days int[] default '{3,4,7}', -- business days after previous step
  updated_at timestamptz default now()
);
insert into settings (id) values (1) on conflict do nothing;

create table profiles (
  id uuid primary key default gen_random_uuid(),
  file_name text,
  storage_path text,
  raw_text text,
  parsed jsonb,
  is_active boolean default true,
  created_at timestamptz default now()
);

create table offer_rows (
  id uuid primary key default gen_random_uuid(),
  profile_id uuid references profiles on delete cascade,
  service text not null,
  problems jsonb default '[]',
  proof jsonb default '[]',
  ideal_customer jsonb default '{}',
  active boolean default true,
  created_at timestamptz default now()
);

create table signals (
  id uuid primary key default gen_random_uuid(),
  offer_row_id uuid references offer_rows on delete cascade,
  name text not null,
  description text,
  detector_type text check (detector_type in ('phrase','tech_absent','tech_present','hiring_role','llm')),
  config jsonb default '{}',
  weight int default 1,
  active boolean default true
);

create table campaigns (
  id uuid primary key default gen_random_uuid(),
  name text not null,
  profile_id uuid references profiles,
  filters jsonb not null,
  status text default 'draft',
  created_at timestamptz default now()
);

create table runs (
  id uuid primary key default gen_random_uuid(),
  campaign_id uuid references campaigns on delete cascade,
  status text default 'queued',        -- queued|running|paused|done|failed|cancelled
  stage text,
  counters jsonb default '{}',
  credits_used int default 0,
  llm_calls int default 0,
  llm_input_tokens bigint default 0,
  llm_output_tokens bigint default 0,
  error text,
  started_at timestamptz,
  finished_at timestamptz,
  created_at timestamptz default now()
);

create table search_queries (
  id uuid primary key default gen_random_uuid(),
  run_id uuid references runs on delete cascade,
  query text not null,
  query_hash text unique,
  results jsonb,
  result_count int,
  credits int,
  created_at timestamptz default now()
);

create table companies (
  id uuid primary key default gen_random_uuid(),
  domain text unique not null,
  name text,
  country text,
  size_estimate int,
  size_bucket text,                    -- '1 - 10' | '11 - 50' | '51+' | 'unknown'
  source text,
  source_ref text,
  run_id uuid references runs,
  status text default 'new',           -- new|auditing|audited|failed|filtered_out|no_contact|judged|qualified|maybe|rejected
  fail_reason text,
  tech jsonb default '{}',
  facts jsonb default '{}',
  keyword_hits text[],
  first_seen timestamptz default now(),
  last_audited_at timestamptz
);

create table pages (
  id uuid primary key default gen_random_uuid(),
  company_id uuid references companies on delete cascade,
  url text not null,
  kind text,                           -- home|about|contact|careers|services|other
  markdown text,
  raw_html text,                       -- homepage only, for tech fingerprints
  fetched_at timestamptz default now(),
  unique (company_id, url)
);

create table evidence (
  id uuid primary key default gen_random_uuid(),
  company_id uuid references companies on delete cascade,
  signal_id uuid references signals,
  kind text,                           -- manual_process|hiring|tech|other
  quote text not null,
  url text not null,
  verified boolean default false,
  created_at timestamptz default now()
);

create table people (
  id uuid primary key default gen_random_uuid(),
  company_id uuid references companies on delete cascade,
  name text,
  title text,
  seniority text,
  source text,                         -- website|companies_house
  source_url text,
  email text,
  email_kind text,                     -- personal|generic
  email_source text,                   -- page URL where the email was published
  mx_ok boolean,
  selected boolean default false,
  created_at timestamptz default now()
);

create table judgments (
  id uuid primary key default gen_random_uuid(),
  company_id uuid references companies on delete cascade,
  run_id uuid references runs,
  offer_row_id uuid references offer_rows,
  fit_score int,
  problem text,
  fix text,
  value_estimate text,
  confidence text,
  evidence_ids uuid[],
  disqualifiers jsonb,
  model text,
  raw jsonb,
  created_at timestamptz default now()
);

create table leads (
  id uuid primary key default gen_random_uuid(),
  company_id uuid unique references companies on delete cascade,
  person_id uuid references people,
  campaign_id uuid references campaigns,
  judgment_id uuid references judgments,
  stage text default 'new',            -- new|ready|in_sequence|replied|meeting|won|lost|bounced|unsubscribed
  score int,
  timezone text,
  notes text,
  created_at timestamptz default now(),
  updated_at timestamptz default now()
);

create table assets (
  id uuid primary key default gen_random_uuid(),
  lead_id uuid references leads on delete cascade,
  kind text,                           -- report|demo_spec
  content_md text,
  public_token text unique,
  demo_url text,
  created_at timestamptz default now()
);

create table messages (
  id uuid primary key default gen_random_uuid(),
  lead_id uuid references leads on delete cascade,
  step int not null,                   -- 0 = main email, 1..3 = follow-ups
  subject text,
  body text,
  evidence_ids uuid[],
  status text default 'draft',         -- draft|approved|scheduled|sending|sent|cancelled|failed
  scheduled_at timestamptz,
  sent_at timestamptz,
  gmail_message_id text,
  gmail_thread_id text,
  rfc_message_id text,
  error text,
  created_at timestamptz default now(),
  unique (lead_id, step)
);

create table replies (
  id uuid primary key default gen_random_uuid(),
  lead_id uuid references leads on delete cascade,
  gmail_message_id text unique,
  from_email text,
  received_at timestamptz,
  snippet text,
  body text,
  classification text,                 -- interested|not_now|not_interested|unsubscribe|out_of_office|other
  created_at timestamptz default now()
);

create table do_not_contact (
  id uuid primary key default gen_random_uuid(),
  value text unique not null,          -- email or domain, lowercase
  kind text,                           -- email|domain
  reason text,
  created_at timestamptz default now()
);

create table events (
  id bigserial primary key,
  run_id uuid,
  lead_id uuid,
  level text,                          -- info|warn|error
  stage text,
  message text,
  data jsonb,
  created_at timestamptz default now()
);

create table usage_daily (
  day date primary key,
  firecrawl_credits int default 0,
  llm_calls int default 0,
  llm_input_tokens bigint default 0,
  llm_output_tokens bigint default 0,
  emails_sent int default 0
);

-- atomic counter (supabase-py cannot increment safely)
create or replace function add_usage(p_credits int, p_calls int, p_in bigint, p_out bigint, p_emails int)
returns void language sql as $$
  insert into usage_daily (day, firecrawl_credits, llm_calls, llm_input_tokens, llm_output_tokens, emails_sent)
  values (current_date, p_credits, p_calls, p_in, p_out, p_emails)
  on conflict (day) do update set
    firecrawl_credits = usage_daily.firecrawl_credits + excluded.firecrawl_credits,
    llm_calls = usage_daily.llm_calls + excluded.llm_calls,
    llm_input_tokens = usage_daily.llm_input_tokens + excluded.llm_input_tokens,
    llm_output_tokens = usage_daily.llm_output_tokens + excluded.llm_output_tokens,
    emails_sent = usage_daily.emails_sent + excluded.emails_sent;
$$;

create index on companies (status);
create index on companies (run_id);
create index on leads (stage);
create index on messages (status, scheduled_at);
create index on events (run_id, created_at desc);
