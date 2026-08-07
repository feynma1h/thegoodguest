# 0086 — Retention design for scenes + perception outputs (gaps F5/F6)

**Date:** 2026-08-07
**Status:** accepted (shipped: TTL policy + lifecycle rule live, backfill applied)

## Context

Gap F6 (decision 0018) asked for a Firestore TTL on the `scenes` collection
"populated at scene creation"; gap F5 asked for a lifecycle rule on
`gs://roomstudio-perception-outputs/scenes/` with "a retention window
appropriate for active scenes (e.g. 30d)". Both were written in May, before
the product reality hardened: ready scenes ARE the product ("rooms are
identity — sharing, comparison, evolution over time"), the capture bundle is
swept at age 1d, so a ready scene's outputs are the ONLY copy of a user's
room, and the objects the viewer renders live under
`scenes/{id}/frames/*/splats/*.ply` — interleaved with cache intermediates in
the same prefix. Executed as designed, F5/F6 would delete living rooms.

## What we tried

- **Stamp expire_at at creation for every scene (0018's literal design),
  cleared on ready.** Rejected on an ownership boundary: the clear must run
  in perception-obj's `release_ready` (its own receiver_repo), which this
  session must not modify beyond the chartered docstring. Shipping
  creation-stamping while the serving perception cannot clear it would put a
  live deletion clock on every ready room — the exact failure the design must
  exclude.
- **Uniform long-horizon TTL (365d+) on all scenes.** Rejected: any age-based
  deletion of ready rooms contradicts the product thesis, regardless of
  horizon; "revisit before the first scene turns one" is a landmine, not a
  design.
- **Blanket age rule on outputs `scenes/` (F5 as conceived, any horizon).**
  Rejected: served splats, manifest.json, shell.json, roomplan/room.json (the
  shell's geometry source for re-derivation) and the .layout.json rotation
  sidecars all live there. There is no horizon at which deleting them is
  correct while the room is someone's product data.
- **customTime-based lifecycle stamped at terminal failure.** Correct shape,
  but the stamping lives in perception's release paths — same ownership
  boundary; recorded as a follow-up option, not shipped.

## What we chose

**F6 — TTL on exactly the terminal-failure subset api-internal itself
writes.** `Scene.expire_at` (server-only, never serialized to clients) is
stamped by api-internal's `update_status` on FAILED (dispatch-time),
FAILED_INVALID, and FAILED_INCOMPLETE at now + `SCENES_FAILED_TTL_DAYS`
(default 90 — deliberately at the launch-hardening floor, flagged no lower),
and CLEARED on revival to QUEUED (the re-upload retry path). READY is never
stamped. The Firestore TTL policy on `scenes.expire_at` is live
(`eventarc_setup.sh --scenes-ttl-only`). `tools/backfill_scene_expiry.py`
stamped the 30 pre-existing terminal-failure scenes (2026-08-07; the
deliberate stuck-scene reference f077e9ed is `processing` and untouched).

**Cascade holds by construction, not by a second TTL:** conversations exist
only for scenes that reached `ready` (every conversation route gates on
`_load_owned_ready_scene`), and swept scenes never reached ready — a revived
scene has its clock cleared before it can. So scene TTL cannot orphan
conversations/turns today. Recorded correction to the old CLAUDE.md note: a
collection-group TTL on `turns.created_at` would delete LIVE turns
immediately (Firestore TTL fires when the named field's VALUE is past);
if ready-scene deletion ever ships, the cascade needs dedicated expire_at
fields or a recursive sweep.

**F5 — one deliberately narrow lifecycle rule:** delete
`scenes/*/frames/*/masks.npz` after 180d. masks.npz is the only object class
under `scenes/` that nothing serves and nothing needs for correctness — a
warm re-drive older than the horizon recomputes segmentation at GPU cost.
Everything else stays, and whole-scene GC is recorded as a
Firestore-state-driven concern (scene status / future user deletion), never
an age rule.

## Why

The split follows who owns the truth about a scene's liveness. Firestore
status is authoritative; object age is not a proxy for it. api-internal owns
every transition that MAKES a scene junk at ingest time, so it can stamp
exactly those without touching perception. What this deliberately leaves
unswept: scenes failed BY PERCEPTION after dispatch (release_failed does not
stamp), and stuck queued/processing scenes (reenqueue tooling is their
documented cure). Those are the follow-up:

**Follow-up (rides a perception deploy cycle, not this session):** stamp
expire_at in perception's `release_failed`, mirroring `expiry_for_transition`
— at which point receiver_repo's claim() NOT_FOUND becomes routine
steady-state (docstring already updated) and the failed-scene sweep is
complete. Optionally, the same cycle can stamp GCS customTime on a failed
scene's output objects to let a daysSinceCustomTime rule reclaim partial
splat caches of dead scenes — the one outputs class this design leaves
unreclaimed.

## What would change this decision

- A user-facing room-deletion feature ships → whole-scene GC (Firestore doc +
  outputs prefix + conversations recursive delete) becomes an explicit
  command path; this TTL design stays as the junk backstop underneath it.
- Ready-room storage cost becomes material pre-launch → revisit compression
  or per-frame splat dedup, NOT age deletion.
- The perception follow-up lands → failed-scene coverage is complete; update
  the "what stays unswept" list here.
