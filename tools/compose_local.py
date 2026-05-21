"""
Local scene composition harness. Reads cached artifacts from disk and
runs the same _compose_scene / _estimate_placement that cmd_scene uses,
without touching the network or any GPU.

Run from the repo root, after the four input files exist:

    outputs/pointmap.npz           (from tools/fetch_pointmap.py)
    outputs/masks.npz              (gsutil cp from gs://...{SHA}/masks.npz)
    outputs/scene_objects.json     (already there if cmd_scene has run, or
                                    gsutil cp from gs://...{SHA}/objects.json)
    outputs/scene_objects_extracted/{NN}_{label}.ply
                                   (already downloaded)

Then:

    python tools/compose_local.py

Writes outputs/scene_local.glb and prints placement metadata. Iterate
on _compose_scene / _estimate_placement in tools/call_perception.py;
re-run this script. No server roundtrip, no GPU.

Override paths with CLI args if you want to A/B different inputs:

    python tools/compose_local.py \
        --pointmap outputs/pointmap.npz \
        --masks outputs/masks.npz \
        --manifest outputs/scene_objects.json \
        --splat-dir outputs/scene_objects_extracted \
        --out outputs/scene_local.glb \
        --canonical-index 0
"""
from __future__ import annotations

import argparse
import io
import json
import sys
from pathlib import Path

import numpy as np

# Reuse the actual composition functions — do not duplicate them here.
# This guarantees the local harness exercises exactly the same code path
# as cmd_scene.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from call_perception import _compose_scene, _safe  # noqa: E402


