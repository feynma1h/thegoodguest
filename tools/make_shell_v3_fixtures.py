"""Generate shell.json v3 dev fixtures for the web viewer (decision 0077).

Stages assets responses under gitignored web/public/dev-fixtures/ so
/viewer?fixture=<dir> renders every shell state offline:

  scene-roomplan-spike          v3 method "roomplan": the committed spike
                                CapturedRoom fixture (13 polygon walls incl.
                                wall_00's explicit 6-corner outline, the
                                10-corner floor polygon, parented door/
                                window/opening rects), materials observed
                                from the spike bundle's own RGB (albedo
                                measured; family null — no vision key
                                offline), three synthetic splats hand-placed
                                on the floor to exercise the reveal.
  scene-roomplan-spike-expired  same geometry, zero frames: every material
                                the honest empty observation (albedo null →
                                the neutral treatment) — the capture_expired
                                leg on v3 surfaces.
  scene-247003de-v3env          v3 method "anchor_envelope": the preserved
                                247003de bundle under the serving merge
                                calibration, which is also the code default;
                                manifest + object splat URLs reused verbatim
                                from the staged scene-247003de fixture (no
                                PLY copies).
  scene-shell-unavailable       a v2-shaped unavailable doc
                                (no_geometry_source) + two objects — the
                                keep-the-grid regression state.

Geometry goes through the MERGED perception-obj code verbatim — the exact
composition tests/test_shell_v3.py pins byte-deterministic
(parse_captured_room / roomplan_wall_pairs / assemble_shell /
derive_envelope / _observe_planes / _v3_* / build_shell_json_v3); nothing
here re-implements a shell decision. One dev-fixture deviation from
production: observation runs with EMPTY exclusion masks (no SAM masks
offline), so object pixels can tint albedos slightly; recorded per fixture
in the _fixture_provenance block (a top-level assets.json sibling the web
client ignores).

Run from repo root with the project venv (deterministic; ~1-2 min for the
observation walks):

    .venv/bin/python tools/make_shell_v3_fixtures.py

Requires outputs/roomplan-spike-bundle/ (regenerate with
tools/convert_roomplan_spike.py if absent — deterministic),
outputs/real-capture-247003de/, and the staged
web/public/dev-fixtures/scene-247003de/assets.json.

Consumers: the /viewer?fixture= dev workbench.
"""
from __future__ import annotations

import io
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "services" / "perception-obj"))

import room_planes  # noqa: E402
from roomplan_room import (  # noqa: E402
    parse_captured_room,
    roomplan_floor_geom,
    roomplan_primary_floor,
    roomplan_wall_pairs,
)
from thegoodguest_schemas import CaptureBundle  # noqa: E402
from shell_envelope import (  # noqa: E402
    derive_envelope,
    envelope_floor_geom,
    envelope_wall_geom,
)
from shell_geometry import assemble_shell  # noqa: E402
from shell_material import MATERIAL_VERSION  # noqa: E402
from shell_observation import FrameSample  # noqa: E402
from shell_receiver import (  # noqa: E402
    _observe_planes,
    _v3_envelope_planes,
    _v3_roomplan_planes,
    build_shell_json,
    build_shell_json_v3,
)

FIXTURES_DIR = REPO / "web" / "public" / "dev-fixtures"
SPIKE_ROOM_JSON = (
    REPO / "services" / "perception-obj" / "tests" / "fixtures"
    / "roomplan_spike" / "captured_room_built.json"
)
SPIKE_BUNDLE_DIR = REPO / "outputs" / "roomplan-spike-bundle"
CAPTURE_247_DIR = REPO / "outputs" / "real-capture-247003de"
STAGED_247_ASSETS = FIXTURES_DIR / "scene-247003de" / "assets.json"

EXPIRES = "2099-01-01T00:00:00+00:00"

# The serving merge calibration. These match room_planes' defaults, so the
# assignment below is a no-op today — it is kept because a staged fixture must
# reproduce what production renders even if a future default moves, and a
# silently-different fixture is worse than a redundant line.
SERVING_WALL_MERGE_GAP_M = 1.0
SERVING_WALL_NORMAL_TOL_DEG = 15.0


def _load_samples(capture_dir: Path, frame_indices: list[int]) -> list[FrameSample]:
    """FrameSamples for the given frame indices of a preserved capture dir
    (bundle.pb + frames/NNNNNN.jpg). Exclusion masks are EMPTY — no SAM
    masks exist offline (the recorded dev-fixture deviation)."""
    bundle = CaptureBundle()
    bundle.ParseFromString((capture_dir / "bundle.pb").read_bytes())
    by_index = {f.frame_index: f for f in bundle.frames}
    samples: list[FrameSample] = []
    for idx in frame_indices:
        frame = by_index.get(idx)
        jpg = capture_dir / "frames" / f"{idx:06d}.jpg"
        if frame is None or not jpg.exists():
            raise SystemExit(f"frame {idx} missing from {capture_dir}")
        rgb = np.asarray(Image.open(io.BytesIO(jpg.read_bytes())).convert("RGB"))
        samples.append(FrameSample(
            frame_index=idx,
            rgb=rgb,
            exclusion_mask=np.zeros(rgb.shape[:2], dtype=bool),
            pose=frame.camera_pose,
            intrinsics=frame.intrinsics,
        ))
    return samples


