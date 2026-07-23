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
detection score, or — under refinement, see below — the reprojection
instrument's score) — the viewer renders one splat per physical object,
not a blend — and the transform it ships is valid for exactly that splat.

Known v1 limitation (deliberate, legacy path only — see below):
two same-label objects closer together than the cluster threshold
(default 0.4 m) can merge into one. The threshold is env-tunable
(FUSION_CLUSTER_DIST_M / FUSION_RAY_RMS_M).

--- Placement-quality refinement (decision 0067) ---------------------------

Everything above is the LEGACY algorithm, preserved verbatim as the
fallback: it runs unchanged whenever no RefinementContext is supplied, or
PLACEMENT_REFINE=0 (the rollback lever — must reproduce today's manifests
byte-for-byte). When a RefinementContext IS supplied and PLACEMENT_REFINE
is not "0", fusion additionally:

  1. Dedups same-frame same-label observations whose masks are a "mutual
     singleton" nested pair (intersection-over-smaller >=
     PLACEMENT_DEDUP_CONTAINMENT, and neither mask overlaps any THIRD
     same-label mask in that frame — a mask containing multiple disjoint
     children is a coarse parent region, not a duplicate detection, and
     must not absorb its children). Runs BEFORE clustering, so a
     duplicate detection never gets the chance to fork a cluster via the
     frame-uniqueness guard.
  2. Relaxes the ray-cluster merge pass's "no shared frames" veto: two
     clusters sharing a frame may still merge if that frame's two masks
     are themselves mutual-singleton-consistent (the same test as dedup);
     genuinely disjoint same-frame masks still refuse the merge.
  3. Adds a footprint-agreement join test (project the cluster's
     provisional volume into a candidate's frame; require soft-containment
     agreement) alongside the existing RMS/proximity gate — a second,
     photometrically-grounded signal for objects too large for centroid
     triangulation to serve well.
  4. Runs a bounded multi-view silhouette fit (reproject.fit_silhouette)
     for >=2-view ray clusters, refining (scale, translation) — rotation
     stays fixed from the best member. Ships only if it beats the
     triangulated init's tier-1 score.
  5. Resolves in-plane ambiguity for planar splats (reproject.is_planar)
     by scoring 4 candidates 90 degrees apart about the object's own
     normal; ships the winner only with a clear margin.
  6. Flags (never auto-corrects) a materially-better-scoring 180-about-
     view-axis "mirrored twin" of the shipped rotation.
  7. Re-selects the best member by the reprojection instrument's combined
     score for depth_fit clusters ONLY (detection score becomes the
     tiebreak); ray clusters keep detection-score selection — a ray
     member has no complete per-member transform of its own, so
     instrument-ranking those members isn't well-defined yet (see
     _reselect_best_placed_member's docstring for the full rationale).
  8. Emits `reprojection_score`, `position_source`, `constraints_applied`,
     `in_plane_resolved`, `sign_flag`, `extent_m_sorted` on every refined
     PLACED object, and `deduped_observations` on every object.
  9. Places single-view objects that can't triangulate against MEASURED
     room planes (decision 0067 chunk D). An unplaced single-member ray
     cluster of a floor/wall-mapped class (contact_priors) gets a contact-
     prior transform — bottom-on-the-detected-floor or ray-onto-a-detected-
     wall — which ships only if it reprojects onto the object's own mask
     (the evidence gate). No planes in the bundle → inert; the object stays
     `insufficient_observations` and the rest of refinement is unchanged.
 10. Applies a room-sanity gate to every PLACED object (the triangulated /
     silhouette / depth_fit path — NOT chunk D's contact placements, which
     are self-gated against a measured surface). A placement whose position
     lands OUTSIDE the measured room (beyond the detected floor rectangle +
     margin, below the floor, or above the wall top), whose physical size is
     implausible, or whose class the shell already renders as a structural
     opening (door/window — a free splat mid-room is double-wrong) is
     demoted to unplaced with an explicit reason rather than rendered as a
     guessed transform. This is the "never emit a guessed transform" rule
     (0052/0067) applied to triangulation blow-ups — the floating mirror,
     the 5 cm speck, the mid-room door. The outside-room half needs measured
     planes and is inert without them (the degrade lock); the class/scale
     halves need no geometry.

Refinement is CPU-only, bounded (fixed iteration budgets, no RNG —
identical inputs always produce identical manifests) and budget-aware
when ctx.budget is supplied: skipped whole up front without slack, and
halted between objects if the budget drains mid-pass (recorded scene-
level as refinement_skipped) — see fuse_scene_objects_with_meta.
The per-frame cache contract is untouched: everything here reads masks /
splats / poses that already exist; nothing new is written per frame.

