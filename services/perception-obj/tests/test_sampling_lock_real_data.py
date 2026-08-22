"""The degrade lock: what the four preserved captures actually shipped.

Every claim in this file is a byte-level reproduction of production output.
`fixtures/sampling_lock/<room>.json` holds, per preserved capture, every
keyframe's pose and intrinsics from the preserved `bundle.pb`, the
CapturedRoom document with `coreModel` stripped (the parser never reads
it), and the `sampling` block of the manifest that scene actually shipped.
The tests replay production's own selector over those inputs and require
the shipped answer back — frame indices, the cover/residue split, the
per-box coverage map, and the uncovered list.

Why it exists: this lane changes what `/process` shows SAM 3D, and the
first thing such a change must prove is that with its flags off it changes
nothing. A unit test over synthetic frames cannot show that — the selector
is a greedy set-cover whose answer depends on the whole frame set, and the
only frame sets that matter are the four real ones. So this is written
before the behaviour change, not after it, and a lane that alters
selection is answerable to it.

Rooms: rp7, rp6g1, rp6g2 and the RoomPlan spike, i.e. every preserved
capture. rp6g2 is included here where decision 0163 excluded it from the
facing-sign pins — the exclusion there was about a manifest assembled over
four rounds from frames the offline cache does not hold, which is a fact
about per-frame RECONSTRUCTION provenance. Selection reads only the bundle
and the CapturedRoom, both preserved whole, and it reproduces.

Run from repo root:
    python -m pytest services/perception-obj/tests/test_sampling_lock_real_data.py -v
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_schemas_path = Path(__file__).resolve().parents[3] / "packages/schemas"
if str(_schemas_path) not in sys.path:
    sys.path.insert(0, str(_schemas_path))

import census_sampling  # noqa: E402
import roomplan_room  # noqa: E402
import sampling  # noqa: E402
from roomstudio_schemas import capture_bundle_pb2  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures" / "sampling_lock"
ROOMS = ("rp7", "rp6g1", "rp6g2", "spike")


def _load(room: str) -> dict:
    return json.loads((FIXTURES / f"{room}.json").read_text())


def _frames(payload: dict) -> list:
    out = []
    for row in payload["frames"]:
        f = capture_bundle_pb2.Frame()
        f.frame_index = row["frame_index"]
        (f.camera_pose.pos_x, f.camera_pose.pos_y, f.camera_pose.pos_z,
         f.camera_pose.quat_x, f.camera_pose.quat_y, f.camera_pose.quat_z,
         f.camera_pose.quat_w) = row["pose"]
        (f.intrinsics.fx, f.intrinsics.fy, f.intrinsics.cx,
         f.intrinsics.cy) = row["intrinsics"][:4]
        f.intrinsics.width, f.intrinsics.height = row["intrinsics"][4:]
        out.append(f)
    return out


def _boxes(payload: dict) -> list:
    room = roomplan_room.parse_captured_room(json.dumps(payload["captured_room"]))
    return list(room.objects)


@pytest.fixture(scope="module", params=ROOMS)
def capture(request):
    payload = _load(request.param)
    return request.param, payload, _frames(payload), _boxes(payload)


class TestShippedSelectionReproduces:
    """The selector, replayed, returns exactly what each scene shipped."""

    def test_selected_frame_indices(self, capture):
        name, payload, frames, boxes = capture
        shipped = payload["shipped_sampling"]
        assert shipped["policy"] == "census_set_cover_v1", name
        selected, _info = census_sampling.select_frames_census(
            frames, boxes, shipped["max_frames"]
        )
        assert [f.frame_index for f in selected] == shipped[
            "selected_frame_indices"
        ], name

    def test_cover_and_residue_split(self, capture):
        name, payload, frames, boxes = capture
        shipped = payload["shipped_sampling"]
        _selected, info = census_sampling.select_frames_census(
            frames, boxes, shipped["max_frames"]
        )
        census = shipped["census"]
        assert info["cover_frame_indices"] == census["cover_frame_indices"], name
        assert info["residue_frame_indices"] == census["residue_frame_indices"], name

    def test_box_coverage_map(self, capture):
        name, payload, frames, boxes = capture
        shipped = payload["shipped_sampling"]
        _selected, info = census_sampling.select_frames_census(
            frames, boxes, shipped["max_frames"]
        )
        census = shipped["census"]
        assert info["box_coverage"] == census["box_coverage"], name
        assert info["uncovered_box_ids"] == census["uncovered_box_ids"], name


# (boxes, cover picks, residue picks) as each scene shipped them. Pinned as
# a table rather than as a rule because the rule people carry around — "the
# cover pass takes 2-3 picks and 9-10 slots go to residue" — is true of the
# two rooms with fewest boxes and false of the other two. Cover picks track
# box count, so the residue share a sampler change has to spend is 75-83%
# on rp7/rp6g1 and 33-42% on spike/rp6g2.
SHIPPED_SPLIT = {
    "rp7": (6, 3, 9),
    "rp6g1": (5, 2, 10),
    "rp6g2": (11, 8, 4),
    "spike": (9, 7, 5),
}


class TestTheShapeOfTheProblemThisLaneAttacks:
    """Facts about the shipped selection, pinned so a change has to face
    them. Not requirements — the measured starting point (0146, 0197)."""

    def test_shipped_cover_residue_split(self, capture):
        name, payload, _frames, boxes = capture
        census = payload["shipped_sampling"]["census"]
        assert (
            len(boxes),
            len(census["cover_frame_indices"]),
            len(census["residue_frame_indices"]),
        ) == SHIPPED_SPLIT[name]

    def test_every_box_is_covered_by_the_cover_pass(self, capture):
        name, payload, _frames, _boxes = capture
        assert payload["shipped_sampling"]["census"]["uncovered_box_ids"] == [], name

    def test_residue_is_object_blind(self, capture):
        """The residue frames are chosen by pose spread alone: dropping the
        boxes entirely and running 0062's sampler from the cover seed gives
        the same residue. That equality IS the defect — 0197's chair had a
        clean view the sampler never looked at, because nothing in this
        pass asks whether a frame sees an object."""
        import numpy as np

        name, payload, frames, boxes = capture
        census = payload["shipped_sampling"]["census"]
        max_frames = payload["shipped_sampling"]["max_frames"]
        cover = census["cover_frame_indices"]
        by_index = {f.frame_index: i for i, f in enumerate(frames)}
        cover_pos = [by_index[i] for i in cover]

        positions, view_dirs = sampling._frame_features(frames)
        dist = sampling._distance_matrix(positions, view_dirs)
        min_dist = dist[cover_pos].min(axis=0)
        picked: list[int] = []
        for _ in range(max_frames - len(cover_pos)):
            min_dist[cover_pos + picked] = -1.0
            nxt = int(np.argmax(min_dist))
            picked.append(nxt)
            min_dist = np.minimum(min_dist, dist[nxt])

        assert sorted(frames[p].frame_index for p in picked) == census[
            "residue_frame_indices"
        ], name
        assert len(boxes) > 0, name  # boxes exist and played no part above


class TestTheNoCensusDegradeIsUntouched:
    """A capture with no CapturedRoom keeps 0062's sampler verbatim. The
    preserved captures all carry a census, so this is pinned on their
    frames with the boxes withheld — the same code path a legacy-tier
    bundle takes."""

    def test_pose_diverse_selection_is_deterministic(self, capture):
        name, payload, frames, _boxes = capture
        max_frames = payload["shipped_sampling"]["max_frames"]
        first = [f.frame_index for f in sampling.select_frames(frames, max_frames)]
        second = [f.frame_index for f in sampling.select_frames(frames, max_frames)]
        assert first == second, name
        assert len(first) == max_frames, name


# What the object-aware residue does to the four preserved captures
# (decision 0202), per room: boxes, then STARVED boxes — the ones with at
# most one qualifying view, so nothing downstream has an alternative arm to
# prefer — then USABLE views, the qualifying views summed with each box
# capped at the plan's own per-box limit of 2, since views past that are
# recorded and never reconstructed.
OBJECT_AWARE_EFFECT = {
    #        boxes, starved before/after, usable before/after
    "rp7": (6, 2, 0, 10, 12),
    "rp6g1": (5, 1, 0, 9, 10),
    "rp6g2": (11, 6, 2, 16, 20),
    "spike": (9, 5, 0, 13, 18),
}


class TestObjectAwareResidue:
    """The residue spent on second views of boxes instead of on pose
    spread. Off by default; these run it explicitly."""

    @staticmethod
    def _select(frames, boxes, *, object_aware: bool):
        import census_sampling as cs

        before = cs.OBJECT_AWARE_RESIDUE
        cs.OBJECT_AWARE_RESIDUE = object_aware
        try:
            return cs.select_frames_census(frames, boxes, 12)
        finally:
            cs.OBJECT_AWARE_RESIDUE = before

    @staticmethod
    def _views_per_box(frames, boxes, selected) -> list[int]:
        _V, Q = census_sampling.box_visibility(frames, boxes)
        pos = {f.frame_index: i for i, f in enumerate(frames)}
        chosen = [pos[f.frame_index] for f in selected]
        return [
            int(sum(Q[p, bi] for p in chosen)) for bi in range(len(boxes))
        ]

    def test_it_is_off_by_default(self):
        assert census_sampling.OBJECT_AWARE_RESIDUE is False

    def test_off_reproduces_the_shipped_selection(self, capture):
        name, payload, frames, boxes = capture
        selected, _info = self._select(frames, boxes, object_aware=False)
        assert [f.frame_index for f in selected] == payload[
            "shipped_sampling"
        ]["selected_frame_indices"], name

    def test_it_feeds_starved_boxes_and_stops_at_the_plans_cap(self, capture):
        name, _payload, frames, boxes = capture
        n_boxes, starved_before, starved_after, usable_before, usable_after = (
            OBJECT_AWARE_EFFECT[name]
        )
        assert len(boxes) == n_boxes

        def measure(object_aware):
            selected, _ = self._select(frames, boxes, object_aware=object_aware)
            per = self._views_per_box(frames, boxes, selected)
            return sum(v <= 1 for v in per), sum(min(v, 2) for v in per)

        assert measure(False) == (starved_before, usable_before), name
        assert measure(True) == (starved_after, usable_after), name

    def test_it_never_uncovers_a_box(self, capture):
        name, _payload, frames, boxes = capture
        _selected, info = self._select(frames, boxes, object_aware=True)
        assert info["uncovered_box_ids"] == [], name

    def test_it_spends_no_extra_frames(self, capture):
        name, payload, frames, boxes = capture
        selected, _info = self._select(frames, boxes, object_aware=True)
        assert len(selected) == payload["shipped_sampling"]["max_frames"], name

    def test_it_is_deterministic(self, capture):
        name, _payload, frames, boxes = capture
        first, _ = self._select(frames, boxes, object_aware=True)
        second, _ = self._select(frames, boxes, object_aware=True)
        assert [f.frame_index for f in first] == [
            f.frame_index for f in second
        ], name

    def test_it_says_so_in_the_manifest_block(self, capture):
        name, _payload, frames, boxes = capture
        _selected, on = self._select(frames, boxes, object_aware=True)
        _selected2, off = self._select(frames, boxes, object_aware=False)
        assert on["residue_policy"] == "object_aware_v1", name
        assert on["views_per_box_target"] == census_sampling.VIEWS_PER_BOX_TARGET
        assert "residue_policy" not in off, name

    def test_it_does_not_reach_the_views_the_hand_fixes_used(self, capture):
        """Recorded because it is the honest limit of this change, not a
        bug in it. 0197 fixed rp7's chair with f275 and rp6g1's table with
        f178, both chosen BY EYES; the residue here picks by pose spread
        from what a box already has, and lands elsewhere. What it buys is
        that the box HAS a second arm at all — which of an object's arms is
        the good one is an output-side question nothing yet asks (see the
        decision note)."""
        name, _payload, frames, boxes = capture
        hand_picked = {"rp7": {275}, "rp6g1": {178}}.get(name)
        if not hand_picked:
            pytest.skip(f"{name} has no hand-picked view on record")
        selected, _info = self._select(frames, boxes, object_aware=True)
        assert not (hand_picked & {f.frame_index for f in selected}), name


class TestVisibilityVeto:
    """The two vetoes against the real frame sets (decision 0234).

    Only the parts that need no rasters are pinned here — the fixture holds
    poses, intrinsics and the CapturedRoom, not depth or RGB. What that
    still covers is the property that matters most: with the flag off the
    shipped selection comes back unchanged, and with it on but no accessors
    supplied the answer is IDENTICAL, so the flag alone is inert and only
    real evidence can move a frame.

    The measured four-capture answers with rasters — 3 unusable frames in
    the shipped selections, none in the veto ones, and 3 band-vetoed
    (frame, box) pairs — are recorded in 0234, reproduced by
    `outputs/room-quality/s_item7.py` over the preserved captures.
    """

    @staticmethod
    def _select(frames, boxes, *, veto: bool, **kw):
        import census_sampling as cs

        before = cs.VISIBILITY_VETO
        cs.VISIBILITY_VETO = veto
        try:
            return cs.select_frames_census(frames, boxes, 12, **kw)
        finally:
            cs.VISIBILITY_VETO = before

    def test_it_is_off_by_default(self):
        assert census_sampling.VISIBILITY_VETO is False

    def test_off_reproduces_the_shipped_selection(self, capture):
        name, payload, frames, boxes = capture
        selected, info = self._select(frames, boxes, veto=False)
        assert [f.frame_index for f in selected] == payload[
            "shipped_sampling"
        ]["selected_frame_indices"], name
        assert "veto" not in info, name

    def test_on_without_evidence_changes_nothing(self, capture):
        """The flag is not the behaviour change; the evidence is. A run with
        the vetoes armed and no way to fetch pixels or depth must return the
        shipped answer, because both vetoes refuse to reject what they
        cannot assess."""
        name, payload, frames, boxes = capture
        selected, info = self._select(frames, boxes, veto=True)
        assert [f.frame_index for f in selected] == payload[
            "shipped_sampling"
        ]["selected_frame_indices"], name
        assert info["veto"]["unusable_frames"] == [], name
        assert info["veto"]["band_vetoed_pairs"] == [], name
        assert info["veto"]["relaxed_boxes"] == {}, name

    def test_a_blanket_rejection_cannot_empty_the_selection(self, capture):
        """The pathological input: every frame unusable. The pass must
        terminate and return something rather than looping or returning an
        empty set — a room with no usable frames is a capture problem, not a
        reason to ship no frames."""
        name, _payload, frames, boxes = capture
        selected, _info = self._select(
            frames, boxes, veto=True,
            get_rgb=lambda _fi: __import__("numpy").zeros((16, 16)),
        )
        assert len(selected) >= 1, name

    def test_the_overrule_is_recorded(self, capture):
        name, payload, frames, boxes = capture
        selected, info = self._select(
            frames, boxes, veto=True,
            get_rgb=lambda _fi: __import__("numpy").zeros((16, 16)),
        )
        assert info["veto"]["overruled"] is True, name
        assert [f.frame_index for f in selected] == payload[
            "shipped_sampling"
        ]["selected_frame_indices"], name
