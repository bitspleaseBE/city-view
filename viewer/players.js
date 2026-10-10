/**
 * Playable cast for Klein Antwerpen. Separate from sidewalk Mixamo civilians
 * in characters.js — these three bodies never enter the pedestrian pool.
 */
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { clone as cloneSkeleton } from "three/addons/utils/SkeletonUtils.js";

export const PLAYERS = [
  {
    id: "pieter",
    name: "Pieter",
    blurb: "Antwerp boy. Jacket, jeans, and the killer smile.",
  },
  {
    id: "mo",
    name: "Mo",
    blurb: "Youthful rascal. Grey hoodie, sneakers, and grit.",
  },
  {
    id: "jacob",
    name: "Jacob",
    blurb: "Traditional and kind. Black coat, white shirt, black hat.",
  },
];

const STORAGE_KEY = "metropolis-player";
const base = new URL("./characters/players/", import.meta.url);
const loader = new GLTFLoader();
const cache = new Map();

function load(path) {
  let p = cache.get(path);
  if (!p) {
    p = loader.loadAsync(new URL(path, base).href);
    cache.set(path, p);
  }
  return p;
}

export function getStoredPlayerId() {
  try {
    const id = localStorage.getItem(STORAGE_KEY);
    if (PLAYERS.some((p) => p.id === id)) return id;
  } catch {
    /* ignore */
  }
  return PLAYERS[0].id;
}

export function setStoredPlayerId(id) {
  if (!PLAYERS.some((p) => p.id === id)) return;
  try {
    localStorage.setItem(STORAGE_KEY, id);
  } catch {
    /* ignore */
  }
}

export function playerById(id) {
  return PLAYERS.find((p) => p.id === id) || PLAYERS[0];
}

/** Walk mesh only. Ride and scooter clips load the first time that character uses them. */
export function preloadPlayer(id = getStoredPlayerId()) {
  return load(`${id}_Walking.glb`);
}

/**
 * Third-person player avatar: walk / ride / scooter clips, with grip IK on wheels.
 */
