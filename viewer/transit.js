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
const BOARD_DIST = 12; // articulated tram: boarding from middle reference toward end doors
const STOP_PROJECT_M = 28;
// tram length is overwritten once TRAM_LEN is known below; bus stays a single rigid body.
const BODY_LEN = { tram: 25.0, bus: 13.5 };
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

// ---------------------------------------------------------------------------
// De Lijn liveries.  White body, grey skirt, dark glazing band, yellow (#FFD800)
// door / front stripes and the "lijn" mark — see De Lijn huisstijlgids 2022 and
// the Antwerp photos listed in README "Livery".  Bus side / front / rear wraps are
// flat elevation textures in ./livery (built by scripts/make_delijn_livery.py).
// Tram wagons use canvas-painted single-door sides (the full elevations show too
// many doors for a car-length car) plus the photo front on the lead/tail noses.
// Live LED destination displays, headlight glow, pantograph and mirrors are
// real geometry on top.
// ---------------------------------------------------------------------------
const LIVERY_VERSION = "2"; // bump when viewer/livery/*.jpg change (Pages caches aggressively)
// Articulated De Lijn tram: 5 wagons coupled by bellows. Lead/tail cab cars are
// a bit longer than the mid sections (Albatros-style).
const TRAM_WAGONS = 5;
const TRAM_WAGON = { w: 2.2, h: 2.85, l: 4.6, lift: 0.28 }; // mid wagon ≈ car length
const TRAM_WAGON_END_L = 5.55; // cab cars (first + last)
const TRAM_WAGON_LENS = Array.from({ length: TRAM_WAGONS }, (_, i) =>
  i === 0 || i === TRAM_WAGONS - 1 ? TRAM_WAGON_END_L : TRAM_WAGON.l,
);
const TRAM_JOINT_GAP = 0.5; // clear gap between wagon bodies (bellows sit here)
/** Centre-to-centre distance from lead wagon to wagon `i` on a straight. */
function tramWagonOffset(i) {
  let s = 0;
  for (let k = 0; k < i; k++) {
    s += TRAM_WAGON_LENS[k] * 0.5 + TRAM_JOINT_GAP + TRAM_WAGON_LENS[k + 1] * 0.5;
  }
  return s;
}
const TRAM_TRAIL_SPAN = tramWagonOffset(TRAM_WAGONS - 1); // lead→tail centre distance
const TRAM_LEN =
  TRAM_WAGON_LENS.reduce((a, b) => a + b, 0) + (TRAM_WAGONS - 1) * TRAM_JOINT_GAP;
BODY_LEN.tram = TRAM_LEN;
const TRAM_DIM = { w: TRAM_WAGON.w, h: TRAM_WAGON.h, l: TRAM_LEN, lift: TRAM_WAGON.lift };
const BUS_DIM = { w: 2.4, h: 2.7, l: 13.5, lift: 0.05 };
// Scratch vectors for articulated tram placement (no per-frame alloc).
const _tramPos = [];
const _tramTan = [];
for (let _i = 0; _i < TRAM_WAGONS; _i++) {
  _tramPos.push({ x: 0, y: 0, z: 0 });
  _tramTan.push({ x: 0, z: 0 });
}
const _jointA = { x: 0, y: 0, z: 0 };
const _jointB = { x: 0, y: 0, z: 0 };
// Destination LED boxes as fractions of the end-face texture: [u0, v0, u1, v1] (v from top).
const LED_BOX = {
  tramFront: [0.187, 0.133, 0.813, 0.22],
  busFront: [0.127, 0.149, 0.873, 0.241],
  busRear: [0.713, 0.136, 0.9, 0.228],
};
const LED_COLOR = "#ffb11a";
const LED_BG = "#14110c";

// Line-number badge colours from the De Lijn palette (digits white, except on yellow/lime).
const LINE_BADGES = [
  ["#e40521", "#ffffff"],
  ["#ef7d00", "#ffffff"],
  ["#ffd800", "#000000"],
  ["#c8d300", "#000000"],
  ["#15882e", "#ffffff"],
  ["#009fe3", "#ffffff"],
  ["#0069b4", "#ffffff"],
  ["#8e2b8b", "#ffffff"],
];

function badgeFor(text) {
  const m = /\d+/.exec(text);
  let n = m ? parseInt(m[0], 10) : 0;
  if (!m) for (let i = 0; i < text.length; i++) n += text.charCodeAt(i);
  return LINE_BADGES[n % LINE_BADGES.length];
}

