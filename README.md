# The Good Guest

A spatial intelligence product: capture a room with an iPhone, and get an
AI-readable, navigable 3D reconstruction of *that* room to reason about and
redesign.

The product, the repo and the app are all **The Good Guest**. The **GCP project
id stays `thegoodguest`**, and so do the bucket names, the service-account
addresses and the `thegoodguest.web.app` hosting URL: GCP project ids are
immutable and bucket names are globally unique, so those can only change by
migrating to a new project. Where you see `thegoodguest` below, it is naming a
live cloud resource, not the product.

The always-current state of the project — what works, what does not, and what
is next — is `CLAUDE.md`. This file covers layout, local setup, and deploys.

## Repository layout

```
packages/schemas/    capture-bundle proto + generated Python + pose/placement math
packages/api-core/   shared logic imported by both API services
services/            one folder per Cloud Run deploy unit
ios/                 the Swift capture app (TheGoodGuest)
web/                 Next.js static-export web app
infra/               deploy scripts, Cloud Build configs, runbooks
tools/               local scripts: fixture builders, smoke clients, converters
docs/decisions/      why non-obvious decisions were made (see CLAUDE.md)
docs/briefs/         design briefs for completed work
test_data/           synthetic fixtures for local pipeline testing
outputs/             local scratch for run artifacts (gitignored)
```

## Services

All four run on Cloud Run in `asia-southeast1`, project `thegoodguest`.

| Service           | State  | Purpose                                                          |
|-------------------|--------|------------------------------------------------------------------|
| `api-public`      | live   | Client-facing. Firebase JWT verified in-app; `--allow-unauthenticated`. Upload sessions, scene reads, signed asset URLs, the conversation, account deletion. |
| `api-internal`    | live   | Eventarc ingest. Cloud Run IAM gated; `--no-allow-unauthenticated`. Validates a finalized bundle and enqueues perception. |
| `perception-obj`  | live   | L4 GPU. SAM 3 segmentation + SAM 3D Objects reconstruction, placement/fusion, room shell, splat compression. |
| `perception-geom` | parked | L4 GPU. VGGT, for a photo-upload path that is deferred. Deployed but nothing calls it. |

The pipeline: iOS uploads a capture bundle to GCS → the `bundle.pb` finalize
event reaches `api-internal/ingest/eventarc` → Cloud Tasks dispatches
`perception-obj/process` → artifacts land in the outputs bucket → `api-public`
serves them to the web app over signed URLs.

`packages/schemas/capture_bundle.proto` is the contract between iOS and the
backend, and its docstring is the reference for the frame and pose
conventions. Read it before touching anything that crosses that boundary.

### Why perception is split into two services

SAM 3D Objects pins `torch==2.5.1+cu121`; VGGT pins `torch==2.3.1`. They cannot
coexist in one pip environment. The split also gives each its own scaling
lifecycle.

## Local development

Python 3.11+ (the services build on `python:3.11-slim`). Create a virtualenv
and install the two local packages editable, plus each component's declared
dependencies:

```bash
python -m venv .venv && .venv/bin/python -m pip install -U pip
.venv/bin/python -m pip install -e packages/schemas -e packages/api-core
```

`tools/ci_deps.py` prints the dependency list for any component's
`pyproject.toml`; `.github/workflows/python.yml` shows the exact install
commands CI uses. The services are flat modules and are deliberately not
pip-installable — `conftest.py` puts them on `sys.path`.

### Tests

`pyproject.toml` `testpaths` selects the root suite. Two suites sit outside it
and are invoked by path — `perception-obj` because it pins `numpy<2` and cannot
share an environment with `packages/schemas`, and the re-enqueue tool because
it is not under a `testpaths` entry:

```bash
.venv/bin/python -m pytest                                 # root suite
.venv/bin/python -m pytest services/perception-obj/tests   # perception
.venv/bin/python -m pytest tools/test_reenqueue_scene.py   # re-enqueue tool
```

The suites must pass with no cloud credentials available — see the Python test
policy in `CLAUDE.md`.

Lint and format with `ruff` (config in `pyproject.toml`). The house rule is
ruff-clean on touched files; the repo-wide run is not yet clean and the CI
lint job is non-gating for that reason.

### Web

Node 22. From `web/`:

```bash
npm ci
npm run dev      # http://localhost:3000, mock fixtures by default
npm test         # vitest
npm run build    # static export to web/out/
```

See `web/README.md` for data modes and the app's structure.

### iOS

Open `ios/TheGoodGuest/TheGoodGuest.xcodeproj`. The app needs a
`GoogleService-Info.plist`, which is gitignored — copy it in before building.
`TheGoodGuest-Integration` is the only scheme, and it runs four live
integration tests against deployed `api-public`; see the iOS test policy in
`CLAUDE.md` before running the suite.

### Regenerating the proto

```bash
./tools/gen_proto.sh    # writes the Python and Swift bindings, both committed
```

## Deploying

`infra/RUNBOOK.md` is the full procedure, including the preflight gates and the
candidate-revision smoke that runs before any traffic flip. The scripts are
idempotent and are run from the repo root:

```bash
./infra/deploy_api_internal.sh        # run first on a fresh project
./infra/deploy_api_public.sh
./infra/deploy_perception.sh obj      # SAM 3 + SAM 3D
./infra/deploy_perception.sh geom     # VGGT (parked)
```

The web app deploys to Firebase Hosting from `web/` (`npm run deploy:preview`
for the preview channel). `infra/PRODUCTION_FLIP.md` covers the production
channel.
