# Layer 1 (Perception) — Tiered Implementation Plan

The Room Perception schema (`room_perception_v2.py`) is the contract.
This document is the **build order** — what to populate first, what to
validate before moving on, what to add next.

The principle: **the schema is fully defined, but we populate it in
tiers.** Earlier tiers produce JSON with empty/null fields for later-tier
features. Downstream layers read the capability flags and degrade gracefully.

---

## Tier 1A — Skeleton (target: 1–2 days)

**Goal:** Prove the pipeline runs end-to-end and produces a valid `RoomPerception`
object on one test image, even if most fields are null or low-quality.

**Populate:**
- `primary_image_id`, dimensions, schema_version (trivial)
- `objects[]` with: `id`, `object_class`, `classification_confidence`, `bbox_2d`,
  `movability` (looked up from class), `surface_material` (material only, colors empty)
- `geometry.dimensions` with normalized values only (`has_metric_scale=False`)
- `geometry.wall_planes` and `wall_count_estimate` (rough — even a single
  hand-tuned floor-plane estimate is fine)
- `overall_perception_confidence` (can be a hand-computed aggregate)
- All capability flags set conservatively (mostly False)

**Skip (leave empty/null):**
- `bbox_3d` — emit dummy values, flag yaw_confidence=0
- `dominant_colors`
- `light_sources`
- `doorways`, `free_floor_polygons`, `raw_sight_lines`
- `inferred_purpose`
- VLM second-pass refinement

**Validate before moving on:**
- A real photo runs through SAM2 → outputs valid masks
- Depth Anything V2 runs → outputs valid depth map
- Fusion code produces a `RoomPerception` that passes Pydantic validation
- Open the JSON and read it as a human — does the object list match the photo?

**Risk this tier proves out:**
"Can we actually fuse SAM2 + DAv2 + classification into a coherent JSON
object at all, on a real photo, without the schema collapsing?"

---

## Tier 1B — Core Geometry (target: 2–3 days)

**Goal:** Make the spatial information real. After this tier, the JSON is
usable for the Claim-1 comparison test (raw image + prompt vs. JSON + prompt).

**Add:**
- `bbox_3d` with axis-aligned 3D boxes (skip yaw — `yaw_confidence=0` for all)
- `dominant_colors` per object (LAB extraction is deterministic, ~30 min of work)
- `distance_to_nearest_wall_normalized` + provenance
- `height_above_floor_normalized`
- `is_partially_occluded` + `occlusion_reason` (computed from mask-boundary
  intersection)
