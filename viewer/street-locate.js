/**
 * Resolve the nearest named OSM street for a world (x, z) position.
 * roads.json points are Blender XY; Three.js uses z = -y.
 */

const SIDEWALK_M = 7;
const HOLD_FRAMES = 4;
const MIN_ANNOUNCE_MS = 400;

function distToSegment2(px, pz, ax, az, bx, bz) {
  const abx = bx - ax;
  const abz = bz - az;
  const apx = px - ax;
  const apz = pz - az;
  const ab2 = abx * abx + abz * abz;
  let t = ab2 > 1e-8 ? (apx * abx + apz * abz) / ab2 : 0;
  if (t < 0) t = 0;
  else if (t > 1) t = 1;
  const cx = ax + abx * t;
  const cz = az + abz * t;
  const dx = px - cx;
  const dz = pz - cz;
  return dx * dx + dz * dz;
}

export async function createStreetLocator(opts = {}) {
  const roadsUrl = opts.roadsUrl || "./roads.json";
  const sidewalkM = opts.sidewalkM ?? SIDEWALK_M;
  /** @type {{ name: string, half: number, segments: Float32Array }[]} */
  const named = [];

  try {
    const res = await fetch(roadsUrl);
    if (res.ok) {
      const data = await res.json();
      for (const road of data.roads || []) {
        const name = String(road.name || "").trim();
        if (!name) continue;
        const pts = road.points || [];
        if (pts.length < 2) continue;
        const half = (Number(road.width) || 6) * 0.5 + sidewalkM;
        const segs = new Float32Array((pts.length - 1) * 4);
        for (let i = 0; i < pts.length - 1; i++) {
          const a = pts[i];
          const b = pts[i + 1];
          const ax = Array.isArray(a) ? a[0] : a.x || 0;
          const ay = Array.isArray(a) ? a[1] : a.y || 0;
          const bx = Array.isArray(b) ? b[0] : b.x || 0;
          const by = Array.isArray(b) ? b[1] : b.y || 0;
          const o = i * 4;
          segs[o] = ax;
          segs[o + 1] = -ay;
          segs[o + 2] = bx;
          segs[o + 3] = -by;
        }
        named.push({ name, half, segments: segs });
      }
    }
  } catch {
    console.warn("StreetLocator: could not load roads");
  }

  let current = "";
  let pending = "";
  let pendingCount = 0;
  let lastAnnounce = -Infinity;

  function locate(x, z) {
    let bestName = "";
    let bestD2 = Infinity;
    for (const road of named) {
      const maxD2 = road.half * road.half;
      const segs = road.segments;
      for (let i = 0; i < segs.length; i += 4) {
        const d2 = distToSegment2(x, z, segs[i], segs[i + 1], segs[i + 2], segs[i + 3]);
        if (d2 <= maxD2 && d2 < bestD2) {
          bestD2 = d2;
          bestName = road.name;
        }
      }
    }
    return bestName || null;
  }

  /**
   * @returns {{ street: string|null, changed: boolean }}
   */
  function update(x, z) {
    const hit = locate(x, z);
    if (!hit) {
      pending = "";
      pendingCount = 0;
      return { street: current || null, changed: false };
    }
    if (hit === current) {
      pending = "";
      pendingCount = 0;
      return { street: current, changed: false };
    }
    if (hit === pending) {
      pendingCount += 1;
    } else {
      pending = hit;
      pendingCount = 1;
    }
    const now = performance.now();
    if (pendingCount >= HOLD_FRAMES && now - lastAnnounce >= MIN_ANNOUNCE_MS) {
      current = hit;
      pending = "";
      pendingCount = 0;
      lastAnnounce = now;
      return { street: current, changed: true };
    }
    return { street: current || null, changed: false };
  }

  return { locate, update, get current() { return current || null; } };
}
