"""Envelope tests for the perception receiver: frame sampling wiring, the
person's boxes, and budget cutoff behaviour.

These drive run_perception/_process_frame with fake models and patched GCS,
pinning the invariants the 2026-07-21 real capture (scene 25a14caf) proved
necessary, now that nothing is reconstructed (decision 0323):

  * only the sampled subset of a large bundle is segmented, and the manifest
    records the sampling (frames_total / frames_sampled / sampling);
  * the boxes the person made are written as boxes.json (even when there are
    none), pick the frames, and are the only object source: the manifest
    carries no objects;
  * when the budget refuses another frame, the run ships what's banked
    instead of computing past the request window;
  * if no frame completed, the attempt raises EnvironmentalError (Cloud Tasks
    retry, warm models) instead of shipping an empty scene.

Run from repo root:
  pytest services/perception-obj/tests/test_envelope.py -v
"""
from __future__ import annotations

import io
import json
import math
import sys
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

import process_receiver  # noqa: E402
from process_receiver import EnvironmentalError, run_perception  # noqa: E402
from thegoodguest_schemas import ARKIT_ONLY, SCHEMA_VERSION, CaptureBundle  # noqa: E402

_SCENE_ID = "scene-envelope-001"
_BUNDLE_URI = "gs://bucket/captures/envtest/bundle.pb"
_OUT = "outputs-bucket"


def _tiny_jpeg() -> bytes:
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (32, 24), (120, 90, 60)).save(buf, format="JPEG")
    return buf.getvalue()


_JPEG = _tiny_jpeg()


def _make_bundle_bytes(frame_count: int, boxes: tuple = ()) -> bytes:
    """Valid ARKIT_ONLY bundle with pose diversity (arc walk + pan), carrying
    the given person boxes: dicts of box_id / label / center / size."""
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
        f.intrinsics.fx = 24.0  # a wide view of this tiny frame, so a box 2 m away fits
        f.intrinsics.fy = 24.0
        f.intrinsics.cx = 16.0
        f.intrinsics.cy = 12.0
        f.intrinsics.width = 32
        f.intrinsics.height = 24
        f.gravity.y = -1.0
    for n, spec in enumerate(boxes):
        pb = b.person_boxes.add()
        pb.box_id = spec["box_id"]
        pb.detector_label = spec.get("label", "chair")
        pb.center_x, pb.center_y, pb.center_z = spec["center"]
        pb.size_x, pb.size_y, pb.size_z = spec.get("size", (0.5, 0.9, 0.5))
        pb.created_at_device_us = n
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


class _FakeSam3:
    def __init__(self, detections_per_frame):
        self.calls = 0
        self._dets = detections_per_frame

    def segment(self, pil, prompt):
        self.calls += 1
        return [dict(d) for d in self._dets]


class _FakeBudget:
    """Duck-typed budget seam: scripted admissions, recorded observations.

    BudgetTracker's arithmetic is pinned in test_budget.py; these tests pin
    run_perception's CONTRACT with whatever tracker it is given.
    """

    def __init__(self, frame_admits=None):
        self._frame = None if frame_admits is None else list(frame_admits)
        self.noted_frames: list[float] = []

    def can_start_frame(self) -> bool:
        if self._frame is None:
            return True
        return self._frame.pop(0) if self._frame else False

    def note_frame(self, s):
        self.noted_frames.append(s)

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

def _run(bundle_bytes, uploads, **kw):
    sam3 = kw.pop("sam3", None) or _FakeSam3([_detection(0)])
    with ExitStack() as stack:
        _gcs_patches(stack, bundle_bytes, uploads)
        uri = run_perception(
            scene_id=_SCENE_ID, bundle_uri=_BUNDLE_URI, outputs_bucket=_OUT,
            sam3_model=sam3, object_prompt="chair", **kw,
        )
    return uri, sam3


class TestSamplingWiring:
    def test_only_sampled_frames_processed(self):
        uploads: list = []
        uri, sam3 = _run(_make_bundle_bytes(30), uploads, max_frames=4)
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
        _, sam3 = _run(_make_bundle_bytes(2), uploads)
        assert sam3.calls == 2
        m = _manifest_from(uploads)
        assert m["frames_total"] == 2
        assert m["frames_sampled"] == 2
        assert m["sampling"]["budget_stopped"] is False

    def test_each_frame_banks_its_masks_for_the_shell(self):
        uploads: list = []
        _run(_make_bundle_bytes(2), uploads)
        blobs = [b for b, _ in uploads]
        assert sum(b.endswith("/masks.npz") for b in blobs) == 2
        m = _manifest_from(uploads)
        assert all(fr["masks_gcs_uri"].endswith("/masks.npz") and fr["mask_count"] == 1
                   for fr in m["frames"])


