# 0157 — a correction departs from a default, not from a measurement

**Date:** 2026-08-13
**Status:** Decided and BUILT, not deployed — `spec_solver.turn_around`,
`design_spec.departs_from`, and the `turn` branch of `guest_tools.run_propose`.
Extends 0131's contract; fires 0133's named re-open for rotation.

## Context

Five instrument families are now measured dead on the 180° facing sign of a
splat inside its measured box: cloud alignment on sign twins and appearance
NCC in every variant (0081), per-view aggregation and a truncation-direction
prior (0104), and semantic recognition by a vision model shown the photo and
both hypotheses (0156). They fail for one reason, measured twice over — a
single-view reconstruction's unseen half is fabricated, and every one of them
asked that fabricated half a question.

0133 descoped rotation from conversational proposals with the trigger "re-open
when splat axis resolution ships". That trigger will not fire. The one it
should have written is this one: **five families are dead and the evidence
source is not coming**, at which point "the cupboard faces the other way",
said once by the person who lives in the room, stops reading as a fallback
and starts reading as the correct design.

## What we tried

The obvious build is to make a facing correction another `move`-class entry:
same document, same keying, same revert. It is one line of enum.

It puts a lie in the field named `measured_transform`.

A `move` proposes a counterfactual — perception measured the bed here, and the
person wants to see it there. Both readings are meaningful and exactly one is
true, which is what 0131's measured-beside-proposed shape is for. A facing
correction is not counterfactual. The person is not asking to see the cupboard
turned round; they are saying it *is* turned round and the room drew it wrong.

And the room agrees. Perception's `resolve_axis_mapping` scores candidates
grouped by ASSIGNMENT and always ships the FIRST candidate of the winning
group — the fixed (+,+) sign. So **the 180° sign is unresolved on every
box-placed object by construction**, whatever `splat_axis_resolved` says; that
flag is about the assignment, which the cloud instrument does resolve (9 of
the 21 box placements across the four preserved walk rooms, at margins
0.10–0.47). Filing a correction as a departure from a measurement would put a
coin flip in the slot this document exists to keep honest.

## What we chose

**Entries record which kind of claim they overruled.** `departs_from` is
`measurement` for a move or a removal and `unresolved_default` for a turn, and
it is not decoration — three behaviours read it, each of which would be wrong
without it.

**1. A turned piece gets no measured outline.** 0131 keeps a moved piece's
measurement on screen as its footprint in the reveal's contour tone. A half
turn maps a rectangle onto itself — measured exactly, 0.00e+00 across all 21
real boxes — so the measured footprint of a turned piece is the ground it is
standing on. Drawing it would put a measurement line under an object that
never left, saying "here is where this used to be" about the spot it currently
occupies.

**2. Revert restores measurements and keeps corrections.** `revert all` drops
moves and removals; an entry carrying a facing correction is REDUCED to a pure
turn rather than dropped. 0133's invariant is that the measured room is never
more than one step away, and it holds exactly: a turn never left it. Dropping
the correction would re-introduce an error the person has already told us
about, and they would have to say it again. Undoing a correction is a second
turn, which is what a person would say anyway.

**3. The guest's grammar does not hedge a turn.** Rule 10 makes facts about a
rearranged room conditional. A turn changes the rotation and nothing else —
not the position, not the box's dims, and above all not the box's yaw — and
nothing `scene_facts` derives reads a rotation. Pinned end to end: the facts
block is byte-identical before and after. Hedging a turn would be evasion
wearing honesty's clothes.

**Computed on the wire, never stored.** `departs_from` is a function of
`action`, so a second copy in Firestore could disagree with the first. It
rides `client_dict` the way `orphaned` does — derived on the way out, never
parsed back in — and the web reads it rather than re-deriving, so there is one
implementation of the rule.

**`facing_flipped` IS stored,** because it is provenance rather than
geometry: it records that the person asserted this. It rides independently of
`action`, so a piece can be both moved and turned, and neither instruction
quietly discards the other.

## Why

The distinction is not a label, it is the difference between the two things
this product can say about a value it did not measure. Everywhere else the
project has faced "the honest value and the shipped value differ" it has
shipped both — `measured_quad`, `measured_polygon`, `splat_clip` declared
rather than applied, `placed: false` with a reason. That pattern assumes there
IS an honest value. Here there is not one, and the correct move is to say so
rather than to dress the pipeline's convention as a measurement and offer to
put the room "back" to it.

The ruling that follows is the one worth carrying: **where the pipeline has no
evidence at all, the person is not a fallback — they are the only instrument.**

## The one instrument-shaped option, and why it was not spent

0156 names a real confound: `render_splat` is a 256 px point rasteriser
producing a sparse dot field, and a proper Gaussian render might move the two
chairs the vision model got wrong. Not pursued, and the reason is 0156's own
cupboard: the model's stated reason for failing there was that both renders
look alike, and they look alike because SAM 3D invented a back carrying a grid
of panels much like its front. Better pixels cannot show a difference that is
not in the geometry. A sixth variant of an idea whose premise one case
contradicts directly is the pattern 0104 warns against, and the afternoon buys
at most two chairs out of five while leaving the cupboard exactly where it is.

## What would change this decision

- **A complete object.** The union of registered reconstructions (0151) would
  give the far side real observed texture, at which point 0156's probe is
  worth re-running and the pipeline might settle the sign itself. The
  correction path stays either way — it would simply stop being the only
  evidence.
- **A correction that DOES depart from a measurement.** Correcting a label, or
  a size, would overrule something the room actually measured. `departs_from`
  already has the vocabulary for it; the treatment rules above do not
  transfer, and each would need its own answer.
- **Direct manipulation.** Dragging a piece round produces a rotation with no
  provenance at all — neither measured nor asserted in words — which is a
  third class this field does not name.
