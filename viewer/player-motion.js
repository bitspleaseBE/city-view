/**
 * Third-person movement with inertia, shared by walking and everything you can ride.
 *
 * Speeds are m/s. Walking is a brisk game walk and Shift jogs; every ride is faster than a jog
 * so it is worth taking, but still slow enough to read the streets. On wheels A/D steer (you
 * can't strafe a bike) and S brakes, then rolls back slowly.
 *
 * `getYaw` / `setYaw` come from the look camera (mouse). The player root only stores position.
 */
export const MOVE = {
  walk: { speed: 3.6, boost: 1.55, accel: 14, brake: 18, eye: 1.7 },
  velo: { speed: 8.6, boost: 1.3, accel: 3.8, brake: 7, eye: 1.62, turn: 1.5, reverse: 1.2 },
  scooter: { speed: 7.6, boost: 1.0, accel: 4.2, brake: 7.5, eye: 1.62, turn: 1.8, reverse: 1.0 },
};

function approach(v, target, up, down, dt) {
  const speedingUp = Math.abs(target) > Math.abs(v) && target * v >= 0;
  const d = target - v;
  const s = (speedingUp ? up : down) * dt;
  return Math.abs(d) <= s ? target : v + Math.sign(d) * s;
}

/**
 * @param {object} THREE
 * @param {import("three").Object3D} playerObject
 * @param {() => number} getYaw
 * @param {(y: number) => void} setYaw
 */
export function createPlayerMotion(THREE, playerObject, getYaw, setYaw) {
  const state = { fwd: 0, side: 0, kind: "walk", footScale: 1 };

  function yaw() {
    return getYaw();
  }

  /**
   * Integrate one frame. `keys` = { w, a, s, d, shift }. Returns how far the player moved
   * so callers can animate wheels / footsteps.
   */
  function step(dt, keys, kind = "walk") {
    const cfg = MOVE[kind] || MOVE.walk;
    if (kind !== state.kind) {
      state.kind = kind;
      state.fwd = Math.min(state.fwd, cfg.speed);
      state.side = 0;
    }
    const onWheels = kind !== "walk";
    const top = cfg.speed * (keys.shift ? cfg.boost : 1) * (onWheels ? 1 : state.footScale);
    const fwdIn = (keys.w ? 1 : 0) - (keys.s ? 1 : 0);
    const sideIn = (keys.d ? 1 : 0) - (keys.a ? 1 : 0);
    const fwdTarget = fwdIn > 0 ? top : fwdIn < 0 ? -(onWheels ? cfg.reverse : top * 0.8) : 0;
    state.fwd = approach(state.fwd, fwdTarget, cfg.accel, cfg.brake, dt);
    state.side = onWheels ? 0 : approach(state.side, sideIn * top * 0.85, cfg.accel, cfg.brake, dt);
    if (onWheels && sideIn) {
      const grip = Math.min(1, 0.35 + Math.abs(state.fwd) / cfg.speed);
      setYaw(getYaw() - sideIn * cfg.turn * grip * dt);
    }
    const y = getYaw();
    const sx = Math.sin(y);
    const cz = Math.cos(y);
    if (state.fwd) {
      playerObject.position.x -= sx * state.fwd * dt;
      playerObject.position.z -= cz * state.fwd * dt;
    }
    if (state.side) {
      playerObject.position.x += cz * state.side * dt;
      playerObject.position.z -= sx * state.side * dt;
    }
    return Math.hypot(state.fwd, state.side) * dt;
  }

  function bump(keep = 0.5) {
    state.fwd *= keep;
    state.side *= keep;
  }

  function stop() {
    state.fwd = 0;
    state.side = 0;
  }

  return {
    state,
    yaw,
    step,
    bump,
    stop,
    eye: (kind) => (MOVE[kind] || MOVE.walk).eye,
    /** Walking / jogging pace multiplier (injuries); rides are unaffected. */
    setFootScale(f) {
      state.footScale = f;
    },
    /** Signed forward speed in m/s (for the speedometer). */
    get speed() {
      return state.fwd;
    },
  };
}
