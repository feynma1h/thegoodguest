/// Pins LiveActivityController's lifecycle through the LiveActivityHost seam.
///
/// The seam exists because ActivityKit does nothing in a unit-test host — no
/// activity is ever created — so a controller talking to it directly would be
/// untestable by construction. What is pinned here is everything the controller
/// decides: bundle scoping (the wrong-capture class this project has been bitten
/// by twice), the terminal end, and launch adoption.

import XCTest
@testable import RoomStudioCapture

// MARK: - Fake host

@MainActor
private final class FakeHost: LiveActivityHost {
    enum Call: Equatable {
        case start(String, RoomActivityStage)
        case update(RoomActivityStage)
        case end(RoomActivityStage)
        case endOrphans(keeping: String?)
    }

    var areActivitiesEnabled = true
    var isRunning = false
    private(set) var calls: [Call] = []

    func start(attributes: RoomActivityAttributes, state: RoomActivityState, staleDate: Date?) {
        isRunning = true
        calls.append(.start(attributes.bundleId, state.stage))
    }
    func update(state: RoomActivityState, staleDate: Date?) {
        calls.append(.update(state.stage))
    }
    func end(state: RoomActivityState, dismissAfter: Date?) {
        isRunning = false
        calls.append(.end(state.stage))
    }
    func endAllOrphans(keeping bundleId: String?) {
        calls.append(.endOrphans(keeping: bundleId))
    }
    var stageUpdates: [RoomActivityStage] {
        calls.compactMap { if case .update(let s) = $0 { return s } else { return nil } }
    }
}

@MainActor
final class LiveActivityControllerTests: XCTestCase {

    private var host: FakeHost!
    private var controller: LiveActivityController!
    private var now = Date(timeIntervalSince1970: 1_800_000_000)

    override func setUp() async throws {
        try await super.setUp()
        host = FakeHost()
        controller = LiveActivityController(host: host)
        controller.clock = { [unowned self] in self.now }
    }

    private func advance(_ seconds: TimeInterval) { now = now.addingTimeInterval(seconds) }

    // MARK: - Start

    func test_begin_startsAtPreparing_andSweepsOrphansFirst() {
        controller.begin(bundleId: "A")
        XCTAssertEqual(host.calls, [.endOrphans(keeping: "A"), .start("A", .preparing)])
        XCTAssertEqual(controller.currentBundleId, "A")
    }

    func test_begin_isIdempotentForTheSameBundle() {
        controller.begin(bundleId: "A")
        controller.begin(bundleId: "A")
        XCTAssertEqual(host.calls.count, 2, "a second begin for a live card must not restart it")
    }

    func test_begin_whenActivitiesDisabled_doesNothing() {
        host.areActivitiesEnabled = false
        controller.begin(bundleId: "A")
        XCTAssertTrue(host.calls.isEmpty)
        XCTAssertNil(controller.currentBundleId, "no card exists, so no bundle is being narrated")
    }

    func test_begin_forANewCapture_endsThePreviousCard() {
        controller.begin(bundleId: "A")
        controller.begin(bundleId: "B")
        XCTAssertEqual(host.calls.last, .start("B", .preparing))
        XCTAssertTrue(host.calls.contains(.endOrphans(keeping: "B")))
        XCTAssertEqual(controller.currentBundleId, "B")
    }

    // MARK: - Bundle scoping (the wrong-capture class)

    func test_updatesForAForeignBundleAreDropped() {
        controller.begin(bundleId: "A")
        advance(10)
        controller.noteUploadProgress(bundleId: "OTHER", sent: 50, total: 100)
        controller.noteUploadFailed(bundleId: "OTHER")
        controller.noteWaitScreen(.doorway, bundleId: "OTHER")
        XCTAssertTrue(host.stageUpdates.isEmpty)
        XCTAssertEqual(controller.currentStage, .preparing, "A's card still says what A is doing")
    }

    func test_endForAForeignBundleIsIgnored() {
        controller.begin(bundleId: "A")
        controller.end(bundleId: "OTHER")
        XCTAssertFalse(host.calls.contains { if case .end = $0 { return true } else { return false } })
        XCTAssertEqual(controller.currentBundleId, "A")
    }

    func test_noteWaitScreenWithNoFlightIsIgnored() {
        controller.begin(bundleId: "A")
        advance(10)
        controller.noteWaitScreen(.doorway, bundleId: nil)
        XCTAssertEqual(controller.currentStage, .preparing)
    }

