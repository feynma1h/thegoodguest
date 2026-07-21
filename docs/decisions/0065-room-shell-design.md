# 0065 — Room shell: measured planes on the wire, textured-quad shell as a second perception stage

**Date:** 2026-07-22
**Status:** Decided (design; implementation pending — build brief at
`docs/briefs/room-shell-build-brief.md` until it ships)

## Context

Perception places objects in the ARKit world frame (0052) but nothing renders
walls or floor — rooms are furniture on a grid. CLAUDE.md has carried
"inpainted scene-3DGS" as the intended approach since the surface descriptions
were written, but nothing was ever designed; this note is that design session,
run 0058-style: forks locked, named rejections recorded, a build brief handed
off. The product need is sharper than "walls render": the founding thesis
(0055) makes the shell the **redesign substrate** — the room, emptied, that
objects can be moved through and conversed about — so the shell must be (a)
object-free, (b) honest about what was measured vs filled in, and (c) cheap
enough to exist inside the deployed budget reality (0060–0062: 900 s request
window, ~3.5 min cold model load, the verification run finished with ~58 s
spare).

Grounding facts this design leans on: the only tier verified end-to-end is
ARKIT_ONLY, which carries **no geometry at all** — no depth, no RoomPlan, and
the proto's per-frame feature-point/mesh-anchor fields are reserved, unused.
The real capture (scene `25a14caf`: 126 keyframes, 12 sampled, 4 complete
frames, 19 fused objects, 2 placed) is the reference workload. SAM 3 masks
(`masks.npz`) are cached in GCS for exactly the frames that completed in full.
The captures bucket has a 1-day lifecycle rule. The viewer's input contract is
`PositionedSplat[]` (0053), Spark was chosen explicitly for mixed
splat-plus-mesh scenes, and the grid stage is already a textured three.js
plane (`depthWrite: false`, so mixed depth compositing is NOT yet proven in
our tree). The 0063 layout-convention probe is live in a parallel session;
this design is written to be independent of its verdict (see below).

## What we tried / rejected (named rejections — do not re-explore without new facts)

- **Per-capture scene-3DGS training** (the literal reading of CLAUDE.md's
  "inpainted scene-3DGS") — rejected on four grounds. (1) 3DGS optimization is
  tens of GPU-minutes per room: it fits no 900 s request and would force a new
  infra class (Cloud Run jobs / a long-timeout service) for the first feature
  to need one. (2) The trained splat **contains the furniture**; producing the
  empty-room substrate from it means segmentation-aware training plus 3D
  inpainting — research-grade machinery for exactly the part the product
  needs most. (3) Sparse handheld phone trajectories (126 keyframes of one
  room) are floater-prone 3DGS inputs; quality would be worst on real
  captures. (4) Decision 0001's razor: ARKit measures gravity, poses, and
  planes directly — re-deriving room geometry from pixels is the VGGT mistake
  again. The phrase "inpainted scene-3DGS" in CLAUDE.md is superseded by this
  note.
- **Feed-forward scene-reconstruction models** (monocular/few-shot splat or
  depth networks) — same 0001 razor, plus a heavyweight new model dependency
  inside the same budget that already can't fit 12 object frames.
- **Server-side wall inference from nothing on ARKIT_ONLY** (room-polygon
  completion from the camera trajectory + object hull, Manhattan priors,
  camera-height floor estimates) — every variant emits geometry nobody
  measured. The placement principle ("a guessed transform is never emitted",
  0052) extends to the shell: invented walls presented as the user's room are
  a silent honesty failure, the same class 0058 rejected for measurements.
- **Floor height from object bottoms** (min world-Y over placed objects'
  transformed splat vertices) — doubly rejected: it consumes object
  *rotations*, which are exactly what the open 0063 verdict says not to trust,
  and a curtain or wall-mounted object poisons the estimate. Rejecting this is
  what makes the shell rotation-independent by construction.
- **Shell as a synthesized scene-level splat PLY** (flat gaussians on the
  planes, riding the existing `PositionedSplat` contract unchanged) — the
  uniform-softness argument lost to three practical points: splat walls are
  visible from both sides, so the orbiting camera outside the room would stare
  at the back of the near wall (fixing that means custom per-frame culling
  inside Spark); a texel-resolution PLY is tens of MB where PNGs are a few; and
  the synthesis step is strictly extra work on top of the textures it would be
  made from. Mesh quads get the dollhouse cutaway for free from single-sided
  materials.
