# 0174 — the room already re-derived it, and the block never said so

**Date:** 2026-08-14
**Status:** Decided — shipped at PROMPT_VERSION 5.

## Context

0173 measured the defect and diagnosed it: with an arrangement in place the
guest refuses to speak the proposed room's numbers, and attaches a false
history to them — "the 2.2 m figure I have is from the original scan, before
this move", when 2.2 m is the number `_proposed_view` re-derived FROM the move
and the measured figure was 1.2 m. It left the remedy deliberately unshipped
on n=2, for whoever owned rule 10 for a session.

The direction of the error decides how urgent it is, and 0173 is right that
the guest errs toward silence rather than inventing a measurement. But this
product's whole claim is that its numbers are measurements and that it says
plainly where each came from, and a number handed over with an invented
history is a lie about exactly that.

## What we tried

**Reproduced first, at n=8 on the serving block: 8/8 refusals, 8/8 with false
provenance.** Worse than 0173's 5/5 and 4/5, and the mechanism is visible in
the transcripts — one sample reasons all the way to the right answer and
still stops: *"I only know what would be conditional on this new spot, and I
don't have even that number for this particular relation."* It is looking at
the number.

Those eight replies are what the misattribution instrument was built from,
rather than the other way round. It then had to be shown it could fail: 8/8 on
the broken replies, **0/6 on replies it must not flag** — rule 10's own charter
exemplar, 0173's two good samples, and the honest hedge every correct reply
contains ("nothing has measured it standing there", which is true, is what
rule 10 asks for, and appears in all eight broken replies too).

**Candidate 1 was 0173's remedy written out** — the facts have been re-derived,
they describe the room on screen, speaking one is quoting rather than
computing. It closed the original defect completely (0/8) and a real sample
immediately showed what n=2 could not: **3 of 8 replies now said the number was
"the same figure as before"**, or that moving the sofa "hasn't changed that
figure". The measured figure was 1.2 m and the proposed is 2.2 m, so this is a
second false claim about the scanned room, wearing a reassuring costume.

A third appeared in the composed turn-and-move case: *"it's a real measurement
of how things stand right now, not a guess."* Nothing measured the arrangement.

So there are three classes, and they are one error:

1. **stale attribution** — the number came from the scan.
2. **false comparison** — the number is unchanged from the scan.
3. **over-claimed measurement** — the number is a measurement of the proposal.

Each requires the guest to believe it possesses the scanned room's figures. It
does not: `_proposed_view` replaces them.

**Candidate 2 says that.** One sentence — *"you are not holding the scanned
room's figures — they are not in front of you"* — is what closes all three at
once, and the enumeration after it ("what a number used to be, whether it has
changed, that one came from the scan, or that one is a measurement of the room
as it now stands") is derived from it rather than being a list of patched
symptoms.

Measured on the shipped text, n=16 over two batches on 0173's own case:
**0/16 invented provenance, 0/16 refusals, 16/16 spoke the distance.** The
literal "would" is 12/16; all 16 tie the number to the arrangement in some
wording. Replies read like rule 10's exemplar:

> "In this arrangement it would be about 2.2 m between the sofa's center and
> the table's center — 'would,' since that's the distance with the sofa
> standing where I've just put it."

Residue, honestly: 1/7 invented provenance in the composed turn-and-move case
(a "same figure as before"), and 1/8 in the clearance case.

## What we chose

Ship candidate 2 as `ARRANGEMENT_PREAMBLE`, and leave the charter untouched —
the fix is "say which room this number describes", not new capability, and
block-only reached 0/16 without spending a charter edit.

**Two measurements changed the shape of what shipped, and neither was
predictable from reading.** The first is class 2 above. The second is a
FALSE POSITIVE in our own instrument: after a REMOVAL it fires 6/8, and all
six are correct — a removal moves nothing, so "that hasn't changed" about the
untouched sofa-and-rug pair is both true and soundly inferred from position
facts rather than from a number the guest doesn't have. Class 2 is only
unambiguous where the pair involves a MOVED piece. That scope is written at
the regex, because the next person to reuse it will not re-measure it.

The eval splits the way 0172 asks. The harm is a RULE, asserted on every one
of three samples, and both per-sample assertions are known falsifiable because
they read 8/8 against the pre-fix block. The literal "would" is the charter's
prescribed MECHANISM for a goal a reply can meet other ways ("that's how it
stands with the sofa against the wall now"), so it is a rate.

A third leg was added that the old pair did not have: after a removal, the
untouched pair keeps plain grammar. This block ends "Say 'would', every time",
and the regression it most invites is hedging facts no change ever touched.

**That leg was written per-sample on an 0/8 probe, and the first live run
failed it** — the guest said "the sofa would still be about 0.9 m from the
rug". Recorded because the mistake generalises: 0 of 8 does not establish a
rate near zero, it is consistent with roughly one in ten, and a per-sample
assertion on a stochastic property needs either a rate or a far larger base.
The same arithmetic is why the two per-sample rules in the move test are
sound and this one was not — those read 8/8 in the OTHER direction against
the pre-fix block, which is evidence about the instrument, not just about a
tail. An over-hedge is also not a harm: it is over-caution, where the failure
being guarded is every untouched fact in the room going conditional at once.
So speaking the distance stays a rule, and not hedging it became a rate.

## Why

The guest was reading its instructions correctly. Rule 1 says THE FACTS is its
entire knowledge; rule 2 says never re-derive a quantity; the facts block's own
provenance line says *"These facts were measured from a scan of 18 frames"*;
and the arrangement block said "Nothing has measured it standing here". From
those four, the only careful conclusion is that the number in front of it is
the scan's and cannot be restated for the new position. The honesty rules were
working. The block simply never mentioned that the re-derivation had already
happened on the guest's behalf.

That is why the fix belongs in the block and not in rule 10. Rule 10 governs
grammar and was never wrong; what was missing was a fact about where this
particular room's numbers came from, and that is contextual.

**The provenance line is still literally false in a rearranged room.**
`derive_scene_facts` is run over the proposed manifest, so its "these facts
were measured from a scan" survives into a view where some of them were not.
We correct it in the arrangement block, which is specific and comes after it,
rather than in `scene_facts` — that would be a FACTS_VERSION bump, and
FACTS_VERSION is a cache key and half of every persisted turn's reproducibility
triple. Worth doing on its own terms; not worth smuggling into a lane whose
stated boundary is what the guest SAYS.

## What would change this decision

- **The composed-case residual shows up in real traffic.** 1/7 in a room with
  both a turn and a move; the fix would be for the arrangement block to
  distinguish the two kinds of entry it lists, which it currently does not.
- **`scene_facts` stops claiming a rearranged room's facts were measured.**
  Then the block's "Worked out is not measured" is reinforcement rather than a
  correction, and could shorten.
- **A user asks a question none of these five scenarios covers.** Everything
  here is a fixture room with three pieces and a solver that grounds; the
  conversation surface has still never had a non-developer user.
