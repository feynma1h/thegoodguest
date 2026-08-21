"""Tests for design_spec.py and guest_tools.py — the proposal and the hands.

The invariant every test here is ultimately about (decision 0131): **an entry
that cannot carry the measurement it departs from does not exist.** That is
what makes the product's central lie structurally unavailable rather than
prohibited by discipline, so it is pinned from both directions — a document
missing `measured_transform` never loads, and no code path writes one.

Run from repo root:
  pytest services/api-public/tests/test_design_spec.py -v
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from design_spec import (
    MAX_ENTRIES,
    DesignSpec,
    Footprint,
    InMemoryDesignSpecRepository,
    SolverTrace,
    SpecEntry,
    Transform,
    apply_to_manifest,
    client_dict,
    moved_object_ids,
)
from guest_tools import (
    TOOLS,
    _find,
    run_propose,
    run_revert,
    run_tool,
    tool_result_texts,
    unprompted_proposal,
)
from room_geometry import derive_room_geometry, spec_key
from scene_facts import derive_scene_facts
from spec_solver import Refusal

_FIXTURES = Path(__file__).resolve().parents[3] / "web/public/dev-fixtures"
NOW = datetime(2026, 8, 9, tzinfo=timezone.utc)


def _spike():
    path = _FIXTURES / "scene-spike-a7e073ae/assets.json"
    if not path.exists():
        pytest.skip("spike fixture not present")
    doc = json.loads(path.read_text())
    facts = derive_scene_facts(doc["manifest"])
    geometry = derive_room_geometry(
        doc["manifest"], doc.get("shell"),
        names={i.object_id: i.name for i in facts.inventory},
    )
    measured = {
        spec_key(o): t
        for o in doc["manifest"]["objects"]
        if (t := Transform.from_doc(o.get("world_transform") or {})) is not None
    }
    return doc["manifest"], geometry, measured


def _entry(key="box:X", action="move", **over):
    measured = Transform((1.0, 0.5, 2.0), (0, 0, 0, 1), 1.0)
    base = dict(
        key=key, action=action, label="bed",
        measured_transform=measured,
        proposed_transform=Transform((3.0, 0.5, 1.0), (0, 0, 0, 1), 1.0)
        if action == "move" else None,
        measured_footprint=Footprint((1.0, 0.5, 2.0), (0.9, 0.3, 1.1), 0.4),
        solver=SolverTrace("against_wall", "wall_02", ("keeps_height",), "because"),
        description="the bed is against the wall",
        turn_index=0, client_msg_id="c1",
    )
    base.update(over)
    return SpecEntry(**base)


# ---------------------------------------------------------------------------
# The invariant
# ---------------------------------------------------------------------------

class TestMeasurementAlwaysTravels:
    def test_round_trip_keeps_both_transforms(self):
        e = _entry()
        back = SpecEntry.from_doc(e.to_doc())
        assert back == e
        assert back.measured_transform.position == (1.0, 0.5, 2.0)
        assert back.proposed_transform.position == (3.0, 0.5, 1.0)

    def test_an_entry_without_its_measurement_never_loads(self):
        doc = _entry().to_doc()
        doc.pop("measured_transform")
        assert SpecEntry.from_doc(doc) is None
        doc = _entry().to_doc()
        doc["measured_transform"] = {"position": [1, 2]}  # malformed
        assert SpecEntry.from_doc(doc) is None

    def test_a_move_without_a_proposal_never_loads(self):
        doc = _entry().to_doc()
        doc["proposed_transform"] = None
        assert SpecEntry.from_doc(doc) is None

    def test_a_remove_needs_no_proposal_but_still_needs_the_measurement(self):
        e = _entry(action="remove", proposed_transform=None, solver=None,
                   description="the bed is out of the room")
        assert SpecEntry.from_doc(e.to_doc()) == e
        doc = e.to_doc()
        doc.pop("measured_transform")
        assert SpecEntry.from_doc(doc) is None

    def test_junk_entries_are_dropped_not_half_read(self):
        for doc in ({}, {"key": ""}, {"key": "k", "action": "explode"}, "nope"):
            assert SpecEntry.from_doc(doc) is None


# ---------------------------------------------------------------------------
# The document
# ---------------------------------------------------------------------------

class TestDesignSpec:
    def test_a_second_proposal_for_a_piece_replaces_the_first(self):
        spec = DesignSpec("s", "u").with_entry(_entry(key="a"))
        spec = spec.with_entry(_entry(key="b"))
        spec = spec.with_entry(_entry(key="a", description="moved again"))
        assert [e.key for e in spec.entries] == ["b", "a"]
        assert spec.by_key("a").description == "moved again"

    def test_orphaned_is_reported_never_dropped(self):
        """A spec keyed on a piece a re-drive removed must SAY so. Silently
        dropping it hides a change the person made; silently re-pointing it
        moves the wrong furniture and nothing notices."""
        spec = DesignSpec("s", "u").with_entry(_entry(key="box:GONE"))
        out = client_dict(spec, live_keys={"box:HERE"})
        assert len(out["entries"]) == 1
        assert out["entries"][0]["orphaned"] is True
        assert client_dict(spec, {"box:GONE"})["entries"][0]["orphaned"] is False

    def test_repository_round_trip_and_cap(self):
        repo = InMemoryDesignSpecRepository()
        assert repo.get("s", "u").entries == ()
        spec = DesignSpec("s", "u")
        for i in range(MAX_ENTRIES + 5):
            spec = spec.with_entry(_entry(key=f"k{i}"))
        stored = repo.put(spec, now=NOW)
        assert len(stored.entries) == MAX_ENTRIES
        assert stored.entries[-1].key == f"k{MAX_ENTRIES + 4}"
        assert repo.get("s", "u").updated_at == NOW
        repo.clear("s", "u")
        assert repo.get("s", "u").entries == ()

    def test_specs_are_isolated_per_scene_and_user(self):
        repo = InMemoryDesignSpecRepository()
        repo.put(DesignSpec("s", "u1").with_entry(_entry()), now=NOW)
        assert repo.get("s", "u2").entries == ()
        assert repo.get("s2", "u1").entries == ()


class TestApplyToManifest:
    def test_no_entries_returns_the_manifest_itself(self):
        manifest, _g, _m = _spike()
        assert apply_to_manifest(manifest, DesignSpec("s", "u")) is manifest

    def test_a_move_updates_the_transform_and_the_box_together(self):
        manifest, _g, _m = _spike()
        target = next(
            o for o in manifest["objects"]
            if o.get("placed") and o.get("roomplan_box", {}).get("identifier")
        )
        key = spec_key(target)
        spec = DesignSpec("s", "u").with_entry(_entry(
            key=key,
            proposed_transform=Transform((9.0, 1.0, 9.0), (0, 0, 0, 1), 1.0),
        ))
        out = apply_to_manifest(manifest, spec)
        moved = next(o for o in out["objects"] if spec_key(o) == key)
        assert moved["world_transform"]["position"] == [9.0, 1.0, 9.0]
        # The box travels: a box left behind would make every derived
        # distance describe a room nobody is looking at.
        assert moved["roomplan_box"]["center_world"] == [9.0, 1.0, 9.0]
        assert moved["roomplan_box"]["dims"] == target["roomplan_box"]["dims"]
        # ...and the ORIGINAL manifest is untouched.
        assert manifest["objects"] is not out["objects"]
        assert next(o for o in manifest["objects"] if spec_key(o) == key)[
            "world_transform"]["position"] != [9.0, 1.0, 9.0]

    def test_a_removed_piece_leaves_the_derived_room_entirely(self):
        manifest, _g, _m = _spike()
        target = next(o for o in manifest["objects"] if o.get("placed"))
        spec = DesignSpec("s", "u").with_entry(
            _entry(key=spec_key(target), action="remove", proposed_transform=None)
        )
        out = apply_to_manifest(manifest, spec)
        assert len(out["objects"]) == len(manifest["objects"]) - 1
        facts = derive_scene_facts(out)
        assert all(spec_key(target).split(":")[-1] not in i.object_id
                   for i in facts.inventory)

    def test_derived_facts_describe_the_proposed_room(self):
        manifest, _g, _m = _spike()
        target = next(
            o for o in manifest["objects"]
            if o.get("placed") and o.get("roomplan_box", {}).get("identifier")
        )
        before = derive_scene_facts(manifest)
        spec = DesignSpec("s", "u").with_entry(_entry(
            key=spec_key(target),
            proposed_transform=Transform((40.0, 1.0, 40.0), (0, 0, 0, 1), 1.0),
        ))
        after = derive_scene_facts(apply_to_manifest(manifest, spec))
        assert before.distances != after.distances, (
            "moving a piece must change the distances the guest reads"
        )


class TestMovedObjectIds:
    """Which pieces the scan never saw where they now stand (decision 0214).

    Fixture-free, like `TestFindingThePiece`: this decides what the guest is
    told about the provenance of every number in a rearranged room, and it
    should not skip when dev-fixtures are absent.
    """

    _MANIFEST = {
        "scene_id": "s", "manifest_version": 2, "frame_count": 9,
        "objects": [
            {"object_id": "obj_000", "label": "sofa", "placed": True,
             "world_transform": {"position": [0, 0.3, 0],
                                 "rotation_xyzw": [0, 0, 0, 1], "scale": 1.0}},
            {"object_id": "obj_001", "label": "table", "placed": True,
             "world_transform": {"position": [2, 0.3, 0],
                                 "rotation_xyzw": [0, 0, 0, 1], "scale": 1.0}},
        ],
        "frames": [],
    }

    def _spec(self, **kw):
        # `obj:` because these objects carry no RoomPlan box — see spec_key.
        return DesignSpec("s", "u").with_entry(_entry(key="obj:obj_000", **kw))

    def test_an_empty_spec_names_nothing(self):
        assert moved_object_ids(self._MANIFEST, DesignSpec("s", "u")) == frozenset()

    def test_a_move_is_named(self):
        assert moved_object_ids(self._MANIFEST, self._spec()) == {"obj_000"}

    def test_a_removal_is_not(self):
        """The piece is gone from the derived room, so there is no fact left
        to attribute to it."""
        spec = self._spec(action="remove", proposed_transform=None)
        assert moved_object_ids(self._MANIFEST, spec) == frozenset()

    def test_a_turn_is_not(self):
        """Nothing `scene_facts` derives reads a rotation, so a turn leaves
        every fact the guest can speak exactly as measured — the same reason
        rule 10's conditional grammar does not apply to one."""
        spec = self._spec(action="turn", proposed_transform=Transform(
            (1.0, 0.5, 2.0), (0, 1, 0, 0), 1.0))
        assert moved_object_ids(self._MANIFEST, spec) == frozenset()

    def test_a_turn_composed_onto_a_move_is_still_a_move(self):
        """`run_propose` keeps the move's action when a turn composes onto
        it, and the piece is still standing somewhere nothing measured."""
        spec = self._spec(proposed_transform=Transform(
            (3.0, 0.5, 1.0), (0, 1, 0, 0), 1.0))
        assert moved_object_ids(self._MANIFEST, spec) == {"obj_000"}

    def test_an_orphaned_entry_names_nothing(self):
        """A key that stops resolving is surfaced elsewhere, never dropped —
        but it points at no object here, so it cannot claim one is moved."""
        spec = DesignSpec("s", "u").with_entry(_entry(key="box:GONE"))
        assert moved_object_ids(self._MANIFEST, spec) == frozenset()

    def test_it_agrees_with_what_apply_to_manifest_did(self):
        """The pair has to read the same spec the same way: every id named
        here is present in the applied room, and carries the proposed
        position rather than the measured one."""
        spec = self._spec()
        applied = apply_to_manifest(self._MANIFEST, spec)
        named = moved_object_ids(self._MANIFEST, spec)
        assert named
        for object_id in named:
            obj = next(o for o in applied["objects"]
                       if o["object_id"] == object_id)
            assert obj["world_transform"]["position"] == [3.0, 0.5, 1.0]


