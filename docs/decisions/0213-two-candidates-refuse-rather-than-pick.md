# 0213 — two candidates refuse rather than pick

**Date:** 2026-08-21
**Status:** Decided and BUILT, merged to `guest`, not yet deployed.

## Context

`guest_tools._find` resolves whatever the model puts in `object_id` to a piece
of the room. Its last tier falls back to the bare LABEL, and a label is shared:
in a two-chair room `"chair"` matched both and the loop returned whichever
sorted first. Nothing told the person which one it had picked, and the guest
then acted on it — a wrong piece moving on screen, which reads to the person as
the room being wrong rather than as the guest being wrong.

The defect was known, pinned as a test, and left alone deliberately in 0185 on
the grounds that it predated colour naming. Colour shipped to production on
2026-08-20, so `red chair` is a real referent today and the reason for leaving
it has expired.

## What we tried

**The discipline already existed one file over, and was never applied here.**
`spec_solver.resolve_object_anchor` has refused ambiguous ANCHORS since 0132,
with the rule written at the function: *"Matching is deliberately shallow —
exact spoken name, then label, then a containment fallback — because a clever
matcher that guesses is the same failure as a solver that guesses. Two
candidates refuse rather than pick."* `resolve_wall_anchor` refuses two windows
the same way. So one request could refuse its anchor and silently guess its
subject, which is not a position anybody chose.

The fix is that discipline, applied to the subject: `_find` returns
`RoomObject | Refusal`, tiers exact name before shared label, resolves on one
hit and refuses on more. **The tiering is what keeps the fix from costing
anything**: `"red chair"` is exact at the name tier, so it resolves in the same
room where `"chair"` refuses.

**Two places it deliberately departs from the anchor resolver.**

The anchor resolver considers only `placed` objects with a box, because it has
to measure against them. `_find` does not filter: a glimpsed piece is something
a person can still refer to, and resolving it earns the specific
`piece_not_placed` refusal that already exists rather than the baffling
`unknown_object`.

And it stops at two tiers rather than three. The anchor resolver's containment
fallback (`want in name or label in want`) is right for the person's own words,
which arrive as free text; the subject arrives as the model's rendering of a
name the facts block showed it, and `_spoken_form` already normalises the five
shapes the transcript measured it emitting.

**Then the detail string turned out to be the real decision.** The first
version listed every candidate, the way `resolve_object_anchor` does. Run
against the eval suite's own five-chair room — the production walk's transcript
in miniature — that produces `"black chair, first chair, red chair, second
chair, third chair"`. Three of those are bookkeeping ordinals, and 0184 is
explicit that an ordinal is not a referent: the person cannot tell which chair
is the third one either. An eval already asserts the guest never speaks one.
A tool result is server-authored and rule 2a asks the guest to quote those
verbatim, so listing them there would have taught it the habit 0184 removed,
arriving by a new road.

So `RoomObject` carries `named_by_bookkeeping` through from `scene_facts`, and
the detail names only the pieces a person could have meant and counts the rest:
`"black chair, red chair, and 3 more chairs that nothing separates"`. Where
none can be named it is a count alone — `"2 chairs that nothing separates"`.

## What we chose

Refuse, with a detail the guest can turn into a question the person can answer.
`revert` gets the same treatment, and no longer says *"nothing to put back"*
when there is something and the room cannot tell which.

**We chose refusal over the plausible pick, in the one case where picking looks
defensible.** Where a room holds one placed chair and one glimpsed chair,
`"move the chair"` has exactly one actionable answer, and resolving to it would
read as helpful. It is still picking a likely answer, the person may have meant
the other, and the guest's facts already say which pieces cannot be moved — so
it can say *"I can only move the red one; the other was never placed"* out of a
refusal, which is better than the room deciding on its behalf.

## Why

**A silent wrong piece is the one failure this layer must never have.** Every
other refusal in this system is visible: `placed: false` carries a reason (0052),
the solver returns `{applied: false, reason}` (0132), a proposed transform ships
only if it reprojects onto the object's own mask (0067 chunk D). Resolution was
the one step that failed by succeeding.

**The charter was protecting the person, and that is not the same as the layer
being safe.** 0185 recorded that the guest asks which one and was measured
doing so. That is true and it is why this was survivable, but it makes the
person's protection a property of a stochastic model rather than of the code
underneath it. The refusal moves it into the resolver, where it holds whatever
the model does.

**The detail is where honesty is spent or saved.** A refusal that hands back
vocabulary the person cannot decode is not a refusal, it is the 0184 defect
wearing a refusal's clothes. Naming what can be named and counting what cannot
is the sentence 0184 asks the guest to say — *"describe the piece instead... and
say plainly when none of that separates them"* — supplied by the room rather
than reconstructed by the model.

**It costs nothing where colour works, which is why it is worth doing now.**
Colour reached production the day before this (0184/0185), and in a room where
it read, the refusal never fires for a person who says what they see.

## What would change this decision

- **A measured handle other than colour separates same-label pieces.** Position
  is already in the facts as nearest-neighbour comparatives, and a detail could
  carry *"the one nearest the desk"* rather than a count. That is a better
  refusal in exactly the rooms where the colour gate declined, which is most of
  them.
- **The refusal rate on a common label proves high in real traffic.** Nobody
  non-developer has used this surface. If people routinely say "the chair" in
  two-chair rooms and routinely get asked back, the answer is a better handle,
  never a loosened resolver.
- **Direct manipulation ships.** Clicking a piece supplies a referent with no
  language in it, and the ambiguity this note is about stops existing for any
  reference that arrives that way.
