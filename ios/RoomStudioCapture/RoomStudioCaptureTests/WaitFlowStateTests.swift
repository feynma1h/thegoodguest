/// Pins the post-send routing table (WaitFlowState) and the elapsed-clock
/// formatter — the first fully offline, deterministic tests of the flow layer
/// (no clock, no network, no simulator, no singletons).
///
/// Each of the four review passes over this branch found a routing hole that a
/// table like this would have surfaced immediately. The regression cases below
/// are named for the defect they pin, so a reintroduction fails loudly.

import XCTest
@testable import RoomStudioCapture

final class WaitFlowStateTests: XCTestCase {

    private let anchor = Date(timeIntervalSince1970: 1_700_000_000)

    private func screen(
        sessionFailure: WaitFlowState.SessionFailure? = nil,
        blobFailed: Bool = false,
        deferred: Bool = false,
        poll: WaitFlowState.PollSnapshot
    ) -> WaitScreen {
        WaitFlowState.screen(
            sessionFailure: sessionFailure,
            terminalBlobFailureForThisBundle: blobFailed,
            deferredForThisBundle: deferred,
            poll: poll
        )
    }

    // MARK: - Regressions (each pins a defect found in review)

    /// The room must never be described as arrived while it is still uploading.
    /// `.idle` is the not-yet-polling state, which spans the whole upload.
    func testIdlePollIsSendingNotAnalyzing() {
        XCTAssertEqual(screen(poll: .idle), .sending)
    }

    /// A terminal blob failure means bundle.pb never lands, so no Scene document is
    /// ever created and the poller 404s forever. Routing must not defer to the poll.
    func testTerminalBlobFailureOutranksAnOptimisticPoll() {
        XCTAssertEqual(
            screen(blobFailed: true,
                   poll: .polling(queued: true, longRunning: false, connectionTrouble: false, anchor: nil)),
            .uploadFailed
        )
    }

    /// A failed upload session outranks everything, including a stale poll state
    /// left over from a previous capture.
    func testFailedSessionOutranksEverything() {
        XCTAssertEqual(screen(sessionFailure: .refused(terminal: false), poll: .succeeded),
                       .sendFailed(terminal: false))
        XCTAssertEqual(screen(sessionFailure: .refused(terminal: true), blobFailed: true, poll: .succeeded),
                       .sendFailed(terminal: true))
    }

    /// A permanent 4xx is distinguishable from a retryable failure, so the UI can
    /// stop offering a retry that provably cannot work.
    func testTerminalSendFailureIsDistinguishable() {
        XCTAssertEqual(screen(sessionFailure: .refused(terminal: true), poll: .idle),
                       .sendFailed(terminal: true))
        XCTAssertNotEqual(screen(sessionFailure: .refused(terminal: true), poll: .idle),
                          .sendFailed(terminal: false))
    }

    /// The anchor is the server-side scene start and must survive into the
    /// poll-error screen, which is the one place its reassurance matters most.
    func testPollErrorCarriesTheServerAnchor() {
        XCTAssertEqual(screen(poll: .pollError(anchor: anchor)),
                       .checkFailed(anchor: anchor, stopped: true))
    }

    /// Transient connection trouble is NOT the same as a dead loop: the copy
    /// promising "I'll keep trying" is only honest for the former.
    func testConnectionTroubleWhilePollingIsNotStopped() {
        XCTAssertEqual(
            screen(poll: .polling(queued: false, longRunning: false, connectionTrouble: true, anchor: anchor)),
            .checkFailed(anchor: anchor, stopped: false)
        )
    }

    /// A DEFERRED upload (retries exhausted this launch / lost context) resumes only
    /// on the next launch. Rendering it as "sending" told the user to keep waiting
    /// in the one process where recovery cannot happen.
    func testDeferredUploadIsPausedNotSending() {
        XCTAssertEqual(screen(deferred: true, poll: .idle), .sendPaused)
        XCTAssertEqual(screen(deferred: false, poll: .idle), .sending)
    }

