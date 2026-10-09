/**
 * Shared e-scooters you can ride: parked at random on the pavement just behind the kerb
 * (how dockless fleets end up in Antwerp), press E next to one to unlock it and E again to
 * park it on its kickstand wherever you are. Battery drains while you ride; the meter runs.
 *
 * Positions come from roads.json (Blender XY → Three XZ with z = −y), offset off the
 * carriageway onto the footway, kept clear of junction mouths and of each other.
 */

import { mergeGeometries } from "three/addons/utils/BufferGeometryUtils.js";

const REACH = 2.2; // m from the deck to unlock
const DRAW_DIST = 140; // m: parked scooters further away than this are hidden
const COUNT = 26;
const NEAR_SPAWN = 4; // guaranteed within ~60 m of the spawn so the first one is easy to find
const MIN_GAP = 4.5; // m between parked scooters (pairs are placed deliberately)
const END_CLEAR = 9; // m from road ends: no scooters in junction mouths
const KERB_BACK = 0.85; // m behind the kerb line, on the footway
const PRICE_UNLOCK = 1.0;
const PRICE_MIN = 0.25;
const SKID_DECEL = 6; // m/s² of a scooter sliding on its side
const FALLEN_LEAN = 1.45; // rad: lying on its side, propped up a little by the bar end

const FLEETS = [
  { name: "Dott", body: 0x18a6e0, trim: 0xf4f6f8, deck: 0x22262b },
  { name: "Bolt", body: 0x34d186, trim: 0x1b1f22, deck: 0x1b1f22 },
];

