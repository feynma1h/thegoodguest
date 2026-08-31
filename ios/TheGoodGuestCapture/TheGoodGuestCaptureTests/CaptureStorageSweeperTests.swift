/// Tests for CaptureStorageSweeper startup cleanup (decision 0043).
///
/// Sweep predicate: delete a session dir when
///   (a) its name is a valid UUID, AND
///   (b) it is older than minAgeBeforeDelete (300 s), AND
///   (c) no UploadSessionRecord exists for that bundle ID.
///
/// In-flight dirs (record exists) must never be deleted.
/// Non-UUID dirs must be left alone.
/// Missing captures root is a no-op.

import XCTest
@testable import TheGoodGuestCapture

@MainActor
final class CaptureStorageSweeperTests: XCTestCase {

    // MARK: - Helpers

    private var capturesRoot: URL!
    private var storeDir: URL!
    private var store: UploadSessionStore!
    private var sweeper: CaptureStorageSweeper!

    override func setUp() async throws {
        capturesRoot = FileManager.default.temporaryDirectory
            .appendingPathComponent("sweeper-test-captures-\(UUID().uuidString)")
        storeDir = FileManager.default.temporaryDirectory
            .appendingPathComponent("sweeper-test-store-\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: capturesRoot, withIntermediateDirectories: true)
        store   = UploadSessionStore(directory: storeDir)
        sweeper = CaptureStorageSweeper(capturesRoot: capturesRoot, store: store)
    }

    override func tearDown() async throws {
        try? FileManager.default.removeItem(at: capturesRoot)
        try? FileManager.default.removeItem(at: storeDir)
    }

    /// Create a session dir with a known modification date age.
    /// Pass `ageSeconds` > 300 to produce a dir that passes the age threshold.
    @discardableResult
    private func makeSessionDir(
        bundleId: String = UUID().uuidString.lowercased(),
        ageSeconds: TimeInterval = 400      // older than minAgeBeforeDelete
    ) throws -> URL {
        let dir = capturesRoot.appendingPathComponent(bundleId)
        try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        // Back-date the modification date so the age threshold fires.
        if ageSeconds > 0 {
            let past = Date().addingTimeInterval(-ageSeconds)
            try FileManager.default.setAttributes(
                [.modificationDate: past],
                ofItemAtPath: dir.path
            )
        }
        return dir
    }

    /// Save a minimal UploadSessionRecord with pending blobs.
    private func saveRecord(bundleId: String, paths: [String] = ["frames/000000.jpg", "bundle.pb"]) async throws {
        let entries = paths.map { UploadSessionEntry(relativePath: $0, sessionUri: "https://example.com/\($0)") }
        let record = UploadSessionRecord(
            bundleId:            bundleId,
            tierRawValue:        1,
            clientMintTimestamp: Date(),
            sessionEntries:      entries,
            manifestPaths:       paths,
            outputDir:           FileManager.default.temporaryDirectory
        )
        try await store.save(record)
    }

    // MARK: - Orphaned dir (no record) → deleted

    func test_sweep_deletesOrphanedDir_noRecord() async throws {
        let bundleId = UUID().uuidString.lowercased()
        let dir = try makeSessionDir(bundleId: bundleId)
        XCTAssertTrue(FileManager.default.fileExists(atPath: dir.path))

        await sweeper.sweep()

        XCTAssertFalse(
            FileManager.default.fileExists(atPath: dir.path),
            "Orphaned session dir (no store record) must be deleted by sweep"
        )
    }

    func test_sweep_deletesMultipleOrphanedDirs() async throws {
        let id1 = UUID().uuidString.lowercased()
        let id2 = UUID().uuidString.lowercased()
        let dir1 = try makeSessionDir(bundleId: id1)
        let dir2 = try makeSessionDir(bundleId: id2)

        await sweeper.sweep()

        XCTAssertFalse(FileManager.default.fileExists(atPath: dir1.path),
                       "First orphaned dir must be deleted")
        XCTAssertFalse(FileManager.default.fileExists(atPath: dir2.path),
                       "Second orphaned dir must be deleted")
    }

    // MARK: - In-flight dir (record exists) → spared

    func test_sweep_sparesInFlightDir_recordExists() async throws {
        let bundleId = UUID().uuidString.lowercased()
        let dir = try makeSessionDir(bundleId: bundleId)
        try await saveRecord(bundleId: bundleId)

        await sweeper.sweep()

        XCTAssertTrue(
            FileManager.default.fileExists(atPath: dir.path),
            "In-flight session dir (record has pending blobs) must NOT be deleted by sweep"
        )
    }

    // MARK: - Completed dir whose record was deleted by onBundleComplete → deleted

    func test_sweep_deletesCompletedDir_afterRecordDeletion() async throws {
        let bundleId = UUID().uuidString.lowercased()
        let dir = try makeSessionDir(bundleId: bundleId)
        // Save then delete record (simulating onBundleComplete deleting the record
        // but failing to delete the dir before process was killed).
        try await saveRecord(bundleId: bundleId)
        try await store.delete(bundleId: bundleId)

        await sweeper.sweep()

        XCTAssertFalse(
            FileManager.default.fileExists(atPath: dir.path),
            "Session dir whose record was deleted by onBundleComplete must be cleaned by sweep"
        )
    }

    // MARK: - Mixed: in-flight spared, orphaned deleted

    func test_sweep_mixedDirs_sparesInFlightDeletesOrphaned() async throws {
        let inFlightId = UUID().uuidString.lowercased()
        let orphanId   = UUID().uuidString.lowercased()
        let inFlightDir = try makeSessionDir(bundleId: inFlightId)
        let orphanDir   = try makeSessionDir(bundleId: orphanId)
        try await saveRecord(bundleId: inFlightId)  // only in-flight has a record

        await sweeper.sweep()

        XCTAssertTrue(FileManager.default.fileExists(atPath: inFlightDir.path),
                      "In-flight dir must survive sweep")
        XCTAssertFalse(FileManager.default.fileExists(atPath: orphanDir.path),
                       "Orphaned dir must be deleted by sweep")
    }

    // MARK: - Non-UUID dirs → left alone

    func test_sweep_ignoresNonUUIDDir() async throws {
        let nonUUIDDir = capturesRoot.appendingPathComponent("not-a-uuid")
        try FileManager.default.createDirectory(at: nonUUIDDir, withIntermediateDirectories: true)

        await sweeper.sweep()

        XCTAssertTrue(
            FileManager.default.fileExists(atPath: nonUUIDDir.path),
            "Non-UUID directory must not be touched by sweep"
        )
    }

    // MARK: - Age threshold: too-recent dir → skipped even without record

    func test_sweep_sparesFreshDir_noRecord_tooRecent() async throws {
        let bundleId = UUID().uuidString.lowercased()
        // Age = 0 → modification date = now → well under the 300 s threshold.
        let dir = try makeSessionDir(bundleId: bundleId, ageSeconds: 0)
        // No record — but it's too fresh to delete (race guard).

        await sweeper.sweep()

        XCTAssertTrue(
            FileManager.default.fileExists(atPath: dir.path),
            "Fresh dir (< minAgeBeforeDelete) must be spared even without a record (race guard)"
        )
    }

    // MARK: - Missing captures root → no-op

    func test_sweep_missingCapturesRoot_isNoop() async throws {
        // Remove the captures root entirely.
        try FileManager.default.removeItem(at: capturesRoot)
        // Sweep must not throw or crash.
        await sweeper.sweep()
        // Nothing to assert — just verifying no crash.
    }

    // MARK: - Empty captures root → no-op

    func test_sweep_emptyCapturesRoot_isNoop() async throws {
        // The captures root is empty (no session dirs).
        await sweeper.sweep()
        let contents = try FileManager.default.contentsOfDirectory(atPath: capturesRoot.path)
        XCTAssertTrue(contents.isEmpty, "Empty captures root must remain empty after sweep")
    }

    // MARK: - Dead-record sweep (decision 0074, cosmetic sibling)

    /// Write a record FILE that fails the strict decode (a pre-P5 shape: valid JSON,
    /// no `uploadPhase`), naming `outputDir` if given. Mirrors the June-era records
    /// an iCloud backup migrated dirless to the 16 Pro.
    private func writeLegacyRecord(bundleId: String, outputDir: URL? = nil) throws -> URL {
        var json: [String: Any] = [
            "bundleId":            bundleId,
            "tierRawValue":        1,
            "clientMintTimestamp": "2026-06-01T00:00:00Z",
            "sessionEntries":      [["relativePath": "bundle.pb", "sessionUri": "https://example.com/s"]],
            "manifestPaths":       ["bundle.pb"],
            "blobStatuses":        ["bundle.pb": "pending"],
            // uploadPhase deliberately absent — this is what breaks the strict decode.
        ]
        if let outputDir { json["outputDir"] = outputDir.absoluteString }
        let url = storeDir.appendingPathComponent("\(bundleId).json")
        try JSONSerialization.data(withJSONObject: json).write(to: url)
        return url
    }

    func test_recordSweep_reclaimsUndecodableRecord_noCaptureDir() async throws {
        let bundleId = UUID().uuidString.lowercased()
        let file = try writeLegacyRecord(bundleId: bundleId)
        // Sanity: the strict decode really does fail (otherwise this test pins nothing).
        await XCTAssertThrowsErrorAsync(try await store.load(bundleId: bundleId))

        await sweeper.sweep()

        XCTAssertFalse(FileManager.default.fileExists(atPath: file.path),
                       "Undecodable record with no surviving capture dir must be reclaimed")
    }

    func test_recordSweep_keepsUndecodableRecord_conventionalDirPresent() async throws {
        let bundleId = UUID().uuidString.lowercased()
        // Fresh dir (age 0): phase 1's race guard spares it, so within this sweep the
        // dir survives and the record must too.
        try makeSessionDir(bundleId: bundleId, ageSeconds: 0)
        let file = try writeLegacyRecord(bundleId: bundleId)

        await sweeper.sweep()

        XCTAssertTrue(FileManager.default.fileExists(atPath: file.path),
                      "An undecodable record whose capture dir still exists must be kept")
    }

    func test_recordSweep_keepsUndecodableRecord_recordedOutputDirPresent() async throws {
        let bundleId = UUID().uuidString.lowercased()
        // A NON-conventional outputDir (e.g. a pre-0043 location) that still exists.
        let elsewhere = FileManager.default.temporaryDirectory
            .appendingPathComponent("sweeper-test-elsewhere-\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: elsewhere, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: elsewhere) }
        let file = try writeLegacyRecord(bundleId: bundleId, outputDir: elsewhere)

        await sweeper.sweep()

        XCTAssertTrue(FileManager.default.fileExists(atPath: file.path),
                      "The outputDir the record names still exists — the record must be kept")
    }

    func test_recordSweep_reclaimsNonJSONGarbage_noCaptureDir() async throws {
        let bundleId = UUID().uuidString.lowercased()
        let file = storeDir.appendingPathComponent("\(bundleId).json")
        try Data("not json at all".utf8).write(to: file)

        await sweeper.sweep()

        XCTAssertFalse(FileManager.default.fileExists(atPath: file.path),
                       "Unparseable record with no capture dir anywhere must be reclaimed")
    }

    func test_recordSweep_neverTouchesDecodableRecords() async throws {
        let bundleId = UUID().uuidString.lowercased()
        // A valid record whose capture dir is long gone — still live machinery
        // (e.g. a .complete record awaiting acknowledgment); only DECODE death
        // qualifies for the record sweep.
        try await saveRecord(bundleId: bundleId)

        await sweeper.sweep()

        let loaded = try await store.load(bundleId: bundleId)
        XCTAssertNotNil(loaded, "A decodable record must never be reclaimed, dir or no dir")
    }

    /// The 0074 migration shape end to end: dirless legacy records are reclaimed in
    /// one pass while a decodable in-flight record and its dir survive.
    func test_recordSweep_migratedStoreShape() async throws {
        let legacy1 = UUID().uuidString.lowercased()
        let legacy2 = UUID().uuidString.lowercased()
        let liveId  = UUID().uuidString.lowercased()
        let f1 = try writeLegacyRecord(bundleId: legacy1)
        let f2 = try writeLegacyRecord(bundleId: legacy2)
        let liveDir = try makeSessionDir(bundleId: liveId)
        try await saveRecord(bundleId: liveId)

        await sweeper.sweep()

        XCTAssertFalse(FileManager.default.fileExists(atPath: f1.path))
        XCTAssertFalse(FileManager.default.fileExists(atPath: f2.path))
        let liveRecord = try await store.load(bundleId: liveId)
        XCTAssertNotNil(liveRecord)
        XCTAssertTrue(FileManager.default.fileExists(atPath: liveDir.path))
    }
}

/// XCTAssertThrowsError has no async overload; minimal shim.
private func XCTAssertThrowsErrorAsync<T>(
    _ expression: @autoclosure () async throws -> T,
    file: StaticString = #filePath,
    line: UInt = #line
) async {
    do {
        _ = try await expression()
        XCTFail("Expected the expression to throw", file: file, line: line)
    } catch { }
}
