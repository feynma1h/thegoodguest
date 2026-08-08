"""Pins for the /compress stage — the compressed-splat tier written
automatically for new captures (decisions 0125/0126; compress_receiver.py).

What these hold in place, in rough order of what would hurt most if it
broke:

  * The FALLBACK POSTURE. Every failure mode has to end at "this splat has
    no compressed tier", never at a failed scene or a corrupt index,
    because api-public's asset_urls never narrows and a missing entry
    already falls back to the PLY that has always been there. A splat that
    will not encode, a source that vanished, a corrupt prior index and a
    request that runs out of budget are each pinned to that outcome.
  * The RENDERED-SET rule, mirrored from assembleScene: unplaced objects
    are signed but never fetched, so compressing them would cost storage
    and buy nothing.
  * Idempotency by source generation — "already built against this exact
    source" vs "the source changed under us", which is the one hazard 0126
    named for a re-drive rewriting the same path.
  * manifest.json is never written. Single writer stays /process, and an
    index living inside the manifest would be erased by the next re-drive.

The encoder itself is NOT faked in test_encode_subprocess_contract: that
one drives the real tools/spz_encode.mjs through the real subprocess path,
because the contract between Python and Node (exit codes, stdout framing)
is exactly the part unit fakes would paper over. It skips when node or the
Spark build is absent.

Run from repo root:
    python -m pytest services/perception-obj/tests/test_compress_receiver.py -v
"""
from __future__ import annotations

import json
import shutil
import struct
import time
from pathlib import Path

import compress_receiver as cr
import pytest
from process_receiver import EnvironmentalError, PoisonError

REPO = Path(__file__).resolve().parents[3]
ENCODER = REPO / "tools" / "spz_encode.mjs"
SPARK = REPO / "web/node_modules/@sparkjsdev/spark/dist/spark.module.js"

_needs_encoder = pytest.mark.skipif(
    not (ENCODER.exists() and SPARK.exists() and shutil.which("node")),
    reason="needs node + web/node_modules (npm install --prefix web)",
)

BUCKET = "outputs-bucket"


def _manifest(*objects) -> dict:
    return {"manifest_version": 2, "objects": list(objects)}


def _obj(oid, uri, placed=True, transform=True):
    return {
        "object_id": oid,
        "splat_gcs_uri": uri,
        "placed": placed,
        "world_transform": {"position": [0, 0, 0]} if transform else None,
    }


def _uri(name: str) -> str:
    return f"gs://{BUCKET}/scenes/S/frames/0000/splats/{name}.ply"


class FakeGcs:
    """Stand-in for the outputs bucket: blob path -> bytes, with a
    generation that changes on every write (as GCS's does)."""

    def __init__(self, blobs: dict[str, bytes] | None = None):
        self.blobs = dict(blobs or {})
        self.generations = {k: f"g{i}" for i, k in enumerate(self.blobs)}
        self.writes: list[str] = []

    def get(self, bucket, path):
        assert bucket == BUCKET
        return self.blobs.get(path)

    def stat(self, bucket, path):
        assert bucket == BUCKET
        if path not in self.blobs:
            return None
        return len(self.blobs[path]), self.generations[path]

    def upload(self, prefix, path, data, content_type):
        self.blobs[path] = data
        self.generations[path] = f"g{len(self.writes)}w"
        self.writes.append(path)
        return f"gs://{BUCKET}/{path}"

    def index(self):
        raw = self.blobs.get("scenes/S/compressed.json")
        return json.loads(raw) if raw else None


@pytest.fixture
def gcs(monkeypatch):
    fake = FakeGcs()
    monkeypatch.setattr(cr, "_gcs_blob_exists_and_get", fake.get)
    monkeypatch.setattr(cr, "_stat", fake.stat)
    monkeypatch.setattr(cr, "_gcs_upload_for_scene", fake.upload)
    return fake


def _seed(gcs, manifest, splats: dict[str, bytes]):
    gcs.blobs["scenes/S/manifest.json"] = json.dumps(manifest).encode()
    gcs.generations["scenes/S/manifest.json"] = "gm"
    for uri, data in splats.items():
        path = uri[len(f"gs://{BUCKET}/"):]
        gcs.blobs[path] = data
        gcs.generations[path] = "gsrc"


