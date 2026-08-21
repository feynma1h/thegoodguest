# 0214 — the provenance line describes the room on screen

**Date:** 2026-08-21
**Status:** Decided and BUILT at `FACTS_VERSION 4`, merged to `guest`, not yet
deployed. Closes the second of 0174's three re-open triggers.

## Context

`derive_scene_facts` ends every facts block with one line saying where its
numbers came from: *"These facts were measured from a scan of 18 frames of this
one room."* In a rearranged room that line is false. `_proposed_view` runs the
same derivation over a manifest with the arrangement applied, so the moved
pieces' positions — and every distance, height and clearance touching one —
were worked out from the move, not measured.

0174 found this while fixing the guest's speech and corrected it downstream, in
`ARRANGEMENT_PREAMBLE`: *"Worked out is not measured, and you are not holding
the scanned room's figures."* That worked, measured 0/16 invented provenance,
and shipped. It also left the note's own closing observation: *"The provenance
line is still literally false in a rearranged room... Worth doing on its own
terms; not worth smuggling into a lane whose stated boundary is what the guest
SAYS."*

The cost of leaving it is that the arrangement block became **load-bearing
rather than belt-and-braces**, and nobody chose that. A block written as
reinforcement is now the only thing standing between the guest and a false
claim about the person's own room — and 0174 measured that the guest reads its
instructions carefully enough for the difference to matter: shown a facts block
asserting the numbers were measured, it reasoned correctly from that assertion
and refused to speak them.

## What we tried

**Where the truth gets told, and the two ways to plumb it.**

`derive_scene_facts` is a pure leaf — it imports nothing else in this service,
deliberately, because it is the guest's entire world and 0132 keeps it apart
from the solver's. So it cannot ask the spec anything; it has to be told.

The first shape tried was a marker on the manifest copy: `apply_to_manifest`
already builds a fresh dict per moved object and could stamp a private key on
it, which `derive_scene_facts` would read. It is tidy and self-consistent — the
object carries its own provenance — but it puts a non-schema key into a
manifest-shaped dict, and it couples `design_spec` to `scene_facts`.

The shipped shape is a keyword argument, `moved_object_ids`, and it is
**ids rather than names for a reason that only shows up in a room with two of
something**: a removal renames a survivor. Drop one of two chairs and
`_spoken_names` renames the other from `"first chair"` to `"chair"`, because
the ordinal existed only to separate them. So a name captured at propose time
does not necessarily name anything in the re-derived room, while the manifest's
own id does.

**Which actions count, and it is only one.** A `move` puts a piece where
nothing measured it. A `remove` takes it out of the derived room entirely, so
there is no fact left to attribute — every fact that survives is still one the
scan measured. A `turn` changes a rotation, and nothing `scene_facts` derives
reads a rotation; that is the same reason `apply_to_manifest` already records
for rule 10's grammar not applying to one. A turn composed onto a move keeps
the move's action in the spec, so it is still caught.

Getting that boundary wrong in the permissive direction would hedge facts
nothing touched — which is precisely the regression 0174 recorded when it drew
the same line for grammar, and had to demote a per-sample assertion to a rate
after a live run failed it.

## What we chose

`FACTS_VERSION 4`. In a rearranged room the line names the pieces:

> These facts describe this one room as it stands on screen. A scan of 18
> frames measured the room; the sofa has been moved since, so nothing measured
> it where it now stands. 3 pieces placed; 1 seen but never placed.

**A room nobody has rearranged reads byte-for-byte as it did at version 3**,
and that is pinned by a test asserting the literal string. Most rooms are that
room, and the whole of this version's difference is confined to the ones that
are not.

**The arrangement block is left exactly as 0174 measured it.** 0174's own
re-open note anticipated this change and suggested the block "could shorten"
once it arrived. We are not shortening it. Its current text is the thing that
read 0/16 on an instrument built from eight broken replies, and that result
cost sixteen live samples; spending it to remove a few sentences that are now
reinforcement is a bad trade. What changes is its STATUS — it is belt-and-
braces again, which is what it was written as.

**No `PROMPT_VERSION` bump.** Nothing under `PROMPT_SURFACE_SHA256` changed:
the charter and the arrangement block are untouched. The facts block is data
the prompt renders, not instruction, and it already changes per scene.

## Why

**This product's whole claim is that its numbers are measurements and that it
says plainly where each came from.** A provenance line is the one sentence that
claim rests on, so it is the worst sentence in the system to leave false. It
is the same shape as every other choice in this pipeline: `measured_quad`
beside the rendered quad (0069), `measured_transform` beside
`proposed_transform` (0131), `placed: false` with a reason rather than a
guessed transform (0052). Measurement is never overwritten by the thing derived
from it, and here the derivation was quietly wearing the measurement's label.

**A correction downstream of a false statement is strictly worse than not
making the false statement**, even when it measures clean. It costs a block
that has to keep working; it makes the two texts disagree until the reader
reaches the second one; and it means any future edit to the arrangement block
is silently editing a load-bearing correction rather than a reminder. 0174 said
the honesty rules were working and the block simply never mentioned that the
re-derivation had happened. The rules work better when the facts do not have to
be argued with.

**Naming the pieces is what makes the line useful rather than a disclaimer.**
"Some of these may not be measured" would be true and worthless. The guest can
act on "the sofa has been moved since" — it is the same set of pieces the
arrangement block lists, said in the register of provenance rather than of
grammar.

## What would change this decision

- **Direct manipulation ships.** Dragging a piece produces a transform with no
  solver reasoning behind it (0131's own re-open note), and the line would then
  be describing two different kinds of unmeasured position with one sentence.
- **The arrangement block is revisited for its own reasons.** It can shorten
  now — the reinforcement is genuinely redundant with this line — but only
  behind the same n=16 live measurement that put its current text there, and
  the residues 0174 left open (1/7 in the composed turn-and-move case) are the
  cases to watch while doing it.
- **Facts are ever derived for a proposed room somewhere other than
  `_proposed_view`.** The pairing of `apply_to_manifest` with
  `moved_object_ids` is enforced by a route test and by both functions'
  docstrings, not by the type system; a third caller that applies an
  arrangement and forgets the second argument would ship version 3's lie under
  version 4's number.
