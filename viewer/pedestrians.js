/**
 * Pedestrian simulation: Mixamo humanoids on real sidewalk / footway routes.
 *
 * Routes come from ``roads.json`` → ``walks`` (exported sidewalk ribbons + OSM
 * footways). People follow a path to its end, then continue onto a connected
 * walk when one exists; they only reverse on a dead end. Lateral offset is
 * perpendicular to the path so they stay on the pavement, not in the road.
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
const JOIN_M = 4.0; // endpoints this close are the same junction
const LATERAL_M = 0.35; // stay inside a 2 m sidewalk

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
    if (useMixamo) return makeMixamoHumanoid(profile, groupId, memberIdx);
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

  /** Pick the next route at an endpoint; prefer continuing forward over U-turns. */
  function pickNext(routeIdx, atEnd, heading) {
    const key = `${routeIdx}:${atEnd ? "e" : "s"}`;
    const cands = graph.get(key) || [];
    if (!cands.length) return null;
    // Prefer links whose outbound heading matches how we arrived.
    const scored = cands.map((c) => {
      const r = walkRoutes[c.routeIdx];
      const a = r.points[c.reverse ? r.points.length - 1 : 0];
      const b = r.points[c.reverse ? r.points.length - 2 : 1] || a;
      const hx = b.x - a.x;
      const hz = b.z - a.z;
      const hl = Math.hypot(hx, hz) || 1;
      const align = (hx / hl) * heading.x + (hz / hl) * heading.z;
      return { c, align };
    });
    scored.sort((a, b) => b.align - a.align);
    // Soft choice among the better-aligned options so crowds fan out.
    const top = scored.filter((s) => s.align > 0.15);
    const pool = top.length ? top : scored;
    return pool[(Math.random() * Math.min(3, pool.length)) | 0].c;
  }

  function advanceEnd(m) {
    const route = walkRoutes[m.routeIdx];
    const atEnd = m.dir > 0;
    const pos = routePosition(route, atEnd ? routeLength(route) : 0);
    const heading = { x: pos.tx * m.dir, z: pos.tz * m.dir };
    const next = pickNext(m.routeIdx, atEnd, heading);
    if (next) {
      m.routeIdx = next.routeIdx;
      m.dir = next.reverse ? -1 : 1;
      m.s = next.reverse ? routeLength(walkRoutes[next.routeIdx]) - 0.05 : 0.05;
      return;
    }
    // Dead end: turn around (natural on a cul-de-sac).
    m.dir = -m.dir;
    m.s = Math.max(0.05, Math.min(routeLength(route) - 0.05, m.s));
  }

  function spawnGroup(profiles, routes) {
    const prof = profiles[(Math.random() * profiles.length) | 0];
    const route = routes[(Math.random() * routes.length) | 0];
    const rLen = routeLength(route);
    const startS = Math.random() * Math.max(1, rLen - 4);
    const dir = Math.random() < 0.5 ? 1 : -1;
    // Small lateral offset on the pavement, not a metre into the carriageway.
    const side = (Math.random() < 0.5 ? -1 : 1) * (0.15 + Math.random() * LATERAL_M);

    const members = [];
    for (let mi = 0; mi < prof.members.length; mi++) {
      const mProf = prof.members[mi];
      const mesh = makeHumanoid(mProf, groups.length, mi);
      const offset = (mi * prof.spread) / (prof.members.length - 1 || 1) - prof.spread * 0.5;
      const speed = WALK_SPEED * (0.85 + Math.random() * 0.3);
      if (mesh.userData.action) {
        mesh.userData.action.setEffectiveTimeScale(speed / WALK_SPEED);
      }
      members.push({
        mesh,
        routeIdx: routes.indexOf(route),
        s: startS + offset * 0.12,
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
  if (!walkRoutes.length) {
    console.warn("[cityview] pedestrians: no walk routes — crowd disabled");
    return { update() {}, dispose() {}, groups, mixamo: useMixamo };
  }
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
      placeMember(m);
    }
  }

  function placeMember(m) {
    const route = walkRoutes[m.routeIdx];
    const pos = routePosition(route, m.s);
    const baseY = m.mesh.userData.baseY || 0;
    // Perpendicular to travel: keep the offset on the pavement.
    const nx = -pos.tz;
    const nz = pos.tx;
    m.mesh.position.set(pos.x + nx * m.side, baseY, pos.z + nz * m.side);
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
      (useMixamo ? ` (Mixamo ×${templates.length})` : " (procedural fallback)")
  );

  function update(dt) {
    if (!(dt > 0)) return;
    for (const g of groups) {
      for (const m of g.members) {
        const route = walkRoutes[m.routeIdx];
        const rLen = routeLength(route);
        m.s += m.speed * m.dir * dt;
        if (m.s >= rLen || m.s < 0) {
          advanceEnd(m);
        }

        placeMember(m);

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

  return { update, dispose, groups, mixamo: useMixamo, routes: walkRoutes };
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
    if (len < 5) continue;
    routes.push({ id: w.id, kind: w.kind || "sidewalk", points: pts, length: len });
  }
  if (routes.length) return routes;
  // Last resort: short stubs near spawn (still sidewalk-ish offsets, not road centre).
  const cx = center.x;
  const cz = center.z;
  return [
    { id: "fallback0", kind: "sidewalk", points: [{ x: cx - 18, z: cz }, { x: cx - 18, z: cz + 80 }] },
    { id: "fallback1", kind: "sidewalk", points: [{ x: cx + 12, z: cz - 10 }, { x: cx + 90, z: cz - 10 }] },
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
      // Arriving at a's end → leave on b starting at b's matching end.
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
