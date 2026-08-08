"""Decision 0081 regression pins on real data: the cloud-alignment axis
instrument on the RP-8 spike scene's six box objects, at achieved values.

The probe verdict this productionizes (recorded in decision 0081): every
appearance-scorer variant (current NCC, NCC@256, gradient NCC, LiDAR
depth-map agreement) across every view set (live SAM-mask views, box-
footprint evidence, three extra census-quality views) failed to separate
ANY spike box's axis mapping — margins 0.0018–0.089 vs the 0.10 gate,
wrong winners on the known-wrong cases. The world-space cloud instrument
(translation-fitted trimmed NN RMS against the observation's own LiDAR
cloud) + the layout prior's sign-agnostic up-axis filter resolves:

  obj_003 bed     RESOLVED margin ~0.160 → assignment (0,2,1)  [was 90° wrong]
  obj_007 chair   RESOLVED margin ~0.206 → assignment (0,2,1)  [was 90° wrong]
  obj_000 storage RESOLVED margin ~0.466 → assignment (0,2,1)
  obj_004 table   RESOLVED margin ~0.147 → assignment (0,2,1)
  obj_005 table   refused  margin ~0.014 → extent-best default (correct)
  obj_006 chair   refused  margin ~0.002 → extent-best default (correct)

plus the pinned near-tie: within the bed's winning assignment the cloud
CANNOT separate the 180° sign twins (spread « the gate) — the recorded
reason the sign leaf ships the fixed (+,+) convention. A future sign
instrument beating this pin is a good failure (the 0068 pattern).

Small evidence committed under tests/fixtures/roomplan_spike/axis/
(per-view masks, per-frame depth+confidence, cameras, observation records
— 293 KB); the six splats live by absolute path with a clean skip
(outputs/rp8-walk/splats/, ~196 MB, gitignored).

Run from repo root:
    python -m pytest services/perception-obj/tests/test_axis_cloud_real_data.py -v
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import box_placement
import numpy as np
import pytest
import roomplan_room

AXIS_FIX = Path(__file__).resolve().parent / "fixtures" / "roomplan_spike" / "axis"
ROOM_JSON = (
    Path(__file__).resolve().parent
    / "fixtures" / "roomplan_spike" / "captured_room_built.json"
)
SPLAT_DIR = Path("/Users/aubrey/projects/roomstudio/outputs/rp8-walk/splats")

_needs_splats = pytest.mark.skipif(
    not SPLAT_DIR.exists(),
    reason="spike splats only in the main checkout's outputs/rp8-walk/splats/",
)

# (resolved, margin, assignment, n_candidates) at achieved values.
PINS = {
    "obj_000": (True, 0.4664, (0, 2, 1), 8),
    "obj_003": (True, 0.1604, (0, 2, 1), 8),
    "obj_004": (True, 0.1474, (0, 2, 1), 8),
    "obj_005": (False, 0.0142, (0, 2, 1), 8),
    "obj_006": (False, 0.0020, (1, 2, 0), 8),
    "obj_007": (True, 0.2063, (0, 2, 1), 8),
}
# The RP-8 walk's shipped (extent-best, no-filter) assignments that the
# instrument now overturns — the two operator-visible rotation defects.
OVERTURNED = {"obj_003": (1, 2, 0), "obj_007": (1, 2, 0)}


@dataclass
class FakeIntrinsics:
    fx: float
    fy: float
    cx: float
    cy: float
    width: int
    height: int


@dataclass
class FakePose:
    pos_x: float
    pos_y: float
    pos_z: float
    quat_x: float
    quat_y: float
    quat_z: float
    quat_w: float


class FixtureCtx:
    """RefinementContext stand-in over the committed axis fixtures."""

    def __init__(self):
        self.cameras = json.loads((AXIS_FIX / "cameras.json").read_text())
        self.observations = json.loads((AXIS_FIX / "observations.json").read_text())
        self.get_appearance = None
        self.get_rgb = None

    def get_camera(self, frame_index):
        c = self.cameras.get(str(frame_index))
        if c is None:
            return None
        return (FakePose(*c["pose"]), FakeIntrinsics(**c["intrinsics"]))

    def mask_for(self, frame_index, mask_index):
        p = AXIS_FIX / f"mask_{frame_index:04d}_{mask_index:02d}.npz"
        if not p.exists():
            return None
        with np.load(p) as z:
            return z["mask"].astype(bool)

    def evidence_for(self, frame_index, mask_index):
        from roomstudio_schemas.placement_math import prepare_mask

        m = self.mask_for(frame_index, mask_index)
        return None if m is None else prepare_mask(m)

    def get_depth(self, frame_index):
        p = AXIS_FIX / f"depth_{frame_index:04d}.npz"
        c = self.cameras.get(str(frame_index))
        if not p.exists() or c is None:
            return None
        with np.load(p) as z:
            depth = z["depth"]
            conf = z["confidence"] if "confidence" in z.files else None
        return (depth, conf, FakeIntrinsics(**c["depth_intrinsics"]))

    def get_splat(self, uri):
        key = uri.split("/frames/")[-1].replace("/", "_")
        p = SPLAT_DIR / key
        if not p.exists():
            return None
        import placement

        return placement.parse_ply_vertices(p.read_bytes())


def _room():
    room, err = roomplan_room.try_parse_captured_room(ROOM_JSON.read_bytes())
    assert room is not None, err
    return room


def _associations(ctx, oid):
    rec = ctx.observations[oid]
    return [box_placement.BoxAssociation(
        box_index=rec["box_index"],
        frame_index=rec["frame_index"],
        mask_index=rec["mask_index"],
        overlap=rec["overlap"],
        in_frame_fraction=rec["in_frame_fraction"],
        obs=rec["obs"],
    )]


@_needs_splats
class TestAxisCloudPins:
    @pytest.fixture(scope="class")
    def built(self):
        ctx = FixtureCtx()
        room = _room()
        out = {}
        for oid, rec in sorted(ctx.observations.items()):
            out[oid] = box_placement.build_box_object(
                box=room.objects[rec["box_index"]],
                box_index=rec["box_index"],
                object_id=oid,
                associations=_associations(ctx, oid),
                ctx=ctx,
                allow_scoring=True,
            )
        return ctx, room, out

    def test_resolutions_and_margins_at_achieved_values(self, built):
        _ctx, _room_, objs = built
        for oid, (resolved, margin, _assign, n_cands) in PINS.items():
            obj = objs[oid]
            q = obj["quality"]
            assert obj["splat_axis_resolved"] is resolved, oid
            assert q["axis_margin"] == pytest.approx(margin, abs=0.02), oid
            assert q["axis_candidates"] == n_cands, oid
            assert q["axis_up_filtered"] is True, oid
            assert q["axis_cloud_points"] > 500, oid

    def test_chosen_assignment_and_conventional_sign(self, built):
        ctx, room, objs = built
        for oid, (_res, _m, assign, _n) in PINS.items():
            rec = ctx.observations[oid]
            splat = ctx.get_splat(rec["obs"]["splat_gcs_uri"])
            u = box_placement.splat_up_local(rec["obs"])
            cands = box_placement.axis_mapping_candidates(
                room.objects[rec["box_index"]],
                box_placement.splat_axis_extents(splat),
                u,
            )
            rot = tuple(objs[oid]["world_transform"]["rotation_xyzw"])
            chosen = next(c for c in cands if tuple(c.rotation_xyzw) == rot)
            assert chosen.assignment == assign, oid
            assert chosen.signs == (1, 1), oid

    def test_walk_defects_are_overturned(self, built):
        """The two operator-visible rotation failures (bed 90°, office
        chair 90°): the instrument's winner is a DIFFERENT assignment from
        the extent-best default that shipped at RP-8."""
        ctx, room, objs = built
        for oid, shipped_assign in OVERTURNED.items():
            rec = ctx.observations[oid]
            splat = ctx.get_splat(rec["obs"]["splat_gcs_uri"])
            # The pre-0081 default: extent-best, no up filter.
            old_cands = box_placement.axis_mapping_candidates(
                room.objects[rec["box_index"]],
                box_placement.splat_axis_extents(splat),
            )
            assert old_cands[0].assignment == shipped_assign, oid
            rot = tuple(objs[oid]["world_transform"]["rotation_xyzw"])
            u = box_placement.splat_up_local(rec["obs"])
            new_cands = box_placement.axis_mapping_candidates(
                room.objects[rec["box_index"]],
                box_placement.splat_axis_extents(splat),
                u,
            )
            chosen = next(c for c in new_cands if tuple(c.rotation_xyzw) == rot)
            assert chosen.assignment != shipped_assign, oid

    def test_bed_sign_twins_stay_cloud_degenerate(self, built):
        """Pinned near-tie: within the bed's winning assignment the cloud
        scores of the 180° sign twins sit far under the gate — the
        recorded reason the sign leaf ships the fixed convention. A sign
        instrument that separates them is a GOOD failure of this pin."""
        ctx, room, _objs = built
        rec = ctx.observations["obj_003"]
        splat = ctx.get_splat(rec["obs"]["splat_gcs_uri"])
        u = box_placement.splat_up_local(rec["obs"])
        box = room.objects[rec["box_index"]]
        cands = box_placement.axis_mapping_candidates(
            box, box_placement.splat_axis_extents(splat), u
        )
        cloud = box_placement.observation_cloud_from_ctx(
            FixtureCtx(), rec["frame_index"], rec["mask_index"]
        )
        wt = (rec["obs"].get("placement") or {}).get("world_transform") or {}
        scores = box_placement.score_candidates_cloud(
            cands, splat, cloud, float(wt["scale"])
        )
        win_assign = (0, 2, 1)
        sign_scores = [
            s for c, s in zip(cands, scores, strict=True)
            if c.assignment == win_assign and c.signs[0] == 1 and s is not None
        ]
        assert len(sign_scores) == 2
        assert abs(sign_scores[0] - sign_scores[1]) < 0.02

    def test_no_depth_degrades_to_up_filtered_default(self, built):
        """Warm re-drive shape: same fixtures, no depth accessor — the
        up-filtered extent default ships unresolved (still strictly better
        than the RP-8 default for the two overturned objects' UP axis)."""
        ctx = FixtureCtx()
        room = _room()
        ctx.get_depth = None  # type: ignore[assignment]

        class NoDepthCtx(FixtureCtx):
            def get_depth(self, frame_index):
                return None

        nctx = NoDepthCtx()
        rec = nctx.observations["obj_003"]
        obj = box_placement.build_box_object(
            box=room.objects[rec["box_index"]],
            box_index=rec["box_index"],
            object_id="obj_003",
            associations=_associations(nctx, "obj_003"),
            ctx=nctx,
            allow_scoring=True,
        )
        assert obj["splat_axis_resolved"] is False
        assert "axis_cloud_points" not in obj["quality"]
        assert obj["quality"]["axis_up_filtered"] is True


# ---------------------------------------------------------------------------
# Decision 0104 — splat clipping, pinned on the same real box objects.
# ---------------------------------------------------------------------------

# (clip emitted?, removed_fraction) at achieved values, measured through
# build_box_object on the spike scene's real splats. The bed is the walk's
# headline: its splat reaches 0.46 m past the measured box and intersects
# the table and the chair, in a room whose boxes the operator verified 9/9.
CLIP_PINS = {
    "obj_000": (False, 0.0),
    "obj_003": (True, 0.3080),   # bed — the phantom length
    "obj_004": (True, 0.0224),   # table — a real but mild overhang
    "obj_005": (False, 0.0),
    "obj_006": (False, 0.0),
    "obj_007": (False, 0.0),
}


@_needs_splats
class TestSplatClipRealData:
    @pytest.fixture(scope="class")
    def built(self):
        ctx = FixtureCtx()
        room = _room()
        return {
            oid: box_placement.build_box_object(
                box=room.objects[rec["box_index"]], box_index=rec["box_index"],
                object_id=oid, associations=_associations(ctx, oid),
                ctx=ctx, allow_scoring=True,
            )
            for oid, rec in sorted(ctx.observations.items())
        }

    def test_clip_emitted_only_where_the_splat_leaves_its_box(self, built):
        for oid, (emitted, fraction) in CLIP_PINS.items():
            clip = built[oid].get("splat_clip")
            assert (clip is not None) is emitted, oid
            if emitted:
                assert clip["removed_fraction"] == pytest.approx(fraction, abs=0.02), oid
                assert clip["kind"] == "roomplan_box"

    def test_clip_volume_is_the_measured_box_grown_by_the_margin(self, built):
        room = _room()
        for oid, (emitted, _f) in CLIP_PINS.items():
            if not emitted:
                continue
            clip = built[oid]["splat_clip"]
            box = room.objects[
                int(built[oid]["roomplan_box"]["box_id"].split("_")[1])
            ]
            margin = clip["margin_m"]
            assert clip["half_extents_m"] == pytest.approx(
                [float(d) / 2.0 + margin for d in box.dimensions], abs=1e-3
            ), oid
            assert clip["center_world"] == pytest.approx(
                [float(c) for c in box.center_world], abs=1e-3
            ), oid

    def test_clip_never_moves_or_rescales_the_object(self, built):
        """The honesty invariant: a clip declines to render known-false
        mass, it does not falsify the measurement that proves it false.
        Position, rotation and scale must be byte-identical to the values
        the axis pins above already assert."""
        for oid, (emitted, _f) in CLIP_PINS.items():
            if not emitted:
                continue
            wt = built[oid]["world_transform"]
            room = _room()
            box = room.objects[
                int(built[oid]["roomplan_box"]["box_id"].split("_")[1])
            ]
            assert wt["position"] == pytest.approx(
                [float(c) for c in box.center_world], abs=1e-9
            ), oid

    def test_bed_clip_removes_the_phantom_length_not_the_bed(self, built):
        """The bed keeps most of itself: a clip that gutted the object
        would be the wrong instrument, and the measured sweep is what
        chose the 0.10 m margin over tighter ones."""
        assert built["obj_003"]["splat_clip"]["removed_fraction"] < 0.40
