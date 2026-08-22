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
from roomstudio_schemas.pose_math import quat_to_rotmat, rotation_angle_deg


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

class _FakeCategory:
    """Just the `category` attribute `vocabulary_gaps` reads off a box."""

    def __init__(self, category):
        self.category = category


class TestFamilies:
    @pytest.mark.parametrize("category,label,ok", [
        ("bed", "bed", True),
        ("table", "desk", True),
        ("table", "nightstand", True),
        ("chair", "chair", True),
        ("storage", "cabinet", True),
        ("sofa", "sofa", True),
        ("television", "tv", True),
        # The names SAM actually emits for the classes the 0077 map named
        # only generically. `table` was operationally {desk, nightstand}
        # until these arrived, because the prompt has no bare `table`.
        ("table", "coffee table", True),
        ("table", "dining table", True),
        ("table", "side table", True),
        ("chair", "dining chair", True),
        # Dual-listed on purpose, like `nightstand` across table/storage.
        ("chair", "armchair", True),
        ("sofa", "armchair", True),
        ("refrigerator", "cabinet", True),
        ("bed", "chair", False),
        (None, "bed", False),
        ("bed", None, False),
    ])
    def test_map(self, category, label, ok):
        assert box_placement.family_compatible(category, label) is ok

    @pytest.mark.parametrize("category,label", [
        ("table", "table"),      # prompt has dining/coffee/side table only
        ("chair", "stool"),
        ("chair", "bench"),
        ("storage", "dresser"),
        ("storage", "wardrobe"),
        ("storage", "shelf"),
        ("sofa", "couch"),
        ("television", "television"),
    ])
    def test_labels_the_prompt_cannot_emit_are_not_in_the_map(
        self, category, label
    ):
        """SAM 3 returns the PROMPT TERM, so a family member absent from
        `DEFAULT_OBJECT_PROMPT` can never match anything. These eight were
        in 0077's map and were measured inert: removing them left the
        association census over the four preserved captures byte-identical
        at 20/31 boxes and 28 associations."""
        assert box_placement.family_compatible(category, label) is False

    def test_vocabulary_gaps_reports_both_directions(self):
        cats = [_FakeCategory("refrigerator"), _FakeCategory("table")]
        unmapped, inert = box_placement.vocabulary_gaps(
            cats, "desk,cabinet,chair,bed,sofa,tv,monitor,nightstand,bookshelf"
        )
        assert unmapped == []          # refrigerator is mapped now
        # The prompt above omits the specific table/chair names, so they
        # report as unemittable against it.
        assert "coffee table" in inert and "armchair" in inert

    def test_vocabulary_gaps_names_an_unmapped_category(self):
        unmapped, _ = box_placement.vocabulary_gaps(
            [_FakeCategory("bathtub")], "desk,cabinet"
        )
        assert unmapped == ["bathtub"]

    def test_the_shipped_map_is_fully_emittable_by_the_shipped_prompt(self):
        """The alignment this pins is the whole point of the map: every
        family member must be a term the shipped prompt can return."""
        import process_receiver

        _, inert = box_placement.vocabulary_gaps(
            [], process_receiver.DEFAULT_OBJECT_PROMPT
        )
        assert inert == []


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

    def test_up_filter_keeps_only_the_layout_up_axis(self):
        """With a layout up prior (decision 0081), all six assignments are
        enumerated and only those mapping the up AXIS LINE near vertical
        survive — both signs (the layout's sign is never trusted: it
        measured wrong on a real walked table)."""
        cands = box_placement.axis_mapping_candidates(
            _box(), np.array([1.0, 0.25, 0.5]), up_local=np.array([0.0, 1.0, 0.0])
        )
        assert cands  # never empty for an axis-aligned prior
        assert {c.assignment[1] for c in cands} == {1}  # splat axis 1 -> up only
        assert {c.signs[0] for c in cands} == {1, -1}  # both up signs alive
        assert len(cands) == 8  # 2 horizontal assignments x 4 signs
        # Order convention unchanged: extent-best assignment, (+, +) first.
        assert cands[0].signs == (1, 1)

    def test_up_filter_excludes_truncation_misleading_assignment(self):
        """The walked bed's failure class in synthetic form: extents prefer
        an assignment whose up axis contradicts the layout prior; with the
        prior the wrong-up assignment is simply not enumerated."""
        cands = box_placement.axis_mapping_candidates(
            _box(), np.array([1.0, 0.25, 0.5]), up_local=np.array([0.0, 0.0, 1.0])
        )
        assert {c.assignment[1] for c in cands} == {2}

    def test_up_filter_diagonal_prior_falls_back(self):
        """A near-diagonal layout up (54.7° from every axis) fails the
        filter for every mapping; the extent-tolerance enumeration stands
        rather than an empty candidate list."""
        diag = np.array([1.0, 1.0, 1.0]) / np.sqrt(3.0)
        with_prior = box_placement.axis_mapping_candidates(
            _box(), np.array([1.0, 0.25, 0.5]), up_local=diag
        )
        without = box_placement.axis_mapping_candidates(
            _box(), np.array([1.0, 0.25, 0.5])
        )
        assert [c.rotation_xyzw for c in with_prior] == [
            c.rotation_xyzw for c in without
        ]

    def test_no_prior_matches_pre_0081_enumeration(self):
        """The 2-arg call (and up_local=None) is byte-identical to the
        pre-0081 extent-tolerance enumeration — the degrade lock for
        observations without a layout rotation."""
        a = box_placement.axis_mapping_candidates(_box(), np.array([1.0, 0.25, 0.5]))
        b = box_placement.axis_mapping_candidates(
            _box(), np.array([1.0, 0.25, 0.5]), up_local=None
        )
        assert [c.rotation_xyzw for c in a] == [c.rotation_xyzw for c in b]
        assert len(a) == 4


