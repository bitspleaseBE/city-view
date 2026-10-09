/**
 * Mini map: a fixed canvas overlay showing the district from above with
 * the player position, vehicles, transit, and click-to-teleport in free mode.
 * Uses a simple cached road map rendering.
 */
export function createMinimap(THREE, opts = {}) {
  const SIZE = 200; // px
  const MARGIN = 12;
  const BOUNDS = opts.playBounds || { minX: -500, maxX: 200, minZ: -800, maxZ: 100 };
  const SPAWN = opts.spawnCenter || { x: -218.5, z: -432.1 };
  const ROADS_URL = opts.roadsUrl || "./roads.json";

  const width = opts.width || SIZE;
  const height = opts.height || SIZE;

  // Canvas state
  const canvas = document.createElement("canvas");
  canvas.width = width * 2;
  canvas.height = height * 2;
  canvas.style.position = "fixed";
  canvas.style.bottom = MARGIN + "px";
  canvas.style.right = MARGIN + "px";
  canvas.style.width = width + "px";
  canvas.style.height = height + "px";
  canvas.style.zIndex = "500";
  canvas.style.border = "1px solid rgba(255,255,255,0.25)";
  canvas.style.borderRadius = "8px";
  canvas.style.pointerEvents = "auto";
  canvas.style.background = "rgba(0,0,0,0.35)";
  canvas.style.cursor = "pointer";
  document.body.appendChild(canvas);

  // Street name label resting above the mini map
  const streetLabel = document.createElement("div");
  streetLabel.setAttribute("aria-live", "polite");
  streetLabel.style.cssText = [
    "position:fixed",
    `right:${MARGIN}px`,
    `bottom:${MARGIN + height + 8}px`,
    "max-width:" + width + "px",
    "padding:6px 10px",
    "background:rgba(26,36,48,0.82)",
    "color:#f4efe6",
    "font:600 0.82rem/1.25 \"Iowan Old Style\",\"Palatino Linotype\",Palatino,serif",
    "letter-spacing:0.01em",
    "border:1px solid rgba(255,255,255,0.12)",
    "border-radius:6px",
    "pointer-events:none",
    "z-index:500",
    "text-align:right",
    "opacity:0",
    "transform:translateY(4px)",
    "transition:opacity 280ms ease, transform 280ms ease",
    "white-space:nowrap",
    "overflow:hidden",
    "text-overflow:ellipsis",
  ].join(";");
  document.body.appendChild(streetLabel);

  let streetHideTimer = 0;
  const STREET_HOLD_MS = 3200;

  function showStreetName(name) {
    if (!name) return;
    streetLabel.textContent = name;
    if (streetHideTimer) clearTimeout(streetHideTimer);
    // Retrigger enter animation
    streetLabel.style.opacity = "0";
    streetLabel.style.transform = "translateY(4px)";
    // Force reflow so the transition restarts
    void streetLabel.offsetWidth;
    streetLabel.style.opacity = "1";
    streetLabel.style.transform = "translateY(0)";
    streetHideTimer = setTimeout(() => {
      streetLabel.style.opacity = "0";
      streetLabel.style.transform = "translateY(4px)";
      streetHideTimer = 0;
    }, STREET_HOLD_MS);
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
  async function loadRoads() {
    try {
      const res = await fetch(ROADS_URL);
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
      // Spawn marker
      const sp = toPixel(SPAWN.x, SPAWN.z);
      bgCtx.fillStyle = "#ffd800";
      bgCtx.beginPath();
      bgCtx.arc(sp.u, sp.v, 4, 0, Math.PI * 2);
      bgCtx.fill();
      bgReady = true;
    } catch (e) {
      console.warn("Minimap: could not load roads");
    }
  }
  loadRoads();

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

    // Bikes / scooters / cargo bikes
    if (micromobility && micromobility.vehicles) {
      for (const v of micromobility.vehicles) {
        if (!v.pos) continue;
        const p = toPixel(v.pos.x, v.pos.z);
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

  function setVisible(v) {
    visible = v;
    canvas.style.display = v ? "block" : "none";
    streetLabel.style.display = v ? "block" : "none";
    if (!v && streetHideTimer) {
      clearTimeout(streetHideTimer);
      streetHideTimer = 0;
      streetLabel.style.opacity = "0";
    }
  }

  return { draw, consumeTeleport, setVisible, showStreetName, canvas };
}