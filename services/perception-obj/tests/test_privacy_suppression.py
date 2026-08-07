"""Privacy suppression invariants (decision 0089 — closing 0070's gap).

Two things must be true at once, and this file pins both:

  SUPPRESSED CONTENT IS SEEN. A person in the room reaches SAM 3 (the concept
  is in the prompt), their mask lands in masks.npz, and it excludes those
  pixels from every surface-evidence path — albedo samples and material
  evidence crops alike, degrading through the gates 0069 already built.

  SUPPRESSED CONTENT IS NEVER SHIPPED. This is the risk the fix introduces:
  the segmenter is now told to find people, so one careless call site turns a
  person into a reconstructed, placed, inventoried object. The end-to-end pins
  below assert a person never reaches SAM 3D, objects.json, or anything the
  manifest carries — which is also what keeps them out of api-public's
  scene_facts, whose entire world is the manifest's objects[].

Run: python -m pytest services/perception-obj/tests/test_privacy_suppression.py
"""
from __future__ import annotations

import importlib
import io
import json
import sys
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

# Stub heavy deps not installed in the test venv (the test_envelope preamble).
sys.modules.setdefault("torch", MagicMock())
sys.modules.setdefault("models", MagicMock())
sys.modules.setdefault("models.sam3", MagicMock())
sys.modules.setdefault("models.sam3d", MagicMock())

import privacy  # noqa: E402
import process_receiver  # noqa: E402
import shell_material  # noqa: E402
from privacy import (  # noqa: E402
    masks_npz_bytes,
    partition_detections,
    read_suppressed,
    segmentation_prompt,
    suppressed_union,
)
from room_planes import ShellPlaneGeom  # noqa: E402
from roomstudio_schemas import Intrinsics, Pose  # noqa: E402
from shell_observation import FrameSample, observe_plane  # noqa: E402


def _det(label: str, mask: np.ndarray, score: float = 0.5) -> dict:
    return {
        "label": label, "instance_idx": 0, "bbox": [0, 0, 1, 1],
        "score": score, "mask": mask,
    }


def _mask(h=8, w=8, rows=slice(0, 2)) -> np.ndarray:
    m = np.zeros((h, w), dtype=bool)
    m[rows, :] = True
    return m


# ---------------------------------------------------------------------------
# The concept seam
# ---------------------------------------------------------------------------

class TestSegmentationPrompt:
    def test_person_is_appended_to_the_production_vocabulary(self):
        from server import DEFAULT_OBJECT_PROMPT

        prompt = segmentation_prompt(DEFAULT_OBJECT_PROMPT)
        classes = [c.strip() for c in prompt.split(",")]
        assert "person" in classes
        # The object vocabulary itself is untouched — suppression adds, never
        # edits (a dropped object class would silently shrink the product).
        assert prompt.startswith(DEFAULT_OBJECT_PROMPT)
        assert all(c in classes for c in DEFAULT_OBJECT_PROMPT.split(","))

    def test_a_concept_already_in_the_prompt_is_not_duplicated(self):
        """SAM 3 runs one pass per comma-separated class; a duplicate would
        pay for the same class twice."""
        assert segmentation_prompt("chair,person").count("person") == 1

    def test_no_suppressed_concepts_is_a_verbatim_passthrough(self, monkeypatch):
        """The degrade lock: PERCEPTION_SUPPRESSED_CONCEPTS='' reproduces
        pre-0089 behaviour exactly."""
        monkeypatch.setenv("PERCEPTION_SUPPRESSED_CONCEPTS", "")
        mod = importlib.reload(privacy)
        try:
            assert mod.SUPPRESSED_CONCEPTS == ()
            assert mod.segmentation_prompt("chair,bed") == "chair,bed"
            kept, suppressed = mod.partition_detections(
                [_det("person", _mask()), _det("bed", _mask())]
            )
            assert len(kept) == 2 and suppressed == []
        finally:
            monkeypatch.delenv("PERCEPTION_SUPPRESSED_CONCEPTS")
            importlib.reload(privacy)

    def test_label_matching_is_case_and_whitespace_insensitive(self):
        assert privacy.is_suppressed_label(" Person ")
        assert not privacy.is_suppressed_label("personal shelf")


