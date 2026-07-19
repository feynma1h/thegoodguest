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
@testable import RoomStudioCapture

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
}
