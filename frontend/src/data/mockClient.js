/**
 * Offline mock of the supabase-js client used by db.js. Enabled at build time
 * with VITE_MOCK=1, so the site renders a snapshot of the live Supabase data
 * with no network and no keys. It implements only the tiny query-builder
 * surface db.js actually uses:
 *
 *   from(table).select(cols, {count}).order(col).order(col2).range(a,b) -> {data,error,count}
 *   from(table).select(cols).eq(col, val).maybeSingle()                 -> {data,error}
 *   from(table).select(cols).in(col, values)                            -> {data,error}
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
  let eqCol = null;
  let eqVal;
  let inCol = null;
  let inVals = null;
  const sorts = [];
  let range = null;

  const rows = async () => {
    let out = (await snapshot())[table] || [];
    if (eqCol !== null) out = out.filter((r) => r[eqCol] === eqVal);
    if (inCol !== null) out = out.filter((r) => inVals.includes(r[inCol]));
    for (const { col, ascending } of sorts) {
      out = [...out].sort((a, z) => {
        const x = a[col];
        const y = z[col];
        if (x === y) return 0;
        return (x > y ? 1 : -1) * (ascending ? 1 : -1);
      });
    }
    const total = out.length;
    if (range) out = out.slice(range[0], range[1] + 1);
    return { out, total };
  };

  const b = {
    select() {
      return b;
    },
    eq(c, v) {
      eqCol = c;
      eqVal = v;
      return b;
    },
    in(c, vals) {
      inCol = c;
      inVals = vals;
      return b;
    },
    order(c, { ascending: asc = true } = {}) {
      sorts.push({ col: c, ascending: asc });
      return b;
    },
    range(from, to) {
      range = [from, to];
      return b;
    },
    maybeSingle() {
      return rows().then(({ out }) => ({ data: out[0] ?? null, error: null }));
    },
    // Thenable: `await client.from(t).select(c).order(...)` resolves here.
    then(resolve, reject) {
      rows().then(
        ({ out, total }) => resolve({ data: out, error: null, count: total }),
        reject,
      );
    },
  };
  return b;
}

export function createMockClient() {
  return { from: (table) => builder(table) };
}
