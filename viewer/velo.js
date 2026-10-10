/**
 * Velo Antwerpen: take/return city bikes at GBFS stations (E).
 *
 * Dock rails + static bikes are baked into the district GLB. This module only
 * spawns the bike you ride, so stations are not doubled with runtime meshes.
 */

const VELO_URL = "./velo.json";
const BOARD_DIST = 4.0; // m to the rail (not only the centre point)
const CAPTION_DIST = 6.0; // slightly wider for GTA-style area captions
const BIKE_SPEED = 8.6; // ~31 km/h cruise (MOVE.velo.speed); the viewer owns acceleration
const FRAME_RED = 0xc41e3a;
const MUDGUARD = 0xf5f2ec;
const METAL = 0x3a3a3c;
const TIRE = 0x1c1c1c;
const RIM = 0xb8b8bc;
// Modelled at 1:1.55 like blender/velo_blender.py; this is a real-size Velo (wheel r ≈ 0.31 m).
const BIKE_SCALE = 1.55;

/** Shared so every ride / street-parked Velo brightens together at night. */
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

/**
 * Compact Velo step-through. Front wheel toward local −Z (matches Three.js look dir).
 * Origin on the ground under the bottom bracket.
 */
export function makeVeloBike(THREE) {
  const g = new THREE.Group();
  const frame = new THREE.MeshStandardMaterial({ color: FRAME_RED, roughness: 0.45, metalness: 0.15 });
  const white = new THREE.MeshStandardMaterial({ color: MUDGUARD, roughness: 0.55, metalness: 0.05 });
  const metal = new THREE.MeshStandardMaterial({ color: METAL, roughness: 0.35, metalness: 0.65 });
  const tire = new THREE.MeshStandardMaterial({ color: TIRE, roughness: 0.9, metalness: 0.05 });
  const rim = new THREE.MeshStandardMaterial({ color: RIM, roughness: 0.4, metalness: 0.5 });
  const { lamp, tail } = nightMats(THREE);

  function tube(len, rad, mat) {
    return new THREE.Mesh(new THREE.CylinderGeometry(rad, rad, len, 8), mat);
  }

  function wheel(radius) {
    const w = new THREE.Group();
    const t = new THREE.Mesh(new THREE.TorusGeometry(radius, 0.022, 8, 20), tire);
    t.rotation.y = Math.PI / 2;
    const hub = new THREE.Mesh(new THREE.CylinderGeometry(0.03, 0.03, 0.035, 8), rim);
    hub.rotation.z = Math.PI / 2;
    const disc = new THREE.Mesh(new THREE.CircleGeometry(radius * 0.85, 16), rim);
    disc.rotation.y = Math.PI / 2;
    disc.material = new THREE.MeshStandardMaterial({
      color: RIM,
      roughness: 0.5,
      metalness: 0.4,
      transparent: true,
      opacity: 0.35,
      side: THREE.DoubleSide,
    });
    w.add(t, hub, disc);
    return w;
  }

  const wr = 0.2;
  // Front toward −Z
  const front = wheel(wr);
  front.position.set(0, wr, -0.33);
  const rear = wheel(wr);
  rear.position.set(0, wr, 0.33);

  // Tube segment in the YZ plane (bike side view); cylinder default axis = Y.
  function frameSeg(z0, y0, z1, y1, rad = 0.017) {
    const dy = y1 - y0;
    const dz = z1 - z0;
    const len = Math.hypot(dy, dz) || 0.01;
    const m = tube(len, rad, frame);
    const dir = new THREE.Vector3(0, dy, dz).normalize();
    m.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), dir);
    m.position.set(0, (y0 + y1) * 0.5, (z0 + z1) * 0.5);
    return m;
  }

  // Open step-through (front −Z ← → rear +Z)
  g.add(frameSeg(-0.28, 0.14, -0.05, 0.22)); // front hub rise → BB
  g.add(frameSeg(-0.05, 0.22, 0.08, 0.26)); // BB → low step-through
  g.add(frameSeg(0.08, 0.26, 0.28, 0.4)); // rise to seat
  g.add(frameSeg(-0.05, 0.22, -0.28, 0.4)); // BB → head tube
  g.add(frameSeg(0.28, 0.4, 0.33, 0.2)); // seat stay → rear hub

  // Head tube / fork
  const head = tube(0.2, 0.016, metal);
  head.position.set(0, 0.48, -0.3);
  const forkL = tube(0.22, 0.01, metal);
  forkL.position.set(-0.03, 0.32, -0.32);
  forkL.rotation.z = 0.12;
  const forkR = tube(0.22, 0.01, metal);
  forkR.position.set(0.03, 0.32, -0.32);
  forkR.rotation.z = -0.12;

  // Seat post + saddle
  const seatPost = tube(0.22, 0.012, metal);
  seatPost.position.set(0, 0.52, 0.28);
  const saddle = new THREE.Mesh(new THREE.BoxGeometry(0.11, 0.035, 0.18), tire);
  saddle.position.set(0, 0.64, 0.28);
  saddle.rotation.x = -0.15;

  // Stem + flat bars
  const stem = tube(0.12, 0.012, metal);
  stem.position.set(0, 0.6, -0.3);
  const bars = tube(0.44, 0.011, metal);
  bars.rotation.z = Math.PI / 2;
  bars.position.set(0, 0.67, -0.3);
  const gripL = tube(0.07, 0.014, tire);
  gripL.rotation.z = Math.PI / 2;
  gripL.position.set(-0.2, 0.67, -0.3);
  const gripR = gripL.clone();
  gripR.position.x = 0.2;

  // Front rack (wire tray)
  const rack = new THREE.Mesh(new THREE.BoxGeometry(0.28, 0.015, 0.18), metal);
  rack.position.set(0, 0.48, -0.42);
  const rackLegL = tube(0.14, 0.008, metal);
  rackLegL.position.set(-0.1, 0.4, -0.42);
  const rackLegR = rackLegL.clone();
  rackLegR.position.x = 0.1;

  // White rear mudguard — thin curved plate, not a brick
  const mud = new THREE.Mesh(new THREE.BoxGeometry(0.08, 0.1, 0.22), white);
  mud.position.set(0, 0.3, 0.4);
  mud.rotation.x = -0.4;
  const badge = new THREE.Mesh(new THREE.BoxGeometry(0.05, 0.05, 0.04), frame);
  badge.position.set(0, 0.32, 0.5);

  // Crank
  const bb = new THREE.Mesh(new THREE.CylinderGeometry(0.03, 0.03, 0.05, 8), metal);
  bb.rotation.z = Math.PI / 2;
  bb.position.set(0, 0.2, 0.02);
  const arm = new THREE.Mesh(new THREE.BoxGeometry(0.02, 0.12, 0.02), metal);
  arm.position.set(0.04, 0.2, 0.02);

  // Headlamp on the rack / fork; red reflector under the mudguard.
  const headlamp = new THREE.Mesh(new THREE.SphereGeometry(0.028, 8, 6), lamp);
  headlamp.position.set(0, 0.5, -0.48);
  const taillight = new THREE.Mesh(new THREE.BoxGeometry(0.045, 0.028, 0.022), tail);
  taillight.position.set(0, 0.34, 0.52);

  g.add(
    front,
    rear,
    head,
    forkL,
    forkR,
    seatPost,
    saddle,
    stem,
    bars,
    gripL,
    gripR,
    rack,
    rackLegL,
    rackLegR,
    mud,
    badge,
    bb,
    arm,
    headlamp,
    taillight
  );
  g.userData.wheels = [front, rear];
  g.scale.setScalar(BIKE_SCALE);
  return g;
}