    /// A stale deferral must never override a live wait: once polling starts the
    /// bytes are already up.
    func testDeferralDoesNotOverrideLivePolling() {
        XCTAssertEqual(
            screen(deferred: true,
                   poll: .polling(queued: false, longRunning: false, connectionTrouble: false, anchor: anchor)),
            .waiting(phase: .analyzing, anchor: anchor)
        )
        XCTAssertEqual(screen(deferred: true, poll: .succeeded), .doorway)
    }

    /// A real terminal failure still outranks a deferral.
    func testTerminalOutranksDeferral() {
        XCTAssertEqual(screen(blobFailed: true, deferred: true, poll: .idle), .uploadFailed)
        XCTAssertEqual(screen(sessionFailure: .refused(terminal: false), deferred: true, poll: .idle),
                       .sendFailed(terminal: false))
    }

    // MARK: - The routing table

    func testPhasePrecedenceConnectionTroubleBeatsLongRunning() {
        XCTAssertEqual(
            screen(poll: .polling(queued: true, longRunning: true, connectionTrouble: true, anchor: anchor)),
            .checkFailed(anchor: anchor, stopped: false)
        )
    }

    func testLongRunningBeatsQueued() {
        XCTAssertEqual(
            screen(poll: .polling(queued: true, longRunning: true, connectionTrouble: false, anchor: anchor)),
            .waiting(phase: .longRunning, anchor: anchor)
        )
    }

    func testQueuedAndAnalyzing() {
        XCTAssertEqual(
            screen(poll: .polling(queued: true, longRunning: false, connectionTrouble: false, anchor: anchor)),
            .waiting(phase: .queued, anchor: anchor)
        )
        XCTAssertEqual(
            screen(poll: .polling(queued: false, longRunning: false, connectionTrouble: false, anchor: anchor)),
            .waiting(phase: .analyzing, anchor: anchor)
        )
    }

    func testTerminalPollStates() {
        XCTAssertEqual(screen(poll: .succeeded), .doorway)
        XCTAssertEqual(screen(poll: .failedTerminal), .processingFailed)
        XCTAssertEqual(screen(poll: .recoverable(missingCount: 3)),
                       .incompleteUpload(missingCount: 3))
    }

    /// The missing-file count must survive routing. It reached the poller and then
    /// died at this table — the screen could not render what the server had already
    /// said (decision 0085 finding 1).
    func testIncompleteUploadCarriesTheMissingCount() {
        XCTAssertEqual(screen(poll: .recoverable(missingCount: 1)),
                       .incompleteUpload(missingCount: 1))
        XCTAssertEqual(screen(poll: .recoverable(missingCount: 127)),
                       .incompleteUpload(missingCount: 127))
        XCTAssertEqual(screen(poll: .recoverable(missingCount: 0)),
                       .incompleteUpload(missingCount: 0),
                       "a server that names no paths still routes here — the copy degrades, the route does not")
    }

    // MARK: - Terminal-not-ours (decision 0074)

    /// THE PHANTOM-ROOM REGRESSION: a by-bundle 403 routed to the connection-trouble
    /// screen, whose copy ("your room is safe up there") is false for a foreign room
    /// and whose onLeave deliberately preserves the flight — so the phantom recurred
    /// on every cold launch forever. notOwned must route to its own screen, never to
    /// checkFailed.
    func testNotOwnedRoutesToNotOursNeverCheckFailed() {
        XCTAssertEqual(screen(poll: .notOwned), .notOurs)
        XCTAssertNotEqual(screen(poll: .notOwned), .checkFailed(anchor: nil, stopped: true))
    }

    /// Upload-side failures still outrank the poll: a terminal blob failure means
    /// bundle.pb never landed, so its screen owns the story whatever the poll says.
    func testUploadFailuresOutrankNotOwned() {
        XCTAssertEqual(screen(sessionFailure: .refused(terminal: true), poll: .notOwned),
                       .sendFailed(terminal: true))
        XCTAssertEqual(screen(blobFailed: true, poll: .notOwned), .uploadFailed)
    }

