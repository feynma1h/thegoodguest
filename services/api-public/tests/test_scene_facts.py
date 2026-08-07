"""Tests for scene_facts.py — the derived-facts layer (decision 0058).

These pin the layer's invariants, not its prose:
  - purity/determinism (same manifest → identical SceneFacts and identical
    rendered block, across calls)
  - inventory confidence tiers from quality.frames_observed / cluster_spread_m
  - distance strings: absolute facts carry their own framing and honest
    rounding; comparative facts exist; a center distance is NEVER restated
    with gap/clearance vocabulary
  - sizes come only from trusted RoomPlan boxes, name only the longest
    dimension, and clearances are rigorous lower bounds (0096)
  - vertical relations are relative-only (no floor references)
  - unplaced objects contribute no positional facts and appear in limits
  - empty / single-placed / unplaced-only manifests degrade honestly
  - no orientation-derived facts (rotation never influences output)
  - the (scene_id, FACTS_VERSION) cache returns the cached object

Run from repo root:
  pytest services/api-public/tests/test_scene_facts.py -v
"""
from __future__ import annotations

import re

import scene_facts
from scene_facts import (
    FACTS_VERSION,
    cached_scene_facts,
    derive_scene_facts,
    render_facts_block,
)


def _obj(
    object_id: str,
    label: str,
    position: list[float] | None,
    *,
    frames: int = 5,
    spread: float | None = 0.05,
    rotation: list[float] | None = None,
) -> dict:
    placed = position is not None
    entry: dict = {
        "object_id": object_id,
        "label": label,
        "placed": placed,
        "method": "depth_fit" if placed else None,
        "splat_gcs_uri": f"gs://outputs/{object_id}.ply",
        "quality": {"frames_observed": frames}
        | ({"cluster_spread_m": spread} if spread is not None else {}),
    }
    entry["world_transform"] = (
        {
            "position": position,
            "rotation_xyzw": rotation or [0.0, 0.0, 0.0, 1.0],
            "scale": 1.0,
        }
        if placed
        else None
    )
    if not placed:
        entry["reason"] = "insufficient_observations"
    return entry


def _manifest(objects: list[dict], frame_count: int = 42) -> dict:
    return {
        "scene_id": "scene-1",
        "manifest_version": 2,
        "frame_count": frame_count,
        "objects": objects,
        "frames": [],
    }


# A room mirroring the web mock: three placed pieces + one unplaced plant.
def _room() -> dict:
    return _manifest([
        _obj("obj_000", "sofa", [0.0, 0.35, -1.6]),
        _obj("obj_001", "table", [0.1, 0.25, -0.4]),
        _obj("obj_002", "lamp", [-1.2, 0.8, -1.2], frames=1, spread=None),
        _obj("obj_003", "plant", None, frames=2),
    ])


# ---------------------------------------------------------------------------
# Determinism / purity
# ---------------------------------------------------------------------------

class TestDeterminism:
    def test_same_manifest_same_facts(self):
        assert derive_scene_facts(_room()) == derive_scene_facts(_room())

    def test_rendered_block_is_byte_stable(self):
        a = render_facts_block(derive_scene_facts(_room()))
        b = render_facts_block(derive_scene_facts(_room()))
        assert a == b

    def test_object_order_in_manifest_does_not_matter(self):
        shuffled = _room()
        shuffled["objects"] = list(reversed(shuffled["objects"]))
        assert derive_scene_facts(shuffled) == derive_scene_facts(_room())

    def test_rotation_never_influences_facts(self):
        # No orientation-derived facts: SAM 3D conventions are unverified.
        rotated = _manifest([
            _obj("obj_000", "sofa", [0.0, 0.35, -1.6],
                 rotation=[0.0, 0.7071068, 0.0, 0.7071068]),
            _obj("obj_001", "table", [0.1, 0.25, -0.4]),
        ])
        plain = _manifest([
            _obj("obj_000", "sofa", [0.0, 0.35, -1.6]),
            _obj("obj_001", "table", [0.1, 0.25, -0.4]),
        ])
        assert derive_scene_facts(rotated) == derive_scene_facts(plain)

    def test_facts_version_stamped(self):
        assert derive_scene_facts(_room()).facts_version == FACTS_VERSION


