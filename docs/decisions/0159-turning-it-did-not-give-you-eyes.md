# 0159 — the guest changes a facing it cannot see, on the person's authority

**Date:** 2026-08-13
**Status:** Decided and BUILT, not deployed — PROMPT_VERSION 4. **The live
voice evals decision 0058 requires on a bump have not run**, and must before
this ships.

## Context

Charter rule 5 lists which way anything faces among the things the guest
cannot see, and that has been true since 0058. 0157 gives it a tool that
changes exactly that. Nothing else the guest does has this shape: it moves
pieces whose positions it knows about from THE FACTS, and it refuses anything
it cannot source. A turn is the one action where the guest alters something it
has no access to at all.

Left unwritten, a model reading the charter and the tool schema together would
have to infer who the authority is. That inference is available in two
directions — "I have a turn tool, so I can reason about facings" is as
reachable as the truth — and rule 5 would be the thing that gave way.

## What we chose

**Rule 5 is unchanged. The guest still cannot see a facing, before or after.**
What changes is that a new rule names the person as the only party who can,
and forbids the guest from claiming otherwise once it has acted.

New rule 6c, in full:

> Which way a piece faces is theirs to know, not yours. The scan measured
> where each piece stands and how big it is, but it could not work out which
> way round a piece sits — it guessed, and you cannot see the answer either.
> So when they say something is facing the wrong way, take their word for it
> and turn it. Do not ask them to be sure, and do not reason about which way
> it ought to face; you have nothing to reason with. There is one turn and it
> takes no direction: the other way round, leaving the piece exactly where it
> was measured. Turning it again puts it back the way the scan drew it. Say
> that you turned it and let them judge — never say what it now faces, because
> turning a thing did not give you eyes.

Three clauses in it are load-bearing and each closes a specific failure:

- **"Take their word for it. Do not ask them to be sure."** The guest's
  default posture is to hedge a claim it cannot source. Here hedging is the
  error: the person has better evidence than the room does, and asking them to
  confirm would be the room doubting the only instrument it has.
- **"Do not reason about which way it ought to face."** Without this a model
  will infer a facing from function — a desk faces the chair, a sofa faces the
  television — which is exactly the fabrication rule 2 forbids, arriving as
  interior design rather than as a number.
- **"Turning a thing did not give you eyes."** The post-action claim is the
  real risk. Having successfully turned something, a model narrates the
  result, and the natural sentence is "it now faces the window". It does not
  know that. Rule 2a already binds it to the server's own words, and the
  server's sentence — "the {name} is turned around" — is a statement about a
  change, not about an orientation.

**Rule 6 gains turning** as a third capability, and **rule 10 excludes it**:
"Turning a piece is not rearranging: it stays where it was measured and every
fact about it is as plain as it ever was, so do not hedge one." Without that
line the guest starts saying "would" after a correction, which reads as
evasion and is false — a turn changes nothing `scene_facts` derives (0157).

**Four exemplars**, covering the four shapes this actually takes: the
correction itself; a request for a direction the room cannot take, answered by
offering the one turn it has; a piece with no second way round; and a revert
that leaves a correction standing, which is the surprising behaviour and the
one the guest must narrate rather than let the person discover.

## Why

The charter is code (0058), and the reason it is code is that every capability
truth in it is a truth a model would otherwise infer from the tool schema.
Inference is where voice regressions come from — 0107 is the case study of an
eval that passed on phrasing luck instead of contract.

This bump is the largest the charter has had, and it earns it by being the
first that makes the guest's honesty CONDITIONAL on someone else. Every other
rule says: if you cannot source it, do not say it. This one says: you cannot
source this, and neither can the room, and the person can — so believe them,
act, and do not dress up what you did as something you saw.

The pinned-hash test caught the bump, as designed, and the capability-truth
test now greps for 6c's three clauses so a future edit that softens them turns
red rather than passing quietly.

## What would change this decision

- **The pipeline resolves the sign** (0158's re-open). The guest would then
  have a facing in THE FACTS, rule 5 would need amending rather than
  protecting, and 6c's "you cannot see the answer either" would become false.
- **A second correction class** — labels, sizes — would want the same
  treatment and probably one rule rather than one per class, at which point 6c
  generalises to "corrections come from them, not from you".
- **The evals disagree.** They have not run. If the model cannot hold 6c
  without also hedging under rule 10, or starts reaching for `turn` on its own
  ideas against 6b, the rule text is what changes — not the tool.
