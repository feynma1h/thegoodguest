"""The facing correction: turning a piece the scan could not read.

Decisions 0157 (a correction departs from a default, not a measurement), 0158
(the turn is a selection between two enumerated mappings) and 0159 (what the
guest may say about a facing it cannot see).

These run against the four preserved walk rooms, because every claim the
feature rests on is a claim about real shipped manifests: that the 180° sign
is unresolved on every box-placed piece, that a half turn moves nothing that
was measured, and that the pieces placed some other way have no second way
round to offer. Synthetic boxes could be built to satisfy all three.

Run from repo root:
  pytest services/api-public/tests/test_facing_correction.py -v
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pytest
from roomstudio_schemas.pose_math import quat_mul, quat_to_rotmat

from design_spec import (
    DEPARTS_FROM_MEASUREMENT,
    DEPARTS_FROM_UNRESOLVED,
    DesignSpec,
    SpecEntry,
    Transform,
    apply_to_manifest,
    client_dict,
    departs_from,
)
from guest_tools import TOOLS, run_propose, run_revert
from room_geometry import derive_room_geometry, spec_key
from scene_facts import derive_scene_facts, render_facts_block
from spec_solver import _ROT_Y_PI, Refusal, Turn, turn_around

_FIXTURES = Path(__file__).resolve().parents[3] / "web/public/dev-fixtures"

WALK_ROOMS = (
    "scene-spike-a7e073ae",
    "scene-rp7-a71d125f",
    "scene-rp6g1-09684dde",
    "scene-rp6g2-b667f891",
)


def _room(name: str):
    path = _FIXTURES / name / "assets.json"
    if not path.exists():
        pytest.skip(f"{name} fixture not present")
    doc = json.loads(path.read_text())
    manifest = doc["manifest"]
    facts = derive_scene_facts(manifest)
    geometry = derive_room_geometry(
        manifest, doc.get("shell"),
        names={i.object_id: i.name for i in facts.inventory},
    )
    measured = {
        spec_key(o): t
        for o in manifest["objects"]
        if (t := Transform.from_doc(o.get("world_transform") or {})) is not None
    }
    return manifest, geometry, measured


def _all_rooms():
    return [(name, *_room(name)) for name in WALK_ROOMS]


def _box_objects(geometry):
    return [o for o in geometry.objects if o.placed and o.box is not None]


def _empty() -> DesignSpec:
    return DesignSpec(scene_id="s", user_id="u")


def _propose(spec, geometry, measured, changes):
    return run_propose(
        spec=spec, geometry=geometry, manifest_transforms=measured,
        changes=changes, turn_index=0, client_msg_id="c1",
    )


# ---------------------------------------------------------------------------
# The flip itself
# ---------------------------------------------------------------------------

class TestTheFlipIsTheEnumeratedPartner:
    """`turn_around` selects perception's OTHER candidate, not an angle.

    Perception's `box_placement._partner_index` defines the partner as the
    same assignment and the same s_up with the opposite s_h1, which is a half
    turn about the box's vertical axis; RoomPlan boxes are pure-yaw (0076), so
    that axis is world up and the partner is a left-multiplication by
    rotY(pi). perception-obj cannot be imported here — it pins numpy<2 and CI
    runs it in its own environment — so the identity is pinned against the
    real shipped rotations of the four walk rooms instead.
    """

    def test_rot_y_pi_is_a_half_turn_about_world_up(self):
        R = quat_to_rotmat(_ROT_Y_PI)
        assert np.allclose(R, np.diag([-1.0, 1.0, -1.0]), atol=1e-12)

    def test_flip_is_a_pure_component_permutation(self):
        """rotY(pi) (x) (x,y,z,w) == (z, w, -x, -y). Exact, no arithmetic —
        which is why a flipped rotation is never a rounded one."""
        q = (0.2, -0.4, 0.1, math.sqrt(1 - 0.04 - 0.16 - 0.01))
        x, y, z, w = q
        assert quat_mul(_ROT_Y_PI, q) == pytest.approx((z, w, -x, -y), abs=1e-15)

    def test_flip_is_its_own_inverse(self):
        """Two half turns are the identity ROTATION, though the quaternion
        comes back negated — q and -q are the same rotation. Production never
        computes the double flip (a second turn drops the entry instead), and
        this is why that is a cleaner answer than flipping twice: a stored
        rotation that is componentwise unequal to the measured one while
        meaning the same thing would be an entry claiming a change it did not
        make."""
        q = (0.2, -0.4, 0.1, math.sqrt(1 - 0.04 - 0.16 - 0.01))
        twice = quat_mul(_ROT_Y_PI, quat_mul(_ROT_Y_PI, q))
        assert np.allclose(quat_to_rotmat(twice), quat_to_rotmat(q), atol=1e-15)
        assert max(abs(a + b) for a, b in zip(twice, q, strict=True)) < 1e-15

    @pytest.mark.parametrize("name", WALK_ROOMS)
    def test_real_rotations_flip_by_negating_two_world_axes(self, name):
        _m, geometry, _t = _room(name)
        for obj in _box_objects(geometry):
            turned = turn_around(geometry, key=obj.key)
            assert isinstance(turned, Turn), obj.name
            R = quat_to_rotmat(obj.rotation_xyzw)
            R_flipped = quat_to_rotmat(turned.rotation_xyzw)
            assert np.allclose(R_flipped, np.diag([-1.0, 1.0, -1.0]) @ R, atol=1e-12)

    @pytest.mark.parametrize("name", WALK_ROOMS)
    def test_a_flip_is_not_a_somersault(self, name):
        """Whichever of the piece's own axes points up keeps pointing up. The
        candidate set also contains the s_up-inverted mappings; those are a
        different DOF and this is not a way to reach them."""
        _m, geometry, _t = _room(name)
        for obj in _box_objects(geometry):
            turned = turn_around(geometry, key=obj.key)
            assert isinstance(turned, Turn)
            R = quat_to_rotmat(obj.rotation_xyzw)
            R_flipped = quat_to_rotmat(turned.rotation_xyzw)
            i_up = int(np.argmax(np.abs(R[1, :])))  # local axis that lands on world Y
            assert np.dot(R[:, i_up], R_flipped[:, i_up]) > 0.9999, obj.name


class TestNothingMeasuredCanChange:
    """The half turn is inert on every measurement, which is why it needs no
    geometric refusal and why the browser's clip volume survives it."""

    @pytest.mark.parametrize("name", WALK_ROOMS)
    def test_the_measured_footprint_is_invariant(self, name):
        _m, geometry, _t = _room(name)
        for obj in _box_objects(geometry):
            before = sorted(round(c, 9) for corner in obj.box.footprint_corners()
                            for c in corner)
            flipped = obj.box.__class__(
                center=obj.box.center, dims=obj.box.dims,
                yaw_rad=obj.box.yaw_rad + math.pi,
            )
            after = sorted(round(c, 9) for corner in flipped.footprint_corners()
                           for c in corner)
            assert before == after, obj.name

    @pytest.mark.parametrize("name", WALK_ROOMS)
    def test_the_clip_volume_is_centred_on_the_piece_it_cuts(self, name):
        """The browser parents the clip SDF to the mesh, so a turn rotates the
        volume with the splat. That still cuts the measured box only because
        the volume's centre sits on the rotation pivot — the object's own
        position — and a box is symmetric about its centre under a half turn.
        """
        manifest, _g, _t = _room(name)
        seen = 0
        for obj in manifest["objects"]:
            clip = obj.get("splat_clip")
            pos = (obj.get("world_transform") or {}).get("position")
            if not clip or not pos:
                continue
            seen += 1
            for a, b in zip(clip["center_world"], pos, strict=True):
                assert abs(a - b) < 1e-3, obj.get("object_id")
        assert seen, "no clip volumes in this room to check"

    def test_a_turn_changes_no_fact_the_guest_can_speak(self):
        manifest, geometry, measured = _room("scene-spike-a7e073ae")
        obj = _box_objects(geometry)[0]
        out = _propose(_empty(), geometry, measured,
                       [{"object_id": obj.object_id, "action": "turn"}])
        assert out.changed
        before = render_facts_block(derive_scene_facts(manifest))
        after = render_facts_block(
            derive_scene_facts(apply_to_manifest(manifest, out.spec))
        )
        assert before == after

    def test_the_box_keeps_its_measured_yaw(self):
        """The box is the measurement; the correction is about which way round
        the piece sits INSIDE it. A turn that rotated the box would be
        falsifying RoomPlan's own reading."""
        manifest, geometry, measured = _room("scene-spike-a7e073ae")
        obj = _box_objects(geometry)[0]
        out = _propose(_empty(), geometry, measured,
                       [{"object_id": obj.object_id, "action": "turn"}])
        applied = apply_to_manifest(manifest, out.spec)
        for before, after in zip(manifest["objects"], applied["objects"], strict=True):
            if before.get("roomplan_box"):
                assert (after["roomplan_box"]["yaw_rad"]
                        == before["roomplan_box"]["yaw_rad"])
                assert after["roomplan_box"]["dims"] == before["roomplan_box"]["dims"]