# ---------------------------------------------------------------------------
# build_box_object decision semantics (decision 0081: assignment resolution
# by the cloud instrument, sign by the fixed convention, facing by the
# appearance partner check — scores injected here; the instruments'
# discrimination is pinned on real data)
# ---------------------------------------------------------------------------

def _built(
    box, ctx, associations, monkeypatch=None,
    cloud_scores=None, pair_scores=None, allow_scoring=True,
):
    if cloud_scores is not None:
        monkeypatch.setattr(
            box_placement, "observation_cloud_from_ctx",
            lambda ctx, fi, mi: np.zeros((100, 3)),
        )
        monkeypatch.setattr(
            box_placement, "score_candidates_cloud",
            lambda candidates, pts, cloud, scale: list(cloud_scores[: len(candidates)]),
        )
    if pair_scores is not None:
        monkeypatch.setattr(
            box_placement, "score_candidates_at_center",
            lambda candidates, center, pts, app, views: list(pair_scores[: len(candidates)]),
        )
    return box_placement.build_box_object(
        box=box, box_index=0, object_id="obj_000",
        associations=associations, ctx=ctx, allow_scoring=allow_scoring,
    )


def _assoc_scene(dims=(1.0, 0.5, 1.0), ext=(0.5, 0.25, 0.5)):
    """A near-square box (two live assignments — 8 candidates) so
    assignment resolution has a rival to beat."""
    box = _box(dims=dims)
    ctx, obs = _scene_with_box(box)
    ctx.splats["gs://o/s.ply"] = _slab_cloud(ext)
    assoc = box_placement.associate_observations([box], [obs], ctx)[0]
    return box, ctx, assoc


def _cands(box, ctx):
    return box_placement.axis_mapping_candidates(
        box, box_placement.splat_axis_extents(ctx.splats["gs://o/s.ply"])
    )


