# 0256 — when only one thing fits, the one that changes wins

**Date:** 2026-08-28
**Status:** Spent

## Context

Home, rebuilt (0254), holds a claim, one reporting sentence, and a pinned
action. At default text sizes all three are on screen with room to spare.

At `accessibility-extra-extra-extra-large` the claim alone fills the entire
scroll region. The sentence — home's **only** reporting surface after the
redesign — sat below the fold, with nothing indicating it was there. On the
`needsYou` variant that meant a home which could not say something needed the
user, which is worse than the stacked notices the redesign replaced.

The suite was green throughout. The routing was correct; only the rendering was
not. This is the third time an accessibility screenshot has found something that
reading the code could not (0224, 0253, this).

## What we tried

**Capping the claim's growth** was the first instinct and is wrong. `RSFont`'s
own note says why: fixed-size text scales uncapped by default, and a cap
inverts the hierarchy at accessibility sizes because the text-style variants
scale without one. The claim would end up smaller than the support copy under
it.

**Pinning the sentence** beside the action breaks 0224's rule directly —
content in the fixed column takes height from the action, which is the exact
failure that rule exists to prevent.

**Truncating the claim** at large sizes makes the product's own thesis a
fragment.

## What we chose

At accessibility sizes, the claim and the sentence swap places. The sentence
comes first; the claim scrolls below it.

## Why

**The claim is a standing statement and the sentence is why the person opened
the app.** The claim is identical on every launch — nothing is lost by having to
scroll to something that never changes. The sentence is the only thing on the
screen that is different today from yesterday, and it is the only thing with
somewhere to go.

Stated as a general rule because it is not about home: **when a screen cannot
show all of its content and one part of it changes while another does not, the
part that changes goes first.** Any screen in this app that pairs a constant
with a report inherits it — the house pairs its epigraph with the room list on
exactly the same terms, and got the same treatment for free by putting the rooms
below.

Reordering rather than resizing also keeps the type scale honest. Nothing is
capped, nothing is truncated, and both elements are still set at the size the
design system says they should be.

## What would change this decision

If a screen ever has two things that BOTH change, this rule says nothing and the
priority has to be decided on its own merits.

If the ordering swap is ever felt as jarring by someone who uses accessibility
sizes full-time — the layout differing from what they have seen in screenshots
or been told about — that is a real cost and the answer is probably to lead with
the sentence at every size rather than to swap.
