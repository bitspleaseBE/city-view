/**
 * Static street props (props.json from cityview.props: tree trunks, posts, benches, bike
 * racks, fences / walls) plus moving cars, buses and trams as solids for the player.
 *
 * Everything is a circle, an oriented box or a thick segment in Three XZ (Blender XY with
 * z = −y). A uniform grid keeps the per-frame query to the handful of props nearby.
 */

const URL_PROPS = "./props.json";
const CELL = 8;

export async function createPropCollider() {
  let data = { trunks: [], boxes: [], segments: [] };
  try {
    const res = await fetch(URL_PROPS);
    if (res.ok) data = await res.json();
  } catch (err) {
    console.warn("props.json unavailable", err);
  }
  const grid = new Map();
  const key = (gx, gz) => gx * 73856093 + gz * 19349663;
  const insert = (item, minX, minZ, maxX, maxZ) => {
    for (let gx = Math.floor(minX / CELL); gx <= Math.floor(maxX / CELL); gx++) {
      for (let gz = Math.floor(minZ / CELL); gz <= Math.floor(maxZ / CELL); gz++) {
        const k = key(gx, gz);
        let list = grid.get(k);
        if (!list) grid.set(k, (list = []));
        list.push(item);
      }
    }
  };
  for (const [x, y, r] of data.trunks || []) {
    const it = { t: 0, x, z: -y, r };
    insert(it, x - r, -y - r, x + r, -y + r);
  }
  for (const [x, y, yaw, hl, hd] of data.boxes || []) {
    // Blender yaw rotates local +X (the long side) about +Z; in Three XZ that is (cos, −sin).
    const it = { t: 1, x, z: -y, ax: Math.cos(yaw), az: -Math.sin(yaw), hl, hd };
    const e = hl + hd;
    insert(it, x - e, -y - e, x + e, -y + e);
  }
  for (const [x0, y0, x1, y1, ht] of data.segments || []) {
    const it = { t: 2, x0, z0: -y0, x1, z1: -y1, ht };
    insert(it, Math.min(x0, x1) - ht, Math.min(-y0, -y1) - ht, Math.max(x0, x1) + ht, Math.max(-y0, -y1) + ht);
  }

  const seen = new Set();

  /** Push `pos` out of a box (centre cx/cz, unit axis ax/az, half extents hl/hw) grown by r. */
  function pushBox(pos, cx, cz, ax, az, hl, hw, r) {
    const dx = pos.x - cx;
    const dz = pos.z - cz;
    const a = dx * ax + dz * az;
    const b = dx * -az + dz * ax;
    const pa = hl + r - Math.abs(a);
    const pb = hw + r - Math.abs(b);
    if (pa <= 0 || pb <= 0) return false;
    if (pa < pb) {
      const s = Math.sign(a) || 1;
      pos.x += ax * pa * s;
      pos.z += az * pa * s;
    } else {
      const s = Math.sign(b) || 1;
      pos.x += -az * pb * s;
      pos.z += ax * pb * s;
    }
    return true;
  }

  function pushCircle(pos, cx, cz, R) {
    const dx = pos.x - cx;
    const dz = pos.z - cz;
    const d2 = dx * dx + dz * dz;
    if (d2 >= R * R) return false;
    const d = Math.sqrt(d2) || 1e-4;
    pos.x = cx + (dx / d) * R;
    pos.z = cz + (dz / d) * R;
    return true;
  }

  function pushSegment(pos, it, r) {
    const vx = it.x1 - it.x0;
    const vz = it.z1 - it.z0;
    const ll = vx * vx + vz * vz || 1e-6;
    const t = Math.max(0, Math.min(1, ((pos.x - it.x0) * vx + (pos.z - it.z0) * vz) / ll));
    return pushCircle(pos, it.x0 + vx * t, it.z0 + vz * t, it.ht + r);
  }

  return {
    counts: {
      trunks: (data.trunks || []).length,
      boxes: (data.boxes || []).length,
      segments: (data.segments || []).length,
    },
    /** Slide `pos` (x/z) out of every static prop within reach. Returns true on contact. */
    resolveStatic(pos, r) {
      seen.clear();
      let hit = false;
      const gx0 = Math.floor((pos.x - r) / CELL);
      const gx1 = Math.floor((pos.x + r) / CELL);
      const gz0 = Math.floor((pos.z - r) / CELL);
      const gz1 = Math.floor((pos.z + r) / CELL);
      for (let gx = gx0; gx <= gx1; gx++) {
        for (let gz = gz0; gz <= gz1; gz++) {
          const list = grid.get(key(gx, gz));
          if (!list) continue;
          for (const it of list) {
            if (seen.has(it)) continue;
            seen.add(it);
            if (it.t === 0) hit = pushCircle(pos, it.x, it.z, it.r + r) || hit;
            else if (it.t === 1) hit = pushBox(pos, it.x, it.z, it.ax, it.az, it.hl, it.hd, r) || hit;
            else hit = pushSegment(pos, it, r) || hit;
          }
        }
      }
      return hit;
    },
    /** Vehicles: [{ pos, tan, hl, hw }] with tan a unit XZ heading. */
    resolveVehicles(pos, r, vehicles) {
      let hit = false;
      for (const v of vehicles) {
        const dx = pos.x - v.pos.x;
        const dz = pos.z - v.pos.z;
        const reach = v.hl + r;
        if (dx * dx + dz * dz > reach * reach) continue;
        const len = Math.hypot(v.tan.x, v.tan.z) || 1;
        hit = pushBox(pos, v.pos.x, v.pos.z, v.tan.x / len, v.tan.z / len, v.hl, v.hw, r) || hit;
      }
      return hit;
    },
  };
}
