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
import os
@testable import TheGoodGuest

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
            outputDir:           FileManager.default.temporaryDirectory
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

        // Blob files must exist on disk: the re-mint manifest reads real sizes and
        // fatals on a missing file.
        for path in ["frames/000000.jpg", "frames/000001.jpg", "bundle.pb"] {
            let fileURL = outputDir.appendingPathComponent(path)
            try FileManager.default.createDirectory(
                at: fileURL.deletingLastPathComponent(),
                withIntermediateDirectories: true
            )
            try Data([0x00, 0x01]).write(to: fileURL)
        }

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

    func test_onSessionExpired_mintFailure_defersToCrossLaunchRetry() async throws {
        // remint_failed is DEFERRED-TRANSIENT (decision 0045 unit b): transient network/server
        // error from /upload_session. Must NOT route to onFatalBlobError. Instead:
        //   • blob stays .pending (uploadPhase unchanged)
        //   • crossLaunchRetryCount bumped to 1
        //   • relaunch path retries on next launch
        let (manager, store, _) = try await makeManager(paths: ["frames/000000.jpg", "bundle.pb"])
        await manager.setRemintProvider { _, _ in
            throw UploadSessionError.serverError(503, "unavailable")
        }

        await manager.onSessionExpired(bundleId: "test-bundle")

        let fatal = await manager._fatalBlobErrorInvocations
        XCTAssertTrue(fatal.isEmpty,
                      "remint_failed must route to deferred (not fatal); got: \(fatal.map(\.reason))")

        let record = try await store.load(bundleId: "test-bundle")!
        XCTAssertNotEqual(record.uploadPhase, .failed,
                          "remint_failed must NOT mark bundle .failed")
        XCTAssertEqual(record.crossLaunchRetryCount, 1,
                       "remint_failed must bump crossLaunchRetryCount to 1")
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
        // Staleness re-mint: blob file missing from disk (App Support dir cleared).
        // A file already missing when onSessionExpired starts is caught at manifest
        // build (real-size read, pre-mint) — before the staleness pre-pass — so the
        // abort must leave the store untouched and start zero uploads.
        // Expect: onFatalBlobError("blob_unreadable_at_remint_manifest") fired once;
        //         no blob status reset to .pending; bundle.pb NOT finalized.
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
            fatal.allSatisfy { $0.reason == "blob_unreadable_at_remint_manifest" },
            "Reason must be blob_unreadable_at_remint_manifest; got: \(fatal.map(\.reason))"
        )
        let completed = await manager._bundleCompleteInvocations
        XCTAssertTrue(completed.isEmpty, "bundle.pb must NOT be finalized when a blob file is missing")

        // KEY ZERO-SIDE-EFFECTS ASSERTIONS (manifest-build ordering guarantee):
        // The manifest build aborts before the mint call, the fresh-record save, and
        // resettingNonBundlePbBlobsToPending, so apart from the .failed phase the store
        // must reflect the pre-call state — no status mutation, no fresh URIs persisted,
        // zero URLSession tasks enqueued.
        let afterAbort = try await store.load(bundleId: "test-bundle")!
        XCTAssertEqual(afterAbort.blobStatuses["frames/000000.jpg"], .uploaded,
                       "Manifest-build abort must NOT reset blob status to .pending (zero state mutation)")
        XCTAssertEqual(afterAbort.blobStatuses["bundle.pb"], .pending,
                       "bundle.pb status must remain .pending after abort (unchanged from pre-call)")
        XCTAssertEqual(afterAbort.sessionUri(for: "frames/000000.jpg"),
                       "https://gcs.example.com/frames/000000.jpg",
                       "Abort happens pre-mint: fresh URIs must never be persisted")
    }

    // MARK: - onSessionExpired: real manifest sizes (pre-launch gap (c) client half)

    func test_onSessionExpired_remintManifestCarriesRealSizes() async throws {
        // The re-mint manifest must carry each blob's real on-disk size — including
        // already-uploaded blobs, since the full path-set is the idempotency key —
        // never the historical placeholder 0.
        let paths = ["frames/000000.jpg", "frames/000001.jpg", "bundle.pb"]
        let (manager, store, outputDir) = try await makeManager(paths: paths)

        // Overwrite the 2-byte placeholder files with distinct known sizes.
        try Data(count: 5).write(to: outputDir.appendingPathComponent("frames/000000.jpg"))
        try Data(count: 7).write(to: outputDir.appendingPathComponent("frames/000001.jpg"))
        try Data(count: 3).write(to: outputDir.appendingPathComponent("bundle.pb"))
        // One blob already uploaded: it must still appear in the manifest with its real size.
        _ = try await store.markBlobUploaded(bundleId: "test-bundle", relativePath: "frames/000000.jpg")

        let captured = OSAllocatedUnfairLock<[UploadManifestEntry]>(initialState: [])
        await manager.setRemintProvider { _, manifest in
            captured.withLock { $0 = manifest }
            return [
                UploadSessionEntry(relativePath: "frames/000000.jpg", sessionUri: "https://fresh.example.com/f0"),
                UploadSessionEntry(relativePath: "frames/000001.jpg", sessionUri: "https://fresh.example.com/f1"),
                UploadSessionEntry(relativePath: "bundle.pb",         sessionUri: "https://fresh.example.com/bp"),
            ]
        }

        await manager.onSessionExpired(bundleId: "test-bundle")

        let sizesByPath = Dictionary(
            uniqueKeysWithValues: captured.withLock { $0 }.map { ($0.relativePath, $0.expectedSizeBytes) }
        )
        XCTAssertEqual(sizesByPath, [
            "frames/000000.jpg": 5,
            "frames/000001.jpg": 7,
            "bundle.pb":         3,
        ], "Re-mint manifest must carry real on-disk sizes for every manifest path")
        let fatal = await manager._fatalBlobErrorInvocations
        XCTAssertTrue(fatal.isEmpty, "Re-mint with readable files must not fatal; got: \(fatal.map(\.reason))")
    }

    func test_onSessionExpired_blobFileMissingAtManifestBuild_fatalsWithoutMintCall() async throws {
        // A blob file missing at size-read time routes to the existing fatal path —
        // never a silent expectedSizeBytes = 0 — and no /upload_session call is spent
        // on a session that could not be used.
        let (manager, store, outputDir) = try await makeManager(paths: ["frames/000000.jpg", "bundle.pb"])
        try FileManager.default.removeItem(at: outputDir.appendingPathComponent("frames/000000.jpg"))

        let mintCalls = OSAllocatedUnfairLock(initialState: 0)
        await manager.setRemintProvider { _, _ in
            mintCalls.withLock { $0 += 1 }
            return [
                UploadSessionEntry(relativePath: "frames/000000.jpg", sessionUri: "https://fresh.example.com/f0"),
                UploadSessionEntry(relativePath: "bundle.pb",         sessionUri: "https://fresh.example.com/bp"),
            ]
        }

        await manager.onSessionExpired(bundleId: "test-bundle")

        let fatal = await manager._fatalBlobErrorInvocations
        XCTAssertEqual(fatal.count, 1, "Missing blob file at manifest build must fatal exactly once")
        XCTAssertEqual(fatal.first?.reason, "blob_unreadable_at_remint_manifest")
        XCTAssertEqual(fatal.first?.relativePath, "frames/000000.jpg")
        XCTAssertEqual(mintCalls.withLock { $0 }, 0,
                       "remintProvider must NOT be called when a blob file is unreadable")
        let stored = try await store.load(bundleId: "test-bundle")!
        XCTAssertEqual(stored.uploadPhase, .failed, "Manifest-build fatal must persist .failed")
        XCTAssertEqual(stored.failureReason, "blob_unreadable_at_remint_manifest")
    }

    func test_stalenessRemint_fileVanishingAfterManifestBuild_prePassStillCatches() async throws {
        // Defence-in-depth: the staleness pre-pass (post-mint, pre-reset) still catches
        // a file that vanishes AFTER the manifest size-read but BEFORE re-enqueue. The
        // remintProvider stub deletes the file to land in exactly that window.
        let fixedNow = Date()
        let mintTime = fixedNow.addingTimeInterval(-(12 * 3600 + 60))
        let paths = ["frames/000000.jpg", "bundle.pb"]
        let (manager, store, outputDir) = try await makeManager(
            paths: paths, mintTimestamp: mintTime, clock: { fixedNow }
        )
        _ = try await store.markBlobUploaded(bundleId: "test-bundle", relativePath: "frames/000000.jpg")
        let record = try await store.load(bundleId: "test-bundle")!

        await manager.setRemintProvider { _, _ in
            try? FileManager.default.removeItem(at: outputDir.appendingPathComponent("frames/000000.jpg"))
            return [
                UploadSessionEntry(relativePath: "frames/000000.jpg", sessionUri: "https://fresh.example.com/f0"),
                UploadSessionEntry(relativePath: "bundle.pb",         sessionUri: "https://fresh.example.com/bp"),
            ]
        }

        await manager.onAllBlobsUploaded(bundleId: "test-bundle", record: record)

        let fatal = await manager._fatalBlobErrorInvocations
        XCTAssertEqual(fatal.map(\.reason), ["blob_file_missing_at_staleness_remint"],
                       "Pre-pass must still catch a file that vanishes after the manifest size-read")
        let afterAbort = try await store.load(bundleId: "test-bundle")!
        XCTAssertEqual(afterAbort.blobStatuses["frames/000000.jpg"], .uploaded,
                       "Pre-pass abort must NOT reset blob status to .pending")
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

    // MARK: - Background completion handler (D2 AppDelegate seam)

    /// Verifies the store/drain/clear lifecycle for the backgroundSessionCompletionHandler.
    /// The effect tested here (handler stored → drain called → handler cleared) is the
    /// seam that AppDelegate.application(_:handleEventsForBackgroundURLSession:completionHandler:)
    /// relies on; the on-device behaviour (actual OS relaunch, delivery of background events)
    /// is untestable in simulator and is covered by on-device gates 2 & 3 (decision 0041).

    func test_setBackgroundCompletionHandler_storesHandler() async {
        let storeDir = FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString)
        let store = UploadSessionStore(directory: storeDir)
        addTeardownBlock { try? FileManager.default.removeItem(at: storeDir) }
        let manager = BlobUploadManager(store: store)

        let beforeSet = await manager.backgroundSessionCompletionHandler
        XCTAssertNil(beforeSet, "Handler must be nil before set")

        await manager.setBackgroundCompletionHandler { }

        let afterSet = await manager.backgroundSessionCompletionHandler
        XCTAssertNotNil(afterSet, "Handler must be non-nil after set")
    }

    func test_drainBackgroundSessionEvents_clearsHandler() async {
        let storeDir = FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString)
        let store = UploadSessionStore(directory: storeDir)
        addTeardownBlock { try? FileManager.default.removeItem(at: storeDir) }
        let manager = BlobUploadManager(store: store)

        await manager.setBackgroundCompletionHandler { }
        let beforeDrain = await manager.backgroundSessionCompletionHandler
        XCTAssertNotNil(beforeDrain, "Pre-condition: handler must be stored before drain")

        await manager.drainBackgroundSessionEvents()

        let afterDrain = await manager.backgroundSessionCompletionHandler
        XCTAssertNil(afterDrain, "Handler must be cleared after drain so a second drain is a no-op")
    }

    func test_drainBackgroundSessionEvents_secondDrain_isNoOp() async {
        // Drain with no stored handler must not crash and must leave handler nil.
        let storeDir = FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString)
        let store = UploadSessionStore(directory: storeDir)
        addTeardownBlock { try? FileManager.default.removeItem(at: storeDir) }
        let manager = BlobUploadManager(store: store)

        await manager.setBackgroundCompletionHandler { }
        await manager.drainBackgroundSessionEvents()  // first drain — clears handler
        await manager.drainBackgroundSessionEvents()  // second drain — must be a no-op

        let afterSecondDrain = await manager.backgroundSessionCompletionHandler
        XCTAssertNil(afterSecondDrain, "Handler must remain nil after second drain (no-op)")
    }

    // MARK: - Group A: drain-gate counter balance (Part B)
    //
    // Strategy: call incrementPendingCompletions() before handleTaskCompletion to mirror
    // production flow (BlobUploadDelegate increments before Task spawn). Verify counter
    // returns to 0 after handleTaskCompletion's defer fires on every exit path.

    private func makeManagerAndIncrement(
        paths: [String] = ["frames/000000.jpg", "bundle.pb"]
    ) async throws -> (BlobUploadManager, UploadSessionStore) {
        let (manager, store, _) = try await makeManager(paths: paths)
        return (manager, store)
    }

    func test_counter_malformedDescription_balances() async throws {
        let (manager, _) = try await makeManagerAndIncrement()
        manager.incrementPendingCompletions()
        await manager.handleTaskCompletion(taskDescription: "no-pipe", statusCode: 200, error: nil)
        XCTAssertEqual(manager._pendingCompletionsCount, 0, "Counter must return to 0 after malformed-desc early return")
    }

    func test_counter_200Success_gateNotFired_balances() async throws {
        // Two blobs; first 200 doesn't fire the gate. Counter must still balance.
        let (manager, _, _) = try await makeManager(paths: ["frames/000000.jpg", "frames/000001.jpg", "bundle.pb"])
        manager.incrementPendingCompletions()
        await manager.handleTaskCompletion(taskDescription: taskDesc(relativePath: "frames/000000.jpg"),
                                           statusCode: 200, error: nil)
        XCTAssertEqual(manager._pendingCompletionsCount, 0)
    }

    func test_counter_200Success_gateFires_balances() async throws {
        // Single non-bundle blob; 200 fires the gate → onAllBlobsUploaded → enqueueBundlePb. Counter balances.
        let (manager, _) = try await makeManagerAndIncrement()
        manager.incrementPendingCompletions()
        await manager.handleTaskCompletion(taskDescription: taskDesc(relativePath: "frames/000000.jpg"),
                                           statusCode: 200, error: nil)
        XCTAssertEqual(manager._pendingCompletionsCount, 0)
    }

    func test_counter_bundlePb200_balances() async throws {
        let (manager, _) = try await makeManagerAndIncrement()
        manager.incrementPendingCompletions()
        await manager.handleTaskCompletion(taskDescription: taskDesc(relativePath: "bundle.pb"),
                                           statusCode: 200, error: nil)
        XCTAssertEqual(manager._pendingCompletionsCount, 0)
    }

    func test_counter_4xxFatal_balances() async throws {
        let (manager, _) = try await makeManagerAndIncrement()
        manager.incrementPendingCompletions()
        await manager.handleTaskCompletion(taskDescription: taskDesc(relativePath: "frames/000000.jpg"),
                                           statusCode: 403, error: nil)
        XCTAssertEqual(manager._pendingCompletionsCount, 0)
    }

    func test_counter_410NoRemint_balances() async throws {
        let (manager, _) = try await makeManagerAndIncrement()
        // remintProvider nil → routes to onFatalBlobError → defer still fires.
        manager.incrementPendingCompletions()
        await manager.handleTaskCompletion(taskDescription: taskDesc(relativePath: "frames/000000.jpg"),
                                           statusCode: 410, error: nil)
        XCTAssertEqual(manager._pendingCompletionsCount, 0)
    }

    func test_counter_410Remint_success_balances() async throws {
        let (manager, _) = try await makeManagerAndIncrement()
        await manager.setRemintProvider { _, _ in
            [UploadSessionEntry(relativePath: "frames/000000.jpg", sessionUri: "https://fresh.example.com/f0"),
             UploadSessionEntry(relativePath: "bundle.pb",         sessionUri: "https://fresh.example.com/bp")]
        }
        manager.incrementPendingCompletions()
        await manager.handleTaskCompletion(taskDescription: taskDesc(relativePath: "frames/000000.jpg"),
                                           statusCode: 410, error: nil)
        // 410 re-mint starts a new URLSession task; THIS call's counter must have decremented.
        XCTAssertEqual(manager._pendingCompletionsCount, 0)
    }

    func test_counter_networkError_noContext_balances() async throws {
        let (manager, _) = try await makeManagerAndIncrement()
        let err = NSError(domain: NSURLErrorDomain, code: NSURLErrorTimedOut)
        manager.incrementPendingCompletions()
        await manager.handleTaskCompletion(taskDescription: taskDesc(relativePath: "frames/000000.jpg"),
                                           statusCode: nil, error: err)
        XCTAssertEqual(manager._pendingCompletionsCount, 0)
    }

    func test_counter_multipleParallelCompletions_allBalance() async throws {
        let paths = ["frames/000000.jpg", "frames/000001.jpg", "bundle.pb"]
        let (manager, _, _) = try await makeManager(paths: paths)
        manager.incrementPendingCompletions()
        manager.incrementPendingCompletions()
        await withTaskGroup(of: Void.self) { group in
            group.addTask {
                await manager.handleTaskCompletion(
                    taskDescription: self.taskDesc(relativePath: "frames/000000.jpg"),
                    statusCode: 200, error: nil as Error?
                )
            }
            group.addTask {
                await manager.handleTaskCompletion(
                    taskDescription: self.taskDesc(relativePath: "frames/000001.jpg"),
                    statusCode: 200, error: nil as Error?
                )
            }
        }
        XCTAssertEqual(manager._pendingCompletionsCount, 0, "All parallel completions must decrement to 0")
    }

    // MARK: - Group B: drain-gate fire conditions (Part B)
    //
    // "spy" helpers below capture call counts through OSAllocatedUnfairLock so the closure
    // is @Sendable-compatible and safe from the actor executor.

    private func makeSpy() -> (handler: () -> Void, callCount: () -> Int) {
        let lock = OSAllocatedUnfairLock(initialState: 0)
        let handler: () -> Void = { lock.withLock { $0 += 1 } }
        let callCount: () -> Int = { lock.withLock { $0 } }
        return (handler, callCount)
    }

    private func makeMinimalManager() -> BlobUploadManager {
        let storeDir = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        let store = UploadSessionStore(directory: storeDir)
        addTeardownBlock { try? FileManager.default.removeItem(at: storeDir) }
        return BlobUploadManager(store: store)
    }

    func test_gate_decrement_withoutDrain_doesNotFireHandler() async {
        // Counter reaches 0 but drainObserved is false → handler must NOT fire.
        let manager = makeMinimalManager()
        let (spy, count) = makeSpy()
        await manager.setBackgroundCompletionHandler(spy)
        // Simulate one in-flight completion: increment, then decrement via handleTaskCompletion.
        manager.incrementPendingCompletions()
        // handleTaskCompletion's defer decrements and routes through the gate before the
        // call returns, so awaiting it is the whole synchronisation — there is no window
        // afterwards in which the handler could still be on its way.
        await manager.handleTaskCompletion(taskDescription: nil, statusCode: nil, error: nil)
        XCTAssertEqual(count(), 0, "Handler must not fire when drainObserved is false")
        let drainSeen = await manager._drainObserved
        XCTAssertFalse(drainSeen, "drainObserved must remain false")
    }

    func test_gate_drain_counterAlreadyZero_firesImmediately() async {
        // drain arrives when count is already 0 → fires synchronously in drainBackgroundSessionEvents.
        let manager = makeMinimalManager()
        let (spy, count) = makeSpy()
        await manager.setBackgroundCompletionHandler(spy)
        await manager.drainBackgroundSessionEvents()
        XCTAssertEqual(count(), 1, "Handler must fire immediately when drain arrives with count == 0")
        let handlerStored = await manager.backgroundSessionCompletionHandler
        XCTAssertNil(handlerStored, "Handler must be cleared after firing")
    }

    func test_gate_lastDecrement_afterDrain_firesHandler() async {
        // drain arrives first (count still > 0), then last decrement → fires on decrement.
        let manager = makeMinimalManager()
        let (spy, count) = makeSpy()
        await manager.setBackgroundCompletionHandler(spy)
        manager.incrementPendingCompletions()
        // Drain arrives while one completion is still in-flight.
        await manager.drainBackgroundSessionEvents()
        XCTAssertEqual(count(), 0, "Handler must not fire: count > 0 despite drain observed")
        // Last handleTaskCompletion completes → counter → 0 → fires, inside that call's own
        // defer. The await is the signal: the handler has run by the time it returns, so this
        // asserts an ordering the seam guarantees rather than outrunning a scheduler.
        await manager.handleTaskCompletion(taskDescription: nil, statusCode: nil, error: nil)
        XCTAssertEqual(count(), 1, "Handler must fire after last decrement when drain already observed")
    }

    func test_gate_multipleDecrements_handlerFiredExactlyOnce() async {
        // N completions all decrement to 0 concurrently; handler fires exactly once.
        let manager = makeMinimalManager()
        let (spy, count) = makeSpy()
        await manager.setBackgroundCompletionHandler(spy)
        manager.incrementPendingCompletions()
        manager.incrementPendingCompletions()
        await manager.drainBackgroundSessionEvents()
        await withTaskGroup(of: Void.self) { group in
            group.addTask { await manager.handleTaskCompletion(taskDescription: nil, statusCode: nil, error: nil) }
            group.addTask { await manager.handleTaskCompletion(taskDescription: nil, statusCode: nil, error: nil) }
        }
        XCTAssertEqual(count(), 1, "Handler must fire exactly once regardless of concurrency")
    }

    func test_gate_noHandlerStored_decrementToZero_isNoOp() async {
        // No completion handler stored; decrement to zero must not crash.
        let manager = makeMinimalManager()
        manager.incrementPendingCompletions()
        await manager.drainBackgroundSessionEvents()
        await manager.handleTaskCompletion(taskDescription: nil, statusCode: nil, error: nil)
        let fired = await manager._handlerFired
        XCTAssertFalse(fired, "handlerFired must remain false when no handler was stored")
    }

    func test_gate_handlerStoredLate_firesOnce() async {
        // drain + last decrement both complete BEFORE setBackgroundCompletionHandler is called.
        // When the handler is stored, fireCompletionHandlerIfReady fires it immediately.
        let manager = makeMinimalManager()
        let (spy, count) = makeSpy()
        manager.incrementPendingCompletions()
        await manager.drainBackgroundSessionEvents()
        // Decrement to 0 (no handler yet).
        await manager.handleTaskCompletion(taskDescription: nil, statusCode: nil, error: nil)
        XCTAssertEqual(count(), 0, "No handler stored yet — must not have fired")
        // Handler arrives late.
        await manager.setBackgroundCompletionHandler(spy)
        XCTAssertEqual(count(), 1, "Handler must fire immediately on setBackgroundCompletionHandler when drain + count == 0")
    }

    func test_gate_secondRound_drainBeforeHandlerStore_firesOnce() async {
        // Regression test for the stranded-handler bug (scenario-a FAIL from the Step 0 analysis).
        //
        // Pre-fix behaviour (handlerFired-gated reset in setBackgroundCompletionHandler):
        //   After round 1 fires, handlerFired=true. Round 2's drain fires and count reaches 0
        //   before setBackgroundCompletionHandler is called (AppDelegate Task-hop-loses-the-race
        //   ordering). setBackgroundCompletionHandler sees handlerFired=true → resets
        //   drainObserved=false → handler is stranded, never fires. FAIL.
        //
        // Post-fix behaviour (drainObserved cleared in fireCompletionHandlerIfReady at fire-time):
        //   After round 1 fires, drainObserved=false (cleared at fire). Round 2's drain sets it
        //   to true; count reaches 0. setBackgroundCompletionHandler only clears handlerFired;
        //   drainObserved=true survives → fires immediately. PASS.
        let manager = makeMinimalManager()
        let (spy1, count1) = makeSpy()
        let (spy2, count2) = makeSpy()

        // ── Round 1: complete a full round so handlerFired=true ──────────────────────────────
        await manager.setBackgroundCompletionHandler(spy1)
        // No completions in round 1; drain arrives with count already 0.
        await manager.drainBackgroundSessionEvents()
        // spy1 must have fired (drain + count==0 + handler stored).
        XCTAssertEqual(count1(), 1, "Round 1: handler must fire when drain arrives with count==0")
        let fired1 = await manager._handlerFired
        let drain1 = await manager._drainObserved
        // Post-fix: after fire, drainObserved=false and handlerFired=true.
        XCTAssertTrue(fired1,  "Round 1: handlerFired must be true after handler fires")
        XCTAssertFalse(drain1, "Round 1: drainObserved must be false after handler fires (cleared at fire-time)")

        // ── Round 2: simulate the AppDelegate-Task-hop-loses-the-race ordering ───────────────
        // 1. Completions arrive and process.
        manager.incrementPendingCompletions()
        await manager.handleTaskCompletion(taskDescription: nil, statusCode: nil, error: nil)
        // 2. Drain fires (urlSessionDidFinishEvents delivered).
        await manager.drainBackgroundSessionEvents()
        // At this point: drainObserved=true, count=0, but NO handler stored yet.
        XCTAssertEqual(count2(), 0, "Round 2: handler must not have fired before setBackgroundCompletionHandler is called")
        // 3. AppDelegate Task hop finally executes — handler arrives late.
        await manager.setBackgroundCompletionHandler(spy2)
        // Must fire immediately because drain + count==0 pre-conditions are already met.
        XCTAssertEqual(count2(), 1, "Round 2: handler must fire immediately on setBackgroundCompletionHandler when drain + count already settled (handler-stored-late in second round)")
        // spy1 must not have been called again.
        XCTAssertEqual(count1(), 1, "Round 1 handler must not fire again in round 2")
    }

    // MARK: - Group C: BackgroundTaskHandle exactly-once semantics

    func test_backgroundTaskHandle_endCalledOnce_normalPath() async throws {
        // endIfNeeded called once → end action fires once.
        let callCount = OSAllocatedUnfairLock(initialState: 0)
        let handle = BackgroundTaskHandle { callCount.withLock { $0 += 1 } }
        handle.endIfNeeded()
        XCTAssertEqual(callCount.withLock { $0 }, 1)
    }

    func test_backgroundTaskHandle_endCalledOnce_doubleEnd() async throws {
        // endIfNeeded called twice → end action fires exactly once.
        let callCount = OSAllocatedUnfairLock(initialState: 0)
        let handle = BackgroundTaskHandle { callCount.withLock { $0 += 1 } }
        handle.endIfNeeded()
        handle.endIfNeeded()
        XCTAssertEqual(callCount.withLock { $0 }, 1, "Double endIfNeeded must fire end action exactly once")
    }

    func test_backgroundTaskHandle_concurrentEnd_exactlyOnce() async {
        // Two concurrent callers race to end; exactly one must win.
        let lock = OSAllocatedUnfairLock(initialState: 0)
        let handle = BackgroundTaskHandle { lock.withLock { $0 += 1 } }
        await withTaskGroup(of: Void.self) { group in
            group.addTask { handle.endIfNeeded() }
            group.addTask { handle.endIfNeeded() }
        }
        XCTAssertEqual(lock.withLock { $0 }, 1, "Concurrent endIfNeeded must fire exactly once")
    }

    func test_backgroundTaskHandle_endCalledAfterHandleTaskCompletion_200Path() async throws {
        // Pass a handle to handleTaskCompletion; defer must call endIfNeeded.
        let (manager, _, _) = try await makeManager(paths: ["frames/000000.jpg", "bundle.pb"])
        let lock = OSAllocatedUnfairLock(initialState: 0)
        let handle = BackgroundTaskHandle { lock.withLock { $0 += 1 } }
        manager.incrementPendingCompletions()
        await manager.handleTaskCompletion(
            taskDescription: taskDesc(relativePath: "frames/000000.jpg"),
            statusCode: 200, error: nil,
            backgroundTaskToken: handle
        )
        XCTAssertEqual(lock.withLock { $0 }, 1, "Defer must end background task on 200 path")
    }

    func test_backgroundTaskHandle_endCalledAfterHandleTaskCompletion_fatalPath() async throws {
        // 4xx path → onFatalBlobError (stub) → defer ends the task.
        let (manager, _, _) = try await makeManager(paths: ["frames/000000.jpg", "bundle.pb"])
        let lock = OSAllocatedUnfairLock(initialState: 0)
        let handle = BackgroundTaskHandle { lock.withLock { $0 += 1 } }
        manager.incrementPendingCompletions()
        await manager.handleTaskCompletion(
            taskDescription: taskDesc(relativePath: "frames/000000.jpg"),
            statusCode: 400, error: nil,
            backgroundTaskToken: handle
        )
        XCTAssertEqual(lock.withLock { $0 }, 1, "Defer must end background task on fatal (4xx) path")
    }

    func test_backgroundTaskHandle_endCalledAfterHandleTaskCompletion_malformedDesc() async throws {
        // Malformed taskDescription → early return → defer still ends the task.
        let manager = makeMinimalManager()
        let lock = OSAllocatedUnfairLock(initialState: 0)
        let handle = BackgroundTaskHandle { lock.withLock { $0 += 1 } }
        manager.incrementPendingCompletions()
        await manager.handleTaskCompletion(
            taskDescription: "malformed-no-pipe",
            statusCode: 200, error: nil,
            backgroundTaskToken: handle
        )
        XCTAssertEqual(lock.withLock { $0 }, 1, "Defer must end background task even on malformed-desc early return")
    }

    func test_backgroundTaskHandle_nilToken_noOp() async throws {
        // nil token: handleTaskCompletion must not crash and must still decrement counter.
        let (manager, _, _) = try await makeManager(paths: ["frames/000000.jpg", "bundle.pb"])
        manager.incrementPendingCompletions()
        await manager.handleTaskCompletion(
            taskDescription: taskDesc(relativePath: "frames/000000.jpg"),
            statusCode: 200, error: nil,
            backgroundTaskToken: nil
        )
        XCTAssertEqual(manager._pendingCompletionsCount, 0, "nil token must still decrement counter")
    }

    // MARK: - Idempotency hardening (unit c, decision 0045)

    // MARK: Latch: in-process double-enqueue prevention

    func test_latch_doubleOnAllBlobsUploaded_enqueuesBundlePbOnce() async throws {
        // Two sequential calls to onAllBlobsUploaded (fresh + in-flight) must produce exactly
        // one bundle.pb URLSession task via enqueueBundlePb. The in-process latch blocks
        // the second call since the first has already inserted the bundleId.
        let (manager, store, _) = try await makeManager(paths: ["frames/000000.jpg", "bundle.pb"])
        _ = try await store.markBlobUploaded(bundleId: "test-bundle", relativePath: "frames/000000.jpg")
        let record = try await store.load(bundleId: "test-bundle")!
        // Stub getAllTasks → [] so the cross-process check doesn't interfere.
        await manager.setGetAllTasksProvider { [] }

        await manager.onAllBlobsUploaded(bundleId: "test-bundle", record: record)
        await manager.onAllBlobsUploaded(bundleId: "test-bundle", record: record)

        let created = await manager._bundlePbTasksCreatedCount
        XCTAssertEqual(created, 1, "Latch must prevent second enqueueBundlePb from creating a task")
    }

    func test_latch_completedRecord_skipsBundlePbEnqueue() async throws {
        // If the persisted record already has uploadPhase == .complete, enqueueBundlePb
        // must be a no-op (terminal guard). Simulates the relaunch scenario where unit (a)
        // loads a completed record and (mistakenly) calls onAllBlobsUploaded.
        let (manager, store, outputDir) = try await makeManager(paths: ["frames/000000.jpg", "bundle.pb"])
        _ = try await store.markBlobUploaded(bundleId: "test-bundle", relativePath: "frames/000000.jpg")
        let record = try await store.load(bundleId: "test-bundle")!
        // Mark the record as complete in the store and in the local copy.
        let completedRecord = record.markingPhase(.complete)
        try await store.save(completedRecord)
        await manager.setGetAllTasksProvider { [] }

        await manager.onAllBlobsUploaded(bundleId: "test-bundle", record: completedRecord)

        let created = await manager._bundlePbTasksCreatedCount
        XCTAssertEqual(created, 0, "uploadPhase == .complete must skip enqueueBundlePb entirely")
        let fatal = await manager._fatalBlobErrorInvocations
        XCTAssertTrue(fatal.isEmpty, "Skipping a completed record must not call onFatalBlobError")
        _ = outputDir
    }

    // MARK: getAllTasks reconciliation

    func test_reconciliation_pendingBlobWithLiveTask_isNotReenqueued() async throws {
        // When getAllTasks returns a task whose description matches a pending blob,
        // enqueuePhasOneBlobs must skip that blob (not create a duplicate PUT task).
        let paths = ["frames/000000.jpg", "bundle.pb"]
        let (manager, store, _) = try await makeManager(paths: paths)
        let record = try await store.load(bundleId: "test-bundle")!

        // Simulate a live task for frames/000000.jpg.
        let fakeTask = URLSession.shared.dataTask(with: URL(string: "https://example.com")!)
        fakeTask.taskDescription = BlobUploadManager.makeTaskDescription(
            bundleId: "test-bundle", relativePath: "frames/000000.jpg"
        )
        await manager.setGetAllTasksProvider { [fakeTask] in [fakeTask] }

        try await manager.enqueuePhasOneBlobs(record: record)

        let enqueued = await manager._phase1BlobsEnqueuedCount
        XCTAssertEqual(enqueued, 0, "Pending blob with a live task must NOT be re-enqueued")
    }

    func test_reconciliation_orphanedPendingBlob_isEnqueued() async throws {
        // When getAllTasks returns [] (no live tasks), a pending blob IS enqueued.
        let paths = ["frames/000000.jpg", "bundle.pb"]
        let (manager, store, _) = try await makeManager(paths: paths)
        let record = try await store.load(bundleId: "test-bundle")!
        await manager.setGetAllTasksProvider { [] }

        try await manager.enqueuePhasOneBlobs(record: record)

        let enqueued = await manager._phase1BlobsEnqueuedCount
        XCTAssertEqual(enqueued, 1, "Orphaned pending blob (no live task) must be enqueued")
    }

    // MARK: Context preserve: second enqueuePhasOneBlobs must not zero retryCount/reputtedPaths

    func test_contextPreserve_secondEnqueueKeeps308ReputtedState() async throws {
        // Regression test for the unconditional `contexts[bundleId] = UploadContext()` overwrite.
        //
        // Protocol: (1) enqueuePhasOneBlobs creates context; (2) 308 → reputtedPaths gains entry;
        // (3) enqueuePhasOneBlobs again — with the fix, context is preserved; (4) second 308 for
        // the same path → "308_persistent" fatal (only possible if reputtedPaths was preserved).
        // Without the fix, context is zeroed in step 3 and step 4 treats it as a first 308.
        let paths = ["frames/000000.jpg", "bundle.pb"]
        let (manager, store, _) = try await makeManager(paths: paths)
        let record = try await store.load(bundleId: "test-bundle")!
        await manager.setGetAllTasksProvider { [] }

        // Step 1: create context.
        try await manager.enqueuePhasOneBlobs(record: record)

        // Step 2: first 308 → reputtedPaths gains "frames/000000.jpg".
        await manager.handleTaskCompletion(
            taskDescription: taskDesc(relativePath: "frames/000000.jpg"),
            statusCode: 308, error: nil
        )

        // Step 3: second enqueuePhasOneBlobs (simulates re-call e.g. from UploadCoordinator
        // on re-entry). With fix: context preserved. Without fix: context zeroed.
        try await manager.enqueuePhasOneBlobs(record: record)

        // Step 4: second 308 for the same path. If reputtedPaths is preserved → "308_persistent"
        // fatal. If context was zeroed → first-308 branch (re-PUT attempt, no fatal yet).
        await manager.handleTaskCompletion(
            taskDescription: taskDesc(relativePath: "frames/000000.jpg"),
            statusCode: 308, error: nil
        )

        let fatal = await manager._fatalBlobErrorInvocations
        let persistent308 = fatal.filter { $0.reason == "308_persistent" }
        XCTAssertFalse(persistent308.isEmpty,
                       "Context must be preserved across second enqueuePhasOneBlobs: second 308 must be '308_persistent'. Got: \(fatal.map(\.reason))")
    }

    // MARK: Phase persistence on bundle.pb success

    func test_phase_bundlePbSuccess_setsCompletePhaseInStore() async throws {
        // After bundle.pb PUT returns 200, the persisted record's uploadPhase must be .complete.
        let (manager, store, _) = try await makeManager(paths: ["frames/000000.jpg", "bundle.pb"])
        await manager.setGetAllTasksProvider { [] }

        // Simulate the full happy path: frame → gate → onAllBlobsUploaded → enqueueBundlePb → 200.
        await manager.handleTaskCompletion(
            taskDescription: taskDesc(relativePath: "frames/000000.jpg"),
            statusCode: 200, error: nil
        )
        await manager.handleTaskCompletion(
            taskDescription: taskDesc(relativePath: "bundle.pb"),
            statusCode: 200, error: nil
        )

        let record = try await store.load(bundleId: "test-bundle")
        XCTAssertEqual(record?.uploadPhase, .complete,
                       "bundle.pb 200 must persist uploadPhase == .complete")
        let completed = await manager._bundleCompleteInvocations
        XCTAssertEqual(completed, ["test-bundle"], "onBundleComplete must still be called")
    }

    func test_phase_bundlePbSuccess_doesNotChangeBlobStatuses() async throws {
        // Setting .complete phase must NOT alter blobStatuses (separate concern).
        let (manager, store, _) = try await makeManager(paths: ["frames/000000.jpg", "bundle.pb"])
        await manager.setGetAllTasksProvider { [] }

        await manager.handleTaskCompletion(
            taskDescription: taskDesc(relativePath: "frames/000000.jpg"),
            statusCode: 200, error: nil
        )
        await manager.handleTaskCompletion(
            taskDescription: taskDesc(relativePath: "bundle.pb"),
            statusCode: 200, error: nil
        )

        let record = try await store.load(bundleId: "test-bundle")
        XCTAssertEqual(record?.blobStatuses["bundle.pb"], .pending,
                       "Setting .complete phase must not alter bundle.pb blobStatus")
        XCTAssertEqual(record?.blobStatuses["frames/000000.jpg"], .uploaded,
                       "Frame blob status must remain .uploaded after bundle.pb success")
    }

    // MARK: - P5 unit (b): onFatalBlobError reclassification (decision 0045)

    // MARK: TERMINAL routing

    func test_400_terminal_marksFailedPhaseInStore() async throws {
        // 400 → TERMINAL → onFatalBlobError → uploadPhase == .failed persisted.
        let (manager, store, _) = try await makeManager(paths: ["frames/000000.jpg", "bundle.pb"])
        await manager.handleTaskCompletion(
            taskDescription: taskDesc(relativePath: "frames/000000.jpg"),
            statusCode: 400, error: nil
        )
        let record = try await store.load(bundleId: "test-bundle")!
        XCTAssertEqual(record.uploadPhase, .failed, "400 must mark bundle .failed")
        XCTAssertEqual(record.failureReason, "http_400", "failureReason must be set to http_400")
        let fatal = await manager._fatalBlobErrorInvocations
        XCTAssertFalse(fatal.isEmpty, "400 must route through onFatalBlobError")
    }

    func test_308persistent_terminal_marksFailedPhaseInStore() async throws {
        // 308_persistent → TERMINAL → .failed.
        let paths = ["frames/000000.jpg", "bundle.pb"]
        let (manager, store, _) = try await makeManager(paths: paths)
        await manager.setGetAllTasksProvider { [] }
        let record = try await store.load(bundleId: "test-bundle")!
        try await manager.enqueuePhasOneBlobs(record: record)

        // First 308 → reputtedPaths gains entry (no fatal yet).
        await manager.handleTaskCompletion(
            taskDescription: taskDesc(relativePath: "frames/000000.jpg"),
            statusCode: 308, error: nil
        )
        // Second 308 for same path → 308_persistent → TERMINAL.
        await manager.handleTaskCompletion(
            taskDescription: taskDesc(relativePath: "frames/000000.jpg"),
            statusCode: 308, error: nil
        )
        let stored = try await store.load(bundleId: "test-bundle")!
        XCTAssertEqual(stored.uploadPhase, .failed, "308_persistent must mark bundle .failed")
        let fatal = await manager._fatalBlobErrorInvocations
        XCTAssertTrue(fatal.contains { $0.reason == "308_persistent" },
                      "Reason must be 308_persistent; got: \(fatal.map(\.reason))")
    }

    func test_bundlePbReadFailed_terminal_marksFailedPhaseInStore() async throws {
        // bundle_pb_read_failed → TERMINAL → .failed.
        let storeDir = FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString)
        let store = UploadSessionStore(directory: storeDir)
        addTeardownBlock { try? FileManager.default.removeItem(at: storeDir) }

        let outputDir = FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString)
        addTeardownBlock { try? FileManager.default.removeItem(at: outputDir) }
        // Create frames blob but NOT bundle.pb — its absence causes resourceValues to throw.
        let framePath = outputDir.appendingPathComponent("frames/000000.jpg")
        try FileManager.default.createDirectory(at: framePath.deletingLastPathComponent(), withIntermediateDirectories: true)
        try Data([0x00]).write(to: framePath)

        let paths = ["frames/000000.jpg", "bundle.pb"]
        let entries = makeSessionEntries(paths)
        let record = UploadSessionRecord(
            bundleId: "test-bundle",
            tierRawValue: 1,
            clientMintTimestamp: Date(),
            sessionEntries: entries,
            manifestPaths: paths,
            outputDir: outputDir
        )
        _ = try await store.markBlobUploaded(bundleId: "test-bundle", relativePath: "frames/000000.jpg")
        // Save record with frame uploaded so the gate fires.
        let uploaded = record.markingBlobUploaded("frames/000000.jpg")
        try await store.save(uploaded)

        let manager = BlobUploadManager(store: store)
        await manager.setGetAllTasksProvider { [] }
        // Trigger onAllBlobsUploaded → enqueueBundlePb → resourceValues throws (file missing).
        await manager.onAllBlobsUploaded(bundleId: "test-bundle", record: uploaded)

        let stored = try await store.load(bundleId: "test-bundle")!
        XCTAssertEqual(stored.uploadPhase, .failed,
                       "bundle_pb_read_failed must mark bundle .failed")
        let fatal = await manager._fatalBlobErrorInvocations
        XCTAssertTrue(fatal.contains { $0.reason.hasPrefix("bundle_pb_read_failed") },
                      "Reason must start with bundle_pb_read_failed; got: \(fatal.map(\.reason))")
    }

    // MARK: TERMINAL → re-entry guard

    func test_terminal_reentryGuardDropsSubsequentCompletions() async throws {
        // After a fatal, subsequent handleTaskCompletion calls for the same bundle are
        // dropped by the re-entry guard (failedBundles set). Fatal count stays at 1.
        let (manager, store, _) = try await makeManager(
            paths: ["frames/000000.jpg", "frames/000001.jpg", "bundle.pb"]
        )
        // Fatal on first blob.
        await manager.handleTaskCompletion(
            taskDescription: taskDesc(relativePath: "frames/000000.jpg"),
            statusCode: 400, error: nil
        )
        let fatalCount1 = await manager._fatalBlobErrorInvocations.count
        XCTAssertEqual(fatalCount1, 1)

        // Subsequent completion for the same bundle → re-entry guard drops it.
        await manager.handleTaskCompletion(
            taskDescription: taskDesc(relativePath: "frames/000001.jpg"),
            statusCode: 200, error: nil
        )
        let fatalCount2 = await manager._fatalBlobErrorInvocations.count
        XCTAssertEqual(fatalCount2, 1, "Re-entry guard must not increase fatal count")

        // The second blob must NOT be marked uploaded (dropped before markBlobUploaded).
        let record = try await store.load(bundleId: "test-bundle")!
        XCTAssertEqual(record.blobStatuses["frames/000001.jpg"], .pending,
                       "Re-entry guard must prevent markBlobUploaded from running")
    }

    func test_terminal_reentryGuardDrop_drainCounterDecrement() async throws {
        // Re-entry guard drop must still decrement the drain counter (defer fires on return).
        let (manager, _, _) = try await makeManager(
            paths: ["frames/000000.jpg", "frames/000001.jpg", "bundle.pb"]
        )
        // Fatal.
        manager.incrementPendingCompletions()
        await manager.handleTaskCompletion(
            taskDescription: taskDesc(relativePath: "frames/000000.jpg"),
            statusCode: 400, error: nil
        )
        XCTAssertEqual(manager._pendingCompletionsCount, 0)

        // Simulate a cancelled-sibling completion arriving.
        manager.incrementPendingCompletions()
        let cancelErr = NSError(domain: NSURLErrorDomain, code: NSURLErrorCancelled)
        await manager.handleTaskCompletion(
            taskDescription: taskDesc(relativePath: "frames/000001.jpg"),
            statusCode: nil, error: cancelErr
        )
        XCTAssertEqual(manager._pendingCompletionsCount, 0,
                       "Re-entry guard return must still decrement drain counter")
    }

    // MARK: DEFERRED-INTERRUPTED: no-context re-routes (no counter, no .failed)

    func test_308noContext_deferredInterrupted_doesNotFatal_doesNotBumpCounter() async throws {
        // 308 arrives with no in-memory context (killed/relaunched process).
        // Must NOT route to onFatalBlobError; blob stays .pending; counter stays 0.
        let (manager, store, _) = try await makeManager(paths: ["frames/000000.jpg", "bundle.pb"])
        // Do NOT call enqueuePhasOneBlobs → contexts[bundleId] is nil.
        await manager.handleTaskCompletion(
            taskDescription: taskDesc(relativePath: "frames/000000.jpg"),
            statusCode: 308, error: nil
        )
        let record = try await store.load(bundleId: "test-bundle")!
        XCTAssertEqual(record.uploadPhase, .uploadingBlobs,
                       "308_no_context must NOT mark bundle .failed")
        XCTAssertEqual(record.crossLaunchRetryCount, 0,
                       "308_no_context must NOT bump crossLaunchRetryCount")
        let fatal = await manager._fatalBlobErrorInvocations
        XCTAssertTrue(fatal.isEmpty, "308_no_context must not route to onFatalBlobError")
    }

    func test_networkNoContext_deferredInterrupted_doesNotFatal_doesNotBumpCounter() async throws {
        // Network error with no context (killed/relaunched).
        // DEFERRED-INTERRUPTED: inline log, no counter, no .failed.
        let (manager, store, _) = try await makeManager(paths: ["frames/000000.jpg", "bundle.pb"])
        let err = NSError(domain: NSURLErrorDomain, code: NSURLErrorTimedOut)
        // No enqueuePhasOneBlobs → no context.
        await manager.handleTaskCompletion(
            taskDescription: taskDesc(relativePath: "frames/000000.jpg"),
            statusCode: nil, error: err
        )
        let record = try await store.load(bundleId: "test-bundle")!
        XCTAssertEqual(record.uploadPhase, .uploadingBlobs,
                       "network_no_context must NOT mark bundle .failed")
        XCTAssertEqual(record.crossLaunchRetryCount, 0,
                       "network_no_context must NOT bump crossLaunchRetryCount")
        let fatal = await manager._fatalBlobErrorInvocations
        XCTAssertTrue(fatal.isEmpty, "network_no_context must not route to onFatalBlobError")
    }

    // MARK: DEFERRED-TRANSIENT: counter bump (408, 429, exhausted, remint variants)

    // 408/429 route through the shared in-process retry schedule (same as 5xx), so
    // the DEFERRED-TRANSIENT counter bump now happens at exhaustion, not on first
    // sight, and a no-context completion is DEFERRED-INTERRUPTED like any other
    // transient. Retry-After honoring has its own section below.

    func test_408_noContext_deferredInterrupted_noBump_notFatal() async throws {
        // 408 with no in-memory context (killed/relaunched process) → DEFERRED-INTERRUPTED:
        // blob stays .pending, no counter bump, no fatal. Same classification as 5xx/network.
        let (manager, store, _) = try await makeManager(paths: ["frames/000000.jpg", "bundle.pb"])
        // No enqueuePhasOneBlobs → contexts[bundleId] is nil.
        await manager.handleTaskCompletion(
            taskDescription: taskDesc(relativePath: "frames/000000.jpg"),
            statusCode: 408, error: nil
        )
        let record = try await store.load(bundleId: "test-bundle")!
        XCTAssertEqual(record.uploadPhase, .uploadingBlobs, "408_no_context must NOT mark bundle .failed")
        XCTAssertEqual(record.crossLaunchRetryCount, 0,
                       "408_no_context must NOT bump crossLaunchRetryCount (relaunch artifact, not a failure)")
        let fatal = await manager._fatalBlobErrorInvocations
        XCTAssertTrue(fatal.isEmpty, "408_no_context must not route to onFatalBlobError")
    }

    func test_429_noContext_deferredInterrupted_noBump_notFatal() async throws {
        // 429 with no context → DEFERRED-INTERRUPTED, same as the 408 case above.
        let (manager, store, _) = try await makeManager(paths: ["frames/000000.jpg", "bundle.pb"])
        await manager.handleTaskCompletion(
            taskDescription: taskDesc(relativePath: "frames/000000.jpg"),
            statusCode: 429, error: nil
        )
        let record = try await store.load(bundleId: "test-bundle")!
        XCTAssertEqual(record.uploadPhase, .uploadingBlobs, "429_no_context must NOT mark bundle .failed")
        XCTAssertEqual(record.crossLaunchRetryCount, 0,
                       "429_no_context must NOT bump crossLaunchRetryCount")
        let fatal = await manager._fatalBlobErrorInvocations
        XCTAssertTrue(fatal.isEmpty, "429_no_context must not route to onFatalBlobError")
    }

    func test_429_withContext_retriesInProcess_thenDefersTransient_neverFatal() async throws {
        // The terminal-failure invariant, preserved at its new position: a persistent 429 is never
        // fatal — it exhausts the in-process schedule (maxRetries sleeps), then defers
        // cross-launch with exactly one counter bump.
        let paths = ["frames/000000.jpg", "bundle.pb"]
        let (manager, store, _) = try await makeManager(paths: paths)
        await manager.setGetAllTasksProvider { [] }
        let sleeps = OSAllocatedUnfairLock<[TimeInterval]>(initialState: [])
        await manager.setSleeper { delay in sleeps.withLock { $0.append(delay) } }
        let record = try await store.load(bundleId: "test-bundle")!
        try await manager.enqueuePhasOneBlobs(record: record)

        for _ in 0...BlobUploadManager.maxRetries {
            await manager.handleTaskCompletion(
                taskDescription: taskDesc(relativePath: "frames/000000.jpg"),
                statusCode: 429, error: nil
            )
        }

        XCTAssertEqual(sleeps.withLock { $0 }.count, BlobUploadManager.maxRetries,
                       "429 must sleep once per in-process retry attempt")
        let stored = try await store.load(bundleId: "test-bundle")!
        XCTAssertEqual(stored.uploadPhase, .uploadingBlobs, "Exhausted 429 must NOT mark bundle .failed")
        XCTAssertEqual(stored.crossLaunchRetryCount, 1,
                       "Exhausted 429 must bump crossLaunchRetryCount exactly once")
        let fatal = await manager._fatalBlobErrorInvocations
        XCTAssertTrue(fatal.isEmpty, "429 must route to deferred at exhaustion, never fatal")
    }

    // MARK: Retry-After honoring (GCS-side; distinct from decision 0038's /upload_session item)

    /// Context + fast sleeper + record loaded — shared setup for the schedule tests.
    private func makeRetryScheduleFixture(
        clock: @escaping () -> Date = { Date() }
    ) async throws -> (BlobUploadManager, UploadSessionStore, OSAllocatedUnfairLock<[TimeInterval]>) {
        let (manager, store, _) = try await makeManager(
            paths: ["frames/000000.jpg", "bundle.pb"], clock: clock
        )
        await manager.setGetAllTasksProvider { [] }
        let sleeps = OSAllocatedUnfairLock<[TimeInterval]>(initialState: [])
        await manager.setSleeper { delay in sleeps.withLock { $0.append(delay) } }
        let record = try await store.load(bundleId: "test-bundle")!
        try await manager.enqueuePhasOneBlobs(record: record)
        return (manager, store, sleeps)
    }

    func test_429_retryAfterSeconds_delayHonored() async throws {
        // Retry-After: 7 → the retry sleeps [7, 8) (stated wait + jitter < 1),
        // overriding the exponential schedule (which would be [1, 2) on attempt 0).
        let (manager, store, sleeps) = try await makeRetryScheduleFixture()
        await manager.handleTaskCompletion(
            taskDescription: taskDesc(relativePath: "frames/000000.jpg"),
            statusCode: 429, error: nil, retryAfterHeader: "7"
        )
        let recorded = sleeps.withLock { $0 }
        XCTAssertEqual(recorded.count, 1, "One retry sleep expected")
        XCTAssertGreaterThanOrEqual(recorded[0], 7, "Delay must be at least the server-stated wait")
        XCTAssertLessThan(recorded[0], 8, "Delay must be stated wait + jitter (< 1s)")
        let record = try await store.load(bundleId: "test-bundle")!
        XCTAssertEqual(record.blobStatuses["frames/000000.jpg"], .pending,
                       "Blob stays .pending across an in-process retry")
        XCTAssertEqual(record.crossLaunchRetryCount, 0,
                       "In-process retry must not spend the cross-launch budget")
        let fatal = await manager._fatalBlobErrorInvocations
        XCTAssertTrue(fatal.isEmpty, "Honored Retry-After must not fatal")
    }

    func test_408_retryAfterAboveLocalMax_stillHonoredInFull() async throws {
        // Retry-After: 45 exceeds the local maxDelaySec (30) but is within the hold cap
        // (60) — the server's statement overrides the local schedule and is slept in full.
        let (manager, _, sleeps) = try await makeRetryScheduleFixture()
        await manager.handleTaskCompletion(
            taskDescription: taskDesc(relativePath: "frames/000000.jpg"),
            statusCode: 408, error: nil, retryAfterHeader: "45"
        )
        let recorded = sleeps.withLock { $0 }
        XCTAssertEqual(recorded.count, 1)
        XCTAssertGreaterThanOrEqual(recorded[0], 45,
                                    "Server-stated wait above maxDelaySec must not be clamped down")
        XCTAssertLessThan(recorded[0], 46)
    }

    func test_429_noRetryAfterHeader_usesExponentialBackoff() async throws {
        // Without the header, the shared schedule applies: attempt 0 sleeps [1, 2).
        let (manager, _, sleeps) = try await makeRetryScheduleFixture()
        await manager.handleTaskCompletion(
            taskDescription: taskDesc(relativePath: "frames/000000.jpg"),
            statusCode: 429, error: nil
        )
        let recorded = sleeps.withLock { $0 }
        XCTAssertEqual(recorded.count, 1)
        XCTAssertGreaterThanOrEqual(recorded[0], 1, "Attempt 0 backoff is baseDelaySec + jitter")
        XCTAssertLessThan(recorded[0], 2)
    }

    func test_429_retryAfterHTTPDate_delayComputedFromInjectedClock() async throws {
        // HTTP-date form, resolved against the injected clock: a date 20s ahead of
        // "now" sleeps [20, 21).
        let fixedNow = Date(timeIntervalSince1970: 1_445_412_460)  // 2015-10-21 07:27:40 GMT
        let (manager, _, sleeps) = try await makeRetryScheduleFixture(clock: { fixedNow })
        await manager.handleTaskCompletion(
            taskDescription: taskDesc(relativePath: "frames/000000.jpg"),
            statusCode: 429, error: nil,
            retryAfterHeader: "Wed, 21 Oct 2015 07:28:00 GMT"
        )
        let recorded = sleeps.withLock { $0 }
        XCTAssertEqual(recorded.count, 1)
        XCTAssertGreaterThanOrEqual(recorded[0], 20)
        XCTAssertLessThan(recorded[0], 21)
    }

    func test_429_retryAfterExceedsHoldCap_defersTransient_withoutSleeping() async throws {
        // Retry-After: 3600 — never retry earlier than the server asked, and never hold
        // the completion chain for an hour: DEFERRED-TRANSIENT immediately, zero sleeps.
        let (manager, store, sleeps) = try await makeRetryScheduleFixture()
        await manager.handleTaskCompletion(
            taskDescription: taskDesc(relativePath: "frames/000000.jpg"),
            statusCode: 429, error: nil, retryAfterHeader: "3600"
        )
        XCTAssertTrue(sleeps.withLock { $0 }.isEmpty,
                      "Beyond the hold cap there must be no in-process sleep")
        let record = try await store.load(bundleId: "test-bundle")!
        XCTAssertEqual(record.uploadPhase, .uploadingBlobs, "Hold-cap deferral must NOT mark .failed")
        XCTAssertEqual(record.blobStatuses["frames/000000.jpg"], .pending)
        XCTAssertEqual(record.crossLaunchRetryCount, 1,
                       "Hold-cap deferral is DEFERRED-TRANSIENT: one counter bump")
        let fatal = await manager._fatalBlobErrorInvocations
        XCTAssertTrue(fatal.isEmpty, "Hold-cap deferral must not fatal")
    }

    func test_503_retryAfterSeconds_delayHonored() async throws {
        // The honoring mechanism is shared with the 5xx path (503 commonly carries
        // Retry-After): stated wait 40 > maxDelaySec sleeps in full.
        let (manager, _, sleeps) = try await makeRetryScheduleFixture()
        await manager.handleTaskCompletion(
            taskDescription: taskDesc(relativePath: "frames/000000.jpg"),
            statusCode: 503, error: nil, retryAfterHeader: "40"
        )
        let recorded = sleeps.withLock { $0 }
        XCTAssertEqual(recorded.count, 1)
        XCTAssertGreaterThanOrEqual(recorded[0], 40)
        XCTAssertLessThan(recorded[0], 41)
    }

    // Retry-After parsing moved to RetryAfterTests when the mint path became its
    // second consumer (decision 0038's follow-up). The blob manager's HONORING of
    // a parsed value is still pinned above; only the parser itself relocated.

    func test_networkExhausted_deferredTransient_bumpsCounter_notFatal() async throws {
        // network_exhausted (in-process maxRetries exhausted) → DEFERRED-TRANSIENT.
        // Requires a context to exist (enqueuePhasOneBlobs) and maxRetries failures.
        let paths = ["frames/000000.jpg", "bundle.pb"]
        let (manager, store, _) = try await makeManager(paths: paths)
        await manager.setGetAllTasksProvider { [] }
        let record = try await store.load(bundleId: "test-bundle")!
        try await manager.enqueuePhasOneBlobs(record: record)

        let err = NSError(domain: NSURLErrorDomain, code: NSURLErrorTimedOut)
        // Drive maxRetries network failures → on the (maxRetries+1)th error, routes deferred.
        for _ in 0...BlobUploadManager.maxRetries {
            await manager.handleTaskCompletion(
                taskDescription: taskDesc(relativePath: "frames/000000.jpg"),
                statusCode: nil, error: err
            )
        }
        let stored = try await store.load(bundleId: "test-bundle")!
        XCTAssertEqual(stored.uploadPhase, .uploadingBlobs,
                       "network_exhausted must NOT mark bundle .failed")
        XCTAssertEqual(stored.crossLaunchRetryCount, 1,
                       "network_exhausted must bump crossLaunchRetryCount to 1")
        let fatal = await manager._fatalBlobErrorInvocations
        XCTAssertTrue(fatal.isEmpty, "network_exhausted must route to deferred, not fatal")
    }

    // MARK: Per-launch idempotent bump

    func test_transient_perLaunchIdempotentBump_sameBundle_countsOnce() async throws {
        // Two remint_failed events in the same launch for the same bundle.
        // crossLaunchRetryCount must advance exactly once (per-launch idempotent bump).
        let (manager, store, _) = try await makeManager(paths: ["frames/000000.jpg", "bundle.pb"])
        await manager.setRemintProvider { _, _ in
            throw UploadSessionError.serverError(503, "unavailable")
        }

        // First onSessionExpired → remint_failed → deferTransient → count 0→1.
        await manager.onSessionExpired(bundleId: "test-bundle")
        let after1 = try await store.load(bundleId: "test-bundle")!
        XCTAssertEqual(after1.crossLaunchRetryCount, 1,
                       "First transient in launch must bump count to 1")

        // Second onSessionExpired → remint_failed → transientCountedThisLaunch hit → no bump.
        await manager.onSessionExpired(bundleId: "test-bundle")
        let after2 = try await store.load(bundleId: "test-bundle")!
        XCTAssertEqual(after2.crossLaunchRetryCount, 1,
                       "Second same-launch transient must NOT bump count (idempotent)")
        let fatal = await manager._fatalBlobErrorInvocations
        XCTAssertTrue(fatal.isEmpty, "Idempotent deferred must not route to fatal")
    }

    func test_transient_progressResetsCountedSet_allowsRebump() async throws {
        // Blob success resets crossLaunchRetryCount (via markingBlobUploaded → 0) AND
        // clears transientCountedThisLaunch. A subsequent transient in the same launch can re-count.
        let paths = ["frames/000000.jpg", "frames/000001.jpg", "bundle.pb"]
        let (manager, store, _) = try await makeManager(paths: paths)
        await manager.setRemintProvider { _, _ in
            throw UploadSessionError.serverError(503, "unavailable")
        }

        // Transient deferral → count 0→1, bundle is in transientCountedThisLaunch.
        await manager.onSessionExpired(bundleId: "test-bundle")
        let afterDefer = try await store.load(bundleId: "test-bundle")!
        XCTAssertEqual(afterDefer.crossLaunchRetryCount, 1, "Pre-condition: count must be 1")

        // Blob success → count reset to 0, transientCountedThisLaunch cleared.
        await manager.handleTaskCompletion(
            taskDescription: taskDesc(relativePath: "frames/000000.jpg"),
            statusCode: 200, error: nil
        )
        let afterSuccess = try await store.load(bundleId: "test-bundle")!
        XCTAssertEqual(afterSuccess.crossLaunchRetryCount, 0,
                       "Blob success must reset crossLaunchRetryCount to 0")

        // Now another transient in the same launch → counted-set was cleared → can re-count.
        await manager.onSessionExpired(bundleId: "test-bundle")
        let afterRebump = try await store.load(bundleId: "test-bundle")!
        XCTAssertEqual(afterRebump.crossLaunchRetryCount, 1,
                       "After progress reset, transient can re-count in same launch (→ 1)")
    }

    // MARK: Counter bound → escalate to fatal

    func test_transient_atBound_escalatesToFatal() async throws {
        // Record starts at crossLaunchRetryCount == maxCrossLaunchRetries (10).
        // Next transient → newCount == 11 > 10 → escalates to onFatalBlobError → .failed.
        let storeDir = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        let store = UploadSessionStore(directory: storeDir)
        addTeardownBlock { try? FileManager.default.removeItem(at: storeDir) }

        let outputDir = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        addTeardownBlock { try? FileManager.default.removeItem(at: outputDir) }
        let paths = ["frames/000000.jpg", "bundle.pb"]
        for path in paths {
            let fileURL = outputDir.appendingPathComponent(path)
            try FileManager.default.createDirectory(at: fileURL.deletingLastPathComponent(), withIntermediateDirectories: true)
            try Data([0x00, 0x01]).write(to: fileURL)
        }
        let entries = makeSessionEntries(paths)
        var record = UploadSessionRecord(
            bundleId: "test-bundle",
            tierRawValue: 1,
            clientMintTimestamp: Date(),
            sessionEntries: entries,
            manifestPaths: paths,
            outputDir: outputDir
        )
        // Bump to exactly the bound.
        for _ in 0..<BlobUploadManager.maxCrossLaunchRetries {
            record = record.bumpingCrossLaunchRetryCount()
        }
        XCTAssertEqual(record.crossLaunchRetryCount, BlobUploadManager.maxCrossLaunchRetries,
                       "Pre-condition: count must equal bound")
        try await store.save(record)

        // Fresh manager (new process — no transientCountedThisLaunch entry for this bundle).
        let manager = BlobUploadManager(store: store)
        await manager.setRemintProvider { _, _ in
            throw UploadSessionError.serverError(503, "unavailable")
        }

        // Transient: newCount = maxCrossLaunchRetries + 1 > max → escalate to fatal.
        await manager.onSessionExpired(bundleId: "test-bundle")

        let stored = try await store.load(bundleId: "test-bundle")!
        XCTAssertEqual(stored.uploadPhase, .failed,
                       "Transient at bound must escalate and mark bundle .failed")
        let fatal = await manager._fatalBlobErrorInvocations
        XCTAssertFalse(fatal.isEmpty, "Transient at bound must route through onFatalBlobError")
    }

    func test_transient_atBoundMinusOne_defers_notTerminal() async throws {
        // Record at maxCrossLaunchRetries - 1 → next transient bumps to max (deferred, not fatal).
        let storeDir = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        let store = UploadSessionStore(directory: storeDir)
        addTeardownBlock { try? FileManager.default.removeItem(at: storeDir) }

        let outputDir = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        addTeardownBlock { try? FileManager.default.removeItem(at: outputDir) }
        let paths = ["frames/000000.jpg", "bundle.pb"]
        for path in paths {
            let fileURL = outputDir.appendingPathComponent(path)
            try FileManager.default.createDirectory(at: fileURL.deletingLastPathComponent(), withIntermediateDirectories: true)
            try Data([0x00, 0x01]).write(to: fileURL)
        }
        let entries = makeSessionEntries(paths)
        var record = UploadSessionRecord(
            bundleId: "test-bundle",
            tierRawValue: 1,
            clientMintTimestamp: Date(),
            sessionEntries: entries,
            manifestPaths: paths,
            outputDir: outputDir
        )
        // Bump to bound - 1.
        for _ in 0..<(BlobUploadManager.maxCrossLaunchRetries - 1) {
            record = record.bumpingCrossLaunchRetryCount()
        }
        try await store.save(record)

        let manager = BlobUploadManager(store: store)
        await manager.setRemintProvider { _, _ in
            throw UploadSessionError.serverError(503, "unavailable")
        }

        // Transient: newCount = max (still within bound) → deferred, NOT fatal.
        await manager.onSessionExpired(bundleId: "test-bundle")

        let stored = try await store.load(bundleId: "test-bundle")!
        XCTAssertEqual(stored.crossLaunchRetryCount, BlobUploadManager.maxCrossLaunchRetries,
                       "Count at bound-1 → bump to bound (deferred)")
        XCTAssertNotEqual(stored.uploadPhase, .failed,
                          "Count at bound-1 must defer, not escalate to fatal")
        let fatal = await manager._fatalBlobErrorInvocations
        XCTAssertTrue(fatal.isEmpty,
                      "Count at bound-1 → deferred, not fatal")
    }

    // MARK: Counter reset on progress

    func test_progressResetsCounter() async throws {
        // After a blob upload succeeds, crossLaunchRetryCount is reset to 0
        // via markingBlobUploaded (which passes crossLaunchRetryCount: 0 to the private init).
        let (manager, store, _) = try await makeManager(
            paths: ["frames/000000.jpg", "frames/000001.jpg", "bundle.pb"]
        )

        // Plant count == 3 in the store.
        var record = try await store.load(bundleId: "test-bundle")!
        for _ in 0..<3 { record = record.bumpingCrossLaunchRetryCount() }
        try await store.save(record)

        // Blob 200 → markBlobUploaded → crossLaunchRetryCount reset to 0.
        await manager.handleTaskCompletion(
            taskDescription: taskDesc(relativePath: "frames/000000.jpg"),
            statusCode: 200, error: nil
        )
        let after = try await store.load(bundleId: "test-bundle")!
        XCTAssertEqual(after.crossLaunchRetryCount, 0,
                       "Blob success must reset crossLaunchRetryCount to 0")
        XCTAssertEqual(after.blobStatuses["frames/000000.jpg"], .uploaded,
                       "Blob status must be .uploaded after success")
    }

    // MARK: - Launch-time rehydration (P5 unit a, decision 0045)

    // MARK: rehydrateBundle: phase-skip guard

    func test_rehydrate_failedRecord_isSkipped() async throws {
        // uploadPhase == .failed → rehydrateBundle is a no-op.
        // No enqueuePhasOneBlobs, no onAllBlobsUploaded, no onFatalBlobError.
        let (manager, store, _) = try await makeManager(paths: ["frames/000000.jpg", "bundle.pb"])
        let failed = try await store.load(bundleId: "test-bundle")!
            .markingPhase(.failed, failureReason: "http_400")
        try await store.save(failed)

        await manager.rehydrateBundle(bundleId: "test-bundle", record: failed)

        let fatal = await manager._fatalBlobErrorInvocations
        let pbCreated = await manager._bundlePbTasksCreatedCount
        let p1Enqueued = await manager._phase1BlobsEnqueuedCount
        XCTAssertTrue(fatal.isEmpty, ".failed record must not call onFatalBlobError")
        XCTAssertEqual(pbCreated, 0, ".failed record must not enqueue bundle.pb")
        XCTAssertEqual(p1Enqueued, 0, ".failed record must not enqueue Phase-1 blobs")
    }

    func test_rehydrate_completeRecord_isSkipped() async throws {
        // uploadPhase == .complete → rehydrateBundle is a no-op.
        let (manager, store, _) = try await makeManager(paths: ["frames/000000.jpg", "bundle.pb"])
        let completed = try await store.load(bundleId: "test-bundle")!.markingPhase(.complete)
        try await store.save(completed)

        await manager.rehydrateBundle(bundleId: "test-bundle", record: completed)

        let fatal = await manager._fatalBlobErrorInvocations
        let pbCreated = await manager._bundlePbTasksCreatedCount
        let p1Enqueued = await manager._phase1BlobsEnqueuedCount
        XCTAssertTrue(fatal.isEmpty, ".complete record must not call onFatalBlobError")
        XCTAssertEqual(pbCreated, 0, ".complete record must not enqueue bundle.pb")
        XCTAssertEqual(p1Enqueued, 0, ".complete record must not enqueue Phase-1 blobs")
    }

    // MARK: rehydrateBundle: Phase-2 path

    func test_rehydrate_phase2_bundlePbPresent_enqueuesBundlePb() async throws {
        // allNonBundlePbBlobsUploaded == true, bundle.pb file present →
        // routes to onAllBlobsUploaded → enqueueBundlePb → _bundlePbTasksCreatedCount == 1.
        let paths = ["frames/000000.jpg", "bundle.pb"]
        let (manager, store, _) = try await makeManager(paths: paths)
        _ = try await store.markBlobUploaded(bundleId: "test-bundle",
                                             relativePath: "frames/000000.jpg")
        let record = try await store.load(bundleId: "test-bundle")!
        XCTAssertTrue(record.allNonBundlePbBlobsUploaded, "Pre-condition: gate must be true")
        await manager.setGetAllTasksProvider { [] }

        await manager.rehydrateBundle(bundleId: "test-bundle", record: record)

        let pbCreated = await manager._bundlePbTasksCreatedCount
        let fatal = await manager._fatalBlobErrorInvocations
        XCTAssertEqual(pbCreated, 1,
                       "Phase-2 rehydrate with bundle.pb present must enqueue bundle.pb PUT")
        XCTAssertTrue(fatal.isEmpty, "Phase-2 with all files present must not fatal")
    }

    func test_rehydrate_phase2_bundlePbMissing_callsFatal() async throws {
        // allNonBundlePbBlobsUploaded == true, bundle.pb file absent →
        // onFatalBlobError("missing_bundle_pb_at_relaunch").
        let paths = ["frames/000000.jpg", "bundle.pb"]
        let (manager, store, outputDir) = try await makeManager(paths: paths)
        _ = try await store.markBlobUploaded(bundleId: "test-bundle",
                                             relativePath: "frames/000000.jpg")
        let record = try await store.load(bundleId: "test-bundle")!
        try FileManager.default.removeItem(at: outputDir.appendingPathComponent("bundle.pb"))

        await manager.rehydrateBundle(bundleId: "test-bundle", record: record)

        let fatal = await manager._fatalBlobErrorInvocations
        let pbCreated = await manager._bundlePbTasksCreatedCount
        XCTAssertFalse(fatal.isEmpty, "Missing bundle.pb must call onFatalBlobError")
        XCTAssertTrue(
            fatal.allSatisfy { $0.reason == "missing_bundle_pb_at_relaunch" },
            "Reason must be missing_bundle_pb_at_relaunch; got: \(fatal.map(\.reason))"
        )
        XCTAssertEqual(pbCreated, 0, "bundle.pb PUT must not be enqueued when file is missing")
    }

    // MARK: rehydrateBundle: Phase-1 path

    func test_rehydrate_phase1_allBlobsPresent_enqueuesBlobs() async throws {
        // allNonBundlePbBlobsUploaded == false, all blob files present →
        // enqueuePhasOneBlobs enqueues blobs; _phase1BlobsEnqueuedCount == 2.
        let paths = ["frames/000000.jpg", "frames/000001.jpg", "bundle.pb"]
        let (manager, store, _) = try await makeManager(paths: paths)
        let record = try await store.load(bundleId: "test-bundle")!
        XCTAssertFalse(record.allNonBundlePbBlobsUploaded, "Pre-condition: gate must be false")
        await manager.setGetAllTasksProvider { [] }

        await manager.rehydrateBundle(bundleId: "test-bundle", record: record)

        let p1Enqueued = await manager._phase1BlobsEnqueuedCount
        let fatal = await manager._fatalBlobErrorInvocations
        XCTAssertEqual(p1Enqueued, 2, "Phase-1 rehydrate must enqueue all pending blobs")
        XCTAssertTrue(fatal.isEmpty, "Phase-1 with all files present must not fatal")
    }

    func test_rehydrate_phase1_missingBlob_callsFatal_noPartialEnqueue() async throws {
        // Phase-1 path: one pending blob file missing on disk (S0b finding) →
        // onFatalBlobError("missing_blob_at_relaunch"). Pre-check fires before enqueuePhasOneBlobs;
        // zero blobs must be enqueued (no partial-enqueue strand).
        let paths = ["frames/000000.jpg", "bundle.pb"]
        let (manager, store, outputDir) = try await makeManager(paths: paths)
        let record = try await store.load(bundleId: "test-bundle")!
        try FileManager.default.removeItem(
            at: outputDir.appendingPathComponent("frames/000000.jpg"))

        await manager.rehydrateBundle(bundleId: "test-bundle", record: record)

        let fatal = await manager._fatalBlobErrorInvocations
        let p1Enqueued = await manager._phase1BlobsEnqueuedCount
        XCTAssertFalse(fatal.isEmpty, "Missing Phase-1 blob must call onFatalBlobError")
        XCTAssertTrue(
            fatal.allSatisfy { $0.reason == "missing_blob_at_relaunch" },
            "Reason must be missing_blob_at_relaunch; got: \(fatal.map(\.reason))"
        )
        XCTAssertEqual(p1Enqueued, 0, "Pre-check abort must produce zero enqueued blobs")
    }

    func test_rehydrate_phase1_missingBlob_persistsFailed_andSkippedOnSecondRehydrate() async throws {
        // Closes the store-write leg of the missing-blob terminalization chain (R4b gap):
        //   1. rehydrateBundle with a missing Phase-1 blob fires onFatalBlobError and enqueues nothing.
        //   2. onFatalBlobError persists uploadPhase == .failed to the store (previously only implied).
        //   3. A second rehydrateBundle call with the reloaded .failed record is a no-op — terminal
        //      across launches, not re-stranded on each open.
        let paths = ["frames/000000.jpg", "bundle.pb"]
        let (manager, store, outputDir) = try await makeManager(paths: paths)
        let record = try await store.load(bundleId: "test-bundle")!
        try FileManager.default.removeItem(
            at: outputDir.appendingPathComponent("frames/000000.jpg"))

        // Act 1: rehydrate with the missing blob on disk.
        await manager.rehydrateBundle(bundleId: "test-bundle", record: record)

        // Assert 1: onFatalBlobError fired, no partial enqueue — mirrors existing missingBlob test.
        let fatalAfterAct1 = await manager._fatalBlobErrorInvocations
        let p1EnqueuedAfterAct1 = await manager._phase1BlobsEnqueuedCount
        XCTAssertFalse(fatalAfterAct1.isEmpty, "Missing Phase-1 blob must call onFatalBlobError")
        XCTAssertTrue(
            fatalAfterAct1.allSatisfy { $0.reason == "missing_blob_at_relaunch" },
            "Reason must be missing_blob_at_relaunch; got: \(fatalAfterAct1.map(\.reason))"
        )
        XCTAssertEqual(p1EnqueuedAfterAct1, 0, "Pre-check abort must produce zero enqueued blobs")

        // Assert 2 (THE GAP): the store-write leg — onFatalBlobError must have persisted .failed.
        let storedRecord = try await store.load(bundleId: "test-bundle")
        XCTAssertEqual(storedRecord?.uploadPhase, .failed,
                       "onFatalBlobError must persist uploadPhase == .failed to the store")
        XCTAssertEqual(storedRecord?.failureReason, "missing_blob_at_relaunch",
                       "onFatalBlobError must persist the failure reason to the store")

        // Act 2: rehydrate again with the now-.failed record (simulates next-launch reopen).
        let reloadedRecord = try XCTUnwrap(storedRecord, "Store must contain a record after fatal")
        let fatalCountBeforeAct2 = fatalAfterAct1.count
        await manager.rehydrateBundle(bundleId: "test-bundle", record: reloadedRecord)

        // Assert 3: top guard skipped the .failed record — no new fatal, no new enqueue.
        let fatalAfterAct2 = await manager._fatalBlobErrorInvocations
        let p1EnqueuedAfterAct2 = await manager._phase1BlobsEnqueuedCount
        XCTAssertEqual(fatalAfterAct2.count, fatalCountBeforeAct2,
                       ".failed record must not trigger a second onFatalBlobError call")
        XCTAssertEqual(p1EnqueuedAfterAct2, 0,
                       ".failed record must not enqueue any Phase-1 blobs")
    }

    func test_rehydrate_doubleTrigger_noDoubleEnqueue() async throws {
        // Two rehydrateBundle calls (simulating double trigger: .task + AppDelegate belt-and-suspenders).
        // Second call must skip all blobs whose tasks are already live (getAllTasks reconciliation).
        let paths = ["frames/000000.jpg", "bundle.pb"]
        let (manager, store, _) = try await makeManager(paths: paths)
        let record = try await store.load(bundleId: "test-bundle")!

        // First call: no live tasks → blob is enqueued.
        await manager.setGetAllTasksProvider { [] }
        await manager.rehydrateBundle(bundleId: "test-bundle", record: record)
        let firstEnqueued = await manager._phase1BlobsEnqueuedCount
        XCTAssertEqual(firstEnqueued, 1,
                       "Pre-condition: first rehydrate must enqueue the blob")

        // Second call: live task for the blob → reconciliation skips it.
        let fakeTask = URLSession.shared.dataTask(with: URL(string: "https://example.com")!)
        fakeTask.taskDescription = BlobUploadManager.makeTaskDescription(
            bundleId: "test-bundle", relativePath: "frames/000000.jpg"
        )
        await manager.setGetAllTasksProvider { [fakeTask] }
        await manager.rehydrateBundle(bundleId: "test-bundle", record: record)

        let secondEnqueued = await manager._phase1BlobsEnqueuedCount
        let fatal = await manager._fatalBlobErrorInvocations
        XCTAssertEqual(secondEnqueued, 0,
                       "Double-trigger: second rehydrate must not re-enqueue blob with a live task")
        XCTAssertTrue(fatal.isEmpty, "Double-trigger rehydrate must not fatal")
    }

    // MARK: rehydrateAllUnfinishedBundles

    func test_rehydrateAll_skipsFailedBundle_processesActiveBundle() async throws {
        // Two records: one .failed (skipped), one .uploadingBlobs (processed).
        let storeDir = FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString)
        let store = UploadSessionStore(directory: storeDir)
        addTeardownBlock { try? FileManager.default.removeItem(at: storeDir) }

        // Active bundle with real files.
        let activeId = "00000000-0000-0000-0000-000000000001"
        let outputDir = FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString)
        addTeardownBlock { try? FileManager.default.removeItem(at: outputDir) }
        for path in ["frames/000000.jpg", "bundle.pb"] {
            let fileURL = outputDir.appendingPathComponent(path)
            try FileManager.default.createDirectory(at: fileURL.deletingLastPathComponent(),
                                                    withIntermediateDirectories: true)
            try Data([0x00, 0x01]).write(to: fileURL)
        }
        let activeRecord = UploadSessionRecord(
            bundleId: activeId, tierRawValue: 1, clientMintTimestamp: Date(),
            sessionEntries: makeSessionEntries(["frames/000000.jpg", "bundle.pb"]),
            manifestPaths: ["frames/000000.jpg", "bundle.pb"],
            outputDir: outputDir
        )
        try await store.save(activeRecord)

        // Failed bundle (no real files needed — skipped before any file check).
        let failedId = "00000000-0000-0000-0000-000000000002"
        let failedRecord = UploadSessionRecord(
            bundleId: failedId, tierRawValue: 1, clientMintTimestamp: Date(),
            sessionEntries: makeSessionEntries(["frames/000000.jpg", "bundle.pb"]),
            manifestPaths: ["frames/000000.jpg", "bundle.pb"],
            outputDir: FileManager.default.temporaryDirectory
        ).markingPhase(.failed, failureReason: "http_400")
        try await store.save(failedRecord)

        let manager = BlobUploadManager(store: store)
        await manager.setGetAllTasksProvider { [] }
        await manager.rehydrateAllUnfinishedBundles()

        let p1Enqueued = await manager._phase1BlobsEnqueuedCount
        let fatal = await manager._fatalBlobErrorInvocations
        XCTAssertGreaterThan(p1Enqueued, 0,
                             "Active bundle must have Phase-1 blobs enqueued")
        XCTAssertTrue(fatal.filter { $0.bundleId == activeId }.isEmpty,
                      "Active bundle must not fatal during rehydration")
    }

    func test_rehydrateAll_loadFailure_silentSkip_doesNotFatal() async throws {
        // One record has corrupted JSON (simulating CAFUFA-locked read → load returns nil).
        // One record is valid and .uploadingBlobs.
        // Corrupted bundle: silently skipped (no onFatalBlobError, no state mutation).
        // Valid bundle: processed normally.
        let storeDir = FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString)
        let store = UploadSessionStore(directory: storeDir)
        addTeardownBlock { try? FileManager.default.removeItem(at: storeDir) }

        // Valid bundle with real files.
        let validId = "00000000-0000-0000-0000-000000000001"
        let outputDir = FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString)
        addTeardownBlock { try? FileManager.default.removeItem(at: outputDir) }
        for path in ["frames/000000.jpg", "bundle.pb"] {
            let fileURL = outputDir.appendingPathComponent(path)
            try FileManager.default.createDirectory(at: fileURL.deletingLastPathComponent(),
                                                    withIntermediateDirectories: true)
            try Data([0x00, 0x01]).write(to: fileURL)
        }
        let validRecord = UploadSessionRecord(
            bundleId: validId, tierRawValue: 1, clientMintTimestamp: Date(),
            sessionEntries: makeSessionEntries(["frames/000000.jpg", "bundle.pb"]),
            manifestPaths: ["frames/000000.jpg", "bundle.pb"],
            outputDir: outputDir
        )
        try await store.save(validRecord)

        // Corrupted record: write invalid JSON with a UUID filename directly to the store dir.
        // allBundleIds() returns this ID; store.load() throws on decode; try? returns nil.
        let corruptId = "00000000-0000-0000-0000-000000000002"
        try Data("not valid json".utf8).write(
            to: storeDir.appendingPathComponent("\(corruptId).json")
        )

        let manager = BlobUploadManager(store: store)
        await manager.setGetAllTasksProvider { [] }
        await manager.rehydrateAllUnfinishedBundles()

        let fatal = await manager._fatalBlobErrorInvocations
        let p1Enqueued = await manager._phase1BlobsEnqueuedCount
        // Corrupted bundle must produce no fatal.
        XCTAssertTrue(fatal.filter { $0.bundleId == corruptId }.isEmpty,
                      "Load failure must be silently skipped, not routed to onFatalBlobError")
        // Valid bundle must have been processed.
        XCTAssertGreaterThan(p1Enqueued, 0,
                             "Valid bundle must be processed even when a peer record fails to load")
    }

}

