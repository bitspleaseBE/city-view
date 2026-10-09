#!/usr/bin/env node
/**
 * Compress a city GLB for Pages: prune (keep empties) → dedup → weld → Meshopt.
 * Preserves HumanSpawn / lamp_h_* empties the viewer looks up by name.
 *
 *   node scripts/compress_glb.mjs viewer/klein_antwerpen.glb
 *   node scripts/compress_glb.mjs in.glb out.glb
 */
import { existsSync, mkdirSync, renameSync, rmSync, statSync, copyFileSync } from "node:fs";
import { dirname, resolve, join } from "node:path";
import { fileURLToPath } from "node:url";
import { spawnSync } from "node:child_process";
import { tmpdir } from "node:os";
import { randomBytes } from "node:crypto";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const CLI = "@gltf-transform/cli@4.1.2";
const input = resolve(process.argv[2] || join(ROOT, "viewer/klein_antwerpen.glb"));
const output = resolve(process.argv[3] || input);

if (!existsSync(input)) {
  console.error(`[compress_glb] missing ${input}`);
  process.exit(1);
}

function run(args) {
  const r = spawnSync("npx", ["--yes", CLI, ...args], {
    stdio: "inherit",
    cwd: ROOT,
    env: process.env,
  });
  if (r.status !== 0) {
    console.error(`[compress_glb] failed: gltf-transform ${args[0]}`);
    process.exit(r.status ?? 1);
  }
}

const before = statSync(input).size;
const work = join(tmpdir(), `cv-glb-${randomBytes(4).toString("hex")}`);
mkdirSync(work);
const steps = [
  ["prune", "--keep-leaves", "true"],
  ["dedup"],
  ["weld"],
  ["meshopt", "--level", "high"],
];

try {
  let cur = input;
  for (let i = 0; i < steps.length; i++) {
    const [cmd, ...flags] = steps[i];
    const next = join(work, `${i}-${cmd}.glb`);
    run([cmd, cur, next, ...flags]);
    cur = next;
  }
  if (output === input && before > statSync(cur).size * 1.1) {
    const bak = `${input}.premeshopt.glb`;
    if (!existsSync(bak)) copyFileSync(input, bak);
  }
  renameSync(cur, output);
} finally {
  rmSync(work, { recursive: true, force: true });
}

const after = statSync(output).size;
const pct = ((1 - after / before) * 100).toFixed(1);
console.log(
  `[compress_glb] ${(before / 1e6).toFixed(2)} MB → ${(after / 1e6).toFixed(2)} MB (−${pct}%) → ${output}`,
);
