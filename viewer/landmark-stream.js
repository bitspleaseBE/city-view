/**
 * One-off landmark GLBs load only while the camera is near them.
 *
 * Paths are relative to the page (`landmarks/<id>.glb`, `landmarks.json`),
 * which is what GitHub Pages serves at /metropolis/.
 *
 * Walking (and riding) loads inside 300 m and unloads past 420 m, so a
 * boundary doesn't thrash. From Halte Gounod that covers Heilige Geestkerk,
 * Mechelsesteenweg 123, the Peter Benoitstraat houses, Vincentius, and
 * Harmoniestraat 24. Free view zoomed out far enough to see the district
 * keeps every landmark visible; zoom back in and the walk radii apply again.
 *
 * Until a GLB arrives the city keeps the ordinary building (`lmbase_<id>`)
 * or, on older city files, the knee-high plinth (`lmhold_<id>`). The stand-in
 * hides once the detailed mesh is in the scene and comes back when it unloads.
 */

export const LOAD_M = 300;
export const UNLOAD_M = 420;
export const OVERVIEW_ON = 190;
export const OVERVIEW_OFF = 130;

/** OSM id from a city-GLB stand-in. Parts are `lmbase_<id>_roof`, `lmhold_<id>`, … */
export function standinKey(name) {
  const m = /^(?:lmbase_|lmhold_)(\d+)/.exec(String(name || ""));
  return m ? m[1] : null;
}

/** Latched "show the whole district" flag for free view. Walking clears it. */
export function overviewLatched(mode, height, overview) {
  if (mode !== "free") return false;
  if (height >= OVERVIEW_ON) return true;
  if (height <= OVERVIEW_OFF) return false;
  return !!overview;
}

/** Whether this landmark should be resident, given the latched overview flag. */
export function landmarkWanted(ctx, item) {
  if (ctx.overview) return true;
  const dist = Math.hypot(ctx.x - item.x, ctx.z - item.z);
  return dist <= (ctx.loaded ? UNLOAD_M : LOAD_M);
}

function disposeObject(root) {
  root.traverse((obj) => {
    if (obj.geometry) obj.geometry.dispose();
    const mats = obj.material == null ? [] : Array.isArray(obj.material) ? obj.material : [obj.material];
    for (const mat of mats) {
      if (!mat) continue;
      for (const key of Object.keys(mat)) {
        const value = mat[key];
        if (value && value.isTexture) value.dispose();
      }
      mat.dispose();
    }
  });
  root.removeFromParent();
}

export function createLandmarkStream({ scene, loader, cityRoot, catalog }) {
  const items = (catalog.landmarks || [])
    .filter((p) => p.file && Number.isFinite(Number(p.x)) && Number.isFinite(Number(p.y)))
    .map((p) => ({
      id: String(p.id),
      file: String(p.file),
      x: Number(p.x),
      z: -Number(p.y),
    }));
  const holds = new Map();
  if (cityRoot) {
    cityRoot.traverse((obj) => {
      const id = standinKey(obj.name || "");
      if (!id) return;
      const list = holds.get(id);
      if (list) list.push(obj);
      else holds.set(id, [obj]);
    });
  }
  const resident = new Map();
  let overview = false;

  function setHold(id, visible) {
    const list = holds.get(String(id));
    if (!list) return;
    for (const obj of list) obj.visible = visible;
  }

  function entry(id) {
    let st = resident.get(id);
    if (!st) {
      st = { gen: 0, group: null, loading: false, failed: false };
      resident.set(id, st);
    }
    return st;
  }

  async function loadOne(item) {
    const st = entry(item.id);
    if (st.group || st.loading || st.failed) return;
    const gen = st.gen;
    st.loading = true;
    try {
      const gltf = await loader.loadAsync(item.file);
      if (st.gen !== gen) {
        disposeObject(gltf.scene);
        st.loading = false;
        return;
      }
      const group = gltf.scene;
      group.name = `stream_${item.id}`;
      group.traverse((obj) => {
        if (obj.isMesh) {
          obj.castShadow = false;
          obj.receiveShadow = false;
          obj.frustumCulled = true;
        }
      });
      scene.add(group);
      st.group = group;
      st.loading = false;
      setHold(item.id, false);
    } catch (err) {
      st.loading = false;
      if (st.gen === gen) st.failed = true;
      console.warn("[cityview] landmark", item.file, err);
    }
  }

  function unloadOne(item) {
    const st = entry(item.id);
    st.gen += 1;
    st.loading = false;
    if (st.group) {
      disposeObject(st.group);
      st.group = null;
      setHold(item.id, true);
    }
  }

  function update(x, z, mode, height) {
    overview = overviewLatched(mode, height, overview);
    for (const item of items) {
      const st = resident.get(item.id);
      const loaded = !!(st && st.group);
      const want = landmarkWanted({ x, z, overview, loaded }, item);
      if (want) loadOne(item);
      else if (loaded || (st && st.loading)) unloadOne(item);
    }
  }

  function prime(x, z) {
    const near = items.filter((item) => Math.hypot(item.x - x, item.z - z) <= LOAD_M);
    return Promise.all(near.map((item) => loadOne(item)));
  }

  return { update, prime, items };
}
