"""shell.json v3 invariants (decision 0077): the roomplan method's verbatim
CapturedRoom geometry (pinned against the committed spike fixture), the
run_shell tier dispatch, every degrade leg (roomplan_parse_failed →
anchor_envelope, capture_expired → materials-only loss, ARKIT_ONLY → the
untouched v2 path), byte-determinism, and the no-texture serving contract
carried into v3.

Run from repo root:
    python -m pytest services/perception-obj/tests/test_shell_v3.py -v
"""
from __future__ import annotations

import io
import json
import math
from pathlib import Path

import numpy as np
import pytest
import shell_material
import shell_observation
import shell_receiver
from PIL import Image
from process_receiver import PoisonError
from roomplan_room import parse_captured_room
from roomstudio_schemas import (
    ARKIT_ONLY,
    LIDAR_ARKIT,
    LIDAR_ROOMPLAN,
    PLANE_HORIZONTAL,
    PLANE_VERTICAL,
    CaptureBundle,
)
from shell_receiver import (
    _observe_planes,
    _v3_roomplan_planes,
    build_shell_json_v3,
    run_shell,
    shell_json_bytes,
)

_SCENE = "33333333-4444-4555-8666-777777777777"
_BUCKET = "test-outputs"
_BUNDLE_URI = "gs://test-captures/captures/rp/bundle.pb"
_SPIKE_ROOM_JSON = (
    Path(__file__).resolve().parent / "fixtures" / "roomplan_spike"
    / "captured_room_built.json"
)

_R = 1.0 / math.sqrt(2.0)


# ---------------------------------------------------------------------------
# Fakes (same pattern as test_shell_receiver)
# ---------------------------------------------------------------------------

class FakeGcs:
    def __init__(self) -> None:
        self.blobs: dict[str, bytes] = {}

    def exists_and_get(self, bucket: str, path: str):
        return self.blobs.get(f"{bucket}/{path}")

    def download(self, uri: str) -> bytes:
        assert uri.startswith("gs://")
        key = uri[5:]
        if key not in self.blobs:
            raise PoisonError(f"GCS object not found: {uri}")
        return self.blobs[key]

    def upload(self, prefix: str, path: str, data: bytes, content_type: str) -> str:
        bucket = prefix[5:].split("/")[0]
        self.blobs[f"{bucket}/{path}"] = data
        return f"gs://{bucket}/{path}"


def _fake_classify(crops, kind):
    return ("wood", 0.9) if kind == "floor" else ("painted", 0.85)


@pytest.fixture
def gcs(monkeypatch) -> FakeGcs:
    fake = FakeGcs()
    monkeypatch.setattr(shell_receiver, "_gcs_blob_exists_and_get", fake.exists_and_get)
    monkeypatch.setattr(shell_receiver, "_download_gcs_uri", fake.download)
    monkeypatch.setattr(shell_receiver, "_gcs_upload_for_scene", fake.upload)
    monkeypatch.setattr(shell_observation, "SHELL_METERS_PER_TEXEL", 0.25)
    monkeypatch.setattr(shell_observation, "SHELL_EVIDENCE_CROP_PX", 16)
    monkeypatch.setattr(shell_material, "classify_family_via_api", _fake_classify)
    return fake


# ---------------------------------------------------------------------------
# Bundle builders
# ---------------------------------------------------------------------------

