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
        session: WaitFlowState.SessionOutcome = .ready,
        blobFailed: Bool = false,
        poll: WaitFlowState.PollSnapshot
    ) -> WaitScreen {
        WaitFlowState.screen(
            session: session,
            terminalBlobFailureForThisBundle: blobFailed,
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
        XCTAssertEqual(screen(session: .failed(terminal: false), poll: .succeeded),
                       .sendFailed(terminal: false))
        XCTAssertEqual(screen(session: .failed(terminal: true), blobFailed: true, poll: .succeeded),
                       .sendFailed(terminal: true))
    }

    /// A permanent 4xx is distinguishable from a retryable failure, so the UI can
    /// stop offering a retry that provably cannot work.
    func testTerminalSendFailureIsDistinguishable() {
        XCTAssertEqual(screen(session: .failed(terminal: true), poll: .idle),
                       .sendFailed(terminal: true))
        XCTAssertNotEqual(screen(session: .failed(terminal: true), poll: .idle),
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
