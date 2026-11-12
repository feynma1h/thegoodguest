/// Pins what a room's own screen says and offers (RoomStatusCopy), for every
/// state it can be in: the old desk, Notes and What's missing, merged.
///
/// The rules here are the ones those screens kept, restated for one screen:
/// no estimate and no invented elapsed time, no step that blames, no "safe"
/// above a button that frees the scan, and none of the retired idiom — the
/// desk as a word, capitals-and-middle-dot status lines.

import XCTest
@testable import TheGoodGuest

final class RoomStatusTests: XCTestCase {

    private let now = Date(timeIntervalSince1970: 1_786_147_200)

    private var everyState: [RoomStatus] {
        let desk: [DeskState] = [
            .sending,
            .working(anchor: now.addingTimeInterval(-268), longRunning: false),
            .working(anchor: nil, longRunning: true),
            .paused,
            .rateLimited(resetsAt: now.addingTimeInterval(3600)),
            .rateLimited(resetsAt: nil),
            .retryableSendFailure,
            .checkFailed(anchor: now, stopped: false),
            .checkFailed(anchor: now, stopped: true),
        ]
        let notes: [NoteKind] = [.uploadFailed(reason: "x"), .uploadFailed(reason: nil),
                                 .processingFailed, .sendFailedTerminal]
        let resends: [FailureCopy.Resend] = [.available, .inFlight, .failed, .unavailable]
        let listed: [SceneStatus] = [.ready, .queued, .processing, .failed, .failedInvalid, .failedIncomplete]
        return desk.map { RoomStatusCopy.onItsWay($0, now: now) }
            + notes.map(RoomStatusCopy.needsYou)
            + resends.flatMap { r in [0, 1, 3].map { RoomStatusCopy.missing(missingCount: $0, resend: r) } }
            + listed.map { RoomStatusCopy.listed($0, sentAt: now.addingTimeInterval(-600), now: now) }
    }

    // MARK: - Shape

    func testEveryStateIsThreeStepsWithAtMostOneHappeningNow() {
        for status in everyState {
            XCTAssertEqual(status.steps.count, 3, status.guest)
            XCTAssertLessThanOrEqual(status.steps.filter { $0.mark == .now }.count, 1, status.guest)
            XCTAssertFalse(status.cardLine.isEmpty)
            XCTAssertFalse(status.guest.isEmpty)
        }
    }

    func testTheRetiredIdiomIsGone() {
        for status in everyState {
            let words = [status.guest, status.note ?? "", status.primary?.label ?? "", status.secondary?.label ?? ""]
                + status.steps.flatMap { [$0.title, $0.detail ?? ""] }
            for text in words where !text.isEmpty {
                XCTAssertFalse(text.lowercased().contains("desk"), "the desk is gone as a word: \(text)")
                XCTAssertFalse(text.contains("·"), "no middle-dot status lines: \(text)")
                XCTAssertNotEqual(text, text.uppercased(), "no capitals-only labels: \(text)")
            }
        }
    }

    // MARK: - Time

    func testElapsedIsCountedFromTheServerAnchorAndNeverInvented() {
        let anchored = RoomStatusCopy.onItsWay(.working(anchor: now.addingTimeInterval(-268), longRunning: false), now: now)
        XCTAssertEqual(anchored.steps[1].detail, "4 min so far")
        XCTAssertEqual(anchored.cardLine, "Being rebuilt, 4 min so far")

        let unanchored = RoomStatusCopy.onItsWay(.working(anchor: nil, longRunning: false), now: now)
        XCTAssertNil(unanchored.steps[1].detail, "no anchor, no time")

        let skewed = RoomStatusCopy.onItsWay(.working(anchor: now.addingTimeInterval(600), longRunning: false), now: now)
        XCTAssertNil(skewed.steps[1].detail, "an anchor in the future is not a time to count from")
    }

    func testNoStateClaimsHowLongIsLeft() {
        for status in everyState {
            let text = ([status.guest, status.note ?? ""] + status.steps.compactMap(\.detail)).joined(separator: " ").lowercased()
            for claim in ["left", "almost", "nearly", "estimated", "about 2 min", "any moment"] {
                XCTAssertFalse(text.contains(claim), "time claim \(claim): \(text)")
            }
        }
    }

