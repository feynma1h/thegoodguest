"""Invariants for the segmentation-only probe (/segment).

The two that matter are containment invariants, not behaviour: this route must
be unable to become pipeline state. It writes only under segment_probe/ and it
never loads or calls SAM 3D. Everything else here is ordinary shape-checking.
"""

from __future__ import annotations

import asyncio
import io
import json

import numpy as np
import pytest
from PIL import Image

import segment_receiver as sr


# ── fakes ────────────────────────────────────────────────────────────────────

class FakeSam3:
    """Returns a fixed detection set; records that it was called."""

    def __init__(self, dets):
        self._dets = dets
        self.calls = 0

    def segment(self, pil, prompt):
        self.calls += 1
        self.prompt = prompt
        return [dict(d) for d in self._dets]


def _mask(h, w, y0, y1, x0, x1):
    m = np.zeros((h, w), dtype=bool)
    m[y0:y1, x0:x1] = True
    return m


def _jpeg(w=64, h=48):
    buf = io.BytesIO()
    Image.new("RGB", (w, h), (120, 130, 140)).save(buf, format="JPEG")
    return buf.getvalue()


class Uploads(dict):
    def __call__(self, base, path, data, content_type):
        self[path] = (data, content_type)
        return base + path


@pytest.fixture
def wired(monkeypatch):
    """Patch the receiver's lazily-imported GCS + bundle helpers."""
    uploads = Uploads()

    class FakeFrame:
        def __init__(self, i):
            self.frame_index = i
            self.rgb_gcs_path = f"frames/{i:06d}.jpg"

    class FakeBundle:
        def __init__(self):
            self.frames = [FakeFrame(i) for i in (0, 41, 42)]

        def ParseFromString(self, _b):
            return None

    import process_receiver as pr

    monkeypatch.setattr(pr, "_download_gcs_uri", lambda uri: _jpeg(), raising=False)
    monkeypatch.setattr(pr, "_gcs_upload_for_scene", uploads, raising=False)
    monkeypatch.setattr(pr, "_bundle_prefix", lambda uri: "gs://caps/x/", raising=False)
    monkeypatch.setattr(
        "roomstudio_schemas.CaptureBundle", lambda: FakeBundle(), raising=False
    )
    return uploads


def _run(req, sam3, uploads):
    return asyncio.run(
        sr.handle_segment(
            request=None,
            req=req,
            oidc_verifier=None,
            outputs_bucket="out-bucket",
            sam3_model=sam3,
            object_prompt="chair,desk",
        )
    )


def _body(resp):
    return json.loads(bytes(resp.body).decode())


# ── containment: the two invariants this route exists under ──────────────────

class TestItCannotBecomePipelineState:
    def test_every_write_is_under_segment_probe(self, wired):
        sam3 = FakeSam3([{"label": "chair", "score": 0.9, "mask": _mask(48, 64, 4, 20, 4, 30)}])
        _run(sr.SegmentRequest(scene_id="s1", bundle_uri="gs://c/b.pb", frame_indices=[41]),
             sam3, wired)
        assert wired, "expected at least the masks.npz write"
        for path in wired:
            assert path.startswith("scenes/s1/segment_probe/"), path

    def test_it_never_writes_a_frames_masks_npz(self, wired):
        """The exact path /process reads as cache. Writing it here would let a
        probe of an unsampled frame silently become a cache hit."""
        sam3 = FakeSam3([{"label": "chair", "score": 0.9, "mask": _mask(48, 64, 4, 20, 4, 30)}])
        _run(sr.SegmentRequest(scene_id="s1", bundle_uri="gs://c/b.pb", frame_indices=[41]),
             sam3, wired)
        assert not any("/frames/" in p for p in wired)

    def test_no_reconstruction_is_attempted(self, wired, monkeypatch):
        """SAM 3D must not be reachable from this path at all."""
        import process_receiver as pr

        def boom(*a, **k):
            raise AssertionError("/segment must never reconstruct")

        monkeypatch.setattr(pr, "_reconstruct_one_object", boom, raising=False)
        sam3 = FakeSam3([{"label": "chair", "score": 0.9, "mask": _mask(48, 64, 4, 20, 4, 30)}])
        resp = _run(sr.SegmentRequest(scene_id="s1", bundle_uri="gs://c/b.pb",
                                      frame_indices=[41]), sam3, wired)
        assert resp.status_code == 200


# ── behaviour ────────────────────────────────────────────────────────────────

