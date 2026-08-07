# 0097 — reveal choreography redesign: the room draws itself, then fills, then settles

**Date:** 2026-08-08
**Status:** Decided

## Context

The reveal is the product's defining moment (CLAUDE.md's thesis section), and
RP-8 (decision 0080) was the first time the operator watched it at real speed.
The verdict, verbatim: it "comes down at high speed then slows as a spring…
I'd rather things settle gracefully," and walls and floor should MATERIALIZE
IN PLACE rather than fly in — with a sketch: "boundary contour with moving
dots." That was logged as a redesign, not a constants retune, and the existing
constants were deliberately left untouched for this session.

Reading the shipped code found three defects, only one of which the operator
had named:

1. **The pieces dropped.** Each object eased from 0.40 m above its place over
   700 ms on `1 − (1 − t)³`. Ease-out cubic has its MAXIMUM velocity at t = 0:
   motion that begins at full speed and then brakes. That is precisely "comes
   down at high speed then slows as a spring." The mesh also became visible at
   full opacity at the top of the fall, so the eye was drawn to the descent.
2. **The surfaces popped.** Walls and floor went `visible = false → true` with
   no transition at all. The operator read this as flying in; mechanically it
   was worse — instantaneous appearance.
3. **The reveal was too long.** A uniform 650 ms per object meant the spike
   room (13 walls, 25 pieces) took ~22.8 s end to end. Attention is gone well
   before that.

A fourth defect surfaced during in-browser verification of the new work, and
is described below.

## What we tried

Considered and rejected for the surfaces: a scale-up "grow in place" (still
motion, still reads as arrival), and a luminance sweep across each plane
(ornament — it draws attention to the transition rather than to the room).

Considered and rejected for the pieces: keeping a downward settle but merely
lengthening it (the wrong-shaped curve stays wrong-shaped at any duration),
and a pure cross-fade with no movement at all (lifeless; the room reads as a
slideshow rather than as furniture coming to rest).

Considered for the contour: dots that circulate the finished outline
continuously. Rejected — it lingers as chrome, and "premium is not ornament"
(the operator's standing design note). The pen reading retires by itself.

## What we chose

Four movements, with ONE easing curve governing everything that moves —
**smootherstep, `6t⁵ − 15t⁴ + 10t³`, zero velocity AND zero acceleration at
both ends** — echoing the single-spring rule the DOM motion system already
follows (`components/ui/spring.tsx`).

1. **The outline.** The room's measured boundary draws itself on the dark
   stage: a pen traces the floor polygon's perimeter at arc-length-exact
   speed (three dots ride at and just behind the tip), verticals grow at each
   floor corner up to the measured wall top, and a matching top loop closes
   the box. No surface exists yet. Drawn in the paper tone at low alpha, the
   floor line brightest — gold stays reserved for light semantics.
2. **The surfaces materialize.** Floor, then walls, fading up IN PLACE with
   zero translation, swept around the room in the contour's own rotational
   direction from the pen's starting corner. The contour dims away underneath
   them.
3. **The pieces settle.** Each fades up while easing down 6 cm (was 0.40 m) on
   the settle curve, so it begins at rest and arrives at rest. Opacity
   finishes at 70 % of the settle, so a piece is fully present before it stops
   moving. The leading three are introduced one at a time and named; the rest
   arrive as one quickening wave, unnamed.
4. **A beat of quiet** (450 ms) before the guest speaks.

Every cue — what starts when, in what order, for how long, and whether it is
named — is a pure function in the new `web/src/lib/reveal.ts`, pinned by 37
tests. `SplatViewer.tsx` plays the plan; it does not decide it.

Reduced motion produces an `immediate` plan: everything visible on the first
frame, no contour, no captions, `onRevealDone` at once.

**The fourth defect, found in the browser and fixed here:** `reveal` was an
effect dependency in SplatViewer, and `RoomStage` turns it off when the reveal
ends. The renderer therefore tore down and rebuilt — the room the user had
just watched assemble blinked out and re-faded in over 900 ms, at exactly the
moment the reveal was supposed to have landed. `reveal` is now read once at
setup through a ref and is not a dependency.

## Why

**On the curve.** "Settle" is a statement about velocity at the endpoints, not
about duration or distance. A curve that starts at maximum speed reads as a
fall no matter how long it takes; a curve that starts and ends at rest reads
as coming to rest even over a short distance. That is why the fix is the
easing function first and the 0.40 m → 0.06 m distance second. The test suite
pins the endpoint derivatives directly, and also pins what we moved away from
(ease-out cubic's velocity of 3 at t = 0), so the operator's finding cannot
silently regress.

**On the contour.** Establishing the room's EXTENT before any material means
surfaces later appear inside a boundary the eye has already accepted — so
nothing ever has to arrive from off-stage, which is what "materialize in
place" actually requires. It is also the honest register: the contour is the
measurement, the thing the capture genuinely produced, drawn from the measured
floor polygon and the measured wall tops. With no measured floor there is no
boundary and none is drawn — nothing is invented.

**On naming.** RP-8 shipped a name for every arriving object. At a uniform
650 ms stagger that is a manifest readout, and at the wave's pace the captions
would flicker. Introducing the leading pieces and then falling silent is what
a host actually does, and it keeps the naming a courtesy rather than a
progress indicator. Small rooms (fewer than six pieces) get every piece named,
because a 3-named-plus-1-wave split would read as an accident.

**On the wave.** The spike room drops from ~22.8 s to ~11.7 s, and a typical
13-piece room to ~9.4 s, without shortening any single piece's settle. The
time comes out of the queue, not out of the motion.

**On the plan being a pure function.** The automation browser throttles rAF
and its drag never reaches OrbitControls, so pacing cannot be judged in it.
Putting the whole score in a table makes ordering, overlap, naming and total
duration verifiable without a browser, and leaves only the aesthetic judgement
— which genuinely needs the operator's eyes — un-automated.

**On objects waiting for the last wall to finish.** Cheap insurance, not
taste: it guarantees no splat ever fades against a half-transparent wall, so
splat/mesh compositing only ever happens in the `depthWrite: true`,
non-transparent configuration decision 0066's V1 depth probe proved. During a
surface's own ramp the material is transparent with `depthWrite: false`, and
on completion it is restored to exactly the proven configuration.

## What would change this decision

- If the operator's consolidated walk finds the contour reads as ornament
  rather than as measurement, drop the top loop and risers and keep only the
  floor perimeter (the hierarchy is already there — they render at half the
  floor line's alpha).
- If the introduce-then-wave rhythm reads as two different reveals rather than
  one, move to a uniform stagger and accept the longer tail, or name nothing
  and let the inventory panel carry the names.
- If a room ever ships a measured floor whose perimeter is long enough that a
  1250 ms trace looks hurried, the draw time should scale with perimeter
  rather than stay fixed.
- If per-object selection (board 6(e)) makes the pieces individually
  addressable, the wave could become a "settle in place as you look at them"
  interaction instead of a timed sequence.
