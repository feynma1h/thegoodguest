/// The navigation spine (decision 0072). Binds the Good Guest screens to the real
/// managers and drives the flow:
///
///   home → guidance → capturing → gotRoom → review → (Send it home)
///        → post-send: waiting (ScenePoller) → doorway / failure
///
/// WHERE THE UPLOAD BEGINS: not when stopCapture() publishes bundlePath, but on
/// review's "Send it home", which is where the design puts the decision.
/// stopCapture() still assembles the bundle; RootFlowView holds it at review
/// until the user sends.
///
/// THIS IS THE APP ROOT (activated 2026-07-25). The former gate — "a non-LiDAR
/// device would see UnsupportedDeviceView" — stopped being a blocker when the
/// product became Pro/LiDAR-only (decision 0071): that screen is now the CORRECT
/// behaviour on unsupported hardware, not a regression. The simulator is treated
/// as supported so development continues without a device.
///
/// Remaining activation follow-ups: add-more resume-with-progress
/// (CaptureManager.startCapture currently mints a new bundle rather than
/// extending) and the real web-handoff universal link (NetworkConfig.webBaseURL
/// is nil, so the doorway hides its CTA). The live floor plan sits behind
/// LiveMeshHost, fed by capture.floorPlanFeed, with the coverage ticks driven
/// from the live census below.
///
/// The §8/§9 history surfaces are WIRED, all three off one RoomsStore fetch of
/// GET /scenes: the returning-home recent-rooms strip, RoomsListView behind
/// "all N rooms", and WhySignInSheet on the first return home with a room and
/// an unlinked identity. A ready room's chevron is gated on
/// NetworkConfig.webBaseURL exactly as the doorway's CTA is — with no web
/// origin configured, rows inform rather than offer a tap that lands nowhere.
///
/// STILL STAGED, and not on that fetch: QRBridgeView (§9), whose blocker is
/// deep-link infrastructure and the associated-domains entitlement, not a room
/// list — the desk names the room in the link it hands over. It has no entry
/// point here and appears only in its own preview.
///
/// §1's cold start is not on that list, in either direction. The flow still
/// opens directly at .home and identity is still minted by the app-level launch
/// task, so nothing here WAITS on a splash — but the splash is real, and it is
/// wrapped around this view by the app entry point rather than routed to from
/// inside it. See SplashView.
///
/// §8's conflict SCREEN is not on that list: it is not built at all
/// (decision 0216), because the count it was designed around cannot be obtained
/// without becoming the account it asks about. SignInSheet owns the conflict.
/// ReviewView's THIN-COVERAGE variant belongs to the staged list too:
/// `thinCoverage` is never passed true below. A coverage signal does
/// exist — the live census drives the FLOOR/WALLS/CORNERS ticks on the capture
/// screen — but promoting it to a quality VERDICT is a copy claim deliberately
/// left unwired, so the "I've got the bones, but a few gaps" treatment renders
/// only in that file's preview.

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
    /// What this identity has sent (GET /scenes). Feeds three surfaces — the
    /// home strip, the rooms list, and the sign-in invitation's count — from one
    /// fetch, so they cannot disagree about how many rooms the user has.
    @ObservedObject private var rooms    = RoomsStore.shared

    @ObservedObject private var auth = AuthManager.shared
    @Environment(\.scenePhase) private var scenePhase
    @Environment(\.dynamicTypeSize) private var typeSize

    @State private var stage: Stage = .home
    @State private var showGuidance = false
    /// Where home has navigated to. Empty is home itself.
    ///
    /// A typed array rather than NavigationPath: the path only ever holds one
    /// kind of thing, and the erased form makes every append need an annotation
    /// while letting an unrelated Hashable compile.
    @State private var path: [HomeRoute] = []
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
    /// True when the sent bundle's PERSISTED record is terminal. Read from disk by
    /// `refreshSentBundlePhase`, because the in-memory failure kick is dismissable
    /// and its absence must not be read as "still uploading".
    @State private var sentBundleFailedOnDisk = false
    /// Launch-scoped latch for `restoreUnfinishedBundle`. home's `.task` re-fires on
    /// every return to `.home`, so without this the restore undid `endFlight()` the
    /// instant it landed — re-adopting the bundle the user had just finished with.
    @State private var didRestoreUnfinished = false
    /// What the `failed_incomplete` screen can offer (decisions 0084 + 0116).
    ///
    /// Starts `.unavailable` — the state that promises nothing — and is raised to
    /// `.available` only once CaptureRecovery has confirmed on disk that every
    /// missing file is still here. The disk check is async, so the screen can
    /// render its rescan-only form for a frame before flipping; that direction
    /// is chosen deliberately. Defaulting to `.available` would show a promise
    /// the phone might not be able to keep, and a promise withdrawn is worse
    /// than one that arrives a frame late.
    @State private var resendState: FailureCopy.Resend = .unavailable

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
        // The 0074 stand-down lives on the ROOT view, not on postSend: the poll loop
        // deliberately outlives the wait screen (the user can leave with a room in
        // flight), so terminal-not-ours can land while any stage is showing. Home is
        // where the phantom row renders, and it must clear there too.
        .onChange(of: poller.pollState) { _, newState in
            if WaitFlowState.standsDownAutomatically(newState) { standDownNotOurs() }
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
                // The completion kick is DROPPED while backgrounded (by design — the
                // persisted record is the seam), resume() early-returns on a nil
                // currentBundleId, and postSend.onAppear does not re-fire because the
                // view never left the hierarchy. Without this re-scan, locking the
                // phone during the ~1 min upload — which the copy explicitly invites —
                // left "Sending your room" on screen forever for a room already
                // uploaded. The .idle guard inside makes it safe to call every time.
                if onWaitScreen { Task { await resumePollIfUploadFinished() } }
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
                feed: capture.floorPlanFeed,
                onFinish: {
                    RSHaptics.fire(.finish)
                    capture.stopCapture()
                    // Don't fire the peak joyful beat ("I've got the room") for a
                    // capture that got nothing — review tells the truth instead.
                    stage = capture.frameCount == 0 ? .review : .gotRoom
                }
            )
            // RoomPlan's 10 s tracking-failure self-abort (decision 0076) ends the
            // capture from the MODEL side — route exactly as a user Finish would,
            // minus the joy haptic (an abort is not a celebration). The user path
            // has already moved `stage` by the time this change lands, so the
            // stage guard makes it abort-only.
            .onChange(of: capture.isRunning) { _, running in
                if !running, stage == .capturing {
                    stage = capture.frameCount == 0 ? .review : .gotRoom
                }
            }
        case .gotRoom:
            GotTheRoomView(onContinue: { stage = .review })
        case .review:
            ReviewView(
                metrics: reviewMetrics,
                // Non-nil exactly when a built room ships (tier LIDAR_ROOMPLAN);
                // publishes when RoomBuilder lands, which the "Packing it up"
                // hold already outlasts. The floor plan follows the same rule —
                // "the room you got" is what the server will see.
                census: capture.builtCensus?.reviewLine,
                floorPlan: capture.builtFloorPlan,
                // Neutral verdict, still: a coverage signal now exists (the live
                // census + floor plan), but turning it into a quality VERDICT
                // ("clean" / thinCoverage) is a copy claim that deserves an
                // operator decision — deliberately deferred.
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
                // REPLACES, does not extend: startCapture() mints a new bundleId and
                // clears frames/anchors/outputDir. True append is an activation
                // follow-up; the label must not promise additive behaviour.
                rescanLabel: "Scan again from scratch",
                onSend: sendItHome,
                onRescan: {
                    stage = .capturing
                    beginCapture()
                },
                onLeave: { stage = .home }
            )
        case .sent:
            postSend
        }
    }

    /// What today looks like, reduced to what home's sentence and the contents
    /// sheet actually read. One value feeds both, so the two cannot disagree
    /// about whether anything needs the user.
    private var homeDay: HomeDay {
        let screen = waitScreen
        let hasFlight = sentBundleId != nil && SurfaceRouter.isInFlight(screen)
        // Two independent sources of "needs you": the flight this launch, if it
        // ended in a note, and a terminal failure persisted from an earlier one.
        // Counted separately because they are different rooms.
        var needs = 0
        if sentBundleId != nil, SurfaceRouter.needsUser(screen) { needs += 1 }
        if let failure = failures.latestFailure, failure.bundleId != sentBundleId { needs += 1 }
        return HomeDay(
            needsYou: needs,
            hasUnseenArrival: sentBundleId != nil && screen == .doorway,
            hasRoomInFlight: hasFlight,
            roomCount: rooms.state.knownCount,
            // First run is "nothing has ever been sent", and an unknown count
            // is not that: a failed fetch must never produce the screen that
            // says you have never scanned anything.
            isFirstRun: rooms.state.knownCount == 0 && sentBundleId == nil
        )
    }

    /// The notes waiting for the user, newest first.
    private var openNotes: [NoteKind] {
        var notes: [NoteKind] = []
        if sentBundleId != nil, case .note(let kind) = SurfaceRouter.placement(for: waitScreen) {
            // The placement deliberately carries no reason — it is read here,
            // at the one call site that has the monitor.
            if case .uploadFailed = kind {
                notes.append(.uploadFailed(reason: failures.latestFailure?.reason))
            } else {
                notes.append(kind)
            }
        }
        if let failure = failures.latestFailure, failure.bundleId != sentBundleId {
            notes.append(.uploadFailed(reason: failure.reason))
        }
        return notes
    }

    /// Where home can push to. A route rather than a set of booleans: these are
    /// screens on a stack now, not sheets over a screen, and the stack needs
    /// something Hashable to hold.
    enum HomeRoute: Hashable { case contents, house, desk, notes, recovery, you }

    private var homeScreen: some View {
        NavigationStack(path: $path) {
            HomeView(
                day: homeDay,
                onScan: { showGuidance = true },
                onOpenContents: { path.append(.contents) },
                onFollowLine: { path.append(route(for: $0)) }
            )
            .navigationBarHidden(true)
            .navigationDestination(for: HomeRoute.self) { route in
                destination(route)
                    .navigationBarHidden(true)
            }
        }
        // The kick from onFatalBlobError cannot outlive the process, so without
        // this independent store scan a failure from a previous launch (crash,
        // dead battery mid-upload) would never surface — exactly the case the
        // notes screen exists for.
        .task { await UploadFailureMonitor.shared.refresh() }
        .task {
            await restoreUnfinishedBundle()
            await refreshSentBundlePhase()
        }
        // Re-fires on every return to home, which is what makes a room the user
        // just sent appear in the house without a relaunch. Single-flighted in
        // the store, so bouncing between screens cannot stack fetches.
        .task { await rooms.refresh() }
        .sheet(isPresented: $showGuidance) {
            GuidanceSheet(
                onStart: {
                    showGuidance = false
                    beginCapture()
                    stage = .capturing
                },
                onDismiss: { showGuidance = false }
            )
            .presentationDetents(typeSize.isAccessibilitySize ? [.large] : [.medium, .large])
            .presentationDragIndicator(.visible)
        }
    }

    /// The pushed screens.
    ///
    /// Every one of them takes `back` for its own header rather than relying on
    /// the system bar: the bars are hidden throughout, because a screen whose
    /// title is set in the guest's display serif cannot be rendered by a
    /// navigation bar without losing the voice.
    @ViewBuilder
    private func destination(_ screen: HomeRoute) -> some View {
        switch screen {
        case .contents:
            ContentsScreen(day: homeDay,
                           onOpen: { path.append(route(for: $0)) },
                           onBack: back)
        case .house:
            RoomsListView(state: rooms.state,
                          canOpenWeb: canOpenAnyRoomOnWeb,
                          onOpen: openRoomOnWeb,
                          onRetry: refreshRooms,
                          onScanAnother: { path = []; showGuidance = true },
                          onProfile: { path.append(.you) },
                          onClose: back)
        case .desk:
            // With a room in flight the desk IS the post-send surface, which
            // owns the poller's lifecycle; without one there is nothing to
            // hand over to, so the clear state is drawn here in the stack.
            if sentBundleId != nil {
                Color.clear.onAppear { path = []; stage = .sent }
            } else {
                DeskView(state: nil,
                         onOpenHouse: { path = [.house] },
                         onClose: back)
            }
        case .notes:
            NotesView(needsYou: openNotes,
                      arrival: nil,
                      canOpenArrival: canOpenAnyRoomOnWeb,
                      onAcknowledge: acknowledge,
                      onOpenNote: { _ in path = [.notes, .recovery] },
                      onClose: back)
        case .recovery:
            // The one note that opens a screen rather than being acknowledged:
            // whether the missing bytes can be re-sent is a question about this
            // phone's disk, and the answer carries two different offers.
            let actions = FailureCopy.recoverableActions(resendState)
            FailureView(
                kind: .recoverable(missingCount: missingPaths.count, resend: resendState),
                onPrimary: { performRecovery(actions.primary) },
                onSecondary: { performRecovery(actions.secondary) }
            )
            .task(id: missingPaths.count) { await refreshResendOffer() }

        case .you:
            ProfileView(uid: auth.currentUID, isLinked: auth.isLinked, onClose: back)
        }
    }

    /// One step back, or all the way home if something already emptied the path.
    private func back() {
        if path.isEmpty { return }
        path.removeLast()
    }

    // MARK: - Going places

    /// Home's sentence, followed. The doorway is not a route — it is the
    /// post-send surface deciding for itself what to show.
    private func route(for destination: HomeDestination) -> HomeRoute {
        switch destination {
        case .notes:          return .notes
        case .house:          return .house
        case .desk, .doorway: return .desk
        }
    }

    /// A contents entry, as a route.
    private func route(for entry: ContentsEntry) -> HomeRoute {
        switch entry {
        case .house: return .house
        case .desk:  return .desk
        case .notes: return .notes
        case .you:   return .you
        }
    }

    /// Acknowledge a note, for good.
    ///
    /// Permanent rather than session-local: the old banner returned on every
    /// launch because it interrupted a screen the user came to for something
    /// else. A note is a screen they navigated to on purpose, so a tap here is
    /// a statement that they have read it.
    private func acknowledge(_ kind: NoteKind) {
        Task { await UploadFailureMonitor.shared.dismiss() }
        if sentBundleId != nil, SurfaceRouter.needsUser(waitScreen) {
            endFlight()
        }
        // Last note acknowledged: nothing left on this screen to read.
        if openNotes.count <= 1 { back() }
    }

    // MARK: - Rooms

    /// The doorway's `canOpenWeb`, asked once for the history surfaces. Nil
    /// webBaseURL is the deliberate state today (NetworkConfig), so this is
    /// false and every row informs rather than offering a dead tap.
    private var canOpenAnyRoomOnWeb: Bool { NetworkConfig.webBaseURL != nil }

    private func refreshRooms() { Task { await rooms.refresh() } }

    private func openRoomOnWeb(_ room: RoomSummary) {
        guard let bundleId = room.bundleId,
              let url = NetworkConfig.webRoomURL(bundleId: bundleId) else { return }
        UIApplication.shared.open(url)
    }

    // MARK: - Post-send (driven by ScenePoller)

    /// The routing DECISION is a pure function (WaitFlowState) so it can be pinned
    /// by tests and read as a table; this property only maps that decision to views.
    private var waitScreen: WaitScreen {
        WaitFlowState.screen(
            sessionFailure: WaitFlowState.sessionFailure(from: coordinator.sessionState),
            // Persisted OR in-memory: dismissing the banner clears the kick for the
            // rest of the launch, and routing that read only the kick then fell
            // through to "Sending your room" forever for a bundle whose on-disk
            // record is .failed and which will never move again.
            terminalBlobFailureForThisBundle: sentBundleId != nil
                && (failures.latestFailure?.bundleId == sentBundleId
                    || sentBundleFailedOnDisk),
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
                    // record is the seam that does not depend on the kick.
                    Task { await resumePollIfUploadFinished() }
                }
                .onDisappear { ScenePoller.shared.setVisible(false) }
                .onChange(of: poller.pollState) { old, _ in retainAnchor(from: old) }
                // Mirror the SAME routing decision the screen just made onto the
                // Lock Screen. Driving the activity off waitScreen rather than off
                // the raw poll state is the point: two surfaces narrating one
                // capture from two different derivations is how they come to
                // disagree. `initial: true` because the screen the user lands on
                // is itself news (a relaunch straight into `.waiting`).
                .onChange(of: waitScreen, initial: true) { _, screen in
                    LiveActivityController.shared.noteWaitScreen(screen, bundleId: sentBundleId)
                }
            // A terminal failure for a DIFFERENT bundle no longer floats here.
            // It is a note, counted into home's sentence and read on the notes
            // screen — a failure belonging to an earlier room has no business
            // interrupting the wait for this one.
        }
    }

    @ViewBuilder
    private var postSendScreen: some View {
        switch SurfaceRouter.placement(for: waitScreen) {
        case .desk(let deskState):
            DeskView(state: deskState,
                     roomTitle: flightTitle,
                     onAct: { deskAction(deskState) },
                     onOpenHouse: { leaveFlight(); path = [.house] },
                     onClose: { leaveDesk(deskState) })

        case .doorway:
            DoorwayView(onStepThrough: openWebDesk,
                        onScanAnother: rescanFromScratch,
                        onDone: endFlight,
                        signedIntoWeb: auth.isLinked,
                        canOpenWeb: webRoomURL != nil)

        case .note:
            // A room that has finished and failed is a note, not a screen the
            // user is held on. Hand them straight to it: they were watching
            // this room, so the kindest thing is to show them what happened
            // rather than bounce them home to be told something needs them.
            ParchmentBackground()
                .onAppear { toNotes() }

        case .nowhere:
            // Terminal-not-ours (decision 0074): the root-level onChange stands
            // this down on the same publish that produced it, so this renders
            // for at most a frame on the way home.
            ParchmentBackground()
        }
    }

    /// The room in flight, titled the way the house titles it, so one room
    /// reads identically wherever it appears.
    private var flightTitle: String? {
        guard sentBundleId != nil else { return nil }
        return RoomHistory.title(sentAt: lastSceneCreatedAt ?? Date(),
                                 now: Date(), withTime: false)
    }

    /// The desk's one control, where it has one.
    private func deskAction(_ state: DeskState) {
        switch state {
        case .retryableSendFailure:
            sendItHome()
        case .checkFailed(_, let stopped):
            if stopped, let id = sentBundleId ?? poller.currentBundleId {
                ScenePoller.shared.start(bundleId: id)
            } else {
                ScenePoller.shared.checkNow()
            }
        case .sending, .working, .paused, .rateLimited:
            break
        }
    }

    /// Leaving the desk, which is NOT the same as being done with the room.
    ///
    /// A room that is still moving keeps moving: the user just stops watching,
    /// and home's sentence still points back here. Only the states that will
    /// not move again on their own end the flight, which is what acknowledges
    /// the record and lets the reaper reclaim it — ending a live flight would
    /// orphan a room that was about to arrive.
    private func leaveDesk(_ state: DeskState) {
        switch state {
        case .sending, .working, .checkFailed:
            stage = .home
        case .paused, .rateLimited, .retryableSendFailure:
            endFlight()
        }
    }

    /// Leave the flight without acknowledging it, then go home.
    private func leaveFlight() { stage = .home }

    /// Show the notes, from wherever.
    private func toNotes() {
        stage = .home
        path = [.notes]
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
        #if DEBUG
        // Staging (failed_invalid): corrupt a frame IN PLACE, same byte length,
        // before the manifest reads sizes off disk. No-op unless the flag is set.
        StagingHooks.applyPreSendSabotage(outputDir: capture.bundleOutputDir)
        #endif
        // Drop the previous capture's poll + session state SYNCHRONOUSLY, before the
        // Task. beginUploadSession only writes pollState at its very end (after
        // sign-in + manifest + POST), so without this reset postSend would render
        // the prior room's .succeeded/.failedTerminal/.pollError for the whole setup
        // window — and a stale "Try now" could re-poll the wrong bundle. reset()
        // (not pause()) is required: pause() deliberately preserves state.
        sentBundleId = nil
        sentBundleFailedOnDisk = false
        lastSceneCreatedAt = nil   // per-send, not per-view: a retained anchor from a
                                   // previous capture would time THIS room's clock
                                   // from the previous room's arrival.
        resendState = .unavailable // same reason: never inherit a re-send state.
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
        // Declare the flight to the poller (after reset(), which cleared the prior
        // expectation): a PREVIOUS capture's resumed upload completing mid-flight
        // must not start polling the old bundle and flash its doorway over this
        // capture's wait. See ScenePoller.expectedBundleId.
        ScenePoller.shared.expectBundle(bundleId)
        // The Lock Screen card starts HERE, not when the mint returns: minting a
        // long walk's manifest measured 14 s, and that is exactly the window in
        // which a user locks the phone and wants to know something is happening.
        LiveActivityController.shared.begin(bundleId: bundleId)
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
            // kick (BlobUploadManager.onBundleComplete → notifyBundleComplete).
            if case .ready = coordinator.sessionState {
                sentBundleId = bundleId
            }
        }
    }

    /// Re-adopt a bundle left behind by a previous launch, newest first — one
    /// whose upload finished while the app was dead. Restoring the id is enough:
    /// the home re-entry row renders from it, and entering the wait resumes
    /// polling from the persisted record.
    ///
    /// ONCE PER LAUNCH, and never for a bundle the user has finished with. home's
    /// `.task` re-fires on every return to `.home`, and `.complete` records are never
    /// deleted, so an unlatched restore that ignored acknowledgement undid every
    /// terminal exit on arrival and re-advertised finished rooms forever. See
    /// BundleRestore for the full reasoning; the choice itself is pinned there.
    ///
    /// Skips `.failed` (the banner owns those via UploadFailureMonitor) and never
    /// overwrites a send started this launch.
    private func restoreUnfinishedBundle() async {
        guard !didRestoreUnfinished else { return }
        didRestoreUnfinished = true
        guard sentBundleId == nil,
              let ids = try? await UploadSessionStore.shared.allBundleIds()
        else { return }
        var candidates: [BundleRestore.Candidate] = []
        for id in ids {
            guard let record = try? await UploadSessionStore.shared.load(bundleId: id) else { continue }
            candidates.append(.init(bundleId: id,
                                    phase: record.uploadPhase,
                                    minted: record.clientMintTimestamp))
        }
        let pick = BundleRestore.pick(from: candidates, dismissed: DismissedBundles().set)
        // Adopt the Lock Screen card belonging to the restored flight (its
        // background upload outlived the process, so the card is still live and
        // still correct) and end any other. Deliberately AFTER the pick, so a
        // launch that restores nothing clears the leftovers. If the scan above
        // failed outright we skip this and leave the card alone — a stale card is
        // a smaller wrong than ending a live upload's only visible surface.
        LiveActivityController.shared.reconcileOnLaunch(restoredBundleId: pick)
        // Re-check: the scan awaited disk, and a send started in that window owns
        // sentBundleId.
        if let pick, sentBundleId == nil {
            sentBundleId = pick
        }
    }

    /// Refresh the persisted terminal state for the sent bundle (see
    /// `sentBundleFailedOnDisk`). Cheap, and the only source of truth that survives
    /// a dismissed banner.
    private func refreshSentBundlePhase() async {
        guard let bundleId = sentBundleId else {
            sentBundleFailedOnDisk = false
            return
        }
        let record = try? await UploadSessionStore.shared.load(bundleId: bundleId)
        sentBundleFailedOnDisk = (record?.uploadPhase == .failed)
    }

    /// If the blobs for the sent bundle already finished while no status surface was
    /// mounted, start polling now. Safe to call repeatedly: ScenePoller.start is
    /// idempotent for the same bundle, and a record that isn't `.complete` is a no-op.
    private func resumePollIfUploadFinished() async {
        await refreshSentBundlePhase()
        guard let bundleId = sentBundleId,
              case .idle = ScenePoller.shared.pollState,
              let record = try? await UploadSessionStore.shared.load(bundleId: bundleId),
              record.uploadPhase == .complete
        else { return }
        ScenePoller.shared.start(bundleId: bundleId)
    }

    // MARK: - failed_incomplete recovery (decisions 0084 + 0116)

    /// The paths the poller is currently reporting missing.
    ///
    /// Read from the POLLER, not from `waitScreen`: WaitFlowState deliberately
    /// narrows `.recoverable` to a count, because a count is all ROUTING needs
    /// and blob paths are plumbing that must never reach copy. The ACTION does
    /// need them, and reading them here — one hop, at the call site that sends
    /// them — keeps the routing table pure rather than widening it to carry an
    /// input only this button uses.
    private var missingPaths: [String] {
        if case .recoverable(let paths) = poller.pollState { return paths }
        return []
    }

    /// Which bundle the recovery acts on: the one the POLLER asked about.
    ///
    /// The paths and the id have to come from the same answer. `sentBundleId`
    /// can name a different capture than the poll loop is on — the loop
    /// deliberately outlives the wait screen, and decision 0074's stand-down
    /// exists precisely because those two can disagree — and re-sending one
    /// bundle's blobs against another's record would fail the plan's
    /// manifest check at best, and cross two captures at worst. Falls back to
    /// the flight only if the poller has already been reset.
    private var recoveryBundleId: String? {
        poller.currentBundleId ?? sentBundleId
    }

    /// Ask CaptureRecovery whether a re-send can honestly be offered, and say so.
    ///
    /// This is the honesty constraint's enforcement point: the screen's promise
    /// is downstream of an actual disk check, so a capture whose files were
    /// reclaimed, never restored (an iCloud-migrated record, decision 0074), or
    /// swept gets the rescan copy rather than a button that cannot work.
    private func refreshResendOffer() async {
        // A re-send in flight or just failed already describes THIS screen's
        // state; the disk cannot contradict it, and overwriting would drop the
        // user's own attempt out of the copy mid-send.
        if resendState == .inFlight || resendState == .failed { return }
        guard let bundleId = recoveryBundleId,
              let record = try? await UploadSessionStore.shared.load(bundleId: bundleId)
        else {
            resendState = .unavailable
            return
        }
        let outputDir = record.outputDir
        let plan = CaptureRecovery.plan(
            missingPaths: missingPaths,
            manifestPaths: record.manifestPaths,
            fileExists: { FileManager.default.fileExists(
                atPath: outputDir.appendingPathComponent($0).path) }
        )
        if case .resend = plan {
            resendState = .available
        } else {
            resendState = .unavailable
        }
    }

    /// Bind one of FailureCopy's actions to what it actually does.
    private func performRecovery(_ action: FailureCopy.Action) {
        switch action {
        case .resend: resendMissingFiles()
        case .rescan: rescanFromScratch()
        case .leave:  endFlight()
        }
    }

    /// Send the missing files again.
    ///
    /// USER-INITIATED, deliberately. An automatic re-send would spend a unit of
    /// the account's daily mint quota and re-upload on whatever network the
    /// phone happens to be on, without the user ever being told the first
    /// attempt fell short — and if it failed the same way it would do it again
    /// on every launch. A tap is also the acknowledgement that makes the
    /// subsequent "Sending your room" screen honest.
    private func resendMissingFiles() {
        // Read both from the poller's answer, in this order: `missingPaths` is
        // only meaningful for the bundle the poller reported them for.
        guard let bundleId = recoveryBundleId else { return }
        let paths = missingPaths
        resendState = .inFlight
        Task {
            let outcome = await BlobUploadManager.shared.resendMissingBlobs(
                bundleId: bundleId, missingPaths: paths)
            switch outcome {
            case .started:
                // Hand the screen back to the ordinary send surfaces. The poller
                // is parked in its terminal `.recoverable` state, so resetting it
                // is what lets `waitScreen` fall back through `.idle` to
                // `.sending` — and re-declaring the expectation is required
                // because reset() clears it (see ScenePoller.expectedBundleId).
                // Polling restarts on the completion kick when bundle.pb lands
                // again, exactly as it does for a first send.
                resendState = .unavailable
                ScenePoller.shared.reset()
                ScenePoller.shared.expectBundle(bundleId)
                // The card was ended when the failure published a terminal
                // stage, so a fresh one is needed rather than an update: real
                // bytes are moving again, and this is precisely the window in
                // which the phone gets locked.
                LiveActivityController.shared.begin(bundleId: bundleId)
            case .refused:
                // The plan changed its mind between the offer and the tap
                // (files disappeared). The rescan copy is the honest fallback.
                resendState = .unavailable
            case .failed:
                resendState = .failed
            }
        }
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
        // Reclaim decision BEFORE clearing (clearFlight resets the poller, which
        // would blank the screen this decision reads). Keyed on the screen the
        // user is LEAVING — the terminal outcome they have actually seen
        // (decision 0084; table in CaptureReclaim). incompleteUpload retains its
        // files for the future re-upload coordinator by that same table.
        let leavingScreen = waitScreen
        // Acknowledge BEFORE clearing: this is the one place that knows the user is
        // done with this bundle, and the record can outlive the app (an
        // unreclaimed record would otherwise be re-adopted by the launch restore
        // forever).
        if let sentBundleId {
            DismissedBundles().acknowledge(sentBundleId)
            if CaptureReclaim.reclaimsAtFlightEnd(leavingScreen) {
                let bundleId = sentBundleId
                Task { await CaptureReaper.shared.reclaim(bundleId: bundleId) }
            }
        }
        // The user has SEEN the outcome — the same trigger the reaper uses. Leaving
        // the card up past that point would be the Lock Screen still reporting on a
        // room the user has already closed the book on.
        LiveActivityController.shared.end(bundleId: sentBundleId)
        clearFlight()
        stage = .home
    }

    /// Clear the in-memory flight state (poller, ids, anchor, deferral) without
    /// navigating. endFlight() adds the acknowledgment and the return home.
    private func clearFlight() {
        ScenePoller.shared.reset()
        UploadFailureMonitor.shared.clearDeferral()
        sentBundleId = nil
        sentBundleFailedOnDisk = false
        lastSceneCreatedAt = nil
        // Per-flight, like the anchor above: a retained `.failed`/`.available`
        // would describe the PREVIOUS capture's re-send on the next one's screen.
        resendState = .unavailable
    }

    /// Decision-0074 stand-down: the polled room belongs to a different identity
    /// (a by-bundle 403 on a verified token — e.g. UploadSessionStore records
    /// migrated by an iCloud backup while the Firebase identity minted fresh).
    /// Definitive, so acknowledge the record with the doorway-Done semantics and
    /// clear the flight; without the acknowledgment, the launch restore re-adopts
    /// the foreign room on every cold launch forever. Navigation is conditional:
    /// the poll loop outlives the wait screen, so this can fire while the user is
    /// mid-capture — clearing state must never yank them out of a live scan.
    private func standDownNotOurs() {
        if let foreignId = WaitFlowState.foreignBundleToAcknowledge(
            pollerBundleId: poller.currentBundleId, sentBundleId: sentBundleId) {
            DismissedBundles().acknowledge(foreignId)
            // A card narrating a room this identity will never own is exactly the
            // phantom decision 0074 exists to kill — end it, don't narrate it.
            LiveActivityController.shared.end(bundleId: foreignId)
        }
        clearFlight()
        if stage == .sent { stage = .home }
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
        // Coverage from the live census: the floor is binary, walls/corners
        // fill toward a closed room's worth.
        // Steering (guidance/moments) rides floorPlanFeed into LiveCaptureView;
        // this guestLine is the DEFAULT the priority table falls back to.
        let cover = FloorPlanVoice.coverage(census: capture.liveCensus,
                                            cornerCount: capture.liveCornerCount)
        return CaptureHUDState(
            tracking: quality,
            guestLine: "Move slowly and I'll sketch the room as you go.",
            floor: cover.floor, walls: cover.walls, corners: cover.corners
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
