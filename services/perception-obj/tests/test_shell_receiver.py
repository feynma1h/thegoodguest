"""/shell receiver invariants (decisions 0066/0069): the
absent-vs-unavailable contract, drain-vs-retry classification,
byte-determinism of shell.json v2, the measured-geometry immutability
pin, the no-texture serving contract, and the never-touch-Firestore
rule — against an in-memory GCS fake. No test touches the network.

Run: python -m pytest services/perception-obj/tests/test_shell_receiver.py
"""
from __future__ import annotations

import asyncio
import io
import json
import math
import time
from pathlib import Path

import numpy as np
import pytest
import shell_material
import shell_observation
import shell_receiver
from PIL import Image
from process_receiver import EnvironmentalError, PoisonError
from roomstudio_schemas import PLANE_HORIZONTAL, PLANE_VERTICAL, CaptureBundle
from shell_receiver import (
    ShellRequest,
    build_shell_json,
    handle_shell,
    run_shell,
    shell_json_bytes,
)

_SCENE = "11111111-2222-4333-8444-555555555555"
_BUCKET = "test-outputs"
_BUNDLE_URI = "gs://test-captures/captures/abc/bundle.pb"


# ---------------------------------------------------------------------------
# Fake GCS + deterministic classifier
# ---------------------------------------------------------------------------

class FakeGcs:
    """Dict-backed stand-in for the three process_receiver GCS helpers."""

    def __init__(self) -> None:
        self.blobs: dict[str, bytes] = {}  # "bucket/path" -> bytes

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
    """Deterministic stand-in for the vision call — the receiver tests
    must never reach the network."""
    return ("wood", 0.9) if kind == "floor" else ("painted", 0.85)


@pytest.fixture
def gcs(monkeypatch) -> FakeGcs:
    fake = FakeGcs()
    monkeypatch.setattr(shell_receiver, "_gcs_blob_exists_and_get", fake.exists_and_get)
    monkeypatch.setattr(shell_receiver, "_download_gcs_uri", fake.download)
    monkeypatch.setattr(shell_receiver, "_gcs_upload_for_scene", fake.upload)
    # Coarse texels: the synthetic planes are meters wide, tests stay fast.
    monkeypatch.setattr(shell_observation, "SHELL_METERS_PER_TEXEL", 0.25)
    monkeypatch.setattr(shell_observation, "SHELL_EVIDENCE_CROP_PX", 16)
    # No live vision calls, ever (also keeps determinism assertions exact).
    monkeypatch.setattr(shell_material, "classify_family_via_api", _fake_classify)
    return fake


# ---------------------------------------------------------------------------
# Synthetic scene: a floor + one wall, one complete frame observing both.
# The wall's detected bottom (-1.0) floats 0.4 above the floor (-1.4), so
# closure demonstrably extends it (measured_quad != quad in the doc).
# ---------------------------------------------------------------------------

_R = 1.0 / math.sqrt(2.0)


def _bundle_with_planes(
    *, planes: bool = True, frames: bool = True, door: bool = False
) -> CaptureBundle:
    b = CaptureBundle()
    b.schema_version = "1"
    b.bundle_id = "abc"
    if planes:
        floor = b.plane_anchors.add()
        floor.pose.pos_y = -1.4
        floor.pose.quat_w = 1.0
        floor.extent_width = 3.0
        floor.extent_height = 3.0
        floor.alignment = PLANE_HORIZONTAL
        floor.classification = "floor"
        wall = b.plane_anchors.add()
        # +90 deg about X: anchor +Y -> world +Z (wall at z=-1 facing +Z).
        wall.pose.pos_z = -1.0
        wall.pose.quat_x = _R
        wall.pose.quat_w = _R
        wall.extent_width = 3.0
        wall.extent_height = 2.0
        wall.alignment = PLANE_VERTICAL
        wall.classification = "wall"
        if door:
            d = b.plane_anchors.add()
            # Same plane as the wall; x in [-1.0, -0.2], y in [-1.0, 0.2].
            d.pose.pos_x = -0.6
            d.pose.pos_y = -0.4
            d.pose.pos_z = -1.0
            d.pose.quat_x = _R
            d.pose.quat_w = _R
            d.extent_width = 0.8
            d.extent_height = 1.2
            d.alignment = PLANE_VERTICAL
            d.classification = "door"
    if frames:
        f = b.frames.add()
        f.frame_index = 0
        f.rgb_gcs_path = "frames/000000.jpg"
        # Camera at (0, 0.4, 2.5) looking down -Z: sees the wall ahead and
        # the floor below.
        f.camera_pose.pos_y = 0.4
        f.camera_pose.pos_z = 2.5
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