    /// The stand-down predicate, as a table: true for exactly the terminal-not-ours
    /// state. Every other state either carries an outcome the user should see or
    /// must keep its screen — auto-dismissing any of them would eat a real result.
    func testStandsDownAutomaticallyTable() {
        XCTAssertTrue(WaitFlowState.standsDownAutomatically(.notOwned))

        XCTAssertFalse(WaitFlowState.standsDownAutomatically(.idle))
        XCTAssertFalse(WaitFlowState.standsDownAutomatically(
            .polling(latest: .queued, since: anchor, sceneCreatedAt: nil,
                     longRunning: false, connectionTrouble: false)))
        XCTAssertFalse(WaitFlowState.standsDownAutomatically(
            .polling(latest: .processing, since: anchor, sceneCreatedAt: anchor,
                     longRunning: true, connectionTrouble: true)))
        XCTAssertFalse(WaitFlowState.standsDownAutomatically(.failedTerminal(.failed)))
        XCTAssertFalse(WaitFlowState.standsDownAutomatically(.recoverable(missingPaths: ["a"])))
        XCTAssertFalse(WaitFlowState.standsDownAutomatically(.pollError("boom")),
                       "a plain poll error is connection trouble, not a stand-down")
    }

    /// succeeded is the one that would hurt most if auto-dismissed: the doorway is
    /// the payoff moment.
    func testSucceededNeverStandsDownAutomatically() {
        let response = SceneResponse(
            sceneId: "s1", bundleId: "b1", status: .ready,
            resultUri: "gs://bucket/obj", missingPaths: nil,
            createdAt: "2026-07-21T13:19:47+00:00", updatedAt: "2026-07-21T13:19:47+00:00")
        XCTAssertFalse(WaitFlowState.standsDownAutomatically(.succeeded(response)))
    }

    /// Which record the stand-down acknowledges: the poller's target (the id the 403
    /// actually answered), falling back to the flight's id.
    func testForeignAcknowledgeTargetPrefersThePolledBundle() {
        XCTAssertEqual(WaitFlowState.foreignBundleToAcknowledge(pollerBundleId: "p", sentBundleId: "s"), "p")
        XCTAssertEqual(WaitFlowState.foreignBundleToAcknowledge(pollerBundleId: "p", sentBundleId: nil), "p")
        XCTAssertEqual(WaitFlowState.foreignBundleToAcknowledge(pollerBundleId: nil, sentBundleId: "s"), "s")
        XCTAssertNil(WaitFlowState.foreignBundleToAcknowledge(pollerBundleId: nil, sentBundleId: nil))
    }

    /// A nil anchor must propagate rather than be substituted with a client time.
    func testNilAnchorPropagates() {
        XCTAssertEqual(
            screen(poll: .polling(queued: false, longRunning: false, connectionTrouble: false, anchor: nil)),
            .waiting(phase: .analyzing, anchor: nil)
        )
    }

    // MARK: - Adapters (a correct table fed a wrong snapshot is still a wrong screen)

    @MainActor
    func testSessionFailureAdapterCarriesTerminality() {
        XCTAssertNil(WaitFlowState.sessionFailure(from: .idle))
        XCTAssertNil(WaitFlowState.sessionFailure(from: .creatingSession))
        XCTAssertEqual(WaitFlowState.sessionFailure(from: .failed("net")),
                       .refused(terminal: false))
        XCTAssertEqual(WaitFlowState.sessionFailure(from: .failed("403", terminal: true)),
                       .refused(terminal: true))
    }

