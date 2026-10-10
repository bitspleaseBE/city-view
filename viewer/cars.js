/**
 * Belgian 2025-26 car fleet: procedural real-model GLBs from ./cars/ (built by
 * blender/build_car_models.py). Each GLB has a plain `car_paint` material that is
 * recoloured per car, `car_headlight` / `car_taillight` lenses that are swapped for the
 * shared night-glow lamp materials, and four `wheel-*` nodes spun about their axles.
 * Falls back to [] when GLTFLoader is unavailable (headless Node sims).
 */

const FLEET_URL = new URL("./cars/fleet.json", import.meta.url);

/** One common SUV and one city hatch. The other eight models load once the street is up. */
export const STARTER_CARS = ["model_y.glb", "peugeot_208.glb"];

/** Weighted paint mix seen on Belgian streets (sRGB): greyscale dominates, a few colours. */
export const CAR_PAINTS = [
  [0xe8e9e6, 20], // white
  [0x0c0d0f, 19], // black
  [0x3b3e42, 17], // dark grey
  [0x9fa3a7, 11], // silver
  [0x6f7275, 8], // mid grey
  [0x1c2a47, 8], // dark blue
  [0x2e5c98, 3], // bright blue
  [0x8c1518, 4], // red
  [0x2b3a30, 3], // dark green
  [0xb1a487, 3], // sand
  [0x6d2a1c, 2], // copper / brown
  [0xc9b23c, 1], // yellow (Renault 5 & co.)
];
const PAINT_TOTAL = CAR_PAINTS.reduce((s, [, w]) => s + w, 0);

/** Paint colour for a unit random number in [0, 1). */
export function pickCarPaint(r) {
  let t = r * PAINT_TOTAL;
  for (const [hex, w] of CAR_PAINTS) {
    t -= w;
    if (t < 0) return hex;
  }
  return CAR_PAINTS[0][0];
}

const PAINT_RE = /^car_paint/;
const HEAD_RE = /^car_headlight/;
const TAIL_RE = /^car_taillight/;

/**
 * @typedef {{ id: string, file: string, weight: number, length: number, width: number, height: number, scene: import('three').Object3D, wheels: import('three').Object3D[], wheelRadius: number, hasLamps: boolean, halfL: number, halfW: number }} CarTemplate
 */

/** @returns {Promise<{ models: object[] } | null>} */
async function loadFleetDoc() {
  try {
    const res = await fetch(FLEET_URL.href);
    if (!res.ok) throw new Error(`fleet.json ${res.status}`);
    return await res.json();
  } catch (err) {
    console.warn("[metropolis] Car fleet manifest missing:", err);
    return null;
  }
}

function forEachMaterial(root, fn) {
  root.traverse((o) => {
    if (!o.isMesh || !o.material) return;
    if (Array.isArray(o.material)) o.material = o.material.map((m) => fn(m) || m);
    else o.material = fn(o.material) || o.material;
  });
}

/** One clone of `base` per paint colour, shared by every car using it. */
function paintMaterial(cache, base, hex) {
  const key = `${base.uuid}|${hex}`;
  let m = cache.get(key);
  if (!m) {
    m = base.clone();
    m.color.setHex(hex);
    cache.set(key, m);
  }
  return m;
}

/**
 * @param {typeof import('three')} THREE
 * @returns {Promise<CarTemplate[]>}
 */
export async function loadCarTemplates(THREE, opts = {}) {
  let GLTFLoader;
  try {
    ({ GLTFLoader } = await import("three/addons/loaders/GLTFLoader.js"));
  } catch {
    return [];
  }
  if (!THREE.Box3) return [];

  const doc = await loadFleetDoc();
  if (!doc?.models?.length) return [];

  let models = doc.models;
  if (opts.only?.length) models = models.filter((spec) => opts.only.includes(spec.file));
  else if (opts.skip?.length) models = models.filter((spec) => !opts.skip.includes(spec.file));
  if (!models.length) return [];

  const loader = new GLTFLoader();
  const base = new URL("./cars/", import.meta.url);
  /** @type {CarTemplate[]} */
  const out = [];

  await Promise.all(
    models.map(async (spec) => {
      try {
        const url = new URL(spec.file, base).href;
        const gltf = await loader.loadAsync(url);
        const root = gltf.scene;
        // Y-up, length on Z, nose toward +Z — matches traffic.js travel.
        const box = new THREE.Box3().setFromObject(root);
        const size = new THREE.Vector3();
        box.getSize(size);
        if (size.x < 1e-3 || size.y < 1e-3 || size.z < 1e-3) {
          throw new Error("empty bounds");
        }
        root.scale.set(spec.width / size.x, spec.height / size.y, spec.length / size.z);
        root.updateMatrixWorld(true);
        box.setFromObject(root);
        const center = new THREE.Vector3();
        box.getCenter(center);
        root.position.x -= center.x;
        root.position.z -= center.z;
        root.position.y -= box.min.y;
        root.updateMatrixWorld(true);

        const wheels = [];
        let hasLamps = false;
        root.traverse((o) => {
          if (o.isMesh) {
            o.castShadow = true;
            o.receiveShadow = true;
            o.frustumCulled = true;
            const mats = Array.isArray(o.material) ? o.material : [o.material];
            if (mats.some((m) => m && (HEAD_RE.test(m.name) || TAIL_RE.test(m.name)))) hasLamps = true;
          }
          const n = String(o.name || "").toLowerCase();
          if (n.startsWith("wheel")) wheels.push(o);
        });
        let wheelRadius = Math.max(0.28, spec.height * 0.22);
        if (wheels.length) {
          const wb = new THREE.Box3().setFromObject(wheels[0]);
          wheelRadius = Math.max(0.2, (wb.max.y - wb.min.y) * 0.5);
        }

        out.push({
          id: spec.id,
          file: spec.file,
          weight: Number(spec.weight) || 1,
          length: spec.length,
          width: spec.width,
          height: spec.height,
          halfL: spec.length * 0.5,
          halfW: spec.width * 0.5,
          scene: root,
          wheels,
          wheelRadius,
          hasLamps,
        });
      } catch (err) {
        console.warn(`[metropolis] Car model load failed: ${spec.file}`, err);
      }
    }),
  );

  return out;
}

