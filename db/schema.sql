-- HCT site schema: all site data lives here so the frontend only needs the
-- project URL + publishable key. Writes happen only via the backend secret /
-- service-role key (which bypasses RLS); the public roles get read-only access.
--
-- Security model (see Supabase RLS guidance):
--   * RLS enabled on every table in the public schema.
--   * One SELECT policy per table for anon + authenticated (USING true) — the
--     whole site is public read.
--   * Two independent layers stop a publishable-key client writing, and it is
--     worth being precise about which does what:
--       - RLS is the real enforcement. Absent an INSERT/UPDATE/DELETE policy,
--         no row may be written, whatever privileges the role holds.
--       - GRANTs are the second layer, and are NOT automatic. Supabase's
--         default privileges give `anon`/`authenticated` the *full* set
--         (including TRUNCATE, which RLS does not police at all) on every new
--         table in `public`. So the `revoke all ... from anon, authenticated`
--         below is load-bearing — the `grant select` lines that follow it only
--         narrow anything *because* of that revoke. Re-running this file
--         re-applies it, which also clears the broad defaults re-granted to
--         any table created since (e.g. via the dashboard).
--   * Exception: `feedback` (bottom of this file) allows anon/authenticated
--     INSERT only, no SELECT — see that section for why.
--
-- This file is the single source of truth and is meant to be re-run as-is on
-- either a brand-new database or an existing one: every `create table` lists
-- the full canonical column set (so a fresh DB gets everything at once), and
-- is immediately followed by `alter table ... add column if not exists` for
-- every column (a no-op on a fresh DB, additive on an older one). Indexes,
-- constraints, RLS and grants always come *after* those alters for the same
-- table, never before — an index on a column that only the alter adds must
-- never run ahead of that alter.

-- ---------------------------------------------------------------------------
-- publications: the structured paper list (replaces publications.yaml). A
-- paper belongs to at most one featured project (see docs/PROJECTS.md) and
-- carries three audience-targeted summaries (promoted from the paper_samples
-- A/B/C styles) plus a representative image.
-- ---------------------------------------------------------------------------
create table if not exists public.publications (
  id          uuid primary key default gen_random_uuid(),
  slug        text not null unique,          -- stable dedupe key (models.slug_for)
  title       text not null,
  authors     jsonb not null default '[]',   -- ordered list of names
  year        int  not null,
  type        text not null default 'misc',
  venue       text,
  link        text,
  bibtex      text,
  description      text,                    -- AI-written, lab voice (optional)
  project_slug     text,                    -- -> research.slug (loose ref); null = timeline-only
  summary_plain    text,                    -- style A: plain-language explainer (public)
  summary_abstract text,                    -- style B: technical abstract (researchers)
  summary_par      text,                    -- style C: problem/approach/result (prospective grads)
  image            text,                    -- representative figure (Supabase Storage URL)
  updated_at  timestamptz not null default now()
);
alter table public.publications add column if not exists description      text;
alter table public.publications add column if not exists project_slug     text;
alter table public.publications add column if not exists summary_plain    text;
alter table public.publications add column if not exists summary_abstract text;
alter table public.publications add column if not exists summary_par      text;
alter table public.publications add column if not exists image            text;
create index if not exists publications_year_idx    on public.publications (year desc);
create index if not exists publications_project_idx  on public.publications (project_slug);

-- ---------------------------------------------------------------------------
-- timeline: the full publication history, newest first (the site's centerpiece,
-- grouped by year in the frontend). Each entry carries an optional AI blurb
-- (reused from publications.description). Year-based dates (the CV/Scholar give
-- us year only). Rebuilt wholesale on every run.
-- ---------------------------------------------------------------------------
create table if not exists public.timeline (
  id         uuid primary key default gen_random_uuid(),
  slug       text,                            -- -> publications.slug (loose ref)
  title      text not null,
  authors    jsonb not null default '[]',
  year       int,
  date_label text,                            -- display label, e.g. "2022"
  blurb      text,                            -- AI, 1-2 sentences
  position   int  not null default 0,         -- 0 = newest
  created_at timestamptz not null default now()
);
create index if not exists timeline_position_idx on public.timeline (position);