def _fake_encode(monkeypatch, out=b"SPZ-BYTES", gaussians=7):
    calls = []

    def enc(ply_bytes, source_uri):
        calls.append(source_uri)
        return out, gaussians

    monkeypatch.setattr(cr, "encode_ply_bytes", enc)
    return calls


# ---------------------------------------------------------------------------
# The rendered set
# ---------------------------------------------------------------------------

class TestRenderedSet:
    def test_only_placed_objects_with_a_transform_and_a_splat(self):
        m = _manifest(
            _obj("a", _uri("a")),
            _obj("b", _uri("b"), placed=False),          # unplaced
            _obj("c", _uri("c"), transform=False),        # no transform
            {"object_id": "d", "placed": True, "world_transform": {}},  # no uri
        )
        assert cr.rendered_splat_uris(m) == [_uri("a")]

    def test_deduped_and_sorted(self):
        m = _manifest(_obj("a", _uri("z")), _obj("b", _uri("a")), _obj("c", _uri("z")))
        assert cr.rendered_splat_uris(m) == [_uri("a"), _uri("z")]

    def test_empty_manifest_is_not_an_error(self):
        assert cr.rendered_splat_uris({}) == []
        assert cr.rendered_splat_uris({"objects": None}) == []

    def test_spz_sibling_naming(self):
        assert cr.spz_uri_for(_uri("a")) == _uri("a")[:-4] + ".spz"
        assert cr.spz_uri_for("gs://b/x.bin") is None


# ---------------------------------------------------------------------------
# The happy path and its index
# ---------------------------------------------------------------------------

class TestBuild:
    def test_writes_an_spz_per_rendered_splat_plus_the_index(self, gcs, monkeypatch):
        _seed(gcs, _manifest(_obj("a", _uri("a")), _obj("b", _uri("b"))),
              {_uri("a"): b"PLY-A" * 10, _uri("b"): b"PLY-B" * 20})
        _fake_encode(monkeypatch)

        body = cr.run_compress(scene_id="S", outputs_bucket=BUCKET)

        assert body["status"] == "ready"
        assert body["built"] == 2 and body["failed"] == 0
        assert "scenes/S/frames/0000/splats/a.spz" in gcs.writes
        assert "scenes/S/frames/0000/splats/b.spz" in gcs.writes
        idx = gcs.index()
        assert idx["compressed_version"] == cr.INDEX_VERSION
        assert idx["format"] == "spz"
        assert set(idx["entries"]) == {_uri("a"), _uri("b")}
        e = idx["entries"][_uri("a")]
        assert e["uri"].endswith("a.spz")
        assert e["gaussians"] == 7
        assert e["source_bytes"] == 50 and e["source_generation"] == "gsrc"

    def test_never_writes_the_manifest(self, gcs, monkeypatch):
        _seed(gcs, _manifest(_obj("a", _uri("a"))), {_uri("a"): b"PLY"})
        _fake_encode(monkeypatch)
        cr.run_compress(scene_id="S", outputs_bucket=BUCKET)
        assert "scenes/S/manifest.json" not in gcs.writes

    def test_unplaced_splats_are_never_encoded(self, gcs, monkeypatch):
        _seed(gcs, _manifest(_obj("a", _uri("a")), _obj("b", _uri("b"), placed=False)),
              {_uri("a"): b"PLY-A", _uri("b"): b"PLY-B"})
        calls = _fake_encode(monkeypatch)
        cr.run_compress(scene_id="S", outputs_bucket=BUCKET)
        assert calls == [_uri("a")]


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------