def _lidar_bundle(*, tier=LIDAR_ARKIT, roomplan: bool = False) -> CaptureBundle:
    """A LiDAR-ish bundle: floor + four tall envelope walls + one low seat
    plane (never rendered), one frame. Tall-wall tops 1.0, seat top -0.9."""
    b = CaptureBundle()
    b.schema_version = "1"
    b.bundle_id = "rp"
    b.tier = tier
    if roomplan:
        b.room_plan.json_gcs_path = "roomplan/room.json"
        b.room_plan.roomplan_version = "test;CapturedRoom.v2;beautifyObjects"

    floor = b.plane_anchors.add()
    floor.pose.pos_y = -1.4
    floor.pose.quat_w = 1.0
    floor.extent_width = 4.0
    floor.extent_height = 3.0
    floor.alignment = PLANE_HORIZONTAL
    floor.classification = "floor"

    def _wall(px, pz, quat, w, h, py=0.0, classification="wall"):
        a = b.plane_anchors.add()
        a.pose.pos_x = px
        a.pose.pos_y = py
        a.pose.pos_z = pz
        a.pose.quat_x, a.pose.quat_y, a.pose.quat_z, a.pose.quat_w = quat
        a.extent_width = w
        a.extent_height = h
        a.alignment = PLANE_VERTICAL
        a.classification = classification

    # Room x in [-2, 2], z in [-1.5, 1.5]; wall planes face the interior.
    # +90 about X: +Y -> +Z (faces +Z);   -90 about X: +Y -> -Z.
    _wall(0.0, -1.5, (_R, 0.0, 0.0, _R), 4.0, 2.4)
    _wall(0.0, 1.5, (-_R, 0.0, 0.0, _R), 4.0, 2.4)
    # -90 about Z: +Y -> +X (faces +X);   +90 about Z: +Y -> -X.
    _wall(-2.0, 0.0, (0.0, 0.0, -_R, _R), 3.0, 2.4)
    _wall(2.0, 0.0, (0.0, 0.0, _R, _R), 3.0, 2.4)
    # A bed rail: seat, low — internal evidence only.
    _wall(0.5, 0.5, (_R, 0.0, 0.0, _R), 2.0, 0.5, py=-1.15, classification="seat")

    f = b.frames.add()
    f.frame_index = 0
    f.rgb_gcs_path = "frames/000000.jpg"
    f.camera_pose.pos_y = 0.2
    f.camera_pose.pos_z = 1.0
    f.camera_pose.quat_w = 1.0
    f.intrinsics.fx = 60.0
    f.intrinsics.fy = 60.0
    f.intrinsics.cx = 32.0
    f.intrinsics.cy = 32.0
    f.intrinsics.width = 64
    f.intrinsics.height = 64
    return b


def _rgb_png_bytes(color=(180, 140, 100)) -> bytes:
    img = np.zeros((64, 64, 3), dtype=np.uint8)
    img[:, :] = color
    buf = io.BytesIO()
    Image.fromarray(img).save(buf, format="PNG")
    return buf.getvalue()


def _masks_npz_bytes() -> bytes:
    buf = io.BytesIO()
    np.savez_compressed(buf, masks=np.zeros((0,), dtype=bool))
    return buf.getvalue()


def _manifest() -> dict:
    return {
        "scene_id": _SCENE,
        "manifest_version": 2,
        "frames": [
            {
                "frame_index": 0,
                "rgb_gcs_uri": "gs://test-captures/captures/rp/frames/000000.jpg",
                "masks_gcs_uri": f"gs://{_BUCKET}/scenes/{_SCENE}/frames/0000/masks.npz",
            }
        ],
    }


def _seed(gcs: FakeGcs, bundle: CaptureBundle, *, room_json: bytes | None = None,
          cached_room_json: bytes | None = None) -> None:
    gcs.blobs["test-captures/captures/rp/bundle.pb"] = bundle.SerializeToString()
    gcs.blobs["test-captures/captures/rp/frames/000000.jpg"] = _rgb_png_bytes()
    gcs.blobs[f"{_BUCKET}/scenes/{_SCENE}/manifest.json"] = json.dumps(_manifest()).encode()
    gcs.blobs[f"{_BUCKET}/scenes/{_SCENE}/frames/0000/masks.npz"] = _masks_npz_bytes()
    if room_json is not None:
        gcs.blobs["test-captures/captures/rp/roomplan/room.json"] = room_json
    if cached_room_json is not None:
        gcs.blobs[f"{_BUCKET}/scenes/{_SCENE}/roomplan/room.json"] = cached_room_json


