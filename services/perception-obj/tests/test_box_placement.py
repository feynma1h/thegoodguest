"""box_placement.py unit invariants (decision 0077 lock 5): footprint
projection + overlap, label-family compatibility, greedy deterministic
association, the axis-mapping candidate set (the P1 probe's up±/long±
regime generalized), the ship/flag margin semantics, box-dims-as-truth,
the honest no_appearance inventory entry, and box-duplicate suppression
geometry. Synthetic ground truth throughout; the achieved-value pins on
real data live in test_box_placement_real_data.py.

Run from repo root:
    python -m pytest services/perception-obj/tests/test_box_placement.py -v
"""
from __future__ import annotations

from dataclasses import dataclass, field

import box_placement
import numpy as np
import pytest
from roomplan_room import RoomPlanBox
from roomstudio_schemas.placement_math import prepare_mask
from roomstudio_schemas.pose_math import quat_to_rotmat


@dataclass
class FakeIntrinsics:
    fx: float = 60.0
    fy: float = 60.0
    cx: float = 32.0
    cy: float = 32.0
    width: int = 64
    height: int = 64


@dataclass
class FakePose:
    pos_x: float = 0.0
    pos_y: float = 0.0
    pos_z: float = 0.0
    quat_x: float = 0.0
    quat_y: float = 0.0
    quat_z: float = 0.0
    quat_w: float = 1.0


def _yaw_transform(center, yaw_rad: float) -> np.ndarray:
    c, s = np.cos(yaw_rad), np.sin(yaw_rad)
    T = np.eye(4)
    T[:3, :3] = np.array([[c, 0.0, s], [0.0, 1.0, 0.0], [-s, 0.0, c]])
    T[:3, 3] = center
    return T


def _box(
    category="bed",
    center=(0.0, 0.0, -3.0),
    dims=(2.0, 0.5, 1.0),
    yaw=0.0,
    identifier="B1",
) -> RoomPlanBox:
    T = _yaw_transform(np.asarray(center, dtype=float), yaw)
    R = T[:3, :3]
    return RoomPlanBox(
        identifier=identifier,
        category=category,
        confidence="high",
        attributes={},
        dimensions=np.asarray(dims, dtype=float),
        transform=T,
        center_world=T[:3, 3].copy(),
        up_y=float(R[1, 1]),
        yaw_rad=float(np.arctan2(R[2, 0], R[0, 0])),
    )


def _mask_from_hull(hull: np.ndarray, shape=(64, 64)) -> np.ndarray:
    ys, xs = np.mgrid[0:shape[0], 0:shape[1]]
    pts = np.column_stack([xs.ravel() + 0.5, ys.ravel() + 0.5]).astype(float)
    inside = box_placement._points_in_hull(pts, hull)
    return inside.reshape(shape)


@dataclass
class StubCtx:
    """Minimal RefinementContext stand-in for the pure module."""

    cameras: dict = field(default_factory=dict)  # frame → (pose, intrinsics)
    masks: dict = field(default_factory=dict)  # (frame, mask_idx) → (H, W) bool
    splats: dict = field(default_factory=dict)  # uri → (N, 3)
    get_appearance: object = None
    get_rgb: object = None

    def get_camera(self, frame_index):
        return self.cameras.get(frame_index)

    def mask_for(self, frame_index, mask_index):
        return self.masks.get((frame_index, mask_index))

    def evidence_for(self, frame_index, mask_index):
        m = self.mask_for(frame_index, mask_index)
        return None if m is None else prepare_mask(m)

    def get_splat(self, uri):
        return self.splats.get(uri)


def _obs(label="bed", frame_index=0, mask_index=0, score=0.9, uri="gs://o/s.ply"):
    return {
        "frame_index": frame_index,
        "label": label,
        "score": score,
        "mask_index": mask_index,
        "splat_gcs_uri": uri,
        "placement": {},
        "view_ray": None,
    }


# ---------------------------------------------------------------------------
# Footprint projection + overlap
# ---------------------------------------------------------------------------

class TestFootprint:
    def test_centered_box_projects_in_frame(self):
        hull, in_frame = box_placement.project_box_footprint(
            _box(), FakeIntrinsics(), FakePose()
        )
        assert hull is not None
        assert in_frame == pytest.approx(1.0, abs=1e-6)

    def test_close_view_is_mostly_out_of_frame(self):
        """The P1 degenerate-view class: a camera very close to a large box
        projects a footprint far bigger than the frame."""
        hull, in_frame = box_placement.project_box_footprint(
            _box(center=(0.0, 0.0, -0.6)), FakeIntrinsics(), FakePose()
        )
        assert hull is not None
        assert in_frame < box_placement._BOX_SCORE_MIN_INFRAME

    def test_behind_camera_no_footprint(self):
        hull, in_frame = box_placement.project_box_footprint(
            _box(center=(0.0, 0.0, 3.0)), FakeIntrinsics(), FakePose()
        )
        assert hull is None
        assert in_frame == 0.0

    def test_mask_overlap(self):
        hull, _ = box_placement.project_box_footprint(
            _box(), FakeIntrinsics(), FakePose()
        )
        inside = _mask_from_hull(hull)
        assert box_placement.mask_overlap_with_hull(inside, hull) == pytest.approx(1.0, abs=0.02)
        outside = np.zeros((64, 64), dtype=bool)
        outside[:6, :6] = True
        assert box_placement.mask_overlap_with_hull(outside, hull) < 0.1


