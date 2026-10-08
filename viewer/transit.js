/**
 * Runtime trams + buses on De Lijn / OSM transit paths.
 * Line numbers shown as canvas sprites above each vehicle.
 */

const TRAM_COUNT = 6;
const BUS_COUNT = 8;
const TRAM_SPEED = 7.5;
const BUS_SPEED = 8.5;
const FOLLOW_DIST = 14;
const PLAYER_STOP_DIST = 5;
const SNAP_M = 14;

function blenderToThree(x, y, out) {
  out.set(x, 0, -y);
  return out;
}

function buildPaths(rawPaths, THREE, modeFilter) {
  const paths = [];
  for (const path of rawPaths) {
    const mode = path.mode || "bus";
    if (modeFilter && !modeFilter.has(mode)) continue;
    const pts = path.points || [];
    if (pts.length < 2) continue;
    const points = [];
    for (const p of pts) {
      points.push(blenderToThree(p[0], p[1], new THREE.Vector3()));
    }
    const cleaned = [points[0]];
    for (let i = 1; i < points.length; i++) {
      if (cleaned[cleaned.length - 1].distanceToSquared(points[i]) > 0.05) {
        cleaned.push(points[i]);
      }
    }
    if (cleaned.length < 2) continue;
    const cumulative = [0];
    let len = 0;
    for (let i = 1; i < cleaned.length; i++) {
      len += cleaned[i].distanceTo(cleaned[i - 1]);
      cumulative.push(len);
    }
    if (len < 8) continue;
    paths.push({
      id: path.id,
      mode,
      lines: path.lines || [],
      points: cleaned,
      cumulative,
      length: len,
      start: cleaned[0],
      end: cleaned[cleaned.length - 1],
    });
  }
  return paths;
}

function samplePath(path, s, THREE, outPos, outTan) {
  const dist = Math.max(0, Math.min(path.length, s));
  const cum = path.cumulative;
  let i = 1;
  while (i < cum.length && cum[i] < dist) i++;
  const i0 = Math.max(0, i - 1);
  const i1 = Math.min(path.points.length - 1, i);
  const segStart = cum[i0];
  const segLen = Math.max(1e-6, cum[i1] - segStart);
  const t = (dist - segStart) / segLen;
  const a = path.points[i0];
  const b = path.points[i1];
  outPos.lerpVectors(a, b, t);
  outTan.subVectors(b, a);
  if (outTan.lengthSq() < 1e-8) {
    outTan.set(1, 0, 0);
  } else {
    outTan.normalize();
  }
}

function lineLabel(lines, mode) {
  if (lines && lines.length) return String(lines[0]);
  return mode === "bus" ? "bus" : "tram";
}

function makeLineSprite(THREE, text, mode) {
  const canvas = document.createElement("canvas");
  canvas.width = 128;
  canvas.height = 64;
  const ctx = canvas.getContext("2d");
  const bg = mode === "bus" ? "#1f6fb2" : "#e09a20";
  ctx.fillStyle = bg;
  ctx.fillRect(8, 10, 112, 44);
  ctx.fillStyle = "#ffffff";
  ctx.font = "bold 28px system-ui, sans-serif";
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  ctx.fillText(text.slice(0, 8), 64, 32);
  const tex = new THREE.CanvasTexture(canvas);
  tex.needsUpdate = true;
  const mat = new THREE.SpriteMaterial({ map: tex, transparent: true, depthTest: true });
  const sprite = new THREE.Sprite(mat);
  sprite.scale.set(3.2, 1.6, 1);
  sprite.position.y = 3.4;
  return { sprite, tex, mat };
}

function makeTramMesh(THREE, parts) {
  const group = new THREE.Group();
  const body = new THREE.Mesh(parts.tramBody, parts.tramMat);
  const cabin = new THREE.Mesh(parts.tramCabin, parts.glassMat);
  cabin.position.set(0, 0.85, 0.2);
  const panto = new THREE.Mesh(parts.pantoGeo, parts.metalMat);
  panto.position.set(0, 1.55, 0);
  group.add(body, cabin, panto);
  return group;
}

function makeBusMesh(THREE, parts) {
  const group = new THREE.Group();
  const body = new THREE.Mesh(parts.busBody, parts.busMat);
  const cabin = new THREE.Mesh(parts.busCabin, parts.glassMat);
  cabin.position.set(0, 0.95, 0.4);
  group.add(body, cabin);
  return group;
}

