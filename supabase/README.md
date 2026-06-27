# KALI Community marketplace — Supabase schema

SQL migrations for the §4 data model of
[`docs/superpowers/specs/2026-06-25-kali-community-marketplace-design.md`](../docs/superpowers/specs/2026-06-25-kali-community-marketplace-design.md).
This is the **Phase B** cloud catalog backend — it **replaces** the flat
`packages` prototype in `kernel/catalog/client.py` (2026-04-13) with seven
normalized tables (`creators`, `skills`, `ratings`, `likes`, `comments`,
`flags`, `installs`) plus a `trending_skills` view.

Schema-only. The Python `CatalogClient` rewrite that targets these tables is a
separate task (3.2) and is **not** in this directory.

## Migrations

| File | Contents |
|---|---|
| `migrations/20260627115811_community_marketplace_schema.sql` | Enums, 7 tables, indexes, `skills.updated_at` trigger, `trending_skills` view (`security_invoker=true`). |
| `migrations/20260627115812_community_marketplace_rls.sql` | `ENABLE ROW LEVEL SECURITY` on every table + all policies. |

> The migration files were authored manually following the Supabase CLI naming
> convention (`<YYYYMMDDHHMMSS>_<name>.sql`, UTC) because the `supabase` CLI is
> **not installed in the authoring environment**. When the CLI is available,
> new migrations should be scaffolded with `supabase migration new <name>` so
> the timestamp is generated for you.

## Applying (requires a provisioned Supabase project — the go-live gate)

There is **no live Supabase project yet**; Vasily provisions it later. Once the
project exists:

```bash
# one-time: link the local repo to the remote project
supabase link --project-ref <project-ref>

# push the migrations to the remote DB (applies in timestamp order)
supabase db push

# or, against a local stack:
supabase start
supabase migration up
```

## REQUIRED after applying: run the advisors

These migrations were **statically authored and self-reviewed only** — they
have **not** been applied to or validated against a live Postgres/Supabase
instance. Before treating the schema as production-ready you **must** run the
Supabase advisors on the real project and fix anything they surface:

```bash
supabase db advisors          # CLI v2.81.3+
```

or via the Supabase MCP server: `get_advisors` (types `security` and
`performance`). Pay attention to:

- **`security`** — confirms RLS is enabled on every exposed table and flags any
  `SECURITY DEFINER` / RLS-bypassing view. (We use `security_invoker = true` on
  `trending_skills` precisely so it does **not** bypass RLS — the advisor should
  pass it.)
- **`performance`** — flags missing indexes on RLS-predicate / FK columns and
  un-wrapped `auth.<fn>()` calls. We pre-index the FK + `status` columns and
  wrap `auth.uid()` as `(select auth.uid())`, but re-verify on the live schema.

## Security model (per table)

| Table | SELECT | INSERT | UPDATE / DELETE |
|---|---|---|---|
| `creators` | public | own row (`auth.uid()=id`) | own row |
| `skills` | public **only `approved`**; creator sees own any-status | creator (`auth.uid()=creator_id`) | creator |
| `ratings` | public | own (`auth.uid()=user_id`) | own |
| `likes` | public | **anon + authed** (device-scoped) | delete: device may unlike |
| `comments` | public **only `approved`**; author sees own any-status | author (`auth.uid()=user_id`) | author |
| `flags` | **none** (moderation-only) | **anon + authed** (report button) | none |
| `installs` | public (aggregate) | **anon + authed** (counter) | none |

- **No `user_metadata` in any policy.** All ownership checks use `auth.uid()`
  (and would use `app_metadata` / `auth.jwt()->'app_metadata'` for any future
  role claim) — `user_metadata` is user-editable and unsafe for authorization.
- **UPDATE policies are paired with SELECT policies** for the same rows
  (`skills`, `comments` add a creator/author "own rows any status" SELECT) so
  updates don't silently affect 0 rows.
- **Moderation** (approve/flag/remove a `skills.status` or `comments.status`,
  and reading/working the `flags` queue) is done by a **privileged backend**
  using the `service_role` key, which **bypasses RLS**. Never ship the
  `service_role` key in a client (use the publishable/anon key there).

## Anon-insert trust caveats (BINDING — read before launch)

Three tables accept **anonymous, client-supplied** writes by design. Their
inputs are **not** authenticated and **must be treated as untrusted**:

- **`likes.device_or_user_id`** and **`installs.device_id`** are opaque strings
  the client sends; the server does **not** verify them against `auth.uid()`.
  The `unique(skill_id, device_or_user_id)` constraint stops a *well-behaved*
  client from double-liking, but a malicious client can forge device ids to
  inflate like/install counters. This is an accepted tradeoff for **vanity
  metrics** — do **not** use these counts for anything that gates trust, money,
  or moderation. Mitigations to layer at the edge (not in this schema): rate
  limiting, IP/device heuristics, or an Edge Function that derives the device
  id server-side.
- **`flags`** INSERT is open so the report button works without an account. The
  queue is **not publicly readable** (no SELECT policy), so a forged flag can't
  directly hide content — a human/automated moderator reviews the queue via
  `service_role` before any `status` change. Expect spam flags; the report
  count is a signal, not an action.
- **`installs`** rows are public-readable but contain **no PII** (opaque
  `device_id` only) — the `trending_skills` view consumes them in aggregate.

## Notes

- All objects are in the **`public`** schema (Data-API-exposed) → RLS is
  mandatory and enabled on all seven tables.
- The `trending_skills` view uses `WITH (security_invoker = true)` (Postgres
  15+) so it runs with the querying role's privileges and respects the base
  tables' RLS instead of bypassing it.
- The `set_updated_at()` trigger function lives in the private `extensions`
  schema (not `public`), keeping helper functions out of the exposed schema.