# ---------------------------------------------------------------------------
# Inventory + confidence tiers
# ---------------------------------------------------------------------------

class TestInventory:
    def test_tiers(self):
        by_name = {i.name: i for i in derive_scene_facts(_room()).inventory}
        assert by_name["sofa"].confidence == "well_observed"
        assert by_name["table"].confidence == "well_observed"
        assert by_name["lamp"].confidence == "provisional"  # 1 frame
        assert by_name["plant"].confidence == "glimpsed"
        assert not by_name["plant"].placed

    def test_high_spread_is_provisional(self):
        facts = derive_scene_facts(
            _manifest([_obj("obj_000", "sofa", [0, 0, 0], frames=5, spread=0.5)])
        )
        assert facts.inventory[0].confidence == "provisional"

    def test_duplicate_labels_get_ordinals(self):
        facts = derive_scene_facts(_manifest([
            _obj("obj_000", "chair", [0, 0, 0]),
            _obj("obj_001", "chair", [1, 0, 0]),
            _obj("obj_002", "sofa", [2, 0, 0]),
        ]))
        names = [i.name for i in facts.inventory]
        assert names == ["first chair", "second chair", "sofa"]


# ---------------------------------------------------------------------------
# Distances
# ---------------------------------------------------------------------------

class TestDistances:
    def test_absolute_distance_carries_framing_and_rounding(self):
        facts = derive_scene_facts(_manifest([
            _obj("obj_000", "sofa", [0.0, 0.0, 0.0]),
            _obj("obj_001", "table", [1.32, 0.0, 0.0]),
        ]))
        absolutes = [d.text for d in facts.distances if d.kind == "absolute"]
        assert absolutes == [
            "about 1.3 m between the sofa's center and the table's center"
        ]

    def test_near_coincident_centers_refuse_a_number(self):
        facts = derive_scene_facts(_manifest([
            _obj("obj_000", "sofa", [0.0, 0.0, 0.0]),
            _obj("obj_001", "table", [0.01, 0.0, 0.0]),
        ]))
        absolutes = [d.text for d in facts.distances if d.kind == "absolute"]
        assert absolutes == [
            "the sofa's center and the table's center are less than 0.1 m apart"
        ]

    def test_comparative_nearest_neighbor(self):
        facts = derive_scene_facts(_manifest([
            _obj("obj_000", "sofa", [0.0, 0.0, 0.0]),
            _obj("obj_001", "table", [1.0, 0.0, 0.0]),
            _obj("obj_002", "lamp", [4.0, 0.0, 0.0]),
        ]))
        comparatives = {d.text for d in facts.distances if d.kind == "comparative"}
        assert (
            "of the placed pieces, the sofa's nearest neighbor is the table"
            in comparatives
        )
        assert (
            "of the placed pieces, the lamp's nearest neighbor is the table"
            in comparatives
        )

    def test_unplaced_objects_join_no_distances(self):
        facts = derive_scene_facts(_room())
        joined = " ".join(d.text for d in facts.distances)
        assert "plant" not in joined

    def test_distance_strings_never_use_gap_or_clearance_vocabulary(self):
        """0096 gave clearances their own separate, rigorously-derived fact
        class — but a CENTER DISTANCE restated as a gap remains the forbidden
        move, so the distance strings themselves stay clean."""
        facts = derive_scene_facts(_room())
        for d in facts.distances:
            lowered = d.text.lower()
            for banned in ("gap", "clearance", "clear space", "fits", "walkway"):
                assert banned not in lowered, f"{banned!r} leaked into {d.text!r}"


# ---------------------------------------------------------------------------
# Vertical relations
# ---------------------------------------------------------------------------

