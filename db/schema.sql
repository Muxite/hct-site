-- HCT site schema: all site data lives here so the frontend only needs the
-- project URL + publishable key. Writes happen only via the backend secret /
-- service-role key (which bypasses RLS); the public roles get read-only access.
--
-- Security model (see Supabase RLS guidance):
--   * RLS enabled on every table in the public schema.
--   * One SELECT policy per table for anon + authenticated (USING true) — the
--     whole site is public read.
--   * NO insert/update/delete policies -> anon/publishable clients cannot write.
--   * Explicit GRANT SELECT to anon/authenticated (new tables are not always
--     auto-exposed to the Data API).
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
-- update policy below, backed by a BEFORE UPDATE trigger that raises if any
-- non-whitelisted column differs between OLD and NEW. Gated on
-- `auth.role() = 'authenticated'` so backend service-role writes (which
-- legitimately touch every other column, e.g. sync_content.py) never trip
-- this guard -- it only fires for edits made through a logged-in Supabase
-- Auth session (i.e. the admin UI). `search_path` is pinned per the
-- function-search-path-mutable advisory.
create or replace function public.research_admin_guard()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  if auth.role() = 'authenticated' then
    if new.id is distinct from old.id
       or new.title is distinct from old.title
       or new.description is distinct from old.description
       or new.link is distinct from old.link
       or new.image is distinct from old.image
       or new.sort_order is distinct from old.sort_order
       or new.kind is distinct from old.kind
       or new.slug is distinct from old.slug
    then
      raise exception 'research_admin_guard: admin update may only change summary, hero_image, tagline';
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
begin
  if auth.role() = 'authenticated' then
    if new.id is distinct from old.id
       or new.slug is distinct from old.slug
       or new.title is distinct from old.title
       or new.authors is distinct from old.authors
       or new.year is distinct from old.year
       or new.type is distinct from old.type
       or new.venue is distinct from old.venue
       or new.link is distinct from old.link
       or new.bibtex is distinct from old.bibtex
       or new.description is distinct from old.description
       or new.updated_at is distinct from old.updated_at
       or new.project_slug is distinct from old.project_slug
       or new.citation_count is distinct from old.citation_count
       or new.concepts is distinct from old.concepts
       or new.oa_status is distinct from old.oa_status
    then
      raise exception 'publications_admin_guard: admin update may only change summary_plain, summary_abstract, summary_par, image';
    end if;
  end if;
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

drop policy if exists "site-media public read" on storage.objects;
create policy "site-media public read" on storage.objects for select to anon, authenticated
  using (bucket_id = 'site-media');
drop policy if exists "site-media admin write" on storage.objects;
create policy "site-media admin write" on storage.objects for insert to authenticated
  with check (bucket_id = 'site-media' and exists (select 1 from public.admins where user_id = (select auth.uid())));
drop policy if exists "site-media admin update" on storage.objects;
create policy "site-media admin update" on storage.objects for update to authenticated
  using (bucket_id = 'site-media' and exists (select 1 from public.admins where user_id = (select auth.uid())));
drop policy if exists "cv-uploads admin all" on storage.objects;
create policy "cv-uploads admin all" on storage.objects for all to authenticated
  using (bucket_id = 'cv-uploads' and exists (select 1 from public.admins where user_id = (select auth.uid())));