function makeLineSprite(THREE, text, mode) {
  const canvas = document.createElement("canvas");
  canvas.width = 128;
  canvas.height = 64;
  const ctx = canvas.getContext("2d");
  const [bg, fg] = badgeFor(text);
  const x = 8;
  const y = 10;
  const w = 112;
  const h = 44;
  const r = 12;
  ctx.fillStyle = "#101214";
  ctx.beginPath();
  ctx.roundRect(x - 2, y - 2, w + 4, h + 4, r + 2);
  ctx.fill();
  ctx.fillStyle = bg;
  ctx.beginPath();
  ctx.roundRect(x, y, w, h, r);
  ctx.fill();
  ctx.fillStyle = fg;
  ctx.font = "bold 28px system-ui, sans-serif";
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  ctx.fillText(text.slice(0, 8), 64, 33);
  const tex = new THREE.CanvasTexture(canvas);
  tex.colorSpace = THREE.SRGBColorSpace;
  tex.needsUpdate = true;
  const mat = new THREE.SpriteMaterial({ map: tex, transparent: true, depthTest: true });
  const sprite = new THREE.Sprite(mat);
  sprite.scale.set(2.4, 1.2, 1);
  sprite.position.y = (mode === "bus" ? BUS_DIM.h : TRAM_DIM.h) + 0.9;
  return { sprite, tex, mat };
}

/** De Lijn LED / HUD copy: drop the GTFS municipality prefix ("Antwerpen Gounod" → "Gounod"). */
function haltDisplayName(raw) {
  let s = String(raw || "").trim();
  if (!s) return "Halt";
  s = s.replace(/^Antwerpen\s+/i, "");
  s = s.replace(/\s+tram\s*halt$/i, "");
  s = s.replace(/\s+tram$/i, "");
  return s || String(raw).trim();
}

/** Final non-synthetic halt in the direction of travel ("7 Gounod" style destination). */
function destinationFor(path, reverse) {
  const halts = (path.halts || []).filter((h) => !String(h.id).startsWith("synth_") && h.name);
  if (!halts.length) return "";
  return haltDisplayName(halts[reverse ? 0 : halts.length - 1].name);
}

/** (Re)draw the amber LED destination displays of one vehicle. */
function drawDisplays(displays, line, dest) {
  for (const d of displays) {
    const { ctx, canvas } = d;
    const W = canvas.width;
    const H = canvas.height;
    ctx.fillStyle = LED_BG;
    ctx.fillRect(0, 0, W, H);
    ctx.fillStyle = LED_COLOR;
    ctx.textBaseline = "middle";
    const mono = "'Courier New', ui-monospace, monospace";
    if (d.kind === "rear") {
      ctx.textAlign = "center";
      ctx.font = `bold ${Math.round(H * 0.74)}px ${mono}`;
      ctx.fillText(line.slice(0, 4), W / 2, H / 2 + 1, W - 8);
    } else {
      ctx.textAlign = "left";
      ctx.font = `bold ${Math.round(H * 0.72)}px ${mono}`;
      const num = line.slice(0, 4);
      ctx.fillText(num, 8, H / 2 + 1);
      const nx = 14 + ctx.measureText(num).width;
      ctx.font = `bold ${Math.round(H * 0.62)}px ${mono}`;
      ctx.fillText(dest || "De Lijn", nx, H / 2 + 1, W - nx - 6);
    }
    d.tex.needsUpdate = true;
  }
}

function addDisplay(THREE, parts, group, dim, kind, box, front) {
  const [u0, v0, u1, v1] = box;
  const canvas = document.createElement("canvas");
  canvas.width = kind === "rear" ? 96 : 256;
  canvas.height = kind === "rear" ? 52 : 40;
  const ctx = canvas.getContext("2d");
  const tex = new THREE.CanvasTexture(canvas);
  tex.colorSpace = THREE.SRGBColorSpace;
  tex.anisotropy = 4;
  const mat = new THREE.MeshBasicMaterial({ map: tex });
  const geo = new THREE.PlaneGeometry((u1 - u0) * dim.w, (v1 - v0) * dim.h);
  parts.ledGeos.push(geo);
  const mesh = new THREE.Mesh(geo, mat);
  const uc = (u0 + u1) / 2;
  const vc = (v0 + v1) / 2;
  const yMid = dim.lift;
  mesh.position.set(
    (front ? 1 : -1) * (uc - 0.5) * dim.w,
    yMid + (0.5 - vc) * dim.h,
    (front ? 1 : -1) * (dim.l / 2 + 0.02),
  );
  if (!front) mesh.rotation.y = Math.PI;
  group.add(mesh);
  return { kind, canvas, ctx, tex, mat, mesh };
}

/** Glow discs (headlights white, tail lights red); invisible by day, additive at night. */
function addLamps(THREE, parts, group, dim, front, vFrac, uL, uR) {
  const sgn = front ? 1 : -1;
  for (const u of [uL, uR]) {
    const lamp = new THREE.Mesh(parts.lampGeo, front ? parts.headGlowMat : parts.tailGlowMat);
    lamp.position.set(sgn * (u - 0.5) * dim.w, dim.lift + (0.5 - vFrac) * dim.h, sgn * (dim.l / 2 + 0.03));
    if (!front) lamp.rotation.y = Math.PI;
    group.add(lamp);
  }
}

