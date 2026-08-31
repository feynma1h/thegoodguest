"""Envelope tests for the perception receiver: frame sampling wiring, budget
cutoff behaviour, and the GPU-memory lifecycle.

These drive run_perception/_process_frame with fake models and patched GCS,
pinning the invariants the 2026-07-21 real capture (scene 25a14caf) proved
necessary:

  * only the sampled subset of a large bundle is reconstructed, and the
    manifest records the sampling (frames_total / frames_sampled / sampling);
  * when the budget refuses another frame (or object, mid-frame), the run
    ships what's banked instead of computing past the request window —
    and a budget-stopped frame is never cached to GCS;
  * if no frame completed in full, the attempt raises EnvironmentalError
    (Cloud Tasks retry, warm models) instead of shipping an empty scene;
  * nothing from a SAM 3D result dict (device tensors) survives into the
    accumulated frame result — the leak class behind the OOM cascade;
  * the single reconstruct retry happens and can succeed.

Run from repo root:
  pytest services/perception-obj/tests/test_envelope.py -v
"""
from __future__ import annotations

import gc
import io
import json
import math
import sys
import weakref
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

_schemas_path = Path(__file__).resolve().parents[3] / "packages/schemas"
if str(_schemas_path) not in sys.path:
    sys.path.insert(0, str(_schemas_path))

# Stub heavy deps that aren't installed in the test venv (same preamble as
# test_process_receiver.py; setdefault keeps whichever file loaded first).
sys.modules.setdefault("torch", MagicMock())
sys.modules.setdefault("models", MagicMock())
sys.modules.setdefault("models.sam3", MagicMock())
sys.modules.setdefault("models.sam3d", MagicMock())

import process_receiver  # noqa: E402
from process_receiver import (  # noqa: E402
    EnvironmentalError,
    _process_frame,
    run_perception,
)
from thegoodguest_schemas import ARKIT_ONLY, SCHEMA_VERSION, CaptureBundle  # noqa: E402

_SCENE_ID = "scene-envelope-001"
_BUNDLE_URI = "gs://bucket/captures/envtest/bundle.pb"
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
    Image.new("RGB", (32, 24), (120, 90, 60)).save(buf, format="JPEG")
    return buf.getvalue()


_JPEG = _tiny_jpeg()


