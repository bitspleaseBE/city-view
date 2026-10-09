/**
 * Rocketbox pedestrians (scripts/build_rocketbox_characters.py → characters/people/).
 *
 * 79 people ship, far more than fit in GPU memory at once (~10 MB of textures each), so a
 * pool keeps a share resident: a balanced first batch for the opening spawns, then the rest
 * streams in behind it and replaces walkers once they are out of sight. Households are put
 * together from the manifest's `look` tags so families, couples and friends look plausible.
 */
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { clone as cloneSkeleton } from "three/addons/utils/SkeletonUtils.js";
import { fitHumanoid } from "./humanoid-fit.js";

const DIR = new URL("./characters/people/", import.meta.url);
const loader = new GLTFLoader();

// Looks that plausibly share a household; anything else pairs within its own look.
const CLUSTER = {
  european: "eu",
  slavic: "eu",
  mediterranean: "eu",
  african: "african",
  asian: "asian",
  muslim: "muslim",
  arab: "muslim",
  hasidic: "hasidic",
};

// Always in the first batch, so the opening streets already show these households.
const FIRST = [
  "Hasidic_Father", "Hasidic_Mother", "Hasidic_Boy", "Hasidic_Girl",
  "Male_Adult_15", "Female_Adult_06", "Female_Child_02", "Male_Child_02_grey",
];

const HOUSEHOLDS = [
  { kind: "single", w: 30 },
  { kind: "couple", w: 16 },
  { kind: "family", w: 14 },
  { kind: "parentChild", w: 9 },
  { kind: "friends", w: 9 },
  { kind: "seniors", w: 6 },
  { kind: "kids", w: 4 },
  { kind: "hasidic", w: 6 },
  { kind: "muslimFamily", w: 6 },
];

const shuffle = (a) => {
  for (let i = a.length - 1; i > 0; i--) {
    const j = (Math.random() * (i + 1)) | 0;
    [a[i], a[j]] = [a[j], a[i]];
  }
  return a;
};
const pick = (a) => a[(Math.random() * a.length) | 0];
const cluster = (p) => CLUSTER[p.look] || p.look;

/**
 * @param THREE three namespace
 * @param opts.initial people loaded before the first spawn
 * @param opts.resident cap on loaded people (GPU memory); unused ones are evicted to make room
 */
