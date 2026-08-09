# perception-obj: SAM 3 segmentation + SAM 3D Objects per-object reconstruction.
# AMD64, Cloud Build only. DO NOT build locally on M-series Mac.
#
# Build context is the REPO ROOT (same as services/api/Dockerfile) so that
# packages/schemas/ is reachable.  Cloud Build stages this correctly via
# infra/cloudbuild/perception-obj.yaml, which also downloads the pytorch3d
# wheel into wheels/ before invoking docker build.
#
# Why this split: SAM 3D Objects pins torch==2.5.1+cu121 while VGGT pins
# torch==2.3.1. They cannot coexist in one pip env. perception-obj uses
# CUDA 12.1 / torch 2.5.1; perception-geom uses CUDA 12.1 / torch 2.3.1.
# Composition happens client-side in tools/call_perception.py.
#
# Build strategy: follow Meta's setup.md exactly. Use mamba to create the
# environment from environments/default.yml (system CUDA toolkit, gcc, python
# 3.11.0), then run Meta's documented pip install sequence inside it. This is
# the only configuration Meta has tested and ships docs for.
#
# Deviation from Meta's flow: we install our pre-built pytorch3d wheel (cached
# in GCS by infra/build_pytorch3d_wheel.sh) instead of compiling pytorch3d
# during the build, because pytorch3d's compile alone is ~30-50 min and would
# push the total build over Cloud Build's 60-min global timeout. The cached
# wheel matches SAM 3D's pinned commit exactly.
#
# DEPENDENCY NOTE — protobuf version conflict (same issue as services/api/):
#   roomstudio-schemas requires protobuf>=7.35.0 (enforced by
#   ValidateProtobufRuntimeVersion in the generated pb2 file).
#   google-cloud-firestore (via proto-plus 1.x) declares protobuf<7.0.0dev.
#   These constraints are mutually exclusive in a single pip resolve.
#
#   Workaround (identical to services/api/Dockerfile, see docs/decisions/0005):
#   install google-cloud-* first (gets protobuf 6.x), then force-reinstall
#   protobuf>=7.35.0 before installing roomstudio-schemas.  --no-deps prevents
#   pip from re-resolving proto-plus's constraint on the upgrade step.

FROM condaforge/mambaforge:24.7.1-0

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HF_HOME=/models \
    DEBIAN_FRONTEND=noninteractive

# System deps not provided by the mamba env
RUN apt-get update && apt-get install -y --no-install-recommends \
        git \
        libgl1 \
        libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# --- Clone SAM 3D Objects so we have the env file ---
RUN git clone --depth 1 https://github.com/facebookresearch/sam-3d-objects.git /opt/sam3d

# --- Create the conda env from Meta's environments/default.yml ---
# This installs the CUDA toolkit (12.1), gcc 12.4, Python 3.11.0, and all the
# system-level deps Meta requires. ~15-25 min on first build.
RUN mamba env create -f /opt/sam3d/environments/default.yml \
    && mamba clean -afy

# Activate the env for all subsequent RUN/CMD instructions.
# (mamba doesn't have a real activation mechanism in Docker; we prepend its
# bin to PATH and set CONDA_PREFIX so anything that reads it gets the right
# value. Meta's notebook/inference.py reads CONDA_PREFIX at import time.)
# CPATH and LD_LIBRARY_PATH are required because conda's CUDA toolkit puts
# headers/libs under targets/x86_64-linux/, not directly under CUDA_HOME.
# nvcc finds them natively; g++ does not — so CUDA-extension builds fail
# without explicit -I paths. CPATH adds them globally for every gcc call.
ENV CONDA_PREFIX=/opt/conda/envs/sam3d-objects \
    PATH=/opt/conda/envs/sam3d-objects/bin:/opt/conda/bin:$PATH \
    CUDA_HOME=/opt/conda/envs/sam3d-objects \
    CPATH=/opt/conda/envs/sam3d-objects/targets/x86_64-linux/include:$CPATH \
    LD_LIBRARY_PATH=/opt/conda/envs/sam3d-objects/targets/x86_64-linux/lib:$LD_LIBRARY_PATH \
    TORCH_CUDA_ARCH_LIST="8.6;8.9;9.0" \
    MAX_JOBS=4

