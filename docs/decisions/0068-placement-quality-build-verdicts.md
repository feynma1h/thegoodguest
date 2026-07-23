# 0068 — placement-quality build verdicts: brief contracts vs measured reality

**Date:** 2026-07-23
**Status:** Decided

## Context

Executing decision 0067's chunks A–C (branch `placement-quality-build`, merged as `e72a256`). The build brief pinned verify-first probes V1–V3 with concrete pass criteria against the recorded scene-`25a14caf` observations. Three of those criteria met reality in ways worth recording: two brief contracts were amended by measured counterexamples, and one gate failed honestly, re-opening a fork 0067 had provisionally closed.

## What we tried

1. **V2 correspondence, the brief's raw-containment dedup** ("a mask fully contained in another same-label mask is duplicate evidence"): real frame data produced a counterexample — one door mask fully contains TWO genuinely distinct doors; raw containment would absorb real objects.
2. **V2's literal bed criterion** ("seven bed observations become ONE cluster"): after dedup kills the frame-28 nested pair, the result is 5+1 — frame 18's centroid ray points ~26° off the bed center, and even the silhouette-FITTED volume projects entirely outside frame 18 (measured), so no footprint join can honestly claim it.
3. **V1's chunk-C in-plane gate** ("resolve the curtain's 90° in-plane error with clear margin"): with tier 2 fully wired at the design's 128 px, the instrument ranks the shipped-wrong candidate last-of-4 — it sees the right direction — but the winner's margin is ≈0.0007 vs the 0.03 gate.

## What we chose

1. Dedup is a **mutual-singleton rule** — both masks must be each other's only same-label containment partner. The frame-28 nested bed pair still dies; the door trio survives.
2. The bed ships as **5+1**: the wrongly-placed phantom bed is eliminated; the residual is one honest unplaced single (`insufficient_observations`), not a forced join.
3. In-plane resolution **stands down below the margin gate**: `in_plane_resolved: false`, the layout rotation ships unchanged. Per 0067's own re-open clause, the **instrument fork RE-OPENS for near-square planar objects**. The failing margin is pinned in `test_placement_quality_real_data.py` so a better instrument surfaces as a good pin failure.

Two smaller deliberate deviations, documented at the code: best-member reselection is depth_fit-clusters-only (ray members carry no complete per-member transform — rationale at `_reselect_best_placed_member`); candidate margins use the combined score.

## Why

All three are the same principle 0052/0065/0066 established: never let a contract force a claim the evidence doesn't support. The brief's criteria were written from the design session's data reading; the build's measured probes are the better instrument, and where they disagree the measurement wins. The in-plane failure specifically is a capability fact, not a wiring bug — appearance NCC at 128 px cannot distinguish a near-square curtain's 90° candidates (the pleats are the only signal at that resolution), and the instrument correctly REFUSES rather than coin-flipping at margin 0.0007.

## What would change this decision

- A tier that clears the 0.03 margin on the pinned curtain case (higher resolution, oriented-gradient features, or a learned embedding) re-closes the in-plane fork — the pin flips to green and `in_plane_resolved` starts shipping true for near-square planar objects.
- If frame-18-style off-center rays prove common across more captures, the footprint-join threshold gets revisited — the 5+1 outcome is per-scene evidence, not a law.
- Chunk D's contact priors may independently place the residual single-frame bed observation, mooting the 5+1 residual.