-- ---------------------------------------------------------------------------
-- people: lab members (parsed from the static People tiles, bios AI-written).
-- ---------------------------------------------------------------------------
create table if not exists public.people (
  id         uuid primary key default gen_random_uuid(),
  name       text not null,
  role       text,
  email      text,
  photo      text,                            -- image path/url
  bio        text,                            -- AI-written (optional)
  kind       text not null default 'current', -- 'current' | 'alumni'
  sort_order int  not null default 0
);
create index if not exists people_sort_idx on public.people (sort_order);

-- ---------------------------------------------------------------------------
-- research: featured projects (synced from research.yaml/projects.yaml; AI
-- fills the blank taglines into a longer description). `slug`/`summary`/
-- `hero_image` are the project-page fields added by the project-centric
-- restructure (see docs/PROJECTS.md); `kind` is current/archived.
-- ---------------------------------------------------------------------------
create table if not exists public.research (
  id          uuid primary key default gen_random_uuid(),
  title       text not null,
  slug        text,                          -- stable project key (models.project_slug_for)
  tagline     text,
  description text,                          -- AI-written when missing
  summary     text,                          -- longer project-page body (see docs/PROJECTS.md)
  link        text,
  image       text,
  hero_image  text,                          -- project hero image
  kind        text not null default 'current', -- 'current' | 'archived'
  sort_order  int  not null default 0
);
alter table public.research add column if not exists slug       text;
alter table public.research add column if not exists summary    text;
alter table public.research add column if not exists hero_image text;
alter table public.research add column if not exists kind text not null default 'current';
alter table public.research drop constraint if exists research_kind_check;
alter table public.research add constraint research_kind_check check (kind in ('current', 'archived'));
create index if not exists research_sort_idx on public.research (sort_order);
create index if not exists research_kind_idx on public.research (kind);
create unique index if not exists research_slug_key on public.research (slug);

-- ---------------------------------------------------------------------------
-- project_people: which lab members are involved in each project. People stay
-- in `people`; this join links them per project (many-to-many — a person can
-- be on several projects). Papers link via publications.project_slug instead.
-- ---------------------------------------------------------------------------
create table if not exists public.project_people (
  id              uuid primary key default gen_random_uuid(),
  project_slug    text not null,               -- -> research.slug (loose ref)
  person_name     text not null,               -- -> people.name (loose ref)
  role_on_project text,                         -- e.g. 'lead', 'collaborator' (optional)
  sort_order      int  not null default 0
);
create index if not exists project_people_project_idx on public.project_people (project_slug);

-- ---------------------------------------------------------------------------
-- site_content: key/value store for free-text sections (vision, innovation,
-- contact, land acknowledgment, EDI, sponsors, opportunities, ...). The
-- frontend fetches any blurb by key.
-- ---------------------------------------------------------------------------
create table if not exists public.site_content (
  key        text primary key,
  value      jsonb not null default '{}',
  updated_at timestamptz not null default now()
);

-- ---------------------------------------------------------------------------
-- RLS: enable everywhere, public read-only.
-- ---------------------------------------------------------------------------
alter table public.publications   enable row level security;
alter table public.timeline       enable row level security;
alter table public.people         enable row level security;
alter table public.research       enable row level security;
alter table public.project_people enable row level security;
alter table public.site_content   enable row level security;

drop policy if exists "public read" on public.publications;
drop policy if exists "public read" on public.timeline;
drop policy if exists "public read" on public.people;
drop policy if exists "public read" on public.research;
drop policy if exists "public read" on public.project_people;
drop policy if exists "public read" on public.site_content;

create policy "public read" on public.publications   for select to anon, authenticated using (true);
create policy "public read" on public.timeline       for select to anon, authenticated using (true);
create policy "public read" on public.people         for select to anon, authenticated using (true);
create policy "public read" on public.research       for select to anon, authenticated using (true);
create policy "public read" on public.project_people for select to anon, authenticated using (true);
create policy "public read" on public.site_content   for select to anon, authenticated using (true);

