# Initial idea draft (pre-pivot, preserved verbatim)

**Provenance:** the founding vision document this project started from, written before
any code existed. Preserved here because CLAUDE.md had drifted into pure infrastructure
framing and lost the product's soul. **Read decision 0055 before acting on anything in
this file** — the *vision* below is current; large parts of the *tech plan* are
superseded (the iOS-first ARKit pivot of decision 0001 replaced the photo-upload
perception stack; GCP/Firebase replaced the Supabase/Vercel/Modal plan; SAM 3 + SAM 3D
replaced SAM2 + Depth Anything; naming: "RoomMind" was discarded — no name has been
chosen; "roomstudio" is a working placeholder).

What remains binding is the thesis, the product framing (AI-guided room *improvement* —
the 3D representation is the medium, not the product), the experience bar, and the
feature map's shape. Treat the month-by-month plan, stack decisions, and
"explicitly decided" list as historical.

---

RoomMind — Complete Project Context & Continuation Prompt

Who I Am & What I'm Building

I am building RoomMind — a spatial intelligence web application that helps people
discover the best version of their home through AI-powered room analysis,
conversational redesign, and immersive 3D visualization. This is not a portfolio demo —
it is a real product I intend to launch, grow, and potentially raise funding for.

My profile as a builder:

* Tech stack is no constraint — I can pick up any technology in a couple of days
* Time is no constraint — I am building this to be exceptional, not fast
* I want this to be my magnum opus: simultaneously showcasing frontier frontend/UI
  engineering, deep AI systems thinking, and founder-level product judgment
* My primary audience is real users, potential investors, and the kind of companies
  that build premium AI consumer products (think Linear, Vercel, Figma, Notion-tier)

The Product Thesis

"Every home contains a version of itself that its owner has never seen. RoomMind makes
that version visible, understandable, and achievable — one conversation at a time."

Every feature decision filters through this thesis. Features that don't serve it get cut.

Core Product Vision

RoomMind is NOT an "upload image → generate result" AI app. It is a spatial
intelligence platform with three layers:

1. The AI Layer — understands space structurally, not just aesthetically. Reasons about
   furniture relationships, traffic flow, light distribution, proportion, and
   constraint hierarchies.
2. The Emotional Layer — feels personal, not algorithmic. Every interaction is designed
   to make the user feel seen by software.
3. The Social Layer — rooms are identity. Users want to share, compare, and evolve
   their spaces over time.

The Five-Layer Intelligence Stack (Core Architecture)

This is the non-negotiable architectural foundation. Do NOT simplify this into a wrapper.

Layer 1 — Perception

* Image → segmentation model (SAM2) → discrete object extraction
* Monocular depth estimation (Depth Anything V2) → dimension estimation
* Surface material classification
* Fixed vs. movable element detection
* Output: Room Perception JSON (structured object: dimensions, objects, materials,
  light sources, fixed constraints)

Layer 2 — Spatial Reasoning

* Room Perception JSON → Spatial Relationship Graph
* Nodes: every object in the room
* Edges: spatial relationships (facing, adjacent, blocking, complementing, competing)
* Algorithmic analysis: traffic flow problems, light conflicts, proportion mismatches,
  dead zones
* This analysis happens BEFORE the LLM is invoked

Layer 3 — Constraint Extraction

* From conversation + persona + budget input → Constraint Object
* Hard constraints (rental-safe, budget ceiling, keep specific items)
* Soft constraints (prefer natural materials, avoid cold tones, pet-friendly)
* Style vector (weighted blend across 12 aesthetic dimensions — NOT a single category label)
* Persona constraints (WFH ergonomics, child-safe clearances, accessibility needs)

Layer 4 — Design Generation

* Inputs: Spatial Relationship Graph + Constraint Object + mood vector + structured
  output schema
* LLM (Claude for reasoning, GPT-4V for perception) generates Design Specification JSON
* Contains: new furniture positions (x, y, z), material selections, color palette,
  lighting recommendations
* Every decision includes a reasoning trace — not just what changed, but why

Layer 5 — Rendering

* Design Specification JSON drives ALL visual output:
   * 3D scene construction in React Three Fiber
   * Shoppable furniture manifest
   * Room Health Score
   * Design DNA card
* The JSON is the contract between intelligence and interface

Full Feature Set (By Priority Tier)

