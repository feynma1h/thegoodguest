# 0055 — Founding vision recovered: what survived the pivot, what didn't

**Date:** 2026-07-20
**Status:** Decided

## Context

CLAUDE.md had drifted into pure infrastructure framing — "browse, edit, replace, share
scenes" — and the first web scaffold inherited that drift: a scene-file browser with a
3D viewer, marketed as "your room in 3D." The founder flagged it: the product is not a
showcase of turning rooms into 3D; it helps people make **AI-based decisions about how
to improve their room** — the 3D representation is part of it, not the point. The
founding vision document (preserved verbatim at `docs/product/initial-idea-draft.md`)
was never captured in the repo.

## What we tried

Reconciled the draft against every decision made since. The draft predates the iOS
pivot (0001) and much of its tech plan lost to real decisions with recorded reasoning.

**Superseded (do not resurrect from the draft):**
- "RoomMind" naming — discarded long ago. **No name has been chosen; "roomstudio" is a
  working placeholder** (repo name, GCP project, wordmark). UI keeps the wordmark
  swappable in one component (`web/src/components/Wordmark.tsx`).
- Perception: SAM2 + Depth Anything V2 monocular estimation → replaced by SAM 3 +
  SAM 3D Objects + **measured** ARKit/LiDAR data (0001: stop reconstructing from
  pixels what the phone measures directly). Photo-upload-first → iOS-capture-first.
- Infra: Supabase/Vercel/Modal/Redis plan → GCP (Cloud Run, Firestore, GCS, Cloud
  Tasks) + Firebase Auth/Hosting (0016, 0050).
- 3D asset plan (Poly Pizza GLTF + TripoSR) → per-object Gaussian splats from the
  user's own room (0052) — strictly closer to the draft's "shows you yours" thesis
  than generic catalog models.
- The draft's "Tech Stack (Decided)" and "Do Not Re-litigate" lists — historical;
  decisions in `docs/decisions/` supersede them. (E.g. R3F/Theatre.js are plausible
  future choices for reveal choreography but are NOT pre-decided; Spark containment
  in 0053 keeps the renderer swappable.)

**Durable (now written into CLAUDE.md as the product frame):**
- The thesis: every home contains a version of itself its owner has never seen; the
  product makes it visible, understandable, achievable — one conversation at a time.
- The three-layer product identity (AI layer / emotional layer / social layer) and the
  intelligence-stack *shape*: perception → spatial reasoning (relationship graph,
  pre-LLM analysis) → constraints → design generation with reasoning traces → a
  specification contract driving all rendering. The current capture→perception→
  placement pipeline is the modern Layer 1–2 substrate.
- The experience bar: Linear/Vercel/Figma-tier premium consumer product; desktop-first;
  conversation as the primary post-reveal interface; the cinematic reveal as the
  defining moment; serif-for-feeling / mono-for-thinking typography; motion and sound
  as first-class.
- The feature map's shape: room health, taste graph, lighting simulation, budget-aware
  shopping, version history as a DAG, collaborative mode — as direction, not commitments.
- The deprioritized list (no AR overlay, no social feed, no photorealistic image gen,
  no floor plans, no voice) — still sound post-pivot.

## What we chose

Three artifacts: the draft preserved verbatim under `docs/product/` with a provenance
header pointing here; CLAUDE.md's "What we're building" rewritten to lead with the
thesis and the decision-support framing (and to state the name situation); and the web
app's copy/IA/visual language redone to match (rooms-centric navigation, thesis-led
landing, serif+mono type system — the draft's one aesthetic decision that survives
unchanged).

## Why

The infrastructure was drifting toward being the product. Fifty-plus decision notes
document *how* the system works; nothing in the repo said *why anyone would want it*.
A repo whose always-current brief describes upload paths but not the thesis produces
exactly the scaffold this session first shipped: technically correct, spiritually
wrong. Capturing the vision where every session reads it is the fix at the root.

## What would change this decision

- A chosen name replaces the placeholder (one component + config references).
- Product-direction changes belong in CLAUDE.md's vision section + a note superseding
  this one — the draft file itself stays frozen as history.