class TestReporting:
    def test_reports_each_detection_with_its_mask_size(self, wired):
        sam3 = FakeSam3([
            {"label": "chair", "score": 0.9, "mask": _mask(48, 64, 4, 20, 4, 30)},
            {"label": "desk", "score": 0.8, "mask": _mask(48, 64, 0, 8, 0, 8)},
        ])
        body = _body(_run(sr.SegmentRequest(scene_id="s1", bundle_uri="gs://c/b.pb",
                                            frame_indices=[41]), sam3, wired))
        objs = body["frames"][0]["objects"]
        assert [o["label"] for o in objs] == ["chair", "desk"]
        assert objs[0]["mask_px"] == 16 * 26
        assert objs[1]["mask_px"] == 64
        assert 0.0 < objs[0]["mask_frac_of_frame"] < 1.0

    def test_writes_one_png_per_detection_when_asked(self, wired):
        sam3 = FakeSam3([{"label": "chair", "score": 0.9, "mask": _mask(48, 64, 4, 20, 4, 30)}])
        body = _body(_run(sr.SegmentRequest(scene_id="s1", bundle_uri="gs://c/b.pb",
                                            frame_indices=[41]), sam3, wired))
        assert body["frames"][0]["objects"][0]["png_gcs_uri"].endswith(".png")
        assert any(p.endswith(".png") for p in wired)

    def test_png_is_suppressible(self, wired):
        sam3 = FakeSam3([{"label": "chair", "score": 0.9, "mask": _mask(48, 64, 4, 20, 4, 30)}])
        _run(sr.SegmentRequest(scene_id="s1", bundle_uri="gs://c/b.pb",
                               frame_indices=[41], write_png=False), sam3, wired)
        assert not any(p.endswith(".png") for p in wired)

    def test_suppressed_detections_are_counted_but_never_returned_as_objects(self, wired):
        """0089: person is segmented and never shipped. It must not appear as a
        detection here either — only as the count and the union's pixel total."""
        sam3 = FakeSam3([
            {"label": "chair", "score": 0.9, "mask": _mask(48, 64, 4, 20, 4, 30)},
            {"label": "person", "score": 0.95, "mask": _mask(48, 64, 0, 10, 0, 10)},
        ])
        body = _body(_run(sr.SegmentRequest(scene_id="s1", bundle_uri="gs://c/b.pb",
                                            frame_indices=[41]), sam3, wired))
        fr = body["frames"][0]
        assert [o["label"] for o in fr["objects"]] == ["chair"]
        assert fr["suppressed_count"] == 1
        assert fr["suppressed_px"] == 100

    def test_a_frame_not_in_the_bundle_is_reported_not_raised(self, wired):
        sam3 = FakeSam3([])
        body = _body(_run(sr.SegmentRequest(scene_id="s1", bundle_uri="gs://c/b.pb",
                                            frame_indices=[999]), sam3, wired))
        assert body["frames"][0]["ok"] is False
        assert "not in bundle" in body["frames"][0]["error"]
        assert sam3.calls == 0

    def test_duplicate_indices_are_segmented_once(self, wired):
        sam3 = FakeSam3([{"label": "chair", "score": 0.9, "mask": _mask(48, 64, 4, 20, 4, 30)}])
        body = _body(_run(sr.SegmentRequest(scene_id="s1", bundle_uri="gs://c/b.pb",
                                            frame_indices=[41, 41, 41]), sam3, wired))
        assert len(body["frames"]) == 1
        assert sam3.calls == 1

    def test_frame_count_is_capped(self, wired):
        sam3 = FakeSam3([])
        req = sr.SegmentRequest(scene_id="s1", bundle_uri="gs://c/b.pb",
                                frame_indices=list(range(200)))
        body = _body(_run(req, sam3, wired))
        assert len(body["frames"]) <= sr.MAX_FRAMES_PER_CALL

    def test_the_prompt_carries_the_suppressed_concepts(self, wired):
        """Same prompt discipline as /process — the probe must see what
        production sees, or its masks are not comparable to production's."""
        sam3 = FakeSam3([{"label": "chair", "score": 0.9, "mask": _mask(48, 64, 4, 20, 4, 30)}])
        _run(sr.SegmentRequest(scene_id="s1", bundle_uri="gs://c/b.pb", frame_indices=[41]),
             sam3, wired)
        from privacy import SUPPRESSED_CONCEPTS

        for concept in SUPPRESSED_CONCEPTS:
            assert concept in sam3.prompt


class TestRequestModel:
    def test_frame_indices_are_required(self):
        with pytest.raises(Exception):
            sr.SegmentRequest(scene_id="s", bundle_uri="gs://c/b.pb", frame_indices=[])
