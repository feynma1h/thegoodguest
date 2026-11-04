# 0297 — the review opens from the Home Screen, and asks again when RoomPlan withholds depth

**Date:** 2026-09-15, amended 2026-09-20 with the review's depth retry
**Status:** Superseded by 0301 — the review screen, its Home Screen entry and its own depth retry are gone; capture's depth guard is the only one

**Net state, 2026-11:** live boxes no longer have a screen of their own, so there is
nothing to open from the Home Screen and nothing to refuse inside the capture flow:
the detector rides the capture's own ARSession (0301). The depth retry below was
the review's own session asking again; riding the capture, the capture's guard
(0076, 0079) is the only one. The finding that RoomPlan's attach can leave a
session without `.sceneDepth` stands, and is why nothing here re-configures
ARKit.

## Context

The live-boxes review (0295) had to be openable on the phone without Xcode, in
DEBUG builds only, and unreachable both in Release and from inside the capture
flow — it runs its own ARSession, and starting one stops the capture's.

The app has no place for it. Every product screen is photographed by the gallery
and measured by the layout audit, the contents screen is a routing table pinned
against home's sentence, and the capture screen is out of this lane's scope. A
DEBUG-only row on any of them would change a screen the operator reviews as
product.

Once open, the review runs capture's own session setup, RoomPlan co-run
included (`CaptureSessionSetup`, 0079), so what it costs describes capture.
That includes capture's depth guard, which re-asserts `.sceneDepth` once per
RoomPlan attach, after ten depthless frames, and cannot fire once any frame has
carried depth.

## What we tried

**A Home Screen quick action** needs a scene delegate in a SwiftUI app: a warm
launch delivers `windowScene(_:performActionFor:completionHandler:)` to the scene's
delegate and nowhere else. The risk is that naming a delegate class in the scene
configuration replaces SwiftUI's own, and with it `onOpenURL` — which is where the
Google sign-in redirect lands.

**Opening the app's own URL scheme on the simulator** could not settle it: iOS
holds both `simctl openurl` and a self-open behind an "Open in …?" confirmation,
and with the build WITHOUT a custom delegate `onOpenURL` still recorded nothing,
so that probe could not tell the two builds apart.

**Asking the scene directly** did. In a DEBUG build whose scene configuration names
`LiveBoxesSceneDelegate`, a temporary breadcrumb recorded the class of the
connected window scene's delegate — `AppSceneDelegate`, SwiftUI's own — and that it
responds to the quick-action selector; invoking that selector with the review's
shortcut item reached `LiveBoxesEntry` and presented the review. SwiftUI keeps its
delegate and forwards to the named class.

**Relying on capture's one-shot depth guard.** On the phone (2026-09-19, 11:47) a
review session ran 19 seconds with RoomPlan co-running and no depth map on any
frame; 92 % of frames were held at "no depth" and no pass started. The guard had
fired at 0.5 s and found `.sceneDepth` already installed (frame semantics 8 → 8),
so the configuration RoomPlan installed after it was the one without depth.
Passes began only when the operator switched RoomPlan off.

**Retrying only while depth had never come** (`e478ca94`) left a RoomPlan attach
made after depth had arrived — the switch turned back on — with no second look.
That is also the shape 0267 recorded in a production capture: depth on frame 0
and none after.

## What we chose

- **A dynamic quick action, "Live boxes"**, registered at launch by DEBUG code. A
  cold launch delivers it in the scene's connection options; a warm one through
  `LiveBoxesSceneDelegate`, forwarded by SwiftUI.
- **Refused anywhere in the capture flow.** `LiveBoxesRoute` opens the review only
  at home with nothing presented over it, and `RootFlowView` reports its stage to
  the entry in DEBUG.
- **`-rs.liveboxes.open YES`** opens the review at launch for unattended runs
  started with `devicectl`, under the same refusal.
- **The installed review build is the Debug configuration compiled with `-O`**
  (`SWIFT_OPTIMIZATION_LEVEL=-O` on the `xcodebuild` command line). The DEBUG flag
  and every gate are unchanged; the prediction runs in Core ML either way, but the
  decode, lift and fuse stages the log times are Swift, and at `-Onone` they would
  describe the compiler rather than the method. The project's own Debug setting is
  still `-Onone`, so a build run straight from Xcode times the compiler; every
  session log says which it came from (`device.optimized`).
- **Release is checked, not assumed.** Built for the simulator in Release, the
  binary holds no string naming a live-boxes type and the bundle no model package,
  while production type names appear 64 times — the control that the search can
  see code at all. `tools/test_live_boxes_boundaries.py` pins the source side.
- **The review asks for depth again** (`DepthRetry`, `55f07888`). After every two
  seconds without depth in a row, whatever came before, it looks at the installed
  configuration, up to ten times per attach: it puts `.sceneDepth` back when it is
  missing, and when it is present and depth still does not come it says so once
  per attach, since re-running an unchanged configuration changes nothing. Each
  attempt is a `depth` event in the session log. Capture's guard, and capture, are
  unchanged.

## Why

**A quick action changes no product surface.** Nothing the gallery photographs
gains a control, so every screen the operator has already judged stays judged.

**The forwarding is what makes the scene delegate safe**, and it was measured
rather than inferred from blog posts, none of which says what happens to
`onOpenURL`.

**The action outlives a DEBUG build.** Dynamic quick actions persist until the app
is deleted, so a Release build installed over a DEBUG one keeps "Live boxes" in the
icon's menu. In Release nothing handles it; it opens the app, and that is all.

**A look at the installed configuration costs nothing, and a missing depth map
costs the whole review.** The retry has since done what it is for: it put
`.sceneDepth` back at 2.9 s (13:18) and 2.4 s (19:34), frame semantics 0 → 8 both
times, and with RoomPlan on for 147 s (19:36) and 43 s (23:30) no frame lacked
depth. It stays the review's own because a change to capture is the operator's
call.

## What would change this decision

- **A SwiftUI release that stops forwarding** to a configured scene delegate: the
  warm quick action would silently do nothing. The cold path would still work, and
  the review's route test would still pass, so this one needs a look on the phone
  after a major iOS update.
- **A product surface for the review** — promoting footprints into capture, say —
  would retire the quick action with the instrument.
- **Another production capture without depth after its first frame**, as 0267's
  `90eebfc4` was, would make the same retry a candidate for capture's guard. That
  is a change to capture, to be put to the operator, not made here.