Consumers: process_receiver.run_perception (manifest "objects" array +
sampling.refinement_skipped).
"""
from __future__ import annotations

import logging
import os
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Optional

import contact_priors
import numpy as np
import reproject
from placement import min_axis_to_vertical_deg
from roomstudio_schemas.placement_math import (
    DegenerateGeometryError,
    MaskEvidence,
    mask_containment,
    prepare_mask,
    robust_cloud_stats,
    triangulate_rays,
)
from roomstudio_schemas.pose_math import pose_quat, quat_to_rotmat

logger = logging.getLogger(__name__)

# A placed observation joins a cluster whose fused center is within this
# many meters (same label required).
_CLUSTER_DIST_M = float(os.environ.get("FUSION_CLUSTER_DIST_M", "0.4"))
# A view ray joins a ray cluster if the cluster still triangulates with an
# RMS perpendicular distance under this bound.
_RAY_RMS_M = float(os.environ.get("FUSION_RAY_RMS_M", "0.3"))

# --- Refinement (decision 0067) env knobs -----------------------------------
_DEDUP_CONTAINMENT = float(os.environ.get("PLACEMENT_DEDUP_CONTAINMENT", "0.8"))
_FOOTPRINT_MIN = float(os.environ.get("PLACEMENT_FOOTPRINT_MIN", "0.5"))
_INPLANE_MARGIN = float(os.environ.get("PLACEMENT_INPLANE_MARGIN", "0.03"))
_SIGNFLAG_MARGIN = float(os.environ.get("PLACEMENT_SIGNFLAG_MARGIN", "0.03"))
_REFINE_MIN_REMAINING_S = float(os.environ.get("PLACEMENT_REFINE_MIN_REMAINING_S", "20"))
# A single-view contact-prior placement (decision 0067 chunk D) ships only
# if the proposed transform reprojects onto the object's OWN mask at least
# this well (tier-1 soft-IoU). The prior closes an under-determined DOF
# against a measured surface; this gate keeps it from ever emitting a
# transform the pixels don't support ("a guessed transform is never
# emitted", carried through priors). One-capture-calibrated placeholder like
# the other PLACEMENT_* knobs.
_SINGLE_VIEW_MIN_TIER1 = float(os.environ.get("PLACEMENT_SINGLE_VIEW_MIN_TIER1", "0.1"))

# --- Room-sanity gate (refinement lock 10) env knobs ------------------------
# A placed object's center may sit this far outside the detected floor
# rectangle (XZ) and still count as in-room — objects near a wall have
# centers on the floor boundary; a wall-mounted object's center sits ON the
# wall. Generous enough to keep edge furniture, far tighter than the metres a
# triangulation blow-up lands out (the reference mirror was 2.24 m beyond the
# floor). One-capture-calibrated placeholder like the other PLACEMENT_* knobs.
_ROOM_MARGIN_M = float(os.environ.get("PLACEMENT_ROOM_MARGIN_M", "0.5"))
# Vertical slack below the floor / above the wall top before a center is
# "outside" the room. An object center is above the floor by ~half its height,
# so the below-floor test only catches placements that went genuinely
# subterranean; the above-top test catches ceiling-punching blow-ups.
_ROOM_VERTICAL_MARGIN_M = float(os.environ.get("PLACEMENT_ROOM_VERTICAL_MARGIN_M", "0.3"))
# Physical-size plausibility on the largest object extent (extent_m_sorted[0]).
# Nothing in a home room is larger than a few metres across its biggest axis,
# and a whole object under a few cm is a collapsed reconstruction (the
# reference artwork rendered as a 5 cm speck). Needs no room geometry.
_MAX_EXTENT_M = float(os.environ.get("PLACEMENT_MAX_EXTENT_M", "5.0"))
_MIN_EXTENT_M = float(os.environ.get("PLACEMENT_MIN_EXTENT_M", "0.08"))
# SAM object classes the room SHELL already renders as structural openings:
# door/window are ARKit plane-anchor classifications AND SAM labels — a door
# is a wall_NN opening, not a free splat floating in the room. Never
# FREE-place (triangulate) these; a measured wall-contact placement (chunk D)
# is exempt (it sits on the actual wall, not mid-room). Env-overridable.
_SHELL_OPENING_CLASSES = frozenset(
    s.strip().lower()
    for s in os.environ.get("PLACEMENT_SHELL_OPENING_CLASSES", "door,window").split(",")
    if s.strip()
)
# Placements produced by chunk D's measured-surface contact priors — exempt
# from the room-sanity gate (they are placed ON the measured floor/wall by
# construction and carry their own bounds + evidence gates).
_CONTACT_POSITION_SOURCES = frozenset(
    ("single_view_floor_contact", "single_view_wall_contact")
)


def _refinement_enabled() -> bool:
    return os.environ.get("PLACEMENT_REFINE", "1") == "1"


# -----------------------------------------------------------------------------
# Refinement context: the IO seam. Fusion never touches GCS directly — the
# caller (process_receiver.py, or a test) supplies plain accessor callables.
# -----------------------------------------------------------------------------

@dataclass
class RefinementContext:
    """Fusion-time data access for decision 0067's refinement pass.

    get_camera(frame_index) -> (pose, intrinsics) | None
    get_mask_stack(frame_index) -> (N, H, W) bool | None — this frame's
        full detection-order mask stack (masks.npz), fetched once and
        reused for every observation in that frame.
    get_splat(splat_gcs_uri) -> (M, 3) float64 local-frame points | None
    get_appearance(splat_gcs_uri) -> reproject.SplatAppearance | None —
        optional; absence degrades every tier-2 use to tier-1-only.
    get_rgb(frame_index) -> (H, W, 3) RGB at mask resolution | None —
        optional, same degrade. uint8 or float both work (tier 2's NCC is
        intensity-scale-invariant), so callers can cache the small form.
    get_room_planes() -> contact_priors.RoomPlanes | None — optional; the
        measured floor + walls (parsed once via room_planes), used for
        single-view contact-prior placement (decision 0067 chunk D). Absent
        or empty (no plane anchors in the bundle) → priors inert, single-
        view objects stay insufficient_observations (the degrade lock).
    budget: object exposing .remaining() -> float (seconds), or None for
        no limit (e.g. tests). Refinement is skipped scene-wide if
        remaining() < min_remaining_s when fusion starts, and stops
        refining FURTHER objects if the budget drains below that line
        mid-pass (each object is either fully refined or fully legacy —
        never half-refined; see fuse_scene_objects_with_meta).
    """
    get_camera: Callable[[int], Optional[tuple]]
    get_mask_stack: Callable[[int], Optional[np.ndarray]]
    get_splat: Callable[[str], Optional[np.ndarray]]
    get_appearance: Optional[Callable[[str], Optional[reproject.SplatAppearance]]] = None
    get_rgb: Optional[Callable[[int], Optional[np.ndarray]]] = None
    get_room_planes: Optional[Callable[[], Any]] = None
    budget: Optional[Any] = None
    min_remaining_s: float = _REFINE_MIN_REMAINING_S
    _evidence_cache: dict = field(default_factory=dict, repr=False)

    def mask_for(self, frame_index, mask_index) -> Optional[np.ndarray]:
        if mask_index is None:
            return None
        stack = self.get_mask_stack(frame_index)
        if stack is None or mask_index >= stack.shape[0]:
            return None
        return stack[mask_index]

    def evidence_for(self, frame_index, mask_index) -> Optional[MaskEvidence]:
        """mask_for + prepare_mask, memoized — every scoring path hits the
        same handful of (frame, mask) pairs dozens of times per pass, and
        the summed-area table build is the expensive part of each."""
        key = (frame_index, mask_index)
        if key not in self._evidence_cache:
            mask = self.mask_for(frame_index, mask_index)
            self._evidence_cache[key] = None if mask is None else prepare_mask(mask)
        return self._evidence_cache[key]


def _budget_allows(ctx: Optional[RefinementContext]) -> bool:
    if ctx is None or ctx.budget is None:
        return True
    return ctx.budget.remaining() >= ctx.min_remaining_s


# -----------------------------------------------------------------------------
# Shared observation helpers (legacy + refined paths)
# -----------------------------------------------------------------------------

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


def _has_frame(cluster: list[dict], frame_index) -> bool:
    """One physical object appears at most once per frame — a cluster must
    never take two observations from the same frame_index."""
    return any(m["frame_index"] == frame_index for m in cluster)


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


# -----------------------------------------------------------------------------
# Legacy fusion (unchanged) — the PLACEMENT_REFINE=0 / no-ctx fallback
# -----------------------------------------------------------------------------

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


def _fuse_scene_objects_legacy(frame_results: list[dict]) -> list[dict]:
    """The original (pre-0067) algorithm, untouched. This is
    PLACEMENT_REFINE=0's bit-parity target and the no-ctx fallback."""
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