# ---------------------------------------------------------------------------
# The tools
# ---------------------------------------------------------------------------

class TestToolSchemas:
    def test_the_schema_offers_no_way_to_pass_a_coordinate(self):
        """0132's central claim, enforced structurally: no FIELD exists
        through which the guest could author a position. Checked on property
        names and value types, not on the prose — the descriptions talk about
        positions precisely in order to say the guest may not give one.
        """
        def field_names(schema: dict) -> set[str]:
            out = set()
            for name, prop in (schema.get("properties") or {}).items():
                out.add(name.lower())
                out |= field_names(prop)
                out |= field_names(prop.get("items") or {})
            return out

        names = set()
        numeric = []
        for tool in TOOLS:
            names |= field_names(tool["input_schema"])
            stack = [tool["input_schema"]]
            while stack:
                node = stack.pop()
                if node.get("type") in ("number", "integer"):
                    numeric.append(node)
                stack += list((node.get("properties") or {}).values())
                if isinstance(node.get("items"), dict):
                    stack.append(node["items"])
        assert names == {"changes", "object_id", "action", "relation", "anchor",
                         "keys"}
        assert not numeric, "a numeric tool field is a coordinate waiting to happen"
        # And every free-form field the guest DOES control is a string it
        # could have read off the inventory or heard the person say.
        assert "relation" in names and "anchor" in names

    def test_relations_come_from_the_solver_not_from_a_second_list(self):
        from spec_solver import RELATIONS
        propose = next(t for t in TOOLS if t["name"] == "propose")
        enum = propose["input_schema"]["properties"]["changes"]["items"][
            "properties"]["relation"]["enum"]
        assert set(enum) == RELATIONS


