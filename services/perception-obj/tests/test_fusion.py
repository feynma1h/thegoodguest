"""Unit tests for services/perception-obj/fusion.py.

Fusion turns per-frame observations into one entry per physical object.
These tests build synthetic frame_results dicts (the shape the frame loop
writes) and pin: proximity clustering of placed observations, transform
fusion (median position; rotation and scale strictly from the best
member, whose splat the cluster renders — canonical frames are
per-reconstruction, decision 0065), ray-cluster triangulation with metric
scale recovery, and every explicit unplaced degradation.

Run from repo root:

    python -m pytest services/perception-obj/tests/test_fusion.py -v
"""
from __future__ import annotations

import math

import numpy as np
import pytest

import fusion

SQRT2_2 = math.sqrt(2) / 2


def _placed_obs(
    label="chair",
    frame_index=0,
    position=(1.0, 0.5, -2.0),
    scale=1.5,
    rotation=(0.0, 0.0, 0.0, 1.0),
    score=0.9,
    mask_index=0,
    min_axis_dev=5.0,
):
    return {
        "label": label,
        "instance_idx": 0,
        "bbox": [0, 0, 10, 10],
        "score": score,
        "mask_index": mask_index,
        "ok": True,
        "splat_gcs_uri": f"gs://out/scenes/s/frames/{frame_index:04d}/splats/00_{label}.ply",
        "placement": {
            "placed": True,
            "method": "depth_fit",
            "world_transform": {
                "position": list(position),
                "rotation_xyzw": list(rotation),
                "scale": scale,
            },
            "quality": {"min_axis_to_vertical_deg": min_axis_dev},
        },
    }


def _ray_obs(
    label="lamp",
    frame_index=0,
    origin=(0.0, 0.0, 0.0),
    direction=(0.0, 0.0, -1.0),
    angular_extent=0.2,
    score=0.8,
    splat_max_extent=1.0,
    world_rotation=(0.0, 0.0, 0.0, 1.0),
):
    d = np.asarray(direction, dtype=float)
    d = (d / np.linalg.norm(d)).tolist()
    placement = {
        "placed": False,
        "method": None,
        "reason": "no_depth_pending_triangulation",
        "world_transform": None,
        "quality": {},
        "splat_max_extent": splat_max_extent,
    }
    if world_rotation is not None:
        placement["world_rotation_xyzw"] = list(world_rotation)
    return {
        "label": label,
        "instance_idx": 0,
        "bbox": [0, 0, 10, 10],
        "score": score,
        "mask_index": 0,
        "ok": True,
        "splat_gcs_uri": f"gs://out/scenes/s/frames/{frame_index:04d}/splats/00_{label}.ply",
        "placement": placement,
        "view_ray": {
            "origin": list(origin),
            "direction": d,
            "angular_extent_rad": angular_extent,
        },
    }


def _frames(*objects_per_frame):
    return [
        {"frame_index": i, "objects": list(objs), "ok": True}
        for i, objs in enumerate(objects_per_frame)
    ]


# -----------------------------------------------------------------------------
# Placed-observation clustering + fusion
# -----------------------------------------------------------------------------

def test_same_object_across_frames_fuses_to_one():
    frames = _frames(
        [_placed_obs(frame_index=0, position=(1.0, 0.5, -2.0), scale=1.4, score=0.8)],
        [_placed_obs(frame_index=1, position=(1.1, 0.5, -2.05), scale=1.6, score=0.95)],
        [_placed_obs(frame_index=2, position=(0.95, 0.55, -1.95), scale=1.5, score=0.9)],
    )
    out = fusion.fuse_scene_objects(frames)
    assert len(out) == 1
    obj = out[0]
    assert obj["placed"] is True
    assert obj["method"] == "depth_fit"
    assert obj["quality"]["frames_observed"] == 3
    assert obj["world_transform"]["position"] == pytest.approx([1.0, 0.5, -2.0], abs=0.01)
    # Scale ships from the best member (frame 1, score 0.95) — it is
    # relative to that member's own splat, not fusable across members.
    assert obj["world_transform"]["scale"] == pytest.approx(1.6)
    # Best-score member's splat is referenced.
    assert obj["source"]["frame_index"] == 1
    assert "0001" in obj["splat_gcs_uri"]
    assert obj["quality"]["cluster_spread_m"] < 0.2


def test_far_apart_same_label_objects_stay_separate():
    frames = _frames(
        [
            _placed_obs(frame_index=0, position=(0.0, 0.5, -2.0)),
            _placed_obs(frame_index=0, position=(3.0, 0.5, -2.0), mask_index=1),
        ],
    )
    out = fusion.fuse_scene_objects(frames)
    assert len(out) == 2
    assert all(o["placed"] for o in out)


