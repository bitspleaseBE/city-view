/**
 * Shared Mixamo character loader. Each character's mesh + textures ship once in
 * {Name}_Walking.glb; the Riding / Scooter clips come from animation-only GLBs in
 * ./characters/clips/ (scripts/extract_anim_clips.py) and bind to the same node names.
 * Loads are cached, so pedestrians and riders share one download per file and the
 * viewer can start fetching while the city GLB is still being parsed.
 */
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";

export const CHARACTERS = ["Remy", "Amy", "James", "Michelle"];

const base = new URL("./characters/", import.meta.url);
const loader = new GLTFLoader();
const cache = new Map();
const listeners = new Set();
let started = 0;
let finished = 0;

function load(path) {
  let p = cache.get(path);
  if (!p) {
    started++;
    p = loader.loadAsync(new URL(path, base).href).finally(() => {
      finished++;
      for (const fn of listeners) fn(finished / started);
    });
    cache.set(path, p);
  }
  return p;
}

const walking = (name) => load(`${name}_Walking.glb`);
const clipFile = (name, kind) => load(`clips/${name}_${kind}.glb`);

/** Start every character download now; resolves when all have settled. */
export function preloadCharacters() {
  return Promise.allSettled(
    CHARACTERS.flatMap((n) => [walking(n), clipFile(n, "Riding"), clipFile(n, "Scooter")]),
  );
}

/** fn(fraction of started character files that have finished). Returns an unsubscribe. */
export function onCharacterProgress(fn) {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

/**
 * One template per character that loaded: { name, scene, clips }. `kind` is
 * "Walking" (clips from the mesh file) or "Riding" / "Scooter" (clips from clips/).
 * The scene is shared between callers; clone it (SkeletonUtils) and never mutate it.
 */
export async function loadCharacterTemplates(kind) {
  const out = await Promise.all(
    CHARACTERS.map(async (name) => {
      try {
        const gltf = await walking(name);
        const clips = kind === "Walking" ? gltf.animations : (await clipFile(name, kind)).animations;
        return { name: `${name}_${kind}`, scene: gltf.scene, clips: clips || [] };
      } catch (err) {
        console.warn(`[cityview] character load failed: ${name} ${kind}`, err);
        return null;
      }
    }),
  );
  return out.filter(Boolean);
}
