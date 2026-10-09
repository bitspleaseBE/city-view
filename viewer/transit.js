/**
 * Runtime trams + buses on De Lijn / OSM transit paths.
 * Halt dwell (smooth brake / 20s stop / accel), E to board/alight.
 *
 * Directions: every path carries `direction` in transit.json (1 = drive the points in order,
 * -1 = against, 0 = either). Tram tracks get it from the ordered OSM route relations (the two
 * tracks of a dual-carriageway median run opposite ways), GTFS bus shapes are inherently
 * stop-to-stop. Vehicles only ever spawn, hand over, and (re-)enter in the legal direction.
 */

import { shared } from "./lanes.js";

const TRANSIT_URL = "./transit.json";
const TRAM_COUNT = 6;
const BUS_COUNT = 8;
const TRAM_SPEED = 7.5;
const BUS_SPEED = 8.5;
const FOLLOW_DIST = 14;
const PLAYER_STOP_DIST = 5;
const SNAP_M = 14;
const DWELL_S = 10;
const DECEL_DIST = 22;
const ARRIVE_DIST = 2.2;
const BOARD_DIST = 9;
const STOP_PROJECT_M = 28;
const BODY_LEN = { tram: 10.5, bus: 9 };
const STANDSTILL_GAP = 2.5; // bumper gap kept behind a leader
const COMFORT_BRAKE = 1.6; // m/s^2 used to plan halt / leader stops
const HALT_CREEP = 0.9; // m/s floor while rolling into a halt (never asymptote to 0)
const STUCK_GHOST_SEC = 10; // held this long by a leader/obstacle -> slide through it
const STUCK_QUEUE_SEC = 100; // longer than any dwell: only a circular queue gets here
const STUCK_FREE_SEC = 4; // held this long with nothing in front -> shove on
const GHOST_SEC = 8;
const GHOST_CREEP = 1.8;
const FIRST_TRAM_DWELL_S = 30; // waiting tram at the spawn halt
const MAX_STEP = 1 / 30; // s: the sim never integrates a bigger step (stable at any frame rate)
const MAX_FRAME = 0.25; // s: longest wall-clock gap simulated in one frame (tab switch, hitch)
const HARD_BRAKE = 3.0; // m/s^2 a tram / bus can shed speed when a car is right in front
const PLAYER_PATIENCE_SEC = 6; // a pedestrian in the lane holds a tram / bus this long, then it creeps past
const CAR_EVICT_SEC = 3; // a car holding a tram / bus still this long is cleared
const GATE_MARGIN = 24; // m inside the district edge where vehicles (re-)enter
const GATE_CLEAR_M = 45; // m of free road required around a gate before a vehicle enters
const SEED_GAP_M = 150; // seeding: min distance between two vehicles on the same track
const GATE_DELAY_S = [4, 24]; // hidden time between leaving the district and re-entering

function blenderToThree(x, y, out) {
  out.set(x, 0, -y);
  return out;
}

/** 1 / -1 / 0 from an exported direction code (unknown = either way). */
function directionCode(v) {
  const n = Number(v);
  return n > 0 ? 1 : n < 0 ? -1 : 0;
}

/** May a vehicle drive `path` backwards (`reverse`) / forwards? */
function mayDrive(path, reverse) {
  return path.dir === 0 || path.dir === (reverse ? -1 : 1);
}

/** The direction flag a vehicle must use on `path`; `want` only decides on two-way paths. */
function legalReverse(path, want) {
  return path.dir === 0 ? !!want : path.dir < 0;
}

