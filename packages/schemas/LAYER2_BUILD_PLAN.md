# Layer 2 (Spatial Reasoning) — Tiered Implementation Plan

The Spatial Relationship Graph schema (`spatial_graph.py`) is the contract.
This document is the **build order** — what to compute first, what to validate
before moving on, what to add next.

**Layer 2's job:** consume a `RoomPerception` and emit a `SpatialRelationshipGraph`
that contains every analysis deterministic enough to compute in code, so Layer 4
(the LLM) can spend its budget on judgment, not on rediscovering geometry.

**The decisive gate sits at the end of this layer.** The Claim-1 test —
raw image + prompt vs. Layer 2 graph + prompt — is what decides whether the
"spatial intelligence platform" framing has substance. Everything in this
build plan is in service of that gate.

---

## Principle from Layer 1, carried forward

Layer 1's principle: **emit geometric facts, not interpretations.**
Layer 2's principle: **emit interpretations only where the rule is
deterministic. Otherwise emit a structured fact and let Layer 4 judge.**

Concretely: if you can't write the detection rule in <50 lines of code with
clear thresholds, it's an Observation, not an Issue.

---

## Tier 2A — Structural Foundation (target: 2–3 days)

**Goal:** Build the structural graph layer. Nodes and edges only, no analysis.

**Produce:**
- `StructuralGraph.nodes` for every object in perception (kind=OBJECT)
- `AdjacencyRelation` edges between objects within a proximity threshold —
  pure geometric distance over floor positions