# -----------------------------------------------------------------------------
# Refinement lock 1: same-frame duplicate-detection dedup
# -----------------------------------------------------------------------------

def _dedup_same_frame(observations: list[dict], ctx: RefinementContext) -> tuple[list[dict], list[dict]]:
    """Absorb same-frame same-label duplicate detections before clustering.

    A pair (i, j) is a duplicate detection only if it is a MUTUAL
    singleton: i's only >=threshold containment match in this frame is j,
    and vice versa. A mask containing multiple mutually-disjoint same-
    label children (a coarse parent region — e.g. a "doorway" mask that
    happens to contain two genuinely separate doors) fails this test for
    every child and is left alone, preserving the "disjoint same-label
    masks are different objects" invariant the legacy frame-uniqueness
    guard also protects.
    """
    by_frame: dict[Any, list[dict]] = {}
    for o in observations:
        by_frame.setdefault(o["frame_index"], []).append(o)

    keep: list[dict] = []
    records: list[dict] = []
    for frame_index, group in by_frame.items():
        if len(group) < 2:
            keep.extend(group)
            continue
        masks = [ctx.mask_for(frame_index, o.get("mask_index")) for o in group]
        if any(m is None for m in masks):
            keep.extend(group)
            continue
        n = len(group)
        containment = [[0.0] * n for _ in range(n)]
        for i in range(n):
            for j in range(n):
                if i != j:
                    containment[i][j] = mask_containment(masks[i], masks[j])
        neighbors = [
            [j for j in range(n) if j != i and containment[i][j] >= _DEDUP_CONTAINMENT]
            for i in range(n)
        ]
        absorbed = [False] * n
        for i in range(n):
            if len(neighbors[i]) != 1:
                continue
            j = neighbors[i][0]
            if i >= j or neighbors[j] != [i]:
                continue  # only a clean, mutual, singleton pair dedups
            lo, hi = (i, j) if group[i]["score"] <= group[j]["score"] else (j, i)
            absorbed[lo] = True
            records.append({
                "frame_index": frame_index,
                "kept_mask_index": group[hi]["mask_index"],
                "absorbed_mask_index": group[lo]["mask_index"],
                "containment": containment[lo][hi],
            })
        keep.extend(group[k] for k in range(n) if not absorbed[k])
    return keep, records


# -----------------------------------------------------------------------------
# Refinement lock 1(b): footprint-based join / merge
# -----------------------------------------------------------------------------

def _provisional_ray_volume(cluster: list[dict], ctx: RefinementContext):
    """Best-effort (splat_local_points, rotation_xyzw, translation, scale)
    for a ray cluster's CURRENT members — the same recipe _fuse_ray_cluster
    uses, computed early so a candidate frame can be footprint-tested
    against it. None if the cluster can't yet support one (fewer than 2
    triangulatable members, or the splat/rotation aren't available)."""
    tri = _try_triangulate(cluster)
    if tri is None:
        return None
    center, _rms = tri
    best = max(cluster, key=lambda m: m["score"])
    rot = best["placement"].get("world_rotation_xyzw")
    if not rot:
        return None
    splat = ctx.get_splat(best["splat_gcs_uri"])
    if splat is None:
        return None
    extents = []
    for m in cluster:
        ray = m.get("view_ray")
        if not ray:
            continue
        dist = float(np.linalg.norm(center - np.asarray(ray["origin"])))
        extents.append(ray["angular_extent_rad"] * dist)
    splat_extent = best["placement"].get("splat_max_extent")
    if not extents or not splat_extent:
        return None
    scale = float(np.median(extents) / splat_extent)
    return splat, rot, center, scale


