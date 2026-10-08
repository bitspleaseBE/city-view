// Minimal THREE + DOM shim so viewer/traffic.js and viewer/transit.js run headless in Node.
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join, resolve, sep } from "node:path";

export const viewerRoot = join(dirname(fileURLToPath(import.meta.url)), "..", "viewer");

export class Vector3 {
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

export class Obj {
  constructor() { this.children = []; this.position = new Vector3(); this.rotation = { y: 0 }; this.scale = new Vector3(1, 1, 1); }
  add(...c) { this.children.push(...c); }
  remove(...c) { this.children = this.children.filter((x) => !c.includes(x)); }
}

class Disposable { dispose() {} }

export const THREE = {
  Vector3, Group: Obj, Mesh: Obj, Sprite: Obj,
  BoxGeometry: Disposable,
  MeshLambertMaterial: Disposable,
  SpriteMaterial: Disposable,
  CanvasTexture: class extends Disposable {},
};

globalThis.document = {
  createElement: () => ({
    width: 0, height: 0,
    getContext: () => new Proxy({}, { get: () => () => {}, set: () => true }),
  }),
};

// Test-only fetch: serves files from viewer/ and refuses anything that escapes it.
globalThis.fetch = async (url) => {
  const file = resolve(viewerRoot, String(url));
  if (!file.startsWith(resolve(viewerRoot) + sep)) throw new Error(`fetch outside viewer/: ${url}`);
  return { ok: true, json: async () => JSON.parse(readFileSync(file, "utf8")) };
};

/** Seeded PRNG replacing Math.random (override with SEED=n). */
export function seedRandom(seed) {
  let s = seed >>> 0;
  Math.random = () => { s = (s * 1664525 + 1013904223) >>> 0; return s / 4294967296; };
}
