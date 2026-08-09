"""
Local CLI for calling the two deployed perception services and composing
their outputs.

PARTLY DEAD: perception-obj's /segment, /segment-raw and /objects were removed
when /process became the only perception entrypoint (it now serves /process,
/shell and /compress), so the `segment`, `objects` and `scene` subcommands
404. Only `geom` (perception-geom /geom) still resolves; the composition
helpers below are still imported by tools/compose_local.py.

Run from the repo root:

    python tools/call_perception.py geom          # VGGT only, save point cloud GLB
    python tools/call_perception.py segment       # SAM 3 on canonical photo, print + save
    python tools/call_perception.py objects       # SAM 3 + SAM 3D, save splats + manifest
    python tools/call_perception.py scene         # full pipeline, compose splats into VGGT frame

Inputs: test_data/photos/ (any mix of JPG/PNG/HEIC).
Outputs: outputs/ (gitignored).

This module owns the client-side composition that the previous monolithic
perception service did internally. In particular, `cmd_scene`:
  1. calls perception-geom /geom-raw for the pointmap
  2. calls perception-obj /objects for masks + splat PLYs
  3. computes per-object splat placement using the pointmap + mask
  4. composes everything into a single GLB
"""
from __future__ import annotations

import io
import json
import os
import sys
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

import numpy as np
import requests
import trimesh
from dotenv import load_dotenv
from PIL import Image

try:
    from pillow_heif import register_heif_opener
    register_heif_opener()
except ImportError:
    pass


# Paths relative to the repo root (where this is run from).
PHOTOS_DIR = Path("test_data/photos")
OUTPUTS_DIR = Path("outputs")
MAX_EDGE_PX = 1024


# ---------------------------------------------------------------------------
# Photo loading
# ---------------------------------------------------------------------------

def load_as_jpeg(path: Path) -> tuple[str, bytes]:
    """Load any supported image format and return (filename, jpeg bytes), downscaled."""
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


def url_or_exit(env_var: str) -> str:
    url = os.environ.get(env_var)
    if not url:
        print(f"ERROR: {env_var} not set in .env at the repo root.")
        sys.exit(1)
    return url.rstrip("/")


def wait_for_ready(base_url: str, *, timeout_s: float = 900.0, poll_s: float = 5.0) -> None:
    """Poll GET {base_url}/ready until 200, or 500 (startup failure), or timeout.
    perception-obj scales to zero; first request triggers a 4-5min cold start
    while SAM 3 + SAM 3D load. Polling /ready is cheap and lets us avoid
    making the actual work request hang against the LB cold-start window."""
    t0 = time.time()
    last_status = None
    last_elapsed = None
    while True:
        elapsed_client = time.time() - t0
        if elapsed_client > timeout_s:
            raise TimeoutError(
                f"{base_url}/ready did not become ready in {timeout_s:.0f}s "
                f"(last status={last_status}, server elapsed={last_elapsed})"
            )
        try:
            r = requests.get(f"{base_url}/ready", timeout=10)
        except requests.RequestException as e:
            # Cold-start LB may briefly drop connections; keep polling.
            print(f"  /ready: connection error ({e.__class__.__name__}); retrying")
            time.sleep(poll_s)
            continue

        last_status = r.status_code
        try:
            body = r.json()
            last_elapsed = body.get("elapsed_seconds")
        except ValueError:
            body = {}

        if r.status_code == 200:
            print(f"  /ready: ready in ~{last_elapsed:.0f}s server-side")
            return
        if r.status_code == 500:
            err = body.get("error", "unknown")
            raise RuntimeError(f"perception-obj startup failed: {err}")
        # 503 = still loading. Keep polling.
        print(
            f"  /ready: 503 loading (server elapsed={last_elapsed}s, "
            f"client elapsed={elapsed_client:.0f}s)"
        )
        time.sleep(poll_s)


# ---------------------------------------------------------------------------
# Single-service commands
# ---------------------------------------------------------------------------

