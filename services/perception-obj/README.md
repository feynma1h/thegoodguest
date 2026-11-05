# perception-obj

GPU service running SAM 3 (open-vocabulary segmentation) over a scan's frames,
writing the boxes the person made (`boxes.json`) and the room shell. It no
longer reconstructs objects (decision 0323): the room's objects are the boxes.

Deployed to Cloud Run with an L4 GPU in `asia-southeast1`.

## Why this service is split

SAM 3D Objects, whose environment this image is still built from, pins `torch==2.5.1+cu121` while VGGT pins `torch==2.3.1`. These
cannot coexist in a single pip environment. The VGGT service that motivated
the split was retired in 2026-08 (decision 0192)
for the other half and `tools/call_perception.py` for the composition step.

## Endpoints

| Method | Path        | Purpose                                                         |
|--------|-------------|-----------------------------------------------------------------|
| GET    | `/`         | Status: device + model names                                    |
| GET    | `/health`   | Startup probe. Never blocks, never touches a model (0007/0009)  |
| GET    | `/ready`    | Per-model load state (`not_loaded`/`loading`/`loaded`/`failed`) |
| POST   | `/process`  | Cloud Tasks perception receiver — the heavy stage               |
| POST   | `/shell`    | Cloud Tasks room-shell receiver (0066/0069/0077)                |
| POST   | `/compress` | Compressed-splat receiver for scans that still have splats (0125/0126); no longer enqueued |

`/process` is the heavy endpoint and the only one that loads models: it claims
the scene's lease, writes `boxes.json` from the bundle's `person_boxes`
(0322), picks frames by those boxes, runs SAM 3 on each, and writes the
per-frame masks and the manifest (with an empty `objects` array) to the outputs
bucket. It is budget-aware — a frame that will not fit the request budget is
refused rather than half-done, and a warm retry resumes against the per-frame
caches.

`/shell` is a derived-asset stage enqueued fire-and-forget by `/process`'s
success path. It touches no model, so it is cold-cheap. `/compress` is no longer
enqueued (a scan has no splats to compress); the route remains to re-drive older
scenes.

The service is deployed `--allow-unauthenticated` so Cloud Run's own probes
reach `/health`; each POST route does its own OIDC verification of the Cloud
Tasks token instead (`oidc.py`), scoped to that route's audience.

## Deploying

From the repo root:

```bash
./infra/deploy_perception.sh obj
```

This runs Cloud Build, pushes to Artifact Registry, deploys to Cloud Run.

## File structure

The Dockerfile's `COPY` list plus its deferred-import smoke is the
authoritative module inventory. Most modules below are imported lazily inside
a route body, so a missing `COPY` passes `/health` and every pre-traffic probe
and only breaks on the first real request — which is what the smoke exists to
catch. Keep the two in step.

```
Dockerfile              Container definition (CUDA 12.1 / torch 2.5.1)
server.py               FastAPI app, route registration, lazy model loading
models/sam3.py          SAM 3 wrapper

/process stage
  process_receiver.py   Receiver semantics (decision 0004): claim, run, release
  receiver_repo.py      Scene lease lifecycle in Firestore
  oidc.py               Cloud Tasks OIDC verification (per-route audience)
  fcm.py                Device notification on terminal Scene transitions
  privacy.py            Concepts SAM 3 sees but the product never ships
  sampling.py           Pose-diverse frame selection
  boxes_json.py         The person's boxes: read from the bundle, boxes.json bytes, census shape
  census_sampling.py    Box-visibility set-cover selection (over the person's boxes)
  budget.py             Request-budget admission — refuse rather than half-do

box geometry (only frame selection reaches these now; the rest of what they
held served reconstruction and is a candidate for removal)
  placement.py          Splats into the ARKit world frame
  reproject.py          Two-tier reprojection-scoring instrument
  box_placement.py      Box footprint projection used by census_sampling
  room_planes.py        ARKit plane-anchor interpretation (single source)
  roomplan_room.py      CapturedRoom JSON interpretation (single source)

/shell stage
  shell_receiver.py     Route body: assemble and PUT shell.json
  shell_geometry.py     Measured-plane assembly + envelope closure
  shell_envelope.py     Envelope-only degrade (LIDAR_ARKIT, roomplan-absent)
  shell_observation.py  What each plane's own pixels observed
  shell_material.py     Per-plane parametric material inference
  shell_enqueue.py      Fire-and-forget task enqueue from /process

/compress stage
  compress_receiver.py  Route body: .spz siblings + compressed.json index
```