# ---------------------------------------------------------------------------
# Eligibility
# ---------------------------------------------------------------------------

class TestOnlyAnUnresolvedFacingIsOursToOverrule:
    def test_every_box_placed_piece_in_every_walk_room_can_be_turned(self):
        total = 0
        for _name, _m, geometry, _t in _all_rooms():
            for obj in _box_objects(geometry):
                assert isinstance(turn_around(geometry, key=obj.key), Turn), obj.name
                total += 1
        assert total == 21, f"the walk rooms ship 21 box placements, saw {total}"

    def test_a_box_and_a_roomplan_rotation_are_the_same_population(self):
        """The eligibility gate reads `rotation_source`, and on real data that
        coincides exactly with having a measured box — so the gate admits the
        pieces whose 180° sign perception left unresolved, and nothing else."""
        for name, _m, geometry, _t in _all_rooms():
            for obj in geometry.objects:
                if not obj.placed:
                    continue
                assert (obj.rotation_source == "roomplan_box") == (
                    obj.box is not None
                ), f"{name} {obj.object_id}"

    def test_pieces_placed_another_way_have_no_second_way_round(self):
        """`sam3d_layout` rotations carry a sign that IS pinned by regression
        (0065), and a piece with no rotation claim has nothing to invert."""
        refused = 0
        for _name, _m, geometry, _t in _all_rooms():
            for obj in geometry.objects:
                if not obj.placed or obj.box is not None:
                    continue
                outcome = turn_around(geometry, key=obj.key)
                assert isinstance(outcome, Refusal), obj.name
                assert outcome.reason in ("piece_not_measured", "facing_not_from_box")
                refused += 1
        assert refused == 26, f"the walk rooms ship 26 such pieces, saw {refused}"

    def test_an_unplaced_piece_refuses_before_geometry(self):
        _m, geometry, _t = _room("scene-spike-a7e073ae")
        unplaced = next(o for o in geometry.objects if not o.placed)
        outcome = turn_around(geometry, key=unplaced.key)
        assert isinstance(outcome, Refusal)
        assert outcome.reason == "piece_not_placed"

    def test_an_unknown_key_refuses(self):
        _m, geometry, _t = _room("scene-spike-a7e073ae")
        outcome = turn_around(geometry, key="box:nothing")
        assert isinstance(outcome, Refusal)
        assert outcome.reason == "unknown_object"