class TestBuildBoxObject:
    def test_resolved_winner_ships(self, monkeypatch):
        """A rival assignment whose best cloud score clears the margin
        resolves the mapping; the shipped candidate is that assignment's
        (+,+) sign (the sign leaf stays convention-bound)."""
        box, ctx, assoc = _assoc_scene()
        cands = _cands(box, ctx)
        assert len(cands) == 8  # 2 assignments x 4 signs
        cloud_scores = [0.5, 0.4, 0.3, 0.2, 0.75, 0.6, 0.1, 0.1]
        obj = _built(box, ctx, assoc, monkeypatch,
                     cloud_scores=cloud_scores, pair_scores=[0.5, 0.4])
        assert obj["placed"] is True
        assert obj["method"] == "roomplan_box"
        assert obj["position_source"] == "roomplan_box"
        assert obj["splat_axis_resolved"] is True
        assert obj["facing_flag"] is False
        assert obj["quality"]["axis_margin"] == pytest.approx(0.25)
        assert obj["world_transform"]["rotation_xyzw"] == list(cands[4].rotation_xyzw)
        assert cands[4].signs == (1, 1)

    def test_below_margin_ships_default_unresolved(self, monkeypatch):
        box, ctx, assoc = _assoc_scene()
        cands = _cands(box, ctx)
        cloud_scores = [0.50, 0.4, 0.3, 0.2, 0.52, 0.4, 0.1, 0.1]
        obj = _built(box, ctx, assoc, monkeypatch,
                     cloud_scores=cloud_scores, pair_scores=[0.5, 0.4])
        assert obj["splat_axis_resolved"] is False
        assert obj["quality"]["axis_margin"] == pytest.approx(0.02)
        assert obj["world_transform"]["rotation_xyzw"] == list(cands[0].rotation_xyzw)

    def test_single_assignment_never_resolves(self, monkeypatch):
        """With one surviving assignment there is no rival — margin None,
        default ships (the live failure mode the walk found, now honest)."""
        box, ctx, assoc = _assoc_scene(dims=(2.0, 0.5, 1.0), ext=(1.0, 0.25, 0.5))
        cands = _cands(box, ctx)
        assert len({c.assignment for c in cands}) == 1
        obj = _built(box, ctx, assoc, monkeypatch,
                     cloud_scores=[0.9, 0.5, 0.4, 0.3], pair_scores=[0.5, 0.4])
        assert obj["splat_axis_resolved"] is False
        assert "axis_margin" not in obj["quality"]
        assert obj["world_transform"]["rotation_xyzw"] == list(cands[0].rotation_xyzw)

    def test_no_cloud_ships_default_unresolved(self, monkeypatch):
        """No depth accessor (StubCtx) → no cloud → the up-filtered extent
        default ships, recorded unresolved — the warm re-drive degrade."""
        box, ctx, assoc = _assoc_scene()
        cands = _cands(box, ctx)
        obj = _built(box, ctx, assoc, monkeypatch, pair_scores=[0.5, 0.4])
        assert obj["splat_axis_resolved"] is False
        assert "axis_cloud_points" not in obj["quality"]
        assert obj["world_transform"]["rotation_xyzw"] == list(cands[0].rotation_xyzw)

    def test_facing_flag_fires_flag_only(self, monkeypatch):
        """The appearance scorer prefers the shipped mapping's 180°
        partner: flag it, ship the conventional sign — flag-only v1,
        semantics unchanged from the pre-0081 clause."""
        box, ctx, assoc = _assoc_scene()
        cands = _cands(box, ctx)
        obj = _built(box, ctx, assoc, monkeypatch, pair_scores=[0.50, 0.55])
        assert obj["splat_axis_resolved"] is False
        assert obj["facing_flag"] is True
        assert obj["world_transform"]["rotation_xyzw"] == list(cands[0].rotation_xyzw)

    def test_budget_refused_ships_default_without_scoring(self):
        box, ctx, assoc = _assoc_scene()
        obj = _built(box, ctx, assoc, allow_scoring=False)
        assert obj["placed"] is True
        assert obj["splat_axis_resolved"] is False
        assert obj["quality"]["axis_scored_views"] == 0

    def test_box_owns_position_scale_and_extents(self, monkeypatch):
        box, ctx, assoc = _assoc_scene(dims=(2.0, 0.5, 1.0), ext=(1.0, 0.25, 0.5))
        obj = _built(box, ctx, assoc, monkeypatch, pair_scores=[0.5, 0.4])
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
# The 180-degree sign, arbitrated by the layout rotation (decision 0170)
# ---------------------------------------------------------------------------

