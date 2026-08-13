# 0153 — nobody ever looked at the picture

**Date:** 2026-08-13
**Status:** Decided — partially supersedes 0146 and 0152

## Context

0146 refuted view selection across seven measures and 0152 added three
more, concluding that ten had failed and that selection was dead ground.
The operator pushed back on the conclusion rather than the arithmetic:
*"are we even sure that the frames used for SAM 3 segment generation were
even good enough?"*

They were right, and the gap is embarrassing once named. **All ten
measures are about geometry** — where the box projects, what occludes it,
how much of the object the mask covers. Not one of them asks whether the
IMAGE was any good. A handheld capture at 60 fps produces a great deal of
motion blur; a blurry crop gives SAM 3 a sloppy mask and SAM 3D a mushy
reconstruction. The brief that opened this session even said there was "no
occlusion test, no sharpness test" — occlusion got tested and sharpness
never did.

## What we tried

Normalised Laplacian variance over each object's own projected region,
downsampled to a fixed budget so the reading tracks blur rather than crop
size, compared between the view the pipeline SHIPPED and the best the
capture holds among frames that see the box at the census cover bar.

**The shipped view is a median 0.50 of the best available sharpness, with
a minimum of 0.09, and below half on 7 of 15 objects.** The extremes:
the spike room's bed shipped at 0.303 against 3.549 available (11.7x), its
storage at 0.181 against 1.103 (6.1x), rp6g1's chair at 0.216 against
0.689 (3.2x).

It is not an artefact of the metric. Two crops were checked by eye:
the spike bed's shipped frame is visibly smeared where the available one
resolves printed text, and rp6g1's chair likewise — individual keyboard
keys and stitching in the available frame, mush in the shipped one.

And sharpness is the first measure to point the right way at all:

    r(sharpness of the shipped view, shape error) = -0.298, n = 15

Weak, and n is small, but every other measure sat at zero or had the wrong
sign. The two sharpest shipped views in the set carry two of the three
best shape errors.

## What we chose

**The claim in 0146 and 0152 that "view selection is dead ground" is
withdrawn.** What those decisions established survives precisely and
should not be re-litigated: *where the camera was* — framing, occlusion,
face balance, projected area, mask coverage — does not predict
reconstruction quality. *Whether the picture was sharp* was never tested,
and the pipeline does not look at it anywhere: the census sampler selects
on pose diversity and box visibility, the association ranks on
footprint-versus-mask overlap, and neither ever opens the image.

Nothing is built here. The operator asked to pause and think before more
code, and this note is the thinking.

## Why the fix is probably not user guidance

The sharp frames are **already in the capture**. Every object above has a
frame two to twelve times sharper than the one it was reconstructed from,
taken during the same walk. So the cheapest fix is not to ask the user for
anything — it is to stop ignoring the image when choosing frames, which
costs no GPU and no capture time.

That is a narrower and better-founded conclusion than 0150's, which it
does not contradict: 0150 ruled out per-object COVERAGE feedback because
coverage is not the scarce resource. Sharpness is not scarce either. What
is missing is selection, on both counts.

Capture guidance keeps exactly one justification, from 0152: obstruction.
rp7's and rp6g1's desks are occluded in EVERY frame of their captures, so
no amount of frame selection reaches their legs, and only a person moving
the chair or crouching would. That is worth building only after the
experiment below says an unobstructed, sharp view actually reconstructs
better.

## What would change this decision

The measurement stops at "a much sharper frame existed". It does not show
that reconstructing from it produces a better object, because none of
those frames was ever segmented — SAM 3 ran only on the twelve sampled
frames. **That needs the GPU and it is one experiment**: score candidate
frames by sharpness (and occlusion, per 0152) behind an env flag,
re-drive, and compare against the shipped reconstructions.

Two confounds to carry into it, both found while checking this one:

* the sharpest available frame for the spike bed contains a PERSON lying
  on it — the 0089 suppression population. Sharpness must not be allowed
  to select frames whose subject is suppressed or occluded by a person;
* sharpness is measured over the box's projected region, which includes
  background. Within one object across frames that is a fair comparison,
  and it is the comparison this note rests on. Across objects it is not,
  which is part of why the -0.298 is offered as suggestive rather than
  decisive.
