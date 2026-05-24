"""End-to-end smoke test for the roomstudio perception pipeline.

Pushes a synthesized capture bundle through the full pipeline:
  1. Upload bundle.pb + frames/ to GCS under a timestamped prefix.
  2. POST to the ingester's /ingest endpoint.
  3. Poll Firestore every 15 s until the scene reaches 'ready' or 'failed'.
  4. Print one status line per poll cycle; exit 0 on ready, 1 on failure/timeout.

Run from the repo root (requires Application Default Credentials and gcloud):
  python tools/smoke_test_e2e.py
  python tools/smoke_test_e2e.py --bundle outputs/test_bundle/bundle.pb
  python tools/smoke_test_e2e.py --dry-run   # print commands without uploading

Credentials: gcloud ADC (run `gcloud auth application-default login` once).
Service URLs are auto-detected via `gcloud run services describe` unless
--ingester-url is passed explicitly.

Consumed by: engineers manually verifying an end-to-end deploy.
"""
from __future__ import annotations

import argparse
import datetime
import json
import subprocess
import sys
import time
from pathlib import Path


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_BUNDLE = "outputs/test_bundle/bundle.pb"
DEFAULT_BUCKET = "roomstudio-captures"
GCP_PROJECT = "roomstudio"
GCP_REGION = "asia-southeast1"
INGESTER_SERVICE = "api"
FIRESTORE_COLLECTION = "scenes"
POLL_INTERVAL_S = 15
DEFAULT_TIMEOUT_S = 1800  # 30 min; model cold-start is ~195 s


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ts() -> str:
    """Current wall-clock time as [HH:MM:SS]."""
    return datetime.datetime.now().strftime("[%H:%M:%S]")


def _elapsed(start: float) -> str:
    """Seconds elapsed since `start`, formatted as Xs."""
    return f"{int(time.time() - start)}s"


def _run(cmd: list[str], *, capture: bool = True) -> str:
    """Run a subprocess and return stdout. Raises on non-zero exit."""
    result = subprocess.run(cmd, capture_output=capture, text=True)
    if result.returncode != 0:
        raise RuntimeError(
            f"Command failed ({result.returncode}): {' '.join(cmd)}\n"
            f"stderr: {result.stderr.strip()}"
        )
    return result.stdout.strip()


def _detect_ingester_url() -> str:
    """Auto-detect the ingester URL from Cloud Run."""
    return _run([
        "gcloud", "run", "services", "describe", INGESTER_SERVICE,
        f"--region={GCP_REGION}", f"--project={GCP_PROJECT}",
        "--format=value(status.url)",
    ])


def _upload_bundle(bundle_path: Path, bucket: str, prefix: str, *, dry_run: bool) -> str:
    """Upload bundle.pb and all frames to GCS. Returns the bundle GCS URI."""
    bundle_dir = bundle_path.parent
    bundle_gcs_uri = f"gs://{bucket}/{prefix}/bundle.pb"

    frames_dir = bundle_dir / "frames"
    upload_pairs: list[tuple[Path, str]] = [(bundle_path, bundle_gcs_uri)]
    if frames_dir.is_dir():
        for frame in sorted(frames_dir.iterdir()):
            if frame.is_file():
                upload_pairs.append((frame, f"gs://{bucket}/{prefix}/frames/{frame.name}"))

    if dry_run:
        print("-- dry-run: would upload:")
        for local, remote in upload_pairs:
            print(f"    {local}  →  {remote}")
        return bundle_gcs_uri

    for local, remote in upload_pairs:
        print(f"  uploading {local.name} → {remote}")
        _run(["gcloud", "storage", "cp", str(local), remote])

    return bundle_gcs_uri


