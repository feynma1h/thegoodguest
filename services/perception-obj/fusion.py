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
     room planes (decision 0067). An unplaced single-member ray
     cluster of a floor/wall-mapped class (contact_priors) gets a contact-
     prior transform — bottom-on-the-detected-floor or ray-onto-a-detected-
     wall — which ships only if it reprojects onto the object's own mask
     (the evidence gate). No planes in the bundle → inert; the object stays
     `insufficient_observations` and the rest of refinement is unchanged.
 10. Applies a room-sanity gate to every PLACED object (the triangulated /
     silhouette / depth_fit path — NOT the single-view contact placements,
     which are self-gated against a measured surface). A placement whose
     position lands OUTSIDE the measured room (beyond the detected floor
     rectangle + margin, below the floor, or above the wall top), whose
     physical size is implausible, or whose class the shell already renders
     as a structural opening (door/window — a free splat mid-room is
     double-wrong) is demoted to unplaced with an explicit reason rather
     than rendered as a guessed transform. This is the "never emit a guessed
     transform" rule (0052/0067) applied to triangulation blow-ups — the
     floating mirror, the 5 cm speck, the mid-room door. The outside-room
     half needs measured planes and is inert without them (the degrade
     lock); the class/scale halves need no geometry.

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
import math
import os
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Optional

import box_placement
import contact_priors
import numpy as np
import reproject
from placement import min_axis_to_vertical_deg
from roomstudio_schemas.placement_math import (
    DegenerateGeometryError,
    MaskEvidence,
    mask_containment,
    minimal_rotation,
    prepare_mask,
    project_points,
    robust_cloud_stats,
    triangulate_rays,
)
from roomstudio_schemas.pose_math import pose_quat, quat_to_rotmat, rotmat_to_quat

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
# A single-view contact-prior placement (decision 0067) ships only
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
# FREE-place (triangulate) these; a single-view measured wall-contact
# placement is exempt (it sits on the actual wall, not mid-room).
# Env-overridable.
_SHELL_OPENING_CLASSES = frozenset(
    s.strip().lower()
    for s in os.environ.get("PLACEMENT_SHELL_OPENING_CLASSES", "door,window").split(",")
    if s.strip()
)
# Placements produced by the single-view measured-surface contact priors
# — exempt from the room-sanity gate (they are placed ON the measured floor/wall by
# construction and carry their own bounds + evidence gates).
_CONTACT_POSITION_SOURCES = frozenset(
    ("single_view_floor_contact", "single_view_wall_contact")
)

# --- LIDAR_ROOMPLAN long-tail gates (decision 0077; measured on 247003de) ---
# These three gates run ONLY when the scene carries a parsed CapturedRoom
# (ctx.get_roomplan) — bundles without one reproduce today's behaviour
# byte-for-byte (the no-CapturedRoom degrade lock).
#
# Cross-label containment dedup: two same-frame masks that are the SAME
# region under different labels (the f242 artwork/painting/mirror triple,
# pairwise IoS 0.999) collapse to the best-scoring one. The test is
# intersection-over-LARGER (near-identity), NOT intersection-over-smaller:
# a small mask nested inside a genuinely larger different-label mask must
# never merge — the higher default reflects that crossing labels is a
# bigger claim than the same-label rule's 0.8.
_CROSS_LABEL_DEDUP_IDENTITY = float(
    os.environ.get("PLACEMENT_CROSS_LABEL_DEDUP_IDENTITY", "0.9")
)
# Mirror depth-trust: a depth_fit whose NN polish RMS is out of family
# (the real mirror measured 0.196 m vs this scene's 0.007 m typical —
# LiDAR through mirror glass returns virtual depth) is demoted to the ray
# path, where the wall-contact prior can still place it against a measured
# wall. The threshold sits an order of magnitude above good fits and 4x
# below the measured failure.
_DEPTH_TRUST_RMS_M = float(os.environ.get("PLACEMENT_DEPTH_TRUST_RMS_M", "0.05"))
# Textile silhouette-span: a placed splat whose projected extent covers
# less than this fraction of its own mask's extent is a scale-collapse
# suspect (the 262k px throw that shipped at 0.34 m — a small splat inside
# a large depth cloud scores excellent one-directional NN RMS). Flag-only
# in v1: scale_suspect + the measured ratio, never a mutation.
_SPAN_MIN = float(os.environ.get("PLACEMENT_SPAN_MIN", "0.5"))

# --- Post-fusion placement passes (decision 0082) ---------------------------
# Knobs for the four defect classes measured on the first real RoomPlan
# rooms: cross-label 3D duplicates, wall back-face anchoring + floor declip,
# door-geometry opening demotion, and the on-top-of support snap.
#
# Cross-label 3D duplicate gate: two placed objects whose VOLUMES
# coincide (sampled-point containment either way >= this) under
# confusable labels are one physical object — the near-identity mask gate's
# 3D, cross-frame sibling (desk+nightstand, monitor+tv, mirror x2 all
# survived it at partial mask overlap).
_CROSS_LABEL_3D_MIN = float(os.environ.get("PLACEMENT_CROSS_LABEL_3D_MIN", "0.5"))
# Labels that SAM confuses for one physical object, beyond exact equality.
# "|"-separated groups; same-label pairs always qualify.
#
# These must span BOTH vocabularies. A box-anchored object is labelled with
# its RoomPlan CATEGORY, not a SAM label, so a category missing here can
# never dedup against the SAM detections of the same physical thing.
# `storage` was the one gap (decision 0104): rp7's nightstand shipped both
# as a storage box and as a free `desk` splat 0.3 m away, and nothing could
# collapse them. `television` is the same alias for the tv/monitor group.
_CROSS_LABEL_3D_GROUPS = [
    frozenset(x.strip().lower() for x in grp.split(",") if x.strip())
    for grp in os.environ.get(
        "PLACEMENT_CROSS_LABEL_3D_GROUPS",
        "tv,television,monitor"
        "|desk,table,nightstand,cabinet,dresser,stool,bench,shelf,bookshelf,storage"
        "|artwork,painting,poster,frame,mirror"
        "|bed,sofa,couch",
    ).split("|")
    if grp.strip()
]

# Wall back-face anchoring: a wall-class splat placed by depth or
# triangulation renders centered IN the wall; snap its back face onto the
# nearest measured wall plane instead. Bounds keep the snap a
# refinement, never a teleport.
_WALL_SNAP_NEAR_M = float(os.environ.get("PLACEMENT_WALL_SNAP_NEAR_M", "0.6"))
_WALL_SNAP_MAX_M = float(os.environ.get("PLACEMENT_WALL_SNAP_MAX_M", "0.5"))
_WALL_SNAP_RECT_PAD_M = float(os.environ.get("PLACEMENT_WALL_SNAP_RECT_PAD_M", "0.4"))
_WALL_ALIGN_MAX_DEG = float(os.environ.get("PLACEMENT_WALL_ALIGN_MAX_DEG", "60"))
# Floor-class wall declip (the same pass's second half): furniture may clip a
# measured wall by at most this before being pushed back into the room.
_WALL_PENETRATION_TOL_M = float(os.environ.get("PLACEMENT_WALL_PENETRATION_TOL_M", "0.08"))
_WALL_DECLIP_MAX_M = float(os.environ.get("PLACEMENT_WALL_DECLIP_MAX_M", "0.35"))

# Door-geometry demotion: a placed object of a storage-ish label sitting ON
# a RoomPlan door/window surface is that opening, mislabeled ("cabinet N is
# actually a door" x5) — demote like the label rule does, keyed on measured
# geometry instead of the label.
_OPENING_GEOM_CLASSES = frozenset(
    s.strip().lower()
    for s in os.environ.get(
        "PLACEMENT_OPENING_GEOM_CLASSES",
        "cabinet,dresser,wardrobe,shelf,bookshelf,storage,door,window",
    ).split(",")
    if s.strip()
)
_OPENING_GEOM_NEAR_M = float(os.environ.get("PLACEMENT_OPENING_GEOM_NEAR_M", "0.35"))
_OPENING_GEOM_RECT_PAD_M = float(os.environ.get("PLACEMENT_OPENING_GEOM_RECT_PAD_M", "0.25"))