/**
 * Soften the sharp corners of a subdivided BoxGeometry by projecting vertices
 * onto a rounded-box shell. Keeps material groups (needed for per-face liveries).
 * No-ops under the headless THREE shim (no position attribute).
 */
function roundBoxCorners(geo, radius) {
  const pos = geo.attributes && geo.attributes.position;
  if (!pos || typeof pos.getX !== "function") return geo;
  const w = (geo.parameters?.width ?? 1) / 2;
  const h = (geo.parameters?.height ?? 1) / 2;
  const d = (geo.parameters?.depth ?? 1) / 2;
  const r = Math.min(radius, w - 0.02, h - 0.02, d - 0.02);
  if (!(r > 0)) return geo;
  const ix = w - r;
  const iy = h - r;
  const iz = d - r;
  for (let i = 0; i < pos.count; i++) {
    const x = pos.getX(i);
    const y = pos.getY(i);
    const z = pos.getZ(i);
    const ox = Math.max(-ix, Math.min(ix, x));
    const oy = Math.max(-iy, Math.min(iy, y));
    const oz = Math.max(-iz, Math.min(iz, z));
    const dx = x - ox;
    const dy = y - oy;
    const dz = z - oz;
    const len = Math.hypot(dx, dy, dz);
    if (len > 1e-8) {
      const s = r / len;
      pos.setXYZ(i, ox + dx * s, oy + dy * s, oz + dz * s);
    }
  }
  pos.needsUpdate = true;
  if (typeof geo.computeVertexNormals === "function") geo.computeVertexNormals();
  return geo;
}

function makeRoundedBox(THREE, width, height, depth, radius, segments = 3) {
  const seg = Math.max(1, segments) * 2 + 1;
  const geo = new THREE.BoxGeometry(width, height, depth, seg, seg, seg);
  return roundBoxCorners(geo, radius);
}

/**
 * Pull the cab face into a more slanted windshield: top of the nose/tail moves
 * inward along travel (+z front / -z rear), with a mild side taper.
 * `face` is "front" (+z) or "rear" (-z). Mutates `geo` in place.
 */
function slantCabFace(geo, face, depth = 0.62) {
  const pos = geo.attributes && geo.attributes.position;
  if (!pos || typeof pos.getX !== "function") return geo;
  const w = (geo.parameters?.width ?? 1) / 2;
  const h = (geo.parameters?.height ?? 1) / 2;
  const d = (geo.parameters?.depth ?? 1) / 2;
  const sign = face === "front" ? 1 : -1;
  const zoneStart = d * 0.28; // only the outer ~72% of half-length is affected
  for (let i = 0; i < pos.count; i++) {
    const x = pos.getX(i);
    const y = pos.getY(i);
    const z = pos.getZ(i);
    const along = sign * z;
    if (along < zoneStart) continue;
    const t = Math.min(1, (along - zoneStart) / Math.max(1e-6, d - zoneStart));
    const yh = Math.max(0, Math.min(1, (y + h) / (2 * h))); // 0 floor → 1 roof
    // Stronger at the roof (windshield rake); mild tuck at the skirt.
    const pull = depth * t * t * (0.18 + 0.82 * yh * yh);
    const taper = 1 - 0.16 * t * yh;
    pos.setXYZ(i, x * taper, y, z - sign * pull);
  }
  pos.needsUpdate = true;
  if (typeof geo.computeVertexNormals === "function") geo.computeVertexNormals();
  return geo;
}

