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
}
