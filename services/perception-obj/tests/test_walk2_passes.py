"""Decision 0104 — the 0085 consolidated-walk fixes.

Four mechanisms, each pinned here as a table rather than left reviewable
only by reading fusion.py:

  * splat clipping — a box-anchored splat that overshoots its measured box
    declares a clip volume instead of moving or rescaling the object;
  * support surfaces — contact height follows the RENDERED top, a measured
    box surface always beats an estimated splat one, and the pass is
    order-independent;
  * the label scale floor — a 0.245 m "television" is a failed
    reconstruction, not a small television, and ships as inventory;
  * the two vocabulary gaps the walk exposed: RoomPlan files a nightstand
    as `storage` where SAM says `nightstand`, and a box object is labelled
    with its RoomPlan CATEGORY, which the dedup groups did not speak.

Real-data pins for the same mechanisms live in
test_axis_cloud_real_data.py (splat clip, on the spike scene's own splats).
"""
from __future__ import annotations

import box_placement
import fusion
import numpy as np
import pytest

# ---------------------------------------------------------------------------
# Minimal stand-ins
# ---------------------------------------------------------------------------

class FakeBox:
    """A yaw-only RoomPlan box (the real ones are pure-yaw by construction)."""

    def __init__(self, center, dims, yaw=0.0, category="table", confidence="high"):
        self.center_world = np.asarray(center, dtype=np.float64)
        self.dimensions = np.asarray(dims, dtype=np.float64)
        self.yaw_rad = float(yaw)
        self.category = category
        self.confidence = confidence
        self.identifier = f"{category}-id"
        self.attributes = {}
        c, s = np.cos(yaw), np.sin(yaw)
        R = np.array([[c, 0.0, s], [0.0, 1.0, 0.0], [-s, 0.0, c]])
        self.transform = np.eye(4)
        self.transform[:3, :3] = R
        self.transform[:3, 3] = self.center_world


class Ctx:
    """RefinementContext stand-in: splats by uri, nothing else."""

    def __init__(self, splats=None):
        self.splats = splats or {}
        self.get_appearance = None
        self.get_rgb = None

    def get_splat(self, uri):
        return self.splats.get(uri)

    def get_camera(self, frame_index):
        return None

    def mask_for(self, *a):
        return None

    def evidence_for(self, *a):
        return None


def _grid(nx=9, ny=5, nz=9, half=(0.5, 0.25, 0.5)):
    """A filled box of points centred on the origin, half-extents `half`."""
    g = np.stack(np.meshgrid(
        np.linspace(-half[0], half[0], nx),
        np.linspace(-half[1], half[1], ny),
        np.linspace(-half[2], half[2], nz),
        indexing="ij",
    ), axis=-1).reshape(-1, 3)
    return g.astype(np.float64)


def _obj(object_id, label, position, uri="gs://o/s.ply", placed=True, **kw):
    o = {
        "object_id": object_id,
        "label": label,
        "placed": placed,
        "splat_gcs_uri": uri,
        "world_transform": {
            "position": list(position),
            "rotation_xyzw": [0.0, 0.0, 0.0, 1.0],
            "scale": 1.0,
        },
        "quality": {},
    }
    o.update(kw)
    return o


# ---------------------------------------------------------------------------
# Splat clipping
# ---------------------------------------------------------------------------

