#!/usr/bin/env node
/**
 * PLY -> SPZ, and nothing else. THE one encoder in this repo.
 *
 * Two callers, deliberately sharing this file rather than each holding a
 * copy of the four lines that matter:
 *
 *   tools/transcode_scene_splats.mjs   the operator's backfill/sweep tool
 *   services/perception-obj/compress_receiver.py  the /compress stage,
 *       which shells out to the CLI below
 *
 * Decision 0126 made the encoder Spark's own SpzWriter so the writer and
 * the browser's reader can never drift apart. Wiring a second caller in
 * (decision 0125's residue: new captures were born slow) makes the same
 * argument apply writer-to-writer — two encoders would be two things to
 * keep in step, and the one that runs unattended in production is the one
 * nobody would notice diverging.
 *
 * NO GCS AND NO CREDENTIALS LIVE HERE. The operator tool reaches the
 * bucket through the gcloud CLI; the service reaches it through
 * google-cloud-storage in Python. The container has no gcloud CLI, and
 * teaching Node to authenticate would be a second credential path to
 * secure for no gain. So this reads a local file and writes a local file,
 * which is the only contract both callers can honestly share.
 *
 * Spark is resolved from SPARK_MODULE_PATH when set (the container bakes
 * it at a fixed path), otherwise from web/node_modules — the same build
 * the browser decodes with, in both cases.
 *
 * Usage (CLI):
 *   node tools/spz_encode.mjs <in.ply> <out.spz> [--source-uri gs://...]
 * Prints one line of JSON to stdout: {"bytes":N,"gaussians":N}
 * Exit 0 on success, 2 on bad usage, 1 on encode failure (stderr carries
 * the reason). Nothing but the JSON goes to stdout, so the Python caller
 * can parse it without filtering log noise.
 */

import { readFileSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");

export const SPARK_PATH =
  process.env.SPARK_MODULE_PATH ||
  join(ROOT, "web/node_modules/@sparkjsdev/spark/dist/spark.module.js");

let _spark = null;

/** The Spark module, loaded once. Exits 2 with a remediation line when it
 * cannot be found — a missing encoder is a setup error, not a transcode
 * failure, and the two should not look alike to a caller. */
export async function loadSpark() {
  if (_spark) return _spark;
  try {
    _spark = await import(`file://${SPARK_PATH}`);
    return _spark;
  } catch (e) {
    console.error(
      `Cannot load Spark from ${SPARK_PATH}\n` +
        `The encoder must be the same build the browser decodes with.\n` +
        `Set SPARK_MODULE_PATH, or run: npm install --prefix web\n\n${e?.message ?? e}`,
    );
    process.exit(2);
  }
}

/**
 * Encode one splat.
 *
 * @param {Uint8Array} fileBytes  the PLY, verbatim
 * @param {string} pathOrUrl      only a hint for Spark's format sniffing
 * @returns {Promise<{fileBytes: Uint8Array, gaussians: number}>}
 *
 * The Gaussian count is read back out of the ENCODED bytes through
 * Spark's own reader rather than carried over from the input. That is the
 * cheap half of a round-trip: it proves the output parses as SPZ and that
 * nothing was dropped, which is the failure worth catching before a file
 * reaches the bucket and a viewer.
 */
export async function encodePly(fileBytes, pathOrUrl = "input.ply") {
  const spark = await loadSpark();
  const out = await spark.transcodeSpz({ inputs: [{ fileBytes, pathOrUrl }] });
  const reader = new spark.SpzReader({ fileBytes: out.fileBytes });
  await reader.parseHeader();
  return { fileBytes: out.fileBytes, gaussians: reader.numSplats };
}

async function main() {
  const argv = process.argv.slice(2);
  // --source-uri takes a value; consume it so it is not read as a path.
  const positional = [];
  let sourceUri = null;
  for (let i = 0; i < argv.length; i++) {
    if (argv[i] === "--source-uri") {
      sourceUri = argv[++i];
    } else if (!argv[i].startsWith("--")) {
      positional.push(argv[i]);
    }
  }
  if (positional.length !== 2 || (sourceUri !== null && !sourceUri)) {
    console.error("usage: node tools/spz_encode.mjs <in.ply> <out.spz> [--source-uri gs://...]");
    process.exit(2);
  }
  const [inPath, outPath] = positional;
  sourceUri = sourceUri || inPath;

  // Spark's encoder writes a progress line to stdout of its own accord
  // (measured: "Compressed N bytes to M bytes"). Stdout is the machine
  // channel here, so send anything the library says to stderr instead and
  // keep the diagnostic rather than suppressing it.
  const realLog = console.log;
  console.log = (...a) => console.error(...a);
  try {
    const { fileBytes, gaussians } = await encodePly(
      new Uint8Array(readFileSync(inPath)),
      sourceUri,
    );
    console.log = realLog;
    writeFileSync(outPath, fileBytes);
    process.stdout.write(
      JSON.stringify({ bytes: fileBytes.byteLength, gaussians }) + "\n",
    );
  } catch (e) {
    console.log = realLog;
    console.error(`encode failed: ${e?.stack ?? e}`);
    process.exit(1);
  }
}

// Only run as a CLI when invoked directly, so importing this module for
// `encodePly` does not consume argv.
if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  await main();
}