function makeTramMesh(THREE, parts) {
  const group = new THREE.Group();
  const wagons = [];
  const joints = [];
  const wagonDims = [];

  for (let i = 0; i < TRAM_WAGONS; i++) {
    const wagon = new THREE.Group();
    const isLead = i === 0;
    const isTail = i === TRAM_WAGONS - 1;
    const len = TRAM_WAGON_LENS[i];
    const d = { w: TRAM_WAGON.w, h: TRAM_WAGON.h, l: len, lift: TRAM_WAGON.lift };
    wagonDims.push(d);
    const roofY = d.lift + d.h / 2;
    // Cab texture only on the outer nose/tail; bellows-facing ends stay dark.
    const mats = isLead ? parts.tramLeadMats : isTail ? parts.tramTailMats : parts.tramMidMats;
    const bodyGeo = isLead ? parts.tramLeadBody : isTail ? parts.tramTailBody : parts.tramWagonBody;
    const body = new THREE.Mesh(bodyGeo, mats);
    body.position.y = d.lift;
    wagon.add(body);

    const pod = new THREE.Mesh(parts.tramPod, parts.podMat);
    // Cab cars: slide the A/C pod toward the bellows end so the slanted nose stays clean.
    const podZ = isLead ? -0.35 : isTail ? 0.35 : 0;
    pod.position.set(0, roofY + 0.12, podZ);
    wagon.add(pod);

    if (i === 2) {
      // Single-arm pantograph on the centre wagon.
      const base = new THREE.Mesh(parts.pantoBase, parts.metalMat);
      base.position.set(0, roofY + 0.06, 0.15);
      const lower = new THREE.Mesh(parts.pantoArm, parts.metalMat);
      lower.position.set(0, roofY + 0.45, 0.35);
      lower.rotation.x = 0.55;
      const upper = new THREE.Mesh(parts.pantoArm, parts.metalMat);
      upper.position.set(0, roofY + 1.0, 0.35);
      upper.rotation.x = -0.55;
      const bar = new THREE.Mesh(parts.pantoBar, parts.metalMat);
      bar.position.set(0, roofY + 1.4, 0.15);
      wagon.add(base, lower, upper, bar);
    }

    group.add(wagon);
    wagons.push(wagon);
  }

  for (let i = 0; i < TRAM_WAGONS - 1; i++) {
    const joint = new THREE.Mesh(parts.tramJoint, parts.jointMat);
    joint.position.y = TRAM_WAGON.lift;
    group.add(joint);
    joints.push(joint);
  }

  // Destination LEDs + lamps live on the lead and tail wagons (wagon-local dims).
  const displays = [
    addDisplay(THREE, parts, wagons[0], wagonDims[0], "front", LED_BOX.tramFront, true),
    addDisplay(THREE, parts, wagons[TRAM_WAGONS - 1], wagonDims[TRAM_WAGONS - 1], "front", LED_BOX.tramFront, false),
  ];
  addLamps(THREE, parts, wagons[0], wagonDims[0], true, 0.76, 0.13, 0.87);
  addLamps(THREE, parts, wagons[TRAM_WAGONS - 1], wagonDims[TRAM_WAGONS - 1], false, 0.76, 0.13, 0.87);

  group.userData.wagons = wagons;
  group.userData.joints = joints;
  group.userData.wagonLens = TRAM_WAGON_LENS;
  group.userData.displays = displays;
  return group;
}

function makeBusMesh(THREE, parts) {
  const group = new THREE.Group();
  const d = BUS_DIM;
  const body = new THREE.Mesh(parts.busBody, parts.busMats);
  body.position.y = d.lift;
  group.add(body);
  const roofY = d.lift + d.h / 2;
  const pod = new THREE.Mesh(parts.busPod, parts.podMat);
  pod.position.set(0, roofY + 0.14, -2.3);
  group.add(pod);
  // Yellow mirrors (as on the Antwerp fleet).
  for (const sx of [-1, 1]) {
    const mirror = new THREE.Mesh(parts.mirrorGeo, parts.mirrorMat);
    mirror.position.set(sx * (d.w / 2 + 0.14), d.lift + 0.35, d.l / 2 - 0.1);
    group.add(mirror);
  }
  const displays = [
    addDisplay(THREE, parts, group, d, "front", LED_BOX.busFront, true),
    addDisplay(THREE, parts, group, d, "rear", LED_BOX.busRear, false),
  ];
  group.userData.displays = displays;
  addLamps(THREE, parts, group, d, true, 0.74, 0.09, 0.89);
  addLamps(THREE, parts, group, d, false, 0.68, 0.06, 0.94);
  return group;
}

/**
 * Paint one car-length De Lijn wagon side (optional single door). Used instead of
 * mapping the full multi-door elevation onto every short wagon.
 */