Tier 1 — Non-Negotiable Core

Spatial Intelligence Pipeline — As described above. The product moat.

Conversational Refinement Loop

* Conversation IS the primary UI after the reveal, not a side panel
* Every message mutates the Design Specification JSON incrementally
* AI holds full context: room graph, all versions, stated constraints, inferred preferences
* AI initiates conversation proactively: "You haven't changed the bookshelf in three
  redesigns — want me to lock it and optimize around it?"
* Streaming responses via SSE, UI updates incrementally as the AI reasons

The Cinematic Reveal (most important UI moment — deserves its own engineering sprint)

* Choreographed sequence (frame-perfect, using Theatre.js):
   * 0ms: ambient room-tone sound fades in at 8% volume
   * 0–800ms: AI analysis annotations appear on original photo (stagger: 120ms per annotation)
   * 800ms: annotations fade out simultaneously
   * 1000ms: transformation sound begins (low architectural chord, not a swoosh)
   * 1000–3000ms: 3D scene morphs — furniture moves first (FLIP in 3D), materials
     dissolve, lighting shifts last
   * 3000–4000ms: room holds. No UI. Silence. Let the moment breathe.
   * 4000ms: conversational interface fades in
   * 4200ms: AI sends first proactive message
* This reveal is the marketing asset, the demo hook, the viral moment

3D Room Engine

* React Three Fiber + Drei + Theatre.js
* PBR materials throughout (not flat shading)
* PCSS soft shadows
* First-person walkthrough (WASD + mouse, touch drag on mobile)
* Third-person orbit with smart camera (avoids clipping)
* Individual furniture selection and repositioning with real-time AI feedback
* Dynamic lighting responding to time-of-day and user adjustment
* Source quality GLTF furniture models (Poly Pizza CC0 library + TripoSR/Shap-E generation)

Version History with Branching

* Every design state saved as a node in a DAG (directed acyclic graph)
* Film strip UI: thumbnail previews with scrubber (not a sidebar list)
* Branch from any version, explore two directions simultaneously
* Side-by-side branch comparison view
* This is "Git for your room" — explain it that way

Tier 2 — High Impact (Raise-Worthy Features)

Lighting Sculptor

* Hemisphere sky dome with draggable sun position
* Real-time shadow recalculation as sun moves
* Geographic + time-of-day presets using user's actual location
* Pull sun position via sun-calc library for "right now in your city" accuracy
* Artificial light source editor: add/remove/reposition, color temperature, intensity
* "Day Cycle" playback: 24-hour light simulation in 10 seconds

Room Health System

* Five dimensions, each with explanation:
   * Light Quality (distribution, natural vs. artificial ratio)
   * Flow (traffic path analysis, clearance measurements, bottlenecks)
   * Proportion (furniture scale vs. room dimensions, ceiling relationships)
   * Thermal Comfort (inferred from window placement, materials, orientation)
   * Psychological Comfort (enclosure ratio, sight lines, natural elements)
* Radar chart visualization (not progress bars)
* Animated before/after comparison
* Drillable: click any dimension for full AI explanation

The Taste Graph

* Built after 2+ redesign sessions
* Multi-dimensional aesthetic vector (not demographic data):
   * Warm/cool temperature preference (0–100)
   * Natural ←→ synthetic material preference
   * Minimal ←→ maximal density preference
   * Structured ←→ organic formality preference
   * Muted ←→ vibrant color saturation preference
   * Low ←→ high furniture vertical preference
* Hexagonal radar chart visualization
* Evolves over sessions, surfaces insights proactively
* Stored as vector embeddings (pgvector)
* This is the data asset with long-term business value

Design DNA Card

* Shareable generative visual artifact (not a screenshot)
* Renders: dominant colors as broad strokes, material textures, mood label in
  variable-weight typography
* Unique generative background per user, consistent with their aesthetic
* Organic growth / social sharing engine

Budget-Aware Shopping Layer

* Every redesigned room → Shoppable Manifest
* Three tiers per item: Dream / Realistic / Thrift
* "What I Already Own" filter — reconfigures recommendations around existing pieces
* Affiliate revenue: 4–8% on purchases (primary monetization surface)
* Why this piece: one-sentence explanation per item
* Compatibility score with rest of room

Tier 3 — Differentiation Layer (Unforgettable)

Environmental Context Engine

