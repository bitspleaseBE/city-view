/**
 * GTA-style cash pickups: a spinning bundle of banknotes dropped where a pedestrian died.
 * Walk or ride through it to pocket the money.
 */

const PICKUP_R = 1.1; // m, horizontal
const LIFETIME_S = 120;
const HOVER_Y = 0.3;

/**
 * Euros in a dead pedestrian's pockets: €5–500, averaging €15. Mostly small change, with the
 * odd fat wallet (2%, log-uniform €50–500).
 */
export function cashAmount() {
  if (Math.random() < 0.02) return Math.round(50 * 10 ** Math.random());
  return Math.min(500, Math.round(5 - 6.3 * Math.log(1 - Math.random())));
}

function noteTexture(THREE) {
  const c = document.createElement("canvas");
  c.width = 128;
  c.height = 64;
  const g = c.getContext("2d");
  const grad = g.createLinearGradient(0, 0, 128, 64);
  grad.addColorStop(0, "#5fb86a");
  grad.addColorStop(1, "#2f7d3e");
  g.fillStyle = grad;
  g.fillRect(0, 0, 128, 64);
  g.strokeStyle = "rgba(230,255,220,0.7)";
  g.lineWidth = 3;
  g.strokeRect(5, 5, 118, 54);
  g.fillStyle = "#eaffe0";
  g.font = "bold 40px Helvetica, Arial, sans-serif";
  g.textAlign = "center";
  g.textBaseline = "middle";
  g.fillText("€", 64, 34);
  const tex = new THREE.CanvasTexture(c);
  tex.colorSpace = THREE.SRGBColorSpace;
  return tex;
}

export function createCashDrops(scene, THREE) {
  const root = new THREE.Group();
  root.name = "CashDrops";
  scene.add(root);

  const noteGeo = new THREE.BoxGeometry(0.24, 0.012, 0.12);
  const bandGeo = new THREE.BoxGeometry(0.035, 0.05, 0.126);
  const face = new THREE.MeshStandardMaterial({
    map: noteTexture(THREE),
    emissive: 0x2a7a34,
    emissiveIntensity: 0.55, // still readable at night
    roughness: 0.8,
  });
  const edge = new THREE.MeshStandardMaterial({ color: 0x9fd8a0, emissive: 0x2a7a34, emissiveIntensity: 0.4 });
  const noteMats = [edge, edge, face, face, edge, edge];
  const band = new THREE.MeshStandardMaterial({ color: 0xf2e7c4, emissive: 0x504830, emissiveIntensity: 0.4 });

  function makeBundle() {
    const g = new THREE.Group();
    for (let i = 0; i < 4; i++) {
      const n = new THREE.Mesh(noteGeo, noteMats);
      n.position.y = i * 0.013;
      n.rotation.y = (Math.random() - 0.5) * 0.25;
      n.castShadow = true;
      g.add(n);
    }
    const b = new THREE.Mesh(bandGeo, band);
    b.position.y = 0.02;
    g.add(b);
    return g;
  }

  const drops = [];
  let clock = 0;

  /** Leave `amount` euros lying at x/z, `y` being the ground there. */
  function drop(x, y, z, amount) {
    const mesh = makeBundle();
    mesh.position.set(x, y + HOVER_Y, z);
    mesh.rotation.y = Math.random() * Math.PI * 2;
    root.add(mesh);
    drops.push({ mesh, amount, groundY: y, age: 0, phase: Math.random() * Math.PI * 2 });
  }

  /** Spin and bob the pickups; returns the euros picked up by a player at px/pz this frame. */
  function update(dt, px, pz) {
    clock += dt;
    let got = 0;
    for (let i = drops.length - 1; i >= 0; i--) {
      const d = drops[i];
      d.age += dt;
      const m = d.mesh;
      m.rotation.y += dt * 2.4;
      m.position.y = d.groundY + HOVER_Y + Math.sin(clock * 3 + d.phase) * 0.05;
      const near = (m.position.x - px) ** 2 + (m.position.z - pz) ** 2 < PICKUP_R * PICKUP_R;
      if (near || d.age > LIFETIME_S) {
        if (near) got += d.amount;
        root.remove(m);
        drops.splice(i, 1);
      }
    }
    return got;
  }

  function dispose() {
    scene.remove(root);
    noteGeo.dispose();
    bandGeo.dispose();
    face.map.dispose();
    for (const m of [face, edge, band]) m.dispose();
  }

  return {
    drop,
    update,
    dispose,
    get count() {
      return drops.length;
    },
  };
}
