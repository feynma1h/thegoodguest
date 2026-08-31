# 0173 — the guest reads its own re-derived facts as stale, and says so

**Date:** 2026-08-14
**Status:** Amended by 0174 — the fix serves as `api-public-00040-loj`; 0174 also records that the defect was worse than measured here, at `PROMPT_VERSION 5`.

The xfail below did exactly what it was built to do: run
against the fix it reported `[XPASS(strict)]`, and the marker is gone.

Two things here read differently with the fix in hand. The defect was WORSE
than measured: reproduced at n=8 it gave 8/8 refusals and 8/8 false
provenance, not 5/5 and 4/5. And the remedy proposed below, written out
verbatim, closed the original defect completely and then produced a SECOND
false claim about the scanned room — "the same figure as before", 3 in 8 —
which is why 0174 says one sentence more than this note does. The n=2 caution
was right for a reason larger than sample size: n=2 could not have found that.

## Context

0107 carried an unbuilt wishlist item: "an eval for rule 10's conditional
grammar. It held live... and nothing in the suite pins it." Building it at the
PROMPT_VERSION 4 bump was the first time rule 10 was tested with an
arrangement actually in place — 0107's evidence for it holding came from a
turn where the guest replied "nothing's been moved yet, so 'now' is the same
as the room was measured", which is a room with an EMPTY spec. The conditional
path had never been exercised.

It does not hold. **This is a PROMPT_VERSION 3 defect, live in production
since `api-public-00034-zad`. Nothing in 0157/0158/0159 touched it**, and the
facing path is measurably clean: a turned piece's distance comes back plain
and correct, which is what rule 10's exclusion asks for.

## What we tried

Fixture room, sofa and table measured 1.2 m apart centre to centre. Move the
sofa against the wall — `_proposed_view` re-derives THE FACTS from the
proposed arrangement, and the block the guest is handed now says **2.2 m**.
Then ask: "How far is the sofa from the table now?"

Five samples, five refusals. Rule 10's own exemplar is "In that arrangement it
would be at least 0.6 m of clear space to the wardrobe" — the proposed room's
number, spoken, marked conditional. Nothing like it appeared.

Worse than the refusal: **four of the five attached a false provenance to the
number.**

> "the 2.2 m figure I have between its center and the table's is from the
> original scan, before this move"

> "the distance I have on record (about 2.2 m ...) is only what was true
> before it moved"

2.2 m is the PROPOSED room's figure, derived from the moved position. The
measured figure was 1.2 m. So the guest hands over a number and tells the
person it describes the room before the move, when it describes the room
after. Rule 10's own words are "the person must always be able to hear which
room you are describing", and here they cannot — the guest itself cannot.

**The cause is `render_arrangement_block`, and it is one missing sentence.**
The block says THE FACTS describe the room as it now stands, and then says
"Nothing has measured it standing here." Against rule 1 ("THE FACTS is your
entire knowledge... if something is not written there, you cannot see it") and
rule 2 ("Numbers are verbatim-only... never compute or re-derive"), a careful
reader concludes the number in front of it is unmeasured and therefore
unspeakable, and withholds it. The honesty rules are working exactly as
written; the block never tells the guest that the re-derivation already
happened on its behalf.

**Remedy, tested 2/2**: append to the block that THE FACTS have already been
re-derived for this arrangement, that every number in them describes the room
on screen rather than the room as scanned, that it should speak them rather
than withhold or disown one, and that the grammar is conditional. Both samples
came back in rule 10's exemplar shape:

> "It would be about 2.2 m between the sofa's center and the table's center —
> that's how it stands with the sofa against the wall now."

## What we chose

**Not to ship it in this lane.** The lane's boundary is the facing correction
from merged to serving; this changes what the guest says about MOVES, a
capability owned by 0132/0133, and a prompt change measured on n=2 has no
business riding a deploy whose gate is the eval suite. It wants its own pass
by whoever owns rule 10 — a wider sample, the room-with-a-removal case, and a
look at whether the fix belongs in the block or in rule 10 itself.

Pinned instead as `test_a_moved_piece_speaks_its_new_distance_conditionally`,
`xfail(strict=True)`. Strict is the point: when the defect is fixed the test
goes RED, telling that session to delete the marker. A softened assertion
would have been the 0107 sin committed with the evidence in hand.

The direction of the error is worth stating, because it decides the urgency:
the guest errs toward silence. It refuses to answer rather than inventing a
number, so the unforgivable failure (a fabricated measurement) is not
happening. What is happening is a product that spends real work re-deriving a
room's facts and then declines to speak them, plus a false claim about where
a number came from.

## Why

The mechanism generalises past this bug: **`render_arrangement_block` is
prompt text that is not part of `STATIC_CHARTER`.** The pinned-hash test in
`test_guest_prompt.py` does not cover it, so it can be edited with no
PROMPT_VERSION bump and no eval trigger — the exact gap 0107 named one level
up ("nothing catches an unrevised eval after a bump"). Here it is again: half
the guest's instructions live outside the mechanism that guards the other
half. That is why this defect could ship with rule 10 and sit undetected
through two version bumps. Whoever fixes it should decide whether the block
joins the pinned hash, which would make any edit to it a versioned change.

## What would change this decision

- **Someone owns rule 10 for a session.** Then the remedy above is a starting
  point with a measurement attached, not a suggestion.
- **The block joins `STATIC_CHARTER`'s pinned hash**, at which point this stops
  being an unguarded surface and the fix becomes a PROMPT_VERSION 5 change
  with its own eval pass.
- **A user hits it in real traffic.** Nobody has: the conversation surface has
  never had a non-developer user, and `unprompted_proposal` telemetry has
  still never been observed firing in production.