* On session start: pull user's geolocation + current time + weather
* Set initial 3D room lighting to match actual current conditions
* Adjust design recommendations based on climate/season/orientation
* "Right now in your room" simulation as the starting state
* ~2 hours to implement, creates "how did it know that" moment every time

Emotional Reaction Layer

* After every reveal: replace star rating with a 3×3 face grid
* Options: Calm / Excited / Inspired / Cozy / Sophisticated / Playful / Focused /
  Romantic / Uncomfortable
* Map reactions over time
* When first "Excited" response detected: "This is the first design that excited you.
  Here's what's different." Feed into taste graph.
* Makes users feel seen by software — rarest feeling in consumer tech

Style Collision Mode

* Entry point: pick two contradictory aesthetics
* AI synthesizes (not compromises) them, explains the resolution architecturally
* Inherently shareable ("look what it did with my impossible combination")
* Demos beautifully, forces genuine AI reasoning

Ambient Mode

* Full-screen room that cycles through 24 hours of real-time lighting
* Subtle ambient sound
* Designed for iPad on a shelf — "your room as living art"
* Signals product sophistication far beyond demo-builder thinking

Collaborative Design Mode

* Two users, same room design session, simultaneously
* Cursors visible, changes merge in real time
* CRDT-based conflict resolution (not last-write-wins)
* Use case: couples, roommates, designer-client pairs
* B2B wedge: interior designers working with clients
* Requires: WebSocket layer + CRDT implementation (both strong engineering stories)

Tier 4 — Foundation for Future Moat (Build now, surface later)

Room Graph Database — anonymized spatial graphs stored at scale → proprietary training
dataset → model fine-tuning → compounding accuracy advantage

Designer API — REST API for interior design studios: room image in, Room Perception
JSON + Design Specification JSON out. B2B revenue stream.

LiDAR Integration — iOS companion app using iPhone Pro/iPad Pro LiDAR for precise point
cloud → exact spatial graph (no estimation). Distribution story: "Works best with
RoomMind iOS scanner."

Features Explicitly Deprioritized (Do Not Revisit Unless Circumstances Change)

* AR room overlay via phone camera — finicky, awkward UX, 6+ month distraction
* Social feed of other people's rooms — requires moderation, content policy, kills
  launch timeline
* Photorealistic image generation (SD/DALL-E output) — everyone does it, feels generic
  at 30 seconds, 3D WebGL render is more technically impressive
* Full e-commerce marketplace integration — affiliate links yes, building a store no
* Multi-room floor plan design — stay focused on one room done extraordinarily
* Voice input — novelty without utility, text conversation is more precise
* Mobile-first architecture — desktop-first, best features don't translate to mobile
  constraints

UX Flow (Complete)

Act 1 — The Arrival (Landing Page)

* Full-screen WebGL room that responds to cursor movement
* Cursor is a soft light source — color bleeds into the room wherever the mouse moves
* The room is desaturated by default, color only exists where the user looks
* Single line of copy: "Your room has a version of itself you've never seen."
* One button: "Show me"
* No nav, no features list, no pricing
* Scroll: room transforms through 3 aesthetics via shader-based dissolve
* Bottom: real-time counter "2,847 rooms reimagined this week"
* Philosophy section — 3 sentences only: "Most rooms are shaped by what was available,
  not by what you wanted. Most design tools show you other people's rooms. RoomMind
  shows you yours."

Act 2 — The Feeling (Mood Selection)

* Full-screen mood gallery, 10 moods
* Slowly panning cinematic room photography + ambient audio (opt-in)
* Labels are emotional/poetic, NOT categorical:
   * "Sunday morning slow"
   * "Tokyo studio, 11pm"
   * "The cabin you keep meaning to rent"
   * "Grown-up finally"
   * "Creative chaos, intentional"
   * "After the renovation in the film"
   * (+ 4 more)
* User selects 1–2 moods
* UI palette immediately adapts to selection — product begins personalizing before upload

Act 3 — The Introduction (Context Gathering)

* One text input, conversational, no form fields
* AI prompt: "Tell me about this room. What's it for? What do you love about it, even
  if it's just one thing? What frustrates you?"
* AI reads free text, extracts intent/constraints/personality
* Response acknowledges specifically what they said

Act 4 — The Upload

* Appears AFTER relationship is established
* Entire screen is the drag-and-drop target
* Accepts multiple angles
* Fallback: "No photo? Describe the dimensions and I'll work from imagination."

