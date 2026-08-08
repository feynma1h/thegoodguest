/// Pins the three Live Activity decisions (LiveActivityPolicy) as tables.
///
/// The merge rule and the throttle are the two places this feature can lie: a
/// late background progress update reopening a finished room, or a slow trickle
/// that never publishes at all. Both are stated here as facts rather than left to
/// be re-derived from a completion handler.

import XCTest
@testable import RoomStudioCapture

final class LiveActivityPolicyTests: XCTestCase {

    private let t0 = Date(timeIntervalSince1970: 1_800_000_000)

    // MARK: - merge: terminal stickiness

    func test_merge_firstStage_isAdopted() {
        XCTAssertEqual(LiveActivityPolicy.merge(current: nil, incoming: .preparing), .preparing)
    }

    func test_merge_terminalIsStickyAgainstLateProgress() {
        // The real sequence: poller says ready, then a background blob completion
        // lands (the session keeps delivering for a while after finalize).
        let merged = LiveActivityPolicy.merge(current: .ready,
                                              incoming: .sending(sent: 126, total: 127))
        XCTAssertEqual(merged, .ready, "a late blob completion must not reopen a finished room")
    }

    func test_merge_terminalIsStickyAgainstPause() {
        XCTAssertEqual(
            LiveActivityPolicy.merge(current: .failed(.upload), incoming: .paused),
            .failed(.upload)
        )
    }

    func test_merge_terminalOverTerminalIsAllowed() {
        // The poller is the more informed answer: a local upload failure followed
        // by a real pipeline verdict should show the pipeline's.
        XCTAssertEqual(
            LiveActivityPolicy.merge(current: .failed(.upload), incoming: .failed(.processing)),
            .failed(.processing)
        )
        XCTAssertEqual(LiveActivityPolicy.merge(current: .ready, incoming: .failed(.incomplete)),
                       .failed(.incomplete))
    }

    func test_merge_nonTerminalProgressesFreely() {
        XCTAssertEqual(
            LiveActivityPolicy.merge(current: .sending(sent: 3, total: 10), incoming: .queued),
            .queued
        )
        XCTAssertEqual(LiveActivityPolicy.merge(current: .paused,
                                                incoming: .sending(sent: 4, total: 10)),
                       .sending(sent: 4, total: 10))
    }

    // MARK: - shouldPublish

    func test_shouldPublish_firstEverAlways() {
        XCTAssertTrue(LiveActivityPolicy.shouldPublish(
            previous: nil, next: .sending(sent: 0, total: 100),
            lastPublishedAt: nil, now: t0))
    }

    func test_shouldPublish_stageKindChangeAlways_evenImmediately() {
        XCTAssertTrue(LiveActivityPolicy.shouldPublish(
            previous: .preparing, next: .sending(sent: 0, total: 100),
            lastPublishedAt: t0, now: t0), "a kind change is the information — never throttled")
    }

    func test_shouldPublish_terminalAlways_evenImmediately() {
        XCTAssertTrue(LiveActivityPolicy.shouldPublish(
            previous: .sending(sent: 99, total: 100), next: .ready,
            lastPublishedAt: t0, now: t0))
        XCTAssertTrue(LiveActivityPolicy.shouldPublish(
            previous: .sending(sent: 5, total: 100), next: .failed(.upload),
            lastPublishedAt: t0, now: t0))
    }

    func test_shouldPublish_progressBelowStep_isSuppressed() {
        // 1/1000 → 2/1000 is still 0% — nothing on screen would change.
        XCTAssertFalse(LiveActivityPolicy.shouldPublish(
            previous: .sending(sent: 1, total: 1000), next: .sending(sent: 2, total: 1000),
            lastPublishedAt: t0, now: t0.addingTimeInterval(60)))
    }

    func test_shouldPublish_progressSteppedButTooSoon_isSuppressed() {
        XCTAssertFalse(LiveActivityPolicy.shouldPublish(
            previous: .sending(sent: 10, total: 100), next: .sending(sent: 15, total: 100),
            lastPublishedAt: t0, now: t0.addingTimeInterval(0.5)))
    }

    func test_shouldPublish_progressSteppedAndIntervalElapsed() {
        XCTAssertTrue(LiveActivityPolicy.shouldPublish(
            previous: .sending(sent: 10, total: 100), next: .sending(sent: 15, total: 100),
            lastPublishedAt: t0, now: t0.addingTimeInterval(LiveActivityPolicy.minProgressInterval)))
    }

    func test_shouldPublish_uploadCompletion_bypassesTheInterval() {
        // "all of it is up" is the one progress value worth spending budget on
        // immediately: the next thing the user sees is the pipeline, not a bar.
        XCTAssertTrue(LiveActivityPolicy.shouldPublish(
            previous: .sending(sent: 99, total: 100), next: .sending(sent: 100, total: 100),
            lastPublishedAt: t0, now: t0))
    }

