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
import segment_receiver as sr
from PIL import Image

# ── fakes ────────────────────────────────────────────────────────────────────

class FakeSam3:
    """Returns a fixed detection set; records that it was called."""

    def __init__(self, dets):
        self._dets = dets
        self.calls = 0

    def segment(self, pil, prompt, *, want_prob=False):
        # Mirrors models.sam3.SAM3Model.segment. A stub that drops a keyword
        # the real model takes turns a signature change into eleven unrelated
        # failures, which is what happened when want_prob landed.
        self.calls += 1
        self.prompt = prompt
        self.want_prob = want_prob
        out = [dict(d) for d in self._dets]
        if want_prob:
            import numpy as np
            for d in out:
                m = np.asarray(d["mask"], dtype=bool)
                # 0.9 where the mask is, 0.4 in a one-pixel skirt around it —
                # the band the upstream 0.5 cut discards.
                pr = np.where(m, 0.9, 0.0).astype(np.float32)
                skirt = np.zeros_like(m)
                skirt[1:] |= m[:-1]
                skirt[:-1] |= m[1:]
                pr[skirt & ~m] = 0.4
                d["mask_prob"] = pr
        return out


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


class FakeRequest:
    def __init__(self, auth=None):
        self.headers = {"Authorization": auth} if auth else {}


