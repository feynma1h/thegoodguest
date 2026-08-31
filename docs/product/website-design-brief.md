# Design brief — the web product (hand-off to a from-scratch design session)

> This is a prompt for a design session. It describes a real, in-development product
> in full: its soul, its complete feature set (built and unbuilt), its every screen,
> and the truths its interface must never violate. You are being asked to **redesign
> the entire web experience from a blank page** — do not treat the current
> implementation as a constraint. Where a feature is only planned, design it anyway.
> Where the reality today is thinner than the ambition, **design for the ambition.**
> Go fully creative. You have absolute freedom over form. The rest of this document
> exists so that freedom is *informed*, not so it is fenced.

---

## 0. The one-line mandate

Design the desktop-first web experience for a **spatial intelligence product that
helps people discover the best version of their own home** — through AI room
analysis, a cinematic 3D reveal of *their actual space*, and an ongoing conversation
that reasons about it and, eventually, redesigns it with them.

The product has no chosen name yet. "thegoodguest" is a working placeholder and the
wordmark is deliberately quiet (the room is the hero, not the brand). **You are free
to propose a name, a wordmark, and a whole identity** — treat this as an opportunity,
not a fixed asset.

---

## 1. The thesis (every pixel filters through this)

> **Every home contains a version of itself that its owner has never seen. This
> product makes that version visible, understandable, and achievable — one
> conversation at a time.**

Read this twice. It has three consequences you must hold onto:

1. **This is NOT an "upload a photo → get a generated result" app.** The 3D
   reconstruction of the room is the *medium*, not the product. The product is
   *helping a person make good, AI-informed decisions about improving the room they
   already live in.* If your design makes it feel like a render generator, it's wrong.
2. **It is deeply personal.** The moment the product shows someone *their own room*,
   rebuilt in 3D, their emotional investment changes completely. The whole experience
   is engineered around that moment of recognition and the relationship that follows.
3. **The room is identity.** People will want to keep rooms over time, compare them,
   evolve them, and eventually share them. Rooms are not disposable outputs; they are
   a person's spaces, held with care.

### The three layers the product is built on

- **The AI layer** — understands space *structurally*, not just aesthetically: object
  relationships, traffic flow, light, proportion, constraint hierarchies. It does
  real spatial analysis *before* any language model speaks, and it can show a
  **reasoning trace** for every claim and, later, every design decision. It never
  fabricates. When it doesn't know, it says so.
- **The emotional layer** — feels personal, never algorithmic. The experience bar is
  **Linear / Vercel / Figma / Notion-tier premium consumer software.** Conversation is
  the *primary* interface after the reveal. The **cinematic reveal is the single
  defining moment** of the whole product and deserves to be designed like a film beat.
- **The social layer** — rooms as identity: sharing, comparison, evolution over time.

---

## 2. The voice: "the Good Guest" (load-bearing — keep the soul, reinvent the skin)

The product is personified as **a guest in your home** — warm, literary, speaks with
permission, never presumptuous, never clinical. It is the opposite of a dashboard.
The room page is framed as *"a conversation happening in a room; everything else is
furniture the conversation can summon."*

This persona is the emotional spine of the product and should survive your redesign —
but **you are free to reinterpret how it looks and feels entirely.** What must remain
true:

- There is a **speaker** — a warm intelligence that talks *to* the person about *their*
  room, in the first person, with care and restraint.
- The register is **hospitable and literary, not corporate.** No "Processing…",
  no "Upload successful", no progress percentages. States are narrated as a *guest's
  experience of arriving*: "Your scan made the trip. I'm at the door." / "I'm inside —
  meeting each piece, working out where it stands."
- **Honesty is a feature, not a footnote.** The guest never claims something it can't
  see. When a scan fails, it apologizes plainly, says it's not the person's fault, and
  offers one concrete next step — never a stack trace. When it can only place three of
  five pieces of furniture, it says exactly that.

Some sample lines from the current product, to calibrate the register (you may rewrite
all copy — this is tone reference only):