class TestPropose:
    def _run(self, changes, spec=None):
        _manifest, geometry, measured = _spike()
        return run_propose(
            spec=spec or DesignSpec("s", "u"),
            geometry=geometry,
            manifest_transforms=measured,
            changes=changes,
            turn_index=3,
            client_msg_id="c9",
        )

    def test_a_grounded_move_lands_with_its_measurement_and_its_reasoning(self):
        out = self._run([{"object_id": "obj_003", "action": "move",
                          "relation": "against_wall"}])
        assert out.changed
        entry = out.spec.entries[0]
        assert entry.action == "move"
        assert entry.measured_transform is not None
        assert entry.proposed_transform.position != entry.measured_transform.position
        assert entry.solver.relation == "against_wall"
        assert entry.solver.reasoning
        assert entry.measured_footprint is not None
        assert entry.turn_index == 3 and entry.client_msg_id == "c9"
        assert out.result["changes"][0] == {
            "object_id": "obj_003", "applied": True,
            "description": entry.description,
        }

    def test_the_proposal_never_changes_rotation_or_scale(self):
        """v1 is translation-only, and it is a scope cut with evidence: every
        box placement ships splat_axis_resolved false (0080/0104)."""
        out = self._run([{"object_id": "obj_003", "action": "move",
                          "relation": "against_wall"}])
        e = out.spec.entries[0]
        assert e.proposed_transform.rotation_xyzw == e.measured_transform.rotation_xyzw
        assert e.proposed_transform.scale == e.measured_transform.scale
        assert e.proposed_transform.position[1] == e.measured_transform.position[1]

    def test_a_refusal_writes_nothing(self):
        out = self._run([{"object_id": "obj_003", "action": "move",
                          "relation": "against_wall", "anchor": "the window"}])
        assert not out.changed
        assert out.spec.entries == ()
        assert out.result["changes"][0]["applied"] is False
        assert out.result["changes"][0]["reason"] == "ambiguous_anchor"

    def test_remove_needs_no_solver_and_no_geometry(self):
        out = self._run([{"object_id": "obj_003", "action": "remove"}])
        entry = out.spec.entries[0]
        assert entry.action == "remove"
        assert entry.proposed_transform is None
        assert entry.solver is None
        assert entry.measured_transform is not None

    def test_changes_are_independent_so_one_refusal_keeps_the_rest(self):
        out = self._run([
            {"object_id": "obj_003", "action": "move", "relation": "against_wall"},
            {"object_id": "nope", "action": "move", "relation": "against_wall"},
            {"object_id": "obj_006", "action": "remove"},
        ])
        applied = [c["applied"] for c in out.result["changes"]]
        assert applied == [True, False, True]
        assert len(out.spec.entries) == 2

    def test_unknown_object_and_action(self):
        out = self._run([{"object_id": "ghost", "action": "move"}])
        assert out.result["changes"][0]["reason"] == "unknown_object"
        out = self._run([{"object_id": "obj_003", "action": "levitate"}])
        assert out.result["changes"][0]["reason"] == "unknown_action"

    def test_a_piece_can_be_named_instead_of_identified(self):
        out = self._run([{"object_id": "bed", "action": "remove"}])
        assert out.changed and out.spec.entries[0].label == "bed"