# ---------------------------------------------------------------------------
# Family map
# ---------------------------------------------------------------------------

class TestFamilies:
    @pytest.mark.parametrize("category,label,ok", [
        ("bed", "bed", True),
        ("table", "desk", True),
        ("table", "nightstand", True),
        ("chair", "stool", True),
        ("storage", "wardrobe", True),
        ("sofa", "couch", True),
        ("television", "tv", True),
        ("bed", "chair", False),
        ("refrigerator", "cabinet", False),  # unmapped category
        (None, "bed", False),
        ("bed", None, False),
    ])
    def test_map(self, category, label, ok):
        assert box_placement.family_compatible(category, label) is ok


# ---------------------------------------------------------------------------
# Association
# ---------------------------------------------------------------------------

def _scene_with_box(box, *, label="bed", frame_index=0, mask_index=0):
    ctx = StubCtx()
    ctx.cameras[frame_index] = (FakePose(), FakeIntrinsics())
    hull, _ = box_placement.project_box_footprint(box, FakeIntrinsics(), FakePose())
    ctx.masks[(frame_index, mask_index)] = _mask_from_hull(hull)
    obs = _obs(label=label, frame_index=frame_index, mask_index=mask_index)
    return ctx, obs


class TestAssociation:
    def test_compatible_overlapping_mask_associates(self):
        box = _box()
        ctx, obs = _scene_with_box(box)
        out = box_placement.associate_observations([box], [obs], ctx)
        assert set(out) == {0}
        assert out[0][0].overlap == pytest.approx(1.0, abs=0.02)

    def test_incompatible_label_never_associates(self):
        box = _box()
        ctx, obs = _scene_with_box(box, label="chair")
        assert box_placement.associate_observations([box], [obs], ctx) == {}

    def test_low_overlap_rejected(self):
        box = _box()
        ctx, obs = _scene_with_box(box)
        far = np.zeros((64, 64), dtype=bool)
        far[:8, :8] = True
        ctx.masks[(0, 0)] = far
        assert box_placement.associate_observations([box], [obs], ctx) == {}

    def test_observation_joins_best_box_only(self):
        """Two family-compatible boxes; the mask painted from box A's
        footprint associates to A, and only once."""
        box_a = _box(center=(0.0, 0.0, -3.0), identifier="A")
        box_b = _box(center=(0.6, 0.0, -3.0), identifier="B")
        ctx, obs = _scene_with_box(box_a)
        out = box_placement.associate_observations([box_a, box_b], [obs], ctx)
        assert set(out) == {0}
        assert sum(len(v) for v in out.values()) == 1

    def test_deterministic(self):
        box = _box()
        ctx, obs = _scene_with_box(box)
        obs2 = _obs(frame_index=0, mask_index=1, score=0.5)
        ctx.masks[(0, 1)] = ctx.masks[(0, 0)]
        a = box_placement.associate_observations([box], [obs, obs2], ctx)
        b = box_placement.associate_observations([box], [obs, obs2], ctx)
        assert [(x.frame_index, x.mask_index) for x in a[0]] == [
            (x.frame_index, x.mask_index) for x in b[0]
        ]


# ---------------------------------------------------------------------------
# Axis-mapping candidates
# ---------------------------------------------------------------------------

def _slab_cloud(ext=(1.0, 0.25, 0.5), n=800) -> np.ndarray:
    """Uniform cloud with FULL extents ≈ ext along the coordinate axes
    (half the box's dims, so the median dim/extent ratio lands near 2)."""
    rng = np.random.default_rng(7)
    return rng.uniform(-0.5, 0.5, size=(n, 3)) * np.asarray(ext)