# On-top-of support snap (v1: RoomPlan box tops only — the measured support
# surfaces): a small-class object whose bottom hovers or sinks within reach
# of a box top, over that box's footprint, rests ON it.
_SUPPORT_CLASSES = frozenset(
    s.strip().lower()
    for s in os.environ.get(
        "PLACEMENT_SUPPORT_CLASSES",
        "speaker,table lamp,lamp,monitor,tv,television,plant,vase,laptop,keyboard",
    ).split(",")
    if s.strip()
)
_SUPPORT_SNAP_M = float(os.environ.get("PLACEMENT_SUPPORT_SNAP_M", "0.35"))
# The snap is deliberately ASYMMETRIC. Lifting an object out of a surface
# it penetrates corrects an impossibility, so it may travel the full reach
# above. LOWERING an object asserts a contact the depth fit did not find,
# and the depth fit is a measurement — beyond a small correction the gap it
# measured is real and the missing thing is the object's own support:
# rp6g1's monitor was pulled 0.123 m down onto its table, hiding the fact
# that the stand holding the screen up was never reconstructed. A screen
# resting at its measured height with a visible gap is the honest picture;
# a screen glued to the desk is a wrong one. Calibrated on the reviewed
# rooms, where the blessed downward corrections are 0.06 m and the rejected
# ones 0.12-0.19 m.
_SUPPORT_DROP_MAX_M = float(os.environ.get("PLACEMENT_SUPPORT_DROP_MAX_M", "0.10"))
_SUPPORT_XZ_PAD_M = float(os.environ.get("PLACEMENT_SUPPORT_XZ_PAD_M", "0.15"))

# Levelling (decision 0147): the classes whose relationship with the room
# is that they rest on something level, so gravity is evidence about their
# rotation. Deliberately the union of the two vocabularies that already
# exist for exactly this population — the things that rest ON surfaces and
# the things that stand ON the floor — so a class joins both rules at
# once. Wall and hanging classes are excluded by their absence: their
# rotation is owed to a measured wall, not to gravity.
_LEVEL_CLASSES = frozenset(
    s.strip().lower()
    for s in os.environ.get(
        "PLACEMENT_LEVEL_CLASSES",
        "speaker,table lamp,lamp,monitor,tv,television,plant,vase,laptop,keyboard,"
        "bed,sofa,couch,chair,stool,bench,table,desk,nightstand,cabinet,dresser,"
        "bookshelf,shelf,sideboard,console,stand,rug",
    ).split(",")
    if s.strip()
)
# Below this there is nothing to correct; above it, no axis is near enough
# to vertical for "which way is up" to be a reading rather than a guess
# (the furthest a coordinate axis of any rotation can sit from the nearest
# world axis is 54.7 degrees).
_LEVEL_MIN_DEG = float(os.environ.get("PLACEMENT_LEVEL_MIN_DEG", "1.0"))
_LEVEL_MAX_DEG = float(os.environ.get("PLACEMENT_LEVEL_MAX_DEG", "45.0"))
# Reading which axis is up off the object's own LiDAR surface: the surface
# must show a level object, and it must say so unambiguously. Measured on
# the reviewed objects, the nearest axis sits 7-16 degrees off vertical
# with the runner-up 58-72 degrees behind it, so neither gate is near real
# data — they are there to refuse a surface that cannot answer.
_LEVEL_CLOUD_MAX_TILT_DEG = float(
    os.environ.get("PLACEMENT_LEVEL_CLOUD_MAX_TILT_DEG", "25.0")
)
_LEVEL_CLOUD_MARGIN_DEG = float(
    os.environ.get("PLACEMENT_LEVEL_CLOUD_MARGIN_DEG", "20.0")
)
_LEVEL_MIN_CLOUD_POINTS = 64
# Cloud and splat axes are matched by extent RANK, so the rank in question
# must be separated from its neighbours in both point sets.
_LEVEL_RANK_SEP = float(os.environ.get("PLACEMENT_LEVEL_RANK_SEP", "0.15"))
# The correction ships only if the underside flattens by at least this
# much — whichever of the two bars is higher, so tiny objects are not
# levelled on rounding and large ones must show a real gain.
_LEVEL_MIN_GAIN_M = float(os.environ.get("PLACEMENT_LEVEL_MIN_GAIN_M", "0.001"))
_LEVEL_MIN_GAIN_FRAC = float(os.environ.get("PLACEMENT_LEVEL_MIN_GAIN_FRAC", "0.05"))
# Principal axes and a bottom-decile percentile both want more than the
# 600 points the containment tests are happy with.
_LEVEL_POINT_CAP = 4000
_LEVEL_MIN_POINTS = 64

# The default scale-floor map (the rule that reads it is at
# _LABEL_SCALE_FLOOR_M below): deliberately just the one class the
# acceptance review measured. Floors for bed, sofa, door and wardrobe were
# drafted and CUT: no reviewed room produced a collapsed one, and the
# drafted values demoted legitimate small-geometry test fixtures — i.e.
# the only evidence they generated was evidence against themselves. Add a
# class when a real capture produces a collapse in it.
_LABEL_SCALE_FLOOR_DEFAULT = "tv:0.35|television:0.35"


def _parse_scale_floors(raw: str) -> dict[str, float]:
    """"tv:0.35|bed:1.4" -> {label: minimum longest extent in metres}."""
    out: dict[str, float] = {}
    for part in raw.split("|"):
        part = part.strip()
        if not part or ":" not in part:
            continue
        label, value = part.split(":", 1)
        try:
            out[label.strip().lower()] = float(value)
        except ValueError:
            continue
    return out


# Label-aware scale floor (decision 0104). The textile silhouette-span gate
# FLAGS collapse-into-cloud degeneracy but never acts on it (0082,
# flag-only) — and on the reviewed rooms it did not even fire for the
# 0.245 m "television" the operator found hanging in the air where a monitor
# should be. Flagging is not fixing: a 24 cm television is not a
# small television, it is a failed reconstruction, and shipping it as
# placed asserts a measurement nobody made.
#
# So: for labels whose real-world size has an unambiguous floor, an object
# whose LONGEST extent falls below it is demoted to honest inventory
# rather than rendered. Never a rescale — there is no measurement to
# rescale TO; the house rule is that a guessed transform is never emitted.
# Box-anchored objects are exempt: their extents are RoomPlan measurement.
# The map is deliberately short — only classes where the floor cannot be
# argued with. A doll's-house prop of any of these is a mislabel anyway.
_LABEL_SCALE_FLOOR_M = _parse_scale_floors(
    os.environ.get("PLACEMENT_LABEL_SCALE_FLOOR_M", _LABEL_SCALE_FLOOR_DEFAULT)
)

