"""Invariants for the tracking probe (/track).

The load-bearing ones are containment, not behaviour: like /segment, this route
must be unable to become pipeline state. It writes only under track_probe/ and
it never touches Firestore.

The rest pin the two things that make an object->frame map trustworthy rather
than merely present: every number that leaves this route is in CAPTURE frame
indices (not positions in the tracked sequence, which is an internal detail of
one propagation), and the (concept, obj_id) key is never collapsed to obj_id —
ids restart per concept because the session holds one text prompt.
"""

from __future__ import annotations

import asyncio
import io
import json

import numpy as np
import pytest
import track_receiver as tr
from PIL import Image

# ── fakes ────────────────────────────────────────────────────────────────────


class FakeVideoModel:
    """Returns a scripted {position: [detections]} per concept.

    Records opens and closes so the tests can assert the video is decoded once
    and always released.
    """

    def __init__(self, by_concept: dict[str, dict[int, list[dict]]]):
        self._by_concept = by_concept
        self.opens = 0
        self.closes = 0
        self.tracked: list[str] = []
        self.n_frames_opened: int | None = None

    def open_video(self, frames, **kw):
        self.opens += 1
        self.n_frames_opened = len(frames)
        return {"frames": len(frames)}

    def track_concept(self, state, concept, *, prompt_frame=0, output_prob_thresh=0.5):
        self.tracked.append(concept)
        if concept == "explode":
            raise RuntimeError("model said no")
        return self._by_concept.get(concept, {})

    def close_video(self, state):
        self.closes += 1


def _det(obj_id, area=100, prob=0.9, shape=(12, 16)):
    small = np.zeros(shape, dtype=bool)
    small[0:2, 0:2] = True
    return {
        "obj_id": obj_id,
        "prob": prob,
        # bbox arrives already denormalised to pixels by the wrapper
        "bbox_px": [1.0, 2.0, 3.0, 4.0],
        "area_px": area,
        "mask_small": np.packbits(small),
        "mask_small_shape": list(shape),
    }


def _jpeg(w=64, h=48):
    buf = io.BytesIO()
    Image.new("RGB", (w, h), (120, 130, 140)).save(buf, format="JPEG")
    return buf.getvalue()


class Uploads(dict):
    def __call__(self, base, path, data, content_type):
        self[path] = (data, content_type)
        return base + path


# Capture frame indices that are deliberately NOT 0..n: a route that confuses a
# sequence position with a frame index passes every test where they coincide.
BUNDLE_FRAMES = (7, 41, 42, 108)


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
            self.frames = [FakeFrame(i) for i in BUNDLE_FRAMES]

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


def _run(req, model, verifier=None, request=None):
    return asyncio.run(
        tr.handle_track(
            request=request if request is not None else FakeRequest(),
            req=req,
            oidc_verifier=verifier,
            outputs_bucket="out-bucket",
            sam3_video_model=model,
        )
    )


def _body(resp):
    return json.loads(bytes(resp.body).decode())


def _req(**kw):
    kw.setdefault("scene_id", "s1")
    kw.setdefault("bundle_uri", "gs://c/b.pb")
    kw.setdefault("concepts", ["monitor"])
    return tr.TrackRequest(**kw)


# ── containment: the two invariants this route exists under ──────────────────


class TestItCannotBecomePipelineState:
    def test_every_write_is_under_track_probe(self, wired):
        model = FakeVideoModel({"monitor": {0: [_det(1)]}})
        _run(_req(), model)
        assert wired, "expected at least tracks.json and masks.npz"
        for path in wired:
            assert path.startswith("scenes/s1/track_probe/"), path

    def test_it_never_writes_a_frames_prefix(self, wired):
        """The exact prefix /process reads as cache (`Frame N cache hit`)."""
        model = FakeVideoModel({"monitor": {0: [_det(1)]}})
        _run(_req(), model)
        assert not any("/frames/" in p for p in wired)

    def test_no_reconstruction_is_attempted(self, wired, monkeypatch):
        import process_receiver as pr

        def boom(*a, **k):
            raise AssertionError("/track must never reconstruct")

        monkeypatch.setattr(pr, "_reconstruct_one_object", boom, raising=False)
        model = FakeVideoModel({"monitor": {0: [_det(1)]}})
        assert _run(_req(), model).status_code == 200


# ── the map's identity contract ──────────────────────────────────────────────