def _run(deadline=None) -> dict:
    return run_shell(
        scene_id=_SCENE, bundle_uri=_BUNDLE_URI,
        outputs_bucket=_BUCKET, deadline=deadline,
    )


def _doc(gcs: FakeGcs) -> dict:
    return json.loads(gcs.blobs[f"{_BUCKET}/scenes/{_SCENE}/shell.json"])


def _spike_room_bytes() -> bytes:
    return _SPIKE_ROOM_JSON.read_bytes()


# ---------------------------------------------------------------------------
# The roomplan method against the committed spike fixture (the RP-3 gate:
# spike fixture reproduction, offline)
# ---------------------------------------------------------------------------

def _polygon_area_xz(poly: list[list[float]]) -> float:
    pts = np.asarray(poly)
    x, z = pts[:, 0], pts[:, 2]
    return 0.5 * abs(float(np.dot(x, np.roll(z, -1)) - np.dot(np.roll(x, -1), z)))


class TestRoomplanDocFromSpikeFixture:
    @pytest.fixture()
    def doc(self) -> dict:
        room = parse_captured_room(_spike_room_bytes())
        plane_results = _observe_planes(_SCENE, _planes_for(room), [], None)
        floor_out, walls_out = _v3_roomplan_planes(room, plane_results)
        return build_shell_json_v3(
            scene_id=_SCENE, status="ready", reason=None, method="roomplan",
            floor=floor_out, walls=walls_out,
            quality={"frames_used": 0},
        )

    def test_walls_and_floor_verbatim(self, doc):
        assert doc["shell_version"] == 3
        assert doc["method"] == "roomplan"
        assert len(doc["walls"]) == 13  # the P2 pin: 13 walls
        floor = doc["floor"]
        assert len(floor["polygon"]) == 10  # 10-corner floor polygon
        assert _polygon_area_xz(floor["polygon"]) == pytest.approx(14.98, abs=0.02)
        assert floor["confidence"] == "high"

    def test_wall_confidence_and_classification_carried(self, doc):
        for w in doc["walls"]:
            assert w["confidence"] in ("high", "medium", "low")
            assert w["classification"] == "wall"
            assert w["provenance"] == {"source": "roomplan"}

    def test_openings_normalized(self, doc):
        walls_with_openings = [w for w in doc["walls"] if w["openings"]]
        assert walls_with_openings  # doors/windows/openings parent to walls
        kinds = set()
        for w in walls_with_openings:
            for op in w["openings"]:
                kinds.add(op["classification"])
                (u0, v0), (u1, v1) = op["rect_uv"]
                assert 0.0 <= u0 <= u1 <= 1.0
                assert 0.0 <= v0 <= v1 <= 1.0
        assert {"door", "window", "opening"} <= kinds

    def test_winding_fronts_interior(self, doc):
        """Every wall polygon's face normal (Newell) points toward the room
        interior — the single-sided dollhouse contract."""
        floor_pts = np.asarray(doc["floor"]["polygon"])
        interior = floor_pts.mean(axis=0) + np.array([0.0, 1.0, 0.0])
        for w in doc["walls"]:
            pts = np.asarray(w["polygon"])
            normal = np.zeros(3)
            for i in range(len(pts)):
                a, b = pts[i], pts[(i + 1) % len(pts)]
                normal += np.cross(a, b)
            anchor = pts.mean(axis=0)
            assert float(np.dot(normal, interior - anchor)) > 0, w["wall_id"]

    def test_empty_samples_yield_null_materials(self, doc):
        """The capture-expired leg: geometry ships, materials are the honest
        empty observation (albedo null, family null — THE fallback rule)."""
        for w in doc["walls"]:
            assert w["material"]["albedo_hex"] is None
            assert w["material"]["family"] is None
        assert doc["floor"]["material"]["albedo_hex"] is None

    def test_deterministic_bytes(self):
        room = parse_captured_room(_spike_room_bytes())
        docs = []
        for _ in range(2):
            plane_results = _observe_planes(_SCENE, _planes_for(room), [], None)
            floor_out, walls_out = _v3_roomplan_planes(room, plane_results)
            docs.append(shell_json_bytes(build_shell_json_v3(
                scene_id=_SCENE, status="ready", reason=None, method="roomplan",
                floor=floor_out, walls=walls_out, quality={},
            )))
        assert docs[0] == docs[1]

    def test_no_texture_or_closure_keys(self, doc):
        raw = json.dumps(doc)
        assert "texture_gcs_uri" not in raw
        assert "inpainted_fraction" not in raw
        assert '"edges"' not in raw  # v2 closure states don't apply (0077)
        for w in doc["walls"]:
            assert "quad" not in w  # v3 walls are polygons


