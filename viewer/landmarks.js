/**
 * Heritage landmark sighting: nearest mesh-kit / memorial POI from landmarks.json
 * (Blender XY → Three XZ with z = −y). Used for GTA-style captions and map pins.
 */

const LANDMARKS_URL = "./landmarks.json";
const REACH_M = 28;

export async function createLandmarkLocator(opts = {}) {
  const reach = opts.reach ?? REACH_M;
  const reach2 = reach * reach;
  let pois = [];
  try {
    const res = await fetch(LANDMARKS_URL);
    if (res.ok) {
      const data = await res.json();
      pois = (data.landmarks || []).map((p) => ({
        id: String(p.id),
        name: p.name,
        kind: p.kind || "landmark",
        x: Number(p.x),
        z: -Number(p.y),
        r2: reach2,
      })).filter((p) => Number.isFinite(p.x) && Number.isFinite(p.z) && p.name);
    }
  } catch {
    console.warn("[cityview] landmarks: could not load landmarks.json");
  }

  let current = null;
  const seen = new Set();

  function update(x, z) {
    let best = null;
    let bestD = Infinity;
    for (const p of pois) {
      const dx = x - p.x;
      const dz = z - p.z;
      const d2 = dx * dx + dz * dz;
      if (d2 <= p.r2 && d2 < bestD) {
        bestD = d2;
        best = p;
      }
    }
    const id = best ? best.id : null;
    const changed = id !== current;
    current = id;
    let firstVisit = false;
    if (changed && best && !seen.has(best.id)) {
      seen.add(best.id);
      firstVisit = true;
    }
    return { landmark: best, changed, firstVisit };
  }

  return { update, pois, count: pois.length };
}