class TestVerticalRelations:
    def test_relative_only_no_floor(self):
        facts = derive_scene_facts(_room())
        joined = " ".join(facts.vertical_relations).lower()
        assert "floor" not in joined
        assert "above the ground" not in joined

    def test_higher_lower_framed(self):
        facts = derive_scene_facts(_manifest([
            _obj("obj_000", "lamp", [0.0, 0.8, 0.0]),
            _obj("obj_001", "table", [0.0, 0.25, 0.0]),
        ]))
        assert facts.vertical_relations == (
            "the lamp's center sits about 0.6 m higher than the table's center",
        )

    def test_same_height_band(self):
        facts = derive_scene_facts(_manifest([
            _obj("obj_000", "sofa", [0.0, 0.30, 0.0]),
            _obj("obj_001", "chair", [1.0, 0.35, 0.0]),
        ]))
        assert facts.vertical_relations == (
            "the sofa's center and the chair's center sit at about the same height",
        )


# ---------------------------------------------------------------------------
# Limits + degradation
# ---------------------------------------------------------------------------

class TestLimits:
    def test_unplaced_object_named_in_limits(self):
        facts = derive_scene_facts(_room())
        assert any("plant" in limit for limit in facts.limits)

    def test_empty_manifest(self):
        facts = derive_scene_facts(_manifest([]))
        assert facts.inventory == ()
        assert facts.distances == ()
        assert facts.vertical_relations == ()
        assert any("no recognizable objects" in limit for limit in facts.limits)
        # Renders without crashing and admits emptiness.
        assert "nothing was recognized" in render_facts_block(facts)

    def test_nothing_placed(self):
        facts = derive_scene_facts(_manifest([
            _obj("obj_000", "sofa", None),
            _obj("obj_001", "table", None),
        ]))
        assert facts.distances == ()
        assert any("nothing could be placed" in limit for limit in facts.limits)

    def test_single_placed(self):
        facts = derive_scene_facts(_manifest([_obj("obj_000", "sofa", [0, 0, 0])]))
        assert facts.distances == ()
        assert any("only one piece was placed" in limit for limit in facts.limits)

    def test_provenance_counts_are_real(self):
        facts = derive_scene_facts(_room())
        assert "3 pieces placed" in facts.provenance
        assert "1 seen but never placed" in facts.provenance
        assert "42 frames" in facts.provenance


# ---------------------------------------------------------------------------
# Rendering + cache
# ---------------------------------------------------------------------------

class TestRenderAndCache:
    def test_block_carries_version_and_sections(self):
        block = render_facts_block(derive_scene_facts(_room()))
        assert f"THE FACTS (v{FACTS_VERSION})" in block
        assert "In this room:" in block
        assert "Distances between centers" in block
        assert "cannot answer" in block

    def test_absolute_numbers_appear_only_in_framed_form(self):
        block = render_facts_block(derive_scene_facts(_room()))
        # Every number+m token in the block sits inside an "about X m" or
        # "less than X m" framing — no bare quantities to parrot.
        for match in re.finditer(r"(\S+\s+)?(\S+\s+)(\d+(?:\.\d+)?) m\b", block):
            framing = (match.group(1) or "") + match.group(2)
            assert ("about" in framing) or ("than" in framing), match.group(0)

    def test_cache_returns_same_object_and_skips_loader_on_hit(self):
        scene_facts._cache.clear()
        loads = 0

        def loader() -> dict:
            nonlocal loads
            loads += 1
            return _room()

        first = cached_scene_facts("scene-1", loader)
        second = cached_scene_facts("scene-1", loader)
        assert first is second
        assert loads == 1  # a hit costs no manifest fetch

    def test_cache_bounded(self):
        scene_facts._cache.clear()
        for i in range(scene_facts._CACHE_MAX_ENTRIES + 10):
            cached_scene_facts(f"scene-{i}", lambda: _manifest([]))
        assert len(scene_facts._cache) == scene_facts._CACHE_MAX_ENTRIES


# ---------------------------------------------------------------------------
# Sizes and clearances (facts_version 2, decision 0096)
# ---------------------------------------------------------------------------