# ---------------------------------------------------------------------------
# What the entry records
# ---------------------------------------------------------------------------

class TestTheEntryCarriesWhatItDepartedFrom:
    def _turn_one(self):
        manifest, geometry, measured = _room("scene-spike-a7e073ae")
        obj = _box_objects(geometry)[0]
        out = _propose(_empty(), geometry, measured,
                       [{"object_id": obj.object_id, "action": "turn"}])
        return manifest, geometry, measured, obj, out

    def test_a_turn_departs_from_an_unresolved_default(self):
        *_rest, out = self._turn_one()
        entry = out.spec.entries[0]
        assert entry.action == "turn"
        assert entry.facing_flipped is True
        assert departs_from(entry) == DEPARTS_FROM_UNRESOLVED

    def test_a_move_departs_from_a_measurement(self):
        _m, geometry, measured = _room("scene-spike-a7e073ae")
        obj = _box_objects(geometry)[0]
        out = _propose(_empty(), geometry, measured, [
            {"object_id": obj.object_id, "action": "move", "relation": "against_wall"},
        ])
        assert out.changed
        assert departs_from(out.spec.entries[0]) == DEPARTS_FROM_MEASUREMENT

    def test_the_measured_transform_is_the_manifest_verbatim(self):
        """0131's invariant does not bend for a correction: the entry still
        carries exactly what perception shipped, including the rotation the
        person overruled."""
        _m, _g, measured, obj, out = self._turn_one()
        entry = out.spec.entries[0]
        assert entry.measured_transform == measured[obj.key]
        assert entry.proposed_transform.rotation_xyzw == pytest.approx(
            quat_mul(_ROT_Y_PI, measured[obj.key].rotation_xyzw), abs=1e-15
        )

    def test_position_and_scale_are_untouched(self):
        _m, _g, measured, obj, out = self._turn_one()
        entry = out.spec.entries[0]
        assert entry.proposed_transform.position == measured[obj.key].position
        assert entry.proposed_transform.scale == measured[obj.key].scale

    def test_departs_from_is_computed_on_the_wire_and_never_stored(self):
        """A second copy in Firestore could disagree with `action`. It is
        derived on the way out, the way `orphaned` is."""
        *_rest, out = self._turn_one()
        entry = out.spec.entries[0]
        assert "departs_from" not in entry.to_doc()
        doc = client_dict(out.spec, {entry.key})
        assert doc["entries"][0]["departs_from"] == DEPARTS_FROM_UNRESOLVED

    def test_an_entry_round_trips_through_the_document(self):
        *_rest, out = self._turn_one()
        entry = out.spec.entries[0]
        assert SpecEntry.from_doc(entry.to_doc()) == entry

    def test_a_turn_with_no_proposed_transform_never_loads(self):
        *_rest, out = self._turn_one()
        doc = out.spec.entries[0].to_doc()
        doc["proposed_transform"] = None
        assert SpecEntry.from_doc(doc) is None

    def test_a_document_written_before_corrections_reads_as_unflipped(self):
        _m, _g, measured, obj, _out = self._turn_one()
        doc = SpecEntry(
            key=obj.key, action="move", label=obj.name,
            measured_transform=measured[obj.key],
            proposed_transform=measured[obj.key],
            measured_footprint=None, solver=None, description="d",
            turn_index=0, client_msg_id="c",
        ).to_doc()
        del doc["facing_flipped"]
        assert SpecEntry.from_doc(doc).facing_flipped is False