-- Strip the broad default privileges Supabase hands `anon`/`authenticated` on
-- every table in `public` (SELECT+INSERT+UPDATE+DELETE+TRUNCATE+REFERENCES+
-- TRIGGER), then hand back only what the policies above and below actually
-- need. Without this the `grant select` lines are decorative and TRUNCATE —
-- which RLS does not cover — is available to a browser key.
--
-- This has to sweep *all* tables, so it necessarily also strips the tables
-- created further down this file (paper_samples, feedback, admins,
-- style_profile); each of those sections re-grants its own privileges after
-- its `create table`, so a full re-run of this file lands in the right place.
revoke all on all tables in schema public from anon, authenticated;

-- Expose to the Data API (read only). Writes are done with the secret key,
-- which bypasses RLS and these grants.
grant select on public.publications   to anon, authenticated;
grant select on public.timeline       to anon, authenticated;
grant select on public.people         to anon, authenticated;
grant select on public.research       to anon, authenticated;
grant select on public.project_people to anon, authenticated;
grant select on public.site_content   to anon, authenticated;

-- ---------------------------------------------------------------------------
-- paper_samples (EXPERIMENT, disposable): the AI summary "bake-off". For each
-- sample paper we generate one row per (style A-E) x mode x model, so
-- the samples page can show them side by side. Not part of the production
-- publication flow; drop the table to remove the experiment. Written by the
-- backend secret key; public read-only like every other table.
--
-- Run this block in the HCT project's SQL editor (the backend can't run DDL).
-- ---------------------------------------------------------------------------
create table if not exists public.paper_samples (
  id                uuid primary key default gen_random_uuid(),
  paper_slug        text not null,                 -- -> publications.slug (loose ref)
  style             text not null,                 -- 'A'..'E'
  mode              text not null,                 -- 'rag' | 'full'
  model             text not null default '',      -- which model produced it
  summary           text not null default '',      -- the generated overview (markdown)
  link              text,                          -- validated canonical URL
  oa_url            text,                          -- free full-text URL, if any
  confidence        real,                          -- link-match confidence 0..1
  prompt_tokens     int  not null default 0,
  completion_tokens int  not null default 0,
  latency_s         real not null default 0,
  position          int  not null default 0,       -- stable display order
  created_at        timestamptz not null default now(),
  unique (paper_slug, style, mode, model)          -- upsert key (on_conflict)
);
create index if not exists paper_samples_position_idx on public.paper_samples (position);

alter table public.paper_samples enable row level security;
drop policy if exists "public read" on public.paper_samples;
create policy "public read" on public.paper_samples for select to anon, authenticated using (true);
grant select on public.paper_samples to anon, authenticated;

-- ---------------------------------------------------------------------------
-- feedback: the right-click "send feedback" widget (ported from muksite).
-- Unlike every other table above, the public role may INSERT but never
-- SELECT — visitors write with the publishable key from the browser; the lab
-- reads submissions only via the backend secret key (`hct-manager feedback`),
-- which bypasses RLS.
--
-- Run this block in the HCT project's SQL editor (the backend can't run DDL).
-- ---------------------------------------------------------------------------
create table if not exists public.feedback (
  id            uuid primary key default gen_random_uuid(),
  created_at    timestamptz not null default now(),
  page_path     text not null,
  element_key   text,
  element_label text,
  element_html  text,
  category      text not null default 'general',
  message       text not null,
  metadata      jsonb not null default '{}'
);

alter table public.feedback drop constraint if exists feedback_category_check;
alter table public.feedback add constraint feedback_category_check
  check (category in ('bug', 'suggestion', 'question', 'general'));

