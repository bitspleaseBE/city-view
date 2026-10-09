// Per-car audit of viewer/traffic.js: every car is tracked every frame.
//
//   node scripts/sim_cars_audit.mjs [minutes=10] [cars] [--seeds=1,2,3] [--verbose] [--json]
//
// For each car we record distance driven, longest stationary stretch, longest stationary
// stretch *inside an intersection* (junction centre = shared road endpoints with >=3 arms, or
// a traffic-signal cluster), the wait reason, ghost-through time and respawn teleports.
//
// Pass-through events: a car that overlaps (oriented 1.75 x 4.2 m footprint) another car's
// footprint. "vs stopped" = the other car is stationary (<0.3 m/s) and the intruder is moving
// (>1 m/s): the "drives through the parked ghost" symptom. "any overlap" counts every
// distinct overlapping pair episode regardless of speed. The run exits non-zero on any
// pass-through or any car stuck >30 s in an intersection. Car vs tram/bus overlaps have a small
// budget (see --max-transit-overlaps, default 1.2 per simulated minute).
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { THREE, Obj, viewerRoot, seedRandom } from "./_three_shim.mjs";

const args = process.argv.slice(2);
const flags = Object.fromEntries(args.filter((a) => a.startsWith("--")).map((a) => {
  const [k, v] = a.slice(2).split("=");
  return [k, v ?? true];
}));
const pos = args.filter((a) => !a.startsWith("--"));
const minutes = Number(pos[0]) || 10;
const carCount = Number(pos[1]) || undefined;
const seeds = String(flags.seeds || process.env.SEED || "1,2,3").split(",").map(Number);
const dt = 1 / (Number(flags.fps) || 30);

const { createTraffic } = await import(join(viewerRoot, "traffic.js"));
const { createTransit } = await import(join(viewerRoot, "transit.js"));
const withTransit = !flags["no-transit"];

const STILL = 0.3;
const MOVING = 1.0;
const CORE_R = 5; // m: the actual crossing box
const JUNCTION_R = 10; // m from junction centre (incl. stop-line zone)
const HALF_W = 0.875;
const HALF_L = 2.1;

function junctions(traffic, signalsRaw) {
  const ends = [];
  for (const p of traffic.paths) { ends.push(p.start); ends.push(p.end); }
  const used = new Array(ends.length).fill(false);
  const nodes = [];
  for (let i = 0; i < ends.length; i++) {
    if (used[i]) continue;
    const group = [ends[i]];
    used[i] = true;
    for (let j = i + 1; j < ends.length; j++) {
      if (!used[j] && ends[i].distanceTo(ends[j]) < 11) { group.push(ends[j]); used[j] = true; }
    }
    if (group.length >= 3) {
      const c = new THREE.Vector3();
      for (const g of group) c.add(g);
      c.multiplyScalar(1 / group.length);
      nodes.push({ c, arms: group.length, kind: "node" });
    }
  }
  const byId = new Map();
  for (const s of signalsRaw) {
    const a = byId.get(s.id) || { x: 0, z: 0, n: 0 };
    a.x += s.x; a.z += -s.y; a.n++;
    byId.set(s.id, a);
  }
  for (const a of byId.values()) {
    const c = new THREE.Vector3(a.x / a.n, 0, a.z / a.n);
    if (!nodes.some((n) => n.c.distanceTo(c) < 14)) nodes.push({ c, arms: a.n, kind: "signal" });
  }
  return nodes;
}

function nearestJunction(nodes, p) {
  let best = null, bd = Infinity;
  for (const n of nodes) {
    const d = Math.hypot(n.c.x - p.x, n.c.z - p.z);
    if (d < bd) { bd = d; best = n; }
  }
  return { node: best, d: bd };
}

// Oriented-box overlap (SAT, 2-D). Dimensions come from the `dims` of each side.
function dimsOf(x) { return x.mode ? (x.mode === "tram" ? [5.25, 1.3] : [4.5, 1.25]) : [HALF_L, HALF_W]; }
function obbOverlap(a, b) {
  const dx = b.pos.x - a.pos.x, dz = b.pos.z - a.pos.z;
  if (dx * dx + dz * dz > 12 * 12) return false;
  const [al, aw] = dimsOf(a), [bl, bw] = dimsOf(b);
  const axes = [
    [a.tan.x, a.tan.z], [a.tan.z, -a.tan.x],
    [b.tan.x, b.tan.z], [b.tan.z, -b.tan.x],
  ];
  for (const [ax, az] of axes) {
    const d = Math.abs(dx * ax + dz * az);
    const ra = al * Math.abs(a.tan.x * ax + a.tan.z * az) + aw * Math.abs(a.tan.z * ax - a.tan.x * az);
    const rb = bl * Math.abs(b.tan.x * ax + b.tan.z * az) + bw * Math.abs(b.tan.z * ax - b.tan.x * az);
    if (d > ra + rb - 0.05) return false;
  }
  return true;
}

