#!/usr/bin/env node
/**
 * Write the compressed tier for a scene: an SPZ beside every PLY the viewer
 * actually renders, plus the index that tells api-public they exist.
 *
 * Read this before changing what the viewer downloads. The render payload was
 * the P0 (decisions 0123/0125): a room is 106-390 MB of uncompressed PLY and
 * the wait is network-bound, so the fix is bytes on the wire. SPZ is the same
 * Gaussians at ~11.6 B each instead of 68.0 -- measured 5.5-6.2x on real
 * rooms, with the count preserved exactly.
 *
 * THIS IS A TRANSCODE, NOT A RE-BAKE. The PLY is the input and is never
 * touched, nothing re-segments, and no perception decision is recomputed.
 * Decision 0070's "re-adjudicate on the reference room before changing what
 * ships" rule is therefore NOT triggered, and a pre-0089 scene's person
 * suppression status is carried across unchanged -- this makes it no better
 * and no worse. A scene that needs suppression still needs a re-drive.
 *
 * The encoder is Spark's own SpzWriter, resolved out of web/node_modules --
 * deliberately the SAME build the browser decodes with, so the writer and the
 * reader can never drift apart. It lives in tools/spz_encode.mjs, shared with
 * the /compress stage that runs this same transcode automatically for new
 * captures; this tool remains the backfill and re-drive path.
 *
 * What it writes, both additive and both ignored by every existing reader:
 *   scenes/{id}/frames/NNNN/splats/NN_label.spz   beside the .ply
 *   scenes/{id}/compressed.json                   the index (shell.json's
 *                                                 precedent: a sibling blob,
 *                                                 absent = tier not built)
 *
 * It does NOT touch manifest.json. That is deliberate: a re-drive rewrites the
 * manifest, and an index living inside it would be silently erased. The index
 * is keyed by the PLY's gs:// URI, so a re-drive that moves a splat to a new
 * frame path simply misses the index and falls back to PLY -- safe by
 * construction. The one hazard is a re-drive that rewrites the SAME path with
 * new content; the recorded source generation catches that on the next run.
 *
 * Usage:
 *   node tools/transcode_scene_splats.mjs <scene_prefix>              # plan only
 *   node tools/transcode_scene_splats.mjs <scene_prefix> --apply
 *   node tools/transcode_scene_splats.mjs --all --apply
 *   node tools/transcode_scene_splats.mjs <scene_prefix> --apply --force
 */

import { execFileSync } from "node:child_process";
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { encodePly, loadSpark } from "./spz_encode.mjs";

const BUCKET = "thegoodguest-perception-outputs";
const INDEX_VERSION = 1;

// --- GCS via the gcloud CLI: no new npm dependency, and the tool inherits the
// operator's own credentials rather than minting any.

function gcloud(args, opts = {}) {
  return execFileSync("gcloud", args, {
    encoding: opts.binary ? "buffer" : "utf8",
    maxBuffer: 1 << 30,
    stdio: ["ignore", "pipe", opts.quiet ? "pipe" : "inherit"],
  });
}

function listScenes() {
  const out = gcloud([
    "storage", "ls", `gs://${BUCKET}/scenes/`,
  ]);
  return out
    .split("\n")
    .map((l) => l.trim().replace(/\/$/, "").split("/").pop())
    .filter(Boolean);
}

function resolveScene(prefix) {
  const matches = listScenes().filter((s) => s.startsWith(prefix));
  if (matches.length !== 1) {
    console.error(`scene prefix ${prefix} matched ${matches.length}: ${matches.join(", ")}`);
    process.exit(2);
  }
  return matches[0];
}

function readText(uri) {
  return gcloud(["storage", "cat", uri], { quiet: true });
}

function readTextOptional(uri) {
  try {
    return readText(uri);
  } catch {
    return null;
  }
}

/** Object metadata, or null when the object does not exist. */
function stat(uri) {
  try {
    const out = gcloud(
      ["storage", "objects", "describe", uri, "--format=json"],
      { quiet: true },
    );
    const j = JSON.parse(out);
    return { size: Number(j.size), generation: String(j.generation) };
  } catch {
    return null;
  }
}

function download(uri, dest) {
  gcloud(["storage", "cp", uri, dest], { quiet: true });
}

function upload(src, uri) {
  gcloud(["storage", "cp", src, uri], { quiet: true });
}

// --- the work

/** The rendered set, using assembleScene's exact rule (web/src/lib/api/types.ts).
 * Unplaced objects are signed by api-public but never fetched, so compressing
 * them would buy the user nothing and cost storage. */
function renderedSplatUris(manifest) {
  const uris = [];
  for (const obj of manifest.objects ?? []) {
    if (obj?.placed && obj?.world_transform && obj?.splat_gcs_uri) {
      uris.push(obj.splat_gcs_uri);
    }
  }
  return [...new Set(uris)].sort();
}

function spzUriFor(plyUri) {
  if (!plyUri.endsWith(".ply")) return null;
  return plyUri.slice(0, -4) + ".spz";
}