def _masks_npz_bytes(n_masks: int = 0) -> bytes:
    buf = io.BytesIO()
    if n_masks:
        np.savez_compressed(buf, masks=np.zeros((n_masks, 64, 64), dtype=bool))
    else:
        np.savez_compressed(buf, masks=np.zeros((0,), dtype=bool))
    return buf.getvalue()


def _manifest(frames_complete: bool = True) -> dict:
    return {
        "scene_id": _SCENE,
        "manifest_version": 2,
        "frames": [
            {
                "frame_index": 0,
                "rgb_gcs_uri": "gs://test-captures/captures/abc/frames/000000.jpg",
                "masks_gcs_uri": f"gs://{_BUCKET}/scenes/{_SCENE}/frames/0000/masks.npz",
                **({} if frames_complete else {"budget_stopped": True}),
            }
        ],
    }


def _seed_ready_scene(gcs: FakeGcs, *, bundle: CaptureBundle | None = None) -> None:
    bundle = bundle or _bundle_with_planes()
    gcs.blobs["test-captures/captures/abc/bundle.pb"] = bundle.SerializeToString()
    gcs.blobs["test-captures/captures/abc/frames/000000.jpg"] = _rgb_png_bytes()
    gcs.blobs[f"{_BUCKET}/scenes/{_SCENE}/manifest.json"] = json.dumps(_manifest()).encode()
    gcs.blobs[f"{_BUCKET}/scenes/{_SCENE}/frames/0000/masks.npz"] = _masks_npz_bytes()


def _run(deadline=None) -> dict:
    return run_shell(
        scene_id=_SCENE, bundle_uri=_BUNDLE_URI,
        outputs_bucket=_BUCKET, deadline=deadline,
    )


def _shell_doc(gcs: FakeGcs) -> dict:
    return json.loads(gcs.blobs[f"{_BUCKET}/scenes/{_SCENE}/shell.json"])


# ---------------------------------------------------------------------------
# Happy path (v2)
# ---------------------------------------------------------------------------