def _footprint_agrees(volume, frame_index, mask_index, ctx: RefinementContext, threshold: float) -> bool:
    if volume is None:
        return False
    splat, rot, translation, scale = volume
    cam = ctx.get_camera(frame_index)
    evidence = ctx.evidence_for(frame_index, mask_index)
    if cam is None or evidence is None:
        return False
    pose, intrinsics = cam
    world_pts = reproject.transform_points(splat, rot, translation, scale)
    score = reproject.score_tier1_containment(world_pts, evidence, intrinsics, pose)
    return score >= threshold


def _shared_frames_compatible(
    cluster_a: list[dict], cluster_b: list[dict], ctx: Optional[RefinementContext]
) -> bool:
    """True if every frame shared between two clusters is duplicate-
    consistent (dedup-style containment) rather than genuinely disjoint
    same-label objects. No shared frames -> trivially compatible. No ctx
    (no mask evidence) -> the legacy hard veto stands."""
    by_frame_a = {m["frame_index"]: m for m in cluster_a}
    shared = [m for m in cluster_b if m["frame_index"] in by_frame_a]
    if not shared:
        return True
    if ctx is None:
        return False
    for mb in shared:
        ma = by_frame_a[mb["frame_index"]]
        mask_a = ctx.mask_for(ma["frame_index"], ma.get("mask_index"))
        mask_b = ctx.mask_for(mb["frame_index"], mb.get("mask_index"))
        if mask_a is None or mask_b is None:
            return False
        if mask_containment(mask_a, mask_b) < _DEDUP_CONTAINMENT:
            return False
    return True


def _merge_cluster_pair(cluster_a: list[dict], cluster_b: list[dict]) -> list[dict]:
    """Merge two (shared-frame-compatible) clusters, keeping only the
    higher-scored observation for any frame present in both."""
    by_frame_a = {m["frame_index"]: m for m in cluster_a}
    merged = list(cluster_a)
    for mb in cluster_b:
        ma = by_frame_a.get(mb["frame_index"])
        if ma is None:
            merged.append(mb)
        elif mb["score"] > ma["score"]:
            merged.remove(ma)
            merged.append(mb)
    return merged


def _cluster_ray_observations(
    with_rays: list[dict], ctx: Optional[RefinementContext], refine: bool
) -> list[list[dict]]:
    ray_clusters: list[list[dict]] = []
    for o in with_rays:
        joined = False
        for cluster in ray_clusters:
            if _has_frame(cluster, o["frame_index"]):
                continue
            candidate = cluster + [o]
            tri = _try_triangulate(candidate)
            rms_ok = tri is not None and tri[1] <= _RAY_RMS_M
            footprint_ok = False
            if not rms_ok and refine and ctx is not None and len(cluster) >= 2:
                volume = _provisional_ray_volume(cluster, ctx)
                footprint_ok = _footprint_agrees(
                    volume, o["frame_index"], o.get("mask_index"), ctx, _FOOTPRINT_MIN
                )
            if rms_ok or footprint_ok:
                cluster.append(o)
                joined = True
                break
        if not joined:
            ray_clusters.append([o])

    merged = True
    while merged and len(ray_clusters) > 1:
        merged = False
        for i in range(len(ray_clusters)):
            for j in range(i + 1, len(ray_clusters)):
                ctx_for_veto = ctx if refine else None
                if not _shared_frames_compatible(ray_clusters[i], ray_clusters[j], ctx_for_veto):
                    continue
                candidate = _merge_cluster_pair(ray_clusters[i], ray_clusters[j])
                tri = _try_triangulate(candidate)
                if tri is not None and tri[1] <= _RAY_RMS_M:
                    ray_clusters[i] = candidate
                    del ray_clusters[j]
                    merged = True
                    break
            if merged:
                break
    return ray_clusters


def _cluster_placed_observations(
    placed: list[dict], ctx: Optional[RefinementContext], refine: bool
) -> list[list[dict]]:
    clusters: list[list[dict]] = []
    for o in placed:
        c = _center(o)
        joined = False
        for cluster in clusters:
            if _has_frame(cluster, o["frame_index"]):
                continue
            ref = np.median(np.stack([_center(m) for m in cluster]), axis=0)
            proximity_ok = np.linalg.norm(c - ref) <= _CLUSTER_DIST_M
            footprint_ok = False
            if not proximity_ok and refine and ctx is not None:
                best = max(cluster, key=lambda m: m["score"])
                best_wt = best["placement"]["world_transform"]
                splat = ctx.get_splat(best["splat_gcs_uri"])
                if splat is not None:
                    volume = (splat, best_wt["rotation_xyzw"], ref, best_wt["scale"])
                    footprint_ok = _footprint_agrees(
                        volume, o["frame_index"], o.get("mask_index"), ctx, _FOOTPRINT_MIN
                    )
            if proximity_ok or footprint_ok:
                cluster.append(o)
                joined = True
                break
        if not joined:
            clusters.append([o])

    if not refine or ctx is None:
        return clusters
    merged = True
    while merged and len(clusters) > 1:
        merged = False
        for i in range(len(clusters)):
            for j in range(i + 1, len(clusters)):
                if not _shared_frames_compatible(clusters[i], clusters[j], ctx):
                    continue
                candidate = _merge_cluster_pair(clusters[i], clusters[j])
                positions = np.stack([_center(m) for m in candidate])
                spread = float(np.linalg.norm(positions - np.median(positions, axis=0), axis=1).max())
                if spread <= _CLUSTER_DIST_M:
                    clusters[i] = candidate
                    del clusters[j]
                    merged = True
                    break
            if merged:
                break
    return clusters