def _make_bundle_bytes(frame_count: int) -> bytes:
    """Valid ARKIT_ONLY bundle with pose diversity (arc walk + pan)."""
    import time as _time

    b = CaptureBundle()
    b.schema_version = SCHEMA_VERSION
    b.bundle_id = "envtest"
    b.user_id = "user-1"
    b.device.hardware_id = "device-env"
    b.tier = ARKIT_ONLY
    now = int(_time.monotonic_ns() // 1_000)
    b.started_at_device_us = now
    b.ended_at_device_us = now + frame_count * 500_000
    b.started_at_wall_us = int(_time.time_ns() // 1_000)
    for i in range(frame_count):
        f = b.frames.add()
        f.frame_index = i
        f.timestamp_us = now + i * 500_000
        f.rgb_gcs_path = f"frames/{i:06d}.jpg"
        f.camera_pose.pos_x = 0.15 * i
        f.camera_pose.pos_z = 0.05 * i
        half = math.radians(3.0 * i) / 2.0
        f.camera_pose.quat_y = math.sin(half)
        f.camera_pose.quat_w = math.cos(half)
        f.intrinsics.fx = 800.0
        f.intrinsics.fy = 800.0
        f.intrinsics.cx = 16.0
        f.intrinsics.cy = 12.0
        f.intrinsics.width = 32
        f.intrinsics.height = 24
        f.gravity.y = -1.0
    return b.SerializeToString()


def _detection(i: int = 0, label: str = "chair") -> dict:
    mask = np.zeros((24, 32), dtype=bool)
    mask[8:16, 10 + i : 18 + i] = True
    return {
        "label": label,
        "instance_idx": i,
        "bbox": [10.0 + i, 8.0, 18.0 + i, 16.0],
        "score": 0.9 - 0.05 * i,
        "mask": mask,
    }


class _FakeTensor:
    """Device-tensor stand-in: satisfies placement's duck-typed conversion."""

    def __init__(self, value):
        self._v = np.asarray(value, dtype=np.float64)

    def detach(self):
        return self

    def cpu(self):
        return self

    def numpy(self):
        return self._v


class _FakeGS:
    def __init__(self):
        self.payload = bytearray(256)  # give the object a body worth leaking

    def save_ply(self, path):
        Path(path).write_text(_MINI_PLY)


def _fake_result() -> dict:
    return {
        "rotation": _FakeTensor([1.0, 0.0, 0.0, 0.0]),  # wxyz identity
        "translation": _FakeTensor([0.0, 0.0, 1.0]),
        "scale": _FakeTensor([1.0, 1.0, 1.0]),
        "coords": _FakeTensor(np.zeros((16, 3))),
        "gs": _FakeGS(),
    }


class _FakeSam3:
    def __init__(self, detections_per_frame):
        self.calls = 0
        self._dets = detections_per_frame

    def segment(self, pil, prompt):
        self.calls += 1
        return [dict(d) for d in self._dets]


class _FakeSam3D:
    def __init__(self, factory=_fake_result):
        self.calls = 0
        self._factory = factory

    def reconstruct(self, pil, mask, seed=42):
        self.calls += 1
        return self._factory()


class _FakeBudget:
    """Duck-typed budget seam: scripted admissions, recorded observations.

    BudgetTracker's arithmetic is pinned in test_budget.py; these tests pin
    run_perception's CONTRACT with whatever tracker it is given.
    """

    def __init__(self, frame_admits=None, object_admits=None):
        self._frame = None if frame_admits is None else list(frame_admits)
        self._object = None if object_admits is None else list(object_admits)
        self.noted_frames: list[float] = []
        self.noted_objects: list[float] = []

    def can_start_frame(self) -> bool:
        if self._frame is None:
            return True
        return self._frame.pop(0) if self._frame else False

    def can_start_object(self) -> bool:
        if self._object is None:
            return True
        return self._object.pop(0) if self._object else False

    def note_frame(self, s):
        self.noted_frames.append(s)

    def note_object(self, s):
        self.noted_objects.append(s)

    def remaining(self):
        return 999.0

    def snapshot(self):
        return {"fake": True}


def _gcs_patches(stack: ExitStack, bundle_bytes: bytes, uploads: list):
    """Patch the receiver's GCS seams: bundle + JPEG downloads, recorded
    uploads, empty cache."""

    def _download(uri):
        if uri.endswith("bundle.pb"):
            return bundle_bytes
        return _JPEG

    def _upload(prefix, blob, data, content_type):
        uploads.append((blob, data))
        return f"gs://{_OUT}/{blob}"

    stack.enter_context(
        patch.object(process_receiver, "_download_gcs_uri", side_effect=_download)
    )
    stack.enter_context(
        patch.object(process_receiver, "_gcs_upload_for_scene", side_effect=_upload)
    )
    stack.enter_context(
        patch.object(process_receiver, "_gcs_blob_exists_and_get", return_value=None)
    )


def _manifest_from(uploads) -> dict:
    bodies = [d for (b, d) in uploads if b.endswith("manifest.json")]
    assert bodies, f"no manifest upload in {[b for b, _ in uploads]}"
    return json.loads(bodies[-1])


# ---------------------------------------------------------------------------
# Sampling wiring
# ---------------------------------------------------------------------------

class TestSamplingWiring:
    def test_only_sampled_frames_processed(self):
        uploads: list = []
        sam3 = _FakeSam3([_detection(0)])
        sam3d = _FakeSam3D()
        with ExitStack() as stack:
            _gcs_patches(stack, _make_bundle_bytes(30), uploads)
            uri = run_perception(
                scene_id=_SCENE_ID,
                bundle_uri=_BUNDLE_URI,
                outputs_bucket=_OUT,
                sam3_model=sam3,
                sam3d_model=sam3d,
                object_prompt="chair",
                max_frames=4,
            )
        assert uri.endswith("manifest.json")
        assert sam3.calls == 4, "exactly the sampled frames must be segmented"
        m = _manifest_from(uploads)
        assert m["frames_total"] == 30
        assert m["frames_sampled"] == 4
        assert m["frame_count"] == 30  # unchanged semantics: bundle total
        assert len(m["frames"]) == 4
        s = m["sampling"]
        assert s["policy"] == "pose_diverse_fps_v1"
        assert s["max_frames"] == 4
        assert s["budget_stopped"] is False
        assert s["frames_processed"] == 4
        assert sorted(s["selected_frame_indices"]) == s["selected_frame_indices"]
        assert len(set(s["selected_frame_indices"])) == 4
        processed = [fr["frame_index"] for fr in m["frames"]]
        assert processed == s["selected_frame_indices"]

    def test_small_bundle_processes_all_frames(self):
        uploads: list = []
        sam3 = _FakeSam3([_detection(0)])
        with ExitStack() as stack:
            _gcs_patches(stack, _make_bundle_bytes(2), uploads)
            run_perception(
                scene_id=_SCENE_ID,
                bundle_uri=_BUNDLE_URI,
                outputs_bucket=_OUT,
                sam3_model=sam3,
                sam3d_model=_FakeSam3D(),
                object_prompt="chair",
            )
        assert sam3.calls == 2
        m = _manifest_from(uploads)
        assert m["frames_total"] == 2
        assert m["frames_sampled"] == 2
        assert m["sampling"]["budget_stopped"] is False


# ---------------------------------------------------------------------------
# Budget cutoff
# ---------------------------------------------------------------------------

class TestBudgetCutoff:
    def test_stops_between_frames_and_ships_banked(self):
        uploads: list = []
        sam3 = _FakeSam3([_detection(0)])
        budget = _FakeBudget(frame_admits=[True, True, True])  # then False
        with ExitStack() as stack:
            _gcs_patches(stack, _make_bundle_bytes(12), uploads)
            uri = run_perception(
                scene_id=_SCENE_ID,
                bundle_uri=_BUNDLE_URI,
                outputs_bucket=_OUT,
                sam3_model=sam3,
                sam3d_model=_FakeSam3D(),
                object_prompt="chair",
                max_frames=6,
                budget=budget,
            )
        assert uri.endswith("manifest.json")
        assert sam3.calls == 3
        m = _manifest_from(uploads)
        assert m["frames_sampled"] == 6
        assert len(m["frames"]) == 3
        assert m["sampling"]["budget_stopped"] is True
        assert m["sampling"]["frames_processed"] == 3
        assert len(budget.noted_frames) == 3
        # Banked frames still fuse into scene objects.
        assert isinstance(m["objects"], list)

    def test_zero_complete_frames_is_environmental(self):
        uploads: list = []
        budget = _FakeBudget(frame_admits=[])  # refuses immediately
        with ExitStack() as stack:
            _gcs_patches(stack, _make_bundle_bytes(5), uploads)
            with pytest.raises(EnvironmentalError):
                run_perception(
                    scene_id=_SCENE_ID,
                    bundle_uri=_BUNDLE_URI,
                    outputs_bucket=_OUT,
                    sam3_model=_FakeSam3([_detection(0)]),
                    sam3d_model=_FakeSam3D(),
                    object_prompt="chair",
                    budget=budget,
                )
        assert not any(b.endswith("manifest.json") for b, _ in uploads)

    def test_only_partial_frames_is_environmental(self):
        """A lone mid-frame-stopped frame is not a shippable scene."""
        uploads: list = []
        budget = _FakeBudget(frame_admits=[True], object_admits=[True])
        # second object refused -> partial frame; no more frames admitted
        with ExitStack() as stack:
            _gcs_patches(stack, _make_bundle_bytes(1), uploads)
            with pytest.raises(EnvironmentalError):
                run_perception(
                    scene_id=_SCENE_ID,
                    bundle_uri=_BUNDLE_URI,
                    outputs_bucket=_OUT,
                    sam3_model=_FakeSam3([_detection(0), _detection(1)]),
                    sam3d_model=_FakeSam3D(),
                    object_prompt="chair",
                    budget=budget,
                )

    def test_midframe_stop_banks_partial_after_complete_frame(self):
        uploads: list = []
        # Frame 1: 2 objects admitted (completes). Frame 2: first object
        # refused -> partial with 0 objects. Then the loop stops.
        budget = _FakeBudget(
            frame_admits=[True, True],
            object_admits=[True, True, False],
        )
        sam3 = _FakeSam3([_detection(0), _detection(1)])
        with ExitStack() as stack:
            _gcs_patches(stack, _make_bundle_bytes(2), uploads)
            uri = run_perception(
                scene_id=_SCENE_ID,
                bundle_uri=_BUNDLE_URI,
                outputs_bucket=_OUT,
                sam3_model=sam3,
                sam3d_model=_FakeSam3D(),
                object_prompt="chair",
                budget=budget,
            )
        assert uri.endswith("manifest.json")
        m = _manifest_from(uploads)
        assert m["sampling"]["budget_stopped"] is True
        assert len(m["frames"]) == 2
        complete, partial = m["frames"][0], m["frames"][1]
        assert "budget_stopped" not in complete
        assert partial["budget_stopped"] is True
        assert partial["objects"] == []
        # The partial frame must not be cached: exactly one objects.json and
        # one masks.npz upload (the complete frame's).
        assert sum(1 for b, _ in uploads if b.endswith("objects.json")) == 1
        assert sum(1 for b, _ in uploads if b.endswith("masks.npz")) == 1


# ---------------------------------------------------------------------------
# Mid-frame stop semantics at the _process_frame level
# ---------------------------------------------------------------------------

class TestProcessFrameBudget:
    def _frame_proto(self):
        b = CaptureBundle()
        b.ParseFromString(_make_bundle_bytes(1))
        return b.frames[0]

    def test_partial_frame_not_cached_and_flagged(self):
        uploads: list = []
        budget = _FakeBudget(object_admits=[True, False])
        with ExitStack() as stack:
            _gcs_patches(stack, b"", uploads)
            fr = _process_frame(
                scene_id=_SCENE_ID,
                frame_idx=0,
                rgb_gcs_uri="gs://bucket/captures/envtest/frames/000000.jpg",
                outputs_bucket=_OUT,
                sam3_model=_FakeSam3([_detection(0), _detection(1), _detection(2)]),
                sam3d_model=_FakeSam3D(),
                object_prompt="chair",
                frame=self._frame_proto(),
                bundle_prefix="gs://bucket/captures/envtest/",
                budget=budget,
            )
        assert fr["budget_stopped"] is True
        assert fr["masks_gcs_uri"] is None
        assert len(fr["objects"]) == 1  # the admitted object was banked
        assert fr["objects"][0]["ok"] is True
        blobs = [b for b, _ in uploads]
        assert not any(b.endswith("objects.json") for b in blobs)
        assert not any(b.endswith("masks.npz") for b in blobs)
        assert any(b.endswith(".ply") for b in blobs)  # completed splat kept

    def test_no_budget_processes_all_objects(self):
        uploads: list = []
        with ExitStack() as stack:
            _gcs_patches(stack, b"", uploads)
            fr = _process_frame(
                scene_id=_SCENE_ID,
                frame_idx=0,
                rgb_gcs_uri="gs://bucket/captures/envtest/frames/000000.jpg",
                outputs_bucket=_OUT,
                sam3_model=_FakeSam3([_detection(0), _detection(1)]),
                sam3d_model=_FakeSam3D(),
                object_prompt="chair",
                frame=self._frame_proto(),
                bundle_prefix="gs://bucket/captures/envtest/",
            )
        assert "budget_stopped" not in fr
        assert len(fr["objects"]) == 2


# ---------------------------------------------------------------------------
# Memory lifecycle
# ---------------------------------------------------------------------------

class TestMemoryLifecycle:
    def test_result_tensors_unreachable_after_frame(self):
        """Nothing from a reconstruct() result — device tensors, the GS
        object — may survive into the accumulated frame result. This is the
        leak class that saturated the GPU on scene 25a14caf."""
        refs: list[weakref.ref] = []

        def _tracked_result():
            r = _fake_result()
            refs.extend(weakref.ref(v) for v in r.values())
            return r

        uploads: list = []
        with ExitStack() as stack:
            _gcs_patches(stack, b"", uploads)
            b = CaptureBundle()
            b.ParseFromString(_make_bundle_bytes(1))
            fr = _process_frame(
                scene_id=_SCENE_ID,
                frame_idx=0,
                rgb_gcs_uri="gs://bucket/captures/envtest/frames/000000.jpg",
                outputs_bucket=_OUT,
                sam3_model=_FakeSam3([_detection(0), _detection(1)]),
                sam3d_model=_FakeSam3D(factory=_tracked_result),
                object_prompt="chair",
                frame=b.frames[0],
                bundle_prefix="gs://bucket/captures/envtest/",
            )
        assert len(refs) == 10  # 5 values x 2 objects
        gc.collect()
        alive = [r for r in refs if r() is not None]
        assert not alive, f"{len(alive)} device-side objects still reachable"
        # And the accumulated result is pure JSON.
        json.dumps(fr)

    def test_frame_result_json_serializable_via_run(self):
        uploads: list = []
        with ExitStack() as stack:
            _gcs_patches(stack, _make_bundle_bytes(3), uploads)
            run_perception(
                scene_id=_SCENE_ID,
                bundle_uri=_BUNDLE_URI,
                outputs_bucket=_OUT,
                sam3_model=_FakeSam3([_detection(0)]),
                sam3d_model=_FakeSam3D(),
                object_prompt="chair",
            )
        m = _manifest_from(uploads)  # json round-trip already proves it
        assert m["scene_id"] == _SCENE_ID


# ---------------------------------------------------------------------------
# Reconstruct retry
# ---------------------------------------------------------------------------

class TestReconstructRetry:
    def test_retry_after_first_failure_succeeds(self):
        calls = {"n": 0}

        class _FlakySam3D:
            def reconstruct(self, pil, mask, seed=42):
                calls["n"] += 1
                if calls["n"] == 1:
                    raise RuntimeError("CUDA out of memory (simulated)")
                return _fake_result()

        uploads: list = []
        with ExitStack() as stack:
            _gcs_patches(stack, b"", uploads)
            b = CaptureBundle()
            b.ParseFromString(_make_bundle_bytes(1))
            fr = _process_frame(
                scene_id=_SCENE_ID,
                frame_idx=0,
                rgb_gcs_uri="gs://bucket/captures/envtest/frames/000000.jpg",
                outputs_bucket=_OUT,
                sam3_model=_FakeSam3([_detection(0)]),
                sam3d_model=_FlakySam3D(),
                object_prompt="chair",
                frame=b.frames[0],
                bundle_prefix="gs://bucket/captures/envtest/",
            )
        assert calls["n"] == 2
        assert fr["objects"][0]["ok"] is True

    def test_both_attempts_failing_soft_fails_object(self):
        class _DeadSam3D:
            def reconstruct(self, pil, mask, seed=42):
                raise RuntimeError("CUDA out of memory (simulated)")

        uploads: list = []
        with ExitStack() as stack:
            _gcs_patches(stack, b"", uploads)
            b = CaptureBundle()
            b.ParseFromString(_make_bundle_bytes(1))
            fr = _process_frame(
                scene_id=_SCENE_ID,
                frame_idx=0,
                rgb_gcs_uri="gs://bucket/captures/envtest/frames/000000.jpg",
                outputs_bucket=_OUT,
                sam3_model=_FakeSam3([_detection(0), _detection(1)]),
                sam3d_model=_DeadSam3D(),
                object_prompt="chair",
                frame=b.frames[0],
                bundle_prefix="gs://bucket/captures/envtest/",
            )
        # Frame completes; both objects soft-failed with recorded errors.
        assert "budget_stopped" not in fr
        assert [o["ok"] for o in fr["objects"]] == [False, False]
        assert all("error" in o for o in fr["objects"])
