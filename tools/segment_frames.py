#!/usr/bin/env python3
"""Ask perception to segment named frames — SAM 3 only, no reconstruction.

    python3 tools/segment_frames.py <scene_id> --frames 41,42,45 [--candidate]

WHY A CLOUD TASK AND NOT CURL. perception-obj is platform-gated (0106): only
`tasks-invoker@` holds run.invoker, and /segment verifies an OIDC token whose
`email` must be that SA and whose `aud` must be RECEIVER_URL + "/segment".
An operator cannot mint that token — impersonating the invoker SA is denied by
design (0090), which is the least-privilege posture working rather than an
obstacle to route around. Cloud Tasks mints it for us, exactly as api-internal's
dispatcher does for /process, so this tool mirrors `reenqueue_scene.py`.

THE AUDIENCE IS SET EXPLICITLY, and that is the whole reason this tool is not a
two-line snippet. Without an explicit `audience`, Cloud Tasks defaults it to the
request URL — which is correct for the stable service URL and WRONG for a
`candidate---` URL, where the token would carry the candidate's host and the
verifier expects RECEIVER_URL's. Probing a candidate is the normal case here,
so the audience is always pinned to RECEIVER_URL + "/segment" while the POST
goes wherever --candidate says.

The route writes only under scenes/{id}/segment_probe/ and never touches
Firestore, so this cannot regress a ready room (see segment_receiver.py).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time

PROJECT = os.environ.get("CLOUD_TASKS_PROJECT", "roomstudio")
LOCATION = os.environ.get("CLOUD_TASKS_LOCATION", "asia-southeast1")
QUEUE = os.environ.get("CLOUD_TASKS_QUEUE", "perception-dispatch")
RECEIVER_URL = os.environ.get(
    "RECEIVER_URL", "https://perception-obj-q62kcditqa-as.a.run.app"
)
CANDIDATE_URL = os.environ.get(
    "CANDIDATE_URL", "https://candidate---perception-obj-q62kcditqa-as.a.run.app"
)
INVOKER_SA = os.environ.get(
    "CLOUD_TASKS_INVOKER_SA", "tasks-invoker@roomstudio.iam.gserviceaccount.com"
)
DISPATCH_DEADLINE_SECONDS = 930


def _bundle_uri_for(scene_id: str) -> str:
    """Read the scene's bundle_uri from Firestore, so the caller need only
    know the scene id."""
    from google.cloud import firestore

    snap = firestore.Client(project=PROJECT).collection("scenes").document(scene_id).get()
    if not snap.exists:
        raise SystemExit(f"scene {scene_id} not found")
    uri = (snap.to_dict() or {}).get("bundle_uri")
    if not uri:
        raise SystemExit(f"scene {scene_id} has no bundle_uri")
    return uri


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("scene_id")
    ap.add_argument("--frames", required=True, help="comma-separated frame indices")
    ap.add_argument("--candidate", action="store_true",
                    help="POST to the candidate revision instead of the serving one")
    ap.add_argument("--no-png", action="store_true", help="masks.npz only")
    ap.add_argument("--bundle-uri", help="override; otherwise read from Firestore")
    args = ap.parse_args(argv)

    frames = [int(x) for x in args.frames.replace(" ", "").split(",") if x]
    if not frames:
        raise SystemExit("--frames named nothing")

    bundle_uri = args.bundle_uri or _bundle_uri_for(args.scene_id)
    post_to = (CANDIDATE_URL if args.candidate else RECEIVER_URL) + "/segment"
    audience = RECEIVER_URL + "/segment"     # NEVER the candidate host — see docstring

    from google.cloud import tasks_v2
    from google.protobuf import duration_pb2

    client = tasks_v2.CloudTasksClient()
    queue_path = client.queue_path(PROJECT, LOCATION, QUEUE)
    body = {
        "scene_id": args.scene_id,
        "bundle_uri": bundle_uri,
        "frame_indices": frames,
        "write_png": not args.no_png,
    }
    task = {
        "name": f"{queue_path}/tasks/segment-{args.scene_id}-{int(time.time())}",
        "http_request": {
            "http_method": tasks_v2.HttpMethod.POST,
            "url": post_to,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps(body).encode(),
            "oidc_token": {
                "service_account_email": INVOKER_SA,
                "audience": audience,
            },
        },
        "dispatch_deadline": duration_pb2.Duration(seconds=DISPATCH_DEADLINE_SECONDS),
    }
    client.create_task(request={"parent": queue_path, "task": task})

    print(f"scene    {args.scene_id}")
    print(f"frames   {frames}")
    print(f"POST to  {post_to}")
    print(f"audience {audience}")
    print(f"task     {task['name']}")
    print()
    print("The task is queued; the route answers asynchronously. Watch:")
    print('  gcloud logging read \'resource.type="cloud_run_revision" AND '
          'resource.labels.service_name="perception-obj" AND '
          'textPayload:"segment probe"\' --limit 5 --freshness=20m')
    print(f"Outputs land under gs://roomstudio-perception-outputs/scenes/"
          f"{args.scene_id}/segment_probe/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
