#!/usr/bin/env python3
"""Re-enqueue an existing scene through the perception pipeline.

Resets the scene's Firestore doc to `queued` (clearing any lease) and
creates a fresh Cloud Tasks task pointing at perception-obj's /process —
the same payload shape api-internal's ingest dispatch uses. Run from the
repo root with ADC credentials:

    python3 tools/reenqueue_scene.py <scene_id> [--force] [--dry-run]

THE GAP THIS CURES (found live on scene 25a14caf, 2026-07-21; the fix
session's decision note is the durable record): the pipeline's crash
recovery assumes every failure mode ends with a Cloud Tasks retry
REACHING the app, where claim() reclaims a stale lease (0011/0012).
But when an attempt outlives the Cloud Run request timeout, the handler
thread keeps computing on the always-allocated CPU and holds the
concurrency=1 slot — so every platform retry waits in the platform
queue, times out with 504 WITHOUT ever reaching the app, and burns one
of maxAttempts. When the retries are exhausted and the zombie instance
is later reaped (no SIGTERM reset fires for an instance killed while
idle-with-no-request), the scene is stranded: status `processing`,
expired lease, empty queue, and nothing left that will ever re-drive
it. No in-band mechanism can help — recovery lives at claim() and
claim() only runs when a request arrives. This tool is the out-of-band
re-drive. (The budget tracker in perception-obj prevents NEW strandings
by finishing inside the request; this tool exists for scenes stranded
before that fix, and as the general operator re-drive for preserved
captures.)

Guards (see decide()): a scene whose lease is still live is refused
(an active worker owns it) and a `ready` scene is refused (re-driving
would regress it to queued) — both overridable with --force, which is
the intended path for deliberately re-running a preserved capture.
`queued`, `failed`, and lease-expired `processing` scenes proceed
without --force. The bundle blob is existence-checked first: the
captures bucket has a 1-day lifecycle rule, so a stranded scene's
bundle may already be swept — re-upload the preserved capture, then
re-run this tool.

Defaults for project/queue/URL/invoker-SA are read from
infra/api-internal.env.yaml (the same values the ingest dispatcher
runs with); every one is flag-overridable.

Exit codes: 0 success (or dry-run would-proceed) / 1 unexpected error /
2 refused by a guard (see --force) / 3 misconfiguration (bad scene id,
missing bundle blob, unreadable env file).

Consumers: operators (manual, ADC). Guard logic is pinned by
tools/test_reenqueue_scene.py.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

# Mirrors services/api-internal/dispatcher.py DISPATCH_DEADLINE_SECONDS:
# must stay >= perception-obj's Cloud Run request timeout (900 s) so Cloud
# Tasks never retries an attempt that is still running.
DISPATCH_DEADLINE_SECONDS = 930

_ENV_FILE_DEFAULT = "infra/api-internal.env.yaml"

# Keys this tool needs from the env file (flat `KEY: value` YAML).
_ENV_KEYS = (
    "CLOUD_TASKS_PROJECT",
    "CLOUD_TASKS_LOCATION",
    "CLOUD_TASKS_QUEUE",
    "CLOUD_TASKS_INVOKER_SA",
    "PERCEPTION_OBJ_PROCESS_URL",
)


def parse_env_file(path: Path) -> dict[str, str]:
    """Parse the flat `KEY: value` lines of an env-vars YAML file.

    Deliberately not a YAML parser: the deploy env files are flat string
    maps by construction, and this keeps the tool dependency-free.
    """
    values: dict[str, str] = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        m = re.match(r"^([A-Z_][A-Z0-9_]*):\s*(.+?)\s*$", line)
        if m:
            values[m.group(1)] = m.group(2)
    return values


@dataclass
class Decision:
    proceed: bool
    reason: str
    forced: bool = False


def decide(scene: dict | None, now: datetime, force: bool) -> Decision:
    """Decide whether re-enqueueing this scene doc is safe.

    Pure function — pinned by tools/test_reenqueue_scene.py. `scene` is
    the Firestore doc dict (None if the doc does not exist).
    """
    if scene is None:
        return Decision(False, "scene document not found")

    status = scene.get("status")
    lease = scene.get("lease_expires_at")

    if status == "processing":
        if lease is not None and lease > now:
            if force:
                return Decision(
                    True,
                    f"lease live until {lease.isoformat()} — forced past an "
                    "active worker; expect claim() ALREADY_OWNED noops until "
                    "it exits",
                    forced=True,
                )
            return Decision(
                False,
                f"lease is live until {lease.isoformat()} — an active worker "
                "may own this scene (--force to override)",
            )
        return Decision(True, "stranded: processing with expired/absent lease")

    if status == "queued":
        return Decision(True, "queued with no live task (duplicate task is "
                              "safe: claim() dedupes)")

    if status == "failed":
        return Decision(True, "manual retry of a failed scene")

    if status == "ready":
        if force:
            return Decision(True, "re-driving a ready scene (forced)", forced=True)
        return Decision(
            False,
            "scene is ready — re-enqueueing would regress it to queued "
            "(--force to re-drive deliberately)",
        )

    return Decision(False, f"unrecognized status {status!r}")


def task_name_for(scene_id: str, now: datetime) -> str:
    """Unique Cloud Tasks task id for this re-enqueue.

    The original ingest task is named bare `{scene_id}`; Cloud Tasks
    tombstones completed task names (~1 h dedup window), so a re-enqueue
    soon after the original attempts would be silently deduped away under
    that name. A timestamp suffix guarantees delivery; operator invocations
    are deliberate, so idempotent naming is not wanted here.
    """
    return f"{scene_id}-r{now.strftime('%Y%m%d%H%M%S')}"


# ---------------------------------------------------------------------------
# --shell mode (decision 0066)
# ---------------------------------------------------------------------------

def decide_shell(scene: dict | None) -> Decision:
    """Decide whether a /shell re-drive makes sense for this scene doc.

    Pure function — pinned by tools/test_reenqueue_scene.py. /shell holds
    no lease and never writes Firestore, so the /process guards don't
    apply: any existing scene proceeds. A non-ready scene gets a caveat
    (the handler noops with manifest_missing until /process finishes),
    and a missing doc is refused — there is nothing to bake for.
    """
    if scene is None:
        return Decision(False, "scene document not found")
    status = scene.get("status")
    if status == "ready":
        return Decision(True, "shell re-drive of a ready scene")
    return Decision(
        True,
        f"scene status is {status!r} (not ready) — /shell will noop with "
        "manifest_missing unless the manifest already exists",
    )


def shell_url_from_process_url(process_url: str) -> str:
    """Derive the /shell endpoint from PERCEPTION_OBJ_PROCESS_URL.

    The env file carries the /process URL; both routes live on the same
    service, so swap the path suffix rather than adding another env key.
    """
    base = process_url.rstrip("/")
    if base.endswith("/process"):
        base = base[: -len("/process")]
    return base + "/shell"


def shell_task_name_for(scene_id: str, now: datetime) -> str:
    """shell-{scene_id}-r{ts}: same tombstone-proof timestamping as
    task_name_for, in shell_enqueue.py's shell- namespace."""
    return f"shell-{scene_id}-r{now.strftime('%Y%m%d%H%M%S')}"