def test_different_labels_never_merge():
    frames = _frames(
        [
            _placed_obs(label="chair", position=(1.0, 0.5, -2.0)),
            _placed_obs(label="table", position=(1.0, 0.5, -2.0)),
        ],
    )
    out = fusion.fuse_scene_objects(frames)
    assert len(out) == 2
    assert {o["label"] for o in out} == {"chair", "table"}


def test_fused_rotation_is_best_members_not_an_average():
    """Each observation's rotation is relative to its OWN reconstruction's
    canonical frame (SAM 3D samples one per reconstruct — decision 0065),
    so the cluster ships the best member's rotation verbatim, never a
    cross-member average."""
    q0 = (0.0, 0.0, 0.0, 1.0)
    q90 = (0.0, SQRT2_2, 0.0, SQRT2_2)
    frames = _frames(
        [_placed_obs(frame_index=0, rotation=q0, score=0.7)],
        [_placed_obs(frame_index=1, rotation=q90, score=0.95)],
    )
    out = fusion.fuse_scene_objects(frames)
    assert len(out) == 1
    assert out[0]["source"]["frame_index"] == 1
    assert np.allclose(out[0]["world_transform"]["rotation_xyzw"], q90, atol=1e-12)
    # Quality carries the best member's own alignment figure, unaveraged.
    assert out[0]["quality"]["min_axis_to_vertical_deg"] == pytest.approx(5.0)


def test_not_ok_objects_are_ignored():
    bad = _placed_obs()
    bad["ok"] = False
    out = fusion.fuse_scene_objects(_frames([bad]))
    assert out == []


# -----------------------------------------------------------------------------
# Ray-cluster triangulation (ARKIT_ONLY path)
# -----------------------------------------------------------------------------

def _rays_toward(target, origins, label="lamp", splat_max_extent=1.0, angular=None):
    """Observations whose rays all point at `target` from given origins,
    with angular extents consistent with a given metric size (if angular
    is None, computed for extent=0.5m)."""
    target = np.asarray(target, dtype=float)
    obs = []
    for i, origin in enumerate(origins):
        origin = np.asarray(origin, dtype=float)
        d = target - origin
        dist = np.linalg.norm(d)
        ang = angular if angular is not None else 0.5 / dist
        obs.append(
            _ray_obs(
                label=label,
                frame_index=i,
                origin=tuple(origin),
                direction=tuple(d / dist),
                angular_extent=float(ang),
                splat_max_extent=splat_max_extent,
            )
        )
    return obs


def test_ray_cluster_triangulates_center_and_scale():
    """Rays from three baseline-separated cameras: center recovered, and
    scale = median(angular_extent x distance) / splat_max_extent. With
    angular extents consistent with a 0.5m object and a unit splat extent,
    scale must be ~0.5."""
    target = (1.0, 0.8, -2.5)
    obs = _rays_toward(target, [(0, 0, 0), (1.5, 0.2, 0), (-1.0, -0.1, 0.5)])
    frames = _frames([obs[0]], [obs[1]], [obs[2]])
    out = fusion.fuse_scene_objects(frames)
    assert len(out) == 1
    obj = out[0]
    assert obj["placed"] is True
    assert obj["method"] == "layout_triangulated"
    assert obj["world_transform"]["position"] == pytest.approx(list(target), abs=1e-6)
    assert obj["world_transform"]["scale"] == pytest.approx(0.5, rel=1e-6)
    assert obj["quality"]["triangulation_rms_m"] < 1e-9
    assert obj["quality"]["frames_observed"] == 3
    assert obj["rotation_source"] == "sam3d_layout"


def test_two_ray_targets_cluster_separately():
    a = _rays_toward((1.0, 0.5, -2.0), [(0, 0, 0), (1.0, 0, 0)], label="lamp")
    b = _rays_toward((-2.0, 1.0, -3.0), [(0, 0, 0), (1.0, 0, 0)], label="lamp")
    frames = _frames([a[0], b[0]], [a[1], b[1]])
    out = fusion.fuse_scene_objects(frames)
    assert len(out) == 2
    placed = [o for o in out if o["placed"]]
    assert len(placed) == 2
    centers = sorted(o["world_transform"]["position"][0] for o in placed)
    assert centers == pytest.approx([-2.0, 1.0], abs=1e-6)


def test_single_ray_is_unplaced():
    obs = _rays_toward((1.0, 0.5, -2.0), [(0, 0, 0)])
    out = fusion.fuse_scene_objects(_frames([obs[0]]))
    assert len(out) == 1
    assert out[0]["placed"] is False
    assert out[0]["reason"] == "insufficient_observations"


