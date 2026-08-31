/// Pins where every post-send state lives after the 2b split.
///
/// This is the table that decides whether a failed room is something the user
/// is asked to acknowledge or something the app is quietly still working on.
/// Getting it wrong does not produce a styling error — it produces a room that
/// is either nagged about forever or never mentioned again.
///
/// Every case of WaitScreen is asserted explicitly rather than by iterating,
/// because the point is the ASSIGNMENT, and a loop that derived the expectation
/// from the same function under test would assert nothing.

import XCTest
@testable import TheGoodGuestCapture

final class SurfacePlacementTests: XCTestCase {

    // MARK: Every state has exactly one home

    func testDeskHoldsEveryRoomStillOnItsWay() {
        let cases: [(WaitScreen, DeskState, String)] = [
            (.sending, .sending, "bytes moving"),
            (.waiting(phase: .queued, anchor: nil),
             .working(anchor: nil, longRunning: false), "queued is working"),
            (.waiting(phase: .analyzing, anchor: nil),
             .working(anchor: nil, longRunning: false), "analyzing is working"),
            (.waiting(phase: .longRunning, anchor: nil),
             .working(anchor: nil, longRunning: true), "long running keeps its flag"),
            (.sendPaused, .paused, "resumes next launch"),
            (.sendRateLimited(resetsAt: nil), .rateLimited(resetsAt: nil), "lifts by itself"),
            (.sendFailed(terminal: false), .retryableSendFailure, "retrying works"),
            (.checkFailed(anchor: nil, stopped: false),
             .checkFailed(anchor: nil, stopped: false), "room is safe, check isn't landing"),
        ]
        for (screen, expected, why) in cases {
            XCTAssertEqual(SurfaceRouter.placement(for: screen), .desk(expected), why)
        }
    }

    func testNotesHoldEveryFinishedFailureWaitingToBeAcknowledged() {
        let cases: [(WaitScreen, NoteKind, String)] = [
            (.uploadFailed, .uploadFailed(reason: nil), "no scene will ever exist"),
            (.processingFailed, .processingFailed, "pipeline hard-failed"),
            (.sendFailed(terminal: true), .sendFailedTerminal, "retrying provably cannot fix it"),
            (.incompleteUpload(missingCount: 3), .incompleteUpload(missingCount: 3),
             "not all of it arrived"),
        ]
        for (screen, expected, why) in cases {
            XCTAssertEqual(SurfaceRouter.placement(for: screen), .note(expected), why)
        }
    }

    func testTheArrivalAndTheSelfClearingStateAreNeither() {
        XCTAssertEqual(SurfaceRouter.placement(for: .doorway), .doorway)
        // Stands itself down on the same publish that produces it — building a
        // surface for it would be building a screen for a state that erases
        // itself.
        XCTAssertEqual(SurfaceRouter.placement(for: .notOurs), .nowhere)
    }

    // MARK: The judgement call

    func testTheSendFailureSplitsOnWhetherRetryingCanWork() {
        // The one judgement in the file, and the pair that states it: the same
        // WaitScreen case lands on two different surfaces depending on whether
        // the room still has a future.
        XCTAssertEqual(SurfaceRouter.placement(for: .sendFailed(terminal: false)),
                       .desk(.retryableSendFailure),
                       "nothing left the phone and trying again works — still on its way")
        XCTAssertEqual(SurfaceRouter.placement(for: .sendFailed(terminal: true)),
                       .note(.sendFailedTerminal),
                       "retrying cannot fix it — the only thing left is to know")
    }

    // MARK: What home reads

    func testNeedsUserIsExactlyTheNotes() {
        let needs: [WaitScreen] = [
            .uploadFailed, .processingFailed,
            .sendFailed(terminal: true), .incompleteUpload(missingCount: 1),
        ]
        let doesNot: [WaitScreen] = [
            .sending, .waiting(phase: .analyzing, anchor: nil), .sendPaused,
            .sendRateLimited(resetsAt: nil), .sendFailed(terminal: false),
            .checkFailed(anchor: nil, stopped: true), .doorway, .notOurs,
        ]
        for s in needs { XCTAssertTrue(SurfaceRouter.needsUser(s), "\(s)") }
        for s in doesNot { XCTAssertFalse(SurfaceRouter.needsUser(s), "\(s)") }
    }

    func testAPausedOrRetryableRoomStillCountsAsInFlight() {
        // From home's point of view these have neither finished nor failed, and
        // telling the user nothing is happening about a capture sitting on
        // their phone would be false.
        XCTAssertTrue(SurfaceRouter.isInFlight(.sendPaused))
        XCTAssertTrue(SurfaceRouter.isInFlight(.sendFailed(terminal: false)))
        XCTAssertTrue(SurfaceRouter.isInFlight(.sendRateLimited(resetsAt: nil)))
        XCTAssertTrue(SurfaceRouter.isInFlight(.checkFailed(anchor: nil, stopped: true)))

        XCTAssertFalse(SurfaceRouter.isInFlight(.doorway), "arrived")
        XCTAssertFalse(SurfaceRouter.isInFlight(.uploadFailed), "finished, failed")
        XCTAssertFalse(SurfaceRouter.isInFlight(.notOurs), "never ours")
    }

    func testInFlightAndNeedsUserAreMutuallyExclusive() {
        // A room cannot simultaneously be something the app is working on and
        // something waiting on the user — that contradiction is what would let
        // home's sentence route two ways at once.
        let all: [WaitScreen] = [
            .sending, .waiting(phase: .queued, anchor: nil),
            .waiting(phase: .analyzing, anchor: Date()),
            .waiting(phase: .longRunning, anchor: Date()),
            .checkFailed(anchor: nil, stopped: false), .checkFailed(anchor: Date(), stopped: true),
            .sendPaused, .sendRateLimited(resetsAt: nil), .sendRateLimited(resetsAt: Date()),
            .sendFailed(terminal: false), .sendFailed(terminal: true),
            .uploadFailed, .processingFailed, .incompleteUpload(missingCount: 0),
            .doorway, .notOurs,
        ]
        for s in all {
            XCTAssertFalse(SurfaceRouter.isInFlight(s) && SurfaceRouter.needsUser(s), "\(s)")
        }
    }

    // MARK: The recovery exception

    func testOnlyTheIncompleteUploadOpensAScreen() {
        XCTAssertFalse(NoteKind.incompleteUpload(missingCount: 2).isAcknowledgeOnly,
                       "whether the bytes can be re-sent is a question about this phone's disk")
        for kind: NoteKind in [.uploadFailed(reason: "http_403"), .processingFailed,
                               .sendFailedTerminal] {
            XCTAssertTrue(kind.isAcknowledgeOnly, "\(kind)")
        }
    }
}