function makeSharedParts(THREE) {
  return {
    tramBody: new THREE.BoxGeometry(2.2, 2.2, 10.5),
    tramCabin: new THREE.BoxGeometry(2.0, 0.7, 4.5),
    pantoGeo: new THREE.BoxGeometry(0.15, 0.7, 1.2),
    busBody: new THREE.BoxGeometry(2.4, 2.6, 9.0),
    busCabin: new THREE.BoxGeometry(2.2, 0.75, 3.2),
    glassMat: new THREE.MeshLambertMaterial({ color: 0x88a8c0, transparent: true, opacity: 0.8 }),
    metalMat: new THREE.MeshLambertMaterial({ color: 0x333333 }),
    tramMat: new THREE.MeshLambertMaterial({ color: 0xc45c28 }),
    busMat: new THREE.MeshLambertMaterial({ color: 0xf0e6c8 }),
  };
}

function pickNextPath(paths, path, atEnd, THREE) {
  const tip = atEnd ? path.end : path.start;
  const candidates = [];
  for (let i = 0; i < paths.length; i++) {
    const other = paths[i];
    if (other === path) continue;
    if (other.mode !== path.mode && !(path.mode === "tram" && other.mode === "subway")) continue;
    const dStart = tip.distanceTo(other.start);
    const dEnd = tip.distanceTo(other.end);
    if (dStart < SNAP_M) candidates.push({ index: i, reverse: false, d: dStart });
    if (dEnd < SNAP_M) candidates.push({ index: i, reverse: true, d: dEnd });
  }
  if (!candidates.length) {
    return { index: paths.indexOf(path), reverse: !atEnd ? false : true, flip: true };
  }
  candidates.sort((a, b) => a.d - b.d);
  const pool = candidates.slice(0, Math.min(4, candidates.length));
  return pool[(Math.random() * pool.length) | 0];
}

function createVehicle(paths, THREE, parts, mode) {
  const pool = paths.filter((p) =>
    mode === "tram" ? p.mode === "tram" || p.mode === "subway" : p.mode === "bus",
  );
  const use = pool.length ? pool : paths;
  const indexInUse = (Math.random() * use.length) | 0;
  const path = use[indexInUse];
  const index = paths.indexOf(path);
  const reverse = Math.random() < 0.5;
  const s = Math.random() * path.length * 0.85;
  const mesh = mode === "tram" ? makeTramMesh(THREE, parts) : makeBusMesh(THREE, parts);
  const labelText = lineLabel(path.lines, mode);
  const label = makeLineSprite(THREE, labelText, mode);
  mesh.add(label.sprite);
  const base = mode === "tram" ? TRAM_SPEED : BUS_SPEED;
  return {
    mesh,
    mode,
    pathIndex: index,
    reverse,
    s,
    speed: base * (0.85 + Math.random() * 0.3),
    velocity: base,
    pos: new THREE.Vector3(),
    tan: new THREE.Vector3(),
    label,
    lineText: labelText,
  };
}

function placeVehicle(v, paths, THREE) {
  const path = paths[v.pathIndex];
  if (!path) return;
  const s = v.reverse ? path.length - v.s : v.s;
  samplePath(path, s, THREE, v.pos, v.tan);
  if (v.reverse) v.tan.multiplyScalar(-1);
  // Buses sit slightly off centreline; trams stay on rails.
  if (v.mode === "bus") {
    v.pos.x += v.tan.z * 1.1;
    v.pos.z += -v.tan.x * 1.1;
  }
  // Tram body (2.2 m tall) rides on top of the rails (Z_TRAM_RAIL = 0.18 in build_city.py).
  v.pos.y = v.mode === "tram" ? 1.3 : 1.35;
  v.mesh.position.copy(v.pos);
  v.mesh.rotation.y = Math.atan2(v.tan.x, v.tan.z);
}

/**
 * @param {import('three').Scene} scene
 * @param {typeof import('three')} THREE
 * @param {{ url?: string, tramCount?: number, busCount?: number }} [opts]
 */
