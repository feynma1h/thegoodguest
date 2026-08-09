# 0069 — Shell surfaces: generated parametric materials replace the photographic bake

**Date:** 2026-07-23
**Status:** Decided and SHIPPED — shell.json v2 with parametric materials,
serving since 2026-07-24. The code is `services/perception-obj/shell_material.py`
and `room_planes.py`; the texture bake it replaced (`shell_texture.py`,
`shell_inpaint.py`, and the LaMa weights) is deleted. Build verdicts are
decision 0070. Supersedes
decision 0066's **surfacing layer** (texture bake + inpaint). 0066 stays
authoritative for everything else: plane-anchor geometry source, the
`/shell` stage architecture, degrade semantics, and the read contract's
shape.

## Context

The room shell shipped and ran E2E on the first plane-carrying capture
(scene `f3d70236`, 2026-07-23). Seeing the real render, the operator
rejected photo-projected surfaces against the product's premium bar:
recognition of one's own room matters, but the room also has to look
*good* — designable, clean, premium — and a low-coverage photographic
bake pasted onto wall quads does not. A second finding from the same
render: 0066's no-extrapolation rule means detected-extent-only walls
float disconnected above the floor and never meet each other — measured
truth reads as broken geometry on screen. The fork was declared
operator-side and resolved in this design session. Grounding facts the
decision leans on: the first real floor baked **31% observed / 69%
LaMa-inpainted**; a family member present during capture was blended
into that floor texture (the shell half of the person-privacy gap); and
walls below the 0.2 observed-fraction bake gate ship as bare gray quads.

## What we tried / rejected (named rejections)

- **Keeping the photographic bake as the product surface** — fails the
  premium bar (operator verdict on real output); its quality ceiling
  scales with capture discipline users won't have; at 31% coverage the
  "photograph" is two-thirds model-generated pixels wearing a
  photographic costume — it *claims* observation it doesn't have; and it
  structurally funnels the redesign layer into photorealistic image
  synthesis (repainting a baked photo credibly IS the founding draft's
  excluded direction), the moment conversation stage 2 mutates a
  surface.
- **Hybrid: photographic view beside the generated view** (candidate b)
  — doubles the viewer surface, keeps LaMa and person-masking on the
  launch path, and invites the user to compare the premium view against
  the one that failed the bar. Recognition doesn't need it: object
  splats, measured geometry, and measured color carry it.
- **Full material + relighting pipeline first** (candidate c) —
  estimating BRDF/illumination from uncontrolled phone capture is
  research-grade; adopted as the *trajectory* instead: the v1 material
  dict is PBR-shaped so (c) extends it rather than replaces it.
- **Visible seam treatment for extrapolated regions in the default
  view** — premium is seamless; honesty lives in the data (per-edge
  provenance, `measured_quad`), not in a rendered scar. A future "show
  me what you actually saw" affordance can consume the same fields.
- **Pattern reproduction (wallpaper, tile grids) in v1** — inference
  quality isn't there; a wrong pattern breaks recognition worse than a
  clean matte in the measured color. Family-typed micro-treatment only.
- **Estimating roughness/sheen from pixels** — family→constant lookup
  reads fine under the viewer's warm lighting; estimation is (c)-era.

## What we chose

**Per-plane parametric materials inferred from the observed pixels,
rendered client-side from parameters — no raster textures in the
serving contract.** V1 inferred features: dominant **albedo** (robust
weighted-median chroma over mask-excluded observed texels, high-lightness
reference band — measured, the recognition anchor), **material family**
(closed vocabulary — floor: wood/tile/stone/carpet/concrete; wall:
painted/wallpaper/tile/exposed — classified by a temperature-0
constrained-JSON vision call from the `/shell` stage, confidence-gated),
family→roughness **lookup**, optional plank direction (dominant gradient
orientation). **The load-bearing fallback rule: below the gate or on any
failure, family = null and the plane renders clean matte in the measured
color — degrade to clean-neutral, never to wrong-specific.** Doors and
windows: ARKit-classified anchors folded during wall merge become
`openings` sub-regions (inset treatment), not painted over.

**Envelope closure joins the shell — joints, never loops.** Detected
wall extents extend to the measured floor-plane intersection, to
wall-wall seam lines with adjacent *detected* walls (gated), and to a
common observed top height; the floor polygon extends to wall contact
lines. No plane is ever invented: 0066's rejection was inventing
geometry nobody measured, and closure derives every extension from the
intersection of two measurements. Open sides stay open. shell.json
carries both geometries — `measured_quad` (detected, what facts may
read) beside the rendered polygon, with per-edge provenance — so the AI
layer never reasons over extended geometry even though the renderer
draws it. Closure also gives floating fragments a principled filter:
unclassified vertical planes that participate in no joint aren't
structure.

**Pipeline: a split, not a rename.** `shell_geometry` survives and gains
closure (after the `room_planes.py` extraction shared with 0067 chunk
D); `shell_texture`'s projection/sampling/weighted-median core is
demoted to an observation layer feeding inference; the PNG/alpha/bake
emission and `shell_inpaint` (LaMa, weights and Dockerfile bake step)
are **deleted from serving**. New `shell_material` owns inference.
`/shell` stage, enqueue, write-once noop, and both degrade legs survive
verbatim. The floor's shape moves from PNG alpha to an explicit polygon
in shell.json (`SHELL_VERSION` 1→2). Shell texture URIs leave the
signing walk; the viewer builds materials from parameters (no texture
fetch) and renders the floor as a shape.

## Why

Four reasons, in weight order. (1) **Stage 2 forces this choice in this
direction anyway**: mutating a parametric wall is a hex edit + WebGL
re-render — the founding draft's chosen fork ("3D WebGL render over
photorealistic image generation"); mutating a baked photo requires image
synthesis — the excluded one. The material dict is the editable-surface
half of the Design Specification contract, arriving early. (2) **The
honesty ledger sharpens**: a 69%-inpainted "photograph" claims
observation it doesn't have; a matte surface in the measured color
claims exactly what it is. 0066 already drew this line when it accepted
material continuation and rejected content hallucination — this is the
same principle taken to its endpoint. (3) **Quality inverts against
capture discipline**: a color estimate needs ~10² texels where a good
bake needs coverage users won't provide; walls below today's bake gate
become confidently colorable; the parametric floor looks identical at
31% and 90% observation. (4) **The shell half of the person-privacy gap
closes outright** — no baked textures, nobody blended into the floor;
LaMa leaves the image. The founding draft's exclusion of photorealistic
image generation was about fabricating fake room photos; rendering
measured parameters inside the WebGL scene is the other side of the
draft's own fork.

## What would change this decision

- Operator adjudication failing on the reference room (`f3d70236` —
  inferred wall color / floor family read wrong to the person who lives
  there) re-opens the inference design before anything ships wider; the
  fallback-to-neutral rule bounds the damage either way.
- Real captures where absolute white balance reads wrong re-open
  capture-side light estimation (ARKit ambient color temperature as an
  additive proto field, the `plane_anchors` pattern) — not client-side
  correction hacks.
- The lighting-simulation direction maturing promotes the material dict
  toward (c): estimated illuminants, richer BRDF — extending
  `material {}`, never replacing it.
- RoomPlan tier arriving (board item 3) makes doors/windows parametric
  at the source; the `openings` mechanism is the compatible slot.
- A future evidence/provenance product surface ("show me what you saw")
  would consume observed crops — kept possible because the observation
  layer survives; it would NOT resurrect the bake as the default view.
