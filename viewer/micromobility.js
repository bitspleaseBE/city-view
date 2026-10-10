/**
 * Micromobility: bicycles, e-scooters, and electric cargo bikes.
 * Ride kerb-side on driveable OSM roads (cycleway export not required).
 * Procedural vehicle meshes + Mixamo riders (Riding / Scooter clips).
 */
import { clone as cloneSkeleton } from "three/addons/utils/SkeletonUtils.js";
import { fitHumanoid } from "./humanoid-fit.js";
import { makeShareScooter } from "./scooters.js";
import { loadCharacterTemplates } from "./characters.js";
import { shared } from "./lanes.js";

const KMH = 1 / 3.6;
const SNAP_M = 14;
const BIKE_LANE_EXTRA = 1.45; // m outside car lane, toward the kerb
const SPAWN_GAP = 7; // m between riders at spawn
const LOOK_AHEAD = 9; // m: riders react to anything this far ahead in their lane
const LOOK_AHEAD_HARD = 22; // m: trams / buses are long — brake earlier
const LANE_HALF = 0.55; // m: half a bike's swept width
const HARD_SIDE = 2.4; // m: notice a tram/bus on a parallel track before riding into it
const STOP_GAP = 1.6; // m nose-to-tail when queued
const SWERVE = 0.75; // m to the right when an oncoming rider shares the lane
const OVERTAKE = 1.3; // m to the left when passing something that blocks the lane
const HARD_HIT_SPEED = 1.5; // m/s closing → knock-down (not a soft brush)
const CRASH_KILL_SPEED = 7.5; // m/s closing with a tram/bus → lethal
const CRASH_LIE_S = 3.2; // s on the deck before scramble / clear
const CRASH_DEAD_S = 9; // s before a killed rider is cleared

/** Shared lamp materials so setNight can brighten every rider at once. */
let _lampMat = null;
let _tailMat = null;

function nightMats(THREE) {
  if (!_lampMat) {
    _lampMat = new THREE.MeshStandardMaterial({
      color: 0xfff6dd,
      emissive: 0xfff2cc,
      emissiveIntensity: 0,
      roughness: 0.4,
    });
    _tailMat = new THREE.MeshStandardMaterial({
      color: 0xa01010,
      emissive: 0xff2020,
      emissiveIntensity: 0,
      roughness: 0.45,
    });
  }
  return { lamp: _lampMat, tail: _tailMat };
}

function addBikeLights(THREE, g, frontZ, rearZ, y = 0.55) {
  const { lamp, tail } = nightMats(THREE);
  const head = new THREE.Mesh(new THREE.SphereGeometry(0.035, 8, 6), lamp);
  head.position.set(0, y, frontZ);
  const back = new THREE.Mesh(new THREE.BoxGeometry(0.05, 0.03, 0.025), tail);
  back.position.set(0, y - 0.05, rearZ);
  g.add(head, back);
}

// Pedals and bars relative to the saddle top (m, +Z forward). The baked Riding clip
// (scripts/bake_mixamo_rider_clips.py) puts ankles and wrists on exactly these points.
const RIDE = { bbFwd: 0.2, bbDown: 0.54, crank: 0.16, barFwd: 0.46, barUp: 0.08, gripHalf: 0.3 };

