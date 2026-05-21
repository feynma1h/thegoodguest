# perception-obj: SAM 3 segmentation + SAM 3D Objects per-object reconstruction.
# AMD64, Cloud Build only. DO NOT build locally on M-series Mac.
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
# gs://roomstudio-build-cache/wheels/. The wheel matches SAM 3D's pinned
# pytorch3d commit. The cloudbuild step downloaded it to wheels/ in the
# build context.
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

# --- App-level deps not already pulled in by SAM 3D's [dev]/[inference] ---
# (FastAPI, uvicorn, and python-multipart are already installed by gradio's
# dependency chain in [inference], at versions newer than we would pin. Do
# NOT re-install them here — that would downgrade and break gradio's imports.
# We only add what SAM 3D doesn't install: pillow-heif for HEIC support.)
RUN pip install "pillow-heif==0.18.0" "google-cloud-storage==2.18.2"

# Server code
COPY service/server.py /app/server.py
COPY service/models/ /app/models/

ENV PORT=8080
EXPOSE 8080

CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "1"]