    func testPollSnapshotAdapterMapsEveryState() {
        XCTAssertEqual(WaitFlowState.snapshot(from: .idle, fallbackAnchor: nil), .idle)
        XCTAssertEqual(WaitFlowState.snapshot(from: .failedTerminal(.failed), fallbackAnchor: nil),
                       .failedTerminal)
        XCTAssertEqual(WaitFlowState.snapshot(from: .recoverable(missingPaths: ["a"]), fallbackAnchor: nil),
                       .recoverable(missingCount: 1))
        XCTAssertEqual(WaitFlowState.snapshot(from: .recoverable(missingPaths: ["a", "b", "c"]),
                                              fallbackAnchor: nil),
                       .recoverable(missingCount: 3),
                       "the adapter counts the paths; the paths themselves stay out of routing")
        XCTAssertEqual(WaitFlowState.snapshot(from: .recoverable(missingPaths: []), fallbackAnchor: nil),
                       .recoverable(missingCount: 0))
        XCTAssertEqual(WaitFlowState.snapshot(from: .notOwned, fallbackAnchor: anchor), .notOwned,
                       "notOwned carries no anchor — there is no honest clock for a foreign room")
    }

    /// The server anchor is the payload .pollError does not carry; the adapter must
    /// substitute the retained one so the elapsed clock survives the transition.
    func testPollErrorAdapterUsesTheFallbackAnchor() {
        XCTAssertEqual(WaitFlowState.snapshot(from: .pollError("boom"), fallbackAnchor: anchor),
                       .pollError(anchor: anchor))
        XCTAssertEqual(WaitFlowState.snapshot(from: .pollError("boom"), fallbackAnchor: nil),
                       .pollError(anchor: nil))
    }

    /// `queued` is derived from the payload's status, not from a separate flag.
    func testPollingAdapterDerivesQueuedFromStatus() {
        let queued = WaitFlowState.snapshot(
            from: .polling(latest: .queued, since: anchor, sceneCreatedAt: anchor,
                           longRunning: false, connectionTrouble: false),
            fallbackAnchor: nil)
        XCTAssertEqual(queued, .polling(queued: true, longRunning: false,
                                        connectionTrouble: false, anchor: anchor))

        let processing = WaitFlowState.snapshot(
            from: .polling(latest: .processing, since: anchor, sceneCreatedAt: nil,
                           longRunning: true, connectionTrouble: true),
            fallbackAnchor: anchor)
        XCTAssertEqual(processing, .polling(queued: false, longRunning: true,
                                            connectionTrouble: true, anchor: nil),
                       "a polling anchor must come from the payload, never the fallback")
    }

    /// End-to-end through the adapters: the defect that started this — polling not
    /// yet begun during an upload must never render as 'analyzing'.
    @MainActor
    func testAdaptersEndToEndIdleIsSending() {
        XCTAssertEqual(
            WaitFlowState.screen(
                sessionFailure: WaitFlowState.sessionFailure(from: .creatingSession),
                terminalBlobFailureForThisBundle: false,
                poll: WaitFlowState.snapshot(from: .idle, fallbackAnchor: nil)
            ),
            .sending
        )
    }

}

/// Pins ScenePoller's `isVisible` contract, which the completion kick trusts.
///
/// A review pass removed `isVisible = true` from `resume()` to stop a foreground
/// transition asserting a status surface was on screen. That was right for the
/// singleton — but `pause()` still clears the flag, and a status surface's only
/// restore is a `.task` that fires once per launch. The result was a launch-long
/// dropped kick that all 266 tests were blind to.
@MainActor
final class ScenePollerVisibilityTests: XCTestCase {

    private func makePoller() -> ScenePoller {
        ScenePoller(now: { Date(timeIntervalSince1970: 0) },
                    sleep: { _ in },
                    performGET: { _, _ in .failure(URLError(.notConnectedToInternet)) },
                    tokenProvider: { "token" })
    }

