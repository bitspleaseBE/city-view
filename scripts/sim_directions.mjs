// Wrong-way audit for cars, buses and trams (viewer/traffic.js + viewer/transit.js).
//
//   node scripts/sim_directions.mjs [minutes=10] [--seeds=1,2,3] [--cars=N] [--player]
//   VIEWER_ROOT=/path/to/older/viewer node scripts/sim_directions.mjs   # replay an older build
//
// The oracle is deliberately independent of roads.json / transit.json: it re-reads the raw
// OpenStreetMap extract (assets/osm/harmonie.json) and derives the legal direction of every
// road segment from its oneway tags, and of every tram track from the ordered members of the
// route=tram relations. A vehicle is "wrong-way" when it sits on (within a few metres of) a
// directed segment, drives along it, and its heading opposes the legal direction.
//
// Exit code 1 when any vehicle is ever wrong-way (use --report-only to just print).
import { readFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { THREE, Obj, viewerRoot, seedRandom } from "./_three_shim.mjs";

const args = process.argv.slice(2);
const flags = Object.fromEntries(args.filter((a) => a.startsWith("--")).map((a) => {
  const [k, v] = a.slice(2).split("=");
  return [k, v ?? true];
}));
const minutes = Number(args.find((a) => !a.startsWith("--"))) || 10;
const seeds = String(flags.seeds || "1,2,3").split(",").map(Number);
const carCount = flags.cars ? Number(flags.cars) : undefined;

const here = dirname(fileURLToPath(import.meta.url));
const ORIGIN = [51.2017, 4.4114]; // scenes/antwerp_places.json klein-antwerpen origin
const project = (lat, lon) => [
  (lon - ORIGIN[1]) * 111320 * Math.cos((ORIGIN[0] * Math.PI) / 180),
  (lat - ORIGIN[0]) * 110540,
];

// ---------------------------------------------------------------- oracle (raw OSM) ----
const osm = JSON.parse(readFileSync(join(here, "..", "assets", "osm", "harmonie.json"), "utf8"));
const nodes = new Map();
const ways = new Map();
const rels = [];
for (const e of osm.elements) {
  if (e.type === "node") nodes.set(e.id, e);
  else if (e.type === "way") ways.set(e.id, e);
  else if (e.type === "relation") rels.push(e);
}
const poly = (w) => w.nodes.filter((n) => nodes.has(n)).map((n) => project(nodes.get(n).lat, nodes.get(n).lon));

const code = (v) => (["yes", "true", "1"].includes(v) ? 1 : ["-1", "reverse"].includes(v) ? -1 : ["no", "false", "0"].includes(v) ? 0 : null);
function carDir(t) {
  const c = code(t.oneway);
  if (c !== null) return c;
  if (t.junction === "roundabout" || t.junction === "circular") return 1;
  return t.highway === "motorway" || t.highway === "motorway_link" ? 1 : 0;
}
function busDir(t) {
  for (const k of ["oneway:bus", "oneway:psv"]) { const c = code(t[k]); if (c !== null) return c; }
  const car = carDir(t);
  if (car && ["busway", "busway:left", "busway:right"].some((k) => String(t[k] || "").startsWith("opposite"))) return 0;
  return car;
}
const DRIVEABLE = new Set(["motorway", "motorway_link", "trunk", "trunk_link", "primary", "primary_link", "secondary", "secondary_link", "tertiary", "tertiary_link", "unclassified", "residential", "living_street"]);

function segmentsOf(points, meta) {
  const out = [];
  for (let i = 1; i < points.length; i++) {
    const [ax, ay] = points[i - 1];
    const [bx, by] = points[i];
    const l = Math.hypot(bx - ax, by - ay);
    if (l < 0.2) continue;
    out.push({ ax, ay, bx, by, tx: (bx - ax) / l, ty: (by - ay) / l, l, ...meta });
  }
  return out;
}

const roadSegs = [];
const trackSegs = [];
// Tram direction: in an ordered route relation a way is driven *with* its node order when the
// next member continues from its last node (or the previous member ends at its first node).
const trackVotes = new Map();
for (const rel of rels) {
  if (rel.tags?.route !== "tram") continue;
  const chain = (rel.members || [])
    .filter((m) => m.type === "way" && !/^(platform|stop|station)/.test(m.role || ""))
    .map((m) => ways.get(m.ref)).filter((w) => w && w.nodes.length >= 2);
  const ends = (w) => [w.nodes[0], w.nodes[w.nodes.length - 1]];
  chain.forEach((w, i) => {
    const [first, last] = ends(w);
    const prev = i > 0 ? ends(chain[i - 1]) : [];
    const next = i + 1 < chain.length ? ends(chain[i + 1]) : [];
    const fwd = (next.includes(last) ? 1 : 0) + (prev.includes(first) ? 1 : 0);
    const bwd = (next.includes(first) ? 1 : 0) + (prev.includes(last) ? 1 : 0);
    if (fwd === bwd) return;
    if (!trackVotes.has(w.id)) trackVotes.set(w.id, new Set());
    trackVotes.get(w.id).add(fwd > bwd ? 1 : -1);
  });
}
for (const w of ways.values()) {
  const t = w.tags || {};
  if (t.railway === "tram" && t.tunnel !== "yes") {
    const votes = trackVotes.get(w.id);
    const dir = votes && votes.size === 1 ? [...votes][0] : 0;
    trackSegs.push(...segmentsOf(poly(w), { id: w.id, dir }));
  } else if (DRIVEABLE.has(t.highway) && !t.building) {
    roadSegs.push(...segmentsOf(poly(w), { id: w.id, name: t.name || "", car: carDir(t), bus: busDir(t) }));
  }
}

function nearest(segs, x, y, maxD) {
  let best = null;
  let bestD = maxD;
  for (const s of segs) {
    const dx = x - s.ax, dy = y - s.ay;
    const t = Math.max(0, Math.min(1, (dx * s.tx + dy * s.ty) / s.l));
    const d = Math.hypot(x - (s.ax + s.tx * s.l * t), y - (s.ay + s.ty * s.l * t));
    if (d < bestD) { bestD = d; best = s; }
  }
  return best ? { seg: best, d: bestD } : null;
}

/** Verdict for one vehicle sample: null (not on a directed segment) | { wrong, seg }. */
function judge(kind, v) {
  const x = v.pos.x, y = -v.pos.z; // three -> blender metres
  const hx = v.tan.x, hy = -v.tan.z;
  const segs = kind === "tram" ? trackSegs : roadSegs;
  const hit = nearest(segs, x, y, kind === "tram" ? 4 : 7);
  if (!hit) return null;
  const s = hit.seg;
  const dir = kind === "tram" ? s.dir : kind === "bus" ? s.bus : s.car;
  const along = hx * s.tx + hy * s.ty;
  if (!dir || Math.abs(along) < 0.7) return { wrong: false, seg: s, directed: false };
  return { wrong: along * dir < 0, seg: s, directed: true, along };
}

// ---------------------------------------------------------------- simulation ----
const { createTraffic } = await import(join(viewerRoot, "traffic.js"));
const { createTransit } = await import(join(viewerRoot, "transit.js"));
const dt = 1 / 30;
const SAMPLE_EVERY = 5; // frames

const totals = {};
const bump = (kind, key, n = 1) => { (totals[kind] ||= {})[key] = (totals[kind][key] || 0) + n; };
const wrongSegs = {};

async function run(seed) {
  seedRandom(seed);
  const scene = new Obj();
  const traffic = await createTraffic(scene, THREE, carCount ? { count: carCount } : {});
  const transit = await createTransit(scene, THREE, { tramCount: 6, busCount: 8 });
  traffic.setObstacles && traffic.setObstacles(() => transit.vehicles || []);
  const player = new Obj();
  player.position.set(1e4, 0, 1e4);
  const fleet = [
    ...traffic.cars.map((v) => ({ kind: "car", v })),
    ...(transit.vehicles || []).map((v) => ({ kind: v.mode === "bus" ? "bus" : "tram", v })),
  ];
  const run = new Map(fleet.map((f) => [f, { wrongFor: 0, everWrong: false }]));
  const frames = Math.round((minutes * 60) / dt);
  for (let n = 0; n < frames; n++) {
    traffic.update(dt, player);
    transit.update(dt, player);
    if (n % SAMPLE_EVERY) continue;
    for (const f of fleet) {
      const v = f.v;
      if (f.kind !== "car" && (v.phase === "gone" || v.mesh.visible === false)) continue;
      const st = run.get(f);
      const verdict = judge(f.kind, v);
      bump(f.kind, "samples");
      if (!verdict || !verdict.directed) { st.wrongFor = 0; continue; }
      bump(f.kind, "directedSamples");
      if (verdict.seg.name === "Mechelsesteenweg" || f.kind === "tram") bump(f.kind, "corridorSamples");
      if (verdict.wrong) {
        bump(f.kind, "wrongSamples");
        if (verdict.seg.name === "Mechelsesteenweg" || f.kind === "tram") bump(f.kind, "corridorWrongSamples");
        if (v.velocity > 0.3) bump(f.kind, "wrongMovingSamples");
        st.wrongFor += SAMPLE_EVERY * dt;
        if (st.wrongFor >= 0.5 && st.wrongFor - SAMPLE_EVERY * dt < 0.5) bump(f.kind, "wrongEpisodes");
        if (!st.everWrong) { st.everWrong = true; bump(f.kind, "vehiclesEverWrong"); }
        const key = `${f.kind} on ${verdict.seg.name || "way"} ${verdict.seg.id}`;
        wrongSegs[key] = (wrongSegs[key] || 0) + 1;
      } else {
        st.wrongFor = 0;
      }
    }
  }
  for (const f of fleet) bump(f.kind, "vehicles");
}

console.log(`oracle: ${roadSegs.length} road segments (${roadSegs.filter((s) => s.car).length} one-way), ${trackSegs.length} tram segments (${trackSegs.filter((s) => s.dir).length} directed)`);
console.log(`viewer: ${viewerRoot}  |  ${minutes} min x seeds ${seeds.join(",")}`);
for (const seed of seeds) await run(seed);
const secs = (n) => (n * SAMPLE_EVERY * dt).toFixed(0);
console.log("\nkind  vehicles  directed-sec  WRONG-sec  wrong%  episodes  vehicles-ever-wrong  | corridor(Mechelsesteenweg/tram) wrong-sec / sec");
for (const kind of ["car", "bus", "tram"]) {
  const t = totals[kind] || {};
  const d = t.directedSamples || 0, w = t.wrongSamples || 0;
  console.log(
    `${kind.padEnd(5)} ${String(t.vehicles || 0).padStart(8)}  ${secs(d).padStart(12)}  ${secs(w).padStart(9)}  ${(d ? (100 * w) / d : 0).toFixed(1).padStart(5)}%  ${String(t.wrongEpisodes || 0).padStart(8)}  ${String(t.vehiclesEverWrong || 0).padStart(19)}  | ${secs(t.corridorWrongSamples || 0)} / ${secs(t.corridorSamples || 0)}`,
  );
}
const top = Object.entries(wrongSegs).sort((a, b) => b[1] - a[1]).slice(0, 8);
if (top.length) console.log("\nworst offenders:\n  " + top.map(([k, n]) => `${k}: ${secs(n)} s`).join("\n  "));
const anyWrong = Object.values(totals).some((t) => (t.wrongSamples || 0) > 0);
if (anyWrong && !flags["report-only"]) { console.error("\nFAIL: wrong-way driving detected"); process.exit(1); }
console.log(anyWrong ? "\n(report only)" : "\nOK: no wrong-way driving");
