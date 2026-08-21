# The social layer

**Status:** design. Nothing here is built.

The operator ruled the social layer a **commitment** on 2026-08-12, explicitly
declining to split it into some-commitment / some-direction. It is therefore
not in CLAUDE.md's direction-not-commitments list beside the taste graph and
budget-aware shopping. It is one of the three layers the thesis names, and it
had never been designed. This document is that design.

It answers four questions — what sharing shares, what comparison means between
two people, what evolution over time is as a surface, and what the smallest
first increment is — and it names what the layer refuses to be.

Every claim about what exists cites the file, decision, or policy section it
comes from. Where a call is the operator's rather than this document's, it is
listed in the last section as an open ruling and designed around rather than
decided.

---

## 1. The invariant: no room arrives unasked

The founding draft cuts the social feed outright — "Social feed of other
people's rooms — requires moderation, content policy, kills launch timeline"
(`docs/product/initial-idea-draft.md:266`), repeated in its do-not-relitigate
list at line 553, carried forward as still-sound in decision 0055, and restated
in the website brief's excluded-forever list
(`docs/product/website-design-brief.md:302`). The operator has ruled the social
*layer* a commitment. Both are true, and the reason they do not collide has
never been written down. It is this:

> **A feed is a place where rooms arrive without being asked for.** It needs
> moderation because it hosts content addressed to no one. Every artifact in
> this layer is *addressed* — a person makes it and hands it to someone, or
> keeps it themselves. Nothing here can put a stranger's home in front of you.

That is the test, and it is structural rather than promissory: **if a stranger's
room can reach a person who did not ask for it, the thing that did it is a feed
and does not ship.** No surface designed below can do it, and the reason is that
none of them has a listing, a ranking, a recommendation, or a browse — not
because those are disallowed by policy, but because no route exists that would
return a room the caller does not already have a link to.

The product already says this out loud on its own marketing surface. The share
card's alternate tagline, kept in the source at `docs/product/og-card.html`,
reads: *"No photos generated. No feed. Your rooms are yours."* The website brief
gets closest to the positive form at line 305 — **"Sharing is intimate, not a
feed."** This document is that sentence with a specification under it.

The distinction matters beyond taste. A feed obliges us to run a moderation
function, adopt a content policy, and adjudicate other people's homes. The
layer designed here obliges us to run none of those, and §9 records the one
place where a small moderation surface could reappear by accident.

---

## 2. What a room is made of

Sharing decisions are only as good as the reader's picture of what a room
actually is on disk. A ready scene is three artifacts, produced by different
stages and stored as separate blobs:

| Artifact | Produced by | Contents | Size |
|---|---|---|---|
| `shell.json` | `/shell` (`shell_receiver.py`, v3) | Floor polygon, wall quads with measured and rendered geometry, heights, door and window openings, per-surface measured albedo and a confidence-gated material family | kilobytes |
| `manifest.json` | `/process` (`fusion.py`, manifest_version 2) | The fused object array: one entry per physical object with label, world transform, RoomPlan box extents, confidence, and — where the measurement concentrates — a `color` block (0184) | tens of kilobytes |
| `*.ply` / `*.spz` | `/process`, `/compress` | The per-object Gaussian splats. One splat is a photographically derived likeness of one of the person's possessions | hundreds of megabytes; ~5.8× smaller in the SPZ tier (0126) |

Two derived layers sit above them and are equally real:

- **`SceneFacts`** (`services/api-public/scene_facts.py`, FACTS_VERSION 3) —
  the guest's entire world, derived from the manifest: inventory with
  confidence tiers, pairwise centre distances, measured sizes from RoomPlan
  boxes, clearances as rigorous lower bounds, colour words. Text, never
  geometry: "no quaternions, no float triples, nothing the model could do 3D
  arithmetic on."
- **The conversation** — turns held in Firestore, keyed by scene, deleted with
  the room (Privacy Policy §6).

What a room does *not* contain is as important. The manifest references no
photograph. The raw capture — "a few hundred JPEG images" of the home, in the
Privacy Policy's own words — lives in the captures bucket under a 24-hour
lifecycle rule and is referenced by nothing the serving path signs.
`get_scene_assets` signs exactly the placed objects' splats plus nothing else
(`services/api-public/public_server.py:1365`, and the placed-only filter is
0124). **No sharing design below can leak an original photograph, because no
route can produce one.**

### The seam this layer cuts on