Act 5 — The Analysis (8-second moment)

* Photo appears centered
* AI annotations overlay in real time as pipeline runs: boxes around objects, glow on
  windows, dotted traffic path
* Typed message: "I see a north-facing room. Your sofa is competing with your desk for
  the best light. Let's fix that."
* Then: the reveal

Act 6 — The Reveal (see Tier 1 above for exact choreography)

Act 7 — The Conversation (Refinement)

* Floating conversational panel
* Room is the canvas, conversation is the tool
* Every change animated (FLIP in 3D)
* AI explains each decision
* Room Health Score updates in real time
* Branch versions, walkthrough, lighting sculptor all accessible

Act 8 — The Identity (Takeaway)

* After 2+ redesigns: Design DNA card generated
* Shareable, beautiful, generative visual
* User's aesthetic fingerprint as a designed artifact

Motion Design System

The Spring System

* All transitions: custom damped spring — tension 180, friction 24
* Feels physically weighted and real, not bouncy or linear
* Applied universally — every element that moves uses this spring

Micro-interaction Library

* Buttons: scale 1.0 → 1.02 on hover, 1.02 → 0.98 on click
* AI thinking state: very subtle ambient occlusion pulse on the room (breathing)
* Loading: furniture fades in piece by piece, not a spinner
* Errors: single gentle shake on affected element (not red, not alarming)
* Success: brief warm light pulse across the scene

Typography in Motion

* Variable font weight responds to emotional intensity
* Lighter during exploration, heavier during key reveals
* Copy adapts voice to chosen aesthetic (haiku-sparse for minimalist, effusive for
  maximalist)

Visual Identity System

The Adaptive Palette

* No fixed color scheme — UI adapts to user's chosen mood
* Each mood has a 5-color seed palette
* Entire UI (backgrounds, buttons, typography, gradients) derives from seed via
  calculated relationships
* The product wears the user's aesthetic

Typography

* Variable serif for atmospheric copy (Fraunces or Playfair Display Variable — weight
  100–900)
* Geometric mono for data/scores/coordinates/AI reasoning (DM Mono)
* Never mixed in the same sentence
* Serif = feeling. Mono = thinking.

Sound Design

* Optional, opt-in, 10% volume default
* Ambient room sounds matching chosen aesthetic
* Transformation sound on reveal (low architectural chord)
* Barely-audible tactile UI sounds
* 5% of engineering effort, 30% of perceived quality

Tech Stack (Decided)

Frontend: Next.js 14 (App Router) + React Three Fiber + Framer Motion + Tailwind with
custom design token system

3D Engine: React Three Fiber + Drei + Leva (dev) + Theatre.js (reveal choreography —
keyframe control over 3D scenes)

AI Pipeline: Python FastAPI microservice

* GPT-4V for perception layer
* Claude (Anthropic) for design reasoning and conversation (better
  instruction-following, longer context)
* Custom orchestration managing all five pipeline layers
* SSE streaming to frontend

Spatial Processing:

* SAM2 (Meta) for segmentation
* Depth Anything V2 for monocular depth estimation
* Both running on Modal or RunPod (serverless GPU)

Database: PostgreSQL via Supabase + pgvector (taste graph embeddings) + Redis (session
state + streaming)

Auth/Storage: Supabase (auth + real-time subscriptions for collaborative mode + image
storage)

3D Assets: Poly Pizza (CC0 GLTF models) + TripoSR/Shap-E for generation + normalized
asset library indexed by type/style/dimension

Deployment: Vercel (frontend) + Modal (AI pipeline, pay-per-inference) + Supabase
(database)

* Scales 0 → 100,000 users without architectural changes
* ~$50/month at low traffic

Monetization Architecture

Freemium

* 3 redesigns free
* 1 version history slot
* Basic 3D orbit view
* Standard recommendations

Pro — $18/month

* Unlimited redesigns
* Full version history + branching
* First-person walkthrough
* Lighting sculptor
* Collaborative mode
* Full shoppable manifest (all budget tiers)
* Design DNA card + taste graph
* Priority AI processing

Studio — $79/month

* Everything in Pro
* Designer API (10,000 calls/month)
* White-label room preview links
* Multiple room projects
* Client collaboration seats
* Export to PDF/presentation