class TestPartition:
    def test_kept_order_and_indices_are_unchanged_by_suppression(self):
        """Per-object splat cache keys are {frame}/splats/{i:02d}_{label}.ply.
        Suppressed detections must not shift i, or every warm re-drive misses
        its cache and re-runs SAM 3D."""
        without = [_det("bed", _mask()), _det("chair", _mask()), _det("rug", _mask())]
        with_person = [
            without[0], _det("person", _mask()), without[1],
            _det("person", _mask()), without[2],
        ]

        kept, suppressed = partition_detections(with_person)

        assert [d["label"] for d in kept] == [d["label"] for d in without]
        assert len(suppressed) == 2

    def test_union_is_none_when_nothing_is_suppressed(self):
        assert suppressed_union([]) is None


# ---------------------------------------------------------------------------
# masks.npz: the on-disk contract both sides read
# ---------------------------------------------------------------------------

class TestMasksNpz:
    def test_bytes_are_identical_to_the_legacy_writer_when_nothing_suppressed(self):
        """No suppression → no new key → warm re-drives and cached frames are
        bit-for-bit what they were before 0089."""
        dets = [_det("bed", _mask(rows=slice(0, 2))), _det("rug", _mask(rows=slice(4, 6)))]

        legacy = io.BytesIO()
        np.savez_compressed(legacy, masks=np.stack([d["mask"] for d in dets]))

        assert masks_npz_bytes(dets, []) == legacy.getvalue()

    def test_suppressed_union_is_written_beside_the_kept_stack(self):
        kept = [_det("bed", _mask(rows=slice(0, 2)))]
        suppressed = [
            _det("person", _mask(rows=slice(4, 5))),
            _det("person", _mask(rows=slice(6, 7))),
        ]

        with np.load(io.BytesIO(masks_npz_bytes(kept, suppressed))) as npz:
            assert npz["masks"].shape == (1, 8, 8)  # kept only
            union = read_suppressed(npz)

        expected = np.zeros((8, 8), dtype=bool)
        expected[4:5, :] = True
        expected[6:7, :] = True
        assert np.array_equal(union, expected)

    def test_a_frame_containing_only_a_person_still_writes_a_valid_npz(self):
        """A close-up of someone: zero shippable objects, one suppressed mask.
        The empty-stack shape must stay the one shell_receiver expects, or the
        frame poisons the shell instead of just contributing nothing."""
        raw = masks_npz_bytes([], [_det("person", _mask())])
        with np.load(io.BytesIO(raw)) as npz:
            masks = npz["masks"]
            union = read_suppressed(npz)

        assert masks.shape == (0,)  # the pre-0089 empty shape, unchanged
        assert masks.ndim != 3  # shell_receiver's exclusion branch condition
        assert np.array_equal(union, _mask())

    def test_a_pre_0089_masks_npz_reads_as_no_suppression(self):
        legacy = io.BytesIO()
        np.savez_compressed(legacy, masks=np.zeros((1, 4, 4), dtype=bool))
        with np.load(io.BytesIO(legacy.getvalue())) as npz:
            assert read_suppressed(npz) is None


# ---------------------------------------------------------------------------
# End of the line: a person never reaches reconstruction or the outputs
# ---------------------------------------------------------------------------

class _FakeSam3:
    """Returns a person alongside real furniture, exactly as the segmenter
    will once 'person' is in the prompt."""

    def __init__(self):
        self.prompts: list[str] = []

    def segment(self, pil, prompt):
        self.prompts.append(prompt)
        return [
            _det("bed", _mask(rows=slice(0, 2)), score=0.9),
            _det("person", _mask(rows=slice(3, 5)), score=0.8),
            _det("rug", _mask(rows=slice(6, 8)), score=0.7),
        ]


