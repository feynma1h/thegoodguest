"""Unit tests for fusion.py's decision-0067 refinement pass: dedup,
footprint-based merge relaxation, the PLACEMENT_REFINE=0 rollback lever,
budget-gated skip, and determinism.

Legacy fusion invariants (clustering, transform fusion, unplaced
degradation) stay pinned in test_fusion.py, untouched by this file — these
tests are additive, exercising the RefinementContext-gated path only.

Run from repo root:

    python -m pytest services/perception-obj/tests/test_fusion_refinement.py -v
"""
from __future__ import annotations

import copy

import fusion
import numpy as np
import pytest

MASK_SHAPE = (30, 30)


# -----------------------------------------------------------------------------
# Synthetic observation builders (duplicated from test_fusion.py rather than
# cross-imported: --import-mode=importlib doesn't put sibling test modules
# on sys.path, and these ~20 lines are cheaper to keep in sync than to wire
# up a shared fixtures module for).
# -----------------------------------------------------------------------------

def _ray_obs(
    label="lamp", frame_index=0, origin=(0.0, 0.0, 0.0), direction=(0.0, 0.0, -1.0),
    angular_extent=0.2, score=0.8, splat_max_extent=1.0, world_rotation=(0.0, 0.0, 0.0, 1.0),
):
    d = np.asarray(direction, dtype=float)
    d = (d / np.linalg.norm(d)).tolist()
    placement = {
        "placed": False, "method": None, "reason": "no_depth_pending_triangulation",
        "world_transform": None, "quality": {}, "splat_max_extent": splat_max_extent,
    }
    if world_rotation is not None:
        placement["world_rotation_xyzw"] = list(world_rotation)
    return {
        "label": label, "instance_idx": 0, "bbox": [0, 0, 10, 10], "score": score,
        "mask_index": 0, "ok": True,
        "splat_gcs_uri": f"gs://out/scenes/s/frames/{frame_index:04d}/splats/00_{label}.ply",
        "placement": placement,
        "view_ray": {"origin": list(origin), "direction": d, "angular_extent_rad": angular_extent},
    }


def _frames(*objects_per_frame):
    return [{"frame_index": i, "objects": list(objs), "ok": True} for i, objs in enumerate(objects_per_frame)]


def _rays_toward(target, origins, label="lamp", splat_max_extent=1.0, angular=None):
    target = np.asarray(target, dtype=float)
    obs = []
    for i, origin in enumerate(origins):
        origin = np.asarray(origin, dtype=float)
        d = target - origin
        dist = np.linalg.norm(d)
        ang = angular if angular is not None else 0.5 / dist
        obs.append(_ray_obs(
            label=label, frame_index=i, origin=tuple(origin), direction=tuple(d / dist),
            angular_extent=float(ang), splat_max_extent=splat_max_extent,
        ))
    return obs


def _rect_mask(y0, y1, x0, x1, shape=MASK_SHAPE):
    m = np.zeros(shape, dtype=bool)
    m[y0:y1, x0:x1] = True
    return m


class FakeBudget:
    def __init__(self, remaining_s):
        self._remaining = remaining_s

    def remaining(self):
        return self._remaining


def _ctx(masks_by_frame, budget=None):
    return fusion.RefinementContext(
        get_camera=lambda fi: None,
        get_mask_stack=lambda fi: masks_by_frame.get(fi),
        get_splat=lambda uri: None,
        budget=budget,
    )


# -----------------------------------------------------------------------------
# Dedup: the structural regression guard (decision 0067's bed case)
# -----------------------------------------------------------------------------

def _bed_like_scene_with_duplicate():
    """Seven ray observations of ONE physical object: six clean
    single-frame observations plus a SEVENTH frame carrying a nested
    duplicate detection (mask 1 fully inside mask 0, matching the real
    bed's frame-28 measurement). Mirrors decision 0067's diagnosis:
    without dedup, the frame-uniqueness guard forces a fork; with it,
    dedup removes the spurious detection before clustering ever runs."""
    target = (1.0, 0.6, -2.0)
    origins = [(0, 0, 0), (1.2, 0.1, 0), (-0.8, 0.3, 0.2), (0.5, -0.6, 0.4), (-1.1, 0.5, -0.3)]
    clean = _rays_toward(target, origins, label="bed")
    for i, o in enumerate(clean):
        o["frame_index"] = i

    dup_frame = len(clean)
    d = np.asarray(target) - np.asarray((0.9, -0.2, 0.6))
    dist = np.linalg.norm(d)
    dup_a = _ray_obs(
        label="bed", frame_index=dup_frame, origin=(0.9, -0.2, 0.6),
        direction=tuple(d / dist), angular_extent=0.5 / dist, splat_max_extent=1.0,
    )
    dup_a["score"] = 0.766
    dup_a["mask_index"] = 3
    dup_b = _ray_obs(
        label="bed", frame_index=dup_frame, origin=(0.9, -0.2, 0.6),
        direction=tuple(d / dist), angular_extent=0.5 / dist, splat_max_extent=1.0,
    )
    dup_b["score"] = 0.695
    dup_b["mask_index"] = 5

    frame_objs = [[o] for o in clean] + [[dup_a, dup_b]]
    frames = _frames(*frame_objs)

    masks_by_frame = {
        dup_frame: np.stack([
            _rect_mask(2, 28, 2, 28),  # mask_index 0 (unused slot)
            _rect_mask(2, 28, 2, 28),  # mask_index 1 (unused)
            _rect_mask(2, 28, 2, 28),  # mask_index 2 (unused)
            _rect_mask(2, 28, 2, 28),  # mask_index 3: dup_a, the bigger mask
            _rect_mask(2, 28, 2, 28),  # mask_index 4 (unused)
            _rect_mask(10, 20, 10, 20),  # mask_index 5: dup_b, nested inside 3
        ])
    }
    return frames, masks_by_frame, dup_frame