class TestRevert:
    def test_reverting_one_piece_leaves_the_others(self):
        _m, geometry, _t = _spike()
        spec = (DesignSpec("s", "u")
                .with_entry(_entry(key="box:A"))
                .with_entry(_entry(key="box:B")))
        out = run_revert(spec=spec, geometry=geometry, keys=["box:A"])
        assert out.changed and [e.key for e in out.spec.entries] == ["box:B"]

    def test_all_puts_the_whole_room_back(self):
        _m, geometry, _t = _spike()
        spec = (DesignSpec("s", "u")
                .with_entry(_entry(key="box:A"))
                .with_entry(_entry(key="box:B")))
        out = run_revert(spec=spec, geometry=geometry, keys=["all"])
        assert out.spec.entries == () and out.result["reverted"] == 2

    def test_reverting_nothing_is_not_a_change(self):
        _m, geometry, _t = _spike()
        out = run_revert(spec=DesignSpec("s", "u"), geometry=geometry, keys=["all"])
        assert not out.changed and out.result["reverted"] == 0

    def test_an_orphaned_entry_can_still_be_cleared(self):
        """Its object is gone from the manifest, so name resolution cannot
        find it — but clearing it is exactly what someone shown "this piece is
        no longer in the room" wants to do."""
        _m, geometry, _t = _spike()
        spec = DesignSpec("s", "u").with_entry(_entry(key="box:VANISHED"))
        out = run_revert(spec=spec, geometry=geometry, keys=["box:VANISHED"])
        assert out.changed and out.spec.entries == ()


