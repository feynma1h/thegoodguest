/// IO behavior pins for CaptureReaper (decision 0084).
///
/// The reaper's contracts under test:
///   • reclaim deletes the record AND the session dir (record first);
///   • reclaim REFUSES active-phase records regardless of the caller's claim;
///   • the launch scan never touches unacknowledged records, confirms
///     acknowledged .complete records via ONE positive GET before reclaiming
///     (no answer / non-terminal answer → retain), and reclaims acknowledged
///     .failed records without asking the server (no scene exists to ask).

import os
import XCTest
@testable import TheGoodGuestCapture

final class CaptureReaperTests: XCTestCase {

    private var storeDir: URL!
    private var store: UploadSessionStore!

    override func setUp() async throws {
        storeDir = FileManager.default.temporaryDirectory
            .appendingPathComponent("reaper-test-store-\(UUID().uuidString)")
        store = UploadSessionStore(directory: storeDir)
    }

    override func tearDown() async throws {
        try? FileManager.default.removeItem(at: storeDir)
    }

    // MARK: - Helpers

    /// A record whose outputDir is a real temp dir containing one blob file.
    /// Returns (bundleId, capture dir).
    @discardableResult
    private func seedRecord(
        phase: UploadPhase,
        bundleId: String = UUID().uuidString.lowercased()
    ) async throws -> (bundleId: String, dir: URL) {
        let dir = FileManager.default.temporaryDirectory
            .appendingPathComponent("reaper-test-capture-\(bundleId)")
        try FileManager.default.createDirectory(
            at: dir.appendingPathComponent("frames"), withIntermediateDirectories: true)
        try Data("jpeg-bytes".utf8).write(to: dir.appendingPathComponent("frames/000000.jpg"))
        let paths = ["frames/000000.jpg", "bundle.pb"]
        let entries = paths.map { UploadSessionEntry(relativePath: $0, sessionUri: "https://example.com/\($0)") }
        var record = UploadSessionRecord(
            bundleId:            bundleId,
            tierRawValue:        1,
            clientMintTimestamp: Date(),
            sessionEntries:      entries,
            manifestPaths:       paths,
            outputDir:           dir
        )
        record = record.markingPhase(phase)
        try await store.save(record)
        return (bundleId, dir)
    }

    /// Reaper with recorded fetch calls. `statusByBundle` maps bundleId → the
    /// canned confirming-GET answer (missing key = nil = no positive answer).
    private func makeReaper(
        acknowledged: Set<String>,
        statusByBundle: [String: SceneStatus] = [:]
    ) -> (reaper: CaptureReaper, fetchCalls: OSAllocatedUnfairLock<[String]>) {
        let calls = OSAllocatedUnfairLock<[String]>(initialState: [])
        let reaper = CaptureReaper(
            store: store,
            fetchStatus: { bundleId in
                calls.withLock { $0.append(bundleId) }
                return statusByBundle[bundleId]
            },
            acknowledged: { acknowledged }
        )
        return (reaper, calls)
    }

    private func recordExists(_ bundleId: String) async -> Bool {
        (try? await store.load(bundleId: bundleId)) != nil
    }

    // MARK: - reclaim

    func test_reclaim_completeRecord_deletesRecordAndDir() async throws {
        let (bundleId, dir) = try await seedRecord(phase: .complete)
        let (reaper, _) = makeReaper(acknowledged: [])

        await reaper.reclaim(bundleId: bundleId)

        let exists = await recordExists(bundleId)
        XCTAssertFalse(exists, "record must be deleted")
        XCTAssertFalse(FileManager.default.fileExists(atPath: dir.path), "session dir must be deleted")
    }

    func test_reclaim_failedRecord_deletesRecordAndDir() async throws {
        let (bundleId, dir) = try await seedRecord(phase: .failed)
        let (reaper, _) = makeReaper(acknowledged: [])

        await reaper.reclaim(bundleId: bundleId)

        let exists = await recordExists(bundleId)
        XCTAssertFalse(exists)
        XCTAssertFalse(FileManager.default.fileExists(atPath: dir.path))
    }

    func test_reclaim_refusesActivePhases_liveMachinerySurvivesCallerBugs() async throws {
        for phase in [UploadPhase.uploadingBlobs, .uploadingBundlePb] {
            let (bundleId, dir) = try await seedRecord(phase: phase)
            let (reaper, _) = makeReaper(acknowledged: [])

            await reaper.reclaim(bundleId: bundleId)

            let exists = await recordExists(bundleId)
            XCTAssertTrue(exists, "active record (\(phase)) must survive a reclaim call")
            XCTAssertTrue(FileManager.default.fileExists(atPath: dir.path))
            try? FileManager.default.removeItem(at: dir)
        }
    }

    func test_reclaim_missingDir_isSuccess_recordStillDeleted() async throws {
        let (bundleId, dir) = try await seedRecord(phase: .complete)
        try FileManager.default.removeItem(at: dir)
        let (reaper, _) = makeReaper(acknowledged: [])

        await reaper.reclaim(bundleId: bundleId)

        let exists = await recordExists(bundleId)
        XCTAssertFalse(exists)
    }

