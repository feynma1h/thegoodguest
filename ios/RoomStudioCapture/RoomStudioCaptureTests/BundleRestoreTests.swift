/// Pins the launch-restore choice and the acknowledgement record it depends on.
///
/// The defect these exist for: home's `.task` re-fires on every return to `.home`
/// (not once per launch), and a `.complete` upload record is never deleted. The
/// first restore implementation combined those into a row that came back the
/// instant `endFlight()` cleared it — and came back on every launch thereafter,
/// permanently claiming a finished room was "on its way".
///
/// The launch latch lives in RootFlowView (@State, not testable offline); the two
/// halves that ARE pure — which candidate wins, and what "the user finished with
/// this" means across launches — are pinned here.

import XCTest
@testable import RoomStudioCapture

final class BundleRestoreTests: XCTestCase {

    private func candidate(_ id: String, _ phase: UploadPhase, _ offset: TimeInterval) -> BundleRestore.Candidate {
        .init(bundleId: id, phase: phase, minted: Date(timeIntervalSince1970: 1_700_000_000 + offset))
    }

    // MARK: - The choice

    func testPicksNewestEligible() {
        let picked = BundleRestore.pick(
            from: [candidate("old", .complete, 0),
                   candidate("new", .uploadingBlobs, 100),
                   candidate("mid", .uploadingBundlePb, 50)],
            dismissed: [])
        XCTAssertEqual(picked, "new")
    }

    /// A `.complete` record IS eligible — recovering a bundle whose upload finished
    /// while the app was dead is the entire point of the restore.
    func testCompleteIsEligible() {
        XCTAssertEqual(
            BundleRestore.pick(from: [candidate("done", .complete, 0)], dismissed: []),
            "done")
    }

    /// Failed uploads belong to UploadFailureMonitor's banner, not the "on its way" row.
    func testFailedIsSkipped() {
        XCTAssertNil(BundleRestore.pick(from: [candidate("bad", .failed, 10)], dismissed: []))
        XCTAssertEqual(
            BundleRestore.pick(from: [candidate("bad", .failed, 10),
                                      candidate("ok", .complete, 0)],
                               dismissed: []),
            "ok",
            "a newer failed record must not shadow an older eligible one")
    }

    /// THE REGRESSION: endFlight() acknowledges the bundle, so the restore must not
    /// re-adopt it — otherwise every terminal exit is undone and home re-advertises
    /// a finished room on every launch forever.
    func testDismissedBundleIsNeverReAdopted() {
        XCTAssertNil(
            BundleRestore.pick(from: [candidate("done", .complete, 0)],
                               dismissed: ["done"]))
    }

    /// Dismissing one bundle must not hide another still genuinely in flight.
    func testDismissalIsPerBundle() {
        XCTAssertEqual(
            BundleRestore.pick(from: [candidate("done", .complete, 100),
                                      candidate("live", .uploadingBlobs, 0)],
                               dismissed: ["done"]),
            "live")
    }

    func testEmptyStoreYieldsNothing() {
        XCTAssertNil(BundleRestore.pick(from: [], dismissed: []))
    }

    // MARK: - The acknowledgement record

    private func freshDefaults() throws -> UserDefaults {
        let name = "BundleRestoreTests.\(UUID().uuidString)"
        let defaults = try XCTUnwrap(UserDefaults(suiteName: name))
        addTeardownBlock { defaults.removePersistentDomain(forName: name) }
        return defaults
    }

    func testAcknowledgeRecordsAndPersists() throws {
        let defaults = try freshDefaults()
        DismissedBundles(defaults: defaults).acknowledge("a")
        // A SEPARATE instance reads it back: the record has to outlive the value type,
        // because the launch that re-adopts is a different launch from the dismissal.
        XCTAssertTrue(DismissedBundles(defaults: defaults).set.contains("a"))
    }

    func testAcknowledgeIsIdempotent() throws {
        let defaults = try freshDefaults()
        let store = DismissedBundles(defaults: defaults)
        store.acknowledge("a")
        store.acknowledge("a")
        XCTAssertEqual(store.ids, ["a"])
    }

    func testUnknownBundleIsNotDismissed() throws {
        let defaults = try freshDefaults()
        XCTAssertFalse(DismissedBundles(defaults: defaults).set.contains("never-seen"))
    }

    /// Bounded growth, evicting oldest-first — so the entry that can ever be lost is
    /// the one the user finished with longest ago.
    func testRetentionCapEvictsOldestFirst() throws {
        let defaults = try freshDefaults()
        let store = DismissedBundles(defaults: defaults)
        for i in 0..<(DismissedBundles.maxRetained + 5) {
            store.acknowledge("bundle-\(i)")
        }
        let ids = store.ids
        XCTAssertEqual(ids.count, DismissedBundles.maxRetained)
        XCTAssertEqual(ids.first, "bundle-5", "oldest entries are the ones evicted")
        XCTAssertEqual(ids.last, "bundle-\(DismissedBundles.maxRetained + 4)")
    }
}
