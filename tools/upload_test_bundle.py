#!/usr/bin/env python3
"""Substitute iOS client for smoke-testing the two-service upload path.

Simulates an iOS client: signs in anonymously via Firebase, synthesizes a
CaptureBundle, calls POST /captures/{bundle_id}/upload_session, uploads blobs
in two phases (all non-bundle.pb first, then bundle.pb), and polls
GET /scenes/by-bundle/{bundle_id} until a terminal state or timeout.

Four mutually exclusive modes (positional argument):

  happy-path (default)
      Full end-to-end. Expects scene status=ready → exit 0.

  skip-blob
      Include a blob in the manifest but never PUT to its session URI.
      Expects status=failed_incomplete with the dropped path in missing_paths
      → exit 0. Requires --drop-blob-kind.

  duplicate-event
      Run happy-path to failed_invalid, then re-upload bundle.pb to GCS directly
      (SDK, not resumable URI), wait 15s for Eventarc redelivery, poll again.
      Expects scene_id unchanged and status=failed_invalid → exit 0.

  auth-rejection
      POST /upload_session with an empty Authorization header (no "Bearer "
      prefix). Expects 401 missing_token → exit 0. Never reaches upload or
      polling phases.

Exit codes:
  0  Expected outcome for the selected mode.
  1  Unexpected outcome from a correctly-configured run.
  2  Tool misconfig: bad flags, missing required args, incompatible combos.
  3  Polling timed out.

Contracts pinned in:
  docs/decisions/0017 — manifest derivation and upload sequencing
  docs/decisions/0019 — scene read endpoint and polling contract
  docs/decisions/0020 — failure-mode flag semantics

Run from the repo root:
  python tools/upload_test_bundle.py [mode] --public-url URL --firebase-api-key KEY ...

Required flags (or env-var fallbacks):
  --public-url            SMOKE_PUBLIC_URL
  --internal-url          SMOKE_INTERNAL_URL
  --firebase-api-key      SMOKE_FIREBASE_API_KEY
  --firebase-project-id   SMOKE_FIREBASE_PROJECT_ID
  --gcs-bucket            SMOKE_GCS_BUCKET
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import requests

# Make local packages importable without pip install.
_repo_root = Path(__file__).resolve().parent.parent
for _pkg in ("packages/schemas", "packages/api-core"):
    _p = str(_repo_root / _pkg)
    if _p not in sys.path:
        sys.path.insert(0, _p)

from roomstudio_api_core.test_fixtures.capture_bundle import (  # noqa: E402
    TestBundleArtifacts,
    build_capture_bundle,
    TIER_ARKIT_ONLY,
    TIER_LIDAR_ARKIT,
    TIER_LIDAR_ROOMPLAN,
)

# ---------------------------------------------------------------------------
# Exit codes
# ---------------------------------------------------------------------------

EXIT_OK = 0
EXIT_UNEXPECTED = 1
EXIT_MISCONFIG = 2
EXIT_TIMEOUT = 3

# Seconds after upload completes before a 404 from the scene endpoint becomes
# a stall signal (matching the Eventarc latency window from decision 0019).
_STALL_DETECT_SECONDS = 15.0


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class SmokeError(Exception):
    exit_code: int = EXIT_UNEXPECTED


class UnexpectedOutcome(SmokeError):
    exit_code = EXIT_UNEXPECTED


class Misconfig(SmokeError):
    exit_code = EXIT_MISCONFIG


class PollTimeout(SmokeError):
    exit_code = EXIT_TIMEOUT


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

class Output:
    """Routes progress, verbose detail, and NDJSON events to the right streams.

    progress() → stdout (suppressed in --json mode; folded into events instead)
    detail()   → stderr (only in --verbose mode)
    event()    → stdout as NDJSON (only in --json mode)
    warn()     → stderr (always)
    """

    def __init__(self, verbose: bool, json_mode: bool) -> None:
        self._verbose = verbose
        self._json = json_mode

    def progress(self, msg: str) -> None:
        if not self._json:
            print(msg, flush=True)

    def detail(self, msg: str) -> None:
        if self._verbose:
            print(msg, file=sys.stderr, flush=True)

    def event(self, event_type: str, **kwargs) -> None:
        if self._json:
            data = {"event": event_type, "ts": _now_iso(), **kwargs}
            print(json.dumps(data), flush=True)

    def warn(self, msg: str) -> None:
        print(f"[warn] {msg}", file=sys.stderr, flush=True)


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

class Config:
    def __init__(self, args: argparse.Namespace) -> None:
        def _e(flag: str, env: str) -> str:
            return getattr(args, flag.replace("-", "_")) or os.environ.get(env, "")

        self.mode: str = args.mode
        self.public_url: str = _e("public_url", "SMOKE_PUBLIC_URL").rstrip("/")
        self.internal_url: str = _e("internal_url", "SMOKE_INTERNAL_URL").rstrip("/")
        self.firebase_api_key: str = _e("firebase_api_key", "SMOKE_FIREBASE_API_KEY")
        self.firebase_project_id: str = _e("firebase_project_id", "SMOKE_FIREBASE_PROJECT_ID")
        self.gcs_bucket: str = _e("gcs_bucket", "SMOKE_GCS_BUCKET")
        self.tier: str = args.tier
        self.frame_count: int = args.frame_count
        self.drop_blob_kind: Optional[str] = args.drop_blob_kind
        self.timeout: float = args.timeout
        self.poll_interval: float = args.poll_interval
        self.reuse_uid: Optional[str] = args.reuse_uid
        self.save_uid: Optional[str] = args.save_uid
        self.cleanup: bool = args.cleanup
        self.verbose: bool = args.verbose
        self.json_mode: bool = args.json
        self.use_hardware_id_fallback: bool = args.use_hardware_id_fallback


# ---------------------------------------------------------------------------
# Config validation (exit-2 conditions)
# ---------------------------------------------------------------------------

def validate_config(cfg: Config) -> None:
    """Raise Misconfig for any exit-2 condition. Called before any I/O."""
    required = {
        "--public-url (SMOKE_PUBLIC_URL)": cfg.public_url,
        "--internal-url (SMOKE_INTERNAL_URL)": cfg.internal_url,
        "--firebase-api-key (SMOKE_FIREBASE_API_KEY)": cfg.firebase_api_key,
        "--firebase-project-id (SMOKE_FIREBASE_PROJECT_ID)": cfg.firebase_project_id,
        "--gcs-bucket (SMOKE_GCS_BUCKET)": cfg.gcs_bucket,
    }
    missing = [k for k, v in required.items() if not v]
    if missing:
        raise Misconfig(f"Required flags not set: {', '.join(missing)}")

    if cfg.frame_count < 1:
        raise Misconfig("--frame-count must be >= 1")

    if cfg.mode == "skip-blob":
        if cfg.drop_blob_kind is None:
            raise Misconfig("mode 'skip-blob' requires --drop-blob-kind")
        if cfg.drop_blob_kind in ("depth", "confidence") and cfg.tier == TIER_ARKIT_ONLY:
            raise Misconfig(
                f"--drop-blob-kind {cfg.drop_blob_kind!r} is incompatible with "
                f"--tier arkit-only: arkit-only bundles have no depth or confidence blobs"
            )
        if cfg.drop_blob_kind == "usdz" and cfg.tier != TIER_LIDAR_ROOMPLAN:
            raise Misconfig(
                f"--drop-blob-kind usdz requires --tier lidar-roomplan (got {cfg.tier!r})"
            )

    if cfg.reuse_uid:
        _validate_uid_cache(cfg.reuse_uid)


def _validate_uid_cache(path_str: str) -> None:
    cache_path = Path(path_str)
    if not cache_path.exists():
        raise Misconfig(f"--reuse-uid cache file not found: {path_str}")
    try:
        data = json.loads(cache_path.read_text())
        if not isinstance(data, dict):
            raise ValueError("not a JSON object")
        for key in ("refresh_token", "local_id"):
            if key not in data or not data[key]:
                raise ValueError(f"missing or empty key: {key!r}")
    except Misconfig:
        raise
    except Exception as exc:
        raise Misconfig(f"--reuse-uid cache file malformed ({path_str}): {exc}") from exc


# ---------------------------------------------------------------------------
# Firebase auth
# ---------------------------------------------------------------------------

def authenticate(cfg: Config, out: Output) -> tuple[str, str]:
    """Return (id_token, local_id). Reuses stored UID if --reuse-uid is set."""
    if cfg.reuse_uid:
        cache_path = Path(cfg.reuse_uid)
        data = json.loads(cache_path.read_text())
        local_id = data["local_id"]
        out.detail(f"  refreshing Firebase token for uid={local_id}")
        id_token, new_refresh = _firebase_refresh_token(cfg.firebase_api_key, data["refresh_token"])
        data["refresh_token"] = new_refresh
        cache_path.write_text(json.dumps(data))
        device_id_src = "hardware_id_fallback" if cfg.use_hardware_id_fallback else "provided"
        out.detail(f"  device_id_source: {device_id_src}")
        out.event("auth_complete", local_id=local_id, device_id_source=device_id_src, reused=True)
        out.progress(f"uid: {local_id} (reused)")
        return id_token, local_id

    out.detail("  signing in as new anonymous Firebase user")
    id_token, local_id, refresh_token = _firebase_sign_in_anon(cfg.firebase_api_key)
    if cfg.save_uid:
        cache_path = Path(cfg.save_uid)
        cache_path.write_text(json.dumps({"local_id": local_id, "refresh_token": refresh_token}))
        out.detail(f"  saved UID cache to {cfg.save_uid}")

    device_id_src = "hardware_id_fallback" if cfg.use_hardware_id_fallback else "provided"
    out.detail(f"  device_id_source: {device_id_src}")
    out.event("auth_complete", local_id=local_id, device_id_source=device_id_src, reused=False)
    out.progress(f"uid: {local_id}")
    return id_token, local_id


def _firebase_sign_in_anon(api_key: str) -> tuple[str, str, str]:
    """Return (id_token, local_id, refresh_token) for a new anonymous Firebase user."""
    url = f"https://identitytoolkit.googleapis.com/v1/accounts:signUp?key={api_key}"
    resp = requests.post(url, json={"returnSecureToken": True}, timeout=15)
    if resp.status_code == 400:
        try:
            err = resp.json().get("error", {}).get("message", "")
        except Exception:
            err = resp.text
        raise Misconfig(f"Firebase API key rejected during anonymous sign-in: {err}")
    resp.raise_for_status()
    body = resp.json()
    return body["idToken"], body["localId"], body["refreshToken"]


def _firebase_refresh_token(api_key: str, refresh_token: str) -> tuple[str, str]:
    """Return (new_id_token, new_refresh_token)."""
    url = f"https://securetoken.googleapis.com/v1/token?key={api_key}"
    resp = requests.post(
        url,
        json={"grant_type": "refresh_token", "refresh_token": refresh_token},
        timeout=15,
    )
    if resp.status_code == 400:
        try:
            err = resp.json().get("error", {}).get("message", "")
        except Exception:
            err = resp.text
        raise Misconfig(f"Firebase token refresh rejected (bad refresh_token?): {err}")
    resp.raise_for_status()
    body = resp.json()
    return body["id_token"], body["refresh_token"]


# ---------------------------------------------------------------------------
# Bundle building
# ---------------------------------------------------------------------------

def build_artifacts(
    cfg: Config,
    bundle_id: str,
    user_id: str,
    out: Output,
) -> TestBundleArtifacts:
    """Synthesize a CaptureBundle for the given tier and frame count."""
    include_depth = cfg.tier in (TIER_LIDAR_ARKIT, TIER_LIDAR_ROOMPLAN)
    include_confidence = include_depth
    include_roomplan = cfg.tier == TIER_LIDAR_ROOMPLAN

    artifacts = build_capture_bundle(
        tier=cfg.tier,
        frame_count=cfg.frame_count,
        bundle_id=bundle_id,
        user_id=user_id,
        include_depth=include_depth,
        include_confidence=include_confidence,
        include_roomplan=include_roomplan,
        use_hardware_id_fallback=cfg.use_hardware_id_fallback,
    )

    total_bytes = sum(len(b) for b in artifacts.blobs.values())
    out.progress(
        f"bundle: {len(artifacts.blobs)} blobs, "
        f"{total_bytes} bytes total, tier={cfg.tier}"
    )
    if cfg.verbose:
        for path, blob_bytes in sorted(artifacts.blobs.items()):
            out.detail(f"  blob: {path} ({len(blob_bytes)} bytes)")
    out.event(
        "bundle_built",
        bundle_id=bundle_id,
        tier=cfg.tier,
        blob_count=len(artifacts.blobs),
        total_bytes=total_bytes,
        blob_paths=sorted(artifacts.blobs.keys()),
    )
    return artifacts


# ---------------------------------------------------------------------------
# Upload session
# ---------------------------------------------------------------------------

def _build_manifest(artifacts: TestBundleArtifacts) -> list[dict]:
    """Decision 0017: non-bundle.pb blobs sorted first, bundle.pb last."""
    entries = [
        {"relative_path": p, "expected_size_bytes": len(b)}
        for p, b in sorted(artifacts.blobs.items())
        if p != "bundle.pb"
    ]
    entries.append({
        "relative_path": "bundle.pb",
        "expected_size_bytes": len(artifacts.blobs["bundle.pb"]),
    })
    return entries


def post_upload_session(
    cfg: Config,
    bundle_id: str,
    artifacts: TestBundleArtifacts,
    id_token: str,
    out: Output,
) -> dict[str, str]:
    """POST /captures/{bundle_id}/upload_session.

    Returns {relative_path: session_uri} for all manifest entries.
    The manifest always includes every blob (including any that skip-blob mode
    will later decline to PUT — the server still mints a URI for it).
    """
    manifest = _build_manifest(artifacts)
    url = f"{cfg.public_url}/captures/{bundle_id}/upload_session"
    headers = {"Authorization": f"Bearer {id_token}"}
    body = {"manifest": manifest, "fcm_token": None}

    out.detail(f"POST {url}")
    out.detail(f"  manifest paths: {[e['relative_path'] for e in manifest]}")

    t0 = time.monotonic()
    resp = requests.post(url, json=body, headers=headers, timeout=30)
    latency = time.monotonic() - t0

    out.detail(f"  → {resp.status_code} ({latency:.2f}s)")
    if resp.status_code not in (200, 201):
        out.detail(f"  body: {resp.text}")
        raise UnexpectedOutcome(
            f"POST /upload_session returned {resp.status_code}: {resp.text}"
        )

    entries = resp.json()
    req_paths = {e["relative_path"] for e in manifest}
    resp_paths = {e["relative_path"] for e in entries}
    if req_paths != resp_paths:
        raise UnexpectedOutcome(
            f"upload_session response path set mismatch: "
            f"sent {sorted(req_paths)}, got {sorted(resp_paths)}"
        )

    session_map = {e["relative_path"]: e["session_uri"] for e in entries}
    out.event(
        "upload_session_response",
        bundle_id=bundle_id,
        latency_s=round(latency, 3),
        path_count=len(session_map),
        paths=sorted(session_map.keys()),
    )
    return session_map


# ---------------------------------------------------------------------------
# Blob uploads
# ---------------------------------------------------------------------------

def _put_blob(
    relative_path: str,
    blob_bytes: bytes,
    session_uri: str,
    out: Output,
) -> None:
    """PUT one blob to its GCS resumable session URI (decision 0017)."""
    size = len(blob_bytes)
    headers = {
        "Content-Length": str(size),
        "Content-Range": f"bytes 0-{size - 1}/{size}",
        # No Content-Type: server's X-Upload-Content-Type (set when the URI was
        # minted) controls the stored content type.
    }
    t0 = time.monotonic()
    resp = requests.put(session_uri, data=blob_bytes, headers=headers, timeout=120)
    latency = time.monotonic() - t0
    out.detail(f"  PUT {relative_path}: {resp.status_code} ({latency:.2f}s)")
    if resp.status_code == 308:
        raise UnexpectedOutcome(
            f"PUT {relative_path!r} returned 308 (incomplete resumable upload); "
            "smoke tool sends complete blobs only"
        )
    if resp.status_code not in (200, 201):
        out.detail(f"  body: {resp.text[:200]}")
        raise UnexpectedOutcome(
            f"PUT {relative_path!r} returned {resp.status_code}: {resp.text[:200]}"
        )


def upload_phase1(
    artifacts: TestBundleArtifacts,
    session_map: dict[str, str],
    out: Output,
    *,
    skip_path: Optional[str] = None,
) -> None:
    """Upload all non-bundle.pb blobs in parallel (decision 0017 phase 1)."""
    paths = [
        p for p in artifacts.blobs
        if p != "bundle.pb" and p != skip_path
    ]
    skipped_note = f" (skipping {skip_path!r})" if skip_path else ""
    out.progress(f"Phase 1: uploading {len(paths)} blob(s){skipped_note}")

    errors: list[str] = []

    def _upload(path: str) -> None:
        _put_blob(path, artifacts.blobs[path], session_map[path], out)

    with ThreadPoolExecutor(max_workers=min(8, len(paths) or 1)) as pool:
        futures = {pool.submit(_upload, p): p for p in paths}
        for fut in futures:
            try:
                fut.result()
            except SmokeError:
                raise
            except Exception as exc:
                errors.append(str(exc))

    if errors:
        raise UnexpectedOutcome(f"Phase 1 upload errors: {errors}")

    out.progress("Phase 1 complete")
    out.event("phase_1_complete", blob_count=len(paths), skipped_path=skip_path)


def upload_phase2(
    artifacts: TestBundleArtifacts,
    session_map: dict[str, str],
    out: Output,
) -> None:
    """Upload bundle.pb only (decision 0017 phase 2)."""
    out.progress("Phase 2: uploading bundle.pb")
    _put_blob("bundle.pb", artifacts.blobs["bundle.pb"], session_map["bundle.pb"], out)
    out.progress("Phase 2 complete")
    out.event("phase_2_complete")


# ---------------------------------------------------------------------------
# Polling
# ---------------------------------------------------------------------------

def poll_scene(
    cfg: Config,
    bundle_id: str,
    id_token: str,
    out: Output,
    *,
    start_time: Optional[float] = None,
) -> dict:
    """Poll GET /scenes/by-bundle/{bundle_id} until terminal or timeout.

    Returns the terminal scene dict. Decision 0019 contracts:
      - 404 is normal for the first 15s (Eventarc delivery latency).
      - After 15s, 404 means stall → exit 1.
      - Terminal states: ready, failed, failed_incomplete.
      - --timeout bounds the whole phase → exit 3.
    """
    if start_time is None:
        start_time = time.monotonic()

    url = f"{cfg.public_url}/scenes/by-bundle/{bundle_id}"
    headers = {"Authorization": f"Bearer {id_token}"}
    stall_deadline = start_time + _STALL_DETECT_SECONDS
    timeout_deadline = start_time + cfg.timeout
    terminal = {"ready", "failed", "failed_incomplete", "failed_invalid"}

    while True:
        if time.monotonic() > timeout_deadline:
            raise PollTimeout(
                f"Polling timed out after {cfg.timeout:.0f}s "
                f"(bundle_id={bundle_id})"
            )

        resp = requests.get(url, headers=headers, timeout=15)
        elapsed = time.monotonic() - start_time

        if resp.status_code == 404:
            if time.monotonic() > stall_deadline:
                raise UnexpectedOutcome(
                    f"Ingest stalled: bundle_id={bundle_id} still 404 "
                    f"after {_STALL_DETECT_SECONDS:.0f}s"
                )
            out.detail(f"  poll 404 at {elapsed:.1f}s (Eventarc latency window)")
            out.event("poll", bundle_id=bundle_id, status="not_found", elapsed_s=round(elapsed, 2))
            time.sleep(cfg.poll_interval)
            continue

        if resp.status_code != 200:
            raise UnexpectedOutcome(
                f"Unexpected poll response {resp.status_code}: {resp.text[:200]}"
            )

        scene = resp.json()
        status = scene.get("status", "")
        updated_at = scene.get("updated_at", "")
        out.detail(f"  poll status={status} updated_at={updated_at} at {elapsed:.1f}s")
        out.event(
            "poll",
            bundle_id=bundle_id,
            status=status,
            elapsed_s=round(elapsed, 2),
            updated_at=updated_at,
        )

        if status in terminal:
            out.progress(f"Scene reached terminal state: status={status}")
            return scene

        time.sleep(cfg.poll_interval)


# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------

def do_cleanup(
    cfg: Config,
    bundle_id: str,
    scene_id: Optional[str],
    out: Output,
) -> None:
    """Best-effort deletion of four artifact targets via developer ADC.

    Per decision 0020: each target's failure logs a warning and continues.
    Cleanup never affects the process exit code.
    """
    out.progress("Cleanup: removing artifacts (best-effort)")
    _outputs_bucket = "roomstudio-perception-outputs"

    # 1. GCS captures bucket
    try:
        from google.cloud import storage as gcs
        client = gcs.Client()
        bucket = client.bucket(cfg.gcs_bucket)
        blobs = list(bucket.list_blobs(prefix=f"captures/{bundle_id}/"))
        for blob in blobs:
            blob.delete()
        out.detail(f"  captures: deleted {len(blobs)} blob(s) from gs://{cfg.gcs_bucket}")
    except Exception as exc:
        out.warn(f"cleanup captures GCS failed: {exc}")

    # 2. GCS perception outputs bucket (only if scene_id known)
    if scene_id:
        try:
            from google.cloud import storage as gcs
            client = gcs.Client()
            bucket = client.bucket(_outputs_bucket)
            blobs = list(bucket.list_blobs(prefix=f"scenes/{scene_id}/"))
            for blob in blobs:
                blob.delete()
            out.detail(
                f"  outputs: deleted {len(blobs)} blob(s) from "
                f"gs://{_outputs_bucket}/scenes/{scene_id}/"
            )
        except Exception as exc:
            out.warn(f"cleanup outputs GCS failed: {exc}")

    # 3. Firestore upload_sessions
    # google-cloud-firestore is not in the root venv; use the REST API instead.
    try:
        import google.auth
        import google.auth.transport.requests as _ga_transport
        import requests as _reqs
        _creds, _ = google.auth.default()
        _creds.refresh(_ga_transport.Request())
        _base = (
            f"https://firestore.googleapis.com/v1/projects/{cfg.firebase_project_id}"
            "/databases/(default)/documents"
        )
        _hdrs = {"Authorization": f"Bearer {_creds.token}"}
        _reqs.delete(f"{_base}/upload_sessions/{bundle_id}", headers=_hdrs)
        out.detail(f"  deleted Firestore upload_sessions/{bundle_id}")
    except Exception as exc:
        out.warn(f"cleanup Firestore upload_sessions failed: {exc}")

    # 4. Firestore scenes (only if scene_id known)
    if scene_id:
        try:
            import google.auth
            import google.auth.transport.requests as _ga_transport
            import requests as _reqs
            _creds, _ = google.auth.default()
            _creds.refresh(_ga_transport.Request())
            _base = (
                f"https://firestore.googleapis.com/v1/projects/{cfg.firebase_project_id}"
                "/databases/(default)/documents"
            )
            _hdrs = {"Authorization": f"Bearer {_creds.token}"}
            _reqs.delete(f"{_base}/scenes/{scene_id}", headers=_hdrs)
            out.detail(f"  deleted Firestore scenes/{scene_id}")
        except Exception as exc:
            out.warn(f"cleanup Firestore scenes failed: {exc}")

    out.progress("Cleanup done")


# ---------------------------------------------------------------------------
# Drop-path resolution
# ---------------------------------------------------------------------------

def _drop_path(drop_blob_kind: str) -> str:
    """Return the first-frame relative path for a given blob kind."""
    return {
        "rgb":        "frames/000000.jpg",
        "depth":      "depth/000000.f32",
        "confidence": "confidence/000000.png",
        "usdz":       "roomplan/room.usdz",
    }[drop_blob_kind]


# ---------------------------------------------------------------------------
# Modes
# ---------------------------------------------------------------------------

def run_auth_rejection(
    cfg: Config,
    bundle_id: str,
    out: Output,
) -> tuple[int, None]:
    """Mode: auth-rejection.

    Sends POST /upload_session with an empty Authorization header value
    (no "Bearer " prefix). FastAPI returns 422 for a fully-absent required
    Header, but the app-level 401 check fires when the header is present
    but does not start with "Bearer ". The empty value reliably triggers
    the 401 missing_token branch in the handler.
    """
    url = f"{cfg.public_url}/captures/{bundle_id}/upload_session"
    minimal_manifest = [{"relative_path": "bundle.pb", "expected_size_bytes": 1}]
    out.progress("Sending POST /upload_session with empty Authorization header")
    out.detail(f"POST {url}")

    resp = requests.post(
        url,
        json={"manifest": minimal_manifest, "fcm_token": None},
        headers={"Authorization": ""},
        timeout=15,
    )
    out.detail(f"  → {resp.status_code}")
    out.detail(f"  body: {resp.text}")

    if resp.status_code == 401:
        try:
            error_code = resp.json().get("error", "")
        except Exception:
            error_code = ""
        if error_code == "missing_token":
            out.progress("PASS: 401 missing_token")
            out.event(
                "run_complete",
                mode="auth-rejection",
                outcome="pass",
                http_status=401,
                error=error_code,
            )
            return EXIT_OK, None
        out.progress(f"FAIL: 401 but error={error_code!r}, expected missing_token")
        out.event(
            "run_complete",
            mode="auth-rejection",
            outcome="fail",
            http_status=401,
            error=error_code,
        )
        return EXIT_UNEXPECTED, None

    out.progress(f"FAIL: expected 401, got {resp.status_code}")
    out.event(
        "run_complete",
        mode="auth-rejection",
        outcome="fail",
        http_status=resp.status_code,
    )
    return EXIT_UNEXPECTED, None


def run_happy_path(
    cfg: Config,
    artifacts: TestBundleArtifacts,
    bundle_id: str,
    id_token: str,
    out: Output,
) -> tuple[int, Optional[str]]:
    """Mode: happy-path. Returns (exit_code, scene_id)."""
    session_map = post_upload_session(cfg, bundle_id, artifacts, id_token, out)
    upload_phase1(artifacts, session_map, out)
    upload_phase2(artifacts, session_map, out)

    out.progress("Polling for scene status...")
    scene = poll_scene(cfg, bundle_id, id_token, out)
    scene_id = scene.get("scene_id")
    status = scene.get("status")

    if status == "failed_invalid":
        # The synthetic fixture carries non-decodable placeholder pixels; the
        # ingest validation gate catches them and transitions to failed_invalid
        # (~3 s). This is the expected terminal state until real iPhone images
        # are used. See docs/decisions/0025.
        out.progress(f"PASS: status=failed_invalid (scene_id={scene_id})")
        out.event("run_complete", mode="happy-path", outcome="pass", scene_id=scene_id, status=status)
        return EXIT_OK, scene_id

    out.progress(f"FAIL: expected status=failed_invalid, got status={status}")
    out.event("run_complete", mode="happy-path", outcome="fail", scene_id=scene_id, status=status)
    return EXIT_UNEXPECTED, scene_id


def run_skip_blob(
    cfg: Config,
    artifacts: TestBundleArtifacts,
    bundle_id: str,
    id_token: str,
    out: Output,
) -> tuple[int, Optional[str]]:
    """Mode: skip-blob. Returns (exit_code, scene_id)."""
    drop = _drop_path(cfg.drop_blob_kind)
    out.progress(f"skip-blob: {drop!r} is in the manifest but will not be PUT")

    session_map = post_upload_session(cfg, bundle_id, artifacts, id_token, out)
    upload_phase1(artifacts, session_map, out, skip_path=drop)
    upload_phase2(artifacts, session_map, out)

    out.progress("Polling for scene status...")
    scene = poll_scene(cfg, bundle_id, id_token, out)
    scene_id = scene.get("scene_id")
    status = scene.get("status")
    missing_paths = scene.get("missing_paths", [])

    if status == "failed_incomplete" and drop in missing_paths:
        out.progress(f"PASS: status=failed_incomplete, {drop!r} in missing_paths")
        out.event(
            "run_complete",
            mode="skip-blob",
            outcome="pass",
            scene_id=scene_id,
            status=status,
            missing_paths=missing_paths,
            dropped_path=drop,
        )
        return EXIT_OK, scene_id

    if status == "failed_incomplete":
        out.progress(
            f"FAIL: status=failed_incomplete but {drop!r} not in missing_paths={missing_paths}"
        )
    else:
        out.progress(f"FAIL: expected status=failed_incomplete, got status={status}")
    out.event(
        "run_complete",
        mode="skip-blob",
        outcome="fail",
        scene_id=scene_id,
        status=status,
        missing_paths=missing_paths,
        dropped_path=drop,
    )
    return EXIT_UNEXPECTED, scene_id


def run_duplicate_event(
    cfg: Config,
    artifacts: TestBundleArtifacts,
    bundle_id: str,
    id_token: str,
    out: Output,
) -> tuple[int, Optional[str]]:
    """Mode: duplicate-event. Returns (exit_code, scene_id)."""
    # Phase 1: full happy-path upload
    session_map = post_upload_session(cfg, bundle_id, artifacts, id_token, out)
    upload_phase1(artifacts, session_map, out)
    upload_phase2(artifacts, session_map, out)

    out.progress("Polling to terminal state (first pass)...")
    t0 = time.monotonic()
    scene = poll_scene(cfg, bundle_id, id_token, out, start_time=t0)
    scene_id = scene.get("scene_id")
    status = scene.get("status")

    if status != "failed_invalid":
        # The synthetic fixture's non-decodable pixels should trigger the ingest
        # validation gate → failed_invalid. See docs/decisions/0025.
        out.progress(
            f"FAIL: expected status=failed_invalid before duplicate event, got status={status}"
        )
        out.event(
            "run_complete",
            mode="duplicate-event",
            outcome="fail",
            scene_id=scene_id,
            status=status,
            phase="initial",
        )
        return EXIT_UNEXPECTED, scene_id

    out.progress(
        f"Scene failed_invalid (scene_id={scene_id}). "
        "Re-uploading bundle.pb to trigger duplicate event..."
    )
    _reupload_bundle_pb_gcs(cfg, bundle_id, artifacts.blobs["bundle.pb"], out)

    # Wait for Eventarc redelivery window (matching stall-detect threshold from 0019).
    out.progress(f"Waiting {_STALL_DETECT_SECONDS:.0f}s for Eventarc redelivery...")
    time.sleep(_STALL_DETECT_SECONDS)

    out.progress("Polling again (idempotency check)...")
    scene2 = poll_scene(cfg, bundle_id, id_token, out, start_time=time.monotonic())
    scene_id2 = scene2.get("scene_id")
    status2 = scene2.get("status")

    if status2 == "failed_invalid" and scene_id2 == scene_id:
        out.progress(f"PASS: scene_id unchanged ({scene_id}), status still failed_invalid")
        out.event(
            "run_complete",
            mode="duplicate-event",
            outcome="pass",
            scene_id=scene_id,
            status=status2,
        )
        return EXIT_OK, scene_id

    out.progress(
        f"FAIL: expected scene_id={scene_id} status=failed_invalid; "
        f"got scene_id={scene_id2} status={status2}"
    )
    out.event(
        "run_complete",
        mode="duplicate-event",
        outcome="fail",
        scene_id=scene_id2,
        status=status2,
        expected_scene_id=scene_id,
    )
    return EXIT_UNEXPECTED, scene_id2


def _reupload_bundle_pb_gcs(
    cfg: Config,
    bundle_id: str,
    bundle_pb_bytes: bytes,
    out: Output,
) -> None:
    """Direct GCS SDK upload of bundle.pb — triggers a fresh GCS finalize event."""
    from google.cloud import storage as gcs  # deferred: only needed for this mode
    client = gcs.Client()
    blob = client.bucket(cfg.gcs_bucket).blob(f"captures/{bundle_id}/bundle.pb")
    blob.upload_from_string(bundle_pb_bytes, content_type="application/octet-stream")
    out.detail(
        f"  re-uploaded bundle.pb to gs://{cfg.gcs_bucket}/captures/{bundle_id}/bundle.pb"
    )


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument(
        "mode",
        nargs="?",
        default="happy-path",
        choices=["happy-path", "skip-blob", "duplicate-event", "auth-rejection"],
        metavar="mode",
        help=(
            "Test mode: happy-path (default), skip-blob, "
            "duplicate-event, auth-rejection"
        ),
    )
    # Required flags
    p.add_argument("--public-url", default="", metavar="URL",
                   help="Base URL of api-public (env: SMOKE_PUBLIC_URL)")
    p.add_argument("--internal-url", default="", metavar="URL",
                   help="Base URL of api-internal (env: SMOKE_INTERNAL_URL)")
    p.add_argument("--firebase-api-key", default="", metavar="KEY",
                   help="Firebase Web API key (env: SMOKE_FIREBASE_API_KEY)")
    p.add_argument("--firebase-project-id", default="", metavar="ID",
                   help="Firebase/GCP project ID (env: SMOKE_FIREBASE_PROJECT_ID)")
    p.add_argument("--gcs-bucket", default="", metavar="BUCKET",
                   help="GCS captures bucket name (env: SMOKE_GCS_BUCKET)")
    # Bundle parameters
    p.add_argument(
        "--tier", default=TIER_LIDAR_ROOMPLAN,
        choices=[TIER_ARKIT_ONLY, TIER_LIDAR_ARKIT, TIER_LIDAR_ROOMPLAN],
        help="Bundle tier (default: lidar-roomplan)",
    )
    p.add_argument("--frame-count", type=int, default=3, metavar="N",
                   help="Number of frames to synthesize (default: 3)")
    p.add_argument(
        "--drop-blob-kind", default=None,
        choices=["rgb", "depth", "confidence", "usdz"],
        metavar="KIND",
        help="Blob kind to include in manifest but NOT upload (required for skip-blob)",
    )
    # Run parameters
    p.add_argument("--timeout", type=float, default=120.0, metavar="SEC",
                   help="Poll timeout in seconds (default: 120)")
    p.add_argument("--poll-interval", type=float, default=2.0, metavar="SEC",
                   help="Poll interval in seconds (default: 2)")
    # UID persistence
    p.add_argument("--reuse-uid", default=None, metavar="PATH",
                   help="Path to UID cache file; reuse stored Firebase UID")
    p.add_argument("--save-uid", default=None, metavar="PATH",
                   help="Write UID cache file after fresh sign-in")
    # Behaviour flags
    p.add_argument("--cleanup", action="store_true",
                   help="Delete artifacts after run (best-effort, via developer ADC)")
    p.add_argument("--verbose", action="store_true",
                   help="Per-request HTTP detail to stderr")
    p.add_argument("--json", action="store_true",
                   help="NDJSON event stream to stdout")
    p.add_argument("--use-hardware-id-fallback", action="store_true",
                   help="Leave device_id empty; set hardware_id instead")
    return p


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    args = _build_parser().parse_args()
    cfg = Config(args)
    out = Output(cfg.verbose, cfg.json_mode)

    bundle_id = str(uuid.uuid4())
    scene_id: Optional[str] = None

    out.progress(f"bundle_id: {bundle_id}")
    out.progress(f"mode:      {cfg.mode}")
    out.event(
        "run_start",
        bundle_id=bundle_id,
        mode=cfg.mode,
        tier=cfg.tier,
        frame_count=cfg.frame_count,
    )

    exit_code = EXIT_UNEXPECTED
    try:
        validate_config(cfg)

        if cfg.mode == "auth-rejection":
            exit_code, scene_id = run_auth_rejection(cfg, bundle_id, out)
            return exit_code

        id_token, local_id = authenticate(cfg, out)
        artifacts = build_artifacts(cfg, bundle_id, local_id, out)

        if cfg.mode == "happy-path":
            exit_code, scene_id = run_happy_path(cfg, artifacts, bundle_id, id_token, out)
        elif cfg.mode == "skip-blob":
            exit_code, scene_id = run_skip_blob(cfg, artifacts, bundle_id, id_token, out)
        elif cfg.mode == "duplicate-event":
            exit_code, scene_id = run_duplicate_event(cfg, artifacts, bundle_id, id_token, out)

    except SmokeError as exc:
        out.warn(str(exc))
        out.event("run_complete", outcome="error", error=str(exc))
        exit_code = exc.exit_code

    finally:
        if cfg.cleanup:
            do_cleanup(cfg, bundle_id, scene_id, out)

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
