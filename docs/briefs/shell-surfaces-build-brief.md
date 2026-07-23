# Build brief — Generated shell surfaces + envelope closure (decision 0069)

Consumes: decision 0069 (the why), 0066 (the surviving substrate: plane
anchors, `/shell` stage, degrade semantics), 0067's brief §room_planes
(the shared-extraction coordination clause). Delete this brief when the
deployed V3 walk (below) is green and CLAUDE.md records it.

## Ground rules

**Survives verbatim:** plane-anchor geometry source; `/shell` receiver
architecture (Cloud Tasks + OIDC, no lease, no Firestore, write-once
noop on existing shell.json, request-entry deadline); both degrade legs
(`capture_expired`, `no_geometry_source`); fire-and-forget enqueue from
`/process`; api-public's verbatim-shell passthrough + degrade-to-null;
`SplatViewer` as the only three.js module; the reveal order (floor →
walls → objects); byte-deterministic shell.json.

**Dies:** `shell_inpaint.py` + the Dockerfile LaMa weight-bake step +
its import-smoke line (image slims); `shell_texture`'s PNG/alpha/bake
emission; shell texture URIs in the assets signing walk; the viewer's
texture-fetch + alphaTest floor path. Git history preserves the bake;
do not keep dead code behind flags.

**Coordination (same clause as 0067's brief):** chunk 1 extracts
`services/perception-obj/room_planes.py` — THE single
anchor-interpretation module (floor selection per 0066's semantics, wall
set, coplanar merge, ray/plane queries). Whichever of this build / the
placement build lands second refactors onto the first's module — check
the other branch's tree state at build time; do NOT duplicate anchor
interpretation.

**Cache contract:** per-frame caches (`objects.json` / `masks.npz`) are
FROZEN. The shell stage reads them; nothing new is written per frame.
Material inference inputs come from bundle RGB + cached masks at /shell
time, inside the captures bucket's 1-day lifecycle window (unchanged
`capture_expired` semantics).

## Contract — shell.json v2 (`SHELL_VERSION` 1 → 2)

Top level unchanged (`shell_version`, `scene_id`, `status`, `reason`,
`method`, `quality`); `quality` gains closure stats (joints made,
fragments dropped) and `material_version`. Byte-determinism test stays.

```
floor: {
  polygon: [[x,y,z]…],        # world-space, replaces PNG-alpha shape
  y, material: {…}, provenance: { edges: "observed"|"extended_to_wall" per segment? — see closure chunk }
}
walls[]: {
  wall_id,
  quad:          rendered corners (post-closure; what the viewer draws),
  measured_quad: detected extent (closure NEVER mutates it — pinned),
  edges: { bottom|top|left|right:
           { state: observed|extended_to_floor|extended_to_common_height
                    |extended_to_wall:<id>, extension_m } },
  openings: [ { classification, rect_uv } ],   # from classified anchors
  material: {…}, classification
}
material: {
  family, family_confidence,           # null when gated/failed/no-key
  albedo_hex, secondary_hex|null,
  params: { plank_direction_deg? },
  render: { roughness },               # family lookup, not estimated
  source: { observed_fraction, texel_count, frames_used },
  inference: { model|null, material_version }
}
```

No `texture_gcs_uri` anywhere. `observed_fraction`/`inpainted_fraction`
per-plane top-level fields are replaced by `material.source`
(`inpainted_fraction` dies with the bake).

Migration: population of ready shells is exactly one (`f3d70236`). No
viewer version-gate for a population of one — delete its shell.json and
re-drive (`tools/reenqueue_scene.py <scene_id> --shell` after the blob
delete; the receiver's noop is on existence, so the delete is the
re-drive switch). `25a14caf`'s permanent `no_geometry_source` shell.json
is untouched and must keep degrading cleanly.

## Chunk 1 — room_planes extraction + envelope closure (geometry)

Extract `room_planes.py` from `shell_geometry`'s anchor interpretation
(see coordination clause). Then the closure pass in `shell_geometry`,
running AFTER merge, BEFORE emission:

- **Wall→floor:** extend each wall's bottom edge to the intersection
  line with the floor plane, gated `SHELL_FLOOR_DROP_MAX_M` (default
  2.0 — a detected wall higher above the floor than this stays
  unextended rather than extruding a curtain-height fragment into a
  full wall).
- **Wall→wall:** extend lateral edges to the seam line with an adjacent
  detected wall when the detected extents approach within
  `SHELL_JOIN_MAX_GAP_M` (default 1.5) and the seam lies beyond neither
  extent by more than that gate; never extend past the seam.
- **Tops:** `SHELL_COMMON_TOP_ENABLED` (default true) brings structural
  walls to the max detected top height; per-wall marked
  `extended_to_common_height`.
- **Floor:** extend the member-polygon union outward to meet wall
  contact lines (bounded by the walls; where no wall exists the
  detected floor edge stands).
- **Fragment filter:** after closure, drop unclassified vertical planes
  with no joint participation (no floor contact within gate, no
  wall-wall seam) and area < `SHELL_STRUCTURAL_MIN_AREA_M2` (default
  1.0). `SHELL_MIN_WALL_AREA_M2` stays 0.3 untouched — the filter
  replaces raising it.
- **Openings:** wall merge must PRESERVE door/window-classified source
  anchors as `openings` rects in the merged wall's UV space (today the
  classification survives only as the merged wall's single string —
  f3d70236's door pair folded into the main wall proves the loss).
- **Invariants (pinned by tests):** closure never adds a plane; open
  sides stay open; `measured_quad` byte-equals the pre-closure detected
  extent; all knobs env-overridable, one-capture-calibrated like the
  SHELL_*/sampling knobs.