def _layout_obs(rotation_xyzw, **kw):
    """An observation carrying a layout rotation, the way a depth_fit
    placement does — the channel `splat_layout_rotation` reads."""
    obs = _obs(**kw)
    obs["placement"] = {
        "placed": True,
        "rotation_source": "sam3d_layout",
        "world_transform": {
            "position": [0.0, 0.0, -3.0],
            "rotation_xyzw": list(rotation_xyzw),
            "scale": 1.0,
        },
    }
    return obs


class TestFacingSign:
    """`resolve_facing_sign` in isolation: it may only ever choose between
    the shipped candidate and its 180-degree partner, and it must abstain
    rather than guess."""

    def _pair(self):
        cands = box_placement.axis_mapping_candidates(
            _box(), np.array([1.0, 0.25, 0.5])
        )
        return cands, box_placement._partner_index(cands, 0)

    def test_no_layout_abstains(self):
        cands, _ = self._pair()
        assert box_placement.resolve_facing_sign(cands, 0, None) == (0, False, None, None)

    def test_no_candidates_abstains(self):
        assert box_placement.resolve_facing_sign([], 0, np.eye(3)) == (0, False, None, None)

    def test_no_partner_abstains(self):
        """A candidate list holding only one sign of the assignment has no
        180-degree partner, so there is no choice to make."""
        cands, partner = self._pair()
        only_chosen = [cands[0]] + [c for c in cands if c.assignment != cands[0].assignment]
        R = quat_to_rotmat(cands[partner].rotation_xyzw)
        idx, resolved, resid, sep = box_placement.resolve_facing_sign(only_chosen, 0, R)
        assert (idx, resolved, resid, sep) == (0, False, None, None)

    def test_layout_on_the_shipped_sign_keeps_it(self):
        cands, _ = self._pair()
        R = quat_to_rotmat(cands[0].rotation_xyzw)
        idx, resolved, resid, sep = box_placement.resolve_facing_sign(cands, 0, R)
        assert (idx, resolved) == (0, True)
        assert resid == pytest.approx(0.0, abs=1e-9)
        assert sep == pytest.approx(180.0, abs=1e-9)

    def test_layout_on_the_partner_flips_to_it(self):
        cands, partner = self._pair()
        R = quat_to_rotmat(cands[partner].rotation_xyzw)
        idx, resolved, resid, sep = box_placement.resolve_facing_sign(cands, 0, R)
        assert (idx, resolved) == (partner, True)
        assert resid == pytest.approx(0.0, abs=1e-9)

    def test_layout_between_the_two_abstains(self):
        """Equidistant from both signs, the layout has nothing to say. The
        residual is still reported, so an abstention is legible rather than
        silent."""
        cands, partner = self._pair()
        quarter = quat_to_rotmat((0.0, np.sin(np.pi / 4), 0.0, np.cos(np.pi / 4)))
        R = quarter @ quat_to_rotmat(cands[0].rotation_xyzw)
        idx, resolved, resid, sep = box_placement.resolve_facing_sign(cands, 0, R)
        assert (idx, resolved) == (0, False)
        assert resid == pytest.approx(90.0, abs=1e-6)
        assert sep == pytest.approx(0.0, abs=1e-6)

    def test_gate_is_what_separates_deciding_from_abstaining(self, monkeypatch):
        """The same layout rotation decides or abstains purely on the gate:
        it is the residual that carries the authority, not the preference."""
        cands, partner = self._pair()
        tilt = quat_to_rotmat((0.0, np.sin(np.pi / 12), 0.0, np.cos(np.pi / 12)))  # 30 deg
        R = tilt @ quat_to_rotmat(cands[partner].rotation_xyzw)
        monkeypatch.setattr(box_placement, "_FACING_SIGN_MAX_RESIDUAL_DEG", 45.0)
        idx, resolved, resid, _ = box_placement.resolve_facing_sign(cands, 0, R)
        assert (idx, resolved) == (partner, True)
        assert resid == pytest.approx(30.0, abs=1e-6)
        monkeypatch.setattr(box_placement, "_FACING_SIGN_MAX_RESIDUAL_DEG", 20.0)
        idx, resolved, resid, _ = box_placement.resolve_facing_sign(cands, 0, R)
        assert (idx, resolved) == (0, False)
        assert resid == pytest.approx(30.0, abs=1e-6)

    def test_never_changes_the_assignment(self):
        """Whatever it decides, it decides between two candidates of the
        SAME assignment — the DOF the cloud instrument owns is untouched."""
        cands, _ = self._pair()
        for k in range(len(cands)):
            for R in (np.eye(3), quat_to_rotmat(cands[k].rotation_xyzw)):
                idx, _r, _d, _s = box_placement.resolve_facing_sign(cands, k, R)
                assert cands[idx].assignment == cands[k].assignment
                assert cands[idx].signs[0] == cands[k].signs[0]