def _boxed(
    object_id: str,
    label: str,
    position: list[float] | None,
    dims: list[float],
    *,
    confidence: str = "high",
    **kw,
) -> dict:
    """An object carrying a RoomPlan box — the only size source 0096 trusts."""
    entry = _obj(object_id, label, position, **kw)
    entry["roomplan_box"] = {
        "box_id": f"box_{object_id[-2:]}",
        "category": label,
        "confidence": confidence,
        "dims": dims,
    }
    entry["extent_m_sorted"] = sorted(dims, reverse=True)
    if position is not None:
        entry["method"] = "roomplan_box"
    return entry


class TestSizes:
    def test_speaks_a_trusted_box_size(self):
        facts = derive_scene_facts(
            _manifest([_boxed("obj_000", "bed", [0, 0.3, 0], [2.1581, 1.854, 0.6109])])
        )
        assert facts.inventory[0].size_text == "about 2.2 m at its longest"

    def test_only_the_longest_dimension_is_ever_named(self):
        """The shipped dims triple has no recoverable axis semantics (module
        docstring): the bed's largest is a length, the wardrobe's a height.
        Any height/width/footprint claim would be a coin flip."""
        facts = derive_scene_facts(
            _manifest([
                _boxed("obj_000", "bed", [0, 0.3, 0], [2.1581, 1.854, 0.6109]),
                _boxed("obj_001", "wardrobe", [3, 0.9, 0], [1.9119, 0.6845, 0.3815]),
            ])
        )
        sizes = " ".join(i.size_text or "" for i in facts.inventory).lower()
        for banned in ("tall", "height", "wide", "width", "deep", "footprint", "area"):
            assert banned not in sizes, f"{banned!r} claims an axis we don't have"
        # The two other dimensions are never quoted at all.
        block = render_facts_block(facts)
        assert "1.9 m" in block and "1.8 m" not in block
        assert "0.7 m" not in block
        # Those words may appear ONLY in the limit that disclaims them.
        for line in block.splitlines():
            if "height" in line:
                assert "unavailable" in line

    def test_splat_extents_are_never_spoken_as_a_size(self):
        """The measured reason this rule exists: a real meter-scale rug ships
        extent_m_sorted of 0.46 x 0.29 x 0.005 (textile scale collapse, 0075),
        and every splat extent is exposed to visible-region truncation."""
        rug = _obj("obj_000", "rug", [0.0, 0.0, 0.0])
        rug["extent_m_sorted"] = [0.4563, 0.2922, 0.0051]
        facts = derive_scene_facts(_manifest([rug]))

        assert facts.inventory[0].size_text is None
        assert "0.5 m" not in render_facts_block(facts)

    def test_low_box_confidence_is_size_silent(self):
        """Low confidence is where the LABEL is wrong too — the spike room's
        wardrobe arrives as a 'refrigerator'. RP-7 withholds the name there;
        0096 withholds the authoritative size that would attach to it."""
        facts = derive_scene_facts(
            _manifest([
                _boxed("obj_000", "refrigerator", [0, 0.9, 0],
                       [1.6351, 0.9063, 0.678], confidence="low")
            ])
        )
        assert facts.inventory[0].size_text is None

    def test_an_unplaced_box_still_has_a_size(self):
        """Placement and measurement are independent: a RoomPlan box that
        failed placement still measured the thing."""
        facts = derive_scene_facts(
            _manifest([_boxed("obj_000", "wardrobe", None, [1.9119, 0.6845, 0.3815])])
        )
        item = facts.inventory[0]
        assert item.placed is False
        assert item.size_text == "about 1.9 m at its longest"

    def test_size_comparisons_are_ordinal_and_measured_only(self):
        facts = derive_scene_facts(
            _manifest([
                _boxed("obj_000", "bed", [0, 0.3, 0], [2.16, 1.85, 0.61]),
                _boxed("obj_001", "chair", [2, 0.4, 0], [0.68, 0.49, 0.45]),
                _obj("obj_002", "rug", [1, 0.0, 0]),  # splat-only: excluded
            ])
        )
        joined = " ".join(facts.size_comparisons)
        assert "the bed is the largest" in joined
        assert "the chair is the smallest" in joined
        assert "rug" not in joined

    def test_limits_name_the_unmeasured_pieces_and_the_axis_gap(self):
        facts = derive_scene_facts(
            _manifest([
                _boxed("obj_000", "bed", [0, 0.3, 0], [2.16, 1.85, 0.61]),
                _obj("obj_001", "rug", [1, 0.0, 0]),
            ])
        )
        limits = " ".join(facts.limits)
        assert "the rug" in limits
        assert "LONGEST dimension" in limits


