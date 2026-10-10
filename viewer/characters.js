/**
 * Shared Mixamo character loader. Each character's mesh + textures ship once in
 * {Name}_Walking.glb; the Riding / Scooter clips come from animation-only GLBs in
 * ./characters/clips/ (scripts/extract_anim_clips.py) and bind to the same node names.
 * Loads are cached, so pedestrians and riders share one download per file and the
 * viewer can start fetching while the city GLB is still being parsed.
 */
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";

/**
 * Drop Mixamo helper meshes (Icosphere) and normalize the tiny Armature scale so
 * Box3 height matches the body. Without this, riders/peds shrink to ~1 cm.
 * (Rocketbox people use fitHumanoid in humanoid-fit.js; this stays for Mixamo-era callers.)
 */
export function fitCharacterRoot(root, THREE, targetH) {
  const drop = [];
  root.traverse((o) => {
    if (!o.isMesh) return;
    const n = (o.name || "").toLowerCase();
    if (n.includes("ico") || n === "sphere" || n.includes("icosphere")) drop.push(o);
    else {
      o.castShadow = true;
      o.receiveShadow = true;
    }
  });
  for (const o of drop) o.parent?.remove(o);

  const arm = root.getObjectByName("Armature");
  if (arm && arm.scale.x > 0 && arm.scale.x < 0.001) arm.scale.setScalar(0.01);
  root.updateMatrixWorld(true);

  const box = new THREE.Box3().setFromObject(root);
  const size = new THREE.Vector3();
  box.getSize(size);
  const s = size.y > 0.01 ? targetH / size.y : 1;
  root.scale.setScalar(s);
  box.setFromObject(root);
  if (Number.isFinite(box.min.y)) root.position.y -= box.min.y;
  return root;
}

export const CHARACTERS = ["Remy", "Amy", "James", "Michelle"];
/** Smallest walking mesh in the rider cast. Remy and James start after the city is visible. */
export const STARTER = "Amy";

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

/**
 * Start character downloads now; resolves when all have settled. By default only the
 * starter Walking GLB is fetched. Pass `{ names: CHARACTERS }` for the whole cast, and
 * `{ clips: true }` to also prefetch Riding / Scooter clips.
 */
/** @deprecated alias — NPC Mixamo warm-up used by the menu boot path. */
export function preloadStarter() {
  return preloadCharacters({ clips: false, names: [STARTER] });
}

export function preloadCharacters({ clips = false, names = [STARTER] } = {}) {
  return Promise.allSettled(
    names.flatMap((n) => (clips ? [walking(n), clipFile(n, "Riding"), clipFile(n, "Scooter")] : [walking(n)])),
  );
}

const restNames = () => CHARACTERS.filter((n) => n !== STARTER);

async function templateFor(name, kind) {
  const gltf = await walking(name);
  const clips = kind === "Walking" ? gltf.animations : (await clipFile(name, kind)).animations;
  return { name: `${name}_${kind}`, scene: gltf.scene, clips: clips || [] };
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
export async function loadCharacterTemplates(kind, names = CHARACTERS) {
  const out = await Promise.all(
    names.map(async (name) => {
      try {
        return await templateFor(name, kind);
      } catch (err) {
        console.warn(`[metropolis] character load failed: ${name} ${kind}`, err);
        return null;
      }
    }),
  );
  return out.filter(Boolean);
}

/** Hand each template to `onOne` as that file finishes. Default is everyone except the starter. */
export function streamCharacterTemplates(kind, onOne, names = restNames()) {
  return Promise.allSettled(
    names.map(async (name) => {
      try {
        const tmpl = await templateFor(name, kind);
        onOne(tmpl);
        return tmpl;
      } catch (err) {
        console.warn(`[metropolis] character load failed: ${name} ${kind}`, err);
        return null;
      }
    }),
  );
}