- `floor_plane_normal` and `primary_view_direction` (from vanishing-line analysis
  or VLM if it's faster)
- Capability flags refined: `has_complete_floor_coverage` based on occlusion stats

**Skip:**
- Yaw / orientation (Tier 1D)
- Light sources (Tier 1C)
- Doorways, free floor polygons, sight lines (Tier 1D)
- VLM purpose inference (Tier 1C)

**Validate before moving on:**
- Plot the 3D bboxes on top of the original image — do they line up visually?
- Spot-check `distance_to_nearest_wall_normalized` on 3–5 objects by hand
- The JSON should now look "substantial" — a reader could roughly imagine the
  room from it

**Risk this tier proves out:**
"Can we lift 2D detections to spatially-coherent 3D positions with monocular
depth, well enough that downstream reasoning will be grounded?"

---

## Tier 1C — Light & Purpose (target: 2 days)

**Goal:** Add the cheaper VLM-driven enrichments. These are independent of the
geometry pipeline, so they can be developed in parallel with Tier 1B if time
allows.

**Add:**
- `light_sources[]` — detect windows from SAM2 (object_class=WINDOW), infer
  `direction_estimate` from window position, mark `is_natural=True`. For lamps,
  detect via object_class and mark `is_natural=False`. Set `quality` and
  `quality_confidence` via VLM ("what kind of light is in this room?").
- `overall_light_quality` — single categorical estimate via VLM
- `inferred_purpose` + `inferred_purpose_confidence` via VLM
- Capability flags: `has_orientation` stays False unless user provides it
- `north_direction` only if user provided (still null in default flow)

**Skip:**
- Doorways, free floor polygons, sight lines (Tier 1D)
- VLM orientation refinement (Tier 1D)

**Validate before moving on:**
- VLM correctly classifies room type on 5 test photos (should be ~5/5 for
  obvious cases — living room, bedroom, kitchen)
- Light quality classification agrees with human judgment on 5 photos

**Risk this tier proves out:**
"Can we use VLM as a cheap enrichment layer for categorical fields without
the rest of the pipeline depending on it?"

---

## Tier 1D — Spatial Intelligence (target: 4–6 days, the hard part)

**Goal:** Add the fields that make Layer 2's reasoning meaningfully better
than what a VLM could do alone. **This is the tier that decides whether
Claim 1 holds.**

**Add:**
- Yaw / orientation for `OBJECT_CLASS_HAS_ORIENTATION=True` classes:
  - First pass: longest-edge heuristic from floor-projected mask
  - Second pass: VLM verification ("which way is this sofa facing?") for
    objects in `SIGHT_LINE_SOURCE_CLASSES` + windows + screens
  - Set `yaw_refined_by_vlm=True` for refined objects
- `doorways[]` — detect from DOOR/DOORWAY classes, compute `floor_position`,
  `width_normalized`, `wall_index`, `leads_to_visible_space`
- `free_floor_polygons[]` — compute via polygon subtraction:
  room floor polygon minus all object floor footprints. Mark `is_near_window`,
  `is_near_doorway`, `is_traffic_path` (inferred path between doorways).
- `raw_sight_lines[]` — ray-cast from every `SIGHT_LINE_SOURCE_CLASSES` object
  along facing direction; record hits, intermediate objects, geometric blocking

**Validate before moving on — THIS IS THE CLAIM-1 TEST:**

Run two prompts to Claude with the same instruction ("suggest three specific
changes to improve this room and explain why"):

- **Prompt A:** raw image only
- **Prompt B:** Tier 1D-complete RoomPerception JSON only (no image)

Score each on:
1. **Specificity** — does the response cite specific objects and positions, or
   does it speak in generalities?
2. **Falsifiability** — could the response have been written about a different
   room? If so, it's not grounded.
3. **Spatial reasoning** — does it reference clearances, sight lines, traffic
   flow, light conflicts? Or just colors and styles?

**If Prompt B is meaningfully better on at least 2 of 3 dimensions on 5 test
rooms: Claim 1 holds. Proceed to graph schema.**

**If Prompt B is not better: the perception layer is descriptive, not
analytical. We need to add more computed analysis fields (dead zones, light
conflicts, proportion mismatches) before Layer 2 — or accept that the moat
is the graph layer, not perception.**

**Risk this tier proves out:**
"Does structured perception actually unlock reasoning that raw VLM inference
can't match?"

---

## Tiering principle (for future reference)

When in doubt about what tier something belongs in, ask:
1. Does the pipeline run without it? → if yes, it's later-tier
2. Does the next layer need it? → if no, it's later-tier
3. Is it the cheapest way to fill a critical field? → if yes, earlier tier
4. Does it require a model we haven't validated yet? → push it later, prove
   the easy stuff first

---

## What Tier 1A–1D explicitly do NOT include

These are deliberately out of scope for Layer 1, regardless of tier:

- **Multi-photo geometric fusion** — supplementary views are stored but not
  fused. The canonical view is the source of truth for 3D.
- **Material sub-classification** beyond MaterialClass coarse buckets
- **Style classification** — that's Layer 3 / Taste Graph territory
- **Any value judgment** on whether the room is "good" or "bad" — that's Layer 2
- **Furniture model matching** — linking detected objects to GLTF assets in
  the library is a Layer 5 (rendering) concern
