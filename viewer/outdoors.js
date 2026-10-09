/**
 * Keep the walker outdoors: building footprints (empty extruded boxes) are
 * solid volumes with no interior. Rings come from buildings.json (Blender XY);
 * Three.js uses z = -y, same as roads.json / street-locate.js.
 */

function pointInRing(x, z, ring) {
  let inside = false;
  const n = ring.length / 2;
  for (let i = 0; i < n; i++) {
    const j = (i + 1) % n;
    const x1 = ring[i * 2];
    const z1 = ring[i * 2 + 1];
    const x2 = ring[j * 2];
    const z2 = ring[j * 2 + 1];
    if ((z1 > z) !== (z2 > z) && x < ((x2 - x1) * (z - z1)) / ((z2 - z1) || 1e-12) + x1) {
      inside = !inside;
    }
  }
  return inside;
}

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
  return { d2: dx * dx + dz * dz, x: cx, z: cz, yaw: Math.atan2(-(bz - az), bx - ax) };
}

/**
 * @param {{ buildingsUrl?: string, roadsUrl?: string }} [opts]
 * opts URL overrides are ignored — only same-origin `./buildings.json` / `./roads.json`.
 */
export async function createOutdoorsGuard(_opts = {}) {
  /** @type {{ minX: number, maxX: number, minZ: number, maxZ: number, ring: Float32Array }[]} */
  const buildings = [];
  /** @type {Float32Array[]} */
  const roadSegs = [];

  try {
    const res = await fetch("./buildings.json");
    if (res.ok) {
      const data = await res.json();
      for (const b of data.buildings || []) {
        const pts = b.ring || [];
        if (pts.length < 3) continue;
        const ring = new Float32Array(pts.length * 2);
        let minX = Infinity;
        let maxX = -Infinity;
        let minZ = Infinity;
        let maxZ = -Infinity;
        for (let i = 0; i < pts.length; i++) {
          const p = pts[i];
          const x = Array.isArray(p) ? Number(p[0]) : Number(p.x) || 0;
          const y = Array.isArray(p) ? Number(p[1]) : Number(p.y) || 0;
          const z = -y;
          ring[i * 2] = x;
          ring[i * 2 + 1] = z;
          if (x < minX) minX = x;
          if (x > maxX) maxX = x;
          if (z < minZ) minZ = z;
          if (z > maxZ) maxZ = z;
        }
        buildings.push({ minX, maxX, minZ, maxZ, ring });
      }
    }
  } catch {
    console.warn("OutdoorsGuard: could not load buildings.json");
  }

  try {
    const res = await fetch("./roads.json");
    if (res.ok) {
      const data = await res.json();
      for (const road of data.roads || []) {
        const pts = road.points || [];
        if (pts.length < 2) continue;
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
        roadSegs.push(segs);
      }
    }
  } catch {
    console.warn("OutdoorsGuard: could not load roads.json");
  }

  function insideBuilding(x, z) {
    for (const b of buildings) {
      if (x < b.minX || x > b.maxX || z < b.minZ || z > b.maxZ) continue;
      if (pointInRing(x, z, b.ring)) return true;
    }
    return false;
  }

  function nearestRoadPose(x, z) {
    let best = Infinity;
    let sx = x;
    let sz = z;
    let yaw = 0;
    for (const segs of roadSegs) {
      for (let i = 0; i < segs.length; i += 4) {
        const hit = distToSegment2(x, z, segs[i], segs[i + 1], segs[i + 2], segs[i + 3]);
        if (hit.d2 < best) {
          best = hit.d2;
          sx = hit.x;
          sz = hit.z;
          yaw = hit.yaw;
        }
      }
    }
    return { x: sx, z: sz, yaw, d2: best };
  }

  /**
   * If (x,z) is inside / against a building, snap to the nearest road centreline.
   * @returns {{ x: number, z: number, yaw: number, snapped: boolean }}
   */
  function snapOutdoors(x, z, yaw = 0) {
    if (!buildings.length) return { x, z, yaw, snapped: false };
    if (!insideBuilding(x, z)) return { x, z, yaw, snapped: false };
    if (!roadSegs.length) return { x, z, yaw, snapped: false };
    const pose = nearestRoadPose(x, z);
    // Prefer road yaw when we had to relocate; keep caller yaw if already outdoors.
    return { x: pose.x, z: pose.z, yaw: pose.yaw, snapped: true };
  }

  /** Mutate a {x,z} / Vector3-like position onto the street if needed. */
  function ensureOutdoors(pos, yawHolder = null) {
    const out = snapOutdoors(pos.x, pos.z, yawHolder ? yawHolder.yaw : 0);
    if (out.snapped) {
      pos.x = out.x;
      pos.z = out.z;
      if (yawHolder && typeof yawHolder.yaw === "number") yawHolder.yaw = out.yaw;
    }
    return out.snapped;
  }

  /**
   * After a walk step: if the new position is inside a building, slide along
   * the façade (keep X or Z) or fully revert. Never leave the camera indoors.
   */
  function rejectIfIndoors(pos, before) {
    if (!buildings.length || !insideBuilding(pos.x, pos.z)) return false;
    const tryX = { x: pos.x, z: before.z };
    const tryZ = { x: before.x, z: pos.z };
    if (!insideBuilding(tryX.x, tryX.z)) {
      pos.x = tryX.x;
      pos.z = tryX.z;
    } else if (!insideBuilding(tryZ.x, tryZ.z)) {
      pos.x = tryZ.x;
      pos.z = tryZ.z;
    } else {
      pos.x = before.x;
      pos.z = before.z;
    }
    if (insideBuilding(pos.x, pos.z)) {
      const out = snapOutdoors(pos.x, pos.z);
      pos.x = out.x;
      pos.z = out.z;
    }
    return true;
  }

  return {
    ready: buildings.length > 0,
    count: buildings.length,
    insideBuilding,
    snapOutdoors,
    ensureOutdoors,
    rejectIfIndoors,
  };
}
