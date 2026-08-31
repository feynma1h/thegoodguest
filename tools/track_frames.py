#!/usr/bin/env python3
"""Ask perception to track concepts across a capture — SAM 3.1, no reconstruction.

    python3 tools/track_frames.py <scene_id> --concepts monitor,door,speaker \
        --bundle-uri gs://... [--candidate]

WHY A CLOUD TASK AND NOT CURL. perception-obj is platform-gated (0106): only
`tasks-invoker@` holds run.invoker, and /track verifies an OIDC token whose
`email` must be that SA and whose `aud` must be RECEIVER_URL + "/track". An
operator cannot mint that token — impersonating the invoker SA is denied by
design (0090), which is least privilege working rather than an obstacle to route
around. Cloud Tasks mints it for us, exactly as `segment_frames.py` does.

THE AUDIENCE IS SET EXPLICITLY, for the reason `segment_frames.py` records:
without it Cloud Tasks defaults the audience to the request URL, which is
correct for the stable service URL and WRONG for a `candidate---` URL, where
the token would carry the candidate's host and the verifier expects
RECEIVER_URL's. Probing a candidate is this route's normal case.

ONE CONCEPT PER PASS is the model's constraint, not ours: the session holds a
single text prompt and must be reset between prompts. The route pays for frame
decode once per CALL, so several concepts per call is much cheaper than several
calls — but every concept costs a full propagation over every frame, and the
request budget is 900 s. `--chunk` splits a long vocabulary across calls; the
route caps a single call at MAX_CONCEPTS_PER_CALL and says so in its response
rather than silently truncating.

The route writes only under scenes/{id}/track_probe/ and never touches
Firestore, so this cannot regress a ready room (see track_receiver.py).
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
RECEIVER_URL = os.environ.get(
    "RECEIVER_URL", "https://perception-obj-q62kcditqa-as.a.run.app"
)
CANDIDATE_URL = os.environ.get(
    "CANDIDATE_URL", "https://candidate---perception-obj-q62kcditqa-as.a.run.app"
)
INVOKER_SA = os.environ.get(
    "CLOUD_TASKS_INVOKER_SA", "tasks-invoker@thegoodguest.iam.gserviceaccount.com"
)
DISPATCH_DEADLINE_SECONDS = 930


def _bundle_uri_for(scene_id: str) -> str:
    """Read the scene's bundle_uri from Firestore, so the caller need only know
    the scene id. A capture restored to GCS by hand (0164) may have no scene
    document at all, which is what --bundle-uri is for."""
    from google.cloud import firestore

    snap = firestore.Client(project=PROJECT).collection("scenes").document(scene_id).get()
    if not snap.exists:
        raise SystemExit(
            f"scene {scene_id} not found — pass --bundle-uri if the capture was "
            f"restored to GCS without a scene document"
        )
    uri = (snap.to_dict() or {}).get("bundle_uri")
    if not uri:
        raise SystemExit(f"scene {scene_id} has no bundle_uri")
    return uri


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("scene_id")
    ap.add_argument("--concepts", required=True, help="comma-separated text prompts")
    ap.add_argument("--frames", help="comma-separated frame indices; default is every frame")
    ap.add_argument("--chunk", type=int, default=0,
                    help="concepts per task; 0 sends them all in one task")
    ap.add_argument("--candidate", action="store_true",
                    help="POST to the candidate revision instead of the serving one")
    ap.add_argument("--prompt-frame-position", type=int, default=0,
                    help="position IN THE TRACKED SEQUENCE to prompt on, not a frame index")
    ap.add_argument("--prob-thresh", type=float, default=0.5)
    ap.add_argument("--bundle-uri", help="override; otherwise read from Firestore")
    args = ap.parse_args(argv)

    concepts = [c.strip() for c in args.concepts.split(",") if c.strip()]
    if not concepts:
        raise SystemExit("--concepts named nothing")
    frames = (
        [int(x) for x in args.frames.replace(" ", "").split(",") if x]
        if args.frames
        else None
    )

    bundle_uri = args.bundle_uri or _bundle_uri_for(args.scene_id)
    post_to = (CANDIDATE_URL if args.candidate else RECEIVER_URL) + "/track"
    audience = RECEIVER_URL + "/track"       # NEVER the candidate host — see docstring

    chunk = args.chunk if args.chunk > 0 else len(concepts)
    batches = [concepts[i:i + chunk] for i in range(0, len(concepts), chunk)]

    from google.cloud import tasks_v2
    from google.protobuf import duration_pb2

    client = tasks_v2.CloudTasksClient()
    queue_path = client.queue_path(PROJECT, LOCATION, QUEUE)

    stamp = int(time.time())
    for n, batch in enumerate(batches):
        body: dict = {
            "scene_id": args.scene_id,
            "bundle_uri": bundle_uri,
            "concepts": batch,
            "prompt_frame_position": args.prompt_frame_position,
            "output_prob_thresh": args.prob_thresh,
        }
        if frames is not None:
            body["frame_indices"] = frames
        task = {
            "name": f"{queue_path}/tasks/track-{args.scene_id}-{stamp}-{n}",
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
        print(f"task {n + 1}/{len(batches)}  {batch}")

    print()
    print(f"scene    {args.scene_id}")
    print(f"frames   {'all' if frames is None else frames}")
    print(f"POST to  {post_to}")
    print(f"audience {audience}")
    print()
    print("The tasks are queued; the route answers asynchronously. Watch:")
    print('  gcloud logging read \'resource.type="cloud_run_revision" AND '
          'resource.labels.service_name="perception-obj" AND '
          'textPayload:"track probe"\' --limit 20 --freshness=30m')
    print(f"Outputs land under gs://thegoodguest-perception-outputs/scenes/"
          f"{args.scene_id}/track_probe/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
