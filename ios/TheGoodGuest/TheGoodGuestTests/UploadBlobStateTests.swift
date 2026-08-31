/// Tests for the P4 per-blob upload-state record and Phase-1→Phase-2 gate.
///
/// Covers:
///   - New record initialization (all statuses .pending)
///   - allNonBundlePbBlobsUploaded gate: false while blobs pending, true when all done
///   - Gate excludes bundle.pb from the Phase-1 check
///   - Edge case: no non-bundle.pb blobs → gate returns true immediately
///   - UploadSessionStore.markBlobUploaded: persists status and returns updated record
///   - Reconstruct-on-relaunch: load from disk → gate predicate reflects saved state
///   - Backward-compatible decode: old records (no blobStatuses key) → all .pending
///
/// Decision 0040, item 5.

import XCTest
@testable import TheGoodGuest

@MainActor
final class UploadBlobStateTests: XCTestCase {

    // MARK: - Helpers

    private func makeEntries(_ relativePaths: [String]) -> [UploadSessionEntry] {
        relativePaths.map { UploadSessionEntry(relativePath: $0, sessionUri: "https://example.com/\($0)") }
    }

    private func makeRecord(paths: [String]) -> UploadSessionRecord {
        UploadSessionRecord(
            bundleId: "test-bundle-id",
            tierRawValue: 1,
            clientMintTimestamp: Date(),
            sessionEntries: makeEntries(paths),
            manifestPaths: paths,
            outputDir: FileManager.default.temporaryDirectory
        )
    }

    // MARK: - New record initialization

    func test_newRecord_allBlobStatusesPending() {
        let paths = ["frames/000000.jpg", "frames/000001.jpg", "bundle.pb"]
        let record = makeRecord(paths: paths)

        for path in paths {
            XCTAssertEqual(
                record.blobStatuses[path], .pending,
                "Expected .pending for \(path) on a new record"
            )
        }
    }

    func test_newRecord_blobStatusCountMatchesEntryCount() {
        let paths = ["frames/000000.jpg", "depth/000000.f32", "bundle.pb"]
        let record = makeRecord(paths: paths)
        XCTAssertEqual(record.blobStatuses.count, paths.count)
    }

    // MARK: - allNonBundlePbBlobsUploaded gate

    func test_gate_falseWhenNonBundleBlobsPending() {
        let record = makeRecord(paths: ["frames/000000.jpg", "frames/000001.jpg", "bundle.pb"])
        XCTAssertFalse(record.allNonBundlePbBlobsUploaded,
                       "Gate must be false when frame blobs are still pending")
    }

    func test_gate_trueAfterAllNonBundleBlobsUploaded() {
        let base = makeRecord(paths: ["frames/000000.jpg", "frames/000001.jpg", "bundle.pb"])

        let afterFirst = base.markingBlobUploaded("frames/000000.jpg")
        XCTAssertFalse(afterFirst.allNonBundlePbBlobsUploaded,
                       "Gate must still be false with one frame blob pending")

        let afterBoth = afterFirst.markingBlobUploaded("frames/000001.jpg")
        XCTAssertTrue(afterBoth.allNonBundlePbBlobsUploaded,
                      "Gate must be true once all non-bundle.pb blobs are uploaded")
    }

    func test_gate_ignoresBundlePbStatus() {
        // Gate should be true even when bundle.pb itself is still .pending.
        let base    = makeRecord(paths: ["frames/000000.jpg", "bundle.pb"])
        let updated = base.markingBlobUploaded("frames/000000.jpg")

        // bundle.pb deliberately left as .pending.
        XCTAssertEqual(updated.blobStatuses["bundle.pb"], .pending)
        XCTAssertTrue(updated.allNonBundlePbBlobsUploaded,
                      "Gate must be true regardless of bundle.pb status")
    }

