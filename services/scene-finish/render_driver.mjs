// Headless driver for the room viewer: render a room's finish and furniture
// from a capture's own camera poses, with no window and no GPU.
//
// The viewer is the static export of web/ built with NEXT_PUBLIC_SHELL_FINISH=1
// (its /shell-finish page carries the compare harness, window.__shellFinishView).
// This driver serves that build and exactly three data files over loopback,
// opens the page in headless Chrome, waits for the viewer's own "settled"
// signal (__shellFinishView.ready), then runs the harness over the poses. The
// harness POSTs three PNGs per frame back to the driver:
//
//   frame_<id>.png   the real look
//   ids_<id>.png     flat region ids (red channel; see REGION_IDS in the harness)
//   mask_<id>.png    each furniture twin flat in its own id
//
// Software GL is mandatory in the cloud: plain headless Chrome has no WebGL at
// all, so the default flags below ask for ANGLE on SwiftShader. Pass --gl default
// (or metal on a Mac) to use the machine's GPU while developing.
//
// Two ways to run it, both taking the same job:
//
//   node render_driver.mjs render --job job.json [--web DIR] [--chrome PATH] [--gl MODE]
//       one job, result JSON on stdout, then exit. Without --chrome (or
//       CHROME_PATH) Playwright's own chromium-headless-shell is used.
//   node render_driver.mjs serve  [--web DIR] [--chrome PATH] [--gl MODE]
//       keeps the browser warm: one JSON job per stdin line, one JSON result per
//       stdout line. (The page is still reloaded per job, because the furniture
//       file is read at load.)
//
// A job is JSON, paths absolute and readable:
//   { "shell": "…/shell.json", "finish": "…/finish.json" | null,
//     "furniture": "…/furniture.json" | null,
//     "frames": [{ "id", "pos":[x,y,z], "quat":[x,y,z,w], "fy", "h", "w" }],
//     "width": 800,            // output width in px (default 800)
//     "outDir": "…" }          // where the PNGs go; the caller owns it
//
// The scene's own files are only read. Nothing leaves the machine: the page
// talks to a loopback server this process starts and to nothing else.
//
// Needs playwright-core (see package.json) and a Chromium binary.

import fs from "node:fs";
import http from "node:http";
import path from "node:path";
import readline from "node:readline";
import { fileURLToPath } from "node:url";

import { chromium } from "playwright-core";

const HERE = path.dirname(fileURLToPath(import.meta.url));

/** The page opens this small; the harness resizes the canvas per frame, so the
 * viewport only decides how much the viewer draws before it is ready. */
export const START_VIEWPORT = { width: 320, height: 240 };
export const DEFAULT_WIDTH = 800;
/** Software GL needs most of a minute for a cold first draw on a small CPU. */
export const READY_TIMEOUT_MS = 180_000;
/** One whole job (page load, ready, every frame) may take this long. */
export const JOB_TIMEOUT_MS = 600_000;

