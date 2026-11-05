"""The boxes the person made on the phone: read from the capture bundle,
written as boxes.json, and shaped for frame selection (decisions 0322, 0323).

The bundle's `person_boxes` (decision 0320) are the only object source. This
module is pure — no GCS, no models — so the same reading serves /process today
and any later stage that wants the boxes.

  boxes.json  (scenes/{scene_id}/boxes.json, single writer: /process)
    {"boxes_version": 1, "scene_id": ..., "source": "person",
     "boxes": [{"id", "label", "center": [x,y,z], "yaw", "size": [x,y,z],
                "created_at_us"}, ...]}

Written even when empty, so "absent" always means "not yet". Same input, same
bytes: canonical key order, floats rounded to 4 places (0.1 mm), boxes ordered
by creation time then id.

Read by: process_receiver, test_boxes_json.
"""
from __future__ import annotations

import json
import math
from typing import Any, Sequence

import numpy as np
from roomplan_room import RoomPlanBox

BOXES_VERSION = 1

# Same limits the phone's writer applies (PersonBoxWire): a bundle from an
# older or different client is held to them here too, since this is the
# cloud's own check. Sizes in metres.
MIN_SIDE_M = 0.05
MAX_SIDE_M = 6.0
MAX_BOXES = 40
# A detector label is advisory text; cap it so a hostile bundle cannot bloat
# the file or smuggle a payload into a downstream prompt.
MAX_LABEL_CHARS = 64
MAX_ID_CHARS = 64

_DECIMALS = 4


def _finite(*values: float) -> bool:
    return all(math.isfinite(v) for v in values)


def boxes_from_bundle(bundle) -> list[dict[str, Any]]:
    """The bundle's person boxes as boxes.json entries.

    Unusable boxes are dropped, never repaired or rejected (a rejected bundle
    loses the whole scan): an empty id, a number that is not finite, a side
    outside [MIN_SIDE_M, MAX_SIDE_M], a repeated id (the first by creation
    time wins). Past MAX_BOXES the earliest are kept. A bundle without the
    field yields [].
    """
    usable: list[dict[str, Any]] = []
    for pb in bundle.person_boxes:
        center = (pb.center_x, pb.center_y, pb.center_z)
        size = (pb.size_x, pb.size_y, pb.size_z)
        box_id = pb.box_id.strip()[:MAX_ID_CHARS]
        if not box_id or not _finite(*center, *size, pb.yaw_rad):
            continue
        if not all(MIN_SIDE_M <= s <= MAX_SIDE_M for s in size):
            continue
        usable.append({
            "id": box_id,
            "label": pb.detector_label.strip()[:MAX_LABEL_CHARS],
            "center": [round(float(c), _DECIMALS) for c in center],
            "yaw": round(float(pb.yaw_rad), _DECIMALS),
            "size": [round(float(s), _DECIMALS) for s in size],
            "created_at_us": int(pb.created_at_device_us),
        })
    usable.sort(key=lambda b: (b["created_at_us"], b["id"]))
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for box in usable:
        if box["id"] in seen:
            continue
        seen.add(box["id"])
        out.append(box)
    return out[:MAX_BOXES]


def boxes_json_bytes(scene_id: str, boxes: Sequence[dict[str, Any]]) -> bytes:
    """Canonical boxes.json bytes: identical inputs, identical bytes."""
    doc = {
        "boxes_version": BOXES_VERSION,
        "scene_id": scene_id,
        "source": "person",
        "boxes": list(boxes),
    }
    return json.dumps(doc, sort_keys=True, separators=(",", ":")).encode("utf-8")


def census_boxes(boxes: Sequence[dict[str, Any]]) -> list[RoomPlanBox]:
    """The boxes in the shape frame selection reads.

    Frame selection (census_sampling) was written for RoomPlan boxes and needs
    only a world_from_local transform and local dimensions, so a person box is
    given exactly those: local +Y up, local +X along the yaw direction, the
    rotation about world +Y that the phone measures (x axis = (cos, 0, -sin)).
    """
    out: list[RoomPlanBox] = []
    for b in boxes:
        c, s = math.cos(b["yaw"]), math.sin(b["yaw"])
        transform = np.array([
            [c, 0.0, s, b["center"][0]],
            [0.0, 1.0, 0.0, b["center"][1]],
            [-s, 0.0, c, b["center"][2]],
            [0.0, 0.0, 0.0, 1.0],
        ])
        out.append(RoomPlanBox(
            identifier=b["id"],
            category=b["label"] or "object",
            confidence="high",
            attributes={},
            dimensions=np.array(b["size"], dtype=float),
            transform=transform,
            center_world=np.array(b["center"], dtype=float),
            up_y=1.0,
            yaw_rad=math.atan2(-s, c),
        ))
    return out
