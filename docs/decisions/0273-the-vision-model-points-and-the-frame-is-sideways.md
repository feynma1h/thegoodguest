# 0273 — a vision model points at the missing part, and the frame is stored sideways

**Date:** 2026-08-30
**Status:** Decided (measured; nothing built — one GPU check outstanding)

## Context

0271 recovered the desk's second leg with a click at (1192, 967) and recorded
that the pointer was a human eye. [0272](0272-the-unclaimed-signal-cannot-be-tested-here.md)
closes the geometric candidate on this capture. The remaining one is a vision
model asked where an object is incomplete — the only candidate that needs no
depth, which matters because 0267 found a whole room arriving without any.

**0156 is not a prior against this.** That note refuted a vision model *as
implemented* on the facing sign, where it was asked to compare two renders of a
single-view splat and failed because SAM 3D invents a plausible far side. The
input was a fabrication. Here the model is shown a real photograph and asked
where it disagrees with a mask. Different question, different input, and a
successor reading "the VLM is refuted" would skip the one case where it works.

## What we tried

Frame 50, the shipped desk mask tinted blue, the model asked to list every piece
of the desk's own structure the blue region missed, largest first, with a point
inside each. Scored against `leg2_mask.npy` — 19,328 px, **0.70% of the frame**.
Eight trials per arm.

| arm | model | orientation | inside target | within 30 px | median closest |
|---|---|---|---|---|---|
| base | sonnet-5 | as stored | 0/8 | 0/8 | 735 px |
| base | sonnet-5 | upright | 0/8 | 5/8 | 25 px |
| + shadow hint | sonnet-5 | upright | 1/8 | 7/8 | 20 px |
| **base** | **opus-5** | **upright** | **5/8** | **8/8** | **0 px** |
| + shadow hint | opus-5 | upright | 3/8 | 5/8 | 20 px |
| control: target already claimed | opus-5 | upright | **0/8** | 0/8 | 641 px |
| control: as stored | opus-5 | as stored | **0/8** | 0/8 | 422 px |

Opus upright is consistent to a fault: **8 of 8 rank-2 answers land at
x 1130-1180, y 919-939**, every one named "left leg column below tabletop" or
"left leg / support under tabletop", 43-64 px from the operator's own click.
Rank 1 is the right leg every trial — a real, larger, unoccluded gap.

**Two controls, because 8/8 needs disproving rather than repeating.** Tinting
the shipped mask UNION the whole target moves the answer 641 px away: the model
promotes the right leg to rank 1 and, where it still says "left leg", points at
the leg's base below the claimed region. **It reads the mask; it does not recite
that desks have two legs.** And the orientation gap survives on the stronger
model — as stored, Opus names "table leg at far right" and a left-hand piece in
**0 of 8**.

## What we chose

**Nothing built.** Two findings recorded, and one check named.

**1. The pointer works, and the ranked list is load-bearing.** Rank 1 is the
right leg in 8 of 8. A pointer returning only its top answer misses this target
every single time. 0271 already established the consuming policy — merge every
candidate that kept what it was given — so several points per object is the
shape that fits.

**And the registered click is NOT a fully automated coordinate — I chose the
rank.** (1149, 926) is the mean of the eight rank-2 answers, and rank 2 was
picked knowing the target was the left leg, which is selection on the outcome.
What rescues it is that the ordering is stable rather than cherry-picked
per trial: rank 1 is the right leg in 8 of 8, rank 2 the left leg in 8 of 8,
rank 3 the target in 0 of 8. So a consumer that clicks EVERY ranked answer,
knowing nothing about which rank matters, reaches within 30 px in **8 of 8** and
inside the target in **5 of 8**, against **0 of 8** for the top answer alone.
Lists average 2.75 entries, so the automated form costs about three clicks per
flagged object rather than one, and the existing retention bar does the choosing.
The averaging is nearly free — the eight land inside x 1130-1180, y 919-939, so
any single call is within 20 px of the mean — but it is still eight calls where
production would make one.

**2. The frame is handed to the model sideways.** Captures are stored in ARKit's
landscape buffer, and the room is rotated 90°. Rotating costs nothing and is
worth 422-735 px against 0-25 px on two different models. Anything in this
system that shows a captured frame to a vision model — this, and the material
inference call in `/shell` — is doing it in the orientation the phone happened
to hold, and that has never been measured before.

## Why

**The reason it works is the reason geometry could not.** Every instrument in
0261-0272 asks a question about pixels or points. "One leg is showing and a desk
needs two" is a question about structure, and structure is what survives shadow.
0270 measured the leg at luma 111 against a lit desk at 195-204 and named that as
the reason four colour-based searches ran past it. The model that finds it is not
looking at brightness.

**The hint that helped the weaker model hurt the stronger one.** Telling Sonnet
the piece may be in shadow moved it 0/8 → 1/8 inside and 5/8 → 7/8 within 30 px.
The identical sentence took Opus 5/8 → 3/8, sending it to the right leg in 3
trials. **A hint written from an observed failure encodes that failure**, which
is the same shape as the four guards 0269/0270 had to delete. It is not carried.

## What would change this decision

**One GPU round settles it, and the prediction is registered here.** Drive the
`/segment` probe's `--refine-click` at **(1149, 926)** against frame 50, seeded
from mask index 6 — the longer desk mask, 342,215 px — which is the identical
call 0271 made with the operator's (1192, 967), one argument changed. That is the centroid of all eight
rank-2 answers, not of the five that hit — averaging only the hits selects on
the outcome, and the eight are tight enough that it costs nothing: x 1130-1180,
y 919-939, every one of them within 20 px of that point, and the point itself
inside the target. The machinery is already deployed and verified from `gcloud`
on 2026-08-30: production is 100% on `perception-obj-00074-var`, and
`perception-obj-00088-vot` sits at 0% traffic carrying
`PERCEPTION_SAM3_INTERACTIVE=1` beside the two ruled-on flags.

**Predicted: best second-leg coverage above 50%.** 0271's click reached 75.0%
from 43-64 px away, and 0269 measured this loop's sensitivity to click placement
as the thing that made it delete the near foot, so the two are not
interchangeable on principle. Below 20% would mean the model finds the right
structure and not a usable click, and the finding degrades from "a pointer" to
"a detector that still needs a human for coordinates".

**What is NOT established:** anything about a second object, a second room, or a
part that is not a leg. One target, one frame, one capture. The controls rule out
recitation on this image; they say nothing about whether the model invents parts
on an object it cannot see well. A second located target is what generalises
this, and it is the same thing 0272 needs.