The shell and the objects are already separate files, written by separate
stages, and separately optional to a client — the assets route treats a missing
or unreachable shell as a degrade to null rather than an error
(`public_server.py:1365`), and a shell with zero objects already plays a
correct, shorter reveal with no special-casing, because `planReveal`'s
`nothingToPlay` requires both to be empty (0122).

That seam is not a privacy abstraction invented here. **It has already been cut
once, in production, for exactly this reason.** Decision 0122 put a real
captured home on the public landing page by shipping its `shell.json` verbatim
with an empty object array — `web/public/hero/room.json`, 3,557 bytes against
roughly 460 MB for the same scene's full splat set. Its stated reasoning is the
foundation of everything in §3:

> "It dissolves the privacy question rather than managing it. With no splats
> there are no possessions on a public origin — a floor polygon, wall heights,
> four measured colours and a window opening."

---

## 3. Sharing: what leaves, and what stays

### 3.1 Sharing is a ladder, and the rungs already exist

There is no single answer to "what does sharing a room share," because a room
discloses in layers and the layers are the pipeline's own artifacts. The design
is a ladder with four rungs. A person picks a rung; the product never picks a
higher one for them.

**Rung 0 — the card.** A generated artifact carrying the room's measured
contour and a line or two of its derived facts. No object data of any kind.
Kilobytes, and it is an image rather than a scene. This is §6's first
increment.

**Rung 1 — the shell.** The room's envelope: floor polygon, wall heights,
openings, measured surface colours. This is the hero rung — a *room* without
*your things*, and the only rung with a shipped precedent (0122).

**Rung 2 — shell plus inventory.** Rung 1 with the derived fact set as text:
what was found, how many, how big, what colour. The guest's world without the
pixels. A viewer learns you own a bed, a desk and two chairs; they see none of
them.

**Rung 3 — the room.** The splats. Your actual possessions, photographically
derived, at hundreds of megabytes.

The ladder is the answer to "what does sharing a room actually share": **it
shares whichever of four already-separable artifacts the person chose, and the
default is the lowest.**

### 3.2 What a viewer can reconstruct, rung by rung

This is a specification, not a principle. The Privacy Policy's standard is
plainness "with the uncomfortable parts included," and this section is held to
it.

**At rung 0 and rung 1, a viewer can reconstruct:** the shape and dimensions of
one room of a home, its ceiling height, where its windows and doors are, and
the measured colour of its walls and floor.

That is not nothing, and it should not be described as nothing. A floor plan
with true dimensions is identifying in combination with knowledge the viewer
may already have — someone who knows which building you live in may be able to
tell which unit. What it does not carry is any possession, any person, any
photograph, any text you wrote, or any location: **a capture contains no GPS
and the app never requests location permission** (Privacy Policy §3), so
nothing in the shell says where on earth the room is. The camera poses inside a
capture are relative to wherever the scan started, and they are not in the
shell at all.

**At rung 2, additionally:** an inventory of your furniture with measured sizes
and colours. This is a meaningful step up. "A bed, a desk, two chairs, a
wardrobe" is a description of how someone lives.

**At rung 3, additionally:** likenesses of the objects themselves, derived from
photographs of your home. A splat is not a photograph, and it is materially
less than one — it is truncated, often missing legs, bases and backs (CLAUDE.md's
open class-6 defect), and it carries only the surfaces the camera saw. But it is
photographically derived, it is recognisable, and anything visible on a surface
when you scanned is in it. **Rung 3 is the rung where a shared room contains
your property, and it should be described to the person in those words.**

### 3.3 The eligibility rule, which is not optional

Decision 0089 made `person` a suppression-only concept: detected, then excluded
from every downstream consumer — never reconstructed, never placed, never
inventoried, never written into the manifest, and never used as surface
evidence (`services/perception-obj/privacy.py`).

**Suppression is not retroactive.** A scene segmented before 0089 shipped was
never asked about people, so its zero person-detections prove nothing, and its
measured wall albedo may literally be a person standing in front of that wall
— which is the shipped defect 0089 was written to fix, on `f3d70236`'s
`wall_03`. The Privacy Policy already says this to users in §8: "Rooms
processed before this behaviour shipped may still carry measurements taken from
a person."

0122 turned that into an eligibility rule for the one room it made public, and
it cost real ground: the rule disqualified the best-looking contour in the
inventory. **That rule generalises, and it is load-bearing for every rung:**

