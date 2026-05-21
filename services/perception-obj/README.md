# perception-obj

GPU service running SAM 3 (open-vocabulary segmentation) and SAM 3D Objects
(per-object Gaussian splat reconstruction).

Deployed to Cloud Run with an L4 GPU in `asia-southeast1`.

## Why split from perception-geom

SAM 3D Objects pins `torch==2.5.1+cu121` while VGGT pins `torch==2.3.1`. These
cannot coexist in a single pip environment. See `services/perception-geom/`
for the other half and `tools/call_perception.py` for the composition step.

## Endpoints

| Method | Path            | Purpose                                                  |
|--------|-----------------|----------------------------------------------------------|
| GET    | `/`             | Health check                                             |
| POST   | `/segment`      | SAM 3 only — object metadata as JSON (no masks)          |
| POST   | `/segment-raw`  | SAM 3 only — zip: manifest.json + masks.npz              |
| POST   | `/objects`      | SAM 3 + SAM 3D — zip: manifest + masks.npz + splat PLYs  |

`/objects` is the heavy endpoint: it runs SAM 3 on a single canonical photo,
then SAM 3D on each detected object. Splats are saved as PLY files and packed
into the response zip. The full SAM-3D run scales with `max_objects` × per-
object inference time.

## Deploying

From the repo root:

```bash
./infra/deploy_perception.sh obj
```

This runs Cloud Build, pushes to Artifact Registry, deploys to Cloud Run.

## File structure

```
Dockerfile           Container definition (CUDA 12.1 / torch 2.5.1)
server.py            FastAPI routes
models/sam3.py       SAM 3 wrapper
models/sam3d.py      SAM 3D Objects wrapper
```