class TestAxisMapping:
    def test_distinct_extents_give_four_candidates(self):
        cands = box_placement.axis_mapping_candidates(_box(), np.array([1.0, 0.25, 0.5]))
        assert len(cands) == 4
        assert cands[0].signs == (1, 1)  # the extent-best default first
        assert [c.signs for c in cands] == [(1, 1), (1, -1), (-1, 1), (-1, -1)]

    def test_scale_is_median_ratio_and_residuals_zero_for_exact(self):
        cands = box_placement.axis_mapping_candidates(_box(), np.array([1.0, 0.25, 0.5]))
        assert cands[0].scale == pytest.approx(2.0)
        assert cands[0].residual_m == pytest.approx([0.0, 0.0, 0.0], abs=1e-6)

    def test_near_square_enumerates_both_horizontal_assignments(self):
        box = _box(dims=(1.0, 0.5, 1.0))
        cands = box_placement.axis_mapping_candidates(box, np.array([0.5, 0.25, 0.5]))
        assignments = {c.assignment for c in cands}
        assert len(assignments) == 2  # x/z swap alive
        assert len(cands) == 8

    def test_rotations_are_proper_and_map_axes(self):
        box = _box(yaw=0.3)
        cands = box_placement.axis_mapping_candidates(box, np.array([1.0, 0.25, 0.5]))
        R_box = box.transform[:3, :3]
        for c in cands:
            R = quat_to_rotmat(c.rotation_xyzw)
            assert np.linalg.det(R) == pytest.approx(1.0, abs=1e-9)
            i_x, i_up, i_z = c.assignment
            s_up, s_x = c.signs
            assert R @ np.eye(3)[i_up] == pytest.approx(s_up * R_box[:, 1], abs=1e-9)
            assert R @ np.eye(3)[i_x] == pytest.approx(s_x * R_box[:, 0], abs=1e-9)

    def test_partner_index_is_the_facing_flip(self):
        cands = box_placement.axis_mapping_candidates(_box(), np.array([1.0, 0.25, 0.5]))
        p = box_placement._partner_index(cands, 0)
        assert cands[p].signs == (1, -1)
        assert cands[p].assignment == cands[0].assignment


# ---------------------------------------------------------------------------
# build_box_object decision semantics (scores injected — the margins are
# the contract; the instrument's discrimination is pinned on real data)
# ---------------------------------------------------------------------------

def _built(box, ctx, associations, monkeypatch=None, scores=None, allow_scoring=True):
    if scores is not None:
        monkeypatch.setattr(
            box_placement, "score_candidates_at_center",
            lambda candidates, center, pts, app, views: list(scores[: len(candidates)]),
        )
    return box_placement.build_box_object(
        box=box, box_index=0, object_id="obj_000",
        associations=associations, ctx=ctx, allow_scoring=allow_scoring,
    )


def _assoc_scene():
    box = _box()
    ctx, obs = _scene_with_box(box)
    ctx.splats["gs://o/s.ply"] = _slab_cloud()
    assoc = box_placement.associate_observations([box], [obs], ctx)[0]
    return box, ctx, assoc