const failures = [];
const overlapKinds = {};
const summary = [];

async function run(seed) {
  seedRandom(seed);
  const scene = new Obj();
  const traffic = await createTraffic(scene, THREE, carCount ? { count: carCount } : {});
  const transit = withTransit ? await createTransit(scene, THREE, { tramCount: 6, busCount: 8 }) : null;
  const tv = transit ? transit.vehicles || [] : [];
  if (traffic.setObstacles && !flags["blind-transit"]) traffic.setObstacles(() => tv);
  const raw = JSON.parse(readFileSync(join(viewerRoot, "roads.json"), "utf8"));
  const nodes = junctions(traffic, raw.signals || []);
  const cars = traffic.cars;
  const player = new Obj(); player.position.set(1e4, 0, 1e4);
  // --player=spawn : a motionless player at the real spawn point (the Gounod halt), as when the
  // user parks the walker and flies the free camera. --player=x,z for an arbitrary spot.
  if (flags.player === "spawn") player.position.set(-98.2, 1.7, -428.26);
  else if (typeof flags.player === "string" && flags.player.includes(",")) {
    const [px, pz] = flags.player.split(",").map(Number); player.position.set(px, 1.7, pz);
  }

  const st = cars.map((c, i) => ({
    id: i, c, last: c.pos.clone(), dist: 0, still: 0, stillJ: 0, maxStill: 0, maxStillJ: 0,
    maxStillJReason: "", respawns: 0, reasonTime: {}, jx: null,
    stillJEpisodes30: 0, counted30: false, passThrough: 0, passedThrough: 0,
  }));
  const overlapping = new Map(); // "a:b" -> {start, movingFrames, stoppedMover}
  const ev = { carVsTransit: 0, carVsStoppedTransit: 0, vsStopped: 0, vsStoppedInJunction: 0, anyOverlap: 0, anyOverlapInJunction: 0, moveMove: 0 };
  const stuckJunctionSamples = []; // {t, id, reason, secs}
  const total = Math.round(minutes * 60 / dt);
  let simT = 0;
  let stoppedFrames = 0, stoppedInJFrames = 0, stoppedInCoreFrames = 0, frames = 0;

  console.log(`\n=== seed ${seed}: cars=${cars.length} paths=${traffic.pathCount} signals=${traffic.signalCount} junctions=${nodes.length} (${minutes} min)`);

  for (let n = 0; n < total; n++) {
    traffic.update(dt, player);
    if (transit) transit.update(dt, player);
    simT += dt;
    frames++;
    for (const s of st) {
      const c = s.c;
      if (c.pathIndex !== s.lastPath) { c.pathSince = simT; s.lastPath = c.pathIndex; }
      const moved = c.pos.distanceTo(s.last);
      if (moved > 15) { s.respawns++; s.still = 0; s.stillJ = 0; s.counted30 = false; }
      else s.dist += moved;
      s.last.copy(c.pos);
      const { node, d } = nearestJunction(nodes, c.pos);
      const inJ = !!node && d < JUNCTION_R;
      s.jx = inJ ? node : null;
      if (c.velocity < STILL) {
        s.still += dt;
        stoppedFrames++;
        const reason = c.wait || "?";
        s.reasonTime[reason] = (s.reasonTime[reason] || 0) + dt;
        // Only real junction nodes count: a lone signal head "node" sits AT its own stop line.
        if (node && node.kind === "node" && d < CORE_R) stoppedInCoreFrames++;
        if (inJ) {
          stoppedInJFrames++;
          s.stillJ += dt;
          if (s.stillJ > s.maxStillJ) { s.maxStillJ = s.stillJ; s.maxStillJReason = reason; }
          if (s.stillJ > 30 && !s.counted30) {
            s.counted30 = true; s.stillJEpisodes30++;
            stuckJunctionSamples.push({ t: simT, id: s.id, reason, node: node.kind, arms: node.arms });
          }
        } else { s.stillJ = 0; s.counted30 = false; }
      } else { s.still = 0; s.stillJ = 0; s.counted30 = false; }
      if (s.still > s.maxStill) s.maxStill = s.still;
    }
    // car vs tram/bus footprint overlap (distinct episodes)
    for (const s of st) {
      for (let k = 0; k < tv.length; k++) {
        const key = `t${s.id}:${k}`;
        const hit = obbOverlap(s.c, tv[k]);
        if (hit && !overlapping.has(key)) {
          overlapping.set(key, true);
          ev.carVsTransit++;
          const o = tv[k], c = s.c, dot = c.tan.x * o.tan.x + c.tan.z * o.tan.z;
          const kind = `${o.mode} ${dot > 0.7 ? "same-way" : dot < -0.7 ? "oncoming" : "crossing"} transit ${o.velocity > 0.3 ? "moving" : o.phase === "dwell" ? "dwelling" : "stopped"} / car ${c.velocity > 0.3 ? "moving" : "stopped:" + (c.wait || "?")}`;
          overlapKinds[kind] = (overlapKinds[kind] || 0) + 1;
          if (flags.debugOverlap && kind.includes(flags.debugOverlap)) {
            const rel = (o.pos.x - c.pos.x) * c.tan.x + (o.pos.z - c.pos.z) * c.tan.z, side = (o.pos.x - c.pos.x) * c.tan.z - (o.pos.z - c.pos.z) * c.tan.x;
            console.log(`    [${simT.toFixed(0)}s] ${kind} | transit ahead of car by ${rel.toFixed(1)} m, side ${side.toFixed(1)} | car v=${c.velocity.toFixed(1)} s=${c.s.toFixed(1)}/${traffic.paths[c.pathIndex].length.toFixed(0)} path=${c.pathIndex} since-path-change=${(simT - (c.pathSince ?? 0)).toFixed(1)}s | transit v=${o.velocity.toFixed(1)} phase=${o.phase} wait=${o.wait}`);
          }
          if (s.c.velocity > MOVING && tv[k].velocity < STILL) ev.carVsStoppedTransit++;
        } else if (!hit) overlapping.delete(key);
      }
    }
    // pairwise footprint overlap
    for (let i = 0; i < st.length; i++) {
      for (let j = i + 1; j < st.length; j++) {
        const a = st[i], b = st[j];
        const key = i * 1000 + j;
        const hit = obbOverlap(a.c, b.c);
        const rec = overlapping.get(key);
        if (hit) {
          const va = a.c.velocity, vb = b.c.velocity;
          const aMovesIntoB = va > MOVING && vb < STILL;
          const bMovesIntoA = vb > MOVING && va < STILL;
          if (!rec) {
            const nj = nearestJunction(nodes, a.c.pos);
            overlapping.set(key, { inJ: nj.d < JUNCTION_R, stopped: false, mm: false, ghost: false });
            if (flags.debugCars) {
              const d = (c) => `#${c === a.c ? a.id : b.id} v=${c.velocity.toFixed(1)} wait=${c.wait || "-"} path=${c.pathIndex}${c.reverse ? "r" : ""} s=${c.s.toFixed(1)}/${traffic.paths[c.pathIndex].length.toFixed(0)} hold=${c.holdEntry}`;
              console.log(`    [${simT.toFixed(1)}s] car-car overlap: ${d(a.c)} | ${d(b.c)} | dist ${a.c.pos.distanceTo(b.c.pos).toFixed(1)}`);
            }
            ev.anyOverlap++;
            if (nj.d < JUNCTION_R) ev.anyOverlapInJunction++;
          }
          const r = overlapping.get(key);
          if (!r.stopped && (aMovesIntoB || bMovesIntoA)) {
            r.stopped = true;
            ev.vsStopped++;
            if (r.inJ) ev.vsStoppedInJunction++;
            (aMovesIntoB ? a : b).passThrough++;
            (aMovesIntoB ? b : a).passedThrough++;
          }
          if (!r.mm && va > MOVING && vb > MOVING) { r.mm = true; ev.moveMove++; }
        } else if (rec) overlapping.delete(key);
      }
    }
  }

  const stuckCars = st.filter((s) => s.maxStillJ > 30);
  const respawns = st.reduce((a, s) => a + s.respawns, 0);
  console.log(`  cars stuck >30s in an intersection: ${stuckCars.length}/${st.length}  (episodes ${st.reduce((a, s) => a + s.stillJEpisodes30, 0)})`);
  console.log(`  stopped time spent in intersections: ${(100 * stoppedInJFrames / Math.max(1, stoppedFrames)).toFixed(0)}% of stationary car-frames`);
  console.log(`  stationary car-frames inside the ${CORE_R} m crossing box: ${(100 * stoppedInCoreFrames / Math.max(1, stoppedFrames)).toFixed(1)}%`);
  console.log(`  longest stationary stretch: ${Math.max(...st.map((s) => s.maxStill)).toFixed(0)}s, longest inside a junction: ${Math.max(...st.map((s) => s.maxStillJ)).toFixed(0)}s`);
  console.log(`  pass-through (moving car overlaps STOPPED car): ${ev.vsStopped} (${ev.vsStoppedInJunction} in junctions)`);
  console.log(`  any footprint overlap episodes: ${ev.anyOverlap} (${ev.anyOverlapInJunction} in junctions), of which moving-moving ${ev.moveMove}`);
  if (tv.length) console.log(`  car footprint overlaps a tram/bus: ${ev.carVsTransit} (car moving into a stopped tram/bus: ${ev.carVsStoppedTransit})`);
  console.log(`  respawn teleports (dead cars despawned): ${respawns} ${JSON.stringify(traffic.stats().respawns)}`);
  for (const x of stuckJunctionSamples.slice(0, 8)) console.log(`    stuck: t=${x.t.toFixed(0)}s car#${x.id} reason=${x.reason} at ${x.node}(${x.arms} arms)`);
  if (flags.verbose) {
    console.log("  per-car: id dist(m) maxStill maxStillInJunction(reason) respawns passThrough/passedThrough waits");
    for (const s of st) {
      const rt = Object.entries(s.reasonTime).map(([k, v]) => `${k}:${v.toFixed(0)}s`).join(" ");
      console.log(`    #${String(s.id).padStart(2)} ${s.dist.toFixed(0).padStart(6)}m  still ${s.maxStill.toFixed(0).padStart(3)}s  inJ ${s.maxStillJ.toFixed(0).padStart(3)}s(${s.maxStillJReason || "-"})  resp ${s.respawns}  pt ${s.passThrough}/${s.passedThrough}  ${rt}`);
    }
  }
  summary.push({ seed, stuckCars: stuckCars.length, episodes: st.reduce((a, s) => a + s.stillJEpisodes30, 0), ...ev, respawns });
  if (stuckCars.length) failures.push(`seed ${seed}: ${stuckCars.length} cars stuck >30s in an intersection`);
  if (ev.vsStopped) failures.push(`seed ${seed}: ${ev.vsStopped} pass-through events vs stopped cars`);
  if (ev.anyOverlap) failures.push(`seed ${seed}: ${ev.anyOverlap} car footprint overlaps`);
  // Trams / buses share streets with cars and their GTFS / rail geometry is 1-4 m off the OSM
  // centrelines, so the odd graze at a crossing is expected; a pile of them is a regression.
  const overlapBudget = Number(flags["max-transit-overlaps"] ?? Math.ceil(minutes * 1.2));
  if (ev.carVsTransit > overlapBudget) failures.push(`seed ${seed}: ${ev.carVsTransit} car/tram-bus overlaps (budget ${overlapBudget})`);
}

for (const seed of seeds) await run(seed);
const sum = (k) => summary.reduce((a, s) => a + s[k], 0);
console.log(`\nTOTAL over ${seeds.length} seeds x ${minutes} min: stuck-in-junction cars ${sum("stuckCars")} (episodes ${sum("episodes")}), pass-through vs stopped ${sum("vsStopped")}, any overlap ${sum("anyOverlap")}, car-vs-transit ${sum("carVsTransit")}, respawns ${sum("respawns")}`);
if (Object.keys(overlapKinds).length) {
  console.log("car/tram-bus overlap kinds:");
  for (const [k, n] of Object.entries(overlapKinds).sort((a, b) => b[1] - a[1])) console.log(`  ${String(n).padStart(4)}  ${k}`);
}
if (flags.json) console.log(JSON.stringify(summary));
if (failures.length) { console.error("\nFAIL:\n  " + failures.join("\n  ")); process.exit(1); }
console.log("\nOK");