def _run(req, sam3, uploads, verifier=None, request=None):
    return asyncio.run(
        sr.handle_segment(
            request=request if request is not None else FakeRequest(),
            req=req,
            oidc_verifier=verifier,
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
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            sr.SegmentRequest(scene_id="s", bundle_uri="gs://c/b.pb", frame_indices=[])


# ── auth ─────────────────────────────────────────────────────────────────────

class TestOIDC:
    """These exist because their absence shipped a 500.

    Every other test passes oidc_verifier=None, which skips the branch
    entirely — so the first live call crashed on
    `'Request' object has no attribute 'strip'`: verify() takes the HEADER
    VALUE, is not async, and raises rather than returning a response. A route
    whose auth path is never exercised is a route whose auth path is untested.
    """

    def test_the_header_value_is_what_reaches_the_verifier(self, wired):
        seen = {}

        class V:
            def verify(self, header):
                seen["header"] = header

        sam3 = FakeSam3([{"label": "chair", "score": 0.9, "mask": _mask(48, 64, 4, 20, 4, 30)}])
        resp = _run(
            sr.SegmentRequest(scene_id="s1", bundle_uri="gs://c/b.pb", frame_indices=[41]),
            sam3, wired, verifier=V(), request=FakeRequest("Bearer tok-123"),
        )
        assert seen["header"] == "Bearer tok-123"
        assert resp.status_code == 200

    def test_a_rejected_token_is_401_not_500(self, wired):
        from oidc import OIDCError

        class V:
            def verify(self, header):
                raise OIDCError("missing_token", "no Authorization header")

        sam3 = FakeSam3([{"label": "chair", "score": 0.9, "mask": _mask(48, 64, 4, 20, 4, 30)}])
        resp = _run(
            sr.SegmentRequest(scene_id="s1", bundle_uri="gs://c/b.pb", frame_indices=[41]),
            sam3, wired, verifier=V(),
        )
        assert resp.status_code == 401
        assert sam3.calls == 0, "a rejected request must not reach the model"


class TestProbabilityMaps:
    """The probability map each binary mask is thresholded from.

    Upstream computes `masks = masks_logits > 0.5` with a bare literal, and
    `masks_logits` is post-sigmoid despite its name — so 0.5 is a probability
    with no parameter behind it, and anything the model scored just under it is
    deleted with no record. `write_prob` is how that record is kept.
    """

    def _dets(self, n=2, with_prob=True, shape=(4, 5)):
        out = []
        for i in range(n):
            m = np.zeros(shape, dtype=bool)
            m[0, i] = True
            d = {"label": f"o{i}", "mask": m}
            if with_prob:
                p = np.zeros(shape, dtype=np.float32)
                p[0, i] = 0.9
                p[1, i] = 0.4          # just under the cut — the part that is lost
                d["mask_prob"] = p
            out.append(d)
        return out

    def test_none_when_no_detection_carries_one(self):
        assert sr.probs_npz_bytes(self._dets(with_prob=False)) is None
        assert sr.probs_npz_bytes([]) is None

    def test_round_trips_the_cut_at_any_threshold(self):
        dets = self._dets()
        raw = sr.probs_npz_bytes(dets)
        z = np.load(io.BytesIO(raw))
        assert list(z["mask_index"]) == [0, 1]
        for k, d in enumerate(dets):
            recovered = z["probs"][k] / 255.0
            # the shipped cut is reproduced exactly
            assert (recovered > 0.5).tolist() == (d["mask_prob"] > 0.5).tolist()
            # and a lower one recovers the pixel 0.5 threw away
            assert (recovered > 0.3).sum() > (recovered > 0.5).sum()

    def test_it_indexes_by_position_not_by_equality(self):
        """These dicts hold numpy arrays, so list.index() raises rather than
        comparing. Two detections with identical content must still map to 0
        and 1."""
        dets = self._dets()
        dets[1] = {k: (v.copy() if hasattr(v, "copy") else v) for k, v in dets[0].items()}
        z = np.load(io.BytesIO(sr.probs_npz_bytes(dets)))
        assert list(z["mask_index"]) == [0, 1]

    def test_partial_coverage_keeps_the_mapping_honest(self):
        """A detection without a probability map must not shift the indices of
        the ones that have it."""
        dets = self._dets(n=3)
        del dets[1]["mask_prob"]
        z = np.load(io.BytesIO(sr.probs_npz_bytes(dets)))
        assert list(z["mask_index"]) == [0, 2]

    def test_the_request_defaults_to_off(self):
        req = sr.SegmentRequest(
            scene_id="s", bundle_uri="gs://b/x/bundle.pb", frame_indices=[1]
        )
        assert req.write_prob is False


class TestClickRefinement:
    """The loop that seeds SAM 3's visual path with a mask and clicks in its own
    leftover. It records every round and decides nothing — the guard lives
    offline, because the guard has been the weak link three times."""

    class _Model:
        """Grows the mask by a fixed band per call, and reports a quality score
        that is deliberately NOT ordered by size — the whole point of taking the
        highest-scoring candidate rather than the largest."""

        def __init__(self, shape=(20, 20)):
            self.shape = shape
            self.calls = []

        def refine_with_points(self, pil, seed, points, labels, *, multimask_output=True):
            self.calls.append({"points": list(points), "labels": list(labels),
                               "seeded": seed is not None})
            n = len(self.calls)
            big = np.zeros(self.shape, dtype=bool)
            big[:, : 6 + 6 * n] = True            # LARGEST every round, LOW score
            mid = np.zeros(self.shape, dtype=bool)
            # Smaller than `big` every round — so taking the highest score and
            # taking the largest give different answers — but growing fast
            # enough that by round 3 it reaches the neighbouring detection at
            # column 15, which is what the guard has to notice.
            mid[:, : 3 + 6 * n] = True            # HIGHEST score
            small = np.zeros(self.shape, dtype=bool)
            small[:, :2] = True
            return [mid, big, small], [0.9, 0.4, 0.1]

    def _dets(self, shape=(20, 20)):
        seed = np.zeros(shape, dtype=bool)
        seed[:, :3] = True
        other = np.zeros(shape, dtype=bool)
        other[:, 15:] = True
        return [{"label": "desk", "mask": seed}, {"label": "chair", "mask": other}]

    def test_it_takes_the_highest_scoring_not_the_largest(self):
        m = self._Model()
        out = sr.click_refine(m, None, self._dets(), 0, rounds=1)
        r = out["rounds"][0]
        assert r["scores"] == [0.9, 0.4, 0.1]
        # round 1: the 0.9 candidate is 9 columns, the 0.4 one is 12. The
        # larger one must lose.
        assert r["chosen_px"] == 20 * 9
        assert max(r["candidate_px"]) == 20 * 12
        assert r["chosen_px"] < max(r["candidate_px"])

    def test_round_zero_seeds_with_the_mask_and_no_click(self):
        m = self._Model()
        sr.click_refine(m, None, self._dets(), 0, rounds=2)
        assert m.calls[0]["points"] == [] and m.calls[0]["seeded"]
        assert len(m.calls[1]["points"]) == 1, "later rounds must carry a click"
        assert m.calls[1]["labels"] == [1], "the click must be positive"

    def test_the_click_lands_inside_the_leftover(self):
        m = self._Model()
        out = sr.click_refine(m, None, self._dets(), 0, rounds=2)
        x, y = out["rounds"][1]["click"]
        # round 0 took columns 0..8 over a seed of 0..2, so the leftover is
        # columns 3..8 and the click must sit inside it
        assert 3 <= x <= 8, f"click at x={x} is not in the leftover"

    def test_it_measures_what_the_growth_covers_of_others(self):
        """The guard's input. Round 2's growth reaches column 15+, which is the
        other detection."""
        m = self._Model()
        out = sr.click_refine(m, None, self._dets(), 0, rounds=3)
        assert out["rounds"][0]["worst_other_covered"] == 0.0
        assert any(r["worst_other_covered"] > 0 for r in out["rounds"]), (
            "growth onto the neighbour was never reported"
        )
        hit = next(r for r in out["rounds"] if r["worst_other_covered"] > 0)
        assert hit["worst_other_index"] == 0, "reports which other mask, by index"

    def test_it_decides_nothing(self):
        """Every round is recorded even when growth swallows the neighbour."""
        m = self._Model()
        out = sr.click_refine(m, None, self._dets(), 0, rounds=3)
        assert len(out["rounds"]) == 3

    def test_a_model_that_returns_nothing_is_not_an_error(self):
        class Dead:
            def refine_with_points(self, *a, **k):
                return None
        assert sr.click_refine(Dead(), None, self._dets(), 0, rounds=2) is None

    def test_an_out_of_range_seed_is_refused(self):
        assert sr.click_refine(self._Model(), None, self._dets(), 9, rounds=1) is None

    def test_the_request_defaults_to_off(self):
        req = sr.SegmentRequest(
            scene_id="s", bundle_uri="gs://b/x/bundle.pb", frame_indices=[1]
        )
        assert req.refine_seed_mask is None