# ---------------------------------------------------------------------------
# Turning twice, and turning something already moved
# ---------------------------------------------------------------------------

class TestTurningComposes:
    def _two_pieces(self):
        _m, geometry, measured = _room("scene-spike-a7e073ae")
        boxes = _box_objects(geometry)
        return geometry, measured, boxes[0]

    def test_turning_twice_puts_the_piece_back_the_way_the_scan_drew_it(self):
        geometry, measured, obj = self._two_pieces()
        change = [{"object_id": obj.object_id, "action": "turn"}]
        once = _propose(_empty(), geometry, measured, change)
        twice = _propose(once.spec, geometry, measured, change)
        assert twice.changed
        assert twice.spec.entries == ()
        assert "back the way the scan drew it" in twice.descriptions[0]

    def test_a_move_onto_a_turned_piece_keeps_the_turn(self):
        geometry, measured, obj = self._two_pieces()
        turned = _propose(_empty(), geometry, measured,
                          [{"object_id": obj.object_id, "action": "turn"}])
        moved = _propose(turned.spec, geometry, measured, [
            {"object_id": obj.object_id, "action": "move", "relation": "against_wall"},
        ])
        entry = moved.spec.entries[0]
        assert entry.action == "move"
        assert entry.facing_flipped is True
        assert entry.proposed_transform.rotation_xyzw == pytest.approx(
            quat_mul(_ROT_Y_PI, measured[obj.key].rotation_xyzw), abs=1e-15
        )
        assert entry.proposed_transform.position != measured[obj.key].position
        assert "still turned around" in entry.description

    def test_a_turn_onto_a_moved_piece_keeps_the_move(self):
        geometry, measured, obj = self._two_pieces()
        moved = _propose(_empty(), geometry, measured, [
            {"object_id": obj.object_id, "action": "move", "relation": "against_wall"},
        ])
        proposed_position = moved.spec.entries[0].proposed_transform.position
        turned = _propose(moved.spec, geometry, measured,
                          [{"object_id": obj.object_id, "action": "turn"}])
        entry = turned.spec.entries[0]
        assert entry.action == "move"
        assert entry.facing_flipped is True
        assert entry.proposed_transform.position == proposed_position

    def test_removing_a_turned_piece_remembers_the_correction(self):
        geometry, measured, obj = self._two_pieces()
        turned = _propose(_empty(), geometry, measured,
                          [{"object_id": obj.object_id, "action": "turn"}])
        removed = _propose(turned.spec, geometry, measured,
                           [{"object_id": obj.object_id, "action": "remove"}])
        entry = removed.spec.entries[0]
        assert entry.action == "remove"
        assert entry.facing_flipped is True