/** Weighted pick into `templates` (same order / weights as loaded). */
export function pickCarTemplate(templates) {
  if (!templates || !templates.length) return null;
  let total = 0;
  for (const t of templates) total += t.weight;
  let r = Math.random() * total;
  for (const t of templates) {
    r -= t.weight;
    if (r <= 0) return t;
  }
  return templates[templates.length - 1];
}

/**
 * Clone a fleet car with its own paint colour and the shared head/tail lamp materials
 * (so setNight lights every car). Templates without lamp lenses get bolt-on lamp boxes.
 * @param {typeof import('three')} THREE
 * @param {ReturnType<typeof makeLampParts>} parts
 * @param {CarTemplate} template
 */
export function cloneCarMesh(THREE, parts, template) {
  const group = new THREE.Group();
  const body = template.scene.clone(true);
  group.add(body);

  const paint = pickCarPaint(Math.random());
  forEachMaterial(body, (m) => {
    if (PAINT_RE.test(m.name)) return paintMaterial(parts.paintMats, m, paint);
    if (HEAD_RE.test(m.name)) return parts.headMat;
    if (TAIL_RE.test(m.name)) return parts.tailMat;
    return null;
  });

  const wheels = [];
  body.traverse((o) => {
    const n = String(o.name || "").toLowerCase();
    if (n.startsWith("wheel")) wheels.push(o);
  });
  group.userData.wheels = wheels;
  group.userData.wheelRadius = template.wheelRadius;
  group.userData.halfL = template.halfL;
  group.userData.halfW = template.halfW;
  group.userData.carId = template.id;

  if (!template.hasLamps) {
    const zNose = template.halfL - 0.06;
    const yLamp = Math.max(0.35, template.height * 0.32);
    const xLamp = template.width * 0.28;
    for (const sx of [-xLamp, xLamp]) {
      const head = new THREE.Mesh(parts.lampGeo, parts.headMat);
      head.position.set(sx, yLamp, zNose);
      const tail = new THREE.Mesh(parts.lampGeo, parts.tailMat);
      tail.position.set(sx, yLamp + 0.08, -zNose);
      group.add(head, tail);
    }
  }
  return group;
}

/** FNV-1a: stable per-name paint for parked cars across reloads. */
function hashUnit(str) {
  let h = 0x811c9dc5;
  for (let i = 0; i < str.length; i++) {
    h ^= str.charCodeAt(i);
    h = Math.imul(h, 0x01000193);
  }
  return (h >>> 0) / 4294967296;
}

const parkedPaints = new Map();

/**
 * Give each parked car baked into the district GLB (nodes `car_<n>_<model>`) its own
 * paint colour. Run before mergeStaticMeshes so cars sharing a colour still batch.
 * @returns {number} cars repainted
 */
export function paintParkedCars(root) {
  let n = 0;
  root.traverse((o) => {
    if (!/^car_\d+_/.test(o.name || "")) return;
    const hex = pickCarPaint(hashUnit(o.name));
    let hit = false;
    forEachMaterial(o, (m) => {
      if (!PAINT_RE.test(m.name)) return null;
      hit = true;
      return paintMaterial(parkedPaints, m, hex);
    });
    if (hit) n++;
  });
  return n;
}

