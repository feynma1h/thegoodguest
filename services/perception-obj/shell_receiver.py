"""POST /shell receiver — the room-shell second stage (decisions 0066
architecture / 0069 parametric surfaces).

Enqueued by /process's success path after release_ready (fire-and-forget;
see shell_enqueue.py). Assembles the measured floor + wall set from the
bundle's plane anchors (room_planes via shell_geometry), closes the
envelope (0069: wall→floor, wall→wall seams, common top, floor snapped
and bounded to wall lines — joints, never loops), observes each plane
from the capture's own RGB (shell_observation), infers per-plane
parametric materials (shell_material: measured albedo + confidence-gated
family + roughness lookup), and writes ONE blob:

  gs://{PERCEPTION_OUTPUTS_BUCKET}/scenes/{scene_id}/shell.json

No raster textures exist in the serving contract (SHELL_VERSION 2 — the
photographic bake and its inpainting left serving per 0069; the viewer
renders materials from parameters). NEVER manifest.json (single writer
stays /process), NEVER Firestore — shell failure cannot un-ready a room,
and there is no scene lease: the shell.json write is a single idempotent
blob PUT, deterministic for identical inputs (the material vision call is
made at most once per plane per scene lifetime thanks to the write-once
noop; MATERIAL_VERSION + model are recorded in the doc).

The client-relied distinction (0066): shell.json ABSENT = not yet (keep
the grace window); status "unavailable" = never coming (stop waiting,
keep the grid). Unavailable is a WRITTEN file with a reason
("no_geometry_source" for pre-plane bundles / unusable anchors;
"capture_expired" when the captures bucket's 1-day lifecycle swept the
pixels), not an error.

Honesty invariants carried in the doc (0069, test-pinned): every wall
ships measured_quad (the DETECTED extent — what facts may read) beside
the rendered quad, with per-edge provenance; the floor ships
measured_polygon beside the rendered polygon with per-segment states;
closure never mutates measured geometry.

Response classification mirrors 0004's receiver semantics: completed
runs AND poison-class outcomes return 200 (Cloud Tasks drains);
environmental failures return 5xx (Cloud Tasks retries, maxAttempts=3).
A request-entry deadline (server.py, SHELL_REQUEST_BUDGET_SECONDS)
bounds the handler inside the Cloud Run request window; running out of
budget is environmental — the retry starts over.

reads: bundle proto (poses/intrinsics/plane_anchors) from the captures
bucket; manifest.json READ-ONLY for the complete-frame list; masks.npz
per complete frame and RGB per frame. No SAM model is ever touched on
this path — cold start is seconds.

Consumers: server.py (POST /shell), tests/test_shell_receiver.py.
"""
from __future__ import annotations

import asyncio
import io
import json
import logging
import time
from typing import Any

import numpy as np
from fastapi import Request
from fastapi.responses import JSONResponse
from process_receiver import (
    EnvironmentalError,
    PoisonError,
    _bundle_prefix,
    _download_gcs_uri,
    _gcs_blob_exists_and_get,
    _gcs_upload_for_scene,
)
from pydantic import BaseModel
from roomplan_room import (
    RoomPlanRoom,
    roomplan_floor_geom,
    roomplan_primary_floor,
    roomplan_wall_pairs,
    try_parse_captured_room,
)
from roomstudio_schemas import LIDAR_ARKIT, LIDAR_ROOMPLAN, CaptureBundle
from roomstudio_schemas.placement_math import resize_mask_to
from shell_envelope import (
    EnvelopeShell,
    derive_envelope,
    envelope_floor_geom,
    envelope_wall_geom,
)
from shell_geometry import (
    ShellClosure,
    ShellGeometry,
    _normalize_ccw_xz,
    assemble_shell,
    close_shell,
)
from shell_material import MATERIAL_VERSION, MaterialResult, infer_material
from shell_observation import FrameSample, ObservationResult, observe_plane

logger = logging.getLogger(__name__)

# v2: the ARKIT_ONLY closure shell (decision 0069) — untouched legacy shape.
SHELL_VERSION = 2
# v3: polygon-wall shells (decision 0077) — method "roomplan" (CapturedRoom
# geometry verbatim) and "anchor_envelope" (the LiDAR degrade envelope).
SHELL_VERSION_V3 = 3