- **Generative diffusion inpainting** for object-removed regions —
  hallucinates *content* (a radiator that isn't there, into "your room"): the
  fabricated-measurement failure wearing pixels. Also heavyweight and
  nondeterministic. Texture-continuation models extend material, not objects.
- **No inpainting at all** — furniture-shaped holes read as damage, and the
  redesign substrate fails at its one job: move the bed and there's a hole.
- **Rewriting `manifest.json` from the shell stage** — a second writer on the
  blob `/process` owns invites read-modify-write races with warm re-drives.
  The shell writes its own sibling blob; composition happens at read time in
  api-public (the same philosophy that keeps facts out of manifests, 0058).
- **Running the shell inline in `/process`** — cold runs finish with ~0–60 s
  spare; inline shell either steals object frames or never runs. **Running it
  as a separate GPU service** — the shell needs neither SAM model (masks are
  already cached in GCS; the inpainting model is small and CPU-capable), so a
  second service duplicates deploy/IAM/ops for minutes of image work.

## What we chose

**Geometry source: ARKit plane anchors, carried on the wire.** The capture
app enables plane detection (`.horizontal` + `.vertical` — available on ALL
ARKit devices, LiDAR or not) and serializes the session's **final** anchor set
at capture stop into a new additive `CaptureBundle` field:
`repeated PlaneAnchor plane_anchors = 12` — per anchor: world_from_anchor
`Pose` (reused message; anchor-local +Y is the plane normal), anchor-space
center + extent (width/height + rotation-on-Y), an alignment enum, ARKit's
classification string verbatim when the device provides one (empty
otherwise), and an optional anchor-space boundary polygon. Additive proto3 —
`schema_version` stays `"1"` (the version bumps on breaking changes only;
the ingest gate is untouched), and bundles without planes remain valid.
This is 0001's razor cutting *for* new data: ARKit measures these planes on
every device; the backend should consume the measurement, not re-derive it.
The tier ladder: plane anchors are the geometry source on all tiers today;
LiDAR depth (hardware-parked, board item 3) adds measured per-pixel occlusion
for texture baking and plane validation; RoomPlan's USDZ supersedes plane
anchors as the geometry source on its tier when that path exists. Same output
shape regardless; `method` records the source.

**Degrade honestly, gate nothing.** A bundle with no plane data (every
existing capture, including the preserved `25a14caf`) yields
`{status: "unavailable", reason: "no_geometry_source"}` and the viewer keeps
today's honest grid stage. No tier is gated out — ARKIT_ONLY carries planes
the same way Pro devices do. Detected walls that don't close a loop ship as
detected: an open dollhouse is the natural presentation, not a failure to
hide. No closing walls are invented.

**Shell form: textured world-space quads.** The shell is a floor plus walls,
each a quad in the ARKit world frame with a baked PNG texture. Floor shape
(polygon from merged floor anchors, clipped by walls where they exist) is
carried in the texture's alpha channel, so the client renders nothing but
quads. Wall quads are wound inward; the client uses single-sided materials —
the camera outside the room sees through the near wall (the dollhouse
cutaway), and `maxPolarAngle` already keeps it above the floor. Textures bake
by projecting the capture's own RGB onto each plane: candidate samples come
only from **complete** frames (the ones with cached `masks.npz`), pixels
under any SAM 3 object mask are excluded, samples are incidence/distance-
weighted and robust-blended (median) across views. Mask-based exclusion is
bounded by the object-prompt vocabulary — an unprompted object can bake into
a texture; the multi-view median suppresses transient bake-in, LiDAR tiers
close the hole with measured occlusion, and this is accepted v1 residue.
Holes (furniture-occluded or unseen texels of an *observed* plane) are filled
by a **texture-continuation inpainting model** (LaMa-class: small,
permissively licensed, CPU-capable, deterministic; weights baked into the
image per 0008). A plane observed below threshold isn't textured from
nothing — it ships flagged `unobserved` with a neutral treatment. Every plane
carries `observed_fraction` and `inpainted_fraction`: the honesty ledger the
product (and any future facts derivation) reads. No ceiling in v1 — rarely
scanned, and the open top serves the orbit camera.

**Where it runs: a second Cloud Tasks stage on perception-obj.** `/process`,
on its success path (after `release_ready`), enqueues a `/shell` task
(same queue, same OIDC invoker pattern, payload `{scene_id, bundle_uri}`,
fire-and-forget — an enqueue failure logs and leaves the objects room
intact). The `/shell` handler never touches the SAM accessors, so its cold
start is seconds, not minutes; it reads the bundle (poses/planes), the
manifest (read-only, for the complete-frame list), cached masks from the
outputs bucket, and RGB from the captures bucket (inside the 1-day lifecycle
window — a late re-run without pixels degrades to
`{unavailable, reason: "capture_expired"}`). It writes
`scenes/{scene_id}/shell.json` + `scenes/{scene_id}/shell/textures/*.png` —
**never** `manifest.json`. No scene lease: the write is a single atomic blob
PUT, deterministic for identical inputs; concurrent runs are benign
(last-write-wins with equivalent content). Scene status is never touched —
shell failure cannot un-ready a room. The same request-entry deadline
pattern bounds the handler (the workload is minutes against a 900 s window).

**Read contract + product surfacing.** `GET /scenes/{scene_id}/assets` gains
a sibling `shell` field (the manifest stays verbatim per 0054's documented
shape): shell.json's content when present, `null` otherwise; shell texture
URIs join the existing signing walk into `asset_urls`. On the web,
`assembleScene` grows a `shell` output; `SplatViewer` gains a renderer-
agnostic `shell?: ShellPlane[]` prop (0053's containment rule intact — the
type is quads + texture URLs, nothing renderer-shaped) and renders them as
single-sided textured meshes. The reveal extends: the shell is the stage —
floor, then walls, then the existing largest-first object assembly. Because
the shell task lands a beat after `ready`, the room page may hold the reveal
briefly for it or let the shell arrive as a second beat — pacing is left to a
real-browser watch (the same one the reveal already needs) under two fixed
constraints: nothing fake is shown, and the wait's narration only promises a
shell when one is actually coming. Conversation/facts consumption of the
shell (room dimensions — the first shell-derived facts) is a deliberate
fast-follow behind a `facts_version` bump, not part of this build.

**The 0063 dependency, stated exactly: there isn't one.** The shell consumes
poses, gravity, masks, and plane anchors — never SAM 3D layout rotations. The
one estimator that would have coupled it (floor from object bottoms) was
rejected partly for that coupling. Whatever the live probe concludes about
quaternion order and the splat frame changes how *objects* render, not where
the floor and walls are. The two workstreams compose at the same manifest
without ordering constraints.

## Why

Every lock traces to one of three masters. **Honesty made structural** (the
0058 pattern): geometry only from measurement, provenance and
observed/inpainted fractions on every plane, material-continuation instead of
content hallucination, `unavailable` instead of invention. **The deployed
budget reality** (0060–0062): nothing new inside `/process`'s window, no SAM
models on the shell path, no training workloads, no new service. **Contract
containment** (0053/0054): one writer per blob, manifest verbatim, renderer
specifics confined to SplatViewer, a renderer-agnostic shell type beside
`PositionedSplat`. The plane-anchor wire change is the one place the design
spends real capture-side effort, and it buys the only thing no server-side
cleverness can: measured room geometry on the tier every user actually has.

## What would change this decision

- The 0063 probe's splat-frame verdict changing how object splats are
  exported changes nothing here (world-frame quads are unaffected) — recorded
  so nobody re-checks.
- RoomPlan tier arriving (Pro hardware, board item 3) upgrades the geometry
  source on that tier — same shell.json shape, `method: "roomplan"`, plus
  parametric doors/windows becoming representable instead of baked pixels.
- Real captures showing ARKit vertical-plane detection too sparse on typical
  walls (bare/glossy surfaces) re-opens LiDAR-derived planes as the primary
  on LiDAR tiers — the tier ladder already has the slot.
- Feed-forward scene splat models maturing to phone-trajectory quality AND a
  budget class that fits them re-opens the trained-shell fork for the
  *occupied* room (the empty-substrate need keeps the planar shell either
  way).
- Extents landing in the manifest (the conversation fast-follow) plus shell
  planes existing unlocks room-dimension facts — that session bumps
  `facts_version` and revisits what the guest may say about walls.
- If the Spark depth-compositing probe (the brief's verify-first step) shows
  splats and `depthWrite: true` meshes cannot coexist correctly, the
  representation fork re-opens toward the synthesized-splat shell — the bake
  pipeline is unchanged; only the final emission step differs.
