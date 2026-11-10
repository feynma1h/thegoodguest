#!/usr/bin/env python3
"""Ask scene-finish to draw rooms' still pictures — render only, no Claude.

    python3 tools/enqueue_still.py <scene_id> [<scene_id> ...] [--candidate]

For a room whose still was never drawn (one made before perception-obj's
/shell started asking for it, decision 0363), for a re-draw after the viewer's
look changed, and for smoking a scene-finish candidate with a real room.

WHY A CLOUD TASK AND NOT CURL. scene-finish is platform-gated like
perception-obj (0106): only tasks-invoker@ holds run.invoker, and /still checks
an OIDC token whose email must be that SA. An operator cannot mint it (0090);
Cloud Tasks mints it, as tools/segment_frames.py explains at length.

THE AUDIENCE IS PINNED to RECEIVER_URL + "/still" while the POST goes wherever
--candidate says. Cloud Tasks would default the audience to the request URL,
which is wrong for a candidate--- URL: the token would name the candidate's
host and /still checks the service URL's.

What a run writes: scenes/<id>/still.jpg (and still-night.jpg when the room has
twins) in the outputs bucket, and the `still` field on the scene's Firestore
document. Nothing else in the scene changes; drawing again is idempotent.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time

PROJECT = os.environ.get("CLOUD_TASKS_PROJECT", "thegoodguest")
LOCATION = os.environ.get("CLOUD_TASKS_LOCATION", "asia-southeast1")
QUEUE = os.environ.get("CLOUD_TASKS_QUEUE", "perception-dispatch")
RECEIVER_URL = os.environ.get("RECEIVER_URL", "https://scene-finish-o4dhc34kqq-as.a.run.app")
CANDIDATE_URL = os.environ.get("CANDIDATE_URL", "https://candidate---scene-finish-o4dhc34kqq-as.a.run.app")
INVOKER_SA = os.environ.get("CLOUD_TASKS_INVOKER_SA", "tasks-invoker@thegoodguest.iam.gserviceaccount.com")
DISPATCH_DEADLINE_SECONDS = 930


def still_task(queue_path: str, scene_id: str, *, candidate: bool, now: int, post=None) -> dict:
    """The Cloud Tasks task for one scene: POST to the service or its candidate,
    with the token's audience always the service URL's /still. `post` is
    tasks_v2.HttpMethod.POST (passed in so the task can be built without the
    queue library)."""
    from google.protobuf import duration_pb2

    return {
        "name": f"{queue_path}/tasks/still-{scene_id}-{now}",
        "http_request": {
            "http_method": post if post is not None else "POST",
            "url": (CANDIDATE_URL if candidate else RECEIVER_URL) + "/still",
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"scene_id": scene_id}).encode(),
            "oidc_token": {"service_account_email": INVOKER_SA, "audience": RECEIVER_URL + "/still"},
        },
        "dispatch_deadline": duration_pb2.Duration(seconds=DISPATCH_DEADLINE_SECONDS),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("scene_ids", nargs="+")
    ap.add_argument("--candidate", action="store_true", help="POST to the candidate--- tag instead of the service")
    args = ap.parse_args(argv)

    from google.cloud import tasks_v2

    client = tasks_v2.CloudTasksClient()
    queue_path = client.queue_path(PROJECT, LOCATION, QUEUE)
    for scene_id in args.scene_ids:
        task = still_task(queue_path, scene_id, candidate=args.candidate, now=int(time.time()),
                          post=tasks_v2.HttpMethod.POST)
        client.create_task(request={"parent": queue_path, "task": task})
        print(f"{scene_id}  POST {task['http_request']['url']}  task {task['name'].rsplit('/', 1)[1]}")
    print()
    print("Queued; /still answers asynchronously. Watch:")
    print('  gcloud logging read \'resource.type="cloud_run_revision" AND '
          'resource.labels.service_name="scene-finish" AND textPayload:"still"\' --limit 10 --freshness=20m')
    return 0


if __name__ == "__main__":
    sys.exit(main())