    func test_reclaim_missingRecord_isNoOp() async throws {
        let (reaper, _) = makeReaper(acknowledged: [])
        await reaper.reclaim(bundleId: "no-such-bundle")
        // Nothing to assert beyond "did not crash / did not create anything".
        let ids = (try? await store.allBundleIds()) ?? []
        XCTAssertTrue(ids.isEmpty)
    }

    // MARK: - Launch scan

    func test_launchScan_unacknowledgedComplete_untouched_andNeverFetched() async throws {
        let (bundleId, dir) = try await seedRecord(phase: .complete)
        let (reaper, calls) = makeReaper(acknowledged: [], statusByBundle: [bundleId: .ready])

        await reaper.reapAcknowledgedAtLaunch()

        let exists = await recordExists(bundleId)
        XCTAssertTrue(exists, "unacknowledged record is the restore's inventory")
        XCTAssertTrue(FileManager.default.fileExists(atPath: dir.path))
        XCTAssertEqual(calls.withLock { $0 }, [], "no confirming GET for unacknowledged records")
        try? FileManager.default.removeItem(at: dir)
    }

    func test_launchScan_acknowledgedComplete_serverReady_reclaims() async throws {
        let (bundleId, dir) = try await seedRecord(phase: .complete)
        let (reaper, calls) = makeReaper(acknowledged: [bundleId], statusByBundle: [bundleId: .ready])

        await reaper.reapAcknowledgedAtLaunch()

        let exists = await recordExists(bundleId)
        XCTAssertFalse(exists)
        XCTAssertFalse(FileManager.default.fileExists(atPath: dir.path))
        XCTAssertEqual(calls.withLock { $0 }, [bundleId])
    }

    func test_launchScan_acknowledgedComplete_serverFailedIncomplete_retains() async throws {
        let (bundleId, dir) = try await seedRecord(phase: .complete)
        let (reaper, _) = makeReaper(acknowledged: [bundleId], statusByBundle: [bundleId: .failedIncomplete])

        await reaper.reapAcknowledgedAtLaunch()

        let exists = await recordExists(bundleId)
        XCTAssertTrue(exists, "failed_incomplete keeps its files")
        XCTAssertTrue(FileManager.default.fileExists(atPath: dir.path))
        try? FileManager.default.removeItem(at: dir)
    }

    func test_launchScan_acknowledgedComplete_noAnswer_retains_neverReclaimOnAGuess() async throws {
        // Missing key = fetch returns nil (network down / 403 / 404 / decode).
        let (bundleId, dir) = try await seedRecord(phase: .complete)
        let (reaper, calls) = makeReaper(acknowledged: [bundleId])

        await reaper.reapAcknowledgedAtLaunch()

        let exists = await recordExists(bundleId)
        XCTAssertTrue(exists, "no positive confirmation → no deletion")
        XCTAssertTrue(FileManager.default.fileExists(atPath: dir.path))
        XCTAssertEqual(calls.withLock { $0 }, [bundleId])
        try? FileManager.default.removeItem(at: dir)
    }

    func test_launchScan_acknowledgedFailed_reclaimsWithoutFetch() async throws {
        let (bundleId, dir) = try await seedRecord(phase: .failed)
        let (reaper, calls) = makeReaper(acknowledged: [bundleId])

        await reaper.reapAcknowledgedAtLaunch()

        let exists = await recordExists(bundleId)
        XCTAssertFalse(exists)
        XCTAssertFalse(FileManager.default.fileExists(atPath: dir.path))
        XCTAssertEqual(calls.withLock { $0 }, [], "client-terminal .failed has no scene to ask about")
    }

    func test_launchScan_acknowledgedActiveUpload_untouched() async throws {
        let (bundleId, dir) = try await seedRecord(phase: .uploadingBlobs)
        let (reaper, calls) = makeReaper(acknowledged: [bundleId])

        await reaper.reapAcknowledgedAtLaunch()

        let exists = await recordExists(bundleId)
        XCTAssertTrue(exists, "rehydration owns live uploads (sendPaused-Leave case)")
        XCTAssertEqual(calls.withLock { $0 }, [])
        try? FileManager.default.removeItem(at: dir)
    }

    func test_launchScan_mixedPopulation_onlyTheEligibleFall() async throws {
        let (ackedReady, dirA)   = try await seedRecord(phase: .complete)
        let (ackedStuck, dirB)   = try await seedRecord(phase: .complete)
        let (unacked, dirC)      = try await seedRecord(phase: .complete)
        let (ackedFailed, dirD)  = try await seedRecord(phase: .failed)
        let (reaper, _) = makeReaper(
            acknowledged: [ackedReady, ackedStuck, ackedFailed],
            statusByBundle: [ackedReady: .ready, ackedStuck: .processing]
        )

        await reaper.reapAcknowledgedAtLaunch()

        let readyExists  = await recordExists(ackedReady)
        let stuckExists  = await recordExists(ackedStuck)
        let unackExists  = await recordExists(unacked)
        let failedExists = await recordExists(ackedFailed)
        XCTAssertFalse(readyExists)
        XCTAssertTrue(stuckExists, "processing is not terminal")
        XCTAssertTrue(unackExists)
        XCTAssertFalse(failedExists)
        for dir in [dirB, dirC] { try? FileManager.default.removeItem(at: dir) }
        XCTAssertFalse(FileManager.default.fileExists(atPath: dirA.path))
        XCTAssertFalse(FileManager.default.fileExists(atPath: dirD.path))
    }
}
