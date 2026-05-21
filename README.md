# roomstudio

Working title for the spatial intelligence platform.

## Repository layout

```
services/      Independently deployable services (one folder = one deploy unit)
packages/      Shared Python code imported by multiple services
web/           Next.js app (not yet created)
infra/         Deployment configs, Cloud Build YAML, deploy scripts
tools/         Local-only scripts: viewers, CLI clients, test harnesses
test_data/     Fixtures: sample photos, sample JSON outputs
outputs/       Local scratch directory for run outputs (gitignored)
```

Run `make help` (or read the `Makefile` / `justfile` if/when one exists) for common commands.

## Local development

1. Install Python 3.11+ and `uv` (or `pip`/`poetry`).
2. Create a `.env` from `.env.example` and fill in real values.
3. For service-local development, `cd services/<name>` and follow that service's README.

## Deploying

Each service has its own deploy script under `infra/`. Example:

```bash
./infra/deploy_perception.sh geom    # VGGT scene-level geometry
./infra/deploy_perception.sh obj     # SAM 3 segmentation + SAM 3D per-object splats
```

## Services

| Service             | Status   | Purpose                                                |
|---------------------|----------|--------------------------------------------------------|
| `perception-geom`   | active   | VGGT for scene geometry. Cloud Run + L4 GPU.           |
| `perception-obj`    | active   | SAM 3 segmentation + SAM 3D per-object splats. L4 GPU. |
| `api` (orchestrator)| planned  | Public API; orchestrates perception + reasoning.       |
| `reasoning`         | planned  | LLM calls (Claude/Gemini) for design generation.       |

### Why perception is split into two services

SAM 3D Objects pins `torch==2.5.1+cu121`. VGGT pins `torch==2.3.1`. They cannot
coexist in a single pip environment. The split also gives each model its own
scaling lifecycle — VGGT runs once per multi-photo capture, SAM 3D runs per
detected object.

Composition (placing per-object splats into VGGT's coordinate frame) currently
happens client-side in `tools/call_perception.py`. When the `api` orchestrator
service is built, that logic moves there — see
`services/api/SERVER_ORCHESTRATION_NOTE.md`.