/** Shared lamp geometry/materials used by both GLB clones and box fallbacks. */
export function makeLampParts(THREE, bodyColors) {
  return {
    lampGeo: new THREE.BoxGeometry(0.34, 0.16, 0.06),
    headMat: new THREE.MeshBasicMaterial({ color: 0xcfd2cc, toneMapped: false }),
    tailMat: new THREE.MeshBasicMaterial({ color: 0x5a1212, toneMapped: false }),
    bodyMats: bodyColors.map((c) => new THREE.MeshLambertMaterial({ color: c })),
    /** @type {Map<string, import('three').Material>} per-colour clones of GLB car_paint */
    paintMats: new Map(),
    glassMat: new THREE.MeshLambertMaterial({ color: 0x88a0b8, transparent: true, opacity: 0.75 }),
    tireMat: new THREE.MeshLambertMaterial({ color: 0x1a1a1a }),
    bodyGeo: new THREE.BoxGeometry(1.75, 1.35, 4.2),
    cabinGeo: new THREE.BoxGeometry(1.55, 0.65, 2.0),
    wheelGeo: new THREE.BoxGeometry(0.22, 0.45, 0.55),
  };
}

const HEAD_DAY = [0.81, 0.82, 0.8];
const HEAD_NIGHT = [1.0, 0.94, 0.72];
const TAIL_DAY = [0.12, 0.02, 0.02];
const TAIL_NIGHT = [1.0, 0.1, 0.08];

/**
 * Night lamps for baked kerbside cars (`car_<n>_<model>`). Models with real
 * headlight / taillight lenses share those materials so they glow at night;
 * anything else gets bolt-on lamp boxes. Each car is wrapped in a Group before
 * mergeStaticMeshes so it is not absorbed into a tile batch.
 * @returns {{ count: number, setNight: (t: number) => void }}
 */
export function wireParkedCarLamps(root, THREE) {
  const parts = makeLampParts(THREE, []);
  const cars = [];
  root.traverse((o) => {
    if (o.isMesh && /^car_\d+_/.test(o.name || "")) cars.push(o);
  });
  const _box = new THREE.Box3();
  const _size = new THREE.Vector3();
  const _inv = new THREE.Matrix4();
  for (const mesh of cars) {
    const parent = mesh.parent;
    if (!parent) continue;
    const g = new THREE.Group();
    g.name = mesh.name;
    parent.add(g);
    g.position.copy(mesh.position);
    g.quaternion.copy(mesh.quaternion);
    g.scale.copy(mesh.scale);
    mesh.position.set(0, 0, 0);
    mesh.quaternion.identity();
    mesh.scale.set(1, 1, 1);
    mesh.name = `${g.name}_body`;
    g.add(mesh);
    mesh.updateMatrix();
    g.updateMatrixWorld(true);

    let hasLamps = false;
    forEachMaterial(mesh, (m) => {
      if (HEAD_RE.test(m.name)) {
        hasLamps = true;
        return parts.headMat;
      }
      if (TAIL_RE.test(m.name)) {
        hasLamps = true;
        return parts.tailMat;
      }
      return null;
    });
    if (hasLamps) continue;

    _box.setFromObject(mesh);
    _inv.copy(g.matrixWorld).invert();
    _box.applyMatrix4(_inv);
    _box.getSize(_size);
    if (_size.x < 0.2 || _size.z < 0.2) continue;
    const yLamp = Math.max(0.35, _box.min.y + _size.y * 0.38);
    const xLamp = Math.min(_size.x * 0.32, 0.7);
    const zNose = _box.max.z - 0.05;
    const zTail = _box.min.z + 0.05;
    for (const sx of [-xLamp, xLamp]) {
      const head = new THREE.Mesh(parts.lampGeo, parts.headMat);
      head.position.set(sx, yLamp, zNose);
      const tail = new THREE.Mesh(parts.lampGeo, parts.tailMat);
      tail.position.set(sx, yLamp + 0.06, zTail);
      g.add(head, tail);
    }
  }
  if (cars.length) {
    console.info(`[metropolis] parked cars: ${cars.length} with night lamps`);
  }
  return {
    count: cars.length,
    setNight(t) {
      const u = Math.max(0, Math.min(1, t));
      parts.headMat.color.setRGB(
        HEAD_DAY[0] + (HEAD_NIGHT[0] - HEAD_DAY[0]) * u,
        HEAD_DAY[1] + (HEAD_NIGHT[1] - HEAD_DAY[1]) * u,
        HEAD_DAY[2] + (HEAD_NIGHT[2] - HEAD_DAY[2]) * u,
      );
      parts.tailMat.color.setRGB(
        TAIL_DAY[0] + (TAIL_NIGHT[0] - TAIL_DAY[0]) * u,
        TAIL_DAY[1] + (TAIL_NIGHT[1] - TAIL_DAY[1]) * u,
        TAIL_DAY[2] + (TAIL_NIGHT[2] - TAIL_DAY[2]) * u,
      );
    },
  };
}
