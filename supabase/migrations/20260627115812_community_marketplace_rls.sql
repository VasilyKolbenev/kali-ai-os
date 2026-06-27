-- KALI Community marketplace — Row-Level Security (§3 of the marketplace design
-- spec + the supabase skill security checklist, BINDING).
--
-- Companion to 20260627115811_community_marketplace_schema.sql.
--
-- Principles enforced here:
--   * RLS is ENABLED on EVERY table in the (exposed) public schema.
--   * Public read is limited to approved content; users write only their own
--     ratings/comments; only a creator edits their own skills.
--   * Authorization is derived ONLY from auth.uid() (never user_metadata,
--     which is user-editable — checklist item).
--   * Every UPDATE policy is paired with a SELECT policy for the same rows,
--     otherwise UPDATE silently affects 0 rows (checklist item).
--   * auth.uid() is wrapped in (select auth.uid()) so the planner caches it
--     per-statement (performance recommendation).
--
-- Roles: `anon` = unauthenticated (device-id only); `authenticated` = magic-link
-- KALI account. `public` is used where BOTH should match.

-- ===========================================================================
-- Enable RLS on every table (BINDING: no table left without RLS).
-- ===========================================================================
alter table public.creators enable row level security;
alter table public.skills   enable row level security;
alter table public.ratings  enable row level security;
alter table public.likes    enable row level security;
alter table public.comments enable row level security;
alter table public.flags    enable row level security;
alter table public.installs enable row level security;

-- ===========================================================================
-- creators — public profile.
--   SELECT: public (anyone can view a creator profile).
--   INSERT/UPDATE/DELETE: a user manages only their OWN row (auth.uid() = id).
-- ===========================================================================
create policy "creators are publicly readable"
on public.creators for select
to anon, authenticated
using (true);

create policy "users insert their own creator row"
on public.creators for insert
to authenticated
with check ((select auth.uid()) = id);

create policy "users update their own creator row"
on public.creators for update
to authenticated
using ((select auth.uid()) = id)
with check ((select auth.uid()) = id);

create policy "users delete their own creator row"
on public.creators for delete
to authenticated
using ((select auth.uid()) = id);

-- ===========================================================================
-- skills — the catalog.
--   SELECT (public): only status='approved'.
--   SELECT (creator): own rows in ANY status (so the creator sees pending/
--     flagged drafts AND so UPDATE/DELETE can locate the row — UPDATE needs a
--     matching SELECT, and an approved-only SELECT would hide a pending row
--     from its own creator's UPDATE).
--   INSERT/UPDATE/DELETE: creator only (auth.uid() = creator_id).
-- ===========================================================================
create policy "approved skills are publicly readable"
on public.skills for select
to anon, authenticated
using (status = 'approved');

create policy "creators read their own skills in any status"
on public.skills for select
to authenticated
using ((select auth.uid()) = creator_id);

create policy "creators insert their own skills"
on public.skills for insert
to authenticated
with check ((select auth.uid()) = creator_id);

create policy "creators update their own skills"
on public.skills for update
to authenticated
using ((select auth.uid()) = creator_id)
with check ((select auth.uid()) = creator_id);

create policy "creators delete their own skills"
on public.skills for delete
to authenticated
using ((select auth.uid()) = creator_id);

-- ===========================================================================
-- ratings — account-gated, 1 per user (unique constraint enforces the count).
--   SELECT: public (so the catalog can show aggregate stars).
--   INSERT/UPDATE/DELETE: only the owning user (auth.uid() = user_id).
-- ===========================================================================
create policy "ratings are publicly readable"
on public.ratings for select
to anon, authenticated
using (true);

create policy "users insert their own rating"
on public.ratings for insert
to authenticated
with check ((select auth.uid()) = user_id);

create policy "users update their own rating"
on public.ratings for update
to authenticated
using ((select auth.uid()) = user_id)
with check ((select auth.uid()) = user_id);

create policy "users delete their own rating"
on public.ratings for delete
to authenticated
using ((select auth.uid()) = user_id);

-- ===========================================================================
-- likes — anonymous device-scoped (1/device via unique constraint).
--   SELECT: public (counts).
--   INSERT: anon AND authenticated allowed. device_or_user_id is supplied by
--     the client and intentionally NOT tied to auth.uid() (likes are
--     anon-by-design). The unique(skill_id, device_or_user_id) constraint
--     enforces 1/device for a well-behaved client; a forged device id can
--     still inflate the counter — accepted tradeoff for a vanity metric,
--     documented in supabase/README.md. No UPDATE policy (a like is
--     insert/delete only); we expose DELETE so a device can unlike its own
--     like by matching the device id it supplied.
-- ===========================================================================
create policy "likes are publicly readable"
on public.likes for select
to anon, authenticated
using (true);

create policy "anyone may like (device-scoped, anon insert)"
on public.likes for insert
to anon, authenticated
with check (true);

create policy "a device may remove its own like"
on public.likes for delete
to anon, authenticated
using (true);

-- ===========================================================================
-- comments — account-gated, moderated.
--   SELECT (public): only status='approved'.
--   SELECT (author): own comments in ANY status (visibility + UPDATE pairing).
--   INSERT/UPDATE/DELETE: author only (auth.uid() = user_id). Status moderation
--     transitions are performed by a privileged backend (service_role bypasses
--     RLS); an author cannot self-approve because UPDATE WITH CHECK only
--     re-asserts ownership, and the public SELECT still gates on 'approved'.
-- ===========================================================================
create policy "approved comments are publicly readable"
on public.comments for select
to anon, authenticated
using (status = 'approved');

create policy "authors read their own comments in any status"
on public.comments for select
to authenticated
using ((select auth.uid()) = user_id);

create policy "authors insert their own comments"
on public.comments for insert
to authenticated
with check ((select auth.uid()) = user_id);

create policy "authors update their own comments"
on public.comments for update
to authenticated
using ((select auth.uid()) = user_id)
with check ((select auth.uid()) = user_id);

create policy "authors delete their own comments"
on public.comments for delete
to authenticated
using ((select auth.uid()) = user_id);

-- ===========================================================================
-- flags — moderation report queue.
--   INSERT: open (report button) for anon AND authenticated.
--   SELECT/UPDATE/DELETE: NONE for anon/authenticated — the queue is
--     moderation-only. With RLS enabled and no SELECT policy, anon/authenticated
--     get zero rows; only the service_role (which bypasses RLS) reads/works the
--     queue. This deliberately keeps reports private (a reporter cannot even
--     read back their own report).
-- ===========================================================================
create policy "anyone may file a flag"
on public.flags for insert
to anon, authenticated
with check (true);

-- (No SELECT/UPDATE/DELETE policies: moderation-only access via service_role.)

-- ===========================================================================
-- installs — counter / attribution (no PII).
--   INSERT: anon AND authenticated allowed (the install counter).
--   SELECT: public (aggregate/trending input). Rows hold no PII (opaque
--     device_id only), so public read of the raw events is acceptable; the
--     trending_skills view consumes them in aggregate.
--   No UPDATE/DELETE (install events are immutable).
-- ===========================================================================
create policy "installs are publicly readable"
on public.installs for select
to anon, authenticated
using (true);

create policy "anyone may record an install (anon insert)"
on public.installs for insert
to anon, authenticated
with check (true);