_MINI_PLY = (
    "ply\nformat ascii 1.0\nelement vertex 8\n"
    "property float x\nproperty float y\nproperty float z\nend_header\n"
    "0 0 0\n1 0 0\n0 1 0\n0 0 1\n1 1 0\n1 0 1\n0 1 1\n1 1 1\n"
)


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
        from pathlib import Path

        Path(path).write_text(_MINI_PLY)


class _RecordingSam3D:
    """Records every mask handed to SAM 3D — the surface the pin watches."""

    def __init__(self):
        self.masks: list[np.ndarray] = []

    def reconstruct(self, pil, mask, seed=42):
        self.masks.append(np.asarray(mask, dtype=bool))
        return {
            "rotation": _FakeTensor([1.0, 0.0, 0.0, 0.0]),
            "translation": _FakeTensor([0.0, 0.0, 1.0]),
            "scale": _FakeTensor([1.0, 1.0, 1.0]),
            "gs": _FakeGS(),
        }


class _FakeGcs:
    def __init__(self):
        self.blobs: dict[str, bytes] = {}

    def download(self, uri: str) -> bytes:
        from PIL import Image

        buf = io.BytesIO()
        Image.new("RGB", (8, 8), (120, 90, 60)).save(buf, format="JPEG")
        return buf.getvalue()

    def exists_and_get(self, bucket: str, path: str):
        return self.blobs.get(f"{bucket}/{path}")

    def upload(self, prefix: str, blob: str, data: bytes, content_type: str) -> str:
        bucket = prefix[5:].split("/")[0]
        self.blobs[f"{bucket}/{blob}"] = data
        return f"gs://{bucket}/{blob}"


class TestPersonNeverShips:
    def _run_frame(self, sam3d):
        gcs = _FakeGcs()
        sam3 = _FakeSam3()
        with patch.object(process_receiver, "_download_gcs_uri", gcs.download), \
             patch.object(process_receiver, "_gcs_blob_exists_and_get", gcs.exists_and_get), \
             patch.object(process_receiver, "_gcs_upload_for_scene", gcs.upload):
            result = process_receiver._process_frame(
                scene_id="scene-priv", frame_idx=0,
                rgb_gcs_uri="gs://captures/x/frames/000000.jpg",
                outputs_bucket="out", sam3_model=sam3, sam3d_model=sam3d,
                object_prompt="bed,rug",
            )
        return result, gcs, sam3

    def test_sam3d_never_receives_a_suppressed_mask(self):
        """The load-bearing pin: a person is segmented but never reconstructed."""
        sam3d = _RecordingSam3D()

        result, _gcs, sam3 = self._run_frame(sam3d)

        assert "person" in sam3.prompts[0]  # it WAS looked for
        assert len(sam3d.masks) == 2  # bed + rug only
        person = _mask(rows=slice(3, 5))
        assert not any(np.array_equal(m, person) for m in sam3d.masks)
        assert [o["label"] for o in result["objects"]] == ["bed", "rug"]

    def test_no_suppressed_label_appears_anywhere_in_the_frame_outputs(self):
        """Scanned as text, not by field: a label leaking into ANY key —
        provenance, reasons, debug — is a leak into the manifest and from
        there into scene_facts."""
        result, gcs, _sam3 = self._run_frame(_RecordingSam3D())

        assert "person" not in json.dumps(result).lower()
        cached = gcs.blobs["out/scenes/scene-priv/frames/0000/objects.json"]
        assert b"person" not in cached.lower()

    def test_masks_npz_carries_the_kept_stack_and_the_suppressed_union(self):
        """Alignment pin: masks[i] must be the mask of objects[i] (fusion
        reads it by detection order), with the person off to the side."""
        result, gcs, _sam3 = self._run_frame(_RecordingSam3D())

        raw = gcs.blobs["out/scenes/scene-priv/frames/0000/masks.npz"]
        with np.load(io.BytesIO(raw)) as npz:
            masks = npz["masks"]
            union = read_suppressed(npz)

        assert masks.shape[0] == len(result["objects"]) == 2
        assert np.array_equal(masks[0], _mask(rows=slice(0, 2)))  # bed
        assert np.array_equal(masks[1], _mask(rows=slice(6, 8)))  # rug
        assert np.array_equal(union, _mask(rows=slice(3, 5)))  # person