    func test_gate_trueForBundlePbOnlyManifest() {
        // Pathological: manifest has only bundle.pb (no frame blobs).
        // allNonBundlePbBlobsUploaded should return true immediately.
        let record = makeRecord(paths: ["bundle.pb"])
        XCTAssertTrue(record.allNonBundlePbBlobsUploaded,
                      "Gate must be true when there are no non-bundle.pb blobs")
    }

    // MARK: - UploadSessionStore.markBlobUploaded

    func test_markBlobUploaded_persistsStatusAndReturnsUpdatedRecord() async throws {
        let dir = FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString)
        let store = UploadSessionStore(directory: dir)
        defer { try? FileManager.default.removeItem(at: dir) }

        let paths = ["frames/000000.jpg", "frames/000001.jpg", "bundle.pb"]
        let original = makeRecord(paths: paths)
        try await store.save(original)

        // Mark one blob uploaded.
        let updated = try await store.markBlobUploaded(
            bundleId: "test-bundle-id",
            relativePath: "frames/000000.jpg"
        )

        // Returned record reflects the change.
        XCTAssertEqual(updated?.blobStatuses["frames/000000.jpg"], .uploaded)
        XCTAssertEqual(updated?.blobStatuses["frames/000001.jpg"], .pending)
        XCTAssertFalse(updated?.allNonBundlePbBlobsUploaded ?? true,
                       "Gate must be false with one blob still pending")

