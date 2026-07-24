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
        XCTAssertEqual(screen(sessionFailure: .init(terminal: false), poll: .succeeded),
                       .sendFailed(terminal: false))
        XCTAssertEqual(screen(sessionFailure: .init(terminal: true), blobFailed: true, poll: .succeeded),
                       .sendFailed(terminal: true))
    }

    /// A permanent 4xx is distinguishable from a retryable failure, so the UI can
    /// stop offering a retry that provably cannot work.
    func testTerminalSendFailureIsDistinguishable() {
        XCTAssertEqual(screen(sessionFailure: .init(terminal: true), poll: .idle),
                       .sendFailed(terminal: true))
        XCTAssertNotEqual(screen(sessionFailure: .init(terminal: true), poll: .idle),
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
        XCTAssertEqual(screen(sessionFailure: .init(terminal: false), deferred: true, poll: .idle),
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
        XCTAssertEqual(screen(poll: .recoverable), .incompleteUpload)
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
                       .init(terminal: false))
        XCTAssertEqual(WaitFlowState.sessionFailure(from: .failed("403", terminal: true)),
                       .init(terminal: true))
    }

    func testPollSnapshotAdapterMapsEveryState() {
        XCTAssertEqual(WaitFlowState.snapshot(from: .idle, fallbackAnchor: nil), .idle)
        XCTAssertEqual(WaitFlowState.snapshot(from: .failedTerminal(.failed), fallbackAnchor: nil),
                       .failedTerminal)
        XCTAssertEqual(WaitFlowState.snapshot(from: .recoverable(missingPaths: ["a"]), fallbackAnchor: nil),
                       .recoverable)
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

    // MARK: - Elapsed clock

    func testClockFormatsAndClampsNegativeSkew() {
        XCTAssertEqual(WaitingView.clock(0), "00:00")
        XCTAssertEqual(WaitingView.clock(-42), "00:00", "clock must clamp negative skew to zero")
        XCTAssertEqual(WaitingView.clock(65), "01:05")
        XCTAssertEqual(WaitingView.clock(599), "09:59")
    }

    func testClockRollsOverToHours() {
        XCTAssertEqual(WaitingView.clock(3599), "59:59")
        XCTAssertEqual(WaitingView.clock(3600), "1:00:00")
        XCTAssertEqual(WaitingView.clock(3661), "1:01:01")
    }
}
