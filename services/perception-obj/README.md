# perception-obj

GPU service running SAM 3 (open-vocabulary segmentation) and SAM 3D Objects
(per-object Gaussian splat reconstruction).

Deployed to Cloud Run with an L4 GPU in `asia-southeast1`.

## Why this service is split

SAM 3D Objects pins `torch==2.5.1+cu121` while VGGT pins `torch==2.3.1`. These
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
| POST   | `/compress` | Cloud Tasks compressed-splat receiver (0125/0126)               |

`/process` is the heavy endpoint and the only one that loads models: it claims
the scene's lease, samples frames from the capture bundle, runs SAM 3 then SAM
3D per detected object, fuses observations into one entry per physical object,
and writes the manifest + splats to the outputs bucket. It is budget-aware —
work that will not fit the request budget is refused rather than half-done, and
a warm retry resumes against the per-object caches.

`/shell` and `/compress` are derived-asset stages enqueued fire-and-forget by
`/process`'s success path. Neither touches a model, so both are cold-cheap.

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
models/sam3d.py         SAM 3D Objects wrapper

/process stage
  process_receiver.py   Receiver semantics (decision 0004): claim, run, release
  receiver_repo.py      Scene lease lifecycle in Firestore
  oidc.py               Cloud Tasks OIDC verification (per-route audience)
  fcm.py                Device notification on terminal Scene transitions
  privacy.py            Concepts SAM 3 sees but the product never ships
  sampling.py           Pose-diverse frame selection
  census_sampling.py    Box-visibility set-cover selection (RoomPlan tier)
  budget.py             Request-budget admission — refuse rather than half-do

placement + fusion
  placement.py          Splats into the ARKit world frame
  fusion.py             One entry per physical object, plus the placement passes
  reproject.py          Two-tier reprojection-scoring instrument
  box_placement.py      RoomPlan boxes as the object skeleton
  contact_priors.py     Single-view placement against measured planes
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
  compress_enqueue.py   Fire-and-forget task enqueue from /process
```
