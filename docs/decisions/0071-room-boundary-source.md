# 0071 — room-boundary source: raw plane anchors vs. RoomPlan vs. reconstructed geometry

**Date:** 2026-07-24
**Status:** OPEN — needs a strategy decision (do NOT treat as decided). Captured
here so the strategy session starts with the measured facts, not a blank page.
**2026-07-24 update:** operator is leaning **Option A (Pro-only / LiDAR-first)**
and has parked the non-LiDAR investment — see the Update section at the end.
Still OPEN.

## Context

The operator's real-room `/viewer` walks keep surfacing shell-geometry
failures the placement work does not touch: adjacent walls not perpendicular,
the floor rendering as a pentagon rather than a rectangle, one physical wall
split into two differently-coloured patches, and only ~2 of 4 walls visible.
The last is BY DESIGN (single-sided `THREE.FrontSide` walls =
dollhouse cutaway, `SplatViewer.tsx:258`; decision 0066). The other three are
real, and they raise a sharper question the operator posed directly: *we have
rich ARKit data and still can't reproduce the room boundaries — is the whole
approach too complex?* This note records what we found when we checked, and
the fork it forces. It does not decide it.

## What we found (measured, 2026-07-24)

- **We ship RAW `ARPlaneAnchor` data and re-derive the room on the server.**
  `capture_bundle.proto`'s `PlaneAnchor` (line 303) carries the raw ARKit
  plane fields verbatim: `center`, `extent`, `rotationOnYAxis`,
  `alignment`, `classification`, `boundaryVertices`. The server then
  reconstructs the room from those anchors: `room_planes.py` (floor
  selection, union-find wall merge, coplanar merge) and `shell_geometry.py`
  (envelope closure — extending walls to meet, Sutherland–Hodgman floor
  clipping). This is a hand-rolled reimplementation of room reconstruction.
- **Apple's RoomPlan already produces exactly that output, on-device.**
  `RoomCaptureSession` → `CapturedRoom` yields merged, SQUARED walls, a
  proper floor polygon, and doors/windows/openings as structured topology —
  the clean parametric room the server code is fighting to compute.
- **RoomPlan is scaffolded but never built.** The `LIDAR_ROOMPLAN` tier
  exists in the proto/enum, but `CaptureManager.swift:130` reads
  "LIDAR_ROOMPLAN is deferred" and there is no `import RoomPlan` anywhere in
  `ios/`. We built the enum slot for the right tool and then rebuilt the
  tool by hand.
- **RoomPlan requires LiDAR; the test device has none.** `iPhone17,5`
  (the device behind `25a14caf` and `f3d70236`) is non-LiDAR, and both real
  captures are `ARKIT_ONLY` — depth-free plane detection. Without depth,
  plane normals/extents are noisy and sparse: non-perpendicular walls, a
  skewed floor, and unmerged coplanar patches are the INHERENT ceiling of
  the input, not merely weak server code. `f3d70236` completed masks on only
  ~5 of 184 frames, compounding wall sparsity.

So the "blatant failure" decomposes into two separable things, and only one
is a code problem: (1) we are validating room boundaries on the WORST input
tier (non-LiDAR, no depth), where crisp boundaries are not recoverable in
principle; and (2) even once LiDAR exists, the design re-derives geometry
from raw anchors instead of taking RoomPlan's `CapturedRoom`.

## The fork (to be decided in the strategy session — NOT here)

- **A. LiDAR-first premium shell.** Adopt RoomPlan; ship `CapturedRoom`;
  delete most of `room_planes.py` + `shell_geometry.py`'s closure. Far
  better boundaries and a large simplification — but the crisp shell becomes
  a LiDAR-device (Pro) feature only.
- **B. Mass-market non-LiDAR must get a shell too.** Then depth-free plane
  anchors are a hard fidelity ceiling, and the honest moves are either don't
  promise a crisp shell on that tier, or derive the shell from RECONSTRUCTED
  geometry (SAM output / monocular depth) rather than raw planes. Grinding
  `room_planes.py` merge knobs is polishing the wrong input.
- **C. Hybrid.** RoomPlan when LiDAR is present; a deliberately humbler
  reconstructed-geometry shell (or none) on non-LiDAR — with the product
  language honest about the difference.