class TestIdempotency:
    def test_second_run_is_a_noop(self, gcs, monkeypatch):
        _seed(gcs, _manifest(_obj("a", _uri("a"))), {_uri("a"): b"PLY"})
        calls = _fake_encode(monkeypatch)
        cr.run_compress(scene_id="S", outputs_bucket=BUCKET)
        body = cr.run_compress(scene_id="S", outputs_bucket=BUCKET)
        assert body["status"] == "noop" and body["reason"] == "already_current"
        assert len(calls) == 1  # not re-encoded

    def test_a_changed_source_is_rebuilt(self, gcs, monkeypatch):
        """0126's named hazard: a re-drive rewriting the SAME path with new
        content must not be served a stale SPZ."""
        _seed(gcs, _manifest(_obj("a", _uri("a"))), {_uri("a"): b"PLY"})
        calls = _fake_encode(monkeypatch)
        cr.run_compress(scene_id="S", outputs_bucket=BUCKET)
        gcs.generations["scenes/S/frames/0000/splats/a.ply"] = "gsrc2"
        cr.run_compress(scene_id="S", outputs_bucket=BUCKET)
        assert len(calls) == 2

    def test_force_rebuilds_a_current_entry(self, gcs, monkeypatch):
        _seed(gcs, _manifest(_obj("a", _uri("a"))), {_uri("a"): b"PLY"})
        calls = _fake_encode(monkeypatch)
        cr.run_compress(scene_id="S", outputs_bucket=BUCKET)
        cr.run_compress(scene_id="S", outputs_bucket=BUCKET, force=True)
        assert len(calls) == 2

    def test_a_corrupt_prior_index_is_rebuilt_not_raised(self, gcs, monkeypatch):
        _seed(gcs, _manifest(_obj("a", _uri("a"))), {_uri("a"): b"PLY"})
        gcs.blobs["scenes/S/compressed.json"] = b"{not json"
        _fake_encode(monkeypatch)
        body = cr.run_compress(scene_id="S", outputs_bucket=BUCKET)
        assert body["status"] == "ready" and body["built"] == 1
        assert set(gcs.index()["entries"]) == {_uri("a")}


# ---------------------------------------------------------------------------
# Degrade: every failure ends at "no compressed tier for that splat"
# ---------------------------------------------------------------------------

class TestDegrade:
    def test_no_manifest_drains(self, gcs):
        body = cr.run_compress(scene_id="S", outputs_bucket=BUCKET)
        assert body == {"status": "noop", "reason": "no_manifest", "scene_id": "S"}
        assert gcs.writes == []

    def test_no_rendered_splats_drains(self, gcs):
        _seed(gcs, _manifest(_obj("a", _uri("a"), placed=False)), {})
        body = cr.run_compress(scene_id="S", outputs_bucket=BUCKET)
        assert body["reason"] == "no_rendered_splats"
        assert gcs.writes == []

    def test_one_failing_splat_does_not_cost_the_others(self, gcs, monkeypatch):
        _seed(gcs, _manifest(_obj("a", _uri("a")), _obj("b", _uri("b"))),
              {_uri("a"): b"PLY-A", _uri("b"): b"PLY-B"})

        def enc(ply_bytes, source_uri):
            if source_uri == _uri("a"):
                raise EnvironmentalError("boom")
            return b"SPZ", 3

        monkeypatch.setattr(cr, "encode_ply_bytes", enc)
        body = cr.run_compress(scene_id="S", outputs_bucket=BUCKET)

        assert body["status"] == "ready"
        assert body["built"] == 1 and body["failed"] == 1
        # The index carries the one that worked and simply omits the other,
        # which is a PLY fallback for that object and nothing more.
        assert set(gcs.index()["entries"]) == {_uri("b")}

    def test_a_missing_source_is_counted_not_raised(self, gcs, monkeypatch):
        _seed(gcs, _manifest(_obj("a", _uri("a")), _obj("b", _uri("b"))),
              {_uri("a"): b"PLY-A"})  # b never written
        _fake_encode(monkeypatch)
        body = cr.run_compress(scene_id="S", outputs_bucket=BUCKET)
        assert body["missing_sources"] == 1 and body["built"] == 1

    def test_a_splat_in_another_bucket_is_skipped(self, gcs, monkeypatch):
        foreign = "gs://other-bucket/scenes/S/x.ply"
        _seed(gcs, _manifest(_obj("a", _uri("a")), _obj("b", foreign)),
              {_uri("a"): b"PLY-A"})
        calls = _fake_encode(monkeypatch)
        cr.run_compress(scene_id="S", outputs_bucket=BUCKET)
        assert calls == [_uri("a")]

    def test_budget_stop_ships_what_is_banked(self, gcs, monkeypatch):
        _seed(gcs, _manifest(_obj("a", _uri("a")), _obj("b", _uri("b"))),
              {_uri("a"): b"PLY-A", _uri("b"): b"PLY-B"})
        _fake_encode(monkeypatch)
        # A deadline already inside the reserve: no splat may start.
        body = cr.run_compress(
            scene_id="S", outputs_bucket=BUCKET,
            deadline=time.monotonic() + cr.COMPRESS_BUDGET_RESERVE_S - 1,
        )
        assert body["budget_stopped"] is True and body["built"] == 0
        # The index is still written, empty — every object falls back to PLY.
        assert gcs.index()["entries"] == {}

    def test_a_poison_encoder_is_not_swallowed(self, gcs, monkeypatch):
        """A broken IMAGE is different from a broken splat: retrying cannot
        help, and it must not look like a per-splat skip."""
        _seed(gcs, _manifest(_obj("a", _uri("a"))), {_uri("a"): b"PLY"})

        def enc(ply_bytes, source_uri):
            raise PoisonError("spz encoder unusable")

        monkeypatch.setattr(cr, "encode_ply_bytes", enc)
        with pytest.raises(PoisonError):
            cr.run_compress(scene_id="S", outputs_bucket=BUCKET)