def cmd_geom() -> None:
    """Call perception-geom /geom. Save GLB point cloud."""
    geom_url = url_or_exit("PERCEPTION_GEOM_URL")
    photos = collect_photos()
    files = [("images", (n, b, "image/jpeg")) for (n, b) in [load_as_jpeg(p) for p in photos]]
    total = sum(len(f[1][1]) for f in files)
    print(f"POST /geom ({len(photos)} images, {total / 1024 / 1024:.1f} MB)")

    r = requests.post(f"{geom_url}/geom", files=files, timeout=900)
    r.raise_for_status()

    OUTPUTS_DIR.mkdir(exist_ok=True)
    out = OUTPUTS_DIR / "point_cloud.glb"
    out.write_bytes(r.content)
    meta = json.loads(r.headers.get("X-Geom-Metadata", "{}"))
    print(f"Saved {out} ({len(r.content) // 1024} KB)")
    print(f"Metadata: {json.dumps(meta, indent=2)}")


def cmd_segment() -> None:
    """Call perception-obj /segment on the first photo."""
    obj_url = url_or_exit("PERCEPTION_OBJ_URL")
    photos = collect_photos()
    p = photos[0]
    name, data = load_as_jpeg(p)
    files = {"image": (name, data, "image/jpeg")}
    print(f"Waiting for perception-obj to be ready...")
    wait_for_ready(obj_url)
    print(f"POST /segment ({p.name})")

    r = requests.post(f"{obj_url}/segment", files=files, timeout=300)
    r.raise_for_status()

    body = r.json()
    OUTPUTS_DIR.mkdir(exist_ok=True)
    (OUTPUTS_DIR / "segments.json").write_text(json.dumps(body, indent=2))

    objects = body["objects"]
    print(f"Found {len(objects)} object instances:")
    by_label: dict[str, list[float]] = {}
    for o in objects:
        by_label.setdefault(o["label"], []).append(o["score"])
    for label, scores in sorted(by_label.items(), key=lambda kv: -max(kv[1])):
        sample = [f"{s:.2f}" for s in scores[:5]]
        print(f"  {label:20s} x{len(scores):2d}  top scores: {sample}")
    print(f"Saved {OUTPUTS_DIR / 'segments.json'}")


def _parse_gs_uri(uri: str) -> tuple[str, str]:
    """Split 'gs://bucket/path/to/blob' into ('bucket', 'path/to/blob')."""
    if not uri.startswith("gs://"):
        raise ValueError(f"Not a gs:// URI: {uri}")
    rest = uri[len("gs://"):]
    bucket, _, blob = rest.partition("/")
    if not bucket or not blob:
        raise ValueError(f"Malformed gs:// URI: {uri}")
    return bucket, blob


_gcs_client = None


def _gcs():
    """Lazily construct a single GCS client using ADC (gcloud auth)."""
    global _gcs_client
    if _gcs_client is None:
        from google.cloud import storage  # noqa: PLC0415
        _gcs_client = storage.Client()
    return _gcs_client


def _gcs_download(uri: str, dst: Path) -> int:
    """Download gs:// URI to local path. Returns bytes written."""
    bucket_name, blob_name = _parse_gs_uri(uri)
    bucket = _gcs().bucket(bucket_name)
    blob = bucket.blob(blob_name)
    dst.parent.mkdir(parents=True, exist_ok=True)
    blob.download_to_filename(str(dst))
    return dst.stat().st_size


def _gcs_download_bytes(uri: str) -> bytes:
    """Download gs:// URI as bytes."""
    bucket_name, blob_name = _parse_gs_uri(uri)
    bucket = _gcs().bucket(bucket_name)
    blob = bucket.blob(blob_name)
    return blob.download_as_bytes()