# -----------------------------------------------------------------------------
# Refinement locks 3-6: silhouette fit, in-plane resolution, sign-flag,
# instrument-scored best-member selection
# -----------------------------------------------------------------------------

def _member_observations(cluster: list[dict], ctx: RefinementContext):
    """[(evidence, intrinsics, pose), ...] for every cluster member fusion
    has real evidence for. Members missing a mask/camera are silently
    dropped (a partial cache miss degrades refinement, never crashes it)."""
    out = []
    for m in cluster:
        cam = ctx.get_camera(m["frame_index"])
        evidence = ctx.evidence_for(m["frame_index"], m.get("mask_index"))
        if cam is None or evidence is None:
            continue
        pose, intrinsics = cam
        out.append((evidence, intrinsics, pose))
    return out


def _score_candidate_over_frames(
    local_points: np.ndarray,
    rotation_xyzw,
    translation,
    scale: float,
    frame_specs: list[tuple[int, Optional[int]]],
    ctx: RefinementContext,
    appearance: Optional[reproject.SplatAppearance] = None,
) -> Optional[float]:
    """Mean combined (tier2-weighted-when-present) score of one candidate
    transform across a set of (frame_index, mask_index) observations.
    None if no observation had usable evidence."""
    scores = []
    for frame_index, mask_index in frame_specs:
        cam = ctx.get_camera(frame_index)
        evidence = ctx.evidence_for(frame_index, mask_index)
        if cam is None or evidence is None:
            continue
        pose, intrinsics = cam
        rgb = ctx.get_rgb(frame_index) if (appearance is not None and ctx.get_rgb is not None) else None
        result = reproject.score_placement(
            local_points=local_points,
            rotation_xyzw=rotation_xyzw,
            translation=translation,
            scale=scale,
            mask=evidence,
            intrinsics=intrinsics,
            pose=pose,
            appearance=appearance,
            rgb=rgb,
        )
        scores.append(reproject.combined_score(result))
    return float(np.mean(scores)) if scores else None


def _reselect_best_placed_member(obj: dict, cluster: list[dict], wt: dict, ctx: RefinementContext) -> None:
    """Instrument-scored best-member selection for depth_fit clusters
    (decision 0067 lock 2: rank by instrument score, detection score only
    as a tiebreak). Each member already carries its own complete
    world_transform (a single-view fit), so this is a well-defined,
    non-circular per-member self-consistency check: does THIS member's own
    splat+rotation+scale, at ITS OWN position, explain ITS OWN frame's
    mask? Mutates obj/wt in place when a different member wins; a no-op
    (silent) for single-member clusters or when evidence is missing.

    Ray (layout_triangulated) clusters keep legacy detection-score
    selection: unlike a depth_fit member, a ray member has no complete
    per-member transform of its own (translation/scale are cluster-level,
    derived FROM whichever member is "best"), so re-ranking members here
    would require calibrating each candidate's scale against a transform
    fit for a different splat's extent — a real correctness risk left for
    a future pass rather than shipped unverified.
    """
    if len(cluster) < 2:
        return
    scored = []
    for m in cluster:
        m_wt = m["placement"].get("world_transform")
        if not m_wt:
            continue
        m_splat = ctx.get_splat(m["splat_gcs_uri"])
        evidence = ctx.evidence_for(m["frame_index"], m.get("mask_index"))
        cam = ctx.get_camera(m["frame_index"])
        if m_splat is None or evidence is None or cam is None:
            continue
        pose, intrinsics = cam
        m_appearance = ctx.get_appearance(m["splat_gcs_uri"]) if ctx.get_appearance is not None else None
        rgb = ctx.get_rgb(m["frame_index"]) if (m_appearance is not None and ctx.get_rgb is not None) else None
        result = reproject.score_placement(
            local_points=m_splat, rotation_xyzw=m_wt["rotation_xyzw"], translation=m_wt["position"],
            scale=m_wt["scale"], mask=evidence, intrinsics=intrinsics, pose=pose,
            appearance=m_appearance, rgb=rgb,
        )
        scored.append((reproject.combined_score(result), m["score"], m))
    if not scored:
        return
    scored.sort(key=lambda c: (c[0], c[1]), reverse=True)
    _best_score, _tiebreak, best_member = scored[0]
    if best_member["splat_gcs_uri"] == obj["splat_gcs_uri"]:
        return
    best_wt = best_member["placement"]["world_transform"]
    wt["rotation_xyzw"] = [float(c) for c in best_wt["rotation_xyzw"]]
    wt["scale"] = float(best_wt["scale"])
    obj["splat_gcs_uri"] = best_member["splat_gcs_uri"]
    obj["source"] = {"frame_index": best_member["frame_index"], "mask_index": best_member["mask_index"]}


