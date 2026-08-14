# 0175 — a version number that guards half a contract

**Date:** 2026-08-14
**Status:** Decided — `PROMPT_SURFACE_SHA256` ships at PROMPT_VERSION 5.

## Context

0173's closing section named a mechanism larger than the bug it was written
about: `render_arrangement_block` is prompt text that is not part of
`STATIC_CHARTER`, so `test_guest_prompt.py`'s pinned hash never covered it. Its
wording could change with no PROMPT_VERSION bump and no eval trigger.

That is how 0174's defect shipped and survived two version bumps unnoticed.
Half the guest's instructions lived outside the mechanism guarding the other
half, and 0107 had already described the failure one level up: an eval suite
pinned to a version "does not fail when the charter moves past it, it quietly
starts certifying less".

## What we tried

Two shapes, and the first is not enough on its own.

**Hash the prose as constants.** Lift the block's text into
`ARRANGEMENT_PREAMBLE` and `ARRANGEMENT_FOOTER` and fold both into the digest.
This closes the case where someone rewords the block — but it reopens the
moment someone adds a sentence *inside the renderer*, which is precisely the
edit that is easiest to make and hardest to notice. The constants would still
hash correctly while the guest read something new.

**Also require the renderer to hold no prose.** `render_arrangement_block` now
assembles from the two constants and the server's own descriptions, and
nothing else; the test asserts the rendered block **equals** preamble +
bullets + footer. Equality rather than containment, because a containment
check passes on smuggled text — which is the whole failure being closed.

A third guard turned out to be worth having: a test that mutating each
constant moves the digest. Without it, an edit that quietly dropped a constant
from the hash input would pass a test that only compared the digest to a
pinned literal, and the pin would silently narrow again.

## What we chose

One hash over everything the guest is instructed by — charter and arrangement
prose together — replacing `STATIC_CHARTER_SHA256` rather than sitting beside
it. Two pins would mean two things to remember and a real chance that a future
edit satisfies one; the point of this note is that a partial guard reads as
coverage.

The consequence is deliberate and new: **PROMPT_VERSION can now move without
`STATIC_CHARTER` changing**, and version 5 is the first bump of that kind. The
charter is untouched at 5; the arrangement block is not.

## Why

An unguarded surface is worse than a guard everyone knows is absent, because
it is silently trusted. Nobody reviewing the v4 bump was careless — the pin
was green, the evals were revised first per 0107, ablation was run per 0172,
and the defect still shipped, because every one of those mechanisms was
pointed at the charter and the defect was three paragraphs away in a file the
mechanisms did not read.

The generalisation is about scope, not diligence: **a contract's guard must
cover the whole contract, or it teaches people the uncovered part does not
exist.**

**The surface is still not complete, and this is the part worth carrying.**
`guest_tools.TOOLS` carries roughly seven description strings, and they are
instructions the model reads on every turn with tools attached. 0172 measured
one of them as load-bearing: with 6c's clause stripped from the charter, the
guest still refused to claim a facing, and the `turn` tool's own description
was named as one of the things holding that property up. So a tool-description
edit can move the voice today with no version bump and no eval trigger —
exactly this defect, one file over.

It is deliberately not pinned here. Coupling PROMPT_VERSION to the tool schema
means a functional change to an argument forces a live voice-eval run, and
whether that trade is worth it is a judgment about how the two evolve
together, not something to settle inside a lane whose boundary is what the
guest says about provenance. The evidence is recorded so the next session can
decide it in one step rather than rediscovering it.

## What would change this decision

- **A voice regression traced to a tool description.** Then the trade above is
  settled by evidence and `TOOLS` joins the digest.
- **A fourth instruction surface appears** — a per-scene preamble, a system
  block for a new capability. It joins the digest when it is created, not
  after it causes something.
- **PROMPT_VERSION bumps start firing on changes that cannot move the voice.**
  That would mean the surface has been drawn too wide, and the eval trigger
  would start being ignored — the same rot, from the other direction.
