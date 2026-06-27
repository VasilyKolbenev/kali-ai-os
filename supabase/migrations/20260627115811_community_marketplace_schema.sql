-- KALI Community marketplace — schema (§4 of the marketplace design spec).
--
-- Source of truth:
--   docs/superpowers/specs/2026-06-25-kali-community-marketplace-design.md §4.
--
-- This migration creates the 7 normalized tables that REPLACE the flat
-- `packages` prototype (kernel/catalog/client.py, 2026-04-13). It defines
-- tables, enums, indexes, the updated_at trigger for `skills`, and the
-- `trending_skills` view. Row-Level Security policies live in the companion
-- migration (20260627115812_community_marketplace_rls.sql).
--
-- All objects live in the `public` schema (the Data-API-exposed schema), so
-- RLS is mandatory on every table — enabled in the RLS migration.

-- ---------------------------------------------------------------------------
-- Extensions
-- ---------------------------------------------------------------------------
-- gen_random_uuid() ships with pgcrypto; on Supabase it is available by
-- default, but we declare the dependency explicitly for portability.
create extension if not exists pgcrypto with schema extensions;

-- ---------------------------------------------------------------------------
-- Enums (§4: status lifecycles + flag target type + skill format)
-- ---------------------------------------------------------------------------
-- skills.status: pending -> approved (auto on safe-gate pass) | flagged | removed
create type public.skill_status as enum ('pending', 'approved', 'flagged', 'removed');

-- comments.status: moderation lifecycle for a comment.
create type public.comment_status as enum ('pending', 'approved', 'flagged', 'removed');

-- skills.format: the on-disk skill descriptor format.
create type public.skill_format as enum ('skill.yaml', 'SKILL.md');

-- flags.target_type: what a moderation report points at.
create type public.flag_target_type as enum ('skill', 'comment');

-- ---------------------------------------------------------------------------
-- creators (§4) — id = auth uid; an optional lightweight KALI account.
-- ---------------------------------------------------------------------------
create table public.creators (
    -- PK == auth.users.id: a creator row is the public profile for an account.
    id uuid primary key references auth.users (id) on delete cascade,
    handle text not null unique,
    -- self-declared social links (TikTok/IG/YT/Telegram/site) — display only,
    -- never OAuth tokens (§2 / §7 anti-pivot).
    socials jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now()
);

comment on table public.creators is
    'KALI account profile (handle + opt-in self-declared socials). id == auth.users.id.';
comment on column public.creators.socials is
    'Self-declared display links only (no tokens, no platform API).';