def _finalize_placed_object(
    obj: dict,
    cluster: list[dict],
    wt: dict,
    quality: dict,
    local_points,
    appearance,
    ctx: RefinementContext,
    position_source: str,
    constraints_applied: list[str],
) -> dict:
    """Shared refinement tail for any placed object (multi-view refined OR
    single-view contact-placed): in-plane resolution for planar splats, the
    sign-flag diagnostic, the final reprojection score, and physical
    extents — then stamp the additive manifest fields. Every step is a
    recorded no-op when its evidence is missing; never raises. `wt` may be
    mutated (in-plane resolution rewrites the rotation)."""
    in_plane_resolved = False
    sign_flag = False
    frame_specs = [(m["frame_index"], m.get("mask_index")) for m in cluster]

    if local_points is not None:
        # --- In-plane resolution (planar splats only). ---
        if reproject.is_planar(local_points):
            candidates = reproject.in_plane_candidates(wt["rotation_xyzw"], local_points)
            scored = []
            for cand_rot in candidates:
                s = _score_candidate_over_frames(
                    local_points, cand_rot, wt["position"], wt["scale"], frame_specs, ctx, appearance
                )
                scored.append(s if s is not None else -1.0)
            order = sorted(range(len(scored)), key=lambda i: -scored[i])
            best_i, second_i = order[0], order[1]
            margin = scored[best_i] - scored[second_i]
            quality["in_plane_scores"] = scored
            if scored[best_i] > -1.0 and margin >= _INPLANE_MARGIN:
                wt["rotation_xyzw"] = list(candidates[best_i])
                in_plane_resolved = True

        # --- Sign-flag diagnostic (never auto-corrects). ---
        best_member = max(cluster, key=lambda m: m["score"])
        cam = ctx.get_camera(best_member["frame_index"])
        if cam is not None:
            pose, _intr = cam
            R_wc = quat_to_rotmat(pose_quat(pose))
            view_dir_world = R_wc @ np.array([0.0, 0.0, -1.0])
            twin_rot = reproject.mirrored_twin(wt["rotation_xyzw"], view_dir_world)
            true_score = _score_candidate_over_frames(
                local_points, wt["rotation_xyzw"], wt["position"], wt["scale"], frame_specs, ctx, appearance
            )
            twin_score = _score_candidate_over_frames(
                local_points, twin_rot, wt["position"], wt["scale"], frame_specs, ctx, appearance
            )
            if true_score is not None and twin_score is not None:
                sign_flag = bool(twin_score > true_score + _SIGNFLAG_MARGIN)
                quality["sign_flag_true_score"] = true_score
                quality["sign_flag_twin_score"] = twin_score

        # --- Final reprojection score + physical extents. ---
        final_score = _score_candidate_over_frames(
            local_points, wt["rotation_xyzw"], wt["position"], wt["scale"], frame_specs, ctx, appearance
        )
        if final_score is not None:
            obj["reprojection_score"] = final_score
        try:
            stats = robust_cloud_stats(local_points)
            extents_m = sorted((stats.extents * wt["scale"]).tolist(), reverse=True)
            obj["extent_m_sorted"] = [float(v) for v in extents_m]
        except DegenerateGeometryError:
            pass

    obj["world_transform"] = wt
    obj["position_source"] = position_source
    obj["constraints_applied"] = constraints_applied
    obj["in_plane_resolved"] = in_plane_resolved
    obj["sign_flag"] = sign_flag
    obj["quality"] = quality
    return obj


def _refine_fused_object(obj: dict, cluster: list[dict], ctx: RefinementContext) -> dict:
    """Apply instrument-scored best-member selection, silhouette fit,
    in-plane resolution, and sign-flagging to one already-fused
    (placed=True) object, in place on a copy. Every step degrades to a
    no-op (recorded, never a crash) when evidence for it is missing."""
    obj = dict(obj)
    quality = dict(obj.get("quality", {}))
    wt = dict(obj["world_transform"])
    if obj["method"] == "depth_fit":
        _reselect_best_placed_member(obj, cluster, wt, ctx)
    local_points = ctx.get_splat(obj["splat_gcs_uri"])
    appearance = ctx.get_appearance(obj["splat_gcs_uri"]) if ctx.get_appearance is not None else None
    position_source = "triangulated" if obj["method"] == "layout_triangulated" else "depth_fit"
    constraints_applied: list[str] = []

    if local_points is not None:
        # --- Silhouette fit (>=2-view ray clusters only). ---
        if obj["method"] == "layout_triangulated" and len(cluster) >= 2:
            observations = _member_observations(cluster, ctx)
            if len(observations) >= 2:
                fit = reproject.fit_silhouette(
                    local_points, wt["rotation_xyzw"], wt["scale"], wt["position"], observations
                )
                if fit["improved"]:
                    wt["position"] = fit["translation"]
                    wt["scale"] = fit["scale"]
                    position_source = "silhouette_fit"
                    quality["silhouette_fit_tier1_mean"] = fit["tier1_mean"]
                    quality["silhouette_fit_init_tier1_mean"] = fit["init_tier1_mean"]

    return _finalize_placed_object(
        obj, cluster, wt, quality, local_points, appearance, ctx,
        position_source, constraints_applied,
    )