def _write_fixture(name: str, assets: dict) -> None:
    out_dir = FIXTURES_DIR / name
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "assets.json"
    path.write_text(json.dumps(assets, indent=1, sort_keys=True))
    print(f"wrote {path.relative_to(REPO)}")


def _synthetic_objects(floor_y: float, cx: float, cz: float) -> tuple[list, dict]:
    """Three synthetic splats (tools/make_synthetic_splat.py PLYs already at
    dev-fixtures root) hand-placed on the spike floor so the reveal has an
    objects phase. Positions are floor-centroid-relative; y mirrors the
    synthetic manifest's half-height convention."""
    spec = [
        ("sofa", (0.6, 0.35, 0.4), [0.0, 0.3826834, 0.0, 0.9238795], 1.4),
        ("table", (-0.7, 0.25, -0.5), [0.0, 0.0, 0.0, 1.0], 0.9),
        ("lamp", (1.2, 0.45, -0.9), [0.0, 0.0, 0.0, 1.0], 1.0),
    ]
    objects, urls = [], {}
    for i, (label, (dx, dy, dz), quat, scale) in enumerate(spec):
        uri = f"gs://fixture/roomplan-spike/{label}.ply"
        urls[uri] = f"/dev-fixtures/{label}.ply"
        objects.append({
            "object_id": f"obj_{i:03d}",
            "label": label,
            "placed": True,
            "method": "depth_fit",
            "splat_gcs_uri": uri,
            "world_transform": {
                "position": [cx + dx, floor_y + dy, cz + dz],
                "rotation_xyzw": quat,
                "scale": scale,
            },
        })
    return objects, urls


def make_roomplan_fixtures() -> None:
    scene_id = "roomplan-spike-c1d97365"
    room = parse_captured_room(SPIKE_ROOM_JSON.read_bytes())

    floor_geom = roomplan_floor_geom(room)
    floor_surface = roomplan_primary_floor(room)
    wall_pairs = roomplan_wall_pairs(room)
    planes: list[tuple[str, object, list | None]] = []
    if floor_geom is not None and floor_surface is not None:
        planes.append(("floor", floor_geom, [floor_surface.polygon_world]))
    for _surface, geom in wall_pairs:
        planes.append((geom.wall_id, geom, None))

    # Every 60th spike frame — 13 of 722; production observes the sampled
    # complete frames, this subset is the offline stand-in.
    frame_indices = list(range(0, 722, 60))
    variants = {
        "scene-roomplan-spike": _load_samples(SPIKE_BUNDLE_DIR, frame_indices),
        "scene-roomplan-spike-expired": [],
    }

    poly = floor_surface.polygon_world
    floor_y = float(poly[:, 1].mean())
    cx, cz = float(poly[:, 0].mean()), float(poly[:, 2].mean())
    objects, urls = _synthetic_objects(floor_y, cx, cz)

    for name, samples in variants.items():
        plane_results = _observe_planes(scene_id, planes, samples, None)
        floor_out, walls_out = _v3_roomplan_planes(room, plane_results)
        quality = {
            "roomplan": {
                "version": room.version,
                "source": "bundle",
                "walls": len(room.walls),
                "floors": len(room.floors),
                "doors": len(room.doors),
                "windows": len(room.windows),
                "openings": len(room.openings),
                "objects": len(room.objects),
            },
            "wall_count": len(walls_out),
            "frames_used": len(samples),
            "material_version": MATERIAL_VERSION,
        }
        if not samples:
            quality["materials_note"] = "capture_expired"
        doc = build_shell_json_v3(
            scene_id=scene_id, status="ready", reason=None, method="roomplan",
            floor=floor_out, walls=walls_out, quality=quality,
        )
        _write_fixture(name, {
            "scene_id": scene_id,
            "manifest": {
                "scene_id": scene_id,
                "manifest_version": 2,
                "frame_count": 722,
                "objects": objects,
            },
            "shell": doc,
            "asset_urls": urls,
            "expires_at": EXPIRES,
            "_fixture_provenance": {
                "generator": "tools/make_shell_v3_fixtures.py",
                "geometry": "committed spike CapturedRoom fixture through the "
                            "merged shell-v3 code path (verbatim)",
                "materials": (
                    "observed from outputs/roomplan-spike-bundle frames "
                    f"{frame_indices} with EMPTY exclusion masks (no SAM "
                    "masks offline); family null (no vision key)"
                    if samples else
                    "zero frames — the capture_expired leg (albedo null)"
                ),
                "objects": "synthetic splats hand-placed on the floor for "
                           "the reveal walk; NOT perception output",
            },
        })