class TestHappyPath:
    def test_ready_shell_written(self, gcs):
        _seed_ready_scene(gcs)
        body = _run()
        assert body == {"status": "ready", "reason": None}
        doc = _shell_doc(gcs)
        assert doc["shell_version"] == 2
        assert doc["status"] == "ready"
        assert doc["method"] == "arkit_planes"
        assert doc["floor"] is not None
        assert len(doc["walls"]) == 1
        assert doc["quality"]["frames_used"] == 1
        assert doc["quality"]["material_version"] == 1

    def test_no_texture_blobs_no_texture_uris(self, gcs):
        """The 0069 serving contract: no raster textures anywhere — no
        texture blob uploads, no texture_gcs_uri key in the doc."""
        _seed_ready_scene(gcs)
        _run()
        assert not any("shell/textures" in k for k in gcs.blobs)
        raw = gcs.blobs[f"{_BUCKET}/scenes/{_SCENE}/shell.json"]
        assert b"texture_gcs_uri" not in raw
        assert b"inpainted_fraction" not in raw

    def test_floor_entry_shape(self, gcs):
        _seed_ready_scene(gcs)
        _run()
        floor = _shell_doc(gcs)["floor"]
        assert len(floor["polygon"]) >= 3 and len(floor["polygon"][0]) == 3
        assert len(floor["measured_polygon"]) >= 3
        assert floor["y"] == pytest.approx(-1.4, abs=1e-3)
        assert len(floor["provenance"]["edges"]) == len(floor["polygon"])
        mat = floor["material"]
        # The camera grazes the floor: no tile clears the evidence gate,
        # so no crops -> family stays null (the wall test covers family
        # threading). The dict SHAPE is the contract here.
        assert set(mat) == {
            "family", "family_confidence", "albedo_hex", "secondary_hex",
            "params", "render", "source", "inference",
        }
        assert set(mat["source"]) == {"observed_fraction", "texel_count", "frames_used"}
        assert mat["inference"]["material_version"] == 1
        assert 0.0 <= mat["source"]["observed_fraction"] <= 1.0

    def test_wall_entry_shape_and_measured_immutability(self, gcs):
        """The wall's detected bottom is 0.4 above the floor: the rendered
        quad reaches the floor, the measured_quad stays detected — the
        0069 immutability pin at the DOC level."""
        _seed_ready_scene(gcs)
        _run()
        wall = _shell_doc(gcs)["walls"][0]
        assert wall["wall_id"] == "wall_00"
        assert wall["classification"] == "wall"
        rendered_ys = [c[1] for c in wall["quad"]]
        measured_ys = [c[1] for c in wall["measured_quad"]]
        assert min(rendered_ys) == pytest.approx(-1.4, abs=1e-3)
        assert min(measured_ys) == pytest.approx(-1.0, abs=1e-3)
        assert wall["edges"]["bottom"]["state"] == "extended_to_floor"
        assert wall["edges"]["bottom"]["extension_m"] == pytest.approx(0.4, abs=1e-3)
        assert wall["material"]["family"] == "painted"

    def test_door_member_ships_as_normalized_opening(self, gcs):
        _seed_ready_scene(gcs, bundle=_bundle_with_planes(door=True))
        _run()
        wall = _shell_doc(gcs)["walls"][0]
        assert wall["classification"] == "wall"  # majority of NON-opening members
        assert len(wall["openings"]) == 1
        op = wall["openings"][0]
        assert op["classification"] == "door"
        (u0, v0), (u1, v1) = op["rect_uv"]
        assert 0.0 <= u0 < u1 <= 1.0
        assert 0.0 <= v0 < v1 <= 1.0
        # The door starts AT the rendered bottom (the wall was extended
        # 0.4 down to the floor; the door's detected bottom sat at the
        # wall's detected bottom, so its v0 is the extension offset).
        assert v0 == pytest.approx(0.4 / 2.4, abs=0.02)

    def test_no_timestamps_and_byte_deterministic(self, gcs):
        _seed_ready_scene(gcs)
        _run()
        first = gcs.blobs[f"{_BUCKET}/scenes/{_SCENE}/shell.json"]
        # Fresh store, same inputs -> byte-identical shell.json.
        gcs.blobs.clear()
        _seed_ready_scene(gcs)
        _run()
        assert gcs.blobs[f"{_BUCKET}/scenes/{_SCENE}/shell.json"] == first


# ---------------------------------------------------------------------------
# Redelivery / noop paths (nothing written)
# ---------------------------------------------------------------------------

class TestNoopPaths:
    def test_current_version_present_noops(self, gcs):
        """Redelivery fast-path holds ONLY for a current-version shell."""
        _seed_ready_scene(gcs)
        existing = b'{"shell_version": 3, "status": "ready"}'
        gcs.blobs[f"{_BUCKET}/scenes/{_SCENE}/shell.json"] = existing
        body = _run()
        assert body == {"status": "noop", "reason": "already_present"}
        assert gcs.blobs[f"{_BUCKET}/scenes/{_SCENE}/shell.json"] == existing

    def test_stale_version_regenerates(self, gcs):
        """A pre-upgrade shell.json must NOT block the rewrite (found live
        at RP-8: v2 shells nooped the v3 --shell re-drives; the walk rooms
        kept furniture-slab arkit_planes walls until hand-deleted). The
        seeded scene is ARKIT_ONLY, so the regenerated doc is the CURRENT
        v2 closure output (degrade lock) — the pin is that the stale blob
        no longer gates, and current code's output replaces it."""
        import json as _json

        _seed_ready_scene(gcs)
        for stale in (b'{"shell_version": 2, "status": "ready"}',
                      b'{"existing": true}'):
            gcs.blobs[f"{_BUCKET}/scenes/{_SCENE}/shell.json"] = stale
            body = _run()
            assert body != {"status": "noop", "reason": "already_present"}
            written = gcs.blobs[f"{_BUCKET}/scenes/{_SCENE}/shell.json"]
            assert written != stale
            doc = _json.loads(written)
            assert doc.get("shell_version") == 2  # ARKIT_ONLY current output
            assert doc.get("status") in ("ready", "unavailable")

    def test_manifest_missing_noops_and_writes_nothing(self, gcs):
        _seed_ready_scene(gcs)
        del gcs.blobs[f"{_BUCKET}/scenes/{_SCENE}/manifest.json"]
        body = _run()
        assert body == {"status": "noop", "reason": "manifest_missing"}
        assert f"{_BUCKET}/scenes/{_SCENE}/shell.json" not in gcs.blobs

    def test_unparseable_bundle_noops_and_writes_nothing(self, gcs):
        _seed_ready_scene(gcs)
        gcs.blobs["test-captures/captures/abc/bundle.pb"] = b"\xff" * 64
        body = _run()
        assert body == {"status": "noop", "reason": "bundle_unparseable"}
        assert f"{_BUCKET}/scenes/{_SCENE}/shell.json" not in gcs.blobs