def _try_single_view_prior(
    obj: dict, cluster: list[dict], ctx: RefinementContext
) -> Optional[dict]:
    """Attempt a measured-plane contact placement for an unplaced single-
    view object (decision 0067 chunk D). Returns a fully-placed object dict
    on success, or None to leave it `insufficient_observations`.

    The prior proposes a transform (contact_priors.solve_placement); this
    function enforces the evidence rule — the transform must reproject onto
    the object's OWN SAM mask at tier-1 >= PLACEMENT_SINGLE_VIEW_MIN_TIER1 —
    before anything ships. No planes, no mapped class, no wall/floor on the
    ray, missing splat/rotation/mask, or a below-threshold reprojection all
    return None (honestly unplaced, never a guessed transform)."""
    if ctx.get_room_planes is None:
        return None
    planes = ctx.get_room_planes()
    if planes is None or not planes.has_geometry:
        return None
    member = cluster[0]
    klass = contact_priors.prior_class(member.get("label"))
    if klass is None:
        return None
    ray = member.get("view_ray")
    world_rot = member["placement"].get("world_rotation_xyzw")
    if not ray or not world_rot:
        return None
    splat = ctx.get_splat(member["splat_gcs_uri"])
    if splat is None:
        return None
    result = contact_priors.solve_placement(klass, splat, world_rot, ray, planes)
    if result is None:
        return None

    # Evidence gate: the proposed transform must reproject onto this frame's
    # own mask. A prior may close a DOF; it may never override pixels.
    cam = ctx.get_camera(member["frame_index"])
    evidence = ctx.evidence_for(member["frame_index"], member.get("mask_index"))
    if cam is None or evidence is None:
        return None
    pose, intrinsics = cam
    world_pts = reproject.transform_points(
        splat, result["rotation_xyzw"], result["position"], result["scale"]
    )
    tier1 = reproject.score_tier1(world_pts, evidence, intrinsics, pose)
    if tier1 < _SINGLE_VIEW_MIN_TIER1:
        return None

    placed = dict(obj)
    placed.pop("reason", None)
    placed["placed"] = True
    placed["method"] = result["method"]
    placed["rotation_source"] = "sam3d_layout"
    quality = dict(placed.get("quality", {}))
    quality["single_view_tier1"] = float(tier1)
    quality["min_axis_to_vertical_deg"] = min_axis_to_vertical_deg(
        quat_to_rotmat(tuple(result["rotation_xyzw"]))
    )
    wt = {
        "position": result["position"],
        "rotation_xyzw": result["rotation_xyzw"],
        "scale": result["scale"],
    }
    appearance = (
        ctx.get_appearance(member["splat_gcs_uri"]) if ctx.get_appearance is not None else None
    )
    return _finalize_placed_object(
        placed, cluster, wt, quality, splat, appearance, ctx,
        result["position_source"], list(result["constraints_applied"]),
    )


# -----------------------------------------------------------------------------
# Refinement lock 10: room-sanity gate (never emit a guessed transform)
# -----------------------------------------------------------------------------

def _room_planes(ctx: Optional[RefinementContext]):
    if ctx is None or ctx.get_room_planes is None:
        return None
    return ctx.get_room_planes()


def _wall_top_y(planes) -> Optional[float]:
    tops = [float(w.corners_world[:, 1].max()) for w in getattr(planes, "walls", [])]
    return max(tops) if tops else None


def _position_outside_room(pos: np.ndarray, planes) -> bool:
    """True if a world position lands outside the MEASURED room: beyond the
    detected floor rectangle in XZ (padded), below the floor, or above the
    wall top. Each sub-test is skipped when its measured input is absent, so
    a room with a floor but no walls still gates XZ + below-floor."""
    floor = getattr(planes, "floor", None)
    if floor is not None:
        rel = pos - floor.origin
        u = float(np.dot(rel, floor.axis_u))
        v = float(np.dot(rel, floor.axis_v))
        m = _ROOM_MARGIN_M
        if not (-m <= u <= floor.width_m + m and -m <= v <= floor.height_m + m):
            return True
        floor_y = planes.floor_y
        if floor_y is not None and pos[1] < floor_y - _ROOM_VERTICAL_MARGIN_M:
            return True
    top = _wall_top_y(planes)
    if top is not None and pos[1] > top + _ROOM_VERTICAL_MARGIN_M:
        return True
    return False


def _room_sanity_reason(obj: dict, ctx: Optional[RefinementContext]) -> Optional[str]:
    """Why a placed object should be demoted to unplaced, or None if it
    passes. Applies to the triangulated / silhouette / depth_fit path only —
    chunk D's measured-surface contact placements are exempt (self-gated).

      * `represented_as_shell_opening` — a door/window class the shell already
        renders as a wall opening; a free (triangulated) splat for it, at a
        mid-room position, is double-wrong. Needs no geometry.
      * `implausible_scale` — the largest physical extent is absurdly small (a
        collapsed reconstruction) or larger than any home-room object. Uses
        extent_m_sorted when present; needs no geometry.
      * `outside_room` — the position lands outside the measured room. Needs
        measured planes; inert without them (the degrade lock).
    """
    # Contact placements sit ON a measured surface by construction — never
    # mid-room, never a guess — and carry their own gates. Exempt entirely.
    if obj.get("position_source") in _CONTACT_POSITION_SOURCES:
        return None

    label = (obj.get("label") or "").strip().lower()
    if label in _SHELL_OPENING_CLASSES:
        return "represented_as_shell_opening"

    extents = obj.get("extent_m_sorted")
    if extents:
        largest = float(extents[0])
        if largest > _MAX_EXTENT_M or largest < _MIN_EXTENT_M:
            return "implausible_scale"

    planes = _room_planes(ctx)
    if planes is None or not getattr(planes, "has_geometry", False):
        return None
    wt = obj.get("world_transform") or {}
    pos = wt.get("position")
    if pos is None:
        return None
    if _position_outside_room(np.asarray(pos, dtype=np.float64), planes):
        return "outside_room"
    return None


def _demote_object(obj: dict, reason: str) -> dict:
    """Turn an over-placed object into an honest unplaced entry, preserving
    its identity/provenance so the manifest still lists it (as inventory, not
    rendered). deduped_observations is added by the caller after this."""
    quality = obj.get("quality", {})
    return {
        "object_id": obj["object_id"],
        "label": obj["label"],
        "placed": False,
        "method": None,
        "reason": reason,
        "splat_gcs_uri": obj.get("splat_gcs_uri"),
        "source": obj.get("source"),
        "world_transform": None,
        "quality": {
            "frames_observed": quality.get("frames_observed"),
            "score": quality.get("score"),
        },
    }


