"""roomstudio bundle ingester — FastAPI service.

Accepts a serialized CaptureBundle by GCS URI, validates it against the
capture_bundle.proto contract, and returns a structured summary or a
structured error.

Endpoints:
  POST /ingest  — validate a bundle, return summary on success.

This route is acknowledgement only: it validates and summarizes the bundle
but does NOT dispatch any perception work. Perception orchestration is a
future concern (see SERVER_ORCHESTRATION_NOTE.md).

Run locally (from services/api/):
  uvicorn server:app --reload --port 8080

Consumed by: the iOS capture app (future) and integration tests.
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel

# Ensure roomstudio_schemas is importable in local dev without a virtualenv
# having it installed. In production it is a declared dependency and will be
# installed. The sys.path guard avoids double-adding it if already present.
_schemas_path = Path(__file__).resolve().parents[2] / "packages/schemas"
if str(_schemas_path) not in sys.path:
    sys.path.insert(0, str(_schemas_path))

from roomstudio_schemas import CaptureBundle, CaptureTier  # noqa: E402
from validation import validate_bundle  # noqa: E402


app = FastAPI(
    title="roomstudio-api",
    description="Capture-bundle ingester. Validates and acknowledges iOS capture bundles.",
    version="0.1.0",
)


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------

class IngestRequest(BaseModel):
    """Body for POST /ingest."""
    bundle_gcs_uri: str


class IngestSummary(BaseModel):
    """Returned on a successful ingest (HTTP 200).

    Contains enough metadata to confirm what was received and route to
    downstream processing, without echoing the full bundle back.

    tier is the enum name (e.g. "ARKIT_ONLY") for human readability.
    tier_value is the stable integer wire value; use this on the iOS side
    where comparing strings across versions is a footgun.
    """
    bundle_id: str
    schema_version: str
    tier: str
    tier_value: int
    frame_count: int
    depth_frame_count: int
    user_id: str
    has_room_plan: bool
    started_at_us: int
    ended_at_us: int


class IngestError(BaseModel):
    """Returned on a validation failure (HTTP 400).

    error:  machine-readable code, stable across versions.
    detail: human-readable explanation with enough context to act on.
    """
    error: str
    detail: str


# ---------------------------------------------------------------------------
# GCS fetch — isolated so tests can patch without google-cloud-storage
# ---------------------------------------------------------------------------

MAX_BUNDLE_BYTES: int = 10 * 1024 * 1024  # 10 MiB — proto metadata only, no pixel data


def _fetch_bundle_bytes(gcs_uri: str) -> bytes:
    """Download bundle bytes from GCS.

    Checks blob.size before downloading and rejects anything over
    MAX_BUNDLE_BYTES. The bundle is metadata only (no pixel data); anything
    larger than 10 MiB is almost certainly a mis-upload.

    Wrapped in its own function so integration tests can patch it without
    needing google-cloud-storage installed. The deferred import of
    google.cloud.storage means importing this module in tests is also safe.

    Raises ValueError for a malformed URI or an oversized blob; raises
    google.cloud.exceptions.* for GCS errors (NotFound, Forbidden, etc.) —
    callers should handle both.
    """
    from google.cloud import storage  # deferred: not installed in tests

    if not gcs_uri.startswith("gs://"):
        raise ValueError(f"Expected gs:// URI, got: {gcs_uri!r}")
    # Strip scheme and split on the first slash: gs://bucket/path/to/blob
    without_scheme = gcs_uri[5:]
    bucket_name, blob_path = without_scheme.split("/", 1)
    client = storage.Client()
    blob = client.bucket(bucket_name).blob(blob_path)
    blob.reload()  # fetches blob metadata (size, content-type, etc.)
    if blob.size is not None and blob.size > MAX_BUNDLE_BYTES:
        raise ValueError(
            f"Bundle blob is {blob.size} bytes, exceeds limit of "
            f"{MAX_BUNDLE_BYTES} bytes ({MAX_BUNDLE_BYTES // (1024 * 1024)} MiB). "
            "The bundle proto must not contain pixel data inline."
        )
    return blob.download_as_bytes()


# ---------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------

@app.post(
    "/ingest",
    response_model=IngestSummary,
    responses={400: {"model": IngestError}},
    summary="Validate and acknowledge a CaptureBundle",
)
def ingest(req: IngestRequest) -> JSONResponse:
    """Accept a serialized CaptureBundle by GCS URI.

    Fetches the bundle bytes, parses the proto, runs all four validation
    checks, and returns either a summary (200) or a structured error (400).

    Validation checks (see validation.py for details):
      - schema_version is a supported version
      - all camera_pose quaternions are unit-norm within 1e-3
      - depth fields only appear with a LIDAR_* tier
      - all GCS paths are relative (not full gs:// URIs)

    No perception work is dispatched.
    """
    # 1. Fetch from GCS.
    try:
        raw = _fetch_bundle_bytes(req.bundle_gcs_uri)
    except Exception as exc:
        logger.exception("Failed to fetch bundle from GCS: %s", req.bundle_gcs_uri)
        return JSONResponse(
            status_code=400,
            content=IngestError(
                error="bundle_fetch_failed",
                detail=str(exc),
            ).model_dump(),
        )

    # 2. Parse proto.
    bundle = CaptureBundle()
    try:
        bundle.ParseFromString(raw)
    except Exception as exc:
        logger.exception(
            "Failed to parse bundle proto from %s (%d bytes)",
            req.bundle_gcs_uri,
            len(raw),
        )
        return JSONResponse(
            status_code=400,
            content=IngestError(
                error="bundle_parse_failed",
                detail=str(exc),
            ).model_dump(),
        )

    # 3. Validate contract.
    err = validate_bundle(bundle)
    if err:
        error_code, detail = err
        return JSONResponse(
            status_code=400,
            content=IngestError(error=error_code, detail=detail).model_dump(),
        )

    # 4. Build and return summary.
    depth_count = sum(1 for f in bundle.frames if f.HasField("depth"))
    summary = IngestSummary(
        bundle_id=bundle.bundle_id,
        schema_version=bundle.schema_version,
        tier=CaptureTier.Name(bundle.tier),
        tier_value=bundle.tier,
        frame_count=len(bundle.frames),
        depth_frame_count=depth_count,
        user_id=bundle.user_id,
        has_room_plan=bundle.HasField("room_plan"),
        started_at_us=bundle.started_at_us,
        ended_at_us=bundle.ended_at_us,
    )
    return JSONResponse(status_code=200, content=summary.model_dump())