- Landing: *"Every home contains a version of itself its owner has never seen."*
- The reveal threshold: *"It's ready. Come in when you have a minute — this is worth
  your full attention."*
- After the reveal: *"Your furniture came through ahead of the walls — they're still on
  their way. Honestly, my favorite way to meet a room: just the things you chose,
  nothing behind them."*
- A failed scan: *"I'm sorry — the scan didn't survive the trip, and there's nothing
  here I could honestly show you. It's not something you did. When you're near the room
  again, let's try one more pass — slower is better."*
- The empty house: *"One room is a conversation. A house is a life — whenever you're
  ready."*

---

## 3. The complete user journey (design every act — future state)

The product is desktop-first and immersive. Capture happens on an **iOS app** (the
phone walks the room); **everything else — analysis, the reveal, conversation, redesign,
identity, sharing — happens on the web.** Design the web as the home of the product.

Think of it as a sequence of acts. Design each as its own considered screen/state.

**Act 1 — Arrival (the landing).** A single, quiet, arresting claim and one action.
The founding vision imagined a full-screen live WebGL room where *the cursor is a soft
light source that bleeds color into a desaturated room — the room is the product demo
before a word is read.* A live 3D demo room is real and available to embed. First-time
visitors get the thesis; returning visitors are *greeted by the guest and pointed at
their newest room* (no marketing flash). No nav clutter, no feature grid, no pricing on
the hero. "Your rooms are yours. No photos generated. No feed."

**Act 2 — The handoff / "the bridge" (phone → desk).** Capture is on the phone; this
desk is where the room *arrives*. The page genuinely listens: it watches for a scan it
hasn't seen, and when one lands, it takes the room in and walks into the wait — no
upload buttons, no filenames, no drag-and-drop. (A phone→desk deep-link QR is a future
convenience; today it's a declared placeholder. Design the *aspiration*: a seamless,
magical "point your phone here" bridge.)

**Act 3 — The wait (minutes, not seconds).** Reconstruction takes real time. The wait is
**narrated as a guest arriving and getting to know the room**, never a progress bar or
pipeline state. An ambient "forming" atmosphere (breathing, not spinning). "You can
leave — this page keeps watch."

**Act 4 — The reveal (THE defining moment — give it its own design sprint).** This is
the product's soul made visible and its viral/marketing asset. The founding vision
specifies a frame-perfect choreographed sequence (paraphrased):

- Ambient room-tone fades in softly.
- AI analysis annotations appear over the source, staggered, then fade together.
- A low architectural chord (not a swoosh) begins the transformation.
- The 3D scene assembles — **objects-first, largest piece first, each named as it lands**
  ("the bed", "the desk lamp"), the room *standing itself up*: floor, then walls, then
  the furniture settling into place.
- The room *holds*. No UI. Silence. Let the moment breathe.
- Then the conversational interface fades in and the guest speaks first.

The reveal **never auto-plays** — the room waits at a threshold until the person chooses
to "come in," and it only reveals once per room. Reduced-motion collapses gracefully to
a finished room. **Own this moment. Make it unforgettable.**

**Act 5 — The room + the conversation (the primary product surface).** After the reveal
the room is a full-bleed immersive **stage**; all chrome floats over it and is minimal.
**Conversation is the primary interface** — a composer where the person asks about their
room and the guest answers, grounded strictly in what was actually measured (streaming,
sentence by sentence, calm). A quiet inventory ("in this room") lists what was placed
and what was seen-but-not-yet-placed. This is where redesign will eventually live: every
request will mutate the room, animated, with the guest explaining each decision.

**Act 6 — The house (all your rooms).** Rooms are **siblings, not a file list** — no floor
plan, no map; each room its own conversation, shown as a stage/card with a derived title
("the July 12 room" until real naming ships) and state expressed as *treatment + words*,
never status badges. Empty, loading, in-flight, failed, and ready are all distinct,
designed states.

**Act 7 — Identity (the takeaway).** After a person has worked with the product, it
should hand them something that is *theirs*: an aesthetic fingerprint, a shareable
generative artifact (the founding vision calls this a "Design DNA card") — beautiful,
generative, unmistakably personal, not a screenshot.

