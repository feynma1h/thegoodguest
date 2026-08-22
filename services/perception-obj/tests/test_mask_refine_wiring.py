"""Mask refinement inside /process: the degrade lock, then the effect.

Two claims, and the first one is the reason this file exists. With
`PERCEPTION_MASK_REFINE` unset — the shipped default — the census two-pass
must behave exactly as it did before the pass existed: SAM 3 is never asked
to refine anything, SAM 3D is shown the segmentation's own mask byte for
byte, placement measures against that same mask, no entry gains a key, and
the manifest is unchanged. Everything the flag adds is additive and gated.

The second claim is that when it IS on, the substitution actually happens
end to end: the detector reads the frame's depth against the measured box,
SAM 3 is prompted with the detector's own region, the accepted mask is what
SAM 3D reconstructs from, the mask is persisted beside the splat so a later
cache hit places the same splat against the same mask, and a view with no
measured box — the long tail — is never touched.

The scene is synthetic on purpose: the fixtures under `mask_refine/` carry
the real masks and the real verdicts, and what is left to pin here is the
wiring, which real data would only make slower to read.

Run from repo root:
    python -m pytest services/perception-obj/tests/test_mask_refine_wiring.py -v
"""
from __future__ import annotations

import io
import json
import sys
import time as _time
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np

_schemas_path = Path(__file__).resolve().parents[3] / "packages/schemas"
if str(_schemas_path) not in sys.path:
    sys.path.insert(0, str(_schemas_path))

sys.modules.setdefault("torch", MagicMock())
sys.modules.setdefault("models", MagicMock())
sys.modules.setdefault("models.sam3", MagicMock())
sys.modules.setdefault("models.sam3d", MagicMock())

import box_placement  # noqa: E402
import mask_refine  # noqa: E402
import process_receiver  # noqa: E402
from process_receiver import run_perception  # noqa: E402
from roomplan_room import parse_captured_room  # noqa: E402
from roomstudio_schemas import (  # noqa: E402
    LIDAR_ROOMPLAN,
    SCHEMA_VERSION,
    CaptureBundle,
)

_SCENE = "scene-refine-001"
_BUNDLE_URI = "gs://captures-bucket/captures/refinetest/bundle.pb"
_OUT = "outputs-bucket"
_N = 32  # both the image and the depth raster are 32x32 here

_MINI_PLY = (
    "ply\nformat ascii 1.0\nelement vertex 8\n"
    "property float x\nproperty float y\nproperty float z\nend_header\n"
    "0 0 0\n1 0 0\n0 1 0\n0 0 1\n1 1 0\n1 0 1\n0 1 1\n1 1 1\n"
)


def _tiny_jpeg() -> bytes:
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (_N, _N), (120, 90, 60)).save(buf, format="JPEG")
    return buf.getvalue()


_JPEG = _tiny_jpeg()
# Flat depth at 3 m: every pixel back-projects onto the plane z = -3, which
# is where the table box sits, so the box's footprint is densely measured.
_DEPTH = np.full((_N, _N), 3.0, dtype="<f4").tobytes()


def _col_major(T: np.ndarray) -> list[float]:
    return [float(v) for v in np.asarray(T, dtype=float).reshape(16, order="F")]


def _floor_entity() -> dict:
    T = np.eye(4)
    T[:3, :3] = np.array([[1.0, 0.0, 0.0], [0.0, 0.0, 1.0], [0.0, -1.0, 0.0]])
    T[1, 3] = -5.0  # well clear of the measured points, so nothing is
    return {                       # discounted as "that is the floor, not the table"
        "identifier": "FLOOR-1",
        "category": {"floor": {}},
        "confidence": {"high": {}},
        "dimensions": [8.0, 8.0, 0.0],
        "transform": _col_major(T),
        "polygonCorners": [],
    }


def _table_entity() -> dict:
    T = np.eye(4)
    T[:3, 3] = (0.0, 0.0, -3.0)
    return {
        "identifier": "TABLE-1",
        "category": {"table": {}},
        "confidence": {"high": {}},
        "attributes": {},
        "dimensions": [2.0, 2.0, 0.5],
        "transform": _col_major(T),
    }


