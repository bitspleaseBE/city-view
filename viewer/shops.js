/**
 * Shopfronts from OpenStreetMap (shops.json, written by cityview.shops): a named fascia
 * board over the ground floor, a hanging blade sign with the category icon, and a warm
 * light pool on the pavement. Signs light up while the place is open (opening_hours, or a
 * typical schedule for the category) and the light pool shows after dusk.
 *
 * Positions are Blender XY on the façade line → Three XZ with z = −y. Everything is baked
 * into three meshes sharing one canvas atlas, so ~130 shops cost three draw calls.
 */

const URL_SHOPS = "./shops.json";
const ATLAS_W = 2048;
const ATLAS_H = 2304; // was 4096; lower rows were unused ~half the GPU upload
const SLOT_W = 512;
const SLOT_H = 64;
const COLS = ATLAS_W / SLOT_W;
const ICON = 128;
const FASCIA_Y = 3.22; // centre height above the pavement (between shop window and 1st floor)
const FASCIA_H = 0.5;
const FASCIA_OUT = 0.24; // in front of the façade, clear of the window reveals
const FRONT_OUT = 0.14; // ground-floor shopfront panel, just proud of the wall
const FRONT_H = 2.85; // kerb to fascia underside
const BLADE = 0.62;
const POOL_DEPTH = 3.2;
const REACH = 7; // m: "what's this shop" prompt range
const DAY = ["Su", "Mo", "Tu", "We", "Th", "Fr", "Sa"];

const STYLE = {
  food: { bg: ["#1f4d36", "#5a2e1a", "#24323f"], fg: "#f3e6c4", serif: true },
  // Hipster Antwerp: oxblood, forest, charcoal, teal — cream / brass lettering
  horeca: { bg: ["#5b1a26", "#1d2a24", "#2a221c", "#1a3a3e"], fg: "#f0c66b", serif: true },
  retail: { bg: ["#1b2844", "#2c2c30", "#41213b"], fg: "#ffffff", serif: false },
  service: { bg: ["#24292e", "#13443f", "#3a3f46"], fg: "#7fe0d3", serif: false },
  pharmacy: { bg: ["#f6f7f5"], fg: "#0c8a3e", serif: false },
  care: { bg: ["#f4f6f9"], fg: "#1d5fae", serif: false },
};

function rgbCss(rgb, fallback = "#222") {
  if (!rgb || rgb.length < 3) return fallback;
  const h = (c) => Math.max(0, Math.min(255, Math.round(c * 255))).toString(16).padStart(2, "0");
  return `#${h(rgb[0])}${h(rgb[1])}${h(rgb[2])}`;
}
const ICONS = ["food", "horeca", "retail", "service", "pharmacy", "care"];

function hash(n) {
  let h = (n ^ 0x9e3779b9) >>> 0;
  h = Math.imul(h ^ (h >>> 16), 0x85ebca6b) >>> 0;
  return ((h ^ (h >>> 13)) >>> 0) / 4294967296;
}

function prettyKind(kind) {
  const EN = {
    bakery: "Bakery", butcher: "Butcher", greengrocer: "Greengrocer", pharmacy: "Pharmacy",
    hairdresser: "Hairdresser", cafe: "Café", pub: "Pub", bar: "Bar", restaurant: "Restaurant",
    fast_food: "Fast food", supermarket: "Supermarket", convenience: "Convenience", bank: "Bank",
    florist: "Florist", bicycle: "Bike shop", dentist: "Dentist", doctors: "Doctor",
    veterinary: "Vet", beauty: "Beauty", clothes: "Clothes", furniture: "Furniture",
    copyshop: "Copy shop", optician: "Optician", laundry: "Laundry", books: "Books",
  };
  return EN[kind] || kind.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase());
}

