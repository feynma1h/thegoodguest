/// Pins the forced re-mint on the 410 loop guard — decision 0049 item 1's named
/// un-defer trigger, taken once decision 0116 gave the mint contract a second
/// input.
///
/// THE CONDITION. A blob PUT returns 410 (GCS has declared that resumable
/// session dead), the client re-mints, and the server answers with the SAME
/// URIs. It is not misbehaving: the path-set is its idempotency key, and a
/// path-set cannot say "the grant you gave me is dead". Before force_remint the
/// only safe response was a terminal `.failed`, because re-enqueueing against
/// URIs known to be dead loops on 410 forever.
///
/// Now the client says it explicitly and gets live sessions. The fatal stays as
/// the floor — reached only after a genuine forced attempt also replays.
///
/// Strategy matches BlobUploadManagerTests: drive the actor directly, no network.

import XCTest
@testable import TheGoodGuestCapture

@MainActor
final class ForcedRemintTests: XCTestCase {

    private let manifest = ["frames/000000.jpg", "frames/000001.jpg", "bundle.pb"]

    /// A record mid-upload (blobs pending), which is the state a 410 arrives in.
    private func makeManager(
        paths: [String], mintTimestamp: Date = Date()
    ) async throws -> (BlobUploadManager, UploadSessionStore) {
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

        try await store.save(UploadSessionRecord(
            bundleId: "test-bundle", tierRawValue: 1, clientMintTimestamp: mintTimestamp,
            sessionEntries: paths.map {
                UploadSessionEntry(relativePath: $0, sessionUri: "https://gcs.example.com/old/\($0)")
            },
            manifestPaths: paths, outputDir: outputDir))
        return (BlobUploadManager(store: store), store)
    }

    /// The un-defer trigger, taken. A server that REPLAYS the stored URIs is
    /// answering the wrong question — the path-set cannot say "these are dead" —
    /// so the client says it with force_remint and gets live sessions.
    func test_loopGuard_retriesOnceWithForce_andProceedsOnFreshURIs() async throws {
        let (manager, store) = try await makeManager(paths: manifest)
        let seen = ForceRecorder()
        await manager.setRemintProviderObservingForce { _, entries, force in
            await seen.record(force: force)
            // Replay on the ordinary mint; genuinely fresh once forced — the
            // production behaviour decision 0116 built.
            return force
                ? forcedFreshEntries(entries.map(\.relativePath))
                : forcedReplayedEntries(entries.map(\.relativePath))
        }

        await manager.onSessionExpired(bundleId: "test-bundle")

        let calls = await seen.calls
        XCTAssertEqual(calls.map(\.force), [false, true],
                       "the forced mint must follow the replay, not replace it")
        let fatal = await manager._fatalBlobErrorInvocations
        XCTAssertTrue(fatal.isEmpty, "fresh URIs are a recovery, not a failure: \(fatal.map(\.reason))")
        let record = try await store.load(bundleId: "test-bundle")!
        XCTAssertEqual(record.sessionUri(for: "frames/000000.jpg"),
                       "https://gcs.example.com/FRESH/frames/000000.jpg")
    }

    /// EXACTLY ONCE. The flag's effect is deterministic: a server that still
    /// replays after being told the sessions are dead will replay again, and
    /// each attempt spends a unit of the daily mint quota. The terminal
    /// `.failed` keeps decision 0049's reason string — it is the same condition
    /// that note named, now reached only after a genuine force attempt.
    func test_loopGuard_stillFatalsIfTheForcedMintAlsoReplays() async throws {
        let (manager, _) = try await makeManager(paths: manifest)
        let seen = ForceRecorder()
        await manager.setRemintProviderObservingForce { _, entries, force in
            await seen.record(force: force)
            return forcedReplayedEntries(entries.map(\.relativePath))
        }

        await manager.onSessionExpired(bundleId: "test-bundle")

        let calls = await seen.calls
        XCTAssertEqual(calls.count, 2, "one ordinary mint, one forced — never a ladder")
        let fatal = await manager._fatalBlobErrorInvocations
        XCTAssertEqual(fatal.map(\.reason), ["remint_returned_stale_uris"])
    }

    /// A transient failure of the FORCED mint defers like any other network
    /// failure. Fatal is reserved for the server answering and still replaying —
    /// a 503 on the second call says nothing about the sessions.
    func test_loopGuard_forcedMintNetworkFailureDefers_ratherThanFatals() async throws {
        let (manager, store) = try await makeManager(paths: manifest)
        await manager.setRemintProviderObservingForce { _, entries, force in
            if force { throw UploadSessionError.serverError(503, "unavailable") }
            return forcedReplayedEntries(entries.map(\.relativePath))
        }

        await manager.onSessionExpired(bundleId: "test-bundle")

        let fatal = await manager._fatalBlobErrorInvocations
        XCTAssertTrue(fatal.isEmpty, "got: \(fatal.map(\.reason))")
        let record = try await store.load(bundleId: "test-bundle")!
        XCTAssertNotEqual(record.uploadPhase, .failed)
        XCTAssertEqual(record.crossLaunchRetryCount, 1, "deferred to the next launch")
    }

    /// The STALENESS path (loopGuardEnabled: false) must never force. At 12 h
    /// the stored URIs are still live and identical IS the correct answer, so a
    /// forced mint would spend quota to replace working sessions — and, worse,
    /// invalidate the ones the already-uploaded blobs were written against.
    func test_stalenessRemint_neverForces() async throws {
        let (manager, _) = try await makeManager(
            paths: manifest, mintTimestamp: Date().addingTimeInterval(-(12 * 3600 + 60)))
        let seen = ForceRecorder()
        await manager.setRemintProviderObservingForce { _, entries, force in
            await seen.record(force: force)
            return forcedReplayedEntries(entries.map(\.relativePath))
        }

        // The staleness caller's own semantics: identical URIs are SUCCESS here.
        await manager.onSessionExpired(bundleId: "test-bundle", loopGuardEnabled: false)

        let calls = await seen.calls
        XCTAssertEqual(calls.map(\.force), [false],
                       "identical URIs are correct on the staleness path — never forced")
        let fatal = await manager._fatalBlobErrorInvocations
        XCTAssertTrue(fatal.isEmpty, "got: \(fatal.map(\.reason))")
    }
}

// MARK: - Stub helpers

/// Session entries a forced re-mint would hand back.
private func forcedFreshEntries(_ paths: [String]) -> [UploadSessionEntry] {
    paths.map { UploadSessionEntry(relativePath: $0, sessionUri: "https://gcs.example.com/FRESH/\($0)") }
}

/// Session entries identical to the stored ones — a server REPLAY.
private func forcedReplayedEntries(_ paths: [String]) -> [UploadSessionEntry] {
    paths.map { UploadSessionEntry(relativePath: $0, sessionUri: "https://gcs.example.com/old/\($0)") }
}

/// Captures what the injected remint provider was asked for, across actor hops.
private actor ForceRecorder {
    struct Call: Equatable { let force: Bool }
    private(set) var calls: [Call] = []
    func record(force: Bool) { calls.append(Call(force: force)) }
}