def test_parallel_rays_unplaced_degenerate():
    """Two rays along the same line (camera moved along its view axis):
    they 'triangulate' nowhere. They never pass the consistency gate, so
    each seeds its own cluster and ends up an unplaced single."""
    obs = [
        _ray_obs(frame_index=0, origin=(0, 0, 0), direction=(0, 0, -1)),
        _ray_obs(frame_index=1, origin=(0, 0, -1), direction=(0, 0, -1)),
    ]
    out = fusion.fuse_scene_objects(_frames([obs[0]], [obs[1]]))
    assert all(o["placed"] is False for o in out)
    assert all(o["reason"] == "insufficient_observations" for o in out)


def test_rays_converging_at_camera_origin_do_not_merge():
    """Regression guard for the camera-origin triangulation trap, isolated
    from the per-frame uniqueness rule: two DIFFERENT objects, observed in
    DIFFERENT frames by cameras at nearly the same position, have rays
    whose closest approach is at the (shared) camera origin — a tiny RMS
    that would pass the consistency gate. The behind-camera check in
    _try_triangulate must reject it; without it, fusion would merge the
    two objects into one phantom placed at the camera."""
    obs_a = _ray_obs(frame_index=0, origin=(0.0, 0.0, 0.0), direction=(0.0, 0.0, -1.0))
    obs_b = _ray_obs(frame_index=1, origin=(0.01, 0.0, 0.0), direction=(0.7, 0.0, -0.7))

    # The specific line under guard: the pair 'triangulates' near the
    # origins with tiny RMS, but the point is behind/at both cameras.
    assert fusion._try_triangulate([obs_a, obs_b]) is None

    out = fusion.fuse_scene_objects(_frames([obs_a], [obs_b]))
    assert len(out) == 2, "distinct objects must not merge at the camera origin"
    assert all(o["placed"] is False for o in out)
    assert all(o["reason"] == "insufficient_observations" for o in out)


def test_ray_cluster_without_splat_extent_unplaced():
    obs = _rays_toward(
        (1.0, 0.5, -2.0), [(0, 0, 0), (1.5, 0, 0)], splat_max_extent=None
    )
    out = fusion.fuse_scene_objects(_frames([obs[0]], [obs[1]]))
    assert len(out) == 1
    assert out[0]["placed"] is False
    assert out[0]["reason"] == "no_scale_reference"


def test_ray_cluster_without_layout_rotation_uses_identity():
    obs = _rays_toward((1.0, 0.5, -2.0), [(0, 0, 0), (1.5, 0, 0)])
    for o in obs:
        o["placement"].pop("world_rotation_xyzw", None)
    out = fusion.fuse_scene_objects(_frames([obs[0]], [obs[1]]))
    assert out[0]["placed"] is True
    assert out[0]["rotation_source"] == "none"
    assert out[0]["world_transform"]["rotation_xyzw"] == [0.0, 0.0, 0.0, 1.0]


def test_ray_cluster_rotation_strictly_paired_with_best_splat():
    """A rotation from a NON-best member never applies to the best
    member's splat: canonical frames differ per reconstruction, so if the
    best member has no layout rotation the cluster ships identity/none —
    not another member's rotation (decision 0065)."""
    obs = _rays_toward((1.0, 0.5, -2.0), [(0, 0, 0), (1.5, 0, 0)])
    best = max(obs, key=lambda o: o["score"])
    other = next(o for o in obs if o is not best)
    best["placement"].pop("world_rotation_xyzw", None)
    assert other["placement"].get("world_rotation_xyzw") is not None
    out = fusion.fuse_scene_objects(_frames([obs[0]], [obs[1]]))
    assert out[0]["placed"] is True
    assert out[0]["rotation_source"] == "none"
    assert out[0]["world_transform"]["rotation_xyzw"] == [0.0, 0.0, 0.0, 1.0]


# -----------------------------------------------------------------------------
# Mixed scenes
# -----------------------------------------------------------------------------

def test_mixed_placed_and_ray_labels_coexist():
    chair = [
        _placed_obs(label="chair", frame_index=0, position=(1.0, 0.4, -2.0)),
        _placed_obs(label="chair", frame_index=1, position=(1.05, 0.4, -2.0)),
    ]
    lamp = _rays_toward((0.0, 1.5, -3.0), [(0, 0, 0), (1.2, 0, 0)], label="lamp")
    frames = _frames([chair[0], lamp[0]], [chair[1], lamp[1]])
    out = fusion.fuse_scene_objects(frames)
    assert len(out) == 2
    by_label = {o["label"]: o for o in out}
    assert by_label["chair"]["method"] == "depth_fit"
    assert by_label["lamp"]["method"] == "layout_triangulated"
    # Stable, unique object ids.
    assert len({o["object_id"] for o in out}) == 2


def test_empty_scene():
    assert fusion.fuse_scene_objects([]) == []
    assert fusion.fuse_scene_objects([{"frame_index": 0, "objects": [], "ok": True}]) == []
