/**
 * One network fetch + one JSON.parse per URL, shared by every module that needs
 * `roads.json` / `buildings.json` (traffic, micromobility, scooters, pedestrians, outdoors,
 * minimap, street locator). Returns a Response-like `{ ok, status, json() }` so call sites only
 * swap `fetch(url)` for `fetchJsonCached(url)`. The parsed object is shared — treat it as
 * read-only. Failures are not cached, so a later caller can retry.
 *
 * Only the fixed same-directory files below are served (never caller-controlled hosts).
 */
const cache = new Map();

/** Literal-URL fetchers: the request target is never derived from caller input. */
function rawFetch(key) {
  switch (key) {
    case "./roads.json":
      return fetch("./roads.json");
    case "./buildings.json":
      return fetch("./buildings.json");
    default:
      return null;
  }
}
const KNOWN = new Set(["./roads.json", "./buildings.json"]);
const resolveUrl = (url) => (KNOWN.has(String(url)) ? String(url) : null);

export function fetchJsonCached(url) {
  const key = resolveUrl(url);
  if (!key) return Promise.resolve({ ok: false, status: 400, json: async () => null });
  let p = cache.get(key);
  if (!p) {
    p = (async () => {
      const res = await rawFetch(key);
      if (!res.ok) return { ok: false, status: res.status, data: null };
      return { ok: true, status: res.status, data: await res.json() };
    })();
    cache.set(key, p);
    p.then(
      (r) => {
        if (!r.ok) cache.delete(key);
      },
      () => cache.delete(key),
    );
  }
  return p.then((r) => ({ ok: r.ok, status: r.status, json: async () => r.data }));
}
