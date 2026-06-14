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

-- ---------------------------------------------------------------------------
-- publications: the structured paper list (replaces publications.yaml).
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
  description text,                            -- AI-written, lab voice (optional)
  updated_at  timestamptz not null default now()
);
create index if not exists publications_year_idx on public.publications (year desc);

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
-- research: research areas/projects (synced from research.yaml; AI fills the
-- blank taglines into a longer description).
-- ---------------------------------------------------------------------------
create table if not exists public.research (
  id          uuid primary key default gen_random_uuid(),
  title       text not null,
  tagline     text,
  description text,                            -- AI-written when missing
  link        text,
  image       text,
  kind        text not null default 'current', -- 'current' | 'archived'
  sort_order  int  not null default 0
);
create index if not exists research_sort_idx on public.research (sort_order);

-- Migration (run in the SQL editor on projects created before research.kind
-- existed): projects gain a current/archived kind for the "Past projects"
-- group, mirroring people.kind.
alter table public.research
  add column if not exists kind text not null default 'current';
alter table public.research
  drop constraint if exists research_kind_check;
alter table public.research
  add constraint research_kind_check check (kind in ('current', 'archived'));
create index if not exists research_kind_idx on public.research (kind);

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
alter table public.publications enable row level security;
alter table public.timeline     enable row level security;
alter table public.people       enable row level security;
alter table public.research     enable row level security;
alter table public.site_content enable row level security;

create policy "public read" on public.publications for select to anon, authenticated using (true);
create policy "public read" on public.timeline     for select to anon, authenticated using (true);
create policy "public read" on public.people       for select to anon, authenticated using (true);
create policy "public read" on public.research     for select to anon, authenticated using (true);
create policy "public read" on public.site_content for select to anon, authenticated using (true);

-- Expose to the Data API (read only). Writes are done with the secret key,
-- which bypasses RLS and these grants.
grant select on public.publications to anon, authenticated;
grant select on public.timeline     to anon, authenticated;
grant select on public.people       to anon, authenticated;
grant select on public.research     to anon, authenticated;
grant select on public.site_content to anon, authenticated;