function mulberry(seed) {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

const _matCache = new Map();
function fleetMaterials(THREE, fleet) {
  let m = _matCache.get(fleet.name);
  if (m) return m;
  const shared = _matCache.get("_shared") || {
    metal: new THREE.MeshStandardMaterial({ color: 0x2b2e33, roughness: 0.4, metalness: 0.7 }),
    tire: new THREE.MeshStandardMaterial({ color: 0x141414, roughness: 0.92 }),
    lamp: new THREE.MeshStandardMaterial({ color: 0xfff6dd, emissive: 0xfff2cc, emissiveIntensity: 0.6 }),
    tail: new THREE.MeshStandardMaterial({ color: 0xa01010, emissive: 0xff2020, emissiveIntensity: 0.5 }),
    screen: new THREE.MeshStandardMaterial({ color: 0x0b1a22, emissive: 0x3ad0ff, emissiveIntensity: 0.35 }),
  };
  _matCache.set("_shared", shared);
  m = {
    ...shared,
    body: new THREE.MeshStandardMaterial({ color: fleet.body, roughness: 0.38, metalness: 0.25 }),
    trim: new THREE.MeshStandardMaterial({ color: fleet.trim, roughness: 0.5, metalness: 0.1 }),
    deck: new THREE.MeshStandardMaterial({ color: fleet.deck, roughness: 0.85, metalness: 0.05 }),
  };
  _matCache.set(fleet.name, m);
  return m;
}

/** Bake every static part into one mesh per material (wheels stay separate so they can spin). */
function mergeByMaterial(THREE, group, keep) {
  const byMat = new Map();
  group.updateMatrixWorld(true);
  for (const child of [...group.children]) {
    if (keep.includes(child) || !child.isMesh) continue;
    const geo = child.geometry.clone().applyMatrix4(child.matrix);
    if (!byMat.has(child.material)) byMat.set(child.material, []);
    byMat.get(child.material).push(geo);
    child.geometry.dispose();
    group.remove(child);
  }
  for (const [mat, geos] of byMat) {
    const merged = mergeGeometries(geos, false);
    geos.forEach((g) => g.dispose());
    if (merged) group.add(new THREE.Mesh(merged, mat));
  }
}

/** Shared e-scooter, front wheel toward local −Z, origin on the ground under the deck. */
export function makeShareScooter(THREE, fleet) {
  const g = new THREE.Group();
  const M = fleetMaterials(THREE, fleet);
  const { body, trim, metal, tire, lamp, tail, screen } = M;
  const deckMat = M.deck;

  const wheel = (r, z) => {
    const w = new THREE.Group();
    const t = new THREE.Mesh(new THREE.TorusGeometry(r, 0.035, 8, 22), tire);
    t.rotation.y = Math.PI / 2;
    const hub = new THREE.Mesh(new THREE.CylinderGeometry(r * 0.62, r * 0.62, 0.05, 14), metal);
    hub.rotation.z = Math.PI / 2;
    w.add(t, hub);
    w.position.set(0, r + 0.035, z);
    return w;
  };
  const front = wheel(0.115, -0.42);
  const rear = wheel(0.115, 0.4);

  // Deck: a rounded-ish slab with a coloured skirt and grip top.
  const deck = new THREE.Mesh(new THREE.BoxGeometry(0.17, 0.06, 0.66), body);
  deck.position.set(0, 0.13, 0);
  const grip = new THREE.Mesh(new THREE.BoxGeometry(0.15, 0.012, 0.58), deckMat);
  grip.position.set(0, 0.166, 0.01);
  const battery = new THREE.Mesh(new THREE.BoxGeometry(0.13, 0.05, 0.5), metal);
  battery.position.set(0, 0.085, 0);
  const fender = new THREE.Mesh(new THREE.BoxGeometry(0.1, 0.02, 0.26), body);
  fender.position.set(0, 0.27, 0.44);
  fender.rotation.x = 0.25;
  const tailLight = new THREE.Mesh(new THREE.BoxGeometry(0.06, 0.03, 0.02), tail);
  tailLight.position.set(0, 0.25, 0.57);

  // Stem: fork up to the bars, raked back a little like the real thing.
  const stemLen = 0.98;
  const stem = new THREE.Mesh(new THREE.CylinderGeometry(0.028, 0.034, stemLen, 12), body);
  const rake = 0.16;
  stem.rotation.x = rake;
  stem.position.set(0, 0.2 + (stemLen / 2) * Math.cos(rake), -0.42 + (stemLen / 2) * Math.sin(rake));
  const stemTop = new THREE.Vector3(0, 0.2 + stemLen * Math.cos(rake), -0.42 + stemLen * Math.sin(rake));
  const neck = new THREE.Mesh(new THREE.BoxGeometry(0.11, 0.22, 0.06), body);
  neck.position.set(0, 0.32, -0.4);
  const headlight = new THREE.Mesh(new THREE.CylinderGeometry(0.03, 0.03, 0.02, 12), lamp);
  headlight.rotation.x = Math.PI / 2;
  headlight.position.set(0, 0.44, -0.44);
  const brand = new THREE.Mesh(new THREE.BoxGeometry(0.075, 0.3, 0.012), trim);
  brand.position.set(0, 0.62, -0.42 + 0.42 * Math.tan(rake) + 0.034); // rider side of the stem
  brand.rotation.x = rake;

  const bars = new THREE.Mesh(new THREE.CylinderGeometry(0.014, 0.014, 0.5, 8), metal);
  bars.rotation.z = Math.PI / 2;
  bars.position.copy(stemTop);
  const gripL = new THREE.Mesh(new THREE.CylinderGeometry(0.019, 0.019, 0.1, 8), tire);
  gripL.rotation.z = Math.PI / 2;
  gripL.position.set(-0.22, stemTop.y, stemTop.z);
  const gripR = gripL.clone();
  gripR.position.x = 0.22;
  const display = new THREE.Mesh(new THREE.BoxGeometry(0.1, 0.02, 0.07), screen);
  display.position.set(0, stemTop.y + 0.02, stemTop.z + 0.03);
  display.rotation.x = 0.5;
  const basket = new THREE.Mesh(new THREE.BoxGeometry(0.16, 0.05, 0.05), body);
  basket.position.set(0, stemTop.y - 0.06, stemTop.z - 0.04);

  const kickstand = new THREE.Mesh(new THREE.BoxGeometry(0.015, 0.015, 0.2), metal);
  kickstand.position.set(-0.1, 0.06, 0.08);
  kickstand.rotation.y = 0.5;

  g.add(front, rear, deck, grip, battery, fender, tailLight, stem, neck, headlight, brand);
  g.add(bars, gripL, gripR, display, basket, kickstand);
  mergeByMaterial(THREE, g, [front, rear, kickstand]);
  g.userData = { wheels: [front, rear], kickstand, lamps: [lamp, tail, screen] };
  return g;
}

function buildKerbSpots(roads, rand) {
  const spots = [];
  for (const road of roads) {
    const kind = String(road.kind || "");
    if (!/primary|secondary|tertiary|residential|living_street|unclassified/.test(kind)) continue;
    if (road.tramShared) continue; // tram streets: kerb is the platform edge
    const pts = (road.points || []).map((p) => ({ x: p[0], z: -p[1] }));
    let total = 0;
    const cum = [0];
    for (let i = 1; i < pts.length; i++) cum.push((total += Math.hypot(pts[i].x - pts[i - 1].x, pts[i].z - pts[i - 1].z)));
    if (total < END_CLEAR * 2 + 4) continue;
    const half = (Number(road.width) || 7) * 0.5;
    for (let s = END_CLEAR + rand() * 10; s < total - END_CLEAR; s += 11 + rand() * 14) {
      let i = 1;
      while (i < cum.length - 1 && cum[i] < s) i++;
      const a = pts[i - 1];
      const b = pts[i];
      const segLen = Math.max(1e-6, cum[i] - cum[i - 1]);
      const t = (s - cum[i - 1]) / segLen;
      const tx = (b.x - a.x) / segLen;
      const tz = (b.z - a.z) / segLen;
      const side = rand() < 0.5 ? 1 : -1;
      const off = half + KERB_BACK + rand() * 0.5;
      spots.push({
        x: a.x + (b.x - a.x) * t - tz * off * side,
        z: a.z + (b.z - a.z) * t + tx * off * side,
        // Parked at an angle to the kerb, mostly tidy, sometimes not.
        yaw: Math.atan2(-tx, -tz) + (rand() < 0.7 ? Math.PI / 2 : rand() * Math.PI * 2) * side,
      });
    }
  }
  return spots;
}

export async function createScooters(scene, THREE, opts = {}) {
  let roads = [];
  try {
    const res = await fetch("./roads.json");
    if (res.ok) roads = (await res.json()).roads || [];
  } catch (err) {
    console.warn("[cityview] scooters: roads.json failed", err);
  }
  const rand = mulberry(opts.seed ?? 20180601);
  const spawn = opts.spawnCenter || { x: 0, z: 0 };
  const isFree = opts.isFree || (() => true);
  const groundAt = opts.groundAt || (() => 0);
  const candidates = buildKerbSpots(roads, rand).filter((p) => isFree(p.x, p.z));
  // Shuffle, but pull a handful of spots near the spawn to the front.
  for (let i = candidates.length - 1; i > 0; i--) {
    const j = (rand() * (i + 1)) | 0;
    [candidates[i], candidates[j]] = [candidates[j], candidates[i]];
  }
  const near = candidates.filter((p) => Math.hypot(p.x - spawn.x, p.z - spawn.z) < 60).slice(0, NEAR_SPAWN);
  const ordered = [...near, ...candidates.filter((p) => !near.includes(p))];

  const root = new THREE.Group();
  root.name = "ShareScooters";
  scene.add(root);
  const fleet = [];
  const place = (p, fleetCfg) => {
    const mesh = makeShareScooter(THREE, fleetCfg);
    mesh.position.set(p.x, groundAt(p.x, p.z), p.z);
    mesh.rotation.set(0, p.yaw, 0.11); // leaning on the kickstand
    root.add(mesh);
    fleet.push({ mesh, brand: fleetCfg.name, battery: 35 + Math.round(rand() * 60), parked: true });
  };
  for (const p of ordered) {
    if (fleet.length >= COUNT) break;
    if (fleet.some((f) => Math.hypot(f.mesh.position.x - p.x, f.mesh.position.z - p.z) < MIN_GAP)) continue;
    const fl = FLEETS[(rand() * FLEETS.length) | 0];
    place(p, fl);
    if (rand() < 0.3 && fleet.length < COUNT) {
      // Dockless scooters travel in pairs: a second one dropped right beside the first.
      const q = { x: p.x + Math.cos(p.yaw) * 0.7, z: p.z - Math.sin(p.yaw) * 0.7, yaw: p.yaw + (rand() - 0.5) * 0.4 };
      if (isFree(q.x, q.z)) place(q, fl);
    }
  }

  let ride = null; // { s: fleet entry, t: seconds, cost }
  let toast = "";
  let toastT = 0;

  function nearest(px, pz) {
    let best = null;
    for (const s of fleet) {
      if (!s.parked) continue;
      const d = Math.hypot(s.mesh.position.x - px, s.mesh.position.z - pz);
      if (d <= REACH && (!best || d < best.d)) best = { s, d };
    }
    return best;
  }

  function tryInteract(player) {
    if (ride) {
      const s = ride.s;
      const yaw = player.yaw ?? 0;
      // Park it on the rider's right so you step off beside it, not inside it.
      const px = player.x + Math.cos(yaw) * 0.6;
      const pz = player.z - Math.sin(yaw) * 0.6;
      s.mesh.position.set(px, groundAt(px, pz), pz);
      s.mesh.rotation.set(0, yaw, 0.11);
      s.mesh.userData.kickstand.visible = true;
      s.parked = true;
      const cost = ride.cost;
      ride = null;
      toast = `Parked ${s.brand} · ride €${cost.toFixed(2)}`;
      toastT = 3;
      return { action: "park", brand: s.brand, cost };
    }
    const n = nearest(player.x, player.z);
    if (!n) return { action: "none" };
    if (n.s.battery < 8) {
      toast = `${n.s.brand} battery empty`;
      toastT = 2.5;
      return { action: "empty" };
    }
    n.s.parked = false;
    n.s.fall = null; // picked back up off the ground
    n.s.mesh.userData.kickstand.visible = false;
    n.s.mesh.rotation.z = 0;
    ride = { s: n.s, t: 0, cost: PRICE_UNLOCK };
    return { action: "take", brand: n.s.brand, battery: n.s.battery };
  }

  /** Rider thrown off: the ride ends where it is and the scooter skids away on its side. */
  function crash(player) {
    if (!ride) return null;
    const s = ride.s;
    const yaw = player.yaw ?? 0;
    const speed = Math.max(0, player.speed || 0);
    const side = Math.random() < 0.5 ? 1 : -1;
    s.parked = true;
    s.mesh.userData.kickstand.visible = false;
    s.fall = {
      t: 0,
      side,
      lean: s.mesh.rotation.z,
      vx: -Math.sin(yaw) * speed * 0.5,
      vz: -Math.cos(yaw) * speed * 0.5,
      spin: (Math.random() - 0.5) * speed * 0.5,
    };
    const cost = ride.cost;
    ride = null;
    return { brand: s.brand, cost };
  }

  function updateFalls(dt) {
    for (const s of fleet) {
      const f = s.fall;
      if (!f) continue;
      f.t += dt;
      const hs = Math.hypot(f.vx, f.vz);
      if (hs > 0.02) {
        const slow = Math.max(0, hs - SKID_DECEL * dt) / hs;
        f.vx *= slow;
        f.vz *= slow;
        s.mesh.position.x += f.vx * dt;
        s.mesh.position.z += f.vz * dt;
        s.mesh.rotation.y += f.spin * dt * slow;
      }
      // Tips over in ~0.35 s and comes to rest on the bar end and deck edge.
      const k = Math.min(1, f.t / 0.35);
      s.mesh.rotation.z = f.lean + (f.side * FALLEN_LEAN - f.lean) * k * k;
      s.mesh.position.y = groundAt(s.mesh.position.x, s.mesh.position.z) + 0.06 * k;
      if (k >= 1 && hs <= 0.02) s.fall = null;
    }
  }

  function getPrompt(player) {
    if (ride) return "E · park scooter here";
    const n = nearest(player.x, player.z);
    if (!n) return null;
    if (n.s.battery < 8) return `${n.s.brand} · battery empty`;
    return `E · ride ${n.s.brand} scooter · ${n.s.battery}% · €${PRICE_UNLOCK.toFixed(2)} + €${PRICE_MIN.toFixed(2)}/min`;
  }

  let cullClock = 0;
  let groundClock = 0;
  let groundY = 0;
  function update(dt, player) {
    if (toastT > 0) toastT -= dt;
    updateFalls(dt);
    if (!player) return;
    if ((cullClock -= dt) <= 0) {
      cullClock = 0.5;
      for (const s of fleet) {
        const d = Math.hypot(s.mesh.position.x - player.x, s.mesh.position.z - player.z);
        s.mesh.visible = !s.parked || d < DRAW_DIST;
      }
    }
    if (!ride) return;
    const s = ride.s;
    const yaw = player.yaw ?? 0;
    // Deck under the rider's feet, bars just ahead of the camera.
    const rx = player.x - Math.sin(yaw) * 0.18;
    const rz = player.z - Math.cos(yaw) * 0.18;
    if ((groundClock -= dt) <= 0) {
      groundClock = 0.12;
      groundY = groundAt(rx, rz);
    }
    s.mesh.position.set(rx, s.mesh.position.y + (groundY - s.mesh.position.y) * Math.min(1, dt * 12), rz);
    s.mesh.rotation.set(0, yaw, -(player.turn || 0) * 0.12);
    const speed = player.speed || 0;
    for (const w of s.mesh.userData.wheels) w.rotation.x -= (speed / 0.15) * dt;
    ride.t += dt;
    ride.cost = PRICE_UNLOCK + Math.ceil(ride.t / 60) * PRICE_MIN;
    if (Math.abs(speed) > 0.5) s.battery = Math.max(5, s.battery - dt * 0.05);
  }

  function getRideHud() {
    if (!ride) return { riding: false, toast: toastT > 0 ? toast : "" };
    const mm = Math.floor(ride.t / 60);
    const ss = String(Math.floor(ride.t % 60)).padStart(2, "0");
    return {
      riding: true,
      brand: ride.s.brand,
      battery: Math.round(ride.s.battery),
      time: `${mm}:${ss}`,
      cost: ride.cost,
      toast: toastT > 0 ? toast : "",
    };
  }

  /** Parked scooters are solid for the walker (centre + radius, XZ). */
  function solids() {
    return fleet.filter((s) => s.parked).map((s) => ({ x: s.mesh.position.x, z: s.mesh.position.z, r: 0.45 }));
  }

  function setNight(glow) {
    const m = _matCache.get("_shared");
    if (!m) return;
    m.lamp.emissiveIntensity = 0.3 + 1.6 * glow;
    m.tail.emissiveIntensity = 0.3 + 1.2 * glow;
    m.screen.emissiveIntensity = 0.35 + 0.6 * glow;
  }

  console.info(`[cityview] scooters: ${fleet.length} shared e-scooters parked (${near.length} near spawn)`);

  return {
    fleet,
    count: fleet.length,
    isRiding: () => !!ride,
    tryInteract,
    crash,
    getPrompt,
    update,
    getRideHud,
    solids,
    setNight,
    dispose() {
      scene.remove(root);
      fleet.length = 0;
      ride = null;
    },
  };
}
