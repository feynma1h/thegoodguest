# perception-geom: VGGT-only geometric reconstruction service.
# AMD64, Cloud Build only. DO NOT build locally on M-series Mac.
#
# Why this split: SAM 3D Objects pins torch==2.5.1+cu121 while VGGT pins
# torch==2.3.1. They cannot coexist in one pip env. perception-geom uses
# VGGT's preferred CUDA 12.4 / torch 2.3.1; perception-obj uses CUDA 12.1
# / torch 2.5.1. Composition happens client-side in tools/call_perception.py.

FROM pytorch/pytorch:2.3.1-cuda12.1-cudnn8-runtime

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HF_HOME=/models

# System deps
RUN apt-get update && apt-get install -y --no-install-recommends \
        git \
        build-essential \
        libgl1 \
        libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Core Python deps (no transformers — VGGT doesn't need it)
RUN pip install \
        "fastapi==0.115.0" \
        "uvicorn[standard]==0.30.6" \
        "python-multipart==0.0.12" \
        "huggingface_hub==0.25.0" \
        "trimesh==4.4.9" \
        "pillow==10.4.0" \
        "pillow-heif==0.18.0" \
        "numpy<2" \
        "einops" \
        "safetensors"

# --- VGGT (geometric backbone) ---
# VGGT pins torch==2.3.1 and torchvision==0.18.1 in its requirements.txt.
# The base image already has matching versions, so `pip install -e .` is a no-op
# for those pins. If VGGT ever bumps, the base image bumps with it.
RUN git clone --depth 1 https://github.com/facebookresearch/vggt.git /opt/vggt \
    && cd /opt/vggt && pip install -e .

# Pre-download VGGT weights at build time (faster cold starts).
# HF_TOKEN comes from a BuildKit secret mounted by Cloud Build.
RUN --mount=type=secret,id=hf_token \
    HF_TOKEN="$(cat /run/secrets/hf_token)" \
    python -c "\
import os; \
from huggingface_hub import login, snapshot_download; \
login(token=os.environ['HF_TOKEN']); \
print('Downloading VGGT...'); \
snapshot_download('facebook/VGGT-1B', cache_dir='/models'); \
print('Done.')"

# Server code
COPY server.py /app/server.py
COPY models/ /app/models/

ENV PORT=8080
EXPOSE 8080

CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "1"]