    /// resume() must NOT assert visibility — that is the caller's to own.
    func testResumeDoesNotAssertVisibility() {
        let poller = makePoller()
        poller.setVisible(true)
        poller.pause()
        XCTAssertFalse(poller.isVisible, "pause() clears visibility")
        poller.resume()
        XCTAssertFalse(poller.isVisible,
                       "resume() must leave visibility to the caller — a foreground trip is not a mounted status surface")
    }

    /// …which means every caller that IS a status surface must restore it itself.
    /// Without this the completion kick is dropped for the rest of the launch.
    func testSetVisibleRestoresTheKickAfterABackgroundTrip() {
        let poller = makePoller()
        poller.setVisible(true)
        poller.pause()
        poller.setVisible(true)          // what RootFlowView does on .active
        XCTAssertTrue(poller.isVisible)

        poller.notifyBundleComplete(bundleId: "b1")
        XCTAssertEqual(poller.currentBundleId, "b1",
                       "a visible surface must let the completion kick start polling")
    }

    /// The kick stays suppressed when nothing is on screen.
    func testKickIsDroppedWhileNotVisible() {
        let poller = makePoller()
        poller.setVisible(false)
        poller.notifyBundleComplete(bundleId: "b1")
        XCTAssertNil(poller.currentBundleId)
    }
}

/// Pins the per-PATH scoping of the upload-deferral signal.
///
/// The signal was introduced bundle-scoped and cleared from `handleSuccess`, which
/// runs per blob. A real capture uploads ~127 blobs concurrently, so any sibling's
/// success erased a genuine deferral milliseconds after it was raised — the
/// deferred blob never moved, the Phase-1 gate never opened, and the wait screen
/// reverted to "sending" forever, which is exactly what the signal exists to
/// prevent. Only total network loss made it work.
@MainActor
final class UploadDeferralScopingTests: XCTestCase {

    private func makeMonitor() -> UploadFailureMonitor {
        UploadFailureMonitor(store: UploadSessionStore.shared)
    }

    func testSiblingProgressDoesNotClearAnotherPathsDeferral() {
        let m = makeMonitor()
        m.notifyUploadDeferred(bundleId: "b1", relativePath: "frames/000042.jpg", reason: "timeout")
        XCTAssertNotNil(m.latestDeferral)

        // A different blob of the SAME bundle succeeds.
        m.clearDeferral(bundleId: "b1", relativePath: "frames/000043.jpg")
        XCTAssertNotNil(m.latestDeferral,
                        "a sibling blob's success must not clear another path's deferral")
    }

    func testTheDeferredPathsOwnProgressClearsIt() {
        let m = makeMonitor()
        m.notifyUploadDeferred(bundleId: "b1", relativePath: "frames/000042.jpg", reason: "timeout")
        m.clearDeferral(bundleId: "b1", relativePath: "frames/000042.jpg")
        XCTAssertNil(m.latestDeferral)
    }

    func testBundleStaysPausedUntilEveryDeferredPathProgresses() {
        let m = makeMonitor()
        m.notifyUploadDeferred(bundleId: "b1", relativePath: "a.jpg", reason: "timeout")
        m.notifyUploadDeferred(bundleId: "b1", relativePath: "b.jpg", reason: "timeout")

        m.clearDeferral(bundleId: "b1", relativePath: "a.jpg")
        XCTAssertNotNil(m.latestDeferral, "one path still deferred")

        m.clearDeferral(bundleId: "b1", relativePath: "b.jpg")
        XCTAssertNil(m.latestDeferral, "all paths progressed")
    }

    /// Completion and a new send clear wholesale.
    func testBundleWideAndGlobalClears() {
        let m = makeMonitor()
        m.notifyUploadDeferred(bundleId: "b1", relativePath: "a.jpg", reason: "timeout")
        m.clearDeferral(bundleId: "b1")
        XCTAssertNil(m.latestDeferral)

        m.notifyUploadDeferred(bundleId: "b2", relativePath: "a.jpg", reason: "timeout")
        m.clearDeferral()
        XCTAssertNil(m.latestDeferral)
    }
}