-- ---------------------------------------------------------------------------
-- skills (§4) — the catalog entry for a published voice-built skill/agent.
-- ---------------------------------------------------------------------------
create table public.skills (
    id uuid primary key default gen_random_uuid(),
    slug text not null unique,
    name text not null,
    description text,
    category text,
    creator_id uuid not null references public.creators (id) on delete cascade,
    bundle_path text,                       -- path in Supabase Storage (Phase B)
    version text not null default '1.0.0',
    template text,
    format public.skill_format not null default 'SKILL.md',
    status public.skill_status not null default 'pending',
    install_count integer not null default 0,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

comment on table public.skills is
    'Published catalog entries. Public read is restricted to status=approved via RLS.';

-- ---------------------------------------------------------------------------
-- ratings (§4) — 1-5 stars, 1 per account per skill.
-- ---------------------------------------------------------------------------
create table public.ratings (
    id uuid primary key default gen_random_uuid(),
    skill_id uuid not null references public.skills (id) on delete cascade,
    user_id uuid not null references auth.users (id) on delete cascade,
    stars smallint not null check (stars between 1 and 5),
    created_at timestamptz not null default now(),
    -- 1 rating per user per skill (§4).
    unique (skill_id, user_id)
);

comment on table public.ratings is 'Account-gated 1-5 star ratings, unique per (skill, user).';

-- ---------------------------------------------------------------------------
-- likes (§4) — anonymous device-scoped, 1 per device per skill.
-- ---------------------------------------------------------------------------
-- NOTE: device_or_user_id is CLIENT-SUPPLIED and NOT verified against auth.uid
-- (likes are anon-by-design, §4). The unique constraint stops a well-behaved
-- client double-liking, but a malicious client can forge device ids. This is an
-- accepted trust tradeoff for a vanity counter — see supabase/README.md.
create table public.likes (
    id uuid primary key default gen_random_uuid(),
    skill_id uuid not null references public.skills (id) on delete cascade,
    device_or_user_id text not null,
    created_at timestamptz not null default now(),
    -- 1 like per device per skill (§4).
    unique (skill_id, device_or_user_id)
);

comment on table public.likes is
    'Anonymous device-scoped likes (1/device). device_or_user_id is client-supplied (see README trust note).';

-- ---------------------------------------------------------------------------
-- comments (§4) — account-gated, moderated.
-- ---------------------------------------------------------------------------
create table public.comments (
    id uuid primary key default gen_random_uuid(),
    skill_id uuid not null references public.skills (id) on delete cascade,
    user_id uuid not null references auth.users (id) on delete cascade,
    body text not null,
    status public.comment_status not null default 'pending',
    created_at timestamptz not null default now()
);

comment on table public.comments is
    'Account-gated comments. Public read is restricted to status=approved (author sees own) via RLS.';

-- ---------------------------------------------------------------------------
-- flags (§4) — moderation report queue. target_id is polymorphic (skill|comment),
-- so it is a bare uuid with no FK (it can point at either table).
-- ---------------------------------------------------------------------------
create table public.flags (
    id uuid primary key default gen_random_uuid(),
    target_type public.flag_target_type not null,
    target_id uuid not null,
    reason text,
    -- nullable: an anonymous (un-authenticated) reporter has no auth.uid.
    reporter_id uuid references auth.users (id) on delete set null,
    created_at timestamptz not null default now()
);

comment on table public.flags is
    'Moderation report queue. INSERT is open (report button); SELECT is moderation-only (no public read) via RLS.';

-- ---------------------------------------------------------------------------
-- installs (§4) — attribution + trending input. Counts only, no PII.
-- ---------------------------------------------------------------------------
create table public.installs (
    id uuid primary key default gen_random_uuid(),
    skill_id uuid not null references public.skills (id) on delete cascade,
    device_id text not null,                -- opaque, no PII (§4)
    creator_attrib uuid,                    -- creator credited for this install
    ts timestamptz not null default now()
);

comment on table public.installs is
    'Install events (attribution + trending). Counts only, no PII. Anon INSERT allowed via RLS.';

-- ---------------------------------------------------------------------------
-- Indexes — slug, handle, skill_id, status, created_at (per task), plus the
-- FK / RLS-predicate columns. Postgres auto-indexes PKs and UNIQUE columns,
-- so `skills.slug`, `creators.handle`, and the composite uniques are already
-- covered; the rest are explicit.
-- ---------------------------------------------------------------------------
create index skills_creator_id_idx on public.skills (creator_id);
create index skills_status_idx on public.skills (status);
create index skills_category_idx on public.skills (category);
create index skills_created_at_idx on public.skills (created_at desc);

create index ratings_skill_id_idx on public.ratings (skill_id);
create index ratings_user_id_idx on public.ratings (user_id);

create index likes_skill_id_idx on public.likes (skill_id);

create index comments_skill_id_idx on public.comments (skill_id);
create index comments_user_id_idx on public.comments (user_id);
create index comments_status_idx on public.comments (status);
create index comments_created_at_idx on public.comments (created_at desc);

create index flags_target_idx on public.flags (target_type, target_id);
create index flags_created_at_idx on public.flags (created_at desc);

create index installs_skill_id_idx on public.installs (skill_id);
create index installs_ts_idx on public.installs (ts desc);

-- ---------------------------------------------------------------------------
-- updated_at trigger for skills (§4 requires skills.updated_at maintenance).
-- The trigger function lives in the private `extensions` schema (NOT an
-- exposed schema) per the security checklist for security-relevant functions;
-- here it is a plain (non-SECURITY DEFINER) trigger, but keeping helper
-- functions out of `public` is the safe default.
-- ---------------------------------------------------------------------------
create or replace function extensions.set_updated_at()
returns trigger
language plpgsql
as $$
begin
    new.updated_at = now();
    return new;
end;
$$;

create trigger skills_set_updated_at
    before update on public.skills
    for each row
    execute function extensions.set_updated_at();

-- ---------------------------------------------------------------------------
-- trending_skills view (§4 derived signal: installs + likes + avg rating +
-- recency over approved skills).
--
-- SECURITY: security_invoker = true (Postgres 15+) so the view is evaluated
-- with the QUERYING role's privileges and DOES NOT bypass the RLS on its base
-- tables (supabase skill checklist — BINDING). The WHERE status='approved'
-- mirrors the skills SELECT policy, and the view only reads aggregate
-- like/rating/install counts (no PII).
--
-- Score: weighted blend with an exponential recency decay (half-life ~7 days).
-- ---------------------------------------------------------------------------
create view public.trending_skills
with (security_invoker = true)
as
select
    s.id,
    s.slug,
    s.name,
    s.category,
    s.creator_id,
    s.install_count,
    coalesce(l.like_count, 0)        as like_count,
    coalesce(r.rating_count, 0)      as rating_count,
    coalesce(r.avg_rating, 0)::numeric(3, 2) as avg_rating,
    s.created_at,
    -- trending score = installs + likes*2 + avg_rating*10, decayed by age.
    (
        (
            s.install_count
            + coalesce(l.like_count, 0) * 2
            + coalesce(r.avg_rating, 0) * 10
        )
        * exp(-extract(epoch from (now() - s.created_at)) / (7 * 24 * 3600.0))
    )::numeric(12, 4) as trending_score
from public.skills s
left join (
    select skill_id, count(*) as like_count
    from public.likes
    group by skill_id
) l on l.skill_id = s.id
left join (
    select
        skill_id,
        count(*)     as rating_count,
        avg(stars)   as avg_rating
    from public.ratings
    group by skill_id
) r on r.skill_id = s.id
where s.status = 'approved'
order by trending_score desc;

comment on view public.trending_skills is
    'Derived trending feed over approved skills (security_invoker=true so RLS is enforced).';