class TestSplatClip:
    def test_no_block_when_the_splat_fits(self):
        box = FakeBox((0, 0, 0), (1.0, 0.6, 1.0))
        pts = _grid(half=(0.4, 0.2, 0.4))
        assert box_placement.splat_clip_block(box, pts, (0, 0, 0, 1), 1.0) is None

    def test_block_measures_the_overshoot(self):
        box = FakeBox((0, 0, 0), (1.0, 0.6, 1.0))
        # Half-extent 1.2 along x vs a 0.5 half-box + 0.10 margin.
        pts = _grid(nx=21, half=(1.2, 0.2, 0.4))
        clip = box_placement.splat_clip_block(box, pts, (0, 0, 0, 1), 1.0)
        assert clip is not None
        assert clip["kind"] == "roomplan_box"
        assert clip["margin_m"] == pytest.approx(0.10)
        assert clip["half_extents_m"] == pytest.approx([0.6, 0.4, 0.6])
        assert 0.0 < clip["removed_fraction"] < 1.0

    def test_block_follows_the_box_yaw(self):
        """A rotated box must clip in ITS frame, not the world's. The box
        is deliberately oblong — a square footprint is yaw-invariant and
        would pass this test without testing anything."""
        pts = _grid(nx=21, half=(1.2, 0.2, 0.4))
        straight = box_placement.splat_clip_block(
            FakeBox((0, 0, 0), (1.0, 0.6, 3.0), yaw=0.0), pts, (0, 0, 0, 1), 1.0)
        turned = box_placement.splat_clip_block(
            FakeBox((0, 0, 0), (1.0, 0.6, 3.0), yaw=np.pi / 2), pts, (0, 0, 0, 1), 1.0)
        # Turned, the box's long axis lies along the splat's long axis and
        # nothing leaves it; straight, the overshoot is clipped.
        assert straight is not None
        assert turned is None

    def test_scale_is_applied_before_the_containment_test(self):
        box = FakeBox((0, 0, 0), (1.0, 0.6, 1.0))
        pts = _grid(half=(0.4, 0.2, 0.4))
        assert box_placement.splat_clip_block(box, pts, (0, 0, 0, 1), 1.0) is None
        assert box_placement.splat_clip_block(box, pts, (0, 0, 0, 1), 3.0) is not None


class TestClippedWorldPoints:
    def test_absent_clip_is_a_passthrough(self):
        ctx = Ctx({"gs://o/s.ply": _grid()})
        obj = _obj("obj_000", "table", (0, 0, 0))
        assert np.array_equal(
            fusion._clipped_world_points(obj, ctx),
            fusion._sampled_world_points(obj, ctx),
        )

    def test_clip_removes_the_outside_points(self):
        ctx = Ctx({"gs://o/s.ply": _grid(nx=21, half=(1.2, 0.2, 0.4))})
        obj = _obj("obj_000", "table", (0, 0, 0), splat_clip={
            "kind": "roomplan_box", "margin_m": 0.1,
            "center_world": [0.0, 0.0, 0.0],
            "half_extents_m": [0.6, 0.4, 0.6], "yaw_rad": 0.0,
        })
        raw = fusion._sampled_world_points(obj, ctx)
        clipped = fusion._clipped_world_points(obj, ctx)
        assert clipped.shape[0] < raw.shape[0]
        assert float(np.abs(clipped[:, 0]).max()) <= 0.6 + 1e-9

    def test_malformed_clip_degrades_to_the_raw_points(self):
        ctx = Ctx({"gs://o/s.ply": _grid()})
        obj = _obj("obj_000", "table", (0, 0, 0), splat_clip={"kind": "roomplan_box"})
        assert fusion._clipped_world_points(obj, ctx) is not None


# ---------------------------------------------------------------------------
# Support surfaces
# ---------------------------------------------------------------------------