# ---------------------------------------------------------------------------
# The Python <-> Node contract, against the REAL encoder
# ---------------------------------------------------------------------------

def _tiny_ply(n: int = 2) -> bytes:
    props = ['x', 'y', 'z', 'nx', 'ny', 'nz', 'f_dc_0', 'f_dc_1', 'f_dc_2',
             'opacity', 'scale_0', 'scale_1', 'scale_2',
             'rot_0', 'rot_1', 'rot_2', 'rot_3']
    hdr = (b'ply\nformat binary_little_endian 1.0\n'
           + f'element vertex {n}\n'.encode()
           + b''.join(f'property float {p}\n'.encode() for p in props)
           + b'end_header\n')
    return hdr + struct.pack(f'<{len(props) * n}f', *([0.1] * (len(props) * n)))


@_needs_encoder
class TestEncodeSubprocessContract:
    @pytest.fixture(autouse=True)
    def _encoder(self, monkeypatch):
        monkeypatch.setattr(cr, "SPZ_ENCODER", str(ENCODER))
        monkeypatch.setenv("SPARK_MODULE_PATH", str(SPARK))

    def test_real_encode_round_trips_the_gaussian_count(self):
        spz, gaussians = cr.encode_ply_bytes(_tiny_ply(3), "gs://b/x.ply")
        assert gaussians == 3
        assert len(spz) > 0

    def test_stdout_framing_survives_sparks_own_logging(self):
        """Spark writes a progress line of its own accord; the encoder sends
        it to stderr and Python reads the LAST stdout line. If either side
        regresses, this is where it shows."""
        spz, gaussians = cr.encode_ply_bytes(_tiny_ply(2), "gs://b/x.ply")
        assert gaussians == 2

    def test_a_non_ply_input_fails_environmentally_not_poison(self):
        """Bad bytes are this splat's problem, not the image's."""
        with pytest.raises(EnvironmentalError):
            cr.encode_ply_bytes(b"not a ply at all", "gs://b/x.ply")

    def test_a_missing_encoder_is_poison(self, monkeypatch):
        monkeypatch.setattr(cr, "SPZ_ENCODER", "/nonexistent/spz_encode.mjs")
        with pytest.raises(PoisonError):
            cr.encode_ply_bytes(_tiny_ply(), "gs://b/x.ply")

    def test_a_missing_node_is_poison(self, monkeypatch):
        monkeypatch.setattr(cr, "NODE_BIN", "/nonexistent/node")
        with pytest.raises(PoisonError):
            cr.encode_ply_bytes(_tiny_ply(), "gs://b/x.ply")

    def test_encoder_exits_2_on_a_missing_spark_build(self, monkeypatch):
        """The encoder's own 'cannot load Spark' exit — a setup error, which
        the receiver must read as poison rather than retry forever."""
        monkeypatch.setenv("SPARK_MODULE_PATH", "/nonexistent/spark.module.js")
        with pytest.raises(PoisonError):
            cr.encode_ply_bytes(_tiny_ply(), "gs://b/x.ply")