def test_nested_duplicate_forks_legacy_but_fuses_under_dedup():
    frames, masks_by_frame, _dup_frame = _bed_like_scene_with_duplicate()

    # Legacy (no ctx): the frame-uniqueness guard forces the duplicate
    # into a second cluster (and the merge pass's hard shared-frame veto
    # keeps them apart) -- this is the documented bug decision 0067 fixes.
    legacy = fusion.fuse_scene_objects(frames)
    assert len(legacy) == 2

    # Refined (ctx with nested masks): dedup absorbs the smaller mask
    # BEFORE clustering, so the fork never happens.
    ctx = _ctx(masks_by_frame)
    refined = fusion.fuse_scene_objects(frames, ctx)
    assert len(refined) == 1
    assert refined[0]["placed"] is True
    assert refined[0]["label"] == "bed"


def test_dedup_records_provenance_on_the_surviving_object():
    frames, masks_by_frame, _dup_frame = _bed_like_scene_with_duplicate()
    ctx = _ctx(masks_by_frame)
    refined = fusion.fuse_scene_objects(frames, ctx)
    assert refined[0]["deduped_observations"] == 1


def test_dedup_keeps_the_higher_scored_mask():
    """dup_a (score 0.766, mask_index 3) is the bigger mask and must
    survive over dup_b (score 0.695, mask_index 5, nested inside it)."""
    frames, masks_by_frame, dup_frame = _bed_like_scene_with_duplicate()
    ctx = _ctx(masks_by_frame)
    collected = fusion._collect_observations(frames)
    kept, records = fusion._dedup_same_frame(
        [o for o in collected if o["frame_index"] == dup_frame], ctx
    )
    assert len(kept) == 1
    assert kept[0]["mask_index"] == 3
    assert records == [{
        "frame_index": dup_frame, "kept_mask_index": 3, "absorbed_mask_index": 5,
        "containment": pytest.approx(1.0),
    }]


# -----------------------------------------------------------------------------
# A mask containing multiple DISJOINT same-label children is a coarse
# parent region, not a duplicate -- must not absorb any of them (the
# real scene's door case: one mask spatially contains two separate doors).
# -----------------------------------------------------------------------------

def test_dedup_refuses_when_container_has_disjoint_children():
    frame_index = 0
    parent = _ray_obs(label="door", frame_index=frame_index, origin=(0, 0, 0), direction=(0, 0, -1))
    parent["mask_index"] = 0
    parent["score"] = 0.5
    child_a = _ray_obs(label="door", frame_index=frame_index, origin=(0, 0, 0), direction=(0.1, 0, -1))
    child_a["mask_index"] = 1
    child_a["score"] = 0.5
    child_b = _ray_obs(label="door", frame_index=frame_index, origin=(0, 0, 0), direction=(-0.1, 0, -1))
    child_b["mask_index"] = 2
    child_b["score"] = 0.5
    collected = fusion._collect_observations(_frames([parent, child_a, child_b]))

    masks_by_frame = {
        frame_index: np.stack([
            _rect_mask(0, 30, 0, 30),   # 0: parent, contains both children
            _rect_mask(2, 10, 2, 10),   # 1: child_a
            _rect_mask(20, 28, 20, 28),  # 2: child_b, disjoint from child_a
        ])
    }
    ctx = _ctx(masks_by_frame)
    kept, records = fusion._dedup_same_frame(collected, ctx)
    assert len(kept) == 3  # nothing absorbed
    assert records == []