    func test_shouldPublish_totalChange_alwaysPublishes() {
        // A re-mint can change the path set; the denominator on screen must follow.
        XCTAssertTrue(LiveActivityPolicy.shouldPublish(
            previous: .sending(sent: 5, total: 100), next: .sending(sent: 5, total: 120),
            lastPublishedAt: t0, now: t0))
    }

    func test_shouldPublish_identicalNonSendingStage_isSuppressed() {
        XCTAssertFalse(LiveActivityPolicy.shouldPublish(
            previous: .analyzing, next: .analyzing,
            lastPublishedAt: t0, now: t0.addingTimeInterval(600)))
        // A deferral storm across ~127 concurrent blobs must not publish 127 times.
        XCTAssertFalse(LiveActivityPolicy.shouldPublish(
            previous: .paused, next: .paused,
            lastPublishedAt: t0, now: t0.addingTimeInterval(600)))
    }

    // MARK: - WaitScreen → stage (the mirroring table)

    func test_stageForScreen_table() {
        XCTAssertEqual(LiveActivityPolicy.stage(for: .waiting(phase: .queued, anchor: nil)), .queued)
        XCTAssertEqual(LiveActivityPolicy.stage(for: .waiting(phase: .analyzing, anchor: nil)), .analyzing)
        XCTAssertEqual(LiveActivityPolicy.stage(for: .waiting(phase: .longRunning, anchor: nil)), .analyzing)
        XCTAssertEqual(LiveActivityPolicy.stage(for: .doorway), .ready)
        XCTAssertEqual(LiveActivityPolicy.stage(for: .processingFailed), .failed(.processing))
        // The count reaches the in-app screen, never the Lock Screen: a card a
        // stranger can read over a shoulder says what happened, not how much.
        XCTAssertEqual(LiveActivityPolicy.stage(for: .incompleteUpload(missingCount: 1)),
                       .failed(.incomplete))
        XCTAssertEqual(LiveActivityPolicy.stage(for: .incompleteUpload(missingCount: 40)),
                       .failed(.incomplete))
        XCTAssertEqual(LiveActivityPolicy.stage(for: .uploadFailed), .failed(.upload))
        XCTAssertEqual(LiveActivityPolicy.stage(for: .sendFailed(terminal: false)), .failed(.upload))
        XCTAssertEqual(LiveActivityPolicy.stage(for: .sendFailed(terminal: true)), .failed(.upload))
        XCTAssertEqual(LiveActivityPolicy.stage(for: .sendPaused), .paused)
    }

    func test_stageForScreen_sendingDefersToTheBackgroundCount() {
        // .sending covers session setup AND the whole upload; the background path
        // already reports it in finer grain. Overriding would throw the count away.
        XCTAssertNil(LiveActivityPolicy.stage(for: .sending))
    }

    func test_stageForScreen_checkFailedIsNotAFailure() {
        // The room IS up there. A poll-side connectivity blip must never flip the
        // Lock Screen to a failure treatment for a capture that is fine.
        XCTAssertNil(LiveActivityPolicy.stage(for: .checkFailed(anchor: nil, stopped: false)))
        XCTAssertNil(LiveActivityPolicy.stage(for: .checkFailed(anchor: nil, stopped: true)))
    }

    func test_stageForScreen_notOursNarratesNothing() {
        // Decision 0074: the flow stands down and ends the card outright rather
        // than narrating a room this identity never owned.
        XCTAssertNil(LiveActivityPolicy.stage(for: .notOurs))
    }

    // MARK: - Stage vocabulary

    func test_isTerminal_isExactlyReadyAndFailed() {
        XCTAssertTrue(RoomActivityStage.ready.isTerminal)
        XCTAssertTrue(RoomActivityStage.failed(.upload).isTerminal)
        for stage: RoomActivityStage in [.preparing, .sending(sent: 1, total: 2), .queued,
                                         .analyzing, .paused] {
            XCTAssertFalse(stage.isTerminal, "\(stage) must not end the activity")
        }
    }

    func test_fraction_onlyWhereThereIsAnHonestNumber() {
        XCTAssertEqual(RoomActivityStage.sending(sent: 25, total: 100).fraction, 0.25)
        XCTAssertNil(RoomActivityStage.sending(sent: 0, total: 0).fraction,
                     "an unknown total must not render as 0% — it renders as no bar")
        XCTAssertNil(RoomActivityStage.analyzing.fraction)
        XCTAssertEqual(RoomActivityStage.sending(sent: 130, total: 100).fraction, 1.0,
                       "clamped: a miscount must never draw past the end of the bar")
    }
}
