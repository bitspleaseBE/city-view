/**
 * Café terraces in front of horeca shopfronts flagged `terrace` in shops.json: bistro tables,
 * two chairs each and a parasol per pair of tables. Everything is instanced (a handful of draw
 * calls for the whole city) and only set out while the place is open.
 */

const TABLE_DEPTH = 1.55; // m in front of the façade
const TABLE_STEP = 1.75; // m between tables along the façade
const MAX_TABLES = 4;
const PARASOLS = [0xb3262b, 0xf1e6cf, 0x2f5d3a, 0x1f3352, 0x8a1c45, 0xe0e0dc];

function hash(n) {
  let h = (n ^ 0x9e3779b9) >>> 0;
  h = Math.imul(h ^ (h >>> 16), 0x85ebca6b) >>> 0;
  h = Math.imul(h ^ (h >>> 13), 0xc2b2ae35) >>> 0;
  return ((h ^ (h >>> 16)) >>> 0) / 4294967296;
}

/** records: shop records from createShops (fx, fz, nx, nz, gy, w, terrace, open). */
export function createTerraces(scene, THREE, records, opts = {}) {
  const groundAt = opts.groundAt || (() => NaN);
  const sites = [];
  for (const r of records) {
    if (!r.terrace) continue;
    const tx = r.nz;
    const tz = -r.nx;
    const n = Math.max(1, Math.min(MAX_TABLES, Math.floor((r.w - 0.4) / TABLE_STEP)));
    const tables = [];
    for (let i = 0; i < n; i++) {
      const a = (i - (n - 1) / 2) * TABLE_STEP;
      const x = r.fx + r.nx * TABLE_DEPTH + tx * a;
      const z = r.fz + r.nz * TABLE_DEPTH + tz * a;
      // Stay on the footway: the chairs' far edge must be level with the table, not down a kerb.
      const h0 = groundAt(x, z);
      const h1 = groundAt(x + r.nx * 0.6, z + r.nz * 0.6);
      const gy = Number.isFinite(h0) ? h0 : r.gy;
      if (Number.isFinite(h1) && Math.abs(h1 - gy) > 0.06) continue;
      if (Math.abs(gy - r.gy) > 0.35) continue;
      tables.push({ x, z, gy, a });
    }
    if (!tables.length) continue;
    sites.push({ r, tables, tx, tz, colour: PARASOLS[Math.floor(hash(r.id) * PARASOLS.length)] });
  }
  const nTables = sites.reduce((s, x) => s + x.tables.length, 0);
  const nParasols = sites.reduce((s, x) => s + Math.ceil(x.tables.length / 2), 0);
  if (!nTables) return null;

  const metal = new THREE.MeshStandardMaterial({ color: 0x2a2b2d, roughness: 0.45, metalness: 0.7 });
  const top = new THREE.MeshStandardMaterial({ color: 0xd9d4ca, roughness: 0.5, metalness: 0.1 });
  const rattan = new THREE.MeshStandardMaterial({ color: 0x8a6440, roughness: 0.85 });
  const cloth = new THREE.MeshStandardMaterial({ color: 0xffffff, roughness: 0.9, side: THREE.DoubleSide });

  const parts = [
    { geo: new THREE.CylinderGeometry(0.34, 0.34, 0.03, 18), mat: top, per: "table", y: 0.74 },
    { geo: new THREE.CylinderGeometry(0.025, 0.025, 0.72, 6), mat: metal, per: "table", y: 0.37 },
    { geo: new THREE.CylinderGeometry(0.2, 0.22, 0.02, 12), mat: metal, per: "table", y: 0.01 },
    { geo: new THREE.BoxGeometry(0.42, 0.05, 0.42), mat: rattan, per: "chair", y: 0.46 },
    { geo: new THREE.BoxGeometry(0.42, 0.44, 0.04), mat: rattan, per: "chair", y: 0.7, back: 0.2 },
    { geo: new THREE.BoxGeometry(0.38, 0.45, 0.38), mat: metal, per: "chair", y: 0.22, legs: true },
    { geo: new THREE.CylinderGeometry(0.025, 0.025, 2.3, 6), mat: metal, per: "parasol", y: 1.15 },
    { geo: new THREE.ConeGeometry(1.25, 0.42, 8, 1, true), mat: cloth, per: "parasol", y: 2.2, cloth: true },
  ];
  // Chair legs as an open frame: just the four corner posts of the box.
  {
    const legs = new THREE.BufferGeometry();
    const leg = new THREE.BoxGeometry(0.03, 0.45, 0.03);
    const pos = [];
    const idx = [];
    for (const [lx, lz] of [[-0.18, -0.18], [0.18, -0.18], [-0.18, 0.18], [0.18, 0.18]]) {
      const base = pos.length / 3;
      const p = leg.attributes.position.array;
      for (let k = 0; k < p.length; k += 3) pos.push(p[k] + lx, p[k + 1], p[k + 2] + lz);
      for (const i of leg.index.array) idx.push(base + i);
    }
    legs.setAttribute("position", new THREE.Float32BufferAttribute(pos, 3));
    legs.setIndex(idx);
    legs.computeVertexNormals();
    parts[5].geo = legs;
  }

  const counts = { table: nTables, chair: nTables * 2, parasol: nParasols };
  const meshes = parts.map((p) => {
    const m = new THREE.InstancedMesh(p.geo, p.mat, counts[p.per]);
    m.name = `terrace_${p.per}`;
    m.castShadow = p.per !== "chair" || !p.legs;
    m.receiveShadow = true;
    m.frustumCulled = false;
    scene.add(m);
    return m;
  });
  const clothMesh = meshes[parts.findIndex((p) => p.cloth)];
  const colour = new THREE.Color();

  const m4 = new THREE.Matrix4();
  const q = new THREE.Quaternion();
  const s1 = new THREE.Vector3(1, 1, 1);
  const s0 = new THREE.Vector3(0, 0, 0);
  const v = new THREE.Vector3();
  const up = new THREE.Vector3(0, 1, 0);

  const solids = [];
  function layout() {
    const slot = { table: 0, chair: 0, parasol: 0 };
    solids.length = 0;
    for (const site of sites) {
      const out = site.r.open === true;
      if (out) for (const t of site.tables) solids.push([t.x, t.z, 0.75]);
      const yaw = Math.atan2(site.r.nx, site.r.nz);
      site.tables.forEach((t, i) => {
        const jit = (hash(site.r.id * 31 + i) - 0.5) * 0.5;
        for (let p = 0; p < parts.length; p++) {
          const part = parts[p];
          if (part.per === "table") {
            q.setFromAxisAngle(up, yaw);
            v.set(t.x, t.gy + part.y, t.z);
            meshes[p].setMatrixAt(slot.table, m4.compose(v, q, out ? s1 : s0));
          } else if (part.per === "chair") {
            for (let c = 0; c < 2; c++) {
              // Chairs either side of the table along the façade, facing it (and half the street).
              const side = c ? 1 : -1;
              const cyaw = yaw - side * (Math.PI / 2) + jit;
              q.setFromAxisAngle(up, cyaw);
              const off = part.back ? 0.2 : 0;
              const dx = Math.sin(cyaw) * off;
              const dz = Math.cos(cyaw) * off;
              v.set(t.x + site.tx * side * 0.55 - dx, t.gy + part.y, t.z + site.tz * side * 0.55 - dz);
              meshes[p].setMatrixAt(slot.chair + c, m4.compose(v, q, out ? s1 : s0));
            }
          } else if (i % 2 === 0) {
            const pair = site.tables[i + 1];
            const px = pair ? (t.x + pair.x) / 2 : t.x;
            const pz = pair ? (t.z + pair.z) / 2 : t.z;
            q.identity();
            v.set(px, t.gy + part.y, pz);
            meshes[p].setMatrixAt(slot.parasol, m4.compose(v, q, out ? s1 : s0));
          }
        }
        slot.table++;
        slot.chair += 2;
        if (i % 2 === 0) slot.parasol++;
      });
    }
    for (const m of meshes) m.instanceMatrix.needsUpdate = true;
  }

  {
    let k = 0;
    for (const site of sites) {
      colour.setHex(site.colour);
      for (let i = 0; i < site.tables.length; i += 2) clothMesh.setColorAt(k++, colour);
    }
    clothMesh.instanceColor.needsUpdate = true;
  }

  let lastKey = "";
  layout();
  return {
    count: nTables,
    /** Open tables (with their chairs) for player collision: [x, z, radius] in viewer space. */
    solids,
    /** Call after shops.update(); re-lays out only when a terrace opens or closes. */
    update() {
      let key = "";
      for (const site of sites) key += site.r.open ? "1" : "0";
      if (key === lastKey) return;
      lastKey = key;
      layout();
    },
  };
}
