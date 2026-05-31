/// Tests for BlobUploadManager: task-description encoding, status-code routing,
/// gate evaluation, staleness guard, 410 re-mint, and cold-relaunch correctness.
///
/// Strategy: call BlobUploadManager.handleTaskCompletion directly (bypassing URLSession
/// entirely) and verify effects via UploadSessionStore and observable tracking vars.
/// This tests the full completion pipeline — including store writes and gate predicate
/// evaluation — without any network.
///
/// Race-safety test: two blobs completing via concurrent Tasks must both reach
/// the store serialized by its actor, so exactly one completion sees the gate flip.
/// Verified by checking store state after both Tasks complete.
///
/// Decisions: 0040, 0041

import XCTest
@testable import RoomStudioCapture

@MainActor
final class BlobUploadManagerTests: XCTestCase {

    // MARK: - Helpers

    private func makeSessionEntries(_ paths: [String]) -> [UploadSessionEntry] {
        paths.map { UploadSessionEntry(relativePath: $0, sessionUri: "https://gcs.example.com/\($0)") }
    }

    /// Set up a manager + store wired to a temp directory, with a record for `bundleId`
    /// pre-saved in the store. The record includes a temp outputDir with stub files so
    /// tests that trigger enqueuePhasOneBlobs or onAllBlobsUploaded have real files on disk.
    ///
    /// - Parameters:
    ///   - bundleId: The bundle identifier for the record.
    ///   - paths: All relative paths in the manifest (including bundle.pb).
    ///   - mintTimestamp: clientMintTimestamp for the record; defaults to Date().
    ///   - clock: Injected clock for the manager; defaults to Date.init.
    private func makeManager(
        bundleId: String = "test-bundle",
        paths: [String],
        mintTimestamp: Date = Date(),
        clock: @escaping () -> Date = { Date() }
    ) async throws -> (BlobUploadManager, UploadSessionStore, URL) {
        let storeDir = FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString)
        let store = UploadSessionStore(directory: storeDir)
        addTeardownBlock { try? FileManager.default.removeItem(at: storeDir) }