export async function createPeoplePool(THREE, { initial = 22, resident = 30 } = {}) {
  const res = await fetch(new URL("manifest.json", DIR));
  if (!res.ok) throw new Error(`people manifest: HTTP ${res.status}`);
  const people = (await res.json()).people;
  const byId = new Map(people.map((p) => [p.id, p]));
  const loaded = new Map(); // id → { person, scene, clip, users, lastUsed }
  const loading = new Map();

  async function load(id) {
    if (loaded.has(id)) return loaded.get(id);
    if (loading.has(id)) return loading.get(id);
    const person = byId.get(id);
    const p = loader
      .loadAsync(new URL(person.file, DIR).href)
      .then((gltf) => {
        gltf.scene.traverse((o) => {
          if (!o.isMesh) return;
          o.castShadow = true;
          o.receiveShadow = true;
          for (const m of [o.material].flat()) {
            if (m.alphaTest > 0) m.alphaToCoverage = true; // hair and lash cards
          }
        });
        const t = {
          person,
          scene: gltf.scene,
          clip: gltf.animations[0] || null,
          users: 0,
          lastUsed: 0,
          since: performance.now(),
        };
        loaded.set(id, t);
        return t;
      })
      .catch((err) => {
        console.warn(`[cityview] person load failed: ${id}`, err);
        return null;
      })
      .finally(() => loading.delete(id));
    loading.set(id, p);
    return p;
  }

  function evictOne() {
    let victim = null;
    for (const t of loaded.values()) {
      if (t.users === 0 && (!victim || t.lastUsed < victim.lastUsed)) victim = t;
    }
    if (!victim) return null;
    loaded.delete(victim.person.id);
    victim.scene.traverse((o) => {
      if (!o.isMesh) return;
      o.geometry.dispose();
      for (const m of [o.material].flat()) {
        for (const v of Object.values(m)) if (v && v.isTexture) v.dispose();
        m.dispose();
      }
    });
    return victim.person.id;
  }

  // First batch: the fixed households, then a spread over ages and looks.
  const first = new Set(FIRST.filter((id) => byId.has(id)));
  const rest = shuffle(people.filter((p) => !first.has(p.id)));
  const need = { child: 4, senior: 2 };
  for (const p of rest) {
    if (first.size >= initial) break;
    if (need[p.age] > 0) {
      need[p.age]--;
      first.add(p.id);
    }
  }
  const seenLook = new Set([...first].map((id) => byId.get(id).look));
  for (const p of rest) {
    if (first.size >= initial) break;
    if (!seenLook.has(p.look) || Math.random() < 0.5) {
      seenLook.add(p.look);
      first.add(p.id);
    }
  }
  for (const p of rest) if (first.size < initial) first.add(p.id);
  await Promise.all([...first].map(load));
  if (!loaded.size) throw new Error("no people loaded");

  // The rest streams in behind; once the pool is full, an unused person makes way for the next
  // one in the queue and rejoins its end, so the whole cast keeps rotating through.
  const queue = shuffle(people.filter((p) => !loaded.has(p.id)).map((p) => p.id));
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  // Everyone resident is usually being worn, so the longest-resident person is retired: new
  // households skip them, and once the last wearer is redressed they can be evicted.
  let retiring = null;
  (async () => {
    for (;;) {
      if (!queue.length) {
        await sleep(5000);
        continue;
      }
      if (loaded.size >= resident) {
        const out = evictOne();
        if (!out) {
          if (!retiring || !loaded.has(retiring.person.id)) {
            retiring = null;
            for (const t of loaded.values()) if (!retiring || t.since < retiring.since) retiring = t;
          }
          await sleep(3000);
          continue;
        }
        retiring = null;
        queue.push(out);
      }
      await load(queue.shift());
      if (loaded.size >= resident) await sleep(4000);
    }
  })();

  const avail = (filter) => [...loaded.values()].filter((t) => filter(t.person));
  /** Prefer people nobody is wearing right now, so streamed-in models actually show up. */
  function choose(filter, exclude) {
    let all = avail((p) => filter(p) && !exclude.has(p.id));
    if (all.length > 1) all = all.filter((t) => t !== retiring);
    if (!all.length) return null;
    const least = Math.min(...all.map((t) => t.users));
    return pick(all.filter((t) => t.users <= least + 1));
  }

  const adult = (p) => p.age === "adult";
  const grown = (p) => p.age !== "child";
  const child = (p) => p.age === "child";

  /** Templates for one household walking together. */
  function household() {
    const used = new Set();
    const take = (filter) => {
      const t = choose(filter, used);
      if (t) used.add(t.person.id);
      return t;
    };
    const kind = (() => {
      let r = Math.random() * HOUSEHOLDS.reduce((s, h) => s + h.w, 0);
      for (const h of HOUSEHOLDS) if ((r -= h.w) < 0) return h.kind;
      return "single";
    })();
    const out = [];
    const pair = (look) => {
      const a = take((p) => adult(p) && (!look || cluster(p) === look));
      if (!a) return null;
      out.push(a);
      const b = take((p) => adult(p) && p.sex !== a.person.sex && cluster(p) === cluster(a.person));
      if (b) out.push(b);
      return cluster(a.person);
    };
    const kids = (look, n) => {
      for (let i = 0; i < n; i++) {
        const k = take((p) => child(p) && cluster(p) === look);
        if (k) out.push(k);
      }
    };
    switch (kind) {
      case "hasidic":
      case "muslimFamily": {
        const look = kind === "hasidic" ? "hasidic" : "muslim";
        pair(look);
        kids(look, 1 + ((Math.random() * (kind === "hasidic" ? 3 : 2)) | 0));
        break;
      }
      case "family":
        kids(pair(null), 1 + (Math.random() < 0.45 ? 1 : 0));
        break;
      case "couple":
        pair(null);
        break;
      case "parentChild": {
        const a = take(adult);
        if (a) {
          out.push(a);
          kids(cluster(a.person), 1);
        }
        break;
      }
      case "friends": {
        const a = take(grown);
        if (a) out.push(a);
        for (let i = 0; a && i < 1 + (Math.random() < 0.4 ? 1 : 0); i++) {
          const b = take((p) => p.age === a.person.age);
          if (b) out.push(b);
        }
        break;
      }
      case "seniors": {
        const a = take((p) => p.age === "senior");
        if (a) out.push(a);
        const b = a && Math.random() < 0.6 && take((p) => p.age === "senior" || (adult(p) && p.sex !== a.person.sex));
        if (b) out.push(b);
        break;
      }
      case "kids":
        for (let i = 0; i < 2; i++) {
          const k = take(child);
          if (k) out.push(k);
        }
        break;
    }
    if (!out.length) out.push(take(grown) || pick([...loaded.values()]));
    // A household with children but no grown-up gets one.
    if (kind !== "kids" && out.every((t) => t.person.age === "child")) {
      const a = take(adult);
      if (a) out.unshift(a);
    }
    return { kind, members: out };
  }

  /**
   * A walking clone of `t`: { root, mixer, action, height, naturalSpeed }. naturalSpeed is the
   * pace (m/s) at which the clip's feet do not slide, after scaling to `height`.
   */
  function instance(t) {
    const p = t.person;
    const jitter = p.age === "child" ? 0.8 + Math.random() * 0.2 : 0.95 + Math.random() * 0.08;
    const height = p.height * jitter;
    const root = cloneSkeleton(t.scene);
    fitHumanoid(THREE, root, height);
    const mixer = new THREE.AnimationMixer(root);
    let action = null;
    if (t.clip) {
      action = mixer.clipAction(t.clip);
      action.play();
      action.time = Math.random() * t.clip.duration;
    }
    t.users++;
    t.lastUsed = performance.now();
    return { root, mixer, action, height, naturalSpeed: p.walkSpeed * jitter, template: t };
  }

  function release(inst) {
    inst.mixer.stopAllAction();
    inst.mixer.uncacheRoot(inst.root);
    inst.template.users--;
    inst.template.lastUsed = performance.now();
  }

  return {
    household,
    instance,
    release,
    get residentCount() {
      return loaded.size;
    },
    get pending() {
      return queue.length;
    },
    /** Person being phased out to make room; redress groups wearing them first. */
    get retiring() {
      return retiring;
    },
    total: people.length,
  };
}