# ---------------------------------------------------------------------------
# Revert
# ---------------------------------------------------------------------------

class TestRevertRestoresMeasurementsAndKeepsCorrections:
    def _moved_and_turned(self):
        _m, geometry, measured = _room("scene-spike-a7e073ae")
        boxes = _box_objects(geometry)
        mover, corrected = boxes[0], boxes[1]
        spec = _propose(_empty(), geometry, measured, [
            {"object_id": mover.object_id, "action": "move",
             "relation": "against_wall"},
            {"object_id": corrected.object_id, "action": "turn"},
        ]).spec
        return geometry, measured, mover, corrected, spec

    def test_revert_all_drops_the_move_and_keeps_the_turn(self):
        geometry, _measured, mover, corrected, spec = self._moved_and_turned()
        out = run_revert(spec=spec, geometry=geometry, keys=["all"])
        assert out.changed
        keys = {e.key for e in out.spec.entries}
        assert mover.key not in keys
        assert corrected.key in keys
        kept = out.spec.by_key(corrected.key)
        assert kept.action == "turn"
        assert kept.facing_flipped is True

    def test_revert_all_says_what_it_left_standing(self):
        geometry, _measured, _mover, _corrected, spec = self._moved_and_turned()
        out = run_revert(spec=spec, geometry=geometry, keys=["all"])
        assert out.result["description"] == (
            "the room is back as measured, with the 1 piece you turned still turned"
        )

    def test_revert_says_as_measured_when_nothing_was_turned(self):
        _m, geometry, measured = _room("scene-spike-a7e073ae")
        obj = _box_objects(geometry)[0]
        spec = _propose(_empty(), geometry, measured, [
            {"object_id": obj.object_id, "action": "move", "relation": "against_wall"},
        ]).spec
        out = run_revert(spec=spec, geometry=geometry, keys=["all"])
        assert out.result["description"] == "the room is back as measured"

    def test_reverting_a_moved_and_turned_piece_leaves_it_where_measured(self):
        _m, geometry, measured = _room("scene-spike-a7e073ae")
        obj = _box_objects(geometry)[0]
        spec = _propose(_empty(), geometry, measured,
                        [{"object_id": obj.object_id, "action": "turn"}]).spec
        spec = _propose(spec, geometry, measured, [
            {"object_id": obj.object_id, "action": "move", "relation": "against_wall"},
        ]).spec
        out = run_revert(spec=spec, geometry=geometry, keys=[obj.object_id])
        kept = out.spec.by_key(obj.key)
        assert kept.action == "turn"
        assert kept.proposed_transform.position == measured[obj.key].position
        assert kept.proposed_transform.rotation_xyzw == pytest.approx(
            quat_mul(_ROT_Y_PI, measured[obj.key].rotation_xyzw), abs=1e-15
        )

    def test_the_reduced_entry_carries_its_own_reasoning_not_the_moves(self):
        _m, geometry, measured = _room("scene-spike-a7e073ae")
        obj = _box_objects(geometry)[0]
        spec = _propose(_empty(), geometry, measured,
                        [{"object_id": obj.object_id, "action": "turn"}]).spec
        spec = _propose(spec, geometry, measured, [
            {"object_id": obj.object_id, "action": "move", "relation": "against_wall"},
        ]).spec
        out = run_revert(spec=spec, geometry=geometry, keys=["all"])
        kept = out.spec.by_key(obj.key)
        assert kept.solver.relation == "turn_around"
        assert "other way round" in kept.solver.reasoning
        assert kept.description == f"the {obj.name} is turned around"

    def test_reverting_reports_every_piece_it_touched(self):
        geometry, _measured, _mover, _corrected, spec = self._moved_and_turned()
        out = run_revert(spec=spec, geometry=geometry, keys=["all"])
        assert out.result["reverted"] == 2

    def test_nothing_to_put_back_is_still_honest(self):
        _m, geometry, _measured = _room("scene-spike-a7e073ae")
        out = run_revert(spec=DesignSpec("s", "u"), geometry=geometry, keys=["all"])
        assert out.changed is False
        assert out.result["description"] == "nothing to put back"


