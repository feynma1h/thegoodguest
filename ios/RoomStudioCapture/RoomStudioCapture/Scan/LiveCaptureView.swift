/// Active capture — THE core screen (design spec §3). Live AR, quiet.
///
/// The design: the LiDAR mesh renders as an ink-on-parchment sketch drawing
/// itself onto the room — no camera photo-feed, no neon wireframe, no coverage
/// percentage. Three things stay legible: tracking quality (the top pill), what
/// you've covered (the sketch filling + the felt floor/walls/corners ticks), and
/// whether it's enough (the guest's spoken confirmation). Warnings speak plainly
/// and never blame.
///
/// LAYERING (decision 0072): this file is the SwiftUI OVERLAY plus an on-brand
/// gold-ink mesh PLACEHOLDER (`InkMeshBackdrop`), both simulator-verifiable. The
/// real live geometry — a RoomPlan / ARKit scene-reconstruction mesh painted as
/// gold ink — replaces the placeholder at the `LiveMeshHost` seam below and can
/// only be built/verified on a LiDAR device (board item 3). The overlay is driven
/// by `CaptureHUDState`, which the AR layer will populate from real tracking +
/// RoomPlan coverage when that lands.

import SwiftUI

// MARK: - HUD state (what the AR layer feeds the overlay)

/// Mirrors what ARKit actually reports, so the screen never asserts a cause the
/// session didn't give. `.finding` covers not-yet-tracking / initializing /
/// relocalizing (no cause claimed); `.tooDark` is ONLY `.insufficientFeatures`.
enum TrackingQuality {
    case good       // mesh draws, pill green
    case slowDown   // moving too fast (.excessiveMotion), pill gold, mesh pauses
    case finding    // not tracking yet / initializing / relocalizing — no cause
    case tooDark    // .insufficientFeatures — the genuine light problem
}

/// A single surface's coverage, felt — never shown as a percentage number.
enum SurfaceCoverage {
    case empty
    case partial(Double)   // 0…1, for the half-filled tick
    case full
}

struct CaptureHUDState {
    var tracking: TrackingQuality = .good
    var guestLine: String = "You've got most of it — one more pass along that far wall and I'll have the whole room."
    var floor: SurfaceCoverage = .full
    var walls: SurfaceCoverage = .full
    var corners: SurfaceCoverage = .partial(0.6)
}

// MARK: - Live capture screen

struct LiveCaptureView: View {
    var state: CaptureHUDState = CaptureHUDState()
    var onFinish: () -> Void = {}

    var body: some View {
        ZStack {
            captureBackdrop

            // The live mesh (placeholder now; RoomPlan on device — see seam).
            LiveMeshHost(paused: state.tracking != .good, dimmed: state.tracking == .tooDark)

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
            colors: [Color(rsHex: 0x2c2214), Color(rsHex: 0x221a0f), Color.rsCaptureBase],
            center: .init(x: 0.5, y: 0.42),
            startRadius: 40, endRadius: 520
        )
        .ignoresSafeArea()
    }

    // MARK: Overlay chrome