class TestFrameIndicesNotPositions:
    """A propagation is keyed by position in the tracked sequence; every number
    this route emits must be a capture frame index. These differ here on
    purpose — BUNDLE_FRAMES is not 0..n."""

    def test_detections_carry_capture_frame_indices(self, wired):
        model = FakeVideoModel({"monitor": {0: [_det(1)], 2: [_det(1)]}})
        _run(_req(), model)
        payload = json.loads(wired["scenes/s1/track_probe/monitor/tracks.json"][0].decode())
        assert [d["frame_index"] for d in payload["detections"]] == [7, 42]

    def test_the_position_to_index_mapping_is_published(self, wired):
        model = FakeVideoModel({"monitor": {0: [_det(1)]}})
        body = _body(_run(_req(), model))
        assert body["frame_indices"] == list(BUNDLE_FRAMES)

    def test_object_summary_spans_capture_indices(self, wired):
        model = FakeVideoModel({"monitor": {0: [_det(1)], 3: [_det(1)]}})
        body = _body(_run(_req(), model))
        obj = body["concepts"][0]["objects"][0]
        assert (obj["first_frame"], obj["last_frame"]) == (7, 108)
        assert obj["n_frames"] == 2

    def test_a_position_outside_the_frame_list_is_dropped_not_misattributed(self, wired):
        """A stray position must never be silently mapped onto the wrong frame."""
        model = FakeVideoModel({"monitor": {0: [_det(1)], 99: [_det(1)]}})
        body = _body(_run(_req(), model))
        assert body["concepts"][0]["n_detections"] == 1

    def test_mask_keys_name_the_capture_frame(self, wired):
        model = FakeVideoModel({"monitor": {1: [_det(5)]}})
        _run(_req(), model)
        blob = wired["scenes/s1/track_probe/monitor/masks.npz"][0]
        keys = set(np.load(io.BytesIO(blob)).files)
        assert "f000041_o0005" in keys

    def test_the_stored_raster_shape_travels_with_it(self, wired):
        """packbits is 1-D; without the shape nothing can unpack it."""
        model = FakeVideoModel({"monitor": {0: [_det(1)]}})
        _run(_req(), model)
        blob = wired["scenes/s1/track_probe/monitor/masks.npz"][0]
        loaded = np.load(io.BytesIO(blob))
        assert list(loaded["mask_shape"]) == [12, 16]
        packed = loaded["f000007_o0001"]
        assert np.unpackbits(packed)[: 12 * 16].reshape(12, 16).sum() == 4


class TestIdsAreScopedToTheConcept:
    def test_two_concepts_reusing_an_id_are_kept_apart(self, wired):
        """obj_id restarts per concept because the session holds one prompt. If
        the map ever keys on obj_id alone, these two collapse into one object —
        which is exactly the silent conflation 0271 names as worse than no map."""
        model = FakeVideoModel({
            "monitor": {0: [_det(1, area=500)]},
            "door": {1: [_det(1, area=900)]},
        })
        body = _body(_run(_req(concepts=["monitor", "door"]), model))
        by_concept = {c["concept"]: c for c in body["concepts"]}
        assert by_concept["monitor"]["objects"][0]["median_area_px"] == 500
        assert by_concept["door"]["objects"][0]["median_area_px"] == 900
        assert "scenes/s1/track_probe/monitor/tracks.json" in wired
        assert "scenes/s1/track_probe/door/tracks.json" in wired

    def test_a_multiword_concept_gets_its_own_directory(self, wired):
        model = FakeVideoModel({"table lamp": {0: [_det(1)]}})
        _run(_req(concepts=["table lamp"]), model)
        assert "scenes/s1/track_probe/table-lamp/tracks.json" in wired


# ── behaviour ────────────────────────────────────────────────────────────────


