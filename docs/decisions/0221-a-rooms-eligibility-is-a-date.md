# 0221 — a room's eligibility is a date, not a field

**Date:** 2026-08-22
**Status:** Decided

## Context

The calling card (`docs/product/social-layer.md` §6) is the first artifact a
person can make from a room and carry out of the product. Decision 0208
attaches a rule to every rung of the sharing ladder, and it binds hardest at
the bottom one:

> A room is eligible to leave the owner's account only if every frame of its
> scene was segmented on a suppression-armed revision.

`person` became a suppression-only concept in 0089, and suppression is not
retroactive. A scene segmented before it shipped was never asked about people,
so zero person-detections prove nothing about it, and its measured wall albedo
may be a person standing in front of that wall — the shipped defect on
`f3d70236`'s `wall_03`. The Privacy Policy says so to users in §8.

The exposure inverts intuition, which is why it needed deciding rather than
assuming. A card ships no splats and therefore looks unrelated to
segmentation; but a person contaminates a wall's measured **albedo**, and the
shell is exactly what the card draws.

The rule is not checkable from a room's own data. `process_receiver.py`'s
manifest carries `scene_id`, versions, frame counts, `sampling`, `objects` and
`frames` — nothing about whether the frames were ever asked about people — and
the per-frame `suppressed` union lives inside `masks.npz`, which the serving
path never reads. 0122 settled the landing hero by hand, comparing
segmentation and bake timestamps against a revision's deploy time. That is
adequate for one curated fixture and inadequate for a feature every person can
invoke.

## What we tried

0208 names two ways to close it, and this lane weighed both.

**A suppression provenance field on the manifest.** The durable fix: exact
rather than conservative, and it makes the answer a property of the room
rather than an inference about it.

**A conservative `created_at` gate.** A scene created after the first
suppression-armed revision deployed had no per-scene frame cache of its own to
inherit pre-0089 masks from, so it was necessarily segmented with suppression
armed. `created_at` is already in the client-facing scene shape
(`_scene_to_client_dict`), so the gate reaches no further than data the room
page has already fetched.

One more candidate was considered and rejected outright. `shell_observation.py`
carries `suppressed_texels` — "in-region texels a person covered in >=1 frame"
— and it reads like the answer. It is not: **0 is ambiguous** between "no
person was present" and "suppression never ran", which is precisely the
distinction the rule turns on.

## What we chose

The date gate, in `web/src/lib/card/eligibility.ts`, keyed on
`SUPPRESSION_ARMED_SINCE = 2026-08-07T21:27:53Z` — `perception-obj-00036-l9l`,
the revision that carried 0089, and the same revision and timestamp 0122 used
to adjudicate the hero by hand. Refusals are typed rather than boolean, so the
surface can say which thing went wrong; there is no branch that admits a room
on the absence of evidence, including a `created_at` it cannot parse.

## Why

**On day one the manifest field refuses strictly more rooms than the date
does, at a much higher cost.** A field is only true of scenes processed after
it ships, and absence is not proof — so every existing room would be refused,
including the ones created after `00036-l9l` that the date gate correctly
admits. The exact fix is *less* permissive than the conservative one until the
whole corpus is re-driven, and re-driving is GPU work rather than a flag
(0122's own trigger: a warm re-drive does not re-segment).

**The honest field is not a boolean, which makes the durable fix bigger than it
looks.** `PERCEPTION_SUPPRESSED_CONCEPTS` is env-configurable and defaults to
`person`, so `suppression_armed: true` would silently mean something different
after a second concept is added. The field that would actually settle it
carries the concept set, which is a manifest version question rather than one
line.

**Both errors are not equal, and only one is available.** The gate is
one-directional: it refuses eligible rooms — an older scene re-driven cold is
eligible and this still says no — and never admits an ineligible one.
Refusing a room a person owns costs them a card. The reverse ships a
measurement we cannot vouch for, out of the product, into someone else's
hands, permanently.

**The gate is a manufacturing rule, not an access boundary, so client-side is
its right home.** The shell is already in the browser — the room page fetched
it to render the room. Nothing about this gate withholds data; it decides
whether the product will turn a measurement it cannot stand behind into a
portable artifact. Putting it on the server would protect nothing that is not
already served, and would buy the card a new api-public route it does not
otherwise need.

**It is 0122's by-hand judgment made general**, rather than a new instrument.
The premise is auditable and is written into the constant: no revision serving
after `00036-l9l` lacks suppression.

## What would change this decision

- **A share rung above 0 ships.** A hosted link serves a room to a third party
  from our systems, and at that point the gate is enforcing a promise we made
  to someone who is not the caller. That is a server-side decision, and it
  wants the exact answer rather than the conservative one.
- **A person is refused a card for a room that was re-driven cold and is
  genuinely eligible.** The date gate cannot see that, and the complaint is
  legitimate. The manifest field is the fix; nothing else recovers those rooms.
- **A second suppression-only concept ships.** The eligibility boundary moves
  forward to that deploy and re-strands every room segmented before it (0208's
  own trigger). Bump `SUPPRESSION_ARMED_SINCE`; do not add a second constant.
- **perception-obj traffic is ever rolled back below `00036-l9l`.** That would
  be a privacy regression in its own right, and it would also invalidate the
  constant this gate rests on.