def _download_splats(manifest: dict[str, Any], dst_dir: Path) -> dict[int, Path]:
    """Download every ok object's splat into dst_dir. Returns
    {mask_index -> local Path}. Runs in parallel."""
    dst_dir.mkdir(parents=True, exist_ok=True)
    splat_paths: dict[int, Path] = {}
    todo = [
        (o["mask_index"], o["splat_gcs_uri"], o["label"])
        for o in manifest["objects"]
        if o.get("ok")
    ]
    if not todo:
        return splat_paths

    def _one(idx_uri_label):
        idx, uri, label = idx_uri_label
        safe = label.replace(" ", "-").replace("/", "-")
        dst = dst_dir / f"{idx:02d}_{safe}.ply"
        size = _gcs_download(uri, dst)
        return idx, dst, size

    with ThreadPoolExecutor(max_workers=8) as pool:
        for fut in as_completed(pool.submit(_one, t) for t in todo):
            idx, dst, size = fut.result()
            splat_paths[idx] = dst
    return splat_paths


def cmd_objects() -> None:
    """Call perception-obj /objects. Server returns a JSON manifest with
    gs:// URIs; client downloads splats from GCS in parallel."""
    obj_url = url_or_exit("PERCEPTION_OBJ_URL")
    photos = collect_photos()
    p = photos[0]
    name, data = load_as_jpeg(p)
    files = {"image": (name, data, "image/jpeg")}
    print(f"Waiting for perception-obj to be ready...")
    wait_for_ready(obj_url)
    print(f"POST /objects ({p.name}, full SAM 3 + SAM 3D pipeline)")
    print("Expected runtime: several minutes (first run); ~instant if cached.")

    # The server's runtime is up to ~10 min on a fresh photo. The response
    # itself is small JSON, so a 1200s timeout is plenty even with margin.
    r = requests.post(f"{obj_url}/objects", files=files, timeout=1200)
    r.raise_for_status()
    manifest = r.json()

    OUTPUTS_DIR.mkdir(exist_ok=True)
    manifest_path = OUTPUTS_DIR / "objects.json"
    manifest_path.write_text(json.dumps(manifest, indent=2))

    n_ok = sum(1 for o in manifest["objects"] if o["ok"])
    cached = manifest.get("cached", False)
    print(
        f"Manifest: {n_ok}/{len(manifest['objects'])} objects reconstructed"
        f"{' (cache HIT)' if cached else ''}"
    )

    # Pull every splat from GCS in parallel.
    extract_dir = OUTPUTS_DIR / "objects_extracted"
    splat_paths = _download_splats(manifest, extract_dir)
    total_bytes = sum(p.stat().st_size for p in splat_paths.values())
    print(
        f"Downloaded {len(splat_paths)} splats to {extract_dir}/ "
        f"({total_bytes // (1024 * 1024)} MiB)"
    )
    print(f"Manifest: {manifest_path}")


# ---------------------------------------------------------------------------
# Full pipeline: geom + objects + client-side composition
# ---------------------------------------------------------------------------

