# 0273 — the keyframes are already a video, and that is what makes a tracker applicable

**Date:** 2026-08-30
**Status:** Decided (measured)

## Context

0271 routes out of the boxless-object problem through an object→frame map, and
the only thing that produces one is SAM 3.1's video tracker — the detector half
of SAM 3 returns instances as rows of a tensor with no identity between calls.

A memory-based tracker assumes temporal continuity. Our captures are not video:
`CaptureManager` accumulates keyframes by POSE DELTA, at 10 cm or 5°, and
throws the rest away. Whether a tracker can work on that set at all is prior to
every other question in the migration, and nothing in this repo records the
answer — the accumulator's thresholds are written down, what they actually
produce is not.

## What we tried

Measured across the 188 consecutive gaps of `capture-90eebfc4` (189 frames,
39.5 s):

| | median | p90 | max |
|---|---|---|---|
| time | **0.167 s** | 0.383 s | 1.150 s |
| translation | **3.0 cm** | 10.0 cm | 10.9 cm |
| rotation | **5.21°** | 5.72° | **6.18°** |

**The two gates partition the gaps exactly.** 165 of 188 (87.8%) are at or over
the 5° rotation threshold; 23 (12.2%) are at or over 10 cm of translation.
**Zero gaps are both, and zero are neither.** Every keyframe in this capture
exists for exactly one reason, and seven times in eight that reason is rotation.

The consequence is the number that matters. At `fx = 1338` on a 1920-wide
frame the horizontal field of view is 71.3°, so the **largest** inter-frame
rotation in the whole capture is **8.7% of the frame width**, and the median is
7.3%. Consecutive keyframes overlap by at least 91% of the field of view.

## What we chose

**Treat the keyframe set as a video, and record the measurement as the reason.**
189 frames over 39.5 s is 4.8 fps of effective playback, with a worst-case
inter-frame motion far smaller than the gap a tracker is built to bridge — SAM
3's tracker exists to survive occlusion and re-identification across a scene,
not to survive 6°.

## Why

**"Keyframes, not video" sounds like a disqualifier and is not one.** The phrase
describes how frames are SELECTED, and a tracker cares about how much the image
CHANGES between them. Those come apart here: the selection rule is aggressive
about discarding redundancy, and what survives is still a slow, near-continuous
pan. Reasoning from the description rather than the measurement would have
killed this migration before it started, for free, and wrongly.

**The 7:1 rotation share is the mechanism.** A person scanning a room pivots far
more than they walk — median translation is 3.0 cm against a 10 cm gate, so
translation almost never fires. That is why the frames stay well-overlapped:
the capture is paced by the one motion that changes the image least per unit of
coverage gained.

**And it is a property of the capture rule, not of this room.** The gates are
`CaptureManager`'s, so any capture from this app has the same ceiling — 5° and
10 cm — whatever the room contains. A capture whose gaps were paced by
translation would look different, and this is the measurement to repeat if one
ever appears.

## What would change this decision

**A capture whose gaps are mostly translation.** 23 of 188 here; a room walked
rather than pivoted would invert the ratio, and 10 cm of translation close to an
object moves the image far more than 6° of yaw does. The per-capture check is
cheap and belongs beside any tracking run on a new room.

**A raised keyframe threshold.** 0062's fired trigger asks for more frames, not
fewer, so it moves the safe direction. Loosening the gates to save upload would
move the other way, and this note is the constraint that change has to clear.

**A time gap is NOT the thing to watch.** The 1.150 s maximum looks alarming
beside a 0.167 s median and is not: the tracker's memory is indexed by frame,
not by clock, and the pose deltas at that gap are inside the same 6° / 11 cm
envelope as everywhere else.
