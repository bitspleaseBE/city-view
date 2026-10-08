// Headless soak test for viewer/traffic.js: `node scripts/sim_traffic.mjs [minutes]`.
// Uses a tiny THREE shim; asserts cars keep flowing and stay near posted limits.
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const root = join(dirname(fileURLToPath(import.meta.url)), "..", "viewer");

class Vector3 {
  constructor(x = 0, y = 0, z = 0) { this.x = x; this.y = y; this.z = z; }
  set(x, y, z) { this.x = x; this.y = y; this.z = z; return this; }
  copy(v) { this.x = v.x; this.y = v.y; this.z = v.z; return this; }
  clone() { return new Vector3(this.x, this.y, this.z); }
  add(v) { this.x += v.x; this.y += v.y; this.z += v.z; return this; }
  multiplyScalar(k) { this.x *= k; this.y *= k; this.z *= k; return this; }
  subVectors(a, b) { this.x = a.x - b.x; this.y = a.y - b.y; this.z = a.z - b.z; return this; }
  lerpVectors(a, b, t) { this.x = a.x + (b.x - a.x) * t; this.y = a.y + (b.y - a.y) * t; this.z = a.z + (b.z - a.z) * t; return this; }
  lengthSq() { return this.x ** 2 + this.y ** 2 + this.z ** 2; }
  length() { return Math.sqrt(this.lengthSq()); }
  normalize() { const l = this.length() || 1; return this.multiplyScalar(1 / l); }
  dot(v) { return this.x * v.x + this.y * v.y + this.z * v.z; }
  distanceToSquared(v) { return (this.x - v.x) ** 2 + (this.y - v.y) ** 2 + (this.z - v.z) ** 2; }
  distanceTo(v) { return Math.sqrt(this.distanceToSquared(v)); }
}
class Obj { constructor() { this.children = []; this.position = new Vector3(); this.rotation = { y: 0 }; } add(...c) { this.children.push(...c); } }
const THREE = {
  Vector3, Group: Obj, Mesh: Obj,
  BoxGeometry: class { dispose() {} },
  MeshLambertMaterial: class { dispose() {} },
};
globalThis.fetch = async (url) => ({
  ok: true,
  json: async () => JSON.parse(readFileSync(join(root, url), "utf8")),
});

// Deterministic runs (override with SEED=n).
let seed = Number(process.env.SEED) || 12345;
Math.random = () => { seed = (seed * 1664525 + 1013904223) >>> 0; return seed / 4294967296; };

const { createTraffic } = await import(join(root, "traffic.js"));
const minutes = Number(process.argv[2]) || 6;
const scene = new Obj();
scene.remove = () => {};
const traffic = await createTraffic(scene, THREE, Number(process.argv[3]) ? { count: Number(process.argv[3]) } : {});
const roads = JSON.parse(readFileSync(join(root, "roads.json"), "utf8")).roads;
const tagged = roads.filter((r) => r.maxspeedKmh).length;
console.log(`cars=${traffic.count} paths=${traffic.pathCount} signals=${traffic.signalCount} tagged=${tagged}/${roads.length}`);

const dt = 1 / 30;
const total = Math.round(minutes * 60 / dt);
let movingSum = 0, samples = 0, minMoving = Infinity, over = 0, maxRatio = 0, zeroCarSeconds = 0;
const maxStall = new Map();
const stallRun = new Map();
let respawnJumps = 0;
const last = traffic.cars.map((c) => c.pos.clone());
const lastPath = traffic.cars.map((c) => c.pathIndex);
const sinceChange = traffic.cars.map(() => 99);
const player = new Obj(); player.position.set(1e4, 0, 1e4);
for (let n = 0; n < total; n++) {
  traffic.update(dt, player);
  traffic.cars.forEach((c, i) => {
    if (c.pos.distanceTo(last[i]) > 15) respawnJumps++;
    last[i].copy(c.pos);
    if (c.pathIndex !== lastPath[i]) { lastPath[i] = c.pathIndex; sinceChange[i] = 0; }
    sinceChange[i] += dt;
    const lim = traffic.paths[c.pathIndex].speedLimit;
    // Allow a few seconds to shed speed after entering a slower road.
    if (sinceChange[i] > 4) {
      maxRatio = Math.max(maxRatio, c.velocity / lim);
      if (c.velocity > lim * 1.06) over++;
    }
    const run = c.velocity < 0.3 ? (stallRun.get(i) || 0) + dt : 0;
    stallRun.set(i, run);
    if (run > (maxStall.get(i) || 0)) maxStall.set(i, run);
  });
  if (n % 30 === 0) {
    const st = traffic.stats();
    movingSum += st.moving / st.total; samples++;
    minMoving = Math.min(minMoving, st.moving / st.total);
  }
}
const stalls = [...maxStall.values()];
const worst = Math.max(...stalls);
console.log(`avg moving ${(100 * movingSum / samples).toFixed(0)}%  min moving ${(100 * minMoving).toFixed(0)}%`);
console.log(`longest single stop ${worst.toFixed(1)}s  respawn-jumps ${respawnJumps}  speed>106% limit frames ${over}  max v/limit ${maxRatio.toFixed(2)}`);
console.log(`final ${JSON.stringify(traffic.stats())}`);
const fail = [];
if (movingSum / samples < 0.6) fail.push("too few cars moving on average");
if (worst > 45) fail.push(`a car sat still ${worst.toFixed(0)}s`);
if (over > 0) fail.push("exceeded speed limit");
if (fail.length) { console.error("FAIL: " + fail.join("; ")); process.exit(1); }
console.log("OK");
