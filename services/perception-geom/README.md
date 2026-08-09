# perception-geom

GPU service running VGGT-1B for scene-level geometric reconstruction.

Deployed to Cloud Run with an L4 GPU in `asia-southeast1`.

## PARKED — nothing in the live pipeline calls this

This service exists for the photo-upload path (Android, and iPhones without
LiDAR), which is deferred until the iOS capture path is solid. The shipping
pipeline is iOS → `api-internal` → `perception-obj`, and no code in that chain
references perception-geom. It stays deployed rather than deleted because the
photo-upload decision is open, not closed; it scales to zero, so an idle
revision costs nothing.

Read the rest of this file as a description of a service that works, not one
that is in use.

## Why split from perception-obj

SAM 3D Objects pins `torch==2.5.1+cu121` while VGGT pins `torch==2.3.1`. These
cannot coexist in a single pip environment. To keep both models on
known-working configurations, we run them in separate containers and compose
their outputs client-side. See `services/perception-obj/` for the other half
and `tools/call_perception.py` for the composition step.

## Endpoints

| Method | Path        | Purpose                                                                |
|--------|-------------|------------------------------------------------------------------------|
| GET    | `/`         | Health check                                                           |
| POST   | `/geom`     | Run VGGT → return a GLB point cloud + scene metadata (small response)  |
| POST   | `/geom-raw` | Run VGGT → return raw per-pixel pointmap + confidence as .npz          |

`/geom` is for viewing/quick checks. `/geom-raw` is what the client-side
composition step calls — it needs the full pointmap to register SAM-3D
splats into VGGT's coordinate frame.

## Deploying

From the repo root:

```bash
./infra/deploy_perception.sh geom
```

This runs Cloud Build, pushes to Artifact Registry, deploys to Cloud Run.

## File structure

```
Dockerfile           Container definition (CUDA 12.1 / torch 2.3.1)
server.py            FastAPI routes
models/vggt.py       VGGT-1B wrapper
```
