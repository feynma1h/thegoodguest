"""boxes.json: reading the bundle's person boxes, the bytes written, and the
shape frame selection receives (decisions 0322, 0323)."""
from __future__ import annotations

import json
import math

import numpy as np
import pytest
from thegoodguest_schemas import SCHEMA_VERSION, CaptureBundle

import boxes_json


def _bundle(*boxes: dict) -> CaptureBundle:
    b = CaptureBundle()
    b.schema_version = SCHEMA_VERSION
    for spec in boxes:
        pb = b.person_boxes.add()
        pb.box_id = spec.get("id", "a")
        pb.detector_label = spec.get("label", "chair")
        pb.center_x, pb.center_y, pb.center_z = spec.get("center", (1.0, 0.5, -2.0))
        pb.yaw_rad = spec.get("yaw", 0.0)
        pb.size_x, pb.size_y, pb.size_z = spec.get("size", (0.5, 0.9, 0.5))
        pb.created_at_device_us = spec.get("at", 10)
    return b


def test_a_bundle_without_the_field_has_no_boxes():
    assert boxes_json.boxes_from_bundle(CaptureBundle()) == []


def test_a_box_comes_through_with_every_field():
    [box] = boxes_json.boxes_from_bundle(_bundle({"id": "x", "label": "dining table", "yaw": 0.3, "at": 77}))
    assert box == {
        "id": "x", "label": "dining table", "center": [1.0, 0.5, -2.0], "yaw": 0.3,
        "size": [0.5, 0.9, 0.5], "created_at_us": 77,
    }


@pytest.mark.parametrize("bad", [
    {"id": ""},
    {"center": (float("nan"), 0, 0)},
    {"yaw": float("inf")},
    {"size": (0.04, 0.5, 0.5)},
    {"size": (0.5, 6.5, 0.5)},
])
def test_an_unusable_box_is_dropped_not_repaired(bad):
    assert boxes_json.boxes_from_bundle(_bundle(bad)) == []


def test_a_repeated_id_keeps_the_earliest_and_order_is_by_time():
    out = boxes_json.boxes_from_bundle(_bundle(
        {"id": "b", "label": "late", "at": 30}, {"id": "a", "label": "first", "at": 5},
        {"id": "b", "label": "early", "at": 10}))
    assert [(b["id"], b["label"]) for b in out] == [("a", "first"), ("b", "early")]


def test_past_the_limit_the_earliest_are_kept():
    specs = [{"id": f"i{n}", "at": n} for n in range(boxes_json.MAX_BOXES + 7)]
    out = boxes_json.boxes_from_bundle(_bundle(*reversed(specs)))
    assert len(out) == boxes_json.MAX_BOXES
    assert out[0]["id"] == "i0" and out[-1]["id"] == f"i{boxes_json.MAX_BOXES - 1}"


def test_a_long_label_is_capped():
    [box] = boxes_json.boxes_from_bundle(_bundle({"label": "x" * 500}))
    assert len(box["label"]) == boxes_json.MAX_LABEL_CHARS


def test_the_bytes_are_canonical_and_an_empty_set_is_still_a_file():
    boxes = boxes_json.boxes_from_bundle(_bundle({}))
    first = boxes_json.boxes_json_bytes("scene-1", boxes)
    assert first == boxes_json.boxes_json_bytes("scene-1", list(boxes))
    doc = json.loads(first)
    assert doc["boxes_version"] == 1 and doc["source"] == "person" and doc["scene_id"] == "scene-1"
    assert b" " not in first
    empty = json.loads(boxes_json.boxes_json_bytes("s", []))
    assert empty["boxes"] == []


def test_census_boxes_stand_where_the_phone_put_them():
    # yaw a quarter turn about +Y: local +X points along world -Z.
    [cb] = boxes_json.census_boxes(boxes_json.boxes_from_bundle(
        _bundle({"center": (1.0, 0.5, -2.0), "yaw": math.pi / 2, "size": (2.0, 1.0, 0.5)})))
    corners = __import__("box_placement").box_corners_world(cb)
    assert corners[:, 1].min() == pytest.approx(0.0, abs=1e-6) and corners[:, 1].max() == pytest.approx(1.0, abs=1e-6)
    assert np.ptp(corners[:, 0]) == pytest.approx(0.5, abs=1e-4)   # the short side now lies along world X
    assert np.ptp(corners[:, 2]) == pytest.approx(2.0, abs=1e-4)   # the long side along world Z
    assert corners.mean(axis=0) == pytest.approx([1.0, 0.5, -2.0], abs=1e-4)
    assert cb.identifier == "a" and cb.category == "chair"
