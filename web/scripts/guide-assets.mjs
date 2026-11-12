// Places the room guide's two outside pieces under public/, same-origin with the
// app, before `next dev` and `next build` (decision 0376):
//
//   public/guide/player.js     the guide's player, from packages/room-guide
//                              (thegoodguest_room_guide/web/player.js), as it is
//   public/diorama/viewer.html the diorama viewer's page and its js/, once the
//   public/diorama/js/         viewer's folder exists (services/diorama/viewer,
//                              on the unmerged diorama branch until it merges)
//   public/diorama/vendor/     every three.js module the viewer and the player
//                              reach, copied from this app's node_modules
//
// Nothing is copied into source control: both folders are gitignored, and this
// runs on every dev start and build, so the copies follow their sources.
//
// The viewer's page is changed in two ways on its way here, both because it is
// served inside the product's own origin and content security policy: its
// import map points at the vendored three.js instead of a CDN (no third-party
// script runs beside a signed-in session), and its web-font links are dropped
// (the policy serves fonts from this origin only; the viewer's own captions,
// which used them, are hidden in the product). The three.js it asked for and the
// one in node_modules must be the same version, or the copy is refused.
//
// DIORAMA_VIEWER_DIR=<folder> takes the viewer from another checkout, for local
// checks against the diorama branch's worktree before it merges.
//
// Run by: npm's predev and prebuild hooks (package.json).

import { cpSync, existsSync, mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const WEB = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const REPO = path.resolve(WEB, "..");
const PUBLIC = path.join(WEB, "public");
const PLAYER = path.join(REPO, "packages", "room-guide", "thegoodguest_room_guide", "web", "player.js");
const VIEWER = process.env.DIORAMA_VIEWER_DIR
  ? path.resolve(process.env.DIORAMA_VIEWER_DIR)
  : path.join(REPO, "services", "diorama", "viewer");
const THREE = path.join(WEB, "node_modules", "three");
const THREE_VERSION = JSON.parse(readFileSync(path.join(THREE, "package.json"), "utf8")).version;
const CDN_THREE = /^https:\/\/cdn\.jsdelivr\.net\/npm\/three@([^/]+)\/(.*)$/;
const IMPORTS = /(?:import|export)\s[^'"]*?from\s*['"]([^'"]+)['"]|import\s*\(?\s*['"]([^'"]+)['"]/g;

function placePlayer() {
  const out = path.join(PUBLIC, "guide");
  rmSync(out, { recursive: true, force: true });
  if (!existsSync(PLAYER)) {
    console.warn(`guide-assets: no player at ${PLAYER}; the room guide cannot play moves`);
    return;
  }
  mkdirSync(out, { recursive: true });
  cpSync(PLAYER, path.join(out, "player.js"));
}

/** The page's import map with every CDN three.js address made a local one. */
function localImportMap(html) {
  return html.replace(
    /(<script type="importmap">)([\s\S]*?)(<\/script>)/,
    (_, open, body, close) => {
      const map = JSON.parse(body);
      for (const [name, url] of Object.entries(map.imports ?? {})) {
        const m = CDN_THREE.exec(url);
        if (!m) continue;
        if (m[1] !== THREE_VERSION) {
          throw new Error(`the viewer asks for three@${m[1]} but node_modules has ${THREE_VERSION}`);
        }
        map.imports[name] = `./vendor/three/${m[2]}`;
      }
      return `${open}\n${JSON.stringify(map, null, 1)}\n${close}`;
    },
  );
}

/** Every three.js file reachable from `entries`, as paths inside node_modules/three. */
function threeFiles(entries) {
  const seen = new Set();
  const found = new Set();
  const queue = [...entries];
  while (queue.length) {
    const file = queue.pop();
    if (seen.has(file)) continue;
    seen.add(file);
    const text = readFileSync(file, "utf8");
    for (const m of text.matchAll(IMPORTS)) {
      const spec = m[1] ?? m[2];
      let target = null;
      if (spec === "three") target = path.join(THREE, "build", "three.module.js");
      else if (spec.startsWith("three/addons/")) target = path.join(THREE, "examples", "jsm", spec.slice(13));
      else if (spec.startsWith("./") || spec.startsWith("../")) target = path.resolve(path.dirname(file), spec);
      if (!target || !existsSync(target)) continue;
      if (target.startsWith(THREE + path.sep)) found.add(path.relative(THREE, target));
      queue.push(target);
    }
  }
  return [...found].sort();
}

function placeViewer() {
  const out = path.join(PUBLIC, "diorama");
  rmSync(out, { recursive: true, force: true });
  const page = path.join(VIEWER, "index.html");
  if (!existsSync(page)) return false;
  mkdirSync(out, { recursive: true });
  let html = readFileSync(page, "utf8");
  html = localImportMap(html);
  html = html.replace(/[ \t]*<link[^>]*fonts\.(?:googleapis|gstatic)\.com[^>]*>\n?/g, "");
  writeFileSync(path.join(out, "viewer.html"), html);
  cpSync(path.join(VIEWER, "js"), path.join(out, "js"), { recursive: true });
  const entries = [path.join(out, "js", "main.js"), path.join(PUBLIC, "guide", "player.js")].filter(existsSync);
  const files = threeFiles(entries);
  for (const rel of files) {
    const to = path.join(out, "vendor", "three", rel);
    mkdirSync(path.dirname(to), { recursive: true });
    cpSync(path.join(THREE, rel), to);
  }
  cpSync(path.join(THREE, "LICENSE"), path.join(out, "vendor", "three", "LICENSE"));
  console.log(`guide-assets: the diorama viewer from ${path.relative(REPO, VIEWER) || VIEWER}, with ${files.length} three.js modules`);
  return true;
}

placePlayer();
if (!placeViewer()) {
  console.log("guide-assets: no diorama viewer yet; the room guide stays dark until it merges");
}