Affiliate Revenue

* 4–8% on furniture purchases
* Exceeds subscription revenue at scale
* Personalized recommendations → 3–5x industry-average conversion

B2B Pitch / Series A Story

* Interior design studios spend $200–500/client on initial visualization
* RoomMind Studio at $79/month = unlimited concepts
* Story: "Started consumer, discovered 23% of Pro users were professional designers,
  built for them, now 40% of revenue is B2B"

Build Sequence (Month-by-Month Roadmap)

Month 1: Five-layer AI pipeline (backend only, no UI). Test end-to-end with curl. Room
Perception JSON and Design Specification JSON must be perfect before any visual work
begins.

Month 2: 3D room engine. Scene construction from Design Specification JSON. Furniture
placement, PBR materials, basic lighting, orbit controls. Hardest technical piece — do
it before building around it.

Month 3: Cinematic reveal animation (Theatre.js choreography) + conversational
interface with streaming AI responses + incremental room mutation as conversation
evolves.

Month 4: Landing page + onboarding flow. Mood selection experience. Adaptive palette
system. Environmental context engine.

Month 5: Taste graph + Design DNA card + Room Health System + version history with DAG
branching. Full product loop closed.

Month 6: Collaborative mode + lighting sculptor + shopping layer + mobile
responsiveness. Polish every interaction to production quality. 50-user beta test. Fix
everything they break.

Month 7: Launch. ProductHunt. Design Twitter. Interior design communities. Measure.
Iterate.

Portfolio Presentation Strategy

The Case Study — 2,000-word document:
Problem → Insight → Architecture → Key Decisions → What I'd Do Differently → Results
Include: five-layer stack diagram, spatial relationship graph visualization, reveal
choreography timing diagram, real user quotes, metrics (sessions/user,
redesigns/session, DNA card share rate)

The Architecture Walkthrough Video — 6-minute screen recording walking through the
code, not the UI. Show the Room Perception JSON being constructed, the Spatial Graph,
the Design Specification driving the 3D scene. Share on Twitter/LinkedIn for
engineering attention.

The Live Demo Protocol — Always try to use the viewer's own room photo. Their emotional
investment shifts completely the moment it's their actual space. Keep a backup
beautifully staged photo that demos perfectly.

The "Making Of" Thread — 15-tweet technical thread on the hardest problem solved
(probably spatial graph or FLIP animation in 3D). Engineers share things they learned.
Drives GitHub stars = social proof for technical recruiters.

Key Engineering Stories (For Interviews)

1. "I built a semantic spatial graph that lets the AI reason about furniture
   relationships, not just pixels — each node is an object, each edge is a spatial
   relationship with type and weight."
2. "The reveal animation is a frame-perfect choreographed sequence using Theatre.js —
   FLIP animation in 3D space so furniture physically moves to its new position rather
   than snapping."
3. "I built a lighting simulation using the user's real geolocation and sun-calc to
   render accurate shadow positions for their actual current moment in time."
4. "The app builds a persistent taste graph across sessions using vector embeddings —
   it shows users their aesthetic fingerprint and how it evolves, which also powers the
   affiliate recommendation engine."
5. "I implemented streaming AI with optimistic UI — the room builds piece by piece as
   the model decides each element, with rollback if the user's manual changes conflict
   with AI reasoning."
6. "The entire landing page is a live WebGL experience — the cursor is a light source
   that bleeds color into a desaturated room, which IS the product demo before a single
   word is read."
7. "Version history is a DAG, not a linear stack — users can branch from any point and
   compare directions side-by-side, exactly like Git but for spatial design."

What Has Been Explicitly Decided — Do Not Re-litigate

* Building for real users and raise potential, not just portfolio
* Desktop-first (mobile responsive, but never mobile-first)
* 3D WebGL render over photorealistic image generation
* Conversational UI as primary post-reveal interface (not a side panel)
* Five-layer pipeline as non-negotiable architectural foundation
* No AR overlay, no social feed, no floor plan editor, no voice input
* Theatre.js for reveal choreography specifically
* Claude for reasoning, GPT-4V for perception
* Supabase + pgvector + Redis + Modal as the data/infra stack
* Adaptive palette system (UI wears the user's chosen aesthetic)
* Variable serif (Fraunces/Playfair) + geometric mono (DM Mono) as the type system
* Version history as a DAG with film strip UI