class TestSupportSurfaces:
    def _table_box_and_object(self, proud):
        """A table box topped by a splat standing `proud` metres above it."""
        box = FakeBox((0, 0, 0), (1.0, 0.6, 1.0))          # top at +0.3
        pts = _grid(ny=5, half=(0.4, 0.3 + proud, 0.4))    # top at +0.3+proud
        ctx = Ctx({"gs://o/table.ply": pts})
        obj = _obj("obj_000", "table", (0, 0, 0), uri="gs://o/table.ply",
                   roomplan_box={"box_id": "box_00"})
        return box, ctx, obj

    def test_contact_height_follows_the_rendered_top(self):
        """The walk's mechanism: resting on the measured box top still
        looks sunk when the splat stands proud of the box."""
        box, ctx, obj = self._table_box_and_object(proud=0.05)
        surfaces = fusion._support_surfaces([obj], [box], ctx)
        assert surfaces[0]["top"] == pytest.approx(0.35, abs=0.01)

    def test_rendered_top_is_capped_by_the_clip_margin(self):
        box, ctx, obj = self._table_box_and_object(proud=0.60)
        surfaces = fusion._support_surfaces([obj], [box], ctx)
        assert surfaces[0]["top"] == pytest.approx(
            0.3 + fusion._SUPPORT_TOP_MAX_PROUD_M, abs=0.01)

    def test_measurement_is_the_floor_when_the_splat_under_reaches(self):
        """A truncated splat must never drag the surface below the box."""
        box = FakeBox((0, 0, 0), (1.0, 0.6, 1.0))
        ctx = Ctx({"gs://o/table.ply": _grid(half=(0.4, 0.05, 0.4))})
        obj = _obj("obj_000", "table", (0, 0, 0), uri="gs://o/table.ply",
                   roomplan_box={"box_id": "box_00"})
        assert fusion._support_surfaces([obj], [box], ctx)[0]["top"] == pytest.approx(0.3)

    def test_box_surface_wins_over_a_splat_surface(self):
        box = FakeBox((0, 0, 0), (1.0, 0.6, 1.0))
        ctx = Ctx({
            "gs://o/table.ply": _grid(half=(0.4, 0.3, 0.4)),
            "gs://o/desk.ply": _grid(half=(0.4, 0.32, 0.4)),
            "gs://o/lamp.ply": _grid(half=(0.05, 0.05, 0.05)),
        })
        table = _obj("obj_000", "table", (0, 0, 0), uri="gs://o/table.ply",
                     roomplan_box={"box_id": "box_00"})
        desk = _obj("obj_001", "desk", (0, 0, 0), uri="gs://o/desk.ply")
        lamp = _obj("obj_002", "table lamp", (0.0, 0.5, 0.0), uri="gs://o/lamp.ply")
        surfaces = fusion._support_surfaces([table, desk, lamp], [box], ctx)
        out = fusion._snap_onto_support(lamp, [box], ctx, surfaces)
        assert out["quality"]["support_box"] == "box_00"

    def test_splat_surface_used_where_no_box_covers(self):
        ctx = Ctx({
            "gs://o/desk.ply": _grid(half=(0.4, 0.3, 0.4)),
            "gs://o/lamp.ply": _grid(half=(0.05, 0.05, 0.05)),
        })
        desk = _obj("obj_001", "nightstand", (0, 0, 0), uri="gs://o/desk.ply")
        lamp = _obj("obj_002", "table lamp", (0.0, 0.5, 0.0), uri="gs://o/lamp.ply")
        surfaces = fusion._support_surfaces([desk, lamp], [], ctx)
        out = fusion._snap_onto_support(lamp, [], ctx, surfaces)
        assert out["quality"]["support_box"] == "obj_001"
        assert out["world_transform"]["position"][1] < 0.5

    def test_a_lamp_is_never_a_support_surface(self):
        ctx = Ctx({"gs://o/lamp.ply": _grid(half=(0.05, 0.05, 0.05))})
        lamp = _obj("obj_002", "table lamp", (0, 0, 0), uri="gs://o/lamp.ply")
        assert fusion._support_surfaces([lamp], [], ctx) == []

    def test_object_never_rests_on_itself(self):
        ctx = Ctx({"gs://o/d.ply": _grid(half=(0.4, 0.3, 0.4))})
        # A desk is both a support class and a support SURFACE class.
        desk = _obj("obj_001", "desk", (0, 0, 0), uri="gs://o/d.ply")
        surfaces = fusion._support_surfaces([desk], [], ctx)
        assert fusion._snap_onto_support(desk, [], ctx, surfaces) is desk

    def test_surfaces_are_built_once_so_the_pass_is_order_independent(self):
        """Snapping A must not change what B comes to rest on."""
        ctx = Ctx({
            "gs://o/desk.ply": _grid(half=(0.4, 0.3, 0.4)),
            "gs://o/a.ply": _grid(half=(0.05, 0.05, 0.05)),
            "gs://o/b.ply": _grid(half=(0.05, 0.05, 0.05)),
        })
        desk = _obj("obj_000", "desk", (0, 0, 0), uri="gs://o/desk.ply")
        a = _obj("obj_001", "speaker", (0.1, 0.5, 0.0), uri="gs://o/a.ply")
        b = _obj("obj_002", "speaker", (-0.1, 0.5, 0.0), uri="gs://o/b.ply")
        surfaces = fusion._support_surfaces([desk, a, b], [], ctx)
        forward = [fusion._snap_onto_support(o, [], ctx, surfaces) for o in (a, b)]
        backward = [fusion._snap_onto_support(o, [], ctx, surfaces) for o in (b, a)]
        assert forward[0]["world_transform"]["position"][1] == pytest.approx(
            backward[1]["world_transform"]["position"][1])

    def test_v1_call_signature_still_snaps_to_measured_box_tops(self):
        """The three-argument form (no surfaces) keeps v1 behaviour."""
        box = FakeBox((0, 0, 0), (1.0, 0.6, 1.0))
        ctx = Ctx({"gs://o/lamp.ply": _grid(half=(0.05, 0.05, 0.05))})
        lamp = _obj("obj_002", "table lamp", (0.0, 0.6, 0.0), uri="gs://o/lamp.ply")
        out = fusion._snap_onto_support(lamp, [box], ctx)
        assert out["quality"]["support_box"] == "box_00"
        assert out["world_transform"]["position"][1] == pytest.approx(0.35, abs=1e-6)


