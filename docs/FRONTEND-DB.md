# Frontend ↔ Database (Supabase)

**For the frontend developer.** All HCT site content lives in a Supabase
database. You can build the site however you like — plain HTML/JS, React, Next,
Vue, Svelte, Astro, even a native app — and just read the data from the database.
You do **not** need this repo, the backend, the scraper, or any secret. The data
is **read-only** and protected by row-level security, so the key below is safe to
ship in your app.

> The existing `frontend/` (static HTML + `hct-render/`) is one example consumer.
> You can ignore it entirely and start fresh; the database is the only contract.

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
The 5 most recent publications, for a "Latest" / highlights strip.
| column | type | notes |
| ------ | ---- | ----- |
| `title` | string | |
| `authors` | string[] | |
| `year` | number | |
| `date_label` | string | display label, e.g. `"2022"` |
| `blurb` | string \| null | AI-written, 1–2 sentences |
| `position` | number | `0` = newest |

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
`image`, `sort_order`.
```js
const { data } = await sb.from("research").select("*").order("sort_order");
```

### `site_content`
Key/value blurbs for the prose sections. `key` (string), `value` (object:
`{ title, text }`). Available keys: `vision`, `innovation`, `contact`,
`land_acknowledgment`, `edi`, `sponsors`, `opportunities`.
```js
const { data } = await sb.from("site_content")
  .select("value").eq("key", "vision").maybeSingle();
// data.value.title, data.value.text
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
