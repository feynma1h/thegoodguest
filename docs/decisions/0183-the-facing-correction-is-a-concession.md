# 0183 — the facing correction is a concession, not a feature

**Date:** 2026-08-19
**Status:** Decided

## Context

Stage 2 shipped a facing correction on 2026-08-14: after five instrument
families failed to settle which way round a reconstruction sits in its box,
the person who lives in the room can say so and the room keeps the
correction (0157, 0158, 0159). A sitting on 2026-08-19 then asked the operator a narrow question about
one control's copy.

The answer was about the feature instead: **"Facing corrections are not
something I'd ideally want the users to do. The product should be able to do
it intelligently."**

That is a product ruling on something already built and serving, and it is
recorded here because it changes what the correction is FOR.

## What we chose

The correction stays, and stops being a destination. It is a concession to a
measurement the pipeline cannot yet make, and **its success condition is its
own disuse** — a room where nobody turns anything is the product working, not
a feature going unused. Nothing gets built on top of it: no bulk correction,
no correction history, no prompting the person to check facings, no surface
that treats turning things as part of the experience.

## Why

The alternative reading — that the person is a sensor the pipeline can lean
on — is the wrong shape for this product. The thesis is that the product
shows people something about their home they could not see themselves. Asking
them which way their own cupboard faces inverts that, and it asks at exactly
the moment the illusion is most fragile: the reveal has just claimed to have
measured the room.

It also has no ceiling. Every correction is one person, one room, one
observation; the measurement it substitutes for would be right on every
capture forever.

## What this does and does not change about the instruments

**Sitting 1's verdict is consistent with this, not in tension with it.** The
operator turned the layout-rotation facing sign OFF in the same sitting (0171 ships
it flag-only, right 2 times in 3, with no gate that separates the miss from
the hits). Off is not a retreat from "do it intelligently" — it is the only
path to it. The flag keeps recording a preference on every capture, so the
rate becomes measured rather than argued from three objects.

**The thing that would make facings resolvable is already scoped.** 0156's
recorded re-open condition is the multi-view union giving the far side real
observed texture, and the reason every facing instrument has failed is now
measured twice: a single-view reconstruction's unseen half is fabricated, and
all of them interrogate that fabricated half. So the operator's "do it
intelligently" and lane D (0151) are the same item, which is worth knowing
before anyone proposes a sixth instrument.

## The copy fix that prompted this

Fixed here rather than deferred, because the affordance is live and will stay
live for as long as facings are unresolved, and because it was a live
honesty defect rather than a polish item.

A room with both a move and a correction offered one control, "back to the
scan", which deletes the whole spec — the turn goes with the move. Both
behaviours are honest (the guest's own `revert` preserves turns; this control
is deliberately more total, and its label changes to say so). The defect was
where the difference was explained: a `title` attribute, which is a hover
tooltip. **A touch device never renders it**, so a phone showed only "back to
the scan", which does not mention turns — and 0157 calls a facing correction
the one thing in the room that is the person's rather than the scan's.

The warning moved into the chrome sentence, which every device shows:
"1 piece moved, 1 turned round — going back to the scan undoes the turn too".
The `title` is gone. `arrangementNote` is pure and the case is pinned; the
rearrangement-only and correction-only sentences are unchanged, so the 0133
invariant keeps its own words where nothing of the person's is at stake.

A confirmation dialog was considered and rejected: 0133 makes "the way back
is one control away" an invariant, and a confirm step trades that away to
solve a problem that plain text solves.

## What would change this decision

The union landing and facings becoming resolvable, at which point the
`corrections` branch of this control has no reason to exist and should be
deleted rather than maintained.

If real usage shows people turning things often, that is not evidence the
feature is working — read it as a measurement of how wrong the facings are,
and prioritise accordingly.
