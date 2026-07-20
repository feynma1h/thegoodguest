"""Tests for scene_facts.py — the derived-facts layer (decision 0058).

These pin the layer's invariants, not its prose:
  - purity/determinism (same manifest → identical SceneFacts and identical
    rendered block, across calls)
  - inventory confidence tiers from quality.frames_observed / cluster_spread_m
  - distance strings: absolute facts carry their own framing and honest
    rounding; comparative facts exist; NO gap/clearance vocabulary anywhere
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

    def test_no_gap_or_clearance_vocabulary(self):
        block = render_facts_block(derive_scene_facts(_room()))
        for banned in ("gap", "clearance", "fits", "walkway"):
            # The words appear only inside the explicit prohibition line.
            for line in block.splitlines():
                if banned in line.lower():
                    assert "never restate" in line.lower()


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

    def test_cache_returns_same_object(self):
        scene_facts._cache.clear()
        manifest = _room()
        first = cached_scene_facts("scene-1", manifest)
        second = cached_scene_facts("scene-1", manifest)
        assert first is second

    def test_cache_bounded(self):
        scene_facts._cache.clear()
        for i in range(scene_facts._CACHE_MAX_ENTRIES + 10):
            cached_scene_facts(f"scene-{i}", _manifest([]))
        assert len(scene_facts._cache) == scene_facts._CACHE_MAX_ENTRIES