# ---------------------------------------------------------------------------
# Label scale floor
# ---------------------------------------------------------------------------

class TestLabelScaleFloor:
    def test_collapsed_television_is_demoted(self):
        obj = _obj("obj_017", "tv", (0, 0, 0), extent_m_sorted=[0.245, 0.159, 0.057])
        out = fusion._apply_label_scale_floor(obj)
        assert out["placed"] is False
        assert out["reason"] == "implausible_scale_for_label"
        assert out["quality"]["longest_extent_m"] == pytest.approx(0.245)
        assert out["quality"]["label_scale_floor_m"] == pytest.approx(0.35)

    def test_plausible_television_survives(self):
        obj = _obj("obj_017", "tv", (0, 0, 0), extent_m_sorted=[0.9, 0.5, 0.06])
        assert fusion._apply_label_scale_floor(obj)["placed"] is True

    def test_unlisted_labels_are_untouched(self):
        """A 0.49 m monitor and a 0.20 m artwork are both real objects."""
        for label, longest in (("monitor", 0.49), ("artwork", 0.198)):
            obj = _obj("x", label, (0, 0, 0), extent_m_sorted=[longest, 0.1, 0.01])
            assert fusion._apply_label_scale_floor(obj)["placed"] is True, label

    def test_box_anchored_objects_are_exempt(self):
        """Box extents are RoomPlan measurement, not a reconstruction."""
        obj = _obj("obj_000", "tv", (0, 0, 0), extent_m_sorted=[0.2, 0.1, 0.05],
                   roomplan_box={"box_id": "box_00"})
        assert fusion._apply_label_scale_floor(obj)["placed"] is True

    def test_unplaced_objects_are_untouched(self):
        obj = _obj("x", "tv", (0, 0, 0), placed=False, extent_m_sorted=[0.1])
        assert fusion._apply_label_scale_floor(obj) is obj

    def test_missing_extents_never_demote(self):
        assert fusion._apply_label_scale_floor(_obj("x", "tv", (0, 0, 0)))["placed"] is True


# ---------------------------------------------------------------------------
# The two vocabulary gaps
# ---------------------------------------------------------------------------

class TestVocabularyGaps:
    def test_roomplan_storage_matches_a_sam_nightstand(self):
        """rp7's nightstand: RoomPlan `storage`, SAM `nightstand`."""
        assert box_placement.family_compatible("storage", "nightstand")

    def test_nightstand_still_matches_a_table_box(self):
        assert box_placement.family_compatible("table", "nightstand")

    def test_storage_category_is_confusable_with_cabinet_labels(self):
        """A box object carries its RoomPlan CATEGORY as its label, so the
        dedup groups have to speak that vocabulary too."""
        assert fusion._labels_confusable("storage", "desk")
        assert fusion._labels_confusable("storage", "cabinet")
        assert fusion._labels_confusable("storage", "nightstand")

    def test_television_category_is_confusable_with_monitor(self):
        assert fusion._labels_confusable("television", "monitor")

    def test_unrelated_labels_stay_unconfusable(self):
        assert not fusion._labels_confusable("storage", "bed")
        assert not fusion._labels_confusable("chair", "table")