@_needs_encoder
class TestEndToEndThroughTheRealEncoder:
    def test_a_scene_builds_a_real_index(self, gcs, monkeypatch):
        """No encoder fake anywhere: the bytes in the index are bytes Spark
        actually produced."""
        monkeypatch.setattr(cr, "SPZ_ENCODER", str(ENCODER))
        monkeypatch.setenv("SPARK_MODULE_PATH", str(SPARK))
        _seed(gcs, _manifest(_obj("a", _uri("a"))), {_uri("a"): _tiny_ply(5)})

        body = cr.run_compress(scene_id="S", outputs_bucket=BUCKET)

        assert body["built"] == 1
        entry = gcs.index()["entries"][_uri("a")]
        assert entry["gaussians"] == 5
        assert entry["bytes"] == len(gcs.blobs["scenes/S/frames/0000/splats/a.spz"])


class TestEncoderIsShared:
    """The operator tool and this stage must not drift into two encoders —
    0126's writer/reader argument, applied writer-to-writer."""

    def test_the_tool_imports_the_shared_encoder(self):
        tool = (REPO / "tools" / "transcode_scene_splats.mjs").read_text()
        assert 'from "./spz_encode.mjs"' in tool
        assert "transcodeSpz" not in tool  # the encode lives in one file only

    def test_the_receiver_points_at_that_same_file(self):
        assert cr.SPZ_ENCODER.endswith("spz_encode.mjs")


