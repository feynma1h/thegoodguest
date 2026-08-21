# 0208 — sharing cuts where the pipeline already cut

**Date:** 2026-08-21
**Status:** Decided

## Context

Designing the social layer required answering what sharing a room actually
shares. A room is a real home, and the honest answers range from a few kilobytes
of measurement to hundreds of megabytes of photographically derived
possessions. Treating "share this room" as one act would mean picking one point
on that range for everybody, forever.

## What we tried

Two framings were weighed.

**A privacy model layered on top of sharing** — share the room, then decide
which parts to redact, blur, or withhold. This is the shape most products take,
and it has a specific failure: the redaction is a policy applied to a complete
artifact, so every bug in it is a leak, and every new manifest field is a new
thing somebody must remember to redact.

**A ladder cut on seams the pipeline already has.** A ready scene is not one
artifact; it is three, written by different stages into different blobs:
`shell.json` from `/shell` (floor polygon, wall geometry, openings, measured
albedo, material family), `manifest.json` from `/process` (the fused object
array), and the per-object `.ply`/`.spz` splats. Two derived layers sit above
them — `SceneFacts` (`services/api-public/scene_facts.py`, FACTS_VERSION 3) and
the conversation.

The second framing had already been validated in production without being
recognised as general. Decision 0122 put a real captured home on the public
landing page by shipping its `shell.json` verbatim with an empty object array —
`web/public/hero/room.json`, **3,557 bytes against roughly 460 MB** for the same
scene's full splat set — and its stated reason was that this "dissolves the
privacy question rather than managing it."

## What we chose

Sharing is a **four-rung disclosure ladder**, each rung an artifact that already
exists separately, the person picks the rung, and the default is the lowest:

- **Rung 0 — the card.** A generated artifact carrying the measured contour and
  a line of derived facts. No object data at all.
- **Rung 1 — the shell.** The room's envelope. 0122's hero rung.
- **Rung 2 — shell plus inventory.** Rung 1 plus `SceneFacts` as text: what was
  found, how many, how big, what colour. No pixels.
- **Rung 3 — the room.** The splats: the person's actual possessions.

Two rules attach.

**A per-rung reconstruction specification**, written as a specification rather
than a principle, in `docs/product/social-layer.md` §3.2 — including the
uncomfortable parts: rungs 0 and 1 disclose a true-dimensioned floor plan of one
room of a home, which is identifying in combination with knowledge a viewer may
already have.

**0122's eligibility rule generalises to every rung.** `person` became a
suppression-only concept in 0089, and suppression is not retroactive: a scene
segmented before it shipped was never asked about people, so zero detections
prove nothing, and its measured wall albedo may be a person standing in front of
that wall — the shipped defect on `f3d70236`'s `wall_03`. So: **a room is
eligible to leave the owner's account only if every frame of its scene was
segmented on a suppression-armed revision.** A pre-0089 scene must be re-driven
first, and a warm re-drive does not re-segment (0122's own trigger), so this is
GPU work rather than a flag.

**That rule is not checkable from a room's own data today.** The manifest
records no suppression provenance — `process_receiver.py` writes `scene_id`,
versions, frame counts, `sampling`, `objects` and `frames`, and nothing about
whether the frames were ever asked about people; the per-frame `suppressed`
union lives in `masks.npz`, which the serving path never reads. 0122 settled the
hero by hand, comparing segmentation and bake timestamps against a revision's
deploy time — adequate for one curated fixture, inadequate for a feature every
person can invoke. Two ways to close it, and a share path needs one:

- **A conservative `created_at` gate**, available with no pipeline change:
  a scene created after the first suppression-armed revision deployed had no
  frame cache of its own to inherit pre-0089 masks from, so it was necessarily
  segmented with suppression armed. `created_at` is already in the client-facing
  scene shape (`_scene_to_client_dict`). The gate is one-directional — it
  refuses some eligible older rooms that were re-driven cold — and refusing an
  eligible room is the safe error.
- **A suppression provenance field on the manifest**, the durable fix, which
  makes the gate exact rather than conservative.

## Why

**The seam is structural, so the privacy property is structural.** A rung is not
a filtered view of a complete artifact; it is a different set of files. Nothing
must remember to strip anything, and a new manifest field cannot leak through a
rung that does not ship the manifest. This is the same reason 0089's suppression
rides `partition_detections` rather than a downstream filter.

**It was already load-bearing and already shipped.** 0122 is not a precedent
being stretched — it is this decision, applied once, to the hardest case (a
permanently public origin), with the argument written out. Generalising it costs
nothing and refusing to would mean holding two incompatible ideas about the same
seam.

**The exposure is inverted from intuition, which is why the rule needs writing
down.** The eligibility rule matters *most* at rungs 0 and 1, where a reader
assumes the risk is lowest, because a person contaminates a wall's measured
albedo and the shell is exactly what those rungs ship. A card carries no splats
and therefore looks unrelated to segmentation. It is not.

**No rung can leak a photograph, and that is checkable.** The manifest
references no photograph, `get_scene_assets` signs exactly the placed objects'
splats (0124's filter), and the raw capture lives under a 24-hour lifecycle rule
(Privacy Policy §6). The property holds because no route can produce one, not
because sharing declines to.

## What would change this decision

- **The pipeline merges the seam.** If shell geometry were ever folded into the
  manifest, or object data into the shell, the ladder loses its structural
  guarantee and becomes a redaction policy — the framing rejected above. Any
  such change is a decision about sharing whether or not it is written as one.
- **Placement quality passes an operator walk at stranger scrutiny.** 0122's own
  reopening trigger. It changes how attractive rung 3 is; it does not change
  §3.2's specification of what rung 3 discloses.
- **A concept beyond `person` becomes suppression-only.** The eligibility rule is
  written against suppression-armed revisions generally, so a new concept moves
  the eligibility boundary forward and re-strands every room segmented before it.
