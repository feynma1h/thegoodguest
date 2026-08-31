/// Pins for ScenePoller's flight expectation (the RootFlowView-era survivor of
/// the room-shell-residue (3) stale-panel finding): while a flight expectation
/// is set, a DIFFERENT bundle's completion kick must not start polling — a
/// previous capture's resumed upload finishing cross-launch would otherwise
/// render its doorway over the new capture's wait.
///
/// Plus the stand-down that is the same judgment on the way OUT: declaring a
/// flight for a different bundle drops what the previous one published, so no
/// surface can render a finished room over a scan still on its way up. That
/// lives in expectBundle rather than at the send sites because a rule spelled
/// out at each site is a rule one site can be written without.

import XCTest
@testable import TheGoodGuest

@MainActor
final class ScenePollExpectationTests: XCTestCase {

    /// Poller whose GET always answers ready — any started loop terminates on
    /// its first tick, so tests never leave a live loop behind.
    private func makePoller() -> ScenePoller {
        let ready: [String: Any] = [
            "scene_id": "s1", "bundle_id": "b1", "status": "ready",
            "result_uri": "gs://bucket/obj", "missing_paths": [],
            "created_at": ISO8601DateFormatter().string(from: Date()),
            "updated_at": ISO8601DateFormatter().string(from: Date()),
        ]
        let data = try! JSONSerialization.data(withJSONObject: ready)
        return ScenePoller(
            now: { Date() },
            sleep: { _ in },
            performGET: { _, _ in .success((200, data)) },
            tokenProvider: { "token" }
        )
    }

    func test_expectationSet_otherBundleCompletion_ignored() {
        let poller = makePoller()
        poller.setVisible(true)
        poller.expectBundle("new-bundle")

        poller.notifyBundleComplete(bundleId: "old-bundle")

        XCTAssertEqual(poller.pollState, .idle, "a foreign completion must not start the loop")
        XCTAssertNil(poller.currentBundleId)
    }

    func test_expectationSet_matchingBundleCompletion_starts() {
        let poller = makePoller()
        poller.setVisible(true)
        poller.expectBundle("new-bundle")

        poller.notifyBundleComplete(bundleId: "new-bundle")

        guard case .polling = poller.pollState else {
            return XCTFail("matching completion must start polling, got \(poller.pollState)")
        }
        XCTAssertEqual(poller.currentBundleId, "new-bundle")
        poller.reset()
    }

    func test_noExpectation_anyBundleCompletion_starts_legacyPath() {
        // The restore/re-entry path sets no expectation; the kick keeps its
        // original semantics there.
        let poller = makePoller()
        poller.setVisible(true)

        poller.notifyBundleComplete(bundleId: "restored-bundle")

        guard case .polling = poller.pollState else {
            return XCTFail("with no expectation any completion may start, got \(poller.pollState)")
        }
        XCTAssertEqual(poller.currentBundleId, "restored-bundle")
        poller.reset()
    }

    func test_reset_clearsExpectation() {
        let poller = makePoller()
        poller.setVisible(true)
        poller.expectBundle("new-bundle")
        poller.reset()

        poller.notifyBundleComplete(bundleId: "old-bundle")

        guard case .polling = poller.pollState else {
            return XCTFail("reset must clear the expectation (legacy semantics return)")
        }
        poller.reset()
    }

    func test_visibilityGate_unchanged_matchingButInvisible_isNoOp() {
        let poller = makePoller()
        poller.setVisible(false)
        poller.expectBundle("new-bundle")

        poller.notifyBundleComplete(bundleId: "new-bundle")

        XCTAssertEqual(poller.pollState, .idle, "visibility gate stays the outer guard")
    }

    // MARK: - Standing the previous room down

    /// Drive a poller to a finished room, the state a status surface renders as
    /// "Room ready".
    private func pollerHoldingAFinishedRoom(_ bundleId: String) async -> ScenePoller {
        let poller = makePoller()
        poller.setVisible(true)
        poller.start(bundleId: bundleId)
        await poller._runTask?.value
        return poller
    }

    func test_newFlight_dropsThePreviousRoomsTerminalStatus() async {
        let poller = await pollerHoldingAFinishedRoom("room-one")
        guard case .succeeded = poller.pollState else {
            return XCTFail("setup: expected a finished room, got \(poller.pollState)")
        }

        // All a send site does when the next capture's bundle is ready.
        poller.expectBundle("room-two")

        XCTAssertEqual(poller.pollState, .idle,
                       "a fresh send must not leave the previous room's outcome on screen")
        XCTAssertNil(poller.currentBundleId,
                     "nor leave the surface able to act on the previous room")
    }

    func test_newFlight_alsoDropsAPreviousRoomsFailure() async {
        // Every terminal state is the previous room's, not just the happy one.
        let failed: [String: Any] = [
            "scene_id": "s1", "bundle_id": "b1", "status": "failed",
            "result_uri": "", "missing_paths": [],
            "created_at": ISO8601DateFormatter().string(from: Date()),
            "updated_at": ISO8601DateFormatter().string(from: Date()),
        ]
        let data = try! JSONSerialization.data(withJSONObject: failed)
        let poller = ScenePoller(now: { Date() }, sleep: { _ in },
                                 performGET: { _, _ in .success((200, data)) },
                                 tokenProvider: { "token" })
        poller.setVisible(true)
        poller.start(bundleId: "room-one")
        await poller._runTask?.value
        guard case .failedTerminal = poller.pollState else {
            return XCTFail("setup: expected a failed room, got \(poller.pollState)")
        }

        poller.expectBundle("room-two")

        XCTAssertEqual(poller.pollState, .idle)
    }

    func test_redeclaringTheSameFlight_doesNotKillItsOwnPoll() {
        // The stand-down keys on a DIFFERENT bundle. Re-declaring the one in
        // flight — a send site called twice, a restore racing a send — must not
        // drop the live poll of the very room being waited on.
        let poller = makePoller()
        poller.setVisible(true)
        poller.expectBundle("room-one")
        poller.notifyBundleComplete(bundleId: "room-one")
        guard case .polling = poller.pollState else {
            return XCTFail("setup: expected a live poll, got \(poller.pollState)")
        }

        poller.expectBundle("room-one")

        guard case .polling = poller.pollState else {
            return XCTFail("re-declaring the same flight must not stand it down")
        }
        XCTAssertEqual(poller.currentBundleId, "room-one")
        poller.reset()
    }

    func test_clearingTheExpectation_doesNotStandDownALivePoll() {
        // nil means "no active flight", not "the room in flight is over".
        let poller = makePoller()
        poller.setVisible(true)
        poller.expectBundle("room-one")
        poller.notifyBundleComplete(bundleId: "room-one")

        poller.expectBundle(nil)

        guard case .polling = poller.pollState else {
            return XCTFail("clearing an expectation must not drop the poll")
        }
        poller.reset()
    }

    func test_afterStandDown_thePreviousRoomsOwnCompletionCannotResurrectIt() async {
        // The old bundle's blobs can still be finishing when the next capture is
        // sent — a resumed cross-launch upload. Its kick must not put the room
        // that is already done back on top of the one now going up.
        let poller = await pollerHoldingAFinishedRoom("room-one")

        poller.expectBundle("room-two")
        poller.notifyBundleComplete(bundleId: "room-one")

        XCTAssertEqual(poller.pollState, .idle)
        XCTAssertNil(poller.currentBundleId)
    }
}
