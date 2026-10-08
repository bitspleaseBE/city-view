/**
 * Runtime GTA3-simple traffic: box cars follow driveable OSM centrelines
 * with car-following, 30s lights at real stop-lines, and stuck recovery.
 * Never uses tram/rail ways.
 *
 * Speeds: each road carries `speedKmh` (OSM maxspeed, else a Belgian urban
 * default by highway class) exported into roads.json. Cars cruise slightly
 * under that limit (per-driver variance) and brake kinematically for leaders,
 * red lights and the player. Waiting at a red is never treated as "stuck";
 * real blockages escalate: nudge -> ghost-through -> respawn.
 */

const KMH = 1 / 3.6;
const DEFAULT_SPEED_KMH = {
  motorway: 70,
  motorway_link: 50,
  trunk: 50,
  trunk_link: 50,
  primary: 50,
  primary_link: 40,
  secondary: 50,
  secondary_link: 40,
  tertiary: 50,
  tertiary_link: 40,
  unclassified: 30,
  residential: 30,
  living_street: 20,
};
const FALLBACK_SPEED_KMH = 30;
const MAX_SPEED_KMH = 90; // sanity clamp on malformed data
const ACCEL = 2.6; // m/s^2
const BRAKE = 4.2; // comfortable decel, m/s^2
const CAR_LEN = 4.2;
const STANDSTILL_GAP = 1.6; // bumper gap kept to the leader / stop line
const STOP_LINE_SETBACK = CAR_LEN * 0.5 + 0.4;
const TURN_SPEED = 5.0; // m/s through sharp junction turns
const CREEP_SPEED = 2.2; // m/s minimum while ghosting through a jam
const BLOCK_NUDGE_SEC = 1.5;
const BLOCK_GHOST_SEC = 4;
const GHOST_SEC = 5;
const BLOCK_RESPAWN_SEC = 14;
const RED_QUEUE_PATIENCE_SEC = 22; // queue longer than a light cycle half = gridlock
const RED_PATIENCE_SEC = 40; // a light that never turns green is ignored after this
const FOLLOW_DIST = 9;
const PLAYER_STOP_DIST = 4;
const SNAP_M = 11;
const LANE_OFFSET = 1.15;
const STUCK_SEC = 6;
const CYCLE_SEC = 30;
const METERS_PER_CAR = 480;
const MIN_CARS = 8;
const MAX_CARS = 16;
const BODY_COLORS = [0xc45c48, 0x3d5a80, 0xd4a373, 0x4a5568, 0xb8b0a4, 0x2f6f5e];

const DRIVEABLE_KINDS = new Set([
  "motorway",
  "motorway_link",
  "trunk",
  "trunk_link",
  "primary",
  "primary_link",
  "secondary",
  "secondary_link",
  "tertiary",
  "tertiary_link",
  "unclassified",
  "residential",
  "living_street",
]);

const BLOCKED_KINDS = new Set([
  "tram",
  "rail",
  "light_rail",
  "subway",
  "narrow_gauge",
  "platform",
  "footway",
  "path",
  "cycleway",
  "steps",
  "pedestrian",
  "service",
  "bus_guideway",
]);

function blenderToThree(x, y, out) {
  out.set(x, 0, -y);
  return out;
}

/** Posted limit in km/h: exported speedKmh, else OSM maxspeed, else urban default. */
function resolveSpeedKmh(road, kind) {
  for (const v of [road.speedKmh, road.maxspeedKmh, road.maxspeed]) {
    const n = Number.parseFloat(v);
    if (Number.isFinite(n) && n > 0) return Math.min(MAX_SPEED_KMH, Math.max(5, n));
  }
  return DEFAULT_SPEED_KMH[kind] ?? FALLBACK_SPEED_KMH;
}

function buildPaths(roads, THREE) {
  const paths = [];
  for (const road of roads) {
    const kind = String(road.kind || "residential").toLowerCase();
    if (BLOCKED_KINDS.has(kind) || (kind && !DRIVEABLE_KINDS.has(kind))) continue;
    if (road.tramShared === true && kind === "tram") continue;
    const pts = road.points || [];
    if (pts.length < 2) continue;
    const points = [];
    for (const p of pts) {
      points.push(blenderToThree(p[0], p[1], new THREE.Vector3()));
    }
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
    const laneOffset = Number.isFinite(road.laneOffset) ? road.laneOffset : LANE_OFFSET;
    const limitKmh = resolveSpeedKmh(road, kind);
    paths.push({
      id: road.id,
      kind,
      limitKmh,
      speedLimit: limitKmh * KMH,
      width: road.width || 6,
      laneOffset: road.tramShared ? Math.max(laneOffset, 2.35) : laneOffset,
      points: cleaned,
      cumulative,
      length: len,
      start: cleaned[0],
      end: cleaned[cleaned.length - 1],
      occupants: 0,
    });
  }
  return paths;
}