def _post_ingest(ingester_url: str, bundle_gcs_uri: str, *, dry_run: bool) -> str | None:
    """POST to /ingest. Returns scene_id, or None in dry-run mode."""
    url = ingester_url.rstrip("/") + "/ingest"
    payload = json.dumps({"bundle_gcs_uri": bundle_gcs_uri})

    if dry_run:
        print(f"-- dry-run: would POST:")
        print(f"    curl -s -X POST '{url}' \\")
        print(f"         -H 'Content-Type: application/json' \\")
        print(f"         -d '{payload}'")
        return None

    import urllib.request
    req = urllib.request.Request(
        url,
        data=payload.encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        body = json.loads(resp.read())

    scene_id = body.get("scene_id")
    if not scene_id:
        raise RuntimeError(f"/ingest returned unexpected body: {body}")
    return scene_id


def _firestore_get(scene_id: str) -> dict:
    """Fetch a Firestore scene document via gcloud CLI. Returns the fields dict."""
    path = f"projects/{GCP_PROJECT}/databases/(default)/documents/{FIRESTORE_COLLECTION}/{scene_id}"
    out = _run([
        "gcloud", "firestore", "documents", "get", path,
        f"--project={GCP_PROJECT}", "--format=json",
    ])
    doc = json.loads(out)
    # Firestore REST format: doc["fields"]["<name>"]["stringValue" | ...]
    fields = doc.get("fields", {})

    def _val(f: dict) -> str | None:
        for k in ("stringValue", "integerValue", "booleanValue", "timestampValue"):
            if k in f:
                return str(f[k])
        return None

    return {k: _val(v) for k, v in fields.items()}


def _extra_info(fields: dict, status: str) -> str:
    """Extract a brief extra-info string for the polling line."""
    if status == "ready":
        return fields.get("result_uri") or ""
    if status == "failed":
        err = fields.get("last_error") or ""
        return err[:80] + ("…" if len(err) > 80 else "")
    return ""


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--bundle", default=DEFAULT_BUNDLE, help="Path to bundle.pb")
    p.add_argument("--bucket", default=DEFAULT_BUCKET, help="GCS bucket for uploads")
    p.add_argument(
        "--prefix",
        default=None,
        help="GCS prefix (default: smoke-test/<timestamp>)",
    )
    p.add_argument("--ingester-url", default=None, help="Ingester service URL (auto-detected if omitted)")
    p.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT_S, help="Poll timeout in seconds")
    p.add_argument("--dry-run", action="store_true", help="Print commands without uploading or posting")
    return p.parse_args()


def main() -> int:
    args = _parse_args()

    bundle_path = Path(args.bundle)
    if not bundle_path.exists():
        print(f"error: bundle not found: {bundle_path}", file=sys.stderr)
        print("  run: python tools/build_test_bundle.py", file=sys.stderr)
        return 1

    prefix = args.prefix or f"smoke-test/{datetime.datetime.utcnow().strftime('%Y%m%d-%H%M%S')}"

    # --- Step 0: resolve ingester URL ---
    if args.ingester_url:
        ingester_url = args.ingester_url
    elif args.dry_run:
        ingester_url = f"https://{INGESTER_SERVICE}-<hash>-as.a.run.app  (would auto-detect)"
    else:
        print("detecting ingester URL...", flush=True)
        ingester_url = _detect_ingester_url()

    print(f"ingester:  {ingester_url}")
    print(f"bucket:    gs://{args.bucket}/{prefix}/")
    print()

    # --- Step 1: upload ---
    print("=== 1/3: Uploading bundle ===")
    bundle_gcs_uri = _upload_bundle(bundle_path, args.bucket, prefix, dry_run=args.dry_run)
    print(f"bundle_gcs_uri: {bundle_gcs_uri}")
    print()

    # --- Step 2: POST /ingest ---
    print("=== 2/3: Posting to /ingest ===")
    scene_id = _post_ingest(ingester_url, bundle_gcs_uri, dry_run=args.dry_run)
    if args.dry_run:
        print()
        print("-- dry-run complete. No uploads or requests were made.")
        return 0
    print(f"scene_id:  {scene_id}")
    print()

    # --- Step 3: poll Firestore ---
    print("=== 3/3: Polling Firestore ===")
    print(f"{'[time]':12}  {'status':12}  extra info")
    print("-" * 60)

    start = time.time()
    while True:
        elapsed = time.time() - start
        if elapsed > args.timeout:
            print(f"\nFAIL  scene {scene_id}  timed out after {int(elapsed)}s")
            return 1

        try:
            fields = _firestore_get(scene_id)
        except Exception as e:
            print(f"{_ts()}  (firestore error: {e})", flush=True)
            time.sleep(POLL_INTERVAL_S)
            continue

        status = fields.get("status", "unknown")
        extra = _extra_info(fields, status)
        line = f"{_ts()}  {status:<12}  {extra}".rstrip()
        print(line, flush=True)

        if status == "ready":
            print()
            print(f"PASS  scene {scene_id}  ready in {_elapsed(start)}")
            return 0
        if status == "failed":
            print()
            print(f"FAIL  scene {scene_id}  failed in {_elapsed(start)}")
            return 1

        time.sleep(POLL_INTERVAL_S)


if __name__ == "__main__":
    sys.exit(main())
