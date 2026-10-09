/**
 * Micromobility: bicycles, e-scooters, and electric cargo bikes.
 * Ride kerb-side on driveable OSM roads (cycleway export not required).
 * Procedural vehicle meshes + Mixamo riders (Riding / Scooter clips).
 */
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { clone as cloneSkeleton } from "three/addons/utils/SkeletonUtils.js";

const KMH = 1 / 3.6;
const SNAP_M = 14;
const BIKE_LANE_EXTRA = 1.45; // m outside car lane, toward the kerb
const SPAWN_GAP = 7; // m between riders at spawn
const LOOK_AHEAD = 9; // m: riders react to anything this far ahead in their lane
const LANE_HALF = 0.55; // m: half a bike's swept width
const STOP_GAP = 1.6; // m nose-to-tail when queued
const SWERVE = 0.75; // m to the right when an oncoming rider shares the lane
const OVERTAKE = 1.3; // m to the left when passing something that blocks the lane

const RIDING_FILES = [
  "Remy_Riding.glb",
  "Amy_Riding.glb",
  "James_Riding.glb",
  "Michelle_Riding.glb",
  "Aj_Riding.glb",
];

const SCOOTER_FILES = [
  "Remy_Scooter.glb",
  "Amy_Scooter.glb",
  "James_Scooter.glb",
  "Michelle_Scooter.glb",
  "Aj_Scooter.glb",
];

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

  const box = new THREE.Box3().setFromObject(root);
  const size = new THREE.Vector3();
  box.getSize(size);
  const targetH = seated ? 1.55 : 1.65;
  const s = size.y > 0.01 ? targetH / size.y : 1;
  root.scale.setScalar(s);
  box.setFromObject(root);
  root.position.y -= box.min.y;

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

  root.userData = { mixamo: true, mixer, action };
  return root;
}

function makeRider(THREE, templates, seated) {
  return makeMixamoRider(THREE, templates, seated);
}

function makeBicycle(THREE, color, rideTemplates) {
  const g = new THREE.Group();
  const frameMat = new THREE.MeshLambertMaterial({ color });
  const tireMat = new THREE.MeshLambertMaterial({ color: 0x1a1a1a });
  const metal = new THREE.MeshLambertMaterial({ color: 0x777777 });

  // Diamond-frame city bike (NPC traffic — distinct from docked Velo step-throughs).
  const top = new THREE.Mesh(new THREE.BoxGeometry(0.045, 0.045, 0.72), frameMat);
  top.position.set(0, 0.55, 0.02);
  const down = new THREE.Mesh(new THREE.BoxGeometry(0.04, 0.04, 0.7), frameMat);
  down.position.set(0, 0.32, 0.05);
  down.rotation.x = 0.42;
  const seatTube = new THREE.Mesh(new THREE.BoxGeometry(0.04, 0.35, 0.04), frameMat);
  seatTube.position.set(0, 0.42, -0.28);
  const seatPost = new THREE.Mesh(new THREE.CylinderGeometry(0.018, 0.018, 0.28, 6), metal);
  seatPost.position.set(0, 0.62, -0.28);
  const seat = new THREE.Mesh(new THREE.BoxGeometry(0.14, 0.04, 0.22), tireMat);
  seat.position.set(0, 0.78, -0.28);
  const stem = new THREE.Mesh(new THREE.CylinderGeometry(0.018, 0.018, 0.28, 6), metal);
  stem.position.set(0, 0.62, 0.36);
  const bars = new THREE.Mesh(new THREE.BoxGeometry(0.5, 0.028, 0.028), metal);
  bars.position.set(0, 0.78, 0.38);
  const fork = new THREE.Mesh(new THREE.BoxGeometry(0.03, 0.28, 0.03), metal);
  fork.position.set(0, 0.32, 0.42);

  const front = makeWheel(THREE, tireMat, metal, 0.3);
  front.position.set(0, 0.3, 0.46);
  const rear = makeWheel(THREE, tireMat, metal, 0.3);
  rear.position.set(0, 0.3, -0.46);

  g.add(top, down, seatTube, seatPost, seat, stem, bars, fork, front, rear);
  const rider = makeRider(THREE, rideTemplates, true);
  rider.position.set(0, 0.55, -0.22);
  g.add(rider);
  g.userData.wheels = [front, rear];
  g.userData.rider = rider;
  return g;
}