def cmd_scene() -> None:
    """
    Full pipeline:
      1. perception-geom /geom-raw  -> pointmap + confidence
      2. perception-obj  /objects   -> masks + per-object splat PLYs
      3. compose locally -> outputs/scene.glb
    """
    geom_url = url_or_exit("PERCEPTION_GEOM_URL")
    obj_url = url_or_exit("PERCEPTION_OBJ_URL")
    photos = collect_photos()
    canonical_index = 0

    OUTPUTS_DIR.mkdir(exist_ok=True)
    t0 = time.time()

    # 1. Geom-raw -> pointmap
    geom_files = [("images", (n, b, "image/jpeg")) for (n, b) in [load_as_jpeg(p) for p in photos]]
    geom_size = sum(len(f[1][1]) for f in geom_files)
    print(f"[1/3] POST /geom-raw ({len(photos)} images, {geom_size / 1024 / 1024:.1f} MB)")
    r_geom = requests.post(f"{geom_url}/geom-raw", files=geom_files, timeout=900)
    r_geom.raise_for_status()
    npz = np.load(io.BytesIO(r_geom.content))
    world_points = npz["world_points"]
    world_points_conf = npz["world_points_conf"]
    print(f"      pointmap shape {world_points.shape} at +{time.time() - t0:.1f}s")

    # 2. Objects on canonical photo -> masks + splats (via GCS)
    canonical = photos[canonical_index]
    name, data = load_as_jpeg(canonical)
    print(f"      waiting for perception-obj to be ready...")
    wait_for_ready(obj_url)
    print(f"[2/3] POST /objects ({canonical.name})")
    r_obj = requests.post(
        f"{obj_url}/objects",
        files={"image": (name, data, "image/jpeg")},
        timeout=1200,
    )
    r_obj.raise_for_status()
    manifest = r_obj.json()
    (OUTPUTS_DIR / "scene_objects.json").write_text(json.dumps(manifest, indent=2))

    # Download splats from GCS in parallel.
    splat_paths = _download_splats(manifest, OUTPUTS_DIR / "scene_objects_extracted")

    # Rehydrate masks from GCS so _compose_scene can place each object using
    # its mask centroid against the VGGT pointmap.
    masks_uri = manifest.get("masks_gcs_uri")
    if not masks_uri:
        raise RuntimeError(
            "Server manifest is missing masks_gcs_uri; cannot compose scene"
        )
    masks_bytes = _gcs_download_bytes(masks_uri)
    masks_npz = np.load(io.BytesIO(masks_bytes))
    masks_array = masks_npz["masks"]

    n_ok = sum(1 for o in manifest["objects"] if o["ok"])
    print(
        f"      {n_ok}/{len(manifest['objects'])} objects reconstructed at "
        f"+{time.time() - t0:.1f}s"
    )

    # 3. Compose: VGGT pointcloud + per-object splats placed by mask centroid
    print(f"[3/3] Compose scene")
    glb_bytes, compose_meta = _compose_scene(
        world_points=world_points,
        world_points_conf=world_points_conf,
        canonical_index=canonical_index,
        masks=masks_array,
        manifest_objects=manifest["objects"],
        splat_paths=splat_paths,
    )
    out = OUTPUTS_DIR / "scene.glb"
    out.write_bytes(glb_bytes)
    print(f"Saved {out} ({len(glb_bytes) // 1024} KB)")
    print(f"Compose metadata: {json.dumps(compose_meta, indent=2)}")
    print(f"Total: {time.time() - t0:.1f}s")


# ---------------------------------------------------------------------------
# Archive unpacking + composition
# ---------------------------------------------------------------------------

def _unpack_objects_archive(
    archive_path: Path, extract_dir: Path
) -> tuple[dict[str, Any], np.ndarray, dict[int, Path]]:
    """Open the perception-obj /objects archive. Returns (manifest, masks array,
    {mask_index -> ply_path}). Extracts PLYs to disk under extract_dir."""
    extract_dir.mkdir(parents=True, exist_ok=True)
    splat_paths: dict[int, Path] = {}
    with zipfile.ZipFile(archive_path, "r") as zf:
        manifest = json.loads(zf.read("manifest.json"))
        with zf.open("masks.npz") as mf:
            masks_npz = np.load(io.BytesIO(mf.read()))
            masks_array = masks_npz["masks"]
        for o in manifest["objects"]:
            if o.get("ok") and "splat_filename" in o:
                fname = o["splat_filename"]
                try:
                    data = zf.read(fname)
                    out = extract_dir / fname
                    out.write_bytes(data)
                    splat_paths[o["mask_index"]] = out
                except KeyError:
                    pass
    return manifest, masks_array, splat_paths