def test_dedup_missing_masks_is_a_safe_noop():
    """No ctx evidence for a frame (e.g. a cache miss) -> observations
    pass through untouched rather than crashing."""
    frame_index = 0
    a = _ray_obs(label="door", frame_index=frame_index, origin=(0, 0, 0), direction=(0.1, 0, -1))
    a["mask_index"] = 0
    b = _ray_obs(label="door", frame_index=frame_index, origin=(0, 0, 0), direction=(-0.1, 0, -1))
    b["mask_index"] = 1
    collected = fusion._collect_observations(_frames([a, b]))
    ctx = _ctx({})  # no masks for frame 0
    kept, records = fusion._dedup_same_frame(collected, ctx)
    assert len(kept) == 2
    assert records == []


# -----------------------------------------------------------------------------
# Shared-frame merge relaxation: disjoint masks must still refuse
# -----------------------------------------------------------------------------

def test_shared_frame_disjoint_masks_still_refuse_merge():
    frame_index = 7
    mask_a = _rect_mask(0, 10, 0, 10)
    mask_b = _rect_mask(20, 30, 20, 30)  # disjoint from mask_a
    obs_a = {"frame_index": frame_index, "mask_index": 0}
    obs_b = {"frame_index": frame_index, "mask_index": 1}
    ctx = _ctx({frame_index: np.stack([mask_a, mask_b])})
    assert fusion._shared_frames_compatible([obs_a], [obs_b], ctx) is False


def test_shared_frame_duplicate_consistent_masks_are_compatible():
    frame_index = 7
    mask_a = _rect_mask(2, 28, 2, 28)
    mask_b = _rect_mask(10, 20, 10, 20)  # nested inside mask_a
    obs_a = {"frame_index": frame_index, "mask_index": 0}
    obs_b = {"frame_index": frame_index, "mask_index": 1}
    ctx = _ctx({frame_index: np.stack([mask_a, mask_b])})
    assert fusion._shared_frames_compatible([obs_a], [obs_b], ctx) is True


def test_no_shared_frames_is_trivially_compatible():
    obs_a = {"frame_index": 1, "mask_index": 0}
    obs_b = {"frame_index": 2, "mask_index": 0}
    assert fusion._shared_frames_compatible([obs_a], [obs_b], None) is True


def test_shared_frame_without_ctx_keeps_legacy_hard_veto():
    obs_a = {"frame_index": 1, "mask_index": 0}
    obs_b = {"frame_index": 1, "mask_index": 1}
    assert fusion._shared_frames_compatible([obs_a], [obs_b], None) is False


# -----------------------------------------------------------------------------
# PLACEMENT_REFINE=0 bit-parity (the rollback lever)
# -----------------------------------------------------------------------------

def test_placement_refine_zero_reproduces_legacy_exactly(monkeypatch):
    frames, masks_by_frame, _dup_frame = _bed_like_scene_with_duplicate()
    ctx = _ctx(masks_by_frame)

    legacy = fusion.fuse_scene_objects(frames)
    monkeypatch.setenv("PLACEMENT_REFINE", "0")
    with_ctx_but_disabled = fusion.fuse_scene_objects(copy.deepcopy(frames), ctx)
    assert with_ctx_but_disabled == legacy


def test_placement_refine_zero_meta_reports_disabled(monkeypatch):
    frames, masks_by_frame, _dup_frame = _bed_like_scene_with_duplicate()
    ctx = _ctx(masks_by_frame)
    monkeypatch.setenv("PLACEMENT_REFINE", "0")
    _objects, meta = fusion.fuse_scene_objects_with_meta(frames, ctx)
    assert meta == {"refinement_enabled": False, "refinement_skipped": False}


def test_no_ctx_is_legacy_regardless_of_env(monkeypatch):
    frames, _masks_by_frame, _dup_frame = _bed_like_scene_with_duplicate()
    monkeypatch.setenv("PLACEMENT_REFINE", "1")
    objects, meta = fusion.fuse_scene_objects_with_meta(frames, None)
    assert len(objects) == 2  # legacy fork, unaffected by the env flag
    assert meta == {"refinement_enabled": False, "refinement_skipped": False}


# -----------------------------------------------------------------------------
# Budget-gated skip
# -----------------------------------------------------------------------------

def test_insufficient_budget_skips_refinement_scene_wide():
    frames, masks_by_frame, _dup_frame = _bed_like_scene_with_duplicate()
    legacy = fusion.fuse_scene_objects(frames)
    ctx = _ctx(masks_by_frame, budget=FakeBudget(remaining_s=1.0))  # under min_remaining_s
    objects, meta = fusion.fuse_scene_objects_with_meta(frames, ctx)
    assert objects == legacy
    assert meta == {"refinement_enabled": False, "refinement_skipped": True}


