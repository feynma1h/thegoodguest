# 0320 — the boxes the person made ride in the capture bundle

**Date:** 2026-11-05
**Status:** Decided

## Context

Phase 2 builds the finished room automatically in the cloud, and the operator
decided the boxes the person makes on the phone (tap a dot, get a box; decisions
0295+) are the only object source: every boxed object gets a furniture model,
an unboxed one does not appear, and RoomPlan boxes are not used. Until now the
boxes lived only on the phone's screen ("they never enter the bundle", 0301),
so the cloud had no way to know them.

## What we tried

- A separate upload beside the bundle. One more blob to keep in step with the
  bundle (a bundle without its boxes is a scan with a silently different
  meaning), and one more thing for the upload code to retry.
- Reusing the RoomPlan object list. It is the model RoomPlan owns, its boxes
  have their own categories and conventions, and phase 1 removes them from play.

## What we chose

- `CaptureBundle.person_boxes` (field 13, additive, `schema_version` still
  "1" — the precedent is `plane_anchors`, field 12): a repeated `PersonBox` with
  an id, the detector's own class name, centre, yaw about world +Y, box-local
  size, and a creation time on the device-monotonic clock. The FINAL set only,
  serialized once at capture stop, in the world frame of the camera poses (the
  detector rides the capture's own ARSession, 0301). No pixels, no masks, no
  detector internals.
- Named `person_boxes`, not `boxes`, so it cannot be confused with the RoomPlan
  objects.
- A bundle without the field parses to an empty list; that is what old clients,
  and every Release build (live boxes is Debug-only, 0295), send.

## Why

The bundle is the one artefact that already carries everything the cloud needs
in one frame of reference; a box is a few numbers and costs nothing to ship.
Additive-with-no-bump keeps servers and clients upgradable in either order.

## What would change this decision

A need for anything pixel-shaped per box (a thumbnail, a mask) would justify a
separate blob; so would boxes becoming editable after the bundle is uploaded.
