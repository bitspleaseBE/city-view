/**
 * Pedestrian simulation: Mixamo humanoids walking sidewalk routes.
 * Loads GLB characters (Remy/Amy/James/Michelle/Aj + Walking) from ./characters/.
 * Falls back to simple capsule humanoids if assets fail to load.
 */
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { clone as cloneSkeleton } from "three/addons/utils/SkeletonUtils.js";

const CHARACTER_FILES = [
  "Remy_Walking.glb",
  "Amy_Walking.glb",
  "James_Walking.glb",
  "Michelle_Walking.glb",
  "Aj_Walking.glb",
];

export async function createPedestrians(scene, THREE, opts = {}) {
  const COUNT = opts.count || 40;
  const SPAWN_CENTER = opts.spawnCenter || { x: -218.5, z: -432.1 };
  const WALK_SPEED = 1.2; // m/s
  const BOBBLE_AMP = 0.02;
  const BOBBLE_FREQ = 9.0;

  const walkRoutes = buildWalkRoutes(SPAWN_CENTER);
  const templates = await loadCharacterTemplates(THREE);
  const useMixamo = templates.length > 0;

  const PROFILES = [
    {
      label: "family",
      spread: 2.2,
      members: [
        { bodyColor: 0x3a5068, legColor: 0x2a3040, topColor: 0x5a7a9a, scale: 1.05, hairColor: 0x3a2a1a },
        { bodyColor: 0x6a5a78, legColor: 0x3a4050, topColor: 0x9a7a8a, scale: 0.95, hairColor: 0x5a3a2a },
        { bodyColor: 0x4a6a8a, legColor: 0x304060, topColor: 0x7aaa6a, scale: 0.65, hairColor: 0xc4a040 },
        { bodyColor: 0x5a5a6a, legColor: 0x3a3a4a, topColor: 0xaa8a6a, scale: 0.55, hairColor: 0xc4a040 },
      ],
    },
    {
      label: "couple",
      spread: 1.4,
      members: [
        { bodyColor: 0x5a4a6a, legColor: 0x303848, topColor: 0x8a6a9a, scale: 1.0, hairColor: 0x1a0a0a },
        { bodyColor: 0x4a6a5a, legColor: 0x384048, topColor: 0x6a9a7a, scale: 0.95, hairColor: 0x8a6a3a },
      ],
    },
    {
      label: "single",
      spread: 0,
      members: [
        { bodyColor: 0x6a5a4a, legColor: 0x3a4048, topColor: 0x9a7a5a, scale: 1.0, hairColor: 0x4a3a2a },
      ],
    },
    {
      label: "group",
      spread: 2.8,
      members: [
        { bodyColor: 0x4a5a7a, legColor: 0x2a3848, topColor: 0x6a8aaa, scale: 1.05, hairColor: 0x2a1a0a },
        { bodyColor: 0x6a4a5a, legColor: 0x384050, topColor: 0x9a6a8a, scale: 0.95, hairColor: 0x8a5a3a },
        { bodyColor: 0x5a6a4a, legColor: 0x384840, topColor: 0x8a9a6a, scale: 1.0, hairColor: 0xc4a040 },
      ],
    },
    {
      label: "elderly",
      spread: 0.8,
      members: [
        { bodyColor: 0x6a6a78, legColor: 0x3a4048, topColor: 0x9a9aa8, scale: 0.9, hairColor: 0x8a8a8a },
        { bodyColor: 0x7a6a6a, legColor: 0x404848, topColor: 0xaa8a8a, scale: 0.9, hairColor: 0x9a8a7a },
      ],
    },
  ];

  function makeProceduralHumanoid(profile, groupId, memberIdx) {
    const group = new THREE.Group();
    group.userData = { groupId, memberIdx, baseY: 0, mixamo: false };
    const mat = (c) => new THREE.MeshLambertMaterial({ color: c });

    const torso = new THREE.Mesh(new THREE.CapsuleGeometry(0.22, 0.6, 4, 8), mat(profile.bodyColor));
    torso.position.y = 0.75;
    group.add(torso);

    const head = new THREE.Mesh(new THREE.SphereGeometry(0.15, 8, 8), mat(0xd4a882));
    head.position.y = 1.15;
    group.add(head);

    const hair = new THREE.Mesh(new THREE.SphereGeometry(0.13, 8, 4), new THREE.MeshLambertMaterial({ color: profile.hairColor || 0x3a2a1a }));
    hair.position.y = 1.28;
    group.add(hair);

    for (const sx of [-0.1, 0.1]) {
      const leg = new THREE.Mesh(new THREE.CapsuleGeometry(0.06, 0.55, 4, 6), mat(profile.legColor));
      leg.position.set(sx, 0.32, 0);
      group.add(leg);
    }
    for (const sx of [-0.25, 0.25]) {
      const arm = new THREE.Mesh(new THREE.CapsuleGeometry(0.04, 0.45, 4, 6), mat(profile.armColor || profile.topColor));
      arm.position.set(sx, 0.74, 0);
      group.add(arm);
    }
    const top = new THREE.Mesh(new THREE.CapsuleGeometry(0.2, 0.1, 4, 6), mat(profile.topColor));
    top.position.set(0, 0.85, 0.05);
    group.add(top);

    group.scale.setScalar(profile.scale);
    return group;
  }

  function makeMixamoHumanoid(profile, groupId, memberIdx) {
    const tmpl = templates[(Math.random() * templates.length) | 0];
    const root = cloneSkeleton(tmpl.scene);
    root.traverse((o) => {
      if (o.isMesh) {
        o.castShadow = true;
        o.receiveShadow = true;
        o.frustumCulled = true;
      }
    });

    // Normalize height to ~1.7m * profile.scale
    const box = new THREE.Box3().setFromObject(root);
    const size = new THREE.Vector3();
    box.getSize(size);
    const targetH = 1.7 * (profile.scale || 1);
    const s = size.y > 0.01 ? targetH / size.y : 1;
    root.scale.setScalar(s);

    // Feet on ground
    box.setFromObject(root);
    root.position.y -= box.min.y;

    const mixer = new THREE.AnimationMixer(root);
    let action = null;
    if (tmpl.clips.length) {
      // Prefer a clip named like Walk / Walking; else first clip
      const clip =
        tmpl.clips.find((c) => /walk/i.test(c.name)) ||
        tmpl.clips[0];
      action = mixer.clipAction(clip);
      action.enabled = true;
      action.setEffectiveTimeScale(1);
      action.setEffectiveWeight(1);
      action.play();
      action.time = Math.random() * clip.duration;
    }

    root.userData = { groupId, memberIdx, baseY: root.position.y, mixamo: true, mixer, action };
    return root;
  }

  function makeHumanoid(profile, groupId, memberIdx) {
    if (useMixamo) return makeMixamoHumanoid(profile, groupId, memberIdx);
    return makeProceduralHumanoid(profile, groupId, memberIdx);
  }

  function buildWalkRoutes(center) {
    const cx = center.x;
    const cz = center.z;
    return [
      { points: [{ x: cx - 16, z: cz }, { x: cx - 16, z: cz + 50 }, { x: cx - 16, z: cz + 100 }] },
      { points: [{ x: cx - 16, z: cz }, { x: cx - 16, z: cz - 50 }] },
      { points: [{ x: cx + 30, z: cz + 10 }, { x: cx + 60, z: cz + 10 }, { x: cx + 100, z: cz + 10 }] },
      { points: [{ x: cx - 40, z: cz + 10 }, { x: cx - 70, z: cz + 10 }, { x: cx - 100, z: cz + 10 }] },
      { points: [{ x: cx - 10, z: cz + 80 }, { x: cx, z: cz + 120 }, { x: cx + 20, z: cz + 150 }] },
      { points: [{ x: cx, z: cz + 15 }, { x: cx + 35, z: cz + 15 }] },
      { points: [{ x: cx - 20, z: cz - 20 }, { x: cx + 20, z: cz - 40 }, { x: cx + 40, z: cz - 60 }] },
    ];
  }

  function routePosition(route, s) {
    const pts = route.points;
    let cum = 0;
    for (let i = 0; i < pts.length - 1; i++) {
      const dx = pts[i + 1].x - pts[i].x;
      const dz = pts[i + 1].z - pts[i].z;
      const segLen = Math.hypot(dx, dz);
      if (s <= cum + segLen + 0.01) {
        const t = segLen > 0 ? (s - cum) / segLen : 0;
        return { x: pts[i].x + dx * t, z: pts[i].z + dz * t, idx: i, t };
      }
      cum += segLen;
    }
    const last = pts[pts.length - 1];
    return { x: last.x, z: last.z, idx: pts.length - 2, t: 1 };
  }

  function routeLength(route) {
    let len = 0;
    for (let i = 0; i < route.points.length - 1; i++) {
      len += Math.hypot(route.points[i + 1].x - route.points[i].x, route.points[i + 1].z - route.points[i].z);
    }
    return len;
  }

  function spawnGroup(profiles, routes) {
    const prof = profiles[(Math.random() * profiles.length) | 0];
    const route = routes[(Math.random() * routes.length) | 0];
    const rLen = routeLength(route);
    const startS = Math.random() * Math.max(1, rLen - 4);
    const dir = Math.random() < 0.5 ? 1 : -1;
    const side = (Math.random() < 0.5 ? -1 : 1) * (1.2 + Math.random() * 0.8);

    const members = [];
    for (let mi = 0; mi < prof.members.length; mi++) {
      const mProf = prof.members[mi];
      const mesh = makeHumanoid(mProf, groups.length, mi);
      const offset = mi * prof.spread / (prof.members.length - 1 || 1) - prof.spread * 0.5;
      const speed = WALK_SPEED * (0.8 + Math.random() * 0.4);
      // Sync walk-cycle playback rate to travel speed (~1.2 m/s baseline)
      if (mesh.userData.action) {
        mesh.userData.action.setEffectiveTimeScale(speed / WALK_SPEED);
      }
      members.push({
        mesh,
        routeIdx: routes.indexOf(route),
        s: startS + offset * 0.15,
        dir,
        side,
        phase: Math.random() * Math.PI * 2,
        speed,
        prof: mProf,
      });
    }
    return { members, routeIdx: routes.indexOf(route), route };
  }

  const root = new THREE.Group();
  root.name = "Pedestrians";
  scene.add(root);

  const groups = [];
  for (let i = 0; i < COUNT; i++) {
    const g = spawnGroup(PROFILES, walkRoutes);
    for (const m of g.members) root.add(m.mesh);
    groups.push(g);
  }

  for (const g of groups) {
    for (const m of g.members) {
      const route = walkRoutes[m.routeIdx];
      const rLen = routeLength(route);
      m.s = ((m.s % rLen) + rLen) % rLen;
      const pos = routePosition(route, m.s);
      const baseY = m.mesh.userData.baseY || 0;
      m.mesh.position.set(pos.x + m.side, baseY, pos.z);
      const dx = route.points[Math.min(pos.idx + 1, route.points.length - 1)].x - route.points[pos.idx].x;
      const dz = route.points[Math.min(pos.idx + 1, route.points.length - 1)].z - route.points[pos.idx].z;
      m.mesh.rotation.y = Math.atan2(dx, dz) + (m.dir < 0 ? Math.PI : 0);
    }
  }

  console.info(
    `[cityview] pedestrians: ${groups.reduce((n, g) => n + g.members.length, 0)} people` +
      (useMixamo ? ` (Mixamo ×${templates.length})` : " (procedural fallback)")
  );

  function update(dt) {
    if (!(dt > 0)) return;
    for (const g of groups) {
      const route = walkRoutes[g.routeIdx];
      const rLen = routeLength(route);
      for (const m of g.members) {
        m.s += m.speed * m.dir * dt;
        if (m.s >= rLen) {
          m.s = Math.max(0, rLen - (m.s - rLen));
          m.dir = -m.dir;
          if (Math.random() < 0.003) {
            const nr = walkRoutes[(Math.random() * walkRoutes.length) | 0];
            m.routeIdx = walkRoutes.indexOf(nr);
            m.s = Math.random() * routeLength(nr) * 0.8;
          }
        } else if (m.s < 0) {
          m.s = Math.min(rLen, -m.s);
          m.dir = -m.dir;
        }

        const liveRoute = walkRoutes[m.routeIdx];
        const liveLen = routeLength(liveRoute);
        const pos = routePosition(liveRoute, m.s);
        const baseY = m.mesh.userData.baseY || 0;
        m.mesh.position.x = pos.x + m.side;
        m.mesh.position.z = pos.z;

        if (m.mesh.userData.mixer) {
          m.mesh.userData.mixer.update(dt);
          m.mesh.position.y = baseY;
        } else {
          m.phase += dt * m.speed * BOBBLE_FREQ;
          m.mesh.position.y = baseY + BOBBLE_AMP * Math.abs(Math.sin(m.phase));
          const swingAmt = 0.2 * Math.sin(m.phase);
          for (let ci = 0; ci < m.mesh.children.length; ci++) {
            const child = m.mesh.children[ci];
            if (Math.abs(child.position.x) > 0.2 && child.position.y > 0.6) {
              child.rotation.z = child.position.x > 0 ? -swingAmt : swingAmt;
            }
          }
        }

        const aheadS = Math.min(liveLen, Math.max(0, m.s + m.dir * 0.5));
        const aheadPos = routePosition(liveRoute, aheadS);
        const dx = aheadPos.x - pos.x;
        const dz = aheadPos.z - pos.z;
        if (Math.abs(dx) > 0.01 || Math.abs(dz) > 0.01) {
          m.mesh.rotation.y = Math.atan2(dx, dz);
        }
      }
    }
  }

  function dispose() {
    scene.remove(root);
    for (const g of groups) {
      for (const m of g.members) {
        if (m.mesh.userData.mixer) m.mesh.userData.mixer.stopAllAction();
      }
    }
  }

  return { update, dispose, groups, mixamo: useMixamo };
}

async function loadCharacterTemplates(THREE) {
  const loader = new GLTFLoader();
  const base = new URL("./characters/", import.meta.url);
  const out = [];
  await Promise.all(
    CHARACTER_FILES.map(async (file) => {
      try {
        const url = new URL(file, base).href;
        const gltf = await loader.loadAsync(url);
        // Keep template off-scene; clones will be added later
        gltf.scene.traverse((o) => {
          if (o.isMesh) {
            o.castShadow = true;
            o.receiveShadow = true;
          }
        });
        out.push({ name: file, scene: gltf.scene, clips: gltf.animations || [] });
      } catch (err) {
        console.warn(`[cityview] Mixamo load failed: ${file}`, err);
      }
    })
  );
  return out;
}
