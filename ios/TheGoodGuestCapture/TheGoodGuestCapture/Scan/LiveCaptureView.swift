/// Active capture — THE core screen (design spec §3). Live AR, quiet.
///
/// The design: the room draws itself in ink — no camera photo-feed, no neon
/// wireframe, no coverage percentage. Three things stay legible: tracking
/// quality (the top pill), what you've covered (the live floor plan filling +
/// the felt floor/walls/corners ticks), and whether it's enough (the guest's
/// spoken confirmation). Warnings speak plainly and never blame.
///
/// LAYERING (decisions 0072/0077): this file is the SwiftUI OVERLAY; the live
/// geometry behind the `LiveMeshHost` seam is the Good Guest FLOOR PLAN
/// (FloorPlanView.swift) — the 2D minimap decision 0077 chose over
/// a 3D mesh render — fed by CaptureManager's RoomPlan delegate stream via
/// `FloorPlanFeed`. With no feed (previews, non-LiDAR simulators) the seam
/// renders empty and the overlay still verifies. The overlay itself is driven
/// by `CaptureHUDState`, which RootFlowView populates from real tracking +
/// the live census.

import SwiftUI

// MARK: - HUD state (what the AR layer feeds the overlay)

/// Mirrors what ARKit actually reports, so the screen never asserts a cause the
/// session didn't give. `.finding` covers not-yet-tracking / initializing /
/// relocalizing (no cause claimed); `.tooDark` is ONLY `.insufficientFeatures`.
enum TrackingQuality {
    case good       // mesh draws; the readout is muted, because nothing is wrong
    case slowDown   // moving too fast (.excessiveMotion), mesh pauses
    case finding    // not tracking yet / initializing / relocalizing — no cause
    case tooDark    // .insufficientFeatures — the genuine light problem
}

/// A single surface's coverage, felt — never shown as a percentage number.
/// Equatable so the FloorPlanVoice.coverage mapping can be pinned as a table.
nonisolated enum SurfaceCoverage: Equatable {
    case empty
    case partial(Double)   // 0…1, for the half-filled tick
    case full
}

struct CaptureHUDState {
    // Defaults assert NOTHING: a defaulted construction anywhere in production would
    // otherwise ship invented coverage and a "far wall" instruction the app cannot
    // know. RootFlowView overrides every field from real tracking state.
    var tracking: TrackingQuality = .good
    var guestLine: String = "Move slowly and I'll sketch the room as you go."
    var floor: SurfaceCoverage = .empty
    var walls: SurfaceCoverage = .empty
    var corners: SurfaceCoverage = .empty
}

// MARK: - Live capture screen

struct LiveCaptureView: View {
    var state: CaptureHUDState = CaptureHUDState()
    /// The floor plan's data stream (CaptureManager.floorPlanFeed). Nil in
    /// previews and on sessions with no RoomPlan co-run — the seam then
    /// renders empty and the overlay carries the screen.
    var feed: FloorPlanFeed? = nil
    var onFinish: () -> Void = {}

    var body: some View {
        ZStack {
            captureBackdrop

            // The live floor plan — the room drawing itself.
            LiveMeshHost(feed: feed,
                         paused: state.tracking != .good,
                         dimmed: state.tracking == .tooDark)

            // Vignette to seat the mesh in the room's darkness.
            RadialGradient(
                colors: [.clear, Color.rsBlack.opacity(0.55)],
                center: .init(x: 0.5, y: 0.45),
                startRadius: 120, endRadius: 460
            )
            .ignoresSafeArea()

            overlay
        }
        .statusBarHidden(false)
        .persistentSystemOverlays(.hidden)
        // Spec §3: the screen stays awake throughout capture; auto-lock mid-scan
        // would interrupt the ARSession.
        .onAppear { UIApplication.shared.isIdleTimerDisabled = true }
        .onDisappear { UIApplication.shared.isIdleTimerDisabled = false }
    }

    private var captureBackdrop: some View {
        RadialGradient(
            colors: [Color(rsHex: 0x25241f), Color(rsHex: 0x1c1b18), Color.rsCaptureBase],
            center: .init(x: 0.5, y: 0.42),
            startRadius: 40, endRadius: 520
        )
        .ignoresSafeArea()
    }

    // MARK: Overlay chrome

    private var overlay: some View {
        VStack(spacing: 0) {
            trackingReadout
                .padding(.top, 14)

            Spacer()

            if state.tracking == .tooDark {
                // Tracking truth outranks everything the guest might say —
                // this override sits ABOVE FloorPlanVoice's priority table.
                GuestLine("It's gone dark — I can't see. A light, or a step back?",
                          size: 17, onDark: true, alignment: .center, maxSize: 22)
                    .fixedSize(horizontal: false, vertical: true)
                    .padding(.horizontal, 28)
                    .padding(.bottom, 16)
            } else if let feed {
                // The one spoken line: guidance / new-piece moments / the
                // "enough" confirmation / the default, per FloorPlanVoice.
                LiveGuestLineView(feed: feed, defaultLine: state.guestLine)
                    .fixedSize(horizontal: false, vertical: true)
                    .shadow(color: .black.opacity(0.6), radius: 12, y: 2)
                    .padding(.horizontal, 24)
                    .padding(.bottom, 16)
            } else {
                GuestLine(state.guestLine, size: 17, onDark: true, alignment: .center, maxSize: 22)
                    .fixedSize(horizontal: false, vertical: true)
                    .shadow(color: .black.opacity(0.6), radius: 12, y: 2)
                    .padding(.horizontal, 24)
                    .padding(.bottom, 16)
            }

            coverageTicks
                .padding(.bottom, 18)

            controls
                .padding(.bottom, 12)
        }
        .padding(.horizontal, 22)
    }