function drawIcon(ctx, cat, x, y, s, st) {
  const c = s / 2;
  ctx.save();
  ctx.translate(x, y);
  ctx.fillStyle = st.bg[0];
  ctx.beginPath();
  ctx.roundRect(4, 4, s - 8, s - 8, 18);
  ctx.fill();
  ctx.strokeStyle = st.fg;
  ctx.lineWidth = 5;
  ctx.stroke();
  ctx.fillStyle = st.fg;
  ctx.strokeStyle = st.fg;
  ctx.lineWidth = 7;
  ctx.lineCap = "round";
  if (cat === "pharmacy" || cat === "care") {
    const a = s * 0.13;
    const b = s * 0.34;
    ctx.fillRect(c - a, c - b, a * 2, b * 2);
    ctx.fillRect(c - b, c - a, b * 2, a * 2);
  } else if (cat === "horeca") {
    // Beer / coffee cup with steam.
    ctx.fillRect(c - 24, c - 8, 38, 36);
    ctx.beginPath();
    ctx.arc(c + 18, c + 9, 11, -Math.PI / 2, Math.PI / 2);
    ctx.stroke();
    for (const dx of [-14, 0]) {
      ctx.beginPath();
      ctx.moveTo(c - 5 + dx, c - 16);
      ctx.quadraticCurveTo(c + 3 + dx, c - 26, c - 5 + dx, c - 36);
      ctx.stroke();
    }
  } else if (cat === "food") {
    // Basket.
    ctx.beginPath();
    ctx.moveTo(c - 34, c - 2);
    ctx.lineTo(c + 34, c - 2);
    ctx.lineTo(c + 24, c + 32);
    ctx.lineTo(c - 24, c + 32);
    ctx.closePath();
    ctx.fill();
    ctx.beginPath();
    ctx.arc(c, c - 2, 24, Math.PI, 0);
    ctx.stroke();
  } else if (cat === "service") {
    // Scissors.
    ctx.lineWidth = 6;
    for (const sx of [-1, 1]) {
      ctx.beginPath();
      ctx.arc(c + sx * 16, c + 22, 11, 0, Math.PI * 2);
      ctx.stroke();
      ctx.beginPath();
      ctx.moveTo(c + sx * 11, c + 12);
      ctx.lineTo(c - sx * 18, c - 34);
      ctx.stroke();
    }
  } else {
    // Shopping bag.
    ctx.fillRect(c - 26, c - 10, 52, 44);
    ctx.beginPath();
    ctx.arc(c, c - 10, 16, Math.PI, 0);
    ctx.stroke();
  }
  ctx.restore();
}

function drawFascia(ctx, shop, sx, sy, aspect) {
  const st = STYLE[shop.cat] || STYLE.retail;
  const branded = shop.fascia && shop.fascia.length >= 3;
  const bg = branded ? rgbCss(shop.fascia) : st.bg[Math.floor(hash(shop.id) * st.bg.length)];
  const fg = branded ? rgbCss(shop.accent, st.fg) : st.fg;
  ctx.fillStyle = bg;
  ctx.fillRect(sx, sy, SLOT_W, SLOT_H);
  ctx.strokeStyle = fg;
  ctx.globalAlpha = shop.mood === "bank" ? 0.35 : 0.55;
  ctx.lineWidth = 2;
  ctx.strokeRect(sx + 3, sy + 3, SLOT_W - 6, SLOT_H - 6);
  ctx.globalAlpha = 1;
  // The slot is stretched to the board's real aspect; pre-squash so letters stay upright.
  const squash = (SLOT_W / SLOT_H) / aspect;
  const label = (shop.name || prettyKind(shop.kind)).toUpperCase();
  const serif = st.serif || shop.mood === "cafe";
  const font = serif ? "Georgia, 'Times New Roman', serif" : "'Avenir Next', 'Helvetica Neue', Arial, sans-serif";
  ctx.save();
  ctx.translate(sx + SLOT_W / 2, sy + SLOT_H / 2 + 1);
  ctx.scale(squash, 1);
  let size = shop.mood === "bank" ? 34 : 38;
  ctx.font = `700 ${size}px ${font}`;
  const maxW = (SLOT_W - 26) / squash;
  const w = ctx.measureText(label).width;
  if (w > maxW) {
    size = Math.max(18, Math.floor(size * (maxW / w)));
    ctx.font = `700 ${size}px ${font}`;
  }
  ctx.fillStyle = fg;
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  ctx.fillText(label, 0, 0, maxW);
  ctx.restore();
}

/** Open at game hour h on day d (0 = Sunday)? Spans may run past midnight (close > 24). */
export function isOpen(hours, d, h) {
  if (!hours) return false;
  for (const [o, c] of hours[d] || []) if (h >= o && h < c) return true;
  const prev = hours[(d + 6) % 7] || [];
  for (const [o, c] of prev) if (c > 24 && h < c - 24 && h + 24 >= o) return true;
  return false;
}