# --- Install pre-built pytorch3d wheel (deviation from Meta's flow) ---
# Compiled once by infra/build_pytorch3d_wheel.sh, cached in
# gs://roomstudio-build-cache/wheels/. The wheel is downloaded into wheels/
# at the repo root by the Cloud Build gsutil step before docker build runs.
# The cached wheel matches SAM 3D's pinned pytorch3d commit exactly.
COPY wheels/pytorch3d-*.whl /tmp/
RUN pip install /tmp/pytorch3d-*.whl && rm /tmp/pytorch3d-*.whl

# --- Meta's exact install sequence from doc/setup.md ---
# Step 1: pytorch/cuda extra index URLs (Meta's exact env var setting)
ENV PIP_EXTRA_INDEX_URL="https://pypi.ngc.nvidia.com https://download.pytorch.org/whl/cu121"

# Step 2: core deps + [dev] extra (skip [p3d] since we installed our wheel)
RUN cd /opt/sam3d && pip install -e '.[dev]'

# Step 3: kaolin index URL + [inference] extra (kaolin, gsplat, etc.)
ENV PIP_FIND_LINKS="https://nvidia-kaolin.s3.us-east-2.amazonaws.com/torch-2.5.1_cu121.html"
RUN cd /opt/sam3d && pip install -e '.[inference]'

# Step 4: apply Meta's hydra patch (required for correct config loading,
# referenced as ./patching/hydra in their setup.md)
RUN python /opt/sam3d/patching/hydra || echo "hydra patch skipped (likely version mismatch with installed hydra)"

# --- Pre-cache DINOv2 weights (fetched by SAM 3D Objects' backbone embedder) ---
# torch.hub is separate from the HuggingFace cache; set TORCH_HOME explicitly
# so the location is visible in the image and not buried under /root/.cache.
# sam3d_objects.model.backbone.dit.embedder.dino.Dino calls:
#   torch.hub.load("facebookresearch/dinov2", "dinov2_vitl14_reg", source="github")
# — the register-token variant, as configured by pipeline.yaml. Without this
# step, ~1.13 GB is fetched from dl.fbaipublicfiles.com on every cold start.
# Floating on "main" is a known limitation: torch.hub has no commit-pin API.
ENV TORCH_HOME=/opt/torch_hub
RUN python -c "\
import torch; \
torch.hub.load('facebookresearch/dinov2', 'dinov2_vitl14_reg', pretrained=True, trust_repo=True)"

# Verify weights landed where we expect. Fails the build loudly if the bake
# didn't populate the cache, so we catch it here rather than at cold-start.
RUN python -c "\
from pathlib import Path; \
cache = Path('/opt/torch_hub/hub/checkpoints'); \
assert any(p.name.endswith('reg4_pretrain.pth') for p in cache.iterdir()), \
    f'DINOv2 weights not cached at {cache}'; \
print(f'DINOv2 cached: {[p.name for p in cache.iterdir()]}')"

# --- Stage SAM 3D checkpoints at the layout Meta's pipeline.yaml expects ---
# The HF repo ships files in `checkpoints/` directly; Meta's setup.md adds the
# `hf/` directory layer via mv. We download with snapshot_download and then
# do the same restructuring. `cp -L` dereferences symlinks so the destination
# is self-contained (HF cache symlinks point relative to the cache dir).
RUN --mount=type=secret,id=hf_token \
    HF_TOKEN="$(cat /run/secrets/hf_token)" \
    python -c "\
import os; \
from huggingface_hub import login, snapshot_download; \
login(token=os.environ['HF_TOKEN']); \
print('Downloading SAM 3 weights...', flush=True); \
snapshot_download('facebook/sam3', cache_dir='/models'); \
print('Downloading SAM 3D Objects weights...', flush=True); \
sam3d_dir = snapshot_download('facebook/sam-3d-objects', cache_dir='/models'); \
open('/tmp/sam3d_snapshot_path.txt', 'w').write(sam3d_dir); \
print('SAM 3D snapshot at:', sam3d_dir, flush=True)"

