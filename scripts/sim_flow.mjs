// "What does the user actually see?" flow audit for cars + trams + buses.
//
//   node scripts/sim_flow.mjs [minutes=10] [--seeds=1,2,3] [--fps=30] [--player=spawn|far|x,z]
//        [--cars=N] [--trams=N] [--buses=N] [--warm=60]
//
// sim_traffic.mjs / sim_cars_audit.mjs only flag *unexplained* stops (anything with a wait
// reason - red, queue, dwell, player - counts as "legit"). A person looking at the street
// does not care why a vehicle is parked: if half the fleet is standing still it reads as a
// jam. This script therefore counts RAW stationary time per vehicle kind, broken down by the
// reason the sim itself gives, after a warm-up. It also reports:
//   - the stationary share sampled once a second (mean / worst moment),
//   - vehicles held >30 s / >60 s of any kind and the longest single hold,
//   - stationary clusters (>=3 vehicles within 25 m, all stopped) = a visible pile-up,
//   - the same numbers restricted to the 150 m around the player (the visible area).
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
const seeds = String(flags.seeds || "1,2,3").split(",").map(Number);
const dt = 1 / (Number(flags.fps) || 30);
const warm = Number(flags.warm ?? 60);
const STILL = 0.3;
const VIEW_R = 150;

const { createTraffic } = await import(join(viewerRoot, "traffic.js"));
const { createTransit } = await import(join(viewerRoot, "transit.js"));

const fails = [];
const totals = { car: {}, tram: {}, bus: {} };
const agg = { samples: 0, stillShare: { car: 0, tram: 0, bus: 0, all: 0 }, worstShare: 0, viewStill: 0, viewN: 0,
  piles: 0, pileSamples: 0, hold30: { car: 0, tram: 0, bus: 0 }, hold60: { car: 0, tram: 0, bus: 0 }, longest: { car: 0, tram: 0, bus: 0 }, respawns: 0, presence: { tram: 0, bus: 0 } };

async function run(seed) {
  seedRandom(seed);
  const scene = new Obj();
  const traffic = await createTraffic(scene, THREE, flags.cars ? { count: Number(flags.cars) } : {});
  const transit = await createTransit(scene, THREE, { tramCount: Number(flags.trams ?? 6), busCount: Number(flags.buses ?? 8) });
  traffic.setObstacles && traffic.setObstacles(() => transit.vehicles || []);
  const player = new Obj();
  if (flags.player === "far") player.position.set(1e4, 1.7, 1e4);
  else if (typeof flags.player === "string" && flags.player.includes(",")) { const [x, z] = flags.player.split(",").map(Number); player.position.set(x, 1.7, z); }
  else player.position.set(-98.2, 1.7, -428.26); // real spawn: the Gounod tram halt
  const fleet = [
    ...traffic.cars.map((v) => ({ kind: "car", v })),
    ...transit.vehicles.map((v) => ({ kind: v.mode === "bus" ? "bus" : "tram", v })),
  ].map((f) => ({ ...f, run: 0, longest: 0, reasons: {}, secs: 0 }));
  // Not part of the street: waiting off-map for a gate, or parked kilometres away from the walkable
  // district (the pre-fix recycle bug teleported trams/buses between the far ends of their routes
  // every frame; they counted as "moving" in the old soak while nobody could ever see them).
  const DISTRICT = 336;
  const hidden = (f) => f.v.phase === "gone" || f.v.mesh.visible === false
    || Math.hypot(f.v.pos.x + 98.2, f.v.pos.z + 428.26) > DISTRICT;
  const reasonOf = (f) => (f.kind === "car" ? f.v.wait || "?" : f.v.phase === "dwell" ? "dwell" : f.v.wait || "?");
  const n = Math.round(minutes * 60 / dt);
  let t = 0, nextSample = warm;
  const per = { car: { n: 0, still: 0 }, tram: { n: 0, still: 0 }, bus: { n: 0, still: 0 } };
  const presence = { car: 0, tram: 0, bus: 0 };
  let samples = 0, sumAll = 0, worst = 0, viewN = 0, viewStill = 0, piles = 0;
  const startResp = JSON.stringify(traffic.stats().respawns);
  for (let i = 0; i < n; i++) {
    traffic.update(dt, player);
    transit.update(dt, player);
    t += dt;
    for (const f of fleet) {
      if (hidden(f)) { f.run = 0; continue; }
      const still = f.v.velocity < STILL;
      f.run = still ? f.run + dt : 0;
      if (f.run > f.longest) f.longest = f.run;
      if (t >= warm && still) { const r = reasonOf(f); f.reasons[r] = (f.reasons[r] || 0) + dt; }
      if (t >= warm) f.secs += dt;
    }
    if (t >= nextSample) {
      nextSample += 1;
      samples++;
      let st = 0, vis = 0;
      const stopped = [];
      for (const f of fleet) {
        if (hidden(f)) continue;
        vis++;
        presence[f.kind]++;
        const still = f.v.velocity < STILL;
        per[f.kind].n++;
        if (still) { per[f.kind].still++; st++; stopped.push(f); }
        const inView = Math.hypot(f.v.pos.x - player.position.x, f.v.pos.z - player.position.z) < VIEW_R;
        if (inView) { viewN++; if (still) viewStill++; }
      }
      sumAll += st / Math.max(1, vis);
      worst = Math.max(worst, st / Math.max(1, vis));
      // pile-up: >=3 stationary vehicles within 25 m of each other
      let pile = false;
      for (const a of stopped) {
        let c = 0;
        for (const b of stopped) if (Math.hypot(a.v.pos.x - b.v.pos.x, a.v.pos.z - b.v.pos.z) < 25) c++;
        if (c >= 3) { pile = true; break; }
      }
      if (pile) piles++;
    }
  }
  const row = {};
  for (const k of ["car", "tram", "bus"]) {
    const g = fleet.filter((f) => f.kind === k);
    const reasons = {};
    let total = 0;
    for (const f of g) for (const [r, s] of Object.entries(f.reasons)) { reasons[r] = (reasons[r] || 0) + s; total += s; }
    const secs = g.reduce((a, f) => a + f.secs, 0);
    row[k] = {
      n: g.length,
      stillPct: Math.round(100 * total / Math.max(1, secs)),
      reasons: Object.fromEntries(Object.entries(reasons).sort((a, b) => b[1] - a[1]).map(([r, s]) => [r, Math.round(100 * s / Math.max(1, secs)) + "%"])),
      longest: Math.round(Math.max(...g.map((f) => f.longest))),
      held30: g.filter((f) => f.longest > 30).length,
      held60: g.filter((f) => f.longest > 60).length,
    };
    agg.hold30[k] += row[k].held30; agg.hold60[k] += row[k].held60; agg.longest[k] = Math.max(agg.longest[k], row[k].longest);
    agg.stillShare[k] += row[k].stillPct;
  }
  const resp = traffic.stats().respawns;
  const meanAll = Math.round(100 * sumAll / Math.max(1, samples));
  console.log(`\n=== seed ${seed}  ${minutes} min @${Math.round(1 / dt)} fps  cars=${row.car.n} trams=${row.tram.n} buses=${row.bus.n}  player=${flags.player || "spawn"}`);
  for (const k of ["car", "tram", "bus"]) {
    const r = row[k];
    console.log(`  ${k.padEnd(4)} stationary ${String(r.stillPct).padStart(2)}% of time  ${JSON.stringify(r.reasons)}  longest hold ${r.longest}s, >30s: ${r.held30}/${r.n}, >60s: ${r.held60}/${r.n}`);
  }
  console.log(`  fleet stationary share per second: mean ${meanAll}%, worst ${Math.round(worst * 100)}%   | within ${VIEW_R} m of player: ${Math.round(100 * viewStill / Math.max(1, viewN))}% of ${Math.round(viewN / samples)} visible   | pile-up (>=3 stopped within 25 m) in ${Math.round(100 * piles / samples)}% of seconds`);
  console.log(`  on the street on average: ${(presence.car / samples).toFixed(1)}/${row.car.n} cars, ${(presence.tram / samples).toFixed(1)}/${row.tram.n} trams, ${(presence.bus / samples).toFixed(1)}/${row.bus.n} buses`);
  agg.presence.tram += presence.tram / samples; agg.presence.bus += presence.bus / samples;
  console.log(`  car respawns ${JSON.stringify(resp)}`);
  agg.samples++;
  agg.stillShare.all += meanAll;
  agg.worstShare = Math.max(agg.worstShare, worst);
  agg.viewStill += viewStill; agg.viewN += viewN;
  agg.piles += piles / samples;
  agg.respawns += Object.values(resp).reduce((a, b) => a + b, 0);
  for (const k of ["car", "tram", "bus"]) if (row[k].longest > 60 && (k === "car" || !Object.keys(row[k].reasons).every((r) => r === "dwell"))) fails.push(`seed ${seed}: ${k} held ${row[k].longest}s`);
}

