/**
 * Mini map: a fixed canvas overlay showing the district from above with
 * the player position, vehicles, transit, and click-to-teleport in free mode.
 * Uses a simple cached road map rendering.
 */

import { fetchJsonCached } from "./json-cache.js";

export function createMinimap(THREE, opts = {}) {
  const SIZE = 200; // px
  const MARGIN = 12;
  const BOUNDS = opts.playBounds || { minX: -500, maxX: 200, minZ: -800, maxZ: 100 };
  const SPAWN = opts.spawnCenter || { x: -218.5, z: -432.1 };
  const ROADS_URL = opts.roadsUrl || "./roads.json";
  const TRANSIT_URL = opts.transitUrl || "./transit.json";

  const width = opts.width || SIZE;
  const height = opts.height || SIZE;

  // Canvas state
  const canvas = document.createElement("canvas");
  canvas.width = width * 2;
  canvas.height = height * 2;
  canvas.style.position = "fixed";
  canvas.style.bottom = "22px";
  canvas.style.left = "22px";
  canvas.style.width = width + "px";
  canvas.style.height = height + "px";
  canvas.style.zIndex = "500";
  canvas.style.border = "1px solid rgba(255,255,255,0.25)";
  canvas.style.borderRadius = "8px";
  canvas.style.pointerEvents = "auto";
  canvas.style.background = "rgba(0,0,0,0.35)";
  canvas.style.cursor = "pointer";
  document.body.appendChild(canvas);

  /** 0 = day palette, 1 = night — synced from applyTimeOfDay. */
  let nightGlow = 0;

  // Street name label resting above the mini map
  const streetLabel = document.createElement("div");
  streetLabel.setAttribute("aria-live", "polite");
  // GTA-style area caption: big outlined street name bottom-right, district underneath.
  streetLabel.style.cssText = [
    "position:fixed",
    "right:28px",
    "bottom:26px",
    "max-width:46vw",
    "color:#fff",
    "font:700 1.7rem/1.05 'Helvetica Neue',Arial,sans-serif",
    "letter-spacing:0.01em",
    "text-shadow:0 0 3px #000,0 2px 2px #000,0 0 8px rgba(0,0,0,0.6)",
    "pointer-events:none",
    "z-index:500",
    "text-align:right",
    "opacity:0",
    "transform:translateY(4px)",
    "transition:opacity 280ms ease, transform 280ms ease",
    "white-space:nowrap",
  ].join(";");
  document.body.appendChild(streetLabel);

  let streetHideTimer = 0;
  const STREET_HOLD_MS = 3200;

  function showStreetName(name, subtitle, holdMs) {
    if (!name) return;
    streetLabel.innerHTML = "";
    const sub = document.createElement("div");
    sub.textContent = subtitle || opts.districtName || "Klein Antwerpen";
    sub.style.cssText = "font-size:0.95rem;font-weight:600;opacity:0.85;margin-top:4px;text-transform:uppercase;letter-spacing:0.12em";
    streetLabel.append(name, sub);
    if (streetHideTimer) clearTimeout(streetHideTimer);
    // Retrigger enter animation
    streetLabel.style.opacity = "0";
    streetLabel.style.transform = "translateY(4px)";
    // Force reflow so the transition restarts
    void streetLabel.offsetWidth;
    streetLabel.style.opacity = "1";
    streetLabel.style.transform = "translateY(0)";
    const hold = Number.isFinite(holdMs) && holdMs > 0 ? holdMs : STREET_HOLD_MS;
    streetHideTimer = setTimeout(() => {
      streetLabel.style.opacity = "0";
      streetLabel.style.transform = "translateY(4px)";
      streetHideTimer = 0;
    }, hold);
  }

  const ctx = canvas.getContext("2d");
  const W = canvas.width;
  const H = canvas.height;
  const scaleX = W / (BOUNDS.maxX - BOUNDS.minX);
  const scaleZ = H / (BOUNDS.maxZ - BOUNDS.minZ);
  const scale = Math.min(scaleX, scaleZ) * 0.85;
  const ox = (W - (BOUNDS.maxX - BOUNDS.minX) * scale) / 2;
  const oy = (H - (BOUNDS.maxZ - BOUNDS.minZ) * scale) / 2;

  function toPixel(x, z) {
    return { u: ox + (x - BOUNDS.minX) * scale, v: oy + (z - BOUNDS.minZ) * scale };
  }

  // ---- Background rendering: will be re-drawn with roads data ----
  const bgCanvas = document.createElement("canvas");
  bgCanvas.width = W;
  bgCanvas.height = H;
  const bgCtx = bgCanvas.getContext("2d");
  bgCtx.fillStyle = "rgba(10,14,24,0.7)";
  bgCtx.fillRect(0, 0, W, H);

  let bgReady = false;

  /** Stroke a Blender-XY polyline onto a 2d context via toPixel(x, z). */
  function strokeWalk(ctx2d, points) {
    if (!points || points.length < 2) return;
    ctx2d.beginPath();
    for (let k = 0; k < points.length; k++) {
      const p = points[k];
      const px = Array.isArray(p) ? p[0] : p.x || 0;
      const py = Array.isArray(p) ? p[1] : p.y || 0;
      const pix = toPixel(px, -py);
      if (k === 0) ctx2d.moveTo(pix.u, pix.v);
      else ctx2d.lineTo(pix.u, pix.v);
    }
    ctx2d.stroke();
  }

  function paintWalkLayer(ctx2d, walks) {
    ctx2d.lineCap = "round";
    ctx2d.lineJoin = "round";
    ctx2d.strokeStyle = "rgba(150,205,165,0.42)";
    ctx2d.lineWidth = 1.5;
    for (const w of walks) {
      if ((w.kind || "") === "crossing") continue;
      strokeWalk(ctx2d, w.points);
    }
    ctx2d.strokeStyle = "rgba(235,220,140,0.55)";
    ctx2d.lineWidth = 1.7;
    ctx2d.setLineDash([3.5, 2.5]);
    for (const w of walks) {
      if ((w.kind || "") !== "crossing") continue;
      strokeWalk(ctx2d, w.points);
    }
    ctx2d.setLineDash([]);
  }

  /** Gold diamond pins for heritage landmarks (landmarks.json, Blender XY). */
  async function paintLandmarkPins(ctx2d, mapPoint, size = 4) {
    try {
      const res = await fetch(opts.landmarksUrl || "./landmarks.json");
      if (!res.ok) return;
      const data = await res.json();
      for (const lm of data.landmarks || []) {
        if (!Number.isFinite(lm.x) || !Number.isFinite(lm.y)) continue;
        const p = mapPoint(lm.x, -lm.y);
        ctx2d.fillStyle = "#d4a017";
        ctx2d.strokeStyle = "rgba(20,12,0,0.55)";
        ctx2d.lineWidth = 1;
        ctx2d.beginPath();
        ctx2d.moveTo(p.u, p.v - size);
        ctx2d.lineTo(p.u + size * 0.75, p.v);
        ctx2d.lineTo(p.u, p.v + size);
        ctx2d.lineTo(p.u - size * 0.75, p.v);
        ctx2d.closePath();
        ctx2d.fill();
        ctx2d.stroke();
      }
    } catch {
      /* landmarks optional */
    }
  }

  /** De Lijn tram (yellow) / bus (blue) routes + halt dots from transit.json. */
  async function paintTransitLayer(ctx2d, mapPoint, opts = {}) {
    const tramW = opts.tramW ?? 2.2;
    const busW = opts.busW ?? 1.4;
    const stopR = opts.stopR ?? 3;
    try {
      const res = await fetch(TRANSIT_URL);
      if (!res.ok) return;
      const data = await res.json();
      ctx2d.lineCap = "round";
      ctx2d.lineJoin = "round";
      for (const path of data.paths || []) {
        const pts = path.points || [];
        if (pts.length < 2) continue;
        const tram = (path.mode || "") === "tram";
        ctx2d.strokeStyle = tram ? "rgba(255,216,0,0.55)" : "rgba(0,159,227,0.4)";
        ctx2d.lineWidth = tram ? tramW : busW;
        ctx2d.beginPath();
        for (let k = 0; k < pts.length; k++) {
          const p = pts[k];
          const px = Array.isArray(p) ? p[0] : p.x || 0;
          const py = Array.isArray(p) ? p[1] : p.y || 0;
          const pix = mapPoint(px, -py);
          if (k === 0) ctx2d.moveTo(pix.u, pix.v);
          else ctx2d.lineTo(pix.u, pix.v);
        }
        ctx2d.stroke();
      }
      for (const st of data.stops || []) {
        if (!Number.isFinite(st.x) || !Number.isFinite(st.y)) continue;
        const pix = mapPoint(st.x, -st.y);
        const tram = (st.mode || "") === "tram";
        ctx2d.fillStyle = tram ? "#ffd800" : "#009fe3";
        ctx2d.beginPath();
        ctx2d.arc(pix.u, pix.v, stopR, 0, Math.PI * 2);
        ctx2d.fill();
        ctx2d.strokeStyle = "rgba(0,0,0,0.35)";
        ctx2d.lineWidth = 1;
        ctx2d.stroke();
      }
    } catch {
      console.warn("Minimap: transit layer unavailable");
    }
  }

  async function loadRoads() {
    try {
      const res = await fetchJsonCached(ROADS_URL);
      if (!res.ok) return;
      const data = await res.json();
      const roads = data.roads || [];
      bgCtx.strokeStyle = "rgba(180,190,210,0.35)";
      bgCtx.lineWidth = 2.5;
      bgCtx.lineCap = "round";
      for (const road of roads) {
        const pts = road.points || [];
        if (pts.length < 2) continue;
        bgCtx.beginPath();
        for (let k = 0; k < pts.length; k++) {
          const p = pts[k];
          const px = Array.isArray(p) ? p[0] : p.x || 0;
          const py = Array.isArray(p) ? p[1] : p.y || 0;
          // roads.json stores [x, y] where y is Blender north; z = -y in Three.js
          const pix = toPixel(px, -py);
          if (k === 0) bgCtx.moveTo(pix.u, pix.v);
          else bgCtx.lineTo(pix.u, pix.v);
        }
        bgCtx.stroke();
      }
      paintWalkLayer(bgCtx, data.walks || []);
      await paintTransitLayer(bgCtx, (x, z) => toPixel(x, z));
      await paintLandmarkPins(bgCtx, (x, z) => toPixel(x, z), 4);
      // Spawn marker (white ring so it doesn't read as a tram halt)
      const sp = toPixel(SPAWN.x, SPAWN.z);
      bgCtx.fillStyle = "#ffffff";
      bgCtx.beginPath();
      bgCtx.arc(sp.u, sp.v, 4.5, 0, Math.PI * 2);
      bgCtx.fill();
      bgCtx.strokeStyle = "#1a1a1a";
      bgCtx.lineWidth = 1.5;
      bgCtx.stroke();
      bgReady = true;
    } catch (e) {
      console.warn("Minimap: could not load roads");
    }
  }

  function consumeTeleport() {
    const t = teleportTarget;
    teleportTarget = null;
    return t;
  }

  let visible = true;
  let teleportTarget = null;
  canvas.addEventListener("click", (e) => {
    const rect = canvas.getBoundingClientRect();
    const cx = e.clientX - rect.left;
    const cy = e.clientY - rect.top;
    const worldX = (cx / width) * (BOUNDS.maxX - BOUNDS.minX) + BOUNDS.minX;
    const worldZ = (cy / height) * (BOUNDS.maxZ - BOUNDS.minZ) + BOUNDS.minZ;
    teleportTarget = { x: worldX, z: worldZ };
  });

  // ---- Draw dynamic elements each frame ----
  function draw(playerPos, traffic, transit, pedestrians, mode, micromobility, velo) {
    if (!visible) return;

    // Clear and redraw from background
    ctx.clearRect(0, 0, W, H);
    ctx.drawImage(bgCanvas, 0, 0);
    if (nightGlow > 0.01) {
      ctx.fillStyle = `rgba(5,8,18,${0.42 * nightGlow})`;
      ctx.fillRect(0, 0, W, H);
    }

    // Velo docking stations
    if (velo && velo.stations) {
      for (const st of velo.stations) {
        const p = toPixel(st.x, st.z);
        ctx.fillStyle = "#c8102e";
        ctx.beginPath();
        ctx.arc(p.u, p.v, 3, 0, Math.PI * 2);
        ctx.fill();
        ctx.strokeStyle = "rgba(255,255,255,0.55)";
        ctx.lineWidth = 1;
        ctx.stroke();
      }
    }

    // Transit vehicles
    if (transit && transit.vehicles) {
      for (const v of transit.vehicles) {
        if (v.phase === "gone" || !v.pos) continue;
        const p = toPixel(v.pos.x, v.pos.z);
        ctx.fillStyle = v.mode === "tram" ? "#ffd800" : "#009fe3";
        const size = v.mode === "tram" ? 5 : 3.5;
        ctx.beginPath();
        const ang = Math.atan2(v.tan.x, v.tan.z);
        // Draw oriented rectangle
        ctx.save();
        ctx.translate(p.u, p.v);
        ctx.rotate(ang);
        ctx.fillRect(-size * 0.8, -size * 0.3, size, size * 0.6);
        ctx.restore();
      }
    }

    // Traffic cars
    if (traffic && traffic.cars) {
      for (const c of traffic.cars) {
        const p = toPixel(c.pos.x, c.pos.z);
        ctx.fillStyle = "#88aacc";
        ctx.fillRect(p.u - 1.5, p.v - 1, 3, 2);
      }
    }

    // Bikes / scooters / cargo bikes (tipped wrecks = static hazard, not a moving rider)
    if (micromobility && micromobility.vehicles) {
      for (const v of micromobility.vehicles) {
        if (!v.pos) continue;
        const p = toPixel(v.pos.x, v.pos.z);
        if (v.crash) {
          ctx.fillStyle = "#c45a3a";
          ctx.fillRect(p.u - 1.5, p.v - 1.5, 3, 3);
          continue;
        }
        ctx.fillStyle = v.kind === "scooter" ? "#00c2a8" : v.kind === "cargo" ? "#d4a020" : "#3a8a5a";
        ctx.fillRect(p.u - 1, p.v - 1, 2, 2);
      }
    }

    // Pedestrians (dense cluster)
    if (pedestrians && pedestrians.groups) {
      for (const g of pedestrians.groups) {
        for (const m of g.members) {
          const p = toPixel(m.mesh.position.x, m.mesh.position.z);
          ctx.fillStyle = "#aabb88";
          ctx.fillRect(p.u - 0.5, p.v - 0.5, 1, 1);
        }
      }
    }

    // Player position + heading
    if (playerPos) {
      const p = toPixel(playerPos.x, playerPos.z);
      // Glow
      ctx.fillStyle = "rgba(255,255,255,0.3)";
      ctx.beginPath();
      ctx.arc(p.u, p.v, 7, 0, Math.PI * 2);
      ctx.fill();
      // Dot
      ctx.fillStyle = "#ffffff";
      ctx.beginPath();
      ctx.arc(p.u, p.v, 3.5, 0, Math.PI * 2);
      ctx.fill();
    }

    // Border
    ctx.strokeStyle = "rgba(255,255,255,0.2)";
    ctx.lineWidth = 1;
    ctx.strokeRect(0, 0, W, H);
  }

  // ---- Radar (walk mode): GTA-style, heading-up, centred a little below the middle ----
  const RW = 248;
  const RH = 156;
  const RADAR_PX_PER_M = 1.15; // radar shows ~215 m x 135 m
  const radar = document.createElement("canvas");
  radar.width = RW * 2;
  radar.height = RH * 2;
  radar.className = "hud-radar";
  radar.style.cssText = `position:fixed;left:22px;bottom:22px;width:${RW}px;height:${RH}px;z-index:500;pointer-events:none;border-radius:6px;box-shadow:0 0 0 3px rgba(0,0,0,0.55),0 6px 18px rgba(0,0,0,0.35)`;
  document.body.appendChild(radar);
  const rctx = radar.getContext("2d");
  const spanX = BOUNDS.maxX - BOUNDS.minX;
  const spanZ = BOUNDS.maxZ - BOUNDS.minZ;
  const hiScale = Math.min(1.5, 2048 / Math.max(spanX, spanZ)); // px/m — was up to 3× and ~23 MB GPU
  const hiBg = document.createElement("canvas");
  hiBg.width = Math.ceil(spanX * hiScale);
  hiBg.height = Math.ceil(spanZ * hiScale);
  const hctx = hiBg.getContext("2d");
  hctx.fillStyle = "#56645a";
  hctx.fillRect(0, 0, hiBg.width, hiBg.height);
  const toHi = (x, z) => [(x - BOUNDS.minX) * hiScale, (z - BOUNDS.minZ) * hiScale];
  let heading = 0;
  let blipSource = null;

  async function paintRadarBase() {
    hctx.fillStyle = "#56645a"; // land
    hctx.fillRect(0, 0, hiBg.width, hiBg.height);
    try {
      const res = await fetchJsonCached("./buildings.json");
      if (res.ok) {
        hctx.fillStyle = "#8d978e";
        for (const b of (await res.json()).buildings || []) {
          const ring = b.ring || [];
          if (ring.length < 3) continue;
          hctx.beginPath();
          ring.forEach((p, i) => {
            const [u, v] = toHi(p[0], -p[1]);
            if (i) hctx.lineTo(u, v);
            else hctx.moveTo(u, v);
          });
          hctx.fill();
        }
      }
    } catch {
      /* buildings are optional on the radar */
    }
    try {
      const res = await fetchJsonCached(ROADS_URL);
      if (!res.ok) return;
      const data = await res.json();
      const roads = data.roads || [];
      hctx.lineCap = "round";
      hctx.lineJoin = "round";
      for (const pass of [0, 1]) {
        for (const road of roads) {
          const pts = road.points || [];
          if (pts.length < 2) continue;
          const w = (Number(road.width) || 7) * hiScale;
          hctx.strokeStyle = pass ? "#e9ece6" : "#2e3530";
          hctx.lineWidth = pass ? w : w + 2.5 * hiScale;
          hctx.beginPath();
          pts.forEach((p, i) => {
            const [u, v] = toHi(p[0], -p[1]);
            if (i) hctx.lineTo(u, v);
            else hctx.moveTo(u, v);
          });
          hctx.stroke();
        }
      }
      // Sidewalk ribbons + zebra links (subtle so the radar stays readable).
      hctx.strokeStyle = "rgba(200,220,190,0.55)";
      hctx.lineWidth = 1.4 * hiScale;
      for (const walk of data.walks || []) {
        const pts = walk.points || [];
        if (pts.length < 2) continue;
        const cross = (walk.kind || "") === "crossing";
        hctx.strokeStyle = cross ? "rgba(230,215,150,0.7)" : "rgba(200,220,190,0.55)";
        hctx.lineWidth = (cross ? 1.8 : 1.3) * hiScale;
        if (cross) hctx.setLineDash([2.5 * hiScale, 1.8 * hiScale]);
        hctx.beginPath();
        pts.forEach((p, i) => {
          const [u, v] = toHi(p[0], -p[1]);
          if (i) hctx.lineTo(u, v);
          else hctx.moveTo(u, v);
        });
        hctx.stroke();
        if (cross) hctx.setLineDash([]);
      }
      await paintTransitLayer(
        hctx,
        (x, z) => {
          const [u, v] = toHi(x, z);
          return { u, v };
        },
        { tramW: 2.4 * hiScale, busW: 1.5 * hiScale, stopR: 2.2 * hiScale },
      );
      await paintLandmarkPins(
        hctx,
        (x, z) => {
          const [u, v] = toHi(x, z);
          return { u, v };
        },
        2.4 * hiScale,
      );
    } catch {
      console.warn("Minimap: radar roads unavailable");
    }
  }

  let baseWarmed = false;
  function warmBase() {
    if (baseWarmed) return;
    baseWarmed = true;
    loadRoads();
    paintRadarBase();
  }

  function drawRadar(playerPos, traffic, transit, micromobility) {
    const W2 = radar.width;
    const H2 = radar.height;
    const k = 2 * RADAR_PX_PER_M; // canvas px per metre (canvas is 2x CSS)
    rctx.setTransform(1, 0, 0, 1, 0, 0);
    // Day olive → night charcoal under the map raster.
    const g = nightGlow;
    const landR = (0x3c + (0x1c - 0x3c) * g) | 0;
    const landG = (0x47 + (0x24 - 0x47) * g) | 0;
    const landB = (0x40 + (0x20 - 0x40) * g) | 0;
    rctx.fillStyle = `rgb(${landR},${landG},${landB})`;
    rctx.fillRect(0, 0, W2, H2);
    rctx.save();
    rctx.translate(W2 / 2, H2 * 0.6);
    rctx.rotate(heading);
    rctx.scale(k, k);
    rctx.translate(-playerPos.x, -playerPos.z);
    rctx.imageSmoothingEnabled = true;
    rctx.drawImage(hiBg, BOUNDS.minX, BOUNDS.minZ, spanX, spanZ);
    if (g > 0.01) {
      rctx.fillStyle = `rgba(5,10,22,${0.5 * g})`;
      rctx.fillRect(BOUNDS.minX, BOUNDS.minZ, spanX, spanZ);
    }
    const box = (x, z, tx, tz, len, wid, color) => {
      rctx.save();
      rctx.translate(x, z);
      rctx.rotate(Math.atan2(tz, tx));
      rctx.fillStyle = color;
      rctx.fillRect(-len / 2, -wid / 2, len, wid);
      rctx.restore();
    };
    if (traffic && traffic.cars) for (const c of traffic.cars) if (c.pos) box(c.pos.x, c.pos.z, c.tan?.x ?? 1, c.tan?.z ?? 0, 4.4, 2, "#9aa7b4");
    if (transit && transit.vehicles) {
      for (const v of transit.vehicles) {
        if (v.phase === "gone" || !v.pos) continue;
        const tram = v.mode === "tram";
        box(v.pos.x, v.pos.z, v.tan.x, v.tan.z, tram ? 30 : 12, 2.8, tram ? "#ffd800" : "#009fe3");
      }
    }
    if (micromobility && micromobility.vehicles) {
      for (const v of micromobility.vehicles) {
        if (!v.pos) continue;
        if (v.crash) {
          // Static hazard diamond — no travel heading.
          rctx.fillStyle = "#c45a3a";
          rctx.beginPath();
          rctx.moveTo(v.pos.x, v.pos.z - 1.4);
          rctx.lineTo(v.pos.x + 1.4, v.pos.z);
          rctx.lineTo(v.pos.x, v.pos.z + 1.4);
          rctx.lineTo(v.pos.x - 1.4, v.pos.z);
          rctx.closePath();
          rctx.fill();
          continue;
        }
        box(v.pos.x, v.pos.z, v.tan.x, v.tan.z, 2, 1.2, "#2fbf71");
      }
    }
    const blips = blipSource ? blipSource() : [];
    for (const b of blips) {
      rctx.fillStyle = "rgba(0,0,0,0.6)";
      rctx.beginPath();
      rctx.arc(b.x, b.z, 3.2, 0, Math.PI * 2);
      rctx.fill();
      rctx.fillStyle = b.color;
      rctx.beginPath();
      rctx.arc(b.x, b.z, 2.3, 0, Math.PI * 2);
      rctx.fill();
    }
    rctx.restore();
    // Player arrow (always points up: the map turns, not you).
    rctx.save();
    rctx.translate(W2 / 2, H2 * 0.6);
    rctx.fillStyle = "#ffffff";
    rctx.strokeStyle = "rgba(0,0,0,0.75)";
    rctx.lineWidth = 3;
    rctx.beginPath();
    rctx.moveTo(0, -13);
    rctx.lineTo(9, 10);
    rctx.lineTo(0, 5);
    rctx.lineTo(-9, 10);
    rctx.closePath();
    rctx.stroke();
    rctx.fill();
    rctx.restore();
    // North marker on the rim.
    const nx = Math.sin(heading);
    const nz = -Math.cos(heading);
    const cx = W2 / 2;
    const cy = H2 * 0.6;
    const t = Math.min((W2 / 2 - 16) / Math.max(1e-6, Math.abs(nx)), (nz < 0 ? cy - 16 : H2 - cy - 16) / Math.max(1e-6, Math.abs(nz)));
    rctx.fillStyle = "rgba(0,0,0,0.7)";
    rctx.beginPath();
    rctx.arc(cx + nx * t, cy + nz * t, 13, 0, Math.PI * 2);
    rctx.fill();
    rctx.fillStyle = "#fff";
    rctx.font = "bold 17px 'Helvetica Neue', Arial, sans-serif";
    rctx.textAlign = "center";
    rctx.textBaseline = "middle";
    rctx.fillText("N", cx + nx * t, cy + nz * t + 1);
  }

  const drawFullMap = draw;
  function drawAny(playerPos, traffic, transit, pedestrians, mode, micromobility, ...rest) {
    const radarMode = mode === "walk";
    if (!visible) return;
    canvas.style.display = radarMode ? "none" : "block";
    radar.style.display = radarMode ? "block" : "none";
    if (radarMode) drawRadar(playerPos, traffic, transit, micromobility);
    else drawFullMap(playerPos, traffic, transit, pedestrians, mode, micromobility, ...rest);
  }

  function setVisible(v) {
    visible = v;
    canvas.style.display = v ? "block" : "none";
    radar.style.display = v ? "block" : "none";
    streetLabel.style.display = v ? "block" : "none";
    if (!v && streetHideTimer) {
      clearTimeout(streetHideTimer);
      streetHideTimer = 0;
      streetLabel.style.opacity = "0";
    }
  }

  function setNight(t) {
    nightGlow = Math.max(0, Math.min(1, Number(t) || 0));
    canvas.style.background = `rgba(0,0,0,${0.35 + 0.35 * nightGlow})`;
    canvas.style.border = `1px solid rgba(255,255,255,${0.25 - 0.08 * nightGlow})`;
    radar.style.boxShadow = `0 0 0 3px rgba(0,0,0,${0.55 + 0.25 * nightGlow}),0 6px 18px rgba(0,0,0,${0.35 + 0.25 * nightGlow})`;
    // Stronger outline so white street captions stay readable on dark façades at night.
    const bloom = 8 + 14 * nightGlow;
    const soft = 0.55 + 0.4 * nightGlow;
    streetLabel.style.textShadow = `0 0 3px #000,0 2px 3px #000,0 0 ${bloom}px rgba(0,0,0,${soft})`;
  }

  return {
    draw: drawAny,
    consumeTeleport,
    setVisible,
    showStreetName,
    setNight,
    canvas,
    radar,
    /** Camera yaw (0 = looking north / −Z); the radar turns so your heading is up. */
    setHeading(yaw) {
      heading = yaw;
    },
    /** () => [{ x, z, color }] extra radar blips (rentable scooters, stations, ...). */
    setBlips(fn) {
      blipSource = fn;
    },
    warmBase,
  };
}