# Support snap v2 (decision 0104): the surfaces a small object may rest on
# when NO RoomPlan box covers it. 0082 deferred these deliberately — "an
# unmeasured support surface would move one estimate onto another" — and
# the acceptance review (decision 0085) collected the bill: the lamp and
# the TV never rest, because the nightstand beneath them is a depth_fit
# object with no box, so v1 had nothing to snap to. Measured on the
# reviewed rooms: the monitor floats 0.221 m above the table it belongs
# on, the lamp sinks 0.058 m into the nightstand.
#
# The v1 objection stands and is answered by ORDERING, not by ignoring it:
# a measured box top always wins over a splat top when both are in reach,
# so a splat surface is consulted only where measurement is silent. The
# supporter must itself be a furniture class that HAS a top surface — a
# lamp never supports a TV.
_SUPPORT_SURFACE_CLASSES = frozenset(
    s.strip().lower()
    for s in os.environ.get(
        "PLACEMENT_SUPPORT_SURFACE_CLASSES",
        "table,desk,nightstand,cabinet,dresser,bookshelf,shelf,sideboard,console,stand",
    ).split(",")
    if s.strip()
)
# The same rule in RoomPlan's own vocabulary, for the measured half of the
# surface set. RoomPlan files every one of the SAM labels above as either
# `table` or `storage`, so this is that list translated, not a second
# policy — and it is the SAME question box_placement asks when it decides
# which face of a box an under-filling splat is seated against, so it has
# one home there rather than a copy here.
_SUPPORT_BOX_CATEGORIES = box_placement.SURFACE_TOP_CATEGORIES
# Percentile for a splat's top surface — the extreme max is a stray
# gaussian, the same reason extents are percentile-clipped everywhere else.
_SUPPORT_SPLAT_TOP_PCTL = float(
    os.environ.get("PLACEMENT_SUPPORT_SPLAT_TOP_PCTL", "98")
)
# Its mirror on the resting object's underside — measured 12 mm of stray
# tail below the reviewed monitors, which the raw minimum turns into
# 12 mm of hover.
_SUPPORT_SPLAT_BOTTOM_PCTL = float(
    os.environ.get("PLACEMENT_SUPPORT_SPLAT_BOTTOM_PCTL", "2")
)
# How far a box-anchored splat's rendered top may stand proud of the
# measured box top before the measurement is trusted instead. Matches the
# splat-clip margin: past it nothing is rendered anyway.
_SUPPORT_TOP_MAX_PROUD_M = float(
    os.environ.get("PLACEMENT_SUPPORT_TOP_MAX_PROUD_M", "0.10")
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
        single-view contact-prior placement (decision 0067). Absent
        or empty (no plane anchors in the bundle) → priors inert, single-
        view objects stay insufficient_observations (the degrade lock).
    get_roomplan() -> roomplan_room.RoomPlanRoom | None — optional; the
        scene's parsed CapturedRoom (decision 0077). Present and non-None →
        the census-aware pass runs: box association + box-anchored objects
        for covered categories, plus the three LIDAR_ROOMPLAN long-tail
        gates (cross-label dedup, mirror depth-trust, textile span). Absent
        or None → fusion reproduces the pre-0077 behaviour byte-for-byte
        (the no-CapturedRoom degrade lock, test-pinned).
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
    # (depth_raster, depth_confidence, depth_intrinsics) | None — the
    # frame's LiDAR payload, for the box-axis cloud scorer (decision 0081).
    # Captures-bucket sourced like get_rgb: a swept capture degrades the
    # scorer to the up-filtered extent default, recorded, never a crash.
    get_depth: Optional[Callable[[int], Optional[tuple]]] = None
    get_room_planes: Optional[Callable[[], Any]] = None
    get_roomplan: Optional[Callable[[], Any]] = None
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
# LIDAR_ROOMPLAN long-tail gates (decision 0077; active only with a parsed
# CapturedRoom — see the knob block for the measured cases)
# -----------------------------------------------------------------------------

def _mask_near_identity(mask_a: np.ndarray, mask_b: np.ndarray) -> float:
    """Intersection-over-LARGER: 1.0 only for near-identical regions. A
    nested pair (small inside big) scores low here even though
    intersection-over-smaller is 1.0 — the protection the cross-label
    dedup needs against absorbing genuinely different nested objects."""
    a = np.asarray(mask_a, dtype=bool)
    b = np.asarray(mask_b, dtype=bool)
    area_a, area_b = int(a.sum()), int(b.sum())
    if area_a == 0 or area_b == 0:
        return 0.0
    inter = int(np.logical_and(a, b).sum())
    return inter / max(area_a, area_b)


def _dedup_cross_label(
    observations: list[dict], ctx: RefinementContext
) -> tuple[list[dict], list[dict]]:
    """Collapse same-frame near-identical masks ACROSS labels (gate i —
    the f242 triple: one ~20k px region shipped three times as artwork /
    painting / mirror, pairwise IoS 0.999). Union-find over pairs whose
    intersection-over-larger clears the identity bar; each group keeps its
    best-scoring observation (label included) verbatim. Runs BEFORE the
    label split, so a collapsed group never seeds objects under several
    labels."""
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
        parent = list(range(n))

        def find(i: int) -> int:
            while parent[i] != i:
                parent[i] = parent[parent[i]]
                i = parent[i]
            return i

        for i in range(n):
            for j in range(i + 1, n):
                if _mask_near_identity(masks[i], masks[j]) >= _CROSS_LABEL_DEDUP_IDENTITY:
                    parent[find(j)] = find(i)

        groups: dict[int, list[int]] = {}
        for i in range(n):
            groups.setdefault(find(i), []).append(i)
        for members in groups.values():
            if len(members) == 1:
                keep.append(group[members[0]])
                continue
            best = max(members, key=lambda k: (group[k]["score"], -k))
            keep.append(group[best])
            for k in members:
                if k != best:
                    records.append({
                        "frame_index": frame_index,
                        "kept_mask_index": group[best]["mask_index"],
                        "absorbed_mask_index": group[k]["mask_index"],
                        "absorbed_label": group[k].get("label"),
                    })
    return keep, records


def _demote_untrusted_depth(
    observations: list[dict], ctx: RefinementContext
) -> tuple[list[dict], set]:
    """Gate ii: strip the depth placement from observations whose NN-polish
    RMS is out of family (specular surfaces — the real mirror's 0.196 m vs
    0.007 m typical). The observation keeps its view ray and layout
    rotation, so it flows down the ray path where triangulation or the
    wall-contact prior (mirror IS a wall class) can still place it against
    something measured — a bad depth fit is never rendered. Returns the
    demoted (frame, mask) keys so fused objects can carry the flag."""
    out: list[dict] = []
    demoted: set = set()
    for o in observations:
        pl = o.get("placement") or {}
        rms = (pl.get("quality") or {}).get("nn_rms_m")
        if not (
            pl.get("placed")
            and rms is not None
            and rms > _DEPTH_TRUST_RMS_M
            and o.get("view_ray")
        ):
            out.append(o)
            continue
        new_pl: dict = {
            "placed": False,
            "reason": "depth_untrusted",
            "depth_trust_demoted": True,
            "layout_prior": pl.get("layout_prior"),
            "quality": dict(pl.get("quality") or {}),
        }
        wt = pl.get("world_transform") or {}
        if wt.get("rotation_xyzw") and pl.get("rotation_source") == "sam3d_layout":
            new_pl["world_rotation_xyzw"] = wt["rotation_xyzw"]
            new_pl["rotation_source"] = "sam3d_layout"
        splat = ctx.get_splat(o["splat_gcs_uri"])
        if splat is not None:
            try:
                new_pl["splat_max_extent"] = float(
                    robust_cloud_stats(splat).extents[0]
                )
            except DegenerateGeometryError:
                pass
        logger.info(
            "fusion: depth-trust demotion frame=%s mask=%s label=%s nn_rms=%.3f",
            o["frame_index"], o.get("mask_index"), o.get("label"), rms,
        )
        out.append({**o, "placement": new_pl})
        demoted.add((o["frame_index"], o.get("mask_index")))
    return out, demoted


def _apply_silhouette_span(obj: dict, ctx: RefinementContext) -> dict:
    """Gate iii: flag a placed depth_fit object whose projected splat
    covers a suspiciously small fraction of its own mask's extent (the
    collapse-into-cloud degeneracy). Flag-only: scale_suspect + the
    measured ratio; the transform is never mutated. A no-op (silent) when
    any evidence is missing."""
    if not obj.get("placed") or obj.get("method") != "depth_fit":
        return obj
    src = obj.get("source") or {}
    frame_index, mask_index = src.get("frame_index"), src.get("mask_index")
    evidence = ctx.evidence_for(frame_index, mask_index)
    cam = ctx.get_camera(frame_index)
    splat = ctx.get_splat(obj.get("splat_gcs_uri"))
    wt = obj.get("world_transform") or {}
    if evidence is None or cam is None or splat is None or not wt:
        return obj
    if evidence.bounds is None:
        return obj
    pose, intrinsics = cam
    world = reproject.transform_points(
        splat, wt["rotation_xyzw"], wt["position"], wt["scale"]
    )
    uv, _depth, valid = project_points(world, intrinsics, pose)
    if int(valid.sum()) < 3:
        return obj
    uv = uv[valid]
    proj_span = float(max(uv[:, 0].max() - uv[:, 0].min(), uv[:, 1].max() - uv[:, 1].min()))
    u0, v0, u1, v1 = evidence.bounds
    mask_span = float(max(u1 - u0, v1 - v0))
    if mask_span <= 0.0:
        return obj
    ratio = proj_span / mask_span
    obj = dict(obj)
    quality = dict(obj.get("quality", {}))
    quality["silhouette_span_ratio"] = round(ratio, 4)
    obj["quality"] = quality
    if ratio < _SPAN_MIN:
        obj["scale_suspect"] = True
        logger.info(
            "fusion: silhouette-span flag %s (%s) ratio=%.3f",
            obj.get("object_id"), obj.get("label"), ratio,
        )
    return obj


# -----------------------------------------------------------------------------
# Post-fusion placement passes (decision 0082): cross-label 3D duplicates,
# wall anchoring + floor declip, door-geometry opening demotion, support snap
# -----------------------------------------------------------------------------

def _sampled_world_points(obj: dict, ctx: RefinementContext, cap: int = 600):
    """Deterministically subsampled world-frame splat points of a placed
    object, or None when its splat/transform is unavailable."""
    wt = obj.get("world_transform") or {}
    if not wt or obj.get("splat_gcs_uri") is None:
        return None
    splat = ctx.get_splat(obj["splat_gcs_uri"])
    if splat is None:
        return None
    n = splat.shape[0]
    if n > cap:
        splat = splat[np.unique(np.linspace(0, n - 1, cap).astype(int))]
    return reproject.transform_points(
        splat, wt["rotation_xyzw"], wt["position"], wt["scale"]
    )


def _containment_in_object(pts: np.ndarray, obj: dict, ctx: RefinementContext) -> float:
    """Fraction of pts inside obj's volume: the exact oriented box for a
    box-anchored object (its RoomPlan box is the measured volume), a padded
    world AABB of its own sampled points otherwise."""
    rb = obj.get("roomplan_box")
    if rb:
        R = _yaw_rotation(float(rb["yaw_rad"]))
        t = np.asarray(rb["center_world"], dtype=np.float64)
        half = np.asarray(rb["dims"], dtype=np.float64) / 2.0
        local = (pts - t) @ R
        return float(np.all(np.abs(local) <= half + 1e-6, axis=1).mean())
    own = _sampled_world_points(obj, ctx)
    if own is None or own.shape[0] < 8:
        return 0.0
    lo = own.min(axis=0) - 0.05
    hi = own.max(axis=0) + 0.05
    return float(np.all((pts >= lo) & (pts <= hi), axis=1).mean())


def _yaw_rotation(yaw_rad: float) -> np.ndarray:
    """world_from_local for a pure-yaw box, roomplan_room's yaw convention
    (heading of local +X: yaw = atan2(x.z, x.x))."""
    c, s = math.cos(yaw_rad), math.sin(yaw_rad)
    return np.array([[c, 0.0, -s], [0.0, 1.0, 0.0], [s, 0.0, c]])


def _grouping_key(label: str | None) -> str:
    """The key one physical object's observations must share (0149).

    Grouping by the raw label forks an object whose label is not stable
    across frames — and SAM's is not. rp7's monitor is detected as both
    `monitor` and `tv` in all three frames that see it, and the same-frame
    cross-label collapse keeps whichever scored higher IN THAT FRAME:
    `monitor` at f7, `tv` at f114 and f385. The collapse's own contract is
    that a collapsed group "never seeds objects under several labels",
    which holds inside a frame and fails across them — so the label split
    then made three views of one monitor into a one-view `monitor` and a
    two-view `tv`, and the pipeline shipped the smallest reconstruction of
    the three while the best was demoted by the tv scale floor.

    So confusable labels share a key, and the fused object still takes its
    NAME from its best-scoring member — nothing is renamed, and two
    genuinely different tables stay apart because the proximity clustering
    below separates them exactly as it always has.
    """
    key = (label or "").strip().lower()
    for grp in _CROSS_LABEL_3D_GROUPS:
        if key in grp:
            return "grp:" + min(grp)
    return key


def _dedup_same_frame_per_label(
    observations: list[dict], ctx: RefinementContext
) -> tuple[list[dict], list[dict]]:
    """`_dedup_same_frame`, applied within each RAW label.

    Grouping by confusable family (0149) is about which observations can
    describe one object across FRAMES. The same-frame nested-pair dedup
    asks a different question — is this a duplicate detection of the same
    thing in this one frame — and its test, containment of the smaller,
    says yes to any nested pair. Run across labels it would absorb a small
    object genuinely sitting inside a larger different-label one, which
    the same-frame CROSS-label collapse already refuses by using
    containment of the LARGER. Keeping this one per-label preserves both
    tests exactly as they were written.
    """
    by_label: dict[str, list[dict]] = {}
    for o in observations:
        by_label.setdefault((o.get("label") or "").strip().lower(), []).append(o)
    kept: list[dict] = []
    records: list[dict] = []
    for label in sorted(by_label):
        k, r = _dedup_same_frame(by_label[label], ctx)
        kept.extend(k)
        records.extend(r)
    kept.sort(key=lambda o: -o["score"])
    return kept, records


def _labels_confusable(a: str | None, b: str | None) -> bool:
    la = (a or "").strip().lower()
    lb = (b or "").strip().lower()
    if not la or not lb:
        return False
    if la == lb:
        return True
    return any(la in grp and lb in grp for grp in _CROSS_LABEL_3D_GROUPS)


def _duplicate_priority(obj: dict) -> tuple:
    """Higher wins a duplicate pair: measured box first, then a measured-
    surface contact placement, then detection score; object_id breaks ties
    deterministically."""
    return (
        1 if obj.get("roomplan_box") else 0,
        1 if obj.get("position_source") in _CONTACT_POSITION_SOURCES else 0,
        float((obj.get("quality") or {}).get("score") or 0.0),
        obj.get("object_id") or "",
    )


def _dedup_cross_label_3d(fused: list[dict], ctx: RefinementContext) -> None:
    """Walk class 2: collapse placed objects whose VOLUMES coincide under
    confusable (or identical) labels — the cross-frame duplicates the
    same-frame mask gates can't reach. Two box-anchored objects never
    dedup (RoomPlan measured two boxes = two real objects). In place."""
    placed = [i for i, o in enumerate(fused) if o.get("placed")]
    pts_cache: dict[int, Any] = {}

    def _pts(i: int):
        if i not in pts_cache:
            pts_cache[i] = _sampled_world_points(fused[i], ctx)
        return pts_cache[i]

    demoted: set[int] = set()
    for ai in range(len(placed)):
        for bi in range(ai + 1, len(placed)):
            i, j = placed[ai], placed[bi]
            if i in demoted or j in demoted:
                continue
            a, b = fused[i], fused[j]
            if a.get("roomplan_box") and b.get("roomplan_box"):
                continue
            if not _labels_confusable(a.get("label"), b.get("label")):
                continue
            pa, pb = _pts(i), _pts(j)
            frac_ab = _containment_in_object(pa, b, ctx) if pa is not None else 0.0
            frac_ba = _containment_in_object(pb, a, ctx) if pb is not None else 0.0
            if max(frac_ab, frac_ba) < _CROSS_LABEL_3D_MIN:
                continue
            keep_i = i if _duplicate_priority(a) >= _duplicate_priority(b) else j
            drop_i = j if keep_i == i else i
            dropped = fused[drop_i]
            out = _demote_object(dropped, "cross_label_duplicate")
            out["suppressed_by"] = fused[keep_i].get("object_id")
            out["cross_label_containment"] = round(max(frac_ab, frac_ba), 4)
            if "deduped_observations" in dropped:
                out["deduped_observations"] = dropped["deduped_observations"]
            logger.info(
                "fusion: cross-label 3D duplicate %s (%s) -> kept %s (%s) cont=%.2f",
                dropped.get("object_id"), dropped.get("label"),
                fused[keep_i].get("object_id"), fused[keep_i].get("label"),
                max(frac_ab, frac_ba),
            )
            fused[drop_i] = out
            demoted.add(drop_i)


def _fusion_walls(ctx: RefinementContext, room) -> list:
    """The measured wall set placement passes snap against: the CapturedRoom
    walls (interior-oriented adapter geoms) when a parsed room carries any,
    else the anchor-plane walls. Same ShellPlaneGeom-shaped frames either
    way. Duck-typed defensively — census test stubs (and any future partial
    room object) may carry only `objects`."""
    if room is not None and getattr(room, "walls", None):
        import roomplan_room as roomplan_room_mod

        try:
            walls = roomplan_room_mod.roomplan_wall_geoms(room)
        except Exception:
            logger.warning("fusion: roomplan wall geoms failed", exc_info=True)
            walls = []
        if walls:
            return walls
    planes = _room_planes(ctx)
    return list(getattr(planes, "walls", []) or [])


def _center_in_wall_rect(center: np.ndarray, wall, pad: float) -> tuple[float, bool]:
    """(signed distance to plane, projects-inside-rect±pad)."""
    rel = center - wall.origin
    d = float(np.dot(rel, wall.normal))
    u = float(np.dot(rel, wall.axis_u))
    v = float(np.dot(rel, wall.axis_v))
    inside = (-pad <= u <= wall.width_m + pad) and (-pad <= v <= wall.height_m + pad)
    return d, inside


def _snap_wall_class_object(obj: dict, walls: list, ctx: RefinementContext) -> dict:
    """Walk class 3: anchor a wall-class object's BACK FACE onto its wall.
    Applies only to free placements (depth/triangulated/silhouette); the
    contact paths and box anchors already sit on measured geometry. The
    rotation may align to the wall normal (planar splats within
    _WALL_ALIGN_MAX_DEG — solve_wall_contact's own convention); the
    position shifts along the wall normal so the rearmost splat point
    touches the plane. Bounded; a no-op when no wall is near."""
    label = (obj.get("label") or "").strip().lower()
    if label not in contact_priors._WALL_CLASSES:
        return obj
    if obj.get("roomplan_box") or obj.get("position_source") in _CONTACT_POSITION_SOURCES:
        return obj
    wt = dict(obj.get("world_transform") or {})
    if not wt or not walls:
        return obj
    center = np.asarray(wt["position"], dtype=np.float64)
    best = None
    for wall in walls:
        d, inside = _center_in_wall_rect(center, wall, _WALL_SNAP_RECT_PAD_M)
        if not inside or abs(d) > _WALL_SNAP_NEAR_M:
            continue
        if best is None or abs(d) < abs(best[0]):
            best = (d, wall)
    if best is None:
        return obj
    _d, wall = best
    splat = ctx.get_splat(obj.get("splat_gcs_uri")) if obj.get("splat_gcs_uri") else None
    if splat is None:
        return obj

    constraints = list(obj.get("constraints_applied") or [])
    quality = dict(obj.get("quality") or {})
    aligned = False
    R_world = quat_to_rotmat(tuple(wt["rotation_xyzw"]))
    if reproject.is_planar(splat):
        try:
            stats = robust_cloud_stats(splat)
            obj_normal_world = R_world @ stats.axes[:, 2]
            obj_normal_world /= np.linalg.norm(obj_normal_world)
            cos = float(np.dot(obj_normal_world, wall.normal))
            n_signed = wall.normal if cos >= 0.0 else -wall.normal
            angle_deg = math.degrees(math.acos(min(1.0, abs(cos))))
            if angle_deg <= _WALL_ALIGN_MAX_DEG and angle_deg > 0.5:
                R_align = minimal_rotation(obj_normal_world, n_signed)
                R_world = R_align @ R_world
                wt["rotation_xyzw"] = [
                    float(c) for c in rotmat_to_quat(R_world)
                ]
                aligned = True
        except (DegenerateGeometryError, ValueError):
            pass

    world_pts = reproject.transform_points(
        splat, wt["rotation_xyzw"], center, wt["scale"]
    )
    d_pts = (world_pts - wall.origin) @ wall.normal
    back = float(d_pts.min())
    shift = -back  # move so the rearmost point sits ON the plane
    if abs(shift) < 0.01 or abs(shift) > _WALL_SNAP_MAX_M:
        if not aligned:
            return obj
        shift = 0.0
    if shift:
        center = center + shift * wall.normal
        wt["position"] = [float(c) for c in center]
        quality["wall_snap_m"] = round(shift, 4)
        constraints.append("wall_back_face")
    if aligned and "wall_normal" not in constraints:
        constraints.append("wall_normal")
    out = dict(obj)
    out["world_transform"] = wt
    out["constraints_applied"] = constraints
    out["quality"] = quality
    if shift or aligned:
        logger.info(
            "fusion: wall snap %s (%s) shift=%.3f aligned=%s",
            obj.get("object_id"), obj.get("label"), shift, aligned,
        )
    return out


def _declip_floor_class_object(obj: dict, walls: list, ctx: RefinementContext) -> dict:
    """Walk class 3, second half: a floor-class splat clipping through a
    measured wall beyond tolerance is pushed back into the room along that
    wall's normal (bounded). Box-anchored objects are exempt — their
    position is RoomPlan measurement; residual overflow there is splat
    truncation (class 6), not a placement error."""
    label = (obj.get("label") or "").strip().lower()
    if label not in contact_priors._FLOOR_CLASSES:
        return obj
    if obj.get("roomplan_box") or obj.get("position_source") in _CONTACT_POSITION_SOURCES:
        return obj
    wt = dict(obj.get("world_transform") or {})
    if not wt or not walls:
        return obj
    center = np.asarray(wt["position"], dtype=np.float64)
    pts = _sampled_world_points(obj, ctx)
    if pts is None:
        return obj
    worst = None
    for wall in walls:
        d_c, inside = _center_in_wall_rect(center, wall, _WALL_SNAP_RECT_PAD_M)
        if not inside or d_c <= 0.0:
            continue  # center must be on the interior side of this wall
        pen = -float(((pts - wall.origin) @ wall.normal).min())
        if pen > _WALL_PENETRATION_TOL_M and (worst is None or pen > worst[0]):
            worst = (pen, wall)
    if worst is None:
        return obj
    pen, wall = worst
    shift = min(pen - _WALL_PENETRATION_TOL_M, _WALL_DECLIP_MAX_M)
    center = center + shift * wall.normal
    out = dict(obj)
    wt["position"] = [float(c) for c in center]
    out["world_transform"] = wt
    quality = dict(out.get("quality") or {})
    quality["wall_declip_m"] = round(shift, 4)
    out["quality"] = quality
    constraints = list(out.get("constraints_applied") or [])
    constraints.append("wall_declip")
    out["constraints_applied"] = constraints
    logger.info(
        "fusion: wall declip %s (%s) by %.3f m", obj.get("object_id"),
        obj.get("label"), shift,
    )
    return out


def _demote_on_opening_geometry(obj: dict, room) -> dict:
    """Walk class 4: a storage-ish placed object sitting ON a RoomPlan
    door/window surface is that opening mislabeled — demote exactly like
    the label rule (same reason string; the shell already renders the
    opening). Geometry-keyed, so a door SAM calls "cabinet" demotes too."""
    if room is None or not obj.get("placed") or obj.get("roomplan_box"):
        return obj
    label = (obj.get("label") or "").strip().lower()
    if label not in _OPENING_GEOM_CLASSES:
        return obj
    wt = obj.get("world_transform") or {}
    pos = wt.get("position")
    if pos is None:
        return obj
    center = np.asarray(pos, dtype=np.float64)
    surfaces = (*getattr(room, "doors", []), *getattr(room, "windows", []))
    for surface in surfaces:
        poly = surface.polygon_world
        R = surface.transform[:3, :3]
        origin = poly.mean(axis=0)
        normal = R[:, 2]
        d = float(np.dot(center - origin, normal))
        if abs(d) > _OPENING_GEOM_NEAR_M:
            continue
        u = (poly - origin) @ R[:, 0]
        v = (poly - origin) @ R[:, 1]
        cu = float(np.dot(center - origin, R[:, 0]))
        cv = float(np.dot(center - origin, R[:, 1]))
        pad = _OPENING_GEOM_RECT_PAD_M
        if (u.min() - pad <= cu <= u.max() + pad) and (v.min() - pad <= cv <= v.max() + pad):
            logger.info(
                "fusion: demoting %s (%s) -> opening geometry (%s %s)",
                obj.get("object_id"), obj.get("label"), surface.kind,
                surface.identifier,
            )
            out = _demote_object(obj, "represented_as_shell_opening")
            out["opening_surface"] = surface.identifier
            if "deduped_observations" in obj:
                out["deduped_observations"] = obj["deduped_observations"]
            return out
    return obj


def _apply_label_scale_floor(obj: dict) -> dict:
    """Walk class 4: demote a placed object whose longest extent is below
    the unambiguous floor for its label — a collapsed reconstruction, not a
    small object. Pure (no ctx, no IO); box-anchored objects are exempt
    because their extents are RoomPlan measurement."""
    if not obj.get("placed") or obj.get("roomplan_box"):
        return obj
    floor = _LABEL_SCALE_FLOOR_M.get((obj.get("label") or "").strip().lower())
    if floor is None:
        return obj
    extents = obj.get("extent_m_sorted") or []
    if not extents:
        return obj
    longest = float(extents[0])
    if longest >= floor:
        return obj
    logger.info(
        "fusion: demoting %s (%s) -> implausible_scale_for_label "
        "longest=%.3f floor=%.2f",
        obj.get("object_id"), obj.get("label"), longest, floor,
    )
    out = _demote_object(obj, "implausible_scale_for_label")
    quality = dict(out.get("quality") or {})
    quality["longest_extent_m"] = round(longest, 4)
    quality["label_scale_floor_m"] = floor
    out["quality"] = quality
    if "deduped_observations" in obj:
        out["deduped_observations"] = obj["deduped_observations"]
    return out


def _clipped_world_points(obj: dict, ctx: RefinementContext, cap: int = 600):
    """An object's world points as RENDERED — i.e. with its declared
    `splat_clip` volume applied (decision 0104). Consumers that care what
    the user actually sees must use this; the raw points remain right for
    anything reasoning about the reconstruction itself."""
    pts = _sampled_world_points(obj, ctx, cap)
    clip = obj.get("splat_clip")
    if pts is None or not clip:
        return pts
    try:
        center = np.asarray(clip["center_world"], dtype=np.float64)
        half = np.asarray(clip["half_extents_m"], dtype=np.float64)
        yaw = float(clip["yaw_rad"])
    except (KeyError, TypeError, ValueError):
        return pts
    c, s = np.cos(yaw), np.sin(yaw)
    R = np.array([[c, 0.0, s], [0.0, 1.0, 0.0], [-s, 0.0, c]])
    local = (pts - center) @ R
    inside = np.all(np.abs(local) <= half, axis=1)
    return pts[inside] if int(inside.sum()) >= 8 else pts


def _bottom_of(obj: dict, ctx: RefinementContext) -> float:
    """The height at which an object meets whatever it rests on — the same
    percentile the snap reasons about, not the extreme point."""
    pts = _clipped_world_points(obj, ctx)
    return float(np.percentile(pts[:, 1], _SUPPORT_SPLAT_BOTTOM_PCTL))


def _bottom_flatness(pts: np.ndarray) -> float:
    """Height range of the lowest decile of an object's mass, in metres.

    This is "touches at one point" as a number: a levelled object with a
    flat underside puts its whole bottom decile at one height, while a
    tilted one spreads it over the drop across its footprint.
    """
    y = np.asarray(pts, dtype=np.float64)[:, 1]
    return float(np.percentile(y, 10.0) - np.percentile(y, 1.0))


def _principal_axes(pts: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """(3x3 columns = principal axes, (3,) extents), descending by extent."""
    centred = pts - pts.mean(axis=0)
    _vals, vecs = np.linalg.eigh(centred.T @ centred)
    proj = centred @ vecs
    ext = np.percentile(proj, 98.0, axis=0) - np.percentile(proj, 2.0, axis=0)
    order = np.argsort(ext)[::-1]
    return vecs[:, order], ext[order]


def _upright_axis_from_cloud(obj: dict, ctx: RefinementContext):
    """Which of an object's axes is vertical, read off its own measured
    LiDAR surface — or None when the surface cannot say.

    The splat's own mass is the wrong place to ask. Its canonical frame is
    arbitrary per reconstruction and its extents are truncated, so "the
    principal axis nearest vertical" is a minimal-motion heuristic, not a
    reading: on the spike room's speaker it picks a middle axis 40 degrees
    out and stands the speaker on an edge, when the object lies flat on its
    largest face in the capture photo.

    The observation's cloud has neither problem. It is metric, it is in the
    world frame by construction, and it is a direct measurement of the
    surface the object presents. On the same speaker it puts the THINNEST
    axis 7.0 degrees off vertical with the next axis 83 degrees away — an
    unambiguous statement that the object is lying down.

    Returns (rank, tilt_deg): which extent-rank of the object is vertical,
    and how convincingly. The splat's axis of the same rank is the one to
    stand up. Both the cloud's confidence and the rank's distinctness are
    gated, because a rank that is ambiguous in one point set cannot be
    matched into the other.
    """
    src = obj.get("source") or {}
    fi, mi = src.get("frame_index"), src.get("mask_index")
    if fi is None:
        return None
    cloud = box_placement.observation_cloud_from_ctx(ctx, fi, mi)
    if cloud is None or cloud.shape[0] < _LEVEL_MIN_CLOUD_POINTS:
        return None
    _axes, ext = _principal_axes(cloud)
    tilts = [
        float(np.degrees(np.arccos(np.clip(abs(_axes[1, i]), 0.0, 1.0))))
        for i in range(3)
    ]
    rank = int(np.argmin(tilts))
    nearest = tilts[rank]
    runner_up = min(t for i, t in enumerate(tilts) if i != rank)
    if nearest > _LEVEL_CLOUD_MAX_TILT_DEG:
        return None  # the surface does not show a level object
    if runner_up - nearest < _LEVEL_CLOUD_MARGIN_DEG:
        return None  # two axes equally vertical: which one is a guess
    if not _rank_is_distinct(ext, rank):
        return None
    return rank, nearest


def _rank_is_distinct(ext: np.ndarray, rank: int) -> bool:
    """Whether the extent at `rank` is separated from its neighbours enough
    to be matched between two point sets by ordering alone."""
    for j in (rank - 1, rank + 1):
        if 0 <= j < 3:
            hi = max(float(ext[rank]), float(ext[j]))
            if hi <= 0 or abs(float(ext[rank]) - float(ext[j])) / hi < _LEVEL_RANK_SEP:
                return False
    return True


def _level_upright_object(obj: dict, ctx: RefinementContext) -> dict:
    """Stand an upright-resting object up (decision 0147).

    The 0104 support snap is height-only, so an object landed exactly on a
    measured surface still meets it at whatever tilt its rotation carried:
    the acceptance walk found four objects at the right height touching at
    a point, and the worst of them — a soundbar that stands vertically in
    its own capture photo — ships lying at 40 degrees.

    Tilt is NOT the degree of freedom three instrument families are
    measured dead on (0081, 0104). Those attack the splat canonical
    frame's axis ASSIGNMENT and its 180 degree yaw sign, where the only
    evidence is appearance or a thin single-view cloud. Tilt is rotation
    about a HORIZONTAL axis, and it has an independent physical prior that
    those never had: gravity, for a class of object whose whole
    relationship with the room is that it rests on something level.

    Which of the object's axes is vertical is read off its own measured
    LiDAR surface (`_upright_axis_from_cloud`), and the correction is the
    minimal rotation taking the splat's axis of that same extent-rank onto
    world up — so the object moves by exactly the measured tilt and never
    further. Without a usable cloud the pass degrades to the splat's own
    nearest-vertical axis, which is a heuristic and is bounded much more
    tightly for that reason.

    Two gates, because a rotation is a claim:
      * class — only classes that rest on something level. Wall and
        hanging classes are excluded by construction: an artwork's
        relationship is with a measured wall (`_snap_wall_class_object`),
        not with gravity, and levelling them measured actively WORSE.
      * evidence — the underside must measurably flatten. A correction
        that does not is discarded, so a mis-identified vertical axis
        costs nothing. This is chunk D's rule (a proposed transform ships
        only if the evidence improves) applied to rotation.
    """
    label = (obj.get("label") or "").strip().lower()
    if label not in _LEVEL_CLASSES:
        return obj
    if obj.get("roomplan_box") or not obj.get("placed"):
        return obj  # box rotations are RoomPlan measurement: pure yaw already
    wt = dict(obj.get("world_transform") or {})
    if not wt:
        return obj
    pts = _clipped_world_points(obj, ctx, cap=_LEVEL_POINT_CAP)
    if pts is None or pts.shape[0] < _LEVEL_MIN_POINTS:
        return obj

    centre = pts.mean(axis=0)
    axes, _ext = _principal_axes(pts)
    up = np.array([0.0, 1.0, 0.0])
    measured = _upright_axis_from_cloud(obj, ctx)
    if measured is not None:
        rank, _cloud_tilt = measured
        source, limit = "lidar_cloud", 90.0
        axis = max((axes[:, rank], -axes[:, rank]), key=lambda v: float(v[1]))
    else:
        # No usable surface: fall back to the splat's own nearest-vertical
        # axis. That is minimal-motion, not a reading, so it is bounded at
        # the furthest a coordinate axis can sit from the nearest world one.
        source, limit = "splat_mass", _LEVEL_MAX_DEG
        axis = max(
            (s * axes[:, i] for i in range(3) for s in (1.0, -1.0)),
            key=lambda v: float(v[1]),
        )
    tilt_deg = float(np.degrees(np.arccos(np.clip(float(axis[1]), -1.0, 1.0))))
    if tilt_deg < _LEVEL_MIN_DEG or tilt_deg > limit:
        return obj

    R_level = minimal_rotation(axis, up)
    before = _bottom_flatness(pts)
    after = _bottom_flatness((pts - centre) @ R_level.T + centre)
    if after > before - max(_LEVEL_MIN_GAIN_M, _LEVEL_MIN_GAIN_FRAC * before):
        logger.info(
            "fusion: level refused %s (%s) tilt=%.1f flatness %.4f -> %.4f",
            obj.get("object_id"), label, tilt_deg, before, after,
        )
        return obj

    position = np.asarray(wt["position"], dtype=np.float64)
    rotation = quat_to_rotmat(tuple(wt["rotation_xyzw"]))
    out = dict(obj)
    wt["position"] = [float(c) for c in (R_level @ (position - centre) + centre)]
    wt["rotation_xyzw"] = [float(c) for c in rotmat_to_quat(R_level @ rotation)]
    out["world_transform"] = wt
    quality = dict(out.get("quality") or {})
    quality["level_correction_deg"] = round(tilt_deg, 2)
    quality["level_source"] = source
    quality["bottom_flatness_m"] = round(after, 4)
    out["quality"] = quality
    out["constraints_applied"] = [*(out.get("constraints_applied") or []), "levelled"]
    logger.info(
        "fusion: levelled %s (%s) by %.1f deg from %s, flatness %.4f -> %.4f",
        obj.get("object_id"), label, tilt_deg, source, before, after,
    )
    return out


def _support_surfaces(
    fused: list[dict], boxes: list, ctx: RefinementContext
) -> list[dict]:
    """Every surface a small object may come to rest on, built ONCE from
    the pre-snap state so the pass is order-independent (a snap can never
    change what another object rests on).

    The contact height is the top of what is RENDERED, not the top of the
    measurement. The 0085 walk is unambiguous that this is the quantity in
    question: the lamp sat exactly on its nightstand's measured box top and
    the operator still saw it sunk into the nightstand, because the splat
    stands 0.058 m proud of the box. Position and footprint stay measured —
    only the height the object lands at follows the render, which is the
    only thing the complaint was ever about.

    Box-anchored surfaces are listed first and win ties: their footprint
    and centre are RoomPlan measurement, so a splat surface is consulted
    only where measurement is silent (0082's objection, answered by
    ordering rather than ignored).

    A box qualifies on the same rule as a splat: the supporter must be a
    category that HAS a top. The acceptance walk collected the bill for
    leaving that rule off the measured half — rp7's monitor rests on the
    top of the CHAIR tucked under its desk, 0.28 m above the desk it
    belongs on, because a chair's box top was in reach and nearer than the
    desk's (decision 0148)."""
    box_surfaces: list[dict] = []
    splat_surfaces: list[dict] = []
    by_box: dict[str, dict] = {}
    for obj in fused:
        rb = obj.get("roomplan_box")
        if rb and obj.get("placed"):
            by_box[rb["box_id"]] = obj

    for bi, box in enumerate(boxes or []):
        if (box.category or "").strip().lower() not in _SUPPORT_BOX_CATEGORIES:
            continue
        dims = np.asarray(box.dimensions, dtype=np.float64)
        box_top = float(box.center_world[1]) + dims[1] / 2.0
        top = box_top
        obj = by_box.get(f"box_{bi:02d}")
        if obj is not None:
            pts = _clipped_world_points(obj, ctx)
            if pts is not None and pts.shape[0] >= 8:
                rendered = float(np.percentile(pts[:, 1], _SUPPORT_SPLAT_TOP_PCTL))
                # The measured top is the floor of the estimate and the clip
                # margin its ceiling: a splat that under-reaches its box must
                # not drag the surface down below the measurement.
                top = max(box_top, min(rendered, box_top + _SUPPORT_TOP_MAX_PROUD_M))
        box_surfaces.append({"kind": "box", "id": f"box_{bi:02d}", "top": top, "box": box})

    for obj in fused:
        if not obj.get("placed") or obj.get("roomplan_box"):
            continue
        if (obj.get("label") or "").strip().lower() not in _SUPPORT_SURFACE_CLASSES:
            continue
        pts = _clipped_world_points(obj, ctx)
        if pts is None or pts.shape[0] < 8:
            continue
        splat_surfaces.append({
            "kind": "splat",
            "id": str(obj.get("object_id")),
            "top": float(np.percentile(pts[:, 1], _SUPPORT_SPLAT_TOP_PCTL)),
            "lo": pts[:, [0, 2]].min(axis=0),
            "hi": pts[:, [0, 2]].max(axis=0),
        })
    splat_surfaces.sort(key=lambda s: s["id"])
    return box_surfaces + splat_surfaces


def _snap_onto_support(
    obj: dict,
    boxes: list,
    ctx: RefinementContext,
    surfaces: list[dict] | None = None,
) -> dict:
    """Walk class 5: rest a small-class object ON the surface beneath it
    when its bottom hovers or sinks within reach over that surface's
    footprint. Vertical shift only, bounded by construction.

    v1 considered RoomPlan box tops alone. v2 (decision 0104) takes its
    contact heights from `_support_surfaces` — the RENDERED tops — and
    adds the splat tops of placed support-class objects, consulted only
    when no box surface is in reach."""
    label = (obj.get("label") or "").strip().lower()
    if label not in _SUPPORT_CLASSES:
        return obj
    if obj.get("roomplan_box") or not obj.get("placed"):
        return obj
    wt = dict(obj.get("world_transform") or {})
    if not wt:
        return obj
    pts = _clipped_world_points(obj, ctx)
    if pts is None:
        return obj
    # Percentile-clipped at both ends of the contact, for the reason the
    # surface top already is: the extreme point is a stray gaussian. Taken
    # from the raw minimum, a 12 mm tail below the object lifts it 12 mm
    # off the surface it is supposed to be resting on.
    bottom = _bottom_of(obj, ctx)
    center = np.asarray(wt["position"], dtype=np.float64)

    if surfaces is None:
        # Callers that only have boxes (and the v1 tests) still get v1
        # behaviour: measured box tops, no rendered-top adjustment.
        surfaces = [
            {"kind": "box", "id": f"box_{bi:02d}",
             "top": float(b.center_world[1]) + float(b.dimensions[1]) / 2.0,
             "box": b}
            for bi, b in enumerate(boxes or [])
            if (b.category or "").strip().lower() in _SUPPORT_BOX_CATEGORIES
        ]

    best_box = best_splat = None  # (|dy|, dy, source_id)
    for surf in surfaces:
        if surf["kind"] == "box":
            box = surf["box"]
            dims = np.asarray(box.dimensions, dtype=np.float64)
            R = box.transform[:3, :3]
            local = R.T @ (center - np.asarray(box.center_world, dtype=np.float64))
            if (abs(local[0]) > dims[0] / 2.0 + _SUPPORT_XZ_PAD_M
                    or abs(local[2]) > dims[2] / 2.0 + _SUPPORT_XZ_PAD_M):
                continue
        else:
            if surf["id"] == str(obj.get("object_id")):
                continue
            lo, hi = surf["lo"] - _SUPPORT_XZ_PAD_M, surf["hi"] + _SUPPORT_XZ_PAD_M
            if not (lo[0] <= center[0] <= hi[0] and lo[1] <= center[2] <= hi[1]):
                continue
        dy = surf["top"] - bottom
        if dy > _SUPPORT_SNAP_M or -dy > _SUPPORT_DROP_MAX_M:
            continue
        slot = best_box if surf["kind"] == "box" else best_splat
        if slot is None or abs(dy) < slot[0]:
            if surf["kind"] == "box":
                best_box = (abs(dy), dy, surf["id"])
            else:
                best_splat = (abs(dy), dy, surf["id"])

    # A measured box surface wins outright; splat surfaces only where
    # measurement is silent.
    best = best_box or best_splat
    if best is None:
        return obj
    _mag, dy, source = best
    if abs(dy) < 0.005:
        return obj
    out = dict(obj)
    center[1] += dy
    wt["position"] = [float(c) for c in center]
    out["world_transform"] = wt
    quality = dict(out.get("quality") or {})
    quality["support_snap_m"] = round(dy, 4)
    quality["support_box"] = source
    out["quality"] = quality
    constraints = list(out.get("constraints_applied") or [])
    constraints.append("on_top_of")
    out["constraints_applied"] = constraints
    logger.info(
        "fusion: support snap %s (%s) onto %s dy=%.3f",
        obj.get("object_id"), obj.get("label"), source, dy,
    )
    return out


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
    view object (decision 0067). Returns a fully-placed object dict
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
    the single-view measured-surface contact placements are exempt
    (self-gated).

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


def _suppress_as_box_duplicate(obj: dict, box_index: int) -> dict:
    """Demote a placed non-box object that duplicates a matched RoomPlan
    box (decision 0077): the entry stays in the manifest as honest
    provenance, never rendered."""
    out = _demote_object(obj, "box_duplicate")
    out["box_duplicate_suppressed"] = True
    out["suppressed_by_box"] = f"box_{box_index:02d}"
    if "deduped_observations" in obj:
        out["deduped_observations"] = obj["deduped_observations"]
    logger.info(
        "fusion: suppressing %s (%s) as duplicate of box_%02d",
        obj.get("object_id"), obj.get("label"), box_index,
    )
    return out


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

    # --- LIDAR_ROOMPLAN census pass (decision 0077) -------------------------
    # Box association/placement/suppression run only when the scene carries
    # a parsed CapturedRoom. The three measured long-tail gates are NOT
    # census-gated — they run for every refined scene (see below) — so a
    # no-census scene differs from the pre-0077 pass exactly by those
    # gates' effects (the revised degrade pin covers this).
    room = None
    if ctx.get_roomplan is not None:
        try:
            room = ctx.get_roomplan()
        except Exception:
            logger.warning(
                "fusion: get_roomplan failed; census pass skipped", exc_info=True
            )
            room = None
    boxes = list(room.objects) if room is not None else []

    fused: list[dict] = []
    dedup_counts: dict[tuple, int] = {}
    counter = 0
    demoted_keys: set = set()
    matched_box_indices: set[int] = set()

    # The three measured long-tail gates (cross-label near-identity dedup,
    # mirror depth-trust, textile silhouette-span below) run for EVERY
    # refined scene, census or not: they were measured on 247003de, a
    # LIDAR_ARKIT capture census keying would leave unprotected, and
    # cross-label duplicates were also observed on census scenes — so the
    # gates are the floor, not the ceiling. Box passes below stay
    # census-gated: they need boxes.
    observations, cross_records = _dedup_cross_label(observations, ctx)
    for rec in cross_records:
        key = (rec["frame_index"], rec["kept_mask_index"])
        dedup_counts[key] = dedup_counts.get(key, 0) + 1
    observations, demoted_keys = _demote_untrusted_depth(observations, ctx)

    if boxes:
        assoc_by_box = box_placement.associate_observations(boxes, observations, ctx)
        matched_box_indices = set(assoc_by_box)
        consumed: set = set()
        for assocs in assoc_by_box.values():
            for a in assocs:
                consumed.add((a.frame_index, a.mask_index))
        # One object per box, in Apple's array order (deterministic ids).
        for bi, box in enumerate(boxes):
            allow = _budget_allows(ctx)
            if not allow:
                refinement_skipped = True
            obj = box_placement.build_box_object(
                box=box, box_index=bi, object_id=f"obj_{counter:03d}",
                associations=assoc_by_box.get(bi, []), ctx=ctx,
                allow_scoring=allow,
            )
            obj["deduped_observations"] = sum(
                dedup_counts.get((a.frame_index, a.mask_index), 0)
                for a in assoc_by_box.get(bi, [])
            )
            fused.append(obj)
            counter += 1
        # Associated observations are CONSUMED by their box — one object
        # per box by construction; the rest flow through unchanged.
        observations = [
            o for o in observations
            if (o["frame_index"], o.get("mask_index")) not in consumed
        ]

    by_label: dict[str, list[dict]] = {}
    for o in observations:
        by_label.setdefault(_grouping_key(o["label"]), []).append(o)

    for label in sorted(by_label):
        group = sorted(by_label[label], key=lambda o: -o["score"])
        placed = [o for o in group if o["placement"].get("placed")]
        with_rays = [
            o for o in group
            if not o["placement"].get("placed") and o.get("view_ray")
        ]

        placed, placed_dedup = _dedup_same_frame_per_label(placed, ctx)
        with_rays, ray_dedup = _dedup_same_frame_per_label(with_rays, ctx)
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
                # place it (decision 0067). Budget-gated like the
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
            if demoted_keys and any(
                (m["frame_index"], m.get("mask_index")) in demoted_keys
                for m in cluster
            ):
                quality = dict(obj.get("quality") or {})
                quality["depth_trust_demoted"] = True
                obj["quality"] = quality
            fused.append(obj)

    # --- census post-passes (decision 0077) ---------------------------------
    if boxes:
        # Box-duplicate suppression: a placed non-box object whose center
        # lands inside a MATCHED box's volume with a compatible label is
        # the same physical object the box already carries.
        for i, obj in enumerate(fused):
            if obj.get("roomplan_box"):
                continue
            bi = box_placement.find_suppressing_box(obj, boxes, matched_box_indices)
            if bi is not None:
                fused[i] = _suppress_as_box_duplicate(obj, bi)

    # --- post-fusion placement passes (decision 0082) -----------------------
    # Order matters: opening demotion first (a mislabeled door needs no
    # snapping), then the 3D duplicate gate over raw placements, then the
    # geometric snaps (wall back-face / declip / support). All bounded
    # numpy; one budget check for the block keeps the honesty contract.
    # Pure and IO-free, so it runs always-on beside the other long-tail
    # gates (same reasoning: a census-keyed gate leaves LIDAR_ARKIT scenes
    # unprotected) and BEFORE the budget-gated block — a demoted object
    # must not then be snapped onto a support.
    for i in range(len(fused)):
        fused[i] = _apply_label_scale_floor(fused[i])

    if _budget_allows(ctx):
        if room is not None:
            for i in range(len(fused)):
                fused[i] = _demote_on_opening_geometry(fused[i], room)
        _dedup_cross_label_3d(fused, ctx)
        walls = _fusion_walls(ctx, room)
        if walls:
            for i in range(len(fused)):
                if not fused[i].get("placed"):
                    continue
                fused[i] = _snap_wall_class_object(fused[i], walls, ctx)
                fused[i] = _declip_floor_class_object(fused[i], walls, ctx)
        # Levelling precedes both surface construction and the snap: a
        # tilted object's bottom is a corner, so its contact height is only
        # meaningful once it stands up, and a tilted support surface would
        # otherwise hand every object resting on it a wrong top.
        for i in range(len(fused)):
            if fused[i].get("placed"):
                fused[i] = _level_upright_object(fused[i], ctx)
        surfaces = _support_surfaces(fused, boxes, ctx)
        if surfaces:
            for i in range(len(fused)):
                if fused[i].get("placed"):
                    fused[i] = _snap_onto_support(fused[i], boxes, ctx, surfaces)
    else:
        refinement_skipped = True

    for i, obj in enumerate(fused):
        if obj.get("roomplan_box"):
            continue
        fused[i] = _apply_silhouette_span(fused[i], ctx)

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