def _gcs_blob_exists(gcs_uri: str) -> bool:
    from google.cloud import storage

    without_scheme = gcs_uri[5:]
    bucket_name, blob_path = without_scheme.split("/", 1)
    return storage.Client().bucket(bucket_name).blob(blob_path).exists()


def _reset_scene_to_queued(db, scene_id: str, expected_status: str, now: datetime) -> None:
    """Transactionally reset the scene doc to queued, clearing the lease.

    Verifies the status inside the transaction is still what decide() saw —
    if a live worker finished (or another operator raced us) between read
    and reset, abort rather than clobber.
    """
    from google.cloud import firestore as _fs

    ref = db.collection("scenes").document(scene_id)

    @_fs.transactional
    def _txn(transaction, ref):
        snap = ref.get(transaction=transaction)
        if not snap.exists:
            raise RuntimeError("scene doc vanished mid-reset")
        current = snap.to_dict().get("status")
        if current != expected_status:
            raise RuntimeError(
                f"scene status changed {expected_status!r} -> {current!r} "
                "between decision and reset; re-run the tool"
            )
        transaction.update(ref, {
            "status": "queued",
            "lease_expires_at": None,
            "lease_holder_id": "",
            "updated_at": now,
            "reenqueued_at": now,
            "reenqueue_count": _fs.Increment(1),
        })

    _txn(db.transaction(), ref)