- `FacingRelation` edges from every object with semantic orientation to whatever
  its facing-ray hits (cribs directly from Layer 1's `raw_sight_lines` —
  reformat, don't recompute)
- `ComplementaryRelation` edges for canonical pairs (nightstand-bed, coffee-table-sofa,
  rug-anchors-cluster) via a small hard-coded compatibility table

**Skip:**
- Zone nodes, focal point nodes
- Blocking, competing relations (Tier 2B)
- All issues and observations (Tier 2C+)
- Computed summaries (Tier 2D)

**Validate before moving on:**
- Render the graph as a node-link diagram over the room floor plan. Does it
  look like a sensible representation of the room?
- Spot-check 5 facing relations against the original photo — does the AI's
  notion of "what the sofa faces" agree with yours?

**Risk this tier proves out:**
"Can we deterministically construct a structural graph from Layer 1's output
that a human would agree is a fair representation of the room's relationships?"

---

## Tier 2B — Zones, Focal Points & Blocking (target: 3–4 days)

**Goal:** Add the computed nodes and the harder edge types. This tier produces
a graph rich enough to do interesting analysis on, even though the analysis
itself isn't done yet.

**Add:**
- `ZONE` nodes via object clustering on floor positions, with type inference
  by member composition (seating zone = ≥1 seating + optional table + optional rug)
- `DEAD_ZONE` nodes from free-floor polygons above a size threshold that are
  not part of any other zone and not on a circulation path
- `FOCAL_POINT` nodes:
  - One per detected window (kind=WINDOW_LIGHT) with strength from window size
  - One per fireplace/TV/major artwork
  - One INTENDED_FOCAL computed as: the point most seating objects point at
- `BlockingRelation` edges:
  - sight_line blocking: read from Layer 1 raw_sight_lines, lift to graph edges
  - traffic_path blocking: an object's floor footprint intersects the inferred
    circulation polyline (requires preliminary traffic path — compute a coarse
    one here, refine in Tier 2D)
  - light_path blocking: an object is between a window node and a zone, taller
    than the zone's typical use height
  - access blocking: object within X normalized units of a doorway/window
- `CompetingRelation` edges:
  - natural_light: two zones both within proximity of the same window
  - focal_attention: two focal points of comparable strength in the same room
  - traffic_space: two objects both encroach on the same circulation polyline

**Skip:**
- Issues (Tier 2C)
- Observations beyond what's implicit in the graph (Tier 2C)
- Refined traffic analysis with pinch points (Tier 2D)
- Illumination grid (Tier 2D)

**Validate before moving on:**
- Render zones as colored regions over the floor plan. Do they match how you
  would describe the room ("the seating area, the work nook, the dead corner")?
- For each `INTENDED_FOCAL` point, ask: does this match what the room is
  designed around? If it doesn't, the heuristic needs tightening before
  downstream analysis trusts it.
- Spot-check 5 blocking relations against the photo.

**Risk this tier proves out:**
"Can we cluster the room into functional zones and identify focal points
robustly enough that issue detection in the next tier will fire on the
right things?"

---

## Tier 2C — Core Issues & Observations (target: 4–5 days, the load-bearing tier)

**Goal:** Implement the issue detection rules and key observations. This is
the tier whose output the LLM consumes in the Claim-1 test.

**Issues to implement first** (pick these for the initial Claim-1 attempt —
they have crisp deterministic rules):

- `BLOCKED_DOORWAY` — any movable/heavy_movable object's footprint within
  threshold of a doorway floor_position
- `INSUFFICIENT_CLEARANCE` — primary path min width below 0.30 normalized
  equivalent; or zone-internal clearance (sofa-to-coffee-table, bed-to-wall)
  below typological convention
- `BLOCKED_TRAFFIC_PATH` — circulation polyline intersects an object footprint
  with severity proportional to intrusion area
- `BLOCKED_WINDOW_ACCESS` — large object directly against window, blocking
  opening/cleaning/curtain operation
- `SEATING_FACES_BLANK_WALL` — facing relation from seating ends in a wall
  hit with no nearby focal point and no decorative anchor
- `SEATING_BACK_TO_PRIMARY_LIGHT` — facing direction of seating is opposite
  to direction of strongest window
- `LARGE_DEAD_ZONE` — dead zone polygon exceeds threshold (e.g. >15% of free
  floor area)
- `NO_CLEAR_FOCAL_POINT` — no focal point has strength above threshold OR no
  seating object faces any focal point
- `MISSING_FUNCTIONAL_ZONE` — using `inferred_purpose` from Layer 1 + a table
  mapping purpose → expected zone kinds, flag any expected zones not detected

**Observations to implement:**

- `PRIMARY_LIGHT_DIRECTION` — from the strongest light source node
- `LIGHT_QUALITY_SUMMARY` — pass through from perception's overall_light_quality
- `PRIMARY_SIGHT_LINE` — strongest facing relation from a seating-class node
- `ROOM_ASPECT_RATIO` — from perception dimensions
- `CEILING_HEIGHT_CHARACTER` — bucket the normalized ceiling-height ratio
- `VISUAL_DENSITY` — total object footprint area / total floor area
- `HEAVIEST_FIXED_ELEMENT` — the FIXED-movability object with the largest
  bbox volume; the thing every design has to accommodate
- `MATERIAL_PALETTE_SUMMARY` — frequency-weighted material counts across objects
- `COLOR_TEMPERATURE_TILT` — aggregate LAB b-channel across surface colors

**Defer to Tier 2D:**
- `OVERSIZED_FURNITURE`, `UNDERSIZED_FURNITURE` — require proportion judgment
- `UNBALANCED_VISUAL_WEIGHT` — requires visual weight estimation
- `WASTED_SIGHT_LINE`, `COMPETING_FOCAL_POINTS` — refinements of Tier 2C work
- `NO_ARTIFICIAL_LIGHT_IN_DARK_ZONE` — needs illumination grid
- `DESK_FACES_LIGHT_GLARE_RISK` — needs time-of-day reasoning
- `ZONE_CONFLICT` — needs Layer 3 functional purpose
- `LEFT_RIGHT_BALANCE` — requires visual weight estimation

**Validate before moving on — THIS IS THE CLAIM-1 GATE:**

Same test as defined in Layer 1's build plan, but now Prompt B uses the full
graph output, not raw perception JSON:

- **Prompt A:** raw image only + "suggest three specific changes and explain why"
- **Prompt B:** Tier 2C-complete `SpatialRelationshipGraph` (no image) + same prompt

Score each on:
1. **Specificity** — cites specific objects and positions, not generalities
2. **Falsifiability** — could the response have been written about a different
   room? If yes, it's not grounded.
3. **Spatial reasoning** — references clearances, sight lines, traffic flow,
   light conflicts, dead zones?

**If Prompt B is meaningfully better on ≥2 of 3 dimensions on 5 test rooms:
Claim 1 holds. Proceed to Layer 3.**

**If not:**
- First, try adding more issue kinds from the deferred list — maybe one of
  them is the missing piece
- If still not better, try a hybrid: pass the graph AND the image. If that
  decisively beats raw-image-only, the perception is contributing, just not
  enough alone — acceptable, but with implications for cost (every Layer 4
  call now has vision context)
- If hybrid also doesn't beat raw image: serious thesis problem. The
  spatial reasoning isn't where the differentiation lives. Reconsider what
  the moat actually is — possibly it's the conversational refinement loop
  (Tier 2 of the product brief) plus the rendering pipeline, not the
  perception/reasoning stack

**Risk this tier proves out — the central thesis question:**
"Does structured spatial analysis unlock LLM reasoning that vision-language
inference can't match on its own?"

---

## Tier 2D — Refinements (target: 3–4 days, after Claim-1 gate passes)

**Goal:** Add the harder issues, the computed summaries, and the illumination
grid. Improves Layer 4's input quality but does not make-or-break the thesis.

**Add:**
- Remaining issue kinds from the deferred list above
- `FunctionalZoneSummary` for each zone (completeness, coherence, missing members)
- `FocalPointRanking` with ordered focal points and their followers
- `TrafficAnalysis` with full polyline, pinch points, secondary paths
- `LightAnalysis.illumination_grid` — 8x8 floor-plane illumination estimate
  via ray casting from light source nodes through object occluders
- `dark_zone_polygons` derived from the illumination grid

**Validate:**
- Re-run the Claim-1 test with Tier 2D-complete output. Did the LLM's responses
  get noticeably more specific or insightful, or was Tier 2C already saturated?
- This tells you which Tier 2D additions actually mattered, useful for
  prioritization later

---

## What Tier 2A–2D explicitly do NOT include

- **Aesthetic style classification.** "This reads as minimalist." → Layer 3 / Taste Graph.
- **Psychological comfort scoring.** → Room Health System (separate component
  that reads this graph as input).
- **Design suggestions or proposed changes.** → Layer 4.
- **Style-aware focal point selection.** "This room's focal point should
  shift from TV to fireplace because the user prefers maximalist warmth"
  is Layer 4 reasoning, not Layer 2.
- **Versioning / diffs across designs.** A separate concern, lives above
  the layer stack.

---

## Time budget summary

- Tier 2A: 2–3 days
- Tier 2B: 3–4 days
- Tier 2C: 4–5 days (Claim-1 gate)
- Tier 2D: 3–4 days (after gate passes)

Roughly 12–16 days total. Combined with Layer 1's 9–13 days, you're looking
at three to four weeks from project start to Claim-1 gate. That's the
honest budget for thesis confidence.
