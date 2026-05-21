# Claim-1 Test — Setup & Methodology

## What this is

The decisive test for the RoomMind thesis: does feeding an LLM a structured
SpatialRelationshipGraph produce meaningfully better design reasoning than
feeding the same LLM a photo of the room?

If YES (graph wins on ≥2 of 3 criteria across test rooms): the
"spatial intelligence platform" thesis has substance. Build the pipeline.

If NO: the perception/reasoning stack is not where the differentiation lives.
Reconsider what the moat actually is — possibly conversation, rendering,
or product judgment, but not the AI stack.

## Why you're running this BEFORE building the pipeline

The pipeline takes 3–4 weeks to build. The test takes a day. If the test
fails, you save 3–4 weeks of work and rethink the architecture. If the test
passes, you build the pipeline with conviction.

The catch: the test uses a HAND-CRAFTED graph, not a pipeline-generated one.
This means the test is *optimistic* — it assumes the pipeline produces clean,
correct output. The real pipeline will produce noisier output and the win
margin will shrink. That's fine; this test gives you the upper bound. If the
upper bound isn't decisively positive, the realistic case won't be either.

## Setup

```bash
cd roommind
pip install anthropic pydantic
export ANTHROPIC_API_KEY=sk-...
```

## Step 1 — Pick a real room

You need one photo of one real room. Constraints:

- **Real, not stock.** Stock photos are professionally staged and don't have
  the problems we want to test detection of. A photo of your own living room,
  your office, a friend's apartment — better.
- **Has visible problems.** A perfectly designed room is the wrong test.
  You want something with a couple of clear issues: bad sofa placement,
  wasted corner, dark zone, blocked traffic, mismatched proportions.
- **Single room.** Not a hallway opening into three other spaces.
- **One angle is fine.** The schema accepts supplementary views but for v0.1
  testing, one good wide shot is enough.

## Step 2 — Hand-craft the graph for that room

This is the hard part. You're producing what the Layer 1+2 pipeline would
output if it worked perfectly. Reference `test_data/graph_room1.json` as
the template — it shows what every field should look like.

Process I recommend:

1. **Open `room_perception_v2.py` and `spatial_graph.py` side by side.**
   You're filling in both implicitly — the graph schema is what gets fed to
   the LLM, but its fields reference perception data, so you need both.

2. **Measure the room (rough is fine).** Pace it out, measure with a tape
   if you have one. Set `scale_factor_m` in the perception's geometry.

3. **List objects.** For each visible piece of furniture, fixed element,
   light source, and architectural feature, add an entry. Use room-normalized
   coordinates (longest dimension = 1.0). Origin at floor centroid.

4. **Build zones.** Cluster objects functionally: seating, work, sleeping,
   storage, dining. Mark dead zones for large unused regions. Mark the
   circulation zone for the inferred path between doorways.

5. **Build focal points.** One per major focal candidate: windows, fireplaces,
   TVs, major art, architectural features. Rank by strength.

6. **Compute edges by hand.**
   - facing_relations: for every oriented object, what does its facing axis
     point at? Look at the photo. Use 0.0 for directly-facing, π for
     facing-away.
   - adjacency_relations: for every pair of objects within a proximity
     threshold (say, separation_normalized < 0.15), add an edge.
   - blocking_relations: any object that intersects a sight line, traffic
     path, light path, or doorway access — flag it.
   - complementary_relations: canonical pairs (sofa-coffee_table,
     bed-nightstand, rug-anchors-zone).
   - competing_relations: zones contending for same wall, focal points of
     similar strength, traffic conflicts.

7. **Detect issues.** Go through the IssueKind enum. For each kind, ask:
   does the room have this problem? If yes, add an Issue with measurement
   data backing the claim.

8. **Add observations.** Go through ObservationKind. For each, fill in the
   payload from your perception data.

9. **Validate it parses:**
   ```bash
   python -c "
   import json
   from schemas.spatial_graph import SpatialRelationshipGraph
   with open('test_data/graph_YOUR_ROOM.json') as f:
       SpatialRelationshipGraph(**json.load(f))
   print('Valid')
   "
   ```

**Be honest in the hand-crafting.** Do NOT pre-load issues with the exact
problems you want the LLM to identify. Build the graph as if you were
running an honest perception pipeline. If a problem is real but the
detection rule wouldn't easily catch it, leave it out of the issues list
and only include it implicitly through the structural relationships.
Otherwise you're testing your scoring of your own room, not the schema.

Time budget for this step: 2–3 hours for the first room. Faster for subsequent.

## Step 3 — Run the test

```bash
python claim1_test.py --room room1 --image path/to/photo.jpg --graph test_data/graph_room1.json
```

This appends results to `results.md`. Open it.

## Step 4 — Score the results

Read both responses carefully. Score each on three criteria:

### Specificity
- Does it name specific objects (by class, position, or ID)?
- Does it give measurements (distances, ratios, sizes)?
- Or does it speak in generic terms ("the sofa," "the room," "the corner")?

### Falsifiability
- Could the response have been written about a different room?
- If you scrubbed the object names and gave it to someone else, could they
  tell which room it was about?
- A falsifiable response is one that *only* makes sense for this specific room.

### Spatial reasoning
- Does the response reference clearances, distances, angles?
- Does it consider light direction, traffic flow, sight lines?
- Does it chain reasoning across multiple aspects (e.g. "moving the sofa fixes
  both the light problem AND opens the traffic path")?
- Or is it primarily aesthetic ("warmer colors," "more textures")?

For each criterion, mark **A wins / B wins / Tie**.

## Step 5 — Decide

**Decisive pass (proceed to pipeline build):**
B wins on at least 2 of 3 criteria, and the margin is "clearly noticeable" —
not just a tiebreaker. Across multiple rooms, B should win consistently.

**Decisive fail (rethink the architecture):**
A wins on at least 2 of 3 criteria, OR the responses are essentially
interchangeable in quality.

**Ambiguous (run more rooms):**
B wins on specificity but A wins on aesthetic intuition; or the criteria are
split 2:1 with small margins. Run 3–4 more rooms before deciding.

## Caveats to remember

1. **The hand-crafted graph is optimistic.** A real pipeline produces noisier
   data. If the test passes narrowly, the real pipeline may fail.

2. **The model is doing some of the work both ways.** When the LLM looks at
   the image directly, it's doing implicit perception. The graph just makes
   that perception explicit and richer. A great VLM with a great photo can
   close some of the gap.

3. **You're scoring this yourself, so be adversarial with your own
   preferences.** You WANT B to win. Catch yourself if you're being generous
   to B. Better: have someone else who hasn't read your design docs score it
   blind.

4. **The 1500-token cap might bias toward Prompt B.** B has structured input
   that lets it pack reasoning densely; A has free-form input. If A is being
   cut off mid-thought, the cap is unfair. Check the responses for
   truncation; raise max_tokens if needed.

## When this test is not enough

If the test passes, you still don't have proof the pipeline will work — only
that the schema is useful when populated correctly. Tier 1A–1D and Tier 2A–2C
are the actual proof.

If the test fails, you have strong evidence to redirect. Don't try to "fix"
the test by tweaking the graph until B wins — that's optimizing toward a
target you set yourself.