/** Closest point on the station rail segment (Blender local X after yaw → Three XZ). */
function distToRail(st, px, pz) {
  const half = (st.railLength || 8) * 0.5;
  const cos = Math.cos(st.yaw);
  const sin = Math.sin(st.yaw);
  // Rail endpoints in Three.js
  const ax = st.x + cos * -half;
  const az = st.z - sin * -half;
  const bx = st.x + cos * half;
  const bz = st.z - sin * half;
  const abx = bx - ax;
  const abz = bz - az;
  const len2 = abx * abx + abz * abz || 1e-6;
  let t = ((px - ax) * abx + (pz - az) * abz) / len2;
  t = Math.max(0, Math.min(1, t));
  const qx = ax + abx * t;
  const qz = az + abz * t;
  return Math.hypot(px - qx, pz - qz);
}

export async function createVelo(scene, THREE) {
  let doc = { stations: [] };
  try {
    const res = await fetch(VELO_URL);
    if (res.ok) doc = await res.json();
  } catch (e) {
    console.warn("[metropolis] velo: could not load", VELO_URL, e);
  }

  const stations = (doc.stations || []).map((raw) => ({
    id: String(raw.id),
    name: raw.name || raw.id,
    x: Number(raw.x),
    z: Number(raw.z),
    yaw: Number(raw.yaw) || 0,
    capacity: Math.max(1, Number(raw.capacity) || 20),
    bikesAvailable: Math.max(0, Number(raw.bikesAvailable) || 0),
    railLength: Number(raw.railLength) || 8,
    slotSpacing: Number(raw.slotSpacing) || 0.95,
  }));

  // Street-parked bikes after a mid-ride hop-off (remount with E).
  const parked = [];
  let ride = null;
  let toast = "";
  let toastT = 0;

  function nearestStation(px, pz, reach = BOARD_DIST) {
    let best = null;
    for (const st of stations) {
      const d = distToRail(st, px, pz);
      if (d <= reach && (best == null || d < best.d)) best = { st, d };
    }
    return best;
  }

  let captionId = null;
  /** Nearest dock for area captions; `{ station, changed }`. */
  function locateStation(px, pz) {
    const hit = nearestStation(px, pz, CAPTION_DIST);
    const st = hit?.st ?? null;
    const id = st ? st.id : null;
    const changed = id !== captionId;
    captionId = id;
    return { station: st, changed };
  }

  function nearestParked(px, pz, reach = 2.8) {
    let best = null;
    for (let i = 0; i < parked.length; i++) {
      const b = parked[i];
      const d = Math.hypot(b.mesh.position.x - px, b.mesh.position.z - pz);
      if (d <= reach && (best == null || d < best.d)) best = { bike: b, index: i, d };
    }
    return best;
  }

  function freeSlots(st) {
    return st.capacity - st.bikesAvailable;
  }

  function disposeMesh(mesh) {
    if (!mesh) return;
    mesh.traverse((o) => {
      if (o.geometry) o.geometry.dispose?.();
      if (o.material) {
        if (Array.isArray(o.material)) o.material.forEach((m) => m.dispose?.());
        else o.material.dispose?.();
      }
    });
  }

  function takeFromStation(st) {
    if (st.bikesAvailable <= 0) return false;
    st.bikesAvailable -= 1;
    const mesh = makeVeloBike(THREE);
    scene.add(mesh);
    ride = { stationId: st.id, mesh, name: st.name };
    return true;
  }

  function mountParked(entry, index) {
    parked.splice(index, 1);
    ride = { stationId: entry.stationId, mesh: entry.mesh, name: entry.name || "Velo" };
    return true;
  }

  function returnToStation(st) {
    if (!ride || freeSlots(st) <= 0) return false;
    st.bikesAvailable += 1;
    scene.remove(ride.mesh);
    disposeMesh(ride.mesh);
    ride = null;
    return true;
  }

  /** Hop off anywhere: leave the bike on the pavement (remountable). */
  function dismount(player) {
    if (!ride) return false;
    const yaw = player.yaw != null ? player.yaw : 0;
    // Step the bike a little to the rider's right so you don't stand inside it.
    const side = 0.85;
    ride.mesh.position.set(
      player.x + Math.cos(yaw) * side,
      0,
      player.z - Math.sin(yaw) * side
    );
    ride.mesh.rotation.y = yaw;
    parked.push({
      mesh: ride.mesh,
      stationId: ride.stationId,
      name: ride.name,
    });
    ride = null;
    return true;
  }

  function isRiding() {
    return !!ride;
  }

  function bikeSpeed() {
    return BIKE_SPEED;
  }

  function tryInteract(player) {
    const near = nearestStation(player.x, player.z);
    if (ride) {
      // Prefer docking when at a station with a free slot.
      if (near && freeSlots(near.st) > 0 && returnToStation(near.st)) {
        return {
          action: "return",
          name: near.st.name,
          bikes: near.st.bikesAvailable,
          capacity: near.st.capacity,
        };
      }
      // Otherwise always allow a sidewalk hop-off.
      if (dismount(player)) {
        return { action: "dismount" };
      }
      return { action: "none" };
    }

    // Remount a street-parked bike first if close.
    const pk = nearestParked(player.x, player.z);
    if (pk && mountParked(pk.bike, pk.index)) {
      return { action: "take", name: pk.bike.name || "Velo", bikes: "—", capacity: "—" };
    }

    if (!near) return { action: "none" };
    if (near.st.bikesAvailable <= 0) {
      toast = "No bikes left here";
      toastT = 2.2;
      return { action: "empty" };
    }
    if (takeFromStation(near.st)) {
      return {
        action: "take",
        name: near.st.name,
        bikes: near.st.bikesAvailable,
        capacity: near.st.capacity,
      };
    }
    return { action: "none" };
  }

  function getRideHud() {
    if (ride) {
      return { riding: true, name: ride.name, toast: toastT > 0 ? toast : "" };
    }
    return { riding: false, toast: toastT > 0 ? toast : "" };
  }

  function getPrompt(player) {
    if (ride) {
      const near = nearestStation(player.x, player.z);
      if (near && freeSlots(near.st) > 0) {
        return `Press E to return Velo · ${near.st.name}`;
      }
      if (near && freeSlots(near.st) <= 0) {
        return `Station full · Press E to hop off`;
      }
      return "Press E to hop off";
    }
    const pk = nearestParked(player.x, player.z);
    if (pk) return "Press E to take parked Velo";
    const near = nearestStation(player.x, player.z);
    if (!near) return null;
    if (near.st.bikesAvailable <= 0) return `No bikes · ${near.st.name}`;
    return `Press E to take a Velo · ${near.st.name} (${near.st.bikesAvailable} left)`;
  }

  function update(dt, player) {
    if (toastT > 0) toastT -= dt;
    if (!ride || !player) return;
    const mesh = ride.mesh;
    const yaw = player.yaw != null ? player.yaw : 0;
    // Sit the bike under the camera; slight forward bias so the rack is in view.
    const fwd = 0.15;
    mesh.position.set(
      player.x - Math.sin(yaw) * fwd,
      0,
      player.z - Math.cos(yaw) * fwd
    );
    mesh.rotation.y = yaw;
    if (player.moving && mesh.userData.wheels) {
      const spin = (player.speed ?? BIKE_SPEED) / (0.2 * BIKE_SCALE);
      for (const w of mesh.userData.wheels) w.rotation.x -= dt * spin;
    }
  }

  function dispose() {
    if (ride?.mesh) {
      scene.remove(ride.mesh);
      disposeMesh(ride.mesh);
    }
    for (const b of parked) {
      scene.remove(b.mesh);
      disposeMesh(b.mesh);
    }
    parked.length = 0;
    ride = null;
  }

  console.info(
    `[metropolis] velo: ${stations.length} stations,` +
      ` ${stations.reduce((n, s) => n + s.bikesAvailable, 0)} bikes available`
  );

  // Rails with their docked bikes as solid boxes, same shape as the vehicle solids.
  const solids = stations.map((st) => ({
    pos: { x: st.x, z: st.z },
    tan: { x: Math.cos(st.yaw), z: -Math.sin(st.yaw) },
    hl: (st.railLength || 8) * 0.5 + 0.3,
    hw: 1.0,
  }));

  function setNight(glow) {
    if (!_lampMat || !_tailMat) return;
    _lampMat.emissiveIntensity = 0.3 + 1.6 * glow;
    _tailMat.emissiveIntensity = 0.3 + 1.2 * glow;
  }

  return {
    stations,
    solids,
    isRiding,
    bikeSpeed,
    tryInteract,
    getRideHud,
    getPrompt,
    locateStation,
    update,
    setNight,
    dispose,
    count: stations.length,
  };
}
