/// The scan screen: the camera, and four quiet things over it.
///
/// THE 2026-11-10 REDESIGN puts the camera behind every scan. The old Release
/// screen drew the floor plan on black with no camera; now the plan is a small
/// card over the camera on phones that have one (RoomPlan needs LiDAR), and a
/// phone without LiDAR simply has no card — the camera, the guest and Finish
/// work the same on every iPhone.
///
/// What stays legible, and only this:
///   • what the tracker knows, as a short state in a pill at the top (the
///     guest's line keeps the instruction, so the pill never duplicates it);
///   • the plan drawing itself, in lamplight, on LiDAR phones;
///   • the guest's one line;
///   • how much of the floor, walls and corners has been seen (LiDAR only:
///     the coverage comes from RoomPlan's census).
/// A stop button (with a confirmation) leaves without sending; Finish ends it.
///
/// Read by: RootFlowView, the gallery.

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
    var guestLine: String = "Move slowly — I’ll draw the room as you go."
    var floor: SurfaceCoverage = .empty
    var walls: SurfaceCoverage = .empty
    var corners: SurfaceCoverage = .empty
}

// MARK: - Live capture screen

struct LiveCaptureView: View {
    var state: CaptureHUDState = CaptureHUDState()
    /// The floor plan's data stream (CaptureManager.floorPlanFeed). Nil in
    /// previews; on a phone without LiDAR it never fills, so `showsPlan` is off.
    var feed: FloorPlanFeed? = nil
    /// Whether this scan draws a live plan and coverage (RoomPlan, LiDAR only).
    var showsPlan: Bool = true
    var onFinish: () -> Void = {}
    /// Leave without sending. Confirmed first: what was walked is not kept.
    var onStop: () -> Void = {}
    /// The camera (CameraFeedView, or live boxes in a Debug build).
    var cameraLayer: AnyView? = nil

    @State private var confirmingStop = false

    var body: some View {
        ZStack {
            // The picture hangs off the ground as an overlay, clipped, so it
            // can never size the screen: a feed (or the gallery's stand-in)
            // wider than the phone would otherwise widen the whole stack and
            // push the stop button and the guest's line off the edges.
            Color.rsDusk
                .overlay { cameraLayer }
                .clipped()
                .ignoresSafeArea()
            // Legibility over whatever the room looks like: a soft dusk at the
            // top and the bottom, where the words are. Not decoration.
            VStack(spacing: 0) {
                LinearGradient(colors: [Color.rsDusk.opacity(0.55), .clear], startPoint: .top, endPoint: .bottom)
                    .frame(height: 170)
                Spacer()
                // Dense where the guest's line and the meters sit, not only at
                // the very bottom: measured over a bright floor, a straight
                // ramp left the line on almost bare picture.
                LinearGradient(stops: [
                    .init(color: .clear, location: 0),
                    .init(color: Color.rsDusk.opacity(0.5), location: 0.3),
                    .init(color: Color.rsDusk.opacity(0.8), location: 0.62),
                    .init(color: Color.rsDusk.opacity(0.9), location: 1),
                ], startPoint: .top, endPoint: .bottom)
                    .frame(height: 420)
            }
            .ignoresSafeArea()
            .allowsHitTesting(false)
            if state.tracking == .tooDark {
                Color.black.opacity(0.45).ignoresSafeArea().allowsHitTesting(false)
            }
            overlay
        }
        .statusBarHidden(false)
        // Capture is dusk: the status bar's clock and battery go light.
        .preferredColorScheme(.dark)
        .persistentSystemOverlays(.hidden)
        // The screen stays awake throughout capture; auto-lock mid-scan
        // would interrupt the ARSession.
        .onAppear { UIApplication.shared.isIdleTimerDisabled = true }
        .onDisappear { UIApplication.shared.isIdleTimerDisabled = false }
        .confirmationDialog("Stop this scan?", isPresented: $confirmingStop, titleVisibility: .visible) {
            Button("Discard scan", role: .destructive) { onStop() }
            Button("Keep scanning", role: .cancel) {}
        } message: {
            Text("What you’ve walked so far isn’t kept unless you finish.")
        }
    }

    // MARK: Overlay

    private var overlay: some View {
        VStack(spacing: 0) {
            ZStack {
                trackingPill
                HStack {
                    Button { confirmingStop = true } label: {
                        Image(systemName: "xmark")
                            .font(.system(size: 16, weight: .semibold))
                            .foregroundStyle(Color.rsOnDusk)
                            .frame(width: 44, height: 44)
                            .background(.ultraThinMaterial, in: Circle())
                            .environment(\.colorScheme, .dark)
                    }
                    .accessibilityLabel("Stop scanning")
                    Spacer()
                }
            }
            .padding(.top, 6)

            if !showsPlan {
                Text("Measuring with the camera")
                    .rsFont(.ui, size: 13)
                    .foregroundStyle(Color.rsOnDusk)
                    .shadow(color: .black.opacity(0.7), radius: 8)
                    .padding(.top, 8)
            }

            HStack {
                Spacer()
                if showsPlan, let feed {
                    planCard(feed)
                }
            }
            .padding(.top, 12)

            Spacer()

            guestLine
                .padding(.horizontal, 8)
                .padding(.bottom, 18)

            if showsPlan {
                coverage
                    .padding(.bottom, 20)
            }

            Button(action: onFinish) {
                Text("Finish").frame(width: 120)
            }
            .buttonStyle(RSPrimaryButtonStyle(onDusk: true))
            .fixedSize()
            .accessibilityLabel("Finish scanning")
            .padding(.bottom, 10)
        }
        .padding(.horizontal, 16)
    }