-- Message + element_html/label are the only anon-writable free text; the RLS
-- policy below is wide open (`with check (true)`), so these CHECKs are the
-- only server-side guard against a direct API POST (bypassing our own UI's
-- client-side maxLength) stuffing huge/blank rows.
alter table public.feedback drop constraint if exists feedback_message_check;
alter table public.feedback add constraint feedback_message_check
  check (char_length(btrim(message)) between 1 and 2000);
alter table public.feedback drop constraint if exists feedback_element_html_check;
alter table public.feedback add constraint feedback_element_html_check
  check (element_html is null or char_length(element_html) <= 4000);
alter table public.feedback drop constraint if exists feedback_element_label_check;
alter table public.feedback add constraint feedback_element_label_check
  check (element_label is null or char_length(element_label) <= 200);

create index if not exists feedback_created_at_idx on public.feedback (created_at desc);
create index if not exists feedback_category_idx   on public.feedback (category);

alter table public.feedback enable row level security;
drop policy if exists "public insert" on public.feedback;
create policy "public insert" on public.feedback
  for insert to anon, authenticated with check (true);
-- Intentionally no `for select` policy and no `grant select`.
grant insert on public.feedback to anon, authenticated;

-- ---------------------------------------------------------------------------
-- Admin CMS foundation: Supabase Auth (magic link) + an `admins` allowlist
-- gate every write below. The frontend signs in via `signInWithOtp`, checks
-- membership in `admins`, and only then shows edit affordances; RLS is the
-- real enforcement (a forged/tampered client can't get past it either way).
--
-- Run this block in the HCT project's SQL editor (the backend can't run DDL).
-- ---------------------------------------------------------------------------

-- admins: which authenticated users may edit site content directly. Every
-- admin-write RLS policy below reuses the
-- `exists (select 1 from public.admins where user_id = (select auth.uid()))`
-- predicate. Seeded manually post-launch: the admin signs in once via magic
-- link, then their `auth.users.id` is inserted here with the secret key (not
-- automated by this codebase).
create table if not exists public.admins (
  user_id uuid primary key references auth.users(id) on delete cascade,
  email   text
);
alter table public.admins enable row level security;
drop policy if exists "admin self read" on public.admins;
create policy "admin self read" on public.admins for select to authenticated
  using (user_id = (select auth.uid()));
grant select on public.admins to authenticated;

-- style_profile: the admin's writing-voice exemplar (source_excerpt, raw text
-- supplied via the admin UI) and the derived profile_text (LLM-distilled
-- guidance, threaded into summarize.py as a distinct `voice_profile` block,
-- separate from the module's existing audience-style A/B/C/D/E parameter).
-- Single row keyed 'default'; admin-only read/write, no public exposure.
create table if not exists public.style_profile (
  id             text primary key default 'default',
  source_excerpt text,
  profile_text   text,
  updated_at     timestamptz default now()
);

-- `source_excerpt` is admin-supplied free text that `hct-manager style-regen`
-- distils into `profile_text`, which is then threaded into every describe /
-- summarize prompt. Unbounded it is both an unbounded-cost surface (the whole
-- excerpt goes to the model on each regen) and an unbounded prompt-injection
-- surface. 20k characters is several thousand words -- far more than a voice
-- sample needs. `profile_text` is model output rather than admin input, but it
-- is what actually lands in the prompts, so it gets the same ceiling. The
-- admin textarea mirrors this limit (frontend/src/components/AdminPage.jsx,
-- `EXCERPT_MAX`) so a long paste is trimmed visibly rather than failing at
-- save time; keep the two numbers in step.
alter table public.style_profile drop constraint if exists style_profile_source_excerpt_check;
alter table public.style_profile add constraint style_profile_source_excerpt_check
  check (source_excerpt is null or char_length(source_excerpt) <= 20000);
alter table public.style_profile drop constraint if exists style_profile_profile_text_check;
alter table public.style_profile add constraint style_profile_profile_text_check
  check (profile_text is null or char_length(profile_text) <= 20000);

alter table public.style_profile enable row level security;
drop policy if exists "admin read/write style_profile" on public.style_profile;
create policy "admin read/write style_profile" on public.style_profile
  for all to authenticated
  using (exists (select 1 from public.admins where user_id = (select auth.uid())))
  with check (exists (select 1 from public.admins where user_id = (select auth.uid())));
grant select, insert, update, delete on public.style_profile to authenticated;

-- publications enrichment columns: scraper/API-sourced (OpenAlex), nullable,
-- filled by the (future) `hct-manager enrich` command, never LLM-invented.
alter table public.publications add column if not exists citation_count int;
alter table public.publications add column if not exists concepts      text[];
alter table public.publications add column if not exists oa_status     text;

-- people_name_key: `name` is the loose-ref join key used by `project_people`
-- and the admin UI's identity rule (name immutable after creation; typo fixes
-- = delete+recreate) -- a uniqueness safety net. Checked the live table first
-- (case-sensitive and case-insensitive) for existing duplicates before adding
-- this: none found as of 2026-07-26.
create unique index if not exists people_name_key on public.people (name);

