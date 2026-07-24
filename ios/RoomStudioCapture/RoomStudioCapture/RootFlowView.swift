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
/// opens directly at .home, and identity is minted by the app-level launch task,
/// so nothing ever waits on a splash). These have no entry point here and appear
/// only in their own previews.

import ARKit
import SwiftUI

struct RootFlowView: View {
    @StateObject private var capture     = CaptureManager()
    /// @StateObject, NOT @State: @State stores the reference and invalidates only on
    /// assignment, so it does not subscribe to objectWillChange — a per-send @State
    /// instance made every sessionState change invisible, and with it every send
    /// failure. Cross-send clobbering is handled where the writes happen instead
    /// (UploadCoordinator's callSequence).
    @StateObject private var coordinator = UploadCoordinator()
    @ObservedObject private var poller   = ScenePoller.shared
    @ObservedObject private var failures = UploadFailureMonitor.shared

    @ObservedObject private var auth = AuthManager.shared
    @Environment(\.scenePhase) private var scenePhase
    @Environment(\.dynamicTypeSize) private var typeSize

    @State private var stage: Stage = .home
    @State private var showGuidance = false
    @State private var showProfile  = false
    /// The bundle id sent for processing — used to restart polling after a fatal
    /// poll error without depending on the current CaptureManager.
    @State private var sentBundleId: String?
    /// Last server-side scene start seen while polling. `pollState` drops it on the
    /// transition to `.pollError`, but the room really did arrive at that time — so
    /// keeping it here is what lets the poll-error screen show the elapsed clock and
    /// its "keeps its place in line" reassurance instead of silently hiding both.
    @State private var lastSceneCreatedAt: Date?
    /// Incremented per send. Guards exactly one write — the post-await bookkeeping
    /// below. Session-state staleness is handled inside UploadCoordinator, where
    /// those writes actually happen.
    @State private var sendGeneration: Int = 0

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
            // Visibility tracks the scene phase as well as the view lifetime. Without
            // this, pause() cleared isVisible with nothing restoring it, and — because
            // currentBundleId is nil for the whole .sending window — a backgrounded app
            // could still have isVisible true when the completion kick landed, starting
            // the FOREGROUND-only poll loop while backgrounded (against ScenePoller's
            // own contract).
            let onWaitScreen = (stage == .sent)
            switch phase {
            case .active:
                ScenePoller.shared.setVisible(onWaitScreen)
                if poller.currentBundleId != nil { ScenePoller.shared.resume() }
            case .background, .inactive:
                ScenePoller.shared.setVisible(false)
                if poller.currentBundleId != nil { ScenePoller.shared.pause() }
            @unknown default:
                break
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
                    // Don't fire the peak joyful beat ("I've got the room") for a
                    // capture that got nothing — review tells the truth instead.
                    stage = capture.frameCount == 0 ? .review : .gotRoom
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
                verdict: reviewVerdict,
                // An empty capture cannot be sent: the backend would reject it as
                // invalid and the user would be told "the scan didn't survive the
                // trip" — blaming the trip for a capture that was empty before it
                // left. Emptiness is checkable here, and needs no coverage signal.
                //
                // Also withheld while bundle.pb is still being written: stopCapture()
                // assembles it asynchronously on jpegQueue, and for a large capture
                // that can outlast the 1.8 s got-the-room hold. Sending early hits
                // beginUploadSession's "No bundle on disk" guard and shows a send
                // FAILURE for a capture that is perfectly fine and merely unfinished.
                canSend: !isEmptyCapture && !isPreparingBundle && capture.assemblyFailure == nil,
                isPreparing: isPreparingBundle,
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
                },
                onLeave: { stage = .home }
            )
        case .sent:
            postSend
        }
    }

    private var homeScreen: some View {
        VStack(spacing: 0) {
            if failures.latestFailure != nil {
                UploadFailedBanner(
                    reason: failures.latestFailure?.reason,
                    onDismiss: { Task { await UploadFailureMonitor.shared.dismiss() } }
                )
                .padding([.horizontal, .top], 20)
            }
            if sentBundleId != nil {
                // Re-entry. Without this, leaving the wait was one-way: the room
                // keeps processing but no surface could ever show it again, so
                // "leaving is free" was false.
                Button { stage = .sent } label: {
                    HStack(spacing: 9) {
                        Circle().fill(Color.rsGold).frame(width: 7, height: 7)
                        Text("One room is on its way — check on it")
                            .font(RSFont.ui(.subheadline, weight: .medium))
                            .foregroundStyle(Color.rsInk)
                        Spacer()
                        Image(systemName: "chevron.right")
                            .font(.system(size: 12, weight: .semibold))
                            .foregroundStyle(Color.rsInk.opacity(0.4))
                    }
                    .padding(.horizontal, 14).padding(.vertical, 11)
                    .background(Color.rsSurface.opacity(0.9), in: RoundedRectangle(cornerRadius: 12, style: .continuous))
                    .overlay(RoundedRectangle(cornerRadius: 12, style: .continuous).stroke(Color.rsHairline, lineWidth: 1))
                }
                .padding([.horizontal, .top], 20)
            }
            HomeView(
                onScan: { showGuidance = true },
                onProfile: { showProfile = true }
            )
        }
        // The banner and re-entry rows live in this wrapper, OUTSIDE HomeView's own
        // backdrop — without this they sat on bare white with a hard seam where the
        // parchment began.
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .rsParchmentScreen()
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
            // At accessibility sizes the .medium detent leaves almost no room for
            // content once the pinned CTA is placed — open large instead.
            .presentationDetents(typeSize.isAccessibilitySize ? [.large] : [.medium, .large])
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

    /// The routing DECISION is a pure function (WaitFlowState) so it can be pinned
    /// by tests and read as a table; this property only maps that decision to views.
    private var waitScreen: WaitScreen {
        WaitFlowState.screen(
            sessionFailure: WaitFlowState.sessionFailure(from: coordinator.sessionState),
            terminalBlobFailureForThisBundle: sentBundleId != nil
                && failures.latestFailure?.bundleId == sentBundleId,
            deferredForThisBundle: sentBundleId != nil
                && failures.latestDeferral?.bundleId == sentBundleId,
            poll: WaitFlowState.snapshot(from: poller.pollState,
                                         fallbackAnchor: lastSceneCreatedAt)
        )
    }

    @ViewBuilder
    private var postSend: some View {
        ZStack(alignment: .top) {
            postSendScreen
                // The completion kick (BlobUploadManager.onBundleComplete →
                // notifyBundleComplete) only starts polling when the poller believes
                // a status surface is visible. Nothing else sets this at cold launch,
                // so without it the kick no-ops and — now that sendItHome no longer
                // polls eagerly — polling would never begin.
                .onAppear {
                    ScenePoller.shared.setVisible(true)
                    // INDEPENDENT of the completion kick. The kick (onBundleComplete →
                    // notifyBundleComplete) is dropped when no status surface is
                    // visible, so a user who leaves the wait mid-upload would never
                    // get polling started again. Reading the persisted `.complete`
                    // record is the same seam SceneStatusView uses.
                    Task { await resumePollIfUploadFinished() }
                }
                .onDisappear { ScenePoller.shared.setVisible(false) }
                .onChange(of: poller.pollState) { old, _ in retainAnchor(from: old) }
            // A terminal blob failure for a DIFFERENT (earlier) bundle is otherwise
            // invisible here — float it over whatever this capture is doing.
            if let failure = failures.latestFailure, failure.bundleId != sentBundleId {
                UploadFailedBanner(
                    reason: failure.reason,
                    onDismiss: { Task { await UploadFailureMonitor.shared.dismiss() } }
                )
                .padding([.horizontal, .top], 20)
            }
        }
    }

    @ViewBuilder
    private var postSendScreen: some View {
        switch waitScreen {
        case .sending:
            // Covers both the session setup AND the blob upload: the poller is
            // deliberately not started until the upload completes, so nothing here
            // may claim the room has arrived.
            WaitingView(phase: .sending, onLeave: { stage = .home })

        case .waiting(let phase, let anchor):
            WaitingView(phase: phase.waitingPhase,
                        anchor: anchor,
                        onTryNow: { ScenePoller.shared.checkNow() },
                        onLeave: { stage = .home })

        case .checkFailed(let anchor, let stopped):
            // The room WAS uploaded, so "your room is safe up there" is honest;
            // `stopped` swaps the "I'll keep trying quietly" half, and drives whether
            // Try now resumes the loop or just fires an immediate tick.
            WaitingView(phase: .connectionTrouble,
                        anchor: anchor,
                        pollingStopped: stopped,
                        onTryNow: {
                            // Fall back to the poller's own bundle: a loop started by
                            // the completion kick can outlive/predate this view's
                            // sentBundleId, and both branches being skipped left a
                            // live-looking button doing nothing.
                            if stopped, let id = sentBundleId ?? poller.currentBundleId {
                                ScenePoller.shared.start(bundleId: id)
                            } else {
                                ScenePoller.shared.checkNow()
                            }
                        },
                        onLeave: { stage = .home })

        case .doorway:
            DoorwayView(onStepThrough: openWebDesk,
                        onScanAnother: rescanFromScratch,
                        signedIntoWeb: auth.isAppleLinked,
                        canOpenWeb: webRoomURL != nil)

        case .processingFailed:
            FailureView(kind: .terminal,
                        onPrimary: rescanFromScratch,
                        onSecondary: endFlight)

        case .incompleteUpload:
            // failed_incomplete: an incomplete upload, not a bad scan. No region is
            // named and no partial re-upload exists yet, so the one honest path is a
            // full rescan (FailureView.recoverable copy owns the honesty).
            FailureView(kind: .recoverable,
                        onPrimary: rescanFromScratch,
                        onSecondary: endFlight)

        case .uploadFailed:
            // The blobs for THIS bundle failed terminally: bundle.pb never lands, no
            // Scene doc is ever created, and the poller would 404 → keep polling
            // forever (it never hard-gives-up by design). Stop it and say so — with
            // upload-honest copy and the reason, since the banner is suppressed here.
            FailureView(kind: .uploadFailed(reason: failures.latestFailure?.reason),
                        onPrimary: rescanFromScratch,
                        onSecondary: endFlight)
                .onAppear { ScenePoller.shared.reset() }

        case .sendFailed(let terminal):
            // Nothing was uploaded, so never the "didn't survive the trip" copy.
            // terminal == a 4xx retrying cannot fix (our bug); the capture stays on
            // disk for the relaunch rehydration path either way.
            WaitingView(phase: terminal ? .sendFailedTerminal : .sendFailed,
                        onTryNow: { if !terminal { sendItHome() } },
                        onLeave: endFlight)

        case .sendPaused:
            // Paused until the next launch — ending the flight is honest here:
            // rehydrateAllUnfinishedBundles picks the bundle up on relaunch, and
            // nothing in THIS process will move it.
            WaitingView(phase: .sendPaused, onLeave: endFlight)
        }
    }

    /// The server anchor as currently published by the poller (nil unless polling).
    private var waitingAnchor: Date? {
        guard case let .polling(_, _, sceneCreatedAt, _, _) = poller.pollState else { return nil }
        return sceneCreatedAt
    }

    /// Mirror the server anchor into @State so it survives the transition to
    /// .pollError (which carries no payload). See `lastSceneCreatedAt`.
    /// Reads the OUTGOING state: on the polling → pollError transition the new state
    /// carries no anchor, so retaining from the old value is what makes the clock
    /// survive that exact hop rather than relying on an earlier tick having done it.
    private func retainAnchor(from previous: ScenePollState) {
        if case let .polling(_, _, sceneCreatedAt, _, _) = previous,
           let sceneCreatedAt, sceneCreatedAt != lastSceneCreatedAt {
            lastSceneCreatedAt = sceneCreatedAt
        }
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
        lastSceneCreatedAt = nil   // per-send, not per-view: a retained anchor from a
                                   // previous capture would time THIS room's clock
                                   // from the previous room's arrival.
        ScenePoller.shared.reset()
        UploadFailureMonitor.shared.clearDeferral()
        coordinator.reset()
        // Snapshot the id SYNCHRONOUSLY. Reading capture.bundleIdString after the
        // await let a "leave → scan again" in the gap mint a new bundleId, so this
        // capture's task would record the NEXT capture's id — poisoning the blob-
        // failure match, the deep link, and the poll restart.
        let bundleId = capture.bundleIdString
        // Set NOW, not after the mint returns: the 0038 ladder can hold that POST for
        // ~a minute, and leaving in that window previously left the capture invisible
        // on every surface (no re-entry row, no banner, no record to scan).
        sentBundleId = bundleId
        sendGeneration &+= 1
        let generation = sendGeneration
        Task {
            await coordinator.beginUploadSession(for: capture)
            // A newer send superseded this one while it was in flight; its writes
            // must not clobber the current capture's state.
            guard generation == sendGeneration else { return }
            // Record the bundle, but do NOT start polling yet. The blobs are still
            // uploading (bundle.pb goes last, decision 0041), so no Scene document
            // can exist: every poll would 404 → .notCreated → latest stays .queued →
            // the screen would say "Getting in line / I'll start the moment there's
            // room" for the whole upload (~1 min on the real 126-frame capture),
            // while nothing had reached the desk. Polling begins on the completion
            // kick (BlobUploadManager.onBundleComplete → notifyBundleComplete),
            // which is the architecture SceneStatusView already uses.
            if case .ready = coordinator.sessionState {
                sentBundleId = bundleId
            }
        }
    }

    /// If the blobs for the sent bundle already finished while no status surface was
    /// mounted, start polling now. Safe to call repeatedly: ScenePoller.start is
    /// idempotent for the same bundle, and a record that isn't `.complete` is a no-op.
    private func resumePollIfUploadFinished() async {
        guard let bundleId = sentBundleId,
              case .idle = ScenePoller.shared.pollState,
              let record = try? await UploadSessionStore.shared.load(bundleId: bundleId),
              record.uploadPhase == .complete
        else { return }
        ScenePoller.shared.start(bundleId: bundleId)
    }

    private func rescanFromScratch() {
        // Ends the old flight (poller, sent id, anchor, deferral) before starting a
        // new capture — otherwise home would keep advertising the abandoned bundle.
        endFlight()
        stage = .capturing
        beginCapture()
    }

    /// End the current flight and go home. EVERY terminal exit must use this: the
    /// home re-entry row and the blob-failure match both key off `sentBundleId`, so
    /// leaving it set after a failure left home advertising "One room is on its way"
    /// for a bundle that will never arrive — and re-entering showed a permanent
    /// "Sending your room" for it.
    private func endFlight() {
        ScenePoller.shared.reset()
        UploadFailureMonitor.shared.clearDeferral()
        sentBundleId = nil
        lastSceneCreatedAt = nil
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

    /// Frames exist but bundle.pb hasn't been published yet (stopCapture assembles
    /// it off the main queue). Transient — the publish flips it, UNLESS assembly
    /// failed, which is terminal and reported separately.
    private var isPreparingBundle: Bool {
        !isEmptyCapture && capture.bundlePath == nil && capture.assemblyFailure == nil
    }

    private var reviewVerdict: String {
        if isEmptyCapture {
            return "I didn't catch anything on that pass — nothing to send yet. Let's walk the room again."
        }
        if let failure = capture.assemblyFailure {
            // Terminal: the publish will never come, so this must not read as a wait.
            return "I couldn't pack this one up to send — \(failure). Let's walk the room again."
        }
        if isPreparingBundle {
            return "Packing it up — one moment before it can travel."
        }
        return "Here's your capture. Send it, and I'll start making sense of it on your desk."
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
}

#Preview("Home (flow root)") {
    RootFlowView()
}
