# Conversational redesign — design session scoping brief

**Status:** EXECUTED 2026-08-09. The design lives in decisions **0129–0133**
(0134 unused); this file is kept for the build session and is now history, not
instruction. Where the two disagree, the decisions win — they were measured.

> **Two claims in the spine below were REFUTED by Probe 1 (see 0129). Read that
> note before using this brief as a design input.**
>
> - *"Removing an object exposes surface that was never observed"* is
>   materially wrong for the shipped shell. 0069 replaced the photographic bake
>   with per-plane measured albedo, so removal leaves clean floor and clean
>   wall. Removal is visually free.
> - *"A moved object exposes exactly the defects its original placement hid"* is
>   true but names the wrong culprit. Class-6 truncation makes the splat
>   *smaller* than its box and stays hidden; what actually shears is the 0104
>   `splat_clip` cross-section, measured cutting 16–31% of the Gaussians off
>   three of five clipped objects. That is known geometry the product owns, not
>   a perception limit.
>
> The brief's central instinct was right and load-bearing: it demanded the probe
> first, and the probe changed the feature's shape.

**Original status:** scoping brief, written by the coordinator 2026-08-09.
Nothing here is designed and nothing is built. The session that picks this up
owns decisions **0129–0134**.

**This is not a new feature request.** It is the product's own definition,
recovered from a record that had let it drift. CLAUDE.md line 3 defines
thegoodguest as "AI-powered room analysis, **conversational redesign**, and an
immersive 3D representation." Decision 0055 lists as *durable* the
intelligence-stack shape ending in "a specification contract driving all
rendering." The founding draft's Conversational Refinement Loop says "every
message mutates the Design Specification JSON incrementally," and Act 7 —
"room is the canvas, conversation is the tool."