**V1 (offline probe, before any service change ships):** run closure on
`f3d70236`'s recorded anchors (`outputs/real-capture-f3d70236/`).
Assert: every structural wall reaches the floor; the main corner seams
exist; provenance populated; the four floating fragments drop (or the
probe output justifies keeping specific ones). Calibrate the four knobs
against this capture the way the V3 walk calibrated SHELL_WALL_*.

## Chunk 2 — observation layer (shell_texture demotion)

`shell_texture` → `shell_observation` (or slim in place; pick one, no
shims): keep the ortho texel grid, mask exclusion,
incidence/distance-weighted sampling, weighted-median math, and
observed-fraction accounting; emit per-plane **observation stats + N
rectified evidence crops** (highest-weight observed regions, N≤4,
in-memory arrays — nothing written to GCS in v1) instead of a PNG.
Delete blend-to-bake, alpha-shape, PNG encode, `InpaintFn`. Bake tests
retire; observation tests replace them (same hand-built-frame fixtures).

## Chunk 3 — material inference (`shell_material`, new)

- **Albedo:** weighted-median chroma over observed texels restricted to
  a high-lightness band (75th-percentile lightness reference — shadows
  darken matte surfaces, rarely brighten). Below
  `SHELL_MATERIAL_MIN_TEXELS` (default 100): `albedo_hex = null` →
  viewer neutral treatment (today's "unobserved" look). Optional
  `secondary_hex` when two-tone separation exceeds a gate — defer if
  noisy.
- **Family:** evidence crops → ONE vision call (Anthropic,
  `SHELL_MATERIAL_MODEL`, default `claude-sonnet-5`), temperature 0,
  constrained JSON `{family, confidence}` over the closed vocabulary
  (floor: wood|tile|stone|carpet|concrete; wall:
  painted|wallpaper|tile|exposed). Gate `SHELL_MATERIAL_MIN_CONF`
  (default 0.6). **Fallback rule (load-bearing, test-pinned): below
  gate, call failure, or no key → `family = null` → clean matte in the
  measured albedo. Degrade to clean-neutral, never wrong-specific. A
  missing/failed inference NEVER blocks shell.json.**
- **Roughness:** family → constant lookup table. **Plank direction:**
  dominant gradient orientation on floor crops when family = wood;
  ship only if it stays a page of numpy.
- **Determinism:** the write-once noop covers re-runs; record
  `MATERIAL_VERSION` + model in `inference`.
- Offline **V2 probe:** run inference on f3d70236's real observed crops;
  the operator adjudicates inferred wall color + floor family against
  the actual room (they live there — this is the acceptance test, per
  0069's re-open clause).

## Chunk 4 — receiver + api-public

`shell_receiver` assembles the v2 doc (geometry + closure + per-plane
material), `SHELL_VERSION = 2`, `build_shell_json` reshaped, degrade
paths and noop untouched. api-public: confirm the signing walk no-ops on
a v2 shell (it walks `texture_gcs_uri` keys; v2 has none — if the walk
is key-targeted, zero code change; verify, don't assume). Shell fetch
error still degrades to null.

## Chunk 5 — web

`ShellPlane` v2 in `lib/api/types.ts`: kind, rendered quad / floor
polygon, material params, openings; `texture_url` gone. `assembleScene`
maps the v2 doc. `SplatViewer`: `MeshStandardMaterial` from
`material.render` + albedo (neutral treatment when albedo null);
floor via `ShapeGeometry` from the polygon; openings as inset material
patches; delete the fetch()+ImageBitmap texture path and alphaTest;
reveal choreography and `PositionedSplat` contract untouched; grid
stand-down rule unchanged. Mock fixtures + `tools/make_synthetic_splat.py`'s
shell fixture → v2. Vitest updates. No CSP change (one less external
fetch class, nothing new).

## Deploy / ops

- Dockerfile: LaMa bake step + weights + import-smoke line removed;
  COPY + import smoke extended to `room_planes.py`, `shell_material.py`
  (deferred imports are the trap the placement/fusion COPY bug proved).
- `deploy_perception.sh`: mount `anthropic-api-key` (exists in Secret
  Manager) on perception-obj + idempotent secret-scoped
  `secretAccessor` grant for its runtime SA (the api-public pattern);
  new env vars in the perception env yaml (`SHELL_MATERIAL_MODEL`,
  gates/knobs) — mirror any env-only revision in the yaml, same commit.
- No api-internal change. No proto change. No CORS change.

## Verification (definition of done)

1. V1 + V2 offline probes green on `outputs/real-capture-f3d70236/`
   (closure walk + operator material adjudication).
2. Suites: perception-obj (closure/observation/material/receiver-v2 +
   the measured_quad-immutability and fallback pins; bake tests
   retired), re-enqueue, root, web vitest + lint + static-export build —
   all green; byte-determinism test intact.
3. Deployed V3: delete `f3d70236`'s shell.json → `reenqueue --shell` →
   v2 shell.json + NO texture blobs; assets response carries it; /viewer
   and /room render the joined parametric room; `25a14caf` still
   degrades `no_geometry_source`; no-key fallback exercised once
   (unset/withhold the secret in a candidate or local run → family null,
   shell still ships).
4. CLAUDE.md updated (What-works bullet; privacy-gap shell half marked
   mooted; this brief deleted per its own header).

## Out of scope (recorded, do not build)

Pattern/wallpaper reproduction; relighting / illuminant estimation
(direction (c)); per-plane region segmentation (two-tone walls ship
dominant color); ceiling; visible seam treatment for extended regions;
facts/conversation consumption of shell or materials (separate
`facts_version`-bump session — but the `measured_quad`-only reading
obligation is recorded in 0069 and the immutability pin lands HERE);
evidence-crop persistence to GCS; person masking (mooted for the shell
by this build; capture-time guidance stays board-4).