def test_sufficient_budget_runs_refinement():
    frames, masks_by_frame, _dup_frame = _bed_like_scene_with_duplicate()
    ctx = _ctx(masks_by_frame, budget=FakeBudget(remaining_s=600.0))
    objects, meta = fusion.fuse_scene_objects_with_meta(frames, ctx)
    assert len(objects) == 1
    assert meta == {"refinement_enabled": True, "refinement_skipped": False}


class DrainingBudget:
    """remaining() returns scripted values in order, repeating the last —
    lets a test drain the budget mid-pass deterministically."""

    def __init__(self, values):
        self._values = list(values)

    def remaining(self):
        if len(self._values) > 1:
            return self._values.pop(0)
        return self._values[0]


def test_budget_draining_mid_pass_halts_further_refinement():
    """The mid-pass safety valve (the 0060 zombie-request guard): if the
    budget drains below min_remaining_s while refining, objects already
    refined keep their refined fields, the REMAINING objects ship legacy
    values (no refined fields), and refinement_skipped is recorded. Two
    single-cluster labels, alphabetical order: 'apple' refines, then the
    budget drains and 'banana' does not."""
    a = _rays_toward((1.0, 0.5, -2.0), [(0, 0, 0), (1.2, 0.1, 0)], label="apple")
    b = _rays_toward((-2.0, 1.0, -3.0), [(0, 0, 0), (1.2, 0.1, 0)], label="banana")
    frames = _frames([a[0], b[0]], [a[1], b[1]])
    # Calls: up-front gate, then one per cluster before refining it.
    budget = DrainingBudget([600.0, 600.0, 1.0])
    ctx = _ctx({}, budget=budget)
    objects, meta = fusion.fuse_scene_objects_with_meta(frames, ctx)
    by_label = {o["label"]: o for o in objects}
    assert "position_source" in by_label["apple"]
    assert "position_source" not in by_label["banana"]
    assert meta == {"refinement_enabled": True, "refinement_skipped": True}


# -----------------------------------------------------------------------------
# Determinism
# -----------------------------------------------------------------------------

def test_refined_fusion_is_deterministic():
    frames, masks_by_frame, _dup_frame = _bed_like_scene_with_duplicate()
    ctx1 = _ctx(masks_by_frame)
    ctx2 = _ctx(masks_by_frame)
    out1 = fusion.fuse_scene_objects(copy.deepcopy(frames), ctx1)
    out2 = fusion.fuse_scene_objects(copy.deepcopy(frames), ctx2)
    assert out1 == out2


def test_legacy_fusion_is_deterministic():
    frames, _masks_by_frame, _dup_frame = _bed_like_scene_with_duplicate()
    out1 = fusion.fuse_scene_objects(copy.deepcopy(frames))
    out2 = fusion.fuse_scene_objects(copy.deepcopy(frames))
    assert out1 == out2


# -----------------------------------------------------------------------------
# Cross-label behaviour after fork (a) (RP-8 walk, always-on): NEAR-IDENTICAL
# masks collapse regardless of label (the cross-label gate's purpose — one
# physical object triple-detected under different names); masks that are NOT
# near-identical never merge across labels (the 0067 same-frame dedup and
# clustering still operate strictly within a by_label group).
# -----------------------------------------------------------------------------

def test_near_identical_cross_label_masks_collapse():
    frame_index = 0
    chair = _ray_obs(label="chair", frame_index=frame_index, origin=(0, 0, 0), direction=(0, 0, -1))
    chair["mask_index"] = 0
    table = _ray_obs(label="table", frame_index=frame_index, origin=(0, 0, 0), direction=(0, 0, -1))
    table["mask_index"] = 1
    frames = _frames([chair, table])
    masks_by_frame = {frame_index: np.stack([_rect_mask(0, 30, 0, 30), _rect_mask(0, 30, 0, 30)])}
    ctx = _ctx(masks_by_frame)
    out = fusion.fuse_scene_objects(frames, ctx)
    assert len(out) == 1  # identical pixels = one physical object


def test_distinct_masks_never_merge_across_labels():
    frame_index = 0
    chair = _ray_obs(label="chair", frame_index=frame_index, origin=(0, 0, 0), direction=(0, 0, -1))
    chair["mask_index"] = 0
    table = _ray_obs(label="table", frame_index=frame_index, origin=(0, 0, 0), direction=(0, 0, -1))
    table["mask_index"] = 1
    frames = _frames([chair, table])
    masks_by_frame = {
        frame_index: np.stack([_rect_mask(0, 30, 0, 30), _rect_mask(34, 60, 34, 60)])
    }
    ctx = _ctx(masks_by_frame)
    out = fusion.fuse_scene_objects(frames, ctx)
    assert len(out) == 2
    assert {o["label"] for o in out} == {"chair", "table"}