const GL_ARGS = {
  swiftshader: ["--use-angle=swiftshader", "--use-gl=angle", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"],
  metal: ["--use-angle=metal", "--use-gl=angle", "--ignore-gpu-blocklist"],
  default: [],
};
/** What a container needs on top: no sandbox (Cloud Run runs us unprivileged
 * in a sandbox of its own) and no /dev/shm (it is tiny there). */
const CONTAINER_ARGS = ["--no-sandbox", "--disable-dev-shm-usage"];

const MIME = {
  ".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".json": "application/json",
  ".txt": "text/plain", ".svg": "image/svg+xml", ".woff2": "font/woff2", ".png": "image/png", ".ico": "image/x-icon",
};
const NAMES = ["shell", "finish", "furniture"];

/** Start Chrome and a loopback server that serves the viewer build. */
export async function launchRenderer({ chrome, webOut = path.resolve(HERE, "web-out"), gl = "swiftshader", sandbox = true }) {
  if (!(gl in GL_ARGS)) throw new Error(`unknown --gl ${gl}`);
  if (!fs.existsSync(path.join(webOut, "shell-finish.html"))) {
    throw new Error(`no viewer build at ${webOut} (expected shell-finish.html; build web/ with NEXT_PUBLIC_SHELL_FINISH=1)`);
  }
  const webRoot = path.resolve(webOut);
  // The job being served. One at a time: the harness posts to a fixed path.
  let current = null;
  const server = http.createServer((req, res) => {
    const u = decodeURIComponent(req.url.split("?")[0]);
    const cors = { "Access-Control-Allow-Origin": "*", "Cache-Control": "no-store" };
    if (req.method === "POST") {
      const m = /^\/renders\/([A-Za-z0-9_.-]+\.png)$/.exec(u);
      if (!m || !current) { res.writeHead(404); return res.end(); }
      const chunks = [];
      req.on("data", (c) => chunks.push(c));
      req.on("end", () => {
        const body = Buffer.concat(chunks);
        const png = body.subarray(0, 4).toString() === "data" ? Buffer.from(body.toString().split(",")[1], "base64") : body;
        fs.writeFileSync(path.join(current.outDir, m[1]), png);
        current.posted.push(m[1]);
        res.writeHead(200, cors);
        res.end("ok");
      });
      return;
    }
    const data = /^\/(shell|finish|furniture)\.json$/.exec(u);
    if (data) {
      const file = current?.files[data[1]];
      if (!file) { res.writeHead(404, cors); return res.end(); }
      res.writeHead(200, { ...cors, "Content-Type": "application/json" });
      return res.end(fs.readFileSync(file));
    }
    let f = path.join(webRoot, u === "/" ? "index.html" : u);
    if (!fs.existsSync(f) && fs.existsSync(f + ".html")) f += ".html";
    if (!f.startsWith(webRoot + path.sep) || !fs.existsSync(f) || fs.statSync(f).isDirectory()) { res.writeHead(404); return res.end(); }
    res.writeHead(200, { ...cors, "Content-Type": MIME[path.extname(f)] ?? "application/octet-stream" });
    res.end(fs.readFileSync(f));
  });
  await new Promise((r) => server.listen(0, "127.0.0.1", r));
  const port = server.address().port;

  const args = [...GL_ARGS[gl], ...(sandbox ? [] : CONTAINER_ARGS), "--hide-scrollbars", "--mute-audio"];
  let browser = await chromium.launch({ executablePath: chrome, headless: true, args });

  /** Render one job; returns what was written and how long it took. */
  async function render(job) {
    const t0 = Date.now();
    const files = {};
    for (const n of NAMES) {
      if (job[n]) {
        if (!fs.existsSync(job[n])) throw new Error(`${n} file not found: ${job[n]}`);
        files[n] = job[n];
      }
    }
    if (!files.shell) throw new Error("job has no shell");
    if (!Array.isArray(job.frames) || job.frames.length === 0) throw new Error("job has no frames");
    const outDir = job.outDir;
    if (!outDir) throw new Error("job has no outDir");
    fs.mkdirSync(outDir, { recursive: true });
    const width = job.width ?? DEFAULT_WIDTH;
    const frames = job.frames.map((f) => ({ ...f, scale: f.w ? width / f.w : undefined }));
    current = { files, outDir, posted: [] };

    if (!browser.isConnected()) browser = await chromium.launch({ executablePath: chrome, headless: true, args });
    const context = await browser.newContext({ viewport: START_VIEWPORT, deviceScaleFactor: 1 });
    const issues = [];
    try {
      const page = await context.newPage();
      page.on("console", (m) => { if (m.type() === "error") issues.push("console: " + m.text().slice(0, 200)); });
      page.on("pageerror", (e) => issues.push("pageerror: " + String(e).slice(0, 200)));
      const origin = `http://127.0.0.1:${port}`;
      const q = ["shell", "finish", "furniture"].filter((n) => files[n]).map((n) => `${n}=${origin}/${n}.json`);
      if (!files.furniture) q.push("furniture=0");
      const tLoad = Date.now();
      await page.goto(`${origin}/shell-finish.html?${q.join("&")}`, { waitUntil: "load", timeout: 60_000 });
      try {
        await page.waitForFunction(
          () => window.__shellFinishView && window.__shellFinishView.ready === true && window.__shellFinishView.harness,
          null,
          { timeout: READY_TIMEOUT_MS },
        );
      } catch (e) {
        const text = await page.evaluate(() => document.body.innerText.slice(0, 300)).catch(() => "");
        throw new Error(`viewer never settled: ${String(e).slice(0, 120)} page says: ${JSON.stringify(text)} issues: ${issues.slice(0, 3).join(" | ")}`);
      }
      const readyMs = Date.now() - tLoad;
      const glInfo = await page.evaluate(() => {
        const g = window.__shellFinishView.renderer.getContext();
        const e = g.getExtension("WEBGL_debug_renderer_info");
        return e ? g.getParameter(e.UNMASKED_RENDERER_WEBGL) : "unknown";
      });
      const tRun = Date.now();
      const done = await page.evaluate(([fr, p]) => window.__shellFinishView.harness.run(fr, p), [frames, port]);
      const runMs = Date.now() - tRun;
      return {
        ok: true, glRenderer: glInfo, frames: done, images: current.posted.length,
        readyMs, runMs, perFrameMs: Math.round(runMs / done.length), totalMs: Date.now() - t0, outDir, issues: issues.slice(0, 5),
      };
    } finally {
      current = null;
      await context.close().catch(() => {});
    }
  }

  async function close() {
    await browser.close().catch(() => {});
    server.close();
  }
  return { render, close };
}

const arg = (k, d) => { const i = process.argv.indexOf("--" + k); return i > 0 ? process.argv[i + 1] : d; };

async function main() {
  const mode = process.argv[2];
  if (mode !== "render" && mode !== "serve") {
    console.error("usage: render_driver.mjs render --job job.json | serve  [--web DIR] [--chrome PATH] [--gl swiftshader|metal|default] [--container]");
    process.exit(2);
  }
  // No path: Playwright's own chromium-headless-shell (what the container installs).
  const chrome = arg("chrome", process.env.CHROME_PATH) || undefined;
  const renderer = await launchRenderer({
    chrome,
    webOut: arg("web", process.env.VIEWER_DIR ?? path.resolve(HERE, "web-out")),
    gl: arg("gl", "swiftshader"),
    sandbox: !process.argv.includes("--container"),
  });
  const withDeadline = (p) =>
    Promise.race([p, new Promise((_, rej) => setTimeout(() => rej(new Error(`job exceeded ${JOB_TIMEOUT_MS} ms`)), JOB_TIMEOUT_MS).unref())]);
  const run = async (job) => {
    try { return await withDeadline(renderer.render(job)); }
    catch (e) { return { ok: false, error: String(e.message ?? e).slice(0, 600) }; }
  };
  if (mode === "render") {
    const result = await run(JSON.parse(fs.readFileSync(arg("job"), "utf8")));
    console.log(JSON.stringify(result));
    await renderer.close();
    process.exit(result.ok ? 0 : 1);
  }
  const rl = readline.createInterface({ input: process.stdin });
  for await (const line of rl) {
    if (!line.trim()) continue;
    console.log(JSON.stringify(await run(JSON.parse(line))));
  }
  await renderer.close();
}

if (process.argv[1] === fileURLToPath(import.meta.url)) await main();