# ---------------------------------------------------------------------------
# The person's boxes, and no reconstruction (decisions 0322, 0323)
# ---------------------------------------------------------------------------

def _boxes_from(uploads) -> dict:
    bodies = [d for (b, d) in uploads if b == f"scenes/{_SCENE_ID}/boxes.json"]
    assert len(bodies) == 1, "boxes.json is written exactly once per run"
    return json.loads(bodies[0])


class TestPersonBoxes:
    BOX = {"box_id": "box-1", "label": "dining table", "center": (0.3, 0.0, -2.0), "size": (1.2, 0.8, 0.6)}

    def test_the_bundles_boxes_are_written_as_boxes_json(self):
        uploads: list = []
        _run(_make_bundle_bytes(3, boxes=(self.BOX,)), uploads)
        doc = _boxes_from(uploads)
        assert doc["scene_id"] == _SCENE_ID and doc["source"] == "person"
        assert [(b["id"], b["label"]) for b in doc["boxes"]] == [("box-1", "dining table")]

    def test_a_bundle_without_boxes_still_writes_an_empty_boxes_json(self):
        uploads: list = []
        _run(_make_bundle_bytes(3), uploads)
        assert _boxes_from(uploads)["boxes"] == []

    def test_boxes_json_is_written_before_any_frame_is_segmented(self):
        uploads: list = []
        _run(_make_bundle_bytes(3, boxes=(self.BOX,)), uploads)
        blobs = [b for b, _ in uploads]
        assert blobs.index(f"scenes/{_SCENE_ID}/boxes.json") < blobs.index(f"scenes/{_SCENE_ID}/manifest.json")
        assert blobs.index(f"scenes/{_SCENE_ID}/boxes.json") == 0

    def test_a_rerun_writes_identical_boxes_bytes(self):
        first: list = []
        second: list = []
        bundle = _make_bundle_bytes(3, boxes=(self.BOX,))
        _run(bundle, first)
        _run(bundle, second)
        pick = lambda ups: [d for b, d in ups if b.endswith("/boxes.json")]  # noqa: E731
        assert pick(first) == pick(second)

    def test_boxes_choose_the_frames_by_census_cover(self):
        uploads: list = []
        # A box in view of the first poses (the camera looks down world -Z).
        _run(_make_bundle_bytes(30, boxes=(self.BOX,)), uploads, max_frames=4)
        m = _manifest_from(uploads)
        assert m["sampling"]["policy"] == "census_set_cover_v1"
        assert "census" in m["sampling"] and m["sampling"]["census"]["cover_frame_indices"]

    def test_nothing_is_reconstructed_the_manifest_has_no_objects(self):
        uploads: list = []
        _run(_make_bundle_bytes(3, boxes=(self.BOX,)), uploads)
        m = _manifest_from(uploads)
        assert m["objects"] == []
        assert all("objects" not in fr for fr in m["frames"])
        assert not any("/splats/" in b for b, _ in uploads)


# ---------------------------------------------------------------------------
# Budget cutoff
# ---------------------------------------------------------------------------

class TestBudgetCutoff:
    def test_stops_between_frames_and_ships_banked(self):
        uploads: list = []
        budget = _FakeBudget(frame_admits=[True, True, True])  # then False
        uri, sam3 = _run(_make_bundle_bytes(12), uploads, max_frames=6, budget=budget)
        assert uri.endswith("manifest.json")
        assert sam3.calls == 3
        m = _manifest_from(uploads)
        assert m["frames_sampled"] == 6
        assert len(m["frames"]) == 3
        assert m["sampling"]["budget_stopped"] is True
        assert m["sampling"]["frames_processed"] == 3
        assert len(budget.noted_frames) == 3

    def test_zero_complete_frames_is_environmental(self):
        uploads: list = []
        with pytest.raises(EnvironmentalError):
            _run(_make_bundle_bytes(5), uploads, budget=_FakeBudget(frame_admits=[]))
        assert not any(b.endswith("manifest.json") for b, _ in uploads)
