/**
 * Pedestrian simulation: Mixamo humanoids on real sidewalk / footway routes.
 *
 * Routes come from ``roads.json`` → ``walks`` (kerb-side sidewalk ribbons, OSM
 * footways, and short crossing links at zebras). People follow a path, continue
 * onto a connected walk at junctions, and only reverse on a dead end. They spawn
 * on safe walks and only use ``crossing`` links when the graph offers no other
 * forward option. Lateral offset stays on the pavement.
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
const ROADS_URL = "./roads.json";
const JOIN_M = 5.0; // endpoints this close are the same junction
const LATERAL_M = 0.28; // stay inside a 2 m sidewalk
const SAFE_KINDS = new Set(["sidewalk", "footway", "path", "pedestrian", "steps"]);
const KNOCK_SPEED = 1.8;
const SLIDE_DECEL = 5.5;
const GET_UP_S = 1.4;

export async function createPedestrians(scene, THREE, opts = {}) {
  const COUNT = opts.count || 40;
  const SPAWN_CENTER = opts.spawnCenter || { x: -218.5, z: -432.1 };
  const WALK_SPEED = 1.25; // m/s
  const BOBBLE_AMP = 0.02;
  const BOBBLE_FREQ = 9.0;

  const walks = opts.walks || (await loadWalks());
  const walkRoutes = buildWalkRoutes(walks, SPAWN_CENTER);
  const graph = buildGraph(walkRoutes);
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
      members: [{ bodyColor: 0x6a5a4a, legColor: 0x3a4048, topColor: 0x9a7a5a, scale: 1.0, hairColor: 0x4a3a2a }],
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

    const hair = new THREE.Mesh(
      new THREE.SphereGeometry(0.13, 8, 4),
      new THREE.MeshLambertMaterial({ color: profile.hairColor || 0x3a2a1a })
    );
    hair.position.y = 1.28;
    group.add(hair);

    for (const sx of [-0.1, 0.1]) {
      const leg = new THREE.Mesh(new THREE.CapsuleGeometry(0.06, 0.55, 4, 6), mat(profile.legColor));
      leg.position.set(sx, 0.32, 0);
      group.add(leg);
    }
    for (const sx of [-0.25, 0.25]) {
      const arm = new THREE.Mesh(
        new THREE.CapsuleGeometry(0.04, 0.45, 4, 6),
        mat(profile.armColor || profile.topColor)
      );
      arm.position.set(sx, 0.74, 0);
      group.add(arm);
    }
    const top = new THREE.Mesh(new THREE.CapsuleGeometry(0.2, 0.1, 4, 6), mat(profile.topColor));
    top.position.set(0, 0.85, 0.05);
    group.add(top);

    group.scale.setScalar(profile.scale);
    return group;
  }

  function makeMixamoHumanoid(profile, groupId, memberIdx, preferIdx) {
    // Prefer a distinct character per group member so couples don't look like ghosts.
    const tmpl =
      templates.length > 1 && preferIdx != null
        ? templates[preferIdx % templates.length]
        : templates[(Math.random() * templates.length) | 0];
    const root = cloneSkeleton(tmpl.scene);
    root.traverse((o) => {
      if (o.isMesh) {
        o.castShadow = true;
        o.receiveShadow = true;
        o.frustumCulled = true;
      }
    });

    const box = new THREE.Box3().setFromObject(root);
    const size = new THREE.Vector3();
    box.getSize(size);
    const targetH = 1.7 * (profile.scale || 1);
    const s = size.y > 0.01 ? targetH / size.y : 1;
    root.scale.setScalar(s);

    box.setFromObject(root);
    root.position.y -= box.min.y;

    const mixer = new THREE.AnimationMixer(root);
    let action = null;
    if (tmpl.clips.length) {
      const clip = tmpl.clips.find((c) => /walk/i.test(c.name)) || tmpl.clips[0];
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
    if (useMixamo) return makeMixamoHumanoid(profile, groupId, memberIdx, groupId * 3 + memberIdx);
    return makeProceduralHumanoid(profile, groupId, memberIdx);
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
        const tx = dx / (segLen || 1);
        const tz = dz / (segLen || 1);
        return { x: pts[i].x + dx * t, z: pts[i].z + dz * t, idx: i, t, tx, tz };
      }
      cum += segLen;
    }
    const last = pts[pts.length - 1];
    const prev = pts[pts.length - 2] || last;
    const dx = last.x - prev.x;
    const dz = last.z - prev.z;
    const segLen = Math.hypot(dx, dz) || 1;
    return { x: last.x, z: last.z, idx: pts.length - 2, t: 1, tx: dx / segLen, tz: dz / segLen };
  }

  function routeLength(route) {
    let len = 0;
    for (let i = 0; i < route.points.length - 1; i++) {
      len += Math.hypot(route.points[i + 1].x - route.points[i].x, route.points[i + 1].z - route.points[i].z);
    }
    return len;
  }

  function outboundHeading(c) {
    const r = walkRoutes[c.routeIdx];
    const a = r.points[c.reverse ? r.points.length - 1 : 0];
    const b = r.points[c.reverse ? r.points.length - 2 : 1] || a;
    const hx = b.x - a.x;
    const hz = b.z - a.z;
    const hl = Math.hypot(hx, hz) || 1;
    return { x: hx / hl, z: hz / hl };
  }

  /** Pick the next route at an endpoint; prefer continuing forward over U-turns. */
  function pickNext(routeIdx, atEnd, heading, recent) {
    const key = `${routeIdx}:${atEnd ? "e" : "s"}`;
    const cands = graph.get(key) || [];
    if (!cands.length) return null;

    const scored = cands.map((c) => {
      const h = outboundHeading(c);
      const align = h.x * heading.x + h.z * heading.z;
      const dest = walkRoutes[c.routeIdx];
      const isCross = dest.kind === "crossing";
      const isSafe = dest.safe !== false && SAFE_KINDS.has(dest.kind);
      const pingPong = recent.has(c.routeIdx) ? 1 : 0;
      // Prefer forward, safe, long paths; crossings only when needed.
      const score = align * 3 + (isSafe ? 1.2 : 0) - (isCross ? 1.5 : 0) - pingPong * 2 + Math.min(2, dest.length / 40);
      return { c, align, score, isCross };
    });
    scored.sort((a, b) => b.score - a.score);

    // Prefer forward non-crossing options; fall back to any forward; then any.
    const forwardSafe = scored.filter((s) => s.align > 0.2 && !s.isCross);
    const forward = scored.filter((s) => s.align > 0.15);
    const pool = forwardSafe.length ? forwardSafe : forward.length ? forward : scored;
    return pool[(Math.random() * Math.min(3, pool.length)) | 0].c;
  }

  function advanceEnd(m) {
    const route = walkRoutes[m.routeIdx];
    const atEnd = m.dir > 0;
    const pos = routePosition(route, atEnd ? routeLength(route) : 0);
    const heading = { x: pos.tx * m.dir, z: pos.tz * m.dir };
    const next = pickNext(m.routeIdx, atEnd, heading, m.recent);
    if (next) {
      m.recent.add(m.routeIdx);
      if (m.recent.size > 4) {
        m.recent = new Set([...m.recent].slice(-3));
      }
      m.routeIdx = next.routeIdx;
      m.dir = next.reverse ? -1 : 1;
      m.s = next.reverse ? routeLength(walkRoutes[next.routeIdx]) - 0.05 : 0.05;
      return;
    }
    // Dead end: turn around (natural on a cul-de-sac).
    m.dir = -m.dir;
    m.s = Math.max(0.05, Math.min(routeLength(route) - 0.05, m.s));
  }

  function spawnRoutes() {
    const safe = walkRoutes.filter((r) => r.safe !== false && SAFE_KINDS.has(r.kind) && r.length >= 12);
    return safe.length ? safe : walkRoutes.filter((r) => r.kind !== "crossing");
  }

  function spawnGroup(profiles, routes) {
    const prof = profiles[(Math.random() * profiles.length) | 0];
    const route = routes[(Math.random() * routes.length) | 0];
    const rLen = routeLength(route);
    const startS = Math.random() * Math.max(1, rLen - 4);
    const dir = Math.random() < 0.5 ? 1 : -1;
    // Pavement lane: group centre, then fan members slightly so they don't stack.
    const side0 = (Math.random() < 0.5 ? -1 : 1) * (0.1 + Math.random() * LATERAL_M);
    const nMem = prof.members.length;

    const members = [];
    for (let mi = 0; mi < nMem; mi++) {
      const mProf = prof.members[mi];
      const mesh = makeHumanoid(mProf, groups.length, mi);
      // ``spread`` is metres of path separation (was wrongly scaled by 0.12 → ghost stacks).
      const along = nMem > 1 ? (mi * prof.spread) / (nMem - 1) - prof.spread * 0.5 : 0;
      const side = side0 + (nMem > 1 ? (mi - (nMem - 1) * 0.5) * 0.22 : 0);
      const speed = WALK_SPEED * (0.85 + Math.random() * 0.3);
      if (mesh.userData.action) {
        mesh.userData.action.setEffectiveTimeScale(speed / WALK_SPEED);
      }
      members.push({
        mesh,
        routeIdx: routes.indexOf(route) >= 0 ? walkRoutes.indexOf(route) : 0,
        s: startS + along,
        dir,
        side: Math.max(-0.55, Math.min(0.55, side)),
        phase: Math.random() * Math.PI * 2,
        speed,
        prof: mProf,
        recent: new Set(),
        offX: 0,
        offZ: 0,
        down: null,
        routeX: 0,
        routeZ: 0,
      });
    }
    return { members, routeIdx: walkRoutes.indexOf(route), route };
  }

  const root = new THREE.Group();
  root.name = "Pedestrians";
  scene.add(root);

  const groups = [];
  const spawnPool = spawnRoutes();
  if (!spawnPool.length) {
    console.warn("[cityview] pedestrians: no walk routes — crowd disabled");
    return { update() {}, dispose() {}, groups, mixamo: useMixamo, hitTest() { return 0; }, setBlocker() {} };
  }
  for (let i = 0; i < COUNT; i++) {
    const g = spawnGroup(PROFILES, spawnPool);
    for (const m of g.members) root.add(m.mesh);
    groups.push(g);
  }

  for (const g of groups) {
    for (const m of g.members) {
      const route = walkRoutes[m.routeIdx];
      const rLen = routeLength(route);
      m.s = ((m.s % rLen) + rLen) % rLen;
      placeMember(m);
    }
  }

  function placeMember(m) {
    const route = walkRoutes[m.routeIdx];
    const pos = routePosition(route, m.s);
    const baseY = m.mesh.userData.baseY || 0;
    const nx = -pos.tz;
    const nz = pos.tx;
    m.routeX = pos.x + nx * m.side;
    m.routeZ = pos.z + nz * m.side;
    m.mesh.position.set(m.routeX + (m.offX || 0), baseY, m.routeZ + (m.offZ || 0));
    const aheadS = Math.min(routeLength(route), Math.max(0, m.s + m.dir * 0.6));
    const ahead = routePosition(route, aheadS);
    const dx = ahead.x - pos.x;
    const dz = ahead.z - pos.z;
    if (Math.abs(dx) > 0.01 || Math.abs(dz) > 0.01) {
      m.mesh.rotation.y = Math.atan2(dx, dz);
    }
  }

  console.info(
    `[cityview] pedestrians: ${groups.reduce((n, g) => n + g.members.length, 0)} people` +
      ` on ${walkRoutes.length} walks` +
      ` (${spawnPool.length} safe spawn)` +
      (useMixamo ? ` (Mixamo ×${templates.length})` : " (procedural fallback)")
  );

  const UP = new THREE.Vector3(0, 1, 0);
  const _axis = new THREE.Vector3();
  const _qFall = new THREE.Quaternion();
  const _qYaw = new THREE.Quaternion();
  let blocked = () => false;

  function hitTest(x, z, vx, vz, r) {
    const speed = Math.hypot(vx, vz);
    let hits = 0;
    for (const g of groups) {
      for (const m of g.members) {
        if (m.down) continue;
        const p = m.mesh.position;
        const dx = p.x - x;
        const dz = p.z - z;
        const reach = r + 0.28 * (m.prof.scale || 1);
        if (dx * dx + dz * dz > reach * reach) continue;
        hits++;
        if (speed < KNOCK_SPEED) {
          const d = Math.hypot(dx, dz) || 1;
          m.offX = (m.offX || 0) + (dx / d) * 0.35;
          m.offZ = (m.offZ || 0) + (dz / d) * 0.35;
          continue;
        }
        const d = Math.hypot(dx, dz) || 1;
        const k = 0.75 + Math.random() * 0.15;
        const tvx = vx * k + (dx / d) * speed * 0.2;
        const tvz = vz * k + (dz / d) * speed * 0.2;
        m.down = {
          vx: tvx,
          vz: tvz,
          vy: 0.6 + speed * 0.12,
          y: 0,
          angle: 0,
          spin: 4.5 + speed * 0.5,
          lie: 3.5 + Math.random() * 3,
          getUp: 0,
          yaw: m.mesh.rotation.y,
          axis: _axis.crossVectors(UP, new THREE.Vector3(tvx, 0, tvz).normalize()).clone(),
        };
        m.offX = p.x - (m.routeX ?? p.x);
        m.offZ = p.z - (m.routeZ ?? p.z);
      }
    }
    return hits;
  }

  function updateDown(m, dt) {
    const f = m.down;
    const p = m.mesh.position;
    const airborne = f.y > 0 || f.vy > 0;
    const hs = Math.hypot(f.vx, f.vz);
    if (hs > 0) {
      const nx = p.x + f.vx * dt;
      const nz = p.z + f.vz * dt;
      if (blocked(nx, nz)) {
        f.vx *= -0.2;
        f.vz *= -0.2;
      } else {
        p.x = nx;
        p.z = nz;
      }
      if (!airborne) {
        const slow = Math.max(0, hs - SLIDE_DECEL * dt) / hs;
        f.vx *= slow;
        f.vz *= slow;
      }
    }
    if (airborne) {
      f.vy -= 9.81 * dt;
      f.y = Math.max(0, f.y + f.vy * dt);
      if (f.y === 0) f.vy = 0;
    }
    let up = false;
    if (f.getUp > 0) {
      f.getUp -= dt;
      f.angle = (Math.PI / 2) * Math.max(0, f.getUp / GET_UP_S);
      up = f.getUp <= 0;
    } else if (f.angle < Math.PI / 2) {
      f.angle = Math.min(Math.PI / 2, f.angle + f.spin * dt);
    } else if (hs < 0.05 && !airborne) {
      f.lie -= dt;
      if (f.lie <= 0) f.getUp = GET_UP_S;
    }
    _qYaw.setFromAxisAngle(UP, f.yaw);
    _qFall.setFromAxisAngle(f.axis, f.angle);
    m.mesh.quaternion.multiplyQuaternions(_qFall, _qYaw);
    p.y = (m.mesh.userData.baseY || 0) + f.y + 0.13 * (m.prof.scale || 1) * Math.sin(f.angle);
    if (up) {
      m.down = null;
      m.mesh.rotation.set(0, f.yaw, 0);
      m.offX = p.x - m.routeX;
      m.offZ = p.z - m.routeZ;
      return false;
    }
    return true;
  }

  function update(dt) {
    if (!(dt > 0)) return;
    for (const g of groups) {
      for (const m of g.members) {
        if (m.down && updateDown(m, dt)) continue;

        const route = walkRoutes[m.routeIdx];
        const rLen = routeLength(route);
        m.s += m.speed * m.dir * dt;
        if (m.s >= rLen || m.s < 0) {
          advanceEnd(m);
        }

        placeMember(m);

        if (m.offX || m.offZ) {
          const keep = Math.max(0, 1 - dt * 0.8);
          m.offX = Math.abs(m.offX * keep) < 0.01 ? 0 : m.offX * keep;
          m.offZ = Math.abs(m.offZ * keep) < 0.01 ? 0 : m.offZ * keep;
          m.mesh.position.x = m.routeX + (m.offX || 0);
          m.mesh.position.z = m.routeZ + (m.offZ || 0);
        }

        if (m.mesh.userData.mixer) {
          m.mesh.userData.mixer.update(dt);
          m.mesh.position.y = m.mesh.userData.baseY || 0;
        } else {
          const baseY = m.mesh.userData.baseY || 0;
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

  return {
    update,
    dispose,
    groups,
    mixamo: useMixamo,
    routes: walkRoutes,
    hitTest,
    setBlocker(fn) {
      blocked = fn;
    },
  };
}

async function loadWalks() {
  try {
    const res = await fetch(ROADS_URL);
    if (!res.ok) return [];
    const data = await res.json();
    return data.walks || [];
  } catch (err) {
    console.warn("[cityview] walks unavailable", err);
    return [];
  }
}

/** Blender XY walks → Three XZ routes (z = −y). */
function buildWalkRoutes(walks, center) {
  const routes = [];
  for (const w of walks) {
    const pts = (w.points || [])
      .map((p) => ({ x: p[0], z: -p[1] }))
      .filter((p, i, arr) => i === 0 || Math.hypot(p.x - arr[i - 1].x, p.z - arr[i - 1].z) > 0.05);
    if (pts.length < 2) continue;
    let len = 0;
    for (let i = 0; i < pts.length - 1; i++) len += Math.hypot(pts[i + 1].x - pts[i].x, pts[i + 1].z - pts[i].z);
    // Crossings are short on purpose; other walks need a few metres.
    if (w.kind !== "crossing" && len < 5) continue;
    routes.push({
      id: w.id,
      kind: w.kind || "sidewalk",
      safe: w.safe !== false,
      points: pts,
      length: len,
    });
  }
  if (routes.length) return routes;
  // Last resort: sidewalk-ish stubs beside spawn, not road centre.
  const cx = center.x;
  const cz = center.z;
  return [
    { id: "fallback0", kind: "sidewalk", safe: true, points: [{ x: cx - 18, z: cz }, { x: cx - 18, z: cz + 80 }], length: 80 },
    { id: "fallback1", kind: "sidewalk", safe: true, points: [{ x: cx + 12, z: cz - 10 }, { x: cx + 90, z: cz - 10 }], length: 78 },
  ];
}

function buildGraph(routes) {
  const ends = [];
  for (let i = 0; i < routes.length; i++) {
    const pts = routes[i].points;
    ends.push({ routeIdx: i, atEnd: false, x: pts[0].x, z: pts[0].z });
    ends.push({ routeIdx: i, atEnd: true, x: pts[pts.length - 1].x, z: pts[pts.length - 1].z });
  }
  const graph = new Map();
  for (const a of ends) {
    const key = `${a.routeIdx}:${a.atEnd ? "e" : "s"}`;
    const links = [];
    for (const b of ends) {
      if (a.routeIdx === b.routeIdx) continue;
      if (Math.hypot(a.x - b.x, a.z - b.z) > JOIN_M) continue;
      links.push({ routeIdx: b.routeIdx, reverse: b.atEnd });
    }
    graph.set(key, links);
  }
  return graph;
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