function fmt(h) {
  const hh = Math.floor(h) % 24;
  const mm = Math.round((h % 1) * 60);
  return `${String(hh).padStart(2, "0")}:${String(mm).padStart(2, "0")}`;
}

export function hoursLine(hours, d, h) {
  if (isOpen(hours, d, h)) {
    for (const [o, c] of hours[d] || []) if (h >= o && h < c) return `Open · until ${fmt(c)}`;
    for (const [, c] of hours[(d + 6) % 7] || []) if (c > 24) return `Open · until ${fmt(c)}`;
    return "Open";
  }
  for (let k = 0; k < 7; k++) {
    const day = (d + k) % 7;
    for (const [o] of hours[day] || []) {
      if (k > 0 || o > h) {
        const when = k === 0 ? "" : k === 1 ? "tomorrow " : `${DAY[day]} `;
        return `Closed · opens ${when}${fmt(o)}`;
      }
    }
  }
  return "Closed";
}

function poolTexture(THREE) {
  const c = document.createElement("canvas");
  c.width = 128;
  c.height = 128;
  const g = c.getContext("2d");
  const grad = g.createRadialGradient(64, 20, 4, 64, 40, 92);
  grad.addColorStop(0, "rgba(255,255,255,1)");
  grad.addColorStop(0.45, "rgba(255,255,255,0.45)");
  grad.addColorStop(1, "rgba(255,255,255,0)");
  g.fillStyle = grad;
  g.fillRect(0, 0, 128, 128);
  // Fade the sides out too, so neighbouring pools never show a hard seam.
  const side = g.createLinearGradient(0, 0, 128, 0);
  side.addColorStop(0, "rgba(0,0,0,0)");
  side.addColorStop(0.28, "rgba(0,0,0,1)");
  side.addColorStop(0.72, "rgba(0,0,0,1)");
  side.addColorStop(1, "rgba(0,0,0,0)");
  g.globalCompositeOperation = "destination-in";
  g.fillStyle = side;
  g.fillRect(0, 0, 128, 128);
  const tex = new THREE.CanvasTexture(c);
  tex.colorSpace = THREE.SRGBColorSpace;
  return tex;
}