class TestFacingSignInBuild:
    """The leaf through `build_box_object`, where it has to leave every
    other decision alone."""

    def _scene(self, sign_index):
        """A box whose associated observation carries a layout rotation
        equal to candidate `sign_index` — so the leaf's answer is known."""
        box = _box()
        ctx, obs = _scene_with_box(box)
        ctx.splats["gs://o/s.ply"] = _slab_cloud((1.0, 0.25, 0.5))
        extents = box_placement.splat_axis_extents(ctx.splats["gs://o/s.ply"])
        plain = box_placement.axis_mapping_candidates(box, extents)
        obs = _layout_obs(plain[sign_index].rotation_xyzw)
        ctx.masks[(0, 0)] = ctx.masks[(0, 0)]
        assoc = box_placement.associate_observations([box], [obs], ctx)[0]
        return box, ctx, assoc, plain

    def test_records_the_preference_but_does_not_act_on_it(self):
        """The shipped default: the disagreement is recorded and the fixed
        convention still ships. This is the whole posture of 0171 and the
        pin that would fail if the default were flipped by accident."""
        box, ctx, assoc, plain = self._scene(sign_index=1)  # the (+, -) partner
        obj = box_placement.build_box_object(
            box=box, box_index=0, object_id="obj_000",
            associations=assoc, ctx=ctx, allow_scoring=False,
        )
        assert obj["facing_sign_resolved"] is True
        assert obj["facing_sign_source"] == "sam3d_layout"
        assert obj["facing_sign_preference"] == "flip"
        assert obj["facing_sign_applied"] is False
        assert obj["quality"]["facing_sign_residual_deg"] == pytest.approx(0.0, abs=1e-6)
        assert obj["world_transform"]["rotation_xyzw"] == list(plain[0].rotation_xyzw)

    def test_flips_to_the_layouts_sign_when_applied(self, monkeypatch):
        monkeypatch.setattr(box_placement, "_FACING_SIGN_APPLY", True)
        box, ctx, assoc, plain = self._scene(sign_index=1)
        obj = box_placement.build_box_object(
            box=box, box_index=0, object_id="obj_000",
            associations=assoc, ctx=ctx, allow_scoring=False,
        )
        assert obj["facing_sign_applied"] is True
        assert obj["world_transform"]["rotation_xyzw"] == list(plain[1].rotation_xyzw)

    def test_keeps_the_convention_when_the_layout_agrees(self, monkeypatch):
        monkeypatch.setattr(box_placement, "_FACING_SIGN_APPLY", True)
        box, ctx, assoc, plain = self._scene(sign_index=0)
        obj = box_placement.build_box_object(
            box=box, box_index=0, object_id="obj_000",
            associations=assoc, ctx=ctx, allow_scoring=False,
        )
        assert obj["facing_sign_resolved"] is True
        assert obj["facing_sign_preference"] == "keep"
        assert obj["world_transform"]["rotation_xyzw"] == list(plain[0].rotation_xyzw)

    def test_turns_the_object_and_nothing_else(self, monkeypatch):
        """Position, scale and extents are the box's measurements; a sign
        decision must not touch any of them."""
        monkeypatch.setattr(box_placement, "_FACING_SIGN_APPLY", True)
        box, ctx, assoc, _ = self._scene(sign_index=1)
        turned = box_placement.build_box_object(
            box=box, box_index=0, object_id="obj_000",
            associations=assoc, ctx=ctx, allow_scoring=False,
        )
        box2, ctx2, assoc2, _ = self._scene(sign_index=1)
        obs2 = assoc2[0].obs
        obs2["placement"] = {}  # same scene, layout channel removed
        kept = box_placement.build_box_object(
            box=box2, box_index=0, object_id="obj_000",
            associations=assoc2, ctx=ctx2, allow_scoring=False,
        )
        assert kept["facing_sign_resolved"] is False
        assert "facing_sign_source" not in kept
        assert turned["world_transform"]["position"] == kept["world_transform"]["position"]
        assert turned["world_transform"]["scale"] == pytest.approx(
            kept["world_transform"]["scale"]
        )
        assert turned["extent_m_sorted"] == kept["extent_m_sorted"]
        assert turned["box_fit_residual"] == kept["box_fit_residual"]
        R_t = quat_to_rotmat(tuple(turned["world_transform"]["rotation_xyzw"]))
        R_k = quat_to_rotmat(tuple(kept["world_transform"]["rotation_xyzw"]))
        assert rotation_angle_deg(R_t, R_k) == pytest.approx(180.0, abs=1e-6)

    def test_an_observation_without_a_layout_is_untouched(self):
        """The degrade lock: no layout channel, no sign claim, and the
        rotation is the same fixed convention that shipped before."""
        box, ctx, assoc = _assoc_scene()
        obj = box_placement.build_box_object(
            box=box, box_index=0, object_id="obj_000",
            associations=assoc, ctx=ctx, allow_scoring=False,
        )
        assert obj["facing_sign_resolved"] is False
        assert "facing_sign_source" not in obj
        assert "facing_sign_residual_deg" not in obj["quality"]
        cands = _cands(box, ctx)
        assert obj["world_transform"]["rotation_xyzw"] == list(cands[0].rotation_xyzw)


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


