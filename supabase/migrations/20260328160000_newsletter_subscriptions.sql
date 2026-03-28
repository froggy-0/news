create extension if not exists pgcrypto;

create table if not exists public.subscriptions (
  id uuid primary key default gen_random_uuid(),
  email text not null,
  email_normalized text not null,
  newsletter text not null,
  status text not null check (status in ('pending', 'active', 'unsubscribed', 'bounced')),
  subscribed_at timestamptz,
  unsubscribed_at timestamptz,
  bounced_at timestamptz,
  status_reason text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create unique index if not exists subscriptions_newsletter_email_normalized_idx
  on public.subscriptions (newsletter, email_normalized);

create index if not exists subscriptions_status_idx
  on public.subscriptions (newsletter, status);

create table if not exists public.subscription_tokens (
  id uuid primary key default gen_random_uuid(),
  subscriber_id uuid not null references public.subscriptions(id) on delete cascade,
  token_type text not null check (token_type in ('confirm_subscription')),
  token_hash text not null unique,
  expires_at timestamptz not null,
  consumed_at timestamptz,
  created_at timestamptz not null default now()
);

create index if not exists subscription_tokens_lookup_idx
  on public.subscription_tokens (token_type, token_hash);

create table if not exists public.mail_events (
  id uuid primary key default gen_random_uuid(),
  subscriber_id uuid references public.subscriptions(id) on delete set null,
  email text not null,
  mail_type text not null check (mail_type in ('newsletter', 'confirm_subscription')),
  status text not null check (status in ('queued', 'sent', 'failed')),
  provider text not null default 'gmail',
  error_code text,
  created_at timestamptz not null default now()
);

create or replace function public.set_updated_at()
returns trigger
language plpgsql
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

drop trigger if exists subscriptions_set_updated_at on public.subscriptions;
create trigger subscriptions_set_updated_at
before update on public.subscriptions
for each row
execute function public.set_updated_at();

alter table public.subscriptions enable row level security;
alter table public.subscription_tokens enable row level security;
alter table public.mail_events enable row level security;
