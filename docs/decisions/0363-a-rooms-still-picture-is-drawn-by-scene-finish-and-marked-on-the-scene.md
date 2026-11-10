# 0363 — A room's still picture is drawn by scene-finish and marked on the scene

**Date:** 2026-11-10
**Status:** Decided

## Context

The iOS redesign (2026-11-10) shows a server-rendered still picture of each
room on its room cards and its "your room is ready" screen, and the app is
being built against a fixed contract: `still_url` and `still_night_url` on every
scene in `GET /scenes` and `GET /scenes/by-bundle`, V4-signed links to
`scenes/{id}/still.jpg` / `still-night.jpg` or null, JPEG 1600 x 1200, the room
from the website's first diorama corner view in the website's look, by day and
in the viewer's lamplit night. `services/scene-finish` holds the only renderer
that draws a room the way the website does (0331, 0332) and had never been
deployed.

## What we tried

- **What a bare shell looks like.** The website draws the corner view only for
  a room whose `finish.json` fits its shell. A bare shell — every room while
  the finish layer is off, including the one room in production — is drawn
  flat, from an orbit camera, and its viewer raised no ready signal. Three
  answers: no still until a room has a finish (the feature would be inert
  today); a finish derived on the server so a bare shell is drawn finished (a
  look the website does not show for that room); or the website's flat look
  from the same corner rig. Rendered locally on SwiftShader: the third shows
  the room's real walls, colours and openings from the same camera as the
  finished room, framed identically.
- **How the picture is taken.** The canvas alone (`toDataURL`) is transparent
  where the page's CSS background shows, so a Python composite would copy the
  website's gradients and drift from them. A screenshot of the page carries
  the background and vignette the website draws, and follows the website's
  look whenever the image is rebuilt from `web/`.
- **How the API knows a still exists.** An existence check per room is a
  bucket round trip per scene in a list; signing every ready scene and letting
  the app 404 breaks "null when there is no still" and spends a signBlob call
  on rooms without one. A field on the scene document costs nothing: the list
  already streams those documents.

## What we chose

- **`POST /still {scene_id}` in scene-finish, render only** (`routes_still.py`).
  It reads `shell.json`, and `finish.json` and `furniture.json` when present,
  and the driver opens the flagged preview page at 1600 x 1200 with
  `?still=1`: the first corner view exactly (no entrance dolly), no view pill
  or day/night button, and a ready signal for a bare shell too. What is drawn
  is the page's call, as on the website: a finish that does not fit is left
  out, twins only stand in a finished room. A bare shell is the flat shell; a
  finished room is the finished room.
- **Night only with twins.** The website has no night without them (its lamps
  are twins, 0343), so `still-night.jpg` is written only when the viewer drew
  twins, and a stale one is deleted.
- **The marker.** After the JPEGs are written, the scene document gets
  `still: {night, rendered_at}` by `update()` — never `status`, so the route
  still cannot un-ready a room. A room deleted while it was drawn has its
  pictures taken back out. scene-finish therefore holds `roles/datastore.user`
  (Firestore IAM has no per-collection role; perception-obj holds the same).
- **api-public** signs `scenes/{id}/still.jpg` (and the night one when the
  marker says so) beside the scene's manifest, in one bounded pool per list
  call, with the assets route's 1 h TTL. A signing failure is a null, never a
  failed list. api-internal never writes the field (pinned by a test).
- **Triggers.** perception-obj's `/shell` enqueues `/still` after writing a
  ready shell (`still_enqueue.py`, `SCENE_FINISH_URL`); `/furniture-merge`
  enqueues it again when it publishes. `tools/enqueue_still.py` queues it by
  hand, for rooms made before the trigger and for smoking a candidate.
- **Access.** Platform-gated like perception-obj (0106), plus a per-route OIDC
  check (`task_auth.py`); production without the settings refuses to run.

## Why

The contract's point is that the app shows what the website will show. Drawing
it with the website's own page, from the website's own camera rig, is the only
way that stays true as the website changes; any second renderer or composited
background would be a copy that drifts. The marker keeps a list call free of
bucket traffic and makes "is there a picture" a fact written by the one thing
that made the picture.

## What would change this decision

- The website's room page drawing a bare shell another way (a diorama, near
  walls cut to stubs as the landing's sample room does): the still follows on
  the next scene-finish build. Today the room page removes the two near walls
  entirely, so the still does too.
- A night look for rooms without twins, or the app wanting another size.
- Known gaps: the trigger is live only once perception-obj is redeployed with
  `SCENE_FINISH_URL`; a still written after account deletion's bucket sweep but
  before its document delete would outlive the room (the race every background
  writer of `scenes/{id}/` has).