def _apply_room_sanity(obj: dict, ctx: Optional[RefinementContext]) -> dict:
    """Demote obj to unplaced if the room-sanity gate rejects it; otherwise
    return it unchanged. Only ever consulted for placed objects."""
    if not obj.get("placed"):
        return obj
    reason = _room_sanity_reason(obj, ctx)
    if reason is None:
        return obj
    logger.info(
        "fusion: demoting %s (%s) -> unplaced: %s",
        obj.get("object_id"), obj.get("label"), reason,
    )
    return _demote_object(obj, reason)


# -----------------------------------------------------------------------------
# Top-level entry points
# -----------------------------------------------------------------------------

def fuse_scene_objects_with_meta(
    frame_results: list[dict], ctx: Optional[RefinementContext] = None
) -> tuple[list[dict], dict]:
    """Cluster per-frame observations into fused scene objects.

    Returns (objects, meta) where meta = {"refinement_enabled": bool,
    "refinement_skipped": bool}. refinement_skipped is True when
    refinement was requested (PLACEMENT_REFINE != "0", ctx supplied) but
    the budget forced any of it to be skipped — either up front (the whole
    pass; the scene ships via the legacy algorithm without the new
    fields), or mid-pass if the budget drains below min_remaining_s while
    refining (already-refined objects keep their refined values; the
    REMAINING objects ship legacy values — each object is either fully
    refined or fully legacy, never half-refined, which is 0067's actual
    invariant). The mid-pass check exists because refinement runs during
    the request's final reserve window: without it, an unexpectedly slow
    pass would recreate the request-timeout zombie that decisions
    0060-0061 eliminated. Never raises; a pathological input degrades to
    unplaced entries, not a failed scene.
    """
    refine_flag = _refinement_enabled()
    has_ctx = ctx is not None
    budget_ok = _budget_allows(ctx) if has_ctx else True
    run_refine = has_ctx and refine_flag and budget_ok
    refinement_skipped = has_ctx and refine_flag and not budget_ok

    if not run_refine:
        return _fuse_scene_objects_legacy(frame_results), {
            "refinement_enabled": run_refine,
            "refinement_skipped": refinement_skipped,
        }

    observations = _collect_observations(frame_results)
    by_label: dict[str, list[dict]] = {}
    for o in observations:
        by_label.setdefault(o["label"] or "", []).append(o)

    fused: list[dict] = []
    dedup_counts: dict[tuple, int] = {}
    counter = 0
    for label in sorted(by_label):
        group = sorted(by_label[label], key=lambda o: -o["score"])
        placed = [o for o in group if o["placement"].get("placed")]
        with_rays = [
            o for o in group
            if not o["placement"].get("placed") and o.get("view_ray")
        ]

        placed, placed_dedup = _dedup_same_frame(placed, ctx)
        with_rays, ray_dedup = _dedup_same_frame(with_rays, ctx)
        for rec in placed_dedup + ray_dedup:
            key = (rec["frame_index"], rec["kept_mask_index"])
            dedup_counts[key] = dedup_counts.get(key, 0) + 1

        for cluster in _cluster_placed_observations(placed, ctx, run_refine):
            obj = _fuse_placed_cluster(cluster, f"obj_{counter:03d}")
            counter += 1
            if _budget_allows(ctx):
                obj = _refine_fused_object(obj, cluster, ctx)
            else:
                refinement_skipped = True
            obj = _apply_room_sanity(obj, ctx)
            n_dedup = sum(dedup_counts.get((m["frame_index"], m.get("mask_index")), 0) for m in cluster)
            obj["deduped_observations"] = n_dedup
            fused.append(obj)

        for cluster in _cluster_ray_observations(with_rays, ctx, run_refine):
            obj = _fuse_ray_cluster(cluster, f"obj_{counter:03d}")
            counter += 1
            if obj["placed"]:
                if _budget_allows(ctx):
                    obj = _refine_fused_object(obj, cluster, ctx)
                else:
                    refinement_skipped = True
            elif obj.get("reason") == "insufficient_observations":
                # Single-view object: a measured-plane contact prior may
                # place it (decision 0067 chunk D). Budget-gated like the
                # refine path — an object is fully placed-and-finalized or
                # left legacy-unplaced, never half-done.
                if _budget_allows(ctx):
                    placed = _try_single_view_prior(obj, cluster, ctx)
                    if placed is not None:
                        obj = placed
                else:
                    refinement_skipped = True
            obj = _apply_room_sanity(obj, ctx)
            n_dedup = sum(dedup_counts.get((m["frame_index"], m.get("mask_index")), 0) for m in cluster)
            obj["deduped_observations"] = n_dedup
            fused.append(obj)

    placed_count = sum(1 for f in fused if f["placed"])
    logger.info(
        "fusion (refined): %d observations -> %d objects (%d placed) refinement_skipped=%s",
        len(observations), len(fused), placed_count, refinement_skipped,
    )
    return fused, {"refinement_enabled": run_refine, "refinement_skipped": refinement_skipped}


def fuse_scene_objects(frame_results: list[dict], ctx: Optional[RefinementContext] = None) -> list[dict]:
    """Convenience wrapper over fuse_scene_objects_with_meta for callers
    (and the existing test suite) that only need the objects array."""
    objects, _meta = fuse_scene_objects_with_meta(frame_results, ctx)
    return objects
