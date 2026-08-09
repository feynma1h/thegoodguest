/// Tests for `resendMissingBlobs` — decision 0084's re-upload coordinator,
/// un-blocked by decision 0116's force_remint.
///
/// A `failed_incomplete` scene names the paths that never reached GCS. Those
/// blobs are re-minted with force_remint (their stored sessions are consumed or
/// swept) and re-sent, and bundle.pb follows LAST through the EXISTING Phase-1
/// gate — decision 0040's ordering invariant is consumed here, never
/// re-implemented, and one of the tests below drives that end to end.
///
/// The 410 loop guard's own forced re-mint lives in ForcedRemintTests.
///
/// Strategy matches BlobUploadManagerTests: drive `handleTaskCompletion`
/// directly and read effects out of the store, so the whole completion pipeline
/// runs with no network. The injected `remintProvider` here is the
/// force-observing variant — WHETHER the flag was set is the property under
/// test, not an implementation detail.

import XCTest
@testable import RoomStudioCapture

@MainActor
final class RecoveryResendTests: XCTestCase {

    // MARK: - Fixture

    /// A capture in the state `failed_incomplete` actually finds it: the client
    /// uploaded everything it could, finalized, and the record is `.complete`.
    private func makeManager(
        bundleId: String = "test-bundle",
        paths: [String],
        phase: UploadPhase = .complete
    ) async throws -> (BlobUploadManager, UploadSessionStore, URL) {
        let storeDir = FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString)
        let store = UploadSessionStore(directory: storeDir)
        addTeardownBlock { try? FileManager.default.removeItem(at: storeDir) }

