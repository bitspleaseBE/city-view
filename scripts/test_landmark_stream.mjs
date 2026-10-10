/**
 * Hysteresis for one-off landmark streaming. No Three.js — the decision is pure.
 *   node scripts/test_landmark_stream.mjs
 */
import assert from "node:assert/strict";
import {
  LOAD_M,
  UNLOAD_M,
  landmarkWanted,
  overviewLatched,
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

console.log("landmark stream hysteresis ok");
