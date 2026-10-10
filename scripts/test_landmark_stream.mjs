/**
 * Hysteresis for one-off landmark streaming. No Three.js — the decision is pure.
 *   node scripts/test_landmark_stream.mjs
 */
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import {
  LOAD_M,
  UNLOAD_M,
  createLandmarkStream,
  landmarkWanted,
  overviewLatched,
  standinKey,
} from "../viewer/landmark-stream.js";

const here = { x: 0, z: 0 };

assert.equal(landmarkWanted({ x: LOAD_M - 1, z: 0, overview: false, loaded: false }, here), true);
assert.equal(landmarkWanted({ x: LOAD_M + 5, z: 0, overview: false, loaded: false }, here), false);
// Still resident between the two radii.
assert.equal(landmarkWanted({ x: LOAD_M + 40, z: 0, overview: false, loaded: true }, here), true);
assert.equal(landmarkWanted({ x: UNLOAD_M + 5, z: 0, overview: false, loaded: true }, here), false);
// Zoomed-out free view keeps a landmark that walking would have dropped.
assert.equal(landmarkWanted({ x: 900, z: 400, overview: true, loaded: false }, here), true);

assert.equal(overviewLatched("walk", 800, true), false);
assert.equal(overviewLatched("free", 400, false), true);
assert.equal(overviewLatched("free", 160, true), true);
assert.equal(overviewLatched("free", 160, false), false);
assert.equal(overviewLatched("free", 100, true), false);

assert.equal(standinKey("lmbase_501410385"), "501410385");
assert.equal(standinKey("lmbase_501410385_roof"), "501410385");
assert.equal(standinKey("lmhold_2396262252"), "2396262252");
assert.equal(standinKey("bldg_501410385"), null);
assert.equal(standinKey("merged_lmhold_1"), null);

const spawn = JSON.parse(readFileSync(new URL("../viewer/spawn.json", import.meta.url), "utf8"));
const catalog = JSON.parse(readFileSync(new URL("../viewer/landmarks.json", import.meta.url), "utf8"));
const sx = spawn.x;
const sz = -spawn.y;
const distOf = (item) => Math.hypot(item.x - sx, -item.y - sz);
const byName = Object.fromEntries(catalog.landmarks.map((item) => [item.name, distOf(item)]));
// Halte Gounod must already be inside the load radius for these.
for (const name of [
  "Heilige Geestkerk",
  "Mechelsesteenweg 123 (Art Deco)",
  "Peter Benoitstraat 34",
  "Peter Benoitstraat 38",
  "Peter Benoitstraat 40",
  "ZAS Vincentius (Sint-Vincentiusgasthuis)",
  "Koetshuis Harmoniestraat 24",
]) {
  assert.ok(byName[name] <= LOAD_M, `${name} is ${byName[name].toFixed(0)} m from spawn, load radius ${LOAD_M}`);
}
// Pages serves these next to index.html, not under a future district folder.
for (const item of catalog.landmarks) {
  assert.match(item.file, /^landmarks\/\d+\.glb$/);
}

const standins = {
  "501410385": [
    { name: "lmbase_501410385", visible: true },
    { name: "lmbase_501410385_roof", visible: true },
  ],
  "503713425": [{ name: "lmhold_503713425", visible: true }],
};
const cityRoot = {
  traverse(fn) {
    for (const list of Object.values(standins)) for (const obj of list) fn(obj);
    fn({ name: "bldg_1", visible: true });
  },
};
const added = [];
const scene = { add(group) { added.push(group); } };
const loadedFiles = [];
const loader = {
  async loadAsync(file) {
    loadedFiles.push(file);
    return {
      scene: {
        name: "",
        traverse(fn) { fn({ isMesh: true }); },
      },
    };
  },
};
const stream = createLandmarkStream({ scene, loader, cityRoot, catalog });
await stream.prime(sx, sz);
const expectNear = catalog.landmarks.filter((item) => distOf(item) <= LOAD_M);
assert.equal(added.length, expectNear.length);
assert.deepEqual(loadedFiles.slice().sort(), expectNear.map((item) => item.file).sort());
for (const obj of standins["501410385"]) assert.equal(obj.visible, false);
for (const obj of standins["503713425"]) assert.equal(obj.visible, false);
assert.ok(added.every((group) => String(group.name).startsWith("stream_")));

console.log(
  `landmark stream ok: ${expectNear.length} spawn-range GLBs added, stand-ins hidden`,
);