def _room_json_cache_blob(scene_id: str) -> str:
    """Outputs-bucket blob where /process caches the bundle's verbatim
    CapturedRoom JSON on first read (decision 0077: geometry must survive
    the captures bucket's 1-day sweep — the 0065 sidecar lesson). /shell
    and warm re-drives read this copy."""
    return f"scenes/{scene_id}/roomplan/room.json"

# Seconds held back from the deadline before STARTING a plane's
# observation + inference: must cover one plane's worst case (projection
# over the complete frames plus one bounded vision call with a retry).
SHELL_BUDGET_RESERVE_S = 90.0


class ShellRequest(BaseModel):
    """Cloud Tasks payload for POST /shell — same shape as /process."""

    scene_id: str
    bundle_uri: str


# ---------------------------------------------------------------------------
# shell.json assembly (deterministic: no timestamps, canonical key order,
# rounded floats)
# ---------------------------------------------------------------------------

def _round4(values) -> list:
    return [round(float(v), 4) for v in values]


def _points(arr: np.ndarray) -> list[list[float]]:
    return [_round4(p) for p in arr]


def _material_dict(mat: MaterialResult, obs: ObservationResult) -> dict[str, Any]:
    params: dict[str, Any] = {}
    if mat.plank_direction_deg is not None:
        params["plank_direction_deg"] = mat.plank_direction_deg
    return {
        "family": mat.family,
        "family_confidence": mat.family_confidence,
        "albedo_hex": mat.albedo_hex,
        "secondary_hex": mat.secondary_hex,
        "params": params,
        "render": {"roughness": mat.roughness},
        "source": {
            "observed_fraction": obs.observed_fraction,
            "texel_count": obs.texel_count,
            "frames_used": obs.frames_used,
        },
        "inference": {"model": mat.model, "material_version": MATERIAL_VERSION},
    }


def build_shell_json(
    *,
    scene_id: str,
    status: str,
    reason: str | None,
    geometry: ShellGeometry | None = None,
    closure: ShellClosure | None = None,
    plane_results: dict[str, tuple[ObservationResult, MaterialResult]] | None = None,
    frames_used: int = 0,
) -> dict[str, Any]:
    """The shell.json v2 document. plane_results maps plane key ("floor" /
    wall_id) to (observation, material). Deterministic for identical
    inputs — no timestamps, floats rounded."""
    doc: dict[str, Any] = {
        "shell_version": SHELL_VERSION,
        "scene_id": scene_id,
        "status": status,
        "reason": reason,
        "method": "arkit_planes",
        "floor": None,
        "walls": [],
        "quality": {"planes_in_bundle": 0, "frames_used": frames_used},
    }
    if geometry is None:
        return doc

    quality: dict[str, Any] = {
        **geometry.quality,
        "frames_used": frames_used,
    }
    if closure is not None:
        quality.update(closure.quality)
        quality["walls_detected"] = geometry.quality["wall_count"]
        quality["wall_count"] = len(closure.walls)
        quality["dropped_wall_ids"] = list(closure.dropped_wall_ids)
        quality["material_version"] = MATERIAL_VERSION
    doc["quality"] = quality

    if closure is None or plane_results is None:
        # Geometry known but nothing shipped (an unavailable status that
        # still records quality counts) — floor/walls stay empty.
        return doc

    if (
        geometry.floor is not None
        and closure.floor_polygon_rendered is not None
        and "floor" in plane_results
    ):
        obs, mat = plane_results["floor"]
        doc["floor"] = {
            "polygon": _points(closure.floor_polygon_rendered),
            "measured_polygon": _points(closure.floor_polygon_measured),
            "y": round(float(geometry.floor.origin[1]), 4),
            "provenance": {"edges": list(closure.floor_edge_states)},
            "material": _material_dict(mat, obs),
        }

    for cw in closure.walls:
        geom = cw.geom
        obs, mat = plane_results[geom.wall_id]
        rw = float(np.linalg.norm(cw.rendered_corners[1] - cw.rendered_corners[0]))
        rh = float(np.linalg.norm(cw.rendered_corners[3] - cw.rendered_corners[0]))
        ext_left = cw.edges["left"].extension_m
        ext_bottom = cw.edges["bottom"].extension_m
        openings = []
        for op in geom.openings:
            openings.append({
                "classification": op.classification,
                "rect_uv": [
                    _round4([
                        np.clip((op.u0 + ext_left) / rw, 0.0, 1.0),
                        np.clip((op.v0 + ext_bottom) / rh, 0.0, 1.0),
                    ]),
                    _round4([
                        np.clip((op.u1 + ext_left) / rw, 0.0, 1.0),
                        np.clip((op.v1 + ext_bottom) / rh, 0.0, 1.0),
                    ]),
                ],
            })
        doc["walls"].append({
            "wall_id": geom.wall_id,
            "quad": _points(cw.rendered_corners),
            "measured_quad": _points(geom.corners_world),
            "edges": {
                name: {"state": e.state, "extension_m": round(e.extension_m, 4)}
                for name, e in cw.edges.items()
            },
            "openings": openings,
            "classification": geom.classification or None,
            "material": _material_dict(mat, obs),
        })
    return doc