class TestClearances:
    def test_bound_is_a_floor_and_is_phrased_as_one(self):
        # Centers 3 m apart; circumradii 1.454 + 0.562 → bound 0.984, and the
        # round-DOWN rule takes that to 0.9. Rounding to nearest would have
        # said 1.0 — overstating a floor, which is the one forbidden direction.
        facts = derive_scene_facts(
            _manifest([
                _boxed("obj_000", "bed", [0.0, 0.3, 0.0], [2.16, 1.85, 0.61]),
                _boxed("obj_001", "desk", [3.0, 0.3, 0.0], [0.9, 0.5, 0.45]),
            ])
        )
        assert len(facts.clearances) == 1
        text = facts.clearances[0]
        assert text.startswith("at least ")
        assert "0.9 m of clear space" in text

    def test_bound_never_exceeds_the_true_minimum_separation(self):
        """The property the whole class rests on: whatever the yaws, no point
        of one box is closer to the other than the quoted number. Checked
        against the worst case — both boxes' longest axes pointed at each
        other, which is the tightest the geometry can ever be."""
        import math

        dims_a, dims_b = (2.16, 1.85, 0.61), (0.9, 0.5, 0.45)
        d = 3.0
        facts = derive_scene_facts(
            _manifest([
                _boxed("obj_000", "bed", [0.0, 0.3, 0.0], list(dims_a)),
                _boxed("obj_001", "desk", [d, 0.3, 0.0], list(dims_b)),
            ])
        )
        quoted = float(facts.clearances[0].split("at least ")[1].split(" m")[0])
        worst_case = d - math.dist((0, 0, 0), dims_a) / 2 - math.dist((0, 0, 0), dims_b) / 2
        assert quoted <= worst_case + 1e-9

    def test_overlapping_or_near_boxes_produce_no_claim(self):
        facts = derive_scene_facts(
            _manifest([
                _boxed("obj_000", "bed", [0.0, 0.3, 0.0], [2.16, 1.85, 0.61]),
                _boxed("obj_001", "table", [0.5, 0.3, 0.0], [0.9, 0.5, 0.45]),
            ])
        )
        assert facts.clearances == ()

    def test_never_between_a_box_and_a_splat_only_object(self):
        """A truncated splat understates the object, so a bound built on it
        would OVERSTATE the gap — the one direction the error must not go."""
        facts = derive_scene_facts(
            _manifest([
                _boxed("obj_000", "bed", [0.0, 0.3, 0.0], [2.16, 1.85, 0.61]),
                _obj("obj_001", "rug", [4.0, 0.0, 0.0]),
            ])
        )
        assert facts.clearances == ()

    def test_unplaced_boxes_contribute_no_clearance(self):
        facts = derive_scene_facts(
            _manifest([
                _boxed("obj_000", "bed", [0.0, 0.3, 0.0], [2.16, 1.85, 0.61]),
                _boxed("obj_001", "wardrobe", None, [1.91, 0.68, 0.38]),
            ])
        )
        assert facts.clearances == ()

    def test_rendered_block_frames_clearances_as_floors(self):
        facts = derive_scene_facts(
            _manifest([
                _boxed("obj_000", "bed", [0.0, 0.3, 0.0], [2.16, 1.85, 0.61]),
                _boxed("obj_001", "desk", [3.0, 0.3, 0.0], [0.9, 0.5, 0.45]),
            ])
        )
        block = render_facts_block(facts)
        assert "floors, not measurements" in block
        assert "never as an exact gap" in block


class TestFactsVersion:
    def test_version_is_two(self):
        assert FACTS_VERSION == 2