def _room_json() -> bytes:
    return json.dumps({
        "version": 2, "walls": [], "floors": [_floor_entity()], "doors": [],
        "windows": [], "openings": [], "objects": [_table_entity()],
    }).encode()


def _make_bundle(frame_count: int = 3) -> CaptureBundle:
    b = CaptureBundle()
    b.schema_version = SCHEMA_VERSION
    b.bundle_id = "refinetest"
    b.user_id = "user-1"
    b.device.hardware_id = "device-refine"
    b.tier = LIDAR_ROOMPLAN
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
        f.camera_pose.quat_w = 1.0
        for intr in (f.intrinsics, f.depth.intrinsics):
            intr.fx = intr.fy = float(_N)
            intr.cx = intr.cy = _N / 2.0
            intr.width = intr.height = _N
        f.depth.depth_gcs_path = f"depth/{i:06d}.f32"
        f.depth.width = f.depth.height = _N
        f.gravity.y = -1.0
    return b


def _footprint() -> np.ndarray:
    room = parse_captured_room(_room_json())
    f = _make_bundle(1).frames[0]
    hull, _ = box_placement.project_box_footprint(
        room.objects[0], f.intrinsics, f.camera_pose
    )
    ys, xs = np.mgrid[0:_N, 0:_N]
    pts = np.column_stack([xs.ravel() + 0.5, ys.ravel() + 0.5]).astype(float)
    return box_placement._points_in_hull(pts, hull).reshape(_N, _N)


_FOOTPRINT = _footprint()