def make_envelope_fixture() -> None:
    staged = json.loads(STAGED_247_ASSETS.read_text())
    scene_id = staged["scene_id"]

    # Pin the serving merge calibration explicitly (module attributes —
    # room_planes reads env at import time). Equal to the defaults today.
    room_planes.SHELL_WALL_MERGE_GAP_M = SERVING_WALL_MERGE_GAP_M
    room_planes.SHELL_WALL_NORMAL_TOL_DEG = SERVING_WALL_NORMAL_TOL_DEG

    bundle = CaptureBundle()
    bundle.ParseFromString((CAPTURE_247_DIR / "bundle.pb").read_bytes())
    geometry = assemble_shell(bundle.plane_anchors)
    envelope = derive_envelope(geometry)
    if envelope is None or not envelope.closed:
        raise SystemExit("247003de envelope did not close — knobs wrong?")

    planes: list[tuple[str, object, list | None]] = []
    if envelope.floor_y is not None and (envelope.closed or geometry.floor is not None):
        planes.append((
            "floor",
            envelope_floor_geom(envelope, geometry),
            geometry.floor_member_polygons or None,
        ))
    for ew in envelope.walls:
        planes.append((ew.wall_id, envelope_wall_geom(ew), None))

    frame_indices = staged["manifest"]["sampling"]["selected_frame_indices"]
    samples = _load_samples(CAPTURE_247_DIR, frame_indices)
    plane_results = _observe_planes(scene_id, planes, samples, None)
    floor_out, walls_out = _v3_envelope_planes(envelope, geometry, plane_results)

    quality = {
        **geometry.quality,
        **envelope.quality,
        "wall_count": len(walls_out),
        "frames_used": len(samples),
        "material_version": MATERIAL_VERSION,
    }
    doc = build_shell_json_v3(
        scene_id=scene_id, status="ready", reason=None,
        method="anchor_envelope",
        floor=floor_out, walls=walls_out, quality=quality,
    )
    _write_fixture("scene-247003de-v3env", {
        "scene_id": scene_id,
        "manifest": staged["manifest"],
        "shell": doc,
        "asset_urls": staged["asset_urls"],
        "expires_at": EXPIRES,
        "_fixture_provenance": {
            "generator": "tools/make_shell_v3_fixtures.py",
            "geometry": (
                "preserved outputs/real-capture-247003de bundle via "
                "assemble_shell + derive_envelope under the SERVING merge "
                f"knobs (gap={SERVING_WALL_MERGE_GAP_M}, "
                f"tol={SERVING_WALL_NORMAL_TOL_DEG})"
            ),
            "materials": (
                f"observed from capture frames {frame_indices} with EMPTY "
                "exclusion masks (no SAM masks offline); family null"
            ),
            "manifest": "reused verbatim from scene-247003de/assets.json "
                        "(same splat URLs; no PLY copies)",
        },
    })


def make_unavailable_fixture() -> None:
    staged = json.loads(STAGED_247_ASSETS.read_text())
    scene_id = "shell-unavailable-fixture"
    # Two real object splats reused by URL; the v2-shaped unavailable doc
    # comes from the real builder (build_shell_json), not a hand-written
    # imitation.
    objects = [o for o in staged["manifest"]["objects"] if o.get("placed")][:2]
    urls = {
        o["splat_gcs_uri"]: staged["asset_urls"][o["splat_gcs_uri"]]
        for o in objects
    }
    doc = build_shell_json(
        scene_id=scene_id, status="unavailable", reason="no_geometry_source",
    )
    _write_fixture("scene-shell-unavailable", {
        "scene_id": scene_id,
        "manifest": {
            "scene_id": scene_id,
            "manifest_version": 2,
            "objects": objects,
        },
        "shell": doc,
        "asset_urls": urls,
        "expires_at": EXPIRES,
        "_fixture_provenance": {
            "generator": "tools/make_shell_v3_fixtures.py",
            "shell": "v2-shaped unavailable doc via build_shell_json — the "
                     "keep-the-grid regression state",
            "objects": "two placed objects reused from scene-247003de",
        },
    })


def main() -> None:
    for path in (SPIKE_ROOM_JSON, SPIKE_BUNDLE_DIR / "bundle.pb",
                 CAPTURE_247_DIR / "bundle.pb", STAGED_247_ASSETS):
        if not path.exists():
            raise SystemExit(
                f"missing input: {path}\n(regenerate the spike bundle with "
                "tools/convert_roomplan_spike.py; the preserved captures and "
                "staged fixtures exist only in the main checkout)"
            )
    make_roomplan_fixtures()
    make_envelope_fixture()
    make_unavailable_fixture()


if __name__ == "__main__":
    main()