export function createPlayerAvatar(THREE, scene) {
  let root = new THREE.Group();
  root.name = "player-avatar";
  scene.add(root);

  let visual = null;
  let mixer = null;
  let actions = { walk: null, ride: null, scooter: null };
  let current = null;
  let playerId = getStoredPlayerId();
  let facing = 0;
  let ready = Promise.resolve();
  let built = false;
  let buildGen = 0;
  let clipLoads = { ride: null, scooter: null };
  /** @type {null | { lUpper: object, lFore: object, lHand: object, rUpper: object, rFore: object, rHand: object }} */
  let armBones = null;

  // Grip targets match viewer/scooters.js + viewer/velo.js (bike scale 1.55).
  const GRIP = {
    scooter: { fwd: 0.18, y: 1.17, z: -0.26, x: 0.22 },
    velo: { fwd: 0.15, y: 0.67 * 1.55, z: -0.3 * 1.55, x: 0.2 * 1.55 },
  };
  const _gripL = new THREE.Vector3();
  const _gripR = new THREE.Vector3();
  const _ikA = new THREE.Vector3();
  const _ikB = new THREE.Vector3();
  const _ikC = new THREE.Vector3();
  const _ikQ = new THREE.Quaternion();
  const _ikParentQ = new THREE.Quaternion();
  const _ikWorldQ = new THREE.Quaternion();

  /**
   * Older Mixamo player GLBs shipped at FBX scale ~0.0001. Current Rocketbox
   * cast (Pieter / Mo / Jacob) is already ~0.01 — only bump when still tiny.
   */
  function normalizeImportScale(root) {
    if (!root) return false;
    let fixed = false;
    for (const name of ["Bip01", "Armature"]) {
      const o = root.getObjectByName(name);
      if (o && o.scale.x > 0 && o.scale.x < 0.001) {
        o.scale.setScalar(0.01);
        fixed = true;
      }
    }
    return fixed;
  }

  /** Drop scale tracks — FBX often keys identity scale and fights normalizeImportScale. */
  function sanitizeClip(clip) {
    if (!clip?.tracks?.length) return clip;
    const tracks = clip.tracks.filter((t) => !t.name.endsWith(".scale"));
    if (tracks.length === clip.tracks.length) return clip;
    return new THREE.AnimationClip(clip.name, clip.duration, tracks);
  }

  // Reused each frame for Mixamo thigh-lift polish.
  const _qLift = new THREE.Quaternion();
  const _vBone = new THREE.Vector3();

  /**
   * After the mixer: boost Mixamo hip flexion so steps read as thigh-led.
   * Rocketbox arms/legs are corrected in scripts/rocketbox_to_player_glb.py
   * (weight repair + arm tuck + world-space bake) — do not double-tuck here.
   */
  function polishWalkPose(rig, walkPhase, moving) {
    if (!rig || !moving) return;
    const swing = Math.sin(walkPhase);
    // Legacy Mixamo UpLeg polish (only if a Mixamo-skinned player GLB is loaded).
    const thighPairs = [
      ["mixamorig9LeftUpLeg", 1, -1, 0, 0],
      ["mixamorig9RightUpLeg", -1, 1, 0, 0],
    ];
    const liftAmp = 0.5;
    for (const [name, side, ax, ay, az] of thighPairs) {
      const bone = rig.getObjectByName(name);
      if (!bone) continue;
      const lift = liftAmp * Math.max(0, side * swing);
      if (lift < 1e-4) continue;
      _qLift.setFromAxisAngle(_vBone.set(ax, ay, az), lift);
      bone.quaternion.premultiply(_qLift);
    }
  }

  function cacheArmBones(rig) {
    armBones = {
      lUpper: findNamed(rig, "Bip01_L_UpperArm", "Bip01 L UpperArm", "LeftArm", "mixamorigLeftArm"),
      lFore: findNamed(rig, "Bip01_L_Forearm", "Bip01 L Forearm", "LeftForeArm", "mixamorigLeftForeArm"),
      lHand: findNamed(rig, "Bip01_L_Hand", "Bip01 L Hand", "LeftHand", "mixamorigLeftHand"),
      rUpper: findNamed(rig, "Bip01_R_UpperArm", "Bip01 R UpperArm", "RightArm", "mixamorigRightArm"),
      rFore: findNamed(rig, "Bip01_R_Forearm", "Bip01 R Forearm", "RightForeArm", "mixamorigRightForeArm"),
      rHand: findNamed(rig, "Bip01_R_Hand", "Bip01 R Hand", "RightHand", "mixamorigRightHand"),
    };
  }

  /** World-space grip point matching scooter/velo mesh placement under the player. */
  function gripTarget(out, yaw, side, cfg) {
    const ox = -Math.sin(yaw) * cfg.fwd;
    const oz = -Math.cos(yaw) * cfg.fwd;
    const lx = side * cfg.x;
    const lz = cfg.z;
    const c = Math.cos(yaw);
    const s = Math.sin(yaw);
    out.set(
      root.position.x + ox + lx * c + lz * s,
      root.position.y + cfg.y,
      root.position.z + oz - lx * s + lz * c,
    );
    return out;
  }

  /** CCD two-bone IK so the wrist reaches the handlebar grip. */
  function ccdArmIK(upper, fore, hand, target, iterations = 10) {
    if (!upper?.parent || !fore || !hand) return;
    const chain = [upper, fore];
    for (let iter = 0; iter < iterations; iter++) {
      for (let i = chain.length - 1; i >= 0; i--) {
        const bone = chain[i];
        bone.updateWorldMatrix(true, true);
        hand.updateWorldMatrix(true, false);
        _ikA.setFromMatrixPosition(bone.matrixWorld);
        _ikB.setFromMatrixPosition(hand.matrixWorld);
        _ikB.sub(_ikA);
        if (_ikB.lengthSq() < 1e-10) continue;
        _ikB.normalize();
        _ikC.copy(target).sub(_ikA);
        if (_ikC.lengthSq() < 1e-10) continue;
        _ikC.normalize();
        _ikQ.setFromUnitVectors(_ikB, _ikC);
        bone.parent.getWorldQuaternion(_ikParentQ);
        bone.getWorldQuaternion(_ikWorldQ);
        _ikWorldQ.premultiply(_ikQ);
        bone.quaternion.copy(_ikParentQ).invert().multiply(_ikWorldQ);
        bone.updateMatrixWorld(true);
      }
    }
  }

  function polishRideGrips(kind, yaw) {
    if (!armBones || (kind !== "velo" && kind !== "scooter")) return;
    const cfg = GRIP[kind];
    if (!cfg) return;
    gripTarget(_gripL, yaw, -1, cfg);
    gripTarget(_gripR, yaw, 1, cfg);
    ccdArmIK(armBones.lUpper, armBones.lFore, armBones.lHand, _gripL);
    ccdArmIK(armBones.rUpper, armBones.rFore, armBones.rHand, _gripR);
  }

  /** Rocketbox Bip01_* or Mixamo mixamorig9:Head etc. */
  function findNamed(root, ...suffixes) {
    for (const s of suffixes) {
      const exact = root.getObjectByName(s);
      if (exact) return exact;
    }
    let found = null;
    const want = suffixes.map((s) =>
      s.toLowerCase().replace(/^mixamorig\d*:/, "").replace(/^mixamorig:?/, "")
    );
    root.traverse((o) => {
      if (found) return;
      const n = (o.name || "")
        .toLowerCase()
        .replace(/^mixamorig\d*:/, "")
        .replace(/^mixamorig:?/, "")
        .replace(/^bip01[_\s]?/, "");
      if (want.includes(n) || want.includes(`bip01_${n}`) || want.includes(n.replace(/\s/g, "_")))
        found = o;
    });
    return found;
  }

  function ensureClip(kind) {
    if (actions[kind] || clipLoads[kind]) return;
    const id = playerId;
    const gen = buildGen;
    const file = kind === "ride" ? "Riding" : "Scooter";
    clipLoads[kind] = load(`${id}_${file}.glb`)
      .then((gltf) => {
        if (gen !== buildGen || !mixer || !gltf?.animations?.length) return;
        const clip = sanitizeClip(gltf.animations[0]);
        if (!clip || clip.duration < 1e-3) return;
        const action = mixer.clipAction(clip);
        action.enabled = true;
        action.setEffectiveWeight(0);
        action.setLoop(THREE.LoopRepeat, Infinity);
        actions[kind] = action;
      })
      .catch(() => {});
  }

  async function build(id) {
    const gen = ++buildGen;
    clipLoads = { ride: null, scooter: null };
    const walkGltf = await load(`${id}_Walking.glb`);
    if (gen !== buildGen) return;

    if (visual) {
      root.remove(visual);
      visual.traverse((o) => {
        if (o.isMesh) {
          o.geometry?.dispose?.();
          const mats = Array.isArray(o.material) ? o.material : [o.material];
          for (const m of mats) m?.dispose?.();
        }
      });
      visual = null;
      armBones = null;
    }
    mixer = null;
    actions = { walk: null, ride: null, scooter: null };
    current = null;

    visual = cloneSkeleton(walkGltf.scene);
    // Drop stray Rocketbox helpers (e.g. Icosphere) that break bounds / grounding.
    const drop = [];
    visual.traverse((o) => {
      if (!o.isMesh) return;
      const n = (o.name || "").toLowerCase();
      if (n.includes("ico") || n.includes("sphere")) drop.push(o);
    });
    for (const o of drop) o.parent?.remove(o);
    visual.traverse((o) => {
      if (o.isMesh) {
        o.castShadow = true;
        o.receiveShadow = true;
        o.frustumCulled = false;
      }
    });
    normalizeImportScale(visual);
    visual.updateMatrixWorld(true);

    const targetH = 1.72;
    const head = findNamed(
      visual,
      "Bip01_Head",
      "Bip01 Head",
      "Head",
      "mixamorigHead",
      "mixamorig:Head"
    );
    const foot = findNamed(
      visual,
      "Bip01_L_Foot",
      "Bip01 L Foot",
      "Bip01_R_Foot",
      "LeftFoot",
      "mixamorigLeftFoot",
      "mixamorig:LeftFoot"
    );
    let measureY = 0;
    if (head && foot) {
      head.updateWorldMatrix(true, false);
      foot.updateWorldMatrix(true, false);
      measureY = Math.abs(head.matrixWorld.elements[13] - foot.matrixWorld.elements[13]);
    }
    if (measureY < 0.2) {
      const box = new THREE.Box3().setFromObject(visual);
      measureY = box.max.y - box.min.y;
    }
    // Pedestrian loader uses >0.01; the old >0.3 gate left Mixamo James at 1.8 cm.
    const s = measureY > 0.01 ? targetH / measureY : 1;
    visual.scale.setScalar(s);
    // Player motion with yaw=0 walks toward −Z (camera on +Z). All three meshes
    // face +Z in bind pose, so every avatar needs the half-turn.
    visual.rotation.y = Math.PI;
    visual.updateMatrixWorld(true);
    if (foot) {
      foot.updateWorldMatrix(true, false);
      visual.position.y -= foot.matrixWorld.elements[13] - root.position.y;
    } else {
      const box = new THREE.Box3().setFromObject(visual);
      if (Number.isFinite(box.min.y)) visual.position.y -= box.min.y;
    }

    mixer = new THREE.AnimationMixer(visual);
    const walkClipRaw =
      walkGltf.animations.find((c) => /walk/i.test(c.name)) || walkGltf.animations[0];
    const walkClip = walkClipRaw ? sanitizeClip(walkClipRaw) : null;
    if (walkClip) {
      actions.walk = mixer.clipAction(walkClip);
      actions.walk.enabled = true;
      actions.walk.setEffectiveWeight(1);
      actions.walk.play();
      current = "walk";
    }

    root.add(visual);
    cacheArmBones(visual);
    playerId = id;
    // A ride clip that resolved against the previous body must be fetched again.
    clipLoads = { ride: null, scooter: null };
  }

  function setAction(name) {
    if (name === current) return;
    const next = actions[name];
    const prev = current ? actions[current] : null;
    if (!next) return;
    next.reset().fadeIn(0.2).play();
    if (prev && prev !== next) prev.fadeOut(0.2);
    current = name;
  }

  function start() {
    if (!built) {
      built = true;
      ready = build(playerId);
    }
    return ready;
  }

  return {
    root,
    get playerId() {
      return playerId;
    },
    get facing() {
      return facing;
    },
    ready: () => start(),
    async setPlayer(id) {
      if (id === playerId && visual) return;
      setStoredPlayerId(id);
      playerId = id;
      built = true;
      ready = build(id);
      await ready;
    },
    /**
     * @param {number} dt
     * @param {{ x: number, y?: number, z: number }} pos  xz world; y = eye height (≈1.7 on ground)
     * @param {number} moveSpeed  m/s forward magnitude
     * @param {number} targetYaw  body facing (Three Y)
     * @param {"walk"|"velo"|"scooter"} kind
     */
    update(dt, pos, moveSpeed, targetYaw, kind = "walk") {
      if (!visual) return;
      root.position.x = pos.x;
      root.position.z = pos.z;
      // Walker stores eye height; feet sit eye−1.7 (jump lifts both).
      const eye = 1.7;
      root.position.y = Number.isFinite(pos.y) ? Math.max(0, pos.y - eye) : 0;

      const dy = Math.atan2(Math.sin(targetYaw - facing), Math.cos(targetYaw - facing));
      facing += dy * (1 - Math.exp(-20 * dt));
      root.rotation.y = facing;

      if (kind === "velo") {
        if (actions.ride) setAction("ride");
        else ensureClip("ride");
      } else if (kind === "scooter") {
        if (actions.scooter) setAction("scooter");
        else ensureClip("scooter");
      } else setAction("walk");

      if (actions.walk && current === "walk") {
        // Hang the stride briefly in the air so a hop reads like GTA, not a mid-walk freeze-frame.
        const airborne = root.position.y > 0.06;
        // Cap high enough for Shift jog (~7.4 m/s) so legs don't skate under a slow cycle.
        const scale = airborne
          ? 0.12
          : Math.max(0.05, Math.min(3.2, Math.abs(moveSpeed) / 1.7));
        actions.walk.setEffectiveTimeScale(airborne ? scale : Math.abs(moveSpeed) < 0.08 ? 0 : scale);
      } else if (actions.ride && current === "ride") {
        actions.ride.setEffectiveTimeScale(Math.max(0.2, Math.min(1.8, Math.abs(moveSpeed) / 4)));
      } else if (actions.scooter && current === "scooter") {
        actions.scooter.setEffectiveTimeScale(Math.max(0.2, Math.min(1.8, Math.abs(moveSpeed) / 3.5)));
      }

      if (mixer) mixer.update(dt);
      // Walk clips re-assert the tiny FBX armature scale after mixer.update.
      normalizeImportScale(visual);
      if (current === "walk" && actions.walk) {
        const dur = actions.walk.getClip()?.duration || 1;
        const phase = (actions.walk.time / dur) * Math.PI * 2;
        polishWalkPose(visual, phase, Math.abs(moveSpeed) >= 0.08);
      } else if (kind === "velo" || kind === "scooter") {
        // Ride clips don't put Rocketbox/Mixamo wrists on the bars — IK does.
        visual.updateMatrixWorld(true);
        polishRideGrips(kind, targetYaw);
      }
      root.visible = true;
    },
    setVisible(v) {
      root.visible = !!v;
    },
  };
}