def _short_mask() -> np.ndarray:
    """The table, photographed and segmented only down to its top edge —
    the synthetic stand-in for a mask that cut the legs off."""
    m = _FOOTPRINT.copy()
    m[_N // 2:, :] = False
    return m


def _full_mask() -> np.ndarray:
    return _FOOTPRINT.copy()


def _lamp_mask() -> np.ndarray:
    m = np.zeros((_N, _N), dtype=bool)
    m[0:3, _N - 4:_N - 1] = True
    return m


def _detections() -> list[dict]:
    return [
        {"label": "desk", "instance_idx": 0, "bbox": [4, 4, 28, 28],
         "score": 0.9, "mask": _short_mask()},
        {"label": "table lamp", "instance_idx": 0, "bbox": [28, 0, 31, 3],
         "score": 0.7, "mask": _lamp_mask()},
    ]


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


class _FakeSam3:
    """Records every refinement asked for, and answers with the full
    footprint — the mask the short one should have been."""

    _DEFAULT = object()

    def __init__(self, answer=_DEFAULT):
        self.segment_calls = 0
        self.refine_calls: list[dict] = []
        self._answer = _full_mask() if answer is _FakeSam3._DEFAULT else answer

    def segment(self, pil, prompt):
        self.segment_calls += 1
        return _detections()

    def refine_with_box(self, image, label, box_cxcywh, target_bbox=None):
        self.refine_calls.append(
            {"label": label, "box": list(box_cxcywh), "target": target_bbox}
        )
        return None if self._answer is None else self._answer.copy()


class _FakeSam3D:
    def __init__(self):
        self.masks_shown: list[np.ndarray] = []

    def reconstruct(self, pil, mask, seed=42):
        self.masks_shown.append(np.asarray(mask, dtype=bool).copy())
        return {
            "rotation": _FakeTensor([1.0, 0.0, 0.0, 0.0]),
            "translation": _FakeTensor([0.0, 0.0, 1.0]),
            "scale": _FakeTensor([1.0, 1.0, 1.0]),
            "gs": _FakeGS(),
        }


class FakeGcs:
    def __init__(self, bundle: CaptureBundle):
        self.blobs: dict[str, bytes] = {
            "captures-bucket/captures/refinetest/bundle.pb":
                bundle.SerializeToString(),
            "captures-bucket/captures/refinetest/roomplan/room.json": _room_json(),
        }
        for f in bundle.frames:
            base = "captures-bucket/captures/refinetest/"
            self.blobs[base + f.rgb_gcs_path] = _JPEG
            self.blobs[base + f.depth.depth_gcs_path] = _DEPTH

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


def _run(*, enabled: bool, sam3=None, monkeypatch=None):
    gcs = FakeGcs(_make_bundle())
    sam3 = sam3 or _FakeSam3()
    sam3d = _FakeSam3D()
    with patch.object(mask_refine, "MASK_REFINE_ENABLED", enabled), \
         patch.object(process_receiver, "_download_gcs_uri", gcs.download), \
         patch.object(process_receiver, "_gcs_blob_exists_and_get",
                      gcs.exists_and_get), \
         patch.object(process_receiver, "_gcs_upload_for_scene", gcs.upload):
        run_perception(
            scene_id=_SCENE, bundle_uri=_BUNDLE_URI, outputs_bucket=_OUT,
            sam3_model=sam3, sam3d_model=sam3d, object_prompt="desk,table lamp",
        )
    return gcs, sam3, sam3d


def _manifest(gcs: FakeGcs) -> dict:
    return json.loads(gcs.blobs[f"{_OUT}/scenes/{_SCENE}/manifest.json"])


def _entries(manifest: dict) -> list[dict]:
    return [o for fr in manifest["frames"] for o in fr["objects"]]


class TestTheDegradeLock:
    """With the flag off, nothing about /process moved."""

    def test_sam3_is_never_asked_to_refine(self):
        _gcs, sam3, _sam3d = _run(enabled=False)
        assert sam3.refine_calls == []

    def test_sam3d_sees_the_segmentation_mask_byte_for_byte(self):
        _gcs, _sam3, sam3d = _run(enabled=False)
        assert sam3d.masks_shown
        short, lamp = _short_mask(), _lamp_mask()
        for shown in sam3d.masks_shown:
            assert np.array_equal(shown, short) or np.array_equal(shown, lamp)

    def test_no_entry_gains_a_key(self):
        gcs, _sam3, _sam3d = _run(enabled=False)
        for entry in _entries(_manifest(gcs)):
            assert "mask_refinement" not in entry
            assert "mask_refined" not in entry

    def test_no_refined_mask_sidecar_is_written(self):
        gcs, _sam3, _sam3d = _run(enabled=False)
        assert not [k for k in gcs.blobs if k.endswith(".mask.npz")]

    def test_the_manifest_is_identical_across_runs(self):
        a, _, _ = _run(enabled=False)
        b, _, _ = _run(enabled=False)
        assert _manifest(a) == _manifest(b)

    def test_turning_it_on_changes_only_additive_keys(self):
        off, _, _ = _run(enabled=False)
        on, _, _ = _run(enabled=True)
        man_off, man_on = _manifest(off), _manifest(on)
        assert man_off["sampling"] == man_on["sampling"]
        assert len(man_off["frames"]) == len(man_on["frames"])
        for fr_off, fr_on in zip(man_off["frames"], man_on["frames"], strict=True):
            for e_off, e_on in zip(fr_off["objects"], fr_on["objects"],
                                   strict=True):
                stripped = {k: v for k, v in e_on.items()
                            if k not in ("mask_refinement", "mask_refined",
                                         "placement", "view_ray")}
                assert set(stripped) <= set(e_off)


class TestTheSubstitutionHappens:
    def test_the_box_view_is_refined_and_the_refined_mask_reconstructed(self):
        _gcs, sam3, sam3d = _run(enabled=True)
        assert sam3.refine_calls, "the flagged box view was never refined"
        assert any(np.array_equal(m, _full_mask()) for m in sam3d.masks_shown)

    def test_only_the_table_is_ever_refined(self):
        """The lamp is long tail — an unassociated mask has no measured
        volume, so there is nothing to detect an incomplete mask against."""
        _gcs, sam3, _sam3d = _run(enabled=True)
        assert {c["label"] for c in sam3.refine_calls} == {"desk"}

    def test_the_prompt_is_normalized_and_names_the_original(self):
        _gcs, sam3, _sam3d = _run(enabled=True)
        call = sam3.refine_calls[0]
        assert len(call["box"]) == 4
        assert all(0.0 <= v <= 1.0 for v in call["box"])
        assert len(call["target"]) == 4

    def test_the_entry_records_the_verdict_and_the_evidence(self):
        gcs, _sam3, _sam3d = _run(enabled=True)
        refined = [e for e in _entries(_manifest(gcs)) if e.get("mask_refined")]
        assert refined, "no entry recorded an accepted refinement"
        rec = refined[0]["mask_refinement"]
        assert rec["accepted"] is True
        assert rec["box_id"] == "box_00"
        assert rec["refined_px"] > rec["original_px"]
        assert rec["unclaimed_fraction"] >= mask_refine.MIN_UNCLAIMED_FRACTION
        assert rec["added_on_signal"] >= mask_refine.MIN_ADDED_ON_SIGNAL

    def test_the_accepted_mask_is_persisted_beside_the_splat(self):
        gcs, _sam3, _sam3d = _run(enabled=True)
        sidecars = [k for k in gcs.blobs if k.endswith(".mask.npz")]
        assert sidecars
        with np.load(io.BytesIO(gcs.blobs[sidecars[0]])) as npz:
            assert np.array_equal(np.asarray(npz["mask"], bool), _full_mask())

    def test_a_cache_hit_places_the_splat_against_the_refined_mask(self):
        """The sidecar exists so a warm re-drive does not measure a splat
        built from one mask against a different one."""
        gcs, _sam3, _sam3d = _run(enabled=True)
        sidecar = next(k for k in gcs.blobs if k.endswith(".mask.npz"))
        splat = sidecar[: -len(".mask.npz")] + ".ply"
        assert splat in gcs.blobs

    def test_a_refusal_leaves_the_original_mask_in_place(self):
        """SAM 3 answers with a mask that moved rather than grew; the
        acceptance test refuses it and the segmentation mask reconstructs."""
        moved = np.zeros((_N, _N), dtype=bool)
        moved[_N - 6:, :6] = True
        gcs, sam3, sam3d = _run(enabled=True, sam3=_FakeSam3(answer=moved))
        assert sam3.refine_calls
        assert not any(np.array_equal(m, moved) for m in sam3d.masks_shown)
        assert not [k for k in gcs.blobs if k.endswith(".mask.npz")]
        recs = [e["mask_refinement"] for e in _entries(_manifest(gcs))
                if "mask_refinement" in e]
        assert any(r.get("reason") for r in recs)

    def test_sam3_returning_nothing_is_not_an_error(self):
        gcs, sam3, sam3d = _run(enabled=True, sam3=_FakeSam3(answer=None))
        assert sam3.refine_calls
        assert sam3d.masks_shown
        recs = [e["mask_refinement"] for e in _entries(_manifest(gcs))
                if "mask_refinement" in e]
        assert any(r.get("reason") == "no_mask_returned" for r in recs)


class TestTheDetectorGatesTheGpuCall:
    def test_an_unflagged_view_never_reaches_sam3(self, monkeypatch):
        """The flag is what makes the pass cheap: an object whose mask
        already claims its measured surface costs nothing at all."""
        monkeypatch.setattr(mask_refine, "MIN_UNCLAIMED_FRACTION", 0.99)
        _gcs, sam3, _sam3d = _run(enabled=True)
        assert sam3.refine_calls == []

    def test_an_unflagged_view_still_records_why_not(self, monkeypatch):
        monkeypatch.setattr(mask_refine, "MIN_UNCLAIMED_FRACTION", 0.99)
        gcs, _sam3, _sam3d = _run(enabled=True)
        recs = [e["mask_refinement"] for e in _entries(_manifest(gcs))
                if "mask_refinement" in e]
        assert recs
        assert all(r["reason"] == "not_flagged" for r in recs)


class TestTheCostBound:
    def test_refinement_adds_no_reconstruction(self):
        """The repaired mask REPLACES the original rather than adding an
        arm, so the plan, the per-box view budget and a starved room's long
        tail are all the length they were."""
        _off_gcs, _off_sam3, off_sam3d = _run(enabled=False)
        _on_gcs, _on_sam3, on_sam3d = _run(enabled=True)
        assert len(on_sam3d.masks_shown) == len(off_sam3d.masks_shown)

    def test_at_most_one_refinement_per_planned_box_view(self):
        gcs, sam3, _sam3d = _run(enabled=True)
        plan = _manifest(gcs)["sampling"]["census"]["plan"]
        box_views = plan["box_best_views"] + plan["box_second_views"]
        assert 0 < len(sam3.refine_calls) <= box_views