function paintTramWagonSide(ctx, w, h, { door = false, glow = false } = {}) {
  if (glow) {
    ctx.fillStyle = "#000000";
    ctx.fillRect(0, 0, w, h);
    // Lit window panes only (skip door leaf + pillars).
    ctx.fillStyle = "#ffce82";
    const bandY = h * 0.22;
    const bandH = h * 0.42;
    const doorX0 = w * 0.38;
    const doorX1 = w * 0.62;
    for (let i = 0; i < 5; i++) {
      const x0 = w * (0.06 + i * 0.18);
      const x1 = x0 + w * 0.14;
      if (door && x1 > doorX0 && x0 < doorX1) continue;
      ctx.fillRect(x0, bandY + bandH * 0.08, x1 - x0, bandH * 0.84);
    }
    return;
  }
  // Roof strip / white body / dark glazing / white lower / grey skirt.
  ctx.fillStyle = "#c8ccd0";
  ctx.fillRect(0, 0, w, h * 0.1);
  ctx.fillStyle = "#f4f5f6";
  ctx.fillRect(0, h * 0.1, w, h * 0.9);
  ctx.fillStyle = "#2a2e33";
  ctx.fillRect(0, h * 0.2, w, h * 0.46);
  // Window panes
  ctx.fillStyle = "#4a5158";
  for (let i = 0; i < 5; i++) {
    const x0 = w * (0.06 + i * 0.18);
    ctx.fillRect(x0, h * 0.24, w * 0.14, h * 0.38);
  }
  ctx.fillStyle = "#f4f5f6";
  ctx.fillRect(0, h * 0.66, w, h * 0.2);
  ctx.fillStyle = "#575e62";
  ctx.fillRect(0, h * 0.86, w, h * 0.14);
  if (!door) return;
  // One double-leaf door with De Lijn yellow diagonal + "lijn".
  const dx = w * 0.38;
  const dw = w * 0.24;
  const dy = h * 0.2;
  const dh = h * 0.66;
  ctx.fillStyle = "#1c1f23";
  ctx.fillRect(dx, dy, dw, dh);
  ctx.fillStyle = "#3a4046";
  ctx.fillRect(dx + dw * 0.06, dy + dh * 0.08, dw * 0.38, dh * 0.55);
  ctx.fillRect(dx + dw * 0.56, dy + dh * 0.08, dw * 0.38, dh * 0.55);
  ctx.save();
  ctx.beginPath();
  ctx.rect(dx, dy, dw, dh);
  ctx.clip();
  ctx.translate(dx + dw * 0.5, dy + dh * 0.55);
  ctx.rotate(-0.55);
  ctx.fillStyle = "#ffd800";
  ctx.fillRect(-dw * 0.7, -dh * 0.09, dw * 1.4, dh * 0.18);
  ctx.fillStyle = "#111111";
  ctx.font = `bold ${Math.round(dh * 0.11)}px system-ui, sans-serif`;
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  ctx.fillText("lijn", 0, 0);
  ctx.restore();
  // Yellow door frame
  ctx.strokeStyle = "#ffd800";
  ctx.lineWidth = Math.max(3, w * 0.012);
  ctx.strokeRect(dx + 1, dy + 1, dw - 2, dh - 2);
}

function makeWagonSideMaps(THREE, door) {
  const w = 512;
  const h = 256;
  const canvas = document.createElement("canvas");
  canvas.width = w;
  canvas.height = h;
  const ctx = canvas.getContext("2d");
  paintTramWagonSide(ctx, w, h, { door, glow: false });
  const map = new THREE.CanvasTexture(canvas);
  map.colorSpace = THREE.SRGBColorSpace;
  map.anisotropy = 4;
  map.needsUpdate = true;

  const gCanvas = document.createElement("canvas");
  gCanvas.width = w;
  gCanvas.height = h;
  const gctx = gCanvas.getContext("2d");
  paintTramWagonSide(gctx, w, h, { door, glow: true });
  const glow = new THREE.CanvasTexture(gCanvas);
  glow.colorSpace = THREE.SRGBColorSpace;
  glow.anisotropy = 4;
  glow.needsUpdate = true;
  return { map, glow };
}