function makeScooter(THREE, color, scooterTemplates) {
  const g = new THREE.Group();
  const bodyMat = new THREE.MeshLambertMaterial({ color });
  const tireMat = new THREE.MeshLambertMaterial({ color: 0x1a1a1a });
  const metal = new THREE.MeshLambertMaterial({ color: 0xaaaaaa });

  const deck = new THREE.Mesh(new THREE.BoxGeometry(0.22, 0.06, 0.85), bodyMat);
  deck.position.set(0, 0.12, 0);
  const stem = new THREE.Mesh(new THREE.CylinderGeometry(0.025, 0.03, 0.95, 8), metal);
  stem.position.set(0, 0.55, 0.32);
  stem.rotation.x = -0.12;
  const bars = new THREE.Mesh(new THREE.CylinderGeometry(0.018, 0.018, 0.42, 6), metal);
  bars.rotation.z = Math.PI / 2;
  bars.position.set(0, 1.05, 0.38);
  const head = new THREE.Mesh(new THREE.BoxGeometry(0.12, 0.08, 0.06), bodyMat);
  head.position.set(0, 1.0, 0.42);

  const front = makeWheel(THREE, tireMat, metal, 0.12, 0.03);
  front.position.set(0, 0.12, 0.4);
  const rear = makeWheel(THREE, tireMat, metal, 0.12, 0.03);
  rear.position.set(0, 0.12, -0.38);

  g.add(deck, stem, bars, head, front, rear);
  const rider = makeRider(THREE, scooterTemplates, false);
  rider.position.set(0, 0.08, -0.08);
  g.add(rider);
  g.userData.wheels = [front, rear];
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

  const seatPost = new THREE.Mesh(new THREE.CylinderGeometry(0.022, 0.022, 0.4, 6), metal);
  seatPost.position.set(0, 0.55, -0.35);
  const seat = new THREE.Mesh(new THREE.BoxGeometry(0.16, 0.05, 0.24), tireMat);
  seat.position.set(0, 0.76, -0.35);
  const stem = new THREE.Mesh(new THREE.CylinderGeometry(0.02, 0.02, 0.4, 6), metal);
  stem.position.set(0, 0.58, -0.05);
  const bars = new THREE.Mesh(new THREE.CylinderGeometry(0.015, 0.015, 0.5, 6), metal);
  bars.rotation.z = Math.PI / 2;
  bars.position.set(0, 0.78, -0.02);

  const frontL = makeWheel(THREE, tireMat, metal, 0.22);
  frontL.position.set(-0.22, 0.22, 0.85);
  const frontR = makeWheel(THREE, tireMat, metal, 0.22);
  frontR.position.set(0.22, 0.22, 0.85);
  const rear = makeWheel(THREE, tireMat, metal, 0.28);
  rear.position.set(0, 0.28, -0.65);

  // Small battery pack under the frame
  const battery = new THREE.Mesh(new THREE.BoxGeometry(0.12, 0.1, 0.35), new THREE.MeshLambertMaterial({ color: 0x222222 }));
  battery.position.set(0, 0.28, -0.15);

  g.add(frame, box, lid, seatPost, seat, stem, bars, frontL, frontR, rear, battery);
  const rider = makeRider(THREE, rideTemplates, true);
  rider.position.set(0, 0.52, -0.32);
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

async function loadRiderTemplates(files) {
  const loader = new GLTFLoader();
  const base = new URL("./characters/", import.meta.url);
  const out = [];
  await Promise.all(
    files.map(async (file) => {
      try {
        const url = new URL(file, base).href;
        const gltf = await loader.loadAsync(url);
        gltf.scene.traverse((o) => {
          if (o.isMesh) {
            o.castShadow = true;
            o.receiveShadow = true;
          }
        });
        out.push({ name: file, scene: gltf.scene, clips: gltf.animations || [] });
      } catch (err) {
        console.warn(`[cityview] rider load failed: ${file}`, err);
      }
    })
  );
  return out;
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
    loadRiderTemplates(RIDING_FILES),
    loadRiderTemplates(SCOOTER_FILES),
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
   */
  function targetSpeed(v, obstacles) {
    let gap = Infinity;
    let oncoming = false;
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
    for (const o of vehicles) if (o !== v) consider(o.pos.x, o.pos.z, o.tan.x, o.tan.z, 0.5);
    for (const ob of obstacles) consider(ob.x, ob.z, 0, 0, ob.r ?? 0.4);
    // Held up for a while behind something that is not moving: pull out and pass on the left.
    v.stuck = gap < STOP_GAP + 1 && v.cur < 0.5 ? (v.stuck || 0) + dtSwerve : 0;
    if (v.stuck > 2.5) {
      v.overtake = 3.5; // s spent out in the passing line
      v.stuck = 0;
    }
    if (v.overtake > 0) v.overtake -= dtSwerve;
    const passing = v.overtake > 0 && !oncoming;
    const want = oncoming ? SWERVE : passing ? -OVERTAKE : 0;
    const k = Math.min(1, dtSwerve * 2.5);
    v.swerve += (want - v.swerve) * k;
    if (passing) return v.speed * 0.6;
    if (gap === Infinity) return v.speed;
    return v.speed * Math.max(0, Math.min(1, (gap - STOP_GAP) / (LOOK_AHEAD - STOP_GAP)));
  }
  let dtSwerve = 0;

  for (let i = 0; i < COUNT; i++) spawnOne();

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

  function update(dt, obstacles = []) {
    if (!(dt > 0)) return;
    dtSwerve = dt;
    for (const v of vehicles) {
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

      // Spin wheels
      v.wheelPhase += delta / 0.32;
      const wheels = v.mesh.userData.wheels || [];
      for (const w of wheels) w.rotation.x = v.wheelPhase;

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
  }

  return {
    update,
    dispose,
    vehicles,
    count: vehicles.length,
    mixamo: rideTemplates.length > 0 || scooterTemplates.length > 0,
  };
}
