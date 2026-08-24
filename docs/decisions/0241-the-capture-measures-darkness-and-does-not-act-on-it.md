# 0241 — the capture measures darkness and does not act on it

**Date:** 2026-08-24
**Status:** Decided (built; reporting only, nothing gated)

## Context

0240 ruled that rp6g2's dark tail is a covered lens rather than an app defect.
That answers what happened and leaves the sharper question: **the app had the
evidence in its hands and said nothing.** Twenty-eight keyframes with no image
were accepted, encoded, written, uploaded, and reconstructed from — the shipped
sampler took f103 and f119 among the twelve views that room was processed from
(0234).

The sitting's ruling was to log the luminance statistic unconditionally, so the
first dim room is data rather than an invisible false positive. This note
records what that statistic is, and the choice not to let it change behaviour.

## What we tried

**Is it detectable at capture time?** Two independent signals, both already in
the frame the delegate is holding:

* **Luminance.** Mean luma of the camera's own luma plane. No colour
  conversion, no decode — plane 0 of the buffer that is about to be encoded.
* **Depth.** A full-frame plane at close range, flat to ~1 cm, holding its
  distance while the camera translates. This is the stronger signal in
  principle: it separates *obstructed* from *dark*, which luminance cannot.

Both are cheap. Neither was being computed.

The reporting floor was validated against every preserved capture rather than
tuned on the one that misbehaved — seven captures, 2,084 keyframes:

| capture | n | min | median | below 16 | longest run |
|---|---|---|---|---|---|
| rp6g1 | 249 | 105.16 | 138.06 | 0 | — |
| rp7 | 386 | 89.27 | 127.43 | 0 | — |
| **rp6g2** | 124 | **0.13** | 130.68 | **27** | **27** |
| spike | 722 | 80.63 | 139.67 | 0 | — |
| 247003de | 293 | 86.41 | 145.50 | 0 | — |
| 25a14caf | 126 | 108.72 | 143.15 | 0 | — |
| f3d70236 | 184 | 111.08 | 138.77 | 0 | — |

## What we chose

**Measure mean luma on every accepted keyframe. Report it at stop on every
capture. Change nothing else.** No frame is dropped, no tier is affected, no
copy is shown, and nothing is gated on the reading.

Three details are load-bearing:

* **The floor is 16 — the video-range black level.** A frame whose mean is
  under it is, on average, darker than the darkest value a studio-swing encoder
  can represent. Not a tuned number, and it sits in a chasm rather than on a
  boundary: healthy captures never read below **80.63**, rp6g2's tail tops out
  at **11.87**, and its first frame back above the floor reads **23.03**.
* **The summary prints even when nothing is dark.** A census that only speaks
  on trouble cannot be told apart from one that never ran.
* **The run is reported beside the count.** Twenty-seven consecutive blank
  frames is a capture that stopped seeing; the same twenty-seven scattered
  through a room is a hard room. The count alone cannot tell those apart.

## Why

**Reporting, not refusing, because the cost of a wrong call is asymmetric and
we have one example of the phenomenon.** Dropping a keyframe is unrecoverable —
the capture is over and the frame is gone — while shipping a dark one costs a
segmentation pass and, at worst, one bad view among twelve. A reporting
threshold that is slightly wrong costs a log line. A gate that is slightly
wrong costs a room. On a corpus with exactly one dark capture there is no basis
for choosing where a gate goes.

**Refusing frames would also hide the evidence for the decision.** Every number
in the table above exists because those keyframes shipped. If the app had
silently dropped them, rp6g2 would have arrived as a short capture and 0235's
finding would have been harder, not easier — the whole reason this was
invisible for weeks is that nobody was looking at what the frames contained.
Measuring first and gating later is the order that keeps the data.

**Luminance rather than depth, for now,** even though depth is the stronger
signal. Luminance is a scalar over a plane already in hand and is directly
comparable to the offline corpus numbers (0234), so an on-device reading and a
bucket-side reading are the same quantity. The depth test needs a plane fit per
frame and a co-motion test across frames, and it would be answering a question
— obstructed vs merely dark — that nothing yet consumes.

**Why the device log is where this lands, and its limit.** The capture path
already reports plane anchors and depth coverage at stop for exactly this
reason ("that depth loss was invisible until the bundle was parsed
server-side — never again"), so this follows a route that exists. The limit is
real and worth stating plainly: **a log line reaches whoever is attached to
Console and nobody else.** It makes the next dark room findable by someone who
goes looking; it does not make it visible on its own.

## What would change this decision

**The durable fix is a per-frame statistic on the bundle**, additive to
`capture_bundle.proto` the way `PlaneAnchor` (field 12) and
`RoomPlanModel.json_gcs_path` (field 4) were, so the reading travels with the
capture and the pipeline can see it without re-deriving it from pixels. Not
taken here because it widens a lane that owns the capture path into the central
contract. **Trigger: the next change to `capture_bundle.proto` for any
reason** — it should carry this field with it, rather than waiting for a second
dark room to justify its own schema bump.

**Gating becomes arguable when there is a second dark capture**, from different
hardware or a different person, to say whether the floor generalises. Until
then a gate is a threshold fitted to n=1.

**The user-facing half is untouched and is the operator's.** The app knows,
at stop, that it saw nothing for the last quarter of a scan — the review screen
is where that would be said, and what it should say is a copy decision, not a
build one.

**Unconfirmed on hardware.** This has run against the preserved capture's
readings and against synthetic planes, never against a live camera buffer.
Confirming it needs a real scan on a re-signed device build, which is the
operator's (enrollment cleared 2026-08-23; the re-sign has not happened). The
one thing a live run would settle that offline work cannot is which luma range
ARKit actually vends on this hardware — the code reads the format and handles
both, so a wrong assumption would show up as a scale error, not a crash.