// MARK: - BlobUploadManager test helpers

extension BlobUploadManager {
    /// Convenience for tests: set remintProvider from a @MainActor context.
    ///
    /// Two-argument shim over the real three-argument seam. Kept deliberately:
    /// every pre-0116 test here asserts something that has nothing to do with
    /// force_remint, and rewriting ~20 call sites to add an ignored `_` would
    /// have churned pins whose meaning must not change. Tests that care about
    /// the flag use setRemintProviderObservingForce below.
    func setRemintProvider(
        _ provider: @escaping @Sendable (String, [UploadManifestEntry]) async throws -> [UploadSessionEntry]
    ) {
        remintProvider = { bundleId, manifest, _ in try await provider(bundleId, manifest) }
    }

    /// Convenience for tests that assert WHETHER force_remint was set.
    func setRemintProviderObservingForce(
        _ provider: @escaping @Sendable (String, [UploadManifestEntry], Bool) async throws -> [UploadSessionEntry]
    ) {
        remintProvider = provider
    }

    /// Convenience for tests: inject a getAllTasks stub for reconciliation tests.
    func setGetAllTasksProvider(_ provider: @escaping @Sendable () async -> [URLSessionTask]) {
        getAllTasksProvider = provider
    }

    /// Convenience for tests: inject a sleep recorder so retry-schedule tests assert
    /// the computed delay (including Retry-After honoring) without real waiting.
    func setSleeper(_ sleeper: @escaping @Sendable (TimeInterval) async -> Void) {
        self.sleeper = sleeper
    }
}