def _resolve_splat_paths(
    manifest_objects: list[dict],
    splat_dir: Path,
) -> dict[int, Path]:
    """Find the local PLY for each ok object. Returns {mask_index -> Path}.

    Match strategy: prefer the filename the manifest specifies in
    splat_gcs_uri (basename), fall back to the {NN}_{safe_label}.ply
    convention that _download_splats writes.
    """
    out: dict[int, Path] = {}
    for o in manifest_objects:
        if not o.get("ok"):
            continue
        mask_idx = o["mask_index"]
        candidates: list[Path] = []

        uri = o.get("splat_gcs_uri", "")
        if uri:
            candidates.append(splat_dir / Path(uri).name)

        safe = o["label"].replace(" ", "-").replace("/", "-")
        candidates.append(splat_dir / f"{mask_idx:02d}_{safe}.ply")
        candidates.append(splat_dir / f"{mask_idx:02d}_{_safe(o['label'])}.ply")

        for c in candidates:
            if c.exists():
                out[mask_idx] = c
                break
        else:
            print(
                f"  WARN: no local splat for mask_index={mask_idx} "
                f"label={o['label']!r}; tried {[str(c) for c in candidates]}",
                file=sys.stderr,
            )
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pointmap", type=Path, default=Path("outputs/pointmap.npz"))
    ap.add_argument("--masks", type=Path, default=Path("outputs/masks.npz"))
    ap.add_argument("--manifest", type=Path, default=Path("outputs/scene_objects.json"))
    ap.add_argument("--splat-dir", type=Path, default=Path("outputs/scene_objects_extracted"))
    ap.add_argument("--out", type=Path, default=Path("outputs/scene_local.glb"))
    ap.add_argument("--canonical-index", type=int, default=0)
    ap.add_argument(
        "--room-scale-meters", type=float, default=None,
        help="If set, treat max(vggt_scene_extent) as this many meters. "
             "Output is then in metric units. Without this, output is in "
             "raw VGGT units (internally consistent but not metric)."
    )
    ap.add_argument(
        "--up-axis", type=str, default="y", choices=["x", "y", "z"],
        help="Which VGGT axis is gravity-up. Default 'y'. Try 'z' or '-' "
             "variants if objects are 'lying on the floor' in the viewer."
    )
    ap.add_argument(
        "--up-sign", type=int, default=1, choices=[1, -1],
        help="Sign of the up axis (+1 or -1). Default +1."
    )
    ap.add_argument(
        "--world-yaw-deg", type=float, default=0.0,
        help="Rotate the entire scene around GLB +Y by this many degrees."
    )
    ap.add_argument(
        "--world-pitch-deg", type=float, default=0.0,
        help="Rotate the entire scene around GLB +X by this many degrees."
    )
    ap.add_argument(
        "--world-roll-deg", type=float, default=0.0,
        help="Rotate the entire scene around GLB +Z by this many degrees."
    )
    ap.add_argument(
        "--splat-yaw-deg", type=float, default=0.0,
        help="Rotate every splat in place around GLB +Y. Use to correct "
             "splat 'facing' direction."
    )
    ap.add_argument(
        "--splat-pitch-deg", type=float, default=0.0,
        help="Rotate every splat in place around GLB +X."
    )
    ap.add_argument(
        "--splat-roll-deg", type=float, default=0.0,
        help="Rotate every splat in place around GLB +Z."
    )
    args = ap.parse_args()

    missing = [p for p in (args.pointmap, args.masks, args.manifest) if not p.exists()]
    if missing:
        print(f"ERROR: missing input files: {[str(p) for p in missing]}")
        print("See module docstring for how to populate them.")
        sys.exit(1)
    if not args.splat_dir.exists():
        print(f"ERROR: splat dir does not exist: {args.splat_dir}")
        sys.exit(1)

    print(f"Loading pointmap from {args.pointmap}")
    npz_geom = np.load(args.pointmap)
    world_points = npz_geom["world_points"]
    world_points_conf = npz_geom["world_points_conf"]
    print(
        f"  world_points shape  {world_points.shape} dtype {world_points.dtype}"
    )
    print(
        f"  conf shape          {world_points_conf.shape}, "
        f"range [{float(world_points_conf.min()):.3f}, "
        f"{float(world_points_conf.max()):.3f}]"
    )
    pts_flat = world_points.reshape(-1, 3)
    print(
        f"  scene extent        "
        f"x=[{float(pts_flat[:,0].min()):.2f}, {float(pts_flat[:,0].max()):.2f}] "
        f"y=[{float(pts_flat[:,1].min()):.2f}, {float(pts_flat[:,1].max()):.2f}] "
        f"z=[{float(pts_flat[:,2].min()):.2f}, {float(pts_flat[:,2].max()):.2f}]"
    )

    print(f"Loading masks from {args.masks}")
    npz_masks = np.load(args.masks)
    masks = npz_masks["masks"]
    print(f"  masks shape         {masks.shape} dtype {masks.dtype}")

    print(f"Loading manifest from {args.manifest}")
    manifest = json.loads(args.manifest.read_text())
    manifest_objects = manifest["objects"]
    n_ok = sum(1 for o in manifest_objects if o.get("ok"))
    print(f"  {n_ok}/{len(manifest_objects)} ok objects in manifest")

    print(f"Resolving splat files in {args.splat_dir}")
    splat_paths = _resolve_splat_paths(manifest_objects, args.splat_dir)
    print(f"  found {len(splat_paths)} local PLYs")

    if args.canonical_index >= world_points.shape[0]:
        print(
            f"WARN: canonical_index={args.canonical_index} >= N={world_points.shape[0]}; "
            f"_estimate_placement will return valid=False for all objects."
        )

    print(f"Composing -> {args.out}")
    glb_bytes, compose_meta = _compose_scene(
        world_points=world_points,
        world_points_conf=world_points_conf,
        canonical_index=args.canonical_index,
        masks=masks,
        manifest_objects=manifest_objects,
        splat_paths=splat_paths,
        room_scale_meters=args.room_scale_meters,
        world_up_axis=args.up_axis,
        world_up_sign=args.up_sign,
        world_yaw_deg=args.world_yaw_deg,
        world_pitch_deg=args.world_pitch_deg,
        world_roll_deg=args.world_roll_deg,
        splat_yaw_deg=args.splat_yaw_deg,
        splat_pitch_deg=args.splat_pitch_deg,
        splat_roll_deg=args.splat_roll_deg,
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_bytes(glb_bytes)
    print(f"Saved {args.out} ({len(glb_bytes) // 1024} KB)")

    print()
    print("=== Calibration / orientation ===")
    cal = compose_meta.get("calibration", {})
    ori = compose_meta.get("orientation", {})
    print(f"  room_scale_meters:    {cal.get('room_scale_meters')}")
    print(f"  vggt_units_per_meter: {cal.get('vggt_units_per_meter')}")
    print(f"  world_up_axis:        {ori.get('world_up_axis')}")
    print(f"  world_up_sign:        {ori.get('world_up_sign')}")
    print(f"  world_yaw_deg:        {ori.get('world_yaw_deg')}")
    print(f"  world_pitch_deg:      {ori.get('world_pitch_deg')}")
    print(f"  world_roll_deg:       {ori.get('world_roll_deg')}")
    print(f"  splat_yaw_deg:        {ori.get('splat_yaw_deg')}")
    print(f"  splat_pitch_deg:      {ori.get('splat_pitch_deg')}")
    print(f"  splat_roll_deg:       {ori.get('splat_roll_deg')}")

    print()
    print("=== Placement metadata ===")
    print(f"n_objects_in_manifest: {compose_meta['n_objects_in_manifest']}")
    print(f"n_placed:              {compose_meta['n_placed']}")
    print()
    print(f"{'idx':>3} {'label':<16} {'valid':<5} {'n_pts':>7} {'scale':>6} "
          f"{'center (x,y,z)':<28} {'extent (x,y,z)':<28} reason")
    for p in compose_meta["placements"]:
        pl = p["placement"]
        center = pl.get("center", [0, 0, 0])
        extent = pl.get("extent", [0, 0, 0])
        scale = pl.get("scale")
        scale_s = f"{scale:.2f}" if scale is not None else "-"
        center_s = f"({center[0]:+.2f},{center[1]:+.2f},{center[2]:+.2f})"
        if "extent" in pl:
            extent_s = f"({extent[0]:.2f},{extent[1]:.2f},{extent[2]:.2f})"
        else:
            extent_s = "-"
        reason = pl.get("reason", "") or pl.get("compose_error", "")
        n_pts = pl.get("n_points", 0)
        print(
            f"{p['mask_index']:>3} {p['label'][:16]:<16} "
            f"{str(pl.get('valid', False)):<5} {n_pts:>7} {scale_s:>6} "
            f"{center_s:<28} {extent_s:<28} {reason}"
        )


if __name__ == "__main__":
    main()