export async function createShops(scene, THREE, opts = {}) {
  let data;
  try {
    const res = await fetch(URL_SHOPS);
    if (!res.ok) throw new Error(String(res.status));
    data = await res.json();
  } catch (err) {
    console.warn("shops.json unavailable", err);
    return null;
  }
  const shops = (data.shops || []).slice(0, COLS * Math.floor((ATLAS_H - ICON * 2) / SLOT_H));
  const groundAt = opts.groundAt || (() => 0);

  const canvas = document.createElement("canvas");
  canvas.width = ATLAS_W;
  canvas.height = ATLAS_H;
  const ctx = canvas.getContext("2d");
  const iconY = ATLAS_H - ICON;
  ICONS.forEach((cat, i) => drawIcon(ctx, cat, i * ICON, iconY, ICON, STYLE[cat]));

  const fasciaPos = [];
  const fasciaUv = [];
  const fasciaLit = [];
  const fasciaIdx = [];
  const frontPos = [];
  const frontCol = [];
  const frontIdx = [];
  const poolPos = [];
  const poolUv = [];
  const poolCol = [];
  const poolIdx = [];
  const records = [];

  const quad = (pos, uv, idx, lit, corners, uvRect, litVal) => {
    const base = pos.length / 3;
    for (const p of corners) pos.push(p.x, p.y, p.z);
    const [u0, v0, u1, v1] = uvRect;
    uv.push(u0, v0, u1, v0, u1, v1, u0, v1);
    if (lit) for (let k = 0; k < 4; k++) lit.push(litVal);
    idx.push(base, base + 1, base + 2, base, base + 2, base + 3);
    return base;
  };
  const uvOf = (px, py, w, h) => [px / ATLAS_W, 1 - (py + h) / ATLAS_H, (px + w) / ATLAS_W, 1 - py / ATLAS_H];
  const V = (x, y, z) => new THREE.Vector3(x, y, z);

  shops.forEach((shop, i) => {
    const sx = (i % COLS) * SLOT_W;
    const sy = Math.floor(i / COLS) * SLOT_H;
    drawFascia(ctx, shop, sx, sy, shop.w / FASCIA_H);
    const fx = shop.x;
    const fz = -shop.y;
    const nx = shop.nx;
    const nz = -shop.ny;
    // Viewer's right-hand direction when facing the façade, so text reads left→right.
    const tx = nz;
    const tz = -nx;
    const g = groundAt(fx + nx * 1.2, fz + nz * 1.2);
    const gy = Number.isFinite(g) ? g : 0;
    // One house bay wide — never spill onto the neighbour's elevation.
    const boardW = shop.houseW ? Math.min(shop.w, shop.houseW * 0.9) : shop.w;
    const half = boardW / 2;
    const cx = fx + nx * FASCIA_OUT;
    const cz = fz + nz * FASCIA_OUT;
    const y0 = gy + FASCIA_Y - FASCIA_H / 2;
    const y1 = gy + FASCIA_Y + FASCIA_H / 2;
    const vBase = fasciaPos.length / 3;
    quad(
      fasciaPos, fasciaUv, fasciaIdx, fasciaLit,
      [V(cx - tx * half, y0, cz - tz * half), V(cx + tx * half, y0, cz + tz * half), V(cx + tx * half, y1, cz + tz * half), V(cx - tx * half, y1, cz - tz * half)],
      uvOf(sx, sy, SLOT_W, SLOT_H), 0,
    );
    // Ground-floor shopfront (banks / cafés): coloured surround + glazing under the fascia.
    if (shop.shopfront) {
      const fw = (shop.houseW || boardW) * 0.92;
      const fh = fw / 2;
      const px = fx + nx * FRONT_OUT;
      const pz = fz + nz * FRONT_OUT;
      const [fr, fg, fb] = shop.fascia || [0.2, 0.18, 0.16];
      const [gr, gg, gb] = shop.glass || [0.5, 0.48, 0.44];
      const bank = shop.mood === "bank";
      // Pillars / plinth in fascia colour
      const addColoured = (corners, r, gch, b) => {
        const base = frontPos.length / 3;
        for (const p of corners) {
          frontPos.push(p.x, p.y, p.z);
          frontCol.push(r, gch, b);
        }
        frontIdx.push(base, base + 1, base + 2, base, base + 2, base + 3);
      };
      const sill = gy + (bank ? 0.35 : 0.45);
      const head = gy + FRONT_H;
      const glassTop = head - 0.18;
      const glassBot = sill + 0.08;
      const inset = bank ? 0.22 : 0.18;
      addColoured(
        [V(px - tx * fh, gy, pz - tz * fh), V(px + tx * fh, gy, pz + tz * fh), V(px + tx * fh, sill, pz + tz * fh), V(px - tx * fh, sill, pz - tz * fh)],
        fr, fg, fb,
      );
      addColoured(
        [V(px - tx * fh, glassTop, pz - tz * fh), V(px + tx * fh, glassTop, pz + tz * fh), V(px + tx * fh, head, pz + tz * fh), V(px - tx * fh, head, pz - tz * fh)],
        fr, fg, fb,
      );
      for (const side of [-1, 1]) {
        const i0 = side < 0 ? -fh : fh - inset;
        const i1 = side < 0 ? -fh + inset : fh;
        addColoured(
          [V(px + tx * i0, sill, pz + tz * i0), V(px + tx * i1, sill, pz + tz * i1), V(px + tx * i1, glassTop, pz + tz * i1), V(px + tx * i0, glassTop, pz + tz * i0)],
          fr * 0.85, fg * 0.85, fb * 0.85,
        );
      }
      // Window glass (slightly proud so it reads at night)
      const gx = px + nx * 0.03;
      const gz = pz + nz * 0.03;
      addColoured(
        [V(gx - tx * (fh - inset), glassBot, gz - tz * (fh - inset)), V(gx + tx * (fh - inset), glassBot, gz + tz * (fh - inset)), V(gx + tx * (fh - inset), glassTop, gz + tz * (fh - inset)), V(gx - tx * (fh - inset), glassTop, gz - tz * (fh - inset))],
        gr, gg, gb,
      );
    }
    // Blade sign at the right end of the fascia, sticking out over the pavement (both faces).
    const bx = fx + tx * (half - 0.15) + nx * (0.3 + BLADE / 2);
    const bz = fz + tz * (half - 0.15) + nz * (0.3 + BLADE / 2);
    const by = gy + FASCIA_Y + 0.55;
    const iu = uvOf(ICONS.indexOf(shop.cat) * ICON, iconY, ICON, ICON);
    const b = BLADE / 2;
    quad(
      fasciaPos, fasciaUv, fasciaIdx, fasciaLit,
      [
        V(bx - nx * b, by - b, bz - nz * b),
        V(bx + nx * b, by - b, bz + nz * b),
        V(bx + nx * b, by + b, bz + nz * b),
        V(bx - nx * b, by + b, bz - nz * b),
      ],
      iu, 0,
    );
    // Light pool on the pavement in front of the shop window.
    const pw = Math.min(shop.w * 0.95, 5.5) / 2;
    // The pool must sit on the raised footway, not the façade strip in front of the door.
    let top = gy;
    for (const depth of [0.6, 1.6, 2.8]) {
      for (const side of [-0.8, 0, 0.8]) {
        const h = groundAt(fx + nx * depth + tx * pw * side, fz + nz * depth + tz * pw * side);
        if (Number.isFinite(h) && h < gy + 0.2) top = Math.max(top, h); // kerb yes, doorsteps no
      }
    }
    const py = top + 0.03;
    const pBase = poolPos.length / 3;
    quad(
      poolPos, poolUv, poolIdx, null,
      [
        V(fx - tx * pw + nx * 0.1, py, fz - tz * pw + nz * 0.1),
        V(fx + tx * pw + nx * 0.1, py, fz + tz * pw + nz * 0.1),
        V(fx + tx * pw + nx * POOL_DEPTH, py, fz + tz * pw + nz * POOL_DEPTH),
        V(fx - tx * pw + nx * POOL_DEPTH, py, fz - tz * pw + nz * POOL_DEPTH),
      ],
      [0, 1, 1, 0], 0,
    );
    for (let k = 0; k < 4; k++) poolCol.push(0, 0, 0);
    records.push({ ...shop, fx, fz, nx, nz, gy, vBase, vCount: 8, pBase, open: null });
  });

  const atlas = new THREE.CanvasTexture(canvas);
  atlas.colorSpace = THREE.SRGBColorSpace;
  atlas.anisotropy = opts.anisotropy || 8;
  atlas.generateMipmaps = true;
  atlas.minFilter = THREE.LinearMipmapLinearFilter;

  const fGeo = new THREE.BufferGeometry();
  fGeo.setAttribute("position", new THREE.Float32BufferAttribute(fasciaPos, 3));
  fGeo.setAttribute("uv", new THREE.Float32BufferAttribute(fasciaUv, 2));
  const litAttr = new THREE.Float32BufferAttribute(fasciaLit, 1);
  litAttr.setUsage(THREE.DynamicDrawUsage);
  fGeo.setAttribute("aLit", litAttr);
  fGeo.setIndex(fasciaIdx);
  fGeo.computeVertexNormals();
  const fMat = new THREE.MeshStandardMaterial({
    map: atlas,
    emissiveMap: atlas,
    emissive: 0xffffff,
    emissiveIntensity: 0,
    roughness: 0.55,
    metalness: 0.05,
    side: THREE.DoubleSide,
    polygonOffset: true,
    polygonOffsetFactor: -2,
  });
  fMat.onBeforeCompile = (sh) => {
    sh.vertexShader = sh.vertexShader
      .replace("#include <common>", "#include <common>\nattribute float aLit;\nvarying float vLit;")
      .replace("#include <begin_vertex>", "#include <begin_vertex>\nvLit = aLit;");
    sh.fragmentShader = sh.fragmentShader
      .replace("#include <common>", "#include <common>\nvarying float vLit;")
      .replace("#include <emissivemap_fragment>", "#include <emissivemap_fragment>\ntotalEmissiveRadiance *= vLit;");
  };
  const fascias = new THREE.Mesh(fGeo, fMat);
  fascias.name = "shop_fascias";
  scene.add(fascias);

  if (frontPos.length) {
    const frGeo = new THREE.BufferGeometry();
    frGeo.setAttribute("position", new THREE.Float32BufferAttribute(frontPos, 3));
    frGeo.setAttribute("color", new THREE.Float32BufferAttribute(frontCol, 3));
    frGeo.setIndex(frontIdx);
    frGeo.computeVertexNormals();
    const frMat = new THREE.MeshStandardMaterial({
      vertexColors: true,
      roughness: 0.55,
      metalness: 0.08,
      side: THREE.DoubleSide,
      polygonOffset: true,
      polygonOffsetFactor: -2,
    });
    const fronts = new THREE.Mesh(frGeo, frMat);
    fronts.name = "shop_fronts";
    scene.add(fronts);
  }

  const pGeo = new THREE.BufferGeometry();
  pGeo.setAttribute("position", new THREE.Float32BufferAttribute(poolPos, 3));
  pGeo.setAttribute("uv", new THREE.Float32BufferAttribute(poolUv, 2));
  const colAttr = new THREE.Float32BufferAttribute(poolCol, 3);
  colAttr.setUsage(THREE.DynamicDrawUsage);
  pGeo.setAttribute("color", colAttr);
  pGeo.setIndex(poolIdx);
  const pMat = new THREE.MeshBasicMaterial({
    map: poolTexture(THREE),
    vertexColors: true,
    side: THREE.DoubleSide,
    transparent: true,
    blending: THREE.AdditiveBlending,
    depthWrite: false,
    polygonOffset: true,
    polygonOffsetFactor: -4,
    fog: false,
  });
  const pools = new THREE.Mesh(pGeo, pMat);
  pools.name = "shop_light_pools";
  pools.renderOrder = 2;
  pools.visible = false;
  scene.add(pools);

  let glow = 0;
  let lastKey = "";
  let captionId = null;

  /** Nearest named shopfront for GTA-style captions (no facing required). */
  function locateShop(x, z, hour, day) {
    let best = null;
    let bestD = REACH;
    for (const r of records) {
      if (!r.name) continue;
      const d = Math.hypot(r.fx - x, r.fz - z);
      if (d > bestD) continue;
      best = r;
      bestD = d;
    }
    const id = best ? best.id : null;
    const changed = id !== captionId;
    captionId = id;
    return {
      shop: best,
      changed,
      subtitle: best
        ? `${prettyKind(best.kind)} · ${hoursLine(best.hours, day, hour)}`
        : "",
    };
  }

  function refresh(day, hour) {
    let changed = false;
    for (const r of records) {
      const open = isOpen(r.hours, day, hour);
      if (open === r.open) continue;
      r.open = open;
      changed = true;
      for (let k = 0; k < r.vCount; k++) litAttr.array[r.vBase + k] = open ? 1 : 0;
    }
    if (changed) litAttr.needsUpdate = true;
    return changed;
  }

  function paintPools() {
    const k = glow * 0.8;
    const warm = [1.0 * k, 0.68 * k, 0.34 * k];
    for (const r of records) {
      for (let v = 0; v < 4; v++) {
        const o = (r.pBase + v) * 3;
        colAttr.array[o] = r.open ? warm[0] : 0;
        colAttr.array[o + 1] = r.open ? warm[1] : 0;
        colAttr.array[o + 2] = r.open ? warm[2] : 0;
      }
    }
    colAttr.needsUpdate = true;
    pools.visible = glow > 0.02;
  }

  return {
    count: records.length,
    records,
    /** Game clock: hour 0..24, day 0 = Sunday. Cheap: only re-tests every game minute. */
    update(hour, day) {
      const key = `${day}:${Math.floor(hour * 60)}`;
      if (key === lastKey) return;
      lastKey = key;
      if (refresh(day, hour)) paintPools();
    },
    setNight(g) {
      glow = g;
      fMat.emissiveIntensity = 0.12 + 0.95 * g;
      paintPools();
    },
    locateShop,
    /** Name + open state for the shopfront the player is facing, or null. */
    getPrompt(p, hour, day) {
      let best = null;
      let bestD = REACH;
      const fx = -Math.sin(p.yaw);
      const fz = -Math.cos(p.yaw);
      for (const r of records) {
        const dx = r.fx - p.x;
        const dz = r.fz - p.z;
        const d = Math.hypot(dx, dz);
        if (d > bestD) continue;
        // In front of the shop and looking roughly at it.
        if (dx * r.nx + dz * r.nz > 0.3) continue;
        if ((dx * fx + dz * fz) / (d || 1) < 0.35) continue;
        best = r;
        bestD = d;
      }
      if (!best) return null;
      const title = best.name || prettyKind(best.kind);
      const kind = best.name ? ` · ${prettyKind(best.kind)}` : "";
      return `${title}${kind}\n${hoursLine(best.hours, day, hour)}${best.hoursKnown ? "" : " (usual hours)"}`;
    },
  };
}
