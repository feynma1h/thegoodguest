"""Scene-level object fusion: one entry per physical object.

The per-frame loop produces observations — the same chair appears in
every keyframe that saw it, each with its own splat and (on LiDAR frames)
its own world placement. Rendering those directly would put N copies of
each object in the room. This pass clusters per-frame observations into
physical objects and fuses their transforms:

What may be fused across observations and what must not be (decision
0065): positions and METRIC extents are physical quantities — the same
across frames — so they fuse (median). Rotations and raw scales are
expressed relative to the observation's own splat frame, and SAM 3D
samples an ARBITRARY canonical frame per reconstruction: the same chair
reconstructed from two frames gets two incompatible local frames, each
with its own compensating layout rotation. Averaging those rotations (or
their raw scales) mixes frames that have nothing to do with each other.
The rotation and scale shipped for a cluster therefore come from the SAME
observation whose splat the cluster renders (the best member).

  * Placed observations (LiDAR depth fits) cluster by label + world-center
    proximity; fused position is the per-axis median; rotation and scale
    are the best member's own.
  * Unplaced observations that carry view rays (ARKIT_ONLY frames)
    cluster by label + ray consistency: a ray joins a cluster if the
    cluster's rays plus it still triangulate with low RMS. Clusters with
    a valid triangulation get their center from the ray intersection
    (metric via the ARKit VIO baseline), scale from the median of
    angular-extent × distance over the member observations (a metric
    size) divided by the BEST member's splat extent, and rotation from
    the best member's layout-derived world rotation.

Each fused object references the single best member's splat (highest
detection score) — the viewer renders one splat per physical object, not
a blend — and the transform it ships is valid for exactly that splat.

Known v1 limitation (deliberate): two same-label objects closer together
than the cluster threshold (default 0.4 m) can merge into one. The
threshold is env-tunable (FUSION_CLUSTER_DIST_M / FUSION_RAY_RMS_M).

Consumers: process_receiver.run_perception (manifest "objects" array).
"""
from __future__ import annotations

import logging
import os
from typing import Any, Optional

import numpy as np

from placement import min_axis_to_vertical_deg
from roomstudio_schemas.placement_math import (
    DegenerateGeometryError,
    triangulate_rays,
)
from roomstudio_schemas.pose_math import quat_to_rotmat

logger = logging.getLogger(__name__)

# A placed observation joins a cluster whose fused center is within this
# many meters (same label required).
_CLUSTER_DIST_M = float(os.environ.get("FUSION_CLUSTER_DIST_M", "0.4"))
# A view ray joins a ray cluster if the cluster still triangulates with an
# RMS perpendicular distance under this bound.
_RAY_RMS_M = float(os.environ.get("FUSION_RAY_RMS_M", "0.3"))


def _collect_observations(frame_results: list[dict]) -> list[dict]:
    obs = []
    for frame in frame_results:
        for entry in frame.get("objects", []):
            if not entry.get("ok"):
                continue
            obs.append({
                "frame_index": frame.get("frame_index"),
                "label": entry.get("label"),
                "score": float(entry.get("score", 0.0)),
                "mask_index": entry.get("mask_index"),
                "splat_gcs_uri": entry.get("splat_gcs_uri"),
                "placement": entry.get("placement") or {},
                "view_ray": entry.get("view_ray"),
            })
    return obs


def _center(o: dict) -> Optional[np.ndarray]:
    wt = o["placement"].get("world_transform")
    if wt is None:
        return None
    return np.asarray(wt["position"], dtype=np.float64)


def _fuse_placed_cluster(members: list[dict], object_id: str) -> dict:
    positions = np.stack([_center(m) for m in members])
    position = np.median(positions, axis=0)
    spread = float(np.linalg.norm(positions - position, axis=1).max()) if len(members) > 1 else 0.0
    best = max(members, key=lambda m: m["score"])
    # Rotation and scale are relative to the best member's own splat frame
    # (canonical frames differ per reconstruction — module docstring), so
    # they ship verbatim from the observation whose splat is rendered.
    best_wt = best["placement"]["world_transform"]
    return {
        "object_id": object_id,
        "label": best["label"],
        "placed": True,
        "method": "depth_fit",
        "splat_gcs_uri": best["splat_gcs_uri"],
        "source": {"frame_index": best["frame_index"], "mask_index": best["mask_index"]},
        "world_transform": {
            "position": [float(c) for c in position],
            "rotation_xyzw": [float(c) for c in best_wt["rotation_xyzw"]],
            "scale": float(best_wt["scale"]),
        },
        "quality": {
            "frames_observed": len(members),
            "cluster_spread_m": spread,
            "min_axis_to_vertical_deg": best["placement"]
            .get("quality", {})
            .get("min_axis_to_vertical_deg"),
            "score": best["score"],
        },
    }


def _try_triangulate(members: list[dict]):
    """Triangulate the view rays of a set of observations, or None.

    Rejects solutions that land behind (or essentially at) any contributing
    camera: rays from a shared origin intersect exactly at that origin, so
    without this check two different objects seen by the same camera would
    'triangulate' perfectly at the camera center."""
    rays = [m["view_ray"] for m in members if m.get("view_ray")]
    if len(rays) < 2:
        return None
    origins = np.array([r["origin"] for r in rays])
    dirs = np.array([r["direction"] for r in rays])
    try:
        center, rms = triangulate_rays(origins, dirs)
    except DegenerateGeometryError:
        return None
    along = ((center - origins) * dirs).sum(axis=1)
    if np.any(along < 0.1):
        return None
    return center, rms


def _has_frame(cluster: list[dict], frame_index) -> bool:
    """One physical object appears at most once per frame — a cluster must
    never take two observations from the same frame_index."""
    return any(m["frame_index"] == frame_index for m in cluster)