# ---------------------------------------------------------------------------
# The tool surface
# ---------------------------------------------------------------------------

class TestTheToolTakesNoDirection:
    def _propose_schema(self):
        tool = next(t for t in TOOLS if t["name"] == "propose")
        return tool["input_schema"]["properties"]["changes"]["items"]["properties"]

    def test_turn_is_an_action(self):
        assert set(self._propose_schema()["action"]["enum"]) == {
            "move", "remove", "turn"
        }

    def test_no_tool_field_is_shaped_like_a_direction(self):
        """A `degrees` field would be a coordinate in the same way `move(x,y,z)`
        would be, and test_design_spec's numeric-field pin already forbids that
        shape. This forbids the string-shaped version — a `direction:
        "clockwise"` would be typed as text and still be a facing the guest
        cannot source. The turn's whole safety is that there is exactly one of
        it and it takes no argument."""
        names: list[str] = []

        def walk(node):
            if isinstance(node, dict):
                names.extend(str(k).lower() for k in (node.get("properties") or {}))
                for value in node.values():
                    walk(value)
            elif isinstance(node, list):
                for value in node:
                    walk(value)

        walk(TOOLS)
        assert names, "no tool properties found to check"
        for name in names:
            for forbidden in ("degree", "angle", "yaw", "radian", "direction",
                              "clockwise", "facing", "rotation"):
                assert forbidden not in name, name

    def test_the_turn_description_names_the_person_as_the_authority(self):
        text = self._propose_schema()["action"]["description"].lower()
        assert "the only one who can see" in text
        assert "no angle" in text

    def test_revert_tells_the_model_a_correction_survives_it(self):
        tool = next(t for t in TOOLS if t["name"] == "revert")
        assert "stays turned" in tool["description"].lower()

    def test_an_unknown_action_is_refused_rather_than_guessed(self):
        _m, geometry, measured = _room("scene-spike-a7e073ae")
        obj = _box_objects(geometry)[0]
        out = _propose(_empty(), geometry, measured,
                       [{"object_id": obj.object_id, "action": "rotate"}])
        assert out.changed is False
        assert out.result["changes"][0]["reason"] == "unknown_action"

    def test_a_refused_turn_leaves_the_arrangement_alone(self):
        _m, geometry, measured = _room("scene-spike-a7e073ae")
        free = next(o for o in geometry.objects if o.placed and o.box is None)
        out = _propose(_empty(), geometry, measured,
                       [{"object_id": free.object_id, "action": "turn"}])
        assert out.changed is False
        assert out.spec.entries == ()
        assert out.result["changes"][0]["applied"] is False

    def test_the_description_is_the_servers_and_says_only_what_happened(self):
        """Rule 2a: the guest quotes this. It must not name a direction, since
        nothing here knows one."""
        _m, geometry, measured = _room("scene-spike-a7e073ae")
        obj = _box_objects(geometry)[0]
        out = _propose(_empty(), geometry, measured,
                       [{"object_id": obj.object_id, "action": "turn"}])
        description = out.result["changes"][0]["description"]
        assert description == f"the {obj.name} is turned around"
        for forbidden in ("faces", "facing", "toward", "towards"):
            assert forbidden not in description