function buildPaths(rawPaths, THREE) {
  const paths = [];
  for (const path of rawPaths) {
    const mode = path.mode || "bus";
    const pts = path.points || [];
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
    if (len < 8) continue;
    paths.push({
      id: path.id,
      mode,
      lines: path.lines || [],
      dir: directionCode(path.direction),
      points: cleaned,
      cumulative,
      length: len,
      start: cleaned[0],
      end: cleaned[cleaned.length - 1],
      halts: [],
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
}

/** Project world point onto path; return {s, dist} or null. */
function projectOnPath(path, wx, wz) {
  let bestS = 0;
  let bestD = Infinity;
  const pts = path.points;
  const cum = path.cumulative;
  for (let i = 0; i < pts.length - 1; i++) {
    const ax = pts[i].x;
    const az = pts[i].z;
    const bx = pts[i + 1].x;
    const bz = pts[i + 1].z;
    const dx = bx - ax;
    const dz = bz - az;
    const len2 = dx * dx + dz * dz;
    let t = 0;
    if (len2 > 1e-8) {
      t = Math.max(0, Math.min(1, ((wx - ax) * dx + (wz - az) * dz) / len2));
    }
    const px = ax + dx * t;
    const pz = az + dz * t;
    const d = Math.hypot(wx - px, wz - pz);
    if (d < bestD) {
      bestD = d;
      const segLen = cum[i + 1] - cum[i];
      bestS = cum[i] + segLen * t;
    }
  }
  return { s: bestS, dist: bestD };
}

function attachHaltsToPaths(paths, stops, THREE) {
  const worldStops = [];
  for (const stop of stops || []) {
    const pos = blenderToThree(stop.x, stop.y, new THREE.Vector3());
    worldStops.push({
      id: stop.id,
      name: stop.name || "Halt",
      mode: stop.mode || "tram",
      lines: stop.lines || [],
      x: pos.x,
      z: pos.z,
      pos,
    });
  }
  const tmp = new THREE.Vector3();
  const tan = new THREE.Vector3();
  for (const path of paths) {
    const halts = [];
    for (const stop of worldStops) {
      if (path.mode === "tram" || path.mode === "subway") {
        if (stop.mode === "bus") continue;
      } else if (path.mode === "bus" && stop.mode !== "bus") {
        continue;
      }
      const hit = projectOnPath(path, stop.x, stop.z);
      if (hit.dist > STOP_PROJECT_M) continue;
      if (halts.some((h) => Math.abs(h.s - hit.s) < 12)) continue;
      // One platform = one stop: OSM maps both ends of a long platform (30 m apart) as separate
      // stops with the same name, and vehicles used to dwell twice in a row at the same halt.
      if (halts.some((h) => h.name === stop.name && Math.abs(h.s - hit.s) < 90)) continue;
      halts.push({
        s: hit.s,
        name: stop.name,
        id: stop.id,
        x: stop.x,
        z: stop.z,
        lines: stop.lines,
      });
    }
    // Ensure vehicles still dwell along long corridors (sparse OSM/GTFS tile exports).
    const spacing = path.mode === "bus" ? 220 : 160;
    if (halts.length < 2 && path.length > spacing) {
      for (let s = spacing * 0.5; s < path.length - 8; s += spacing) {
        if (halts.some((h) => Math.abs(h.s - s) < spacing * 0.45)) continue;
        samplePath(path, s, THREE, tmp, tan);
        halts.push({
          s,
          name: `Halt ${halts.length + 1}`,
          id: `synth_${path.id}_${Math.round(s)}`,
          x: tmp.x,
          z: tmp.z,
          lines: path.lines,
        });
      }
    }
    halts.sort((a, b) => a.s - b.s);
    path.halts = halts;
  }
  return worldStops;
}

function lineLabel(lines, mode) {
  if (lines && lines.length) return String(lines[0]);
  return mode === "bus" ? "bus" : "tram";
}

function makeLineSprite(THREE, text, mode) {
  const canvas = document.createElement("canvas");
  canvas.width = 128;
  canvas.height = 64;
  const ctx = canvas.getContext("2d");
  const bg = mode === "bus" ? "#1f6fb2" : "#e09a20";
  ctx.fillStyle = bg;
  ctx.fillRect(8, 10, 112, 44);
  ctx.fillStyle = "#ffffff";
  ctx.font = "bold 28px system-ui, sans-serif";
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  ctx.fillText(text.slice(0, 8), 64, 32);
  const tex = new THREE.CanvasTexture(canvas);
  tex.needsUpdate = true;
  const mat = new THREE.SpriteMaterial({ map: tex, transparent: true, depthTest: true });
  const sprite = new THREE.Sprite(mat);
  sprite.scale.set(3.2, 1.6, 1);
  sprite.position.y = 3.4;
  return { sprite, tex, mat };
}

function makeTramMesh(THREE, parts) {
  const group = new THREE.Group();
  const body = new THREE.Mesh(parts.tramBody, parts.tramMat);
  const cabin = new THREE.Mesh(parts.tramCabin, parts.glassMat);
  cabin.position.set(0, 0.85, 0.2);
  const panto = new THREE.Mesh(parts.pantoGeo, parts.metalMat);
  panto.position.set(0, 1.55, 0);
  group.add(body, cabin, panto);
  return group;
}

function makeBusMesh(THREE, parts) {
  const group = new THREE.Group();
  const body = new THREE.Mesh(parts.busBody, parts.busMat);
  const cabin = new THREE.Mesh(parts.busCabin, parts.glassMat);
  cabin.position.set(0, 0.95, 0.4);
  group.add(body, cabin);
  return group;
}

function makeSharedParts(THREE) {
  return {
    tramBody: new THREE.BoxGeometry(2.2, 2.2, 10.5),
    tramCabin: new THREE.BoxGeometry(2.0, 0.7, 4.5),
    pantoGeo: new THREE.BoxGeometry(0.15, 0.7, 1.2),
    busBody: new THREE.BoxGeometry(2.4, 2.6, 9.0),
    busCabin: new THREE.BoxGeometry(2.2, 0.75, 3.2),
    glassMat: new THREE.MeshLambertMaterial({ color: 0x88a8c0, transparent: true, opacity: 0.8 }),
    metalMat: new THREE.MeshLambertMaterial({ color: 0x333333 }),
    tramMat: new THREE.MeshLambertMaterial({ color: 0xc45c28 }),
    busMat: new THREE.MeshLambertMaterial({ color: 0xf0e6c8 }),
  };
}

function pickNextPath(paths, path, atEnd, THREE) {
  const tip = atEnd ? path.end : path.start;
  const candidates = [];
  for (let i = 0; i < paths.length; i++) {
    const other = paths[i];
    if (other === path) continue;
    if (other.mode !== path.mode && !(path.mode === "tram" && other.mode === "subway")) continue;
    const dStart = tip.distanceTo(other.start);
    const dEnd = tip.distanceTo(other.end);
    // Entering at the start drives the path forwards, at the end backwards: only legal ways.
    if (dStart < SNAP_M && mayDrive(other, false)) candidates.push({ index: i, reverse: false, d: dStart });
    if (dEnd < SNAP_M && mayDrive(other, true)) candidates.push({ index: i, reverse: true, d: dEnd });
  }
  if (!candidates.length) {
    return { index: paths.indexOf(path), reverse: !atEnd ? false : true, flip: true };
  }
  candidates.sort((a, b) => a.d - b.d);
  const pool = candidates.slice(0, Math.min(4, candidates.length));
  return pool[(Math.random() * pool.length) | 0];
}

/** Path-space s for vehicle (always forward travel distance from path start of its direction). */
function travelS(v, path) {
  return v.reverse ? path.length - v.s : v.s;
}

function nextHaltAhead(v, path) {
  const halts = path.halts || [];
  if (!halts.length) return null;
  const ts = travelS(v, path);
  if (!v.reverse) {
    for (const h of halts) {
      if (h.s > ts + 0.8) return h;
    }
    return null;
  }
  for (let i = halts.length - 1; i >= 0; i--) {
    const h = halts[i];
    if (h.s < ts - 0.8) return h;
  }
  return null;
}

function distToHalt(v, path, halt) {
  if (!halt) return Infinity;
  const ts = travelS(v, path);
  return Math.abs(halt.s - ts);
}

const _lane = { x: 0, z: 0 };
/** Ease a bus into the lane of the car road it is driving on (rate = 1/s; Infinity = snap). */
function steerBus(v, rate, dt) {
  if (v.mode !== "bus" || !v.offSet) return;
  let tx = -v.tan.z * 1.1;
  let tz = v.tan.x * 1.1;
  if (shared.laneAt && shared.laneAt(v.baseX, v.baseZ, v.tan.x, v.tan.z, _lane, "bus")) {
    tx = _lane.x - v.baseX;
    tz = _lane.z - v.baseZ;
  }
  const k = Math.min(1, rate * dt);
  v.offX += (tx - v.offX) * k;
  v.offZ += (tz - v.offZ) * k;
}

function createVehicle(paths, THREE, parts, mode) {
  const pool = paths.filter((p) =>
    mode === "tram" ? p.mode === "tram" || p.mode === "subway" : p.mode === "bus",
  );
  const use = pool.length ? pool : paths;
  const indexInUse = (Math.random() * use.length) | 0;
  const path = use[indexInUse];
  const index = paths.indexOf(path);
  const reverse = legalReverse(path, Math.random() < 0.5);
  const s = Math.random() * path.length * 0.85;
  const mesh = mode === "tram" ? makeTramMesh(THREE, parts) : makeBusMesh(THREE, parts);
  const labelText = lineLabel(path.lines, mode);
  const label = makeLineSprite(THREE, labelText, mode);
  mesh.add(label.sprite);
  const base = mode === "tram" ? TRAM_SPEED : BUS_SPEED;
  return {
    mesh,
    mode,
    pathIndex: index,
    reverse,
    s,
    speed: base * (0.85 + Math.random() * 0.3),
    velocity: 0,
    accel: 0,
    pos: new THREE.Vector3(),
    tan: new THREE.Vector3(),
    label,
    lineText: labelText,
    phase: "cruise", // cruise | approach | dwell
    dwellLeft: 0,
    haltIndex: -1,
    currentHalt: null,
    stuckT: 0,
    ghostUntil: 0,
    respawnAt: 0,
    carBlockT: 0,
    playerT: 0,
    offX: 0,
    offZ: 0,
    offSet: false,
    baseX: 0,
    baseZ: 0,
    wait: "",
  };
}

function placeVehicle(v, paths, THREE) {
  if (v.phase === "gone") return; // hidden off-map: keep its parked position
  const path = paths[v.pathIndex];
  if (!path) return;
  const s = v.reverse ? path.length - v.s : v.s;
  samplePath(path, s, THREE, v.pos, v.tan);
  if (v.reverse) v.tan.multiplyScalar(-1);
  if (v.mode === "bus") {
    // Right-hand traffic. The sideways offset follows the car lane when one runs alongside
    // (steerBus), else the default 1.1 m to the right of the route.
    v.baseX = v.pos.x;
    v.baseZ = v.pos.z;
    if (!v.offSet) {
      v.offX = -v.tan.z * 1.1;
      v.offZ = v.tan.x * 1.1;
      v.offSet = true;
    }
    v.pos.x += v.offX;
    v.pos.z += v.offZ;
  }
  v.pos.y = v.mode === "tram" ? 1.3 : 1.35;
  v.mesh.position.copy(v.pos);
  v.mesh.rotation.y = Math.atan2(v.tan.x, v.tan.z);
}

/**
 * @param {import('three').Scene} scene
 * @param {typeof import('three')} THREE
 * @param {{ tramCount?: number, busCount?: number }} [opts]
 */
export async function createTransit(scene, THREE, opts = {}) {
  // Fixed same-origin data file (no caller-supplied URL).
  const url = TRANSIT_URL;
  let data;
  try {
    const res = await fetch(url);
    if (!res.ok) throw new Error(`transit.json ${res.status}`);
    data = await res.json();
  } catch (err) {
    console.warn("Transit disabled — could not load transit.json:", err);
    return emptyTransit();
  }

  const allPaths = buildPaths(data.paths || [], THREE);
  const worldStops = attachHaltsToPaths(allPaths, data.stops || [], THREE);
  const tramPaths = allPaths.filter((p) => p.mode === "tram" || p.mode === "subway");
  const busPaths = allPaths.filter((p) => p.mode === "bus");
  if (allPaths.length < 1) {
    console.warn("Transit disabled — no paths");
    return emptyTransit();
  }

  const root = new THREE.Group();
  root.name = "RuntimeTransit";
  scene.add(root);
  const parts = makeSharedParts(THREE);
  const vehicles = [];

  // Prefer enough trams even when only a couple of OSM ways are in the tile.
  const tramN = Math.max(opts.tramCount ?? TRAM_COUNT, tramPaths.length ? 4 : 0);
  const busN = Math.min(opts.busCount ?? BUS_COUNT, Math.max(0, busPaths.length * 2));

  const spawnLocal = data.spawn
    ? blenderToThree(data.spawn.x, data.spawn.y, new THREE.Vector3())
    : new THREE.Vector3();

  const DISTRICT_R = Math.max(320, (data.radius || 280) * 1.2);
  const ENTRY_R = DISTRICT_R - GATE_MARGIN;

  /**
   * Where each path crosses into / sits inside the district bubble. Routes are kilometres
   * long but only ~0.7 km of each lies inside the walkable tile, so vehicles must be seeded
   * inside it and re-enter through a gate where the route crosses the rim. (They used to be
   * respawned at the far *ends* of the route - kilometres outside the bubble - and were
   * immediately "left the tile"-recycled again, every frame, forever: after ~2 minutes the
   * district had no moving trams or buses at all, and the headless soak counted the
   * teleporting ghosts as "moving".)
   */
  const gates = { tram: [], bus: [] };
  {
    const tmpP = new THREE.Vector3();
    const tmpT = new THREE.Vector3();
    const STEP = 3;
    for (let pi = 0; pi < allPaths.length; pi++) {
      const path = allPaths[pi];
      const grp = path.mode === "bus" ? gates.bus : gates.tram;
      path.inside = [];
      let prevIn = null;
      for (let c = 0; c <= path.length; c += STEP) {
        samplePath(path, c, THREE, tmpP, tmpT);
        const inside = Math.hypot(tmpP.x - spawnLocal.x, tmpP.z - spawnLocal.z) < ENTRY_R;
        if (inside) path.inside.push(c);
        if (prevIn !== null && inside !== prevIn) {
          // outside -> inside going forward = forward gate; inside -> outside = reverse gate.
          // A directed path only has the gate it may be driven through (a one-way track or bus
          // shape is never entered backwards at the far rim).
          if (inside && mayDrive(path, false)) grp.push({ pathIndex: pi, reverse: false, coord: Math.min(path.length - 1, c + 2) });
          else if (!inside && mayDrive(path, true)) grp.push({ pathIndex: pi, reverse: true, coord: Math.max(1, c - STEP - 2) });
        }
        prevIn = inside;
      }
    }
  }

  /** Closest named halt (on a tram path) to the human spawn. */
  function findServiceHalt() {
    let best = null;
    let bestD = Infinity;
    for (let pi = 0; pi < allPaths.length; pi++) {
      const path = allPaths[pi];
      if (path.mode !== "tram" && path.mode !== "subway") continue;
      for (const h of path.halts || []) {
        // Prefer real De Lijn names over synthetic "Halt N".
        const synthetic = String(h.id).startsWith("synth_");
        const d = Math.hypot(h.x - spawnLocal.x, h.z - spawnLocal.z);
        const score = d + (synthetic ? 80 : 0);
        if (score < bestD) {
          bestD = score;
          best = { pathIndex: pi, halt: h, dist: d };
        }
      }
    }
    return best;
  }

  function placeOnPath(v, pathIndex, travel, reverse) {
    const path = allPaths[pathIndex];
    if (!path) return;
    v.pathIndex = pathIndex;
    v.reverse = legalReverse(path, reverse); // one-way paths ignore the requested direction
    const ts = Math.max(0.5, Math.min(path.length - 0.5, travel));
    v.s = v.reverse ? path.length - ts : ts;
    v.phase = "cruise";
    v.currentHalt = null;
    v.dwellLeft = 0;
    v.velocity = v.speed * 0.55;
    placeVehicle(v, allPaths, THREE);
    if (v.mode === "bus") {
      steerBus(v, Infinity, 1); // snap straight into the car lane: no sideways glide on (re-)entry
      placeVehicle(v, allPaths, THREE);
    }
  }

  /** Is (path, direction, coord) free of other (visible) vehicles for `gap` metres? */
  function trackClear(v, gap) {
    if (shared.cars) {
      for (const c of shared.cars) {
        if (c.pos.distanceTo(v.pos) < 16) return false;
      }
    }
    for (const o of vehicles) {
      if (o === v || o.phase === "gone") continue;
      if (o.pos.distanceTo(v.pos) < 40) return false;
      if (o.pathIndex === v.pathIndex && o.reverse === v.reverse) {
        const path = allPaths[v.pathIndex];
        if (Math.abs(travelS(o, path) - travelS(v, path)) < gap) return false;
      }
    }
    return true;
  }

  /** Put `v` somewhere on the part of the route that lies inside the district, well spaced. */
  function seedInside(v, pathPool) {
    const usable = pathPool.filter((p) => p.inside && p.inside.length);
    if (!usable.length) return false;
    for (let tries = 0; tries < 80; tries++) {
      const path = usable[(Math.random() * usable.length) | 0];
      const coord = path.inside[(Math.random() * path.inside.length) | 0];
      placeOnPath(v, allPaths.indexOf(path), coord, Math.random() < 0.5);
      if (trackClear(v, tries < 60 ? SEED_GAP_M : SEED_GAP_M * 0.5)) break;
    }
    v.velocity = v.speed * (0.7 + Math.random() * 0.2);
    setVehicleLabel(v, allPaths[v.pathIndex]);
    return true;
  }

  function spawnFleet(n, mode, pathPool) {
    if (!pathPool.length || n <= 0) return;
    for (let i = 0; i < n; i++) {
      const v = createVehicle(allPaths, THREE, parts, mode);
      if (!seedInside(v, pathPool)) {
        // Route never enters the district: keep the vehicle parked out of sight.
        v.phase = "gone";
        v.mesh.visible = false;
        v.respawnAt = Infinity;
      }
      root.add(v.mesh);
      vehicles.push(v);
    }
  }

  /** Put trams on the line that serves spawn — one waiting, others inbound. */
  function seedTramsAtServiceHalt() {
    const service = findServiceHalt();
    if (!service || !tramPaths.length) {
      spawnFleet(tramN, "tram", tramPaths);
      return service;
    }
    const { pathIndex, halt } = service;
    const path = allPaths[pathIndex];
    const n = tramN;

    for (let i = 0; i < n; i++) {
      const v = createVehicle(allPaths, THREE, parts, "tram");
      // Force onto the service path (or its reverse counterpart if present).
      let pi = pathIndex;
      let reverse = false; // placeOnPath coerces this to the path's legal direction
      if (i % 2 === 1 && tramPaths.length > 1) {
        // Prefer the other tram way when it also hosts this halt.
        for (let j = 0; j < allPaths.length; j++) {
          if (j === pathIndex) continue;
          const p = allPaths[j];
          if (p.mode !== "tram" && p.mode !== "subway") continue;
          if ((p.halts || []).some((h) => Math.abs(h.s - halt.s) < 40 || h.name === halt.name)) {
            pi = j;
            break;
          }
        }
      }
      const p = allPaths[pi];
      // Match halt s on this path.
      let h = (p.halts || []).find((x) => x.name === halt.name) || halt;
      if (!(p.halts || []).includes(h)) {
        const hit = projectOnPath(p, halt.x, halt.z);
        h = { ...halt, s: hit.s };
      }

      if (i === 0) {
        // First tram: waiting at the halt so E boards immediately at spawn.
        reverse = false;
        placeOnPath(v, pi, h.s, reverse);
        beginDwell(v, h);
        v.dwellLeft = FIRST_TRAM_DWELL_S;
        v.velocity = 0;
      } else if (i === 1) {
        // Inbound ~55 m before halt — arrives soon if the waiter left.
        reverse = false;
        // ~55 m *before* the halt along the direction of travel.
        const approach = allPaths[pi].dir < 0 ? Math.min(allPaths[pi].length - 1, h.s + 55) : Math.max(1, h.s - 55);
        placeOnPath(v, pi, approach, reverse);
        v.velocity = v.speed;
      } else {
        // The rest are spread along the part of the line that lies inside the district. They
        // used to be stacked in a convoy right behind the halt: every tram then queued for
        // the one dwelling at the stop and the first minute at spawn was a wall of parked trams.
        seedInside(v, tramPaths);
      }

      // Refresh line label from chosen path.
      const lbl = lineLabel(allPaths[v.pathIndex].lines, "tram");
      if (lbl !== v.lineText) {
        v.mesh.remove(v.label.sprite);
        v.label.tex.dispose();
        v.label.mat.dispose();
        v.label = makeLineSprite(THREE, lbl, "tram");
        v.mesh.add(v.label.sprite);
        v.lineText = lbl;
      }

      root.add(v.mesh);
      vehicles.push(v);
    }
    return service;
  }

  // beginDwell is used while seeding — define a lightweight local until full fn exists.
  function beginDwell(v, halt) {
    v.phase = "dwell";
    v.dwellLeft = DWELL_S;
    v.velocity = 0;
    v.accel = 0;
    v.currentHalt = halt;
    const path = allPaths[v.pathIndex];
    if (path && halt) {
      v.s = v.reverse ? path.length - halt.s : halt.s;
    }
  }

  const serviceHalt = seedTramsAtServiceHalt();
  spawnFleet(busN, "bus", busPaths);
  if (serviceHalt) {
    console.info(
      `Transit: seeded trams for ${serviceHalt.halt.name} (${serviceHalt.dist.toFixed(0)} m from spawn)`,
    );
  }

  const playerPos = new THREE.Vector3();
  let simTime = 0;
  let ride = null; // { vehicle, wantAlight }
  const rideCamPos = new THREE.Vector3();
  const rideLook = new THREE.Vector3();

  function setVehicleLabel(v, path) {
    const nextLabel = lineLabel(path.lines, v.mode);
    if (nextLabel === v.lineText) return;
    v.mesh.remove(v.label.sprite);
    v.label.tex.dispose();
    v.label.mat.dispose();
    v.label = makeLineSprite(THREE, nextLabel, v.mode);
    v.mesh.add(v.label.sprite);
    v.lineText = nextLabel;
  }

  /**
   * Take a vehicle out of the district (it left the walkable tile / ran off the end of its
   * route). It stays hidden for a few seconds, then re-enters through a gate on the rim
   * (see tryEnter) so the fleet keeps flowing and the street never empties.
   */
  function recycleVehicle(v) {
    if (ride && ride.vehicle === v) {
      const drop = alightAt(v);
      ride = { pendingDrop: drop };
    }
    v.mesh.visible = false;
    v.phase = "gone";
    v.velocity = 0;
    v.pos.set(1e5, -100, 1e5); // far off-map so nothing can ever collide with / follow a hidden vehicle
    v.currentHalt = null;
    v.dwellLeft = 0;
    v.stuckT = 0;
    v.wait = "";
    const [lo, hi] = GATE_DELAY_S;
    v.respawnAt = simTime + lo + Math.random() * (hi - lo);
  }

  /** Try to bring a hidden vehicle back in through a free gate. Retries every second. */
  function tryEnter(v) {
    const list = v.mode === "bus" ? gates.bus : gates.tram;
    if (!list.length) {
      // No route crosses the rim: drop it somewhere inside instead.
      const pool = v.mode === "bus" ? busPaths : tramPaths;
      if (seedInside(v, pool)) {
        v.mesh.visible = true;
        v.ghostUntil = simTime + 3;
        return;
      }
      v.respawnAt = Infinity;
      return;
    }
    const start = (Math.random() * list.length) | 0;
    for (let k = 0; k < list.length; k++) {
      const g = list[(start + k) % list.length];
      placeOnPath(v, g.pathIndex, g.coord, g.reverse);
      if (trackClear(v, GATE_CLEAR_M)) {
        v.mesh.visible = true;
        v.velocity = v.speed * (0.7 + Math.random() * 0.2);
        v.ghostUntil = simTime + 2;
        v.stuckT = 0;
        v.wait = "";
        setVehicleLabel(v, allPaths[g.pathIndex]);
        return;
      }
    }
    v.phase = "gone";
    v.mesh.visible = false;
    v.pos.set(1e5, -100, 1e5);
    v.velocity = 0;
    v.respawnAt = simTime + 1; // every gate is busy: wait a second and look again
  }

  function advanceOrRecycle(v) {
    const path = allPaths[v.pathIndex];
    if (!path) {
      recycleVehicle(v);
      return;
    }
    const atEnd = !v.reverse;
    const next = pickNextPath(allPaths, path, atEnd, THREE);
    // End of usable network / U-turn → leave the district and respawn inbound.
    if (next.flip) {
      recycleVehicle(v);
      return;
    }
    const np = allPaths[next.index];
    // Don't continue onto a segment that immediately exits the bubble.
    const tip = next.reverse ? np.end : np.start;
    if (tip.distanceTo(spawnLocal) > DISTRICT_R * 0.95) {
      recycleVehicle(v);
      return;
    }
    v.pathIndex = next.index;
    v.reverse = next.reverse;
    v.s = 0.5;
    v.phase = "cruise";
    v.currentHalt = null;
    setVehicleLabel(v, np);
  }

  function updateVehicleMotion(v, dt, walkObject) {
    if (v.phase === "gone") {
      if (simTime >= v.respawnAt) tryEnter(v);
      return;
    }
    const path = allPaths[v.pathIndex];
    if (!path) return;
    placeVehicle(v, allPaths, THREE);
    steerBus(v, 3, dt);

    if (v.phase === "dwell") {
      v.velocity = 0;
      v.dwellLeft -= dt;
      if (v.dwellLeft <= 0) {
        const left = v.currentHalt;
        v.phase = "cruise";
        v.currentHalt = null;
        v.accel = 0;
        // Nudge past the halt so the same stop is not re-targeted immediately.
        if (left && path) {
          const nudge = 2.5;
          if (v.reverse) v.s = Math.min(path.length - 0.5, path.length - left.s + nudge);
          else v.s = Math.min(path.length - 0.5, left.s + nudge);
        }
      }
      placeVehicle(v, allPaths, THREE);
      return;
    }

    const activeHalt = nextHaltAhead(v, path);
    const ghosting = simTime < v.ghostUntil;
    let desire = v.speed;
    let limitedBy = "";

    if (activeHalt) {
      const dHalt = distToHalt(v, path, activeHalt);
      if (dHalt < DECEL_DIST) {
        v.phase = "approach";
        // Kinematic stop at the halt, with a creep floor so smooth easing can
        // never decay to a standstill a couple of metres short of the platform.
        const planned = Math.sqrt(2 * COMFORT_BRAKE * Math.max(0, dHalt - 0.4));
        desire = Math.min(desire, Math.max(HALT_CREEP, planned));
        if (dHalt < ARRIVE_DIST * 0.7 || (dHalt < ARRIVE_DIST && v.velocity < 1.4)) {
          beginDwell(v, activeHalt);
          placeVehicle(v, allPaths, THREE);
          return;
        }
      } else {
        v.phase = "cruise";
      }
    } else {
      v.phase = "cruise";
    }

    const len = BODY_LEN[v.mode] || BODY_LEN.bus;
    if (!ghosting) {
      for (let j = 0; j < vehicles.length; j++) {
        const other = vehicles[j];
        if (other === v || other.phase === "gone") continue;
        const dx = other.pos.x - v.pos.x;
        const dz = other.pos.z - v.pos.z;
        const distSq = dx * dx + dz * dz;
        const reach = FOLLOW_DIST + len + 8;
        if (distSq > reach * reach) continue;
        // Only follow traffic going our way; oncoming vehicles pass in their own lane.
        if (other.tan.x * v.tan.x + other.tan.z * v.tan.z < 0.35) continue;
        const ahead = dx * v.tan.x + dz * v.tan.z;
        const side = Math.abs(dx * v.tan.z + dz * -v.tan.x);
        if (ahead > 0.5 && side < 3.2) {
          const olen = BODY_LEN[other.mode] || BODY_LEN.bus;
          const gap = ahead - (len + olen) * 0.5 - STANDSTILL_GAP;
          const safe = other.velocity * 0.9 + Math.sqrt(2 * COMFORT_BRAKE * Math.max(0, gap));
          if (safe < desire) {
            desire = Math.max(0, safe);
            // Waiting behind a vehicle that is dwelling (or itself queued) is normal.
            limitedBy = other.phase === "dwell" || other.wait === "queue" ? "queue" : "leader";
          }
        }
      }
    }

    // Cars share the street. They give way to us (traffic.js), but a car that is in our lane
    // right in front of us (queued at a red, stopped for the player, ...) must not be driven
    // through: follow it like a leader. A car that keeps us stationary for a few seconds is
    // dead weight and is cleared (despawned), never ghosted through.
    let carBlocker = null;
    const cars = shared.cars;
    if (cars && !ghosting) {
      const half = (BODY_LEN[v.mode] || BODY_LEN.bus) * 0.5;
      const hw = v.mode === "tram" ? 1.3 : 1.25;
      for (let j = 0; j < cars.length; j++) {
        const c = cars[j];
        const dx = c.pos.x - v.pos.x;
        const dz = c.pos.z - v.pos.z;
        if (dx * dx + dz * dz > 40 * 40) continue;
        const dot = c.tan.x * v.tan.x + c.tan.z * v.tan.z;
        const crs = c.tan.x * v.tan.z - c.tan.z * v.tan.x;
        // The car's footprint projected on our axes (it may be crossing us sideways).
        const extA = 2.1 * Math.abs(dot) + 0.875 * Math.abs(crs);
        const extS = 2.1 * Math.abs(crs) + 0.875 * Math.abs(dot);
        const ahead = dx * v.tan.x + dz * v.tan.z;
        if (ahead < 0.5 || ahead - extA > half + 3 + (v.velocity * v.velocity) / (2 * HARD_BRAKE) * 1.15) continue;
        const side = Math.abs(dx * v.tan.z - dz * v.tan.x);
        if (side > hw + extS - 0.1) continue;
        // Moving cars that are not heading our way (crossing / oncoming) look after themselves:
        // they brake for us. Only react to ones that are slow or stopped.
        if (dot < 0.35 && c.velocity > 1.5) continue;
        const gap = ahead - extA - half - 2.2;
        const lead = dot > 0.35 ? c.velocity * 0.9 : 0;
        const safe = lead + Math.sqrt(2 * COMFORT_BRAKE * Math.max(0, gap));
        if (safe < desire) {
          desire = Math.max(0, safe);
          limitedBy = c.wait === "red" || c.wait === "queue" ? "queue" : "car";
          carBlocker = c;
        }
      }
    }
    if (carBlocker && v.velocity < 0.3 && limitedBy === "car") {
      v.carBlockT += dt;
      if (v.carBlockT > CAR_EVICT_SEC) {
        carBlocker.evict = true;
        v.carBlockT = 0;
      }
    } else {
      v.carBlockT = Math.max(0, v.carBlockT - dt * 2);
    }

    if (walkObject && !(ride && ride.vehicle === v)) {
      const dx = playerPos.x - v.pos.x;
      const dz = playerPos.z - v.pos.z;
      if (dx * dx + dz * dz < (PLAYER_STOP_DIST + 8) ** 2) {
        const ahead = dx * v.tan.x + dz * v.tan.z;
        const side = Math.abs(dx * v.tan.z + dz * -v.tan.x);
        if (ahead > 0.2 && ahead < PLAYER_STOP_DIST + 6 && side < 3) {
          const gap = ahead - 1.5;
          desire = Math.min(desire, v.speed * Math.max(0, gap / PLAYER_STOP_DIST) ** 2);
          limitedBy = "player";
        }
      }
    }

    // A walker standing in the lane holds the vehicle for a moment (and everything queued behind
    // it); after that it creeps past rather than blocking the line for as long as they stand there.
    if (limitedBy === "player" && v.velocity < 0.3) {
      v.playerT += dt;
      if (v.playerT > PLAYER_PATIENCE_SEC) {
        v.ghostUntil = simTime + GHOST_SEC;
        v.playerT = 0;
      }
    } else {
      v.playerT = Math.max(0, v.playerT - dt);
    }

    // Recovery: a vehicle that is held for too long (leader jam, bad geometry)
    // slides through at a crawl instead of sitting there for the rest of the session.
    if (v.velocity < 0.3 && limitedBy !== "player") {
      v.stuckT += dt;
      const limit =
        limitedBy === "queue" || limitedBy === "car"
          ? STUCK_QUEUE_SEC
          : limitedBy === "leader"
            ? STUCK_GHOST_SEC
            : STUCK_FREE_SEC;
      if (v.stuckT > limit) {
        v.ghostUntil = simTime + GHOST_SEC;
        v.stuckT = 0;
      }
    } else {
      v.stuckT = Math.max(0, v.stuckT - dt * 2);
    }
    v.wait = v.velocity < 0.3 && v.phase !== "dwell" ? limitedBy : "";
    if (simTime < v.ghostUntil) desire = Math.max(desire, Math.min(v.speed, GHOST_CREEP));

    const prevV = v.velocity;
    // Smooth accel / brake (approach uses stronger brake).
    const rate = v.phase === "approach" ? 2.2 : 1.4;
    v.velocity += (desire - v.velocity) * Math.min(1, dt * rate);
    // Smooth easing is for halts and comfort; a car in the lane needs a firm, bounded stop.
    if (carBlocker && v.velocity > desire) v.velocity = Math.max(desire, Math.min(v.velocity, prevV - HARD_BRAKE * dt));
    if (v.velocity < 0.08 && desire < 0.08) v.velocity = 0;

    v.s += v.velocity * dt;
    if (v.s >= path.length - 0.5) {
      advanceOrRecycle(v);
      placeVehicle(v, allPaths, THREE);
      return;
    }
    placeVehicle(v, allPaths, THREE);
    // Left the walkable tile — despawn and bring a fresh one in from the edge.
    if (Math.hypot(v.pos.x - spawnLocal.x, v.pos.z - spawnLocal.z) > DISTRICT_R) {
      recycleVehicle(v);
      placeVehicle(v, allPaths, THREE);
    }
  }

  function findBoardable(player) {
    if (!player || ride) return null;
    let best = null;
    let bestD = BOARD_DIST;
    for (const v of vehicles) {
      if (v.phase !== "dwell" || !v.currentHalt) continue;
      const dx = player.x - v.pos.x;
      const dz = player.z - v.pos.z;
      const d = Math.hypot(dx, dz);
      if (d < bestD) {
        bestD = d;
        best = v;
      }
    }
    // Also allow boarding if standing at a stop and a dwelling vehicle is there.
    if (!best) {
      for (const stop of worldStops) {
        const dStop = Math.hypot(player.x - stop.x, player.z - stop.z);
        if (dStop > BOARD_DIST) continue;
        for (const v of vehicles) {
          if (v.phase !== "dwell") continue;
          const dV = Math.hypot(player.x - v.pos.x, player.z - v.pos.z);
          if (dV < BOARD_DIST + 4 && dV < bestD) {
            bestD = dV;
            best = v;
          }
        }
      }
    }
    return best;
  }

  function nextHaltName(v) {
    const path = allPaths[v.pathIndex];
    if (!path) return "—";
    if (v.phase === "dwell" && v.currentHalt) {
      const upcoming = nextHaltAhead(v, path);
      return upcoming ? upcoming.name : "End of line";
    }
    const h = nextHaltAhead(v, path);
    return h ? h.name : "End of line";
  }

  function alightAt(v) {
    const halt = v.currentHalt;
    const drop = {
      x: halt ? halt.x + v.tan.z * 3.2 : v.pos.x + v.tan.z * 3.2,
      y: 1.7,
      z: halt ? halt.z + -v.tan.x * 3.2 : v.pos.z + -v.tan.x * 3.2,
    };
    ride = null;
    return drop;
  }

  function step(dt, walkObject) {
    simTime += dt;
    for (const v of vehicles) {
      updateVehicleMotion(v, dt, walkObject);
    }

    // Honour alight request when dwelling.
    if (ride && ride.wantAlight && ride.vehicle.phase === "dwell") {
      const drop = alightAt(ride.vehicle);
      ride = { pendingDrop: drop };
    }
  }

  /**
   * Advance the simulation by `dt` wall-clock seconds. Time is integrated in steps of at most
   * MAX_STEP, so a slow frame (the 60 MB district renders at 10-20 fps on many machines) does
   * not slow the trams down: previously dt was clamped to 0.05 s by the caller, which made a
   * 10 fps session run the whole street at half speed - dwell, red lights and all.
   */
  function update(dt, walkObject) {
    if (!(dt > 0) || !vehicles.length) return;
    if (walkObject) {
      playerPos.set(walkObject.position.x, 0, walkObject.position.z);
    }
    const total = Math.min(dt, MAX_FRAME);
    const n = Math.max(1, Math.ceil(total / MAX_STEP));
    const h = total / n;
    for (let i = 0; i < n; i++) step(h, walkObject);
  }

  function tryInteract(player) {
    // Returns { action, drop?, prompt? }
    if (ride && ride.vehicle) {
      const v = ride.vehicle;
      if (v.phase === "dwell") {
        const drop = alightAt(v);
        return { action: "alight", drop };
      }
      ride.wantAlight = true;
      return {
        action: "request_alight",
        nextHalt: nextHaltName(v),
      };
    }
    if (ride && ride.pendingDrop) {
      const drop = ride.pendingDrop;
      ride = null;
      return { action: "alight", drop };
    }
    const v = findBoardable(player);
    if (!v) return { action: "none" };
    ride = { vehicle: v, wantAlight: false };
    return {
      action: "board",
      line: v.lineText,
      mode: v.mode,
      nextHalt: nextHaltName(v),
    };
  }

  function consumePendingDrop() {
    if (ride && ride.pendingDrop) {
      const drop = ride.pendingDrop;
      ride = null;
      return drop;
    }
    return null;
  }

  function isRiding() {
    return !!(ride && ride.vehicle);
  }

  function nearestTramHalt(px, pz) {
    let best = null;
    let bestD = Infinity;
    for (const path of allPaths) {
      if (path.mode !== "tram" && path.mode !== "subway") continue;
      for (const h of path.halts || []) {
        if (String(h.id).startsWith("synth_")) continue;
        const d = Math.hypot(h.x - px, h.z - pz);
        if (d < bestD) {
          bestD = d;
          best = { halt: h, dist: d, path };
        }
      }
    }
    return best;
  }

  function approachingEta(halt, px, pz) {
    let bestEta = Infinity;
    let bestV = null;
    for (const v of vehicles) {
      if (v.mode !== "tram" && v.mode !== "subway") continue;
      if (v.phase === "gone") continue;
      if (v.phase === "dwell" && v.currentHalt && v.currentHalt.name === halt.name) {
        return { eta: 0, vehicle: v, dwelling: true };
      }
      const path = allPaths[v.pathIndex];
      if (!path) continue;
      const h =
        (path.halts || []).find((x) => x.name === halt.name) ||
        (Math.hypot(v.pos.x - halt.x, v.pos.z - halt.z) < 40 ? halt : null);
      if (!h) continue;
      // Only count if heading toward this halt.
      const ahead = nextHaltAhead(v, path);
      if (!ahead || ahead.name !== halt.name) {
        // Still count if close and approaching by distance decreasing proxy.
        const d = Math.hypot(v.pos.x - halt.x, v.pos.z - halt.z);
        if (d > 120) continue;
      }
      const dHalt = Math.hypot(v.pos.x - halt.x, v.pos.z - halt.z);
      const speed = Math.max(v.velocity, 2.5);
      const eta = dHalt / speed + (v.phase === "dwell" ? v.dwellLeft : 0);
      if (eta < bestEta) {
        bestEta = eta;
        bestV = v;
      }
    }
    if (!bestV) return null;
    return { eta: bestEta, vehicle: bestV, dwelling: false };
  }

  function getRideHud() {
    if (ride && ride.pendingDrop) {
      return { riding: false, message: "" };
    }
    if (!ride || !ride.vehicle) {
      const boardable = findBoardable({ x: playerPos.x, z: playerPos.z });
      if (boardable) {
        const halt = boardable.currentHalt;
        return {
          riding: false,
          prompt: `Press E to enter ${boardable.mode} ${boardable.lineText}${
            halt ? ` · ${halt.name}` : ""
          }`,
        };
      }
      const near = nearestTramHalt(playerPos.x, playerPos.z);
      if (near && near.dist < 220) {
        const arr = approachingEta(near.halt, playerPos.x, playerPos.z);
        if (near.dist > BOARD_DIST + 2) {
          const dir = arr
            ? arr.dwelling
              ? `tram waiting · walk ${near.dist.toFixed(0)} m to ${near.halt.name}`
              : `tram ~${Math.max(1, Math.round(arr.eta))}s · walk ${near.dist.toFixed(0)} m to ${near.halt.name}`
            : `walk ${near.dist.toFixed(0)} m to ${near.halt.name} tram stop`;
          return { riding: false, prompt: dir };
        }
        if (arr && !arr.dwelling) {
          return {
            riding: false,
            prompt: `Tram ${arr.vehicle.lineText} arriving in ~${Math.max(1, Math.round(arr.eta))}s at ${near.halt.name}`,
          };
        }
      }
      return { riding: false };
    }
    const v = ride.vehicle;
    const next = nextHaltName(v);
    const here = v.phase === "dwell" && v.currentHalt ? v.currentHalt.name : null;
    return {
      riding: true,
      line: v.lineText,
      mode: v.mode,
      nextHalt: next,
      currentHalt: here,
      wantAlight: !!ride.wantAlight,
      dwelling: v.phase === "dwell",
      dwellLeft: v.dwellLeft,
    };
  }

  function getRideCamera(outPos, outLook) {
    if (!ride || !ride.vehicle) return false;
    const v = ride.vehicle;
    // Overhead follow: above and slightly behind.
    outPos.set(
      v.pos.x - v.tan.x * 10,
      22,
      v.pos.z - v.tan.z * 10,
    );
    outLook.set(v.pos.x + v.tan.x * 6, 1.2, v.pos.z + v.tan.z * 6);
    return true;
  }

  function dispose() {
    scene.remove(root);
    for (const v of vehicles) {
      v.label.tex.dispose();
      v.label.mat.dispose();
    }
    parts.tramBody.dispose();
    parts.tramCabin.dispose();
    parts.pantoGeo.dispose();
    parts.busBody.dispose();
    parts.busCabin.dispose();
    parts.glassMat.dispose();
    parts.metalMat.dispose();
    parts.tramMat.dispose();
    parts.busMat.dispose();
  }

  /** Night: lit cabin windows on trams and buses (0 = day, 1 = full night). */
  function setNight(t) {
    parts.glassMat.emissive.setRGB(1.0 * t, 0.78 * t, 0.42 * t);
    parts.glassMat.opacity = 0.8 + 0.15 * t;
  }

  return {
    update,
    dispose,
    setNight,
    vehicles,
    count: vehicles.length,
    pathCount: allPaths.length,
    stopCount: worldStops.length,
    tryInteract,
    consumePendingDrop,
    isRiding,
    getRideHud,
    getRideCamera,
    _rideCamPos: rideCamPos,
    _rideLook: rideLook,
  };
}

function emptyTransit() {
  return {
    update() {},
    dispose() {},
    setNight() {},
    count: 0,
    tryInteract() {
      return { action: "none" };
    },
    consumePendingDrop() {
      return null;
    },
    isRiding() {
      return false;
    },
    getRideHud() {
      return { riding: false };
    },
    getRideCamera() {
      return false;
    },
  };
}
