-- Anchor & Delta — Supabase Schema
-- Timezone: Australia/Sydney
-- All primary keys: uuid, default gen_random_uuid()

create extension if not exists "pgcrypto";

-- 1. cards
create table if not exists cards (
  id uuid primary key default gen_random_uuid(),
  domain text not null,
  umbrella_title text not null,
  anchor_text text not null,
  is_archived boolean not null default false,
  created_at timestamptz not null default now(),
  last_delta_at timestamptz not null default now()
);

create index if not exists idx_cards_domain on cards(domain);
create index if not exists idx_cards_is_archived on cards(is_archived);
create index if not exists idx_cards_last_delta_at on cards(last_delta_at desc);

-- 2. delta_events (append-only, never update or delete)
create table if not exists delta_events (
  id uuid primary key default gen_random_uuid(),
  card_id uuid not null references cards(id) on delete cascade,
  event_date date not null,
  headline text not null,
  what_happened text not null,
  dialogue jsonb not null default '[]'::jsonb,
  tldr text,
  created_at timestamptz not null default now()
);

create index if not exists idx_delta_events_card_id on delta_events(card_id);
create index if not exists idx_delta_events_event_date on delta_events(event_date desc);

-- 3. transmissions (one per card, upsert only — never insert a second row)
create table if not exists transmissions (
  id uuid primary key default gen_random_uuid(),
  card_id uuid not null unique references cards(id) on delete cascade,
  chain_latex text not null,
  nodes_markdown text not null,
  updated_at timestamptz not null default now()
);

create index if not exists idx_transmissions_card_id on transmissions(card_id);

-- 4. processed_articles (deduplication log — hashes only)
create table if not exists processed_articles (
  id uuid primary key default gen_random_uuid(),
  url_hash text not null,
  headline_hash text not null,
  source_url text not null,
  processed_at timestamptz not null default now()
);

create index if not exists idx_processed_articles_url_hash on processed_articles(url_hash);
create index if not exists idx_processed_articles_headline_hash on processed_articles(headline_hash);

-- 5. noise_log (pipeline transparency — surfaced in UI)
create table if not exists noise_log (
  id uuid primary key default gen_random_uuid(),
  headline text not null,
  source_url text not null,
  gate_failed text not null,
  reason text not null,
  rerouted_to text default null,
  logged_at timestamptz not null default now()
);

create index if not exists idx_noise_log_logged_at on noise_log(logged_at desc);
