/**
 * Runtime traffic: Belgian 2025-26 fleet GLBs (see cars.js / cars/fleet.json)
 * follow driveable OSM centrelines with car-following, 30s lights at real
 * stop-lines, and stuck recovery. Falls back to box cars when GLBs cannot load
 * (headless Node soaks). Never uses tram/rail ways.
 *
 * Directions: every road carries `oneway` (1 = only along its points, -1 = only against, 0 =
 * both ways) straight from the OSM oneway tags, and `onewayBus` for buses. Cars only ever
 * spawn, respawn and hand over onto a road in a legal direction, so the two halves of a dual
 * carriageway (each its own one-way OSM way) carry traffic in opposite directions.
 *
 * Speeds: each road carries `speedKmh` (OSM maxspeed, else a Belgian urban
 * default by highway class) exported into roads.json. Cars cruise slightly
 * under that limit (per-driver variance) and brake kinematically for leaders,
 * red lights, crossing traffic, trams/buses, the player and pedestrians. Waiting at a
 * red is never treated as "stuck". Cars NEVER pass through each other: a car that is
 * genuinely blocked for too long (gridlock, bad geometry) is despawned and respawned on
 * a free road instead of sliding through its blocker and leaving a ghost behind. Cars
 * brake for people in their lane; a hard overlap still knocks them down via `onHitPed`.
 */

import { shared } from "./lanes.js";
import { cloneCarMesh, loadCarTemplates, makeLampParts, pickCarTemplate } from "./cars.js";

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
const TRANSIT_PATIENCE_SEC = 100; // longer than any halt dwell
const ROADS_URL = "./roads.json";
const PLAYER_PATIENCE_SEC = 15; // player or pedestrian in the lane: wait, then clear the car
const HEAD_ON_DOT = -0.5; // oncoming-ish headings share the braking distance
const HEAD_ON_RESPAWN_SEC = 3; // the lower-priority car of a nose-to-nose deadlock is cleared quickly
const BLOCK_RESPAWN_SEC = 8; // blocked this long by a car / crossing car -> despawn + respawn
const RESPAWN_CLEARANCE = 14; // m of free space required around a respawn point
const HALF_L = CAR_LEN * 0.5;
const HALF_W = 0.875;
/** Road surface in viewer Y (matches Blender ``Z_ROAD`` / kerbs.Z_ROAD_SURFACE). */
const ROAD_Y = 0.05;
const OBSTACLE_ZONE = HALF_W + 0.05; // a tram / bus in the neighbouring lane is not in our way
const ZONE_HALF_W = HALF_W + 0.3; // swept corridor ahead of a car (oncoming lane stays clear of it)
const NEXT_LOOKAHEAD = 34; // m before a junction: pick the next road early and check it is free
const FUTURE_T = [0, 0.5, 1.0, 1.5]; // s: horizons for predicted footprint overlap
const CROSS_REACH = 34; // m: ignore other vehicles beyond this
const SIGNAL_CLUSTER_M = 32; // signal heads this close belong to one intersection controller
const RED_QUEUE_PATIENCE_SEC = 12; // queue longer than 12s = gridlock
const RED_PATIENCE_SEC = 40; // a light that never turns green is ignored after this
const FOLLOW_DIST = 9;
const PLAYER_STOP_DIST = 4;
const PED_STOP_DIST = 5.5; // brake earlier for walkers than for a standing player
const PED_HIT_SPEED = 1.8; // m/s: below this a nose-overlap is a shove the ped sim handles
const SNAP_M = 11;
const LANE_OFFSET = 1.15;
const STUCK_SEC = 5; // respawn after 5s of unexplained stop - never leave a car dead
const QUEUE_STUCK_SEC = 10; // even queueing cars should move eventually
const MAX_STEP = 0.05; // s: largest integration step (kinematics tuned and soaked at <= 20 Hz)
const MAX_FRAME = 0.25; // s: longest wall-clock gap simulated in one frame
const CYCLE_SEC = 30;
const AMBER_SEC = 3; // green → amber → red → green (no amber returning to green)
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

/** 1 / -1 / 0 from an exported oneway code (anything unknown = two-way). */
function directionCode(v) {
  const n = Number(v);
  return n > 0 ? 1 : n < 0 ? -1 : 0;
}

/** May a car drive `path` backwards (`reverse`) / forwards? */
function mayDrive(path, reverse) {
  return path.dir === 0 || path.dir === (reverse ? -1 : 1);
}

