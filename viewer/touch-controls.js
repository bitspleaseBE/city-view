/**
 * On-screen controls for phones / tablets (and any coarse-pointer device).
 * Feeds the same `keys` object the desktop keyboard uses, plus look / pinch callbacks.
 */

const CSS = `
#touch-ui {
  position: fixed; inset: 0; z-index: 720; pointer-events: none;
  font-family: "Helvetica Neue", Arial, sans-serif;
  --safe-b: env(safe-area-inset-bottom, 0px);
  --safe-l: env(safe-area-inset-left, 0px);
  --safe-r: env(safe-area-inset-right, 0px);
  --safe-t: env(safe-area-inset-top, 0px);
}
#touch-ui .tc-pad {
  position: absolute;
  left: calc(20px + var(--safe-l));
  bottom: calc(28px + var(--safe-b));
  width: 148px; height: 148px;
  pointer-events: auto;
  touch-action: none;
  -webkit-user-select: none; user-select: none;
}
#touch-ui .tc-ring {
  position: absolute; inset: 0;
  border-radius: 50%;
  background: rgba(10, 12, 16, 0.28);
  border: 2px solid rgba(255, 255, 255, 0.28);
  box-shadow: inset 0 0 0 1px rgba(0, 0, 0, 0.25);
}
#touch-ui .tc-knob {
  position: absolute; left: 50%; top: 50%;
  width: 58px; height: 58px; margin: -29px 0 0 -29px;
  border-radius: 50%;
  background: rgba(255, 255, 255, 0.42);
  border: 2px solid rgba(255, 255, 255, 0.55);
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.35);
  will-change: transform;
}
#touch-ui .tc-actions {
  position: absolute;
  right: calc(16px + var(--safe-r));
  bottom: calc(28px + var(--safe-b));
  display: flex; flex-direction: column; align-items: flex-end; gap: 10px;
  pointer-events: auto;
}
#touch-ui .tc-row {
  display: flex; gap: 10px; align-items: center;
}
#touch-ui .tc-btn {
  min-width: 56px; min-height: 56px;
  padding: 0 14px;
  border: 0; border-radius: 50%;
  background: rgba(10, 12, 16, 0.55);
  color: #fff;
  font: 700 0.72rem/1 "Helvetica Neue", Arial, sans-serif;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  box-shadow: 0 2px 10px rgba(0, 0, 0, 0.35);
  touch-action: manipulation;
  -webkit-user-select: none; user-select: none;
  -webkit-tap-highlight-color: transparent;
}
#touch-ui .tc-btn.wide {
  border-radius: 28px;
  min-width: 72px;
  padding: 0 16px;
}
#touch-ui .tc-btn.big {
  min-width: 68px; min-height: 68px;
  background: rgba(255, 216, 0, 0.88);
  color: #111;
}
#touch-ui .tc-btn.on {
  background: rgba(255, 255, 255, 0.88);
  color: #111;
}
#touch-ui .tc-btn:active { transform: scale(0.96); }
#touch-ui .tc-top {
  position: absolute;
  top: calc(14px + var(--safe-t));
  left: 50%;
  transform: translateX(-50%);
  display: flex; gap: 8px; flex-wrap: wrap; justify-content: center;
  max-width: min(92vw, 420px);
  pointer-events: auto;
}
#touch-ui .tc-top .tc-btn {
  min-width: 0; min-height: 40px;
  border-radius: 20px;
  font-size: 0.68rem;
  padding: 0 12px;
  background: rgba(10, 12, 16, 0.62);
}
body.free-view #touch-ui .tc-pad,
body.free-view #touch-ui .tc-actions .tc-jump,
body.free-view #touch-ui .tc-actions .tc-interact,
body.free-view #touch-ui .tc-actions .tc-sprint {
  opacity: 0.35;
}
body.on-transit #touch-ui .tc-pad,
body.on-transit #touch-ui .tc-actions .tc-jump,
body.on-transit #touch-ui .tc-actions .tc-sprint {
  opacity: 0.25;
  pointer-events: none;
}
`;

/** Prefer touch UI on phones/tablets; keep desktop keyboard-only when fine pointer + hover. */
export function wantsTouchControls() {
  if (typeof window === "undefined") return false;
  const coarse = window.matchMedia("(pointer: coarse)").matches;
  const noHover = window.matchMedia("(hover: none)").matches;
  const multiTouch = (navigator.maxTouchPoints || 0) > 0;
  // iPadOS 13+ may report as Mac with touch points; coarse/hover catch phones.
  return coarse || noHover || (multiTouch && window.innerWidth <= 1366);
}

