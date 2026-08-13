# 0151 — splat-to-splat registration is ajar, not open

**Date:** 2026-08-13
**Status:** Probed, not built

## Context

0146 and 0150 close both stated attacks on class-6 truncation: picking a
better view among the ones you hold does not work, and capturing more
views does not help because the pipeline already discards 96–98% of the
good ones. What that leaves is the attack nobody has tried — SAM 3D
reconstructs from ONE view, the pipeline ships one splat and throws the
rest away, so **using more than one view of an object** is the only
remaining channel through which a capture's real coverage could reach the
output.

Its precondition is cheap to test and worth knowing before anyone scopes
the build: two reconstructions of one physical object, each placed by its
own fit, would have to be registerable to each other.

## What we tried

**They do not already align.** Six pairs across the four preserved rooms:
placed centres 0.11–0.78 m apart, principal frames 10–52° apart even after
allowing every axis permutation and sign, symmetric nearest-neighbour RMS
0.07–0.42 m. The best pair (rp7's monitor) is still 7 cm of RMS on a
0.39 m object — a union would be a ghosted double image.

**Trimmed ICP closes most of it, and RMS says it closes all of it.** From
each splat's own fit, `refine_similarity_nn` in similarity mode over 12
passes brings RMS to 0.009–0.093 m, and 24 axis-aligned restarts only help
two pairs. On RMS alone this looks like a solved problem.

**It is not, and the check that catches it is scale drift plus mutual
coverage:**

| pair | RMS | scale ratio | coverage A / B |
|---|---|---|---|
| rp7 monitor | 0.009 | 1.03 | 0.90 / 0.55 |
| spike cabinet | 0.022 | 1.13 | 0.75 / 0.57 |
| rp7 desk | 0.026 | 1.43 | 0.63 / 0.28 |
| rp6g1 desk | 0.030 | 1.25 | 0.54 / 0.23 |
| rp6g1 bed | 0.047 | **1.91** | 0.22 / 0.05 |
| spike bed | 0.093 | **1.70** | 0.08 / 0.08 |

Two register honestly. The rest are trimmed ICP finding a locally
consistent sliver: the bed pairs inflate one reconstruction by 70–90% and
end with 5–22% mutual coverage, which is two surfaces grazing, not one
object seen twice.

## What we chose

Nothing built. Recorded, with the discriminator, because the next session
to reach for this will otherwise reach for RMS.

**Splat-to-splat is a genuinely different question from the three dead
instrument families** (0081, 0104), which all score one reconstruction
against thin external evidence — a photo, or a single-view LiDAR surface
correlated with that same reconstruction's truncation. Two dense surfaces
of the same object are evidence of a kind none of them had, and on the two
honest pairs the registration is decisive.

**But RMS is not the acceptance criterion.** Similarity ICP will always
find a scale that makes some subset agree. Any build here needs scale
drift bounded and mutual coverage measured, and should refuse rather than
union when either fails — the same shape as every other gate in this
pipeline.

## Why this matters beyond the union

A union of registered reconstructions has honest proportions, and 0081's
central finding is that **extent consistency is "actively MISLEADING under
visible-region truncation"** — that is why the axis instrument abstains on
most boxes and the extent-best default ships. Remove the truncation and
the premise of that failure weakens. So this is the one line of attack
that could reach the rotation ceiling indirectly, without re-running any
of the instruments that are measured dead.

## What would change this decision

Nothing needs to change for it to be picked up — it is a probe result, not
a refusal. What it wants before a build is a criterion for when a
registration is trustworthy, validated on more than the two pairs that
worked here.

If a reconstruction model arrives that consumes several views itself, or
exposes calibrated metric scale or pose (decision 0052's standing
trigger), this whole approach is obsolete before it is built — which is a
reason to keep the probe cheap rather than to hurry.