def _compose_scene(
    world_points: np.ndarray,
    world_points_conf: np.ndarray,
    canonical_index: int,
    masks: np.ndarray,
    manifest_objects: list[dict[str, Any]],
    splat_paths: dict[int, Path],
    room_scale_meters: float | None = None,
    world_up_axis: str = "y",
    world_up_sign: int = 1,
    world_yaw_deg: float = 0.0,
    world_pitch_deg: float = 0.0,
    world_roll_deg: float = 0.0,
    splat_yaw_deg: float = 0.0,
    splat_pitch_deg: float = 0.0,
    splat_roll_deg: float = 0.0,
) -> tuple[bytes, dict[str, Any]]:
    """Build a single GLB containing:
      - the VGGT point cloud (high-confidence points only)
      - each successfully-reconstructed splat, transformed into the GLB
        world frame.

    Coordinate frames:
      - VGGT outputs points in its own world frame. The user tells us
        which axis of that frame is gravity-up (world_up_axis / sign).
      - SAM 3D outputs splats in some canonical frame (empirically near
        +Y-up but with possible per-object rotation).
      - The output GLB uses glTF +Y-up convention.

    Two layers of rotation, tunable independently:

      WORLD: rotate the entire scene (pointcloud + splat centroids).
        - First, M_vggt2glb maps VGGT's specified up axis to +Y.
        - Then, R_world_yaw rotates the whole scene around +Y so the
          room sits at a sensible default yaw in the viewer.

      SPLAT: rotate every splat's local geometry by yaw/pitch/roll about
        the GLB axes, applied at the splat's local origin (i.e. before
        translation to its world position). Use this to correct any
        residual SAM 3D orientation offset (e.g. all chairs facing the
        wrong way). Order: yaw (+Y) -> pitch (+X) -> roll (+Z), applied
        right-to-left to vertices.

    Args:
        room_scale_meters: if set, treat max(vggt_scene_extent) as this
            many meters and rescale every position and splat-extent
            accordingly. If None, output is in raw VGGT units.
        world_up_axis: one of "x", "y", "z". Which VGGT axis is up.
        world_up_sign: +1 or -1.
        world_yaw_deg: rotation around +Y applied to the whole scene
            AFTER M_vggt2glb. Use to make the room sit upright in the
            viewer's default camera.
        splat_yaw_deg, splat_pitch_deg, splat_roll_deg: rotations applied
            to each splat's local geometry (about the splat's own origin)
            before translation to its world position.

    Returns (glb_bytes, metadata).
    """
    scene = trimesh.Scene()

    # First compute kept VGGT points; defer adding to scene until we know
    # the metric/orientation transforms (so the pointcloud and splats end
    # up in the same frame).
    pts_flat = world_points.reshape(-1, 3)
    conf_flat = world_points_conf.reshape(-1)
    pts_kept = np.zeros((0, 3), dtype=pts_flat.dtype)
    if conf_flat.size:
        threshold = np.percentile(conf_flat, 50.0)
        sel = conf_flat > threshold
        pts_kept = pts_flat[sel]

    placements: list[dict[str, Any]] = []
    placed = 0

    # Canonical pointmap for placing per-object splats.
    if canonical_index >= world_points.shape[0]:
        canonical_pts = None
        canonical_conf = None
    else:
        canonical_pts = world_points[canonical_index]      # (H, W, 3)
        canonical_conf = world_points_conf[canonical_index]  # (H, W)

    # ---- Global calibration (scale) -------------------------------------
    # If room_scale_meters is provided, compute "VGGT units per meter" by
    # equating max(scene_extent_kept) with room_scale_meters. Measured on
    # the same high-confidence points used for the gray cloud to stay
    # consistent.
    vggt_units_per_meter: float | None = None
    if room_scale_meters is not None and room_scale_meters > 0 and pts_kept.size:
        ext = pts_kept.max(axis=0) - pts_kept.min(axis=0)
        if float(ext.max()) > 0:
            vggt_units_per_meter = float(ext.max()) / float(room_scale_meters)

    # ---- Frame conversion (VGGT world -> GLB +Y-up world) ---------------
    # The output GLB must be +Y-up per glTF convention. The user tells us
    # which VGGT axis is gravity-up. We build M_vggt2glb that maps the
    # specified VGGT axis to +Y. This rotation is applied to the gray
    # pointcloud AND to each splat's centroid (positions), so the entire
    # scene ends up +Y-up.
    #
    # The splats themselves are SAM-3D-native +Y-up, which equals
    # GLB-+Y-up, so their orientations DO NOT need this rotation — only
    # their positions do.
    axis_map = {"x": np.array([1.0, 0.0, 0.0]),
                "y": np.array([0.0, 1.0, 0.0]),
                "z": np.array([0.0, 0.0, 1.0])}
    vggt_up = axis_map[world_up_axis.lower()] * float(world_up_sign)
    glb_up = np.array([0.0, 1.0, 0.0])
    glb_x  = np.array([1.0, 0.0, 0.0])
    glb_z  = np.array([0.0, 0.0, 1.0])
    M_vggt2glb_axis = _rotation_aligning(vggt_up, glb_up)        # 4x4
    R_world_yaw   = trimesh.transformations.rotation_matrix(np.radians(world_yaw_deg),   glb_up)
    R_world_pitch = trimesh.transformations.rotation_matrix(np.radians(world_pitch_deg), glb_x)
    R_world_roll  = trimesh.transformations.rotation_matrix(np.radians(world_roll_deg),  glb_z)
    # Full VGGT-frame -> GLB-frame mapping: align up axis, then yaw/pitch/
    # roll the whole scene in GLB. Applied right-to-left to vertices, so
    # axis-alignment happens first, then yaw, then pitch, then roll.
    M_vggt2glb = R_world_roll @ R_world_pitch @ R_world_yaw @ M_vggt2glb_axis

    # Per-splat local rotation: yaw (+Y), pitch (+X), roll (+Z), applied
    # right-to-left to vertices. Acts at the splat's local origin (splats
    # are origin-centered), so this rotates each splat in place before
    # it gets translated to its world centroid.
    R_splat_yaw   = trimesh.transformations.rotation_matrix(np.radians(splat_yaw_deg),   glb_up)
    R_splat_pitch = trimesh.transformations.rotation_matrix(np.radians(splat_pitch_deg), glb_x)
    R_splat_roll  = trimesh.transformations.rotation_matrix(np.radians(splat_roll_deg),  glb_z)
    R_splat_local = R_splat_yaw @ R_splat_pitch @ R_splat_roll

    # ---- Build the (calibrated, oriented) gray pointcloud ---------------
    # The pointcloud is in VGGT world frame; we map it to GLB +Y-up frame
    # via M_vggt2glb. We also rescale to metric units if calibration is set.
    if pts_kept.size:
        pts_kept_world = pts_kept
        if vggt_units_per_meter is not None:
            pts_kept_world = pts_kept_world / vggt_units_per_meter
        # Apply M_vggt2glb to every point. 3x3 part of the homogeneous 4x4.
        R3 = M_vggt2glb[:3, :3]
        pts_kept_world = pts_kept_world @ R3.T
        colors = np.full((pts_kept_world.shape[0], 4),
                         [180, 180, 180, 255], dtype=np.uint8)
        scene.add_geometry(
            trimesh.PointCloud(vertices=pts_kept_world, colors=colors),
            node_name="vggt_pointcloud",
        )

    for obj in manifest_objects:
        if not obj.get("ok"):
            continue
        mask_idx = obj["mask_index"]
        if mask_idx not in splat_paths:
            continue
        mask = masks[mask_idx]
        placement = _estimate_placement(
            mask=mask,
            canonical_pts=canonical_pts,
            canonical_conf=canonical_conf,
        )
        # Compute uniform scale from VGGT-derived extent. SAM 3D outputs
        # splats normalized so their longest native axis = 1.0 (verified
        # empirically across 18 objects: extent max ~1.0 on every PLY,
        # centroid mean ~(0,0,0) with std < 0.04). So scaling the splat
        # by `max(vggt_extent)` makes its longest axis match the longest
        # observed extent of the mask in the room's world frame. This is
        # uniform (not per-axis) to preserve object shape.
        #
        # If `vggt_units_per_meter` is set, we also divide by it so the
        # output is in metric units. Otherwise the scene is in VGGT-native
        # units (not metric, but internally consistent).
        scale: float | None = None
        if placement["valid"]:
            ext = placement.get("extent", [0, 0, 0])
            longest = float(max(ext))
            # Guard against degenerate masks producing ~0 extent. Below
            # ~1cm in VGGT units would scale a unit splat to invisibility;
            # mark such placements invalid for scaling and skip the scale
            # (translation only) rather than collapsing the splat.
            if longest > 0.01:
                scale = longest
                if vggt_units_per_meter is not None:
                    scale = scale / vggt_units_per_meter
            placement["scale"] = scale
        placements.append({
            "label": obj["label"],
            "mask_index": mask_idx,
            "placement": placement,
        })
        try:
            splat_cloud = trimesh.load(str(splat_paths[mask_idx]))
            # Transform order on the origin-centered splat:
            #   1. Scale uniformly (longest axis -> mask extent / cal).
            #   2. Apply per-splat local rotation (yaw/pitch/roll).
            # Then translate to the centroid, after mapping the centroid
            # from VGGT frame to GLB frame (which includes world yaw).
            if scale is not None:
                splat_cloud.apply_scale(scale)
            if (splat_yaw_deg or splat_pitch_deg or splat_roll_deg):
                splat_cloud.apply_transform(R_splat_local)
            if placement["valid"]:
                center = np.asarray(placement["center"], dtype=float)
                if vggt_units_per_meter is not None:
                    center = center / vggt_units_per_meter
                center = M_vggt2glb[:3, :3] @ center
                splat_cloud.apply_translation(center)
            scene.add_geometry(
                splat_cloud,
                node_name=f"obj_{mask_idx:02d}_{_safe(obj['label'])}",
            )
            placed += 1
        except Exception as e:
            placement["compose_error"] = str(e)

    glb_bytes = scene.export(file_type="glb")
    return glb_bytes, {
        "n_objects_in_manifest": len(manifest_objects),
        "n_placed": placed,
        "placements": placements,
        "calibration": {
            "room_scale_meters": room_scale_meters,
            "vggt_units_per_meter": vggt_units_per_meter,
        },
        "orientation": {
            "world_up_axis": world_up_axis,
            "world_up_sign": world_up_sign,
            "world_yaw_deg": world_yaw_deg,
            "world_pitch_deg": world_pitch_deg,
            "world_roll_deg": world_roll_deg,
            "splat_yaw_deg": splat_yaw_deg,
            "splat_pitch_deg": splat_pitch_deg,
            "splat_roll_deg": splat_roll_deg,
        },
    }