    /// What the tracker knows, as a state. The ordinary state is the quiet
    /// one; the dot is lit (lamplight) only while tracking is good.
    private var trackingPill: some View {
        let (text, dot): (String, Color) = switch state.tracking {
        case .good:     ("Tracking", .rsLamp)
        case .slowDown: ("Moving too fast", Color.rsOnDusk.opacity(0.55))
        case .finding:  ("Finding the room", Color.rsOnDusk.opacity(0.55))
        case .tooDark:  ("Too dark to see", .clear)
        }
        return HStack(spacing: 8) {
            Circle()
                .fill(dot)
                .overlay(Circle().strokeBorder(Color.rsOnDusk.opacity(state.tracking == .tooDark ? 0.8 : 0), lineWidth: 1.5))
                .frame(width: 8, height: 8)
                .shadow(color: state.tracking == .good ? Color.rsLamp : .clear, radius: 5)
            Text(text)
                .rsFont(.ui, size: 15, weight: .medium, maxSize: 20)
                .foregroundStyle(Color.rsOnDusk)
                .lineLimit(1)
        }
        .padding(.horizontal, 16)
        .frame(minHeight: 40)
        .background(.ultraThinMaterial, in: Capsule())
        .environment(\.colorScheme, .dark)
        .animation(.easeOut(duration: 0.2), value: text)
        .accessibilityElement(children: .combine)
        .accessibilityAddTraits(.updatesFrequently)
    }

    /// The plan drawing itself, small, in lamplight, top right.
    private func planCard(_ feed: FloorPlanFeed) -> some View {
        LiveFloorPlan(feed: feed, paused: state.tracking != .good, dimmed: state.tracking == .tooDark)
            .padding(10)
            .frame(width: 124, height: 124)
            .background(Color.rsRaised.opacity(0.86), in: RoundedRectangle(cornerRadius: 22, style: .continuous))
            .overlay {
                if feed.snapshot.walls.isEmpty && feed.snapshot.boxes.isEmpty {
                    Text("The plan draws itself here")
                        .rsFont(.ui, size: 12)
                        .foregroundStyle(Color.rsOnDusk2)
                        .multilineTextAlignment(.center)
                        .padding(14)
                }
            }
    }

    @ViewBuilder
    private var guestLine: some View {
        if state.tracking == .tooDark {
            // Tracking truth outranks anything the guest might say.
            GuestLine("It’s gone dark — I can’t see. A light, or a step back?",
                      size: 19, onDark: true, alignment: .center, maxSize: 26)
                .fixedSize(horizontal: false, vertical: true)
                .shadow(color: .black.opacity(0.6), radius: 12, y: 2)
        } else if let feed, showsPlan {
            LiveGuestLineView(feed: feed, defaultLine: state.guestLine)
                .fixedSize(horizontal: false, vertical: true)
                .shadow(color: .black.opacity(0.6), radius: 12, y: 2)
        } else {
            GuestLine(state.guestLine, size: 19, onDark: true, alignment: .center, maxSize: 26)
                .fixedSize(horizontal: false, vertical: true)
                .shadow(color: .black.opacity(0.6), radius: 12, y: 2)
        }
    }

    private var coverage: some View {
        HStack(spacing: 22) {
            meter("Floor", state.floor)
            meter("Walls", state.walls)
            meter("Corners", state.corners)
        }
        .accessibilityElement(children: .ignore)
        .accessibilityLabel("Seen so far: floor \(percent(state.floor)), walls \(percent(state.walls)), corners \(percent(state.corners))")
    }

    private func meter(_ label: String, _ coverage: SurfaceCoverage) -> some View {
        VStack(spacing: 6) {
            Capsule()
                .fill(Color.rsOnDusk.opacity(0.22))
                .frame(width: 46, height: 4)
                .overlay(alignment: .leading) {
                    Capsule().fill(Color.rsOnDusk)
                        .frame(width: 46 * fraction(coverage), height: 4)
                }
            Text(label)
                .rsFont(.ui, size: 12, weight: .medium, maxSize: 16)
                .foregroundStyle(Color.rsOnDusk.opacity(0.88))
        }
        .shadow(color: .black.opacity(0.45), radius: 6, y: 1)
    }

    private func fraction(_ coverage: SurfaceCoverage) -> Double {
        switch coverage {
        case .empty:          return 0
        case .partial(let f): return min(max(f, 0), 1)
        case .full:           return 1
        }
    }

    private func percent(_ coverage: SurfaceCoverage) -> String {
        "\(Int((fraction(coverage) * 100).rounded())) percent"
    }
}

#Preview("Tracking") {
    LiveCaptureView()
}

#Preview("Too dark") {
    LiveCaptureView(state: CaptureHUDState(tracking: .tooDark))
}