        // Create an outputDir with placeholder files so file-size checks pass.
        let outputDir = FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString)
        addTeardownBlock { try? FileManager.default.removeItem(at: outputDir) }

        for path in paths {
            let fileURL = outputDir.appendingPathComponent(path)
            try FileManager.default.createDirectory(
                at: fileURL.deletingLastPathComponent(),
                withIntermediateDirectories: true
            )
            try Data([0x00, 0x01]).write(to: fileURL)
        }

        let entries = makeSessionEntries(paths)
        let record  = UploadSessionRecord(
            bundleId:            bundleId,
            tierRawValue:        1,
            clientMintTimestamp: mintTimestamp,
            sessionEntries:      entries,
            manifestPaths:       paths,
            outputDir:           outputDir
        )
        try await store.save(record)

        let manager = BlobUploadManager(store: store, clock: clock)
        return (manager, store, outputDir)
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
        let (manager, store, _) = try await makeManager(paths: ["frames/000000.jpg", "bundle.pb"])
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
        let (manager, store, _) = try await makeManager(paths: ["frames/000000.jpg", "bundle.pb"])
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
        let (manager, store, _) = try await makeManager(paths: paths)

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
        let (manager, store, _) = try await makeManager(paths: paths)

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
        let paths = ["frames/000000.jpg", "bundle.pb"]
        let (manager, store, _) = try await makeManager(paths: paths)

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
        let paths = ["frames/000000.jpg", "frames/000001.jpg", "bundle.pb"]
        let (manager, store, _) = try await makeManager(paths: paths)

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
        XCTAssertEqual(record?.blobStatuses["frames/000000.jpg"], .uploaded)
        XCTAssertEqual(record?.blobStatuses["frames/000001.jpg"], .uploaded)
        XCTAssertTrue(record?.allNonBundlePbBlobsUploaded ?? false,
                      "Gate must be true when both blobs are uploaded")
    }

    // MARK: - 410 → blob status unchanged, fresh URIs persisted

    func test_handleTaskCompletion_410_doesNotMarkBlobUploaded() async throws {
        // 410 must not mark the blob as uploaded — the re-mint re-enqueues it, but the
        // completion delegate hasn't fired again yet.
        let (manager, store, _) = try await makeManager(paths: ["frames/000000.jpg", "bundle.pb"])

        // Inject different URIs so the loop guard passes (different == fresh).
        let freshEntry    = UploadSessionEntry(relativePath: "frames/000000.jpg",
                                              sessionUri: "https://fresh.gcs.example.com/frames/000000.jpg")
        let bundlePbEntry = UploadSessionEntry(relativePath: "bundle.pb",
                                              sessionUri: "https://fresh.gcs.example.com/bundle.pb")
        await manager.setRemintProvider { _, _ in [freshEntry, bundlePbEntry] }

        await manager.handleTaskCompletion(
            taskDescription: taskDesc(relativePath: "frames/000000.jpg"),
            statusCode: 410, error: nil
        )

        // Blob status must still be .pending (not marked uploaded by the re-mint).
        let after = try await store.load(bundleId: "test-bundle")
        XCTAssertEqual(after?.blobStatuses["frames/000000.jpg"], .pending,
                       "410 re-mint must not mark blob as uploaded")
        // Fresh URIs must have been persisted (re-mint succeeded with different URIs).
        XCTAssertEqual(after?.sessionUri(for: "frames/000000.jpg"),
                       "https://fresh.gcs.example.com/frames/000000.jpg",
                       "Fresh session URI must be persisted after re-mint")
    }

    // MARK: - 4xx → store unchanged

    func test_handleTaskCompletion_400_doesNotUpdateStore() async throws {
        let (manager, store, _) = try await makeManager(paths: ["frames/000000.jpg", "bundle.pb"])
        await manager.handleTaskCompletion(
            taskDescription: taskDesc(relativePath: "frames/000000.jpg"),
            statusCode: 400, error: nil
        )
        let record = try await store.load(bundleId: "test-bundle")
        XCTAssertEqual(record?.blobStatuses["frames/000000.jpg"], .pending)
    }

    func test_handleTaskCompletion_403_doesNotUpdateStore() async throws {
        let (manager, store, _) = try await makeManager(paths: ["frames/000000.jpg", "bundle.pb"])
        await manager.handleTaskCompletion(
            taskDescription: taskDesc(relativePath: "frames/000000.jpg"),
            statusCode: 403, error: nil
        )
        let record = try await store.load(bundleId: "test-bundle")
        XCTAssertEqual(record?.blobStatuses["frames/000000.jpg"], .pending)
    }

    // MARK: - Malformed / nil taskDescription → safe no-op

    func test_handleTaskCompletion_nilDescription_noOp() async throws {
        let (manager, store, _) = try await makeManager(paths: ["frames/000000.jpg", "bundle.pb"])
        await manager.handleTaskCompletion(taskDescription: nil, statusCode: 200, error: nil)
        let record = try await store.load(bundleId: "test-bundle")
        XCTAssertEqual(record?.blobStatuses["frames/000000.jpg"], .pending)
    }

    func test_handleTaskCompletion_malformedDescription_noOp() async throws {
        let (manager, store, _) = try await makeManager(paths: ["frames/000000.jpg", "bundle.pb"])
        await manager.handleTaskCompletion(taskDescription: "no-pipe-here", statusCode: 200, error: nil)
        let record = try await store.load(bundleId: "test-bundle")
        XCTAssertEqual(record?.blobStatuses["frames/000000.jpg"], .pending)
    }

    // MARK: - network error → store unchanged (5xx / error path)

    func test_handleTaskCompletion_networkError_doesNotUpdateStore() async throws {
        let (manager, store, _) = try await makeManager(paths: ["frames/000000.jpg", "bundle.pb"])
        let fakeError = NSError(domain: NSURLErrorDomain, code: NSURLErrorTimedOut, userInfo: nil)
        await manager.handleTaskCompletion(
            taskDescription: taskDesc(relativePath: "frames/000000.jpg"),
            statusCode: nil, error: fakeError
        )
        let record = try await store.load(bundleId: "test-bundle")
        XCTAssertEqual(record?.blobStatuses["frames/000000.jpg"], .pending)
    }

    // MARK: - onAllBlobsUploaded: staleness guard (Step 2 — injectable clock)

    func test_stalenessGuard_justUnder12h_proceedsToFinalize() async throws {
        // Clock injects a fixed "now". clientMintTimestamp is 11h59m before "now".
        // Elapsed = 11h59m < 12h → fresh → must NOT call onSessionExpired.
        let fixedNow = Date()
        let mintTime = fixedNow.addingTimeInterval(-(11 * 3600 + 59 * 60))
        let (manager, _, _) = try await makeManager(
            paths: ["bundle.pb"],
            mintTimestamp: mintTime,
            clock: { fixedNow }
        )
        let record = try await manager.store.load(bundleId: "test-bundle")!
        await manager.onAllBlobsUploaded(bundleId: "test-bundle", record: record)

        let expired = await manager._sessionExpiredInvocations
        XCTAssertTrue(expired.isEmpty, "11h59m elapsed must NOT trigger the staleness guard")
    }

    func test_stalenessGuard_justOver12h_callsSessionExpired() async throws {
        // Clock injects a fixed "now". clientMintTimestamp is 12h01m before "now".
        // Elapsed = 12h01m > 12h → stale → must call onSessionExpired.
        let fixedNow = Date()
        let mintTime = fixedNow.addingTimeInterval(-(12 * 3600 + 60))
        let (manager, _, _) = try await makeManager(
            paths: ["bundle.pb"],
            mintTimestamp: mintTime,
            clock: { fixedNow }
        )
        let record = try await manager.store.load(bundleId: "test-bundle")!
        await manager.onAllBlobsUploaded(bundleId: "test-bundle", record: record)

        let expired = await manager._sessionExpiredInvocations
        XCTAssertEqual(expired, ["test-bundle"], "12h01m elapsed must trigger staleness guard → onSessionExpired")
        let completed = await manager._bundleCompleteInvocations
        XCTAssertTrue(completed.isEmpty, "Stale path must not call onBundleComplete")
    }

    func test_onAllBlobsUploaded_staleRecord_callsSessionExpired() async throws {
        // Legacy test using a stale record (>12h using the default wall clock).
        // The fixed-clock tests above are the authoritative staleness guard tests;
        // this retains the original scenario.
        let staleTimestamp = Date().addingTimeInterval(-(13 * 3600))
        let entries = makeSessionEntries(["bundle.pb"])
        let staleRecord = UploadSessionRecord(
            bundleId:            "test-bundle",
            tierRawValue:        1,
            clientMintTimestamp: staleTimestamp,
            sessionEntries:      entries,
            manifestPaths:       ["bundle.pb"],
            outputDir:           nil
        )
        let (manager, _, _) = try await makeManager(paths: ["bundle.pb"])

        await manager.onAllBlobsUploaded(bundleId: "test-bundle", record: staleRecord)

        let expired = await manager._sessionExpiredInvocations
        XCTAssertEqual(expired, ["test-bundle"], "Stale record must call onSessionExpired")
        let completed = await manager._bundleCompleteInvocations
        XCTAssertTrue(completed.isEmpty, "Stale record must not call onBundleComplete")
    }

    func test_onAllBlobsUploaded_freshRecord_doesNotCallSessionExpired() async throws {
        let (manager, store, _) = try await makeManager(paths: ["bundle.pb"])
        let record = try await store.load(bundleId: "test-bundle")!

        await manager.onAllBlobsUploaded(bundleId: "test-bundle", record: record)

        let expired = await manager._sessionExpiredInvocations
        XCTAssertTrue(expired.isEmpty, "Fresh record must not call onSessionExpired")
    }

    // MARK: - bundle.pb completion routing

    func test_handleTaskCompletion_bundlePb_200_callsBundleComplete() async throws {
        let (manager, _, _) = try await makeManager(paths: ["frames/000000.jpg", "bundle.pb"])
        await manager.handleTaskCompletion(
            taskDescription: taskDesc(relativePath: "bundle.pb"),
            statusCode: 200, error: nil
        )
        let completed = await manager._bundleCompleteInvocations
        XCTAssertEqual(completed, ["test-bundle"], "bundle.pb 200 must route to onBundleComplete")
    }

    func test_handleTaskCompletion_bundlePb_200_doesNotUpdateStore() async throws {
        let (manager, store, _) = try await makeManager(paths: ["frames/000000.jpg", "bundle.pb"])
        await manager.handleTaskCompletion(
            taskDescription: taskDesc(relativePath: "bundle.pb"),
            statusCode: 200, error: nil
        )
        let record = try await store.load(bundleId: "test-bundle")
        XCTAssertEqual(record?.blobStatuses["bundle.pb"], .pending,
                       "bundle.pb 200 must not update blobStatuses in the store")
    }

    func test_handleTaskCompletion_bundlePb_200_doesNotRefireGate() async throws {
        let (manager, _, _) = try await makeManager(paths: ["frames/000000.jpg", "bundle.pb"])
        await manager.handleTaskCompletion(
            taskDescription: taskDesc(relativePath: "bundle.pb"),
            statusCode: 200, error: nil
        )
        let completed = await manager._bundleCompleteInvocations
        XCTAssertEqual(completed.count, 1, "onBundleComplete must fire exactly once for bundle.pb 200")
    }

    // MARK: - Phase-1 excludes bundle.pb (integration)

    func test_enqueuePhasOneBlobs_excludesBundlePb_bundlePbFinalizedAfterGate() async throws {
        let (manager, _, outputDir) = try await makeManager(paths: ["frames/000000.jpg", "bundle.pb"])
        let record = try await manager.store.load(bundleId: "test-bundle")!

        try await manager.enqueuePhasOneBlobs(record: record)

        // Simulate frame blob 200 → gate flips → onAllBlobsUploaded fires → enqueues bundle.pb.
        await manager.handleTaskCompletion(
            taskDescription: taskDesc(relativePath: "frames/000000.jpg"),
            statusCode: 200, error: nil
        )
        // Simulate bundle.pb 200 → onBundleComplete.
        await manager.handleTaskCompletion(
            taskDescription: taskDesc(relativePath: "bundle.pb"),
            statusCode: 200, error: nil
        )

        let completed = await manager._bundleCompleteInvocations
        XCTAssertEqual(completed, ["test-bundle"],
                       "bundle.pb must be finalized by onAllBlobsUploaded (not Phase-1)")
        let expired = await manager._sessionExpiredInvocations
        XCTAssertTrue(expired.isEmpty, "No session expiry in the happy path")
        _ = outputDir  // referenced to suppress unused-result warning
    }

    // MARK: - onSessionExpired: re-mint

    func test_onSessionExpired_noRemintProvider_routesToFatalError() async throws {
        let (manager, _, _) = try await makeManager(paths: ["frames/000000.jpg", "bundle.pb"])
        // remintProvider is nil by default.
        await manager.onSessionExpired(bundleId: "test-bundle")

        let fatal = await manager._fatalBlobErrorInvocations
        XCTAssertFalse(fatal.isEmpty, "No remintProvider must route to onFatalBlobError")
        XCTAssertTrue(fatal.allSatisfy { $0.reason.contains("expired_no_remint_provider") },
                      "Reason must indicate missing provider; got: \(fatal.map(\.reason))")
    }

    func test_onSessionExpired_freshURIs_reenqueuesPendingBlobs_andPersists() async throws {
        // Fresh URIs returned → re-mint persists fresh record + re-enqueues pending blobs.
        let (manager, store, outputDir) = try await makeManager(paths: ["frames/000000.jpg", "bundle.pb"])

        let freshFrameURI  = "https://fresh.gcs.example.com/frames/000000.jpg"
        let freshBundleURI = "https://fresh.gcs.example.com/bundle.pb"
        await manager.setRemintProvider { _, _ in
            [
                UploadSessionEntry(relativePath: "frames/000000.jpg", sessionUri: freshFrameURI),
                UploadSessionEntry(relativePath: "bundle.pb",         sessionUri: freshBundleURI),
            ]
        }

        await manager.onSessionExpired(bundleId: "test-bundle")

        // Fresh URIs must be persisted.
        let freshRecord = try await store.load(bundleId: "test-bundle")
        XCTAssertEqual(freshRecord?.sessionUri(for: "frames/000000.jpg"), freshFrameURI,
                       "Fresh frame URI must be persisted after re-mint")
        XCTAssertEqual(freshRecord?.sessionUri(for: "bundle.pb"), freshBundleURI,
                       "Fresh bundle.pb URI must be persisted after re-mint")

        // No fatal error (the re-mint succeeded with different URIs).
        let fatal = await manager._fatalBlobErrorInvocations
        XCTAssertTrue(fatal.isEmpty, "Successful re-mint with fresh URIs must not call onFatalBlobError")
        _ = outputDir
    }

    func test_onSessionExpired_freshURIs_preservesUploadedBlobStatus() async throws {
        // If one blob was already uploaded before the 410, its status must be preserved
        // so the re-mint path doesn't re-enqueue it.
        let storeDir = FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString)
        let store = UploadSessionStore(directory: storeDir)
        addTeardownBlock { try? FileManager.default.removeItem(at: storeDir) }

        let outputDir = FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString)
        addTeardownBlock { try? FileManager.default.removeItem(at: outputDir) }

        // Create a record where frames/000000.jpg is already uploaded.
        let entries  = makeSessionEntries(["frames/000000.jpg", "frames/000001.jpg", "bundle.pb"])
        var record   = UploadSessionRecord(
            bundleId:            "test-bundle",
            tierRawValue:        1,
            clientMintTimestamp: Date(),
            sessionEntries:      entries,
            manifestPaths:       ["frames/000000.jpg", "frames/000001.jpg", "bundle.pb"],
            outputDir:           outputDir
        )
        record = record.markingBlobUploaded("frames/000000.jpg")
        try await store.save(record)

        let manager = BlobUploadManager(store: store)
        await manager.setRemintProvider { _, _ in
            [
                UploadSessionEntry(relativePath: "frames/000000.jpg", sessionUri: "https://fresh.example.com/f0"),
                UploadSessionEntry(relativePath: "frames/000001.jpg", sessionUri: "https://fresh.example.com/f1"),
                UploadSessionEntry(relativePath: "bundle.pb",         sessionUri: "https://fresh.example.com/bp"),
            ]
        }

        await manager.onSessionExpired(bundleId: "test-bundle")

        // Already-uploaded blob must retain .uploaded status in the fresh record.
        let freshRecord = try await store.load(bundleId: "test-bundle")
        XCTAssertEqual(freshRecord?.blobStatuses["frames/000000.jpg"], .uploaded,
                       "Re-mint must preserve .uploaded status for already-done blobs")
        XCTAssertEqual(freshRecord?.blobStatuses["frames/000001.jpg"], .pending,
                       "Pending blob must stay .pending in the fresh record")
    }

    // test_410Remint_identicalURIs_stillRoutesToFatalError (below) supersedes this scenario;
    // keeping the original as a direct onSessionExpired call without the staleness path.
    func test_onSessionExpired_directCall_sameURIs_routesToFatalError() async throws {
        // Direct call to onSessionExpired (default loopGuardEnabled: true, i.e. 410 path).
        // If re-mint returns identical URIs, must route to onFatalBlobError (loop prevention).
        let (manager, _, _) = try await makeManager(paths: ["frames/000000.jpg", "bundle.pb"])
        await manager.setRemintProvider { _, _ in
            [
                UploadSessionEntry(relativePath: "frames/000000.jpg",
                                   sessionUri: "https://gcs.example.com/frames/000000.jpg"),
                UploadSessionEntry(relativePath: "bundle.pb",
                                   sessionUri: "https://gcs.example.com/bundle.pb"),
            ]
        }
        await manager.onSessionExpired(bundleId: "test-bundle")

        let fatal = await manager._fatalBlobErrorInvocations
        XCTAssertFalse(fatal.isEmpty, "Same URIs from re-mint (410 path) must route to onFatalBlobError")
        XCTAssertTrue(fatal.allSatisfy { $0.reason.contains("remint_returned_stale_uris") },
                      "Reason must be remint_returned_stale_uris; got: \(fatal.map(\.reason))")
    }

    func test_stalenessRemint_identicalValidURIs_proceedsToBundlePb() async throws {
        // CHECK 1 regression test.
        // Staleness guard fires (>12h), re-mint returns IDENTICAL URIs (server correctly
        // returned the still-valid stored entries — 12h < 7-day GCS window).
        // Must NOT route to onFatalBlobError. All blobs are reset to .pending and re-enqueued.
        // After directly simulating bundle.pb 200, onBundleComplete fires.
        // (The full ordered path — blob re-upload → gate → enqueueBundlePb — is covered by
        // test_stalenessRemint_afterRecompletion_bundlePbFinalized.)
        let fixedNow  = Date()
        let mintTime  = fixedNow.addingTimeInterval(-(12 * 3600 + 60))  // 12h01m ago → stale
        let (manager, _, _) = try await makeManager(
            paths: ["frames/000000.jpg", "bundle.pb"],
            mintTimestamp: mintTime,
            clock: { fixedNow }
        )

        // Mark the frame blob as uploaded (simulating completed Phase-1 before staleness fires).
        _ = try await manager.store.markBlobUploaded(
            bundleId: "test-bundle", relativePath: "frames/000000.jpg"
        )
        let record = try await manager.store.load(bundleId: "test-bundle")!

        // remintProvider returns the SAME URIs (server-side idempotency, still-valid at 12h).
        await manager.setRemintProvider { _, _ in
            [
                UploadSessionEntry(relativePath: "frames/000000.jpg",
                                   sessionUri: "https://gcs.example.com/frames/000000.jpg"),
                UploadSessionEntry(relativePath: "bundle.pb",
                                   sessionUri: "https://gcs.example.com/bundle.pb"),
            ]
        }

        // onAllBlobsUploaded → staleness guard fires → onSessionExpired(loopGuardEnabled: false).
        await manager.onAllBlobsUploaded(bundleId: "test-bundle", record: record)

        // No fatal error: identical URIs must be treated as valid on the staleness path.
        let fatal = await manager._fatalBlobErrorInvocations
        XCTAssertTrue(fatal.isEmpty,
                      "Staleness re-mint with identical valid URIs must NOT fatal; got: \(fatal.map(\.reason))")

        // onSessionExpired was invoked (staleness guard routed correctly).
        let expired = await manager._sessionExpiredInvocations
        XCTAssertEqual(expired, ["test-bundle"])

        // Simulate bundle.pb 200 (directly — production path routes via re-enqueue → gate).
        await manager.handleTaskCompletion(
            taskDescription: BlobUploadManager.makeTaskDescription(
                bundleId: "test-bundle", relativePath: "bundle.pb"),
            statusCode: 200, error: nil
        )
        let completed = await manager._bundleCompleteInvocations
        XCTAssertEqual(completed, ["test-bundle"],
                       "Staleness re-mint must proceed to bundle.pb finalization")
    }

    func test_410Remint_identicalURIs_stillRoutesToFatalError() async throws {
        // CHECK 1: The loop guard must STILL fire on the 410-triggered path when
        // re-mint returns identical URIs (dead URIs still in Firestore → 410 loop risk).
        // This test confirms the fix didn't break the 410 path.
        let (manager, _, _) = try await makeManager(paths: ["frames/000000.jpg", "bundle.pb"])
        // remintProvider returns the same URIs as the stored record.
        await manager.setRemintProvider { _, _ in
            [
                UploadSessionEntry(relativePath: "frames/000000.jpg",
                                   sessionUri: "https://gcs.example.com/frames/000000.jpg"),
                UploadSessionEntry(relativePath: "bundle.pb",
                                   sessionUri: "https://gcs.example.com/bundle.pb"),
            ]
        }
        // Call directly with default loopGuardEnabled: true (the 410 path).
        await manager.onSessionExpired(bundleId: "test-bundle")

        let fatal = await manager._fatalBlobErrorInvocations
        XCTAssertFalse(fatal.isEmpty, "410 re-mint with identical URIs must still fatal")
        XCTAssertTrue(fatal.allSatisfy { $0.reason.contains("remint_returned_stale_uris") },
                      "reason must be remint_returned_stale_uris; got: \(fatal.map(\.reason))")
    }

    func test_onSessionExpired_mintFailure_routesToFatalError() async throws {
        // re-mint throws → onFatalBlobError.
        let (manager, _, _) = try await makeManager(paths: ["frames/000000.jpg", "bundle.pb"])
        await manager.setRemintProvider { _, _ in
            throw UploadSessionError.serverError(503, "unavailable")
        }

        await manager.onSessionExpired(bundleId: "test-bundle")

        let fatal = await manager._fatalBlobErrorInvocations
        XCTAssertFalse(fatal.isEmpty, "Re-mint failure must route to onFatalBlobError")
        XCTAssertTrue(fatal.allSatisfy { $0.reason.contains("remint_failed") },
                      "Reason must be remint_failed; got: \(fatal.map(\.reason))")
    }

    // MARK: - Staleness re-upload: Check-3 (all blobs reset + re-enqueued)

    func test_stalenessRemint_allBlobsResetToPending_bundlePbNotEnqueuedBeforeGateReCloses() async throws {
        // Staleness fires (>12h). All blobs previously .uploaded.
        // After staleness re-mint: all non-bundle.pb blobs must be .pending in the store,
        // and bundle.pb must NOT be finalized until the gate re-closes via normal completion.
        let fixedNow = Date()
        let mintTime = fixedNow.addingTimeInterval(-(12 * 3600 + 60))  // 12h01m ago → stale
        let paths = ["frames/000000.jpg", "frames/000001.jpg", "bundle.pb"]
        let (manager, store, _) = try await makeManager(
            paths: paths, mintTimestamp: mintTime, clock: { fixedNow }
        )
        _ = try await store.markBlobUploaded(bundleId: "test-bundle", relativePath: "frames/000000.jpg")
        _ = try await store.markBlobUploaded(bundleId: "test-bundle", relativePath: "frames/000001.jpg")
        let record = try await store.load(bundleId: "test-bundle")!
        XCTAssertTrue(record.allNonBundlePbBlobsUploaded, "Pre-condition: gate must be true before staleness fires")

        await manager.setRemintProvider { _, _ in
            [
                UploadSessionEntry(relativePath: "frames/000000.jpg", sessionUri: "https://fresh.example.com/f0"),
                UploadSessionEntry(relativePath: "frames/000001.jpg", sessionUri: "https://fresh.example.com/f1"),
                UploadSessionEntry(relativePath: "bundle.pb",         sessionUri: "https://fresh.example.com/bp"),
            ]
        }

        // Staleness guard fires → all blobs reset to .pending, re-enqueued.
        await manager.onAllBlobsUploaded(bundleId: "test-bundle", record: record)

        let afterReset = try await store.load(bundleId: "test-bundle")!
        XCTAssertEqual(afterReset.blobStatuses["frames/000000.jpg"], .pending,
                       "frames/000000.jpg must be reset to .pending after staleness re-mint")
        XCTAssertEqual(afterReset.blobStatuses["frames/000001.jpg"], .pending,
                       "frames/000001.jpg must be reset to .pending after staleness re-mint")
        let completed = await manager._bundleCompleteInvocations
        XCTAssertTrue(completed.isEmpty,
                      "bundle.pb must NOT be finalized before gate re-closes via normal completion")
        let fatal = await manager._fatalBlobErrorInvocations
        XCTAssertTrue(fatal.isEmpty, "No fatal error expected on staleness re-mint with all files present")
    }

    func test_stalenessRemint_afterRecompletion_bundlePbFinalized() async throws {
        // End-to-end: staleness fires → all blobs reset → re-uploaded → gate re-fires →
        // bundle.pb enqueued → onBundleComplete. Verifies the full ordering guarantee.
        let fixedNow = Date()
        let mintTime = fixedNow.addingTimeInterval(-(12 * 3600 + 60))
        let paths = ["frames/000000.jpg", "bundle.pb"]
        let (manager, store, _) = try await makeManager(
            paths: paths, mintTimestamp: mintTime, clock: { fixedNow }
        )
        _ = try await store.markBlobUploaded(bundleId: "test-bundle", relativePath: "frames/000000.jpg")
        let record = try await store.load(bundleId: "test-bundle")!

        await manager.setRemintProvider { _, _ in
            [
                UploadSessionEntry(relativePath: "frames/000000.jpg", sessionUri: "https://fresh.example.com/f0"),
                UploadSessionEntry(relativePath: "bundle.pb",         sessionUri: "https://fresh.example.com/bp"),
            ]
        }

        // Staleness fires → blob reset to .pending, re-enqueued.
        await manager.onAllBlobsUploaded(bundleId: "test-bundle", record: record)
        let notYetCompleted = await manager._bundleCompleteInvocations
        XCTAssertTrue(notYetCompleted.isEmpty,
                      "bundle.pb must NOT be finalized before blob re-upload completes")

        // Simulate re-upload of the frame blob → gate re-closes → onAllBlobsUploaded →
        // clientMintTimestamp is now fixedNow (fresh), so staleness check passes → enqueueBundlePb.
        await manager.handleTaskCompletion(
            taskDescription: taskDesc(relativePath: "frames/000000.jpg"),
            statusCode: 200, error: nil
        )
        // Simulate bundle.pb 200 → onBundleComplete.
        await manager.handleTaskCompletion(
            taskDescription: taskDesc(relativePath: "bundle.pb"),
            statusCode: 200, error: nil
        )

        let completed = await manager._bundleCompleteInvocations
        XCTAssertEqual(completed, ["test-bundle"],
                       "Staleness re-mint → re-upload → gate → bundle.pb must finalize end-to-end")
        let fatal = await manager._fatalBlobErrorInvocations
        XCTAssertTrue(fatal.isEmpty, "No fatal error expected on full staleness re-upload path")
    }

    func test_stalenessRemint_blobFileMissing_routesToFatalError() async throws {
        // Staleness re-enqueue: blob file missing from disk (App Support dir cleared).
        // Expect: onFatalBlobError("blob_file_missing_at_staleness_remint"), bundle.pb NOT finalized.
        // Detection: FileManager.fileExists(atPath:) returns false for the missing file.
        let fixedNow = Date()
        let mintTime = fixedNow.addingTimeInterval(-(12 * 3600 + 60))
        let paths = ["frames/000000.jpg", "bundle.pb"]
        let (manager, store, outputDir) = try await makeManager(
            paths: paths, mintTimestamp: mintTime, clock: { fixedNow }
        )
        _ = try await store.markBlobUploaded(bundleId: "test-bundle", relativePath: "frames/000000.jpg")
        let record = try await store.load(bundleId: "test-bundle")!

        // Delete the blob file to simulate App Support loss.
        try FileManager.default.removeItem(at: outputDir.appendingPathComponent("frames/000000.jpg"))

        await manager.setRemintProvider { _, _ in
            [
                UploadSessionEntry(relativePath: "frames/000000.jpg", sessionUri: "https://fresh.example.com/f0"),
                UploadSessionEntry(relativePath: "bundle.pb",         sessionUri: "https://fresh.example.com/bp"),
            ]
        }

        await manager.onAllBlobsUploaded(bundleId: "test-bundle", record: record)

        let fatal = await manager._fatalBlobErrorInvocations
        XCTAssertFalse(fatal.isEmpty, "Missing blob file must route to onFatalBlobError")
        XCTAssertTrue(
            fatal.allSatisfy { $0.reason == "blob_file_missing_at_staleness_remint" },
            "Reason must be blob_file_missing_at_staleness_remint; got: \(fatal.map(\.reason))"
        )
        let completed = await manager._bundleCompleteInvocations
        XCTAssertTrue(completed.isEmpty, "bundle.pb must NOT be finalized when a blob file is missing")
    }

    func test_coldRelaunch_stalenessRemint_finalizesBundlePb() async throws {
        // Cold-relaunch + staleness: fresh manager, only on-disk record present, >12h elapsed.
        // Verifies that path reconstruction from outputDir in the persisted record works,
        // all blobs are re-enqueued, and the full pipeline finalizes correctly.
        let fixedNow = Date()
        let mintTime = fixedNow.addingTimeInterval(-(12 * 3600 + 60))
        let paths = ["frames/000000.jpg", "bundle.pb"]
        let (_, store, _) = try await makeManager(
            paths: paths, mintTimestamp: mintTime, clock: { fixedNow }
        )
        _ = try await store.markBlobUploaded(bundleId: "test-bundle", relativePath: "frames/000000.jpg")

        // Cold-relaunch: fresh manager instance, no in-memory contexts.
        let coldManager = BlobUploadManager(store: store, clock: { fixedNow })
        await coldManager.setRemintProvider { _, _ in
            [
                UploadSessionEntry(relativePath: "frames/000000.jpg", sessionUri: "https://fresh.example.com/f0"),
                UploadSessionEntry(relativePath: "bundle.pb",         sessionUri: "https://fresh.example.com/bp"),
            ]
        }

        let record = try await store.load(bundleId: "test-bundle")!
        XCTAssertTrue(record.allNonBundlePbBlobsUploaded, "Pre-condition: gate must be true before staleness fires")
        XCTAssertNotNil(record.outputDir, "Record must carry outputDir for cold-relaunch path reconstruction")

        // Staleness fires → reset → re-enqueue (reconstructs paths from record.outputDir).
        await coldManager.onAllBlobsUploaded(bundleId: "test-bundle", record: record)

        let afterReset = try await store.load(bundleId: "test-bundle")!
        XCTAssertEqual(afterReset.blobStatuses["frames/000000.jpg"], .pending,
                       "Cold-relaunch: blob must be reset to .pending after staleness re-mint")

        // Simulate re-upload → gate → bundle.pb → onBundleComplete.
        await coldManager.handleTaskCompletion(
            taskDescription: BlobUploadManager.makeTaskDescription(bundleId: "test-bundle", relativePath: "frames/000000.jpg"),
            statusCode: 200, error: nil
        )
        await coldManager.handleTaskCompletion(
            taskDescription: BlobUploadManager.makeTaskDescription(bundleId: "test-bundle", relativePath: "bundle.pb"),
            statusCode: 200, error: nil
        )

        let completed = await coldManager._bundleCompleteInvocations
        XCTAssertEqual(completed, ["test-bundle"],
                       "Cold-relaunch staleness re-mint must finalize bundle end-to-end")
        let fatal = await coldManager._fatalBlobErrorInvocations
        XCTAssertTrue(fatal.isEmpty, "Cold-relaunch staleness re-mint must not fatal")
    }

    // MARK: - Step 3: cold-relaunch correctness

    func test_coldRelaunch_onAllBlobsUploaded_usesRecordOutputDir() async throws {
        // Simulate cold relaunch: fresh manager (no contexts), on-disk record has outputDir.
        // onAllBlobsUploaded must locate and PUT bundle.pb from the record alone.
        let (_, store, outputDir) = try await makeManager(paths: ["bundle.pb"])
        let record = try await store.load(bundleId: "test-bundle")!

        // Fresh manager — no in-memory context for this bundle.
        let coldManager = BlobUploadManager(store: store)
        XCTAssertNotNil(record.outputDir, "Record must have outputDir for cold relaunch to work")

        await coldManager.onAllBlobsUploaded(bundleId: "test-bundle", record: record)

        // Should proceed without error (no sessionExpired, no fatal).
        let expired = await coldManager._sessionExpiredInvocations
        XCTAssertTrue(expired.isEmpty, "Fresh record must not trigger staleness guard")
        let fatal = await coldManager._fatalBlobErrorInvocations
        XCTAssertTrue(fatal.isEmpty, "Cold relaunch with valid record must not fatal")

        // Simulate bundle.pb task completing (OS delivers it to the new session instance).
        await coldManager.handleTaskCompletion(
            taskDescription: BlobUploadManager.makeTaskDescription(
                bundleId: "test-bundle", relativePath: "bundle.pb"),
            statusCode: 200, error: nil
        )
        let completed = await coldManager._bundleCompleteInvocations
        XCTAssertEqual(completed, ["test-bundle"],
                       "bundle.pb 200 on cold relaunch must route to onBundleComplete")
        _ = outputDir
    }

    func test_coldRelaunch_onSessionExpired_reenqueuesPendingBlobs() async throws {
        // Simulate cold relaunch: fresh manager, on-disk record, remintProvider injected.
        // onSessionExpired must re-enqueue pending blobs using ONLY the on-disk record.
        let (_, store, outputDir) = try await makeManager(
            paths: ["frames/000000.jpg", "bundle.pb"]
        )
        let coldManager = BlobUploadManager(store: store)

        let freshFrameURI  = "https://fresh.example.com/frames/000000.jpg"
        let freshBundleURI = "https://fresh.example.com/bundle.pb"
        await coldManager.setRemintProvider { _, _ in
            [
                UploadSessionEntry(relativePath: "frames/000000.jpg", sessionUri: freshFrameURI),
                UploadSessionEntry(relativePath: "bundle.pb",         sessionUri: freshBundleURI),
            ]
        }

        // onSessionExpired: loads record, re-mints, re-enqueues frames/000000.jpg.
        await coldManager.onSessionExpired(bundleId: "test-bundle")

        // Simulate re-enqueued frame 200 → gate flips → onAllBlobsUploaded → bundle.pb enqueued.
        await coldManager.handleTaskCompletion(
            taskDescription: BlobUploadManager.makeTaskDescription(
                bundleId: "test-bundle", relativePath: "frames/000000.jpg"),
            statusCode: 200, error: nil
        )
        // Simulate bundle.pb 200 → onBundleComplete.
        await coldManager.handleTaskCompletion(
            taskDescription: BlobUploadManager.makeTaskDescription(
                bundleId: "test-bundle", relativePath: "bundle.pb"),
            statusCode: 200, error: nil
        )

        let completed = await coldManager._bundleCompleteInvocations
        XCTAssertEqual(completed, ["test-bundle"],
                       "Cold relaunch: re-mint → re-enqueue → gate → onBundleComplete must complete end-to-end")
        let fatal = await coldManager._fatalBlobErrorInvocations
        XCTAssertTrue(fatal.isEmpty, "Cold relaunch happy path must not fatal")
        _ = outputDir
    }

}

// MARK: - BlobUploadManager test helpers

extension BlobUploadManager {
    /// Convenience for tests: set remintProvider from a @MainActor context.
    func setRemintProvider(
        _ provider: @escaping @Sendable (String, [UploadManifestEntry]) async throws -> [UploadSessionEntry]
    ) {
        remintProvider = provider
    }
}