def _planes_for(room):
    from roomplan_room import (
        roomplan_floor_geom,
        roomplan_primary_floor,
        roomplan_wall_pairs,
    )
    planes = []
    fg = roomplan_floor_geom(room)
    fs = roomplan_primary_floor(room)
    if fg is not None and fs is not None:
        planes.append(("floor", fg, [fs.polygon_world]))
    for _s, g in roomplan_wall_pairs(room):
        planes.append((g.wall_id, g, None))
    return planes


# ---------------------------------------------------------------------------
# run_shell tier dispatch
# ---------------------------------------------------------------------------

class TestDispatch:
    def test_roomplan_bundle_ships_v3_roomplan(self, gcs):
        _seed(gcs, _lidar_bundle(tier=LIDAR_ROOMPLAN, roomplan=True),
              room_json=_spike_room_bytes())
        body = _run()
        assert body == {"status": "ready", "reason": None}
        doc = _doc(gcs)
        assert doc["shell_version"] == 3
        assert doc["method"] == "roomplan"
        assert doc["quality"]["roomplan"]["source"] == "bundle"
        assert doc["quality"]["roomplan"]["walls"] == 13
        assert len(doc["walls"]) == 13

    def test_cached_room_json_preferred(self, gcs):
        _seed(gcs, _lidar_bundle(tier=LIDAR_ROOMPLAN, roomplan=True),
              room_json=b"{corrupt-but-never-read",
              cached_room_json=_spike_room_bytes())
        _run()
        doc = _doc(gcs)
        assert doc["method"] == "roomplan"
        assert doc["quality"]["roomplan"]["source"] == "cached"

    def test_roomplan_missing_json_degrades_to_envelope(self, gcs):
        """The 0077 degrade lock: room.json gone → LIDAR_ARKIT semantics
        (anchor_envelope), a recorded reason, NEVER a failure."""
        _seed(gcs, _lidar_bundle(tier=LIDAR_ROOMPLAN, roomplan=True))
        body = _run()
        assert body == {"status": "ready", "reason": None}
        doc = _doc(gcs)
        assert doc["method"] == "anchor_envelope"
        assert doc["quality"]["roomplan_parse_failed"] == "room_json_missing"

    def test_roomplan_corrupt_json_degrades_to_envelope(self, gcs):
        _seed(gcs, _lidar_bundle(tier=LIDAR_ROOMPLAN, roomplan=True),
              room_json=b"not json at all")
        _run()
        doc = _doc(gcs)
        assert doc["method"] == "anchor_envelope"
        assert "not valid JSON" in doc["quality"]["roomplan_parse_failed"]

    def test_lidar_arkit_ships_envelope(self, gcs):
        _seed(gcs, _lidar_bundle(tier=LIDAR_ARKIT))
        body = _run()
        assert body == {"status": "ready", "reason": None}
        doc = _doc(gcs)
        assert doc["shell_version"] == 3
        assert doc["method"] == "anchor_envelope"
        assert "roomplan_parse_failed" not in doc["quality"]
        assert len(doc["walls"]) == 4  # the seat rail is never rendered
        assert doc["quality"]["envelope_closed"] is True
        srcs = [w["provenance"]["merged_wall_id"] for w in doc["walls"]]
        assert len(set(srcs)) == 4
        # measured beside rendered (the honesty invariant carried into v3)
        for w in doc["walls"]:
            assert len(w["measured_quad"]) == 4
            assert len(w["polygon"]) == 4

    def test_envelope_floor_is_intersection_rectangle(self, gcs):
        _seed(gcs, _lidar_bundle(tier=LIDAR_ARKIT))
        _run()
        doc = _doc(gcs)
        floor = doc["floor"]
        assert floor["provenance"]["source"] == "envelope_intersection"
        assert len(floor["polygon"]) == 4
        assert _polygon_area_xz(floor["polygon"]) == pytest.approx(12.0, abs=0.1)
        assert floor["measured_polygon"] is not None

    def test_arkit_only_keeps_v2_path(self, gcs):
        """The tier-ladder lock: ARKIT_ONLY is legacy, untouched — same doc
        shape as before 0077 (shell_version 2, method arkit_planes,
        closure edges present)."""
        b = _lidar_bundle(tier=ARKIT_ONLY)
        _seed(gcs, b)
        body = _run()
        assert body == {"status": "ready", "reason": None}
        doc = _doc(gcs)
        assert doc["shell_version"] == 2
        assert doc["method"] == "arkit_planes"
        assert all("edges" in w for w in doc["walls"])

    def test_unspecified_tier_keeps_v2_path(self, gcs):
        b = _lidar_bundle(tier=ARKIT_ONLY)
        b.tier = 0  # CAPTURE_TIER_UNSPECIFIED
        _seed(gcs, b)
        _run()
        assert _doc(gcs)["shell_version"] == 2


