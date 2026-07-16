"""Ingest-side image-blob validation for CaptureBundle RGB frames.

Validates that every RGB frame blob is both large enough and matches the
expected image format before the bundle is dispatched to the GPU pipeline.
This fast-fails bundles with non-decodable image data at ingest time (~3 s)
instead of letting them burn expensive GPU capacity before failing at
reconstruction.

Design constraints:
  - Size is the PRIMARY check: catches zero-byte uploads, truncated uploads,
    and tiny synthetic test-fixture blobs. The minimum (1024 bytes) is
    intentionally conservative — valid JPEG/PNG images are at least several KB.
  - Magic-byte check is SECONDARY: catches format-consistency failures (file
    named .jpg but containing PNG data, or arbitrary non-image data that
    happens to be large enough). It is NOT a full decode; it only verifies
    the first few bytes match the claimed extension.
  - RGB frames only. Depth (.f32), confidence, and USDZ files are intentionally
    excluded: they are not decoded by the perception pipeline using image
    libraries, so the same "magic" heuristic does not apply.
  - No PIL/Pillow. PIL.verify() truncates the file object and requires a full
    decode pass; it is heavier than what we need here. If full decode
    verification is ever added, wire it in here under an optional flag and add
    the Pillow dependency to pyproject.toml + Dockerfile.

Consumers: services/api-internal/ingest_server.py (called from _validate_image_blobs wrapper).
"""
from __future__ import annotations

import concurrent.futures
import logging
import os
from typing import Optional

from roomstudio_api_core.scene import InvalidBlobReason

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# 1 KiB. Valid JPEG and PNG images are at minimum several KB, while synthetic
# test-fixture blobs are far smaller. This threshold is the primary check that
# catches zero-byte, truncated, and synthetic-fixture blobs.
MIN_IMAGE_SIZE_BYTES: int = 1024

# First bytes that identify each supported format.
_JPEG_MAGIC: bytes = b"\xff\xd8\xff"
_PNG_MAGIC: bytes = b"\x89PNG\r\n\x1a\n"

# Number of bytes to fetch from GCS for the magic check. 8 bytes covers PNG
# fully (8 bytes); JPEG needs 3. We read 16 to leave room for future formats.
_HEADER_READ_BYTES: int = 16

# Extension → expected magic prefix.
_EXT_MAGIC: dict[str, bytes] = {
    ".jpg": _JPEG_MAGIC,
    ".jpeg": _JPEG_MAGIC,
    ".png": _PNG_MAGIC,
}


# ---------------------------------------------------------------------------
# GCS I/O — isolated for patching in tests
# ---------------------------------------------------------------------------

def _fetch_blob_header(bucket_name: str, blob_path: str) -> tuple[int, bytes]:
    """Return (total_size_bytes, header_bytes) from GCS.

    Downloads blob metadata (for size) and up to _HEADER_READ_BYTES of content.
    This is the only GCS I/O in this module; patch it in tests to avoid network
    calls.

    Returns (0, b"") for blobs that are reported as 0 bytes (should not happen
    for finalized GCS objects, but handled defensively).
    """
    from google.cloud import storage  # deferred: safe to import only in non-test paths

    blob = storage.Client().bucket(bucket_name).blob(blob_path)
    blob.reload()
    size = blob.size or 0
    if size == 0:
        return 0, b""
    read_end = min(_HEADER_READ_BYTES - 1, size - 1)
    header = blob.download_as_bytes(start=0, end=read_end)
    return size, header


# ---------------------------------------------------------------------------
# Per-blob check
# ---------------------------------------------------------------------------

def _check_rgb_blob(
    bucket_name: str,
    full_blob_path: str,
    rel_path: str,
) -> Optional[tuple[str, str]]:
    """Check one RGB blob. Return (rel_path, reason) if invalid, None if valid.

    Checks (in order):
      1. TOO_SMALL — size < MIN_IMAGE_SIZE_BYTES
      2. UNRECOGNIZED_FORMAT — extension not in known image format set
      3. BAD_MAGIC — first bytes don't match the extension's expected prefix
    """
    size, header = _fetch_blob_header(bucket_name, full_blob_path)

    if size < MIN_IMAGE_SIZE_BYTES:
        logger.info(
            "blob_invalid: path=%s size=%d reason=too_small", rel_path, size
        )
        return rel_path, InvalidBlobReason.TOO_SMALL

    # Determine expected magic from extension.
    _, ext = os.path.splitext(rel_path.lower())
    expected_magic = _EXT_MAGIC.get(ext)
    if expected_magic is None:
        # Extension is not in the known image format set. Depth (.f32),
        # confidence, and USDZ files are never passed here (caller filters
        # to RGB paths only), so this is genuinely unrecognized.
        logger.info(
            "blob_invalid: path=%s ext=%s reason=unrecognized_format",
            rel_path,
            ext or "(none)",
        )
        return rel_path, InvalidBlobReason.UNRECOGNIZED_FORMAT

    if not header.startswith(expected_magic):
        logger.info(
            "blob_invalid: path=%s ext=%s header_hex=%s reason=bad_magic",
            rel_path,
            ext,
            header[:8].hex(),
        )
        return rel_path, InvalidBlobReason.BAD_MAGIC

    return None


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def validate_image_blobs(bundle, bucket: str, bundle_id: str) -> list[dict]:
    """Check all RGB frame blobs in bundle for decodability.

    Runs checks in parallel using ThreadPoolExecutor. Returns a list of
    invalid-blob descriptors:

        [{"relative_path": str, "reason": str}, ...]

    An empty list means all RGB blobs passed. The caller (ingest_server.py)
    is responsible for transitioning the Scene to FAILED_INVALID when this
    list is non-empty.

    Intentional exclusions (see module docstring):
      - Depth frames (.f32)
      - Confidence maps
      - USDZ room-plan meshes

    Only RGB frame blobs (frame.rgb_gcs_path) are checked.
    """
    # Collect (rel_path, full_blob_path) pairs for all RGB frames.
    rgb_checks: list[tuple[str, str]] = []
    for frame in bundle.frames:
        if frame.rgb_gcs_path:
            rel_path = frame.rgb_gcs_path
            full_path = f"captures/{bundle_id}/{rel_path}"
            rgb_checks.append((rel_path, full_path))

    if not rgb_checks:
        return []

    invalid: list[dict] = []

    def _worker(args: tuple[str, str]) -> Optional[tuple[str, str]]:
        rel_path, full_path = args
        return _check_rgb_blob(bucket, full_path, rel_path)

    max_workers = min(8, len(rgb_checks))
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as pool:
        for result in pool.map(_worker, rgb_checks):
            if result is not None:
                rel_path, reason = result
                invalid.append({"relative_path": rel_path, "reason": reason})

    return invalid
