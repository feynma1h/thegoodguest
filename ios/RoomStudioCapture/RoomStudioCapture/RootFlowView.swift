/// The navigation spine (decision 0072). Binds the Good Guest screens to the real
/// managers and drives the flow:
///
///   home → guidance → capturing → gotRoom → review → (Send it home)
///        → post-send: waiting (ScenePoller) → doorway / failure
///
/// KEY BEHAVIORAL CHANGE vs the old ContentView: the upload no longer begins
/// automatically when stopCapture() publishes bundlePath — it begins on review's
/// "Send it home", which is where the design puts the decision. stopCapture()
/// still assembles the bundle; RootFlowView holds it at review until the user
/// sends.
///
/// NOT THE APP ROOT YET. ContentView remains the live root. Swapping to
/// RootFlowView is the ACTIVATION step, deliberately coupled to LiDAR-device
/// verification (task #13 / board item 3): on a non-LiDAR device this gates
/// straight to UnsupportedDeviceView, which would remove capture from the only
/// current test device. Activation follow-ups: relaunch poll-resume (restart
/// polling for a bundle still processing after a cold launch), add-more
/// resume-with-progress (CaptureManager.startCapture currently resets), and the
/// real web-handoff universal link. Verified today via the temp-entry preview
/// path on the simulator (dev-override), same as every screen.

import ARKit
import SwiftUI

struct RootFlowView: View {
    @StateObject private var capture     = CaptureManager()
    @StateObject private var coordinator = UploadCoordinator()
    @ObservedObject private var poller   = ScenePoller.shared
    @ObservedObject private var failures = UploadFailureMonitor.shared

    @State private var stage: Stage = .home
    @State private var showGuidance = false
    @State private var showProfile  = false

    enum Stage: Equatable { case home, capturing, gotRoom, review, sent }

    /// The device gate. The simulator is treated as supported so the flow can be
    /// developed without LiDAR hardware; real non-LiDAR devices see the honest
    /// unsupported screen (decision 0072). The Info.plist install-time gate is a
    /// separate release step.
    private var deviceSupported: Bool {
        #if targetEnvironment(simulator)
        return true
        #else
        return LiDARGate.isSupported
        #endif
    }

    var body: some View {
        Group {
            if !deviceSupported {
                UnsupportedDeviceView()
            } else {
                flow
            }
        }
    }

    // MARK: - Flow

    @ViewBuilder
    private var flow: some View {
        switch stage {
        case .home:
            homeScreen
        case .capturing:
            LiveCaptureView(
                state: hudState,
                onFinish: {
                    RSHaptics.fire(.finish)
                    capture.stopCapture()
                    stage = .gotRoom
                },
                onRecenter: {}
            )
        case .gotRoom:
            GotTheRoomView(onContinue: { stage = .review })
        case .review:
            ReviewView(
                metrics: reviewMetrics,
                onSend: sendItHome,
                onAddMore: {
                    // CaptureManager.startCapture() currently resets progress;
                    // true resume-with-progress is an activation follow-up.
                    stage = .capturing
                    capture.startCapture()
                }
            )
        case .sent:
            postSend
        }
    }

    private var homeScreen: some View {
        VStack(spacing: 0) {
            if failures.latestFailure != nil {
                UploadFailedBanner(
                    onRetry: { retryFailedUpload() },
                    onDismiss: { Task { await UploadFailureMonitor.shared.dismiss() } }
                )
                .padding([.horizontal, .top], 20)
            }
            HomeView(
                onScan: { showGuidance = true },
                onProfile: { showProfile = true }
            )
        }
        .sheet(isPresented: $showGuidance) {
            GuidanceSheet(
                onStart: {
                    showGuidance = false
                    capture.startCapture()
                    stage = .capturing
                },
                onDismiss: { showGuidance = false }
            )
            .presentationDetents([.medium, .large])
            .presentationDragIndicator(.visible)
        }
        .sheet(isPresented: $showProfile) {
            NavigationStack { ProfileView(onClose: { showProfile = false }) }
        }
    }

    // MARK: - Post-send (driven by ScenePoller)

    @ViewBuilder
    private var postSend: some View {
        switch poller.pollState {
        case .idle, .polling:
            WaitingView(phase: waitingPhase, anchor: waitingAnchor)
        case .succeeded:
            DoorwayView(onStepThrough: openWebDesk)
        case .failedTerminal:
            FailureView(
                kind: .terminal(cause: "the mirror"),
                onPrimary: rescanFromScratch,
                onSecondary: { stage = .home }
            )
        case .recoverable(let missing):
            FailureView(
                kind: .recoverable(region: recoverableRegion(missing)),
                onPrimary: rescanFromScratch,
                onSecondary: { stage = .home }
            )
        case .pollError:
            WaitingView(phase: .connectionTrouble,
                        onTryNow: { ScenePoller.shared.checkNow() },
                        onLeave: { stage = .home })
        }
    }

    private var waitingPhase: WaitingView.Phase {
        guard case let .polling(latest, _, _, longRunning, connectionTrouble) = poller.pollState else {
            return .analyzing
        }
        if connectionTrouble { return .connectionTrouble }
        if longRunning       { return .longRunning }
        if latest == .queued { return .queued }
        return .analyzing
    }

    private var waitingAnchor: Date {
        guard case let .polling(_, since, sceneCreatedAt, _, _) = poller.pollState else { return .now }
        return sceneCreatedAt ?? since
    }

    // MARK: - Actions

    private func sendItHome() {
        stage = .sent
        let bundleId = capture.bundleIdString
        Task {
            await coordinator.beginUploadSession(for: capture)
            ScenePoller.shared.start(bundleId: bundleId)
        }
    }

    private func retryFailedUpload() {
        // Re-drive the upload for the failed bundle; the coordinator's fast path
        // reuses the persisted session record.
        Task { await coordinator.beginUploadSession(for: capture) }
    }

    private func rescanFromScratch() {
        // No poller reset API; pause the current loop. The next send starts a
        // fresh poll with the new bundle id.
        ScenePoller.shared.pause()
        stage = .capturing
        capture.startCapture()
    }

    private func openWebDesk() {
        // Universal-link handoff is enrollment/entitlement-gated (associated-domains).
        // Wire the real link on activation (decision 0072); no-op seam for now.
    }

    // MARK: - Derived display state

    private var hudState: CaptureHUDState {
        let quality: TrackingQuality = switch capture.trackingState {
        case .normal:       .good
        case .limited:      .slowDown
        case .notAvailable: .lost
        @unknown default:   .lost
        }
        // Coverage is placeholder until the RoomPlan coverage wiring (task #13).
        return CaptureHUDState(tracking: quality)
    }

    private var reviewMetrics: String {
        "\(capture.frameCount) frames · \(tierLabel)"
    }

    private var tierLabel: String {
        switch capture.tier {
        case .lidarRoomplan: return "LiDAR + RoomPlan"
        case .lidarArkit:    return "LiDAR"
        default:             return "Standard"
        }
    }

    private func recoverableRegion(_ missing: [String]) -> String {
        missing.count <= 1 ? "One corner" : "\(missing.count) parts of the room"
    }
}

#Preview("Home (flow root)") {
    RootFlowView()
}