-- Guard triggers: RLS can restrict which *rows* an admin may update but not
-- which *columns* -- `research` and `publications` each get a narrow admin
-- update policy below, backed by a BEFORE UPDATE trigger that raises if
-- anything outside a small allowlist differs between OLD and NEW.
--
-- Two properties matter here, and both were originally the other way round:
--
--   * ALLOWLIST, not denylist. The check compares `to_jsonb(new)` against
--     `to_jsonb(old)` with the *allowed* keys removed, rather than naming the
--     forbidden columns one by one. A denylist has to be edited every time the
--     table grows or the new column silently becomes admin-writable; this
--     locks unknown columns out by default and needs no maintenance.
--
--   * FAIL-CLOSED. The guard runs for every caller *except* the backend's
--     service role, instead of running only when `auth.role()` happens to read
--     'authenticated'. The service test keys off `current_user` first, because
--     PostgREST switches to the `service_role` DB role for the secret key
--     whatever that key's claims look like; `auth.role()` is a second signal.
--     Both comparisons use `is distinct from`, which is NULL-safe --- with `=`
--     the whole condition evaluates to NULL when there is no JWT, plpgsql
--     treats that as false, and the guard skips itself (verified: that is
--     exactly what happened before this was corrected).
--
-- Consequence: a direct owner/superuser session (SQL editor, MCP, a migration)
-- is guarded too. That is the intent. For a deliberate maintenance write to a
-- locked column from such a session, run it inside a transaction that first
-- does `set local role service_role;`.
--
-- `search_path` is pinned per the function-search-path-mutable advisory.
-- `publications.updated_at` is bookkeeping, not admin-editable content, so it
-- sits in the allowlist (excluded from the diff) and is unconditionally
-- stamped to `now()` by the trigger -- an admin update that also sends
-- `updated_at` (a natural thing for a client to do) is silently corrected
-- rather than rejected. `research` has no analogous timestamp column, so it
-- needs no such carve-out.
create or replace function public.research_admin_guard()
returns trigger
language plpgsql
set search_path = ''
as $$
declare
  -- The only columns an admin-UI update may change.
  allowed constant text[] := array['summary', 'hero_image', 'tagline'];
begin
  if current_user is distinct from 'service_role'
     and auth.role() is distinct from 'service_role'
  then
    if to_jsonb(new) - allowed is distinct from to_jsonb(old) - allowed then
      raise exception
        'research_admin_guard: admin update may only change summary, hero_image, tagline';
    end if;
  end if;
  return new;
end;
$$;
drop trigger if exists research_admin_guard_trigger on public.research;
create trigger research_admin_guard_trigger
  before update on public.research
  for each row execute function public.research_admin_guard();

create or replace function public.publications_admin_guard()
returns trigger
language plpgsql
set search_path = ''
as $$
declare
  -- Admin-editable columns, plus `updated_at` (see the note above).
  allowed constant text[] := array[
    'summary_plain', 'summary_abstract', 'summary_par', 'image', 'updated_at'
  ];