const DRIVEABLE = new Set([
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

const KINDS = {
  bicycle: {
    label: "bicycle",
    weight: 0.5,
    speedKmh: 18,
    color: [0x2a6a9a, 0xc44a3a, 0x3a8a5a, 0x1a1a1a, 0xe8c040],
  },
  scooter: {
    label: "scooter",
    weight: 0.3,
    speedKmh: 20,
    color: [0x00c2a8, 0x6b4cff, 0xff3d6e, 0x222222], // shared-fleet vibes
  },
  cargo: {
    label: "cargo",
    weight: 0.2,
    speedKmh: 15,
    color: [0x3a5a78, 0xd4a020, 0x5a7a4a, 0x8a4a3a],
  },
};

function blenderToThree(x, y, out) {
  out.set(x, 0, -y);
  return out;
}

function pickKind() {
  const r = Math.random();
  if (r < KINDS.bicycle.weight) return "bicycle";
  if (r < KINDS.bicycle.weight + KINDS.scooter.weight) return "scooter";
  return "cargo";
}

function buildPaths(roads, THREE) {
  const paths = [];
  for (const road of roads) {
    const kind = String(road.kind || "residential").toLowerCase();
    if (!DRIVEABLE.has(kind)) continue;
    const pts = road.points || [];
    if (pts.length < 2) continue;
    const points = [];
    for (const p of pts) points.push(blenderToThree(p[0], p[1], new THREE.Vector3()));
    const cleaned = [points[0]];
    for (let i = 1; i < points.length; i++) {
      if (cleaned[cleaned.length - 1].distanceToSquared(points[i]) > 0.05) cleaned.push(points[i]);
    }
    if (cleaned.length < 2) continue;
    const cumulative = [0];
    let len = 0;
    for (let i = 1; i < cleaned.length; i++) {
      len += cleaned[i].distanceTo(cleaned[i - 1]);
      cumulative.push(len);
    }
    if (len < 8) continue;
    // Skip dual-carriageway link stubs / alley scraps — not rideable streets.
    if ((kind === "residential" || kind === "living_street" || kind === "unclassified") && len < 35) continue;
    const carLane = Number.isFinite(road.laneOffset) ? road.laneOffset : 1.15;
    const width = road.width || 6;
    // Sit between the car lane and the kerb (Belgian right-hand cycling).
    const bikeOffset = Math.min(width * 0.48, carLane + BIKE_LANE_EXTRA);
    const oneway = Number(road.oneway) || 0;
    paths.push({
      id: road.id,
      kind,
      dir: oneway === 1 || oneway === -1 ? oneway : 0,
      width,
      bikeOffset,
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
  if (outTan.lengthSq() < 1e-8) outTan.set(1, 0, 0);
  else outTan.normalize();
  outPos.y = 0;
}

function applyBikeLane(path, travelTan, outPos) {
  // Right-hand side of travel direction (Belgium).
  outPos.x += -travelTan.z * path.bikeOffset;
  outPos.z += travelTan.x * path.bikeOffset;
}

function makeWheel(THREE, tireMat, rimMat, radius, thick = 0.04) {
  const g = new THREE.Group();
  const tire = new THREE.Mesh(new THREE.TorusGeometry(radius, thick, 6, 14), tireMat);
  tire.rotation.y = Math.PI / 2;
  const hub = new THREE.Mesh(new THREE.CylinderGeometry(thick * 1.2, thick * 1.2, thick * 1.5, 8), rimMat);
  hub.rotation.z = Math.PI / 2;
  g.add(tire, hub);
  g.userData.spin = true;
  return g;
}

function makeProceduralRider(THREE, seated) {
  const g = new THREE.Group();
  const skin = new THREE.MeshLambertMaterial({ color: 0xd4a882 });
  const cloth = new THREE.MeshLambertMaterial({
    color: [0x3a5068, 0x6a4a5a, 0x4a6a5a, 0x5a5a78][(Math.random() * 4) | 0],
  });
  const torso = new THREE.Mesh(
    new THREE.CapsuleGeometry(0.14, seated ? 0.35 : 0.45, 3, 6),
    cloth
  );
  torso.position.y = seated ? 0.95 : 1.15;
  if (seated) torso.rotation.x = 0.35;
  const head = new THREE.Mesh(new THREE.SphereGeometry(0.12, 8, 8), skin);
  head.position.y = seated ? 1.35 : 1.55;
  head.position.z = seated ? 0.08 : 0;
  g.add(torso, head);
  g.userData = { hipsY: seated ? 0.75 : null };
  return g;
}

function makeMixamoRider(THREE, templates, seated) {
  if (!templates.length) return makeProceduralRider(THREE, seated);
  const tmpl = templates[(Math.random() * templates.length) | 0];
  const root = cloneSkeleton(tmpl.scene);
  root.traverse((o) => {
    if (o.isMesh) {
      o.castShadow = true;
      o.receiveShadow = true;
      o.frustumCulled = true;
    }
  });

  // Clips are baked for a 1.70 m rider; stay close so hands and feet land on the controls.
  const hipsY = fitHumanoid(THREE, root, 1.67 + Math.random() * 0.06);

  const mixer = new THREE.AnimationMixer(root);
  let action = null;
  if (tmpl.clips.length) {
    const clip =
      tmpl.clips.find((c) => (seated ? /rid|bike|cycl/i : /scoot|kick/i).test(c.name)) ||
      tmpl.clips[0];
    action = mixer.clipAction(clip);
    action.enabled = true;
    action.setEffectiveTimeScale(1);
    action.setEffectiveWeight(1);
    action.setLoop(THREE.LoopRepeat, Infinity);
    action.play();
    action.time = Math.random() * clip.duration;
  }

  root.userData = { mixamo: true, mixer, action, hipsY };
  return root;
}

function makeRider(THREE, templates, seated) {
  return makeMixamoRider(THREE, templates, seated);
}

/** Put a fitted rider's pelvis just above the saddle (feet are at the rider's y = 0). */
function seatRider(rider, saddleY, saddleZ) {
  const hipsY = rider.userData.hipsY ?? 0.9;
  rider.position.y += saddleY + 0.07 - hipsY;
  rider.position.z = saddleZ;
}

/** Thin cylinder from a to b (each [x, y, z]). */
function tube(THREE, mat, a, b, r) {
  const A = new THREE.Vector3(...a);
  const B = new THREE.Vector3(...b);
  const dir = B.clone().sub(A);
  const m = new THREE.Mesh(new THREE.CylinderGeometry(r, r, dir.length(), 8), mat);
  m.position.copy(A).addScaledVector(dir, 0.5);
  m.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), dir.normalize());
  return m;
}

function handlebar(THREE, metal, gripMat, y, z) {
  const h = RIDE.gripHalf;
  return [
    tube(THREE, metal, [-h - 0.04, y, z], [h + 0.04, y, z], 0.012),
    tube(THREE, gripMat, [h - 0.05, y, z], [h + 0.05, y, z], 0.018),
    tube(THREE, gripMat, [-h + 0.05, y, z], [-h - 0.05, y, z], 0.018),
  ];
}

function makeBicycle(THREE, color, rideTemplates) {
  const g = new THREE.Group();
  const frameMat = new THREE.MeshLambertMaterial({ color });
  const tireMat = new THREE.MeshLambertMaterial({ color: 0x1a1a1a });
  const metal = new THREE.MeshLambertMaterial({ color: 0x777777 });

  // Diamond-frame city bike (NPC traffic — distinct from docked Velo step-throughs), front +Z.
  const R = 0.32; // wheel radius
  const rearHub = [0, R, -0.52];
  const frontHub = [0, R, 0.52];
  const saddleY = 0.82;
  const saddleZ = -0.27;
  const bb = [0, saddleY - RIDE.bbDown, saddleZ + RIDE.bbFwd]; // bottom bracket
  const barY = saddleY + RIDE.barUp;
  const barZ = saddleZ + RIDE.barFwd;
  const seatTop = [0, 0.7, -0.25];
  const headTop = [0, 0.76, 0.33];
  const headBot = [0, 0.6, 0.38];
  const parts = [
    tube(THREE, frameMat, bb, seatTop, 0.02), // seat tube
    tube(THREE, frameMat, [0, 0.67, -0.24], headTop, 0.02), // top tube
    tube(THREE, frameMat, bb, headBot, 0.024), // down tube
    tube(THREE, frameMat, headBot, headTop, 0.026), // head tube
    tube(THREE, frameMat, [0.05, ...bb.slice(1)], [0.05, ...rearHub.slice(1)], 0.012), // chainstays
    tube(THREE, frameMat, [-0.05, ...bb.slice(1)], [-0.05, ...rearHub.slice(1)], 0.012),
    tube(THREE, frameMat, [0.04, ...seatTop.slice(1)], [0.05, ...rearHub.slice(1)], 0.011), // seatstays
    tube(THREE, frameMat, [-0.04, ...seatTop.slice(1)], [-0.05, ...rearHub.slice(1)], 0.011),
    tube(THREE, metal, [0.04, ...headBot.slice(1)], [0.04, ...frontHub.slice(1)], 0.012), // fork
    tube(THREE, metal, [-0.04, ...headBot.slice(1)], [-0.04, ...frontHub.slice(1)], 0.012),
    tube(THREE, metal, seatTop, [0, saddleY - 0.02, saddleZ], 0.014), // seat post
    tube(THREE, metal, headTop, [0, barY, barZ], 0.014), // stem
    ...handlebar(THREE, metal, tireMat, barY, barZ),
    tube(THREE, metal, [-0.09, ...bb.slice(1)], [0.09, ...bb.slice(1)], 0.012), // crank axle
  ];
  const saddle = new THREE.Mesh(new THREE.BoxGeometry(0.15, 0.05, 0.26), tireMat);
  saddle.position.set(0, saddleY, saddleZ);

  const front = makeWheel(THREE, tireMat, metal, R, 0.025);
  front.position.set(...frontHub);
  const rear = makeWheel(THREE, tireMat, metal, R, 0.025);
  rear.position.set(...rearHub);

  g.add(...parts, saddle, front, rear);
  addBikeLights(THREE, g, 0.42, -0.4, 0.72);
  const rider = makeRider(THREE, rideTemplates, true);
  seatRider(rider, saddleY, saddleZ);
  g.add(rider);
  g.userData.wheels = [front, rear];
  g.userData.rider = rider;
  return g;
}

function makeScooter(THREE, color, scooterTemplates) {
  const g = new THREE.Group();
  // Same model as the parked share scooters; that one faces −Z, NPC traffic faces +Z.
  const body = makeShareScooter(THREE, { name: `npc-${color}`, body: color, trim: 0xf4f6f8, deck: 0x22262b });
  body.rotation.y = Math.PI;
  body.userData.kickstand.visible = false;
  g.add(body);
  addBikeLights(THREE, g, 0.47, -0.5, 0.44);
  const rider = makeRider(THREE, scooterTemplates, false);
  // Deck top and stance; the baked Scooter clip reaches grips 0.99 m up and 0.34 m ahead.
  rider.position.y += 0.175;
  rider.position.z = -0.08;
  g.add(rider);
  g.userData.wheels = body.userData.wheels;
  g.userData.wheelSign = -1; // wheels live in the flipped frame
  g.userData.wheelR = 0.15;
  g.userData.rider = rider;
  return g;
}

function makeCargoBike(THREE, color, rideTemplates) {
  const g = new THREE.Group();
  const frameMat = new THREE.MeshLambertMaterial({ color });
  const boxMat = new THREE.MeshLambertMaterial({ color: 0xe8e0d0 });
  const tireMat = new THREE.MeshLambertMaterial({ color: 0x1a1a1a });
  const metal = new THREE.MeshLambertMaterial({ color: 0x777777 });

  // Longtail / bakfiets-ish: rider mid, cargo box in front
  const frame = new THREE.Mesh(new THREE.BoxGeometry(0.08, 0.07, 1.55), frameMat);
  frame.position.set(0, 0.4, 0.05);
  const box = new THREE.Mesh(new THREE.BoxGeometry(0.55, 0.45, 0.7), boxMat);
  box.position.set(0, 0.45, 0.75);
  const lid = new THREE.Mesh(new THREE.BoxGeometry(0.58, 0.04, 0.72), frameMat);
  lid.position.set(0, 0.7, 0.75);

  const saddleY = 0.82;
  const saddleZ = -0.45;
  const bb = [0, saddleY - RIDE.bbDown, saddleZ + RIDE.bbFwd];
  const barY = saddleY + RIDE.barUp;
  const barZ = saddleZ + RIDE.barFwd;
  const seatPost = tube(THREE, metal, [0, 0.4, saddleZ + 0.04], [0, saddleY - 0.02, saddleZ], 0.022);
  const seat = new THREE.Mesh(new THREE.BoxGeometry(0.16, 0.05, 0.24), tireMat);
  seat.position.set(0, saddleY, saddleZ);
  const stem = tube(THREE, metal, [0, 0.4, barZ - 0.08], [0, barY, barZ], 0.02);
  const bars = handlebar(THREE, metal, tireMat, barY, barZ);
  const bbTube = tube(THREE, frameMat, [0, 0.4, bb[2] - 0.05], bb, 0.025);
  const crank = tube(THREE, metal, [-0.09, bb[1], bb[2]], [0.09, bb[1], bb[2]], 0.012);

  const frontL = makeWheel(THREE, tireMat, metal, 0.22);
  frontL.position.set(-0.34, 0.22, 0.85);
  const frontR = makeWheel(THREE, tireMat, metal, 0.22);
  frontR.position.set(0.34, 0.22, 0.85);
  const rear = makeWheel(THREE, tireMat, metal, 0.28);
  rear.position.set(0, 0.28, -0.65);

  // Small battery pack under the frame
  const battery = new THREE.Mesh(new THREE.BoxGeometry(0.12, 0.1, 0.35), new THREE.MeshLambertMaterial({ color: 0x222222 }));
  battery.position.set(0, 0.28, -0.15);

  g.add(frame, box, lid, seatPost, seat, stem, ...bars, bbTube, crank, frontL, frontR, rear, battery);
  addBikeLights(THREE, g, 1.05, -0.7, 0.7);
  const rider = makeRider(THREE, rideTemplates, true);
  seatRider(rider, saddleY, saddleZ);
  g.add(rider);
  g.userData.wheels = [frontL, frontR, rear];
  g.userData.rider = rider;
  return g;
}

function makeVehicle(THREE, kind, rideTemplates, scooterTemplates) {
  const cfg = KINDS[kind];
  const colors = cfg.color;
  const color = colors[(Math.random() * colors.length) | 0];
  if (kind === "scooter") return makeScooter(THREE, color, scooterTemplates);
  if (kind === "cargo") return makeCargoBike(THREE, color, rideTemplates);
  return makeBicycle(THREE, color, rideTemplates);
}

function buildHandoffs(paths, THREE) {
  // Tip → nearby tips for soft junction hops
  const tips = [];
  for (const path of paths) {
    tips.push({ path, atEnd: false, pos: path.start });
    tips.push({ path, atEnd: true, pos: path.end });
  }
  const links = new Map(); // key pathId|atEnd|reverse -> candidates
  for (let i = 0; i < tips.length; i++) {
    const a = tips[i];
    const cands = [];
    for (let j = 0; j < tips.length; j++) {
      if (i === j) continue;
      const b = tips[j];
      if (a.path === b.path) continue;
      if (a.pos.distanceTo(b.pos) > SNAP_M) continue;
      // Enter the other path away from the tip we snapped to
      const reverse = b.atEnd; // enter from end → travel reverse
      if (b.path.dir === 1 && reverse) continue;
      if (b.path.dir === -1 && !reverse) continue;
      cands.push({ path: b.path, reverse, s: reverse ? b.path.length - 0.5 : 0.5 });
    }
    links.set(`${a.path.id}:${a.atEnd ? "e" : "s"}`, cands);
  }
  return links;
}


export async function createMicromobility(scene, THREE, opts = {}) {
  const COUNT = opts.count ?? 28;

  let roads = [];
  try {
    // Fixed relative path only (opts.roadsUrl ignored — avoids SSRF on user-controlled URLs).
    const res = await fetch("./roads.json");
    if (res.ok) {
      const data = await res.json();
      roads = data.roads || [];
    }
  } catch (err) {
    console.warn("[cityview] micromobility: roads.json failed", err);
  }

  const paths = buildPaths(roads, THREE);
  if (!paths.length) {
    console.warn("[cityview] micromobility: no bikeable paths");
    return { update() {}, dispose() {}, vehicles: [], count: 0 };
  }

  const [rideTemplates, scooterTemplates] = await Promise.all([
    loadCharacterTemplates("Riding"),
    loadCharacterTemplates("Scooter"),
  ]);

  const handoffs = buildHandoffs(paths, THREE);
  const root = new THREE.Group();
  root.name = "Micromobility";
  scene.add(root);

  const _pos = new THREE.Vector3();
  const _tan = new THREE.Vector3();
  const vehicles = [];

  function place(v) {
    samplePath(v.path, v.s, THREE, _pos, _tan);
    if (v.reverse) _tan.negate();
    applyBikeLane(v.path, _tan, _pos);
    if (v.swerve) {
      _pos.x += -_tan.z * v.swerve;
      _pos.z += _tan.x * v.swerve;
    }
    v.mesh.position.copy(_pos);
    v.mesh.rotation.y = Math.atan2(_tan.x, _tan.z);
    v.pos.set(_pos.x, 0, _pos.z);
    v.tan.set(_tan.x, 0, _tan.z);
  }

  function legalDirs(path) {
    if (path.dir === 1) return [false];
    if (path.dir === -1) return [true];
    return [false, true];
  }

  function spawnOne() {
    // Pick a free spot: never spawn a rider on top of another one (they would ride as one).
    let path = paths[0];
    let reverse = false;
    let s = 0.5;
    for (let attempt = 0; attempt < 12; attempt++) {
      path = paths[(Math.random() * paths.length) | 0];
      const dirs = legalDirs(path);
      reverse = dirs[(Math.random() * dirs.length) | 0];
      s = Math.random() * path.length * 0.9 + 0.5;
      samplePath(path, s, THREE, _pos, _tan);
      if (!vehicles.some((o) => o.pos.distanceToSquared(_pos) < SPAWN_GAP * SPAWN_GAP)) break;
    }
    const kind = pickKind();
    const cfg = KINDS[kind];
    const speed = cfg.speedKmh * KMH * (0.85 + Math.random() * 0.3);
    const mesh = makeVehicle(THREE, kind, rideTemplates, scooterTemplates);
    root.add(mesh);
    const v = {
      kind,
      path,
      reverse,
      s,
      speed,
      cur: speed,
      swerve: 0,
      mesh,
      pos: new THREE.Vector3(),
      tan: new THREE.Vector3(),
      wheelPhase: Math.random() * Math.PI * 2,
    };
    place(v);
    vehicles.push(v);
  }

  /**
   * Keep riders apart: follow the one ahead in the same lane, swerve right for oncoming
   * riders sharing the lane, and brake for the walker / other obstacles on the bike lane.
   * Oriented obstacles (trams / buses: `{ x, z, tx, tz, hl, hw, hard }`) are solid — riders
   * brake and never try to overtake through them.
   */
  function targetSpeed(v, obstacles) {
    let gap = Infinity;
    let oncoming = false;
    let hardBlock = false;
    const tx = v.tan.x;
    const tz = v.tan.z;
    const consider = (ox, oz, otx, otz, radius) => {
      const dx = ox - v.pos.x;
      const dz = oz - v.pos.z;
      const along = dx * tx + dz * tz;
      if (along <= 0 || along > LOOK_AHEAD) return;
      const lat = Math.abs(dx * tz - dz * tx);
      if (lat > LANE_HALF + radius) return;
      if (otx * tx + otz * tz < -0.3) oncoming = true;
      gap = Math.min(gap, along - radius);
    };
    const considerBox = (ob) => {
      const dx = ob.x - v.pos.x;
      const dz = ob.z - v.pos.z;
      const hl = ob.hl ?? 1;
      const hw = ob.hw ?? 1;
      const ahead = dx * tx + dz * tz;
      const reach = (ob.hard ? LOOK_AHEAD_HARD : LOOK_AHEAD) + hl;
      if (ahead < -hl || ahead > reach) return;
      const lat = Math.abs(dx * tz - dz * tx);
      // Soft lane box for cars; hard transit is noticed from the neighbouring track too
      // so riders brake instead of overtaking into a tram that looks "beside" them.
      const side = ob.hard ? HARD_SIDE + hw : LANE_HALF + hw;
      if (lat > side) return;
      const otx = ob.tx || 0;
      const otz = ob.tz || 0;
      if (otx * tx + otz * tz < -0.3) oncoming = true;
      // Closing on the box: prefer the nose gap; if already alongside, treat as zero gap.
      const nose = ahead - hl;
      gap = Math.min(gap, lat > LANE_HALF + hw * 0.85 ? Math.max(0.2, nose) : nose);
      if (ob.hard) hardBlock = true;
    };
    for (const o of vehicles) {
      if (o === v) continue;
      // Tipped wrecks are static debris in the lane — brake for them, do not ride through.
      if (o.crash) {
        consider(o.pos.x, o.pos.z, 0, 0, 0.85);
        continue;
      }
      consider(o.pos.x, o.pos.z, o.tan.x, o.tan.z, 0.5);
    }
    for (const ob of obstacles) {
      if (ob.hl != null) considerBox(ob);
      else consider(ob.x, ob.z, 0, 0, ob.r ?? 0.4);
    }
    // Held up for a while behind something that is not moving: pull out and pass on the left —
    // never past a tram / bus (they fill the lane; "passing" would ride through them).
    v.stuck = gap < STOP_GAP + 1 && v.cur < 0.5 ? (v.stuck || 0) + dtSwerve : 0;
    if (!hardBlock && v.stuck > 2.5) {
      v.overtake = 3.5; // s spent out in the passing line
      v.stuck = 0;
    }
    if (hardBlock) v.overtake = 0;
    if (v.overtake > 0) v.overtake -= dtSwerve;
    const passing = v.overtake > 0 && !oncoming && !hardBlock;
    const want = oncoming ? SWERVE : passing ? -OVERTAKE : 0;
    const k = Math.min(1, dtSwerve * 2.5);
    v.swerve += (want - v.swerve) * k;
    if (passing) return v.speed * 0.6;
    if (gap === Infinity) return v.speed;
    // Hard stop in front of a tram / bus that already overlaps the bike's nose.
    if (hardBlock && gap < STOP_GAP) return 0;
    return v.speed * Math.max(0, Math.min(1, (gap - STOP_GAP) / (LOOK_AHEAD - STOP_GAP)));
  }
  let dtSwerve = 0;

  for (let i = 0; i < COUNT; i++) spawnOne();
  shared.bikes = vehicles;

  console.info(
    `[cityview] micromobility: ${vehicles.length} riders` +
      ` (${vehicles.filter((v) => v.kind === "bicycle").length} bikes,` +
      ` ${vehicles.filter((v) => v.kind === "scooter").length} scooters,` +
      ` ${vehicles.filter((v) => v.kind === "cargo").length} cargo)` +
      ` · Mixamo ride=${rideTemplates.length} scooter=${scooterTemplates.length}`
  );

  function advanceEnd(v) {
    const atEnd = !v.reverse;
    const key = `${v.path.id}:${atEnd ? "e" : "s"}`;
    const cands = handoffs.get(key) || [];
    if (cands.length) {
      const next = cands[(Math.random() * cands.length) | 0];
      v.path = next.path;
      v.reverse = next.reverse;
      v.s = next.s;
      return;
    }
    // Dead end: U-turn if the road allows both ways, else teleport to a random path
    if (v.path.dir === 0) {
      v.reverse = !v.reverse;
      v.s = Math.max(0.5, Math.min(v.path.length - 0.5, v.s));
    } else {
      const path = paths[(Math.random() * paths.length) | 0];
      v.path = path;
      v.reverse = legalDirs(path)[0];
      v.s = Math.random() * path.length * 0.8;
    }
  }

  /** Nearest hard tram/bus the rider's body is inside, or null. */
  function hardHit(v, obstacles) {
    let best = null;
    let bestD = Infinity;
    for (const ob of obstacles) {
      if (!ob.hard || ob.hl == null) continue;
      const dx = v.pos.x - ob.x;
      const dz = v.pos.z - ob.z;
      const otx = ob.tx || 0;
      const otz = ob.tz || 0;
      const along = dx * otx + dz * otz;
      const lat = Math.abs(dx * otz - dz * otx);
      if (Math.abs(along) >= (ob.hl ?? 1) * 0.95 || lat >= (ob.hw ?? 1) * 0.95) continue;
      const d = Math.abs(along) + lat;
      if (d < bestD) {
        bestD = d;
        best = ob;
      }
    }
    return best;
  }

  /** Put the rider back on a free path after an accident (or after lying dead is cleared). */
  function respawnRider(v) {
    const path = paths[(Math.random() * paths.length) | 0];
    v.path = path;
    v.reverse = legalDirs(path)[0];
    v.s = Math.random() * Math.max(1, path.length - 2) + 0.5;
    v.cur = 0;
    v.swerve = 0;
    v.overtake = 0;
    v.stuck = 0;
    v.crash = null;
    v.mesh.rotation.x = 0;
    v.mesh.rotation.z = 0;
    v.mesh.visible = true;
    const rider = v.mesh.userData.rider;
    if (rider) {
      rider.visible = true;
      if (rider.userData?.action) rider.userData.action.setEffectiveTimeScale(1);
    }
    place(v);
  }

  /**
   * Real-world hit: tip the bike, throw the rider, damage by closing speed.
   * Trams never swerve — the bike takes the hit; violent ones kill and clear later.
   */
  function startCrash(v, ob) {
    const otx = ob.tx || 0;
    const otz = ob.tz || 0;
    // Throw off the track: bike heading plus a shove from the consist's flank.
    const dx = v.pos.x - ob.x;
    const dz = v.pos.z - ob.z;
    let nx = dx - (dx * otx + dz * otz) * otx;
    let nz = dz - (dx * otx + dz * otz) * otz;
    let nl = Math.hypot(nx, nz);
    if (nl < 0.05) {
      // Dead-centre hit: shove sideways off the track instead of nowhere.
      nx = -otz;
      nz = otx;
      nl = 1;
    }
    nx /= nl;
    nz /= nl;
    const speed = Math.max(v.cur, 0);
    const closing = speed + Math.max(0, Number(ob.speed) || 0);
    const kick = 2.2 + closing * 0.55;
    const dead = closing >= CRASH_KILL_SPEED;
    v.cur = 0;
    v.swerve = 0;
    v.overtake = 0;
    v.stuck = 0;
    v.crash = {
      t: 0,
      dead,
      vx: v.tan.x * Math.max(speed, 1.2) * 0.35 + nx * kick,
      vz: v.tan.z * Math.max(speed, 1.2) * 0.35 + nz * kick,
      vy: 1.1 + closing * 0.18,
      y: 0.15,
      roll: 0,
      spin: 3.8 + closing * 0.35,
      lie: dead ? CRASH_DEAD_S : CRASH_LIE_S,
    };
    const rider = v.mesh.userData.rider;
    if (rider?.userData?.action) rider.userData.action.setEffectiveTimeScale(0);
  }

  function updateCrash(v, dt, obstacles = []) {
    const c = v.crash;
    c.t += dt;
    const airborne = c.y > 0 || c.vy > 0;
    const hs = Math.hypot(c.vx, c.vz);
    if (hs > 0.05) {
      v.mesh.position.x += c.vx * dt;
      v.mesh.position.z += c.vz * dt;
      v.pos.x = v.mesh.position.x;
      v.pos.z = v.mesh.position.z;
      // Do not slide the wreck back through a tram/bus body.
      if (hardHit(v, obstacles)) {
        c.vx *= -0.15;
        c.vz *= -0.15;
        v.mesh.position.x += c.vx * dt;
        v.mesh.position.z += c.vz * dt;
        v.pos.x = v.mesh.position.x;
        v.pos.z = v.mesh.position.z;
      }
      if (!airborne) {
        const slow = Math.max(0, hs - 6 * dt) / hs;
        c.vx *= slow;
        c.vz *= slow;
      }
    }
    if (airborne) {
      c.vy -= 9.81 * dt;
      c.y = Math.max(0, c.y + c.vy * dt);
      if (c.y === 0) c.vy = 0;
    }
    // Tip onto the side while thrown.
    if (c.roll < Math.PI / 2) c.roll = Math.min(Math.PI / 2, c.roll + c.spin * dt);
    v.mesh.rotation.z = c.roll;
    v.mesh.position.y = c.y + Math.sin(c.roll) * 0.35;
    if (c.roll >= Math.PI / 2 - 1e-3 && hs < 0.08 && !airborne) {
      c.lie -= dt;
      if (c.lie <= 0) {
        if (c.dead) {
          // Violent hit: clear the wreck and put a fresh rider elsewhere.
          respawnRider(v);
        } else {
          // Survived: scramble back onto the network (no ghosting through the tram).
          respawnRider(v);
        }
      }
    }
  }

  function update(dt, obstacles = [], cam = null) {
    if (!(dt > 0)) return;
    dtSwerve = dt;
    const cx = cam ? cam.x : null;
    const cz = cam ? cam.z : null;
    const hot2 = 60 * 60;
    const cold2 = 180 * 180;
    for (const v of vehicles) {
      if (v.crash) {
        updateCrash(v, dt, obstacles);
        continue;
      }

      const d2 =
        cx == null ? 0 : (v.pos.x - cx) * (v.pos.x - cx) + (v.pos.z - cz) * (v.pos.z - cz);
      if (d2 > cold2) {
        v.mesh.visible = false;
        // Still advance on the path so they don't pile up far away.
        v.s += (v.reverse ? -v.speed : v.speed) * dt * 0.85;
        if (v.s >= v.path.length) {
          v.s = v.path.length - 0.01;
          advanceEnd(v);
        } else if (v.s <= 0) {
          v.s = 0.01;
          advanceEnd(v);
        }
        place(v);
        continue;
      }
      v.mesh.visible = true;

      const want = targetSpeed(v, obstacles);
      const rate = want < v.cur ? 6.0 : 1.6; // brake hard, pull away gently
      v.cur += Math.max(-rate * dt, Math.min(rate * dt, want - v.cur));
      const delta = v.cur * dt;
      v.s += v.reverse ? -delta : delta;
      if (v.s >= v.path.length) {
        v.s = v.path.length - 0.01;
        advanceEnd(v);
      } else if (v.s <= 0) {
        v.s = 0.01;
        advanceEnd(v);
      }
      place(v);

      // Far riders: skip hard-hit / skinned anim (still collide near the camera).
      if (d2 > hot2) {
        continue;
      }

      // Still inside a tram/bus after braking → accident: fly off, maybe die.
      const hit = hardHit(v, obstacles);
      if (hit) {
        const closing = Math.max(v.cur, 0) + Math.max(0, Number(hit.speed) || 0);
        if (closing >= HARD_HIT_SPEED || v.cur < 0.4) {
          startCrash(v, hit);
          continue;
        }
      }

      // Spin wheels
      v.wheelPhase += delta / (v.mesh.userData.wheelR || 0.32);
      const wheels = v.mesh.userData.wheels || [];
      const spin = v.wheelPhase * (v.mesh.userData.wheelSign || 1);
      for (const w of wheels) w.rotation.x = spin;

      const rider = v.mesh.userData.rider;
      if (rider?.userData?.mixer) {
        // Pedal / push cadence roughly tracks travel speed
        const scale = Math.max(0.05, Math.min(1.6, v.cur / 4.5));
        if (rider.userData.action) rider.userData.action.setEffectiveTimeScale(scale);
        rider.userData.mixer.update(dt);
      }
    }
  }

  function dispose() {
    scene.remove(root);
    for (const v of vehicles) {
      const rider = v.mesh.userData.rider;
      if (rider?.userData?.mixer) rider.userData.mixer.stopAllAction();
    }
    vehicles.length = 0;
    if (shared.bikes === vehicles) shared.bikes = null;
  }

  function setNight(glow) {
    const g = Math.max(0, Math.min(1, Number(glow) || 0));
    nightMats(THREE);
    _lampMat.emissiveIntensity = 0.25 + 1.8 * g;
    _tailMat.emissiveIntensity = 0.2 + 1.4 * g;
  }

  return {
    update,
    dispose,
    vehicles,
    count: vehicles.length,
    mixamo: rideTemplates.length > 0 || scooterTemplates.length > 0,
    setNight,
  };
}
