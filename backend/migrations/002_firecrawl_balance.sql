-- Phase 8: starting Firecrawl balance, entered in Settings. Used for "credits left".
alter table settings add column if not exists firecrawl_start_balance int;