RUN sam3d_dir="$(cat /tmp/sam3d_snapshot_path.txt)" \
    && mkdir -p /opt/sam3d/checkpoints/hf \
    && cp -rL "$sam3d_dir"/checkpoints/. /opt/sam3d/checkpoints/hf/ \
    && ls -la /opt/sam3d/checkpoints/hf \
    && test -f /opt/sam3d/checkpoints/hf/pipeline.yaml \
    && echo "pipeline.yaml verified"

# --- SAM 3 (segmentation) ---
# Installed last so it picks up the same torch/cuda environment.
RUN git clone --depth 1 https://github.com/facebookresearch/sam3.git /opt/sam3-repo \
    && cd /opt/sam3-repo && pip install -e .

# ── App-level deps: Layer A — google-cloud-* (brings in proto-plus → protobuf 6.x) ──
# Install all Google Cloud and Firebase packages together so pip resolves them
# as a group before the protobuf upgrade below.  Order matters: these must be
# installed BEFORE the force-reinstall step, or proto-plus will downgrade
# protobuf again after the upgrade.
# (FastAPI, uvicorn, and python-multipart are already installed by gradio's
# dependency chain in [inference]; do NOT re-install to avoid downgrades.)
RUN pip install \
        "pillow-heif==0.18.0" \
        "google-cloud-storage==2.18.2" \
        "google-cloud-firestore>=2.14,<3.0" \
        "google-cloud-tasks>=2.13,<3.0" \
        "firebase-admin>=6.0,<7.0" \
        "anthropic>=0.100,<1.0"

# ── App-level deps: Layer B — protobuf upgrade + roomstudio-schemas ──────────
# Force-reinstall protobuf to >=7.35.0 BEFORE installing roomstudio-schemas so
# that ValidateProtobufRuntimeVersion in capture_bundle_pb2.py succeeds.
# --no-deps prevents pip from re-resolving proto-plus's protobuf constraint
# (which would downgrade again).  See docs/decisions/0005.
COPY packages/schemas/ packages/schemas/
RUN pip install --no-deps --force-reinstall "protobuf>=7.35.0" \
    && pip install packages/schemas/

# ── Server code ───────────────────────────────────────────────────────────────
# All Python modules that make up the perception-obj service, including the
# /process receiver modules added after the initial deployment.
COPY services/perception-obj/server.py /app/server.py
COPY services/perception-obj/models/ /app/models/
COPY services/perception-obj/process_receiver.py /app/process_receiver.py
COPY services/perception-obj/oidc.py /app/oidc.py
COPY services/perception-obj/receiver_repo.py /app/receiver_repo.py
COPY services/perception-obj/fcm.py /app/fcm.py
COPY services/perception-obj/privacy.py /app/privacy.py
COPY services/perception-obj/placement.py /app/placement.py
COPY services/perception-obj/fusion.py /app/fusion.py
COPY services/perception-obj/reproject.py /app/reproject.py
COPY services/perception-obj/sampling.py /app/sampling.py
COPY services/perception-obj/census_sampling.py /app/census_sampling.py
COPY services/perception-obj/budget.py /app/budget.py
COPY services/perception-obj/room_planes.py /app/room_planes.py
COPY services/perception-obj/roomplan_room.py /app/roomplan_room.py
COPY services/perception-obj/contact_priors.py /app/contact_priors.py
COPY services/perception-obj/box_placement.py /app/box_placement.py
COPY services/perception-obj/shell_geometry.py /app/shell_geometry.py
COPY services/perception-obj/shell_envelope.py /app/shell_envelope.py
COPY services/perception-obj/shell_observation.py /app/shell_observation.py
COPY services/perception-obj/shell_material.py /app/shell_material.py
COPY services/perception-obj/shell_receiver.py /app/shell_receiver.py
COPY services/perception-obj/shell_enqueue.py /app/shell_enqueue.py
COPY services/perception-obj/compress_receiver.py /app/compress_receiver.py
COPY services/perception-obj/compress_enqueue.py /app/compress_enqueue.py