async function transcodeScene(sceneId, { apply, force }) {
  const base = `gs://${BUCKET}/scenes/${sceneId}`;
  const manifestRaw = readTextOptional(`${base}/manifest.json`);
  if (!manifestRaw) {
    console.log(`  ${sceneId}: no manifest — skipped`);
    return null;
  }
  const manifest = JSON.parse(manifestRaw);
  const uris = renderedSplatUris(manifest);
  if (!uris.length) {
    console.log(`  ${sceneId}: no rendered splats — skipped`);
    return null;
  }

  const existingRaw = readTextOptional(`${base}/compressed.json`);
  const existing = existingRaw ? JSON.parse(existingRaw) : null;
  const prior = existing?.entries ?? {};

  const work = [];
  const entries = {};
  for (const plyUri of uris) {
    const src = stat(plyUri);
    if (!src) {
      console.log(`    ! source missing, skipped: ${plyUri}`);
      continue;
    }
    const p = prior[plyUri];
    const fresh =
      p && p.source_generation === src.generation && p.source_bytes === src.size;
    if (fresh && !force) {
      entries[plyUri] = p; // already built against this exact source
      continue;
    }
    work.push({ plyUri, src, reason: p ? "source changed" : "new" });
  }

  const totalIn = work.reduce((a, w) => a + w.src.size, 0);
  console.log(
    `  ${sceneId}: ${uris.length} rendered splats, ${Object.keys(entries).length} already current, ` +
      `${work.length} to build (${(totalIn / 1e6).toFixed(1)} MB in)`,
  );
  for (const w of work) console.log(`      ${w.reason.padEnd(14)} ${w.plyUri.split("/").slice(-3).join("/")}`);

  if (!work.length) {
    if (existing) return { sceneId, built: 0, entries };
    // Nothing to build and no index yet: still publish the index below.
  }
  if (!apply) return { sceneId, built: 0, entries, planned: work.length };

  const tmp = mkdtempSync(join(tmpdir(), "spz-"));
  try {
    for (const w of work) {
      const spzUri = spzUriFor(w.plyUri);
      if (!spzUri) {
        console.log(`    ! not a .ply, skipped: ${w.plyUri}`);
        continue;
      }
      const local = join(tmp, "in.ply");
      download(w.plyUri, local);
      const fileBytes = new Uint8Array(readFileSync(local));
      const t0 = Date.now();
      const out = await encodePly(fileBytes, w.plyUri);

      const outLocal = join(tmp, "out.spz");
      writeFileSync(outLocal, out.fileBytes);
      upload(outLocal, spzUri);

      entries[w.plyUri] = {
        uri: spzUri,
        bytes: out.fileBytes.byteLength,
        gaussians: out.gaussians,
        source_bytes: w.src.size,
        source_generation: w.src.generation,
      };
      console.log(
        `      ${(w.src.size / 1e6).toFixed(1)} MB -> ${(out.fileBytes.byteLength / 1e6).toFixed(2)} MB ` +
          `(${(w.src.size / out.fileBytes.byteLength).toFixed(2)}x, ${out.gaussians} gaussians, ` +
          `${((Date.now() - t0) / 1000).toFixed(1)}s)`,
      );
      rmSync(local, { force: true });
    }

    const index = {
      compressed_version: INDEX_VERSION,
      format: "spz",
      encoder: "sparkjsdev/spark SpzWriter",
      entries,
    };
    const idxLocal = join(tmp, "compressed.json");
    writeFileSync(idxLocal, JSON.stringify(index, null, 1));
    upload(idxLocal, `${base}/compressed.json`);
    console.log(`    index written: ${Object.keys(entries).length} entries`);
  } finally {
    rmSync(tmp, { recursive: true, force: true });
  }

  return { sceneId, built: work.length, entries };
}

async function main() {
  const argv = process.argv.slice(2);
  const apply = argv.includes("--apply");
  const force = argv.includes("--force");
  const all = argv.includes("--all");
  const positional = argv.filter((a) => !a.startsWith("--"));

  if (!all && positional.length !== 1) {
    console.error(
      "usage: node tools/transcode_scene_splats.mjs <scene_prefix>|--all [--apply] [--force]",
    );
    process.exit(2);
  }

  await loadSpark();  // fail fast on a missing encoder, before any GCS work
  const scenes = all ? listScenes() : [resolveScene(positional[0])];

  if (!apply) {
    console.log("PLAN ONLY — re-run with --apply to write to the outputs bucket\n");
  }
  console.log(`scenes: ${scenes.length}`);

  let inTotal = 0;
  let outTotal = 0;
  for (const s of scenes) {
    const r = await transcodeScene(s, { apply, force });
    if (!r) continue;
    for (const e of Object.values(r.entries)) {
      inTotal += e.source_bytes;
      outTotal += e.bytes;
    }
  }
  if (outTotal > 0) {
    console.log(
      `\ncompressed tier across processed scenes: ` +
        `${(inTotal / 1e6).toFixed(1)} MB PLY -> ${(outTotal / 1e6).toFixed(1)} MB SPZ ` +
        `(${(inTotal / outTotal).toFixed(2)}x, +${((outTotal / inTotal) * 100).toFixed(0)}% storage)`,
    );
  }
}

await main();
