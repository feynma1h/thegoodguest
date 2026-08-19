# 0185 — a number is not a referent

**Date:** 2026-08-19
**Status:** Built, at PROMPT_VERSION 6

## Context

Four turns on the production origin, and by the third of them the person was
saying "move the first chair" to their own room. The guest had offered "a
first chair, second chair, third chair, fourth chair, and fifth chair", and
they had taken the vocabulary because it was the only one on the table.

`scene_facts._spoken_names` had produced those ordinals since 0058, for a
reason that was sound as far as it went: a distance string needs to say WHICH
chair, and duplicate labels do not. The mistake was treating a key as a name.

Three more defects from the same walk are the same mistake wearing other
clothes, so they are decided here together:

- three of those five chairs were seen but never placed, so they cannot be
  moved, taken out or turned at all — and they were still enumerated as
  options for a move;
- asked to "turn the chair round" one turn after moving one, the guest asked
  which of five, then proposed that very chair in its next sentence;
- the guest uses inline markdown, and there is no markdown renderer anywhere
  in `web/src`, so `*used*` reaches the person as literal asterisks (this
  half was already ruled on in 0178; it ships here because it costs the same
  evals run).

## What we tried

**Colour first, and it is the only handle that survived.** Two other ways of
telling same-named pieces apart were considered and rejected on their own
terms:

- **Position** — "the chair by the window" — is how people actually speak, and
  the room knows where things are. It was rejected because it is not invariant
  under rearrangement: `scene_facts` is re-derived from the PROPOSED manifest
  when an arrangement is in place (0131), so a piece named by what it stands
  nearest would silently change its name the moment the guest moved something.
  Losing the referent mid-conversation is worse than never having had one.
- **Size** — "the taller chair" — is invariant, and with 0143's declared up
  axis it is a real claim. It was rejected because sizes exist only for boxes
  at high or medium confidence, and the transcript's own room is the
  counterexample: the chair the person called red carries a LOW-confidence
  box, so "the taller chair" would have been taller than the one measured
  piece it could be compared with. A handle that silently ranks against a
  subset is a worse handle than none.

Colour is invariant under rearrangement, exists independently of placement and
of box confidence, and is what the person reached for unprompted.

**What replaces the ordinal where colour cannot.** Nothing does — and that is
the finding. Where several pieces share a label and no measured colour
separates them, the numbers stay, and both the facts and the charter say what
they are: bookkeeping, not names. The person cannot decode "the third chair"
either, so offering it is not a question, it is a menu of things they cannot
read.

**The rule was tightened once, on live evidence.** The first version forbade
offering the numbers as choices. Probed live, the guest then said "The first,
second, and third chairs were seen but never placed, so there's nothing for me
to act on with them" — not a menu, entirely honest, and still teaching the
person the vocabulary the operator objected to. The rule now forbids saying
the numbers at all: the guest talks about them together, as "the other three",
and says plainly that it cannot separate them. Re-probed, it does exactly
that.

## Why

**A referent the person cannot resolve is not a referent.** That is the whole
of it. An index is a fact about the guest's notes, and the product's claim is
that it talks about the person's room.

**The cost of the tightening is small and worth naming.** Where three
same-named pieces are all PLACED and none carries a colour, the facts hold
distances involving them that the guest can now no longer quote, because
quoting one means saying a number. That is a real loss of a fact. It is also a
fact of near-zero use — "one of the three chairs is 1.3 m from the bed" tells
the person nothing they can act on — and the honest sentence, "there are three
chairs here I can't tell apart", is available and better. In the four walk
rooms this case does not arise: every group of indistinguishable pieces is
either unplaced or separated by colour.

**Unplaced pieces are not candidates, and this is a truth about the code**, not
a stylistic preference. `spec_solver.solve` and `turn_around` both refuse with
`piece_not_placed`, and `remove` refuses through the same gate for want of a
measured transform. All three actions are closed. The facts now say so on the
same line that says the piece has no position, and the charter carries it as
rule 4b, so the guest does not have to infer a capability boundary from a tool
schema.

**A referent the previous turn fixed is not re-asked**, because the arithmetic
is one-sided: everything here is one step from undone (0133), so acting on the
obvious reading and being corrected costs the person a sentence, while asking
them to re-identify something they named a moment ago costs them the thread.
That asymmetry is written into the charter rather than left as taste.

## The eval found a production defect, which is what evals are for

The colour names worked and the tool refused them. Asked to move the red
chair, the model wrote `object_id: "red_chair"` and `guest_tools._find`
returned `unknown_object`, so the guest said "I'm hitting a wall trying to
name the red chair for the move" — the worst refusal this product ships, on
the transcript's own first turn.

Measured before touching anything: **5 of 8 samples emit the underscored
form** under the colour names. It is NOT a defect the colour names created —
the control, the same room with colours stripped and the person addressing a
piece by number as they did on turn three of the real transcript, misses **2
of 8** on the bare definite article. Multi-word names simply make an existing
gap fire about two and a half times as often, because a field called
`object_id` shown a NAME invites the model to normalise one into the other.
The deeper cause is that the tool's own description says "the id of the piece
to change, exactly as it appears in THE FACTS inventory", and what appears
there is a name; that string was left alone here because it is instruction and
belongs to whoever owns that surface.

`_find` now reduces both sides before comparing: lowercase, `_` and `-` as
spaces, collapsed whitespace, a leading "the" dropped. Reduction, never fuzzy
matching — names are unique space-separated words, so this can resolve MORE
and can never resolve differently, which is the property that made it safe to
widen without re-adjudicating anything.

One thing it does NOT fix, found while pinning it and left alone: `_find`
falls back to the bare LABEL, so "chair" in a two-chair room silently resolves
to whichever comes first rather than refusing. The charter is what protects
the person there — the guest asks which one, and was measured doing so — but
a resolver whose failure mode is a silently wrong piece is worth a look by
whoever next opens that file. It is pinned as found, not as wanted.

## What would change this decision

If a room ever ships several placed, indistinguishable, same-named pieces and
a person is measurably hindered by not hearing their distances, the ban on
speaking a number is the clause to revisit — but the fix is more likely to be
a better handle than a restored index. The union of views (0151) or a second
colour reading would give more pieces a real colour, which is the direction
that actually helps.

If a markdown renderer is ever added to the conversation surface, the markup
rule does not change: 0178 already recorded why. The guest's line is italic
serif, so emphasis inside it inverts.