# Deferred-import smoke: placement/fusion/sampling/budget and the shell_*
# modules are imported lazily inside /process and /shell, so a missing COPY
# above passes /health and every pre-traffic probe, then breaks the first
# real reconstruction (this happened: placement.py and fusion.py were
# absent from an image that passed /health and every probe). Fail the
# BUILD instead.
# (Light imports only — numpy + roomstudio_schemas; no torch, no model
# weights.) `anthropic` is on the line because shell_material defers it:
# a missing pip install would not crash — the 0069 fallback rule would
# silently null every family forever, which the build must catch instead.
RUN python -c "import placement, fusion, reproject, sampling, census_sampling, \
budget, room_planes, roomplan_room, contact_priors, box_placement, privacy, \
shell_geometry, shell_envelope, shell_observation, shell_material, \
shell_receiver, shell_enqueue, compress_receiver, compress_enqueue, anthropic"

# ── The SPZ encoder: Node + Spark, for the /compress stage ───────────────────
# The compressed splat tier (decisions 0125/0126) must be written by Spark's
# OWN SpzWriter — the same build the browser decodes with — so the encoder is
# JavaScript and this CUDA image needs a Node runtime. It is CPU-only work and
# never touches a model; see compress_receiver.py for why the stage rides this
# service rather than a fourth one.
#
# Pinned versions, not a lockfile-free "npm install @sparkjsdev/spark": the
# encoder and the browser's decoder drifting apart is the exact failure 0126
# exists to prevent, so both sides move deliberately. Keep the spark and three
# versions in step with web/package.json.
RUN apt-get update && apt-get install -y --no-install-recommends nodejs npm \
    && rm -rf /var/lib/apt/lists/*
RUN mkdir -p /opt/spz && cd /opt/spz \
    && npm init -y >/dev/null \
    && npm install --no-audit --no-fund --omit=dev \
        "@sparkjsdev/spark@2.1.0" "three@0.185.1"
COPY tools/spz_encode.mjs /app/tools/spz_encode.mjs
ENV SPARK_MODULE_PATH=/opt/spz/node_modules/@sparkjsdev/spark/dist/spark.module.js \
    SPZ_ENCODER_PATH=/app/tools/spz_encode.mjs

# The encoder must be ARMED in the image, for the same reason privacy is
# below: compress_receiver imports nothing from Node at module scope, so a
# missing runtime, a missing Spark, or a bad COPY would pass /health and
# every probe, and only surface as "no compressed tier, ever" — silently
# slow rooms, not a crash. Prove the real encode path end to end at BUILD
# time on a synthetic 2-Gaussian PLY: node runs, Spark loads from
# SPARK_MODULE_PATH, transcodeSpz produces bytes, and Spark's own reader
# parses them back with the count preserved.
RUN python -c "\
import struct, subprocess, os, json, tempfile; \
hdr = b'ply\nformat binary_little_endian 1.0\nelement vertex 2\n' \
      + b''.join(('property float ' + p + '\n').encode() for p in \
        ['x','y','z','nx','ny','nz','f_dc_0','f_dc_1','f_dc_2','opacity', \
         'scale_0','scale_1','scale_2','rot_0','rot_1','rot_2','rot_3']) \
      + b'end_header\n'; \
body = struct.pack('<34f', *([0.1] * 34)); \
d = tempfile.mkdtemp(); p = os.path.join(d, 'a.ply'); q = os.path.join(d, 'a.spz'); \
open(p, 'wb').write(hdr + body); \
out = subprocess.run(['node', os.environ['SPZ_ENCODER_PATH'], p, q], \
                     capture_output=True, check=True); \
stats = json.loads(out.stdout.decode().strip().splitlines()[-1]); \
assert stats['gaussians'] == 2, stats; \
assert os.path.getsize(q) > 0; \
print('spz encoder armed:', stats)"

# Privacy suppression must be ARMED in the image (decision 0089). privacy.py
# is a deferred import inside /process, so a missing COPY passes every probe
# and then silently ships people again — worse than a crash, because the
# pipeline keeps working. Assert the default concept is live at build time.
RUN python -c "\
import privacy; \
assert 'person' in privacy.SUPPRESSED_CONCEPTS, privacy.SUPPRESSED_CONCEPTS; \
assert 'person' in privacy.segmentation_prompt('chair,bed'); \
print('privacy suppression armed:', privacy.SUPPRESSED_CONCEPTS)"

ENV PORT=8080
EXPOSE 8080

CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "1"]
