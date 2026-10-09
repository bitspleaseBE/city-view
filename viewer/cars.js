/**
 * Antwerp-weighted car fleet: Kenney Car Kit GLBs (CC0) from ./cars/.
 * Falls back to [] when GLTFLoader is unavailable (headless Node sims).
 */

const FLEET_URL = new URL("./cars/fleet.json", import.meta.url);

/**
 * @typedef {{ id: string, file: string, weight: number, length: number, width: number, height: number, scene: import('three').Object3D, wheels: import('three').Object3D[], halfL: number, halfW: number }} CarTemplate
 */

/** @returns {Promise<{ models: object[] } | null>} */
async function loadFleetDoc() {
  try {
    const res = await fetch(FLEET_URL.href);
    if (!res.ok) throw new Error(`fleet.json ${res.status}`);
    return await res.json();
  } catch (err) {
    console.warn("[cityview] Car fleet manifest missing:", err);
    return null;
  }
}

/**
 * @param {typeof import('three')} THREE
 * @returns {Promise<CarTemplate[]>}
 */
export async function loadCarTemplates(THREE) {
  let GLTFLoader;
  try {
    ({ GLTFLoader } = await import("three/addons/loaders/GLTFLoader.js"));
  } catch {
    return [];
  }
  if (!THREE.Box3) return [];

  const doc = await loadFleetDoc();
  if (!doc?.models?.length) return [];

  const loader = new GLTFLoader();
  const base = new URL("./cars/", import.meta.url);
  /** @type {CarTemplate[]} */
  const out = [];

  await Promise.all(
    doc.models.map(async (spec) => {
      try {
        const url = new URL(spec.file, base).href;
        const gltf = await loader.loadAsync(url);
        const root = gltf.scene;
        // Kenney GLBs are Y-up, length on Z, front toward +Z — matches traffic.js travel.
        const box = new THREE.Box3().setFromObject(root);
        const size = new THREE.Vector3();
        box.getSize(size);
        if (size.x < 1e-3 || size.y < 1e-3 || size.z < 1e-3) {
          throw new Error("empty bounds");
        }
        const sx = spec.width / size.x;
        const sy = spec.height / size.y;
        const sz = spec.length / size.z;
        root.scale.set(sx, sy, sz);
        root.updateMatrixWorld(true);
        box.setFromObject(root);
        const center = new THREE.Vector3();
        box.getCenter(center);
        root.position.x -= center.x;
        root.position.z -= center.z;
        root.position.y -= box.min.y;
        root.updateMatrixWorld(true);

        const wheels = [];
        root.traverse((o) => {
          if (o.isMesh) {
            o.castShadow = true;
            o.receiveShadow = true;
            o.frustumCulled = true;
          }
          const n = String(o.name || "").toLowerCase();
          if (n.includes("wheel")) wheels.push(o);
        });

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
        });
      } catch (err) {
        console.warn(`[cityview] Car model load failed: ${spec.file}`, err);
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
 * Clone a normalised Kenney car and bolt on shared head/tail lamps for night glow.
 * @param {typeof import('three')} THREE
 * @param {ReturnType<typeof makeLampParts>} parts
 * @param {CarTemplate} template
 */
export function cloneCarMesh(THREE, parts, template) {
  const group = new THREE.Group();
  const body = template.scene.clone(true);
  group.add(body);

  const wheels = [];
  body.traverse((o) => {
    const n = String(o.name || "").toLowerCase();
    if (n.includes("wheel")) wheels.push(o);
  });
  group.userData.wheels = wheels;
  group.userData.wheelRadius = Math.max(0.28, template.height * 0.22);
  group.userData.halfL = template.halfL;
  group.userData.halfW = template.halfW;
  group.userData.carId = template.id;

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
  return group;
}

/** Shared lamp geometry/materials used by both GLB clones and box fallbacks. */
export function makeLampParts(THREE, bodyColors) {
  return {
    lampGeo: new THREE.BoxGeometry(0.34, 0.16, 0.06),
    headMat: new THREE.MeshBasicMaterial({ color: 0xcfd2cc, toneMapped: false }),
    tailMat: new THREE.MeshBasicMaterial({ color: 0x5a1212, toneMapped: false }),
    bodyMats: bodyColors.map((c) => new THREE.MeshLambertMaterial({ color: c })),
    glassMat: new THREE.MeshLambertMaterial({ color: 0x88a0b8, transparent: true, opacity: 0.75 }),
    tireMat: new THREE.MeshLambertMaterial({ color: 0x1a1a1a }),
    bodyGeo: new THREE.BoxGeometry(1.75, 1.35, 4.2),
    cabinGeo: new THREE.BoxGeometry(1.55, 0.65, 2.0),
    wheelGeo: new THREE.BoxGeometry(0.22, 0.45, 0.55),
  };
}