# ---------------------------------------------------------------------------
# Surface evidence: the person-free degrade path
# ---------------------------------------------------------------------------

def _wall_geom(width: float = 1.0, height: float = 1.0) -> ShellPlaneGeom:
    origin = np.array([0.0, 0.0, 0.0])
    u = np.array([1.0, 0.0, 0.0])
    v = np.array([0.0, 1.0, 0.0])
    corners = np.stack([
        origin, origin + width * u, origin + width * u + height * v, origin + height * v,
    ])
    return ShellPlaneGeom(
        kind="wall", corners_world=corners, normal=np.array([0.0, 0.0, 1.0]),
        origin=origin, axis_u=u, axis_v=v, width_m=width, height_m=height,
        classification="wall", member_indices=[0], wall_id="wall_00",
    )


def _pose(pos, quat=(0.0, 0.0, 0.0, 1.0)) -> Pose:
    p = Pose()
    p.pos_x, p.pos_y, p.pos_z = pos
    p.quat_x, p.quat_y, p.quat_z, p.quat_w = quat
    return p


def _intrinsics(w=100, h=100) -> Intrinsics:
    i = Intrinsics()
    i.fx, i.fy, i.cx, i.cy = 100.0, 100.0, 50.0, 50.0
    i.width, i.height = w, h
    return i


def _frame(
    *, frame_index=0, wall_color=(200, 190, 180), person_color=(137, 159, 191),
    person_rows: slice | None = None, pos=(0.5, 0.5, 2.0),
) -> FrameSample:
    """A camera looking at the 1x1 m wall. person_rows paints a band of the
    image in person_color AND marks it suppressed — the shape masks.npz
    delivers. #899fbf is f3d70236 wall_03's shipped albedo: a person."""
    img = np.zeros((100, 100, 3), dtype=np.uint8)
    img[:, :] = wall_color
    suppressed = np.zeros((100, 100), dtype=bool)
    if person_rows is not None:
        img[person_rows, :] = person_color
        suppressed[person_rows, :] = True
    return FrameSample(
        frame_index=frame_index, rgb=img,
        exclusion_mask=suppressed.copy(),  # shell_receiver ORs it in
        pose=_pose(pos), intrinsics=_intrinsics(),
        suppressed_mask=suppressed if person_rows is not None else None,
    )