    // MARK: - Honesty about the scan

    func testAStalledUploadIsNeverCalledSafeAboveTheButtonThatFreesIt() {
        // The old Notes card said "It's still here on your phone, safe" above
        // "Got it", and Got it reclaimed the capture.
        let status = RoomStatusCopy.needsYou(.uploadFailed(reason: nil))
        XCTAssertFalse(status.guest.lowercased().contains("safe"))
        XCTAssertEqual(status.secondary?.label, "Let this scan go")
        XCTAssertEqual(status.secondary?.action, .discard)
    }

    func testTheDiagnosticIsCarriedOnlyWhenOneWasPersisted() {
        XCTAssertEqual(RoomStatusCopy.needsYou(.uploadFailed(reason: "blob_x")).details, "blob_x")
        XCTAssertNil(RoomStatusCopy.needsYou(.uploadFailed(reason: nil)).details)
    }

    func testARefusalOffersNoRetry() {
        let status = RoomStatusCopy.needsYou(.sendFailedTerminal)
        XCTAssertNotEqual(status.primary?.action, .sendAgain)
        XCTAssertNotEqual(status.secondary?.action, .sendAgain)
    }

    func testPausedOffersNothingToDo() {
        // An upload may still be running, so there is nothing to let go.
        let status = RoomStatusCopy.onItsWay(.paused, now: now)
        XCTAssertNil(status.primary)
        XCTAssertNil(status.secondary)
    }

    func testCheckAgainAppearsOnlyOnceTheLoopHasStopped() {
        XCTAssertNil(RoomStatusCopy.onItsWay(.checkFailed(anchor: now, stopped: false), now: now).primary)
        XCTAssertEqual(RoomStatusCopy.onItsWay(.checkFailed(anchor: now, stopped: true), now: now).primary?.action, .checkAgain)
    }

    // MARK: - Missing files: the offer comes from FailureCopy

    func testTheMissingFilesOfferIsFailureCopys() {
        for resend: FailureCopy.Resend in [.available, .inFlight, .failed, .unavailable] {
            let status = RoomStatusCopy.missing(missingCount: 3, resend: resend)
            let actions = FailureCopy.recoverableActions(resend)
            XCTAssertEqual(status.primary?.label, actions.primaryLabel)
            XCTAssertEqual(status.primary?.enabled, actions.primaryEnabled)
            XCTAssertEqual(status.secondary?.label, actions.secondaryLabel)
            XCTAssertEqual(status.guest, FailureCopy.incompleteBody(missingCount: 3, resend: resend))
        }
    }

    func testOnlyTheSendingStateIsBusy() {
        XCTAssertEqual(RoomStatusCopy.missing(missingCount: 3, resend: .inFlight).primary?.busy, true)
        for resend: FailureCopy.Resend in [.available, .failed, .unavailable] {
            XCTAssertEqual(RoomStatusCopy.missing(missingCount: 3, resend: resend).primary?.busy, false)
        }
    }

    func testTheMissingCountAgrees() {
        XCTAssertEqual(RoomStatusCopy.missing(missingCount: 1, resend: .available).steps[0].title,
                       "Sent, but one file didn\u{2019}t arrive")
        XCTAssertEqual(RoomStatusCopy.missing(missingCount: 3, resend: .available).steps[0].title,
                       "Sent, but 3 files didn\u{2019}t arrive")
        XCTAssertFalse(RoomStatusCopy.missing(missingCount: 0, resend: .unavailable).steps[0].title.contains("0"),
                       "an unnamed count is not a zero")
    }

    // MARK: - Attention

    func testOnlyAStoppedRoomAsksForAttention() {
        XCTAssertFalse(RoomStatusCopy.onItsWay(.sending, now: now).needsAttention)
        XCTAssertFalse(RoomStatusCopy.onItsWay(.working(anchor: nil, longRunning: false), now: now).needsAttention)
        XCTAssertTrue(RoomStatusCopy.onItsWay(.retryableSendFailure, now: now).needsAttention)
        XCTAssertTrue(RoomStatusCopy.needsYou(.processingFailed).needsAttention)
        XCTAssertTrue(RoomStatusCopy.listed(.failedIncomplete, sentAt: nil, now: now).needsAttention)
    }
}