> A room is eligible to leave the owner's account only if every frame of its
> scene was segmented on a suppression-armed revision. A pre-0089 scene must be
> re-driven before it can be shared, and a warm re-drive does not re-segment
> (0122's own trigger note) — so this is a real re-processing cost, not a flag.

Note the shape of the exposure: this rule matters *most* at rungs 0 and 1,
where intuition says the risk is lowest. A person contaminates a wall's
measured albedo, and the shell is exactly what rungs 0 and 1 ship.

**The rule is not currently checkable from a room's own data.** The manifest
records no suppression provenance — `process_receiver.py`'s manifest dict
carries `scene_id`, versions, frame counts, `sampling`, `objects` and `frames`,
and nothing that says whether this scene's frames were ever asked about people.
Suppression is logged per frame and stored as a `suppressed` union inside
`masks.npz`, neither of which the serving path reads. 0122 established the
hero's eligibility by hand instead, comparing the scene's segmentation and bake
timestamps against a revision's deploy time.

A manual forensic check is adequate for one curated fixture and inadequate for a
feature every person can invoke, so a share path needs one of two things:

- **A conservative date gate**, available today with no pipeline change: a scene
  whose `created_at` is later than the deploy of the first suppression-armed
  revision was necessarily segmented with suppression armed, because it had no
  frame cache of its own to inherit pre-0089 masks from. It is one-directional —
  it will refuse some eligible older rooms that were re-driven cold — and
  refusing an eligible room is the safe error.
- **A suppression provenance field on the manifest**, which is the durable fix
  and makes the gate exact rather than conservative.

Either is a dependency of the first increment; neither is optional.

### 3.4 What the Terms already permit, and what they do not

The content licence in Terms §5 is deliberately narrow: permission to store,
process, send the §5a material crops, build, host, "and show it back to you.
You grant us a worldwide, royalty-free licence to do exactly that **and nothing
more**." The same section adds: "We will not use your rooms in marketing,
publish them, or show them to anyone else **without asking you first**."

Two consequences bind the whole design:

1. **Every act of sharing must be initiated by the person, per room, per
   instance.** Nothing may be shared by default, in aggregate, or as a
   consequence of some other action. The Terms as shipped already forbid it.
2. **Hosting a shared room for a third party is outside the current licence.**
   The licence covers showing the room *to you*. A hosted share link shows it to
   someone else, which is a grant the Terms do not yet carry. Rung 2 and rung 3
   need a Terms and Privacy Policy amendment in the same commit as the feature —
   which is the convention the Privacy Policy's own header already states for
   any change to what leaves.

Rung 0 as designed in §6 needs neither, because nothing leaves our systems: the
artifact is generated in the person's browser from data their browser already
holds, and they carry it away themselves.

Terms §4 covers the other half of consent — "Only scan a space you own, occupy,
or have permission to scan… If a person will be in frame, get their agreement
first." That obligation was written for capture. Sharing widens its
consequences, and §9's copy obligation follows from it.

---

## 4. Comparison

### 4.1 The draft's comparisons are a room against itself

The founding draft names comparison twice — "Side-by-side branch comparison
view" (line 150) and "Animated before/after comparison" (line 173). Both compare
a room to *itself*: two branches of one design, or one room before and after a
change. Neither is comparison between two people. The thesis names that
("share, compare, and evolve", line 54) and nothing in the draft defines it.

### 4.2 Comparison between two people is not a surface

Consider what a comparison surface between two people's homes would actually
do. Rooms differ by budget far more than by taste. A view that puts your room
beside a stranger's, on any axis the product can measure — size, light,
proportion, how much of the floor is clear — is a view that tells some people
their home is worse. The Room Health System (draft lines 164–174) is a fine
instrument pointed at your own room and a cruel one pointed across a gap in
income.

It also contradicts the product's own landing copy, which the founding draft
fixes at lines 288–290: *"Most rooms are shaped by what was available, not by
what you wanted. Most design tools show you other people's rooms. [This] shows
you yours."* A comparison surface is the thing that sentence sells against.

**So comparison between two people is not a surface. It is an input to the AI
layer.** The useful content of "other people's rooms" is evidence — rooms
shaped like yours, and what worked in them — and evidence belongs inside the
reasoning, surfacing as a sentence the guest can say with a trace behind it,
not as a rendering of someone's home. The founding draft already has the
substrate in Tier 4: "Room Graph Database — anonymized spatial graphs stored at
scale" (line 253).

Two rules make that safe to build later, and it is not designed further here:

- **It never renders.** Evidence may inform a claim; another person's room is
  never drawn, listed, linked, or named.
- **It is aggregate or it does not exist.** A claim traceable to one other room
  is that room being shown to you with extra steps.

There is a live obstacle, recorded here because it will otherwise be discovered
late. **Aggregate evidence conflicts with the deletion promise as written.**
Privacy Policy §7 says deleting your account removes "every room and everything
built from it," and account deletion is implemented as exactly that
(`account_deletion.py`, decision 0095). An anonymised spatial graph retained in
an aggregate that survives deletion is *something built from your room that
outlives it*. Building this requires either a disclosed carve-out in §7 written
before any retention begins, or not building it. The carve-out is the operator's
call (§10, ruling 5); this document's recommendation is to leave it unbuilt
until the product has enough rooms for aggregation to mean anything, at which
point the disclosure can be written honestly rather than speculatively.

### 4.3 What comparison does mean, concretely

Comparison in this layer is **a room against itself over time**, which is §5,
and that is the form the draft's own two examples already take.

---

## 5. Evolution over time

### 5.1 The hole at the bottom

**Nothing in the system links two scans of the same physical room.** The `Scene`
model (`packages/api-core/roomstudio_api_core/scene.py`) carries `scene_id`,
`device_id`, `status`, `bundle_uri`, timestamps, `result_uri`, `attempt_count`,
`last_error`, `expire_at` — and no field that would relate one capture to
another. None of the nine routes on api-public would set one. The only
cross-capture linkages that exist are `user_id` (same account) and `device_id`
(same phone), and neither says *same room*.

So a person who rearranges their bedroom and scans it again gets a second,
unrelated room. The web app titles both from their creation date —
`roomTitle()` in `web/src/lib/voice.ts` returns "the August 21 room" — so the
product has a time axis it is not using and no identity axis at all.

### 5.2 Evolution is a lineage, and it does not need the DAG

The draft's version history is a DAG of *design versions* — branches of a
proposal, "Git for your room" (lines 145–151) — and CLAUDE.md lists it as
direction, not commitment. Evolution over time is a different axis: **the same
physical room, re-measured.** The draft conflates them; they should not be.

A lineage is an ordered chain of captures a person has asserted are the same
room. It is a linked list, not a DAG, and it leaves the DAG exactly where
CLAUDE.md has it.

**The person asserts the linkage.** Not geometry matching: this repo has
expensive experience with instruments that were never validated, and a floor
polygon similarity score is a new instrument that would sometimes silently
merge two rooms of a person's home. Asking is cheap, correct, and reversible.

### 5.3 The unit of comparison is measurement

What a lineage shows is a **diff of measurements**, drawn from facts the
pipeline already derives: the ceiling is the same 2.99 m; the bed moved; there
is one more chair than there was; the wall that measured warm grey now measures
warmer. All of that comes from `SceneFacts` and `shell.json`, both already
built.

This matters because a measured diff is honest in a way an aesthetic diff is
not. The product can defend "the bed is 1.4 m from where it was" against a
RoomPlan box; it cannot defend "this arrangement is better," and the guest's
charter already forbids claiming what it cannot ground — "you cannot see it —
say so plainly rather than guessing" (`services/api-public/guest_prompt.py`).

### 5.4 What a lineage costs

It needs a room to have an identity a person can point at, which means **room
naming** — the missing primitive the website brief already flags in passing
("a derived title… until real naming ships",
`docs/product/website-design-brief.md:156`). Naming carries a consequence that
belongs in this document rather than in a build charter, and §9 states it.

---

## 6. The first increment: the calling card

**The smallest thing that is genuinely social and genuinely shippable is an
artifact, not a link.**

A person generates a card for one of their rooms. It carries the room's
measured floor contour, the room's derived title, and one or two of its facts.
It is rendered in the browser from data the room page has already fetched, and
the person downloads it and sends it however they send things.

### 6.1 Why this is the first increment

**It needs no new trust boundary.** Every scene route on api-public refuses a
request for a room the caller does not own, and the Privacy Policy states that
to users: "Rooms are scoped to the account that made them, and a request for
someone else's room is refused rather than filtered." A hosted share link is a
new unauthenticated read path — a genuinely new trust boundary on the
client-facing service. The card adds none: the browser already has the manifest
and shell for a room the person owns, and the card is a pure function of them.

**It needs no new storage, no new licence, and no new policy.** Nothing leaves
our systems, so Terms §5's "and nothing more" is not strained, and there is
nothing to retain, expire, revoke or delete.

**Sharing without a server is sharing without a moderation surface.** §1's
invariant is satisfied structurally rather than by promise: there is no route
that could serve a stranger's room, because there is no route at all.

**The project has already proved it can do this.** `docs/product/og-card.html`
renders a designed 1200×630 card whose floor plan *is* the hero room's measured
floor polygon — "all six wall lengths verified within 0.7% of the same scale,
the window drawn at its real 56–90% span of its wall, and '3.02 m' derived from
that wall's true length (3.0233 m)." The first increment is that, per room, in
the browser, for the person whose room it is.

**It is the draft's own Act 8**, reached honestly. The draft's Design DNA card
(line 193, Act 8 at lines 342–345) is "a shareable generative visual artifact
(not a screenshot)" — but it is an artifact of *taste*, generated after two or
more redesigns, and the taste graph is direction rather than commitment. What
the product can honestly make today is an artifact of *measurement*. The DNA
card is this card's later sibling and arrives with the taste graph; it is not
what ships first.

### 6.2 What it carries, and what it must not

Rung 0. The contour, the derived date title, and facts drawn from `SceneFacts`
— a dimension, a count, a measured colour.

It must not carry: any splat or object likeness; any user-authored text (§9);
any photograph; any identifier that resolves back to the account or scene. A
card is a picture of a measurement, and it should be legible as one to whoever
receives it.

### 6.3 Dependencies, stated honestly

- **The room page's data.** Already there — the room page fetches manifest and
  shell today via `/scenes/{id}/assets`.
- **The eligibility rule (§3.3), and a way to evaluate it.** A pre-0089 scene
  must not produce a card until it is re-driven, and the rule is not currently
  checkable from a room's own data — so the increment carries either the
  conservative `created_at` gate or the manifest provenance field. This is the
  one dependency that can require GPU work on an existing room, and it is the
  easiest to forget, because the card carries no splats and therefore looks
  unrelated to segmentation.
- **A rendering path to a raster.** The og-card is exported by headless Chrome
  from a hand-authored file; the card must render in the person's browser
  instead. That is the one genuinely new piece of engineering, and it is
  contained.
- **Nothing else.** No new route, no new trust boundary, no new storage, no
  licence or policy amendment. The eligibility gate above is the only question
  that reaches past the browser, and its cheaper form reaches only as far as a
  field the scene list already returns.

**The name is a design call, not a fixture.** "Calling card" sits in the Good
Guest register (0072) — the thing a guest leaves behind — and avoids colliding
with `web/src/components/RoomCard.tsx`, which is the room grid's tile. The
operator owns naming; this is a working name, offered so the increment can be
discussed without one.

---

## 7. The second increment, and what blocks it

The hosted share link — rung 1 or 2 at a URL — is the obvious next step and it
is **blocked on something that does not exist.**

> **Unshare is not a feature of sharing. It is a precondition.**

A person who shares a room must be able to stop sharing it, and today they
cannot stop *anything* at room granularity: account deletion is all-or-nothing
(`DELETE /account`, keyed on the token's own uid), there is no per-room delete
route among api-public's nine, and the Privacy Policy sends per-room requests
to a human — "To delete a single room rather than everything… write to
23singhutkarsh@gmail.com." CLAUDE.md already lists the gap as an open defect and
calls it conspicuous for a product whose thesis is that rooms are identity.

That gap is a mild embarrassment for a private product and a real defect for one
that shares. **Per-room deletion is therefore a hard prerequisite of the hosted
link, and the sequencing is not negotiable.** Revocation of a share and deletion
of a room are the same mechanism seen from two angles, and building the second
without the first would ship a share that outlives every means of stopping it.

The rest of the hosted link's dependencies, named so nobody rediscovers them:

- **A share token model** — an unguessable, revocable, per-room, per-instance
  grant, and a decision about expiry.
- **The first unauthenticated read path on api-public**, which today verifies a
  Firebase JWT on every route as its trust boundary (0016).
- **A preview image.** Link previews want one, and there is no thumbnail
  pipeline — `RoomCard.tsx` says so in its own docstring ("a placeholder hatch
  where the room's likeness will eventually render (no thumbnail pipeline
  yet)"). The card of §6 is the natural answer, which is a second reason to
  build it first.
- **A Terms §5 and Privacy Policy amendment in the same commit** (§3.4).
- **Signed-URL lifetime.** Object splats are signed for one hour
  (`public_server.py`); a share that outlives its URLs needs re-signing on
  demand, which is a design constraint on the route rather than an afterthought.

---

## 8. What this layer refuses to build

A design that only adds is not a design. These are refusals, not deferrals —
each would need new evidence to reopen, not merely a free week.

1. **A feed, a browse, a discovery surface, or any listing of rooms the viewer
   does not own.** §1. This is the draft's own cut (line 266), and the
   invariant that enforces it is that no such route exists.

2. **Comparison or scoring of one person's room against another's.** §4.2. It
   ranks homes, homes track income far more than taste, and it contradicts the
   landing page's own claim. The Room Health System stays pointed at your own
   room, across your own time.

3. **Profiles, followers, and a display identity.** The product holds no
   display name, no avatar, and no profile — verified: nothing in the web app
   reads `displayName` or `photoURL`, and Firebase anonymous auth "produces an
   opaque account identifier and nothing else — no email, no name, no profile"
   (Privacy Policy §3). Adding an identity layer *in order to* enable social is
   the tail wagging the dog. The room is the content; the person is not.

4. **Public-by-default anything.** Every rung is opt-in per room per instance,
   which Terms §5 already requires.

5. **Collaborative editing of a shared room.** The draft's Tier 3 collaborative
   mode (lines 242–249) is a different product surface with a different
   substrate (CRDTs, a WebSocket layer) and it is not what "rooms are identity"
   asks for. It stays direction.

---

## 9. Two consequences that will otherwise be discovered late

**Room naming introduces user-generated content, and content travels.** §5
needs naming; naming is free text a person authors. If a room's name travels
with a shared artifact, the product has acquired its first piece of
user-authored content shown to another person — which is a moderation surface,
which is the thing §1 exists to avoid. The resolution is narrow and costs
nothing: **a room's name is private, and does not travel.** Shared artifacts
carry the derived date title. A person who wants their own word on a card is
asking for a feature that reopens §1, and should be told so rather than quietly
given it.

**Sharing widens the consent Terms §4 collected.** A person agreed not to scan a
space without permission and to get agreement from anyone in frame. They agreed
to that for a capture that would be *shown back to them*. Sharing changes who
sees it, and the share flow's copy must say what is about to be visible and to
whom, in the Privacy Policy's plain register — particularly at rung 3, where
the answer is "your possessions." §3.2 is written to be the source for that
copy.

---

## 10. Rulings that are the operator's

Each carries this document's recommendation and its reasoning. They are open
questions, not decisions, and §§1–9 are designed so that either branch of each
remains buildable.

1. **Is any shared room reachable without a link — that is, is there ever a
   public surface?**
   *Recommendation: no.* Link-only and unlisted, at every rung. A public
   surface is a browse away from a feed, and §1's invariant is much easier to
   hold as an architectural fact than as a policy.

2. **Is a shared room a snapshot or does it stay live as the original
   changes?**
   *Recommendation: snapshot.* A live share means a room shared last year
   silently changes when the person rescans, which nobody consented to at the
   moment of sharing. Snapshots also match the lineage model in §5, where each
   capture is already a moment rather than a state.

3. **Does a shared room carry its conversation?**
   *Recommendation: never, at any rung.* The conversation is the most personal
   artifact in the system — a person talking about their home. It should not be
   an option that can be got wrong.

4. **Which rung is the default when a person shares?**
   *Recommendation: rung 0, the card.* It is the only rung that needs no new
   trust boundary, and defaults are where privacy is actually decided.

5. **Does anonymised aggregate evidence (§4.2) get a disclosed carve-out from
   the deletion promise, or is it refused?**
   *Recommendation: refuse for now, revisit when the corpus is large enough for
   aggregation to mean anything.* A carve-out written speculatively is a
   weakening of Privacy Policy §7 bought for a capability we cannot yet build.

6. **Is the first increment's artifact called the calling card?**
   *Recommendation: yes as a working name, settled when the product name lands.*
   Naming is the operator's, and the product's own name is still a placeholder.

---

## What would change this document

- **The product acquires a display identity** (a name, an avatar) for some other
  reason. §8's third refusal is contingent on the product not having one; if one
  arrives, the argument becomes a real trade-off rather than a foregone one.
- **Placement quality reaches a bar where a full room reads correctly to a
  stranger.** 0122's own reopening trigger. Rung 3 is designed here as the
  heaviest and most exposing rung; if rooms become genuinely presentable, its
  weight changes but its privacy specification (§3.2) does not.
- **Per-room deletion ships.** §7's blocker clears and the hosted link becomes
  the next increment rather than a blocked one.
- **The operator rules any of §10 against the recommendation.** Each is designed
  around, not designed on.
