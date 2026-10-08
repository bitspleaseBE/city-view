/**
 * Runtime GTA3-simple traffic: box cars follow OSM road centrelines
 * with car-to-car / player following-distance avoidance.
 */

const CAR_COUNT = 18;
const BASE_SPEED = 9.5;
const FOLLOW_DIST = 8;
const PLAYER_STOP_DIST = 4;
const SNAP_M = 11;
const LANE_OFFSET = 1.15;
const BODY_COLORS = [0xc45c48, 0x3d5a80, 0xd4a373, 0x4a5568, 0xb8b0a4, 0x2f6f5e];

function blenderToThree(x, y, out) {
  out.set(x, 0, -y);
  return out;
}

function buildPaths(roads, THREE) {
  const paths = [];
  for (const road of roads) {
    const pts = road.points || [];
    if (pts.length < 2) continue;
    const points = [];
    for (const p of pts) {
      points.push(blenderToThree(p[0], p[1], new THREE.Vector3()));
    }
    // Deduplicate consecutive duplicates
    const cleaned = [points[0]];
    for (let i = 1; i < points.length; i++) {
      if (cleaned[cleaned.length - 1].distanceToSquared(points[i]) > 0.05) {
        cleaned.push(points[i]);
      }
    }
    if (cleaned.length < 2) continue;
    const cumulative = [0];
    let len = 0;
    for (let i = 1; i < cleaned.length; i++) {
      len += cleaned[i].distanceTo(cleaned[i - 1]);
      cumulative.push(len);
    }
    if (len < 4) continue;
    paths.push({
      id: road.id,
      width: road.width || 6,
      points: cleaned,
      cumulative,
      length: len,
      start: cleaned[0],
      end: cleaned[cleaned.length - 1],
    });
  }
  return paths;
}

function samplePath(path, s, THREE, outPos, outTan) {
  const dist = Math.max(0, Math.min(path.length, s));
  const cum = path.cumulative;
  let i = 1;
  while (i < cum.length && cum[i] < dist) i++;
  const i0 = Math.max(0, i - 1);
  const i1 = Math.min(path.points.length - 1, i);
  const segStart = cum[i0];
  const segLen = Math.max(1e-6, cum[i1] - segStart);
  const t = (dist - segStart) / segLen;
  const a = path.points[i0];
  const b = path.points[i1];
  outPos.lerpVectors(a, b, t);
  outTan.subVectors(b, a);
  if (outTan.lengthSq() < 1e-8) {
    outTan.set(1, 0, 0);
  } else {
    outTan.normalize();
  }
  // Right-hand lane offset
  const rx = outTan.z;
  const rz = -outTan.x;
  outPos.x += rx * LANE_OFFSET;
  outPos.z += rz * LANE_OFFSET;
  outPos.y = 0.75;
}

function makeSharedParts(THREE) {
  return {
    bodyGeo: new THREE.BoxGeometry(1.75, 1.35, 4.2),
    cabinGeo: new THREE.BoxGeometry(1.55, 0.65, 2.0),
    wheelGeo: new THREE.BoxGeometry(0.22, 0.45, 0.55),
    glassMat: new THREE.MeshLambertMaterial({ color: 0x88a0b8, transparent: true, opacity: 0.75 }),
    tireMat: new THREE.MeshLambertMaterial({ color: 0x1a1a1a }),
    bodyMats: BODY_COLORS.map((c) => new THREE.MeshLambertMaterial({ color: c })),
  };
}

function makeCarMesh(THREE, parts, colorIndex) {
  const group = new THREE.Group();
  // Length along local +Z (Three.js forward for yaw)
  const body = new THREE.Mesh(parts.bodyGeo, parts.bodyMats[colorIndex % parts.bodyMats.length]);
  const cabin = new THREE.Mesh(parts.cabinGeo, parts.glassMat);
  cabin.position.set(0, 0.7, 0.1);
  group.add(body, cabin);
  for (const [lx, lz] of [
    [0.85, 1.35],
    [-0.85, 1.35],
    [0.85, -1.35],
    [-0.85, -1.35],
  ]) {
    const wheel = new THREE.Mesh(parts.wheelGeo, parts.tireMat);
    wheel.position.set(lx, -0.45, lz);
    group.add(wheel);
  }
  return group;
}

function pickNextPath(paths, path, atEnd, THREE) {
  const tip = atEnd ? path.end : path.start;
  const candidates = [];
  for (let i = 0; i < paths.length; i++) {
    const other = paths[i];
    if (other === path) continue;
    const dStart = tip.distanceTo(other.start);
    const dEnd = tip.distanceTo(other.end);
    if (dStart < SNAP_M) candidates.push({ index: i, reverse: false, d: dStart });
    if (dEnd < SNAP_M) candidates.push({ index: i, reverse: true, d: dEnd });
  }
  if (!candidates.length) {
    // U-turn on same path
    return { index: paths.indexOf(path), reverse: !atEnd ? false : true, flip: true };
  }
  candidates.sort((a, b) => a.d - b.d);
  const pool = candidates.slice(0, Math.min(4, candidates.length));
  return pool[(Math.random() * pool.length) | 0];
}

function createCar(paths, THREE, parts) {
  const index = (Math.random() * paths.length) | 0;
  const path = paths[index];
  const reverse = Math.random() < 0.5;
  const s = Math.random() * path.length * 0.85;
  const colorIndex = (Math.random() * BODY_COLORS.length) | 0;
  const mesh = makeCarMesh(THREE, parts, colorIndex);
  const speed = BASE_SPEED * (0.85 + Math.random() * 0.35);
  return {
    mesh,
    pathIndex: index,
    reverse,
    s,
    speed,
    velocity: speed,
    pos: new THREE.Vector3(),
    tan: new THREE.Vector3(),
    lateral: 0,
  };
}

