/**
 * Tiny uniform XZ cell grid for cheap proximity prefilters (peds, obstacles, …).
 *
 * Rebuilt once per frame: `clear()`, `insert(item, x, z)` for each item, then
 * `query(x, z, r, out)` returns every item whose *cell* overlaps the circle — callers still
 * do their exact distance / corridor tests, so collision behaviour is unchanged; only the
 * candidate set shrinks. Buckets are pooled so a steady-state frame allocates nothing.
 */
export const CELL_M = 24; // 20–30 m: ≥ the longest per-vehicle ped/obstacle reach we care about

export function createCellGrid(cell = CELL_M) {
  const inv = 1 / cell;
  const buckets = new Map();
  const used = [];
  const pool = [];
  let size = 0;

  const key = (cx, cz) => (cx + 4096) * 8192 + (cz + 4096);

  function clear() {
    for (let i = 0; i < used.length; i++) {
      const b = used[i];
      b.length = 0;
      pool.push(b);
    }
    used.length = 0;
    buckets.clear();
    size = 0;
  }

  function insert(item, x, z) {
    const k = key(Math.floor(x * inv), Math.floor(z * inv));
    let b = buckets.get(k);
    if (!b) {
      b = pool.pop() || [];
      buckets.set(k, b);
      used.push(b);
    }
    b.push(item);
    size++;
  }

  /** Fill `out` (cleared first) with items in cells overlapping the circle (x, z, r). */
  function query(x, z, r, out) {
    out.length = 0;
    if (!size) return out;
    const c0 = Math.floor((x - r) * inv);
    const c1 = Math.floor((x + r) * inv);
    const r0 = Math.floor((z - r) * inv);
    const r1 = Math.floor((z + r) * inv);
    for (let cx = c0; cx <= c1; cx++) {
      for (let cz = r0; cz <= r1; cz++) {
        const b = buckets.get(key(cx, cz));
        if (!b) continue;
        for (let i = 0; i < b.length; i++) out.push(b[i]);
      }
    }
    return out;
  }

  return {
    clear,
    insert,
    query,
    get size() {
      return size;
    },
  };
}