function makeSharedParts(THREE, liveryBase) {
  const loader = new THREE.TextureLoader();
  const maps = [];
  const load = (name) => {
    const t = loader.load(`${liveryBase}${name}.jpg?v=${LIVERY_VERSION}`);
    t.colorSpace = THREE.SRGBColorSpace;
    t.anisotropy = 4;
    maps.push(t);
    return t;
  };
  const litMats = [];
  const wrap = (name, glow) => {
    const m = new THREE.MeshLambertMaterial({
      map: load(name),
      emissive: 0x000000,
      emissiveMap: glow ? load(glow) : null,
    });
    m.color.setScalar(1.22); // the flat wraps read grey under Lambert + ACES; lift them to paint-white
    if (glow) litMats.push(m);
    return m;
  };
  const wrapMaps = (map, glow) => {
    maps.push(map, glow);
    const m = new THREE.MeshLambertMaterial({
      map,
      emissive: 0x000000,
      emissiveMap: glow,
    });
    m.color.setScalar(1.22);
    litMats.push(m);
    return m;
  };
  const roofMat = new THREE.MeshLambertMaterial({ color: 0xd4d7d9 });
  const underMat = new THREE.MeshLambertMaterial({ color: 0x25282b });
  const bellowsEnd = new THREE.MeshLambertMaterial({ color: 0x2a2e33 });
  const tramFront = wrap("tram_front");
  // One door on the boarding (-x) side; window-only on +x. Full multi-door elevations
  // used to be stretched onto every segment and looked overcrowded on short wagons.
  const sideDoor = makeWagonSideMaps(THREE, true);
  const sidePlain = makeWagonSideMaps(THREE, false);
  const tramSideL = wrapMaps(sidePlain.map, sidePlain.glow);
  const tramSideR = wrapMaps(sideDoor.map, sideDoor.glow);
  // BoxGeometry face order: +x, -x, +y, -y, +z (front), -z (rear).
  const tramSideMats = [tramSideL, tramSideR, roofMat, underMat];
  // Face order: +x, -x, +y, -y, +z (travel front), -z (travel rear).
  const tramLeadMats = [...tramSideMats, tramFront, bellowsEnd];
  const tramTailMats = [...tramSideMats, bellowsEnd, tramFront];
  const tramMidMats = [...tramSideMats, bellowsEnd, bellowsEnd];
  // Right-hand traffic: the door side of a bus faces -x (right of travel along +z).
  const busMats = [
    wrap("bus_side_l", "bus_side_l_glow"),
    wrap("bus_side_r", "bus_side_r_glow"),
    roofMat,
    underMat,
    wrap("bus_front"),
    wrap("bus_rear"),
  ];
  const wagonR = 0.22; // rounded body corners (~modern Albatros look)
  const busR = 0.28; // soften the sharp box corners of the bus body
  // Cab cars: longer body + windshield rake on the outer face only (bellows end stays square).
  const tramLeadBody = makeRoundedBox(THREE, TRAM_WAGON.w, TRAM_WAGON.h, TRAM_WAGON_END_L, wagonR, 4);
  slantCabFace(tramLeadBody, "front", 0.72);
  const tramTailBody = makeRoundedBox(THREE, TRAM_WAGON.w, TRAM_WAGON.h, TRAM_WAGON_END_L, wagonR, 4);
  slantCabFace(tramTailBody, "rear", 0.72);
  const geos = {
    tramWagonBody: makeRoundedBox(THREE, TRAM_WAGON.w, TRAM_WAGON.h, TRAM_WAGON.l, wagonR, 3),
    tramLeadBody,
    tramTailBody,
    tramJoint: new THREE.BoxGeometry(TRAM_WAGON.w * 0.82, TRAM_WAGON.h * 0.86, TRAM_JOINT_GAP),
    busBody: (() => {
      const g = makeRoundedBox(THREE, BUS_DIM.w, BUS_DIM.h, BUS_DIM.l, busR, 4);
      // Mild cab rake front and rear so the bus doesn't read as a sharp brick.
      slantCabFace(g, "front", 0.55);
      slantCabFace(g, "rear", 0.45);
      return g;
    })(),
    tramPod: new THREE.BoxGeometry(1.35, 0.24, 1.8),
    busPod: new THREE.BoxGeometry(1.5, 0.3, 2.8),
    pantoBase: new THREE.BoxGeometry(0.6, 0.12, 1.0),
    pantoArm: new THREE.BoxGeometry(0.07, 0.9, 0.07),
    pantoBar: new THREE.BoxGeometry(1.4, 0.05, 0.12),
    mirrorGeo: new THREE.BoxGeometry(0.1, 0.5, 0.22),
    lampGeo: new THREE.CircleGeometry(0.15, 12),
  };
  const glowMat = (color) =>
    new THREE.MeshBasicMaterial({
      color,
      transparent: true,
      opacity: 0,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
    });
  const jointMat = new THREE.MeshLambertMaterial({ color: 0x2a2e33 });
  return {
    ...geos,
    ledGeos: [],
    maps,
    litMats,
    tramLeadMats,
    tramTailMats,
    tramMidMats,
    busMats,
    allMats: [...new Set([...tramLeadMats, ...tramTailMats, ...tramMidMats, ...busMats, jointMat, bellowsEnd])],
    jointMat,
    metalMat: new THREE.MeshLambertMaterial({ color: 0x2f3336 }),
    podMat: new THREE.MeshLambertMaterial({ color: 0x8d9296 }),
    mirrorMat: new THREE.MeshLambertMaterial({ color: 0xffd800 }),
    headGlowMat: glowMat(0xfff2cc),
    tailGlowMat: glowMat(0xff2418),
  };
}

