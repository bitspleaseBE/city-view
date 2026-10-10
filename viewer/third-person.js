/**
 * Third-person boom camera: look is instant, boom position lags, looks along the
 * aim ray (crosshair stays screen-center), pulls in when a building blocks the boom.
 */

export function createThirdPersonCamera(THREE, camera, getOutdoors = () => null) {
  const lookYaw = { value: 0 };
  const lookPitch = { value: 0.14 };
  const desired = new THREE.Vector3();
  const aimDir = new THREE.Vector3();
  const camPos = new THREE.Vector3();
  const chest = new THREE.Vector3();
  const probe = new THREE.Vector3();

  const DIST = 4.4;
  const SIDE = 0.3;
  const FOV_WALK = 58;
  const FOV_TIGHT = 48;
  const PITCH_MIN = -0.5;
  const PITCH_MAX = 0.72;
  const LOOK_X = 0.0025;
  const LOOK_Y = 0.002;

  let fov = FOV_WALK;
  let snapped = false;

  function applyLook(dx, dy) {
    lookYaw.value -= dx * LOOK_X;
    lookPitch.value = Math.max(PITCH_MIN, Math.min(PITCH_MAX, lookPitch.value + dy * LOOK_Y));
  }

  function setYaw(y) {
    lookYaw.value = y;
  }

  function yaw() {
    return lookYaw.value;
  }

  function pitch() {
    return lookPitch.value;
  }

  /** Desired boom position behind the player (world). */
  function desiredPosition(playerPos, yEye = 1.45) {
    const yaw = lookYaw.value;
    const pitch = lookPitch.value;
    const o = DIST;
    const a = SIDE;
    desired.set(
      playerPos.x + Math.sin(yaw) * o + Math.cos(yaw) * a,
      Math.max(0.45, yEye + Math.sin(pitch) * o),
      playerPos.z + Math.cos(yaw) * o - Math.sin(yaw) * a,
    );
    return desired;
  }

  /**
   * If the boom would sit inside a building, binary-search back toward the chest.
   */
  function clearBoom(from, to) {
    const outdoors = typeof getOutdoors === "function" ? getOutdoors() : getOutdoors;
    if (!outdoors || !outdoors.insideBuilding) return to;
    if (!outdoors.insideBuilding(to.x, to.z)) return to;
    let lo = 0;
    let hi = 1;
    const clear = probe;
    for (let i = 0; i < 12; i++) {
      const mid = (lo + hi) / 2;
      clear.set(
        from.x + (to.x - from.x) * mid,
        from.y + (to.y - from.y) * mid,
        from.z + (to.z - from.z) * mid,
      );
      if (outdoors.insideBuilding(clear.x, clear.z)) hi = mid;
      else lo = mid;
    }
    to.set(
      from.x + (to.x - from.x) * lo,
      from.y + (to.y - from.y) * lo,
      from.z + (to.z - from.z) * lo,
    );
    return to;
  }

  /**
   * @param {number} dt
   * @param {{ x: number, y?: number, z: number }} playerPos
   * @param {{ tight?: boolean }} [opts]
   */
  function update(dt, playerPos, opts = {}) {
    const tight = !!opts.tight;
    // Player root stores eye height (~1.7 on ground). Lift the boom with jumps.
    const eye = 1.7;
    const lift = Number.isFinite(playerPos.y) ? Math.max(0, playerPos.y - eye) : 0;
    chest.set(playerPos.x, 1.45 + lift, playerPos.z);
    desiredPosition(playerPos, chest.y);
    clearBoom(chest, desired);

    if (!snapped) {
      camPos.copy(desired);
      snapped = true;
    } else {
      const k = 1 - Math.exp(-12 * dt);
      camPos.lerp(desired, k);
    }

    aimDir.set(
      -Math.sin(lookYaw.value) * Math.cos(lookPitch.value),
      -Math.sin(lookPitch.value),
      -Math.cos(lookYaw.value) * Math.cos(lookPitch.value),
    );

    camera.position.copy(camPos);
    camera.up.set(0, 1, 0);
    camera.lookAt(camPos.x + aimDir.x * 30, camPos.y + aimDir.y * 30, camPos.z + aimDir.z * 30);

    const targetFov = tight ? FOV_TIGHT : FOV_WALK;
    fov += (targetFov - fov) * (1 - Math.exp(-8 * dt));
    if (Math.abs(camera.fov - fov) > 0.05) {
      camera.fov = fov;
      camera.updateProjectionMatrix();
    }
  }

  function snap(playerPos) {
    snapped = false;
    update(1 / 60, playerPos);
    snapped = true;
  }

  /**
   * Ease camera yaw toward a vehicle heading (wheels face one way; look can drift).
   * Heading is the direction of travel on XZ (atan2 style matching playerMotion.yaw).
   */
  function easeYawToward(heading, dt, lambda = 3) {
    const target = heading;
    const dy = Math.atan2(Math.sin(target - lookYaw.value), Math.cos(target - lookYaw.value));
    lookYaw.value += dy * (1 - Math.exp(-lambda * dt));
  }

  return {
    applyLook,
    setYaw,
    yaw,
    pitch,
    update,
    snap,
    easeYawToward,
    DIST,
    SIDE,
  };
}