class TestTracking:
    def test_the_video_is_opened_once_for_many_concepts(self, wired):
        """Frame decode is the expensive part; N concepts must not cost N decodes."""
        model = FakeVideoModel({"monitor": {0: [_det(1)]}, "door": {0: [_det(2)]}})
        _run(_req(concepts=["monitor", "door"]), model)
        assert model.opens == 1
        assert model.tracked == ["monitor", "door"]

    def test_the_video_is_released_even_when_a_concept_raises(self, wired):
        model = FakeVideoModel({"monitor": {0: [_det(1)]}})
        body = _body(_run(_req(concepts=["explode", "monitor"]), model))
        assert model.closes == 1
        assert body["concepts"][0]["ok"] is False
        assert body["concepts"][1]["ok"] is True

    def test_default_is_every_frame_in_the_bundle(self, wired):
        model = FakeVideoModel({"monitor": {}})
        body = _body(_run(_req(), model))
        assert model.n_frames_opened == len(BUNDLE_FRAMES)
        assert body["n_frames"] == len(BUNDLE_FRAMES)

    def test_an_explicit_frame_list_is_honoured(self, wired):
        model = FakeVideoModel({"monitor": {}})
        body = _body(_run(_req(frame_indices=[41, 108]), model))
        assert body["frame_indices"] == [41, 108]

    def test_a_frame_that_will_not_download_is_reported_not_raised(self, wired, monkeypatch):
        import process_receiver as pr

        def flaky(uri):
            if "000042" in uri:
                raise RuntimeError("gone")
            return _jpeg()

        monkeypatch.setattr(pr, "_download_gcs_uri", flaky, raising=False)
        model = FakeVideoModel({"monitor": {}})
        body = _body(_run(_req(), model))
        assert body["frame_indices"] == [7, 41, 108]
        assert body["frame_failures"][0]["frame_index"] == 42

    def test_concepts_over_the_cap_are_named_not_silently_dropped(self, wired):
        asked = [f"c{i}" for i in range(tr.MAX_CONCEPTS_PER_CALL + 3)]
        model = FakeVideoModel({})
        body = _body(_run(_req(concepts=asked), model))
        assert len(body["concepts"]) == tr.MAX_CONCEPTS_PER_CALL
        assert body["concepts_dropped_over_cap"] == asked[tr.MAX_CONCEPTS_PER_CALL:]

    def test_duplicate_concepts_are_tracked_once(self, wired):
        model = FakeVideoModel({"monitor": {0: [_det(1)]}})
        _run(_req(concepts=["monitor", "monitor"]), model)
        assert model.tracked == ["monitor"]

    def test_objects_are_ordered_by_how_many_frames_hold_them(self, wired):
        model = FakeVideoModel({
            "monitor": {0: [_det(1), _det(2)], 1: [_det(2)], 2: [_det(2)]},
        })
        body = _body(_run(_req(), model))
        objs = body["concepts"][0]["objects"]
        assert [o["obj_id"] for o in objs] == [2, 1]
        assert [o["n_frames"] for o in objs] == [3, 1]

    def test_a_capture_with_no_usable_frame_says_so(self, wired, monkeypatch):
        import process_receiver as pr

        def bundle_ok_frames_gone(uri):
            # The bundle itself must still arrive; it is the FRAMES that are
            # unreachable. Failing both would test a different thing.
            if "/frames/" in uri:
                raise RuntimeError("gone")
            return b""

        monkeypatch.setattr(pr, "_download_gcs_uri", bundle_ok_frames_gone, raising=False)
        model = FakeVideoModel({})
        body = _body(_run(_req(), model))
        assert "no frame downloaded" in body["error"]
        assert model.opens == 0, "nothing should reach the GPU with no frames"


class TestRequestModel:
    def test_concepts_are_required(self):
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            tr.TrackRequest(scene_id="s", bundle_uri="gs://c/b.pb", concepts=[])

    def test_frame_indices_are_optional(self):
        assert tr.TrackRequest(
            scene_id="s", bundle_uri="gs://c/b.pb", concepts=["x"]
        ).frame_indices is None


# ── auth ─────────────────────────────────────────────────────────────────────


class TestOIDC:
    """These exist because their absence shipped a 500 on /segment (0260).

    Every other test here passes oidc_verifier=None, which skips the branch
    entirely — so on /segment the first live call crashed on
    `'Request' object has no attribute 'strip'`: verify() takes the HEADER
    VALUE, is not async, and raises rather than returning a response. A branch
    exercised only with the check disabled is untested.
    """

    def test_the_header_value_is_what_reaches_the_verifier(self, wired):
        seen = {}

        class V:
            def verify(self, header):
                seen["header"] = header

        model = FakeVideoModel({"monitor": {0: [_det(1)]}})
        resp = _run(_req(), model, verifier=V(), request=FakeRequest("Bearer tok-123"))
        assert seen["header"] == "Bearer tok-123"
        assert resp.status_code == 200

    def test_a_rejected_token_is_401_not_500(self, wired):
        from oidc import OIDCError

        class V:
            def verify(self, header):
                raise OIDCError("missing_token", "no Authorization header")

        model = FakeVideoModel({"monitor": {0: [_det(1)]}})
        resp = _run(_req(), model, verifier=V())
        assert resp.status_code == 401
        assert model.opens == 0, "a rejected request must not decode the capture"

    def test_the_real_verifier_rejects_a_missing_header_as_401(self, wired):
        """The strongest form: the production OIDCVerifier class, not a fake.

        A fake cannot catch a wrong argument TYPE, because a fake accepts
        anything. This calls the real `verify`, whose first act on a missing or
        malformed header is to raise OIDCError — so it proves the value handed
        over is one the real implementation can consume.
        """
        from oidc import OIDCVerifier

        verifier = OIDCVerifier(
            audience="https://example.invalid/track",
            allowed_email="tasks-invoker@roomstudio.iam.gserviceaccount.com",
        )
        model = FakeVideoModel({"monitor": {0: [_det(1)]}})
        resp = _run(_req(), model, verifier=verifier, request=FakeRequest())
        assert resp.status_code == 401
        assert model.opens == 0

    def test_the_real_verifier_rejects_a_malformed_bearer_as_401(self, wired):
        from oidc import OIDCVerifier

        verifier = OIDCVerifier(
            audience="https://example.invalid/track",
            allowed_email="tasks-invoker@roomstudio.iam.gserviceaccount.com",
        )
        model = FakeVideoModel({"monitor": {0: [_det(1)]}})
        resp = _run(
            _req(), model, verifier=verifier, request=FakeRequest("Bearer not-a-jwt")
        )
        assert resp.status_code == 401
        assert model.opens == 0