function buildSignals(raw, THREE, cycleSec) {
  const signals = [];
  const tmp = new THREE.Vector3();
  for (const s of raw || []) {
    const stopX = s.stopX ?? s.x;
    const stopY = s.stopY ?? s.y;
    if (!Number.isFinite(stopX) || !Number.isFinite(stopY)) continue;
    blenderToThree(stopX, stopY, tmp);
    const stop = tmp.clone();
    let tx = Number(s.tx);
    let ty = Number(s.ty);
    let tan;
    if (Number.isFinite(tx) && Number.isFinite(ty) && tx * tx + ty * ty > 1e-6) {
      // Blender (x,y) → Three (x, 0, -y); tangent likewise.
      tan = new THREE.Vector3(tx, 0, -ty).normalize();
    } else {
      tan = new THREE.Vector3(1, 0, 0);
    }
    const id = s.id ?? signals.length;
    const phaseOffset = (Math.abs(Number(id) || signals.length) % 17) * 1.7;
    // Axis group: NS vs EW for alternating greens within the 30s cycle.
    const ns = Math.abs(tan.z) >= Math.abs(tan.x);
    signals.push({
      stop,
      tan,
      ns,
      phaseOffset,
      width: s.width || 6,
    });
  }
  return { signals, cycleSec };
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
  const lane = path.laneOffset ?? LANE_OFFSET;
  const rx = outTan.z;
  const rz = -outTan.x;
  outPos.x += rx * lane;
  outPos.z += rz * lane;
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

function tipTangent(path, atEnd, THREE) {
  const pts = path.points;
  if (atEnd) {
    return new THREE.Vector3().subVectors(pts[pts.length - 1], pts[pts.length - 2]).normalize();
  }
  return new THREE.Vector3().subVectors(pts[0], pts[1]).normalize();
}

function entryTangent(path, reverse, THREE) {
  const pts = path.points;
  if (reverse) {
    return new THREE.Vector3().subVectors(pts[pts.length - 2], pts[pts.length - 1]).normalize();
  }
  return new THREE.Vector3().subVectors(pts[1], pts[0]).normalize();
}

function pickNextPath(paths, path, atEnd, cars, car, THREE) {
  const tip = atEnd ? path.end : path.start;
  const outTan = tipTangent(path, atEnd, THREE);
  const candidates = [];
  for (let i = 0; i < paths.length; i++) {
    const other = paths[i];
    if (other === path) continue;
    const dStart = tip.distanceTo(other.start);
    const dEnd = tip.distanceTo(other.end);
    if (dStart < SNAP_M) {
      const inTan = entryTangent(other, false, THREE);
      candidates.push({ index: i, reverse: false, d: dStart, align: outTan.dot(inTan) });
    }
    if (dEnd < SNAP_M) {
      const inTan = entryTangent(other, true, THREE);
      candidates.push({ index: i, reverse: true, d: dEnd, align: outTan.dot(inTan) });
    }
  }
  if (!candidates.length) {
    return { index: paths.indexOf(path), reverse: !atEnd ? false : true, flip: true };
  }
  // Prefer continuing forward; avoid U-turns; prefer quieter edges.
  for (const c of candidates) {
    let crowd = 0;
    for (const other of cars) {
      if (other === car) continue;
      if (other.pathIndex === c.index) crowd++;
    }
    c.score = c.align * 2.2 - crowd * 0.55 - c.d * 0.04;
    if (c.align < -0.25) c.score -= 3.5;
  }
  candidates.sort((a, b) => b.score - a.score);
  const forward = candidates.filter((c) => c.align > 0.15);
  const pool = (forward.length ? forward : candidates).slice(0, Math.min(3, candidates.length));
  // Soft random among top choices so fleets diverge.
  const weights = pool.map((_, i) => 3 - i);
  let r = Math.random() * weights.reduce((a, b) => a + b, 0);
  for (let i = 0; i < pool.length; i++) {
    r -= weights[i];
    if (r <= 0) return pool[i];
  }
  return pool[0];
}

function createCar(paths, THREE, parts) {
  const index = (Math.random() * paths.length) | 0;
  const path = paths[index];
  const reverse = Math.random() < 0.5;
  const s = 2 + Math.random() * Math.max(1, path.length * 0.8 - 4);
  const colorIndex = (Math.random() * BODY_COLORS.length) | 0;
  const mesh = makeCarMesh(THREE, parts, colorIndex);
  // Per-driver variance: 85-100% of the posted limit (rarely a touch over).
  const driver = 0.85 + Math.random() * 0.15 + (Math.random() < 0.08 ? 0.05 : 0);
  const speed = path.speedLimit * driver;
  return {
    mesh,
    pathIndex: index,
    reverse,
    s,
    driver,
    speed,
    velocity: speed * (0.6 + Math.random() * 0.4),
    pos: new THREE.Vector3(),
    tan: new THREE.Vector3(),
    lateral: 0,
    stuck: 0,
    blocked: 0,
    queued: 0,
    redWait: 0,
    ghostUntil: 0,
    ignoreSignalsUntil: 0,
    wait: "",
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

function fleetCount(paths, requested) {
  if (Number.isFinite(requested)) return requested;
  let total = 0;
  for (const p of paths) total += p.length;
  return Math.max(MIN_CARS, Math.min(MAX_CARS, Math.round(total / METERS_PER_CAR)));
}

function signalIsGreen(sig, nowSec, cycleSec) {
  const phase = ((nowSec + sig.phaseOffset) % cycleSec + cycleSec) % cycleSec;
  const nsGreen = phase < cycleSec * 0.5;
  return sig.ns ? nsGreen : !nsGreen;
}

/**
 * @param {import('three').Scene} scene
 * @param {typeof import('three')} THREE
 * @param {{ url?: string, count?: number }} [opts]
 */
export async function createTraffic(scene, THREE, opts = {}) {
  const url = opts.url || "./roads.json";
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

  const cycleSec = Number(data.cycleSeconds) || CYCLE_SEC;
  const { signals } = buildSignals(data.signals || [], THREE, cycleSec);
  const count = fleetCount(paths, opts.count);

  const root = new THREE.Group();
  root.name = "RuntimeTraffic";
  scene.add(root);
  const parts = makeSharedParts(THREE);

  const cars = [];
  for (let i = 0; i < count; i++) {
    const car = createCar(paths, THREE, parts);
    let tries = 0;
    while (tries < 20) {
      placeCar(car, paths, THREE);
      const clash = cars.some((c) => c.pos.distanceToSquared(car.pos) < 100);
      if (!clash) break;
      car.pathIndex = (Math.random() * paths.length) | 0;
      car.s = 2 + Math.random() * Math.max(1, paths[car.pathIndex].length * 0.8 - 4);
      car.reverse = Math.random() < 0.5;
      tries++;
    }
    // Path may have been re-rolled above; start at a fraction of *its* limit.
    car.velocity = paths[car.pathIndex].speedLimit * car.driver * (0.6 + Math.random() * 0.4);
    placeCar(car, paths, THREE);
    root.add(car.mesh);
    cars.push(car);
  }

  const playerPos = new THREE.Vector3();
  let simTime = Math.random() * cycleSec;

  function respawnCar(car) {
    let best = null;
    for (let attempt = 0; attempt < 32; attempt++) {
      const pathIndex = (Math.random() * paths.length) | 0;
      const reverse = Math.random() < 0.5;
      const s = 2 + Math.random() * Math.max(1, paths[pathIndex].length * 0.85 - 4);
      car.pathIndex = pathIndex;
      car.reverse = reverse;
      car.s = s;
      placeCar(car, paths, THREE);
      let minD = Infinity;
      for (const other of cars) {
        if (other === car) continue;
        minD = Math.min(minD, car.pos.distanceTo(other.pos));
      }
      const playerD = playerPos.lengthSq() > 0 ? car.pos.distanceTo(playerPos) : 80;
      const score = Math.min(minD, 40) + Math.min(playerD, 60) * 0.35;
      if (!best || score > best.score) {
        best = { pathIndex, reverse, s, score, pos: car.pos.clone(), tan: car.tan.clone() };
      }
      if (minD > 18 && playerD > 35) break;
    }
    if (best) {
      car.pathIndex = best.pathIndex;
      car.reverse = best.reverse;
      car.s = best.s;
    }
    const path = paths[car.pathIndex];
    car.velocity = path.speedLimit * car.driver * 0.7;
    car.stuck = 0;
    car.blocked = 0;
    car.queued = 0;
    car.redWait = 0;
    car.ghostUntil = 0;
    car.ignoreSignalsUntil = simTime + 3;
    car.wait = "";
    car.lateral = 0;
    placeCar(car, paths, THREE);
  }

  function advanceJunction(car, overshoot) {
    const path = paths[car.pathIndex];
    const atEnd = !car.reverse;
    const next = pickNextPath(paths, path, atEnd, cars, car, THREE);
    if (next.flip) {
      car.reverse = !car.reverse;
      car.s = 1.0;
      car.velocity = Math.min(car.velocity, TURN_SPEED);
      return;
    }
    const nextPath = paths[next.index];
    car.pathIndex = next.index;
    car.reverse = next.reverse;
    car.s = Math.min(Math.max(1.0, overshoot), Math.max(1.0, nextPath.length - 1));
    // Slow through sharp turns; they re-accelerate toward the new road's limit.
    if (next.align < 0.7) car.velocity = Math.min(car.velocity, TURN_SPEED);
  }

  /** Max speed that still lets us stop within `gap` metres (v^2 = 2*a*d). */
  function stopSpeed(gap) {
    return gap <= 0 ? 0 : Math.sqrt(2 * BRAKE * gap);
  }

  function update(dt, walkObject) {
    if (dt <= 0) return;
    const step = Math.min(dt, 0.05);
    simTime += step;
    if (walkObject) {
      playerPos.set(walkObject.position.x, 0, walkObject.position.z);
    }

    for (let i = 0; i < cars.length; i++) {
      const car = cars[i];
      const roadPath = paths[car.pathIndex];
      placeCar(car, paths, THREE);

      const ghosting = simTime < car.ghostUntil;
      const cruise = roadPath.speedLimit * car.driver;
      car.speed = cruise;
      let desire = cruise;
      let lateralNudge = 0;
      let reason = "";
      let leader = null;

      if (!ghosting) {
        for (let j = 0; j < cars.length; j++) {
          if (i === j) continue;
          const other = cars[j];
          const dx = other.pos.x - car.pos.x;
          const dz = other.pos.z - car.pos.z;
          const distSq = dx * dx + dz * dz;
          if (distSq > (FOLLOW_DIST + 14) ** 2) continue;
          const heading = other.tan.x * car.tan.x + other.tan.z * car.tan.z;
          // Only follow leaders on a similar heading (same corridor / same way).
          if (heading < 0.35) continue;
          const ahead = dx * car.tan.x + dz * car.tan.z;
          const side = dx * car.tan.z + dz * -car.tan.x;
          if (ahead > 0.5 && Math.abs(side) < 2.8) {
            const gap = ahead - CAR_LEN - STANDSTILL_GAP;
            // Match the leader's speed plus whatever braking distance remains.
            const safe = other.velocity * 0.95 + stopSpeed(gap);
            if (safe < desire) {
              desire = Math.max(0, safe);
              reason = "car";
              leader = other;
            }
            if (Math.abs(side) < 1.6 && ahead < 6) {
              lateralNudge += side > 0 ? -0.3 : 0.3;
            }
          }
        }
      }

      if (walkObject) {
        const dx = playerPos.x - car.pos.x;
        const dz = playerPos.z - car.pos.z;
        const distSq = dx * dx + dz * dz;
        if (distSq < (PLAYER_STOP_DIST + 14) ** 2) {
          const ahead = dx * car.tan.x + dz * car.tan.z;
          const side = Math.abs(dx * car.tan.z + dz * -car.tan.x);
          if (ahead > 0.2 && side < 2.4) {
            const safe = stopSpeed(ahead - CAR_LEN * 0.5 - PLAYER_STOP_DIST * 0.5);
            if (safe < desire) {
              desire = safe;
              reason = "player";
            }
          }
        }
      }

      // Queueing behind a car that is itself waiting at a red / for the player is fine.
      if (reason === "car" && leader && (leader.wait === "red" || leader.wait === "queue" || leader.wait === "player")) {
        reason = "queue";
      }

      // Stop-line red lights (shared 30s NS/EW phases).
      let facingRed = false;
      if (simTime >= car.ignoreSignalsUntil) {
        for (let s = 0; s < signals.length; s++) {
          const sig = signals[s];
          const dx = sig.stop.x - car.pos.x;
          const dz = sig.stop.z - car.pos.z;
          const distSq = dx * dx + dz * dz;
          if (distSq > 40 * 40) continue;
          const ahead = dx * car.tan.x + dz * car.tan.z;
          const side = Math.abs(dx * car.tan.z + dz * -car.tan.x);
          const approachDot = car.tan.x * sig.tan.x + car.tan.z * sig.tan.z;
          if (ahead < 0.4 || ahead > 34 || side > Math.max(3.2, sig.width * 0.55)) continue;
          if (approachDot < 0.35) continue;
          if (signalIsGreen(sig, simTime, cycleSec)) continue;
          const gap = ahead - STOP_LINE_SETBACK;
          // Already too close to stop comfortably (light just turned): clear the box.
          if (gap < 0 && car.velocity * car.velocity > 2 * BRAKE * 1.6 * Math.max(0.1, ahead)) continue;
          facingRed = true;
          const safe = stopSpeed(gap);
          if (safe < desire) {
            desire = safe;
            reason = "red";
          }
        }
      }

      // Escalating recovery when not waiting for a legitimate reason.
      if (ghosting) desire = Math.max(desire, Math.min(cruise, CREEP_SPEED));

      // Kinematic follow: accelerate gently, brake as hard as needed.
      if (desire > car.velocity) {
        car.velocity = Math.min(desire, car.velocity + ACCEL * step);
      } else {
        car.velocity = Math.max(desire, car.velocity - BRAKE * 2.2 * step);
      }
      if (car.velocity < 0.05) car.velocity = 0;
      car.lateral += (lateralNudge - car.lateral) * Math.min(1, step * 3);
      car.lateral = Math.max(-0.7, Math.min(0.7, car.lateral));

      const crawling = car.velocity < 0.3 && cruise > 1;
      // A queue should clear within a light cycle; a circular "queue" is gridlock.
      if (crawling && reason === "queue") {
        car.queued += step;
        if (car.queued > RED_QUEUE_PATIENCE_SEC) reason = "car";
      } else {
        car.queued = 0;
      }
      car.wait = crawling ? reason || "?" : "";

      if (crawling && reason === "red" && facingRed) {
        // Legitimate wait: never respawn. If a light is somehow stuck red,
        // stop obeying it after a long patience window.
        car.redWait += step;
        car.blocked = 0;
        car.stuck = 0;
        if (car.redWait > RED_PATIENCE_SEC) {
          car.ignoreSignalsUntil = simTime + 8;
          car.redWait = 0;
        }
      } else if (crawling && reason === "queue") {
        car.redWait = 0;
        car.blocked = 0;
        car.stuck = 0;
      } else if (crawling && (reason === "car" || reason === "player")) {
        car.redWait = 0;
        car.blocked += step;
        if (car.blocked > BLOCK_GHOST_SEC && reason === "car") {
          // Soft push: slide through the blocker at a crawl, then flow on.
          car.ghostUntil = simTime + GHOST_SEC;
          car.blocked = BLOCK_NUDGE_SEC;
        }
        if (car.blocked > BLOCK_RESPAWN_SEC) {
          respawnCar(car);
          continue;
        }
      } else if (crawling) {
        // Stopped with no explanation (bad data, zero-speed road): recover fast.
        car.redWait = 0;
        car.stuck += step;
        if (car.stuck > STUCK_SEC) {
          respawnCar(car);
          continue;
        }
      } else {
        car.redWait = 0;
        car.stuck = Math.max(0, car.stuck - step);
        car.blocked = Math.max(0, car.blocked - step * 2);
      }

      car.s += car.velocity * step;
      const path = paths[car.pathIndex];
      if (car.s >= path.length - 0.5) {
        advanceJunction(car, car.s - (path.length - 0.5));
      }
      placeCar(car, paths, THREE);
    }
  }

  /** Debug / test helper. */
  function stats() {
    let moving = 0;
    let sum = 0;
    const waits = { red: 0, queue: 0, car: 0, player: 0, "?": 0 };
    for (const c of cars) {
      if (c.velocity > 0.5) moving++;
      sum += c.velocity;
      if (c.wait) waits[c.wait] = (waits[c.wait] || 0) + 1;
    }
    return { moving, total: cars.length, avgKmh: (sum / Math.max(1, cars.length)) * 3.6, waits };
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

  return {
    update,
    dispose,
    stats,
    cars,
    paths,
    count: cars.length,
    pathCount: paths.length,
    signalCount: signals.length,
  };
}