# ---------------------------------------------------------------------------
# Unavailable paths (a WRITTEN file, not an error)
# ---------------------------------------------------------------------------

class TestUnavailable:
    def test_bundle_swept_writes_capture_expired(self, gcs):
        _seed_ready_scene(gcs)
        del gcs.blobs["test-captures/captures/abc/bundle.pb"]
        body = _run()
        assert body == {"status": "unavailable", "reason": "capture_expired"}
        doc = _shell_doc(gcs)
        assert doc["status"] == "unavailable"
        assert doc["shell_version"] == 2
        assert doc["floor"] is None and doc["walls"] == []

    def test_no_plane_anchors_writes_no_geometry_source(self, gcs):
        _seed_ready_scene(gcs, bundle=_bundle_with_planes(planes=False))
        body = _run()
        assert body == {"status": "unavailable", "reason": "no_geometry_source"}
        assert _shell_doc(gcs)["reason"] == "no_geometry_source"

    def test_unusable_anchors_write_no_geometry_source(self, gcs):
        b = _bundle_with_planes(planes=False)
        speck = b.plane_anchors.add()
        speck.pose.quat_w = 1.0
        speck.extent_width = 0.1
        speck.extent_height = 0.1
        speck.alignment = PLANE_VERTICAL
        _seed_ready_scene(gcs, bundle=b)
        body = _run()
        assert body == {"status": "unavailable", "reason": "no_geometry_source"}
        assert _shell_doc(gcs)["quality"]["planes_in_bundle"] == 1

    def test_all_fragments_filtered_writes_no_geometry_source(self, gcs):
        """No floor + every vertical dropped by the fragment filter: the
        closure stats are recorded but nothing measured is shippable."""
        b = _bundle_with_planes(planes=False)
        frag = b.plane_anchors.add()
        # Unclassified 0.35 m² vertical, floating, no partners.
        frag.pose.pos_z = -1.0
        frag.pose.quat_x = _R
        frag.pose.quat_w = _R
        frag.extent_width = 0.7
        frag.extent_height = 0.5
        frag.alignment = PLANE_VERTICAL
        _seed_ready_scene(gcs, bundle=b)
        body = _run()
        assert body == {"status": "unavailable", "reason": "no_geometry_source"}
        doc = _shell_doc(gcs)
        assert doc["quality"]["fragments_dropped"] == 1
        assert doc["walls"] == []

    def test_all_rgb_swept_writes_capture_expired(self, gcs):
        _seed_ready_scene(gcs)
        del gcs.blobs["test-captures/captures/abc/frames/000000.jpg"]
        body = _run()
        assert body == {"status": "unavailable", "reason": "capture_expired"}

    def test_budget_stopped_frames_excluded(self, gcs):
        """A budget-stopped manifest frame has no masks.npz by contract —
        it must not be sampled; with no complete frames and no missing
        RGB the shell still writes (all planes unobserved, materials
        fully null: the clean-neutral treatment)."""
        _seed_ready_scene(gcs)
        gcs.blobs[f"{_BUCKET}/scenes/{_SCENE}/manifest.json"] = json.dumps(
            _manifest(frames_complete=False)
        ).encode()
        body = _run()
        assert body["status"] == "ready"
        doc = _shell_doc(gcs)
        assert doc["quality"]["frames_used"] == 0
        for entry in [doc["floor"], *doc["walls"]]:
            mat = entry["material"]
            assert mat["family"] is None
            assert mat["albedo_hex"] is None
            assert mat["source"]["observed_fraction"] == 0.0
            assert mat["inference"]["model"] is None