class TestStructuralInvariants:
    """Mirrors /shell's pins (test_shell_receiver.py): the same hard rules
    apply, and pinning them structurally is what stops a future edit from
    quietly giving this stage the power to break a ready room."""

    def _imports_and_calls(self):
        import ast

        tree = ast.parse(Path(cr.__file__).read_text())
        imported: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported += [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                imported.append(node.module or "")
                imported += [a.name for a in node.names]
        calls = {
            node.func.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        }
        return imported, calls

    def test_never_touches_firestore_or_scene_state(self):
        imported, calls = self._imports_and_calls()
        for name in imported:
            assert "firestore" not in name.lower(), name
            assert "receiver_repo" not in name, name
        assert not calls & {"release_ready", "release_failed", "claim", "release_lease"}

    def test_never_loads_a_model(self):
        """A cold /compress must cost seconds, not the ~3.5 min a model load
        costs — the same reason /shell never touches the SAM accessors."""
        imported, _ = self._imports_and_calls()
        for name in imported:
            assert not name.startswith("models"), name
            assert name not in {"torch", "sam3", "sam3d"}, name

    def test_never_reads_the_captures_bucket(self):
        """Everything this stage needs is in the outputs bucket, so a swept
        capture (1-day lifecycle) is not a failure mode here."""
        imported, calls = self._imports_and_calls()
        # The two process_receiver helpers that reach an absolute gs:// URI
        # (i.e. the captures bucket) must not be imported OR called here.
        assert "_download_gcs_uri" not in imported and "_download_gcs_uri" not in calls
        assert "_bundle_prefix" not in imported and "_bundle_prefix" not in calls

    def test_index_version_matches_the_operator_tool(self):
        """Both writers produce the same document; a reader must not be able
        to tell which one wrote it."""
        tool = (REPO / "tools" / "transcode_scene_splats.mjs").read_text()
        assert f"const INDEX_VERSION = {cr.INDEX_VERSION};" in tool


class TestApiPublicContract:
    """The index is a CROSS-SERVICE contract and the two sides ship
    independently, so pin the shape against api-public's own source text —
    the 0089/0090 precedent for cross-service constants that must not
    drift. This side WRITES scenes/{id}/compressed.json; api-public READS
    it in the /scenes/{id}/assets handler and degrades to PLY on anything
    it does not recognise, which means a shape mistake here is silent: the
    room stays correct and stays slow.
    """

    @property
    def _api_public(self) -> str:
        p = REPO / "services" / "api-public" / "public_server.py"
        if not p.exists():
            pytest.skip("api-public not present in this checkout")
        return p.read_text()

    def test_reader_expects_the_blob_name_this_stage_writes(self):
        assert '"/compressed.json"' in self._api_public

    def test_reader_expects_a_top_level_entries_dict(self, gcs, monkeypatch):
        assert 'doc.get("entries")' in self._api_public
        # ...and that is exactly what this stage writes, checked against a
        # real index rather than against the source that produced it.
        _seed(gcs, _manifest(_obj("a", _uri("a"))), {_uri("a"): b"PLY"})
        _fake_encode(monkeypatch)
        cr.run_compress(scene_id="S", outputs_bucket=BUCKET)
        idx = gcs.index()
        assert isinstance(idx, dict) and isinstance(idx["entries"], dict)

    def test_reader_takes_the_spz_path_from_entry_uri(self):
        """The one field api-public actually consumes out of an entry. The
        rest (bytes/gaussians/source_*) exist for this side's idempotency
        and are deliberately ignored over there."""
        assert 'entry.get("uri")' in self._api_public

    def test_entries_are_keyed_by_the_manifest_splat_uri(self, gcs, monkeypatch):
        """api-public looks the entry up by the manifest's splat_gcs_uri, so
        the index must be keyed by the PLY URI — not by blob path, not by
        object_id."""
        assert "compressed_index.get(uri)" in self._api_public
        _seed(gcs, _manifest(_obj("a", _uri("a"))), {_uri("a"): b"PLY"})
        _fake_encode(monkeypatch)
        cr.run_compress(scene_id="S", outputs_bucket=BUCKET)
        assert list(gcs.index()["entries"]) == [_uri("a")]


# ---------------------------------------------------------------------------
# handle_compress (route-level semantics) — mirrors TestHandleShell
# ---------------------------------------------------------------------------

def _fake_request(headers: dict | None = None):
    from fastapi import Request as _Request

    hdrs = {"content-type": "application/json", **(headers or {})}
    return _Request({
        "type": "http",
        "method": "POST",
        "path": "/compress",
        "headers": [(k.lower().encode(), v.encode()) for k, v in hdrs.items()],
        "query_string": b"",
    })


def _call_handle(oidc=None, force=False):
    import asyncio

    async def _go():
        return await cr.handle_compress(
            _fake_request(),
            cr.CompressRequest(scene_id="S", force=force),
            oidc_verifier=oidc,
            outputs_bucket=BUCKET,
        )

    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(_go())
    finally:
        loop.close()


class TestHandleCompress:
    def test_oidc_reject_401(self, gcs):
        from oidc import OIDCError

        class Rejecting:
            def verify(self, header):
                raise OIDCError("missing_token", "no Authorization header")

        resp = _call_handle(oidc=Rejecting())
        assert resp.status_code == 401
        assert gcs.writes == []

    def test_success_200(self, gcs, monkeypatch):
        _seed(gcs, _manifest(_obj("a", _uri("a"))), {_uri("a"): b"PLY"})
        _fake_encode(monkeypatch)
        resp = _call_handle()
        assert resp.status_code == 200
        assert json.loads(resp.body)["status"] == "ready"

    def test_noop_drains_200(self, gcs):
        """No manifest: nothing to do and nothing a retry would find, so the
        task must DRAIN rather than be retried forever."""
        resp = _call_handle()
        assert resp.status_code == 200
        assert json.loads(resp.body)["reason"] == "no_manifest"

    def test_poison_drains_200(self, gcs, monkeypatch):
        """A broken image is poison: 200 so Cloud Tasks stops, and the room
        keeps rendering from PLY."""
        _seed(gcs, _manifest(_obj("a", _uri("a"))), {_uri("a"): b"PLY"})

        def enc(ply_bytes, source_uri):
            raise PoisonError("spz encoder unusable")

        monkeypatch.setattr(cr, "encode_ply_bytes", enc)
        resp = _call_handle()
        assert resp.status_code == 200
        assert json.loads(resp.body)["status"] == "failed"

    def test_environmental_retries_500(self, gcs, monkeypatch):
        _seed(gcs, _manifest(_obj("a", _uri("a"))), {_uri("a"): b"PLY"})
        monkeypatch.setattr(
            cr, "_gcs_upload_for_scene",
            lambda *a, **k: (_ for _ in ()).throw(EnvironmentalError("gcs down")),
        )
        _fake_encode(monkeypatch)
        resp = _call_handle()
        assert resp.status_code == 500

    def test_force_flag_reaches_the_core(self, gcs, monkeypatch):
        _seed(gcs, _manifest(_obj("a", _uri("a"))), {_uri("a"): b"PLY"})
        calls = _fake_encode(monkeypatch)
        _call_handle()
        _call_handle(force=True)
        assert len(calls) == 2
