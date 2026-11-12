/// The navigation spine. Binds the screens to the real managers and drives the
/// flow:
///
///   home (your rooms) → before you start → scanning → review → Send it
///        → that room's own screen: sending, being rebuilt, ready or needs you
///
/// THE 2026-11-10 REDESIGN changed where things are shown, not how a room
/// travels. Home is the navigation root and lists the rooms; a sent room opens
/// its own screen in that stack instead of replacing the app, and the person
/// can go back to their rooms at any point while it keeps moving. Every rule
/// below about the flight — when polling starts, what a terminal exit
/// acknowledges and reclaims, the stand-down of a room that is not ours, the
/// disk-checked re-send — is the one this file has always kept.
///
/// WHERE THE UPLOAD BEGINS: on review's "Send it", which is where the person
/// makes the decision. stopCapture() assembles the bundle; review holds it.
///
/// EVERY IPHONE (operator ruling, 2026-11-10). The LiDAR gate is gone: a phone
/// without LiDAR scans with the camera, has no live plan, and sends a bundle of
/// tier ARKIT_ONLY. Decisions 0071 and 0072 made the app Pro-only; this is
/// their reversal.
///
/// The conflict SCREEN for sign-in is not built (decision 0216); the account
/// sheet owns the conflict, in system alerts.

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
    /// What this identity has sent (GET /scenes): the rooms on home.
    @ObservedObject private var rooms    = RoomsStore.shared
    @ObservedObject private var auth = AuthManager.shared
    @Environment(\.scenePhase) private var scenePhase

    @State private var stage: Stage = .home
    @State private var showGuidance = false
    @State private var showAccount = false
    /// Where home has navigated to. Empty is home itself.
    @State private var path: [Route] = []
    /// The bundle id sent for processing — used to restart polling after a fatal
    /// poll error without depending on the current CaptureManager.
    @State private var sentBundleId: String?
    /// When this launch sent it, so its card is named like any other room.
    @State private var flightSentAt: Date?
    /// Last server-side scene start seen while polling. `pollState` drops it on the
    /// transition to `.pollError`, but the room really did arrive at that time — so
    /// keeping it here is what lets the room screen keep its elapsed clock.
    @State private var lastSceneCreatedAt: Date?
    /// Incremented per send. Guards exactly one write — the post-await bookkeeping.
    @State private var sendGeneration: Int = 0
    /// True when the sent bundle's PERSISTED record is terminal. Read from disk by
    /// `refreshSentBundlePhase`, because the in-memory failure kick is dismissable
    /// and its absence must not be read as "still uploading".
    @State private var sentBundleFailedOnDisk = false
    /// Launch-scoped latch for `restoreUnfinishedBundle`: home's `.task` re-fires
    /// on every return, and an unlatched restore re-adopted finished rooms.
    @State private var didRestoreUnfinished = false
    /// What the missing-files state can offer (decisions 0084 + 0116). Starts
    /// `.unavailable`, the state that promises nothing, and is raised only once
    /// CaptureRecovery has confirmed on disk that every missing file is here.
    @State private var resendState: FailureCopy.Resend = .unavailable

    enum Stage: Equatable { case home, capturing, review }

    /// Where home can push to.
    enum Route: Hashable {
        /// The room this phone is sending or watching.
        case flight
        /// A send from an earlier launch that failed.
        case earlierFailure
        /// A room the server has, by scene id.
        case room(String)
    }

    var body: some View {
        flow
            // The 0074 stand-down lives on the ROOT view: the poll loop outlives
            // every screen, so terminal-not-ours can land while anything shows.
            .onChange(of: poller.pollState) { _, newState in
                if WaitFlowState.standsDownAutomatically(newState) { standDownNotOurs() }
                // A room that just finished: ask for the list now, so its card
                // reads Ready, and once more when its picture has had time to
                // be drawn (8-36 s measured; it is drawn after ready, not with it).
                if case .succeeded = newState {
                    refreshRooms()
                    Task {
                        try? await Task.sleep(for: .seconds(45))
                        await rooms.refresh()
                    }
                }
            }
            .onChange(of: poller.pollState) { old, _ in retainAnchor(from: old) }
            // Mirror the routing decision onto the Lock Screen, from the same
            // derivation the room screen uses, so the two cannot disagree.
            .onChange(of: waitScreen, initial: true) { _, screen in
                guard let sentBundleId else { return }
                LiveActivityController.shared.noteWaitScreen(screen, bundleId: sentBundleId)
            }
            .onChange(of: pollerShouldWatch, initial: true) { _, watch in
                ScenePoller.shared.setVisible(watch)
                if watch { Task { await resumePollIfUploadFinished() } }
            }
            .onChange(of: scenePhase) { _, phase in
                // ScenePoller's contract: pause polling when backgrounded, driven
                // off the poller's own state rather than the screen.
                switch phase {
                case .active:
                    ScenePoller.shared.setVisible(pollerShouldWatch)
                    if poller.currentBundleId != nil { ScenePoller.shared.resume() }
                    // The completion kick is dropped while backgrounded; re-scan
                    // the persisted record so a room uploaded while the phone was
                    // locked does not read "Sending" forever.
                    if pollerShouldWatch { Task { await resumePollIfUploadFinished() } }
                case .background, .inactive:
                    ScenePoller.shared.setVisible(false)
                    if poller.currentBundleId != nil { ScenePoller.shared.pause() }
                @unknown default:
                    break
                }
            }
    }

    /// The status surface is on screen whenever home (with its flight card) or
    /// the flight's own screen is: both report the room as it moves.
    private var pollerShouldWatch: Bool {
        stage == .home && sentBundleId != nil
    }

    /// Start (or restart) capture with its start cue (haptic + tone).
    private func beginCapture() {
        RSHaptics.fire(.captureStart)
        RSSound.play(.captureStart)
        capture.startCapture()
    }

    /// The camera behind the scan screen. In a Debug build with live boxes on,
    /// their camera (decision 0301), which renders the same session; otherwise
    /// the plain camera, in every build.
    private var cameraLayer: AnyView {
        #if DEBUG
        if LiveBoxesFeature.isEnabled { return AnyView(LiveBoxesCamera(capture: capture)) }
        #endif
        return AnyView(CameraFeedView(session: capture.arSession))
    }

    // MARK: - Flow

    @ViewBuilder
    private var flow: some View {
        switch stage {
        case .home:
            homeStack
        case .capturing:
            LiveCaptureView(
                state: hudState,
                feed: capture.floorPlanFeed,
                showsPlan: capture.tier != .arkitOnly,
                onFinish: finishCapture,
                onStop: {
                    capture.stopCapture()
                    stage = .home
                },
                cameraLayer: cameraLayer
            )
            // RoomPlan's 10 s tracking-failure self-abort (decision 0076) ends the
            // capture from the MODEL side — route exactly as a user Finish would.
            .onChange(of: capture.isRunning) { _, running in
                if !running, stage == .capturing { stage = .review }
            }
        case .review:
            ReviewView(
                content: ReviewCopy.content(
                    frames: capture.frameCount,
                    tier: capture.tier,
                    census: capture.builtCensus,
                    hasPlan: capture.builtFloorPlan.map { !$0.isEmpty } ?? false,
                    boxes: boxCount,
                    isPreparing: isPreparingBundle,
                    assemblyFailure: capture.assemblyFailure
                ),
                floorPlan: capture.builtFloorPlan,
                onSend: sendItHome,
                onRescan: {
                    stage = .capturing
                    beginCapture()
                },
                onDiscard: { stage = .home }
            )
        }
    }

    private func finishCapture() {
        RSHaptics.fire(.finish)
        capture.stopCapture()
        // The joyful beat only for a capture that got something; review tells
        // the truth otherwise. It used to be a 1.8 s screen of its own.
        if capture.frameCount > 0 {
            RSHaptics.fire(.gotTheRoom)
            RSSound.play(.enough)
        }
        stage = .review
    }

    /// The pieces boxed, where the build can box them.
    private var boxCount: Int? {
        #if DEBUG
        return LiveBoxesFeature.isEnabled ? capture.capturedPersonBoxes.count : nil
        #else
        return nil
        #endif
    }

    // MARK: - Home

    private var homeStack: some View {
        NavigationStack(path: $path) {
            TimelineView(.periodic(from: .now, by: 30)) { timeline in
                HomeScreen(
                    content: homeContent(now: timeline.date),
                    onScan: { showGuidance = true },
                    onOpenAccount: { showAccount = true },
                    onOpenCard: open,
                    onRetry: refreshRooms,
                    onRefresh: { await rooms.refresh() }
                )
            }
            .navigationDestination(for: Route.self) { route in
                destination(route)
            }
        }
        .tint(Color.rsInk)
        // The kick from onFatalBlobError cannot outlive the process, so a
        // failure from a previous launch is found by scanning the store.
        .task { await UploadFailureMonitor.shared.refresh() }
        .task {
            await restoreUnfinishedBundle()
            await refreshSentBundlePhase()
        }
        // Re-fires on every return to home, which is what makes a room just
        // sent appear without a relaunch. Single-flighted in the store.
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
            .presentationDragIndicator(.visible)
        }
        .sheet(isPresented: $showAccount) {
            AccountSheet()
        }
    }

    private func homeContent(now: Date) -> HomeContent {
        let flight = sentBundleId.map {
            HomeFlight(bundleId: $0,
                       placement: SurfaceRouter.placement(for: waitScreen),
                       sentAt: flightSentAt ?? lastSceneCreatedAt)
        }
        let earlier = failures.latestFailure
            .flatMap { $0.bundleId == sentBundleId ? nil : HomeEarlierFailure(bundleId: $0.bundleId, reason: $0.reason) }
        return RoomCards.content(rooms: rooms.state, flight: flight, earlierFailure: earlier, now: now)
    }

    private func open(_ card: HomeCard) {
        switch card.destination {
        case .flight:          path.append(.flight)
        case .earlierFailure:  path.append(.earlierFailure)
        case .room(let room):  path.append(.room(room.id))
        }
    }

    @ViewBuilder
    private func destination(_ route: Route) -> some View {
        switch route {
        case .flight:
            flightScreen
        case .earlierFailure:
            RoomScreen(title: "A room you scanned",
                       status: RoomStatusCopy.needsYou(.uploadFailed(reason: failures.latestFailure?.reason)),
                       onAction: earlierFailureAction)
        case .room(let sceneId):
            if let room = rooms.state.knownRooms?.first(where: { $0.id == sceneId }) {
                listedRoomScreen(room)
            } else {
                // The list refreshed under the person and the room left it.
                Color.rsGround.onAppear { path = [] }
            }
        }
    }

    // MARK: - The flight's own screen

    @ViewBuilder
    private var flightScreen: some View {
        switch SurfaceRouter.placement(for: waitScreen) {
        case .desk(let state):
            TimelineView(.periodic(from: .now, by: 15)) { timeline in
                RoomScreen(title: flightTitle,
                           status: RoomStatusCopy.onItsWay(state, now: timeline.date),
                           onAction: flightAction)
            }
        case .doorway:
            let picture = flightPicture
            ReadyScreen(roomTitle: flightTitle,
                        sceneId: picture.sceneId, stillURL: picture.still, stillNightURL: picture.night,
                        canOpenWeb: canOpenAnyRoomOnWeb && webRoomURL != nil,
                        shareURL: webRoomURL,
                        isArrival: true,
                        onOpen: openWebDesk,
                        onSignIn: { showAccount = true },
                        onScanAnother: rescanFromScratch,
                        onDone: endFlight)
        case .note(let kind):
            if case .incompleteUpload = kind {
                RoomScreen(title: flightTitle,
                           status: RoomStatusCopy.missing(missingCount: missingPaths.count, resend: resendState),
                           onAction: flightAction)
                    .task(id: missingPaths.count) { await refreshResendOffer() }
            } else if case .uploadFailed = kind {
                RoomScreen(title: flightTitle,
                           status: RoomStatusCopy.needsYou(.uploadFailed(reason: failures.latestFailure?.reason)),
                           onAction: flightAction)
            } else {
                RoomScreen(title: flightTitle, status: RoomStatusCopy.needsYou(kind), onAction: flightAction)
            }
        case .nowhere:
            // Terminal-not-ours (decision 0074): the root stand-down pops this
            // on the same publish that produced it.
            Color.rsGround
        }
    }

    /// The flight's scene in the rooms list, once the server has one.
    private var flightScene: RoomSummary? {
        guard let sentBundleId else { return nil }
        return rooms.state.knownRooms?.first { $0.bundleId == sentBundleId }
    }

    /// The finished flight's picture: its scene and its stills. The poller's
    /// own ready answer names the scene even when the list was fetched before
    /// the room was ready; the list wins on the links, because the still is
    /// drawn some seconds after ready and only a later fetch carries it.
    private var flightPicture: (sceneId: String?, still: URL?, night: URL?) {
        var ready: SceneResponse?
        if case .succeeded(let response) = poller.pollState { ready = response }
        let listed = flightScene
        return (listed?.id ?? ready?.sceneId,
                listed?.stillURL ?? ready?.stillUrl.flatMap(URL.init(string:)),
                listed?.stillNightURL ?? ready?.stillNightUrl.flatMap(URL.init(string:)))
    }

    /// The room in flight, titled the way the list titles it.
    private var flightTitle: String {
        RoomHistory.title(sentAt: flightSentAt ?? lastSceneCreatedAt ?? flightScene?.sentAt ?? Date(),
                          now: Date(), withTime: false)
    }

    /// What the flight screen's buttons do.
    private func flightAction(_ action: RoomAction) {
        switch action {
        case .sendAgain:
            sendItHome()
        case .checkAgain:
            if let id = sentBundleId ?? poller.currentBundleId {
                ScenePoller.shared.start(bundleId: id)
            } else {
                ScenePoller.shared.checkNow()
            }
        case .sendMissing:
            resendMissingFiles()
        case .scanAgain:
            rescanFromScratch()
        case .acknowledge:
            Task { await UploadFailureMonitor.shared.dismiss() }
            endFlight()
        case .discard:
            discardFlight()
        case .leave:
            path = []
        }
    }

    /// A send from an earlier launch: acknowledge it, or scan again.
    private func earlierFailureAction(_ action: RoomAction) {
        switch action {
        case .scanAgain:
            Task { await UploadFailureMonitor.shared.dismiss() }
            path = []
            showGuidance = true
        case .discard, .acknowledge:
            Task { await UploadFailureMonitor.shared.dismiss() }
            path = []
        case .sendAgain, .checkAgain, .sendMissing, .leave:
            path = []
        }
    }

    /// A room the server has that is not this phone's flight.
    @ViewBuilder
    private func listedRoomScreen(_ room: RoomSummary) -> some View {
        if room.state == .ready {
            let url = room.bundleId.flatMap { NetworkConfig.webRoomURL(bundleId: $0) }
            ReadyScreen(roomTitle: room.title,
                        sceneId: room.id, stillURL: room.stillURL, stillNightURL: room.stillNightURL,
                        canOpenWeb: RoomHistory.isOpenable(room, canOpenWeb: canOpenAnyRoomOnWeb) && url != nil,
                        shareURL: url,
                        onOpen: { openRoomOnWeb(room) },
                        onSignIn: { showAccount = true },
                        onScanAnother: {
                            path = []
                            showGuidance = true
                        },
                        onDone: { path = [] })
        } else {
            TimelineView(.periodic(from: .now, by: 30)) { timeline in
                RoomScreen(title: room.title,
                           status: RoomStatusCopy.listed(room.status, sentAt: room.sentAt, now: timeline.date),
                           onAction: { action in
                               path = []
                               if action == .scanAgain { showGuidance = true }
                           })
            }
        }
    }

    // MARK: - Rooms

    /// Whether a room's web handoff would land: an origin AND a linked
    /// identity (RoomHistory.webHandoffLands).
    private var canOpenAnyRoomOnWeb: Bool {
        RoomHistory.webHandoffLands(
            hasWebOrigin: NetworkConfig.webBaseURL != nil,
            isLinked: auth.isLinked
        )
    }

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
            // Persisted OR in-memory: dismissing a failure clears the kick for the
            // rest of the launch, and routing that read only the kick then fell
            // through to "Sending" forever for a bundle whose record is .failed.
            terminalBlobFailureForThisBundle: sentBundleId != nil
                && (failures.latestFailure?.bundleId == sentBundleId
                    || sentBundleFailedOnDisk),
            deferredForThisBundle: sentBundleId != nil
                && failures.latestDeferral?.bundleId == sentBundleId,
            poll: WaitFlowState.snapshot(from: poller.pollState,
                                         fallbackAnchor: lastSceneCreatedAt)
        )
    }

    /// Mirror the server anchor into @State so it survives the transition to
    /// .pollError (which carries no payload). Reads the OUTGOING state.
    private func retainAnchor(from previous: ScenePollState) {
        if case let .polling(_, _, sceneCreatedAt, _, _) = previous,
           let sceneCreatedAt, sceneCreatedAt != lastSceneCreatedAt {
            lastSceneCreatedAt = sceneCreatedAt
        }
    }

    // MARK: - Actions

    private func sendItHome() {
        stage = .home
        path = [.flight]
        #if DEBUG
        // Staging (failed_invalid): corrupt a frame IN PLACE, same byte length,
        // before the manifest reads sizes off disk. No-op unless the flag is set.
        StagingHooks.applyPreSendSabotage(outputDir: capture.bundleOutputDir)
        #endif
        // Drop the previous capture's poll + session state SYNCHRONOUSLY, before
        // the Task: a stale state would otherwise narrate this room for the whole
        // setup window, and a stale "Check again" could re-poll the wrong bundle.
        sentBundleId = nil
        sentBundleFailedOnDisk = false
        lastSceneCreatedAt = nil
        resendState = .unavailable
        ScenePoller.shared.reset()
        UploadFailureMonitor.shared.clearDeferral()
        coordinator.reset()
        // Snapshot the id SYNCHRONOUSLY: reading it after the await let a "scan
        // again" in the gap mint a new bundleId into this send.
        let bundleId = capture.bundleIdString
        // Set NOW, not after the mint returns: leaving in that window left the
        // capture invisible on every surface.
        sentBundleId = bundleId
        flightSentAt = Date()
        // Declare the flight to the poller (after reset()).
        ScenePoller.shared.expectBundle(bundleId)
        // The Lock Screen card starts HERE: minting a long walk's manifest
        // measured 14 s, exactly the window in which a phone gets locked.
        LiveActivityController.shared.begin(bundleId: bundleId)
        sendGeneration &+= 1
        let generation = sendGeneration
        Task {
            await coordinator.beginUploadSession(for: capture)
            guard generation == sendGeneration else { return }
            // Record the bundle, but do NOT start polling yet: bundle.pb goes
            // last, so no Scene exists until the completion kick.
            if case .ready = coordinator.sessionState {
                sentBundleId = bundleId
            }
        }
    }

    /// Re-adopt a bundle left behind by a previous launch, newest first — once
    /// per launch, and never one the person has finished with (BundleRestore).
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
        // Adopt the Lock Screen card of the restored flight and end any other.
        LiveActivityController.shared.reconcileOnLaunch(restoredBundleId: pick)
        // Re-check: a send started while the scan awaited disk owns sentBundleId.
        if let pick, sentBundleId == nil {
            sentBundleId = pick
        }
    }

    /// Refresh the persisted terminal state for the sent bundle.
    private func refreshSentBundlePhase() async {
        guard let bundleId = sentBundleId else {
            sentBundleFailedOnDisk = false
            return
        }
        let record = try? await UploadSessionStore.shared.load(bundleId: bundleId)
        sentBundleFailedOnDisk = (record?.uploadPhase == .failed)
    }

    /// If the blobs for the sent bundle finished while no status surface was
    /// mounted, start polling now. Safe to call repeatedly.
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

    /// The paths the poller is currently reporting missing. Read from the
    /// POLLER, which is the answer the re-send acts on.
    private var missingPaths: [String] {
        if case .recoverable(let paths) = poller.pollState { return paths }
        return []
    }

    /// Which bundle the recovery acts on: the one the POLLER asked about.
    private var recoveryBundleId: String? {
        poller.currentBundleId ?? sentBundleId
    }

    /// Ask CaptureRecovery whether a re-send can honestly be offered — the
    /// promise is downstream of an actual disk check.
    private func refreshResendOffer() async {
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

    /// Send the missing files again. USER-INITIATED: an automatic re-send would
    /// spend the day's quota and upload on whatever network, unasked.
    private func resendMissingFiles() {
        guard let bundleId = recoveryBundleId else { return }
        let paths = missingPaths
        resendState = .inFlight
        Task {
            let outcome = await BlobUploadManager.shared.resendMissingBlobs(
                bundleId: bundleId, missingPaths: paths)
            switch outcome {
            case .started:
                // Hand the screen back to the ordinary send states.
                resendState = .unavailable
                ScenePoller.shared.reset()
                ScenePoller.shared.expectBundle(bundleId)
                LiveActivityController.shared.begin(bundleId: bundleId)
            case .refused:
                resendState = .unavailable
            case .failed:
                resendState = .failed
            }
        }
    }

    private func rescanFromScratch() {
        // Ends the old flight before starting a new capture.
        endFlight()
        stage = .capturing
        beginCapture()
    }

    /// End the current flight and go back to the rooms. EVERY terminal exit uses
    /// this: home's flight card keys off `sentBundleId`.
    private func endFlight() {
        // Reclaim decision BEFORE clearing, keyed on the outcome the person has
        // actually seen (decision 0084; table in CaptureReclaim).
        let leavingScreen = waitScreen
        // Acknowledge BEFORE clearing: the record can outlive the app.
        if let sentBundleId {
            DismissedBundles().acknowledge(sentBundleId)
            if CaptureReclaim.reclaimsAtFlightEnd(leavingScreen) {
                let bundleId = sentBundleId
                Task { await CaptureReaper.shared.reclaim(bundleId: bundleId) }
            }
        }
        // The person has seen the outcome; the Lock Screen stops reporting.
        LiveActivityController.shared.end(bundleId: sentBundleId)
        clearFlight()
        stage = .home
        path = []
    }

    /// Let an unsent scan go: end the flight and free its files. Offered only
    /// where nothing left the phone (today's limit, a send that never started),
    /// so there is no upload to strand.
    private func discardFlight() {
        if let bundleId = sentBundleId {
            Task { await CaptureReaper.shared.reclaim(bundleId: bundleId) }
        }
        endFlight()
    }

    /// Clear the in-memory flight state without navigating.
    private func clearFlight() {
        ScenePoller.shared.reset()
        UploadFailureMonitor.shared.clearDeferral()
        sentBundleId = nil
        flightSentAt = nil
        sentBundleFailedOnDisk = false
        lastSceneCreatedAt = nil
        resendState = .unavailable
    }

    /// Decision-0074 stand-down: the polled room belongs to a different identity.
    /// Definitive, so acknowledge it and clear the flight; never yank the person
    /// out of a live scan.
    private func standDownNotOurs() {
        if let foreignId = WaitFlowState.foreignBundleToAcknowledge(
            pollerBundleId: poller.currentBundleId, sentBundleId: sentBundleId) {
            DismissedBundles().acknowledge(foreignId)
            LiveActivityController.shared.end(bundleId: foreignId)
        }
        clearFlight()
        path.removeAll { $0 == .flight }
    }

    /// The web URL for the room that was just sent, or nil without a web origin.
    private var webRoomURL: URL? {
        guard let id = sentBundleId else { return nil }
        return NetworkConfig.webRoomURL(bundleId: id)
    }

    /// Open the room on the web. A plain `open(_:)`; the button is shown only
    /// when the handoff would land.
    private func openWebDesk() {
        guard let url = webRoomURL else { return }
        UIApplication.shared.open(url)
    }

    // MARK: - Derived display state

    private var hudState: CaptureHUDState {
        // ARKit hands us a REASON; don't discard it and assert a cause. Only
        // .insufficientFeatures is actually about light.
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
        // fill toward a closed room's worth. Without RoomPlan there is none.
        let cover = FloorPlanVoice.coverage(census: capture.liveCensus,
                                            cornerCount: capture.liveCornerCount)
        return CaptureHUDState(
            tracking: quality,
            guestLine: capture.tier == .arkitOnly
                ? "Move slowly and keep the walls in view — I’m measuring with the camera."
                : "Move slowly — I’ll draw the room as you go.",
            floor: cover.floor, walls: cover.walls, corners: cover.corners
        )
    }

    /// Nothing was captured. An EMPTINESS check, not a quality threshold.
    private var isEmptyCapture: Bool { capture.frameCount == 0 }

    /// Frames exist but bundle.pb hasn't been published yet. Transient —
    /// unless assembly failed, which is terminal and reported separately.
    private var isPreparingBundle: Bool {
        !isEmptyCapture && capture.bundlePath == nil && capture.assemblyFailure == nil
    }
}
