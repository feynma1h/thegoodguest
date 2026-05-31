/// Tests for BlobUploadManager: task-description encoding, status-code routing,
/// gate evaluation, and concurrency safety.
///
/// Strategy: call BlobUploadManager.handleTaskCompletion directly (bypassing URLSession
/// entirely) and verify effects via UploadSessionStore. This tests the full completion
/// pipeline — including store writes and gate predicate evaluation — without any network.
///
/// Race-safety test: two blobs completing via concurrent Tasks must both reach
/// the store serialized by its actor, so exactly one completion sees the gate flip.
/// Verified by checking store state after both Tasks complete.
///
/// Decision 0040.

import XCTest
@testable import RoomStudioCapture

@MainActor
final class BlobUploadManagerTests: XCTestCase {

    // MARK: - Helpers

    private func makeSessionEntries(_ paths: [String]) -> [UploadSessionEntry] {
        paths.map { UploadSessionEntry(relativePath: $0, sessionUri: "https://gcs.example.com/\($0)") }
    }

    /// Set up a manager + store wired to a temp directory, with a record for `bundleId`
    /// pre-saved in the store. Returns (manager, store, tmpDir) ready for tests.
    private func makeManager(
        bundleId: String = "test-bundle",
        paths: [String]
    ) async throws -> (BlobUploadManager, UploadSessionStore) {
        let dir = FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString)
        let store = UploadSessionStore(directory: dir)
        addTeardownBlock { try? FileManager.default.removeItem(at: dir) }

        let entries = makeSessionEntries(paths)
        let record  = UploadSessionRecord(
            bundleId:            bundleId,
            tierRawValue:        1,
            clientMintTimestamp: Date(),
            sessionEntries:      entries,
            manifestPaths:       paths
        )
        try await store.save(record)