/** Set line badge + LED displays when a vehicle (re)joins a path or reverses. */
function setLabel(THREE, v, path) {
  const text = lineLabel(path.lines, v.mode);
  const dest = destinationFor(path, v.reverse);
  const key = `${text}|${dest}`;
  if (v.labelKey === key) return;
  v.labelKey = key;
  if (v.label) {
    v.mesh.remove(v.label.sprite);
    v.label.tex.dispose();
    v.label.mat.dispose();
  }
  // GTFS labels bus lines "bus 22": the badge and LED boards only carry the number.
  const shown = text.replace(/^(bus|tram|premetro)\s+/i, "");
  v.label = makeLineSprite(THREE, shown, v.mode);
  v.mesh.add(v.label.sprite);
  v.lineText = text;
  drawDisplays(v.mesh.userData.displays || [], shown, dest);
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
  // Leave room behind a tram for its trailing wagons to sit on the path.
  const minS = mode === "tram" ? TRAM_TRAIL_SPAN + 1 : 1;
  const span = Math.max(8, path.length * 0.85 - minS);
  const s = minS + Math.random() * span;
  const mesh = mode === "tram" ? makeTramMesh(THREE, parts) : makeBusMesh(THREE, parts);
  const base = mode === "tram" ? TRAM_SPEED : BUS_SPEED;
  const v = {
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
    label: null,
    labelKey: "",
    lineText: "",
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
  setLabel(THREE, v, path);
  return v;
}

/**
 * Place each tram wagon on the path behind the lead, so the consist bends through
 * corners instead of sliding as one rigid box. `v.s` is travel distance of the
 * lead wagon centre; trailing wagons sample `v.s - tramWagonOffset(i)`.
 */
function placeTramArticulated(v, path, THREE) {
  const wagons = v.mesh.userData.wagons;
  const joints = v.mesh.userData.joints;
  const lens = v.mesh.userData.wagonLens || TRAM_WAGON_LENS;
  if (!wagons || !wagons.length) return;

  const tmpPos = v.pos;
  const tmpTan = v.tan;
  const n = wagons.length;
  for (let i = 0; i < n; i++) {
    const travel = Math.max(0.05, v.s - tramWagonOffset(i));
    const pathS = v.reverse ? path.length - travel : travel;
    const clamped = Math.max(0, Math.min(path.length, pathS));
    samplePath(path, clamped, THREE, tmpPos, tmpTan);
    if (v.reverse) tmpTan.multiplyScalar(-1);
    const p = _tramPos[i];
    const t = _tramTan[i];
    p.x = tmpPos.x;
    p.y = 1.3;
    p.z = tmpPos.z;
    t.x = tmpTan.x;
    t.z = tmpTan.z;
  }

  // Parent sits at the middle wagon with no yaw; children carry world offsets + heading.
  const mid = _tramPos[(n / 2) | 0];
  const midTan = _tramTan[(n / 2) | 0];
  v.pos.set(mid.x, mid.y, mid.z);
  v.tan.set(midTan.x, 0, midTan.z);
  if (v.tan.lengthSq() < 1e-8) v.tan.set(1, 0, 0);
  else v.tan.normalize();

  v.mesh.position.copy(v.pos);
  v.mesh.rotation.set(0, 0, 0);
  for (let i = 0; i < n; i++) {
    const p = _tramPos[i];
    const t = _tramTan[i];
    const wagon = wagons[i];
    wagon.position.set(p.x - mid.x, p.y - mid.y, p.z - mid.z);
    wagon.rotation.y = Math.atan2(t.x, t.z);
  }

  if (joints) {
    for (let i = 0; i < joints.length; i++) {
      const a = _tramPos[i];
      const b = _tramPos[i + 1];
      const ta = _tramTan[i];
      const tb = _tramTan[i + 1];
      const halfA = (lens[i] || TRAM_WAGON.l) * 0.5;
      const halfB = (lens[i + 1] || TRAM_WAGON.l) * 0.5;
      // Coupler points at the facing ends of neighbouring wagons.
      _jointA.x = a.x - ta.x * halfA;
      _jointA.y = a.y;
      _jointA.z = a.z - ta.z * halfA;
      _jointB.x = b.x + tb.x * halfB;
      _jointB.y = b.y;
      _jointB.z = b.z + tb.z * halfB;
      const jx = (_jointA.x + _jointB.x) * 0.5;
      const jz = (_jointA.z + _jointB.z) * 0.5;
      const dx = _jointB.x - _jointA.x;
      const dz = _jointB.z - _jointA.z;
      const span = Math.hypot(dx, dz);
      const joint = joints[i];
      joint.position.set(jx - mid.x, TRAM_WAGON.lift, jz - mid.z);
      joint.rotation.y = Math.atan2(dx, dz);
      // Stretch the bellows to the real gap so turns don't leave a hole or overlap.
      joint.scale.z = Math.max(0.35, span / Math.max(0.15, TRAM_JOINT_GAP));
    }
  }
}

function placeVehicle(v, paths, THREE) {
  if (v.phase === "gone") return; // hidden off-map: keep its parked position
  const path = paths[v.pathIndex];
  if (!path) return;
  if (v.mode === "tram" && v.mesh.userData.wagons) {
    placeTramArticulated(v, path, THREE);
    return;
  }
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
  // Browser: resolve next to transit.json. Headless sims have no document.baseURI.
  let liveryBase = "livery/";
  try {
    liveryBase = new URL("livery/", new URL(url, document.baseURI || "http://local/")).href;
  } catch {
    /* keep relative */
  }
  const parts = makeSharedParts(THREE, liveryBase);
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

      // Refresh line badge + LED destination from the chosen path.
      setLabel(THREE, v, allPaths[v.pathIndex]);

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
    setLabel(THREE, v, path);
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
    // Keep the consist on the path: lead starts far enough ahead for trailing wagons.
    v.s = v.mode === "tram" ? TRAM_TRAIL_SPAN + 0.5 : 0.5;
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
      return upcoming ? haltDisplayName(upcoming.name) : "Einde lijn";
    }
    const h = nextHaltAhead(v, path);
    return h ? haltDisplayName(h.name) : "Einde lijn";
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
            halt ? ` · ${haltDisplayName(halt.name)}` : ""
          }`,
        };
      }
      const near = nearestTramHalt(playerPos.x, playerPos.z);
      if (near && near.dist < 220) {
        const arr = approachingEta(near.halt, playerPos.x, playerPos.z);
        const haltLabel = haltDisplayName(near.halt.name);
        if (near.dist > BOARD_DIST + 2) {
          const dir = arr
            ? arr.dwelling
              ? `tram waiting · walk ${near.dist.toFixed(0)} m to ${haltLabel}`
              : `tram ~${Math.max(1, Math.round(arr.eta))}s · walk ${near.dist.toFixed(0)} m to ${haltLabel}`
            : `walk ${near.dist.toFixed(0)} m to ${haltLabel} tram stop`;
          return { riding: false, prompt: dir };
        }
        if (arr && !arr.dwelling) {
          return {
            riding: false,
            prompt: `Tram ${arr.vehicle.lineText} arriving in ~${Math.max(1, Math.round(arr.eta))}s at ${haltLabel}`,
          };
        }
      }
      return { riding: false };
    }
    const v = ride.vehicle;
    const next = nextHaltName(v);
    const here =
      v.phase === "dwell" && v.currentHalt ? haltDisplayName(v.currentHalt.name) : null;
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
      if (v.label) {
        v.label.tex.dispose();
        v.label.mat.dispose();
      }
      for (const d of v.mesh.userData.displays || []) {
        d.tex.dispose();
        d.mat.dispose();
      }
    }
    for (const g of [
      parts.tramWagonBody, parts.tramLeadBody, parts.tramTailBody, parts.tramJoint, parts.busBody, parts.tramPod, parts.busPod,
      parts.pantoBase, parts.pantoArm, parts.pantoBar, parts.mirrorGeo, parts.lampGeo,
      ...parts.ledGeos,
    ]) g.dispose();
    for (const m of [
      ...parts.allMats, parts.metalMat, parts.podMat, parts.mirrorMat,
      parts.headGlowMat, parts.tailGlowMat,
    ]) m.dispose();
    for (const t of parts.maps) t.dispose();
  }

  /** Night: lit windows (emissive glow maps), headlights and tail lights (0 = day, 1 = full night). */
  function setNight(t) {
    for (const m of parts.litMats) m.emissive.setRGB(0.8 * t, 0.7 * t, 0.5 * t);
    parts.headGlowMat.opacity = 0.9 * t;
    parts.tailGlowMat.opacity = 0.85 * t;
  }

  // Caption lookup: dedupe OSM platform twins that share a name within a few metres.
  const haltPois = [];
  const haltSeen = new Set();
  for (const st of worldStops) {
    if (!st.name || String(st.id).startsWith("synth_")) continue;
    const key = `${st.name}|${Math.round(st.x / 25)}|${Math.round(st.z / 25)}`;
    if (haltSeen.has(key)) continue;
    haltSeen.add(key);
    haltPois.push(st);
  }
  const HALT_REACH2 = 20 * 20; // platform edge at Gounod is ~18 m from the OSM stop node
  let haltCurrent = null;

  /** Nearest real De Lijn halt for GTA-style captions; `{ stop, changed }`. */
  function locateStop(x, z) {
    let best = null;
    let bestD = Infinity;
    for (const st of haltPois) {
      const dx = x - st.x;
      const dz = z - st.z;
      const d2 = dx * dx + dz * dz;
      if (d2 <= HALT_REACH2 && d2 < bestD) {
        bestD = d2;
        best = st;
      }
    }
    const id = best ? best.id : null;
    const changed = id !== haltCurrent;
    haltCurrent = id;
    if (!best) return { stop: null, changed };
    // Captions use the short De Lijn name; keep id/lines/coords from the OSM stop.
    return {
      stop: { ...best, name: haltDisplayName(best.name) },
      changed,
    };
  }

  return {
    update,
    dispose,
    setNight,
    locateStop,
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
    locateStop() {
      return { stop: null, changed: false };
    },
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
