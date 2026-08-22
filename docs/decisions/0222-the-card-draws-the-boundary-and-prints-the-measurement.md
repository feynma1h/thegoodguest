# 0222 — the card draws the boundary and prints the measurement

**Date:** 2026-08-22
**Status:** Decided

## Context

The calling card is "a picture of a measurement" (`docs/product/social-layer.md`
§6.2), and its acceptance test is that the contour is true to measurement and
that every number on it is derived rather than typed. A shell offers two
geometries to be true to, and the difference is load-bearing (0069):

- `polygon` / `quad` — what the viewer RENDERS, after closure has extended a
  wall to meet its neighbour or dropped it to the floor.
- `measured_polygon` / `measured_quad` — what was DETECTED.

On the roomplan method — the product's own LiDAR path — the two are the same
object, CapturedRoom geometry verbatim, and the question does not arise. It
arises on `arkit_planes` and on the `anchor_envelope` degrade.

## What we tried

**Draw the measured geometry throughout.** This is the reading the repo's
instincts push toward: measurement survives beside the render everywhere else
(`measured_quad`, `splat_clip`, the design spec's `measured_footprint`), so a
card about measurement should draw the measured polygon.

It was built. It creates one problem and appears to solve it exactly. An
opening's `rect_uv` is normalized against the RENDERED polygon's in-plane
bounding rect (`lib/shell3d.ts` mirrors the server frame), so a fraction taken
from the rendered wall cannot simply be replayed against a shorter measured
one — so openings were resolved to their world position in the rendered frame
and then expressed against the measured segment, on the u-axis both project
onto, with anything outside the measured extent clipped away.

Every test passed. Then it was rendered, against the v2 fixture whose floor
coverage and wall positions deliberately differ, and it was plainly wrong: a
ghost outline ran 10 cm inside every wall, doubling the room's edge.

The cause is that `floor.measured_polygon` does not mean what the name
suggests in this context. It is the floor COVERAGE the scan observed — how
much floor the camera saw — not the room's boundary. The boundary is where the
walls are, and those walls were measured too. The fixture's own
`provenance.edges` says so: the differing edges read
`extended_to_wall:wall_00`.

## What we chose

The card **draws the rendered boundary** and **prints only what was detected**.

- The contour is `floor.polygon`, and each wall's plan segment is its rendered
  extent. Openings sit at their `rect_uv` fractions directly, with no
  reprojection.
- A wall is dimensioned only when its detected extent matches its rendered
  extent ALONG THE WALL. Closure dropping a wall to the floor does not
  disqualify its length; closure widening it does.
- The ceiling is the tallest DETECTED wall height, which is a lower bound —
  the scan only measured what it saw.
- A room where closure widened every wall gets no dimension at all rather than
  a number the scan cannot stand behind.

`measure.ts` carries the whole rule; `measure.test.ts` pins both halves,
including a fixture mutated so that no wall qualifies.

## Why

**Closure reconciles measurements; it does not invent.** An edge marked
`extended_to_wall:wall_00` was closed to a wall that was itself measured. Two
measurements meeting is not a fabrication, and drawing the coverage polygon
instead does not make the card more honest — it makes it depict how much floor
the camera happened to see, which is a fact about the scan rather than about
the room.

**The rendered frame is the only self-consistent one.** Openings are
normalized against it. Drawing walls in one frame and placing their windows
from another is a correspondence that has to be maintained by care, and the
version that maintained it was more code, harder to check, and still wrong.

**The two claims are genuinely different and deserve to be separated.** A
drawing is a depiction; a printed number is an assertion. The failure mode
worth engineering against is not "the outline is 10 cm off" — it is "3.5 m"
under a wall that was never measured end to end. Splitting them lets the card
be a complete picture and a conservative claim at the same time, which the
all-measured version could be neither of.

**The rejected version passed every test it had.** That is the durable lesson
here and the reason this note exists: the defect was a correspondence between
two geometries, and correspondence is what a render shows and a unit test
does not. The og-card reproduction test in `measure.test.ts` compares
world-space geometry to the hand-authored precedent and would have gone on
passing.

## What would change this decision

- **A shell stops carrying per-edge closure provenance.** The argument rests on
  closure being a reconciliation between two measurements, which
  `provenance.edges` is what makes checkable.
- **The card gains a legend, or a second line weight that reads as
  deliberate.** Drawing both geometries was rejected because a card travels
  alone and cannot explain itself to a stranger, not because both are not
  true. A surface that can explain itself may want both.
- **`arkit_planes` and `anchor_envelope` stop shipping.** The question is only
  live on those paths; on `roomplan` the two geometries are one object.