def shell_json_bytes(doc: dict[str, Any]) -> bytes:
    """Canonical serialization — sorted keys, no whitespace jitter — so
    identical inputs produce byte-identical shell.json."""
    return json.dumps(doc, sort_keys=True, separators=(",", ":")).encode("utf-8")


# ---------------------------------------------------------------------------
# shell.json v3 (decision 0077): polygon walls, method-level provenance.
# No closure states — the roomplan method never closes (CapturedRoom arrives
# squared and full-height), and the envelope method records its derivation in
# provenance/quality instead of per-edge states.
# ---------------------------------------------------------------------------

def build_shell_json_v3(
    *,
    scene_id: str,
    status: str,
    reason: str | None,
    method: str,
    floor: dict[str, Any] | None = None,
    walls: list[dict[str, Any]] | None = None,
    quality: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """The shell.json v3 skeleton. Callers assemble floor/walls dicts via
    the _v3_* helpers; deterministic for identical inputs (no timestamps,
    rounded floats)."""
    return {
        "shell_version": SHELL_VERSION_V3,
        "scene_id": scene_id,
        "status": status,
        "reason": reason,
        "method": method,
        "floor": floor,
        "walls": walls or [],
        "quality": quality or {},
    }


def _rect_uv(u0: float, v0: float, u1: float, v1: float,
             width_m: float, height_m: float) -> list[list[float]]:
    """Normalize an opening rect (meters in a wall's rendered frame) to the
    0069 rect_uv shape, clipped to [0, 1]."""
    w = max(width_m, 1e-9)
    h = max(height_m, 1e-9)
    return [
        _round4([float(np.clip(u0 / w, 0.0, 1.0)), float(np.clip(v0 / h, 0.0, 1.0))]),
        _round4([float(np.clip(u1 / w, 0.0, 1.0)), float(np.clip(v1 / h, 0.0, 1.0))]),
    ]


def _wound_wall_polygon(surface, geom) -> np.ndarray:
    """A RoomPlan wall polygon wound so its front face is the room interior
    (the single-sided-rendering / dollhouse contract): CCW in the wall's
    interior-oriented (axis_u, axis_v) frame. Vertices are Apple's,
    verbatim; only the ORDER may reverse."""
    poly = surface.polygon_world
    u = (poly - geom.origin) @ geom.axis_u
    v = (poly - geom.origin) @ geom.axis_v
    area2 = float(np.dot(u, np.roll(v, -1)) - np.dot(np.roll(u, -1), v))
    return poly if area2 >= 0 else poly[::-1]


def _v3_roomplan_planes(
    room: RoomPlanRoom,
    plane_results: dict[str, tuple[ObservationResult, MaterialResult]],
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    """(floor dict, wall dicts) for the roomplan method. Geometry is the
    CapturedRoom's, verbatim (no closure ran; winding normalized only)."""
    floor_out = None
    floor_surface = roomplan_primary_floor(room)
    if floor_surface is not None and "floor" in plane_results:
        obs, mat = plane_results["floor"]
        poly = _normalize_ccw_xz(floor_surface.polygon_world)
        floor_out = {
            "polygon": _points(poly),
            "y": round(float(poly[:, 1].mean()), 4),
            "confidence": floor_surface.confidence,
            "provenance": {"source": "roomplan"},
            "material": _material_dict(mat, obs),
        }

    walls_out: list[dict[str, Any]] = []
    for surface, geom in roomplan_wall_pairs(room):
        obs, mat = plane_results[geom.wall_id]
        walls_out.append({
            "wall_id": geom.wall_id,
            "polygon": _points(_wound_wall_polygon(surface, geom)),
            "classification": surface.category,
            "confidence": surface.confidence,
            "openings": [
                {
                    "classification": op.classification,
                    "rect_uv": _rect_uv(
                        op.u0, op.v0, op.u1, op.v1, geom.width_m, geom.height_m
                    ),
                }
                for op in geom.openings
            ],
            "provenance": {"source": "roomplan"},
            "material": _material_dict(mat, obs),
        })
    return floor_out, walls_out


def _v3_envelope_planes(
    envelope: EnvelopeShell,
    geometry: ShellGeometry,
    plane_results: dict[str, tuple[ObservationResult, MaterialResult]],
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    """(floor dict, wall dicts) for the anchor_envelope method. Rendered
    geometry beside the measured (measured_quad / measured_polygon) — the
    0069 honesty invariant carried into v3."""
    floor_out = None
    measured_polygon = None
    if geometry.floor is not None and geometry.floor_member_polygons:
        base = max(
            geometry.floor_member_polygons,
            key=lambda p: abs(
                float(np.dot(p[:, 0], np.roll(p[:, 2], -1))
                      - np.dot(np.roll(p[:, 0], -1), p[:, 2]))
            ),
        )
        measured_polygon = _normalize_ccw_xz(np.asarray(base, dtype=np.float64))

    if "floor" in plane_results and envelope.floor_y is not None:
        obs, mat = plane_results["floor"]
        if envelope.closed and envelope.floor_corners is not None:
            floor_out = {
                "polygon": _points(envelope.floor_corners),
                "measured_polygon": (
                    _points(measured_polygon) if measured_polygon is not None else None
                ),
                "y": round(envelope.floor_y, 4),
                "provenance": {"source": "envelope_intersection"},
                "material": _material_dict(mat, obs),
            }
        elif measured_polygon is not None:
            floor_out = {
                "polygon": _points(measured_polygon),
                "measured_polygon": _points(measured_polygon),
                "y": round(envelope.floor_y, 4),
                "provenance": {"source": "detected_extent"},
                "material": _material_dict(mat, obs),
            }

    walls_out: list[dict[str, Any]] = []
    for ew in envelope.walls:
        obs, mat = plane_results[ew.wall_id]
        walls_out.append({
            "wall_id": ew.wall_id,
            "polygon": _points(ew.corners_world),
            "measured_quad": _points(ew.source.corners_world),
            "classification": ew.source.classification or None,
            "confidence": None,
            "openings": [
                {
                    "classification": op.classification,
                    "rect_uv": _rect_uv(
                        op.u0, op.v0, op.u1, op.v1, ew.width_m, ew.height_m
                    ),
                }
                for op in ew.openings
            ],
            "provenance": {
                "source": (
                    "anchor_envelope" if envelope.closed else "detected_extent"
                ),
                "merged_wall_id": ew.source.wall_id,
                "measured_width_m": round(ew.source.width_m, 4),
                "measured_height_m": round(ew.source.height_m, 4),
            },
            "material": _material_dict(mat, obs),
        })
    return floor_out, walls_out


# ---------------------------------------------------------------------------
# Frame loading
# ---------------------------------------------------------------------------

def _load_frame_samples(
    bundle: CaptureBundle, manifest: dict
) -> tuple[list[FrameSample], int]:
    """Build FrameSamples for the manifest's COMPLETE frames (entries
    without budget_stopped — the ones whose masks.npz exists).

    Returns (samples, rgb_missing_count). A frame whose masks or RGB blob
    is gone is skipped (logged); the caller decides whether zero usable
    frames means capture_expired.
    """
    by_index = {f.frame_index: f for f in bundle.frames}
    samples: list[FrameSample] = []
    rgb_missing = 0

    for entry in manifest.get("frames", []):
        if entry.get("budget_stopped"):
            continue
        idx = entry.get("frame_index")
        frame = by_index.get(idx)
        masks_uri = entry.get("masks_gcs_uri")
        if frame is None or not masks_uri:
            logger.warning("shell: frame %s unusable (no bundle frame/masks)", idx)
            continue

        try:
            rgb_bytes = _download_gcs_uri(entry["rgb_gcs_uri"])
        except PoisonError:
            rgb_missing += 1
            logger.info("shell: frame %s RGB swept by lifecycle", idx)
            continue

        from PIL import Image  # deferred: keep module import light

        try:
            rgb = np.asarray(Image.open(io.BytesIO(rgb_bytes)).convert("RGB"))
        except Exception as exc:
            raise PoisonError(
                f"shell: frame {idx} image cannot be opened: {exc}"
            ) from exc

        try:
            masks_bytes = _download_gcs_uri(masks_uri)
            with np.load(io.BytesIO(masks_bytes)) as npz:
                masks = npz["masks"]
        except PoisonError:
            logger.warning("shell: frame %s masks.npz missing; skipping frame", idx)
            continue

        if masks.ndim == 3 and masks.shape[0] > 0:
            exclusion = masks.any(axis=0)
            if exclusion.shape != rgb.shape[:2]:
                exclusion = resize_mask_to(
                    exclusion, (rgb.shape[1], rgb.shape[0])
                )
        else:
            exclusion = np.zeros(rgb.shape[:2], dtype=bool)

        samples.append(
            FrameSample(
                frame_index=idx,
                rgb=rgb,
                exclusion_mask=exclusion,
                pose=frame.camera_pose,
                intrinsics=frame.intrinsics,
            )
        )
    return samples, rgb_missing


# ---------------------------------------------------------------------------
# Core (sync; run via asyncio.to_thread from the route)
# ---------------------------------------------------------------------------

def _observe_planes(
    scene_id: str,
    planes: list[tuple[str, Any, list | None]],
    samples: list[FrameSample],
    deadline: float | None,
) -> dict[str, tuple[ObservationResult, MaterialResult]]:
    """Observation + material inference for a list of (key, geom, floor
    member polygons) planes — the budget-gated walk every ready path runs.
    With samples == [] (an expired capture whose geometry survived) each
    plane yields the honest empty observation: albedo null, family null —
    THE fallback rule's terminal case. Raises EnvironmentalError when the
    request budget runs out mid-walk."""
    plane_results: dict[str, tuple[ObservationResult, MaterialResult]] = {}
    for key, geom, polygons in planes:
        if deadline is not None and time.monotonic() > deadline - SHELL_BUDGET_RESERVE_S:
            # Out of request budget mid-run: environmental — the Cloud
            # Tasks retry redoes the (deterministic) work from the top.
            raise EnvironmentalError(
                f"shell budget exhausted before plane {key} "
                f"({len(plane_results)}/{len(planes)} inferred)"
            )
        obs = observe_plane(geom, samples, floor_member_polygons=polygons)
        kind = "floor" if key == "floor" else "wall"
        mat = infer_material(obs, kind)
        plane_results[key] = (obs, mat)
        logger.info(
            "shell: scene %s plane %s observed=%.3f texels=%d crops=%d "
            "family=%s albedo=%s",
            scene_id, key, obs.observed_fraction, obs.texel_count,
            len(obs.crops), mat.family, mat.albedo_hex,
        )
    return plane_results


def _read_manifest(scene_id: str, outputs_bucket: str) -> dict | None:
    """The scene manifest, read-only, or None when absent (the scene is not
    actually post-ready — mis-enqueued/mid-flight; callers noop)."""
    manifest_bytes = _gcs_blob_exists_and_get(
        outputs_bucket, f"scenes/{scene_id}/manifest.json"
    )
    if manifest_bytes is None:
        return None
    return json.loads(manifest_bytes)


def _run_shell_arkit_planes(
    *,
    scene_id: str,
    bundle: CaptureBundle,
    outputs_bucket: str,
    deadline: float | None,
    write,
) -> dict[str, Any]:
    """The v2 closure shell — the ARKIT_ONLY legacy path, byte-for-byte the
    pre-0077 behaviour (decision 0077 tier ladder: 'ARKIT_ONLY: legacy,
    fixtures only, untouched')."""
    # Pre-plane bundles (every capture before the wire change) → unavailable.
    if len(bundle.plane_anchors) == 0:
        return write(build_shell_json(
            scene_id=scene_id, status="unavailable", reason="no_geometry_source",
        ))

    manifest = _read_manifest(scene_id, outputs_bucket)
    if manifest is None:
        logger.warning("shell: scene %s has no manifest.json; noop", scene_id)
        return {"status": "noop", "reason": "manifest_missing"}

    geometry = assemble_shell(bundle.plane_anchors)
    if geometry.floor is None and not geometry.walls:
        return write(build_shell_json(
            scene_id=scene_id, status="unavailable", reason="no_geometry_source",
            geometry=geometry,
        ))

    closure = close_shell(geometry)
    if geometry.floor is None and not closure.walls:
        # Everything vertical was a filtered fragment and no floor exists:
        # nothing measured is shippable — same honest degrade as unusable
        # anchors, with the closure stats recorded.
        return write(build_shell_json(
            scene_id=scene_id, status="unavailable", reason="no_geometry_source",
            geometry=geometry, closure=closure,
        ))

    samples, rgb_missing = _load_frame_samples(bundle, manifest)
    if not samples and rgb_missing > 0:
        return write(build_shell_json(
            scene_id=scene_id, status="unavailable", reason="capture_expired",
            geometry=geometry, closure=closure,
        ))

    planes: list[tuple[str, Any, list | None]] = []
    if geometry.floor is not None:
        planes.append(("floor", geometry.floor, geometry.floor_member_polygons))
    for cw in closure.walls:
        planes.append((cw.geom.wall_id, cw.geom, None))

    plane_results = _observe_planes(scene_id, planes, samples, deadline)

    return write(build_shell_json(
        scene_id=scene_id, status="ready", reason=None,
        geometry=geometry, closure=closure, plane_results=plane_results,
        frames_used=len(samples),
    ))


def _run_shell_roomplan(
    *,
    scene_id: str,
    room: RoomPlanRoom,
    roomplan_source: str,  # "cached" | "bundle"
    bundle: CaptureBundle | None,  # None when the capture was swept
    outputs_bucket: str,
    deadline: float | None,
    write,
) -> dict[str, Any]:
    """shell.json v3, method "roomplan": CapturedRoom geometry verbatim
    (decision 0077 — closure retires on this tier). With bundle None (the
    1-day sweep took the capture) geometry still ships from the cached
    room.json and only materials are lost: every plane gets the honest
    empty observation (albedo null → the neutral treatment)."""
    materials_note = None
    if bundle is not None:
        manifest = _read_manifest(scene_id, outputs_bucket)
        if manifest is None:
            logger.warning("shell: scene %s has no manifest.json; noop", scene_id)
            return {"status": "noop", "reason": "manifest_missing"}
        samples, rgb_missing = _load_frame_samples(bundle, manifest)
        if not samples and rgb_missing > 0:
            materials_note = "capture_expired"
    else:
        samples = []
        materials_note = "capture_expired"

    floor_geom = roomplan_floor_geom(room)
    floor_surface = roomplan_primary_floor(room)
    wall_pairs = roomplan_wall_pairs(room)

    planes: list[tuple[str, Any, list | None]] = []
    if floor_geom is not None and floor_surface is not None:
        planes.append(("floor", floor_geom, [floor_surface.polygon_world]))
    for _surface, geom in wall_pairs:
        planes.append((geom.wall_id, geom, None))

    plane_results = _observe_planes(scene_id, planes, samples, deadline)
    floor_out, walls_out = _v3_roomplan_planes(room, plane_results)

    quality: dict[str, Any] = {
        "roomplan": {
            "version": room.version,
            "source": roomplan_source,
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
    if materials_note is not None:
        quality["materials_note"] = materials_note

    return write(build_shell_json_v3(
        scene_id=scene_id, status="ready", reason=None, method="roomplan",
        floor=floor_out, walls=walls_out, quality=quality,
    ))


def _run_shell_envelope(
    *,
    scene_id: str,
    bundle: CaptureBundle,
    outputs_bucket: str,
    deadline: float | None,
    write,
    roomplan_parse_failed: str | None = None,
) -> dict[str, Any]:
    """shell.json v3, method "anchor_envelope": the LiDAR degrade shell
    (decision 0077 — LIDAR_ARKIT bundles and roomplan-absent/unparseable
    LIDAR_ROOMPLAN bundles). Furniture-face planes are internal evidence,
    never rendered (the 0075 defect class closed by selection, not
    closure)."""
    base_quality: dict[str, Any] = {}
    if roomplan_parse_failed is not None:
        base_quality["roomplan_parse_failed"] = roomplan_parse_failed

    if len(bundle.plane_anchors) == 0:
        return write(build_shell_json_v3(
            scene_id=scene_id, status="unavailable", reason="no_geometry_source",
            method="anchor_envelope", quality=base_quality,
        ))

    geometry = assemble_shell(bundle.plane_anchors)
    envelope = derive_envelope(geometry)
    if envelope is None or (not envelope.walls and geometry.floor is None):
        return write(build_shell_json_v3(
            scene_id=scene_id, status="unavailable", reason="no_geometry_source",
            method="anchor_envelope",
            quality={**base_quality, **geometry.quality},
        ))

    manifest = _read_manifest(scene_id, outputs_bucket)
    if manifest is None:
        logger.warning("shell: scene %s has no manifest.json; noop", scene_id)
        return {"status": "noop", "reason": "manifest_missing"}

    samples, rgb_missing = _load_frame_samples(bundle, manifest)
    materials_note = None
    if not samples and rgb_missing > 0:
        # The RGB is gone but the anchors (in the bundle) still measure the
        # room: geometry ships, only materials are lost — unlike the v2
        # path, which had nothing left to ship without pixels.
        materials_note = "capture_expired"

    planes: list[tuple[str, Any, list | None]] = []
    if envelope.floor_y is not None and (
        envelope.closed or geometry.floor is not None
    ):
        planes.append((
            "floor",
            envelope_floor_geom(envelope, geometry),
            geometry.floor_member_polygons or None,
        ))
    for ew in envelope.walls:
        planes.append((ew.wall_id, envelope_wall_geom(ew), None))

    plane_results = _observe_planes(scene_id, planes, samples, deadline)
    floor_out, walls_out = _v3_envelope_planes(envelope, geometry, plane_results)

    quality: dict[str, Any] = {
        **base_quality,
        **geometry.quality,
        **envelope.quality,
        "wall_count": len(walls_out),
        "frames_used": len(samples),
        "material_version": MATERIAL_VERSION,
    }
    if materials_note is not None:
        quality["materials_note"] = materials_note

    return write(build_shell_json_v3(
        scene_id=scene_id, status="ready", reason=None, method="anchor_envelope",
        floor=floor_out, walls=walls_out, quality=quality,
    ))


def run_shell(
    *,
    scene_id: str,
    bundle_uri: str,
    outputs_bucket: str,
    deadline: float | None,
) -> dict[str, Any]:
    """Produce shell.json for one scene. Returns the response body.
    Raises EnvironmentalError for retryable failures.

    Tier dispatch (decision 0077): a parseable CapturedRoom (cached copy
    first, then the bundle's blob) → method "roomplan"; LiDAR bundles
    without one → method "anchor_envelope" (incl. the roomplan_parse_failed
    degrade — NEVER a failure); ARKIT_ONLY → the untouched v2 closure
    path."""
    shell_blob = f"scenes/{scene_id}/shell.json"

    # Redelivery fast-path: the output is deterministic, so an existing
    # shell.json (ready OR unavailable — neither changes on re-run: the
    # bundle is immutable and swept pixels never return) means done.
    if _gcs_blob_exists_and_get(outputs_bucket, shell_blob) is not None:
        logger.info("shell: scene %s already has shell.json; noop", scene_id)
        return {"status": "noop", "reason": "already_present"}

    def _write(doc: dict[str, Any]) -> dict[str, Any]:
        _gcs_upload_for_scene(
            f"gs://{outputs_bucket}/", shell_blob, shell_json_bytes(doc),
            "application/json",
        )
        logger.info(
            "shell: scene %s wrote shell.json status=%s reason=%s",
            scene_id, doc["status"], doc["reason"],
        )
        return {"status": doc["status"], "reason": doc["reason"]}

    # Bundle: gone (1-day lifecycle). A cached room.json (written by
    # /process on the ROOMPLAN tier) still carries the geometry — capture
    # expiry costs materials only (decision 0077). Without it: unavailable,
    # exactly as before.
    try:
        raw = _download_gcs_uri(bundle_uri)
    except PoisonError:
        cached = _gcs_blob_exists_and_get(
            outputs_bucket, _room_json_cache_blob(scene_id)
        )
        if cached is not None:
            room, parse_reason = try_parse_captured_room(cached)
            if room is not None and room.has_geometry:
                return _run_shell_roomplan(
                    scene_id=scene_id, room=room, roomplan_source="cached",
                    bundle=None, outputs_bucket=outputs_bucket,
                    deadline=deadline, write=_write,
                )
            logger.warning(
                "shell: scene %s cached room.json unusable (%s); "
                "capture_expired", scene_id, parse_reason,
            )
        return _write(build_shell_json(
            scene_id=scene_id, status="unavailable", reason="capture_expired",
        ))
    bundle = CaptureBundle()
    try:
        bundle.ParseFromString(raw)
    except Exception as exc:
        # Post-ready corrupt bundle: ingest validated it and /process
        # parsed it, so this is an operator-visible anomaly, not a state
        # to persist. Drain with a log; write nothing.
        logger.error("shell: scene %s bundle unparseable: %s", scene_id, exc)
        return {"status": "noop", "reason": "bundle_unparseable"}

    # CapturedRoom lookup: cached copy first (deterministic across
    # re-drives, sweep-proof), then the bundle's own blob.
    room = None
    parse_reason: str | None = None
    room_bytes = _gcs_blob_exists_and_get(
        outputs_bucket, _room_json_cache_blob(scene_id)
    )
    roomplan_source = "cached"
    if room_bytes is None and bundle.HasField("room_plan") and bundle.room_plan.json_gcs_path:
        roomplan_source = "bundle"
        try:
            room_bytes = _download_gcs_uri(
                _bundle_prefix(bundle_uri) + bundle.room_plan.json_gcs_path
            )
        except PoisonError:
            room_bytes = None
            parse_reason = "room_json_missing"
    if room_bytes is not None:
        room, reason = try_parse_captured_room(room_bytes)
        if room is not None and not room.has_geometry:
            room, reason = None, "no walls or floor in CapturedRoom"
        if room is None:
            parse_reason = reason

    if room is not None:
        return _run_shell_roomplan(
            scene_id=scene_id, room=room, roomplan_source=roomplan_source,
            bundle=bundle, outputs_bucket=outputs_bucket,
            deadline=deadline, write=_write,
        )

    if bundle.tier in (LIDAR_ARKIT, LIDAR_ROOMPLAN):
        if parse_reason is not None:
            # The 0077 degrade lock: a ROOMPLAN bundle whose room.json is
            # missing/corrupt gets LIDAR_ARKIT semantics + a structured
            # log — never a failure.
            logger.warning(
                "shell: scene %s roomplan_parse_failed reason=%s; "
                "degrading to anchor_envelope", scene_id, parse_reason,
            )
        return _run_shell_envelope(
            scene_id=scene_id, bundle=bundle, outputs_bucket=outputs_bucket,
            deadline=deadline, write=_write,
            roomplan_parse_failed=parse_reason,
        )

    return _run_shell_arkit_planes(
        scene_id=scene_id, bundle=bundle, outputs_bucket=outputs_bucket,
        deadline=deadline, write=_write,
    )


# ---------------------------------------------------------------------------
# Route handler (registered in server.py)
# ---------------------------------------------------------------------------

async def handle_shell(
    request: Request,
    req: ShellRequest,
    *,
    oidc_verifier,  # OIDCVerifier | None (None disables auth, for tests)
    outputs_bucket: str,
    deadline: float | None = None,
) -> JSONResponse:
    """Core handler for POST /shell. No scene lease, no Firestore — see the
    module docstring. The sync core runs off the event loop so /health
    stays responsive during the observation + inference walk."""
    from oidc import OIDCError

    if oidc_verifier is not None:
        try:
            oidc_verifier.verify(request.headers.get("Authorization"))
        except OIDCError as exc:
            logger.warning("shell OIDC rejected: %s %s", exc.code, exc.detail)
            return JSONResponse(
                status_code=401,
                content={"error": exc.code, "detail": exc.detail},
            )

    try:
        body = await asyncio.to_thread(
            run_shell,
            scene_id=req.scene_id,
            bundle_uri=req.bundle_uri,
            outputs_bucket=outputs_bucket,
            deadline=deadline,
        )
    except PoisonError as exc:
        # Poison drains: retrying cannot change the outcome.
        logger.error("shell: poison failure for scene %s: %s", req.scene_id, exc)
        return JSONResponse({"status": "failed", "reason": str(exc)})
    except EnvironmentalError as exc:
        logger.error("shell: environmental failure for scene %s: %s", req.scene_id, exc)
        return JSONResponse(status_code=500, content={"status": "error", "reason": str(exc)})
    except Exception as exc:
        logger.exception("shell: unexpected failure for scene %s", req.scene_id)
        return JSONResponse(status_code=500, content={"status": "error", "reason": str(exc)})

    return JSONResponse(body)