class TestBuildBoxObject:
    def test_resolved_winner_ships(self, monkeypatch):
        box, ctx, assoc = _assoc_scene()
        obj = _built(box, ctx, assoc, monkeypatch, scores=[0.5, 0.75, 0.4, 0.3])
        assert obj["placed"] is True
        assert obj["method"] == "roomplan_box"
        assert obj["position_source"] == "roomplan_box"
        assert obj["splat_axis_resolved"] is True
        assert obj["facing_flag"] is False
        assert obj["quality"]["axis_margin"] == pytest.approx(0.25)
        cands = box_placement.axis_mapping_candidates(
            box, box_placement.splat_axis_extents(ctx.splats["gs://o/s.ply"])
        )
        assert obj["world_transform"]["rotation_xyzw"] == list(cands[1].rotation_xyzw)

    def test_below_margin_ships_default_unresolved(self, monkeypatch):
        box, ctx, assoc = _assoc_scene()
        obj = _built(box, ctx, assoc, monkeypatch, scores=[0.50, 0.52, 0.45, 0.44])
        assert obj["splat_axis_resolved"] is False
        cands = box_placement.axis_mapping_candidates(
            box, box_placement.splat_axis_extents(ctx.splats["gs://o/s.ply"])
        )
        assert obj["world_transform"]["rotation_xyzw"] == list(cands[0].rotation_xyzw)

    def test_facing_flag_fires_flag_only(self, monkeypatch):
        """The scorer prefers the anti-RoomPlan facing (the default's
        180°-about-vertical partner) but below the ship margin: flag it,
        ship RoomPlan's conventional mapping — flag-only v1."""
        box, ctx, assoc = _assoc_scene()
        obj = _built(box, ctx, assoc, monkeypatch, scores=[0.50, 0.55, 0.45, 0.44])
        assert obj["splat_axis_resolved"] is False
        assert obj["facing_flag"] is True
        cands = box_placement.axis_mapping_candidates(
            box, box_placement.splat_axis_extents(ctx.splats["gs://o/s.ply"])
        )
        assert obj["world_transform"]["rotation_xyzw"] == list(cands[0].rotation_xyzw)

    def test_budget_refused_ships_default_without_scoring(self):
        box, ctx, assoc = _assoc_scene()
        obj = _built(box, ctx, assoc, allow_scoring=False)
        assert obj["placed"] is True
        assert obj["splat_axis_resolved"] is False
        assert obj["quality"]["axis_scored_views"] == 0

    def test_box_owns_position_scale_and_extents(self, monkeypatch):
        box, ctx, assoc = _assoc_scene()
        obj = _built(box, ctx, assoc, monkeypatch, scores=[0.5, 0.4, 0.3, 0.2])
        assert obj["world_transform"]["position"] == pytest.approx([0.0, 0.0, -3.0])
        assert obj["extent_m_sorted"] == [2.0, 1.0, 0.5]  # BOX dims, sorted
        assert obj["world_transform"]["scale"] == pytest.approx(2.0, abs=0.2)
        assert obj["label"] == "bed"
        assert obj["sam_label"] == "bed"
        assert obj["roomplan_box"]["box_id"] == "box_00"
        assert obj["roomplan_box"]["dims"] == pytest.approx([2.0, 0.5, 1.0])

    def test_degenerate_views_are_skipped(self, monkeypatch):
        """An association whose footprint is mostly out of frame never
        reaches the scorer (P1's f164 lesson)."""
        box, ctx, assoc = _assoc_scene()
        assoc = [box_placement.BoxAssociation(
            box_index=a.box_index, frame_index=a.frame_index,
            mask_index=a.mask_index, overlap=a.overlap,
            in_frame_fraction=0.1, obs=a.obs,
        ) for a in assoc]
        called = []
        monkeypatch.setattr(
            box_placement, "score_candidates_at_center",
            lambda *a, **k: called.append(1) or [None] * 4,
        )
        obj = box_placement.build_box_object(
            box=box, box_index=0, object_id="obj_000",
            associations=assoc, ctx=ctx, allow_scoring=True,
        )
        assert called == []  # zero scoreable views -> scorer never invoked
        assert obj["quality"]["axis_scored_views"] == 0
        assert obj["splat_axis_resolved"] is False

    def test_no_associations_is_honest_inventory(self):
        box = _box()
        obj = box_placement.build_box_object(
            box=box, box_index=2, object_id="obj_005",
            associations=[], ctx=StubCtx(), allow_scoring=True,
        )
        assert obj["placed"] is False
        assert obj["reason"] == "no_appearance"
        assert obj["splat_gcs_uri"] is None
        assert obj["world_transform"] is None
        assert obj["extent_m_sorted"] == [2.0, 1.0, 0.5]  # geometry carried
        assert obj["roomplan_box"]["box_id"] == "box_02"
        assert obj["roomplan_box"]["center_world"] == pytest.approx([0.0, 0.0, -3.0])

    def test_missing_splat_is_no_appearance(self):
        box, ctx, assoc = _assoc_scene()
        ctx.splats.clear()
        obj = box_placement.build_box_object(
            box=box, box_index=0, object_id="obj_000",
            associations=assoc, ctx=ctx, allow_scoring=True,
        )
        assert obj["placed"] is False
        assert obj["reason"] == "no_appearance"


# ---------------------------------------------------------------------------
# Suppression geometry
# ---------------------------------------------------------------------------

class TestSuppression:
    def test_center_inside_box(self):
        box = _box(center=(1.0, 0.5, -2.0), dims=(2.0, 1.0, 1.0), yaw=0.5)
        assert box_placement.center_inside_box((1.0, 0.5, -2.0), box)
        R = box.transform[:3, :3]
        edge = np.array([1.0, 0.5, -2.0]) + R[:, 0] * 1.04  # just inside margin
        assert box_placement.center_inside_box(edge, box)
        far = np.array([1.0, 0.5, -2.0]) + R[:, 0] * 1.3
        assert not box_placement.center_inside_box(far, box)

    def test_find_suppressing_box_semantics(self):
        boxes = [_box(center=(0.0, 0.0, -3.0)), _box(center=(5.0, 0.0, -3.0), identifier="B2")]
        inside = {
            "placed": True, "label": "bed",
            "world_transform": {"position": [0.1, 0.0, -3.0]},
        }
        # Matched box → suppressed; unmatched → not.
        assert box_placement.find_suppressing_box(inside, boxes, {0}) == 0
        assert box_placement.find_suppressing_box(inside, boxes, {1}) is None
        # Incompatible label → not.
        chair = {**inside, "label": "chair"}
        assert box_placement.find_suppressing_box(chair, boxes, {0}) is None
        # Unplaced → not.
        unplaced = {**inside, "placed": False}
        assert box_placement.find_suppressing_box(unplaced, boxes, {0}) is None