class TestToolDispatch:
    def test_unknown_tool_and_empty_input_change_nothing(self):
        _m, geometry, measured = _spike()
        spec = DesignSpec("s", "u")
        for name, payload in (("teleport", {}), ("propose", {}),
                              ("propose", {"changes": []})):
            out = run_tool(name, payload, spec=spec, geometry=geometry,
                           manifest_transforms=measured, turn_index=0,
                           client_msg_id="c")
            assert not out.changed and out.spec is spec


class TestTelemetry:
    def test_tool_results_join_the_measurement_allowlist(self):
        from guest_prompt import foreign_measurements
        reply = "It is 0.8 m clear now."
        assert foreign_measurements(reply, "", []) == ["0.8 m"]
        assert foreign_measurements(
            reply, "", [], ["at least 0.8 m of clear space would remain"]
        ) == []

    def test_texts_are_collected_from_both_tool_shapes(self):
        assert tool_result_texts([
            {"changes": [{"applied": True, "description": "the bed moved"},
                         {"applied": False, "reason": "no_clear_space"}]},
            {"reverted": 1, "description": "put back as measured"},
        ]) == ["the bed moved", "put back as measured"]

    def test_unprompted_proposal_flags_only_an_unasked_change(self):
        assert unprompted_proposal("What do you think of this room?", True)
        assert not unprompted_proposal("What do you think of this room?", False)
        for asked in ("move the bed over there", "can we try that?",
                      "yes please", "get rid of the chair", "sure"):
            assert not unprompted_proposal(asked, True), asked


