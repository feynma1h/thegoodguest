# 0155 — the single-viewpoint ceiling, and why guidance cannot pass it

**Date:** 2026-08-13
**Status:** Refuted — settles the capture-guidance question 0150 opened

## Context

The operator's argument, and it is the strongest form of it: *"if every
candidate is bad, isn't that evidence that we should be having the live
view while capturing and guiding the user while they are doing so, so that
we never even run into these problems?"*

It follows validly from everything measured so far. It is only true,
though, if a much better single frame is physically achievable. A single
view of a solid object cannot see more than its front-facing half, so
there is a geometric ceiling that no guidance can raise, and where the
best achievable frame sits relative to that ceiling is a measurement
nobody had taken.

0154's numbers could not answer it: its denominator is the union over ~70
frames, which absorbs every frame's depth noise, and a frame that saw
everything would still score well under 1 (two viewpoints 1 cm apart share
only 0.17-0.60 of their voxels).

## What we tried

A reference of voxels seen by at least THREE frames, which drops
single-frame noise, then greedy cover: what the best one, two and three
viewpoints contribute to it. 15 box objects, 23-71 qualifying frames each.

    the SHIPPED frame covers      median 0.18
    the BEST single frame covers  median 0.31, and 0.50 at its maximum
    the best THREE together cover median 0.65

## What we chose

**Live capture guidance is not the fix, and this is the reason — not
0150's.** 0150 argued from coverage not being scarce, which was true but
oblique. The direct reason is that the best single frame already covers a
median 0.31 and tops out at **0.50**, which is exactly the geometric
ceiling for one viewpoint of a solid object: you see the front-facing
half, never the back. The best-case objects in these captures are AT the
ceiling. A perfectly guided user standing in the ideal spot cannot pass
it, because it is not a capture failure.

**Selection is worth having, and needs no user at all.** 0.18 to 0.31 is
a 1.7x gain in the surface a reconstruction is fed, and the 0.31 frame is
already sitting in the capture. That is free and server-side. Combined
with the sharpness gap (0153, median 0.50 of the best available), it is
the cheapest improvement available anywhere in this pipeline.

**Three frames reach 0.65 — more than double the best single frame.**
That is 0151's multi-view union with a magnitude on it at last: the third
viewpoint contributes more than the best one contains. The object's
surface is not missing from the capture; it is distributed across frames,
and no single-frame policy can gather it.

## Why

The three numbers rank the three candidate fixes against each other for
the first time, on one instrument:

| | surface fed to the reconstruction | needs |
|---|---|---|
| today | 0.18 | — |
| better selection | 0.31 | server-side, free |
| best 3 views unioned | 0.65 | registration (0151) |
| better capture guidance | ≤ 0.50, one frame | the user, and it cannot pass the ceiling |

Guidance is the only one of the three that asks something of the person
holding the phone, and it is the one with the lowest ceiling.

## What would change this decision

**The one honest case for guidance survives and is narrow.** The reference
here is what the capture SAW, so surface no frame ever saw — the back of a
cabinet against a wall — is absent from both sides of the ratio and this
measurement is blind to it. If a future instrument shows objects whose
reconstructions fail for want of surface that no frame in the capture
holds, guidance about obstruction (0152: get low, move the chair) becomes
the fix for those, and only those.

**And the ceiling argument dies entirely if reconstruction stops being
single-view.** With a model or a union consuming several frames, "which
single viewpoint" stops being the question, guidance would be about
covering an object from several sides rather than finding one perfect
angle, and 0150's original reasoning — that coverage is not scarce —
becomes the operative one again.
