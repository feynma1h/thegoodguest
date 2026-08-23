# 0234 — the selector can reject, but not rank

**Date:** 2026-08-23
**Status:** Decided (built, flagged off)

## Context

`select_frames_census` asks one question of a frame: where does each box
PROJECT into it. Two frames can project a box identically while one of them
is black and the other shows the object's lower half.

Every attempt to make selection smarter than that has failed. Eleven view
measures are refuted (0146, 0152, 0162), and 0197 measured the twelfth as
large and **bidirectional** — the same swap gained one table a full set of
legs and cost another the ones it had. Part-wise visibility is the newest
candidate and it carries its own tripwire: it separated an object with no leg
failure mode by 5.7x, and its top-ranked frames have never been
reconstructed.

So the question here is not "which frame is better". It is whether a frame
can serve an object **at all**.

## What we tried

Two vetoes, both REJECT-ONLY, both at zero, behind
`PERCEPTION_VISIBILITY_VETO`.

**Veto 1, whole-frame usability.** Mean luma, blown-pixel share, and variance
of the Laplacian, at thresholds chosen to reject a frame carrying no
information rather than one merely worse than another. What it found was not
subtle:

| capture | unusable | share | run |
|---|---|---|---|
| rp7 | 37 of 386 | 9.6% | frames 143-235 |
| rp6g1 | 2 of 249 | 0.8% | 244-245 |
| **rp6g2** | **29 of 124** | **23.4%** | 36-123 |
| spike | 1 of 722 | 0.1% | 617 |

**rp6g2's last 28 keyframes are black** — mean luma 0.13 to 4.49 against a
capture median of 129.5. That capture is the one room that budget-stops every
round, and a quarter of it is blank.

**Veto 2, per (object, frame) lower-band visibility.** The detector's own
geometry with the mask half absent, so it is available before any GPU work.
Fires on **3 (frame, box) pairs** across the four captures — including
`rp7 f7:box_02`, which is exactly the case that motivated it: the desk whose
legs run off the frame, 0.163 pooled and 0.000 in the lower band.

**The measured result, and it is one number.**

| | frames selected | UNUSABLE frames in the selection |
|---|---|---|
| shipped sampler | 48 across four captures | **3** — rp7 f143, rp6g2 f103, f119 |
| with the vetoes | 48 | **0** |

Two of those three are in rp6g2, the room that runs out of budget.

Predictions registered first: veto 2 fires on 6-10 of 26 planned box views
(**MISS**, 3 pairs — the denominators differ, since selection asks only about
the frames it is about to take, not about every sampled view); long-tail
detection counts drop <= 10% (**unmeasurable offline**, see below); exactly 1
of item 2's six unmatched boxes acquires a view (**MISS**, none do).

## What we chose

Both vetoes, reject-only, asked **only about the frame the pass is about to
take**. Scoring every candidate would fetch a frame's pixels and its depth
raster per keyframe — **1,444 blobs on the spike capture** — to answer a
question about the twelve that get picked. Ranking stays on the projection
alone; the veto removes a winner and the pass re-ranks.

Three properties the implementation had to be corrected to get right, each
pinned by a test:

* **The residue draws from the survivors too.** The first version wired the
  vetoes into the cover pass only, and rp6g2's black frames came straight
  back in through pose-diverse residue. A frame carrying no information is no
  more useful as spread than as coverage.
* **Per-object relaxation is the veto's counterweight, not a feature.** Veto 2
  REMOVES candidates, so it can starve a box that had few — rp6g2 carries one
  with exactly one qualifying frame across 124. The bar relaxes per box, never
  globally, until something qualifies. It fires on none of the four captures
  today.
* **A veto that empties the selection is overruled.** Found by a test that
  rejects every frame: the selector returned NOTHING. A dark capture is a
  capture problem, and the right response is a bad scene rather than no
  scene — zero frames means the room produces nothing at all, where the
  sampler's own picks at least reach the ingest gate with something a person
  can be told about. Recorded in the manifest, never silent.

`_object_aware_residue` is NOT reimplemented here. The charter's fourth
bullet — angular spread for second views — is that function, already built
behind `PERCEPTION_OBJECT_AWARE_RESIDUE` and waiting on one more room
(0202/0212). The vetoes compose with it rather than replacing it.

