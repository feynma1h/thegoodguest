# 0235 — a quarter of rp6g2 is dark

**Date:** 2026-08-23
**Status:** Decided (a fact about the corpus, not a change)

## Context

`b667f891` — "rp6g2" in the offline harness — is one of the four preserved
captures every perception measurement in this repo regresses against. It is
also the corpus's thin case, and has been named as such repeatedly: round 2's
completeness table measured **5 of its 11 boxes losing every fully-in-frame
view** at a 0.95 bar, round 3's fused cloud gave one of its boxes **2,585
voxels** against another room's 444,126, and CLAUDE.md carries it as the
budget-starved room whose 53-item long tail stops every round.

Each of those was read as a hard room: cluttered, small, awkwardly captured.

## What we tried

Decision 0234's frame-usability veto, run over every keyframe of all four
captures. It measures mean luminance, blown-pixel share and variance of the
Laplacian — a frame-quality question nobody had asked of this corpus.

| capture | unusable frames | share | run |
|---|---|---|---|
| rp7 | 37 of 386 | 9.6% | 143-235 |
| rp6g1 | 2 of 249 | 0.8% | 244-245 |
| **rp6g2** | **29 of 124** | **23.4%** | **36, then 96-123 unbroken** |
| spike | 1 of 722 | 0.1% | 617 |

**rp6g2's last 28 keyframes are black.** Mean luminance runs **0.13 to 4.49**
against a whole-capture median of **129.5** — a factor of thirty, not a dim
tail. Frames 97 through 123 never rise above 4.5.

And the shipped sampler takes two of them: **f103 and f119 are among the
twelve frames that room was processed from.**

## What we chose

Record it against the room, so nobody reads rp6g2 as a representative capture
again without the caveat.

**It is not a hard room. It is a capture that stopped producing images a
quarter of the way from the end and kept recording keyframes.**

## Why

This matters beyond one room because **rp6g2 is the case that every thin
result in this corpus rests on**, and the defect predates and confounds all
of them.

* Round 2's "5 of 11 boxes lose every fully-in-frame view" was measured over
  124 keyframes, 29 of which show nothing. The real denominator is 95.
* Round 3's 2,585-voxel box is starved by the same 28 frames, which
  contribute depth but no image.
* Its 53-item long tail and permanent budget stop are measured on a frame
  set that includes black frames — and a black frame still costs a
  segmentation pass.
* 0227 attributed two of the corpus's five unmatched-box causes to this room
  (rp6g2 b01 NEVER_FRAMED at 0.657 in-frame, b02 SAMPLING). Neither verdict
  changes, but both were drawn from a capture a quarter of which is blank.

**None of those findings is retracted.** Each is a correct measurement of
what that capture contains. What changes is the inference: they describe a
DEFECTIVE capture, not a difficult room, and generalising from them to "rooms
like this are hard" is unsupported.

The four-capture corpus is small enough that one bad member is a quarter of
the evidence. It should keep its place — a defective capture is a real thing
production will see — but any claim resting mainly on rp6g2 now needs this
note beside it.

## What would change this decision

Nothing about the capture; it is preserved and immutable. What would change
the CORPUS is a fifth preserved room, which is the only way to stop one
defective member carrying this much weight. That is worth the operator's
attention the next time a real scan happens.

Two smaller consequences worth knowing:

* **The re-scan 0150 named as a test is more valuable than it looked.** It
  was framed as a test of a prediction that supply does not limit quality;
  it is also the cheapest way to replace this room's contribution.
* **The cause is unknown and worth one look.** Twenty-eight consecutive black
  frames with valid poses and depth means ARKit kept tracking while the
  camera produced nothing — a covered lens, a pocketed phone, or an RGB
  pipeline stall. If it is the third, it is an iOS capture defect that would
  affect real users and nobody has looked for it.
