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
///
/// BUILT BUT NOT YET REACHABLE from this flow (staged, not wired): the
/// returning-home recent-rooms strip and RoomsListView / QRBridgeView (§9, need a
/// GET /scenes fetch + trigger points), WhySignInSheet / AccountConflictView
/// (§8 — BOTH are unreachable: SignInSheet handles the conflict with two stock
/// `.alert`s and never presents AccountConflictView), and ColdStartView (§1 — the flow
/// opens directly at .home; identity is minted lazily on first send, so the
/// cold-start splash has no trigger). These have no entry point here and appear
/// only in their own previews.

import ARKit
import SwiftUI

struct RootFlowView: View {
    @StateObject private var capture     = CaptureManager()
    @StateObject private var coordinator = UploadCoordinator()
    @ObservedObject private var poller   = ScenePoller.shared
    @ObservedObject private var failures = UploadFailureMonitor.shared

    @ObservedObject private var auth = AuthManager.shared
    @Environment(\.scenePhase) private var scenePhase

    @State private var stage: Stage = .home
    @State private var showGuidance = false
    @State private var showProfile  = false
    /// The bundle id sent for processing — used to restart polling after a fatal
    /// poll error without depending on the current CaptureManager.
    @State private var sentBundleId: String?

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
        .onChange(of: scenePhase) { _, phase in
            // ScenePoller's contract: pause polling when backgrounded. Driven off
            // the POLLER's own state, not `stage`: the user can leave the wait
            // (stage == .home) while a poll loop is still live, and a stage-gated
            // guard would then never pause it.
            guard poller.currentBundleId != nil else { return }
            switch phase {
            case .active:                ScenePoller.shared.resume()
            case .background, .inactive: ScenePoller.shared.pause()
            @unknown default:            break
            }
        }
    }

    /// Start (or restart) capture with its start cue (spec §3/§10 — haptic + tone
    /// as the first ink strokes land).
    private func beginCapture() {
        RSHaptics.fire(.captureStart)
        RSSound.play(.captureStart)
        capture.startCapture()
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
                }
            )
        case .gotRoom:
            GotTheRoomView(onContinue: { stage = .review })
        case .review:
            ReviewView(
                metrics: reviewMetrics,
                // Neutral verdict: the app has no coverage signal (task #13), so it
                // must not assert "clean / whole room". Once coverage lands, drive
                // verdict + thinCoverage from it.
                verdict: isEmptyCapture
                    ? "I didn't catch anything on that pass — nothing to send yet. Let's walk the room again."
                    : "Here's your capture. Send it, and I'll start making sense of it on your desk.",
                // An empty capture cannot be sent: the backend would reject it as
                // invalid and the user would be told "the scan didn't survive the
                // trip" — blaming the trip for a capture that was empty before it
                // left. Emptiness is checkable here, and needs no coverage signal.
                canSend: !isEmptyCapture,
                // HONEST LABEL: CaptureManager.startCapture() mints a new bundleId
                // and clears frames/anchors/outputDir — this REPLACES the pass, it
                // does not extend it. True append (preserving bundleId + frames) is
                // the activation follow-up; until then the label must not promise
                // additive behaviour it doesn't have.
                addMoreLabel: "Scan again from scratch",
                onSend: sendItHome,
                onAddMore: {
                    stage = .capturing
                    beginCapture()
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
                    onDismiss: { Task { await UploadFailureMonitor.shared.dismiss() } }
                )
                .padding([.horizontal, .top], 20)
            }
            HomeView(
                onScan: { showGuidance = true },
                onProfile: { showProfile = true }
            )
        }
        // The kick from onFatalBlobError cannot outlive the process, so without this
        // independent store scan a failure from a previous launch (crash, dead
        // battery mid-upload) would never surface — exactly the case the banner
        // exists for. Mirrors what UploadFailureView does for the old ContentView.
        .task { await UploadFailureMonitor.shared.refresh() }
        .sheet(isPresented: $showGuidance) {
            GuidanceSheet(
                onStart: {
                    showGuidance = false
                    beginCapture()
                    stage = .capturing
                },
                onDismiss: { showGuidance = false }
            )
            .presentationDetents([.medium, .large])
            .presentationDragIndicator(.visible)
        }
        .sheet(isPresented: $showProfile) {
            NavigationStack {
                ProfileView(
                    uid: auth.currentUID,
                    isLinked: auth.isAppleLinked,
                    onClose: { showProfile = false }
                )
            }
        }
    }

    // MARK: - Post-send (driven by ScenePoller)

    @ViewBuilder
    private var postSend: some View {
        if case .failed(_, let terminal) = coordinator.sessionState {
            if terminal {
                // A 4xx the server will never accept — retrying provably cannot
                // work, so this is a terminal screen, not an invitation to retry.
                FailureView(
                    kind: .terminal,
                    onPrimary: rescanFromScratch,
                    onSecondary: { stage = .home }
                )
            } else {
                // Session/upload SETUP failed (sign-in, network, or the bundle
                // wasn't written yet — the send-before-bundle-ready race, which
                // yields .failed("No bundle on disk") and self-heals on retry).
                // Nothing was uploaded, so this uses the honest .sendFailed copy,
                // NOT .connectionTrouble (which claims the room is safely "in line").
                WaitingView(phase: .sendFailed,
                            onTryNow: { sendItHome() },
                            onLeave: { stage = .home })
            }
        } else if let failure = failures.latestFailure, failure.bundleId == sentBundleId {
            // The blobs for THIS bundle failed terminally, so bundle.pb will never
            // land, no Scene doc is ever created, and the poller would 404 → keep
            // polling forever (it never hard-gives-up by design). Stop the poll and
            // show a terminal screen — a banner floated over a live "getting in
            // line" wait would leave the user waiting for a room that cannot arrive.
            FailureView(
                kind: .terminal,
                onPrimary: rescanFromScratch,
                onSecondary: { stage = .home }
            )
            .onAppear { ScenePoller.shared.reset() }
        } else {
            ZStack(alignment: .top) {
                pollPostSend
                // A terminal blob failure for a DIFFERENT (earlier) bundle is
                // otherwise invisible here — float it over the wait.
                if failures.latestFailure != nil {
                    UploadFailedBanner(
                        onDismiss: { Task { await UploadFailureMonitor.shared.dismiss() } }
                    )
                    .padding([.horizontal, .top], 20)
                }
            }
        }
    }

    @ViewBuilder
    private var pollPostSend: some View {
        switch poller.pollState {
        case .idle, .polling:
            WaitingView(phase: waitingPhase,
                        anchor: waitingAnchor,
                        onLeave: { stage = .home })
        case .succeeded:
            DoorwayView(onStepThrough: openWebDesk,
                        onScanAnother: returnHomeFromDoorway,
                        signedIntoWeb: auth.isAppleLinked,
                        canOpenWeb: webRoomURL != nil)
        case .failedTerminal:
            FailureView(
                kind: .terminal,
                onPrimary: rescanFromScratch,
                onSecondary: { stage = .home }
            )
        case .recoverable:
            // failed_incomplete: an incomplete upload, not a bad scan. No region is
            // named and no partial re-upload exists yet, so the one honest path is a
            // full rescan (FailureView.recoverable copy owns the honesty).
            FailureView(
                kind: .recoverable,
                onPrimary: rescanFromScratch,
                onSecondary: { stage = .home }
            )
        case .pollError:
            // pollError is fatal — the poll loop has already stopped. The room WAS
            // uploaded (we got far enough to poll it), so .connectionTrouble ("lost
            // my line to the desk… your room is safe") is the honest copy here.
            // Offer a real retry that restarts polling, not a dead "Try now".
            // pollingStopped swaps the "I'll keep trying quietly" reassurance —
            // nothing is trying once the loop is fatal.
            WaitingView(phase: .connectionTrouble,
                        anchor: waitingAnchor,
                        pollingStopped: true,
                        onTryNow: { if let id = sentBundleId { ScenePoller.shared.start(bundleId: id) } },
                        onLeave: { stage = .home })
        }
    }

    private var waitingPhase: WaitingView.Phase {
        // .idle is the pre-upload window: sendItHome resets the poller synchronously
        // and only starts it after the awaited session setup returns .ready. Mapping
        // that to .analyzing would tell the user "It's here — all of it" before a
        // single byte has left the phone.
        guard case let .polling(latest, _, _, longRunning, connectionTrouble) = poller.pollState else {
            return .sending
        }
        if connectionTrouble { return .connectionTrouble }
        if longRunning       { return .longRunning }
        if latest == .queued { return .queued }
        return .analyzing
    }

    /// The SERVER-side scene start, or nil when it isn't known yet. Never falls back
    /// to a client-side moment: the elapsed clock is only honest counted from the
    /// scene's real creation time (the rule SceneStatusView already follows), and
    /// WaitingView renders no clock while this is nil.
    private var waitingAnchor: Date? {
        guard case let .polling(_, _, sceneCreatedAt, _, _) = poller.pollState else { return nil }
        return sceneCreatedAt
    }

    // MARK: - Actions

    private func sendItHome() {
        stage = .sent
        // Drop the previous capture's poll + session state SYNCHRONOUSLY, before the
        // Task. beginUploadSession only writes pollState at its very end (after
        // sign-in + manifest + POST), so without this reset postSend would render
        // the prior room's .succeeded/.failedTerminal/.pollError for the whole setup
        // window — and a stale "Try now" could re-poll the wrong bundle. reset()
        // (not pause()) is required: pause() deliberately preserves state.
        sentBundleId = nil
        ScenePoller.shared.reset()
        coordinator.reset()
        Task {
            await coordinator.beginUploadSession(for: capture)
            // Only start polling if the session was actually created. On failure
            // sessionState == .failed and postSend surfaces it — no phantom poll.
            if case .ready = coordinator.sessionState {
                let bundleId = capture.bundleIdString
                sentBundleId = bundleId
                ScenePoller.shared.start(bundleId: bundleId)
            }
        }
    }

    private func rescanFromScratch() {
        // Reset the poll loop (not just pause) so the failed capture's terminal
        // state can't linger; the next send starts a fresh poll with the new id.
        ScenePoller.shared.reset()
        stage = .capturing
        beginCapture()
    }

    /// Return to home from the doorway (a successful capture). Resets the poller
    /// so the next capture can send cleanly — resume() early-returns on .succeeded,
    /// so without this a second capture would be impossible without a force-quit.
    private func returnHomeFromDoorway() {
        ScenePoller.shared.reset()
        sentBundleId = nil
        stage = .home
    }

    /// The web URL for the room that was just sent, or nil when no web origin is
    /// configured (see NetworkConfig.webBaseURL — nil today).
    private var webRoomURL: URL? {
        guard let id = sentBundleId else { return nil }
        return NetworkConfig.webRoomURL(bundleId: id)
    }

    /// Open the room on the web. A plain `open(_:)` — no associated-domains
    /// entitlement needed (that governs links this app CLAIMS). Inert only because
    /// no durable web origin is configured yet, and the CTA hides in that case, so
    /// this is never a dead button.
    private func openWebDesk() {
        guard let url = webRoomURL else { return }
        UIApplication.shared.open(url)
    }

    // MARK: - Derived display state

    private var hudState: CaptureHUDState {
        // ARKit hands us a REASON; don't discard it and assert a cause.
        // .notAvailable is the not-yet-tracking state every session reports right
        // after run() — treating it as "lost" made a fully lit room's first message
        // "It's gone dark". Only .insufficientFeatures is actually about light.
        let quality: TrackingQuality = switch capture.trackingState {
        case .normal:
            .good
        case .limited(.excessiveMotion):
            .slowDown
        case .limited(.insufficientFeatures):
            .tooDark
        case .limited(.initializing), .limited(.relocalizing):
            .finding
        case .limited:
            .finding
        case .notAvailable:
            .finding
        @unknown default:
            .finding
        }
        // Real coverage + steering are unwired until the RoomPlan coverage wiring
        // (task #13). Show neutral-empty, never fabricated "far wall" progress.
        return CaptureHUDState(
            tracking: quality,
            guestLine: "Move slowly and I'll sketch the room as you go.",
            floor: .empty, walls: .empty, corners: .empty
        )
    }

    /// Nothing was captured. This is an EMPTINESS check, not a quality threshold —
    /// it needs no coverage signal and no tuned judgement.
    private var isEmptyCapture: Bool { capture.frameCount == 0 }

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
}

#Preview("Home (flow root)") {
    RootFlowView()
}
