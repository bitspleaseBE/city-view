// Headless soak for viewer/traffic.js (cars) AND viewer/transit.js (trams + buses).
//
//   node scripts/sim_traffic.mjs [minutes=6] [cars] [--seeds=1,2,3] [--quiet]
//
// Cars and transit are stepped at 30 fps against the same roads.json / transit.json the
// viewer loads. Every 60 s (plus t=0) a stuck report is printed: how many vehicles have been
// at ~zero speed for >10 s / >30 s ("still"), and how many of those have no legitimate reason
// (red light / queue behind a red / dwelling at a halt) = "jam", plus the longest jam so far. A fleet is healthy when only a
// small minority is held more than 30 s and nothing is held for minutes.
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { THREE, Obj, viewerRoot, seedRandom } from "./_three_shim.mjs";

const args = process.argv.slice(2);
const flags = Object.fromEntries(args.filter((a) => a.startsWith("--")).map((a) => {
  const [k, v] = a.slice(2).split("=");
  return [k, v ?? true];
}));
const pos = args.filter((a) => !a.startsWith("--"));
const minutes = Number(pos[0]) || 6;
const carCount = Number(pos[1]) || undefined;
const seeds = String(flags.seeds || process.env.SEED || "12345").split(",").map(Number);
const quiet = !!flags.quiet;

const { createTraffic } = await import(join(viewerRoot, "traffic.js"));
const { createTransit } = await import(join(viewerRoot, "transit.js"));

const STILL = 0.3; // m/s
const checkpoints = [0, 60, 120, 180, 300, 420, 600, 900].filter((t) => t <= minutes * 60);
const dt = 1 / (Number(flags.fps) || 30);
let failures = [];

function pct(a, b) { return b ? `${Math.round((100 * a) / b)}%` : "-"; }

async function run(seed) {
  seedRandom(seed);
  const scene = new Obj();
  const traffic = await createTraffic(scene, THREE, carCount ? { count: carCount } : {});
  const transit = await createTransit(scene, THREE, { tramCount: 6, busCount: 8 });
  const roads = JSON.parse(readFileSync(join(viewerRoot, "roads.json"), "utf8")).roads;
  const tagged = roads.filter((r) => r.maxspeedKmh).length;
  const cars = traffic.cars;
  const tv = transit.vehicles || [];
  console.log(`\n=== seed ${seed}: cars=${cars.length} trams+buses=${tv.length} carPaths=${traffic.pathCount} signals=${traffic.signalCount} osmSpeedTagged=${tagged}/${roads.length}`);

  const fleet = [
    ...cars.map((c) => ({ kind: "car", v: c })),
    ...tv.map((v) => ({ kind: v.mode === "bus" ? "bus" : "tram", v })),
  ];
  const state = fleet.map((f) => ({ ...f, still: 0, jamRun: 0, lastPos: f.v.pos.clone(), jumps: 0, over: 0, since: 99, path: f.v.pathIndex }));
  const player = new Obj(); player.position.set(1e4, 0, 1e4);

  const legit = (s) => {
    const v = s.v;
    if (s.kind === "car") return v.wait === "red" || v.wait === "queue" || v.wait === "player";
    return v.phase === "dwell" || v.wait === "queue";
  };
  const speedOf = (s) => (s.kind === "car" ? s.v.velocity : s.v.velocity);

  let nextCp = 0;
  let movingSum = 0, movingSamples = 0, speedOver = 0;
  const total = Math.round(minutes * 60 / dt);
  const report = (t) => {
    const row = {};
    for (const kind of ["car", "tram", "bus"]) {
      const group = state.filter((s) => s.kind === kind);
      if (!group.length) continue;
      const still10 = group.filter((s) => s.still > 10);
      const still30 = group.filter((s) => s.still > 30);
      // jam = stationary for N s *without* a legitimate reason (red light / halt dwell);
      // the run restarts whenever the vehicle moves or is legitimately waiting.
      const jam30 = group.filter((s) => s.jamRun > 30);
      const jam10 = group.filter((s) => s.jamRun > 10);
      const moving = group.filter((s) => speedOf(s) > 0.5).length;
      row[kind] = {
        n: group.length, moving, still10: still10.length, still30: still30.length,
        jam10: jam10.length, jam30: jam30.length,
        longest: Math.max(...group.map((s) => s.jamRun)),
      };
    }
    const fmt = Object.entries(row).map(([k, r]) =>
      `${k} ${r.moving}/${r.n} moving, >10s still ${r.still10} (jam ${r.jam10}), >30s ${r.still30} (jam ${r.jam30}), longest ${r.longest.toFixed(0)}s jammed`).join(" | ");
    console.log(`  t=${String(t).padStart(4)}s  ${fmt}`);
  };

  let worst = { car: 0, tram: 0, bus: 0 };
  let carJumps = 0;
  for (let n = 0; n <= total; n++) {
    const t = n * dt;
    if (nextCp < checkpoints.length && t >= checkpoints[nextCp]) { if (!quiet || true) report(checkpoints[nextCp]); nextCp++; }
    if (n === total) break;
    traffic.update(dt, player);
    transit.update(dt, player);
    for (const s of state) {
      const v = s.v;
      if (s.kind === "car" && v.pos.distanceTo(s.lastPos) > 15) carJumps++;
      s.lastPos.copy(v.pos);
      s.still = speedOf(s) < STILL ? s.still + dt : 0;
      s.jamRun = s.still > 0 && !legit(s) ? s.jamRun + dt : 0;
      if (s.jamRun > worst[s.kind]) worst[s.kind] = s.jamRun;
      if (s.kind === "car") {
        if (v.pathIndex !== s.path) { s.path = v.pathIndex; s.since = 0; }
        s.since += dt;
        if (s.since > 4 && v.velocity > traffic.paths[v.pathIndex].speedLimit * 1.06) speedOver++;
      }
    }
    if (n % 30 === 0) {
      const m = cars.filter((c) => c.velocity > 0.5).length / cars.length;
      movingSum += m; movingSamples++;
    }
  }
  console.log(`  worst non-legit stop: car ${worst.car.toFixed(0)}s  tram ${worst.tram.toFixed(0)}s  bus ${worst.bus.toFixed(0)}s | car respawn-jumps ${carJumps} | car speed>106%limit frames ${speedOver} | car avg moving ${pct(movingSum, movingSamples)}`);
  if (worst.car > 45) failures.push(`seed ${seed}: car stopped ${worst.car.toFixed(0)}s with no legit reason`);
  if (worst.tram > 45) failures.push(`seed ${seed}: tram stopped ${worst.tram.toFixed(0)}s with no legit reason`);
  if (worst.bus > 45) failures.push(`seed ${seed}: bus stopped ${worst.bus.toFixed(0)}s with no legit reason`);
  if (speedOver > 0) failures.push(`seed ${seed}: cars exceeded speed limit`);
  if (movingSum / movingSamples < 0.6) failures.push(`seed ${seed}: too few cars moving on average`);
}

for (const seed of seeds) await run(seed);
if (failures.length) { console.error("\nFAIL:\n  " + failures.join("\n  ")); process.exit(1); }
console.log("\nOK");