/** The travel direction a car is allowed on `path` (random on two-way roads). */
function legalReverse(path) {
  return path.dir === 0 ? Math.random() < 0.5 : path.dir < 0;
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
    // Dual-carriageway link stubs (Mechelsesteenweg 4480699 / unclassified 4445986) are not streets.
    if ((kind === "residential" || kind === "living_street" || kind === "unclassified") && len < 35) continue;
    const laneOffset = Number.isFinite(road.laneOffset) ? road.laneOffset : LANE_OFFSET;
    const limitKmh = resolveSpeedKmh(road, kind);
    const dir = directionCode(road.oneway);
    paths.push({
      id: road.id,
      kind,
      dual: !!road.dualCarriageway,
      dir, // legal car direction along `points`: 1 forward only, -1 reverse only, 0 both
      busDir: Number.isFinite(road.onewayBus) ? directionCode(road.onewayBus) : dir,
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

/**
 * Junction centres from the road graph: path end points that cluster within SNAP_M and have
 * three or more arms. Each arm records the unit vector pointing *out* of the junction.
 */
function buildJunctions(paths, THREE) {
  const ends = [];
  for (const path of paths) {
    ends.push({ path, atStart: true, v: path.start });
    ends.push({ path, atStart: false, v: path.end });
  }
  const used = new Array(ends.length).fill(false);
  const nodes = [];
  for (let i = 0; i < ends.length; i++) {
    if (used[i]) continue;
    const group = [ends[i]];
    used[i] = true;
    for (let j = i + 1; j < ends.length; j++) {
      if (!used[j] && ends[i].v.distanceTo(ends[j].v) < SNAP_M) {
        group.push(ends[j]);
        used[j] = true;
      }
    }
    if (group.length < 3) continue;
    const c = new THREE.Vector3();
    for (const g of group) c.add(g.v);
    c.multiplyScalar(1 / group.length);
    const arms = [];
    for (const g of group) {
      const pts = g.path.points;
      const from = g.atStart ? pts[0] : pts[pts.length - 1];
      let to = from;
      for (let k = 1; k < pts.length; k++) {
        to = g.atStart ? pts[k] : pts[pts.length - 1 - k];
        if (to.distanceTo(from) >= 6) break;
      }
      const dx = to.x - from.x;
      const dz = to.z - from.z;
      const len = Math.hypot(dx, dz);
      if (len < 1e-3) continue;
      arms.push({ ux: dx / len, uz: dz / len, width: g.path.width, hasHead: false });
    }
    if (arms.length >= 3) nodes.push({ c, arms, offset: null });
  }
  return nodes;
}

function buildSignals(raw, THREE, cycleSec, paths = []) {
  const signals = [];
  const tmp = new THREE.Vector3();
  const nodes = buildJunctions(paths, THREE);
  // Heads within one intersection must share a controller, otherwise each OSM node (often
  // 2-3 per junction) gets its own phase and cross streets are green together.
  const list = (raw || []).filter((s) => Number.isFinite(s.stopX ?? s.x) && Number.isFinite(s.stopY ?? s.y));
  const parent = list.map((_, i) => i);
  const find = (i) => {
    while (parent[i] !== i) {
      parent[i] = parent[parent[i]];
      i = parent[i];
    }
    return i;
  };
  for (let i = 0; i < list.length; i++) {
    for (let j = i + 1; j < list.length; j++) {
      const d = Math.hypot(list[i].x - list[j].x, list[i].y - list[j].y);
      if (d < SIGNAL_CLUSTER_M) parent[find(j)] = find(i);
    }
  }
  const controllerKey = new Map();
  for (let i = 0; i < list.length; i++) {
    const root = find(i);
    const id = Math.abs(Number(list[i].id) || 0);
    controllerKey.set(root, Math.min(controllerKey.get(root) ?? Infinity, id));
  }
  for (let k = 0; k < list.length; k++) {
    const s = list[k];
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
    const id = controllerKey.get(find(k)) || signals.length;
    const phaseOffset = (id % 17) * 1.7;

    // Orient the head along the road graph. Half of the exported heads point OUT of the
    // junction (they sit on the exit lane): the approaching cars never saw them (red ignored),
    // while cars that had already crossed the junction stopped at the "line" on the far side,
    // parked inside the intersection. A stop line must face the traffic entering the junction.
    let node = null;
    let nodeD = 30;
    for (const n of nodes) {
      const d = Math.hypot(n.c.x - stop.x, n.c.z - stop.z);
      if (d < nodeD) {
        nodeD = d;
        node = n;
      }
    }
    if (node) {
      const vx = stop.x - node.c.x;
      const vz = stop.z - node.c.z;
      const vl = Math.hypot(vx, vz) || 1;
      let best = null;
      let bestAlign = 0.7;
      for (const arm of node.arms) {
        const al = (arm.ux * vx + arm.uz * vz) / vl;
        if (al > bestAlign) {
          bestAlign = al;
          best = arm;
        }
      }
      if (best) {
        if (-(best.ux * tan.x + best.uz * tan.z) < 0) tan.multiplyScalar(-1);
        best.hasHead = true;
        if (node.offset === null) node.offset = phaseOffset;
      }
    }
    // Axis group: NS vs EW for alternating greens within the 30s cycle.
    const ns = Math.abs(tan.z) >= Math.abs(tan.x);
    const pole = new THREE.Vector3();
    if (Number.isFinite(s.x) && Number.isFinite(s.y)) blenderToThree(s.x, s.y, pole);
    else pole.copy(stop);
    const yawBlender = Number(s.yaw);
    const pedYawBlender = Number(s.pedYaw);
    signals.push({
      stop,
      pole: pole.clone(),
      tan,
      ns,
      phaseOffset,
      width: s.width || 6,
      // OSM node id — matches roads.json walks `cross{id}` for ped wait.
      osmId: Math.abs(Number(s.id) || 0) || null,
      yawBlender: Number.isFinite(yawBlender) ? yawBlender : null,
      pedYawBlender: Number.isFinite(pedYawBlender) ? pedYawBlender : null,
    });
  }
  // A signalised junction must control every arm, not only the arms that happened to carry an
  // OSM signal node: add a stop line on each unguarded arm, sharing the junction's phase.
  for (const node of nodes) {
    if (node.offset === null) continue;
    for (const arm of node.arms) {
      if (arm.hasHead) continue;
      const setback = Math.max(4.4, (arm.width || 6) * 0.6 + 1.2);
      const stop = new THREE.Vector3(node.c.x + arm.ux * setback, 0, node.c.z + arm.uz * setback);
      // Approach tangent into the junction (cars travel along this toward the stop).
      const tan = new THREE.Vector3(-arm.ux, 0, -arm.uz);
      const halfW = (arm.width || 6) * 0.5 + 0.85;
      // Right-hand curb relative to inbound tan.
      const pole = new THREE.Vector3(
        stop.x + -tan.z * halfW,
        0,
        stop.z + tan.x * halfW,
      );
      signals.push({
        stop,
        pole,
        tan,
        ns: Math.abs(tan.z) >= Math.abs(tan.x),
        phaseOffset: node.offset,
        width: arm.width || 6,
        yawBlender: null,
        pedYawBlender: null,
        synthesized: true,
      });
    }
  }
  return { signals, cycleSec };
}

/** Blender local-+Y yaw → Three.js rotation.y when local +Z is the front. */
function blenderFaceYawToThree(yaw) {
  const fx = -Math.sin(yaw);
  const fy = Math.cos(yaw);
  return Math.atan2(fx, -fy);
}

/** Face oncoming traffic from an inbound Three.js tangent. */
function faceYawFromTan(tan) {
  // Lenses look opposite the travel direction.
  return Math.atan2(-tan.x, -tan.z);
}

function signalPhase(sig, nowSec, cycleSec) {
  const phase = ((nowSec + sig.phaseOffset) % cycleSec + cycleSec) % cycleSec;
  const half = cycleSec * 0.5;
  const mine = sig.ns ? phase < half : phase >= half;
  if (!mine) return "red";
  const local = sig.ns ? phase : phase - half;
  if (local >= half - AMBER_SEC) return "amber";
  return "green";
}

function makeEmissiveMat(THREE, color, on) {
  const mat = new THREE.MeshBasicMaterial({
    color,
    fog: false,
    toneMapped: false,
  });
  mat.userData = mat.userData || {};
  mat.userData.base = color;
  mat.userData.on = !!on;
  return mat;
}

function setLampLit(mat, lit, litColor, dimColor) {
  const next = lit ? litColor : dimColor;
  const ud = mat.userData || (mat.userData = {});
  if (ud.on === lit && ud.base === next) return;
  if (mat.color && typeof mat.color.setHex === "function") mat.color.setHex(next);
  ud.on = lit;
  ud.base = next;
}

function addPedFigure(THREE, parent, y, walking, mat) {
  const head = new THREE.Mesh(new THREE.BoxGeometry(0.05, 0.05, 0.04), mat);
  head.position.set(0, y + 0.07, 0.02);
  parent.add(head);
  const torso = new THREE.Mesh(new THREE.BoxGeometry(0.06, 0.09, 0.04), mat);
  torso.position.set(0, y, 0.02);
  parent.add(torso);
  if (walking) {
    const legA = new THREE.Mesh(new THREE.BoxGeometry(0.03, 0.08, 0.04), mat);
    legA.position.set(0.025, y - 0.08, 0.02);
    parent.add(legA);
    const legB = new THREE.Mesh(new THREE.BoxGeometry(0.03, 0.08, 0.04), mat);
    legB.position.set(-0.025, y - 0.08, 0.04);
    parent.add(legB);
    const arm = new THREE.Mesh(new THREE.BoxGeometry(0.08, 0.03, 0.03), mat);
    arm.position.set(0.04, y + 0.02, 0.03);
    parent.add(arm);
  } else {
    const legs = new THREE.Mesh(new THREE.BoxGeometry(0.05, 0.09, 0.04), mat);
    legs.position.set(0, y - 0.08, 0.02);
    parent.add(legs);
  }
}

function buildSignalVisuals(signals, THREE, root) {
  const housingMat = new THREE.MeshLambertMaterial({ color: 0x141414 });
  const poleMat = new THREE.MeshLambertMaterial({ color: 0x2a2a2a });
  const dims = {
    redOn: 0xff2a1a,
    amberOn: 0xffa010,
    greenOn: 0x1ad64a,
    redOff: 0x3a100c,
    amberOff: 0x3a2410,
    greenOff: 0x0c2a14,
    pedRedOn: 0xff3030,
    pedGreenOn: 0x22e060,
    pedRedOff: 0x351010,
    pedGreenOff: 0x0e2814,
  };
  const lampGeo = new THREE.BoxGeometry(0.18, 0.16, 0.1);
  const disposables = [housingMat, poleMat, lampGeo];

  for (let i = 0; i < signals.length; i++) {
    const sig = signals[i];
    const group = new THREE.Group();
    group.name = `runtime_signal_${i}`;
    const polePos = sig.pole || sig.stop;
    group.position.set(polePos.x, 0, polePos.z);
    const faceYaw =
      sig.yawBlender != null ? blenderFaceYawToThree(sig.yawBlender) : faceYawFromTan(sig.tan);
    group.rotation.y = faceYaw;

    const pole = new THREE.Mesh(new THREE.BoxGeometry(0.1, 3.4, 0.1), poleMat);
    pole.position.y = 1.7;
    group.add(pole);

    const head = new THREE.Mesh(new THREE.BoxGeometry(0.3, 0.9, 0.22), housingMat);
    head.position.set(0, 3.55, 0.18);
    group.add(head);

    const redMat = makeEmissiveMat(THREE, dims.redOff, false);
    const amberMat = makeEmissiveMat(THREE, dims.amberOff, false);
    const greenMat = makeEmissiveMat(THREE, dims.greenOff, false);
    disposables.push(redMat, amberMat, greenMat);
    const lamps = [
      { mat: redMat, mesh: new THREE.Mesh(lampGeo, redMat), y: 3.85 },
      { mat: amberMat, mesh: new THREE.Mesh(lampGeo, amberMat), y: 3.59 },
      { mat: greenMat, mesh: new THREE.Mesh(lampGeo, greenMat), y: 3.33 },
    ];
    for (const lamp of lamps) {
      lamp.mesh.position.set(0, lamp.y, 0.32);
      group.add(lamp.mesh);
    }

    // Pedestrian head: faces across the zebra (people waiting to cross).
    const pedGroup = new THREE.Group();
    pedGroup.position.set(0, 0, 0);
    let pedYaw;
    if (sig.pedYawBlender != null) pedYaw = blenderFaceYawToThree(sig.pedYawBlender);
    else {
      // From the right-hand curb, face into the carriageway (−right).
      pedYaw = Math.atan2(sig.tan.z, -sig.tan.x);
    }
    // Ped group is parented under the vehicle group; apply relative yaw.
    pedGroup.rotation.y = pedYaw - faceYaw;
    const pedHead = new THREE.Mesh(new THREE.BoxGeometry(0.24, 0.55, 0.14), housingMat);
    pedHead.position.set(0, 2.35, 0.16);
    pedGroup.add(pedHead);
    const pedRedMat = makeEmissiveMat(THREE, dims.pedRedOff, false);
    const pedGreenMat = makeEmissiveMat(THREE, dims.pedGreenOff, false);
    disposables.push(pedRedMat, pedGreenMat);
    const pedRed = new THREE.Group();
    pedRed.position.set(0, 2.52, 0.26);
    const pedRedLens = new THREE.Mesh(new THREE.BoxGeometry(0.16, 0.2, 0.08), pedRedMat);
    pedRed.add(pedRedLens);
    addPedFigure(THREE, pedRed, 0, false, pedRedMat);
    pedGroup.add(pedRed);
    const pedGreen = new THREE.Group();
    pedGreen.position.set(0, 2.3, 0.26);
    const pedGreenLens = new THREE.Mesh(new THREE.BoxGeometry(0.16, 0.2, 0.08), pedGreenMat);
    pedGreen.add(pedGreenLens);
    addPedFigure(THREE, pedGreen, 0, true, pedGreenMat);
    pedGroup.add(pedGreen);
    group.add(pedGroup);

    root.add(group);
    sig.visual = {
      redMat,
      amberMat,
      greenMat,
      pedRedMat,
      pedGreenMat,
      dims,
      group,
    };
  }
  return disposables;
}

function updateSignalVisuals(signals, nowSec, cycleSec) {
  for (let i = 0; i < signals.length; i++) {
    const sig = signals[i];
    const v = sig.visual;
    if (!v) continue;
    const phase = signalPhase(sig, nowSec, cycleSec);
    const d = v.dims;
    setLampLit(v.redMat, phase === "red", d.redOn, d.redOff);
    setLampLit(v.amberMat, phase === "amber", d.amberOn, d.amberOff);
    setLampLit(v.greenMat, phase === "green", d.greenOn, d.greenOff);
    // Pedestrians walk while cars on this approach are held (red only — not amber).
    const walk = phase === "red";
    setLampLit(v.pedRedMat, !walk, d.pedRedOn, d.pedRedOff);
    setLampLit(v.pedGreenMat, walk, d.pedGreenOn, d.pedGreenOff);
  }
}

/** Hide baked GLB signal lamps (always-on colours); runtime heads own the aspect. */
function hideBakedSignalLamps(scene) {
  if (!scene || typeof scene.traverse !== "function") return;
  scene.traverse((obj) => {
    const n = obj.name || "";
    if (/^signal_\d/i.test(n)) obj.visible = false;
  });
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
  // GLB cars are authored with wheels on y=0; old box cars used a 0.75 m lift because their
  // geometry was centred on the origin. Both meshes are now grounded — sit on the asphalt.
  outPos.y = ROAD_Y;
}

/**
 * Offset a centreline sample into the driver's own lane: the right-hand side of the
 * direction the car is actually travelling (Belgium drives on the right). `travelTan` is
 * the car's heading, i.e. the path tangent flipped for reverse cars. Previously the offset
 * was taken from the path's *forward* tangent for every car, so cars running a road in
 * both directions shared one lane and drove straight through each other head-on.
 */
function applyLane(path, travelTan, outPos) {
  const lane = path.laneOffset ?? LANE_OFFSET;
  outPos.x += -travelTan.z * lane;
  outPos.z += travelTan.x * lane;
}

function makeSharedParts(THREE) {
  // Lamps: dull glass by day, glowing at night (see setNight). Unlit + fog-exempt tone
  // mapping so they stay punchy against the dark street. Box geos are the headless fallback.
  return makeLampParts(THREE, BODY_COLORS);
}

const HEAD_DAY = [0.81, 0.82, 0.8];
const HEAD_NIGHT = [1.0, 0.94, 0.72];
const TAIL_DAY = [0.12, 0.02, 0.02];
const TAIL_NIGHT = [1.0, 0.1, 0.08];

function makeBoxCarMesh(THREE, parts, colorIndex) {
  // Geometry is authored around y=0; shift so the wheel bottoms sit on y=0 (same as GLB cars).
  const group = new THREE.Group();
  const body = new THREE.Mesh(parts.bodyGeo, parts.bodyMats[colorIndex % parts.bodyMats.length]);
  body.position.y = 0.675;
  const cabin = new THREE.Mesh(parts.cabinGeo, parts.glassMat);
  cabin.position.set(0, 1.375, 0.1);
  group.add(body, cabin);
  // +z is the direction of travel (rotation.y = atan2(tan.x, tan.z)).
  for (const sx of [-0.55, 0.55]) {
    const head = new THREE.Mesh(parts.lampGeo, parts.headMat);
    head.position.set(sx, 0.595, 2.11);
    const tail = new THREE.Mesh(parts.lampGeo, parts.tailMat);
    tail.position.set(sx, 0.695, -2.11);
    group.add(head, tail);
  }
  const wheels = [];
  for (const [lx, lz] of [
    [0.85, 1.35],
    [-0.85, 1.35],
    [0.85, -1.35],
    [-0.85, -1.35],
  ]) {
    const wheel = new THREE.Mesh(parts.wheelGeo, parts.tireMat);
    wheel.position.set(lx, 0.225, lz);
    group.add(wheel);
    wheels.push(wheel);
  }
  group.userData.wheels = wheels;
  group.userData.wheelRadius = 0.32;
  group.userData.halfL = HALF_L;
  group.userData.halfW = HALF_W;
  group.userData.carId = "box";
  return group;
}

function makeCarMesh(THREE, parts, colorIndex, templates) {
  const template = pickCarTemplate(templates);
  if (template) return cloneCarMesh(THREE, parts, template);
  return makeBoxCarMesh(THREE, parts, colorIndex);
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
    // Entering `other` at its start means driving it forwards, at its end backwards: only
    // roads that may be driven that way are on the menu (never a one-way street's wrong end).
    if (dStart < SNAP_M && mayDrive(other, false)) {
      const inTan = entryTangent(other, false, THREE);
      candidates.push({ index: i, reverse: false, d: dStart, align: outTan.dot(inTan) });
    }
    if (dEnd < SNAP_M && mayDrive(other, true)) {
      const inTan = entryTangent(other, true, THREE);
      candidates.push({ index: i, reverse: true, d: dEnd, align: outTan.dot(inTan) });
    }
  }
  // A one-way road cannot turn round at its end, and swinging back onto the opposite
  // carriageway is not a junction either: with no legal way on, the car leaves the map and
  // re-enters elsewhere (advanceJunction → respawnCar).
  if (!candidates.length || (path.dir !== 0 && candidates.every((c) => c.align < -0.5))) {
    if (path.dir !== 0) {
      return { index: paths.indexOf(path), reverse: !atEnd, flip: true, recycle: true, align: -1 };
    }
    return { index: paths.indexOf(path), reverse: !atEnd ? false : true, flip: true, align: -1 };
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

function createCar(paths, THREE, parts, templates) {
  const index = (Math.random() * paths.length) | 0;
  const path = paths[index];
  const reverse = legalReverse(path);
  const s = 2 + Math.random() * Math.max(1, path.length * 0.8 - 4);
  const colorIndex = (Math.random() * BODY_COLORS.length) | 0;
  const mesh = makeCarMesh(THREE, parts, colorIndex, templates);
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
    next: null, // planned hand-off onto the next road (see NEXT_LOOKAHEAD)
    headOnLoser: false, // lower-priority half of a nose-to-nose standoff this frame
    holdEntry: false, // waiting at the end of the road for the next road's entry to clear
    ignoreSignalsUntil: 0,
    wait: "",
    evict: false, // set by transit.js when this car keeps a tram / bus from moving
  };
}

function placeCar(car, paths, THREE) {
  const path = paths[car.pathIndex];
  const s = car.reverse ? path.length - car.s : car.s;
  samplePath(path, s, THREE, car.pos, car.tan);
  if (car.reverse) {
    car.tan.multiplyScalar(-1);
  }
  applyLane(path, car.tan, car.pos);
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
  // Amber is not green: approaching cars must stop when they can.
  return signalPhase(sig, nowSec, cycleSec) === "green";
}

/**
 * @param {import('three').Scene} scene
 * @param {typeof import('three')} THREE
 * @param {{ count?: number }} [opts]
 */
export async function createTraffic(scene, THREE, opts = {}) {
  // Fixed same-origin data file (no caller-supplied URL).
  let data;
  try {
    const res = await fetch(ROADS_URL);
    if (!res.ok) throw new Error(`roads.json ${res.status}`);
    data = await res.json();
  } catch (err) {
    console.warn("Traffic disabled — could not load roads:", err);
    return { update() {}, dispose() {}, pedMayCross: () => true };
  }
  const paths = buildPaths(data.roads || [], THREE);
  if (paths.length < 2) {
    console.warn("Traffic disabled — not enough road paths");
    return { update() {}, dispose() {}, pedMayCross: () => true };
  }

  const cycleSec = Number(data.cycleSeconds) || CYCLE_SEC;
  const { signals } = buildSignals(data.signals || [], THREE, cycleSec, paths);
  /** @type {Map<number, (typeof signals)[0]>} first head per OSM crossing node */
  const signalByOsm = new Map();
  for (const sig of signals) {
    if (sig.osmId && !signalByOsm.has(sig.osmId)) signalByOsm.set(sig.osmId, sig);
  }
  const count = fleetCount(paths, opts.count);

  const root = new THREE.Group();
  root.name = "RuntimeTraffic";
  scene.add(root);
  hideBakedSignalLamps(scene);
  const signalDisposables = buildSignalVisuals(signals, THREE, root);
  updateSignalVisuals(signals, 0, cycleSec);
  const parts = makeSharedParts(THREE);
  const templates = (await loadCarTemplates(THREE)) || [];
  if (templates.length) {
    console.info(`[cityview] Traffic fleet: ${templates.length} Antwerp-weighted car models`);
  } else {
    console.warn("[cityview] Traffic fleet: using box cars (GLB templates unavailable)");
  }

  const cars = [];
  shared.cars = cars;
  for (let i = 0; i < count; i++) {
    const car = createCar(paths, THREE, parts, templates);
    let tries = 0;
    while (tries < 20) {
      placeCar(car, paths, THREE);
      const clash = cars.some((c) => c.pos.distanceToSquared(car.pos) < 256);
      if (!clash) break;
      car.pathIndex = (Math.random() * paths.length) | 0;
      car.s = 2 + Math.random() * Math.max(1, paths[car.pathIndex].length * 0.8 - 4);
      car.reverse = legalReverse(paths[car.pathIndex]);
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

  /**
   * Lane centre for a vehicle heading (tx, tz) on the car road nearest (x, z); see lanes.js.
   * Only roads the vehicle may legally drive that way count (`mode` "bus" honours
   * oneway:bus), so a bus never snaps into the lane of a one-way carriageway it would be
   * driving the wrong way down.
   *
   * Buses search a wider corridor, ignore short residential spurs, and prefer
   * boulevard/secondary ribbons (GTFS shapes on Mechelsesteenweg often sit on the
   * building-side asphalt strip past the sidewalk instead of the main carriageway).
   */
  const BUS_KIND_RANK = {
    motorway: 6,
    trunk: 5,
    primary: 4,
    secondary: 3,
    tertiary: 2,
    unclassified: 1,
    residential: 0,
    living_street: -1,
  };
  /** Dual-carriageway link roads (e.g. Mechelsesteenweg spur 4480699) — not bus lanes. */
  const BUS_MIN_LOCAL_M = 40;
  function laneAt(x, z, tx, tz, out, mode = "car") {
    const maxD = mode === "bus" ? 10.0 : 4.5;
    let bestScore = maxD;
    let found = false;
    for (let i = 0; i < paths.length; i++) {
      const path = paths[i];
      if (
        mode === "bus" &&
        (path.kind === "residential" || path.kind === "living_street" || path.kind === "unclassified") &&
        path.length < BUS_MIN_LOCAL_M
      ) {
        continue;
      }
      const pts = path.points;
      const rank = BUS_KIND_RANK[path.kind] ?? 0;
      const dualBonus = path.dual ? 0.8 : 0;
      for (let k = 0; k < pts.length - 1; k++) {
        const a = pts[k];
        const b = pts[k + 1];
        const dx = b.x - a.x;
        const dz = b.z - a.z;
        const l2 = dx * dx + dz * dz;
        if (l2 < 1e-6) continue;
        const t = Math.max(0, Math.min(1, ((x - a.x) * dx + (z - a.z) * dz) / l2));
        const px = a.x + dx * t;
        const pz = a.z + dz * t;
        const d = Math.hypot(x - px, z - pz);
        if (d >= maxD) continue;
        const len = Math.sqrt(l2);
        let ux = dx / len;
        let uz = dz / len;
        const dot = ux * tx + uz * tz;
        if (Math.abs(dot) < 0.7) continue;
        const legal = mode === "bus" ? path.busDir : path.dir;
        if (legal !== 0 && legal !== (dot < 0 ? -1 : 1)) continue;
        if (dot < 0) {
          ux = -ux;
          uz = -uz;
        }
        // Cars: nearest road. Buses: distance minus class rank so a secondary several
        // metres away beats a residential spur under the GTFS polyline.
        const score = mode === "bus" ? d - rank * 1.4 - dualBonus : d;
        if (score >= bestScore) continue;
        const lane = path.laneOffset ?? LANE_OFFSET;
        bestScore = score;
        out.x = px - uz * lane;
        out.z = pz + ux * lane;
        found = true;
      }
    }
    return found;
  }
  shared.laneAt = laneAt;

  // Trams / buses are drawn by transit.js; cars give way to them via this provider.
  let obstacleProvider = null;
  /** `() => [{ x, z, r }, …]` upright pedestrians in the street. */
  let pedProvider = null;
  /** `(x, z, vx, vz, r) => void` — knock a ped down when a car cannot stop in time. */
  let onHitPed = null;
  /** `(speed, vx, vz) => void` — player hit by a car that failed to stop. */
  let onHitPlayer = null;
  const obstacleCache = [];
  function obstacleList() {
    obstacleCache.length = 0;
    const src = obstacleProvider ? obstacleProvider() : null;
    if (src) {
      for (const v of src) {
        if (!v || !v.pos || !v.tan || v.phase === "gone") continue;
        const tram = v.mode === "tram";
        const bike = v.mode === "bike" || v.mode === "bicycle" || v.mode === "scooter" || v.mode === "cargo";
        const hl = tram ? 16.0 : bike ? 0.9 : 6.8;
        const hw = tram ? 1.2 : bike ? 0.45 : 1.25;
        // Micromobility exposes `cur`; transit uses `velocity`.
        const speed = Number.isFinite(v.velocity) ? v.velocity : v.cur || 0;
        obstacleCache.push({ isObstacle: true, pos: v.pos, tan: v.tan, velocity: speed, hl, hw });
      }
    }
    return obstacleCache;
  }

  /** Is `o` (centre/tangent/half extents) intersecting the corridor `car` sweeps ahead? */
  function inCorridor(car, lookahead, o, zone = ZONE_HALF_W) {
    const dx = o.pos.x - car.pos.x;
    const dz = o.pos.z - car.pos.z;
    const ahead = dx * car.tan.x + dz * car.tan.z;
    const side = dx * car.tan.z - dz * car.tan.x;
    // Extent of the other footprint projected on our axes.
    const c = o.tan.x * car.tan.x + o.tan.z * car.tan.z;
    const sn = o.tan.x * car.tan.z - o.tan.z * car.tan.x;
    const extAhead = o.hl * Math.abs(c) + o.hw * Math.abs(sn);
    const extSide = o.hl * Math.abs(sn) + o.hw * Math.abs(c);
    if (ahead <= 0.3) return null; // beside / behind: their problem, not ours
    if (ahead - extAhead > HALF_L + lookahead) return null;
    if (Math.abs(side) - extSide > zone) return null;
    return { gap: ahead - extAhead - HALF_L };
  }

  /** SAT overlap of two oriented boxes (centre, unit tangent, half length/width, margin). */
  function boxesOverlap(ax, az, at, ahl, ahw, bx, bz, bt, bhl, bhw, margin) {
    const dx = bx - ax;
    const dz = bz - az;
    const axes = [at.x, at.z, at.z, -at.x, bt.x, bt.z, bt.z, -bt.x];
    for (let k = 0; k < 8; k += 2) {
      const ux = axes[k];
      const uz = axes[k + 1];
      const d = Math.abs(dx * ux + dz * uz);
      const ra = ahl * Math.abs(at.x * ux + at.z * uz) + ahw * Math.abs(at.z * ux - at.x * uz);
      const rb = bhl * Math.abs(bt.x * ux + bt.z * uz) + bhw * Math.abs(bt.z * ux - bt.x * uz);
      if (d > ra + rb + margin) return false;
    }
    return true;
  }

  const _poseP = new THREE.Vector3();
  const _poseT = new THREE.Vector3();
  /**
   * Where will `car` be after driving `dist` metres? Follows its planned hand-off onto the
   * next road so turning cars are predicted along the turn, not along a straight line.
   */
  function poseAt(car, dist, out) {
    let path = paths[car.pathIndex];
    let reverse = car.reverse;
    let s = car.s + dist;
    if (s > path.length - 0.5) {
      if (car.next) {
        s = 1 + (s - (path.length - 0.5));
        path = paths[car.next.index];
        reverse = car.next.flip ? !reverse : car.next.reverse;
      }
      s = Math.min(s, path.length);
    }
    samplePath(path, reverse ? path.length - s : s, THREE, _poseP, _poseT);
    if (reverse) _poseT.multiplyScalar(-1);
    applyLane(path, _poseT, _poseP);
    out.x = _poseP.x;
    out.z = _poseP.z;
    out.tan.x = _poseT.x;
    out.tan.z = _poseT.z;
  }
  const _fa = { x: 0, z: 0, tan: { x: 0, z: 0 } };
  const _fb = { x: 0, z: 0, tan: { x: 0, z: 0 } };

  /**
   * Will our footprint touch `other`'s within the next ~1.5 s if both keep driving their
   * (planned) roads at the current speed? Catches turning / merging traffic that a straight
   * corridor misses. Returns the along-heading gap to brake for, or null.
   */
  function futureConflict(car, other) {
    const dx = other.pos.x - car.pos.x;
    const dz = other.pos.z - car.pos.z;
    const ahead = dx * car.tan.x + dz * car.tan.z;
    if (ahead <= 0.3) return null;
    for (let k = 0; k < FUTURE_T.length; k++) {
      const t = FUTURE_T[k];
      poseAt(car, Math.max(0, car.velocity) * t, _fa);
      poseAt(other, Math.max(0, other.velocity) * t, _fb);
      if (boxesOverlap(_fa.x, _fa.z, _fa.tan, HALF_L, HALF_W, _fb.x, _fb.z, _fb.tan, HALF_L, HALF_W, 0.15)) {
        const c = other.tan.x * car.tan.x + other.tan.z * car.tan.z;
        const sn = other.tan.x * car.tan.z - other.tan.z * car.tan.x;
        const extAhead = HALF_L * Math.abs(c) + HALF_W * Math.abs(sn);
        return { gap: ahead - extAhead - HALF_L };
      }
    }
    return null;
  }

  /** Nearest other car / obstacle centre to a point (for clearance checks). */
  function nearestOther(car, pos) {
    let minD = Infinity;
    for (const other of cars) {
      if (other === car) continue;
      minD = Math.min(minD, pos.distanceTo(other.pos));
    }
    for (const o of obstacleList()) {
      minD = Math.min(minD, pos.distanceTo(o.pos));
    }
    return minD;
  }

  /**
   * Despawn a dead car and put it back on a free road. Returns false (car stays put, caller
   * retries next frame) when no spot with enough clearance exists, so a respawn can never
   * drop a car on top of another one.
   */
  const respawnCounts = {};
  function respawnCar(car, why = "blocked") {
    if (globalThis.__DBG_RESP) globalThis.__DBG_RESP(car, why, cars, paths, simTime);
    let best = null;
    const origin = { pathIndex: car.pathIndex, reverse: car.reverse, s: car.s };
    for (let attempt = 0; attempt < 48; attempt++) {
      const pathIndex = (Math.random() * paths.length) | 0;
      const reverse = legalReverse(paths[pathIndex]);
      const s = 2 + Math.random() * Math.max(1, paths[pathIndex].length * 0.85 - 4);
      car.pathIndex = pathIndex;
      car.reverse = reverse;
      car.s = s;
      placeCar(car, paths, THREE);
      const minD = nearestOther(car, car.pos);
      const playerD = playerPos.lengthSq() > 0 ? car.pos.distanceTo(playerPos) : 80;
      // Never respawn in front of the player's nose either.
      if (minD < RESPAWN_CLEARANCE || playerD < 12) continue;
      const score = Math.min(minD, 40) + Math.min(playerD, 60) * 0.35;
      if (!best || score > best.score) {
        best = { pathIndex, reverse, s, score };
      }
      if (minD > 24 && playerD > 35) break;
    }
    if (!best) {
      car.pathIndex = origin.pathIndex;
      car.reverse = origin.reverse;
      car.s = origin.s;
      placeCar(car, paths, THREE);
      return false;
    }
    car.pathIndex = best.pathIndex;
    car.reverse = best.reverse;
    car.s = best.s;
    const path = paths[car.pathIndex];
    car.velocity = path.speedLimit * car.driver * 0.7;
    car.stuck = 0;
    car.blocked = 0;
    car.queued = 0;
    car.redWait = 0;
    car.ignoreSignalsUntil = simTime + 3;
    car.wait = "";
    car.next = null;
    car.holdEntry = false;
    car.lateral = 0;
    respawnCounts[why] = (respawnCounts[why] || 0) + 1;
    placeCar(car, paths, THREE);
    return true;
  }

  const _entry = { pathIndex: 0, reverse: false, s: 0, next: null };
  /** Would a car dropped onto (pathIndex, reverse, s) overlap any other car right now? */
  function entryBlocked(car, pathIndex, reverse, s) {
    _entry.pathIndex = pathIndex;
    _entry.reverse = reverse;
    _entry.s = s;
    poseAt(_entry, 0, _fa);
    const me = cars.indexOf(car);
    for (let j = 0; j < cars.length; j++) {
      const other = cars[j];
      if (other === car) continue;
      // Our own followers (same road, same way, behind us) are waiting for *us*; only a real
      // overlap counts, otherwise leader and follower would block each other forever.
      if (other.pathIndex === car.pathIndex && other.reverse === car.reverse && other.s < car.s) {
        if (boxesOverlap(_fa.x, _fa.z, _fa.tan, HALF_L, HALF_W, other.pos.x, other.pos.z, other.tan, HALF_L, HALF_W, -0.4)) {
          return other;
        }
        continue;
      }
      // Fixed priority again: a lower-index car only yields to a physical overlap, so two
      // cars can never hold each other's drop points hostage.
      const lowerPriority = j > me;
      const margin = lowerPriority ? 0.1 : 0.5;
      if (boxesOverlap(_fa.x, _fa.z, _fa.tan, HALF_L, HALF_W, other.pos.x, other.pos.z, other.tan, HALF_L, HALF_W, margin)) {
        return other;
      }
      if (lowerPriority) continue;
      // ...and where it is about to be (a car still rolling toward the drop point).
      poseAt(other, Math.max(0, other.velocity) * 0.6, _fb);
      if (boxesOverlap(_fa.x, _fa.z, _fa.tan, HALF_L, HALF_W, _fb.x, _fb.z, _fb.tan, HALF_L, HALF_W, 0.5)) {
        return other;
      }
    }
    for (const o of obstacleList()) {
      if (boxesOverlap(_fa.x, _fa.z, _fa.tan, HALF_L, HALF_W, o.pos.x, o.pos.z, o.tan, o.hl, o.hw, 0.1)) return o;
      // A tram / bus rolling toward the drop point (it will be there in a second or two).
      if (o.velocity > 0.5) {
        const reach = o.velocity * 1.8 + 1.5;
        if (boxesOverlap(_fa.x, _fa.z, _fa.tan, HALF_L, HALF_W, o.pos.x + o.tan.x * reach * 0.5, o.pos.z + o.tan.z * reach * 0.5, o.tan, o.hl + reach * 0.5, o.hw, 0.3)) return o;
      }
    }
    return null;
  }

  /**
   * Hand the car over to the next road. Returns false (car stays at the end of its road,
   * stopped) when the drop point is occupied: teleporting onto another car is exactly how
   * cars ended up sharing a footprint at junctions and dead-end U-turns.
   */
  function advanceJunction(car, overshoot) {
    const path = paths[car.pathIndex];
    const atEnd = !car.reverse;
    const next = car.next || pickNextPath(paths, path, atEnd, cars, car, THREE);
    if (next.recycle) {
      // End of a one-way road with no legal way on (map edge / dead end): it may not turn
      // round, so it leaves and re-enters on a free road, always in a legal direction.
      car.next = null;
      if (respawnCar(car, "oneway-end")) return true;
      car.s = path.length - 0.5; // no free spot yet: wait at the end, retry next step
      car.velocity = 0;
      return false;
    }
    const nextPath = paths[next.index];
    // Sharp turns / U-turns swing the car's body back across the road it came from, onto the
    // car following it. Drop it a car-half-length further along so it clears that lane.
    const sharp = next.flip || next.align < 0.3;
    const entryS = Math.min(
      Math.max(1.0, next.flip ? 1.0 : overshoot) + (sharp ? HALF_L + 0.6 : 0),
      Math.max(1.0, nextPath.length - 1),
    );
    const newReverse = next.flip ? !car.reverse : next.reverse;
    if (entryBlocked(car, next.index, newReverse, entryS)) {
      car.next = next;
      car.holdEntry = true;
      car.s = path.length - 0.55;
      car.velocity = 0;
      return false;
    }
    car.holdEntry = false;
    car.next = null;
    car.pathIndex = next.index;
    car.reverse = newReverse;
    car.s = entryS;
    if (next.flip) {
      car.velocity = Math.min(car.velocity, TURN_SPEED);
    } else if (next.align < 0.7) {
      // Slow through sharp turns; they re-accelerate toward the new road's limit.
      car.velocity = Math.min(car.velocity, TURN_SPEED);
    }
    return true;
  }

  /** Max speed that still lets us stop within `gap` metres (v^2 = 2*a*d). */
  function stopSpeed(gap) {
    return gap <= 0 ? 0 : Math.sqrt(2 * BRAKE * gap);
  }

  /**
   * Speed that keeps us behind a leader moving at `leaderV`: match it plus the braking
   * headroom, but when we are already closer than the standstill gap drop *below* the
   * leader's speed so the gap re-opens instead of persisting (or shrinking) forever.
   */
  function followSpeed(leaderV, gap) {
    // Plan for the leader to brake harder than we comfortably can (a car ahead stopping for a
    // tram / bus drops from cruise to 0 in ~1 s), so a queue forming at a halt never concertinas.
    return Math.max(0, leaderV * 0.95 + (gap >= 0 ? Math.sqrt(2 * BRAKE * 0.65 * gap) : gap * 1.5));
  }

  /**
   * Advance by `dt` wall-clock seconds in sub-steps of at most MAX_STEP. The old update()
   * clamped one big step to 0.05 s, so on a 10-15 fps machine the whole street (lights, queues,
   * pulling away) ran at 40-75% speed and read as "standing still".
   */
  function update(dt, walkObject) {
    if (!(dt > 0)) return;
    if (walkObject) {
      playerPos.set(walkObject.position.x, 0, walkObject.position.z);
    }
    const total = Math.min(dt, MAX_FRAME);
    const n = Math.max(1, Math.ceil(total / MAX_STEP));
    const h = total / n;
    for (let i = 0; i < n; i++) stepSim(h, walkObject);
    updateSignalVisuals(signals, simTime, cycleSec);
  }

  function stepSim(step, walkObject) {
    simTime += step;

    for (let i = 0; i < cars.length; i++) {
      const car = cars[i];
      // A tram / bus has been held up by this car for too long: it is dead weight, clear it.
      if (car.evict) {
        car.evict = false;
        if (respawnCar(car, "evict")) continue;
      }
      const roadPath = paths[car.pathIndex];
      placeCar(car, paths, THREE);

      const cruise = roadPath.speedLimit * car.driver;
      car.speed = cruise;
      let desire = cruise;
      let lateralNudge = 0;
      let reason = "";
      let leader = null;
      car.headOnLoser = false;

      // Lookahead for the swept corridor: our braking distance plus a margin.
      const lookahead = Math.min(22, Math.max(4, (car.velocity * car.velocity) / (2 * BRAKE) + 3.5));
      {
        for (let j = 0; j < cars.length; j++) {
          if (i === j) continue;
          const other = cars[j];
          const dx = other.pos.x - car.pos.x;
          const dz = other.pos.z - car.pos.z;
          const distSq = dx * dx + dz * dz;
          if (distSq > CROSS_REACH * CROSS_REACH) continue;
          const heading = other.tan.x * car.tan.x + other.tan.z * car.tan.z;
          // Crossing / merging / turning traffic: never drive into a footprint that sits in
          // our swept corridor. Priority is a fixed total order (lower index goes first) and
          // only applies when both cars see each other, so it cannot deadlock in a cycle.
          if (heading < 0.7) {
            const mine = inCorridor(car, lookahead, { pos: other.pos, tan: other.tan, hl: HALF_L, hw: HALF_W });
            if (mine) {
              const theirs = inCorridor(
                other,
                Math.min(22, Math.max(4, (other.velocity * other.velocity) / (2 * BRAKE) + 3.5)),
                { pos: car.pos, tan: car.tan, hl: HALF_L, hw: HALF_W },
              );
              const headOn = theirs && heading < HEAD_ON_DOT;
              // Oncoming cars share the closing distance: both brake for half the gap each,
              // so neither relies on the other to get out of the way in time.
              const hasPriority = theirs && i < j && !headOn;
              if (headOn) car.headOnLoser = i > j;
              if (!hasPriority) {
                const safe = stopSpeed(headOn ? (mine.gap - 1.0) * 0.5 : mine.gap - 1.2);
                if (safe < desire) {
                  desire = Math.max(0, safe);
                  reason = "cross";
                  leader = other;
                }
              }
            } else {
              const fut = futureConflict(car, other);
              if (fut) {
                // Overlap is symmetric: the car whose front half contains the other yields,
                // and when both see each other the higher index gives way.
                const otherSeesUs = futureConflict(other, car);
                const headOn = !!otherSeesUs && heading < HEAD_ON_DOT;
                if (headOn) car.headOnLoser = i > j;
                if (!otherSeesUs || i > j || headOn) {
                  const safe = stopSpeed(headOn ? (fut.gap - 1.0) * 0.5 : fut.gap - 1.0);
                  if (safe < desire) {
                    desire = Math.max(0, safe);
                    reason = "cross";
                    leader = other;
                  }
                }
              }
            }
          }
          if (distSq > (FOLLOW_DIST + 14) ** 2) continue;
          // Only follow leaders on a similar heading (same corridor / same way).
          if (heading < 0.35) continue;
          const ahead = dx * car.tan.x + dz * car.tan.z;
          const side = dx * car.tan.z + dz * -car.tan.x;
          if (ahead > 0.5 && Math.abs(side) < 2.8) {
            const gap = ahead - CAR_LEN - STANDSTILL_GAP;
            // Match the leader's speed plus whatever braking distance remains.
            const safe = followSpeed(other.velocity, gap);
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

      // Junction hand-off: choose the next road early and do not roll onto it while its
      // entry is occupied (another car just turned in, or is merging from a side road).
      // Without this two cars spawn into the same spot of the next road and overlap.
      const remaining = roadPath.length - 0.5 - car.s;
      if (!car.next && remaining < NEXT_LOOKAHEAD) {
        car.next = pickNextPath(paths, roadPath, !car.reverse, cars, car, THREE);
      }
      if (car.holdEntry) {
        desire = 0;
        reason = "cross";
        if (car.next && !car.next.recycle) {
          const b = entryBlocked(
            car,
            car.next.index,
            car.next.flip ? !car.reverse : car.next.reverse,
            car.next.flip || car.next.align < 0.3 ? 1.0 + HALF_L + 0.6 : 1.0,
          );
          if (b && b.isObstacle) reason = "transit";
          else if (b) leader = b;
        }
      }
      if (car.next && !car.next.recycle && remaining < NEXT_LOOKAHEAD) {
        const nx = car.next;
        // Do not roll up to the hand-off while the drop point is occupied: stop short of it
        // smoothly instead of being held at the last moment (a hard stop gets us rear-ended).
        {
          const nReverse = nx.flip ? !car.reverse : nx.reverse;
          const nEntryS = nx.flip || nx.align < 0.3 ? 1.0 + HALF_L + 0.6 : 1.0;
          const blocker = entryBlocked(car, nx.index, nReverse, nEntryS);
          if (blocker) {
            const safe = stopSpeed(remaining - 1.5);
            if (safe < desire) {
              desire = safe;
              reason = blocker.isObstacle ? "transit" : "cross";
              leader = blocker.isObstacle ? null : blocker;
            }
          }
        }
        // Sharp turn / U-turn ahead: ease down to turning speed *before* the hand-off so the
        // speed never snaps (a sudden drop makes the car behind rear-end it).
        if (nx.flip || nx.align < 0.7) {
          const eased = Math.sqrt(TURN_SPEED * TURN_SPEED + 2 * BRAKE * 0.7 * Math.max(0, remaining));
          if (eased < desire) desire = eased;
        }
        for (let j = 0; j < cars.length; j++) {
          if (i === j) continue;
          const other = cars[j];
          let gapS = null;
          let leaderSpeed = other.velocity;
          if (other.pathIndex === nx.index && other.reverse === nx.reverse) {
            // Already driving the road we are about to enter.
            gapS = remaining + Math.max(0, other.s - 1) - CAR_LEN - STANDSTILL_GAP;
          } else if (
            other.next &&
            other.next.index === nx.index &&
            other.next.reverse === nx.reverse &&
            other.pathIndex !== car.pathIndex
          ) {
            // Competing for the same entry: whoever is closer (then lower index) goes first.
            const oRem = paths[other.pathIndex].length - 0.5 - other.s;
            if (oRem < remaining - 0.5 || (Math.abs(oRem - remaining) <= 0.5 && j < i)) {
              gapS = remaining - oRem - CAR_LEN - STANDSTILL_GAP;
              leaderSpeed = 0;
            }
          }
          if (gapS === null) continue;
          const safe = followSpeed(leaderSpeed, gapS);
          if (safe < desire) {
            desire = Math.max(0, safe);
            reason = "cross";
            leader = other;
          }
        }
      }

      // Trams and buses (transit.js) always have right of way over cars.
      {
        const obstacles = obstacleList();
        for (let o = 0; o < obstacles.length; o++) {
          const ob = obstacles[o];
          const same = ob.tan.x * car.tan.x + ob.tan.z * car.tan.z > 0.5;
          let hit;
          if (same) {
            // Same way: follow it like a leader.
            hit = inCorridor(car, lookahead + 8, ob, OBSTACLE_ZONE);
            if (!hit) continue;
            const safe = followSpeed(ob.velocity * 0.95, hit.gap - STANDSTILL_GAP);
            if (safe < desire) {
              desire = Math.max(0, safe);
              reason = "transit";
            }
            continue;
          }
          // Crossing / oncoming: respect the ground it will sweep over in the next ~2.5 s.
          const reach = ob.velocity > 0.5 ? ob.velocity * 2.5 + 1 : 0;
          const swept = {
            pos: { x: ob.pos.x + ob.tan.x * reach * 0.5, z: ob.pos.z + ob.tan.z * reach * 0.5 },
            tan: ob.tan,
            hl: ob.hl + reach * 0.5,
            hw: ob.hw,
          };
          hit = inCorridor(car, lookahead + 2, swept, OBSTACLE_ZONE);
          if (!hit) continue;
          const safe = stopSpeed(hit.gap - 1.5);
          if (safe < desire) {
            desire = Math.max(0, safe);
            reason = "transit";
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
            // Could not stop: the car strikes the player.
            if (
              onHitPlayer &&
              car.velocity > PED_HIT_SPEED &&
              ahead < CAR_LEN * 0.55 + 0.6 &&
              side < 1.15
            ) {
              onHitPlayer(car.velocity, car.tan.x * car.velocity, car.tan.z * car.velocity);
            }
          }
        }
      }

      // Pedestrians in the lane: brake like for the player; hard overlaps knock them down.
      {
        const peds = pedProvider ? pedProvider() : null;
        if (peds && peds.length) {
          for (let p = 0; p < peds.length; p++) {
            const ped = peds[p];
            const dx = ped.x - car.pos.x;
            const dz = ped.z - car.pos.z;
            if (dx * dx + dz * dz > (PED_STOP_DIST + 12) ** 2) continue;
            const ahead = dx * car.tan.x + dz * car.tan.z;
            const side = Math.abs(dx * car.tan.z + dz * -car.tan.x);
            const pr = ped.r ?? 0.35;
            if (ahead > 0.15 && side < 2.2 + pr) {
              const safe = stopSpeed(ahead - CAR_LEN * 0.5 - pr - 0.6);
              if (safe < desire) {
                desire = Math.max(0, safe);
                reason = "ped";
              }
              if (
                onHitPed &&
                car.velocity > PED_HIT_SPEED &&
                ahead < CAR_LEN * 0.5 + pr + 0.45 &&
                side < 1.05 + pr
              ) {
                onHitPed(ped.x, ped.z, car.tan.x * car.velocity, car.tan.z * car.velocity, 0.95);
              }
            }
          }
        }
      }

      // Queueing behind a car that is itself waiting at a red / for the player / a ped is fine.
      if (
        (reason === "car" || reason === "cross") &&
        leader &&
        (leader.wait === "red" || leader.wait === "queue" || leader.wait === "player" || leader.wait === "ped")
      ) {
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

      // Kinematic follow: accelerate gently, brake as hard as needed.
      if (desire > car.velocity) {
        car.velocity = Math.min(desire, car.velocity + ACCEL * step);
      } else {
        car.velocity = Math.max(desire, car.velocity - BRAKE * 2.2 * step);
      }
      // Snap to rest only when we actually want to be at rest. Clamping on speed alone
      // zeroes every launch once ACCEL*step < 0.05 (>= ~52 fps), so cars that stopped at
      // a red could never pull away again on 60/120 Hz displays.
      if (car.velocity < 0.05 && desire < 0.05) car.velocity = 0;
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
      } else if (crawling && reason === "transit") {
        // A tram/bus dwelling at a halt is a legitimate wait (up to a minute+ for the first tram).
        car.redWait = 0;
        car.blocked += step;
        if (car.blocked > TRANSIT_PATIENCE_SEC && respawnCar(car, "transit")) {
          continue;
        }
      } else if (crawling && (reason === "car" || reason === "cross" || reason === "player" || reason === "ped")) {
        car.redWait = 0;
        car.blocked += step;
        // Truly dead (gridlock / blocked far longer than any light or dwell): despawn
        // it onto a free road. Never slide through the blocker and leave a ghost.
        // Waiting for a walker is legitimate — same patience as waiting for the player.
        const limit =
          car.headOnLoser && reason === "cross"
            ? HEAD_ON_RESPAWN_SEC
            : reason === "player" || reason === "ped"
              ? PLAYER_PATIENCE_SEC
              : BLOCK_RESPAWN_SEC;
        if (car.blocked > limit && respawnCar(car, `${reason}${limit === HEAD_ON_RESPAWN_SEC ? "-headon" : ""}${car.holdEntry ? "-hold" : ""}`)) {
          continue;
        }
      } else if (crawling) {
        // Stopped with no explanation (bad data, zero-speed road): recover fast.
        car.redWait = 0;
        car.stuck += step;
        if (car.stuck > STUCK_SEC && respawnCar(car, "stuck")) {
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
      const wheels = car.mesh.userData.wheels;
      if (wheels && wheels.length && car.velocity > 0.05) {
        const spin = (car.velocity * step) / (car.mesh.userData.wheelRadius || 0.32);
        for (const w of wheels) w.rotation.x += spin;
      }
    }
  }

  /** Debug / test helper. */
  function stats() {
    let moving = 0;
    let sum = 0;
    const waits = { red: 0, queue: 0, car: 0, cross: 0, transit: 0, player: 0, ped: 0, "?": 0 };
    for (const c of cars) {
      if (c.velocity > 0.5) moving++;
      sum += c.velocity;
      if (c.wait) waits[c.wait] = (waits[c.wait] || 0) + 1;
    }
    return { moving, total: cars.length, avgKmh: (sum / Math.max(1, cars.length)) * 3.6, waits, respawns: { ...respawnCounts } };
  }

  function dispose() {
    scene.remove(root);
    parts.bodyGeo.dispose();
    parts.cabinGeo.dispose();
    parts.wheelGeo.dispose();
    parts.glassMat.dispose();
    parts.tireMat.dispose();
    parts.lampGeo.dispose();
    parts.headMat.dispose();
    parts.tailMat.dispose();
    for (const m of parts.bodyMats) m.dispose();
    for (const m of parts.paintMats.values()) m.dispose();
    for (const d of signalDisposables) {
      if (d && typeof d.dispose === "function") d.dispose();
    }
  }

  /** Night glow for every car's head/tail lamps: 0 = day, 1 = full night. */
  function setNight(t) {
    parts.headMat.color.setRGB(
      HEAD_DAY[0] + (HEAD_NIGHT[0] - HEAD_DAY[0]) * t,
      HEAD_DAY[1] + (HEAD_NIGHT[1] - HEAD_DAY[1]) * t,
      HEAD_DAY[2] + (HEAD_NIGHT[2] - HEAD_DAY[2]) * t,
    );
    parts.tailMat.color.setRGB(
      TAIL_DAY[0] + (TAIL_NIGHT[0] - TAIL_DAY[0]) * t,
      TAIL_DAY[1] + (TAIL_NIGHT[1] - TAIL_DAY[1]) * t,
      TAIL_DAY[2] + (TAIL_NIGHT[2] - TAIL_DAY[2]) * t,
    );
  }

  /** Let cars give way to other vehicles: `() => [...transit.vehicles, ...bikes]`. */
  function setObstacles(provider) {
    obstacleProvider = typeof provider === "function" ? provider : null;
  }

  /** `() => [{ x, z, r }]` — upright pedestrians cars should brake for. */
  function setPedestrians(provider) {
    pedProvider = typeof provider === "function" ? provider : null;
  }

  /** Called when a car strikes a pedestrian it could not stop for. */
  function setOnHitPed(fn) {
    onHitPed = typeof fn === "function" ? fn : null;
  }

  /** Called when a car strikes the player it could not stop for. */
  function setOnHitPlayer(fn) {
    onHitPlayer = typeof fn === "function" ? fn : null;
  }

  /**
   * Pedestrian walk light for a ``cross{osmId}`` route: true when cars on that
   * approach are red (same rule as the ped signal head). Unlinked zebras always allow.
   */
  function pedMayCross(routeId) {
    const m = /^cross(\d+)/.exec(routeId || "");
    if (!m) return true;
    const sig = signalByOsm.get(Number(m[1]));
    if (!sig) return true;
    return signalPhase(sig, simTime, cycleSec) === "red";
  }

  return {
    update,
    dispose,
    stats,
    setObstacles,
    setPedestrians,
    setOnHitPed,
    setOnHitPlayer,
    setNight,
    pedMayCross,
    cars,
    paths,
    count: cars.length,
    pathCount: paths.length,
    signalCount: signals.length,
  };
}