The choice is a product/strategy call (who the premium shell is FOR — LiDAR
Pro owners vs. every iPhone), not an engineering preference, which is why it
is parked for a strategy session rather than settled in a build session.

## What this does NOT change

- **The placement work is orthogonal and still lands.** The sanity gate and
  chunk D consume floor/wall PLANES, whoever produces them; RoomPlan would
  feed the same consumers BETTER planes. `contact_priors.py` /
  `room_planes.py`'s query surface stays; only the plane SOURCE is in
  question. The 2026-07-24 placement deploy is not wasted by any branch of
  this fork.
- **The dollhouse cutaway (2-of-4 walls) is not a bug** and is out of this
  fork's scope.

## What would change / decide this

- A strategy decision on who the premium shell serves (LiDAR-first vs.
  every-device) resolves the fork; this note flips to Superseded-by-that.
- If the product is LiDAR-first, a spike proving `RoomCaptureSession` can run
  ALONGSIDE the existing keyframe/pose/SAM capture (RoomPlan wraps an
  `ARSession`; the open question is co-running it with our frame accumulation
  and getting both `CapturedRoom` AND the RGB keyframes SAM needs) would
  de-risk option A before any deletion.
- If Apple ever brings RoomPlan (or an equivalent parametric room API) to
  non-LiDAR devices, option B's ceiling lifts and the fork collapses toward A.

## Update — 2026-07-24: operator pivot to Pro-only (leaning Option A)

After the non-LiDAR reference room (`f3d70236`) still read poorly on real
output, the operator chose to **pivot to a Pro-only / LiDAR-first pipeline for
now** and park further investment in the mass-market non-LiDAR shell +
placement. This points the fork at **Option A**, but is recorded as a *lean*,
not a settled decision — the fork is still to be resolved in a dedicated
strategy session, because A's headline simplification ("delete most of the
server geometry") is partly a mirage: `room_planes.py` now ALSO feeds placement
chunk D (`contact_priors.py`), so the anchor-interpretation module cannot be
fully deleted even if RoomPlan supersedes it as the shell's geometry source.
Only `shell_geometry.py`'s closure pass is a clean deletion candidate, and only
on the LiDAR tier.

The session that surfaced this also verified the enabling facts (chat history):
RoomPlan requires LiDAR (Pro-only; the test device `iPhone17,5` is non-LiDAR);
`RoomCaptureSession(arSession:)` co-runs with a custom
`ARWorldTrackingConfiguration` (iOS 17+) and yields BOTH `CapturedRoom` and the
RGB keyframes SAM needs — with a documented `sceneDepth`-strip caveat (workaround:
re-run a depth-enabled config in the `didStart` callback) and a known
ARFrame-retention memory issue. So Option A/C both need a **RoomPlan co-run
spike** on real Pro hardware to de-risk — folded into board item 3 (shared
blocker). No published figure was found for the LiDAR share of the installed
base, but non-LiDAR is the clear majority (LiDAR is Pro-only and began only with
the 12 Pro in late 2020); that directional fact is sufficient — the premium
shell's tier reaches a minority of users.

A higher-altitude question surfaced alongside and MUST be decided in the same
session: **recognition-first vs assembly-first.** Polycam produces recognisable
rooms on ANY phone (cloud photogrammetry / Gaussian splatting) by reconstructing
the whole scene as one frozen, furniture-included, textured artifact — the
opposite of this product's clean, decomposed, editable room. roomstudio
deliberately declined whole-scene reconstruction (0066/0069: the 900 s budget,
the empty-room-substrate need, decision 0001's razor, and the founding draft's
exclusion of photorealistic image generation). The open question is whether
recognisability should START from faithful capture (then decompose) or from
semantic assembly (accepting it won't look photographic, and that
recognisability is gated on object COVERAGE, not the shell). The pivot to
Pro-only does not by itself answer this — a LiDAR mesh is faithful-capture-shaped,
so the two questions are coupled.

**Concrete resume step:** acquire a LiDAR Pro device, run the RoomPlan co-run
spike (board item 3), then hold the strategy session to decide A-vs-C and
recognition-first-vs-assembly-first together.
