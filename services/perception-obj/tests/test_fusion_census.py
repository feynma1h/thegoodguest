"""Census-aware fusion invariants (decision 0077; fusion.py + box_placement).

The load-bearing locks, each pinned:
  * DEGRADE: without a parsed CapturedRoom (ctx.get_roomplan absent or
    None) fusion output is json-IDENTICAL to the pre-0077 pass; with
    PLACEMENT_REFINE=0 the census machinery is entirely inert.
  * One object per box, in Apple's array order; associated observations
    are CONSUMED (never double-shipped as long-tail objects); unmatched
    observations flow through the existing pipeline untouched.
  * The three long-tail gates on their measured mechanics: cross-label
    near-identity dedup (the f242 triple's structure) with nested-parent
    protection; mirror depth-trust demotion at the recorded RMS values
    (0.196 demotes, 0.007 stays); textile silhouette-span flag (flag-only).
  * Box-duplicate suppression: recorded, never silently gone.

Run from repo root:
    python -m pytest services/perception-obj/tests/test_fusion_census.py -v
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from types import SimpleNamespace

import box_placement
import fusion
import numpy as np
from roomplan_room import RoomPlanBox
from roomstudio_schemas.placement_math import prepare_mask


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
    category="bed", center=(0.0, 0.0, -3.0), dims=(2.0, 0.5, 1.0),
    yaw=0.0, identifier="B1",
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


def _slab_cloud(ext=(1.0, 0.25, 0.5), n=800) -> np.ndarray:
    rng = np.random.default_rng(7)
    return rng.uniform(-0.5, 0.5, size=(n, 3)) * np.asarray(ext)


@dataclass
class CensusCtx:
    """RefinementContext stand-in with the census seam."""

    cameras: dict = field(default_factory=dict)
    masks: dict = field(default_factory=dict)  # (frame, mask_idx) → bool array
    splats: dict = field(default_factory=dict)
    room: object = None
    get_appearance: object = None
    get_rgb: object = None
    get_room_planes: object = None
    budget: object = None
    min_remaining_s: float = 0.0
    _evidence_cache: dict = field(default_factory=dict)

    def get_camera(self, frame_index):
        return self.cameras.get(frame_index)

    def get_mask_stack(self, frame_index):
        idxs = [k[1] for k in self.masks if k[0] == frame_index]
        if not idxs:
            return None
        n = max(idxs) + 1
        shape = next(iter(self.masks.values())).shape
        stack = np.zeros((n,) + shape, dtype=bool)
        for (fi, mi), m in self.masks.items():
            if fi == frame_index:
                stack[mi] = m
        return stack

    def mask_for(self, frame_index, mask_index):
        return self.masks.get((frame_index, mask_index))

    def evidence_for(self, frame_index, mask_index):
        key = (frame_index, mask_index)
        if key not in self._evidence_cache:
            m = self.mask_for(frame_index, mask_index)
            self._evidence_cache[key] = None if m is None else prepare_mask(m)
        return self._evidence_cache[key]

    def get_splat(self, uri):
        return self.splats.get(uri)

    def get_roomplan(self):
        return self.room


def _room_with(boxes: list[RoomPlanBox]):
    return SimpleNamespace(objects=boxes)


def _obs_entry(
    label="bed", score=0.9, mask_index=0, uri=None,
    placed=False, position=(0, 0, -3), nn_rms=None, scale=1.0,
    view_ray=None, world_rotation=(0.0, 0.0, 0.0, 1.0),
):
    uri = uri or f"gs://o/{label}_{mask_index}.ply"
    entry = {
        "label": label,
        "instance_idx": 0,
        "bbox": [0, 0, 10, 10],
        "score": score,
        "mask_index": mask_index,
        "ok": True,
        "splat_gcs_uri": uri,
    }
    if placed:
        entry["placement"] = {
            "placed": True,
            "method": "depth_fit",
            "rotation_source": "sam3d_layout",
            "world_transform": {
                "position": list(position),
                "rotation_xyzw": [0.0, 0.0, 0.0, 1.0],
                "scale": scale,
            },
            "quality": {"nn_rms_m": nn_rms, "min_axis_to_vertical_deg": 5.0},
            "layout_prior": None,
        }
    else:
        entry["placement"] = {
            "placed": False,
            "method": None,
            "reason": "no_depth_pending_triangulation",
            "world_transform": None,
            "quality": {},
            "splat_max_extent": 1.0,
        }
        if world_rotation is not None:
            entry["placement"]["world_rotation_xyzw"] = list(world_rotation)
    if view_ray is not None:
        o, d = view_ray
        d = np.asarray(d, dtype=float)
        entry["view_ray"] = {
            "origin": list(o),
            "direction": (d / np.linalg.norm(d)).tolist(),
            "angular_extent_rad": 0.3,
        }
    return entry


def _frames(*objects_per_frame):
    return [
        {"frame_index": i, "objects": list(objs), "ok": True}
        for i, objs in enumerate(objects_per_frame)
    ]


def _scene_for_box(box, n_frames=2, label="bed"):
    """A ctx + frame_results where `label` masks in n_frames match the box
    footprint from distinct cameras."""
    ctx = CensusCtx()
    frames = []
    for i in range(n_frames):
        pose = FakePose(pos_x=0.3 * i)
        intr = FakeIntrinsics()
        ctx.cameras[i] = (pose, intr)
        hull, _ = box_placement.project_box_footprint(box, intr, pose)
        ctx.masks[(i, 0)] = _mask_from_hull(hull)
        entry = _obs_entry(label=label, mask_index=0, uri=f"gs://o/{label}_{i}.ply")
        ctx.splats[f"gs://o/{label}_{i}.ply"] = _slab_cloud()
        frames.append([entry])
    return ctx, _frames(*frames)


# ---------------------------------------------------------------------------
# Degrade locks
# ---------------------------------------------------------------------------

class TestDegradeLocks:
    def test_no_roomplan_is_json_identical(self):
        """ctx without a census (get_roomplan returns None) produces output
        json-identical to a ctx that has no get_roomplan at all — the
        pre-0077 pass."""
        box = _box()
        ctx_a, frames = _scene_for_box(box)
        ctx_a.room = None
        out_a = fusion.fuse_scene_objects(frames, ctx_a)

        ctx_b, frames_b = _scene_for_box(box)
        ctx_b.get_roomplan = None  # the seam absent entirely
        out_b = fusion.fuse_scene_objects(frames_b, ctx_b)
        assert json.dumps(out_a, sort_keys=True) == json.dumps(out_b, sort_keys=True)
        assert all(not o.get("roomplan_box") for o in out_a)

    def test_placement_refine_zero_is_legacy(self, monkeypatch):
        monkeypatch.setenv("PLACEMENT_REFINE", "0")
        box = _box()
        ctx, frames = _scene_for_box(box)
        ctx.room = _room_with([box])
        out = fusion.fuse_scene_objects(frames, ctx)
        legacy = fusion._fuse_scene_objects_legacy(frames)
        assert json.dumps(out, sort_keys=True) == json.dumps(legacy, sort_keys=True)


# ---------------------------------------------------------------------------
# Box objects + consumption
# ---------------------------------------------------------------------------

class TestBoxObjects:
    def test_one_object_per_box_observations_consumed(self):
        box = _box()
        ctx, frames = _scene_for_box(box, n_frames=2)
        ctx.room = _room_with([box])
        out = fusion.fuse_scene_objects(frames, ctx)
        box_objs = [o for o in out if o.get("roomplan_box")]
        assert len(box_objs) == 1
        assert box_objs[0]["object_id"] == "obj_000"
        assert box_objs[0]["placed"] is True
        assert box_objs[0]["method"] == "roomplan_box"
        # No long-tail bed object — both observations were consumed.
        assert not any(
            o["label"] == "bed" and not o.get("roomplan_box") for o in out
        )

    def test_unmatched_observation_flows_through(self):
        box = _box()
        ctx, frames = _scene_for_box(box, n_frames=2)
        ctx.room = _room_with([box])
        # A lamp (family-incompatible) in frame 0, plus rays so the legacy
        # path has something to do.
        lamp = _obs_entry(
            label="lamp", mask_index=1,
            view_ray=((0, 0, 0), (0, 0, -1)),
        )
        ctx.masks[(0, 1)] = np.zeros((64, 64), dtype=bool)
        ctx.masks[(0, 1)][:5, :5] = True
        frames[0]["objects"].append(lamp)
        out = fusion.fuse_scene_objects(frames, ctx)
        labels = [(o["label"], bool(o.get("roomplan_box"))) for o in out]
        assert ("bed", True) in labels
        assert ("lamp", False) in labels

    def test_unmatched_box_ships_inventory(self):
        box = _box(center=(50.0, 0.0, -50.0))  # nowhere near any mask
        ctx, frames = _scene_for_box(_box(), n_frames=1)
        ctx.room = _room_with([box])
        out = fusion.fuse_scene_objects(frames, ctx)
        inv = [o for o in out if o.get("roomplan_box")]
        assert len(inv) == 1
        assert inv[0]["placed"] is False
        assert inv[0]["reason"] == "no_appearance"
        assert inv[0]["extent_m_sorted"] == [2.0, 1.0, 0.5]

    def test_box_order_is_apple_order(self):
        b0 = _box(identifier="A", center=(0.0, 0.0, -3.0))
        b1 = _box(identifier="B", center=(50.0, 0.0, -50.0))
        ctx, frames = _scene_for_box(b0, n_frames=1)
        ctx.room = _room_with([b0, b1])
        out = fusion.fuse_scene_objects(frames, ctx)
        box_objs = [o for o in out if o.get("roomplan_box")]
        assert [o["roomplan_box"]["identifier"] for o in box_objs] == ["A", "B"]
        assert [o["object_id"] for o in box_objs] == ["obj_000", "obj_001"]


# ---------------------------------------------------------------------------
# Gate (i): cross-label near-identity dedup
# ---------------------------------------------------------------------------

class TestCrossLabelDedup:
    def _triple_scene(self):
        """The f242 structure: one region under three labels, one frame."""
        ctx = CensusCtx()
        ctx.cameras[0] = (FakePose(), FakeIntrinsics())
        region = np.zeros((64, 64), dtype=bool)
        region[20:40, 20:40] = True
        entries = []
        for mi, (label, score) in enumerate(
            [("artwork", 0.9), ("painting", 0.8), ("mirror", 0.7)]
        ):
            ctx.masks[(0, mi)] = region.copy()
            e = _obs_entry(
                label=label, score=score, mask_index=mi,
                view_ray=((0, 0, 0), (0, 0, -1)),
            )
            entries.append(e)
        ctx.room = _room_with([])  # census present (parsed room), no boxes
        return ctx, _frames(entries)

    def test_triple_collapses_to_one(self):
        ctx, frames = self._triple_scene()
        out = fusion.fuse_scene_objects(frames, ctx)
        assert len(out) == 1
        assert out[0]["label"] == "artwork"  # best score wins, label kept
        assert out[0]["deduped_observations"] == 2

    def test_without_census_all_three_ship(self):
        ctx, frames = self._triple_scene()
        ctx.room = None
        out = fusion.fuse_scene_objects(frames, ctx)
        assert len(out) == 3  # today's behaviour: labels never merge

    def test_nested_parent_not_absorbed(self):
        """A small mask genuinely inside a larger different-label mask is
        NOT near-identical (intersection-over-larger low) — never merged."""
        ctx = CensusCtx()
        ctx.cameras[0] = (FakePose(), FakeIntrinsics())
        big = np.zeros((64, 64), dtype=bool)
        big[10:50, 10:50] = True
        small = np.zeros((64, 64), dtype=bool)
        small[20:28, 20:28] = True
        ctx.masks[(0, 0)] = big
        ctx.masks[(0, 1)] = small
        entries = [
            _obs_entry(label="mirror", score=0.9, mask_index=0,
                       view_ray=((0, 0, 0), (0, 0, -1))),
            _obs_entry(label="painting", score=0.8, mask_index=1,
                       view_ray=((0, 0, 0), (0, 0, -1))),
        ]
        ctx.room = _room_with([])
        out = fusion.fuse_scene_objects(_frames(entries), ctx)
        assert len(out) == 2


# ---------------------------------------------------------------------------
# Gate (ii): mirror depth-trust demotion (recorded RMS values)
# ---------------------------------------------------------------------------

class TestDepthTrust:
    def _mirror_scene(self, nn_rms):
        ctx = CensusCtx()
        ctx.cameras[0] = (FakePose(), FakeIntrinsics())
        mask = np.zeros((64, 64), dtype=bool)
        mask[10:50, 20:44] = True
        ctx.masks[(0, 0)] = mask
        ctx.splats["gs://o/mirror_0.ply"] = _slab_cloud()
        entry = _obs_entry(
            label="mirror", mask_index=0, uri="gs://o/mirror_0.ply",
            placed=True, position=(0.0, 0.0, -3.0), nn_rms=nn_rms,
            view_ray=((0, 0, 0), (0, 0, -1)),
        )
        ctx.room = _room_with([])
        return ctx, _frames([entry])

    def test_out_of_family_rms_demotes(self):
        """The real mirror's 0.196 m (28x the scene's 0.007 typical): the
        depth fit is never rendered; the object flows down the ray path."""
        ctx, frames = self._mirror_scene(nn_rms=0.1959)
        out = fusion.fuse_scene_objects(frames, ctx)
        assert len(out) == 1
        obj = out[0]
        assert obj["method"] != "depth_fit"
        assert obj["quality"].get("depth_trust_demoted") is True

    def test_in_family_rms_stays_placed(self):
        ctx, frames = self._mirror_scene(nn_rms=0.0066)
        out = fusion.fuse_scene_objects(frames, ctx)
        assert out[0]["placed"] is True
        assert out[0]["method"] == "depth_fit"
        assert "depth_trust_demoted" not in out[0]["quality"]

    def test_without_census_bad_rms_still_ships(self):
        """Today's behaviour preserved on non-roomplan scenes."""
        ctx, frames = self._mirror_scene(nn_rms=0.1959)
        ctx.room = None
        out = fusion.fuse_scene_objects(frames, ctx)
        assert out[0]["placed"] is True
        assert out[0]["method"] == "depth_fit"