# ---------------------------------------------------------------------------
# Budget
# ---------------------------------------------------------------------------

class TestBudget:
    def test_exhausted_budget_is_environmental(self, gcs):
        _seed_ready_scene(gcs)
        with pytest.raises(EnvironmentalError):
            _run(deadline=time.monotonic() - 1.0)

    def test_generous_budget_completes(self, gcs):
        _seed_ready_scene(gcs)
        assert _run(deadline=time.monotonic() + 900)["status"] == "ready"


# ---------------------------------------------------------------------------
# handle_shell (route-level semantics)
# ---------------------------------------------------------------------------

def _fake_request(headers: dict | None = None):
    from fastapi import Request as _Request

    hdrs = {"content-type": "application/json", **(headers or {})}
    return _Request({
        "type": "http",
        "method": "POST",
        "path": "/shell",
        "headers": [(k.lower().encode(), v.encode()) for k, v in hdrs.items()],
        "query_string": b"",
    })


def _call_handle(oidc=None):
    async def _go():
        return await handle_shell(
            _fake_request(),
            ShellRequest(scene_id=_SCENE, bundle_uri=_BUNDLE_URI),
            oidc_verifier=oidc,
            outputs_bucket=_BUCKET,
        )

    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(_go())
    finally:
        loop.close()


class TestHandleShell:
    def test_oidc_reject_401(self, gcs):
        from oidc import OIDCError

        class RejectingVerifier:
            def verify(self, header):
                raise OIDCError("missing_token", "no Authorization header")

        resp = _call_handle(oidc=RejectingVerifier())
        assert resp.status_code == 401
        assert json.loads(resp.body)["error"] == "missing_token"

    def test_environmental_returns_500(self, gcs, monkeypatch):
        def _boom(**kwargs):
            raise EnvironmentalError("outputs bucket flaked")

        monkeypatch.setattr(shell_receiver, "run_shell", _boom)
        resp = _call_handle()
        assert resp.status_code == 500
        assert json.loads(resp.body)["status"] == "error"

    def test_poison_drains_200(self, gcs, monkeypatch):
        def _boom(**kwargs):
            raise PoisonError("frame image cannot be opened")

        monkeypatch.setattr(shell_receiver, "run_shell", _boom)
        resp = _call_handle()
        assert resp.status_code == 200
        assert json.loads(resp.body)["status"] == "failed"

    def test_happy_200(self, gcs):
        _seed_ready_scene(gcs)
        resp = _call_handle()
        assert resp.status_code == 200
        assert json.loads(resp.body)["status"] == "ready"


# ---------------------------------------------------------------------------
# Structural invariants
# ---------------------------------------------------------------------------

class TestStructuralInvariants:
    def test_never_touches_firestore_or_scene_state(self):
        """The 0066 hard rule: /shell never writes Scene state. Pinned at
        the import level — the module must import neither the receiver
        repo nor any firestore client, at module level OR deferred."""
        import ast

        tree = ast.parse(Path(shell_receiver.__file__).read_text())
        imported: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported += [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                imported.append(node.module or "")
                imported += [a.name for a in node.names]
        for name in imported:
            assert "firestore" not in name.lower(), name
            assert "receiver_repo" not in name, name
        # And none of the lease/state mutations appear as call names.
        calls = {
            node.func.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        }
        assert not calls & {"release_ready", "release_failed", "claim", "release_lease"}

    def test_shell_json_bytes_canonical(self):
        doc = build_shell_json(
            scene_id=_SCENE, status="unavailable", reason="no_geometry_source",
        )
        b1 = shell_json_bytes(doc)
        b2 = shell_json_bytes(json.loads(b1.decode()))
        assert b1 == b2
        assert b" " not in b1.split(b'"scene_id"')[0]  # compact separators

    def test_unavailable_doc_shape(self):
        doc = build_shell_json(
            scene_id=_SCENE, status="unavailable", reason="capture_expired",
        )
        assert doc == {
            "shell_version": 2,
            "scene_id": _SCENE,
            "status": "unavailable",
            "reason": "capture_expired",
            "method": "arkit_planes",
            "floor": None,
            "walls": [],
            "quality": {"planes_in_bundle": 0, "frames_used": 0},
        }