begin
  if current_user is distinct from 'service_role'
     and auth.role() is distinct from 'service_role'
  then
    if to_jsonb(new) - allowed is distinct from to_jsonb(old) - allowed then
      raise exception
        'publications_admin_guard: admin update may only change summary_plain, summary_abstract, summary_par, image';
    end if;
  end if;
  new.updated_at := now();
  return new;
end;
$$;
drop trigger if exists publications_admin_guard_trigger on public.publications;
create trigger publications_admin_guard_trigger
  before update on public.publications
  for each row execute function public.publications_admin_guard();

-- New admin write policies on tables that were previously backend-secret-key
-- write-only. `site_content`/`people` are unrestricted at the column level
-- (nothing in either needs it); `research`/`publications` pair their policy
-- with the guard trigger above.
drop policy if exists "admin insert site_content" on public.site_content;
create policy "admin insert site_content" on public.site_content
  for insert to authenticated
  with check (exists (select 1 from public.admins where user_id = (select auth.uid())));
drop policy if exists "admin update site_content" on public.site_content;
create policy "admin update site_content" on public.site_content
  for update to authenticated
  using (exists (select 1 from public.admins where user_id = (select auth.uid())))
  with check (exists (select 1 from public.admins where user_id = (select auth.uid())));
grant insert, update on public.site_content to authenticated;

drop policy if exists "admin insert people" on public.people;
create policy "admin insert people" on public.people
  for insert to authenticated
  with check (exists (select 1 from public.admins where user_id = (select auth.uid())));
drop policy if exists "admin update people" on public.people;
create policy "admin update people" on public.people
  for update to authenticated
  using (exists (select 1 from public.admins where user_id = (select auth.uid())))
  with check (exists (select 1 from public.admins where user_id = (select auth.uid())));
drop policy if exists "admin delete people" on public.people;
create policy "admin delete people" on public.people
  for delete to authenticated
  using (exists (select 1 from public.admins where user_id = (select auth.uid())));
grant insert, update, delete on public.people to authenticated;

drop policy if exists "admin update research" on public.research;
create policy "admin update research" on public.research
  for update to authenticated
  using (exists (select 1 from public.admins where user_id = (select auth.uid())))
  with check (exists (select 1 from public.admins where user_id = (select auth.uid())));
grant update on public.research to authenticated;

drop policy if exists "admin update publications" on public.publications;
create policy "admin update publications" on public.publications
  for update to authenticated
  using (exists (select 1 from public.admins where user_id = (select auth.uid())))
  with check (exists (select 1 from public.admins where user_id = (select auth.uid())));
grant update on public.publications to authenticated;

-- Storage buckets: `site-media` (public read, admin write -- people/project/
-- paper photos) and `cv-uploads` (private, admin-only -- the CV docx that
-- triggers the CI sync job). Path convention: `people/<slug>.<ext>`,
-- `projects/<slug>.<ext>`, `papers/<slug>.<ext>` in site-media; fixed object
-- `cv/current.docx` in cv-uploads (overwritten each upload, no versioning).
-- Backend reads cv-uploads with the existing secret key, which bypasses
-- storage RLS the same way it bypasses table RLS today.
--
-- Advisor note: `site-media public read` trips the "public bucket allows
-- listing" lint (a broad SELECT policy lets anyone list every object in the
-- bucket, not just fetch by known path). Accepted for now -- site-media only
-- ever holds non-sensitive presentational images (people/project/paper
-- photos), and this matches the plan's spec verbatim; revisit if that
-- changes.
insert into storage.buckets (id, name, public) values ('site-media', 'site-media', true) on conflict (id) do nothing;
insert into storage.buckets (id, name, public) values ('cv-uploads', 'cv-uploads', false) on conflict (id) do nothing;

