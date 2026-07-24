# 0072 — iOS app design locked; LiDAR-only client pivot

**Date:** 2026-07-24
**Status:** Decided

## Context

The web app's design is locked (Good Guest, decisions 0057/0069/0070). The iOS
capture app, by contrast, was still the P1-era placeholder: a headless utility
screen (start/stop, a frame counter, a tracking-state badge, no camera preview —
"headless by design"). With the web direction settled and the operator's
2026-07-24 pivot toward a Pro/LiDAR-first pipeline (board item 7, decision 0071),
we ran a dedicated Claude Design session for the iOS surface. It returned a
complete 11-screen spec (`Roomstudio iOS Capture.dc.html`, untracked at repo
root), faithful to Good Guest and translated to iOS idioms (SF Symbols, native
sheets, safe areas, haptics/sound).

## What we chose

1. **Adopt the spec as the locked iOS design direction.** The spine is: cold
   start → idle home → guidance sheet → live capture → got-it/review →
   upload/analyzing → the doorway → (web), with failure off-ramps (terminal /
   recoverable + a relaunch banner) and sidings (sign-in/conflict, thin history,
   QR bridge, push). §10 maps the whole Good Guest system to SwiftUI (three type
   roles, the warm palette, gold = light-semantic only, the haptic/sound
   vocabulary). The reveal, the 3D viewer, the guest conversation, and redesign
   **stay on the web** — the phone renders none of them.

2. **Reverse "headless by design."** Capture becomes a **live AR-guided** screen:
   the LiDAR/RoomPlan mesh paints as an "ink-on-parchment" sketch drawing itself
   onto the room — no camera photo-feed, no neon wireframe, **no coverage
   percentage**. Coverage is *felt* (floor/walls/corners ticks settling) and
   *spoken* (the guest says "enough"), then *seen* whole at review. The old
   headless screen ("did I get enough?" unanswerable while blind) is explicitly
   the road not taken.

3. **LiDAR-only on the client (operator decision, 2026-07-24).** The app will not
   be available on non-LiDAR devices for now. Consequences:
   - The capture **tier split collapses on the client** — there is one capture
     path (LiDAR). The spec's non-LiDAR "degraded ring" treatment (its honest
     headless fallback) is **not built** — it targets a device class that can't
     install the app.
   - The **backend keeps all its tiers untouched.** ARKIT_ONLY remains a valid
     wire tier; our existing real captures (`25a14caf`, `f3d70236`) and the whole
     placement/shell pipeline consume ARKIT_ONLY data. This is purely a client
     install-gate, not a schema or pipeline change.

## Why

- The web and iOS directions now **agree**: both are LiDAR/Pro-first premium. A
  week ago the app's headless minimalism and the mass-market non-LiDAR path were
  the working assumption; decision 0071 changed that, and this design lands on top
  of it rather than fighting it.
- The phone's one job is producing a good capture. Hiding the one thing that
  matters (whether you're actually getting the room) behind a headless screen is
  the core anxiety unaddressed. RoomPlan/LiDAR already yields a real-time mesh;
  showing it — quietly, as brand-consistent ink, not a game overlay — turns a
  blind walk into a legible one.
- Building a full degraded UI for a device class that cannot install the app is
  wasted surface and blurs the clean single-path story.

## Consequences for the build

- **ARKit on-device verification is fully hardware-gated.** The iOS Simulator
  cannot run ARKit/RoomPlan, and the only test device (iPhone 16e / iPhone17,5)
  has no LiDAR and cannot install a LiDAR-gated app. Every ARKit-driven screen
  (live capture, the mesh, got-the-room) is therefore built to spec now and
  **visually verified only when a LiDAR Pro device lands** — the same blocker as
  board item 3, now escalated to gate the capture path's on-device proof.
  Non-ARKit SwiftUI screens (home, guidance, review, upload/analyzing, failures,
  profile, history, doorway, sign-in) remain simulator-previewable.
- **Universal-link handoff (the doorway), the QR bridge, push, and device SIWA**
  are gated on Apple Developer Program enrollment + entitlements
  (associated-domains / APNs) — see decision 0064 and the pre-launch gap list.
  Build the UI now; wire transport when the gates clear.
- **Fonts:** Source Serif 4 / Instrument Sans / IBM Plex Mono are not yet in the
  repo. The type system is built on the spec's own specified fallbacks
  (New York serif / SF Pro / `.monospaced`) with a one-file seam to bundle the
  branded faces later.
- The existing capture/upload/auth/poll plumbing (`CaptureManager`,
  `BlobUploadManager`, `UploadSessionClient`, `ScenePoller`, `AuthManager`) is
  sound and is retained — this is a **presentation-layer rebuild on stable rails**,
  plus a new design-system foundation and a Live Activity widget target.

## What would change this decision

- If the product later re-opens a mass-market non-LiDAR path (reversing 0071),
  the degraded-capture treatment in the spec (§3 middle phone) is the pre-designed
  slot to build, and the client install-gate is lifted.
- If a cloud photogrammetry / any-phone capture path is chosen in the board-item-7
  strategy session (recognition-first, Option C), the "one capture path" premise
  here is revisited.
