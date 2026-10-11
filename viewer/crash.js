/**
 * Coming off a scooter / bike in first person: thrown over the bars, tumble, hit the deck,
 * slide, lie there dazed, get back up hurt — or die if the impact was violent enough.
 * Health drops with impact speed and slowly comes back while alive; while hurt the screen
 * edges are red and you walk slower.
 */

const G = 9.81;
const LIE_EYE = 0.24; // m: eye height with your head on the paving
const SLIDE_DECEL = 6.5; // m/s² of a body sliding on paving
const RISE_S = 1.5;
const REGEN_DELAY = 8; // s after a hit before health starts coming back
const REGEN_RATE = 1.5; // health / s
const DEAD_LIE_S = 4.5; // s face-down before the death callback / respawn can fire

const CSS = `
#hurt { position: fixed; inset: 0; pointer-events: none; z-index: 550; opacity: 0;
  background: radial-gradient(ellipse at center, rgba(120,0,0,0) 45%, rgba(150,0,0,0.55) 78%, rgba(90,0,0,0.9) 100%); }
#hurt-flash { position: fixed; inset: 0; pointer-events: none; z-index: 551; opacity: 0; background: #fff; }
`;

export function createPlayerCrash(THREE, camera, opts = {}) {
  const style = document.createElement("style");
  style.textContent = CSS;
  document.head.appendChild(style);
  const vignette = document.createElement("div");
  vignette.id = "hurt";
  const flashEl = document.createElement("div");
  flashEl.id = "hurt-flash";
  document.body.append(vignette, flashEl);
  const canvas = opts.canvas || null;
  const standEye = opts.eye ?? 1.7;

  const euler = new THREE.Euler(0, 0, 0, "YXZ");
  let health = 100;
  let sinceHit = Infinity;
  let flash = 0;
  let daze = 0;
  let shownBlur = "";
  let dead = false;
  let deathReported = false;
  let onDeath = null;
  /** null, or the state of the fall in progress. */
  let c = null;
  /** ms timestamp: ignore new hits until the get-up camera has settled. */
  let safeUntil = 0;

  /** Thrown off at `speed` m/s heading `yaw`. Returns the damage taken. */
  function start(pos, yaw, speed) {
    if (dead) return 0;
    euler.setFromQuaternion(camera.quaternion);
    const throwSpeed = Math.min(16, Math.max(0, Number.isFinite(speed) ? speed : 4));
    const dmg = Math.round(Math.min(90, Math.max(8, 8 + (throwSpeed - 3) * 10)));
    health = Math.max(0, health - dmg);
    sinceHit = 0;
    const killed = health <= 0;
    if (killed) {
      dead = true;
      health = 0;
      deathReported = false;
    }
    const fx = -Math.sin(yaw);
    const fz = -Math.cos(yaw);
    // Harder impacts throw farther and hang in the air longer.
    const throwK = killed ? 1.15 : 1;
    c = {
      phase: "fly",
      t: 0,
      yaw: euler.y,
      pitch: euler.x,
      roll: 0,
      side: Math.random() < 0.5 ? -1 : 1,
      vx: fx * throwSpeed * 0.8 * throwK,
      vz: fz * throwSpeed * 0.8 * throwK,
      vy: 1.6 + throwSpeed * 0.12 * throwK,
      y: pos.y,
      shake: 0,
      lie: killed ? DEAD_LIE_S : 1.6 + dmg * 0.035,
      dmg,
      killed,
    };
    flash = 0;
    return dmg;
  }

  /** Something solid in the way: the body stops travelling sideways and drops. */
  function stopHorizontal() {
    if (!c) return;
    c.vx = 0;
    c.vz = 0;
  }

  const ease = (a, b, k) => a + (b - a) * k;

  function update(dt, obj) {
    sinceHit += dt;
    if (!dead && sinceHit > REGEN_DELAY && health < 100) health = Math.min(100, health + REGEN_RATE * dt);
    flash = Math.max(0, flash - dt * 2.2);
    daze = Math.max(0, daze - dt * 0.35);
    vignette.style.opacity = String(Math.min(1, flash * 0.8 + (1 - health / 100) * 0.75 + (dead ? 0.35 : 0)));
    flashEl.style.opacity = String(Math.max(0, flash - 0.55));
    const blur = daze > 0.02 ? `blur(${(daze * 3).toFixed(1)}px)` : "";
    if (canvas && blur !== shownBlur) canvas.style.filter = shownBlur = blur;
    if (!c) return false;

    c.t += dt;
    const p = obj.position;
    if (c.phase !== "rise") {
      p.x += c.vx * dt;
      p.z += c.vz * dt;
    }
    if (c.phase === "fly") {
      c.vy -= G * dt;
      c.y += c.vy * dt;
      // Over the bars: the view pitches down at the ground coming up and starts to roll.
      c.pitch = ease(c.pitch, -1.05, Math.min(1, dt * 4.5));
      c.roll = ease(c.roll, c.side * 0.45, Math.min(1, dt * 3));
      if (c.y <= LIE_EYE) {
        c.y = LIE_EYE;
        c.phase = "slide";
        c.t = 0;
        c.shake = 0.45;
        flash = 1;
        daze = 1;
      }
    } else if (c.phase === "slide" || c.phase === "lie") {
      let hs = Math.hypot(c.vx, c.vz);
      if (!Number.isFinite(hs)) {
        c.vx = 0;
        c.vz = 0;
        hs = 0;
      }
      if (hs > 0) {
        const slow = Math.max(0, hs - SLIDE_DECEL * dt) / hs;
        c.vx *= slow;
        c.vz *= slow;
      }
      // Rolled onto your side, cheek on the paving.
      c.pitch = ease(c.pitch, 0.08, Math.min(1, dt * 3.5));
      c.roll = ease(c.roll, c.side * 1.2, Math.min(1, dt * 3.5));
      if (c.phase === "slide" && hs < 0.05) {
        c.phase = "lie";
        c.t = 0;
      } else if (c.phase === "lie" && c.t > c.lie) {
        if (c.killed || dead) {
          if (!deathReported) {
            deathReported = true;
            if (onDeath) onDeath();
          }
          // Stay down until respawn clears the crash.
          c.t = c.lie;
        } else {
          c.phase = "rise";
          c.t = 0;
          c.fromY = c.y;
          c.fromPitch = c.pitch;
          c.fromRoll = c.roll;
        }
      }
    } else if (c.phase === "rise") {
      const k = Math.min(1, c.t / RISE_S);
      const s = k * k * (3 - 2 * k);
      c.y = ease(c.fromY, standEye, s);
      c.pitch = ease(c.fromPitch, 0, s);
      c.roll = ease(c.fromRoll, 0, s);
      if (k >= 1) {
        p.y = standEye;
        c.pitch = 0;
        c.roll = 0;
        camera.up.set(0, 1, 0);
        camera.quaternion.setFromEuler(euler.set(0, c.yaw, 0, "YXZ"));
        safeUntil = performance.now() + 2800;
        c = null;
        return false;
      }
    }

    c.shake = Math.max(0, c.shake - dt);
    const sh = c.shake * c.shake;
    p.y = c.y + (Math.random() - 0.5) * sh * 0.08;
    camera.quaternion.setFromEuler(
      euler.set(c.pitch + (Math.random() - 0.5) * sh * 0.25, c.yaw, c.roll + (Math.random() - 0.5) * sh * 0.25, "YXZ")
    );
    return true;
  }

  function respawn(pos, yaw) {
    dead = false;
    deathReported = false;
    health = 100;
    sinceHit = Infinity;
    flash = 0;
    daze = 0;
    c = null;
    if (pos) {
      pos.y = standEye;
    }
    if (Number.isFinite(yaw)) {
      camera.quaternion.setFromEuler(euler.set(0, yaw, 0, "YXZ"));
    }
    if (canvas) canvas.style.filter = shownBlur = "";
    vignette.style.opacity = "0";
    flashEl.style.opacity = "0";
  }

  return {
    start,
    update,
    stopHorizontal,
    respawn,
    setOnDeath(fn) {
      onDeath = typeof fn === "function" ? fn : null;
    },
    get active() {
      return !!c;
    },
    /** True once the get-up has finished and a new hit is allowed. */
    get vulnerable() {
      return performance.now() >= safeUntil;
    },
    get airborne() {
      return !!c && c.phase === "fly";
    },
    get dead() {
      return dead;
    },
    get health() {
      return health;
    },
    /** Walking pace multiplier: you limp while hurt. */
    speedScale: () => (dead ? 0 : 0.55 + 0.45 * (health / 100)),
  };
}