        let manager = BlobUploadManager(store: store)
        return (manager, store)
    }

    private func taskDesc(bundleId: String = "test-bundle", relativePath: String) -> String {
        BlobUploadManager.makeTaskDescription(bundleId: bundleId, relativePath: relativePath)
    }

    // MARK: - Task description encoding

    func test_makeTaskDescription_separatedByPipe() {
        let desc = BlobUploadManager.makeTaskDescription(bundleId: "abc-123", relativePath: "frames/0.jpg")
        XCTAssertEqual(desc, "abc-123|frames/0.jpg")
    }

    func test_parseTaskDescription_roundTrip() {
        let desc   = BlobUploadManager.makeTaskDescription(bundleId: "abc-123", relativePath: "frames/0.jpg")
        let parsed = BlobUploadManager.parseTaskDescription(desc)
        XCTAssertEqual(parsed?.bundleId,     "abc-123")
        XCTAssertEqual(parsed?.relativePath, "frames/0.jpg")
    }

    func test_parseTaskDescription_relativePathWithSubdir_preservesSlash() {
        // Relative paths contain `/`; maxSplits:1 ensures only the first `|` is used.
        let desc   = BlobUploadManager.makeTaskDescription(bundleId: "b", relativePath: "depth/000001.f32")
        let parsed = BlobUploadManager.parseTaskDescription(desc)
        XCTAssertEqual(parsed?.relativePath, "depth/000001.f32")
    }

    func test_parseTaskDescription_noPipe_returnsNil() {
        XCTAssertNil(BlobUploadManager.parseTaskDescription("nopipe"))
    }

    func test_parseTaskDescription_emptyString_returnsNil() {
        XCTAssertNil(BlobUploadManager.parseTaskDescription(""))
    }

    func test_parseTaskDescription_pipeOnly_returnsNil() {
        XCTAssertNil(BlobUploadManager.parseTaskDescription("|"))
    }

    func test_parseTaskDescription_emptyBundleId_returnsNil() {
        XCTAssertNil(BlobUploadManager.parseTaskDescription("|frames/0.jpg"))
    }

    func test_parseTaskDescription_emptyRelativePath_returnsNil() {
        XCTAssertNil(BlobUploadManager.parseTaskDescription("bundle-id|"))
    }

    // MARK: - 200 / 201 → markBlobUploaded

    func test_handleTaskCompletion_200_marksBlobUploaded() async throws {
        let (manager, store) = try await makeManager(paths: ["frames/000000.jpg", "bundle.pb"])
        await manager.handleTaskCompletion(
            taskDescription: taskDesc(relativePath: "frames/000000.jpg"),
            statusCode: 200, error: nil
        )
        let record = try await store.load(bundleId: "test-bundle")
        XCTAssertEqual(record?.blobStatuses["frames/000000.jpg"], .uploaded,
                       "200 must mark the blob as uploaded")
        XCTAssertEqual(record?.blobStatuses["bundle.pb"], .pending,
                       "bundle.pb must remain pending")
    }

    func test_handleTaskCompletion_201_marksBlobUploaded() async throws {
        let (manager, store) = try await makeManager(paths: ["frames/000000.jpg", "bundle.pb"])
        await manager.handleTaskCompletion(
            taskDescription: taskDesc(relativePath: "frames/000000.jpg"),
            statusCode: 201, error: nil
        )
        let record = try await store.load(bundleId: "test-bundle")
        XCTAssertEqual(record?.blobStatuses["frames/000000.jpg"], .uploaded,
                       "201 must be treated identically to 200")
    }

    // MARK: - Gate evaluation

    func test_handleTaskCompletion_gateNotFiredUntilLastBlob() async throws {
        let paths = ["frames/000000.jpg", "frames/000001.jpg", "bundle.pb"]
        let (manager, store) = try await makeManager(paths: paths)

        await manager.handleTaskCompletion(
            taskDescription: taskDesc(relativePath: "frames/000000.jpg"),
            statusCode: 200, error: nil
        )
        let afterFirst = try await store.load(bundleId: "test-bundle")
        XCTAssertFalse(afterFirst?.allNonBundlePbBlobsUploaded ?? true,
                       "Gate must be false with one frame blob still pending")
    }

    func test_handleTaskCompletion_gateFlipsAfterLastNonBundleBlob() async throws {
        let paths = ["frames/000000.jpg", "frames/000001.jpg", "bundle.pb"]
        let (manager, store) = try await makeManager(paths: paths)

        await manager.handleTaskCompletion(
            taskDescription: taskDesc(relativePath: "frames/000000.jpg"),
            statusCode: 200, error: nil
        )
        await manager.handleTaskCompletion(
            taskDescription: taskDesc(relativePath: "frames/000001.jpg"),
            statusCode: 200, error: nil
        )
        let record = try await store.load(bundleId: "test-bundle")
        XCTAssertTrue(record?.allNonBundlePbBlobsUploaded ?? false,
                      "Gate must flip to true after both non-bundle.pb blobs are uploaded")
    }

    func test_handleTaskCompletion_bundlePbCompletionDoesNotBlock_gate() async throws {
        // Completing bundle.pb before frame blobs must NOT set gate to true.
        // (bundle.pb is excluded from the Phase-1 gate check.)
        let paths = ["frames/000000.jpg", "bundle.pb"]
        let (manager, store) = try await makeManager(paths: paths)

        await manager.handleTaskCompletion(
            taskDescription: taskDesc(relativePath: "bundle.pb"),
            statusCode: 200, error: nil
        )
        let record = try await store.load(bundleId: "test-bundle")
        XCTAssertFalse(record?.allNonBundlePbBlobsUploaded ?? true,
                       "Uploading bundle.pb alone must not satisfy the Phase-1 gate")
    }

    // MARK: - Race safety: concurrent completions

    func test_handleTaskCompletion_concurrentCompletions_bothBlobsMarked() async throws {
        // Two blobs completing concurrently. Both must be marked uploaded and the
        // store must reflect both writes — no interleaving or lost update.
        let paths = ["frames/000000.jpg", "frames/000001.jpg", "bundle.pb"]
        let (manager, store) = try await makeManager(paths: paths)

        await withTaskGroup(of: Void.self) { group in
            group.addTask {
                await manager.handleTaskCompletion(
                    taskDescription: self.taskDesc(relativePath: "frames/000000.jpg"),
                    statusCode: 200, error: nil
                )
            }
            group.addTask {
                await manager.handleTaskCompletion(
                    taskDescription: self.taskDesc(relativePath: "frames/000001.jpg"),
                    statusCode: 200, error: nil
                )
            }
        }

        let record = try await store.load(bundleId: "test-bundle")
        XCTAssertEqual(record?.blobStatuses["frames/000000.jpg"], .uploaded,
                       "frames/000000.jpg must be marked uploaded after concurrent completions")
        XCTAssertEqual(record?.blobStatuses["frames/000001.jpg"], .uploaded,
                       "frames/000001.jpg must be marked uploaded after concurrent completions")
        XCTAssertTrue(record?.allNonBundlePbBlobsUploaded ?? false,
                      "Gate must be true when both blobs are uploaded after concurrent completions")
    }

    // MARK: - 410 → store unchanged

    func test_handleTaskCompletion_410_doesNotUpdateStore() async throws {
        let (manager, store) = try await makeManager(paths: ["frames/000000.jpg", "bundle.pb"])
        let before = try await store.load(bundleId: "test-bundle")

        await manager.handleTaskCompletion(
            taskDescription: taskDesc(relativePath: "frames/000000.jpg"),
            statusCode: 410, error: nil
        )

        let after = try await store.load(bundleId: "test-bundle")
        XCTAssertEqual(after?.blobStatuses["frames/000000.jpg"], .pending,
                       "410 (session expired) must not mark blob as uploaded")
        XCTAssertEqual(after?.clientMintTimestamp, before?.clientMintTimestamp,
                       "Store record must be unchanged after 410")
    }

    // MARK: - 4xx → store unchanged

    func test_handleTaskCompletion_400_doesNotUpdateStore() async throws {
        let (manager, store) = try await makeManager(paths: ["frames/000000.jpg", "bundle.pb"])

        await manager.handleTaskCompletion(
            taskDescription: taskDesc(relativePath: "frames/000000.jpg"),
            statusCode: 400, error: nil
        )

        let record = try await store.load(bundleId: "test-bundle")
        XCTAssertEqual(record?.blobStatuses["frames/000000.jpg"], .pending,
                       "400 client error must not mark blob as uploaded")
    }

    func test_handleTaskCompletion_403_doesNotUpdateStore() async throws {
        let (manager, store) = try await makeManager(paths: ["frames/000000.jpg", "bundle.pb"])

        await manager.handleTaskCompletion(
            taskDescription: taskDesc(relativePath: "frames/000000.jpg"),
            statusCode: 403, error: nil
        )

        let record = try await store.load(bundleId: "test-bundle")
        XCTAssertEqual(record?.blobStatuses["frames/000000.jpg"], .pending,
                       "403 must not mark blob as uploaded")
    }

    // MARK: - Malformed / nil taskDescription → safe no-op

    func test_handleTaskCompletion_nilDescription_noOp() async throws {
        let (manager, store) = try await makeManager(paths: ["frames/000000.jpg", "bundle.pb"])

        await manager.handleTaskCompletion(taskDescription: nil, statusCode: 200, error: nil)

        let record = try await store.load(bundleId: "test-bundle")
        XCTAssertEqual(record?.blobStatuses["frames/000000.jpg"], .pending,
                       "nil taskDescription must be a safe no-op")
    }

    func test_handleTaskCompletion_malformedDescription_noOp() async throws {
        let (manager, store) = try await makeManager(paths: ["frames/000000.jpg", "bundle.pb"])

        await manager.handleTaskCompletion(taskDescription: "no-pipe-here", statusCode: 200, error: nil)

        let record = try await store.load(bundleId: "test-bundle")
        XCTAssertEqual(record?.blobStatuses["frames/000000.jpg"], .pending,
                       "Malformed taskDescription must be a safe no-op")
    }

    // MARK: - network error → store unchanged (5xx / error path)

    func test_handleTaskCompletion_networkError_doesNotUpdateStore() async throws {
        let (manager, store) = try await makeManager(paths: ["frames/000000.jpg", "bundle.pb"])
        let fakeError = NSError(domain: NSURLErrorDomain, code: NSURLErrorTimedOut, userInfo: nil)

        // 5xx/network errors trigger retry logic (needs context), then fatal if no context.
        // In either case the blob must remain .pending.
        await manager.handleTaskCompletion(
            taskDescription: taskDesc(relativePath: "frames/000000.jpg"),
            statusCode: nil, error: fakeError
        )

        let record = try await store.load(bundleId: "test-bundle")
        XCTAssertEqual(record?.blobStatuses["frames/000000.jpg"], .pending,
                       "Network error must not mark blob as uploaded")
    }

    // MARK: - onAllBlobsUploaded: staleness guard

    func test_onAllBlobsUploaded_staleRecord_callsSessionExpired() async throws {
        // A record whose mint timestamp is >12 h old must be routed to onSessionExpired
        // rather than enqueuing bundle.pb. Early blobs may have been GC'd by the age=1
        // lifecycle rule; finalizing against absent blobs wastes a reconstruction attempt.
        let staleTimestamp = Date().addingTimeInterval(-(13 * 3600))
        let entries = makeSessionEntries(["bundle.pb"])
        let staleRecord = UploadSessionRecord(
            bundleId: "test-bundle",
            tierRawValue: 1,
            clientMintTimestamp: staleTimestamp,
            sessionEntries: entries,
            manifestPaths: ["bundle.pb"]
        )
        let (manager, _) = try await makeManager(paths: ["bundle.pb"])
        // outputDir need not contain a real file — staleness guard returns before using it.
        let outputDir = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        addTeardownBlock { try? FileManager.default.removeItem(at: outputDir) }

        await manager.onAllBlobsUploaded(bundleId: "test-bundle", record: staleRecord, outputDir: outputDir)

        let expired = await manager._sessionExpiredInvocations
        XCTAssertEqual(expired, ["test-bundle"], "Stale record must call onSessionExpired")
        let completed = await manager._bundleCompleteInvocations
        XCTAssertTrue(completed.isEmpty, "Stale record must not call onBundleComplete")
    }

    func test_onAllBlobsUploaded_freshRecord_doesNotCallSessionExpired() async throws {
        // A fresh record must pass the staleness guard and proceed to enqueue bundle.pb.
        let entries = makeSessionEntries(["bundle.pb"])
        let freshRecord = UploadSessionRecord(
            bundleId: "test-bundle",
            tierRawValue: 1,
            clientMintTimestamp: Date(),
            sessionEntries: entries,
            manifestPaths: ["bundle.pb"]
        )
        let storeDir = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        let store = UploadSessionStore(directory: storeDir)
        addTeardownBlock { try? FileManager.default.removeItem(at: storeDir) }

        let outputDir = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: outputDir, withIntermediateDirectories: true)
        addTeardownBlock { try? FileManager.default.removeItem(at: outputDir) }
        // Write a non-empty bundle.pb so the size guard passes.
        try Data([0x00, 0x01]).write(to: outputDir.appendingPathComponent("bundle.pb"))

        let manager = BlobUploadManager(store: store)
        await manager.onAllBlobsUploaded(bundleId: "test-bundle", record: freshRecord, outputDir: outputDir)

        let expired = await manager._sessionExpiredInvocations
        XCTAssertTrue(expired.isEmpty, "Fresh record must not call onSessionExpired")
    }

    // MARK: - bundle.pb completion routing

    func test_handleTaskCompletion_bundlePb_200_callsBundleComplete() async throws {
        // bundle.pb 200 must route to onBundleComplete (Phase-2 terminal), not the
        // Phase-1 gate. The gate (allNonBundlePbBlobsUploaded) excludes bundle.pb, so
        // routing it through the gate would cause onAllBlobsUploaded to fire again.
        let (manager, _) = try await makeManager(paths: ["frames/000000.jpg", "bundle.pb"])
        await manager.handleTaskCompletion(
            taskDescription: taskDesc(relativePath: "bundle.pb"),
            statusCode: 200, error: nil
        )
        let completed = await manager._bundleCompleteInvocations
        XCTAssertEqual(completed, ["test-bundle"], "bundle.pb 200 must route to onBundleComplete")
    }

    func test_handleTaskCompletion_bundlePb_200_doesNotUpdateStore() async throws {
        // bundle.pb 200 bypasses markBlobUploaded — the store record is not touched.
        let (manager, store) = try await makeManager(paths: ["frames/000000.jpg", "bundle.pb"])
        await manager.handleTaskCompletion(
            taskDescription: taskDesc(relativePath: "bundle.pb"),
            statusCode: 200, error: nil
        )
        let record = try await store.load(bundleId: "test-bundle")
        XCTAssertEqual(record?.blobStatuses["bundle.pb"], .pending,
                       "bundle.pb 200 must not update blobStatuses in the store")
    }

    func test_handleTaskCompletion_bundlePb_200_doesNotRefireGate() async throws {
        // If bundle.pb 200 were routed through the gate, allNonBundlePbBlobsUploaded
        // would still be true (gate excludes bundle.pb), causing onAllBlobsUploaded
        // to fire again. Verify onBundleComplete fires exactly once, not twice.
        let (manager, _) = try await makeManager(paths: ["frames/000000.jpg", "bundle.pb"])
        await manager.handleTaskCompletion(
            taskDescription: taskDesc(relativePath: "bundle.pb"),
            statusCode: 200, error: nil
        )
        let completed = await manager._bundleCompleteInvocations
        XCTAssertEqual(completed.count, 1, "onBundleComplete must fire exactly once for bundle.pb 200")
    }

    // MARK: - Phase-1 excludes bundle.pb (integration)

    func test_enqueuePhasOneBlobs_excludesBundlePb_bundlePbFinalizedAfterGate() async throws {
        // Verify the bundle.pb ordering invariant end-to-end:
        //   Phase-1 enqueues only frame blobs (bundle.pb excluded by the `where` filter).
        //   Gate fires after the last frame blob succeeds.
        //   onAllBlobsUploaded enqueues bundle.pb.
        //   bundle.pb 200 routes to onBundleComplete.
        // If bundle.pb were included in Phase-1, onAllBlobsUploaded would re-enqueue it
        // after the gate fires — violating the 0040 ordering guarantee.
        let outputDir = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        let framesDir = outputDir.appendingPathComponent("frames")
        try FileManager.default.createDirectory(at: framesDir, withIntermediateDirectories: true)
        addTeardownBlock { try? FileManager.default.removeItem(at: outputDir) }

        try Data(repeating: 0xFF, count: 100).write(to: framesDir.appendingPathComponent("000000.jpg"))
        try Data(repeating: 0xAB, count: 50).write(to: outputDir.appendingPathComponent("bundle.pb"))

        let storeDir = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        let store = UploadSessionStore(directory: storeDir)
        addTeardownBlock { try? FileManager.default.removeItem(at: storeDir) }

        let paths = ["frames/000000.jpg", "bundle.pb"]
        let entries = makeSessionEntries(paths)
        let record = UploadSessionRecord(
            bundleId: "test-bundle",
            tierRawValue: 1,
            clientMintTimestamp: Date(),
            sessionEntries: entries,
            manifestPaths: paths
        )
        try await store.save(record)
        let manager = BlobUploadManager(store: store)

        // Phase-1: only frames/000000.jpg is enqueued (bundle.pb is excluded).
        try await manager.enqueuePhasOneBlobs(record: record, outputDir: outputDir)

        // Simulate frame blob 200 → gate flips → onAllBlobsUploaded fires → enqueues bundle.pb.
        await manager.handleTaskCompletion(
            taskDescription: BlobUploadManager.makeTaskDescription(
                bundleId: "test-bundle", relativePath: "frames/000000.jpg"),
            statusCode: 200, error: nil
        )

        // Simulate bundle.pb 200 (delivered by the background session after onAllBlobsUploaded
        // enqueues it) → onBundleComplete.
        await manager.handleTaskCompletion(
            taskDescription: BlobUploadManager.makeTaskDescription(
                bundleId: "test-bundle", relativePath: "bundle.pb"),
            statusCode: 200, error: nil
        )

        let completed = await manager._bundleCompleteInvocations
        XCTAssertEqual(completed, ["test-bundle"],
                       "bundle.pb must be finalized by onAllBlobsUploaded after the gate, not Phase-1")
        let expired = await manager._sessionExpiredInvocations
        XCTAssertTrue(expired.isEmpty, "No session expiry in the happy path")
    }
}
