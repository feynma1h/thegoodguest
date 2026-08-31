# 0056 — Design language: Apple-grade restraint; 3D-stack and conversation sequencing

**Date:** 2026-07-20
**Status:** Superseded by 0057, which replaced the visual reading. The stack gating and the amendments to 0055's "durable" list still stand.

## Context

The first product-true redesign interpreted "premium" as warm luxury: Fraunces serif
headlines, amber/gold accent, mono eyebrows. The founder's correction was precise:
**"Apple premium, not gold premium."** Gold premium makes the chrome the jewelry;
Apple premium makes the chrome disappear so the product's content is the only
ornament. For this product the distinction is close to philosophical — the user's own
room is the hero image, and a UI wearing gold competes with it.

Alongside the visual pivot, two open stack questions needed pinning: whether the
founding draft's R3F/Drei/Theatre.js/Framer-Motion frontend stack still binds, and
where the conversational feature (the draft's primary post-reveal interface) actually
lives in the roadmap.

## What we chose

**Design language — permanent rules, not a theme:**
- **Neutral chrome.** Near-black achromatic surfaces, hairline borders (white at low
  opacity), translucent blur for the nav, white filled-pill primary actions. No brand
  color in chrome. Color belongs to CONTENT: the room, its light. (The landing's
  cursor-light survives as warm-white room light — it *is* the product — not as gold
  paint.) This also resolves the draft's "adaptive palette" more cleanly than the
  draft did: chrome stays neutral forever; mood/room-derived tint may inflect content
  surfaces (hero lighting, viewer ambiance), never controls or typography.
- **Sans-led typography.** One geometric sans (Geist) carries all hierarchy through
  weight, size, and tracking. **This amends 0055**: the draft's "serif = feeling"
  rule is retired from product UI (Fraunces removed). DM Mono survives with a
  narrowed charter — machine data only: identifiers, coordinates, reasoning traces.
  Never decorative (no uppercase-tracked eyebrows, no mono badges). Status reads as a
  colored dot + quiet sans label.
- **One spring.** The `motion` library, adopted now, with a single spring config
  (stiffness 180 / damping 24 — the draft's spring, finally real instead of a CSS
  approximation) in `web/src/components/ui/spring.tsx`. Every element that moves uses
  it; nothing animates that doesn't need to.
- **De-boxing.** Whitespace and alignment do the separation; bordered panels only for
  genuinely tappable objects (room cards) and content stages (the viewer).
- **Dark-first stays** — deliberately not chasing Apple into lightness, because the
  content is luminous 3D scenes and dark stages light.

**3D stack — scheduled, not rejected:**
- R3F + Drei (+ Theatre.js for reveal choreography, + Leva for dev tuning) are
  adopted **when the scene graph becomes reactive state** — board item 6's
  interactive surface: per-object selection, gizmos, conversation-driven mutation,
  the reveal. Today's viewer is a write-once splat stage; R3F reconciles nothing
  there. The 0053 containment rule makes the future adoption a one-file rewrite of
  `SplatViewer` internals. The earliest natural adoption point is per-object
  selection, which is buildable against fixtures with no backend prerequisite.

**Conversation — two stages with different prerequisites:**
- **Stage 1, conversation-over-analysis** (read-only, grounded): Q&A about what
  perception already produced — the manifest-v2 objects, dimensions, placement,
  light. Needs only an SSE streaming endpoint on api-public (static-export client +
  existing CSP connect-src are already compatible), conversation state in Firestore
  keyed by scene, and Claude as the reasoning model. No design-generation machinery.
  Scheduled directly after board item 1's deploy/verification — it is the first
  feature that delivers the product's decision-support promise, and the first
  consumer that will make the unbuilt spatial-relationship graph earn its place.
- **Stage 2, conversation-that-mutates** (the draft's refinement loop): lands
  together with the Design Specification contract and the reactive scene — they are
  two halves of one mechanism (conversation mutates the spec; the scene reconciles
  against it).
- The room page is laid out as **viewer + side rail** from this pass onward; the
  rail carries analysis/inventory today and is the conversation's designated home —
  no fake chat UI shipped, just layout that anticipates its tenant.

## Why

Restraint is the harder, higher signal: it survives a chosen name, a light theme, a
marketing site, and every future feature without redesign, and it keeps every surface
subordinate to the one image that matters emotionally — the user's own space.
Scheduling R3F at the reactive-scene boundary spends complexity exactly when it buys
reconciliation, not before. Splitting conversation lets the product's core promise
(understand your room, ask it questions) ship quarters before the redesign engine
exists, instead of being held hostage by it.

## What would change this decision

- A chosen name with strong brand color could earn a *single* accent in chrome —
  applied to at most one element class (primary action), never surfaces.
- If stage-1 conversation proves users want mutation immediately, stage 2's
  design-spec work gets pulled forward on product evidence.
- If per-object selection lands and R3F friction with Spark proves worse than
  expected in practice, the containment rule permits staying imperative — the gate is
  an intent, the boundary is the guarantee.