-- Bounded uploads. Both buckets shipped with `file_size_limit` and
-- `allowed_mime_types` null, i.e. any size, any type. The frontend's
-- isImageFile/isDocxFile checks (frontend/src/lib/format.js) are client-side
-- hints and are trivially bypassed; these are the server-side bound.
--
-- site-media is public-read, so the allowlist is deliberately narrow: the four
-- raster formats every browser renders. image/svg+xml is excluded on purpose
-- -- an SVG is a script-carrying document served from a public origin. Adding
-- a format here (avif, heic, ...) means updating this list.
update storage.buckets
   set allowed_mime_types = array['image/jpeg', 'image/png', 'image/webp', 'image/gif'],
       file_size_limit    = 10485760   -- 10 MiB
 where id = 'site-media';
-- cv-uploads holds exactly one object, cv/current.docx. The docx MIME type is
-- pinned client-side too (frontend/src/data/storage.js `asDocx`), because some
-- pickers report an empty type for a .docx and Storage reads the type off the
-- blob rather than from supabase-js's `contentType` option.
update storage.buckets
   set allowed_mime_types = array['application/vnd.openxmlformats-officedocument.wordprocessingml.document'],
       file_size_limit    = 20971520   -- 20 MiB
 where id = 'cv-uploads';

drop policy if exists "site-media public read" on storage.objects;
create policy "site-media public read" on storage.objects for select to anon, authenticated
  using (bucket_id = 'site-media');
drop policy if exists "site-media admin write" on storage.objects;
create policy "site-media admin write" on storage.objects for insert to authenticated
  with check (bucket_id = 'site-media' and exists (select 1 from public.admins where user_id = (select auth.uid())));
-- Both admin policies scope `bucket_id` in *every* clause, WITH CHECK
-- included. Postgres would reuse USING as the WITH CHECK where one is missing,
-- so this is equivalent today; writing it out means a later edit to one clause
-- cannot silently widen the other.
drop policy if exists "site-media admin update" on storage.objects;
create policy "site-media admin update" on storage.objects for update to authenticated
  using      (bucket_id = 'site-media' and exists (select 1 from public.admins where user_id = (select auth.uid())))
  with check (bucket_id = 'site-media' and exists (select 1 from public.admins where user_id = (select auth.uid())));
drop policy if exists "cv-uploads admin all" on storage.objects;
create policy "cv-uploads admin all" on storage.objects for all to authenticated
  using      (bucket_id = 'cv-uploads' and exists (select 1 from public.admins where user_id = (select auth.uid())))
  with check (bucket_id = 'cv-uploads' and exists (select 1 from public.admins where user_id = (select auth.uid())));

-- ...and the clause scoping above is necessary but not sufficient, which is
-- why this trigger exists. Permissive policies OR together *per phase*, and an
-- UPDATE tests USING against the OLD row and WITH CHECK against the NEW one.
-- So `update storage.objects set bucket_id = 'site-media' where bucket_id =
-- 'cv-uploads'` passes USING via the cv-uploads policy and WITH CHECK via the
-- site-media policy: an admin could walk the private CV into the public
-- bucket (verified live before this was added). No arrangement of permissive
-- policies can express "the bucket must not change" -- RLS cannot compare OLD
-- to NEW.
--
-- Nothing in this app ever moves an object between buckets (see
-- frontend/src/data/storage.js: two fixed buckets, fixed path conventions), so
-- the operation is forbidden outright for the roles the API can reach.
-- `service_role` (the backend's secret key) and `supabase_storage_admin`
-- (Storage's own service role, for its internal maintenance) are exempt. The
-- function lives in `public` because this project cannot create objects in the
-- `storage` schema -- it can create the trigger.
create or replace function public.storage_objects_bucket_lock()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  if new.bucket_id is distinct from old.bucket_id
     and current_user not in ('service_role', 'supabase_storage_admin')
     and auth.role() is distinct from 'service_role'
  then
    raise exception
      'storage_objects_bucket_lock: objects may not be moved between buckets (% -> %)',
      old.bucket_id, new.bucket_id;
  end if;
  return new;
end;
$$;
drop trigger if exists storage_objects_bucket_lock_trigger on storage.objects;
create trigger storage_objects_bucket_lock_trigger
  before update on storage.objects
  for each row execute function public.storage_objects_bucket_lock();
