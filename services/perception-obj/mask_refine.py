"""Repair a SAM 3 mask that provably cut its object short (decision 0198).

SAM 3D Objects' input is RGBA with **alpha = the SAM mask**
(`models/sam3d.py`), so an incomplete mask deletes from the model's input
what the photograph actually contains. rp7 f114's mask excluded both desk
legs; adding ~3,000 mask pixels took the splat from
`0.983 x 0.212 x 0.718` — a 21 cm slab that cannot be a desk under any
rotation — to `0.983 x 0.655 x 0.444`, a body that renders as a desk with
legs. Same photograph, same seed.

This module holds the geometry and the judgement; the model call itself is
`models.sam3.SAM3Model.refine_mask`, and the wiring is
`process_receiver._maybe_refine_mask`. Three steps, in the order they run:

1. **Detect** — `unclaimed_in_box`. Back-project the frame's LiDAR depth,
   keep the points inside the object's measured RoomPlan box, drop the
   ones lying on a measured wall or floor, and ask which of the remaining
   pixels NO mask in the frame claims. On the two frames the operator
   flagged this reads 0.403 / 0.435 against 0.163 / 0.191 on each object's
   shipped frame — a ~2.4x separation.

2. **Prompt** — `prompt_box_cxcywh`. The positive box is the bbox of
   (own mask u the unclaimed region), normalized cxcywh. It is deliberately
   NOT the measured box's own projected bbox: a box volume legitimately
   contains other objects (a chair tucked under a desk, 0148), and the raw
   box bbox asks SAM 3 to merge them — measured, on rp7 f114, at 113,465 px
   with the chair base and a stool absorbed. Detection and prompt are the
   same computation.

3. **Judge** — `accept_refined`. The detector is not a defect-finder: four
   of six flags in 0198's round 2 were neighbouring clutter or
   unphotographed mass, and its known contaminant is undetected OTHER
   objects, which no threshold on the signal itself can see. So the signal
   is validated AFTER use, on the refined mask: it must have grown, must
   still be the same instance, must contain what it started from, must stay
   inside the measured box, and must not have eaten a neighbouring
   detection. A refusal costs nothing — the original mask is used, which is
   exactly what ships today.

The whole pass is off unless `PERCEPTION_MASK_REFINE=1`.

Consumers: process_receiver (the census two-pass), tests/test_mask_refine.py,
tests/test_mask_refine_real_data.py.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

import numpy as np
from roomstudio_schemas import placement_math as pm

# The pass itself. Off by default: turning it on changes what the model is
# shown on every room, which wants the operator's eyes on more than the
# three objects 0197/0198 fixed by hand.
MASK_REFINE_ENABLED = os.environ.get("PERCEPTION_MASK_REFINE", "0") == "1"

# Flag an object-view when at least this share of its in-box, off-plane
# measured surface is claimed by no mask at all. 0.30 sits below every
# object 0198 refined (0.312-0.673) and above every shipped control it
# measured (0.025-0.268) — but it is a FLAG, not a verdict: the four
# false positives in that set are all above it, and are caught after the
# refinement by accept_refined rather than before it.
MIN_UNCLAIMED_FRACTION = float(
    os.environ.get("PERCEPTION_MASK_REFINE_MIN_UNCLAIMED", "0.30")
)

# ... and only when the evidence is more than a handful of depth pixels.
# The thinnest real flag in 0198's set carried 659.
MIN_UNCLAIMED_PIXELS = int(
    os.environ.get("PERCEPTION_MASK_REFINE_MIN_PIXELS", "200")
)

# Acceptance. Deliberately several cheap tests rather than one clever one:
# each catches a different way the refinement can be wrong, and the one
# that matters most (a neighbour absorbed) is invisible to the others.
MIN_IOU_WITH_ORIGINAL = float(
    os.environ.get("PERCEPTION_MASK_REFINE_MIN_IOU", "0.40")
)
MIN_ORIGINAL_KEPT = float(
    os.environ.get("PERCEPTION_MASK_REFINE_MIN_KEPT", "0.90")
)
MAX_GROWTH_RATIO = float(
    os.environ.get("PERCEPTION_MASK_REFINE_MAX_GROWTH", "2.50")
)
MAX_NEIGHBOUR_ABSORBED = float(
    os.environ.get("PERCEPTION_MASK_REFINE_MAX_ABSORB", "0.20")
)
MIN_NEW_INSIDE_BOX = float(
    os.environ.get("PERCEPTION_MASK_REFINE_MIN_IN_BOX", "0.60")
)

# The load-bearing one. The refinement must have added the structure the
# detector pointed AT — measured as the share of newly-claimed pixels that
# land on the unclaimed region. On the eight refined masks 0198 produced on
# a GPU this is the only test that separates the measured merge from the
# wins: 0.137 for the variant-B merge and 0.075 for the false-positive
# flag, against 0.561-0.813 for every arm that improved or was harmless.
# A 4.1x gap with nothing inside it, stable across a 6x sweep of the block
# size the region is painted with. See docs/decisions/0201.
MIN_ADDED_ON_SIGNAL = float(
    os.environ.get("PERCEPTION_MASK_REFINE_MIN_ON_SIGNAL", "0.35")
)

# Metres of slack when deciding whether a measured point lies on a measured
# wall or floor, and when growing the measured box to admit depth noise.
# Both carried verbatim from the probe that measured the separation above.
ROOM_PLANE_TOL_M = float(
    os.environ.get("PERCEPTION_MASK_REFINE_PLANE_TOL_M", "0.08")
)
# 0.08 LOOKS like a room-scale number misapplied to an object: it reaches 8 cm
# up into every box standing on the floor, which is where feet are, and the
# bottom tenth of nine of eleven legged boxes is empty because of it. A
# box-aware relaxation to 0.02 was built and MEASURED, and it is refused —
# what it restores is the floor, not the feet (decision 0232). The floor's own
# measured spread about the plane is p90 +2.2 to +4.3 cm across the four
# preserved captures, so 0.02 sits INSIDE the noise, and the restored points
# collapse by 96-100% between 0.02 and 0.06 — a thin sheet, where a leg would
# thin out linearly. `_on_room_plane` keeps `floor_tol_m` as a parameter so
# the measurement is one line to reproduce and so a LOCAL floor estimate could
# use it, but no env flag ships: a switch whose measured effect is to feed the
# detector floor is worse than no switch, because it looks live.

BOX_PAD_M = float(os.environ.get("PERCEPTION_MASK_REFINE_BOX_PAD_M", "0.05"))


@dataclass
class UnclaimedSignal:
    """What the frame's own measurements say is inside this box and not in
    anybody's mask. `unclaimed_vu` is on the MASK grid, so it composes with
    the mask stack directly.

    `bands` decomposes the same points by height (decision 0231). `fraction`
    pools the whole box volume, and pooling hides which of two different
    defects produced it:

      * the camera SAW surface in a band and the mask claimed none of it —
        a mask defect, and the one 0198's repair is for;
      * the camera saw NOTHING there — a view defect, which no prompt and no
        repair can reach.

    Both raise `fraction` the same way, and the pooled number cannot tell
    them apart because a band the camera never saw contributes no considered
    pixels at all. A band with zero considered pixels therefore reports
    `None`, never 0.0 — the distinction is the whole point.
    """

    fraction: float
    own_fraction: float
    considered_px: int
    unclaimed_vu: np.ndarray  # (N, 2) int, (row, col) on the mask grid
    # band name -> (considered_px, unclaimed fraction or None)
    bands: dict = field(default_factory=dict)

    @property
    def flagged(self) -> bool:
        return (
            self.considered_px > 0
            and len(self.unclaimed_vu) >= MIN_UNCLAIMED_PIXELS
            and self.fraction >= MIN_UNCLAIMED_FRACTION
        )

    def as_record(self) -> dict:
        rec = {
            "unclaimed_fraction": round(self.fraction, 4),
            "own_fraction": round(self.own_fraction, 4),
            "considered_px": self.considered_px,
        }
        for name, (n, frac) in sorted(self.bands.items()):
            rec[f"{name}_considered_px"] = int(n)
            # Explicitly null, not absent and not zero: a reader must be able
            # to tell "the mask claimed none of what was seen" from "nothing
            # was seen".
            rec[f"{name}_unclaimed_fraction"] = (
                None if frac is None else round(float(frac), 4)
            )
        return rec


# The crude structural split: a slab and what holds it up. Deliberately not
# tuned — 0.70 puts a tabletop in `upper` on every box in the four preserved
# captures, and the point of the split is that pooling hides the defect, not
# that this particular cut is optimal. `lower` starts at 0.10 because the
# room-plane rejection above has already emptied the bottom tenth of every
# floor-standing box.
BAND_LOWER_MIN = 0.10
BAND_UPPER_MIN = 0.70


def height_bands(height_frac: np.ndarray) -> dict[str, np.ndarray]:
    """Boolean masks over a height-fraction array (0 at the box's floor face,
    1 at its top). Three bands, and the bottom one exists to be empty.

    `foot` is [0, 0.10): the slice `_on_room_plane` deletes at the shipped
    tolerance, because 0.08 m of floor rejection reaches 8 cm up into every
    object standing on the floor. Measured on production's own geometry over
    the 26 planned box views of the four preserved captures: **0.2% of all
    considered points, and exactly zero on 24 of the 26**. Reporting it as a
    band rather than letting it fall outside the decomposition is what makes
    `PERCEPTION_BOX_AWARE_FLOOR_TOL` observable — the restored mass lands
    here and nowhere else.
    """
    return {
        "foot": height_frac < BAND_LOWER_MIN,
        "lower": (height_frac >= BAND_LOWER_MIN) & (height_frac < BAND_UPPER_MIN),
        "upper": height_frac >= BAND_UPPER_MIN,
    }


def _box_local(world: np.ndarray, box) -> np.ndarray:
    T = np.asarray(box.transform, dtype=float)
    R = T[:3, :3] / np.linalg.norm(T[:3, :3], axis=0, keepdims=True)
    return (world - np.asarray(box.center_world, dtype=float)) @ R


def _on_room_plane(
    world: np.ndarray, room, floor_tol_m: float | None = None
) -> np.ndarray:
    """Points lying within ROOM_PLANE_TOL_M of a measured floor or wall.

    Floors are read as a world-Y level and walls as a plane through the
    surface origin with the surface's local +Z as normal — the same
    reading `contact_priors` takes of the same entities.

    `floor_tol_m` overrides the FLOOR tolerance only; walls always keep
    ROOM_PLANE_TOL_M. Callers that have already clipped `world` to one
    object's volume pass the tight value (decision 0232) — inside a box the
    room-scale tolerance is not deciding what is floor, it is deleting the
    object's feet.
    """
    on = np.zeros(len(world), dtype=bool)
    if room is None:
        return on
    floor_tol = ROOM_PLANE_TOL_M if floor_tol_m is None else float(floor_tol_m)
    for floor in getattr(room, "floors", ()):
        y = float(np.asarray(floor.transform, dtype=float)[1, 3])
        on |= np.abs(world[:, 1] - y) < floor_tol
    for wall in getattr(room, "walls", ()):
        T = np.asarray(wall.transform, dtype=float)
        n = T[:3, 2]
        norm = float(np.linalg.norm(n))
        if norm < 1e-9:
            continue
        on |= np.abs((world - T[:3, 3]) @ (n / norm)) < ROOM_PLANE_TOL_M
    return on


def unclaimed_in_box(
    *,
    box,
    room,
    camera_pose,
    depth_raster,
    depth_confidence,
    depth_intrinsics,
    mask_stack: np.ndarray,
    mask_index: int,
    extra_claimed: np.ndarray | None = None,
) -> UnclaimedSignal | None:
    """The incompleteness signal for one (frame, mask) view of one box.

    Returns None — never raises — when the frame carries no usable depth,
    when too little of the box was measured to say anything, or when the
    mask stack does not cover `mask_index`. `extra_claimed` is an optional
    2D mask-grid union counted as claimed without being a candidate for
    refinement; the suppressed-concept union (0089) rides in there, so a
    person standing in front of the object is not read as missing object.
    """
    if depth_raster is None or mask_stack is None:
        return None
    if mask_index is None or mask_index >= len(mask_stack):
        return None
    depth = np.asarray(depth_raster)
    if depth.ndim != 2 or depth.size == 0:
        return None

    pointmap = pm.depth_pointmap(
        depth, depth_intrinsics, depth_confidence, min_confidence=1
    )
    dh, dw = depth.shape
    flat = pointmap.reshape(-1, 3)
    measured = np.isfinite(flat[:, 0])
    if not measured.any():
        return None
    world = np.full_like(flat, np.nan)
    world[measured] = pm.camera_to_world(flat[measured], camera_pose)

    half = np.asarray(box.dimensions, dtype=float) / 2.0 + BOX_PAD_M
    local = _box_local(world, box)
    inside = measured & np.all(np.abs(local) <= half, axis=1)
    idx = np.nonzero(inside)[0]
    if len(idx) < MIN_UNCLAIMED_PIXELS:
        return None

    keep = np.zeros(len(flat), dtype=bool)
    keep[idx[~_on_room_plane(world[idx], room)]] = True
    vs, us = np.nonzero(keep.reshape(dh, dw))
    if len(us) == 0:
        return None

    mh, mw = mask_stack[0].shape
    mu = np.clip((us * mw / dw).astype(int), 0, mw - 1)
    mv = np.clip((vs * mh / dh).astype(int), 0, mh - 1)

    claimed = np.zeros(len(us), dtype=bool)
    for j in range(len(mask_stack)):
        claimed |= mask_stack[j][mv, mu]
    if extra_claimed is not None and extra_claimed.shape == (mh, mw):
        claimed |= extra_claimed[mv, mu]
    own = mask_stack[mask_index][mv, mu]

    free = ~claimed
    # Height fraction of the same considered points, in the same order as
    # `us`/`vs`: `keep` selected them out of the flattened pointmap, so the
    # nonzero order of `keep.reshape(dh, dw)` and the row order of
    # `local[keep]` are the same raster order.
    box_height = float(box.dimensions[1])
    kept_local = local[keep]
    bands: dict[str, tuple[int, float | None]] = {}
    if box_height > 0.0:
        hf = (kept_local[:, 1] + box_height / 2.0) / box_height
        for name, sel in height_bands(hf).items():
            n = int(sel.sum())
            bands[name] = (n, float(free[sel].mean()) if n else None)

    return UnclaimedSignal(
        fraction=float(free.mean()),
        own_fraction=float(own.mean()),
        considered_px=int(len(us)),
        unclaimed_vu=np.column_stack([mv[free], mu[free]]),
        bands=bands,
    )


def prompt_box_cxcywh(
    mask: np.ndarray, unclaimed_vu: np.ndarray
) -> list[float] | None:
    """SAM 3's positive-box prompt: bbox of (mask u unclaimed), normalized
    [cx, cy, w, h] on the mask grid. None when the mask is empty."""
    ys, xs = np.nonzero(np.asarray(mask, dtype=bool))
    if len(ys) == 0:
        return None
    if len(unclaimed_vu):
        ys = np.concatenate([ys, unclaimed_vu[:, 0]])
        xs = np.concatenate([xs, unclaimed_vu[:, 1]])
    h, w = np.asarray(mask).shape
    x0, x1 = float(xs.min()), float(xs.max() + 1)
    y0, y1 = float(ys.min()), float(ys.max() + 1)
    return [
        ((x0 + x1) / 2.0) / w,
        ((y0 + y1) / 2.0) / h,
        (x1 - x0) / w,
        (y1 - y0) / h,
    ]


def unclaimed_region_mask(
    unclaimed_vu: np.ndarray, shape: tuple[int, int], depth_shape: tuple[int, int]
) -> np.ndarray:
    """The unclaimed depth pixels painted onto the mask grid.

    Each LiDAR sample covers a block of RGB pixels — 256x192 depth against a
    1440x1920 image is ~7.5 x 10 — so a single unclaimed sample is evidence
    about a neighbourhood, not about one pixel. The block is that footprint
    and nothing more: it is derived from the two grid shapes, not tuned.
    """
    h, w = shape
    dh, dw = depth_shape
    ry = max(1, int(np.ceil(h / max(1, dh))))
    rx = max(1, int(np.ceil(w / max(1, dw))))
    region = np.zeros((h, w), dtype=bool)
    for v, u in np.asarray(unclaimed_vu, dtype=int):
        region[max(0, v - ry):v + ry + 1, max(0, u - rx):u + rx + 1] = True
    return region


def box_hull_mask(box, intrinsics, camera_pose, shape: tuple[int, int]):
    """The measured box's projected footprint rasterized on the mask grid,
    or None when the box does not project. Used to ask whether the pixels
    a refinement ADDED are pixels the measured object could occupy."""
    import box_placement  # deferred: pulls the placement stack

    hull, _frac = box_placement.project_box_footprint(box, intrinsics, camera_pose)
    if hull is None or len(hull) < 3:
        return None
    h, w = shape
    ys, xs = np.mgrid[0:h, 0:w]
    pts = np.column_stack([xs.ravel() + 0.5, ys.ravel() + 0.5]).astype(float)
    return box_placement._points_in_hull(pts, hull).reshape(h, w)


def accept_refined(
    *,
    original: np.ndarray,
    refined: np.ndarray | None,
    mask_stack: np.ndarray,
    mask_index: int,
    box_hull: np.ndarray | None = None,
    unclaimed_region: np.ndarray | None = None,
) -> tuple[bool, dict]:
    """Validate the refinement after the fact. Returns (accept, record).

    The record is written into the object's entry whatever the verdict, so
    a room can be audited for what was offered and what was taken without
    re-running anything.
    """
    rec: dict = {"accepted": False}
    if refined is None:
        rec["reason"] = "no_mask_returned"
        return False, rec
    refined = np.asarray(refined, dtype=bool)
    original = np.asarray(original, dtype=bool)
    if refined.shape != original.shape:
        rec["reason"] = "shape_mismatch"
        return False, rec

    o_px = int(original.sum())
    r_px = int(refined.sum())
    rec.update(original_px=o_px, refined_px=r_px)
    if o_px == 0:
        rec["reason"] = "empty_original"
        return False, rec
    if r_px <= o_px:
        # A shrink or a no-op. Both are refusals for the same reason: the
        # only thing worth accepting is structure the original lacked.
        rec["reason"] = "no_growth"
        return False, rec

    inter = int((refined & original).sum())
    union = int((refined | original).sum())
    iou = inter / union if union else 0.0
    kept = inter / o_px
    growth = r_px / o_px
    rec.update(iou=round(iou, 4), original_kept=round(kept, 4),
               growth=round(growth, 4))
    if iou < MIN_IOU_WITH_ORIGINAL:
        rec["reason"] = "iou_too_low"
        return False, rec
    if kept < MIN_ORIGINAL_KEPT:
        rec["reason"] = "original_not_contained"
        return False, rec
    if growth > MAX_GROWTH_RATIO:
        rec["reason"] = "grew_too_much"
        return False, rec

    added = refined & ~original
    if unclaimed_region is not None and unclaimed_region.shape == original.shape:
        on_signal = float((added & unclaimed_region).sum()) / float(added.sum())
        rec["added_on_signal"] = round(on_signal, 4)
        if on_signal < MIN_ADDED_ON_SIGNAL:
            rec["reason"] = "growth_is_not_what_the_signal_pointed_at"
            return False, rec
    if box_hull is not None and box_hull.shape == original.shape:
        in_box = float((added & box_hull).sum()) / float(added.sum())
        rec["added_inside_box"] = round(in_box, 4)
        if in_box < MIN_NEW_INSIDE_BOX:
            rec["reason"] = "grew_outside_the_measured_box"
            return False, rec

    worst, worst_j = 0.0, None
    for j in range(len(mask_stack)):
        if j == mask_index:
            continue
        other = np.asarray(mask_stack[j], dtype=bool)
        n = int(other.sum())
        if n == 0:
            continue
        share = float((added & other).sum()) / n
        if share > worst:
            worst, worst_j = share, j
    rec["neighbour_absorbed"] = round(worst, 4)
    if worst_j is not None:
        rec["neighbour_mask_index"] = int(worst_j)
    if worst > MAX_NEIGHBOUR_ABSORBED:
        rec["reason"] = "absorbed_a_neighbour"
        return False, rec

    rec["accepted"] = True
    return True, rec