class TestCaptureExpired:
    def test_swept_bundle_with_cached_roomplan_ships_geometry(self, gcs):
        """capture_expired costs materials only (decision 0077): the cached
        room.json carries the geometry; every material is the honest empty
        observation."""
        gcs.blobs[f"{_BUCKET}/scenes/{_SCENE}/roomplan/room.json"] = _spike_room_bytes()
        body = _run()
        assert body == {"status": "ready", "reason": None}
        doc = _doc(gcs)
        assert doc["method"] == "roomplan"
        assert doc["quality"]["roomplan"]["source"] == "cached"
        assert doc["quality"]["materials_note"] == "capture_expired"
        assert len(doc["walls"]) == 13
        assert all(w["material"]["albedo_hex"] is None for w in doc["walls"])

    def test_swept_bundle_without_cache_is_unavailable(self, gcs):
        body = _run()
        assert body == {"status": "unavailable", "reason": "capture_expired"}
        doc = _doc(gcs)
        assert doc["shell_version"] == 2
        assert doc["status"] == "unavailable"

    def test_swept_rgb_with_live_bundle_ships_envelope_geometry(self, gcs):
        """Bundle present, RGB swept: the anchors still measure the room —
        geometry ships with empty materials (unlike the v2 path, which had
        nothing to ship without pixels)."""
        _seed(gcs, _lidar_bundle(tier=LIDAR_ARKIT))
        del gcs.blobs["test-captures/captures/rp/frames/000000.jpg"]
        body = _run()
        assert body == {"status": "ready", "reason": None}
        doc = _doc(gcs)
        assert doc["method"] == "anchor_envelope"
        assert doc["quality"]["materials_note"] == "capture_expired"
        assert doc["quality"]["frames_used"] == 0


class TestDeterminismAndRedelivery:
    def test_redelivery_noop(self, gcs):
        _seed(gcs, _lidar_bundle(tier=LIDAR_ARKIT))
        assert _run() == {"status": "ready", "reason": None}
        assert _run() == {"status": "noop", "reason": "already_present"}

    def test_v3_doc_byte_deterministic(self, gcs):
        _seed(gcs, _lidar_bundle(tier=LIDAR_ARKIT))
        _run()
        first = gcs.blobs[f"{_BUCKET}/scenes/{_SCENE}/shell.json"]
        del gcs.blobs[f"{_BUCKET}/scenes/{_SCENE}/shell.json"]
        _run()
        assert gcs.blobs[f"{_BUCKET}/scenes/{_SCENE}/shell.json"] == first