function placeCar(car, paths, THREE) {
  const path = paths[car.pathIndex];
  const s = car.reverse ? path.length - car.s : car.s;
  samplePath(path, s, THREE, car.pos, car.tan);
  if (car.reverse) {
    car.tan.multiplyScalar(-1);
  }
  if (car.lateral) {
    car.pos.x += car.tan.z * car.lateral;
    car.pos.z += -car.tan.x * car.lateral;
  }
  car.mesh.position.copy(car.pos);
  car.mesh.rotation.y = Math.atan2(car.tan.x, car.tan.z);
}

/**
 * @param {import('three').Scene} scene
 * @param {typeof import('three')} THREE
 * @param {{ url?: string, count?: number }} [opts]
 */
export async function createTraffic(scene, THREE, opts = {}) {
  const url = opts.url || "./roads.json";
  const count = opts.count ?? CAR_COUNT;
  let data;
  try {
    const res = await fetch(url);
    if (!res.ok) throw new Error(`roads.json ${res.status}`);
    data = await res.json();
  } catch (err) {
    console.warn("Traffic disabled — could not load roads:", err);
    return { update() {}, dispose() {} };
  }
  const paths = buildPaths(data.roads || [], THREE);
  if (paths.length < 2) {
    console.warn("Traffic disabled — not enough road paths");
    return { update() {}, dispose() {} };
  }

  const root = new THREE.Group();
  root.name = "RuntimeTraffic";
  scene.add(root);
  const parts = makeSharedParts(THREE);

  const cars = [];
  for (let i = 0; i < count; i++) {
    const car = createCar(paths, THREE, parts);
    // Spread spawn so cars don't stack
    let tries = 0;
    while (tries < 12) {
      placeCar(car, paths, THREE);
      const clash = cars.some((c) => c.pos.distanceToSquared(car.pos) < 64);
      if (!clash) break;
      car.pathIndex = (Math.random() * paths.length) | 0;
      car.s = Math.random() * paths[car.pathIndex].length * 0.85;
      car.reverse = Math.random() < 0.5;
      tries++;
    }
    placeCar(car, paths, THREE);
    root.add(car.mesh);
    cars.push(car);
  }

  const playerPos = new THREE.Vector3();

  function advanceJunction(car) {
    const path = paths[car.pathIndex];
    const atEnd = !car.reverse;
    const next = pickNextPath(paths, path, atEnd, THREE);
    if (next.flip) {
      car.reverse = !car.reverse;
      car.s = 0.5;
      return;
    }
    car.pathIndex = next.index;
    car.reverse = next.reverse;
    car.s = 0.5;
  }

  function update(dt, walkObject) {
    if (dt <= 0) return;
    if (walkObject) {
      playerPos.set(walkObject.position.x, 0, walkObject.position.z);
    }

    for (let i = 0; i < cars.length; i++) {
      const car = cars[i];
      placeCar(car, paths, THREE);
      let desire = car.speed;
      let lateralNudge = 0;

      for (let j = 0; j < cars.length; j++) {
        if (i === j) continue;
        const other = cars[j];
        const dx = other.pos.x - car.pos.x;
        const dz = other.pos.z - car.pos.z;
        const distSq = dx * dx + dz * dz;
        if (distSq > FOLLOW_DIST * FOLLOW_DIST * 2.5) continue;
        const dist = Math.sqrt(distSq);
        const ahead = dx * car.tan.x + dz * car.tan.z;
        const side = dx * car.tan.z + dz * -car.tan.x;
        if (ahead > 0.4 && ahead < FOLLOW_DIST + 4 && Math.abs(side) < 3.2) {
          const gap = ahead - 3.2;
          if (gap < FOLLOW_DIST) {
            const factor = Math.max(0, gap / FOLLOW_DIST);
            desire = Math.min(desire, car.speed * factor * factor);
          }
          if (Math.abs(side) < 1.8 && dist < 5) {
            lateralNudge += side > 0 ? -0.35 : 0.35;
          }
        }
      }

      if (walkObject) {
        const dx = playerPos.x - car.pos.x;
        const dz = playerPos.z - car.pos.z;
        const distSq = dx * dx + dz * dz;
        if (distSq < (PLAYER_STOP_DIST + 6) ** 2) {
          const ahead = dx * car.tan.x + dz * car.tan.z;
          const side = Math.abs(dx * car.tan.z + dz * -car.tan.x);
          if (ahead > 0.2 && ahead < PLAYER_STOP_DIST + 5 && side < 2.4) {
            const gap = ahead - 1.2;
            const factor = Math.max(0, gap / PLAYER_STOP_DIST);
            desire = Math.min(desire, car.speed * factor * factor);
          }
        }
      }

      car.velocity += (desire - car.velocity) * Math.min(1, dt * 4);
      if (car.velocity < 0.15) car.velocity = 0;
      car.lateral += (lateralNudge - car.lateral) * Math.min(1, dt * 3);
      car.lateral = Math.max(-0.9, Math.min(0.9, car.lateral));

      car.s += car.velocity * dt;
      const path = paths[car.pathIndex];
      if (car.s >= path.length - 0.5) {
        advanceJunction(car);
      }
      placeCar(car, paths, THREE);
    }
  }

  function dispose() {
    scene.remove(root);
    parts.bodyGeo.dispose();
    parts.cabinGeo.dispose();
    parts.wheelGeo.dispose();
    parts.glassMat.dispose();
    parts.tireMat.dispose();
    for (const m of parts.bodyMats) m.dispose();
  }

  return { update, dispose, count: cars.length, pathCount: paths.length };
}