# ---------------------------------------------------------------------------
# Gate (iii): textile silhouette-span (flag-only)
# ---------------------------------------------------------------------------

class TestSilhouetteSpan:
    def _rug_scene(self, splat_scale):
        """A depth_fit rug whose splat projects at splat_scale of the
        mask's span."""
        ctx = CensusCtx()
        ctx.cameras[0] = (FakePose(), FakeIntrinsics())
        mask = np.zeros((64, 64), dtype=bool)
        mask[16:48, 8:56] = True  # 48 px wide
        ctx.masks[(0, 0)] = mask
        # A flat splat centered at (0,0,-3): full extent chosen so the
        # projection spans splat_scale x the mask span.
        span_m = 48 / 60.0 * 3.0  # pixels -> meters at depth 3, fx 60
        ext = span_m * splat_scale
        ctx.splats["gs://o/rug_0.ply"] = _slab_cloud(ext=(ext, ext * 0.6, 0.01))
        entry = _obs_entry(
            label="rug", mask_index=0, uri="gs://o/rug_0.ply",
            placed=True, position=(0.0, 0.0, -3.0), nn_rms=0.008, scale=1.0,
        )
        ctx.room = _room_with([])
        return ctx, _frames([entry])

    def test_collapsed_scale_flagged(self):
        ctx, frames = self._rug_scene(splat_scale=0.3)
        out = fusion.fuse_scene_objects(frames, ctx)
        obj = out[0]
        assert obj["placed"] is True  # flag-only: the transform stands
        assert obj.get("scale_suspect") is True
        assert obj["quality"]["silhouette_span_ratio"] < 0.5

    def test_healthy_scale_not_flagged(self):
        ctx, frames = self._rug_scene(splat_scale=0.95)
        out = fusion.fuse_scene_objects(frames, ctx)
        obj = out[0]
        assert "scale_suspect" not in obj
        assert obj["quality"]["silhouette_span_ratio"] >= 0.5

    def test_without_census_no_ratio_computed(self):
        ctx, frames = self._rug_scene(splat_scale=0.3)
        ctx.room = None
        out = fusion.fuse_scene_objects(frames, ctx)
        assert "silhouette_span_ratio" not in out[0]["quality"]