for (const seed of seeds) await run(seed);
const S = agg.samples;
console.log(`\nAVERAGE over ${S} seeds: cars still ${Math.round(agg.stillShare.car / S)}%  trams still ${Math.round(agg.stillShare.tram / S)}%  buses still ${Math.round(agg.stillShare.bus / S)}%  | fleet mean ${Math.round(agg.stillShare.all / S)}%, worst second ${Math.round(agg.worstShare * 100)}% | near player ${Math.round(100 * agg.viewStill / Math.max(1, agg.viewN))}% | pile-up seconds ${Math.round(100 * agg.piles / S)}% | hold>60s car/tram/bus ${agg.hold60.car}/${agg.hold60.tram}/${agg.hold60.bus} | respawns ${agg.respawns} | avg on street: trams ${(agg.presence.tram / S).toFixed(1)}, buses ${(agg.presence.bus / S).toFixed(1)}`);
// Fleet-level guards (a person looking at the street, not the sim's own idea of "legit").
{
  const S2 = agg.samples;
  if (minutes >= 3) {
    if (agg.presence.tram / S2 < 0.6 * Number(flags.trams ?? 6)) fails.push(`only ${(agg.presence.tram / S2).toFixed(1)} trams on the street on average`);
    if (agg.presence.bus / S2 < 0.5 * Number(flags.buses ?? 8)) fails.push(`only ${(agg.presence.bus / S2).toFixed(1)} buses on the street on average`);
    if (agg.stillShare.all / S2 > 20) fails.push(`${Math.round(agg.stillShare.all / S2)}% of the visible fleet is standing still on average (budget 20%)`);
    if (agg.piles / S2 > 0.15) fails.push(`pile-ups (>=3 stopped within 25 m) in ${Math.round(100 * agg.piles / S2)}% of seconds (budget 15%)`);
  }
}
if (fails.length) { console.error("\nFAIL:\n  " + fails.join("\n  ")); process.exit(1); }
console.log("\nOK");
