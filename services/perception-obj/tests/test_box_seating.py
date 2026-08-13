"""Decision 0148 — where an under-filling splat sits inside its box, and
decision 0147 — which boxes are support surfaces at all.

Both come out of the same measurement. rp7's monitor rests on the top of
the CHAIR tucked under its desk, 0.28 m above the desk, because the
measured half of the support-surface set applied no class rule while the
estimated half did. Fixing that alone leaves the monitor on the desk's
MEASURED top and still 0.206 m above the desk you can see, because the
desk's own splat fills 0.42 of its measured height and was centred in its
box — half the deficit below, half above.

So one vocabulary answers both: a category whose top is a surface things
rest on must have its top right, and is the only kind of box that can BE a
surface.
"""
from __future__ import annotations

import box_placement
import numpy as np
import pytest
from roomplan_room import RoomPlanBox


def _box(center, dims, category="table", yaw=0.0):
    c, s = np.cos(yaw), np.sin(yaw)
    T = np.eye(4)
    T[:3, :3] = np.array([[c, 0.0, s], [0.0, 1.0, 0.0], [-s, 0.0, c]])
    T[:3, 3] = np.asarray(center, dtype=np.float64)
    return RoomPlanBox(
        identifier=f"b-{category}", category=category, confidence="high",
        attributes={}, dimensions=np.asarray(dims, dtype=np.float64),
        transform=T, center_world=T[:3, 3].copy(), up_y=1.0, yaw_rad=float(yaw),
    )


def _slab(half=(0.5, 0.1, 0.3), n=(11, 5, 9)):
    return np.stack(np.meshgrid(
        np.linspace(-half[0], half[0], n[0]),
        np.linspace(-half[1], half[1], n[1]),
        np.linspace(-half[2], half[2], n[2]),
        indexing="ij",
    ), axis=-1).reshape(-1, 3).astype(np.float64)


IDENTITY = (0.0, 0.0, 0.0, 1.0)


class TestVerticalSeat:
    def test_a_full_height_splat_is_left_centred(self):
        box = _box((0, 1.0, 0), (1.0, 0.4, 0.6))
        pts = _slab(half=(0.5, 0.19, 0.3))
        assert box_placement.vertical_seat_offset(box, pts, IDENTITY, 1.0) is None

    def test_a_short_table_is_seated_against_its_measured_top(self):
        """rp7's desk: a tabletop with the legs cut off. Its top is where
        other objects rest, so the top is the end that must be right."""
        box = _box((0, 1.0, 0), (1.0, 0.8, 0.6), category="table")
        pts = _slab(half=(0.5, 0.15, 0.3))  # 0.30 of an 0.80 box
        dy, anchor, fill = box_placement.vertical_seat_offset(box, pts, IDENTITY, 1.0)
        assert anchor == "box_top"
        assert fill == pytest.approx(0.375, abs=0.01)
        assert dy == pytest.approx(0.25, abs=0.01)   # 1.4 top - 1.15 splat top

    def test_a_short_chair_is_seated_on_the_floor(self):
        """A chair's top supports nothing; its one contact worth being
        right is the floor."""
        box = _box((0, 1.0, 0), (1.0, 0.8, 0.6), category="chair")
        pts = _slab(half=(0.5, 0.15, 0.3))
        dy, anchor, _fill = box_placement.vertical_seat_offset(box, pts, IDENTITY, 1.0)
        assert anchor == "box_floor"
        assert dy == pytest.approx(-0.25, abs=0.01)

    def test_seating_never_leaves_the_measured_box(self):
        for category in ("table", "chair"):
            box = _box((0, 1.0, 0), (1.0, 0.8, 0.6), category=category)
            pts = _slab(half=(0.5, 0.15, 0.3))
            dy, _a, _f = box_placement.vertical_seat_offset(box, pts, IDENTITY, 1.0)
            lo = 1.0 + dy - 0.15
            hi = 1.0 + dy + 0.15
            assert lo >= 1.0 - 0.4 - 1e-9 and hi <= 1.0 + 0.4 + 1e-9


class TestSeatedObjectStaysConsistent:
    def _entry(self, category):
        box = _box((0, 1.0, 0), (1.0, 0.8, 0.5), category=category)
        pts = _slab(half=(0.5, 0.15, 0.25))

        class Ctx:
            get_appearance = None
            get_rgb = None

            def get_splat(self, uri):
                return pts

            def get_camera(self, fi):
                return None

            def mask_for(self, *a):
                return None

            def evidence_for(self, *a):
                return None

        # A layout prior calling the splat's own +Y up, so the axis filter
        # settles on the mapping that puts the THIN axis vertical — which
        # is the regime seating exists for (rp7's legless desk).
        assoc = box_placement.BoxAssociation(
            box_index=0, frame_index=0, mask_index=0, overlap=1.0,
            in_frame_fraction=1.0,
            obs={
                "splat_gcs_uri": "gs://o/s.ply", "score": 0.9, "label": "desk",
                "placement": {"world_rotation_xyzw": [0.0, 0.0, 0.0, 1.0]},
            },
        )
        return box, pts, box_placement.build_box_object(
            box=box, box_index=0, object_id="obj_000", associations=[assoc],
            ctx=Ctx(), allow_scoring=False,
        )

    def test_the_object_ships_the_seated_position(self):
        _box_, _pts, entry = self._entry("table")
        assert entry["quality"]["vertical_seat_anchor"] == "box_top"
        assert entry["world_transform"]["position"][1] > 1.0

    def test_only_the_height_moves(self):
        """Seating answers a question about the box's TOP and FLOOR. The
        horizontal placement is RoomPlan measurement and is not up for
        revision by it."""
        box, _pts, entry = self._entry("table")
        pos = entry["world_transform"]["position"]
        assert pos[0] == pytest.approx(float(box.center_world[0]))
        assert pos[2] == pytest.approx(float(box.center_world[2]))

    def test_the_clip_volume_follows_the_object(self):
        """The clip is measured against where the object actually IS. A
        clip computed at the box centre for an object seated against a face
        would report a removed fraction the renderer never applies."""
        box = _box((0, 1.0, 0), (1.0, 0.8, 0.6), category="table")
        pts = _slab(half=(0.9, 0.15, 0.3), n=(31, 5, 9))
        at_centre = box_placement.splat_clip_block(box, pts, IDENTITY, 1.0)
        seated = box_placement.splat_clip_block(
            box, pts, IDENTITY, 1.0, np.array([0.0, 1.45, 0.0])
        )
        assert at_centre is not None and seated is not None
        assert seated["removed_fraction"] > at_centre["removed_fraction"]

    def test_the_default_position_is_still_the_box_centre(self):
        """The degrade lock: every caller that does not pass a position —
        including the whole pre-0148 test suite — gets the old behaviour."""
        box = _box((0, 1.0, 0), (1.0, 0.8, 0.6))
        pts = _slab(half=(0.9, 0.15, 0.3), n=(31, 5, 9))
        assert box_placement.splat_clip_block(box, pts, IDENTITY, 1.0) == (
            box_placement.splat_clip_block(
                box, pts, IDENTITY, 1.0, box.center_world
            )
        )


class TestSurfaceVocabularyIsShared:
    def test_fusion_reads_box_placement_s_vocabulary(self):
        """One question, one home: which categories have a top that things
        rest on. A second copy would drift."""
        import fusion
        assert fusion._SUPPORT_BOX_CATEGORIES is box_placement.SURFACE_TOP_CATEGORIES