class TestSurfaceEvidence:
    def test_a_persons_color_never_reaches_the_albedo(self):
        """0070's concrete manifestation, in miniature: with the person
        suppressed, the measured albedo is the WALL, not the person."""
        geom = _wall_geom()
        obs = observe_plane(geom, [_frame(person_rows=slice(0, 60))])

        assert obs.suppressed_texels > 0  # the mechanism fired
        assert obs.colors.size > 0
        # Every sampled color is the wall's, none the person's.
        assert np.allclose(obs.colors, np.array([200.0, 190.0, 180.0]), atol=1.0)
        assert shell_material.compute_albedo(obs.colors, obs.weights) == "#c8beb4"

    def test_a_contaminated_tile_falls_back_to_a_person_free_frame(self):
        """Two frames see the same wall; one has a person in front of it. The
        evidence crop must come from the other frame."""
        geom = _wall_geom()
        # The nearer camera would win on weight everywhere — but a person
        # stands across the whole wall in it.
        contaminated = _frame(frame_index=0, person_rows=slice(0, 100), pos=(0.5, 0.5, 1.5))
        clean = _frame(frame_index=1, pos=(0.5, 0.5, 2.0))

        obs = observe_plane(geom, [contaminated, clean])

        assert obs.crops, "the plane should still yield evidence"
        assert all(c.frame_index == 1 for c in obs.crops)

    def test_no_person_free_frame_means_no_crops_and_no_family(self):
        """The end of the fallback chain: every view is contaminated, so the
        plane produces no evidence and 0069's EXISTING gate nulls the family.
        classify_fn asserts it is never even asked."""
        geom = _wall_geom()

        def _must_not_be_called(crops, kind):  # pragma: no cover - the assertion
            raise AssertionError("a contaminated plane must not reach the model")

        obs = observe_plane(geom, [
            _frame(frame_index=0, person_rows=slice(0, 100)),
            _frame(frame_index=1, person_rows=slice(0, 100), pos=(0.5, 0.5, 1.6)),
        ])

        assert obs.crops == []
        mat = shell_material.infer_material(obs, "wall", classify_fn=_must_not_be_called)
        assert mat.family is None
        assert mat.roughness == 0.9  # the clean-matte constant

    def test_too_little_person_free_evidence_ships_the_honest_neutral(self):
        """Below shell_material's texel gate the albedo goes None — the
        viewer's neutral treatment, not a person-tinted guess."""
        geom = _wall_geom()
        obs = observe_plane(geom, [_frame(person_rows=slice(0, 99))])

        assert obs.texel_count < shell_material.SHELL_MATERIAL_MIN_TEXELS
        assert shell_material.compute_albedo(obs.colors, obs.weights) is None

    def test_absent_suppression_is_byte_identical(self):
        """A frame with suppressed_mask=None (every pre-0089 masks.npz) must
        observe exactly as it did before."""
        geom = _wall_geom()
        clean = _frame(frame_index=0)
        assert clean.suppressed_mask is None

        obs = observe_plane(geom, [clean])

        assert obs.suppressed_texels == 0
        assert obs.observed_fraction == 1.0
        assert len(obs.crops) > 0


class TestEverySegmentationCallSiteIsCovered:
    """A structural pin, in the style of /shell's no-Firestore AST test.

    The two suppression call sites are correct today; the risk is the THIRD
    one — a future path that calls sam3_model.segment() with a bare prompt
    would reconstruct people and no behavioural test would notice, because
    the fake segmenters in those tests do not return any.
    """

    def _segment_calls(self):
        import ast
        import pathlib

        src = pathlib.Path(process_receiver.__file__).read_text()
        tree = ast.parse(src)
        calls = []
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "segment"
            ):
                calls.append((node, src))
        return calls

    def test_no_bare_prompt_reaches_the_segmenter(self):
        import ast

        calls = self._segment_calls()
        assert calls, "expected to find sam3_model.segment() call sites"
        for node, src in calls:
            prompt_arg = node.args[1] if len(node.args) > 1 else None
            assert isinstance(prompt_arg, ast.Call), (
                f"line {node.lineno}: segment() must be given "
                f"segmentation_prompt(...), not a bare prompt"
            )
            assert getattr(prompt_arg.func, "id", None) == "segmentation_prompt", (
                f"line {node.lineno}: prompt is not built by segmentation_prompt"
            )

    def test_every_segment_call_site_partitions_the_result(self):
        """Seeing people is only safe if they are removed immediately after."""
        import pathlib

        src = pathlib.Path(process_receiver.__file__).read_text()
        lines = src.splitlines()
        for node, _ in self._segment_calls():
            window = "\n".join(lines[node.lineno - 1: node.lineno + 12])
            assert "partition_detections(" in window, (
                f"line {node.lineno}: no partition_detections() within 12 lines "
                f"of the segmentation call"
            )


# Image rows the 1x1 m wall actually projects into from the test camera
# (u,v both span 25..75): a band outside that range would suppress nothing.
@pytest.mark.parametrize("rows", [slice(26, 36), slice(45, 55), slice(64, 74)])
def test_suppression_is_positional_not_global(rows):
    """A person occupies part of a plane, not all of it: the rest of the wall
    still ships. (Sanity against an over-broad fix that nulls whole planes.)"""
    obs = observe_plane(_wall_geom(), [_frame(person_rows=rows)])
    assert obs.observed_fraction > 0.5
    assert obs.suppressed_texels > 0