# ---------------------------------------------------------------------------
# Up-axis extent semantics (decision 0096's named trigger)
# ---------------------------------------------------------------------------

class TestExtentAxes:
    """`extent_axes_m` says which of the box's three extents is vertical.

    The pins that matter are the two directions of the warrant: an upright
    box names its up extent, and a box whose own transform does not put
    local +Y on the world vertical names nothing at all.
    """

    def test_upright_box_names_its_up_extent(self):
        # dims (x, y, z) = (2.0, 0.5, 1.0): a bed-shaped box, 0.5 m tall.
        axes = box_placement.box_extent_axes(_box(dims=(2.0, 0.5, 1.0)))
        assert axes == {
            "up_m": 0.5,
            "horizontal_m": [2.0, 1.0],
            "up_tilt_deg": 0.0,
        }

    def test_up_is_dims_index_1_not_the_largest(self):
        """The whole point: the vertical extent is not recoverable by
        sorting. A wardrobe's up extent IS its largest; a bed's is its
        smallest. Both come from the same index."""
        wardrobe = box_placement.box_extent_axes(_box(dims=(0.9, 1.9, 0.6)))
        bed = box_placement.box_extent_axes(_box(dims=(1.9, 0.6, 2.1)))
        assert wardrobe["up_m"] == 1.9 == max(wardrobe["horizontal_m"] + [1.9])
        assert bed["up_m"] == 0.6 == min(bed["horizontal_m"] + [0.6])

    def test_horizontal_pair_is_descending(self):
        axes = box_placement.box_extent_axes(_box(dims=(0.7, 0.5, 1.4)))
        assert axes["horizontal_m"] == [1.4, 0.7]

    def test_yaw_does_not_disturb_the_up_axis(self):
        """A pure-yaw box is upright at every heading — the real regime."""
        for yaw in (0.0, 0.7, 2.5, -1.9):
            axes = box_placement.box_extent_axes(_box(dims=(2.0, 0.5, 1.0), yaw=yaw))
            assert axes is not None, yaw
            assert axes["up_m"] == 0.5
            assert axes["up_tilt_deg"] == 0.0

    def test_tilted_box_names_nothing(self):
        """Past the gate there is no up extent to report, so the block is
        absent rather than present-and-wrong."""
        box = _box(dims=(2.0, 0.5, 1.0))
        tilt = np.radians(20.0)
        R = np.array([
            [1.0, 0.0, 0.0],
            [0.0, np.cos(tilt), -np.sin(tilt)],
            [0.0, np.sin(tilt), np.cos(tilt)],
        ])
        box.transform = box.transform.copy()
        box.transform[:3, :3] = R
        assert box_placement.box_extent_axes(box) is None

    def test_upside_down_box_names_nothing(self):
        box = _box(dims=(2.0, 0.5, 1.0))
        box.transform = box.transform.copy()
        box.transform[:3, :3] = np.diag([1.0, -1.0, -1.0])
        assert box_placement.box_extent_axes(box) is None

    def test_gate_is_the_tilt_not_the_sign_of_y(self):
        """A box tilted just inside the gate still reports, and its
        measured tilt ships with it — the number is not rounded away."""
        box = _box(dims=(2.0, 0.5, 1.0))
        tilt = np.radians(3.0)
        R = np.array([
            [1.0, 0.0, 0.0],
            [0.0, np.cos(tilt), -np.sin(tilt)],
            [0.0, np.sin(tilt), np.cos(tilt)],
        ])
        box.transform = box.transform.copy()
        box.transform[:3, :3] = R
        axes = box_placement.box_extent_axes(box)
        assert axes is not None
        assert abs(axes["up_tilt_deg"] - 3.0) < 1e-3

    def test_degenerate_dims_name_nothing(self):
        box = _box(dims=(2.0, 0.0, 1.0))
        assert box_placement.box_extent_axes(box) is None