        let outputDir = FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString)
        addTeardownBlock { try? FileManager.default.removeItem(at: outputDir) }
        for path in paths {
            let fileURL = outputDir.appendingPathComponent(path)
            try FileManager.default.createDirectory(
                at: fileURL.deletingLastPathComponent(), withIntermediateDirectories: true)
            try Data([0x00, 0x01]).write(to: fileURL)
        }

        let entries = paths.map {
            UploadSessionEntry(relativePath: $0, sessionUri: "https://gcs.example.com/old/\($0)")
        }
        var record = UploadSessionRecord(
            bundleId: bundleId, tierRawValue: 1, clientMintTimestamp: Date(),
            sessionEntries: entries, manifestPaths: paths, outputDir: outputDir)
        for path in paths { record = record.markingBlobUploaded(path) }
        record = record.markingPhase(phase)
        try await store.save(record)

        return (BlobUploadManager(store: store), store, outputDir)
    }

    private let manifest = ["frames/000000.jpg", "frames/000001.jpg", "bundle.pb"]

    // MARK: - resendMissingBlobs: the happy path

    func test_resend_mintsOnlyTheMissingPathsPlusBundlePb_withForceSet() async throws {
        let (manager, _, _) = try await makeManager(paths: manifest)
        let seen = Recorder()
        await manager.setRemintProviderObservingForce { _, entries, force in
            await seen.record(paths: entries.map(\.relativePath), force: force)
            return entries.map { UploadSessionEntry(relativePath: $0.relativePath,
                                                    sessionUri: "https://gcs.example.com/FRESH/\($0.relativePath)") }
        }

        let outcome = await manager.resendMissingBlobs(
            bundleId: "test-bundle", missingPaths: ["frames/000001.jpg"])

        XCTAssertEqual(outcome, .started(blobs: 1))
        let calls = await seen.calls
        XCTAssertEqual(calls.count, 1, "one mint per re-send")
        // A SUBSET, not the whole manifest: re-minting ~2,000 sessions to fix
        // one file is the thing the subset exists to avoid.
        XCTAssertEqual(calls.first?.paths, ["frames/000001.jpg", "bundle.pb"])
        XCTAssertEqual(calls.first?.force, true,
                       "a failed_incomplete scene IS the evidence force_remint asks for")
    }

    /// Real sizes, read from disk — never a fabricated 0. GCS enforces the
    /// declared length the session was minted against, so a wrong size makes the
    /// PUT fail at the far end where nothing can explain it.
    func test_resend_sendsRealPerBlobSizes() async throws {
        let (manager, _, outputDir) = try await makeManager(paths: manifest)
        try Data(repeating: 0xAB, count: 4096).write(
            to: outputDir.appendingPathComponent("frames/000001.jpg"))
        let seen = Recorder()
        await manager.setRemintProviderObservingForce { _, entries, _ in
            await seen.record(sizes: Dictionary(uniqueKeysWithValues:
                entries.map { ($0.relativePath, $0.expectedSizeBytes) }))
            return freshEntries(entries.map(\.relativePath))
        }

        _ = await manager.resendMissingBlobs(
            bundleId: "test-bundle", missingPaths: ["frames/000001.jpg"])

        let sizes = await seen.sizes
        XCTAssertEqual(sizes["frames/000001.jpg"], 4096)
        XCTAssertEqual(sizes["bundle.pb"], 2, "the stub bundle.pb is 2 bytes")
    }

    /// The record after a re-send: fresh URIs merged in for the re-minted paths,
    /// OLD URIs preserved for everything else, and only the re-sent paths back
    /// to .pending. Replacing the entry list wholesale (as the 410 path does)
    /// would drop every path not re-minted and with it the gate's knowledge of
    /// what is already up.
    func test_resend_mergesFreshURIsAndResetsOnlyTheResentPaths() async throws {
        let (manager, store, _) = try await makeManager(paths: manifest)
        await manager.setRemintProviderObservingForce { _, entries, _ in
            freshEntries(entries.map(\.relativePath))
        }

        _ = await manager.resendMissingBlobs(
            bundleId: "test-bundle", missingPaths: ["frames/000001.jpg"])

        let record = try await store.load(bundleId: "test-bundle")!
        XCTAssertEqual(record.sessionUri(for: "frames/000001.jpg"),
                       "https://gcs.example.com/FRESH/frames/000001.jpg")
        XCTAssertEqual(record.sessionUri(for: "bundle.pb"),
                       "https://gcs.example.com/FRESH/bundle.pb")
        XCTAssertEqual(record.sessionUri(for: "frames/000000.jpg"),
                       "https://gcs.example.com/old/frames/000000.jpg",
                       "a path that was not re-minted keeps its entry")
        XCTAssertEqual(record.blobStatuses["frames/000001.jpg"], .pending)
        XCTAssertEqual(record.blobStatuses["bundle.pb"], .pending)
        XCTAssertEqual(record.blobStatuses["frames/000000.jpg"], .uploaded,
                       "a blob that DID land must not be sent again")
        XCTAssertEqual(record.manifestPaths, manifest,
                       "the capture's full path-set survives a subset re-mint")
    }

    /// THE PHASE RESET. After a completed upload the record is `.complete`, and
    /// `enqueueBundlePb` refuses to enqueue for a `.complete` record — so
    /// without this the re-sent blobs would land and the finalize would never
    /// follow. That is the exact silent strand this path exists to avoid.
    func test_resend_movesThePhaseBackOffComplete() async throws {
        let (manager, store, _) = try await makeManager(paths: manifest, phase: .complete)
        await manager.setRemintProviderObservingForce { _, entries, _ in
            freshEntries(entries.map(\.relativePath))
        }

        _ = await manager.resendMissingBlobs(
            bundleId: "test-bundle", missingPaths: ["frames/000001.jpg"])

        let record = try await store.load(bundleId: "test-bundle")!
        XCTAssertEqual(record.uploadPhase, .uploadingBlobs)
        XCTAssertFalse(record.allNonBundlePbBlobsUploaded,
                       "the Phase-1 gate must re-open, or bundle.pb never re-fires")
    }

    // MARK: - The ordering guarantee (decision 0040), end to end

    /// The whole point of routing the re-send through `enqueuePhasOneBlobs`:
    /// bundle.pb-last is the machinery's own invariant and is not
    /// re-implemented here. Drive the resent blob to 200 and the finalize must
    /// appear — and not one moment earlier.
    func test_resend_sendsBundlePbLast_viaTheExistingPhase1Gate() async throws {
        let paths = ["frames/000000.jpg", "frames/000001.jpg", "bundle.pb"]
        let (manager, store, _) = try await makeManager(paths: paths)
        await manager.setRemintProviderObservingForce { _, entries, _ in
            freshEntries(entries.map(\.relativePath))
        }

        _ = await manager.resendMissingBlobs(
            bundleId: "test-bundle", missingPaths: ["frames/000000.jpg", "frames/000001.jpg"])

        // Two blobs enqueued, bundle.pb NOT among them.
        let enqueued = await manager._phase1BlobsEnqueuedCount
        XCTAssertEqual(enqueued, 2)
        var created = await manager._bundlePbTasksCreatedCount
        XCTAssertEqual(created, 0, "bundle.pb must not be enqueued before the gate closes")

        // First blob lands: still not the finalize.
        await manager.handleTaskCompletion(
            taskDescription: BlobUploadManager.makeTaskDescription(
                bundleId: "test-bundle", relativePath: "frames/000000.jpg"),
            statusCode: 200, error: nil)
        created = await manager._bundlePbTasksCreatedCount
        XCTAssertEqual(created, 0, "one of two blobs is not the gate")

        // Second blob lands: the gate closes and the finalize goes.
        await manager.handleTaskCompletion(
            taskDescription: BlobUploadManager.makeTaskDescription(
                bundleId: "test-bundle", relativePath: "frames/000001.jpg"),
            statusCode: 200, error: nil)
        created = await manager._bundlePbTasksCreatedCount
        XCTAssertEqual(created, 1, "the finalize follows the last blob, automatically")

        let record = try await store.load(bundleId: "test-bundle")!
        XCTAssertEqual(record.uploadPhase, .uploadingBundlePb)
    }

    /// And the round completes: bundle.pb's 200 marks the record complete again
    /// and re-notifies, which is what re-triggers ingest server-side.
    func test_resend_completesTheBundleAgainWhenBundlePbLands() async throws {
        let (manager, store, _) = try await makeManager(paths: manifest)
        await manager.setRemintProviderObservingForce { _, entries, _ in
            freshEntries(entries.map(\.relativePath))
        }
        _ = await manager.resendMissingBlobs(
            bundleId: "test-bundle", missingPaths: ["frames/000001.jpg"])

        for path in ["frames/000001.jpg", "bundle.pb"] {
            await manager.handleTaskCompletion(
                taskDescription: BlobUploadManager.makeTaskDescription(
                    bundleId: "test-bundle", relativePath: path),
                statusCode: 200, error: nil)
        }

        let completed = await manager._bundleCompleteInvocations
        XCTAssertEqual(completed, ["test-bundle"])
        let record = try await store.load(bundleId: "test-bundle")!
        XCTAssertEqual(record.uploadPhase, .complete)
    }

    // MARK: - resendMissingBlobs: refusals and failures

    /// The plan's refusal reaches the caller intact, and NOTHING is changed —
    /// no mint, no store write. The screen falls back to the rescan copy.
    func test_resend_refusesWhenAFileIsGone_andTouchesNothing() async throws {
        let (manager, store, outputDir) = try await makeManager(paths: manifest)
        try FileManager.default.removeItem(at: outputDir.appendingPathComponent("frames/000001.jpg"))
        let seen = Recorder()
        await manager.setRemintProviderObservingForce { _, entries, force in
            await seen.record(paths: entries.map(\.relativePath), force: force)
            return freshEntries(entries.map(\.relativePath))
        }

        let outcome = await manager.resendMissingBlobs(
            bundleId: "test-bundle", missingPaths: ["frames/000001.jpg"])

        XCTAssertEqual(outcome, .refused(.filesGone(["frames/000001.jpg"])))
        let calls = await seen.calls
        XCTAssertTrue(calls.isEmpty, "a refused plan must not spend a mint")
        let record = try await store.load(bundleId: "test-bundle")!
        XCTAssertEqual(record.uploadPhase, .complete, "the record is untouched")
    }

    func test_resend_refusesWhenTheServerNamedNoPaths() async throws {
        let (manager, _, _) = try await makeManager(paths: manifest)
        await manager.setRemintProviderObservingForce { _, entries, _ in
            freshEntries(entries.map(\.relativePath))
        }
        let outcome = await manager.resendMissingBlobs(bundleId: "test-bundle", missingPaths: [])
        XCTAssertEqual(outcome, .refused(.serverNamedNoPaths))
    }

    /// A mint failure is NOT a terminal failure of the bundle: the files are
    /// still here and the offer stands. It must not mark the record `.failed`,
    /// which would send the flow to the upload-failed screen for a capture that
    /// is merely one network hiccup from finishing.
    func test_resend_mintFailureIsRecoverable_notFatal() async throws {
        let (manager, store, _) = try await makeManager(paths: manifest)
        await manager.setRemintProviderObservingForce { _, _, _ in
            throw UploadSessionError.serverError(503, "unavailable")
        }

        let outcome = await manager.resendMissingBlobs(
            bundleId: "test-bundle", missingPaths: ["frames/000001.jpg"])

        guard case .failed = outcome else { return XCTFail("expected .failed, got \(outcome)") }
        let fatal = await manager._fatalBlobErrorInvocations
        XCTAssertTrue(fatal.isEmpty, "a failed re-send attempt must not fatal the bundle")
        let record = try await store.load(bundleId: "test-bundle")!
        XCTAssertEqual(record.uploadPhase, .complete, "unchanged: nothing was re-sent")
    }

    func test_resend_withNoRecord_failsWithoutCrashing() async throws {
        let (manager, _, _) = try await makeManager(paths: manifest)
        let outcome = await manager.resendMissingBlobs(
            bundleId: "no-such-bundle", missingPaths: ["frames/000001.jpg"])
        XCTAssertEqual(outcome, .failed("no_record"))
    }

    /// A re-send is a DELIBERATE restart, so it must clear the in-memory debris
    /// a previous attempt left: a lingering `failedBundles` entry would drop
    /// every completion for the blobs it just enqueued, stranding the capture
    /// with no terminal state at all.
    func test_resend_clearsAPriorFatalSoCompletionsAreNotDropped() async throws {
        let (manager, store, _) = try await makeManager(paths: manifest)
        await manager.onFatalBlobError(bundleId: "test-bundle", relativePath: "*", reason: "http_500")
        await manager.setRemintProviderObservingForce { _, entries, _ in
            freshEntries(entries.map(\.relativePath))
        }

        _ = await manager.resendMissingBlobs(
            bundleId: "test-bundle", missingPaths: ["frames/000001.jpg"])
        await manager.handleTaskCompletion(
            taskDescription: BlobUploadManager.makeTaskDescription(
                bundleId: "test-bundle", relativePath: "frames/000001.jpg"),
            statusCode: 200, error: nil)

        let record = try await store.load(bundleId: "test-bundle")!
        XCTAssertEqual(record.blobStatuses["frames/000001.jpg"], .uploaded,
                       "the completion was dropped by a stale re-entry guard")
    }
}

// MARK: - Stub helpers

/// Session entries a forced re-mint would hand back. Free function (not a
/// method) so the injected @Sendable provider closures can call it without
/// hopping to the MainActor-isolated test case.
private func freshEntries(_ paths: [String]) -> [UploadSessionEntry] {
    paths.map { UploadSessionEntry(relativePath: $0, sessionUri: "https://gcs.example.com/FRESH/\($0)") }
}

// MARK: - Recorder

/// Captures what the injected remint provider was asked for, across actor hops.
private actor Recorder {
    struct Call: Equatable { let paths: [String]; let force: Bool }
    private(set) var calls: [Call] = []
    private(set) var sizes: [String: Int] = [:]

    func record(paths: [String], force: Bool) {
        calls.append(Call(paths: paths, force: force))
    }
    func record(sizes: [String: Int]) {
        self.sizes = sizes
    }
}
