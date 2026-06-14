# Frontend ↔ Database (Supabase)

**For the frontend developer.** All HCT site content lives in a Supabase
database. You can build the site however you like — plain HTML/JS, React, Next,
Vue, Svelte, Astro, even a native app — and just read the data from the database.
You do **not** need this repo, the backend, the scraper, or any secret. The data
is **read-only** and protected by row-level security, so the key below is safe to
ship in your app.

> The `frontend/` in this repo (a **React + Vite** app) is the reference
> consumer — it reads these tables with the publishable key via Vite env vars
> (`VITE_SB_URL` / `VITE_SB_PUBLISHABLE_KEY`). You can ignore it entirely and
> start fresh in any stack; the database is the only contract.

---

## 1. What you need (the only two values)

| Name | Value |
| ---- | ----- |
| Project URL | `https://uashejcjldoedqmgeujc.supabase.co` |
| Publishable key | `sb_publishable_wUyd7oNkFcArSZQnS2m2Ug_7Rt-PEkk` |

Both are **public by design** — the publishable key can only read, and only the
rows the lab has chosen to expose. Commit it, embed it in client JS, whatever.
(The *secret* key is different — it lives only in the backend's `.env` and
must never appear in frontend code.)

If the project is ever migrated, these two values are the only things that change.

---

## 2. Connecting

Pick whichever fits your stack. All three hit the same database.

### Option A — supabase-js (recommended, any framework)

Install via npm…
```bash
npm install @supabase/supabase-js
```
```js
import { createClient } from "@supabase/supabase-js";

export const sb = createClient(
  "https://uashejcjldoedqmgeujc.supabase.co",
  "sb_publishable_wUyd7oNkFcArSZQnS2m2Ug_7Rt-PEkk"
);
```

…or from a CDN with no build step:
```html
<script src="https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2"></script>
<script type="module">
  const sb = window.supabase.createClient(
    "https://uashejcjldoedqmgeujc.supabase.co",
    "sb_publishable_wUyd7oNkFcArSZQnS2m2Ug_7Rt-PEkk"
  );
  const { data } = await sb.from("publications").select("*").order("year", { ascending: false });
  console.log(data);
</script>
```

### Option B — plain `fetch` (no dependency, works anywhere)

Supabase exposes a REST API; you don't have to use the SDK.
```js
const SB_URL = "https://uashejcjldoedqmgeujc.supabase.co";
const KEY = "sb_publishable_wUyd7oNkFcArSZQnS2m2Ug_7Rt-PEkk";

const res = await fetch(
  `${SB_URL}/rest/v1/publications?select=*&order=year.desc`,
  { headers: { apikey: KEY, Authorization: `Bearer ${KEY}` } }
);
const publications = await res.json();
```

### Option C — quick check from the terminal

```bash
curl "https://uashejcjldoedqmgeujc.supabase.co/rest/v1/timeline?select=*&order=position" \
  -H "apikey: sb_publishable_wUyd7oNkFcArSZQnS2m2Ug_7Rt-PEkk"
```

---

## 3. The tables

All are read-only. Column types are plain JSON (strings, numbers, arrays,
objects), so they map straight onto whatever UI you build.

### `publications`
| column | type | notes |
| ------ | ---- | ----- |
| `slug` | string | stable unique id |
| `title` | string | |
| `authors` | string[] | ordered |
| `year` | number | |
| `type` | string | `article \| inproceedings \| preprint \| book \| incollection \| thesis \| techreport \| misc` |
| `venue` | string \| null | |
| `link` | string \| null | DOI / URL |
| `bibtex` | string \| null | |
| `description` | string \| null | AI-written, optional |

```js
const { data } = await sb.from("publications")
  .select("slug,title,authors,year,type,venue,link,description")
  .order("year", { ascending: false });
```

### `timeline`
The **full publication history**, newest first — the site's centerpiece (group
it by year to render). One row per publication.
| column | type | notes |
| ------ | ---- | ----- |
| `slug` | string \| null | -> `publications.slug` (for a detail link) |
| `title` | string | |
| `authors` | string[] | |
| `year` | number | |
| `date_label` | string | display label, e.g. `"2022"` |
| `blurb` | string \| null | AI-written, 1–2 sentences (often empty for older papers) |
| `position` | number | `0` = newest, contiguous |

```js
const { data } = await sb.from("timeline").select("*").order("position");
```

### `people`
`name`, `role`, `email`, `photo` (image path/url), `bio` (string|null, AI),
`kind` (`current` \| `alumni`), `sort_order`.
```js
const { data } = await sb.from("people").select("*").order("sort_order");
```

### `research`
`title`, `tagline` (string|null), `description` (string|null, AI), `link`,
`image`, `kind` (`current` \| `archived`), `sort_order`.
```js
const { data } = await sb.from("research").select("*").order("sort_order");
```

### `site_content`
Key/value boilerplate (sourced from the backend `site.yaml`). `key` (string),
`value` (jsonb object).
- Prose sections — `value` is `{ title, text }`. Keys: `vision`, `innovation`,
  `contact`, `land_acknowledgment`, `edi`, `sponsors`, `opportunities`.
- `site_meta` — the masthead: `value` is `{ title, subtitle, tagline, nav[] }`.
```js
// one section
const { data } = await sb.from("site_content")
  .select("value").eq("key", "vision").maybeSingle();
// data.value.title, data.value.text

// everything in one round trip (what the reference app does)
const rows = await sb.from("site_content").select("key,value");
const content = Object.fromEntries(rows.data.map((r) => [r.key, r.value]));
// content.site_meta.title, content.vision.text, ...
```

---

## 4. Common patterns

**React / Next (Server Component or client):**
```jsx
const { data: pubs } = await sb.from("publications")
  .select("*").order("year", { ascending: false });

return (
  <ul>
    {pubs.map((p) => (
      <li key={p.slug}>
        <strong>{p.title}</strong> — {p.authors.join("; ")} ({p.year})
        {p.link && <a href={p.link}> link</a>}
      </li>
    ))}
  </ul>
);
```

**Group publications by year:**
```js
const byYear = {};
for (const p of pubs) (byYear[p.year] ??= []).push(p);
// Object.keys(byYear).sort((a, b) => b - a)  -> newest first
```

**Filtering / paging** (PostgREST query params via supabase-js):
```js
sb.from("publications").select("*").eq("year", 2022);          // one year
sb.from("publications").select("*").ilike("title", "%speech%"); // search
sb.from("publications").select("*").range(0, 19);               // first 20
```

---

## 5. Rules of the road

- **Read-only.** The publishable key can only `SELECT`. Any insert/update/delete
  from the browser is rejected by row-level security (HTTP 401) — that's expected,
  not a bug. New data is written by the lab's backend with a separate secret key.
- **Content refreshes itself.** When the lab re-runs the backend, the rows update
  in place. Your site always shows the current data with no redeploy.
- **Always set an `order`** for lists you care about (`year desc` for
  publications, `position`/`sort_order` for the rest) — the database doesn't
  guarantee row order otherwise.
- **Empty is normal.** If a query returns `[]`, the table just has no rows yet;
  render a graceful fallback rather than erroring.