class TestFindingThePiece:
    """`_find` is where the model's `object_id` meets the room, and the one
    place a good answer can still be thrown away (decision 0185).

    Fixture-free on purpose: this is the resolution the transcript's own first
    turn depends on, and it should not skip when dev-fixtures are absent.
    """

    def _geometry(self):
        manifest = {
            "scene_id": "s", "manifest_version": 2, "frame_count": 9,
            "objects": [
                {"object_id": "obj_000", "label": "chair", "placed": True,
                 "color": {"hex": "#880607", "concentration": 0.74,
                           "visible_fraction": 0.9, "visible_points": 9000},
                 "quality": {"frames_observed": 4, "cluster_spread_m": 0.05},
                 "world_transform": {"position": [0, 0.3, 0],
                                     "rotation_xyzw": [0, 0, 0, 1], "scale": 1.0}},
                {"object_id": "obj_001", "label": "chair", "placed": True,
                 "color": {"hex": "#151414", "concentration": 0.9,
                           "visible_fraction": 0.9, "visible_points": 9000},
                 "quality": {"frames_observed": 4, "cluster_spread_m": 0.05},
                 "world_transform": {"position": [2, 0.3, 0],
                                     "rotation_xyzw": [0, 0, 0, 1], "scale": 1.0}},
                {"object_id": "obj_002", "label": "bed", "placed": True,
                 "quality": {"frames_observed": 5, "cluster_spread_m": 0.03},
                 "world_transform": {"position": [0, 0.3, 3],
                                     "rotation_xyzw": [0, 0, 0, 1], "scale": 1.0}},
            ],
            "frames": [],
        }
        facts = derive_scene_facts(manifest)
        assert [i.name for i in facts.inventory] == [
            "red chair", "black chair", "bed"
        ]
        return derive_room_geometry(
            manifest, None,
            names={i.object_id: i.name for i in facts.inventory},
        )

    def test_the_forms_the_model_actually_emits_all_resolve(self):
        """Measured on the transcript's first turn: 5 of 8 samples wrote
        "red_chair" and were refused, and 2 of 8 wrote "the first chair" under
        the pre-0184 names. The field is called object_id and THE FACTS show a
        name, so the model normalises one into the other."""
        geometry = self._geometry()
        for form in ("red chair", "red_chair", "the red chair", "Red Chair",
                     "red-chair", "  red   chair  ", "the_red_chair",
                     "obj_000"):
            found = _find(geometry, form)
            assert found is not None and found.object_id == "obj_000", form

    def test_it_still_refuses_a_piece_the_room_does_not_have(self):
        geometry = self._geometry()
        for form in ("bookshelf", "the bookshelf", "blue chair", "", "the", "_"):
            found = _find(geometry, form)
            assert isinstance(found, Refusal), form
            assert found.reason == "unknown_object", form

    def test_tolerance_never_moves_a_match_to_a_different_piece(self):
        """Reduction, not fuzzy matching. Names are unique space-separated
        words, so normalising can resolve MORE and can never resolve
        differently — the property that made this safe to widen."""
        geometry = self._geometry()
        for obj in geometry.objects:
            assert _find(geometry, obj.name) is obj
            assert _find(geometry, obj.object_id) is obj
        assert _find(geometry, "the bed").object_id == "obj_002"

    def test_a_bare_ambiguous_label_refuses_and_names_the_candidates(self):
        """The defect this class was written to pin, now fixed (0213).

        "chair" in a two-chair room used to resolve to whichever object
        sorted first, silently. It now refuses with both spoken names, which
        is what lets the guest ask a question the person can actually answer.
        """
        geometry = self._geometry()
        for form in ("chair", "the chair", "  Chair ", "the_chair"):
            found = _find(geometry, form)
            assert isinstance(found, Refusal), form
            assert found.reason == "ambiguous_object", form
            assert found.detail == "black chair, red chair", form

    def test_colour_is_what_separates_them(self):
        """Acceptance criterion 2. The tiers exist so that an exact NAME is
        never thrown away by a LABEL two pieces share — "red chair" resolves
        in the same room where "chair" refuses."""
        geometry = self._geometry()
        assert _find(geometry, "red chair").object_id == "obj_000"
        assert _find(geometry, "black chair").object_id == "obj_001"
        assert isinstance(_find(geometry, "chair"), Refusal)

    def test_the_refusal_reaches_the_guest_as_a_refusal(self):
        """The whole point: `propose` must not act. A silent wrong piece is
        the one failure that reads to the person as the room being wrong."""
        geometry = self._geometry()
        out = run_propose(
            spec=DesignSpec("s", "u"),
            geometry=geometry,
            manifest_transforms={},
            changes=[{"object_id": "chair", "action": "remove"}],
            turn_index=0,
            client_msg_id="m",
        )
        assert out.changed is False
        assert out.spec.entries == ()
        change = out.result["changes"][0]
        assert change["applied"] is False
        assert change["reason"] == "ambiguous_object"
        assert change["detail"] == "black chair, red chair"

    def test_revert_refuses_the_same_reference_rather_than_picking(self):
        """And does not then say "nothing to put back", which would be a lie:
        there is something, the room cannot tell which."""
        geometry = self._geometry()
        moved = run_propose(
            spec=DesignSpec("s", "u"),
            geometry=geometry,
            manifest_transforms={},
            changes=[{"object_id": "red chair", "action": "remove"},
                     {"object_id": "black chair", "action": "remove"}],
            turn_index=0,
            client_msg_id="m",
        )
        assert len(moved.spec.entries) == 2
        out = run_revert(spec=moved.spec, geometry=geometry, keys=["chair"])
        assert out.changed is False
        assert out.result["reverted"] == 0
        assert "description" not in out.result
        assert out.result["refused"] == [
            {"key": "chair", "reason": "ambiguous_object",
             "detail": "black chair, red chair"}
        ]

    def _uncoloured_geometry(self):
        """Two chairs the scan could not read a colour for — the common case,
        and the one where the confidence gate is working rather than failing.
        scene_facts falls back to ordinals here, and 0184 is explicit that an
        ordinal is not a referent: the person cannot tell which chair is the
        second one either.
        """
        manifest = {
            "scene_id": "s", "manifest_version": 2, "frame_count": 9,
            "objects": [
                {"object_id": "obj_000", "label": "chair", "placed": True,
                 "quality": {"frames_observed": 4, "cluster_spread_m": 0.05},
                 "world_transform": {"position": [0, 0.3, 0],
                                     "rotation_xyzw": [0, 0, 0, 1], "scale": 1.0}},
                {"object_id": "obj_001", "label": "chair", "placed": True,
                 "quality": {"frames_observed": 4, "cluster_spread_m": 0.05},
                 "world_transform": {"position": [2, 0.3, 0],
                                     "rotation_xyzw": [0, 0, 0, 1], "scale": 1.0}},
            ],
            "frames": [],
        }
        facts = derive_scene_facts(manifest)
        assert [i.name for i in facts.inventory] == ["first chair", "second chair"]
        return derive_room_geometry(
            manifest, None,
            names={i.object_id: i.name for i in facts.inventory},
        )

    def test_the_refusal_is_clean_where_no_colour_exists(self):
        """Acceptance criterion 2's other half. Nothing measured separates
        these two, so the refusal must still be a refusal — not a silent pick,
        and not an invented distinguishing feature."""
        geometry = self._uncoloured_geometry()
        found = _find(geometry, "chair")
        assert isinstance(found, Refusal)
        assert found.reason == "ambiguous_object"
        assert found.detail == "first chair, second chair"

    def test_an_ordinal_still_resolves_for_the_tool_even_though_it_is_not_a_name(self):
        """The ordinal is bookkeeping the guest may USE and must not OFFER
        (0184). Refusing it here would make a piece unmovable rather than
        unnameable, so the tool resolves it; what stops it being spoken as a
        choice is the facts block's own limit, which is present in exactly
        the rooms where a refusal can carry an ordinal.
        """
        geometry = self._uncoloured_geometry()
        assert _find(geometry, "first chair").object_id == "obj_000"
        assert _find(geometry, "the second chair").object_id == "obj_001"
