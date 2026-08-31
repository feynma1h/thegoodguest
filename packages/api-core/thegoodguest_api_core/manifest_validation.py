"""Semantic manifest validation for POST /captures/{bundle_id}/upload_session.

Decisions 0015/0018 close two admission gaps here: every manifest entry
must declare a real, bounded expected_size_bytes, and every relative_path must
match the shapes the capture clients actually produce. The mint endpoint is
the admission gate for upload capacity — a URI minted here is authority to
write bytes into the captures bucket, so what gets minted is exactly what a
conforming client uploads, nothing else.

The path grammar is the union of what the deployed writers emit:

    bundle.pb                      (exactly once, root level)
    frames/<name>.jpg              (RGB keyframes)
    depth/<name>.f32               (LiDAR depth rasters)
    confidence/<name>.png          (LiDAR confidence maps)
    roomplan/<name>.json           (CapturedRoom JSON, decision 0077)
    roomplan/<name>.usdz           (RoomPlan debug artifact)

Sources of truth for that inventory: ios ManifestBuilder.swift (blobDirs) and
the api-core capture-bundle fixture builder. A new blob class is a client
release, so extending the allowlist is a code change here by design — there
is deliberately no env override for the grammar itself.

Size rules:
  - expected_size_bytes is REQUIRED, an int (bool excluded), and >= 1. The
    mint layer then always sets X-Upload-Content-Length, so GCS itself
    enforces the declared size on the upload (0015's uncapped-upload hole).
  - Per-blob cap: UPLOAD_SESSION_MAX_BLOB_BYTES (default 100 MiB).
  - bundle.pb cap: 10 MiB, mirroring api-internal's MAX_BUNDLE_BYTES fetch
    guard — an oversized bundle.pb would otherwise upload fine and then
    bounce forever at ingest.
  - Whole-manifest caps: UPLOAD_SESSION_MAX_PATHS entries (default 6000;
    the largest real manifest to date is 2,170 paths, 2026-08-06) and
    UPLOAD_SESSION_MAX_TOTAL_BYTES declared total (default 8 GiB; largest
    real bundle to date ~517 MB).

Env caps are read per call (the _mint_concurrency pattern) so tests and
emergency retunes don't need a restart. Unknown extra keys on an entry are
ignored — clients may grow the entry shape additively (0035 frozen shape is
about what the server reads, not what clients send).

Consumers: services/api-public (POST /captures/{bundle_id}/upload_session).
"""
from __future__ import annotations

import os
import re

from .upload_session_repo import validate_manifest_path

# Per-subdirectory extension allowlist. Keys are the only permitted top-level
# directories; bundle.pb is the only permitted root-level file.
ALLOWED_SUBDIRS: dict[str, frozenset[str]] = {
    "frames": frozenset({"jpg"}),
    "depth": frozenset({"f32"}),
    "confidence": frozenset({"png"}),
    "roomplan": frozenset({"json", "usdz"}),
}

# Filename charset: conservative, no leading dot (hidden files), matching
# every name the clients emit (zero-padded frame indices, room.json, …).
_FILENAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")

# Longest real path today is ~26 chars; 128 is headroom, not a target.
_MAX_PATH_CHARS = 128

# Mirrors services/api-internal/ingest_server.py MAX_BUNDLE_BYTES (10 MiB).
# Not importable from here (api-core must not depend on a service); keep the
# two in sync by hand — a mint-time cap larger than the ingest fetch guard
# would let a bundle.pb upload cleanly and then bounce forever at ingest.
BUNDLE_PB_MAX_BYTES = 10 * 1024 * 1024

_ENV_MAX_PATHS = "UPLOAD_SESSION_MAX_PATHS"
_DEFAULT_MAX_PATHS = 6000

_ENV_MAX_BLOB_BYTES = "UPLOAD_SESSION_MAX_BLOB_BYTES"
_DEFAULT_MAX_BLOB_BYTES = 100 * 1024 * 1024  # 100 MiB

_ENV_MAX_TOTAL_BYTES = "UPLOAD_SESSION_MAX_TOTAL_BYTES"
_DEFAULT_MAX_TOTAL_BYTES = 8 * 1024 * 1024 * 1024  # 8 GiB


