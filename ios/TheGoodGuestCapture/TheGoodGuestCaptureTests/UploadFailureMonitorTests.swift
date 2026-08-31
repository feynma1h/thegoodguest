/// Tests for UploadFailureMonitor: the .failed-record scan (refresh), the in-process
/// kick (notifyUploadFailed), and session-local dismissal.
///
/// Strategy: drive the monitor against an UploadSessionStore in a temp directory —
/// the same seam BlobUploadManagerTests uses — and assert the published state.
/// No BlobUploadManager involvement: the kick's call site is one line in
/// onFatalBlobError; the surfaced-state semantics all live here.

import XCTest
@testable import TheGoodGuestCapture

@MainActor
final class UploadFailureMonitorTests: XCTestCase {

    // MARK: - Helpers

    private func makeStore() -> UploadSessionStore {
        let dir = FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString)
        addTeardownBlock { try? FileManager.default.removeItem(at: dir) }
        return UploadSessionStore(directory: dir)
    }

    /// Save a record for `bundleId` in the given phase. bundleId must be a UUID string
    /// (allBundleIds filters on that). Mint timestamp is configurable so recency
    /// selection can be pinned.
    private func saveRecord(
        _ store: UploadSessionStore,
        bundleId: String,
        phase: UploadPhase,
        failureReason: String? = nil,
        mintTimestamp: Date = Date()
    ) async throws {
        let entries = [
            UploadSessionEntry(relativePath: "frames/000000.jpg",
                               sessionUri: "https://gcs.example.com/f0"),
            UploadSessionEntry(relativePath: "bundle.pb",
                               sessionUri: "https://gcs.example.com/bp"),
        ]
        let record = UploadSessionRecord(
            bundleId:            bundleId,
            tierRawValue:        1,
            clientMintTimestamp: mintTimestamp,
            sessionEntries:      entries,
            manifestPaths:       ["frames/000000.jpg", "bundle.pb"],
            outputDir:           FileManager.default.temporaryDirectory
        ).markingPhase(phase, failureReason: failureReason)
        try await store.save(record)
    }

    private let idA = "00000000-0000-0000-0000-00000000000a"
    private let idB = "00000000-0000-0000-0000-00000000000b"
    private let idC = "00000000-0000-0000-0000-00000000000c"

    // MARK: - refresh: the .failed scan

    func test_refresh_failedRecord_surfacesBundleAndReason() async throws {
        let store = makeStore()
        try await saveRecord(store, bundleId: idA, phase: .failed, failureReason: "http_403")
        let monitor = UploadFailureMonitor(store: store)

        await monitor.refresh()

        XCTAssertEqual(monitor.latestFailure,
                       .init(bundleId: idA, reason: "http_403"),
                       "refresh must surface a persisted .failed record with its reason")
    }

    func test_refresh_nonFailedPhases_surfaceNothing() async throws {
        // .uploadingBlobs, .uploadingBundlePb, and .complete are not failures.
        let store = makeStore()
        try await saveRecord(store, bundleId: idA, phase: .uploadingBlobs)
        try await saveRecord(store, bundleId: idB, phase: .uploadingBundlePb)
        try await saveRecord(store, bundleId: idC, phase: .complete)
        let monitor = UploadFailureMonitor(store: store)

        await monitor.refresh()

        XCTAssertNil(monitor.latestFailure,
                     "Only uploadPhase == .failed may surface")
    }

    func test_refresh_multipleFailed_picksMostRecentMint() async throws {
        let store = makeStore()
        try await saveRecord(store, bundleId: idA, phase: .failed, failureReason: "http_400",
                             mintTimestamp: Date(timeIntervalSince1970: 1_000))
        try await saveRecord(store, bundleId: idB, phase: .failed, failureReason: "http_403",
                             mintTimestamp: Date(timeIntervalSince1970: 2_000))
        let monitor = UploadFailureMonitor(store: store)

        await monitor.refresh()

        XCTAssertEqual(monitor.latestFailure?.bundleId, idB,
                       "The most recently minted .failed bundle must win")
        XCTAssertEqual(monitor.latestFailure?.reason, "http_403")
    }

    func test_refresh_missingFailureReason_surfacesPlaceholder() async throws {
        // failureReason should always accompany .failed (onFatalBlobError sets both),
        // but a nil must not hide the failure itself.
        let store = makeStore()
        try await saveRecord(store, bundleId: idA, phase: .failed, failureReason: nil)
        let monitor = UploadFailureMonitor(store: store)

        await monitor.refresh()

        XCTAssertEqual(monitor.latestFailure,
                       .init(bundleId: idA, reason: "unknown"))
    }

    func test_refresh_noFailedRecords_doesNotClearSurfacedState() async throws {
        // refresh never clears: no code path un-fails a record, so a surfaced failure
        // stays until dismiss(). Covers the kick-then-scan window where the record
        // write may have failed silently.
        let store = makeStore()
        let monitor = UploadFailureMonitor(store: store)
        monitor.notifyUploadFailed(bundleId: idA, reason: "http_400")

        await monitor.refresh()

        XCTAssertEqual(monitor.latestFailure,
                       .init(bundleId: idA, reason: "http_400"),
                       "A scan that finds nothing must leave kick-surfaced state alone")
    }

    // MARK: - notifyUploadFailed: the in-process kick

    func test_notify_surfacesImmediately_withoutStore() async {
        let monitor = UploadFailureMonitor(store: makeStore())

        monitor.notifyUploadFailed(bundleId: idA, reason: "308_persistent")

        XCTAssertEqual(monitor.latestFailure,
                       .init(bundleId: idA, reason: "308_persistent"),
                       "The kick must surface without any disk read")
    }

    // MARK: - dismiss: session-local

    func test_dismiss_clearsSurfacedFailure_andSticksForThisLaunch() async throws {
        let store = makeStore()
        try await saveRecord(store, bundleId: idA, phase: .failed, failureReason: "http_403")
        let monitor = UploadFailureMonitor(store: store)
        await monitor.refresh()
        XCTAssertNotNil(monitor.latestFailure, "Pre-condition: failure surfaced")

        await monitor.dismiss()

        XCTAssertNil(monitor.latestFailure, "Dismiss must clear the surfaced failure")
        await monitor.refresh()
        XCTAssertNil(monitor.latestFailure,
                     "A dismissed bundle must not resurface via refresh in the same launch")
        monitor.notifyUploadFailed(bundleId: idA, reason: "http_403")
        XCTAssertNil(monitor.latestFailure,
                     "A dismissed bundle must not resurface via the kick in the same launch")
    }

    func test_dismiss_surfacesNextFailedBundle() async throws {
        // Two failed bundles: dismissing the surfaced one rescans and shows the other.
        let store = makeStore()
        try await saveRecord(store, bundleId: idA, phase: .failed, failureReason: "http_400",
                             mintTimestamp: Date(timeIntervalSince1970: 1_000))
        try await saveRecord(store, bundleId: idB, phase: .failed, failureReason: "http_403",
                             mintTimestamp: Date(timeIntervalSince1970: 2_000))
        let monitor = UploadFailureMonitor(store: store)
        await monitor.refresh()
        XCTAssertEqual(monitor.latestFailure?.bundleId, idB, "Pre-condition: most recent surfaced")

        await monitor.dismiss()

        XCTAssertEqual(monitor.latestFailure?.bundleId, idA,
                       "Dismissing the surfaced failure must let the next .failed bundle show")
    }

    func test_freshLaunch_resurfacesUndismissedFailure() async throws {
        // Dismissal is in-memory: a new monitor (new launch) over the same store
        // surfaces the failure again — the condition still holds on disk.
        let store = makeStore()
        try await saveRecord(store, bundleId: idA, phase: .failed, failureReason: "http_403")
        let firstLaunch = UploadFailureMonitor(store: store)
        await firstLaunch.refresh()
        await firstLaunch.dismiss()
        XCTAssertNil(firstLaunch.latestFailure, "Pre-condition: dismissed in launch 1")

        let secondLaunch = UploadFailureMonitor(store: store)
        await secondLaunch.refresh()

        XCTAssertEqual(secondLaunch.latestFailure?.bundleId, idA,
                       "A persisted .failed record must resurface on the next launch")
    }
}
