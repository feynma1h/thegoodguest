"""Census two-pass /process invariants (decision 0077 lock 6;
process_receiver._run_census_two_pass + run_perception dispatch).

The gates, each pinned against fake models + a dict-backed GCS:
  * per-object reconstruction: SAM 3D runs once per PLAN item (box best +
    second views + long tail), NOT per mask-per-frame — the starvation
    class relieved architecturally; policy-skipped views carry
    skipped_reason and CACHE (deterministic decision);
  * the budget guarantee untouched: a budget-cut frame is never cached
    (objects.json absent, budget_stopped recorded); completed frames
    cache;
  * determinism: two clean runs produce byte-identical manifests;
  * whole-frame cache hits skip segmentation;
  * the no-census dispatch keeps the 0062 sampler + legacy loop verbatim
    (manifest policy pose_diverse_fps_v1).

Run from repo root:
    python -m pytest services/perception-obj/tests/test_census_two_pass.py -v
"""
from __future__ import annotations

import io
import json
import sys
import time as _time
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

_schemas_path = Path(__file__).resolve().parents[3] / "packages/schemas"
if str(_schemas_path) not in sys.path:
    sys.path.insert(0, str(_schemas_path))

# Stub heavy deps not installed in the test venv (test_envelope's preamble).
sys.modules.setdefault("torch", MagicMock())
sys.modules.setdefault("models", MagicMock())
sys.modules.setdefault("models.sam3", MagicMock())
sys.modules.setdefault("models.sam3d", MagicMock())

import box_placement  # noqa: E402
import process_receiver  # noqa: E402
from process_receiver import run_perception  # noqa: E402
from roomplan_room import parse_captured_room  # noqa: E402
from roomstudio_schemas import (  # noqa: E402
    LIDAR_ROOMPLAN,
    SCHEMA_VERSION,
    CaptureBundle,
)

_SCENE = "scene-census-001"
_BUNDLE_URI = "gs://captures-bucket/captures/censustest/bundle.pb"
_OUT = "outputs-bucket"

_MINI_PLY = (
    "ply\n"
    "format ascii 1.0\n"
    "element vertex 8\n"
    "property float x\n"
    "property float y\n"
    "property float z\n"
    "end_header\n"
    "0 0 0\n1 0 0\n0 1 0\n0 0 1\n1 1 0\n1 0 1\n0 1 1\n1 1 1\n"
)


def _tiny_jpeg() -> bytes:
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (64, 64), (120, 90, 60)).save(buf, format="JPEG")
    return buf.getvalue()


_JPEG = _tiny_jpeg()


# ---------------------------------------------------------------------------
# CapturedRoom JSON (minimal, parseable: one floor + one bed box)
# ---------------------------------------------------------------------------

def _col_major(T: np.ndarray) -> list[float]:
    return [float(v) for v in np.asarray(T, dtype=float).reshape(16, order="F")]


def _floor_entity() -> dict:
    # Local +Z is world up: columns (e_x, -e_z, e_y); floor at y = -1.4.
    T = np.eye(4)
    T[:3, :3] = np.array([[1.0, 0.0, 0.0], [0.0, 0.0, 1.0], [0.0, -1.0, 0.0]])
    T[1, 3] = -1.4
    return {
        "identifier": "FLOOR-1",
        "category": {"floor": {}},
        "confidence": {"high": {}},
        "dimensions": [8.0, 8.0, 0.0],
        "transform": _col_major(T),
        "polygonCorners": [],
    }


def _bed_entity(center=(0.0, 0.0, -3.0), dims=(2.0, 0.5, 1.0)) -> dict:
    T = np.eye(4)
    T[:3, 3] = center
    return {
        "identifier": "BED-1",
        "category": {"bed": {}},
        "confidence": {"high": {}},
        "attributes": {},
        "dimensions": list(dims),
        "transform": _col_major(T),
    }


def _room_json(objects=None) -> bytes:
    doc = {
        "version": 2,
        "walls": [],
        "floors": [_floor_entity()],
        "doors": [],
        "windows": [],
        "openings": [],
        "objects": objects if objects is not None else [_bed_entity()],
    }
    return json.dumps(doc).encode()