    private var overlay: some View {
        VStack(spacing: 0) {
            trackingPill
                .padding(.top, 8)

            Spacer()

            if state.tracking == .tooDark {
                GuestLine("It's gone dark — I can't see. A light, or a step back?",
                          size: 17, onDark: true, alignment: .center)
                    .padding(.horizontal, 28)
                    .padding(.bottom, 16)
            } else {
                GuestLine(state.guestLine, size: 17, onDark: true, alignment: .center)
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

    private var trackingPill: some View {
        let (dot, text): (Color, String) = switch state.tracking {
        case .good:     (.rsSensorGood, "Tracking is good")
        case .slowDown: (.rsSensorWarn, "Go a little slower")
        case .finding:  (.rsSensorWarn, "Finding the room…")
        case .tooDark:  (.rsSensorLost, "Too dark to see")
        }
        return HStack(spacing: 8) {
            Circle()
                .fill(dot)
                .frame(width: 8, height: 8)
                .shadow(color: dot, radius: state.tracking == .good ? 6 : 0)
            Text(text)
                .font(RSFont.ui(.subheadline, weight: .medium))
                .foregroundStyle(Color.rsOnDark)
        }
        .padding(.horizontal, 15)
        .padding(.vertical, 7)
        .background(
            Capsule().fill(Color.rsBlack.opacity(0.6))
                .overlay(Capsule().stroke(dot.opacity(0.4), lineWidth: 1))
        )
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
                .font(RSFont.mono(size: 10, weight: .medium))
                .tracking(0.5)
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
                    .font(RSFont.ui(.subheadline, weight: .semibold))
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

// MARK: - Live mesh seam

/// Hosts the live geometry. TODAY: the on-brand SwiftUI ink placeholder, which
/// conveys the aesthetic and is simulator-verifiable. ON A LiDAR DEVICE: replace
/// the body with a RoomPlan / ARKit scene-reconstruction mesh rendered as gold
/// ink (an `ARSCNView`/`RoomCaptureView` `UIViewRepresentable`) — that render is
/// the hardware-gated piece (board item 3). Keeping the seam here means the
/// overlay above never has to change when the real mesh lands.
private struct LiveMeshHost: View {
    var paused: Bool
    var dimmed: Bool

    var body: some View {
        InkMeshBackdrop()
            .opacity(dimmed ? 0.25 : (paused ? 0.6 : 0.85))
            .animation(.easeInOut(duration: 0.4), value: dimmed)
            .animation(.easeInOut(duration: 0.4), value: paused)
    }
}

/// Gold-ink room sketch — a stand-in for the live mesh, in the brand's ink
/// aesthetic. Vector, so it reads as "drawn," not rendered.
private struct InkMeshBackdrop: View {
    var body: some View {
        GeometryReader { geo in
            let w = geo.size.width, h = geo.size.height
            // Normalized room-ish wireframe (fractions of the frame).
            let ink = Color.rsGoldLight
            ZStack {
                Path { p in
                    // left wall
                    p.move(to: pt(0.06, 0.36, w, h)); p.addLine(to: pt(0.48, 0.29, w, h))
                    p.addLine(to: pt(0.48, 0.68, w, h)); p.addLine(to: pt(0.06, 0.78, w, h)); p.closeSubpath()
                }.stroke(ink.opacity(0.9), lineWidth: 1)
                Path { p in
                    // right wall
                    p.move(to: pt(0.48, 0.29, w, h)); p.addLine(to: pt(0.95, 0.36, w, h))
                    p.addLine(to: pt(0.95, 0.78, w, h)); p.addLine(to: pt(0.48, 0.68, w, h)); p.closeSubpath()
                }.stroke(ink.opacity(0.5), lineWidth: 1)
                Path { p in
                    // floor
                    p.move(to: pt(0.06, 0.78, w, h)); p.addLine(to: pt(0.48, 0.68, w, h))
                    p.addLine(to: pt(0.95, 0.78, w, h)); p.addLine(to: pt(0.48, 0.89, w, h)); p.closeSubpath()
                }.stroke(ink.opacity(0.7), lineWidth: 1)
                Path { p in
                    // a piece of furniture
                    p.move(to: pt(0.6, 0.69, w, h)); p.addLine(to: pt(0.79, 0.66, w, h))
                    p.addLine(to: pt(0.79, 0.75, w, h)); p.addLine(to: pt(0.6, 0.78, w, h)); p.closeSubpath()
                }.stroke(ink.opacity(0.8), lineWidth: 1)
                // vertex dots
                ForEach(Array(vertices.enumerated()), id: \.offset) { _, v in
                    Circle().fill(Color.rsGold.opacity(0.55))
                        .frame(width: 5, height: 5)
                        .position(pt(v.0, v.1, w, h))
                }
            }
        }
        .ignoresSafeArea()
    }

    private var vertices: [(Double, Double)] {
        [(0.48, 0.29), (0.06, 0.36), (0.95, 0.36), (0.48, 0.68), (0.79, 0.66), (0.6, 0.69)]
    }

    private func pt(_ fx: Double, _ fy: Double, _ w: CGFloat, _ h: CGFloat) -> CGPoint {
        CGPoint(x: CGFloat(fx) * w, y: CGFloat(fy) * h)
    }
}

#Preview("Good tracking") {
    LiveCaptureView()
}

#Preview("Too dark") {
    LiveCaptureView(state: CaptureHUDState(tracking: .tooDark))
}

#Preview("Finding the room") {
    LiveCaptureView(state: CaptureHUDState(tracking: .finding))
}
