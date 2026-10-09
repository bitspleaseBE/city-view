/**
 * Pedestrian simulation: humanoids walking on sidewalks and crosswalks.
 * People appear in groups (families, couples, singles) and walk naturally.
 * Uses simple articulated geometry (no Mixamo yet — humanoid capsules with limb hints).
 */
export async function createPedestrians(scene, THREE, opts = {}) {
  const COUNT = opts.count || 40;
  const SPAWN_CENTER = opts.spawnCenter || { x: -218.5, z: -432.1 };
  const PLAY_BOUNDS = opts.playBounds || { minX: -500, maxX: 200, minZ: -800, maxZ: 100 };
  const WALK_SPEED = 1.2; // m/s, comfortable stroll
  const BOBBLE_AMP = 0.04; // vertical bob per step
  const BOBBLE_FREQ = 9.0;
  const STEP_LEN = 0.65;

  // Seed along a few known sidewalk corridors near the Gounod halt.
  // Each route is {points: [{x,z},...], side: -1|1 for lane offset}
  const walkRoutes = buildWalkRoutes(SPAWN_CENTER);

  // ----- Group types with unique profiles -----
  const PROFILES = [
    // { members: [{bodyColor, legColor, topColor, scale, hairColor}, ...], groupSpread: m, label }
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
    {
      label: "cyclist",
      spread: 0.3,
      members: [
        { bodyColor: 0xcc4444, legColor: 0x222244, topColor: 0xeeeeee, scale: 1.0, hairColor: 0x3a2a1a },
      ],
    },
  ];

  // ---- Create humanoid mesh with simple articulated limbs ----
  function makeHumanoid(THREE, profile, groupId, memberIdx) {
    const group = new THREE.Group();
    group.userData = { groupId, memberIdx, baseY: 0 };
    const mat = (c) => new THREE.MeshLambertMaterial({ color: c });

    // Body (torso)
    const torsoMat = mat(profile.bodyColor);
    const torso = new THREE.Mesh(new THREE.CapsuleGeometry(0.22, 0.6, 4, 8), torsoMat);
    torso.position.y = 0.75;
    group.add(torso);

    // Head
    const headMat = mat(0xd4a882); // skin
    const head = new THREE.Mesh(new THREE.SphereGeometry(0.15, 8, 8), headMat);
    head.position.y = 1.15;
    group.add(head);

    // Hair hint
    const hairMat = new THREE.MeshLambertMaterial({ color: profile.hairColor || 0x3a2a1a });
    const hair = new THREE.Mesh(new THREE.SphereGeometry(0.13, 8, 4), hairMat);
    hair.position.y = 1.28;
    group.add(hair);

    // Legs (simple capsules)
    const legMat = mat(profile.legColor);
    for (const sx of [-0.1, 0.1]) {
      const leg = new THREE.Mesh(new THREE.CapsuleGeometry(0.06, 0.55, 4, 6), legMat);
      leg.position.set(sx, 0.32, 0);
      group.add(leg);
    }

    // Arms (simple cylinders) - will be animated per frame
    const armMat = mat(profile.armColor || profile.topColor);
    for (const sx of [-0.25, 0.25]) {
      const arm = new THREE.Mesh(new THREE.CapsuleGeometry(0.04, 0.45, 4, 6), armMat);
      arm.position.set(sx, 0.74, 0);
      group.add(arm);
    }

    // Top/clothing detail
    const topMat = mat(profile.topColor);
    const top = new THREE.Mesh(new THREE.CapsuleGeometry(0.2, 0.1, 4, 6), topMat);
    top.position.set(0, 0.85, 0.05);
    group.add(top);

    group.scale.setScalar(profile.scale);
    return group;
  }

  // ---- Build a few walkable routes around the spawn ----
  function buildWalkRoutes(center) {
    const r = 140;
    const cx = center.x;
    const cz = center.z;
    // A set of sidewalk paths: points roughly on the pavement near roads
    return [
      // Gounodstraat (north-south near spawn)
      { points: [{ x: cx - 16, z: cz }, { x: cx - 16, z: cz + 50 }, { x: cx - 16, z: cz + 100 }] },
      { points: [{ x: cx - 16, z: cz }, { x: cx - 16, z: cz - 50 }] },
      // Mechelsesteenweg (east-west boulevard) — both sides
      { points: [{ x: cx + 30, z: cz + 10 }, { x: cx + 60, z: cz + 10 }, { x: cx + 100, z: cz + 10 }] },
      { points: [{ x: cx - 40, z: cz + 10 }, { x: cx - 70, z: cz + 10 }, { x: cx - 100, z: cz + 10 }] },
      // Side street to the north
      { points: [{ x: cx - 10, z: cz + 80 }, { x: cx, z: cz + 120 }, { x: cx + 20, z: cz + 150 }] },
      // Crosswalk area
      { points: [{ x: cx, z: cz + 15 }, { x: cx + 35, z: cz + 15 }] },
      // Diagonal path through the square
      { points: [{ x: cx - 20, z: cz - 20 }, { x: cx + 20, z: cz - 40 }, { x: cx + 40, z: cz - 60 }] },
    ];
  }

  // ---- Pick a random point along any route ----
  function randomRoutePoint(routes) {
    const route = routes[(Math.random() * routes.length) | 0];
    const pts = route.points;
    let i = 0;
    let cum = 0;
    const total = pts.length - 1;
    const seg = Math.random() * total;
    i = Math.floor(seg);
    const t = seg - i;
    const a = pts[i];
    const b = pts[Math.min(i + 1, pts.length - 1)];
    return {
      x: a.x + (b.x - a.x) * t,
      z: a.z + (b.z - a.z) * t,
      routeIdx: routes.indexOf(route),
      pIdx: i,
      frac: t,
    };
  }

  // ---- Pick a random position along the chosen route ----
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

  // ---- Total length of a route ----
  function routeLength(route) {
    let len = 0;
    for (let i = 0; i < route.points.length - 1; i++) {
      len += Math.hypot(route.points[i + 1].x - route.points[i].x, route.points[i + 1].z - route.points[i].z);
    }
    return len;
  }

  // ---- Place a group on a random route ----
  function spawnGroup(profiles, routes) {
    const prof = profiles[(Math.random() * profiles.length) | 0];
    const route = routes[(Math.random() * routes.length) | 0];
    const rLen = routeLength(route);
    const startS = Math.random() * Math.max(1, rLen - 4);
    const dir = Math.random() < 0.5 ? 1 : -1;
    const side = (Math.random() < 0.5 ? -1 : 1) * (1.2 + Math.random() * 0.8); // sidewalk offset

    const members = [];
    for (let mi = 0; mi < prof.members.length; mi++) {
      const mProf = prof.members[mi];
      const mesh = makeHumanoid(THREE, mProf, groups.length, mi);
      const offset = mi * prof.spread / (prof.members.length - 1 || 1) - prof.spread * 0.5;
      members.push({
        mesh,
        routeIdx: routes.indexOf(route),
        s: startS + offset * 0.15,
        dir,
        side,
        phase: Math.random() * Math.PI * 2, // walk cycle phase
        speed: WALK_SPEED * (0.8 + Math.random() * 0.4),
        prof: mProf,
      });
    }
    return { members, routeIdx: routes.indexOf(route), route };
  }

  // ---- Create the pedestrian world ----
  const root = new THREE.Group();
  root.name = "Pedestrians";
  scene.add(root);

  const groups = [];
  for (let i = 0; i < COUNT; i++) {
    const g = spawnGroup(PROFILES, walkRoutes);
    for (const m of g.members) {
      root.add(m.mesh);
    }
    groups.push(g);
  }

  // Initial placement
  for (const g of groups) {
    for (const m of g.members) {
      const route = walkRoutes[m.routeIdx];
      const rLen = routeLength(route);
      m.s = ((m.s % rLen) + rLen) % rLen;
      const pos = routePosition(route, m.s);
      m.mesh.position.set(pos.x + m.side, 0, pos.z);
      // Face direction of travel
      const dx = route.points[Math.min(pos.idx + 1, route.points.length - 1)].x - route.points[pos.idx].x;
      const dz = route.points[Math.min(pos.idx + 1, route.points.length - 1)].z - route.points[pos.idx].z;
      const angle = Math.atan2(dx, dz) + (m.dir < 0 ? Math.PI : 0);
      m.mesh.rotation.y = angle;
    }
  }

  // ---- Update per frame ----
  function update(dt) {
    if (!(dt > 0)) return;
    const step = dt;
    for (const g of groups) {
      const route = walkRoutes[g.routeIdx];
      const rLen = routeLength(route);
      for (const m of g.members) {
        m.s += m.speed * m.dir * step;
        // Wrap at ends
        if (m.s >= rLen) {
          m.s = Math.max(0, rLen - (m.s - rLen));
          m.dir = -m.dir;
          // Random chance to change route
          if (Math.random() < 0.003) {
            const nr = walkRoutes[(Math.random() * walkRoutes.length) | 0];
            m.routeIdx = walkRoutes.indexOf(nr);
            // Recalculate s on new route
            const nLen = routeLength(nr);
            m.s = Math.random() * nLen * 0.8;
          }
        } else if (m.s < 0) {
          m.s = Math.min(rLen, -m.s);
          m.dir = -m.dir;
        }
        const pos = routePosition(route, m.s);
        m.mesh.position.x = pos.x + m.side;
        m.mesh.position.z = pos.z;

        // Walk cycle bob
        m.phase += step * m.speed * BOBBLE_FREQ;
        m.mesh.position.y = BOBBLE_AMP * Math.abs(Math.sin(m.phase));

        // Arm swing animation (simple: rotate children)
        const swingAmt = 0.2 * Math.sin(m.phase);
        for (let ci = 0; ci < m.mesh.children.length; ci++) {
          const child = m.mesh.children[ci];
          // Arms are at x positions ±0.25: swing them
          if (Math.abs(child.position.x) > 0.2 && child.position.y > 0.6) {
            child.rotation.z = child.position.x > 0 ? -swingAmt : swingAmt;
          }
        }

        // Face direction of travel
        const aheadS = Math.min(rLen, Math.max(0, m.s + m.dir * 0.5));
        const aheadPos = routePosition(route, aheadS);
        const dx = aheadPos.x - pos.x;
        const dz = aheadPos.z - pos.z;
        if (Math.abs(dx) > 0.01 || Math.abs(dz) > 0.01) {
          const angle = Math.atan2(dx, dz);
          m.mesh.rotation.y = angle;
        }
      }
    }
  }

  function dispose() {
    scene.remove(root);
    for (const g of groups) {
      for (const m of g.members) {
        // Dispose meshes/materials if needed
      }
    }
  }

  return { update, dispose, groups };
}