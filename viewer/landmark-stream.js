/**
 * One-off landmark GLBs load only while the camera is near them.
 *
 * Walking (and riding) loads inside 220 m and unloads past 310 m, so a
 * boundary doesn't thrash. Free view zoomed out far enough to see the
 * district keeps every landmark visible; zoom back in and the walk radii
 * apply again.
 */

export const LOAD_M = 220;
export const UNLOAD_M = 310;
export const OVERVIEW_ON = 190;
export const OVERVIEW_OFF = 130;

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
      const name = obj.name || "";
      if (name.startsWith("lmhold_")) holds.set(name.slice("lmhold_".length), obj);
    });
  }
  const resident = new Map();
  let overview = false;

  function setHold(id, visible) {
    const hold = holds.get(String(id));
    if (hold) hold.visible = visible;
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