def _create_task(
    *,
    project: str,
    location: str,
    queue: str,
    task_name: str,
    process_url: str,
    invoker_sa: str,
    scene_id: str,
    bundle_uri: str,
) -> str:
    """Create the Cloud Tasks task, mirroring api-internal's dispatcher."""
    from google.cloud import tasks_v2
    from google.protobuf import duration_pb2

    client = tasks_v2.CloudTasksClient()
    queue_path = client.queue_path(project, location, queue)
    http_request: dict = {
        "http_method": tasks_v2.HttpMethod.POST,
        "url": process_url,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps({"scene_id": scene_id, "bundle_uri": bundle_uri}).encode(),
    }
    if invoker_sa:
        http_request["oidc_token"] = {"service_account_email": invoker_sa}
    task = {
        "name": f"{queue_path}/tasks/{task_name}",
        "http_request": http_request,
        "dispatch_deadline": duration_pb2.Duration(seconds=DISPATCH_DEADLINE_SECONDS),
    }
    client.create_task(request={"parent": queue_path, "task": task})
    return task["name"]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("scene_id", help="Firestore scene document id (full UUID)")
    ap.add_argument("--env-file", default=_ENV_FILE_DEFAULT,
                    help=f"deploy env yaml for defaults (default {_ENV_FILE_DEFAULT})")
    ap.add_argument("--project", help="override CLOUD_TASKS_PROJECT")
    ap.add_argument("--location", help="override CLOUD_TASKS_LOCATION")
    ap.add_argument("--queue", help="override CLOUD_TASKS_QUEUE")
    ap.add_argument("--process-url", help="override PERCEPTION_OBJ_PROCESS_URL")
    ap.add_argument("--invoker-sa", help="override CLOUD_TASKS_INVOKER_SA")
    ap.add_argument("--force", action="store_true",
                    help="override the live-lease and ready-scene guards")
    ap.add_argument("--shell", action="store_true",
                    help="enqueue a /shell task (decision 0066) instead of "
                         "/process: no Firestore reset, no lease, no bundle "
                         "existence gate (a swept bundle IS the "
                         "capture_expired case the handler must record). "
                         "NOTE: the /shell noop is VERSION-GATED (0d67608): an "
                         "existing shell.json at the current max output "
                         "version noops, an older one regenerates. Delete the "
                         "blob only to force a same-version re-bake.")
    ap.add_argument("--dry-run", action="store_true",
                    help="print the decision and planned actions; change nothing")
    args = ap.parse_args(argv)

    env_path = Path(args.env_file)
    env = {}
    if env_path.exists():
        env = parse_env_file(env_path)
    project = args.project or env.get("CLOUD_TASKS_PROJECT")
    location = args.location or env.get("CLOUD_TASKS_LOCATION")
    queue = args.queue or env.get("CLOUD_TASKS_QUEUE")
    process_url = args.process_url or env.get("PERCEPTION_OBJ_PROCESS_URL")
    invoker_sa = args.invoker_sa or env.get("CLOUD_TASKS_INVOKER_SA", "")
    missing = [n for n, v in [("project", project), ("location", location),
                              ("queue", queue), ("process-url", process_url)] if not v]
    if missing:
        print(f"misconfig: missing {', '.join(missing)} (no {args.env_file} "
              "and no flag override)", file=sys.stderr)
        return 3

    from google.cloud import firestore

    db = firestore.Client(project=project)
    snap = db.collection("scenes").document(args.scene_id).get()
    scene = snap.to_dict() if snap.exists else None
    now = datetime.now(tz=UTC)

    if scene is not None:
        print(f"scene {args.scene_id}")
        print(f"  status={scene.get('status')!r} lease_expires_at="
              f"{scene.get('lease_expires_at')} bundle_uri={scene.get('bundle_uri')}")
    decision = decide_shell(scene) if args.shell else decide(scene, now, args.force)
    print(f"decision: {'PROCEED' if decision.proceed else 'REFUSE'} — {decision.reason}")
    if not decision.proceed:
        return 3 if scene is None else 2

    bundle_uri = scene.get("bundle_uri", "")
    if not bundle_uri.startswith("gs://"):
        print(f"misconfig: scene has no usable bundle_uri: {bundle_uri!r}",
              file=sys.stderr)
        return 3

    if args.shell:
        shell_url = shell_url_from_process_url(process_url)
        name = shell_task_name_for(args.scene_id, now)
        if args.dry_run:
            print(f"dry-run: would create shell task {name} -> {shell_url} "
                  "(no Firestore changes)")
            return 0
        full_name = _create_task(
            project=project, location=location, queue=queue, task_name=name,
            process_url=shell_url, invoker_sa=invoker_sa,
            scene_id=args.scene_id, bundle_uri=bundle_uri,
        )
        print(f"shell task created: {full_name}")
        print("watch: perception-obj logs for 'shell:' lines; the outputs "
              "bucket for scenes/<id>/shell.json (already-present -> noop)")
        return 0
    if not _gcs_blob_exists(bundle_uri):
        print(f"misconfig: bundle blob is gone: {bundle_uri}\n"
              "  (captures-bucket lifecycle sweeps after 1 day — re-upload the "
              "preserved capture to this exact path, then re-run)", file=sys.stderr)
        return 3

    name = task_name_for(args.scene_id, now)
    if args.dry_run:
        print(f"dry-run: would reset status {scene.get('status')!r} -> 'queued', "
              f"then create task {name} -> {process_url}")
        return 0

    _reset_scene_to_queued(db, args.scene_id, scene.get("status"), now)
    print("scene reset: status -> 'queued', lease cleared")
    full_name = _create_task(
        project=project, location=location, queue=queue, task_name=name,
        process_url=process_url, invoker_sa=invoker_sa,
        scene_id=args.scene_id, bundle_uri=bundle_uri,
    )
    print(f"task created: {full_name}")
    print("watch: perception-obj logs for claim -> sampling -> budget lines; "
          "scene doc for ready/failed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