def _estimate_placement(
    mask: np.ndarray,
    canonical_pts: np.ndarray | None,
    canonical_conf: np.ndarray | None,
) -> dict[str, Any]:
    """Use VGGT's pointmap on the canonical photo to estimate where the
    segmented object sits in 3D. Returns center, extent, n_points, valid.

    Strategy:
      1. Resize mask to VGGT pointmap resolution (nearest).
      2. Take ALL pointmap points inside the mask (no confidence threshold
         here — for thin/textureless objects like curtains or a ceiling
         fan, strict thresholds drop too many points and the bbox
         collapses to noise).
      3. Robust-clip outliers per axis: keep only points whose coordinates
         fall within the [5th, 95th] percentile band per axis. This
         removes the rare wild VGGT depth outlier without depending on
         confidence being well-calibrated for the object.
      4. Use the highest-confidence inliers (top 50% by canonical_conf)
         to compute the *center*; use the full inlier set for *extent*.
         Center wants precision (where the object is); extent wants
         coverage (how big it is).
    """
    if canonical_pts is None or canonical_conf is None:
        return {"center": [0, 0, 0], "valid": False, "reason": "no_canonical_pointmap"}

    H_v, W_v = canonical_pts.shape[:2]
    mask_resized = np.array(
        Image.fromarray(mask).resize((W_v, H_v), Image.NEAREST)
    ).astype(bool)
    if not mask_resized.any():
        return {"center": [0, 0, 0], "valid": False, "reason": "empty_mask_after_resize"}

    all_pts = canonical_pts[mask_resized]            # (M, 3)
    all_conf = canonical_conf[mask_resized]          # (M,)
    if all_pts.shape[0] == 0:
        return {"center": [0, 0, 0], "valid": False, "reason": "no_points_in_mask"}

    # Per-axis robust clipping: drop the top and bottom 5% on each axis
    # independently. This is cheap and handles the dominant failure mode
    # (a few pixels in the mask happen to land on VGGT-estimated points
    # far from the object surface — typically through-the-window leaks).
    lo = np.percentile(all_pts, 5.0, axis=0)
    hi = np.percentile(all_pts, 95.0, axis=0)
    inlier = np.all((all_pts >= lo) & (all_pts <= hi), axis=1)
    if not inlier.any():
        return {"center": [0, 0, 0], "valid": False, "reason": "no_inliers_after_clipping"}

    inlier_pts = all_pts[inlier]
    inlier_conf = all_conf[inlier]

    # Extent: full robust span.
    extent = inlier_pts.max(axis=0) - inlier_pts.min(axis=0)

    # Center: high-confidence subset of inliers if available, else mean
    # of all inliers. For low-confidence objects (curtains, fan) this
    # falls back to the inlier mean.
    if inlier_conf.size >= 4:
        conf_thresh = np.percentile(inlier_conf, 50.0)
        high = inlier_conf >= conf_thresh
        center_pts = inlier_pts[high] if high.any() else inlier_pts
    else:
        center_pts = inlier_pts
    center = center_pts.mean(axis=0)

    return {
        "center": center.tolist(),
        "extent": extent.tolist(),
        "n_points": int(inlier.sum()),
        "n_points_total_in_mask": int(all_pts.shape[0]),
        "valid": True,
    }


