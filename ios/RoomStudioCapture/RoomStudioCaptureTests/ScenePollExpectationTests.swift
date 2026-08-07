/// Pins for ScenePoller's flight expectation (the RootFlowView-era survivor of
/// the room-shell-residue (3) stale-panel finding): while a flight expectation
/// is set, a DIFFERENT bundle's completion kick must not start polling — a
/// previous capture's resumed upload finishing cross-launch would otherwise
/// render its doorway over the new capture's wait.

import XCTest
@testable import RoomStudioCapture

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
}