export async function createTransit(scene, THREE, opts = {}) {
  const url = opts.url || "./transit.json";
  let data;
  try {
    const res = await fetch(url);
    if (!res.ok) throw new Error(`transit.json ${res.status}`);
    data = await res.json();
  } catch (err) {
    console.warn("Transit disabled — could not load transit.json:", err);
    return { update() {}, dispose() {}, count: 0 };
  }

  const allPaths = buildPaths(data.paths || [], THREE, null);
  const tramPaths = allPaths.filter((p) => p.mode === "tram" || p.mode === "subway");
  const busPaths = allPaths.filter((p) => p.mode === "bus");
  if (allPaths.length < 1) {
    console.warn("Transit disabled — no paths");
    return { update() {}, dispose() {}, count: 0 };
  }

  const root = new THREE.Group();
  root.name = "RuntimeTransit";
  scene.add(root);
  const parts = makeSharedParts(THREE);
  const vehicles = [];

  const tramN = Math.min(opts.tramCount ?? TRAM_COUNT, Math.max(0, tramPaths.length * 2));
  const busN = Math.min(opts.busCount ?? BUS_COUNT, Math.max(0, busPaths.length * 2));

  function spawnFleet(n, mode, pathPool) {
    if (!pathPool.length || n <= 0) return;
    for (let i = 0; i < n; i++) {
      const v = createVehicle(allPaths, THREE, parts, mode);
      let tries = 0;
      while (tries < 12) {
        placeVehicle(v, allPaths, THREE);
        const clash = vehicles.some((o) => o.pos.distanceToSquared(v.pos) < 100);
        if (!clash) break;
        v.pathIndex = allPaths.indexOf(pathPool[(Math.random() * pathPool.length) | 0]);
        v.s = Math.random() * allPaths[v.pathIndex].length * 0.85;
        tries++;
      }
      placeVehicle(v, allPaths, THREE);
      root.add(v.mesh);
      vehicles.push(v);
    }
  }

  spawnFleet(tramN, "tram", tramPaths);
  spawnFleet(busN, "bus", busPaths);

  const playerPos = new THREE.Vector3();

  function advanceJunction(v) {
    const path = allPaths[v.pathIndex];
    const atEnd = !v.reverse;
    const next = pickNextPath(allPaths, path, atEnd, THREE);
    if (next.flip) {
      v.reverse = !v.reverse;
      v.s = 0.5;
      return;
    }
    v.pathIndex = next.index;
    v.reverse = next.reverse;
    v.s = 0.5;
    const np = allPaths[v.pathIndex];
    const nextLabel = lineLabel(np.lines, v.mode);
    if (nextLabel !== v.lineText) {
      v.mesh.remove(v.label.sprite);
      v.label.tex.dispose();
      v.label.mat.dispose();
      v.label = makeLineSprite(THREE, nextLabel, v.mode);
      v.mesh.add(v.label.sprite);
      v.lineText = nextLabel;
    }
  }

  function update(dt, walkObject) {
    if (dt <= 0 || !vehicles.length) return;
    if (walkObject) {
      playerPos.set(walkObject.position.x, 0, walkObject.position.z);
    }
    for (let i = 0; i < vehicles.length; i++) {
      const v = vehicles[i];
      placeVehicle(v, allPaths, THREE);
      let desire = v.speed;

      for (let j = 0; j < vehicles.length; j++) {
        if (i === j) continue;
        const other = vehicles[j];
        const dx = other.pos.x - v.pos.x;
        const dz = other.pos.z - v.pos.z;
        const distSq = dx * dx + dz * dz;
        if (distSq > FOLLOW_DIST * FOLLOW_DIST * 3) continue;
        const ahead = dx * v.tan.x + dz * v.tan.z;
        const side = Math.abs(dx * v.tan.z + dz * -v.tan.x);
        if (ahead > 0.5 && ahead < FOLLOW_DIST + 6 && side < 3.5) {
          const gap = ahead - 5;
          if (gap < FOLLOW_DIST) {
            desire = Math.min(desire, v.speed * Math.max(0, gap / FOLLOW_DIST) ** 2);
          }
        }
      }

      if (walkObject) {
        const dx = playerPos.x - v.pos.x;
        const dz = playerPos.z - v.pos.z;
        if (dx * dx + dz * dz < (PLAYER_STOP_DIST + 8) ** 2) {
          const ahead = dx * v.tan.x + dz * v.tan.z;
          const side = Math.abs(dx * v.tan.z + dz * -v.tan.x);
          if (ahead > 0.2 && ahead < PLAYER_STOP_DIST + 6 && side < 3) {
            const gap = ahead - 1.5;
            desire = Math.min(desire, v.speed * Math.max(0, gap / PLAYER_STOP_DIST) ** 2);
          }
        }
      }

      v.velocity += (desire - v.velocity) * Math.min(1, dt * 3);
      if (v.velocity < 0.12) v.velocity = 0;
      v.s += v.velocity * dt;
      const path = allPaths[v.pathIndex];
      if (path && v.s >= path.length - 0.5) {
        advanceJunction(v);
      }
      placeVehicle(v, allPaths, THREE);
    }
  }

  function dispose() {
    scene.remove(root);
    for (const v of vehicles) {
      v.label.tex.dispose();
      v.label.mat.dispose();
    }
    parts.tramBody.dispose();
    parts.tramCabin.dispose();
    parts.pantoGeo.dispose();
    parts.busBody.dispose();
    parts.busCabin.dispose();
    parts.glassMat.dispose();
    parts.metalMat.dispose();
    parts.tramMat.dispose();
    parts.busMat.dispose();
  }

  return {
    update,
    dispose,
    count: vehicles.length,
    pathCount: allPaths.length,
    stopCount: (data.stops || []).length,
  };
}
