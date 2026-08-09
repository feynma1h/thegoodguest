"""POST /compress receiver — the compressed-splat third stage (decisions
0125/0126; this file is 0126's "new captures are born slow" residue).

Enqueued by /process's success path after release_ready, beside the /shell
enqueue and for the same reason: it is derived-asset work that must not be
able to un-ready a room. Writes an SPZ beside every PLY the viewer actually
renders, plus the index that tells api-public they exist:

  gs://{PERCEPTION_OUTPUTS_BUCKET}/scenes/{id}/frames/NNNN/splats/NN_x.spz
  gs://{PERCEPTION_OUTPUTS_BUCKET}/scenes/{id}/compressed.json

Both additive, both invisible to every existing reader. NEVER manifest.json
(single writer stays /process — and 0126's reason stands: a re-drive
rewrites the manifest and would silently erase an index living inside it),
NEVER Firestore, no scene lease.

WHY THIS RUNS HERE, ON A GPU SERVICE, DOING NO GPU WORK
The transcode is CPU-and-IO only, so a dedicated service was the obvious
alternative and was rejected on cost-of-surface: it would need its own
Cloud Run service, SA, IAM, cloudbuild config, smoke and runbook phase for
a job measured at ~1.2 s per splat. /shell already established that a
derived-asset stage rides this service without touching a model, and this
stage reuses its queue, its invoker SA and its enqueue pattern verbatim.
The marginal GPU-seconds are real but small against the ~1500 GPU-s a
capture already spends, and the instance is warm because the enqueue fires
the moment /process finishes. A scheduled sweep was rejected as the primary
path for the one reason that matters: it does not fix born-slow for the
person who just captured the room. The sweep still exists as the backfill
and re-drive path (tools/transcode_scene_splats.mjs --all).

WHY THE ENCODE IS A SUBPROCESS
The encoder must be Spark's own SpzWriter — the same build the browser
decodes with (0126) — which is JavaScript. So Python owns GCS and the
index (it already holds credentials in-process; the container has no
gcloud CLI) and Node owns only bytes-in/bytes-out, via tools/spz_encode.mjs
shared with the operator tool. Nothing authenticates twice.

FAILURE POSTURE
Every failure degrades to "no compressed tier for that splat", which is
already a supported state end to end: api-public's asset_urls never
narrows, so a missing index entry falls back to the PLY that has always
been there. One splat that will not encode is logged and skipped, not
raised — the per-object soft-fail precedent (0048) — because failing the
scene would throw away the splats that DID encode. Running out of request
budget writes the index with what is banked, for the same reason.

Response classification mirrors /shell: completed and poison-class
outcomes return 200 (Cloud Tasks drains), environmental failures 5xx
(Cloud Tasks retries).

Consumers: server.py (POST /compress), tests/test_compress_receiver.py.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
import tempfile
import time
from pathlib import Path

from fastapi import Request
from fastapi.responses import JSONResponse
from process_receiver import (
    EnvironmentalError,
    PoisonError,
    _gcs_blob_exists_and_get,
    _gcs_upload_for_scene,
)
from pydantic import BaseModel

logger = logging.getLogger(__name__)

# Bump only when the index's SHAPE changes. Kept equal to the operator
# tool's INDEX_VERSION on purpose: both write the same document, and a
# reader must not be able to tell which of them produced it.
INDEX_VERSION = 1

# The Node entrypoint. Baked at /app/tools/spz_encode.mjs in the image; the
# env var exists so a test or a local run can point at the checkout.
SPZ_ENCODER = os.environ.get("SPZ_ENCODER_PATH", "/app/tools/spz_encode.mjs")
NODE_BIN = os.environ.get("NODE_BIN", "node")

# Per-splat wall clock for the encoder subprocess. Measured ~1.2 s for a
# 34 MB / 500k-Gaussian splat on a laptop; this is a hang guard, not a
# budget, and is deliberately far above the measurement.
ENCODE_TIMEOUT_S = float(os.environ.get("SPZ_ENCODE_TIMEOUT_S", "300"))

# Seconds held back before STARTING another splat: must cover one splat's
# download + encode + upload worst case.
COMPRESS_BUDGET_RESERVE_S = 120.0


class CompressRequest(BaseModel):
    """Cloud Tasks payload for POST /compress.

    Deliberately scene-only: everything this stage reads already lives in
    the outputs bucket, so it never touches the captures bucket and a
    swept capture is not a failure mode here.
    """

    scene_id: str
    force: bool = False


def rendered_splat_uris(manifest: dict) -> list[str]:
    """The set the viewer actually fetches — assembleScene's exact rule
    (web/src/lib/api/types.ts), mirrored by the operator tool.

    Unplaced objects are signed by api-public but never fetched, so
    compressing them would cost storage and buy the user nothing.
    """
    uris = []
    for obj in manifest.get("objects") or []:
        if not isinstance(obj, dict):
            continue
        if obj.get("placed") and obj.get("world_transform") and obj.get("splat_gcs_uri"):
            uris.append(obj["splat_gcs_uri"])
    return sorted(set(uris))


def spz_uri_for(ply_uri: str) -> str | None:
    """The .spz sibling, or None when the source is not a .ply."""
    if not ply_uri.endswith(".ply"):
        return None
    return ply_uri[: -len(".ply")] + ".spz"


def _blob_path(gcs_uri: str, bucket: str) -> str | None:
    """The blob path within `bucket`, or None when the URI names another
    bucket — a splat outside the outputs bucket is not ours to transcode."""
    prefix = f"gs://{bucket}/"
    if not gcs_uri.startswith(prefix):
        return None
    return gcs_uri[len(prefix):]


def _stat(bucket: str, blob_path: str):
    """(size, generation) for a blob, or None when it does not exist.

    Both are recorded in the index so the next run can tell "already built
    against this exact source" from "the source changed under us" — the
    hazard 0126 named, a re-drive rewriting the SAME path with new content.
    """
    from google.cloud import storage  # deferred: not installed in tests

    try:
        blob = storage.Client().bucket(bucket).get_blob(blob_path)
    except Exception as exc:  # pragma: no cover - transport
        raise EnvironmentalError(f"stat failed for {blob_path}: {exc}") from exc
    if blob is None:
        return None
    return int(blob.size), str(blob.generation)


def encode_ply_bytes(ply_bytes: bytes, source_uri: str) -> tuple[bytes, int]:
    """(spz_bytes, gaussians) via the shared Node encoder.

    Raises PoisonError when the encoder itself is unusable (missing node,
    missing module) — retrying a broken image cannot help — and
    EnvironmentalError for a failure on THIS splat, which the caller
    demotes to a skip rather than propagating.
    """
    if not Path(SPZ_ENCODER).exists():
        raise PoisonError(f"spz encoder not found at {SPZ_ENCODER}")

    with tempfile.TemporaryDirectory(prefix="spz-") as tmp:
        src = Path(tmp) / "in.ply"
        dst = Path(tmp) / "out.spz"
        src.write_bytes(ply_bytes)
        try:
            proc = subprocess.run(
                [NODE_BIN, SPZ_ENCODER, str(src), str(dst), "--source-uri", source_uri],
                capture_output=True,
                timeout=ENCODE_TIMEOUT_S,
            )
        except FileNotFoundError as exc:
            raise PoisonError(f"node not available: {exc}") from exc
        except subprocess.TimeoutExpired as exc:
            raise EnvironmentalError(
                f"encoder timed out after {ENCODE_TIMEOUT_S}s on {source_uri}"
            ) from exc

        stderr = proc.stderr.decode("utf-8", "replace").strip()
        if proc.returncode == 2:
            # The encoder's own "cannot load Spark" exit: a broken image.
            raise PoisonError(f"spz encoder unusable: {stderr[-500:]}")
        if proc.returncode != 0:
            raise EnvironmentalError(
                f"encode failed for {source_uri} (rc={proc.returncode}): {stderr[-500:]}"
            )
        if not dst.exists():
            raise EnvironmentalError(f"encoder wrote no output for {source_uri}")

        # Spark logs to stdout of its own accord; the encoder redirects that
        # to stderr, but parse the LAST line regardless so a future library
        # that slips a line through cannot corrupt the read.
        stdout = proc.stdout.decode("utf-8", "replace").strip()
        try:
            stats = json.loads(stdout.splitlines()[-1])
            gaussians = int(stats["gaussians"])
        except (ValueError, KeyError, IndexError) as exc:
            raise EnvironmentalError(
                f"encoder stats unreadable for {source_uri}: {stdout[-200:]!r}"
            ) from exc
        return dst.read_bytes(), gaussians


def run_compress(
    *,
    scene_id: str,
    outputs_bucket: str,
    deadline: float | None = None,
    force: bool = False,
) -> dict:
    """Build (or refresh) the scene's compressed tier. Returns the response
    body. Raises EnvironmentalError only for failures that a retry could
    plausibly fix."""
    base = f"gs://{outputs_bucket}"
    manifest_raw = _gcs_blob_exists_and_get(
        outputs_bucket, f"scenes/{scene_id}/manifest.json"
    )
    if manifest_raw is None:
        # No manifest = the scene never reached ready. Nothing to compress
        # and nothing a retry would find; drain.
        logger.info("compress noop (no manifest) scene_id=%s", scene_id)
        return {"status": "noop", "reason": "no_manifest", "scene_id": scene_id}

    try:
        manifest = json.loads(manifest_raw)
    except ValueError as exc:
        raise PoisonError(f"manifest is not JSON: {exc}") from exc

    uris = rendered_splat_uris(manifest)
    if not uris:
        logger.info("compress noop (no rendered splats) scene_id=%s", scene_id)
        return {"status": "noop", "reason": "no_rendered_splats", "scene_id": scene_id}

    index_blob = f"scenes/{scene_id}/compressed.json"
    existing_raw = _gcs_blob_exists_and_get(outputs_bucket, index_blob)
    prior = {}
    if existing_raw is not None:
        try:
            prior = (json.loads(existing_raw) or {}).get("entries") or {}
        except ValueError:
            # A corrupt index is not worth failing over: rebuild it.
            logger.warning("compress: unreadable index, rebuilding scene_id=%s", scene_id)

    entries: dict[str, dict] = {}
    work: list[tuple[str, str, int, str]] = []  # (ply_uri, blob_path, size, generation)
    missing = 0
    for ply_uri in uris:
        blob_path = _blob_path(ply_uri, outputs_bucket)
        if blob_path is None:
            logger.warning("compress: splat outside outputs bucket, skipped %s", ply_uri)
            continue
        stat = _stat(outputs_bucket, blob_path)
        if stat is None:
            missing += 1
            continue
        size, generation = stat
        p = prior.get(ply_uri)
        if (
            not force
            and isinstance(p, dict)
            and p.get("source_generation") == generation
            and p.get("source_bytes") == size
        ):
            entries[ply_uri] = p  # already built against this exact source
            continue
        work.append((ply_uri, blob_path, size, generation))

    if not work and existing_raw is not None:
        logger.info(
            "compress noop (index current) scene_id=%s entries=%d", scene_id, len(entries)
        )
        return {
            "status": "noop",
            "reason": "already_current",
            "scene_id": scene_id,
            "entries": len(entries),
        }

    built = 0
    failed = 0
    budget_stopped = False
    in_bytes = 0
    out_bytes = 0
    for ply_uri, blob_path, size, generation in work:
        if deadline is not None and (deadline - time.monotonic()) < COMPRESS_BUDGET_RESERVE_S:
            # Ship what is banked: a partial index is strictly better than
            # none, because every absent entry falls back to its PLY.
            budget_stopped = True
            logger.info(
                "compress budget_stop scene_id=%s built=%d remaining=%d",
                scene_id, built, len(work) - built - failed,
            )
            break
        spz_uri = spz_uri_for(ply_uri)
        if spz_uri is None:
            logger.warning("compress: not a .ply, skipped %s", ply_uri)
            continue
        try:
            ply_bytes = _gcs_blob_exists_and_get(outputs_bucket, blob_path)
            if ply_bytes is None:
                missing += 1
                continue
            spz_bytes, gaussians = encode_ply_bytes(ply_bytes, ply_uri)
            spz_blob = _blob_path(spz_uri, outputs_bucket)
            _gcs_upload_for_scene(
                f"{base}/", spz_blob, spz_bytes, "application/octet-stream"
            )
        except PoisonError:
            raise
        except Exception as exc:
            # One splat's failure costs that splat its compressed tier and
            # nothing else.
            failed += 1
            logger.warning("compress: splat failed, skipped %s: %s", ply_uri, exc)
            continue

        entries[ply_uri] = {
            "uri": spz_uri,
            "bytes": len(spz_bytes),
            "gaussians": gaussians,
            "source_bytes": size,
            "source_generation": generation,
        }
        built += 1
        in_bytes += size
        out_bytes += len(spz_bytes)
        logger.info(
            "compress splat scene_id=%s %s %.1fMB -> %.2fMB (%.2fx, %d gaussians)",
            scene_id, ply_uri.rsplit("/", 1)[-1], size / 1e6, len(spz_bytes) / 1e6,
            size / max(len(spz_bytes), 1), gaussians,
        )

    index = {
        "compressed_version": INDEX_VERSION,
        "format": "spz",
        "encoder": "sparkjsdev/spark SpzWriter",
        "entries": entries,
    }
    _gcs_upload_for_scene(
        f"{base}/", index_blob,
        json.dumps(index, indent=1, sort_keys=True).encode("utf-8"),
        "application/json",
    )

    logger.info(
        "compress done scene_id=%s entries=%d built=%d failed=%d missing=%d "
        "budget_stopped=%s %.1fMB -> %.1fMB",
        scene_id, len(entries), built, failed, missing, budget_stopped,
        in_bytes / 1e6, out_bytes / 1e6,
    )
    return {
        "status": "ready",
        "scene_id": scene_id,
        "entries": len(entries),
        "built": built,
        "failed": failed,
        "missing_sources": missing,
        "budget_stopped": budget_stopped,
    }


async def handle_compress(
    request: Request,
    req: CompressRequest,
    *,
    oidc_verifier,  # OIDCVerifier | None (None disables auth, for tests)
    outputs_bucket: str,
    deadline: float | None = None,
) -> JSONResponse:
    """Core handler for POST /compress. No scene lease, no Firestore, no
    model — see the module docstring. The sync core runs off the event loop
    so /health stays responsive during the transcode walk."""
    from oidc import OIDCError

    if oidc_verifier is not None:
        try:
            oidc_verifier.verify(request.headers.get("Authorization"))
        except OIDCError as exc:
            logger.warning("compress OIDC rejected: %s %s", exc.code, exc.detail)
            return JSONResponse(
                status_code=401,
                content={"error": exc.code, "detail": exc.detail},
            )

    try:
        body = await asyncio.to_thread(
            run_compress,
            scene_id=req.scene_id,
            outputs_bucket=outputs_bucket,
            deadline=deadline,
            force=req.force,
        )
    except PoisonError as exc:
        logger.error("compress: poison failure for scene %s: %s", req.scene_id, exc)
        return JSONResponse({"status": "failed", "reason": str(exc)})
    except EnvironmentalError as exc:
        logger.error("compress: environmental failure for scene %s: %s", req.scene_id, exc)
        return JSONResponse(status_code=500, content={"status": "error", "reason": str(exc)})
    except Exception as exc:
        logger.exception("compress: unexpected failure for scene %s", req.scene_id)
        return JSONResponse(status_code=500, content={"status": "error", "reason": str(exc)})

    return JSONResponse(body)
