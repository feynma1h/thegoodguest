"""
perception-geom server.

VGGT-only inference. One model, one heavy endpoint.

All inference logic lives in models/vggt.py. This file is FastAPI routes only.
"""
from __future__ import annotations

import io
import json
import os
import tempfile
import time
from typing import Any

import torch
import trimesh
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import Response
from PIL import Image

try:
    from pillow_heif import register_heif_opener
    register_heif_opener()
except ImportError:
    pass

from models.vggt import VGGTModel


# -----------------------------------------------------------------------------
# Configuration
# -----------------------------------------------------------------------------
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
DTYPE = torch.bfloat16 if DEVICE == "cuda" else torch.float32

# -----------------------------------------------------------------------------
# Model initialization (once at container startup)
# -----------------------------------------------------------------------------
print(f"[startup] Initializing on {DEVICE}, dtype={DTYPE}", flush=True)
_t = time.time()
vggt = VGGTModel(device=DEVICE, dtype=DTYPE)
print(f"[startup] VGGT loaded in {time.time() - _t:.1f}s", flush=True)


# -----------------------------------------------------------------------------
# FastAPI app
# -----------------------------------------------------------------------------
app = FastAPI(title="thegoodguest-perception-geom")


@app.get("/")
def health() -> dict[str, Any]:
    return {"status": "ok", "device": DEVICE, "model": "vggt-1b"}


@app.post("/geom")
async def geom(images: list[UploadFile] = File(...)) -> Response:
    """
    Run VGGT on N photos. Returns a GLB containing:
      - the unified point cloud
      - per-pixel world points (encoded in glTF extras as JSON metadata)

    Metadata returned in the X-Geom-Metadata response header:
      n_images, total_seconds, n_points, scene_dimensions.

    The full per-pixel pointmap is NOT returned over the wire (would be ~hundreds of
    MB). Clients that need per-pixel pointmaps for splat placement should call
    /geom-raw instead.
    """
    if not images:
        raise HTTPException(400, "No images provided")
    if len(images) > 12:
        raise HTTPException(400, "Max 12 images per request")

    t0 = time.time()
    paths = await _save_uploads(images)
    predictions = vggt.infer(paths)
    pts, colors = VGGTModel.predictions_to_pointcloud(predictions)
    cloud = trimesh.PointCloud(vertices=pts, colors=colors)
    glb_bytes = trimesh.Scene([cloud]).export(file_type="glb")

    metadata = {
        "n_images": len(paths),
        "n_points": int(pts.shape[0]),
        "scene_extent": (pts.max(0) - pts.min(0)).tolist(),
        "total_seconds": time.time() - t0,
    }
    print(f"[geom] done in {time.time() - t0:.1f}s, {pts.shape[0]} points", flush=True)
    return Response(
        content=glb_bytes,
        media_type="model/gltf-binary",
        headers={"X-Geom-Metadata": json.dumps(metadata)},
    )


@app.post("/geom-raw")
async def geom_raw(images: list[UploadFile] = File(...)) -> Response:
    """
    Run VGGT and return the raw per-pixel pointmap and confidence as an
    .npz blob. Used by the client-side composition step in
    tools/call_perception.py to register SAM-3D splats into VGGT's frame.

    Response is a binary .npz with keys:
      world_points       (N, H, W, 3) float32  — VGGT pointmap, batch removed
      world_points_conf  (N, H, W)    float32  — confidence per pixel
      image_size         (2,)         int32    — (H, W) of VGGT's working res
    """
    if not images:
        raise HTTPException(400, "No images provided")
    if len(images) > 12:
        raise HTTPException(400, "Max 12 images per request")

    import numpy as np

    t0 = time.time()
    paths = await _save_uploads(images)
    predictions = vggt.infer(paths)

    world_points = predictions["world_points"].squeeze(0).cpu().float().numpy()
    confs = predictions["world_points_conf"].squeeze(0).cpu().float().numpy()
    H, W = world_points.shape[1:3]

    buf = io.BytesIO()
    np.savez_compressed(
        buf,
        world_points=world_points,
        world_points_conf=confs,
        image_size=np.array([H, W], dtype=np.int32),
    )
    payload = buf.getvalue()
    print(
        f"[geom-raw] done in {time.time() - t0:.1f}s, "
        f"pointmap shape {world_points.shape}, payload {len(payload)//1024} KB",
        flush=True,
    )
    return Response(content=payload, media_type="application/octet-stream")


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------

async def _save_uploads(uploads: list[UploadFile]) -> list[str]:
    """Save uploaded images to a temp dir as normalized JPEGs."""
    tmpdir = tempfile.mkdtemp()
    paths = []
    for i, upload in enumerate(uploads):
        data = await upload.read()
        img = Image.open(io.BytesIO(data)).convert("RGB")
        p = os.path.join(tmpdir, f"img_{i:03d}.jpg")
        img.save(p, "JPEG", quality=95)
        paths.append(p)
    return paths