def _rotation_aligning(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Return a 4x4 rotation matrix that rotates unit vector `a` to align
    with unit vector `b`. Uses Rodrigues' formula. Handles the antiparallel
    edge case by rotating 180 degrees around an arbitrary perpendicular."""
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    a = a / (np.linalg.norm(a) + 1e-12)
    b = b / (np.linalg.norm(b) + 1e-12)
    d = float(np.dot(a, b))
    if d > 1 - 1e-9:
        # Parallel: identity.
        return np.eye(4)
    if d < -1 + 1e-9:
        # Antiparallel: pick any perpendicular axis to a, rotate 180.
        # Use the smallest-component basis to avoid degeneracy.
        idx = int(np.argmin(np.abs(a)))
        perp = np.eye(3)[idx]
        perp = perp - a * np.dot(perp, a)
        perp = perp / (np.linalg.norm(perp) + 1e-12)
        return trimesh.transformations.rotation_matrix(np.pi, perp)
    v = np.cross(a, b)
    s = float(np.linalg.norm(v))
    K = np.array([[0, -v[2], v[1]],
                  [v[2], 0, -v[0]],
                  [-v[1], v[0], 0]])
    R3 = np.eye(3) + K + K @ K * ((1 - d) / (s * s + 1e-12))
    R4 = np.eye(4)
    R4[:3, :3] = R3
    return R4


def _safe(label: str) -> str:
    return "".join(c if c.isalnum() else "_" for c in label)[:32]


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

COMMANDS = {
    "geom": cmd_geom,
    "segment": cmd_segment,
    "objects": cmd_objects,
    "scene": cmd_scene,
}


def main() -> None:
    load_dotenv()
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        print(__doc__)
        sys.exit(1)
    COMMANDS[sys.argv[1]]()


if __name__ == "__main__":
    main()
