# 0207 — a layer is not a feed

**Date:** 2026-08-21
**Status:** Decided

## Context

The founding draft cuts the social feed twice — in its deprioritized list
("Social feed of other people's rooms — requires moderation, content policy,
kills launch timeline", `docs/product/initial-idea-draft.md:266`) and again in
its do-not-relitigate list at line 553. Decision 0055 carried that cut forward
as still sound post-pivot, and the website brief repeats it in its
excluded-forever list (`docs/product/website-design-brief.md:302`).

On 2026-08-12 the operator ruled the social *layer* a commitment, declining the
option to split it. Both facts are load-bearing and they read as a contradiction
to anyone who has not been told the difference. Nothing in the repo stated it,
so "social layer" meant whatever the reader assumed — which is how a commitment
sat undesigned for nine days while being cited as a commitment.

## What we tried

Three ways of separating the two were weighed:

1. **By content** — a feed carries strangers' rooms, a layer carries your own.
   Fails immediately: sharing a room with someone means a stranger's room
   reaches a person, which is the whole point.
2. **By policy** — a feed is what we promise not to build. Fails for the reason
   this repo distrusts promises generally: it makes the property depend on
   nobody later shipping a browse, and gives a reviewer nothing to check.
3. **By addressing** — the distinction is whether the room was asked for.

## What we chose

(3), stated as an invariant with a checkable test:

> A feed is a place where rooms arrive **without being asked for**. It needs
> moderation because it hosts content addressed to no one. Every artifact in
> the social layer is addressed — a person makes it and hands it to someone, or
> keeps it themselves.
>
> **If a stranger's room can reach a person who did not ask for it, the thing
> that did it is a feed and does not ship.**

The enforcement is architectural, not editorial: no surface in the design has a
listing, a ranking, a recommendation, or a browse, because no route exists that
returns a room the caller does not already hold a link to. Every route on
api-public today refuses a request for a room the caller does not own
(`_load_owned_ready_scene` in `public_server.py`), and the Privacy Policy states
that to users as "a request for someone else's room is refused rather than
filtered." The invariant says that property survives the social layer rather
than being spent by it.

The full design is `docs/product/social-layer.md`.

## Why

**A policy is not a mechanism.** The moderation obligation a feed creates does
not arrive because we called something a feed; it arrives the moment a person
can see a room they did not ask for. Pinning the definition to that moment makes
the obligation predictable and makes any proposal checkable by one question,
which a taste-based definition ("is this feed-like?") never is.

**It converts an apparent contradiction into a design constraint.** The draft's
cut and the operator's ruling were never in conflict — but until the difference
was written down, every future session had to re-derive it, and re-derivation is
how a cut becomes a "well, sort of" three sessions later.

**It is the phrasing the project had already reached for and never finished.**
The website brief gets closest at line 305 — "Sharing is intimate, not a feed"
— and the share card's alternate tagline, kept in `docs/product/og-card.html`,
says "No photos generated. No feed. Your rooms are yours." Both are the right
instinct stated as a slogan. This is the same instinct stated as a test.

**It buys the product out of a whole function.** A feed obliges us to run
moderation, adopt a content policy, and adjudicate other people's homes. The
layer as designed obliges us to run none of those — which is worth defending
deliberately rather than losing to one convenient surface.

## What would change this decision

- **A surface is proposed that fails the test and is worth it anyway.** The test
  is a definition, not a prohibition on ever changing course; what it forbids is
  changing course by accident. Reopening it means arguing for the moderation
  function, not around it.
- **User-authored content enters a shared artifact.** Room naming is the live
  candidate (`docs/product/social-layer.md` §9): a name that travels with a
  shared artifact is the first user-authored content shown to another person,
  which is a moderation surface arriving through the side door. The design keeps
  names private for exactly this reason; reversing that reopens this note.