    /// What the tracker knows, in the machine's own voice.
    ///
    /// NOT A BADGE. This was a bordered capsule holding a coloured dot beside a
    /// sentence — the single most generic status component in software, and the
    /// only element on this screen not written in the app's own idiom. The
    /// coverage ticks eighteen points below it are mono, uppercase, tracked and
    /// uncontained; so is the desk's status line; so is every other piece of
    /// machine truth in this app. The tracker is machine truth. It reads like
    /// the rest of it now.
    ///
    /// THE ORDINARY STATE IS QUIET, which is the inversion the badge had
    /// backwards: `.good` carried the ONLY glow in the component, so the state
    /// where nothing is wrong was the loudest thing on screen. Good tracking is
    /// now set in the same muted ink as the coverage labels, and colour is
    /// spent only where something needs attention.
    ///
    /// THE DOT IS GONE AND NOTHING REPLACES IT. It duplicated the text, and it
    /// duplicated it badly: two of the four states share a colour, so the dot
    /// carried three values where the words carry four.
    private var trackingReadout: some View {
        let (ink, text): (Color, String) = switch state.tracking {
        // Muted, not green: the resting state of a working instrument.
        case .good:     (.rsOnDark.opacity(0.55), "TRACKING")
        case .slowDown: (.rsSensorWarn, "MOVING TOO FAST")
        case .finding:  (.rsSensorWarn, "FINDING THE ROOM")
        case .tooDark:  (.rsSensorLost, "TOO DARK TO SEE")
        }
        return Text(text)
            .rsFont(.mono, size: 11, weight: .medium, maxSize: 15, cap: .mono)
            .tracking(1.4)
            .foregroundStyle(ink)
            .lineLimit(1)
            .fixedSize()
            // The same shadow the guest's line carries, and for the same
            // reason: this sits over a live camera feed with no plate behind
            // it, and the feed is whatever the room happens to be.
            .shadow(color: .black.opacity(0.75), radius: 10, y: 1)
            .animation(.easeOut(duration: 0.2), value: text)
    }

    private var coverageTicks: some View {
        HStack(spacing: 8) {
            coverageTick("FLOOR", state.floor)
            coverageTick("WALLS", state.walls)
            coverageTick("CORNERS", state.corners)
        }
    }

    private func coverageTick(_ label: String, _ coverage: SurfaceCoverage) -> some View {
        HStack(spacing: 6) {
            Text(label)
                .rsFont(.mono, size: 10, weight: .medium, maxSize: 13, cap: .mono)
                .tracking(0.5)
                .lineLimit(1)
                .fixedSize()
                .foregroundStyle(Color.rsOnDark.opacity(0.55))
            Capsule()
                .fill(Color.rsOnDark.opacity(0.18))
                .frame(width: 22, height: 5)
                .overlay(alignment: .leading) {
                    Capsule()
                        .fill(Color.rsGold)
                        .frame(width: 22 * coverageFraction(coverage), height: 5)
                }
        }
    }

    private func coverageFraction(_ coverage: SurfaceCoverage) -> Double {
        switch coverage {
        case .empty:            return 0
        case .partial(let f):   return min(max(f, 0), 1)
        case .full:             return 1
        }
    }

    private var controls: some View {
        HStack {
            // Balance the shutter; no re-center control is shown because
            // CaptureManager has no recenter capability — a visible button that did
            // nothing would be a dead control.
            Color.clear.frame(width: 52, height: 52)

            Spacer()

            // Finish — the primary shutter (rust, cream ring).
            Button(action: onFinish) {
                Text("Finish")
                    // Fixed-geometry control: the app's ONE capture action must stay
                    // legible at every text size rather than truncate to "Fi…".
                    .rsFont(.ui, size: 15, weight: .semibold, maxSize: 17)
                    .lineLimit(1)
                    .minimumScaleFactor(0.7)
                    .foregroundStyle(Color.rsSurface)
                    .frame(width: 78, height: 78)
                    .background(Color.rsAction, in: Circle())
                    .overlay(Circle().stroke(Color.rsOnDark.opacity(0.85), lineWidth: 4))
                    .shadow(color: Color.rsAction.opacity(0.5), radius: 12, y: 6)
            }
            .accessibilityLabel("Finish scanning")

            Spacer()

            Color.clear.frame(width: 52, height: 52)
        }
    }
}

// MARK: - Live floor plan seam

/// Hosts the live geometry: the Good Guest floor plan, fed by CaptureManager's
/// RoomPlan delegate stream. The inset keeps the plan's fit region clear of the
/// overlay chrome (tracking pill above; guest line, ticks and shutter below)
/// so the room draws in the screen's visual center band.
/// With no feed (previews, sessions without a RoomPlan co-run) the seam is
/// empty — an honest nothing, never an invented room.
private struct LiveMeshHost: View {
    var feed: FloorPlanFeed?
    var paused: Bool
    var dimmed: Bool

    var body: some View {
        Group {
            if let feed {
                LiveFloorPlan(feed: feed, paused: paused, dimmed: dimmed)
            } else {
                Color.clear
            }
        }
        .padding(EdgeInsets(top: 78, leading: 26, bottom: 236, trailing: 26))
    }
}

#Preview("Good tracking") {
    LiveCaptureView()
}

#Preview("Mid-scan (seeded feed)") {
    let feed = FloorPlanFeed()
    feed.publish(snapshot: .previewRoom)
    feed.publish(camera: .previewCamera)
    return LiveCaptureView(feed: feed)
}

#Preview("Too dark") {
    LiveCaptureView(state: CaptureHUDState(tracking: .tooDark))
}

#Preview("Finding the room") {
    LiveCaptureView(state: CaptureHUDState(tracking: .finding))
}