export function createTouchControls(opts) {
  const {
    keys,
    onInteract,
    onToggleMode,
    onToggleNight,
    onToggleHelp,
    onToggleMap,
    onLook,
    onPinchZoom,
    canLook,
    onStart,
  } = opts;

  const style = document.createElement("style");
  style.textContent = CSS;
  document.head.appendChild(style);

  const root = document.createElement("div");
  root.id = "touch-ui";
  root.hidden = true;
  root.innerHTML = `
    <div class="tc-top">
      <button type="button" class="tc-btn tc-mode" data-act="mode">Kaart</button>
      <button type="button" class="tc-btn" data-act="night">Nacht</button>
      <button type="button" class="tc-btn" data-act="map">Radar</button>
      <button type="button" class="tc-btn" data-act="help">Hulp</button>
    </div>
    <div class="tc-pad" aria-label="Bewegen">
      <div class="tc-ring"></div>
      <div class="tc-knob"></div>
    </div>
    <div class="tc-actions">
      <div class="tc-row">
        <button type="button" class="tc-btn tc-sprint wide" data-hold="shift">Rennen</button>
      </div>
      <div class="tc-row">
        <button type="button" class="tc-btn tc-jump" data-hold="space">Spring</button>
        <button type="button" class="tc-btn tc-interact big" data-act="interact">Ga</button>
      </div>
    </div>
  `;
  document.body.appendChild(root);

  const pad = root.querySelector(".tc-pad");
  const knob = root.querySelector(".tc-knob");
  const modeBtn = root.querySelector(".tc-mode");
  const nightBtn = root.querySelector('[data-act="night"]');

  let active = false;
  let stickId = null;
  let lookId = null;
  let lookX = 0;
  let lookY = 0;
  let pinch = null;
  const DEAD = 0.18;
  const RADIUS = 52;

  function setActive(on) {
    active = !!on;
    root.hidden = !active;
    document.body.classList.toggle("touch-ui", active);
  }

  function startSession() {
    if (!active) setActive(true);
    document.body.classList.add("locked");
    document.getElementById("hud")?.classList.add("gone");
    onStart?.();
  }

  function clearMoveKeys() {
    keys.w = keys.a = keys.s = keys.d = false;
    knob.style.transform = "translate(0,0)";
  }

  function applyStick(nx, ny) {
    // Screen-up = forward (W). Invert Y so dragging up walks forward.
    const mag = Math.hypot(nx, ny);
    if (mag < DEAD) {
      clearMoveKeys();
      return;
    }
    const ax = nx / mag;
    const ay = ny / mag;
    keys.w = ay < -0.35;
    keys.s = ay > 0.35;
    keys.a = ax < -0.35;
    keys.d = ax > 0.35;
    // Prefer diagonals when both axes strong
    if (Math.abs(ax) > 0.55 && Math.abs(ay) > 0.55) {
      keys.w = ay < 0;
      keys.s = ay > 0;
      keys.a = ax < 0;
      keys.d = ax > 0;
    }
    const px = ax * Math.min(mag, 1) * RADIUS;
    const py = ay * Math.min(mag, 1) * RADIUS;
    knob.style.transform = `translate(${px}px,${py}px)`;
  }

  function stickFromEvent(e) {
    const r = pad.getBoundingClientRect();
    const cx = r.left + r.width / 2;
    const cy = r.top + r.height / 2;
    const dx = e.clientX - cx;
    const dy = e.clientY - cy;
    const mag = Math.hypot(dx, dy) || 1;
    const scale = Math.min(1, RADIUS / mag);
    applyStick((dx * scale) / RADIUS, (dy * scale) / RADIUS);
  }

  pad.addEventListener("pointerdown", (e) => {
    if (e.pointerType === "mouse" && e.button !== 0) return;
    e.preventDefault();
    e.stopPropagation();
    startSession();
    stickId = e.pointerId;
    pad.setPointerCapture(e.pointerId);
    stickFromEvent(e);
  });
  pad.addEventListener("pointermove", (e) => {
    if (e.pointerId !== stickId) return;
    e.preventDefault();
    stickFromEvent(e);
  });
  const endStick = (e) => {
    if (e.pointerId !== stickId) return;
    stickId = null;
    clearMoveKeys();
  };
  pad.addEventListener("pointerup", endStick);
  pad.addEventListener("pointercancel", endStick);

  root.querySelectorAll("[data-hold]").forEach((btn) => {
    const key = btn.getAttribute("data-hold");
    const down = (e) => {
      e.preventDefault();
      e.stopPropagation();
      startSession();
      keys[key] = true;
      btn.classList.add("on");
      try {
        btn.setPointerCapture(e.pointerId);
      } catch (_) {
        /* ignore */
      }
    };
    const up = (e) => {
      e.preventDefault();
      e.stopPropagation();
      keys[key] = false;
      btn.classList.remove("on");
    };
    btn.addEventListener("pointerdown", down);
    btn.addEventListener("pointerup", up);
    btn.addEventListener("pointercancel", up);
    btn.addEventListener("lostpointercapture", () => {
      keys[key] = false;
      btn.classList.remove("on");
    });
  });

  root.querySelectorAll("[data-act]").forEach((btn) => {
    btn.addEventListener("pointerdown", (e) => {
      e.preventDefault();
      e.stopPropagation();
      startSession();
      const act = btn.getAttribute("data-act");
      if (act === "interact") onInteract?.();
      else if (act === "mode") onToggleMode?.();
      else if (act === "night") onToggleNight?.();
      else if (act === "help") onToggleHelp?.();
      else if (act === "map") onToggleMap?.();
    });
  });

  /** Look / pinch on the canvas; free-view pan stays in index.html. */
  function bindCanvas(canvas) {
    canvas.style.touchAction = "none";

    canvas.addEventListener(
      "pointerdown",
      (e) => {
        if (!active) return;
        if (e.target.closest?.("#touch-ui")) return;
        // Free view: leave single-finger pan to the existing freeDrag handler.
        if (!canLook?.()) {
          if (e.pointerType !== "mouse" && e.isPrimary === false) {
            // second finger starts a pinch
          }
          return;
        }
        if (stickId != null && e.pointerId === stickId) return;
        if (lookId != null) {
          // two fingers → pinch
          if (pinch) return;
          pinch = {
            a: lookId,
            b: e.pointerId,
            dist: 0,
            ax: lookX,
            ay: lookY,
            bx: e.clientX,
            by: e.clientY,
          };
          pinch.dist = Math.hypot(pinch.bx - pinch.ax, pinch.by - pinch.ay) || 1;
          lookId = null;
          return;
        }
        if (e.pointerType === "mouse" && e.button !== 0) return;
        // Don't steal the left stick's pointer if it somehow hits the canvas.
        if (stickId != null) return;
        lookId = e.pointerId;
        lookX = e.clientX;
        lookY = e.clientY;
        startSession();
      },
      { capture: true },
    );

    canvas.addEventListener(
      "pointermove",
      (e) => {
        if (!active) return;
        if (pinch) {
          if (e.pointerId === pinch.a) {
            pinch.ax = e.clientX;
            pinch.ay = e.clientY;
          } else if (e.pointerId === pinch.b) {
            pinch.bx = e.clientX;
            pinch.by = e.clientY;
          } else return;
          const dist = Math.hypot(pinch.bx - pinch.ax, pinch.by - pinch.ay) || 1;
          const ratio = dist / pinch.dist;
          pinch.dist = dist;
          onPinchZoom?.(ratio);
          return;
        }
        if (e.pointerId !== lookId || !canLook?.()) return;
        const dx = e.clientX - lookX;
        const dy = e.clientY - lookY;
        lookX = e.clientX;
        lookY = e.clientY;
        if (dx || dy) onLook?.(dx, dy);
      },
      { capture: true },
    );

    const endLook = (e) => {
      if (pinch) {
        if (e.pointerId === pinch.a || e.pointerId === pinch.b) pinch = null;
        return;
      }
      if (e.pointerId === lookId) lookId = null;
    };
    canvas.addEventListener("pointerup", endLook, { capture: true });
    canvas.addEventListener("pointercancel", endLook, { capture: true });
  }

  function setModeLabel(mode) {
    modeBtn.textContent = mode === "free" ? "Lopen" : "Kaart";
  }

  function setNightLabel(isNight) {
    nightBtn.textContent = isNight ? "Dag" : "Nacht";
  }

  /** Rewrite keyboard-centric prompts for touch. */
  function softenPrompt(text) {
    if (!text || !active) return text;
    return text
      .replace(/^Press E to (\w)/i, (_, c) => c.toUpperCase())
      .replace(/^E · /i, "")
      .replace(/^E om af te stappen$/i, "tik Ga om af te stappen")
      .replace(/ · E om af te stappen/i, " · tik Ga om af te stappen")
      .replace(/ · E om uit te stappen/i, " · tik Ga om uit te stappen")
      .replace(/ · E to leave/i, " · tik Ga om uit te stappen")
      .replace(/\bE\b/g, "Ga");
  }

  return {
    wants: true,
    root,
    setActive,
    startSession,
    isActive: () => active,
    /** Playing walk session without pointer lock. */
    isEngaged: () => active && document.body.classList.contains("locked"),
    bindCanvas,
    setModeLabel,
    setNightLabel,
    softenPrompt,
    clearMoveKeys,
  };
}
