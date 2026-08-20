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
