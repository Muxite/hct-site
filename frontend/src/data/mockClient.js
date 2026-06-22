/**
 * Offline mock of the supabase-js client used by db.js. Enabled at build time
 * with VITE_MOCK=1, so the site renders a snapshot of the live Supabase data
 * with no network and no keys. It implements only the tiny query-builder
 * surface db.js actually uses:
 *
 *   from(table).select(cols).order(col, {ascending})    -> await -> {data,error}
 *   from(table).select(cols).eq(col, val).maybeSingle() -> {data,error}
 *
 * `select(cols)` is a no-op (the snapshot rows already carry every column). The
 * snapshot is dynamically imported (a lazy chunk), so a normal live-Supabase
 * build's main bundle never includes it.
 */
let _snapshot = null;
async function snapshot() {
  if (!_snapshot) _snapshot = (await import("./snapshot.json")).default;
  return _snapshot;
}

function builder(table) {
  let col = null;
  let val;
  let sortCol = null;
  let ascending = true;

  const rows = async () => {
    let out = (await snapshot())[table] || [];
    if (col !== null) out = out.filter((r) => r[col] === val);
    if (sortCol !== null) {
      out = [...out].sort((a, z) => {
        const x = a[sortCol];
        const y = z[sortCol];
        if (x === y) return 0;
        return (x > y ? 1 : -1) * (ascending ? 1 : -1);
      });
    }
    return out;
  };

  const b = {
    select() {
      return b;
    },
    eq(c, v) {
      col = c;
      val = v;
      return b;
    },
    order(c, { ascending: asc = true } = {}) {
      sortCol = c;
      ascending = asc;
      return b;
    },
    maybeSingle() {
      return rows().then((out) => ({ data: out[0] ?? null, error: null }));
    },
    // Thenable: `await client.from(t).select(c).order(...)` resolves here.
    then(resolve, reject) {
      rows().then((out) => resolve({ data: out, error: null }), reject);
    },
  };
  return b;
}

export function createMockClient() {
  return { from: (table) => builder(table) };
}
