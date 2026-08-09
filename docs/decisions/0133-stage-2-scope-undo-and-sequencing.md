# 0133 — Stage 2 scope: move and remove ship, the catalog does not, the ledger stays banned

**Date:** 2026-08-09
**Status:** Decided and BUILT, not yet deployed — move and remove ship; the
catalog, versioning, and the ledger deliberately do not. Merged to `main`
2026-08-09.

## Context

The board-9 brief asks for a recommended scope split rather than a smuggled one,
and reopens three questions 0058 parked: undo/versioning (the founding draft
wants a DAG; CLAUDE.md files version history as direction, not commitment), the
ledger (0058 deferred it **and banned its vocabulary**), and what the guest may
propose unprompted (settled in 0132).

## What we chose

### In scope: move and remove. They are one mechanism.

Both are a single entry in the specification (0131) — one carries a
`proposed_transform`, the other withholds the splat. Same keying, same
measured-beside-proposed rule, same solver refusal path, same revert. Splitting
them would double the surface for nothing.

Probe 1 (0129) makes this cheap in a way it might not have been: removal is
**visually free** on the shipped shell, because 0069 replaced the photographic
bake with per-plane measured albedo and the room has no memory of what stood in
front of it. Hiding an object leaves clean floor and clean wall.

### Out of scope: suggesting new furniture. Different capability, different thread.

It needs a product catalog and a source of truth about what exists to buy —
CLAUDE.md files this under *budget-aware shopping*, in the direction-not-
commitments list. Three further reasons specific to what we now know:

1. **The honesty contract has no answer for it.** Every claim the guest makes is
   sourced to a measurement of *this* room (0058, 0096). A catalog item's
   dimensions come from a vendor, and the guest has no way to mark that a number
   is trustworthy-but-foreign. The foreign-measurement detector would fire on
   every one, correctly.
2. **The visual register problem is unprobed.** The brief's third consequence —
   a clean asset among partial, baked-light reconstructions — was **not tested in
   either direction** (0129). It might look fine; nobody has looked.
3. **"Will it fit" is the question a catalog invites and the one the data cannot
   answer.** 0096's clearances are rigorous *floors*, and rule 3a forbids turning
   a floor into a verdict on fit. A shopping feature whose central question the
   guest must decline is a bad feature, not a constrained one.

**Re-open trigger:** the up-axis extent lands in the manifest (0096's own
trigger), *and* a probe shows a clean asset composited into a real room reads
acceptably.

### Undo: linear, not a DAG. One arrangement per scene+user.

- The spec is an ordered list of entries; each records the turn that created it
  (0131). Undo drops the last entry; revert drops one object's entry.
- **"Back to measured" is always one action.** This is not a versioning feature,
  it is the honesty invariant made operable: the measured room must never be
  more than one step away.
- No branches, no named alternatives, no comparison view.

**Re-open trigger:** a user wanting two arrangements side by side. That is the
first thing a DAG actually buys, and until someone wants it the DAG is a schema
carrying no information.

### The ledger stays deferred, and the vocabulary ban stays.

0058 deferred it with four reasons and set the trigger as "extents and/or
per-object selection". Extents shipped (0096), and stage 2 adds tools — so the
trigger is met and two of the four objections are gone. It still should not ship,
for the objection that survives:

**A stated constraint is model-authored text fed back as grounding.** 0058
rejected summarization for exactly this — *"model-generated content feeding
future grounding is a compounding fabrication channel"* — and a pin reading "they
need the path to the window kept clear" is that channel with a nicer name. Tools
dissolve the zero-tools objection; they do nothing about this one.

And the thing a ledger was for now exists in a checkable form: **the spec is a
durable record of what the person asked for**, one entry per request, each
carrying its originating turn. That is a ledger of actions, which can be verified
against geometry, rather than a ledger of paraphrased intentions, which cannot.

**The vocabulary ban is unchanged**: no product copy adopts "put into words" /
pin / keep until a real ledger ships. New trigger, added to 0058's: real usage
showing people restating the same constraint every turn because the system cannot
hold it.

### Sequencing: per-object selection is NOT a prerequisite, and R3F is not either.

0056's instinct was that the spec and the reactive scene are two halves of one
mechanism. They are — but only for a *changing object set*. A changing
**transform** needs no reconciliation, and that is all `move` is.

- **Selection is a nicety, not a gate.** People name things in words, and the
  inventory panel already lists them. 0058 recorded selection-as-asking as a
  POST-body extension; it stays that.
- **R3F is not a gate either**, though 0130 proves it works and it becomes worth
  adopting when the object set goes reactive (remove, restore, add).

**But there is one real blocker, and it is small and specific.**
`SplatViewer.tsx:194` computes its renderer key as
`splats.map((s) => `${s.url}@${s.position.join(",")}`)`, and the renderer effect
depends on it (`:968`). **A proposed move therefore changes the key, tears down
the renderer, and reloads every splat** — 275.8 MB and 25–56 s on the reference
room, per 0123. Stage 2 is unusable until transforms leave the key and are
applied in their own effect. That is roughly fifteen lines, it is
renderer-internal, and it is the same seam an eventual R3F migration deletes.

Two things fall out of that line worth stating separately: the array identity
`splats` is also in the dependency list and must be memoized upstream, and
`rotation_xyzw` and `scale` are **not** in the key today — so a rotation-only
change already fails to apply, silently. Nothing depends on that yet.

## Why

The scope line falls where the *source of truth* changes. Move and remove
rearrange things this room measured; a catalog introduces objects it did not, and
with them a second epistemics the guest has no grammar for. That is a bigger
change than it looks, and it is why CLAUDE.md files it separately.

The ledger reasoning is the interesting one, because the trigger 0058 wrote did
fire. Re-reading the four objections rather than the trigger is what showed that
the surviving objection is the one that was always load-bearing, and that the
feature's actual purpose is served better by a record of actions than a record of
paraphrases. Triggers are prompts to re-examine, not commitments to build.

Separating the two halves of 0056's "one mechanism" is the highest-value finding
here for scheduling: it means stage 2 can ship on the imperative viewer with a
fifteen-line change, and R3F adoption stays a real decision made when selection
and add/remove arrive, on 0130's evidence, rather than a prerequisite bundled
into a feature that does not need it.

## What would change this decision

- **Direct manipulation becomes the primary interaction** rather than
  conversation. Then selection *is* the feature and R3F moves first.
- **A user asks to compare arrangements**, which re-opens versioning.
- **People restate constraints every turn**, which re-opens the ledger.
- **The catalog thread starts independently** (it is not blocked on any of this)
  — then the register probe from 0129's open list should run before any of it is
  designed.
