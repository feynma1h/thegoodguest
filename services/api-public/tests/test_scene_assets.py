"""Tests for GET /scenes/{scene_id}/assets.

Covers:
  - 200 happy path: verbatim manifest passthrough, one signed URL per
    unique fused-object splat URI, expires_at ~1h out
  - splat-URI dedupe across fused objects
  - unplaced fused objects still get their splat signed (viewer may show
    them off to the side); objects without a splat URI are skipped
  - 409 scene_not_ready for every non-ready status (body carries status)
  - 401 / 400 / 403 / 404 mirroring the by-bundle contract
  - 502 upstream_error: manifest fetch failure, malformed JSON, signer
    failure

InMemoryManifestFetcher + a fake signer are injected; no GCS.

Run from repo root:
  pytest services/api-public/tests/test_scene_assets.py -v
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

import public_server as server
from auth import NullTokenVerifier  # noqa: E402
from public_server import InMemoryManifestFetcher  # noqa: E402
from roomstudio_api_core.scene import Scene, SceneStatus  # noqa: E402
from roomstudio_api_core.scene_read_repo import InMemorySceneReadRepository  # noqa: E402

_NOW = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
_MANIFEST_URI = "gs://outputs/scenes/s1/manifest.json"


class FakeSigner:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.calls: list[str] = []

    def sign(self, gs_uri: str, ttl_seconds: int) -> str:
        if self.fail:
            raise RuntimeError("signblob unavailable")
        self.calls.append(gs_uri)
        _, _, path = gs_uri[5:].partition("/")
        return f"https://signed.example/{path}?sig=abc"


def _scene(
    user_id: str | None = "user-abc",
    status: SceneStatus = SceneStatus.READY,
    result_uri: str | None = _MANIFEST_URI,
) -> Scene:
    bundle_id = str(uuid.uuid4())
    return Scene(
        scene_id=str(uuid.uuid4()),
        device_id="device-1",
        status=status,
        bundle_uri=f"gs://roomstudio-captures/captures/{bundle_id}/bundle.pb",
        created_at=_NOW,
        updated_at=_NOW,
        bundle_id=bundle_id,
        user_id=user_id,
        result_uri=result_uri if status == SceneStatus.READY else None,
    )


def _manifest(objects: list[dict] | None = None) -> dict:
    return {
        "scene_id": "s1",
        "manifest_version": 2,
        "objects": objects if objects is not None else [
            {
                "object_id": "obj_000",
                "label": "chair",
                "placed": True,
                "splat_gcs_uri": "gs://outputs/scenes/s1/frames/0000/splats/00_chair.ply",
            },
            {
                "object_id": "obj_001",
                "label": "lamp",
                "placed": False,
                "splat_gcs_uri": "gs://outputs/scenes/s1/frames/0001/splats/00_lamp.ply",
            },
        ],
        "frames": [],
    }


_SHELL_URI = "gs://outputs/scenes/s1/shell.json"


def _material(family: str | None = "painted") -> dict:
    return {
        "family": family,
        "family_confidence": 0.8 if family else None,
        "albedo_hex": "#aab9c3",
        "secondary_hex": None,
        "params": {},
        "render": {"roughness": 0.85},
        "source": {"observed_fraction": 0.5, "texel_count": 900, "frames_used": 3},
        "inference": {"model": "claude-sonnet-5" if family else None,
                      "material_version": 1},
    }


def _shell_doc() -> dict:
    """A shell.json v2 document (decision 0069): parametric materials,
    NO fetchable blobs — nothing here may join the signing walk."""
    return {
        "shell_version": 2,
        "scene_id": "s1",
        "status": "ready",
        "reason": None,
        "method": "arkit_planes",
        "floor": {
            "polygon": [[0, -1, 0], [2, -1, 0], [2, -1, 2], [0, -1, 2]],
            "measured_polygon": [[0, -1, 0], [2, -1, 0], [2, -1, 2], [0, -1, 2]],
            "y": -1.0,
            "provenance": {"edges": ["observed"] * 4},
            "material": _material("wood"),
        },
        "walls": [
            {
                "wall_id": "wall_00",
                "quad": [[0, -1.4, 0], [2, -1.4, 0], [2, 1, 0], [0, 1, 0]],
                "measured_quad": [[0, -1, 0], [2, -1, 0], [2, 1, 0], [0, 1, 0]],
                "edges": {
                    "bottom": {"state": "extended_to_floor", "extension_m": 0.4},
                    "top": {"state": "observed", "extension_m": 0.0},
                    "left": {"state": "observed", "extension_m": 0.0},
                    "right": {"state": "observed", "extension_m": 0.0},
                },
                "openings": [
                    {"classification": "door", "rect_uv": [[0.1, 0.0], [0.4, 0.8]]}
                ],
                "classification": "wall",
                "material": _material("painted"),
            }
        ],
        "quality": {"planes_in_bundle": 2, "frames_used": 3,
                    "material_version": 1},
    }


def _get_assets(
    client: TestClient,
    scene: Scene,
    uid: str = "user-abc",
    manifest_bytes: bytes | None = None,
    signer: FakeSigner | None = None,
    scene_id: str | None = None,
    headers: dict | None = None,
    shell_bytes: bytes | None = None,
    fetcher: InMemoryManifestFetcher | None = None,
):
    repo = InMemorySceneReadRepository({scene.scene_id: scene})
    fetcher = fetcher or InMemoryManifestFetcher()
    if manifest_bytes is not None:
        fetcher.store[_MANIFEST_URI] = manifest_bytes
    if shell_bytes is not None:
        fetcher.store[_SHELL_URI] = shell_bytes
    if headers is None:
        headers = {"Authorization": f"Bearer test-uid:{uid}"}
    with (
        patch.object(server, "_token_verifier", NullTokenVerifier()),
        patch.object(server, "_scene_read_repo", repo),
        patch.object(server, "_manifest_fetcher", fetcher),
        patch.object(server, "_url_signer", signer or FakeSigner()),
    ):
        return client.get(
            f"/scenes/{scene_id or scene.scene_id}/assets", headers=headers
        )


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(server.app)


class TestAssetsHappyPath:
    def test_manifest_passthrough_and_signed_urls(self, client) -> None:
        scene = _scene()
        manifest = _manifest()
        resp = _get_assets(client, scene, manifest_bytes=json.dumps(manifest).encode())
        assert resp.status_code == 200
        body = resp.json()
        assert body["scene_id"] == scene.scene_id
        assert body["manifest"] == manifest  # verbatim, not rewritten
        urls = body["asset_urls"]
        # Both fused objects' splats signed — including the unplaced one.
        assert set(urls) == {
            "gs://outputs/scenes/s1/frames/0000/splats/00_chair.ply",
            "gs://outputs/scenes/s1/frames/0001/splats/00_lamp.ply",
        }
        for gs_uri, https in urls.items():
            assert https.startswith("https://signed.example/")
        # expires_at is ISO 8601, ~1h out.
        expires = datetime.fromisoformat(body["expires_at"])
        delta = (expires - datetime.now(tz=timezone.utc)).total_seconds()
        assert 3500 < delta < 3700

    def test_duplicate_splat_uris_signed_once(self, client) -> None:
        shared = "gs://outputs/scenes/s1/frames/0000/splats/00_chair.ply"
        manifest = _manifest(objects=[
            {"object_id": "a", "splat_gcs_uri": shared},
            {"object_id": "b", "splat_gcs_uri": shared},
        ])
        signer = FakeSigner()
        resp = _get_assets(
            client, _scene(), manifest_bytes=json.dumps(manifest).encode(), signer=signer
        )
        assert resp.status_code == 200
        assert signer.calls == [shared]

    def test_objects_without_splat_uri_skipped(self, client) -> None:
        manifest = _manifest(objects=[{"object_id": "a", "splat_gcs_uri": None}])
        resp = _get_assets(client, _scene(), manifest_bytes=json.dumps(manifest).encode())
        assert resp.status_code == 200
        assert resp.json()["asset_urls"] == {}


class TestAssetsNotReady:
    @pytest.mark.parametrize("status", [
        SceneStatus.QUEUED,
        SceneStatus.PROCESSING,
        SceneStatus.FAILED,
        SceneStatus.FAILED_INCOMPLETE,
        SceneStatus.FAILED_INVALID,
    ])
    def test_non_ready_statuses_409(self, client, status) -> None:
        resp = _get_assets(client, _scene(status=status))
        assert resp.status_code == 409
        body = resp.json()
        assert body["error"] == "scene_not_ready"
        assert body["status"] == status.value

    def test_ready_without_result_uri_409(self, client) -> None:
        scene = _scene()
        scene.result_uri = None
        resp = _get_assets(client, scene)
        assert resp.status_code == 409


class TestAssetsAuthAndLookup:
    def test_non_bearer_401(self, client) -> None:
        resp = _get_assets(client, _scene(), headers={"Authorization": "Basic x"})
        assert resp.status_code == 401
        assert resp.json()["error"] == "missing_token"

    def test_invalid_token_401(self, client) -> None:
        resp = _get_assets(client, _scene(), headers={"Authorization": "Bearer nope"})
        assert resp.status_code == 401
        assert resp.json()["error"] == "invalid_token"

    def test_invalid_scene_id_400(self, client) -> None:
        resp = _get_assets(client, _scene(), scene_id="not-a-uuid")
        assert resp.status_code == 400
        assert resp.json()["error"] == "invalid_scene_id"

    def test_unknown_scene_404(self, client) -> None:
        resp = _get_assets(client, _scene(), scene_id=str(uuid.uuid4()))
        assert resp.status_code == 404
        assert resp.json()["error"] == "not_found"

    def test_wrong_owner_403(self, client) -> None:
        resp = _get_assets(client, _scene(user_id="someone-else"))
        assert resp.status_code == 403

    def test_unowned_scene_403(self, client) -> None:
        resp = _get_assets(client, _scene(user_id=None))
        assert resp.status_code == 403


class TestAssetsShellSibling:
    """The shell field (decisions 0066/0069): verbatim sibling, null when
    the blob is absent, contributing NOTHING to the signing walk."""

    def test_shell_absent_is_null(self, client) -> None:
        resp = _get_assets(
            client, _scene(), manifest_bytes=json.dumps(_manifest()).encode()
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["shell"] is None  # absent = not yet; NOT an error
        # And the manifest half is unaffected.
        assert set(body["asset_urls"]) == {
            "gs://outputs/scenes/s1/frames/0000/splats/00_chair.ply",
            "gs://outputs/scenes/s1/frames/0001/splats/00_lamp.ply",
        }

    def test_shell_present_verbatim_and_signs_nothing(self, client) -> None:
        """A v2 shell passes through byte-for-byte and adds no asset URLs
        — parametric materials have no fetchable blobs (0069)."""
        shell = _shell_doc()
        resp = _get_assets(
            client,
            _scene(),
            manifest_bytes=json.dumps(_manifest()).encode(),
            shell_bytes=json.dumps(shell).encode(),
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["shell"] == shell  # verbatim, not rewritten
        # The signing walk carries exactly the splats, nothing shell-borne.
        assert set(body["asset_urls"]) == {
            "gs://outputs/scenes/s1/frames/0000/splats/00_chair.ply",
            "gs://outputs/scenes/s1/frames/0001/splats/00_lamp.ply",
        }

    def test_unavailable_shell_passes_through(self, client) -> None:
        """status 'unavailable' is a real document the client must see —
        it is what stops the grace window."""
        shell = {
            "shell_version": 2,
            "scene_id": "s1",
            "status": "unavailable",
            "reason": "no_geometry_source",
            "method": "arkit_planes",
            "floor": None,
            "walls": [],
            "quality": {"planes_in_bundle": 0, "frames_used": 0},
        }
        resp = _get_assets(
            client,
            _scene(),
            manifest_bytes=json.dumps(_manifest()).encode(),
            shell_bytes=json.dumps(shell).encode(),
        )
        assert resp.status_code == 200
        assert resp.json()["shell"]["status"] == "unavailable"

    def test_legacy_texture_uris_no_longer_signed(self, client) -> None:
        """The v1 bake's texture_gcs_uri keys left the signing walk with
        0069 — even a stale v1 doc adds no URLs (population of ready v1
        shells is zero after the migration re-drive)."""
        shell = {
            "shell_version": 1,
            "scene_id": "s1",
            "status": "ready",
            "reason": None,
            "method": "arkit_planes",
            "floor": {
                "quad": [[0, -1, 0], [2, -1, 0], [2, -1, 2], [0, -1, 2]],
                "y": -1.0,
                "texture_gcs_uri": "gs://outputs/scenes/s1/shell/textures/floor.png",
                "observed_fraction": 0.8,
                "inpainted_fraction": 0.1,
                "source": "baked",
            },
            "walls": [],
            "quality": {"planes_in_bundle": 1, "frames_used": 3},
        }
        resp = _get_assets(
            client,
            _scene(),
            manifest_bytes=json.dumps(_manifest()).encode(),
            shell_bytes=json.dumps(shell).encode(),
        )
        assert resp.status_code == 200
        urls = resp.json()["asset_urls"]
        assert not any("shell/textures" in u for u in urls)

    def test_shell_fetch_error_degrades_to_null(self, client) -> None:
        """A flaking shell fetch must not 502 the room — the optional
        sibling degrades to null with a log."""

        class ExplodingShellFetcher(InMemoryManifestFetcher):
            def fetch_optional(self, gs_uri: str):
                raise server.ManifestFetchError("gcs flaked")

        fetcher = ExplodingShellFetcher()
        resp = _get_assets(
            client,
            _scene(),
            manifest_bytes=json.dumps(_manifest()).encode(),
            fetcher=fetcher,
        )
        assert resp.status_code == 200
        assert resp.json()["shell"] is None

    def test_malformed_shell_degrades_to_null(self, client) -> None:
        resp = _get_assets(
            client,
            _scene(),
            manifest_bytes=json.dumps(_manifest()).encode(),
            shell_bytes=b"not json {",
        )
        assert resp.status_code == 200
        assert resp.json()["shell"] is None


class TestAssetsUpstreamFailures:
    def test_missing_manifest_502(self, client) -> None:
        resp = _get_assets(client, _scene(), manifest_bytes=None)
        assert resp.status_code == 502
        assert resp.json()["error"] == "upstream_error"

    def test_malformed_manifest_502(self, client) -> None:
        resp = _get_assets(client, _scene(), manifest_bytes=b"not json {")
        assert resp.status_code == 502

    def test_signer_failure_502(self, client) -> None:
        resp = _get_assets(
            client,
            _scene(),
            manifest_bytes=json.dumps(_manifest()).encode(),
            signer=FakeSigner(fail=True),
        )
        assert resp.status_code == 502
        assert resp.json()["detail"] == "asset URL signing failed"