**Correcting the record, because it will be read the other way:** decision
0056's line about pulling stage 2 forward "if stage-1 conversation proves
users want mutation immediately" sits under `## What would change this
decision` — this project's re-open-trigger section. It is an accelerant, not
a gate. What 0056 actually chose was sequencing on *technical* prerequisites,
and its stated reason for splitting the stages was to avoid holding the core
promise "hostage" to the redesign engine. Nobody decided to defer mutation.
It drifted into a dependent clause of board item 6(e) and stopped being
scheduled.

---

## What already exists, and is more than nothing

- **Conversation stage 1 is deployed and serving** (0058/0059). Grounded,
  streaming, read-only, cached, quota'd, with a disconnect shield.
- **The refusal is designed, not accidental.** `guest_prompt.py:99` — "You
  cannot move, change, redecorate, or buy anything yet — today you have eyes,
  not hands" — with a worked exemplar at line 143 for "Move the sofa under
  the window." 0058 enforces it structurally: "all mutation (stage 2 entire,
  **enforced by zero tools**)." All three verbs the operator named already
  have honest behavior in production.
- **`scene_facts`** at FACTS_VERSION 2 (0096): inventory with confidence
  tiers, sizes from `roomplan_box.dims` at high/medium confidence speaking
  only the longest dimension, and clearances as rigorous *lower bounds*.
- **The room page is already laid out for it** — viewer plus side rail, which
  0056 chose specifically as "the conversation's designated home."
- **`splat_clip`** (0104) — per-object measured volumes the renderer already
  honors.

## What does not exist

Stage 2 entire. Its two named prerequisites from 0056 — the **Design
Specification contract** and the **reactive scene** — are unbuilt, and 0056
calls them "two halves of one mechanism (conversation mutates the spec; the
scene reconciles against it)." Per-object selection, the stepping stone, is
unbuilt but marked buildable against fixtures today. R3F/Drei is unadopted;
`SplatViewer` is a write-once imperative stage that, in 0056's words,
"reconciles nothing."

---

## The spine: what makes this hard here, specifically

Every difficult problem in this feature is one problem wearing different
clothes:

> **The room is a measurement of ONE arrangement. Changing the arrangement
> moves objects into regions nothing was ever measured for.**

Three consequences, each grounded in a defect this project has already
measured and recorded:

1. **A moved object exposes exactly the defects its original placement hid.**
   Class-6 splat visible-region truncation is a *named open defect*
   (CLAUDE.md calls it "the named bottleneck"). A bed against a wall has no
   observed back; move it into the room and the missing face turns toward the
   camera. The splat also carries baked lighting from where it stood.
2. **Removing an object exposes surface that was never observed.** 0069
   records observed vs inpainted fractions per plane precisely because
   coverage is partial; the shell has measured albedo only where something
   was seen.
3. **A catalog object is a clean asset among partial, baked-light
   reconstructions.** Different visual register entirely.

And it collides with this project's deepest invariant: **measurement is never
falsified.** 0069 ships `measured_quad` beside the rendered quad; 0082
refuses to move an object to hide a splat artifact; 0104 declares a clip
volume rather than rescaling; placement ships `placed: false` with a reason
rather than a guessed transform. A Design Specification is by construction a
set of **non-measured** transforms. **How proposed and measured coexist
without the product lying is the central design question of this session**,
and it should be answered before any schema is written.

---

## Two verify-first probes, before any design is committed

This project's pattern (0067, 0077, 0081, 0104): probe on real recorded data
first, and let measurement kill the expensive assumption. Both of these are
runnable today against existing fixtures.

**Probe 1 — what does a real object actually look like moved?** Take real
placed objects from the staged walk rooms, translate them 1–3 m, orbit, and
look. Vary the class: something that stood against a wall, something
free-standing, something large, something small. Measure and describe the
truncation and baked-light artifacts honestly.

**This probe can reframe the entire feature and should be run first.** If
moved objects read as broken, then "move the furniture" may need a different
visual language — ghosted volumes, outlines, footprints on the floor,
annotation over the measured room — rather than photoreal relocation. That is
a product-defining answer, it is cheap to get, and getting it after the
architecture is chosen would be expensive. Do not assume the outcome in
either direction; the operator's walk verdicts (0080, 0085) are the standard
for what "reads right" means.

**Probe 2 — can R3F reconcile a Spark `SplatMesh` at all?** 0056 named this
risk explicitly and left an escape hatch: "if per-object selection lands and
R3F friction with Spark proves worse than expected in practice, the
containment rule permits staying imperative — the gate is an intent, the
boundary is the guarantee." Decision 0053 contains Spark to one module
specifically to keep this swappable. Prove reconciliation on a real scene
before adopting R3F, and note that "stay imperative and build reconciliation
by hand" is a legitimate outcome, not a failure.

---

## Questions the session must answer

- **What IS the Design Specification?** Its relationship to manifest v2 —
  delta over measured state, or a parallel document? What carries the
  reasoning trace 0055 lists as durable? What makes it renderable without
  overwriting anything measured?
- **The tool surface.** Stage 1 has zero tools *by design*. What is the
  minimum set, and how does the guest stay honest while using them — sizes
  speak only a longest dimension, clearances are lower bounds (0096), and
  "will it fit" is a claim the current facts often cannot support.
- **Scope split.** Move and remove are one mechanism. **"Suggest new
  furniture" is a different capability** — it needs a product catalog and a
  source of truth about what exists to buy, and CLAUDE.md files it under
  "budget-aware shopping" in the direction-not-commitments list. Recommend a
  split; do not smuggle it in.
- **Undo and versions.** The draft wants a DAG; CLAUDE.md files version
  history as direction, not commitment. Does v1 need any of it?
- **The ledger question returns.** 0058 deferred the ledger *and banned its
  vocabulary* ("no product copy adopts 'put into words'/pin/keep vocabulary
  until the real ledger ships"). "Constraints the user stated" is the ledger
  under another name. Decide deliberately whether stage 2 revives it, and
  keep the vocabulary ban intact until something real ships.
- **What the guest may propose unprompted.** The draft wants proactive
  initiation. Stage 1's charter is built around invitations, not assertions.

## Coordination

- **The P0 outranks this for BUILD, not for design.** People currently cannot
  see their rooms; that ships first. Design costs no code and touches no
  files the compressed-tier session is in.
- **One real interaction to hand back.** Progressive loading (the P0's open
  half) and the reactive scene touch the same module. If R3F adoption is
  likely, the P0 session should know whether load orchestration belongs
  *outside* the renderer so it survives the migration. Report that as soon as
  Probe 2 has an answer, even before the rest of the design is done.

## Constraints that are not negotiable

- Measurement is never falsified, and never silently. If the spec proposes a
  non-measured position, the measured one survives beside it.
- The guest never claims what it cannot see. Sizes, clearances, colors,
  materials, and facing all have recorded epistemics (0096, `guest_prompt`
  rules 3a/3b/5).
- Design language: Good Guest (0057). Gold is light-semantic only. One
  spring. No ornament-as-status.
- Person suppression (0089) survives any new bake or asset path.

## Ready report

Per-item outcome with evidence, the probe verdicts stated as measurements
rather than impressions, decisions written to `docs/decisions/`, what was
descoped and its re-open trigger, and — separately — what was measured versus
reasoned about, and what was not verified at all.
