/**
 * First-person movement with inertia, shared by walking and everything you can ride.
 *
 * Speeds are m/s. Walking is a brisk game walk and Shift jogs; every ride is faster than a jog
 * so it is worth taking, but still slow enough to read the streets. On wheels A/D steer (you
 * can't strafe a bike) and S brakes, then rolls back slowly.
 */
export const MOVE = {
  walk: { speed: 4.2, boost: 1.65, accel: 14, brake: 18, eye: 1.7 },
  velo: { speed: 7.6, boost: 1.3, accel: 3.2, brake: 7, eye: 1.45, turn: 1.5, reverse: 1.2 },
  scooter: { speed: 6.9, boost: 1.0, accel: 3.8, brake: 7.5, eye: 1.62, turn: 1.8, reverse: 1.0 },
};

function approach(v, target, up, down, dt) {
  const speedingUp = Math.abs(target) > Math.abs(v) && target * v >= 0;
  const d = target - v;
  const s = (speedingUp ? up : down) * dt;
  return Math.abs(d) <= s ? target : v + Math.sign(d) * s;
}

export function createPlayerMotion(THREE, camera, controls) {
  const state = { fwd: 0, side: 0, kind: "walk" };
  const euler = new THREE.Euler(0, 0, 0, "YXZ");
  const dir = new THREE.Vector3();

  /** Heading of the camera on the ground plane (0 = looking down −Z). */
  function yaw() {
    camera.getWorldDirection(dir);
    return Math.atan2(-dir.x, -dir.z);
  }

  /**
   * Integrate one frame. `keys` = { w, a, s, d, shift }. Returns how far the player moved
   * so callers can animate wheels / footsteps.
   */
  function step(dt, keys, kind = "walk") {
    const cfg = MOVE[kind] || MOVE.walk;
    if (kind !== state.kind) {
      state.kind = kind;
      state.fwd = Math.min(state.fwd, cfg.speed); // hopping off a bike doesn't sprint you
      state.side = 0;
    }
    const onWheels = kind !== "walk";
    const top = cfg.speed * (keys.shift ? cfg.boost : 1);
    const fwdIn = (keys.w ? 1 : 0) - (keys.s ? 1 : 0);
    const sideIn = (keys.d ? 1 : 0) - (keys.a ? 1 : 0);
    const fwdTarget = fwdIn > 0 ? top : fwdIn < 0 ? -(onWheels ? cfg.reverse : top * 0.8) : 0;
    state.fwd = approach(state.fwd, fwdTarget, cfg.accel, cfg.brake, dt);
    state.side = onWheels ? 0 : approach(state.side, sideIn * top * 0.85, cfg.accel, cfg.brake, dt);
    if (onWheels && sideIn) {
      // Steering bites harder at speed, but you can still turn on the spot while pushing off.
      const grip = Math.min(1, 0.35 + Math.abs(state.fwd) / cfg.speed);
      euler.setFromQuaternion(camera.quaternion);
      euler.y -= sideIn * cfg.turn * grip * dt;
      camera.quaternion.setFromEuler(euler);
    }
    if (state.fwd) controls.moveForward(state.fwd * dt);
    if (state.side) controls.moveRight(state.side * dt);
    return Math.hypot(state.fwd, state.side) * dt;
  }

  /** Bumping into something solid bleeds speed instead of keeping full momentum. */
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
    /** Signed forward speed in m/s (for the speedometer). */
    get speed() {
      return state.fwd;
    },
  };
}