    // MARK: - Progress

    func test_progressPublishes_thenThrottles_thenPublishesAgain() {
        controller.begin(bundleId: "A")
        advance(10)
        controller.noteUploadProgress(bundleId: "A", sent: 10, total: 100)   // kind change → publishes
        controller.noteUploadProgress(bundleId: "A", sent: 11, total: 100)   // too soon → suppressed
        XCTAssertEqual(host.stageUpdates, [.sending(sent: 10, total: 100)])

        advance(LiveActivityPolicy.minProgressInterval)
        controller.noteUploadProgress(bundleId: "A", sent: 20, total: 100)
        XCTAssertEqual(host.stageUpdates,
                       [.sending(sent: 10, total: 100), .sending(sent: 20, total: 100)])
    }

    func test_throttledProgressStillAdvancesTheComparisonBaseline() {
        // If a suppressed update were forgotten, every later comparison would be
        // made against a stale value and a slow trickle would never publish at all.
        controller.begin(bundleId: "A")
        advance(10)
        controller.noteUploadProgress(bundleId: "A", sent: 10, total: 100)
        controller.noteUploadProgress(bundleId: "A", sent: 40, total: 100)   // suppressed (too soon)
        XCTAssertEqual(controller.currentStage, .sending(sent: 40, total: 100),
                       "the stage is KNOWN even when it was not published")
    }

    // MARK: - Terminal

    func test_terminalEndsTheActivityRatherThanUpdatingIt() {
        controller.begin(bundleId: "A")
        advance(10)
        controller.noteWaitScreen(.doorway, bundleId: "A")
        XCTAssertEqual(host.calls.last, .end(.ready))
        XCTAssertTrue(host.stageUpdates.isEmpty)
    }

    func test_lateProgressAfterReadyDoesNotReopenTheCard() {
        controller.begin(bundleId: "A")
        advance(10)
        controller.noteWaitScreen(.doorway, bundleId: "A")
        advance(30)
        controller.noteUploadProgress(bundleId: "A", sent: 126, total: 127)
        XCTAssertEqual(controller.currentStage, .ready)
        XCTAssertTrue(host.stageUpdates.isEmpty, "no update may follow the end")
    }

    func test_uploadFailureEndsWithTheUploadTreatment() {
        controller.begin(bundleId: "A")
        advance(10)
        controller.noteUploadFailed(bundleId: "A")
        XCTAssertEqual(host.calls.last, .end(.failed(.upload)))
    }

    func test_pauseIsNotTerminal_andRecoversOnProgress() {
        controller.begin(bundleId: "A")
        advance(10)
        controller.noteUploadPaused(bundleId: "A")
        XCTAssertEqual(host.stageUpdates.last, .paused)
        advance(10)
        controller.noteUploadProgress(bundleId: "A", sent: 5, total: 50)
        XCTAssertEqual(host.stageUpdates.last, .sending(sent: 5, total: 50))
    }

    func test_endUsesTheStageTheCardLastShowed() {
        controller.begin(bundleId: "A")
        advance(10)
        controller.noteUploadProgress(bundleId: "A", sent: 5, total: 50)
        controller.end(bundleId: "A")
        XCTAssertEqual(host.calls.last, .end(.sending(sent: 5, total: 50)))
        XCTAssertNil(controller.currentBundleId)
    }

    // MARK: - Launch reconciliation

    func test_reconcileAdoptsTheRestoredFlight() {
        // The background session outlived the process, so the card is still live
        // and still correct — this process must be able to keep feeding it.
        controller.reconcileOnLaunch(restoredBundleId: "A")
        XCTAssertEqual(host.calls, [.endOrphans(keeping: "A")])
        XCTAssertEqual(controller.currentBundleId, "A")
        XCTAssertNil(controller.currentStage)

        controller.noteUploadProgress(bundleId: "A", sent: 60, total: 100)
        XCTAssertEqual(host.stageUpdates, [.sending(sent: 60, total: 100)],
                       "the first update after adoption publishes unconditionally")
    }

    func test_reconcileWithNothingRestored_sweepsEverything() {
        controller.reconcileOnLaunch(restoredBundleId: nil)
        XCTAssertEqual(host.calls, [.endOrphans(keeping: nil)])
        XCTAssertNil(controller.currentBundleId)
    }
}