def _env_int(name: str, default: int) -> int:
    try:
        return max(1, int(os.environ.get(name, default)))
    except ValueError:
        return default


def _validate_path_shape(path: str) -> str | None:
    """Structural path checks beyond validate_manifest_path. Returns an error
    detail string, or None if the path is well-formed."""
    if len(path) > _MAX_PATH_CHARS:
        return f"path exceeds {_MAX_PATH_CHARS} characters: {path[:64]!r}…"
    if path == "bundle.pb":
        return None
    parts = path.split("/")
    if len(parts) != 2:
        return (
            f"path must be 'bundle.pb' or '<dir>/<file>' (exactly one level): {path!r}"
        )
    subdir, filename = parts
    if subdir not in ALLOWED_SUBDIRS:
        allowed = ", ".join(sorted(ALLOWED_SUBDIRS))
        return f"unknown directory {subdir!r} in {path!r}; allowed: {allowed}"
    if not _FILENAME_RE.match(filename):
        return f"invalid filename {filename!r} in {path!r}"
    ext = filename.rsplit(".", 1)[-1] if "." in filename else ""
    if ext not in ALLOWED_SUBDIRS[subdir]:
        allowed = ", ".join(sorted(ALLOWED_SUBDIRS[subdir]))
        return (
            f"extension {ext!r} not allowed under {subdir}/ in {path!r}; "
            f"allowed: {allowed}"
        )
    return None


def _validate_size(path: str, entry: dict, max_blob_bytes: int) -> str | None:
    """expected_size_bytes: required, an int (bool excluded), 1..cap."""
    size = entry.get("expected_size_bytes")
    if size is None:
        return f"expected_size_bytes is required (missing for {path!r})"
    if isinstance(size, bool) or not isinstance(size, int):
        return (
            f"expected_size_bytes must be an integer byte count for {path!r}, "
            f"got {size!r}"
        )
    if size < 1:
        return (
            f"expected_size_bytes must be >= 1 for {path!r}, got {size} "
            "(the client reads the real on-disk size; 0 means the file was "
            "unreadable at manifest-build time)"
        )
    cap = BUNDLE_PB_MAX_BYTES if path == "bundle.pb" else max_blob_bytes
    if size > cap:
        return f"expected_size_bytes {size} exceeds the {cap}-byte cap for {path!r}"
    return None


def validate_manifest(manifest: list[dict]) -> str | None:
    """Validate a full upload-session manifest.

    Returns None when the manifest is acceptable, else a human-readable error
    detail for the 400 invalid_manifest response. The caller handles the
    empty-manifest case separately (400 manifest_empty predates this module).
    """
    max_paths = _env_int(_ENV_MAX_PATHS, _DEFAULT_MAX_PATHS)
    max_blob_bytes = _env_int(_ENV_MAX_BLOB_BYTES, _DEFAULT_MAX_BLOB_BYTES)
    max_total_bytes = _env_int(_ENV_MAX_TOTAL_BYTES, _DEFAULT_MAX_TOTAL_BYTES)

    if len(manifest) > max_paths:
        return f"manifest has {len(manifest)} entries, exceeding the {max_paths} cap"

    seen: set[str] = set()
    bundle_pb_count = 0
    total_bytes = 0
    for entry in manifest:
        if not isinstance(entry, dict):
            return f"manifest entries must be objects, got {type(entry).__name__}"
        path = entry.get("relative_path", "")
        err = validate_manifest_path(path)
        if err:
            return err
        err = _validate_path_shape(path)
        if err:
            return err
        if path in seen:
            return f"duplicate relative_path in manifest: {path!r}"
        seen.add(path)
        if path == "bundle.pb":
            bundle_pb_count += 1
        err = _validate_size(path, entry, max_blob_bytes)
        if err:
            return err
        total_bytes += entry["expected_size_bytes"]

    if bundle_pb_count != 1:
        return (
            "manifest must include exactly one 'bundle.pb' entry (the ingest "
            f"trigger); found {bundle_pb_count}"
        )
    if total_bytes > max_total_bytes:
        return (
            f"manifest declares {total_bytes} total bytes, exceeding the "
            f"{max_total_bytes}-byte cap"
        )
    return None