# ---------------------------------------------------------------------------
# Bundle: 4 frames, identical cameras (all see the bed box footprint)
# ---------------------------------------------------------------------------

def _make_bundle(frame_count: int = 4, roomplan: bool = True) -> CaptureBundle:
    b = CaptureBundle()
    b.schema_version = SCHEMA_VERSION
    b.bundle_id = "censustest"
    b.user_id = "user-1"
    b.device.hardware_id = "device-census"
    b.tier = LIDAR_ROOMPLAN
    if roomplan:
        b.room_plan.json_gcs_path = "roomplan/room.json"
        b.room_plan.roomplan_version = "test;CapturedRoom.v2;beautifyObjects"
    now = int(_time.monotonic_ns() // 1_000)
    b.started_at_device_us = now
    b.ended_at_device_us = now + frame_count * 500_000
    b.started_at_wall_us = int(_time.time_ns() // 1_000)
    for i in range(frame_count):
        f = b.frames.add()
        f.frame_index = i
        f.timestamp_us = now + i * 500_000
        f.rgb_gcs_path = f"frames/{i:06d}.jpg"
        f.camera_pose.quat_w = 1.0  # identity pose at the origin
        f.intrinsics.fx = 60.0
        f.intrinsics.fy = 60.0
        f.intrinsics.cx = 32.0
        f.intrinsics.cy = 32.0
        f.intrinsics.width = 64
        f.intrinsics.height = 64
        f.gravity.y = -1.0
    return b


def _bed_mask() -> np.ndarray:
    """The bed box's projected footprint under the identity camera —
    guaranteed to associate."""
    room = parse_captured_room(_room_json())
    box = room.objects[0]
    b = _make_bundle(1)
    f = b.frames[0]
    hull, _ = box_placement.project_box_footprint(box, f.intrinsics, f.camera_pose)
    ys, xs = np.mgrid[0:64, 0:64]
    pts = np.column_stack([xs.ravel() + 0.5, ys.ravel() + 0.5]).astype(float)
    return box_placement._points_in_hull(pts, hull).reshape(64, 64)


def _lamp_mask() -> np.ndarray:
    m = np.zeros((64, 64), dtype=bool)
    m[2:8, 56:63] = True
    return m


def _detections() -> list[dict]:
    return [
        {"label": "bed", "instance_idx": 0, "bbox": [10, 10, 50, 50],
         "score": 0.9, "mask": _bed_mask()},
        {"label": "lamp", "instance_idx": 0, "bbox": [56, 2, 63, 8],
         "score": 0.7, "mask": _lamp_mask()},
    ]


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------

class _FakeTensor:
    def __init__(self, value):
        self._v = np.asarray(value, dtype=np.float64)

    def detach(self):
        return self

    def cpu(self):
        return self

    def numpy(self):
        return self._v


class _FakeGS:
    def save_ply(self, path):
        Path(path).write_text(_MINI_PLY)


def _fake_result() -> dict:
    return {
        "rotation": _FakeTensor([1.0, 0.0, 0.0, 0.0]),
        "translation": _FakeTensor([0.0, 0.0, 1.0]),
        "scale": _FakeTensor([1.0, 1.0, 1.0]),
        "gs": _FakeGS(),
    }


class _FakeSam3:
    def __init__(self):
        self.calls = 0

    def segment(self, pil, prompt):
        self.calls += 1
        return _detections()


class _FakeSam3D:
    def __init__(self):
        self.calls = 0

    def reconstruct(self, pil, mask, seed=42):
        self.calls += 1
        return _fake_result()


class _FakeBudget:
    def __init__(self, object_admits=None):
        self._object = None if object_admits is None else list(object_admits)

    def can_start_frame(self) -> bool:
        return True

    def can_start_object(self) -> bool:
        if self._object is None:
            return True
        return self._object.pop(0) if self._object else False

    def note_frame(self, s):
        pass

    def note_object(self, s):
        pass

    def remaining(self):
        return 999.0

    def snapshot(self):
        return {"fake": True}


class FakeGcs:
    """Dict-backed GCS covering all three receiver seams (stateful — cache
    reads must see prior uploads)."""

    def __init__(self, bundle: CaptureBundle, room_json: bytes | None):
        self.blobs: dict[str, bytes] = {
            "captures-bucket/captures/censustest/bundle.pb": bundle.SerializeToString(),
        }
        for f in bundle.frames:
            self.blobs[f"captures-bucket/captures/censustest/{f.rgb_gcs_path}"] = _JPEG
        if room_json is not None:
            self.blobs["captures-bucket/captures/censustest/roomplan/room.json"] = room_json

    def download(self, uri: str) -> bytes:
        key = uri[5:]
        if key not in self.blobs:
            raise process_receiver.PoisonError(f"GCS object not found: {uri}")
        return self.blobs[key]

    def exists_and_get(self, bucket: str, path: str):
        return self.blobs.get(f"{bucket}/{path}")

    def upload(self, prefix: str, blob: str, data: bytes, content_type: str) -> str:
        bucket = prefix[5:].split("/")[0]
        self.blobs[f"{bucket}/{blob}"] = data
        return f"gs://{bucket}/{blob}"


def _run(gcs: FakeGcs, *, budget=None, sam3=None, sam3d=None):
    sam3 = sam3 or _FakeSam3()
    sam3d = sam3d or _FakeSam3D()
    with patch.object(process_receiver, "_download_gcs_uri", gcs.download), \
         patch.object(process_receiver, "_gcs_blob_exists_and_get", gcs.exists_and_get), \
         patch.object(process_receiver, "_gcs_upload_for_scene", gcs.upload):
        uri = run_perception(
            scene_id=_SCENE,
            bundle_uri=_BUNDLE_URI,
            outputs_bucket=_OUT,
            sam3_model=sam3,
            sam3d_model=sam3d,
            object_prompt="bed,lamp",
            budget=budget,
        )
    return uri, sam3, sam3d


def _manifest(gcs: FakeGcs) -> dict:
    return json.loads(gcs.blobs[f"{_OUT}/scenes/{_SCENE}/manifest.json"])


# ---------------------------------------------------------------------------
# Per-object reconstruction (the starvation-class fix)
# ---------------------------------------------------------------------------

class TestPerObjectReconstruction:
    def test_reconstruct_count_is_plan_size_not_mask_count(self):
        """4 frames x 2 masks = 8 legacy reconstructions. Two-pass: the bed
        box takes best + second view (2), the other two bed views are
        policy-skipped, the 4 lamp masks are long tail — 6 total."""
        gcs = FakeGcs(_make_bundle(), _room_json())
        _uri, sam3, sam3d = _run(gcs)
        assert sam3.calls == 4  # one segmentation per frame
        assert sam3d.calls == 6
        man = _manifest(gcs)
        plan = man["sampling"]["census"]["plan"]
        assert plan["box_best_views"] == 1
        assert plan["box_second_views"] == 1
        assert plan["long_tail"] == 4
        assert plan["policy_skipped"] == 2

    def test_policy_skips_are_cached_with_reason(self):
        gcs = FakeGcs(_make_bundle(), _room_json())
        _run(gcs)
        skipped = []
        for i in range(4):
            blob = gcs.blobs.get(f"{_OUT}/scenes/{_SCENE}/frames/{i:04d}/objects.json")
            assert blob is not None  # every frame finalized + cached
            doc = json.loads(blob)
            for o in doc["objects"]:
                if o.get("skipped_reason"):
                    assert o["ok"] is False
                    assert o["skipped_reason"] == "box_covered_by_other_view"
                    skipped.append((doc["frame_index"], o["mask_index"]))
        assert len(skipped) == 2

    def test_masks_npz_written_per_frame(self):
        gcs = FakeGcs(_make_bundle(), _room_json())
        _run(gcs)
        for i in range(4):
            raw = gcs.blobs[f"{_OUT}/scenes/{_SCENE}/frames/{i:04d}/masks.npz"]
            with np.load(io.BytesIO(raw)) as npz:
                assert npz["masks"].shape[0] == 2

    def test_manifest_census_metadata(self):
        gcs = FakeGcs(_make_bundle(), _room_json())
        _run(gcs)
        man = _manifest(gcs)
        assert man["sampling"]["policy"] == "census_set_cover_v1"
        assert man["roomplan"]["present"] is True
        assert man["roomplan"]["parse_ok"] is True
        assert man["roomplan"]["object_count"] == 1
        census = man["sampling"]["census"]
        assert census["box_coverage"]["box_00"]
        # The box object itself came out of fusion.
        box_objs = [o for o in man["objects"] if o.get("roomplan_box")]
        assert len(box_objs) == 1
        assert box_objs[0]["placed"] is True
        assert box_objs[0]["method"] == "roomplan_box"

    def test_room_json_cached_to_outputs(self):
        gcs = FakeGcs(_make_bundle(), _room_json())
        _run(gcs)
        assert f"{_OUT}/scenes/{_SCENE}/roomplan/room.json" in gcs.blobs


# ---------------------------------------------------------------------------
# Budget guarantee
# ---------------------------------------------------------------------------

class TestBudget:
    def test_budget_cut_frame_never_cached(self):
        """Admissions: 4 segmentations + 4 reconstructions (bed best f0,
        bed second f1, lamp f0, lamp f1), then refusal at lamp f2. Frames
        0/1 completed their planned masks and cache; frames 2/3 carry a
        cut planned mask — recorded budget_stopped, never cached."""
        gcs = FakeGcs(_make_bundle(), _room_json())
        budget = _FakeBudget(object_admits=[True] * 4 + [True] * 4 + [False] * 10)
        _uri, _s3, sam3d = _run(gcs, budget=budget)
        assert sam3d.calls == 4
        man = _manifest(gcs)
        assert man["sampling"]["budget_stopped"] is True
        cached = sorted(
            i for i in range(4)
            if f"{_OUT}/scenes/{_SCENE}/frames/{i:04d}/objects.json" in gcs.blobs
        )
        stopped = sorted(
            fr["frame_index"] for fr in man["frames"] if fr.get("budget_stopped")
        )
        assert cached == [0, 1]
        assert stopped == [2, 3]

    def test_budget_cut_then_warm_retry_completes(self):
        """The 0062 retry law end-to-end: after a cut, a warm retry reuses
        the cached frames verbatim and the per-object splat caches, and
        finishes the scene."""
        gcs = FakeGcs(_make_bundle(), _room_json())
        budget = _FakeBudget(object_admits=[True] * 4 + [True] * 4 + [False] * 10)
        _run(gcs, budget=budget)
        first_manifest = gcs.blobs[f"{_OUT}/scenes/{_SCENE}/manifest.json"]
        sam3d_2 = _FakeSam3D()
        _run(gcs, sam3d=sam3d_2)  # unlimited budget
        assert sam3d_2.calls == 2  # only the two cut lamps; the rest cached
        man = _manifest(gcs)
        assert man["sampling"]["budget_stopped"] is False
        assert gcs.blobs[f"{_OUT}/scenes/{_SCENE}/manifest.json"] != first_manifest
        for i in range(4):
            assert f"{_OUT}/scenes/{_SCENE}/frames/{i:04d}/objects.json" in gcs.blobs

    def test_zero_admissions_raises_environmental(self):
        gcs = FakeGcs(_make_bundle(), _room_json())
        budget = _FakeBudget(object_admits=[False] * 20)
        with pytest.raises(process_receiver.EnvironmentalError):
            _run(gcs, budget=budget)


# ---------------------------------------------------------------------------
# Determinism + caching
# ---------------------------------------------------------------------------

class TestDeterminismAndCache:
    def test_two_clean_runs_identical_manifest(self):
        g1 = FakeGcs(_make_bundle(), _room_json())
        _run(g1)
        g2 = FakeGcs(_make_bundle(), _room_json())
        _run(g2)
        assert (
            g1.blobs[f"{_OUT}/scenes/{_SCENE}/manifest.json"]
            == g2.blobs[f"{_OUT}/scenes/{_SCENE}/manifest.json"]
        )

    def test_whole_frame_cache_hit_skips_segmentation(self):
        gcs = FakeGcs(_make_bundle(), _room_json())
        _run(gcs)
        sam3_2 = _FakeSam3()
        sam3d_2 = _FakeSam3D()
        _run(gcs, sam3=sam3_2, sam3d=sam3d_2)
        assert sam3_2.calls == 0
        assert sam3d_2.calls == 0


# ---------------------------------------------------------------------------
# Dispatch degrade locks
# ---------------------------------------------------------------------------

class TestDispatch:
    def test_no_roomplan_keeps_legacy_policy(self):
        gcs = FakeGcs(_make_bundle(roomplan=False), None)
        _uri, sam3, sam3d = _run(gcs)
        man = _manifest(gcs)
        assert man["sampling"]["policy"] == "pose_diverse_fps_v1"
        assert "census" not in man["sampling"]
        assert "roomplan" not in man
        assert sam3d.calls == 8  # every mask reconstructed, the legacy way

    def test_missing_room_json_degrades_to_legacy_selection(self):
        bundle = _make_bundle(roomplan=True)
        gcs = FakeGcs(bundle, None)  # claims roomplan; blob absent
        _uri, _sam3, sam3d = _run(gcs)
        man = _manifest(gcs)
        assert man["sampling"]["policy"] == "pose_diverse_fps_v1"
        assert man["roomplan"]["present"] is True
        assert man["roomplan"]["parse_ok"] is False
        assert man["roomplan"]["parse_failed"] == "room_json_missing"
        assert sam3d.calls == 8


# ---------------------------------------------------------------------------
# Privacy suppression through the census path (decision 0089)
# ---------------------------------------------------------------------------

class _PersonMask:
    @staticmethod
    def mask() -> np.ndarray:
        m = np.zeros((64, 64), dtype=bool)
        m[20:44, 4:20] = True
        return m


class _FakeSam3WithPerson:
    """Segmentation as it looks once 'person' is in the prompt: a person
    detected between the two real objects."""

    def __init__(self):
        self.calls = 0
        self.prompts: list[str] = []

    def segment(self, pil, prompt):
        self.calls += 1
        self.prompts.append(prompt)
        bed, lamp = _detections()
        return [
            bed,
            {"label": "person", "instance_idx": 0, "bbox": [4, 20, 20, 44],
             "score": 0.85, "mask": _PersonMask.mask()},
            lamp,
        ]


class TestPrivacySuppression:
    """The census two-pass path must partition suppressed detections out
    before the plan is built — a person that survived into the plan would be
    reconstructed, box-associated, and inventoried."""

    def test_person_never_reaches_the_manifest_or_sam3d(self):
        gcs = FakeGcs(_make_bundle(), _room_json())
        sam3 = _FakeSam3WithPerson()
        sam3d = _FakeSam3D()

        _uri, _s3, _s3d = _run(gcs, sam3=sam3, sam3d=sam3d)

        assert "person" in sam3.prompts[0]  # it WAS segmented
        man = _manifest(gcs)
        # Scanned as text: a leak into ANY manifest field is a leak into
        # api-public's scene_facts, whose world is this document.
        assert "person" not in json.dumps(man).lower()
        assert all("person" not in str(o.get("label", "")) for o in man["objects"])
        # Reconstruction count is unchanged from the person-free run: the
        # suppressed mask never entered the plan.
        assert sam3d.calls == 6

    def test_suppressed_union_lands_in_masks_npz_for_the_shell(self):
        gcs = FakeGcs(_make_bundle(), _room_json())
        _run(gcs, sam3=_FakeSam3WithPerson())

        raw = gcs.blobs[f"{_OUT}/scenes/{_SCENE}/frames/0000/masks.npz"]
        with np.load(io.BytesIO(raw)) as npz:
            assert npz["masks"].shape[0] == 2  # bed + lamp, person absent
            union = npz["suppressed"]
        assert np.array_equal(union, _PersonMask.mask())