def _fuse_ray_cluster(members: list[dict], object_id: str) -> dict:
    best = max(members, key=lambda m: m["score"])
    label = best["label"]
    tri = _try_triangulate(members)
    if tri is None:
        reason = (
            "insufficient_observations" if len(members) < 2 else "triangulation_degenerate"
        )
        return _unplaced_object(members, object_id, reason)
    center, rms = tri

    # Metric extent: angular size × distance per observation, medianed.
    extents = []
    for m in members:
        ray = m.get("view_ray")
        if not ray:
            continue
        dist = float(np.linalg.norm(center - np.asarray(ray["origin"])))
        extents.append(ray["angular_extent_rad"] * dist)
    splat_extent = best["placement"].get("splat_max_extent")
    if not extents or not splat_extent:
        return _unplaced_object(members, object_id, "no_scale_reference")
    scale = float(np.median(extents) / splat_extent)

    # Rotation must pair with the splat actually rendered (best's): each
    # observation's world rotation is relative to its OWN reconstruction's
    # canonical frame, so other members' rotations do not apply to best's
    # splat (module docstring; decision 0065).
    best_rot = best["placement"].get("world_rotation_xyzw")
    if best_rot:
        rotation = [float(c) for c in best_rot]
        rotation_source = "sam3d_layout"
        min_axis_dev = min_axis_to_vertical_deg(quat_to_rotmat(tuple(rotation)))
    else:
        rotation = [0.0, 0.0, 0.0, 1.0]
        rotation_source = "none"
        min_axis_dev = None

    return {
        "object_id": object_id,
        "label": label,
        "placed": True,
        "method": "layout_triangulated",
        "rotation_source": rotation_source,
        "splat_gcs_uri": best["splat_gcs_uri"],
        "source": {"frame_index": best["frame_index"], "mask_index": best["mask_index"]},
        "world_transform": {
            "position": [float(c) for c in center],
            "rotation_xyzw": rotation,
            "scale": scale,
        },
        "quality": {
            "frames_observed": len(members),
            "triangulation_rms_m": float(rms),
            "min_axis_to_vertical_deg": min_axis_dev,
            "score": best["score"],
        },
    }


def _unplaced_object(members: list[dict], object_id: str, reason: str) -> dict:
    best = max(members, key=lambda m: m["score"])
    return {
        "object_id": object_id,
        "label": best["label"],
        "placed": False,
        "method": None,
        "reason": reason,
        "splat_gcs_uri": best["splat_gcs_uri"],
        "source": {"frame_index": best["frame_index"], "mask_index": best["mask_index"]},
        "world_transform": None,
        "quality": {"frames_observed": len(members), "score": best["score"]},
    }


def fuse_scene_objects(frame_results: list[dict]) -> list[dict]:
    """Cluster per-frame observations into fused scene objects.

    Returns the manifest's scene-level "objects" array. Never raises; a
    pathological input degrades to unplaced entries, not a failed scene.
    """
    observations = _collect_observations(frame_results)

    by_label: dict[str, list[dict]] = {}
    for o in observations:
        by_label.setdefault(o["label"] or "", []).append(o)

    fused: list[dict] = []
    counter = 0
    for label in sorted(by_label):
        group = sorted(by_label[label], key=lambda o: -o["score"])
        placed = [o for o in group if o["placement"].get("placed")]
        with_rays = [
            o for o in group
            if not o["placement"].get("placed") and o.get("view_ray")
        ]

        # --- Placed observations: greedy proximity clustering. ---
        clusters: list[list[dict]] = []
        for o in placed:
            c = _center(o)
            joined = False
            for cluster in clusters:
                if _has_frame(cluster, o["frame_index"]):
                    continue
                ref = np.median(np.stack([_center(m) for m in cluster]), axis=0)
                if np.linalg.norm(c - ref) <= _CLUSTER_DIST_M:
                    cluster.append(o)
                    joined = True
                    break
            if not joined:
                clusters.append([o])
        for cluster in clusters:
            fused.append(_fuse_placed_cluster(cluster, f"obj_{counter:03d}"))
            counter += 1

        # --- Ray-only observations: consistency-gated ray clustering. ---
        ray_clusters: list[list[dict]] = []
        for o in with_rays:
            joined = False
            for cluster in ray_clusters:
                if _has_frame(cluster, o["frame_index"]):
                    continue
                candidate = cluster + [o]
                tri = _try_triangulate(candidate)
                if tri is not None and tri[1] <= _RAY_RMS_M:
                    cluster.append(o)
                    joined = True
                    break
            if not joined:
                ray_clusters.append([o])
        # Merge pass: a lone ray can seed a cluster before a compatible one
        # arrives; try merging pairs of clusters once.
        merged = True
        while merged and len(ray_clusters) > 1:
            merged = False
            for i in range(len(ray_clusters)):
                for j in range(i + 1, len(ray_clusters)):
                    candidate = ray_clusters[i] + ray_clusters[j]
                    frames_seen = [m["frame_index"] for m in candidate]
                    if len(frames_seen) != len(set(frames_seen)):
                        continue
                    tri = _try_triangulate(candidate)
                    if tri is not None and tri[1] <= _RAY_RMS_M:
                        ray_clusters[i] = candidate
                        del ray_clusters[j]
                        merged = True
                        break
                if merged:
                    break
        for cluster in ray_clusters:
            fused.append(_fuse_ray_cluster(cluster, f"obj_{counter:03d}"))
            counter += 1

    placed_count = sum(1 for f in fused if f["placed"])
    logger.info(
        "fusion: %d observations -> %d objects (%d placed)",
        len(observations), len(fused), placed_count,
    )
    return fused