# ---------------------------------------------------------------------------
# Box-duplicate suppression
# ---------------------------------------------------------------------------

class TestSuppression:
    def test_duplicate_inside_matched_box_demoted(self):
        box = _box()  # bed at (0, 0, -3)
        ctx, frames = _scene_for_box(box, n_frames=1)
        ctx.room = _room_with([box])
        # A second, independent placed "bed" whose center sits inside the
        # box volume but whose mask doesn't associate (tiny, off-footprint).
        dup_mask = np.zeros((64, 64), dtype=bool)
        dup_mask[:4, 60:] = True
        ctx.masks[(0, 1)] = dup_mask
        dup = _obs_entry(
            label="bed", mask_index=1, uri="gs://o/dup.ply",
            placed=True, position=(0.2, 0.1, -3.0), nn_rms=0.008,
        )
        ctx.splats["gs://o/dup.ply"] = _slab_cloud()
        frames[0]["objects"].append(dup)
        out = fusion.fuse_scene_objects(frames, ctx)
        suppressed = [o for o in out if o.get("box_duplicate_suppressed")]
        assert len(suppressed) == 1
        s = suppressed[0]
        assert s["placed"] is False
        assert s["reason"] == "box_duplicate"
        assert s["suppressed_by_box"] == "box_00"

    def test_outside_box_not_suppressed(self):
        box = _box()
        ctx, frames = _scene_for_box(box, n_frames=1)
        ctx.room = _room_with([box])
        dup_mask = np.zeros((64, 64), dtype=bool)
        dup_mask[:4, 60:] = True
        ctx.masks[(0, 1)] = dup_mask
        far = _obs_entry(
            label="bed", mask_index=1, uri="gs://o/far.ply",
            placed=True, position=(4.0, 0.0, -3.0), nn_rms=0.008,
        )
        ctx.splats["gs://o/far.ply"] = _slab_cloud()
        frames[0]["objects"].append(far)
        out = fusion.fuse_scene_objects(frames, ctx)
        assert not any(o.get("box_duplicate_suppressed") for o in out)
        placed_beds = [
            o for o in out
            if o["label"] == "bed" and o["placed"] and not o.get("roomplan_box")
        ]
        assert len(placed_beds) == 1
