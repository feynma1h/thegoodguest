# 0376 — The room guide is in the product behind one switch

**Date:** 2026-11-12
**Status:** Decided — `services/api-public/guide_session.py`, `guide_repo.py` and the guide routes in `public_server.py`; `web/src/lib/guide/`, `web/src/components/guide/GuideRoom.tsx`, `web/scripts/guide-assets.mjs`. Off until `ROOM_GUIDE_ENABLED` is turned on.

## Context

The room guide (0370–0373) ran only in its local harness, with one room held in
memory. The operator wants it in the product. A room whose pipeline wrote a
diorama `scene.json` should get the guide; every other room keeps the guest
(0058, 0131–0133).

Two things are not in place yet. The diorama pipeline is unmerged, so nothing in
the cloud writes `scene.json`. And deploys and traffic flips wait for the
operator.

## What we tried

- **Copying the guide's turn loop into api-public.** Two loops would drift
  apart. Instead, the harness's session is rebuilt from Firestore on each
  request, and `run_turn` plays unchanged against it.
- **Keeping messages as Firestore maps.** Maps reorder keys and cannot hold an
  array inside an array. Stored as JSON text, every block comes back byte for
  byte, which the API needs for reasoning signatures.
- **Relying on the gateway's file cache for the rules pass.** That cache does
  not outlive a Cloud Run request.
- **Taking part shapes from the browser, as the harness does.** A client could
  then make the engine collide with anything it likes.
- **A per-conversation turn quota, like the guest's.** One guide turn can cost
  ten times another (the rules pass, the searches), and the gateway already
  prices every call.
- **Copying the diorama viewer and the player into web.** The copies would
  drift from their sources.

## What we chose

**api-public**

- `GET /scenes/{id}/assets` gains `scene_url`. It follows 0313's rule: any
  failure is null and a log line.
- Four routes:
  - `GET /scenes/{id}/guide`
  - `POST …/guide/turns`, which streams `delta`, `card`, `play`, `focus`,
    `note`, then `done` or `error`
  - `POST …/guide/show`
  - `POST …/guide/undo`

  A room without `scene.json` answers 404 `no_guide`.
- **What is kept.** Each `{scene_id}__{user_id}` has a `room_guides` document
  with a `turns` subcollection. A turn keeps the messages it added, as Claude
  returned them, and what the panel showed. The document keeps the room's
  state:
  - the arrangement history;
  - what the person said;
  - the needs, once the person's words change them;
  - every proposal by id, with the arrangement it was offered on.
- **Cards.** A card is "ready" while the room is as it was when the card was
  offered, and "shown" while its change is on screen. Once the room moves on it
  is "stale", and it cannot be shown: that would silently undo the other
  changes. Pressing "Show me" also tells the guide what is on the screen. The
  harness's button did not.
- **`needs.json`.** It is written beside the scene the first time a turn needs
  it, and is valid only for the same `scene.json` hash and rules prompt version.
- **Solids.** Part shapes come from the pipeline's `solids.json`. Without one,
  each piece is its whole box.
- **The guest's guarantees hold.**
  - Firebase auth and ownership.
  - A daily budget per person across every room, in dollars (`GUIDE_DAILY_USD`,
    default 2.00; 0 turns the guide off). It is checked when a turn is
    accepted. After every turn, completed or not, the turn's cost is charged:
    billed when live, priced when replayed or stubbed.
  - A 150 s lease that both buttons take too.
  - Turns run on a small worker pool of their own. One past 100 s is told to
    stop at its next event; it then charges what it spent and lets go of the
    lease.
  - A client disconnect does not stop a turn.
- **The model** comes from `GUIDE_MODEL`, and only the two models 0360 allows
  are accepted. The key is the guest's Secret Manager key. Production always
  calls Claude live; replay and stub modes are for local runs and tests.
- **Account deletion** erases `room_guides`, its `turns` and
  `room_guide_budgets`. The scene's files go with its folder.

**web**

- **The switch.** `ROOM_GUIDE_ENABLED` in `lib/guide/switch.ts` is false (the
  0340 pattern). With it on, the room page asks for the assets once:
  - a room with `scene_url` gets `GuideRoom`;
  - any other room gets RoomStage, handed the same assets so nothing is signed
    twice.

  If the guide or the viewer fails, the room falls back to RoomStage. With the
  switch off, nothing changes.
- **The viewer.** It is embedded same-origin from `DIORAMA_VIEWER_PATH`
  (`/diorama/viewer.html`). `scripts/guide-assets.mjs` runs before dev and
  build. It copies the viewer once its folder exists, and the guide's
  `player.js` as it is. It also serves three.js from this app's `node_modules`
  instead of a CDN, so no third-party script runs beside a signed-in session.
  It refuses a three.js version that differs from the one the viewer asks for.
- **The page.** The player is injected into the viewer's frame. The viewer's own
  room name, capture time and caption are hidden, because the room page shows
  them in its own chrome. The rail is RoomStage's rail:
  - the guest's words in the serif's italic;
  - cards and notes in the interface face;
  - "Put it back" in the strip that says the room on screen has changed.
- **Hosting.** `firebase.json` lets `/diorama/**` be framed by the site itself,
  and its policy allows the signed scene's images and fetches. This changes
  nothing until the viewer ships.

## Why

The product runs the same turn loop as the harness, so the guide lane's evals
and replays apply here unchanged. In the local run, the recorded live run's
seven turns replayed through the product at the same per-turn costs. That shows
the requests are byte-identical, including after "Put it back" restores the
room.

The switch and the `no_guide` fallback leave every room exactly as it was until
the operator turns the guide on.

## What would change this decision

- **Switching on** needs four things: the diorama merge, a cloud stage that
  publishes `scene.json` and `solids.json`, the constant set to true, and a
  deploy the operator approves.
- **Files beside the scene.** If a scene names photo maps or meshes, the viewer
  fetches them relative to the signed URL, so each needs a signed link of its
  own.
- **CPU.** Searches are CPU-heavy: about 4 s each on the demo room, on a 1-CPU
  instance shared by up to 80 requests. If that slows other routes, the guide
  gets its own service or more CPU.
- **Long conversations.** Past `GUIDE_HISTORY_TURNS` (30) turns, the oldest
  drop out of the model's view. A summary would be the next step.