**Act 8 — Sign-in / account / the cross-device seam.** Rooms are captured signed-in on
the phone and followed to the web by signing in with the same identity (Apple). Signed-out
states are **invitations**, not errors: "Your rooms are signed in on your iPhone. Sign in
here with the same Apple ID, and the house follows." Design the account surface, the
sign-in moment (which should feel like being *recognized*, not authenticating), and the
signed-out invitations across the house / a room / the bridge.

---

## 4. The complete feature set (design for ALL of it — mark of quality is that nothing is missed)

Organized by ambition tier. **Legend:** ● built & live · ◐ partially built / near · ○ planned,
unbuilt. Design for the full set regardless of state; **prefer the future state everywhere.**

### Tier 1 — Non-negotiable core

- **Spatial intelligence pipeline** ● — phone capture → segmentation → per-object 3D
  reconstruction → placement in the room's real metric frame → a room shell (floor +
  walls with measured materials). The output is a genuine 3D reconstruction of the
  person's actual room, assembled from individually recognized objects plus a parametric
  room shell. (This is *not* photorealistic image generation — see §6.)
- **Conversational refinement loop** ◐ — conversation is the primary post-reveal UI.
  *Built today:* read-only Q&A grounded strictly in measured facts, streaming replies,
  a durable transcript, honest "I can't see that yet" answers, budget-honest rests.
  *Future:* every message mutates the design; the AI holds full context (room graph,
  all versions, stated constraints, inferred preferences); it initiates proactively
  ("You haven't changed the bookshelf in three redesigns — want me to lock it and
  optimize around it?").
- **The cinematic reveal** ◐ — see Act 4. The assembly + threshold + naming exist; the
  full film-grade choreography (annotations over the source, sound design, the held
  silence) is the ambition.
- **3D room engine** ◐ — orbiting view of the assembled room exists (a "dollhouse
  cutaway" where near walls fall away so you can see in). *Future:* individual furniture
  selection & repositioning with real-time AI feedback; first-person walkthrough;
  smart camera; PBR materials and soft shadows; dynamic lighting.
- **Version history with branching** ○ — every design state as a node in a DAG ("Git for
  your room"): branch from any version, explore two directions at once, compare
  side-by-side. Presented as a **film strip with a scrubber**, not a sidebar list.

### Tier 2 — High-impact

- **Room Health System** ○ — five scored dimensions, each explainable: Light Quality,
  Flow (traffic paths, clearances, bottlenecks), Proportion, Thermal Comfort,
  Psychological Comfort. Visualized as a **radar chart** (not progress bars), animated
  before/after, drillable into a full AI explanation per dimension.
- **The Taste Graph** ○ — a multi-dimensional aesthetic fingerprint (warm↔cool,
  natural↔synthetic, minimal↔maximal, structured↔organic, muted↔vibrant, low↔high),
  built after a couple of sessions, shown as a hexagonal radar, evolving over time,
  surfacing insights proactively. The long-term data asset.
- **Design DNA card** ○ — see Act 7. Shareable generative artifact; social-growth engine.
- **Lighting Sculptor** ○ — draggable sun position over a sky dome, real-time shadow
  recalculation, "right now in your city" geo/time presets, an artificial-light editor
  (position, color temperature, intensity), and a "24 hours in 10 seconds" day-cycle
  playback.
- **Budget-aware shopping layer** ○ — each redesigned room yields a shoppable manifest:
  three tiers per item (Dream / Realistic / Thrift), a "what I already own" filter, a
  one-sentence "why this piece", and a compatibility score. (Primary monetization.)

### Tier 3 — Differentiation ("how did it know that")

- **Environmental context engine** ○ — on session start, use geo + time + weather to set
  the room's initial lighting to *actual current conditions* — "right now in your room."
- **Emotional reaction layer** ○ — after a reveal, replace star ratings with a 3×3 grid of
  feelings (Calm / Excited / Inspired / Cozy / Sophisticated / Playful / Focused /
  Romantic / Uncomfortable); map reactions over time; "This is the first design that
  excited you — here's what's different."
- **Style Collision mode** ○ — pick two contradictory aesthetics; the AI *synthesizes*
  (not compromises) them and explains the resolution architecturally. Inherently shareable.
- **Ambient mode** ○ — a full-screen room cycling through 24 hours of real-time lighting
  with subtle ambient sound; "your room as living art" (designed for a tablet on a shelf).
- **Collaborative design mode** ○ — two people in one room session simultaneously, live
  cursors, changes merging in real time (couples, roommates, designer-client).

### Tier 4 — Foundational moat (design need not surface these, but know they exist)

Anonymized room-graph dataset; a designer API (B2B); LiDAR-precise capture (the premium
capture path the product is now leaning into — see §6).

### Monetization surfaces to accommodate (future)

Freemium (a few free redesigns, basic orbit) → **Pro (~$18/mo:** unlimited redesigns,
full version history + branching, walkthrough, lighting sculptor, collaboration, full
shopping manifest, DNA card + taste graph, priority processing) → **Studio (~$79/mo:**
designer API, white-label preview links, multiple projects, client seats, PDF export).
You don't need to design pricing pages now, but the product should have *room* for these
tiers and a Pro upgrade moment that feels earned, never nagging.

---

## 5. The explicit list of views/screens to design

At minimum, design considered states for all of these. Invent more if the product wants them.

1. **Landing / arrival** — first-time (thesis + one action + live demo room) and
   returning-visitor (guest greeting + pointer to newest room).
2. **The house** — the room collection: empty, loading, ready-with-rooms, signed-out,
   error. Room cards/stages with derived titles and state-as-treatment.
3. **The bridge** — phone→desk handoff: listening, "heard it", signed-out.
4. **The wait** — a room being rebuilt, narrated; queued vs. in-progress vs. taking-long.
5. **The reveal** — threshold ("come in"), the objects-first assembly with naming, the
   settle into the room.
6. **The room (settled)** — full-bleed stage, floating chrome, the conversation
   composer + transcript, the inventory panel, the "as captured" moment.
7. **Conversation states** — idle, streaming reply, the guest thinking, an earlier
   exchange collapsed to a tap-to-expand stub, a budget rest, a mid-turn failure with the
   person's words kept, "one voice at a time" (open in two tabs).
8. **Failure states** — partial scan (recoverable, honest about missing pieces),
   terminal failure (dark, apologetic, one next step).
9. **Sign-in / account menu / signed-out invitations** (house, room, bridge).
10. **Future surfaces to design speculatively:** the redesign/mutation loop, version
    history film-strip + branch comparison, room health radar + drill-down, the taste
    graph, the Design DNA card, lighting sculptor, the shopping manifest, the emotional
    reaction grid, ambient mode, style collision, collaborative cursors.

---

## 6. Hard truths the design must honor (do not violate)

These are not stylistic preferences; they are what the product actually is.

- **No fabricated data, ever.** The guest speaks only from what was truly measured. If
  the interface shows a number, a placement, or a claim, it must be real. Design *around*
  honest uncertainty — "seen but not yet placed", "walls still on their way" — rather than
  papering over it. This honesty is a differentiator, not a limitation to hide.
- **No fake affordances.** Don't design controls that don't do anything. If a feature
  isn't built, either design it as a genuine future state (clearly aspirational) or don't
  imply it's live. (The current build ships some elements deliberately labeled as
  placeholders for exactly this reason.)
- **The 3D is real reconstruction, not image generation.** Explicitly out of scope and not
  to be implied: photorealistic AI image generation of rooms. The room is built from the
  person's actual captured space (per-object 3D splats + a measured parametric shell). A
  live WebGL room, not a pretty picture.
- **Capture is iOS-only and lives on the phone.** The web never has a "drag a photo here"
  primary path. The premium future leans **LiDAR / Pro-device capture** for the most
  faithful rooms; the web treats a room as a room regardless, but "LiDAR gives the most
  faithful rooms" is a true, surfaceable nudge.
- **Deliberately excluded forever** (per founding product decisions — do not design these):
  AR camera overlay, a social feed of strangers' rooms, multi-room floor-plan editing,
  voice input, a full e-commerce marketplace (affiliate links only), and mobile-first
  layouts. **Desktop-first**; mobile can be responsive but is never the design driver.
- **Sharing is intimate, not a feed.** Rooms as identity means share *your* room / your DNA
  card, compare *your* rooms over time — not a public timeline of others' homes.

---

## 7. Design-system DNA (durables worth carrying — but reinvent freely)

The current product uses a warm, literary system called **"Good Guest."** You are free to
keep it, evolve it, or replace it — but here is the DNA, and the founding vision's original
system, so your choices are informed. Treat everything in this section as **inspiration and
rationale, not a spec.**

**Current palette & type (what exists):** warm light-first — parchment/cream surfaces,
warm-brown ink, **rust** as the single action/emphasis color, and muted **gold used
*strictly* as a light/sun indicator, never as ornament or status.** Dark warm-ink panels
are the emphasis register (the reveal threshold, terminal failure). Type: a **serif
(Source Serif 4 italic) reserved for the guest's voice**, a **sans (Instrument Sans) for
all UI**, and a **mono (IBM Plex Mono) for eyebrow labels + machine data (ids,
coordinates).** The rule "serif = speech, mono = thinking, sans = interface" is semantic,
not decorative.

**A standing taste rule from the founder: "Apple premium, not gold premium."** Warmth and
hospitality pass the bar; *ornament-as-status / gilt* does not. Whatever palette you choose,
restraint and content-forward calm beat decoration. The room carries the color; the chrome
stays quiet.

**The founding vision's original system (an alternate, richer direction you may draw on):**

- **Adaptive palette** — no fixed scheme; the UI *wears the user's chosen aesthetic*. Each
  mood seeds a 5-color palette from which the whole UI derives. ("The product wears your
  aesthetic.")
- **Type as feeling vs. thinking** — a *variable* serif (Fraunces / Playfair, weight
  100–900) for atmospheric copy whose weight responds to emotional intensity; a geometric
  mono for data/scores/coordinates/AI reasoning. Never mixed in one sentence.
- **Mood-poetic labels over categories** — "Sunday morning slow", "Tokyo studio, 11pm",
  "The cabin you keep meaning to rent", "Grown-up, finally", "Creative chaos, intentional".

**Motion — "the spring system" (keep this discipline):** every element that moves uses one
custom damped spring (physically weighted, not bouncy, not linear). Micro-interactions:
buttons breathe on hover and press; the AI "thinking" state is a subtle breathing pulse on
the room (never a spinner); loading is furniture fading in piece by piece; errors are a
single gentle shake (not red, not alarming); success is a brief warm light pulse. One spring,
applied universally, is what makes the whole thing feel *real*.

**Sound (optional, opt-in, ~10% volume):** ambient room tone matching the aesthetic, a low
architectural chord on the reveal, barely-audible tactile UI sounds. "5% of the engineering
effort, 30% of the perceived quality." Design with the *intention* that sound exists.

---

## 8. What I want back from you

Go fully creative and start from a blank page. I'd rather see a bold, coherent, emotionally
resonant vision than a safe iteration of what exists. Specifically:

- A **complete visual and interaction design** for the web product covering the journey in
  §3 and the screens in §5 — with the **reveal (Act 4)** and the **room + conversation
  surface (Act 5)** as the centerpieces.
- A **design system** — identity/wordmark (propose a name if you like), palette(s), type,
  motion, sound intentions — that could carry the whole product, including the unbuilt
  Tier 2/3 features.
- **Speculative but concrete** designs for the marquee future features: version-history
  film strip, room-health radar, taste graph, Design DNA card, lighting sculptor, the
  redesign/mutation loop, and the shopping manifest.
- Honor §6's hard truths. Everything else is yours to reimagine.

Make it feel like software that makes a person *feel seen* — the rarest feeling in consumer
tech, and the entire point of this product.