        // Persisted record also reflects the change (reconstruct-on-relaunch path).
        let reloaded = try await store.load(bundleId: "test-bundle-id")
        XCTAssertEqual(reloaded?.blobStatuses["frames/000000.jpg"], .uploaded,
                       "Persisted record must show the updated status")
    }

    func test_markBlobUploaded_gateFlipsWhenLastNonBundleBlobMarked() async throws {
        let dir = FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString)
        let store = UploadSessionStore(directory: dir)
        defer { try? FileManager.default.removeItem(at: dir) }

        let paths = ["frames/000000.jpg", "frames/000001.jpg", "bundle.pb"]
        try await store.save(makeRecord(paths: paths))

        _ = try await store.markBlobUploaded(bundleId: "test-bundle-id", relativePath: "frames/000000.jpg")
        let afterSecond = try await store.markBlobUploaded(
            bundleId: "test-bundle-id",
            relativePath: "frames/000001.jpg"
        )

        XCTAssertTrue(afterSecond?.allNonBundlePbBlobsUploaded ?? false,
                      "Gate must flip to true after the last non-bundle.pb blob is marked uploaded")
    }

    func test_markBlobUploaded_returnsNilForMissingRecord() async throws {
        let dir = FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString)
        let store = UploadSessionStore(directory: dir)
        defer { try? FileManager.default.removeItem(at: dir) }

        let result = try await store.markBlobUploaded(
            bundleId: "nonexistent-bundle",
            relativePath: "frames/000000.jpg"
        )
        XCTAssertNil(result, "markBlobUploaded must return nil when no record exists")
    }

    // MARK: - Backward-compatible decode (pre-P4 records)

    // MARK: - UploadPhase defaults and round-trip (decision 0045)

    func test_newRecord_uploadPhaseIsUploadingBlobs() {
        let record = makeRecord(paths: ["frames/000000.jpg", "bundle.pb"])
        XCTAssertEqual(record.uploadPhase, .uploadingBlobs,
                       "New record must default to .uploadingBlobs")
        XCTAssertNil(record.failureReason, "New record must have nil failureReason")
    }

    func test_markingPhase_roundTrip() {
        let record = makeRecord(paths: ["frames/000000.jpg", "bundle.pb"])
        let updated = record.markingPhase(.uploadingBundlePb)
        XCTAssertEqual(updated.uploadPhase, .uploadingBundlePb)
        XCTAssertNil(updated.failureReason)

        let completed = updated.markingPhase(.complete)
        XCTAssertEqual(completed.uploadPhase, .complete)
        XCTAssertNil(completed.failureReason)

        // Functional mutations preserve other fields.
        XCTAssertEqual(completed.bundleId, record.bundleId)
        XCTAssertEqual(completed.sessionEntries.count, record.sessionEntries.count)
        XCTAssertEqual(completed.blobStatuses, record.blobStatuses)
    }

    func test_uploadPhase_codableRoundTrip_preservesValue() throws {
        let record = makeRecord(paths: ["frames/000000.jpg", "bundle.pb"])
            .markingPhase(.uploadingBundlePb)

        let encoder = JSONEncoder()
        encoder.dateEncodingStrategy = .iso8601
        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .iso8601

        let data    = try encoder.encode(record)
        let decoded = try decoder.decode(UploadSessionRecord.self, from: data)

        XCTAssertEqual(decoded.uploadPhase, .uploadingBundlePb,
                       "uploadPhase must survive encode/decode round-trip")
        XCTAssertNil(decoded.failureReason, "failureReason must remain nil after round-trip")
    }

    func test_markingPhase_preservesCrossLaunchRetryCount() {
        // Functional mutations via markingPhase must preserve crossLaunchRetryCount.
        let base = makeRecord(paths: ["frames/000000.jpg", "bundle.pb"])
        // Plant a non-zero count via bumpingCrossLaunchRetryCount.
        let bumped = base.bumpingCrossLaunchRetryCount().bumpingCrossLaunchRetryCount()
        XCTAssertEqual(bumped.crossLaunchRetryCount, 2, "Two bumps must yield count == 2")

        let phaseChanged = bumped.markingPhase(.uploadingBundlePb)
        XCTAssertEqual(phaseChanged.crossLaunchRetryCount, 2,
                       "markingPhase must preserve crossLaunchRetryCount")
        XCTAssertEqual(phaseChanged.uploadPhase, .uploadingBundlePb)
    }

    func test_bumpingCrossLaunchRetryCount_incrementsAndPreservesOtherFields() {
        let base   = makeRecord(paths: ["frames/000000.jpg", "bundle.pb"])
        let bumped = base.bumpingCrossLaunchRetryCount()
        XCTAssertEqual(bumped.crossLaunchRetryCount, 1)
        XCTAssertEqual(bumped.bundleId,         base.bundleId)
        XCTAssertEqual(bumped.uploadPhase,      base.uploadPhase)
        XCTAssertEqual(bumped.sessionEntries.count, base.sessionEntries.count)
        XCTAssertEqual(bumped.blobStatuses,     base.blobStatuses)
    }

    func test_markingBlobUploaded_resetsCrossLaunchRetryCount() {
        // markingBlobUploaded must reset crossLaunchRetryCount to 0 (reset on progress).
        var record = makeRecord(paths: ["frames/000000.jpg", "bundle.pb"])
        record = record.bumpingCrossLaunchRetryCount().bumpingCrossLaunchRetryCount()
        XCTAssertEqual(record.crossLaunchRetryCount, 2, "Pre-condition: count must be 2")

        let updated = record.markingBlobUploaded("frames/000000.jpg")
        XCTAssertEqual(updated.crossLaunchRetryCount, 0,
                       "markingBlobUploaded must reset crossLaunchRetryCount to 0")
        XCTAssertEqual(updated.blobStatuses["frames/000000.jpg"], .uploaded)
    }

    func test_crossLaunchRetryCount_codableRoundTrip() throws {
        let base   = makeRecord(paths: ["frames/000000.jpg", "bundle.pb"])
        let bumped = base.bumpingCrossLaunchRetryCount().bumpingCrossLaunchRetryCount()

        let encoder = JSONEncoder()
        encoder.dateEncodingStrategy = .iso8601
        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .iso8601

        let data    = try encoder.encode(bumped)
        let decoded = try decoder.decode(UploadSessionRecord.self, from: data)

        XCTAssertEqual(decoded.crossLaunchRetryCount, 2,
                       "crossLaunchRetryCount must survive encode/decode round-trip")
    }

    // MARK: - Strict decode (no migration shims)

    func test_decode_missingRequiredKey_throws() throws {
        // The decode path is strict (synthesized Codable, no migration shims):
        // a record missing a required key must throw, never silently default.
        // No legacy on-disk records exist — the shims were removed pre-launch.
        let jsonMissingBlobStatuses = """
        {
            "bundleId": "some-bundle",
            "tierRawValue": 1,
            "clientMintTimestamp": "2026-05-31T00:00:00Z",
            "sessionEntries": [
                {"relative_path": "frames/000000.jpg", "session_uri": "https://example.com/f0"}
            ],
            "manifestPaths": ["frames/000000.jpg"]
        }
        """
        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .iso8601
        XCTAssertThrowsError(
            try decoder.decode(UploadSessionRecord.self, from: Data(jsonMissingBlobStatuses.utf8)),
            "Strict decode must throw on a record missing required keys"
        )
    }

    // MARK: - UploadSessionStore.allBundleIds (decision 0045)

    func test_allBundleIds_returnsAllSavedBundleIds() async throws {
        let storeDir = FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString)
        let store = UploadSessionStore(directory: storeDir)
        addTeardownBlock { try? FileManager.default.removeItem(at: storeDir) }

        let id1 = "00000000-0000-0000-0000-000000000001"
        let id2 = "00000000-0000-0000-0000-000000000002"
        try await store.save(UploadSessionRecord(bundleId: id1, tierRawValue: 1,
                                                 clientMintTimestamp: Date(),
                                                 sessionEntries: [], manifestPaths: [],
                                                 outputDir: FileManager.default.temporaryDirectory))
        try await store.save(UploadSessionRecord(bundleId: id2, tierRawValue: 1,
                                                 clientMintTimestamp: Date(),
                                                 sessionEntries: [], manifestPaths: [],
                                                 outputDir: FileManager.default.temporaryDirectory))

        let ids = try await store.allBundleIds()
        XCTAssertEqual(Set(ids), Set([id1, id2]), "allBundleIds must return all saved bundle IDs")
    }

    func test_allBundleIds_emptyDir_returnsEmpty() async throws {
        let storeDir = FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString)
        let store = UploadSessionStore(directory: storeDir)
        addTeardownBlock { try? FileManager.default.removeItem(at: storeDir) }

        let ids = try await store.allBundleIds()
        XCTAssertTrue(ids.isEmpty, "allBundleIds on an empty store must return []")
    }

    func test_allBundleIds_ignoresNonUUIDFilenames() async throws {
        let storeDir = FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString)
        let store = UploadSessionStore(directory: storeDir)
        addTeardownBlock { try? FileManager.default.removeItem(at: storeDir) }

        let validId = "00000000-0000-0000-0000-000000000001"
        try await store.save(UploadSessionRecord(bundleId: validId, tierRawValue: 1,
                                                 clientMintTimestamp: Date(),
                                                 sessionEntries: [], manifestPaths: [],
                                                 outputDir: FileManager.default.temporaryDirectory))
        // Write a non-UUID JSON file directly.
        try Data("{}".utf8).write(to: storeDir.appendingPathComponent("not-a-uuid.json"))

        let ids = try await store.allBundleIds()
        XCTAssertEqual(ids, [validId], "allBundleIds must skip non-UUID filenames")
    }

    func test_allBundleIds_ignoresNonJSONFiles() async throws {
        let storeDir = FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString)
        let store = UploadSessionStore(directory: storeDir)
        addTeardownBlock { try? FileManager.default.removeItem(at: storeDir) }

        let validId = "00000000-0000-0000-0000-000000000001"
        try await store.save(UploadSessionRecord(bundleId: validId, tierRawValue: 1,
                                                 clientMintTimestamp: Date(),
                                                 sessionEntries: [], manifestPaths: [],
                                                 outputDir: FileManager.default.temporaryDirectory))
        // Write a UUID-named non-.json file directly.
        try Data([0x00]).write(
            to: storeDir.appendingPathComponent("00000000-0000-0000-0000-000000000002.pb")
        )

        let ids = try await store.allBundleIds()
        XCTAssertEqual(ids, [validId], "allBundleIds must skip non-.json files")
    }
}
