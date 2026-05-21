"""
Measure what's actually in the SAM 3D PLYs and how their native frame
relates to VGGT's world frame. Pure diagnostic — does not modify or
compose anything.

For each PLY:
  - centroid, bbox center, bbox extent (the "native" frame)
  - PCA principal axes (dominant orientation in native frame)
  - extent ratio along each principal axis (is the object elongated?)

Plus, for context:
  - VGGT scene extent and the apparent up-axis (axis of smallest
    height-spread aggregated over confident points)

Run from the repo root:

    python tools/inspect_splats.py
    python tools/inspect_splats.py --splat-dir outputs/objects_extracted
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import trimesh


def _pca_axes(pts: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Return (eigvalues_desc, eigvectors_cols_desc) of the covariance
    of `pts` (N, 3). Sorted by descending eigenvalue."""
    c = pts.mean(axis=0)
    centered = pts - c
    cov = (centered.T @ centered) / max(len(pts) - 1, 1)
    w, v = np.linalg.eigh(cov)  # ascending
    order = np.argsort(w)[::-1]
    return w[order], v[:, order]


def _summarize_splat(path: Path) -> dict:
    pc = trimesh.load(str(path))
    if isinstance(pc, trimesh.Scene):
        # Concatenate any geometry in the scene.
        verts = np.concatenate(
            [g.vertices for g in pc.geometry.values() if hasattr(g, "vertices")],
            axis=0,
        )
    else:
        verts = np.asarray(pc.vertices)

    n = verts.shape[0]
    centroid = verts.mean(axis=0)
    bb_min = verts.min(axis=0)
    bb_max = verts.max(axis=0)
    extent = bb_max - bb_min
    bb_center = (bb_max + bb_min) / 2.0

    w, v = _pca_axes(verts)
    # Eigvalue ratios: spread along each principal axis (in pts^2),
    # convert to spread length by sqrt.
    spreads = np.sqrt(np.clip(w, 0, None))

    return {
        "n_vertices": int(n),
        "centroid": centroid.tolist(),
        "bbox_min": bb_min.tolist(),
        "bbox_max": bb_max.tolist(),
        "bbox_center": bb_center.tolist(),
        "extent": extent.tolist(),
        "pca_spreads": spreads.tolist(),
        "pca_axes_cols": v.tolist(),  # columns are eigvectors, descending
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--splat-dir", type=Path, default=Path("outputs/scene_objects_extracted")
    )
    ap.add_argument(
        "--pointmap", type=Path, default=Path("outputs/pointmap.npz"),
        help="Optional. If present, also print VGGT scene context."
    )
    ap.add_argument(
        "--manifest", type=Path, default=Path("outputs/scene_objects.json"),
        help="Optional. If present, attach labels to each PLY by mask_index."
    )
    args = ap.parse_args()

    if not args.splat_dir.exists():
        print(f"ERROR: splat dir does not exist: {args.splat_dir}")
        return

    # Pull label mapping if available.
    label_for: dict[int, str] = {}
    if args.manifest.exists():
        manifest = json.loads(args.manifest.read_text())
        for o in manifest.get("objects", []):
            label_for[int(o.get("mask_index", -1))] = o.get("label", "?")

    plys = sorted(args.splat_dir.glob("*.ply"))
    if not plys:
        print(f"No PLYs in {args.splat_dir}")
        return

    print(f"=== Per-splat native frame ({len(plys)} files) ===")
    print(
        f"{'file':<32} {'n':>7} "
        f"{'centroid':<26} {'extent':<22} {'pca_spreads':<22}"
    )

    # Aggregate stats across all splats — useful to spot conventions.
    all_centroids = []
    all_extents = []
    all_principal_axes = []  # the dominant (largest-eigvalue) axis per object
    all_minor_axes = []      # the smallest-eigvalue axis per object

    for p in plys:
        s = _summarize_splat(p)
        # Parse leading index from filename: "00_ceiling-fan.ply" -> 0
        try:
            idx = int(p.stem.split("_", 1)[0])
        except ValueError:
            idx = -1
        label = label_for.get(idx, p.stem)

        c = s["centroid"]
        e = s["extent"]
        sp = s["pca_spreads"]
        print(
            f"{p.name[:32]:<32} {s['n_vertices']:>7} "
            f"({c[0]:+.3f},{c[1]:+.3f},{c[2]:+.3f})    "
            f"({e[0]:.3f},{e[1]:.3f},{e[2]:.3f})  "
            f"({sp[0]:.3f},{sp[1]:.3f},{sp[2]:.3f})"
        )

        all_centroids.append(c)
        all_extents.append(e)
        # PCA axes returned as columns of v, descending. Largest principal
        # axis is v[:, 0]; smallest is v[:, 2].
        axes = np.array(s["pca_axes_cols"])
        all_principal_axes.append(axes[:, 0])
        all_minor_axes.append(axes[:, 2])

    cents = np.array(all_centroids)
    exts = np.array(all_extents)
    print()
    print("=== Aggregate across splats ===")
    print(
        f"  centroid  mean=({cents.mean(0)[0]:+.3f},{cents.mean(0)[1]:+.3f},{cents.mean(0)[2]:+.3f})  "
        f"std=({cents.std(0)[0]:.3f},{cents.std(0)[1]:.3f},{cents.std(0)[2]:.3f})"
    )
    print(
        f"  extent    mean=({exts.mean(0)[0]:.3f},{exts.mean(0)[1]:.3f},{exts.mean(0)[2]:.3f})  "
        f"max =({exts.max(0)[0]:.3f},{exts.max(0)[1]:.3f},{exts.max(0)[2]:.3f})  "
        f"min =({exts.min(0)[0]:.3f},{exts.min(0)[1]:.3f},{exts.min(0)[2]:.3f})"
    )
    print(
        "  hint: if centroid mean is near (0,0,0), splats are origin-centered. "
        "If extent max is roughly 1.0, splats are unit-bbox normalized."
    )

    # For ceiling-fan/plant/cabinet etc., the *minor* axis of PCA is often
    # the object's vertical axis (fan is wide+flat, plant is tall, cabinet
    # is taller-than-deep). Print the minor-axis distribution; if SAM 3D
    # has a consistent up convention, all minor axes will cluster near
    # one cardinal direction.
    minors = np.array(all_minor_axes)
    # Flip sign ambiguity: eigenvector sign is arbitrary. Canonicalize so
    # the largest |component| is positive, then look at distribution.
    minors_canon = minors * np.sign(minors[np.arange(len(minors)),
                                          np.argmax(np.abs(minors), axis=1)])[:, None]
    print()
    print("=== PCA minor-axis distribution (which axis is the 'flat'/thin one?) ===")
    print(f"  axis 0 (X)  |mean|={np.abs(minors_canon[:, 0]).mean():.3f}")
    print(f"  axis 1 (Y)  |mean|={np.abs(minors_canon[:, 1]).mean():.3f}")
    print(f"  axis 2 (Z)  |mean|={np.abs(minors_canon[:, 2]).mean():.3f}")
    print(
        "  hint: a dominant axis here means SAM 3D outputs in a consistent up "
        "convention. If all three are ~equal, objects come out in arbitrary "
        "orientations and rotation must be derived per-object."
    )

    # Per-object: which axis is "thinnest" relative to the largest? Print
    # the ratio for each object so we can see e.g. ceiling-fan having one
    # axis much smaller than the others (it's flat).
    print()
    print("=== Per-object thin-axis (smallest extent / largest extent) ===")
    print(f"{'file':<32} {'thin_axis':>9} {'ratio':>6}")
    for p, e in zip(plys, exts):
        thin = int(np.argmin(e))
        ratio = float(e[thin]) / max(float(e.max()), 1e-9)
        print(f"{p.name[:32]:<32} {'XYZ'[thin]:>9} {ratio:>6.3f}")

    # VGGT scene context — to compare splat extents against the metric
    # scale of the room.
    if args.pointmap.exists():
        print()
        print(f"=== VGGT pointmap context ({args.pointmap}) ===")
        npz = np.load(args.pointmap)
        wp = npz["world_points"]
        wc = npz["world_points_conf"]
        pts = wp.reshape(-1, 3)
        # High-confidence points only.
        thresh = np.percentile(wc, 50)
        sel = wc.reshape(-1) > thresh
        kept = pts[sel]
        if kept.size:
            mn, mx = kept.min(0), kept.max(0)
            ext = mx - mn
            print(f"  world_points shape: {wp.shape}")
            print(
                f"  scene extent (kept conf>p50): "
                f"({ext[0]:.2f}, {ext[1]:.2f}, {ext[2]:.2f})  meters?"
            )
            print(
                f"  scene bbox: "
                f"x=[{mn[0]:+.2f}, {mx[0]:+.2f}]  "
                f"y=[{mn[1]:+.2f}, {mx[1]:+.2f}]  "
                f"z=[{mn[2]:+.2f}, {mx[2]:+.2f}]"
            )
            # Apparent up: which axis has the smallest extent? Rooms are
            # usually wider-and-deeper than tall.
            thin_axis = int(np.argmin(ext))
            print(
                f"  smallest-extent axis: {'XYZ'[thin_axis]}  "
                f"(rooms are usually wider+deeper than tall, so this is a "
                f"weak hint at VGGT's up-axis)"
            )
        else:
            print("  (no confident points)")
    else:
        print()
        print(f"(no pointmap at {args.pointmap}; skipping VGGT context)")


if __name__ == "__main__":
    main()