## Why

**Reject-only is the entire design, and it is the only posture the evidence
supports.** A veto at zero says "this frame cannot serve this object"; a rank
says "this frame is worse", and twelve measures have now failed to make that
second statement stick. The distinction survives 0197's bidirectionality
because a frame that shows none of an object's lower band cannot be the frame
that gains it a set of legs, whichever direction the effect runs.

**None of item 2's six unmatched boxes gains an association, and that is the
predicted outcome rather than a disappointment.** 0227 attributed them to
OOM, plan skip, competition, detection and never-framed — five causes, none
selection-side. The one SAMPLING case, rp6g2 b02, had its covering frame
(f51, in-frame 0.943) **already selected** in both runs; that room stopped on
budget before processing it. Selection was never what was wrong with those
boxes, and this measures it rather than assuming it.

**What the vetoes do buy is smaller and real:** three unusable frames
replaced by usable ones, two of them in the capture that can least afford a
wasted slot, plus rp7 b03 moving from a 0.929 in-frame view to a fully
in-frame one at f363.

**The long-tail regression check could not be run as specified.** It asks for
detection counts under the new sampler, and the new sampler picks frames that
were never segmented, so their counts need a GPU. The available proxy is pose
coverage of the USABLE frames — mean distance from every usable keyframe to
its nearest selected one, which is what the residue exists to minimise:

| capture | shipped | with vetoes |
|---|---|---|
| rp7 | 0.524 | **0.498** |
| rp6g1 | 0.358 | 0.379 |
| rp6g2 | 0.235 | **0.189** |
| spike | 0.571 | 0.571 |

Better on two, unchanged on one, 6% worse on rp6g1. Measured over ALL frames
rather than usable ones it looks worse on rp6g2, and that reading is an
artefact: the metric penalises a selection for not covering 28 black frames.
No regression, on a proxy, and the real check is a GPU drive.

## Two follow-ups, neither built here

**1. The long-tail check is a BLOCKER on this flag, not a completed item.**
The charter asked for detection counts under the new sampler against today's;
the new sampler picks frames that were never segmented, so the counts need a
GPU drive. The pose-coverage proxy above shows no regression, and a proxy is
not the measurement. **`PERCEPTION_VISIBILITY_VETO` must not be enabled
anywhere until that drive has run** — the residue exists to serve objects
RoomPlan does not box, and a box-shaped veto reshuffling the residue is
exactly the kind of change that could serve them worse while every number
this note reports improves.

**2. Log the luminance statistic on every capture, whether the veto fires or
not.** Veto 1's thresholds sit roughly thirty times below anything in this
corpus — rp6g2's blank tail reads 0.13-4.49 against a 129.5 median — and they
have never been tested against a genuinely dim room, a night capture, or a
motion-blurred pan that still carries structure. Today the manifest records
only what was REJECTED, so a first false positive would appear as a frame
count quietly dropping on a capture nobody thinks is dark. Recording the
distribution unconditionally turns that first dim room into data instead.
Not built here: it is a change to what every capture writes, and it belongs
with whoever next touches the manifest's sampling block.

## What would change this decision

**The thresholds are the weak point and they are not fitted.** Veto 1's three
constants were chosen to sit far below any real frame — rp6g2's blank tail
reads mean luma 0.13-4.49 against a median of 129.5, a factor of 30 — and
they have never been tested against a merely DIM room, a night capture, or a
motion-blurred pan that still carries structure. The first false positive is
the signal to re-measure, and it will look like a frame count dropping on a
capture nobody thinks is dark.

**Veto 2's rate is measured on the winners, not on the population.** Three
pairs across four captures is what selection asked about; item 4 measured 8
of 26 sampled box views with an invisible lower band. Those are different
questions and the numbers should never be compared.

**Do not turn this into a ranking.** The tripwire is already recorded: if
someone proposes ordering surviving frames by lower-band visibility, the
answer is that the measure separated an object with no leg failure mode by
5.7x, and no reconstruction has ever been run on its top-ranked frames. That
bench, not an argument, is what would reopen it.
