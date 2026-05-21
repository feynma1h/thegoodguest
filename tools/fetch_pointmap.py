"""
Fetch the raw VGGT pointmap from perception-geom /geom-raw and persist
it to disk for offline composition iteration.

Run from the repo root:

    python tools/fetch_pointmap.py

Reads photos from test_data/photos/, writes outputs/pointmap.npz.

This is the same call that cmd_scene step 1 makes; cmd_scene just doesn't
persist the result. Standalone so you can populate pointmap.npz without
having to run the whole scene pipeline (in particular, without depending
on perception-obj being warm).
"""
from __future__ import annotations

import io
import os
import sys
import time
from pathlib import Path

import requests
from dotenv import load_dotenv
from PIL import Image

try:
    from pillow_heif import register_heif_opener
    register_heif_opener()
except ImportError:
    pass


PHOTOS_DIR = Path("test_data/photos")
OUTPUTS_DIR = Path("outputs")
OUT_PATH = OUTPUTS_DIR / "pointmap.npz"
MAX_EDGE_PX = 1024


def load_as_jpeg(path: Path) -> tuple[str, bytes]:
    img = Image.open(path).convert("RGB")
    w, h = img.size
    scale = MAX_EDGE_PX / max(w, h)
    if scale < 1.0:
        img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=85)
    return f"{path.stem}.jpg", buf.getvalue()


def collect_photos() -> list[Path]:
    if not PHOTOS_DIR.exists():
        raise FileNotFoundError(f"Photos directory not found: {PHOTOS_DIR}")
    photos = sorted(
        p for p in PHOTOS_DIR.iterdir()
        if p.suffix.lower() in (".jpg", ".jpeg", ".png", ".heic", ".heif")
    )
    if not photos:
        raise FileNotFoundError(f"No photos in {PHOTOS_DIR}/")
    return photos


def main() -> None:
    load_dotenv()
    geom_url = os.environ.get("PERCEPTION_GEOM_URL")
    if not geom_url:
        print("ERROR: PERCEPTION_GEOM_URL not set in .env at the repo root.")
        sys.exit(1)
    geom_url = geom_url.rstrip("/")

    photos = collect_photos()
    files = [("images", (n, b, "image/jpeg")) for (n, b) in [load_as_jpeg(p) for p in photos]]
    total_mb = sum(len(f[1][1]) for f in files) / 1024 / 1024
    print(f"POST {geom_url}/geom-raw ({len(photos)} images, {total_mb:.1f} MB)")

    # Retry handful of times on 503 — geom is uvicorn-binds-after-model-load,
    # so cold start can return 503 from the LB until the startup probe passes.
    t0 = time.time()
    max_attempts = 8
    for attempt in range(1, max_attempts + 1):
        try:
            r = requests.post(f"{geom_url}/geom-raw", files=files, timeout=900)
        except requests.RequestException as e:
            print(f"  attempt {attempt}/{max_attempts}: connection error ({e.__class__.__name__}); waiting 15s")
            time.sleep(15)
            continue
        if r.status_code == 503:
            print(f"  attempt {attempt}/{max_attempts}: 503 (cold start in progress); waiting 15s")
            time.sleep(15)
            continue
        r.raise_for_status()
        break
    else:
        print(f"FAILED after {max_attempts} attempts")
        sys.exit(1)

    OUTPUTS_DIR.mkdir(exist_ok=True)
    OUT_PATH.write_bytes(r.content)
    print(f"Saved {OUT_PATH} ({len(r.content) // 1024} KB) in {time.time() - t0:.1f}s")


if __name__ == "__main__":
    main()
