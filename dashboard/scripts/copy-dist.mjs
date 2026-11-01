// Copies the static Next.js export (dashboard/out) into the Python package so
// `devpilot dashboard` can serve it. Paths are resolved relative to this file.
import { cpSync, existsSync, mkdirSync, readdirSync, rmSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const source = resolve(here, "..", "out");
const target = resolve(here, "..", "..", "devpilot", "dashboard_server", "static");

if (!existsSync(source)) {
  console.error(`[copy-dist] Build output not found: ${source}. Run \`next build\` first.`);
  process.exit(1);
}

mkdirSync(target, { recursive: true });
for (const entry of readdirSync(target)) {
  rmSync(join(target, entry), { recursive: true, force: true });
}
cpSync(source, target, { recursive: true });

console.log(`[copy-dist] Copied ${source} -> ${target}`);