class TestExtentAxesDegradeLock:
    """A reader that does not know the new key must see exactly the block
    it saw before."""

    _PRE_CHANGE_KEYS = {
        "box_id", "identifier", "category", "confidence",
        "attributes", "dims", "yaw_rad", "center_world",
    }

    def test_every_pre_existing_key_is_untouched(self):
        box = _box(dims=(1.9, 0.6, 2.1), yaw=0.4)
        block = box_placement._box_dict(box, 3)
        assert self._PRE_CHANGE_KEYS <= set(block)
        assert set(block) - self._PRE_CHANGE_KEYS == {"extent_axes_m"}
        # dims stays RoomPlan's own local order — provenance, not sorted.
        assert block["dims"] == [1.9, 0.6, 2.1]

    def test_block_is_absent_not_null_when_unwarranted(self):
        """Absent is the state existing consumers already handle; a null
        would be a new shape for them to learn."""
        box = _box(dims=(2.0, 0.5, 1.0))
        box.transform = box.transform.copy()
        box.transform[:3, :3] = np.diag([1.0, -1.0, -1.0])
        assert "extent_axes_m" not in box_placement._box_dict(box, 0)

    def test_extent_m_sorted_is_unchanged_by_this_field(self):
        """The sorted triple keeps its old meaning and old value: the new
        block adds semantics beside it, it does not redefine it."""
        box = _box(dims=(1.9, 0.6, 2.1))
        assert sorted((round(float(d), 4) for d in box.dimensions), reverse=True) == [
            2.1, 1.9, 0.6
        ]
        assert box_placement.box_extent_axes(box)["up_m"] == 0.6

    def test_emission_is_deterministic(self):
        box = _box(dims=(1.9, 0.6, 2.1), yaw=0.4)
        assert box_placement._box_dict(box, 1) == box_placement._box_dict(box, 1)
