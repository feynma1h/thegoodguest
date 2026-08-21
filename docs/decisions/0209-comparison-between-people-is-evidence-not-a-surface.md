# 0209 — comparison between people is evidence, not a surface

**Date:** 2026-08-21
**Status:** Decided

## Context

The thesis names comparison as one third of the social layer — "rooms are
identity. Users want to share, compare, and evolve their spaces over time"
(`docs/product/initial-idea-draft.md:54`). The draft then defines comparison
twice, and both definitions are a room against *itself*: "Side-by-side branch
comparison view" (line 150) compares two branches of one design, and "Animated
before/after comparison" (line 173) compares one room across a change.

Comparison between two *people's* rooms is named in the thesis and defined
nowhere. Designing the social layer meant deciding what it is before someone
built the obvious thing.

## What we tried

**The obvious thing: a comparison surface.** Two rooms side by side, or a score
placing yours against others — the Room Health System (draft lines 164–174)
pointed across accounts instead of across time. It has ready-made substrate: the
health dimensions exist as a design, and `SceneFacts` already derives measured
sizes, distances and clearances that would make the numbers easy.

**Comparison as an input to the AI layer.** The useful content of "other
people's rooms" is evidence — rooms shaped like yours, and what worked in them —
consumed inside the reasoning and surfaced as a claim the guest can make with a
trace behind it. The founding draft already carries the substrate in Tier 4:
"Room Graph Database — anonymized spatial graphs stored at scale" (line 253).

## What we chose

**Comparison between two people is not a surface. It is an input to reasoning,
and it is not built yet.**

The comparison surface is refused outright. Two rules bound the input form if it
is ever built:

- **It never renders.** Evidence may inform a claim; another person's room is
  never drawn, listed, linked, or named.
- **It is aggregate or it does not exist.** A claim traceable to one other room
  is that room being shown to you with extra steps.

Comparison in the shipped sense stays what the draft's own two examples already
are: **a room against itself over time**, which the social-layer design makes a
user-asserted lineage of captures diffed on measurement
(`docs/product/social-layer.md` §5).

## Why

**A comparison surface ranks homes, and homes track income far more than
taste.** Every axis the product can actually measure — floor area, ceiling
height, natural light, how much of the floor is clear — is closer to a proxy for
what someone can afford than for anything they chose. A view that places your
room against a stranger's on those axes tells some people their home is worse. A
health score is a useful instrument pointed at your own room and a cruel one
pointed across a gap in income.

**It contradicts the product's own landing copy.** The draft fixes the
philosophy section at lines 288–290: *"Most rooms are shaped by what was
available, not by what you wanted. Most design tools show you other people's
rooms. [This] shows you yours."* A comparison surface is precisely the thing
that sentence sells against. This is not a taste objection; it is the product
promising one thing on the first screen and doing the opposite on a later one.

**It fails 0207's test the moment it is useful.** A comparison surface that
shows you a stranger's room delivers a room you did not ask for. To be worth
building it must be discoverable, and discoverable comparison is a feed with a
scoreboard.

**The evidence form keeps everything valuable and discards the harm.** "Rooms
shaped like yours put the bed on the other wall" is the thesis working — it
makes a version of your home visible that you had not seen. It needs no other
person's room to be rendered, named, or ranked.

### The obstacle the input form has, recorded so it is not found late

**Aggregate evidence conflicts with the deletion promise as written.** Privacy
Policy §7 says deleting your account removes "every room and everything built
from it," and `account_deletion.py` (0095) implements exactly that. An
anonymised spatial graph retained in an aggregate that survives deletion *is*
something built from your room that outlives it. Building this needs either a
disclosed carve-out in §7, written before any retention begins, or not building
it. The recommendation on the operator's docket is to leave it unbuilt until the
corpus is large enough for aggregation to mean anything — a carve-out written
speculatively weakens a shipped promise to buy a capability we cannot yet
deliver.

## What would change this decision

- **A comparison form is found that is not a ranking.** The refusal is of
  ranking and of rendering, not of the word "comparison". A surface that shows
  two rooms without ordering them, and without either being a stranger's, is
  outside what this note refuses — the lineage of §5 is exactly that.
- **The corpus becomes large enough for aggregation to be meaningful**, at which
  point the §7 carve-out can be written honestly and the input form becomes
  buildable. That is a disclosure decision before it is an engineering one.
- **The landing copy changes.** The contradiction argument above is anchored to a
  claim the product makes on its first screen. If that claim goes, that argument
  goes with it — the income argument does not.
