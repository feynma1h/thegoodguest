/// Background URLSession manager for Phase-1 and Phase-2 blob uploads (P4, decision 0040).
///
/// One shared instance per app. A single background URLSession (identifier:
/// BlobUploadManager.backgroundSessionIdentifier) persists across app suspension
/// and kill. On a relaunch triggered by pending background events, accessing
/// BlobUploadManager.shared re-attaches to the same session and the delegate
/// starts receiving completions.
///
/// Public API:
///   enqueuePhasOneBlobs(record:)   — create one PUT task per non-bundle.pb blob
///   handleTaskCompletion(taskDescription:statusCode:error:) — called by BlobUploadDelegate;
///       also the entry point for unit tests (call directly, bypassing URLSession)
///   setBackgroundCompletionHandler(_:) — called by the AppDelegate background-session hook
///
/// Injectable dependencies (set after init for production, or via testing init):
///   remintProvider  — called by onSessionExpired to re-POST /upload_session.
///                     Wraps UploadSessionClient + AuthManager in production.
///                     Tests inject a stub. Nil → routes to onFatalBlobError.
///   clock           — returns "now"; default Date.init. Inject a fixed Date in tests
///                     for deterministic staleness-guard behavior (Step 2, decision 0041).
///
/// Task description format:
///   "\(bundleId)|\(relativePath)"
///   Stable across kill/relaunch per Apple docs ("The system preserves this property even
///   after you restart the app"). taskIdentifier is ephemeral — a new Int is assigned per
///   session instance. NEVER use taskIdentifier for cross-launch association.
///
/// Unbuilt seams (Chat-scoped future units):
///   onFatalBlobError(bundleId:relativePath:reason:) — surface error to UI / FCM
///
/// AppDelegate hook (not yet wired — requires @UIApplicationDelegateAdaptor):
///   application(_:handleEventsForBackgroundURLSession:completionHandler:)
///   → Task { await BlobUploadManager.shared.setBackgroundCompletionHandler(handler) }
///
/// Decisions: 0040, 0041

import Foundation

// MARK: - UploadContext

/// In-memory state for one active bundle upload.
/// Created at enqueuePhasOneBlobs time; not persisted.
/// Cold-relaunch correctness: outputDir is now stored in UploadSessionRecord.outputDir,
/// not here, so all file-path reconstruction works from the on-disk record alone.
private struct UploadContext: Sendable {
    /// App-level retry count per relative path (mirrors 0038 policy).
    /// The OS handles transport retries; this counts re-enqueues after OS gives up.
    var retryCount: [String: Int] = [:]
    /// Paths that have already received one re-PUT after a 308 response.
    /// A second 308 on the same path is persistent → fatal.
    var reputtedPaths: Set<String> = []
}

// MARK: - BlobUploadManager

actor BlobUploadManager {

    // MARK: - Singleton

    static let shared = BlobUploadManager()

    // MARK: - Constants

    static let backgroundSessionIdentifier = "com.roomstudio.capture.blobUpload"
    static let maxRetries = 3
    /// Sessions older than this threshold may have had early blobs GC'd by the
    /// age=1 lifecycle rule. Re-mint rather than finalizing against absent blobs.
    static let stalenessThreshold: TimeInterval = 12 * 3600

    private static let baseDelaySec: TimeInterval = 1.0   // mirrors 0038
    private static let maxDelaySec:  TimeInterval = 30.0

    // MARK: - Stored properties

    private let session: URLSession
    let store: UploadSessionStore                     // internal (not private) for tests
    private var contexts: [String: UploadContext] = [:]

    /// Set by the AppDelegate background-session hook; called in urlSessionDidFinishEvents.
    var backgroundSessionCompletionHandler: (() -> Void)?

    // MARK: - Injectable dependencies

    /// Returns "now". Inject a fixed Date in tests for deterministic staleness-guard behavior.
    var clock: () -> Date = { Date() }

    /// Called by onSessionExpired to re-POST /upload_session.
    /// Receives (bundleId, manifestEntries) and returns fresh [UploadSessionEntry].
    /// Production: wrap UploadSessionClient.shared.createUploadSession + AuthManager.shared.
    /// Tests: inject a stub that returns predetermined entries or throws.
    /// Nil means "not wired" — routes to onFatalBlobError.
    var remintProvider: (@Sendable (String, [UploadManifestEntry]) async throws -> [UploadSessionEntry])?

    // MARK: - Test observability

    /// Populated by onSessionExpired. Tests read via await to confirm routing.
    var _sessionExpiredInvocations: [String] = []
    /// Populated by onBundleComplete. Tests read via await to confirm routing.
    var _bundleCompleteInvocations: [String] = []
    /// Populated by onFatalBlobError. Tests read via await to confirm routing.
    var _fatalBlobErrorInvocations: [(bundleId: String, relativePath: String, reason: String)] = []

    // MARK: - Init

    /// Production singleton: creates the background URLSession.
    private init() {
        let del = BlobUploadDelegate()
        let cfg = URLSessionConfiguration.background(
            withIdentifier: Self.backgroundSessionIdentifier
        )
        cfg.sessionSendsLaunchEvents = true   // relaunch app to deliver completions
        cfg.isDiscretionary          = false  // upload promptly, not in low-power window
        cfg.allowsCellularAccess     = true
        self.store   = .shared
        self.session = URLSession(configuration: cfg, delegate: del, delegateQueue: nil)
    }

    /// Testing init: accepts injected store, URLSession, and clock.
    /// Call handleTaskCompletion directly in tests — no network required.
    init(
        store: UploadSessionStore,
        session: URLSession = URLSession(configuration: .ephemeral),
        clock: @escaping () -> Date = { Date() }
    ) {
        self.store   = store
        self.session = session
        self.clock   = clock
    }

    // MARK: - Background session lifecycle

    func setBackgroundCompletionHandler(_ handler: @escaping () -> Void) {
        backgroundSessionCompletionHandler = handler
    }

    /// Called by BlobUploadDelegate.urlSessionDidFinishEvents(forBackgroundURLSession:).
    /// Invokes the stored completion handler so the system can suspend the app.
    func drainBackgroundSessionEvents() {
        backgroundSessionCompletionHandler?()
        backgroundSessionCompletionHandler = nil
    }

    // MARK: - Task description encoding (stable across kill/relaunch)

    /// Encode bundleId and relativePath into a single taskDescription string.
    ///
    /// The `|` separator is safe: bundleIds are lowercase UUIDs (no `|`), relative paths
    /// are subdirectory/filename components (no `|`). The separator is consumed by
    /// `split(separator:maxSplits:)` with maxSplits=1 so embedded `/` in relativePath
    /// is preserved correctly (e.g. "frames/000000.jpg" round-trips exactly).
    static func makeTaskDescription(bundleId: String, relativePath: String) -> String {
        "\(bundleId)|\(relativePath)"
    }

    /// Parse a taskDescription produced by makeTaskDescription.
    /// Returns nil for malformed strings (no `|`, or empty components).
    static func parseTaskDescription(_ desc: String) -> (bundleId: String, relativePath: String)? {
        // maxSplits:1 preserves any (hypothetical) `|` within relativePath.
        let parts = desc.split(separator: "|", maxSplits: 1, omittingEmptySubsequences: false)
        guard parts.count == 2 else { return nil }
        let bundleId     = String(parts[0])
        let relativePath = String(parts[1])
        guard !bundleId.isEmpty, !relativePath.isEmpty else { return nil }
        return (bundleId, relativePath)
    }

    // MARK: - Phase-1 enqueue

    /// Create one background uploadTask per non-bundle.pb blob not yet uploaded.
    ///
    /// - Skips blobs already .uploaded in the persisted record (relaunch resume path).
    /// - Excludes bundle.pb: it is enqueued by onAllBlobsUploaded after the gate fires,
    ///   never by this loop. This is the load-bearing ordering guarantee (decision 0040).
    /// - Derives outputDir from record.outputDir; throws missingOutputDir if absent
    ///   (pre-P4 records without the field cannot participate in Phase-1).
    /// - Sets Content-Range: bytes 0-{size-1}/{size} (required by GCS single-shot resumable PUT).
    /// - Does NOT set Content-Length: URLSession computes it from the file URL automatically.
    /// - Does NOT set Content-Type: the session_uri was minted with
    ///   X-Upload-Content-Type: application/octet-stream; the server controls the stored type
    ///   (gap F2, decision 0040 item 2).
    /// - task.taskDescription = makeTaskDescription(bundleId:relativePath:) for stable
    ///   cross-relaunch association.
    ///
    /// Stores an UploadContext for this bundle in memory (retryCount + reputtedPaths only;
    /// outputDir is now in the persisted record). Context is NOT persisted.
    func enqueuePhasOneBlobs(record: UploadSessionRecord) throws {
        guard let outputDir = record.outputDir else {
            throw BlobUploadError.missingOutputDir(record.bundleId)
        }
        let bundleId = record.bundleId
        contexts[bundleId] = UploadContext()

        var enqueued = 0
        // bundle.pb is excluded here: the Phase-1→Phase-2 gate (allNonBundlePbBlobsUploaded)
        // ensures bundle.pb is enqueued by onAllBlobsUploaded only after all other blobs
        // succeed. Including bundle.pb here would violate the 0040 ordering guarantee.
        for entry in record.sessionEntries where entry.relativePath != "bundle.pb" {
            guard record.blobStatuses[entry.relativePath] != .uploaded else { continue }

            let fileURL = outputDir.appendingPathComponent(entry.relativePath)
            guard let sessionURL = URL(string: entry.sessionUri) else {
                throw BlobUploadError.invalidSessionUri(entry.sessionUri)
            }
            let size = try fileURL.resourceValues(forKeys: [.fileSizeKey]).fileSize ?? 0
            guard size > 0 else {
                throw BlobUploadError.emptyBlob(entry.relativePath)
            }

            var req = URLRequest(url: sessionURL)
            req.httpMethod = "PUT"
            req.setValue("bytes 0-\(size - 1)/\(size)", forHTTPHeaderField: "Content-Range")
            // Content-Length: omitted — URLSession sets it from the file.
            // Content-Type: omitted — session URI controls the stored type (F2).

            let task = session.uploadTask(with: req, fromFile: fileURL)
            task.taskDescription = Self.makeTaskDescription(bundleId: bundleId, relativePath: entry.relativePath)
            task.resume()
            enqueued += 1
        }
        print("[BlobUploadManager] enqueued \(enqueued) Phase-1 task(s) for bundle \(bundleId)")
    }

    // MARK: - Completion routing (0040 item 4)

    /// Map a completing task to the decision-0040 action table and dispatch.
    ///
    /// Call surface for BlobUploadDelegate (via Task { await ... }) and directly
    /// for unit tests. The `statusCode` parameter is nil when `error` is non-nil
    /// (network-layer failure with no HTTP response).
    ///
    /// Race safety: markBlobUploaded is actor-isolated on UploadSessionStore, so
    /// concurrent completions for the same bundle are serialized there. The gate
    /// predicate is evaluated ONLY on the record returned by markBlobUploaded —
    /// never on a separately-loaded copy — so exactly one completion sees
    /// allNonBundlePbBlobsUploaded == true.
    func handleTaskCompletion(
        taskDescription: String?,
        statusCode: Int?,
        error: Error?
    ) async {
        guard
            let desc = taskDescription,
            let (bundleId, relativePath) = Self.parseTaskDescription(desc)
        else {
            print("[BlobUploadManager] ⚠ malformed taskDescription '\(taskDescription ?? "nil")' — skipping")
            return
        }

        if let error {
            await handleNetworkError(bundleId: bundleId, relativePath: relativePath, error: error)
            return
        }

        switch statusCode {
        case 200, 201:
            await handleSuccess(bundleId: bundleId, relativePath: relativePath)

        case 308:
            // Anomalous for a complete single-shot PUT. Re-PUT once; persistent 308 → fatal.
            await handleResumeIncomplete(bundleId: bundleId, relativePath: relativePath)

        case 410:
            // GCS resumable session expired. Re-mint via onSessionExpired.
            await onSessionExpired(bundleId: bundleId)

        case let code where (400..<500).contains(code ?? -1):
            await onFatalBlobError(
                bundleId: bundleId, relativePath: relativePath,
                reason: "http_\(code!)"
            )

        default:
            // 5xx or missing status code — retryable server error.
            await handleServerError(
                bundleId: bundleId, relativePath: relativePath,
                statusCode: statusCode ?? 0
            )
        }
    }

    // MARK: - Private: success path

    private func handleSuccess(bundleId: String, relativePath: String) async {
        // bundle.pb 200/201 = Phase-2 complete; route to onBundleComplete rather than
        // the Phase-1 gate. If routed through the gate, allNonBundlePbBlobsUploaded
        // would still be true (gate excludes bundle.pb from its check), causing
        // onAllBlobsUploaded to fire again — an incorrect re-entry.
        if relativePath == "bundle.pb" {
            print("[BlobUploadManager] ✓ bundle.pb uploaded for bundle \(bundleId)")
            await onBundleComplete(bundleId: bundleId)
            return
        }

        do {
            guard let record = try await store.markBlobUploaded(
                bundleId: bundleId, relativePath: relativePath
            ) else {
                print("[BlobUploadManager] ⚠ markBlobUploaded returned nil for \(bundleId)/\(relativePath)")
                return
            }
            print("[BlobUploadManager] ✓ uploaded \(relativePath) for bundle \(bundleId)")

            if record.allNonBundlePbBlobsUploaded {
                // Phase-1 complete. Hand off to bundle.pb finalizer.
                // outputDir comes from the persisted record — works on cold relaunch too.
                await onAllBlobsUploaded(bundleId: bundleId, record: record)
            }
        } catch {
            print("[BlobUploadManager] ⚠ store update failed for \(bundleId)/\(relativePath): \(error)")
        }
    }

    // MARK: - Private: 308 path

    private func handleResumeIncomplete(bundleId: String, relativePath: String) async {
        guard var ctx = contexts[bundleId] else {
            await onFatalBlobError(bundleId: bundleId, relativePath: relativePath,
                                   reason: "308_no_context")
            return
        }
        if ctx.reputtedPaths.contains(relativePath) {
            // Already re-PUT once and received another 308 → persistent → fatal.
            contexts[bundleId] = ctx
            await onFatalBlobError(bundleId: bundleId, relativePath: relativePath,
                                   reason: "308_persistent")
            return
        }
        ctx.reputtedPaths.insert(relativePath)
        contexts[bundleId] = ctx
        do {
            try await enqueueReput(bundleId: bundleId, relativePath: relativePath)
            print("[BlobUploadManager] 308 → re-PUT \(relativePath) (first attempt)")
        } catch {
            await onFatalBlobError(bundleId: bundleId, relativePath: relativePath,
                                   reason: "308_reput_failed: \(error)")
        }
    }

    // MARK: - Private: 5xx / network error path

    private func handleNetworkError(bundleId: String, relativePath: String, error: Error) async {
        await handleServerError(bundleId: bundleId, relativePath: relativePath,
                                statusCode: 0, networkError: error)
    }

    private func handleServerError(
        bundleId: String,
        relativePath: String,
        statusCode: Int,
        networkError: Error? = nil
    ) async {
        guard var ctx = contexts[bundleId] else {
            let reason = networkError.map { "network_no_context: \($0)" }
                ?? "http_\(statusCode)_no_context"
            await onFatalBlobError(bundleId: bundleId, relativePath: relativePath, reason: reason)
            return
        }
        let attempts = ctx.retryCount[relativePath, default: 0]
        guard attempts < Self.maxRetries else {
            contexts[bundleId] = ctx
            let reason = networkError.map { "network_exhausted: \($0)" }
                ?? "http_\(statusCode)_exhausted"
            await onFatalBlobError(bundleId: bundleId, relativePath: relativePath, reason: reason)
            return
        }
        ctx.retryCount[relativePath] = attempts + 1
        contexts[bundleId] = ctx

        let jitter = Double.random(in: 0..<1.0)
        let delay  = min(Self.baseDelaySec * pow(2.0, Double(attempts)) + jitter, Self.maxDelaySec)
        print("[BlobUploadManager] retry \(attempts + 1)/\(Self.maxRetries) for \(relativePath) in \(String(format: "%.2f", delay))s")
        try? await Task.sleep(nanoseconds: UInt64(delay * 1_000_000_000))
        do {
            try await enqueueReput(bundleId: bundleId, relativePath: relativePath)
        } catch {
            await onFatalBlobError(bundleId: bundleId, relativePath: relativePath,
                                   reason: "reput_failed: \(error)")
        }
    }

    // MARK: - Private: shared re-enqueue (used by 308 and 5xx retry paths)

    /// Re-create and resume an upload task for a blob, using the persisted record for
    /// both the outputDir and the session URI. Does not require in-memory UploadContext
    /// for file-path reconstruction (cold-relaunch safe).
    private func enqueueReput(bundleId: String, relativePath: String) async throws {
        guard let record = try await store.load(bundleId: bundleId) else {
            throw BlobUploadError.missingContext(bundleId)
        }
        guard let outputDir = record.outputDir else {
            throw BlobUploadError.missingOutputDir(bundleId)
        }
        let sessionUri = record.sessionUri(for: relativePath)
        guard let sessionUri, let sessionURL = URL(string: sessionUri) else {
            throw BlobUploadError.invalidSessionUri(relativePath)
        }
        let fileURL = outputDir.appendingPathComponent(relativePath)
        let size    = try fileURL.resourceValues(forKeys: [.fileSizeKey]).fileSize ?? 0
        guard size > 0 else {
            throw BlobUploadError.emptyBlob(relativePath)
        }
        var req = URLRequest(url: sessionURL)
        req.httpMethod = "PUT"
        req.setValue("bytes 0-\(size - 1)/\(size)", forHTTPHeaderField: "Content-Range")

        let task = session.uploadTask(with: req, fromFile: fileURL)
        task.taskDescription = Self.makeTaskDescription(bundleId: bundleId, relativePath: relativePath)
        task.resume()
    }

    // MARK: - Phase-2: bundle.pb finalize

    /// Enqueue the bundle.pb PUT, completing Phase-2.
    ///
    /// Called when the Phase-1 gate fires (all non-bundle.pb blobs uploaded) or by the
    /// relaunch path in UploadCoordinator (not yet built) when the persisted record already
    /// satisfies allNonBundlePbBlobsUploaded on app restart.
    ///
    /// Staleness guard (0040 item 6): if elapsed since the persisted mint timestamp exceeds
    /// stalenessThreshold (12 h), early blobs may have been GC'd by the age=1 per-object
    /// lifecycle rule. Routes to onSessionExpired (re-mint path) rather than finalizing
    /// against possibly-absent blobs.
    ///
    /// The `clock` property provides "now" — inject a fixed Date in tests for deterministic
    /// staleness-guard behavior (decision 0041, Step 2).
    ///
    /// Cold-relaunch safe: outputDir and sessionUri are both read from the persisted record.
    func onAllBlobsUploaded(bundleId: String, record: UploadSessionRecord) async {
        guard clock().timeIntervalSince(record.clientMintTimestamp) <= Self.stalenessThreshold else {
            print("[BlobUploadManager] ⚠ bundle \(bundleId) session stale (>12 h) — routing to re-mint")
            // loopGuardEnabled: false — at 12 h, stored URIs are still valid (well within
            // the 7-day GCS window). Identical returned URIs indicate the server correctly
            // returned the still-live stored entries; treat as success, not as a 410 loop.
            // The 410-triggered path uses the default loopGuardEnabled: true.
            await onSessionExpired(bundleId: bundleId, loopGuardEnabled: false)
            return
        }
        await enqueueBundlePb(bundleId: bundleId, record: record)
    }

    /// Enqueue a single-shot whole-file PUT task for bundle.pb against its session URI.
    ///
    /// Shared by onAllBlobsUploaded (fresh path) and onSessionExpired (post-staleness-remint
    /// path). PUT semantics identical to Phase-1 blobs: Content-Range set, Content-Length
    /// and Content-Type omitted (URLSession and session URI handle them — F2).
    private func enqueueBundlePb(bundleId: String, record: UploadSessionRecord) async {
        guard let outputDir = record.outputDir else {
            print("[BlobUploadManager] ⚠ no outputDir in record for \(bundleId)")
            await onFatalBlobError(bundleId: bundleId, relativePath: "bundle.pb",
                                   reason: "missing_output_dir")
            return
        }

        guard let sessionUri = record.sessionUri(for: "bundle.pb"),
              let sessionURL = URL(string: sessionUri) else {
            print("[BlobUploadManager] ⚠ no bundle.pb session URI for \(bundleId)")
            await onFatalBlobError(bundleId: bundleId, relativePath: "bundle.pb",
                                   reason: "missing_bundle_pb_uri")
            return
        }

        let fileURL = outputDir.appendingPathComponent("bundle.pb")
        do {
            let size = try fileURL.resourceValues(forKeys: [.fileSizeKey]).fileSize ?? 0
            guard size > 0 else {
                await onFatalBlobError(bundleId: bundleId, relativePath: "bundle.pb",
                                       reason: "empty_bundle_pb")
                return
            }
            var req = URLRequest(url: sessionURL)
            req.httpMethod = "PUT"
            req.setValue("bytes 0-\(size - 1)/\(size)", forHTTPHeaderField: "Content-Range")
            // Content-Length: URLSession sets from file. Content-Type: omitted (F2).

            let task = session.uploadTask(with: req, fromFile: fileURL)
            task.taskDescription = Self.makeTaskDescription(bundleId: bundleId, relativePath: "bundle.pb")
            task.resume()
            print("[BlobUploadManager] → enqueued bundle.pb PUT for bundle \(bundleId)")
        } catch {
            await onFatalBlobError(bundleId: bundleId, relativePath: "bundle.pb",
                                   reason: "bundle_pb_read_failed: \(error)")
        }
    }

    // MARK: - 410 re-mint / staleness re-mint (shared implementation)

    /// Re-mint session URIs, then re-enqueue affected blobs or finalize bundle.pb.
    ///
    /// Two callers — same re-mint implementation, different loop-guard semantics:
    ///
    ///   • 410-triggered (loopGuardEnabled: true, default):
    ///       handleTaskCompletion routes here on a blob PUT returning 410 Gone.
    ///       Identical returned URIs = Firestore doc still alive after 7-day TTL batch lag,
    ///       still-dead GCS URIs stored → silent loop risk → fatal.
    ///       Different URIs → persist fresh record, re-enqueue pending blobs.
    ///       After blobs complete, the Phase-1 gate fires → onAllBlobsUploaded → bundle.pb.
    ///
    ///   • Staleness-guard (loopGuardEnabled: false):
    ///       onAllBlobsUploaded routes here when >12 h since mint.
    ///       At 12 h, stored URIs are still valid (well within the 7-day GCS window).
    ///       Identical returned URIs = server correctly returned the still-live stored entries;
    ///       treat as success and proceed to bundle.pb (do NOT fatal).
    ///       After re-mint, all blobs are already .uploaded (gate was true), so the re-enqueue
    ///       loop is a no-op; bundle.pb is enqueued directly via enqueueBundlePb.
    ///
    /// Re-mint flow:
    ///   1. Load persisted record (cold-relaunch safe: no in-memory context needed).
    ///   2. Call remintProvider with the stored manifest paths (expectedSizeBytes = 0,
    ///      server accepts per gap F3). Reuses the full 0038 retry/backoff + 401
    ///      token-refresh policy implemented in UploadSessionClient.
    ///   3. Loop guard (410 path only): if returned URIs == persisted URIs → fatal.
    ///   4. Persist fresh record (new sessionEntries + fresh clientMintTimestamp).
    ///   5. Re-enqueue pending non-bundle.pb blobs (no-op for staleness path).
    ///   6. Staleness path only: enqueue bundle.pb directly (Phase-1 already complete).
    ///
    /// Cold-relaunch safe: all state comes from the on-disk record; no UploadContext needed.
    func onSessionExpired(bundleId: String, loopGuardEnabled: Bool = true) async {
        _sessionExpiredInvocations.append(bundleId)
        print("[BlobUploadManager] ↺ session expired for bundle \(bundleId) — attempting re-mint")

        // 1. Load persisted record.
        guard let record = try? await store.load(bundleId: bundleId) else {
            print("[BlobUploadManager] ⚠ onSessionExpired: no record for \(bundleId)")
            await onFatalBlobError(bundleId: bundleId, relativePath: "*",
                                   reason: "expired_no_record")
            return
        }

        // 2. Re-mint via /upload_session (reuses 0038 retry/backoff + 401 token-refresh).
        guard let mintFn = remintProvider else {
            print("[BlobUploadManager] ⚠ remintProvider not wired for \(bundleId)")
            await onFatalBlobError(bundleId: bundleId, relativePath: "*",
                                   reason: "expired_no_remint_provider")
            return
        }
        // Send expectedSizeBytes = 0; server accepts per gap F3 and the path-set alone
        // is the idempotency key. We cannot reconstruct exact sizes from the record.
        let manifestEntries = record.manifestPaths.map {
            UploadManifestEntry(relativePath: $0, expectedSizeBytes: 0)
        }
        let freshEntries: [UploadSessionEntry]
        do {
            freshEntries = try await mintFn(bundleId, manifestEntries)
        } catch {
            print("[BlobUploadManager] ⚠ re-mint failed for \(bundleId): \(error)")
            await onFatalBlobError(bundleId: bundleId, relativePath: "*",
                                   reason: "remint_failed: \(error)")
            return
        }

        // 3. Loop guard (410-triggered path only).
        //    Identical URIs = server returned stored dead URIs (Firestore batch lag after
        //    7-day TTL). Re-enqueuing with dead URIs would loop on 410 immediately.
        //    Not applied on the staleness path: at 12 h, stored URIs are still valid and
        //    identical == correct server behaviour, not a dead-URI condition.
        let oldUriMap = record.sessionUriMap
        let newUriMap = Dictionary(
            uniqueKeysWithValues: freshEntries.map { ($0.relativePath, $0.sessionUri) }
        )
        if loopGuardEnabled && newUriMap == oldUriMap {
            print("[BlobUploadManager] ⚠ re-mint returned identical URIs for \(bundleId) — stale doc still in Firestore")
            await onFatalBlobError(bundleId: bundleId, relativePath: "*",
                                   reason: "remint_returned_stale_uris")
            return
        }

        // 4. Persist fresh record: new URIs + fresh mint timestamp.
        //    Preserves per-blob .uploaded statuses so already-done blobs aren't re-sent.
        let freshRecord = record.updatingSessionEntries(freshEntries, mintTimestamp: clock())
        do {
            try await store.save(freshRecord)
        } catch {
            print("[BlobUploadManager] ⚠ failed to persist fresh record for \(bundleId): \(error)")
            await onFatalBlobError(bundleId: bundleId, relativePath: "*",
                                   reason: "remint_persist_failed: \(error)")
            return
        }

        // 5. Re-enqueue blobs that are not yet .uploaded against the fresh URIs.
        //    bundle.pb is skipped: it is only enqueued after the gate (or directly below).
        //    On the staleness path all blobs are already .uploaded → this loop is a no-op.
        guard let outputDir = freshRecord.outputDir else {
            print("[BlobUploadManager] ⚠ no outputDir in record for \(bundleId) — cannot re-enqueue")
            await onFatalBlobError(bundleId: bundleId, relativePath: "*",
                                   reason: "remint_no_output_dir")
            return
        }

        var reenqueued = 0
        for entry in freshRecord.sessionEntries where entry.relativePath != "bundle.pb" {
            guard freshRecord.blobStatuses[entry.relativePath] != .uploaded else { continue }
            guard let sessionURL = URL(string: entry.sessionUri) else { continue }
            let fileURL = outputDir.appendingPathComponent(entry.relativePath)
            guard
                let resources = try? fileURL.resourceValues(forKeys: [.fileSizeKey]),
                let sz = resources.fileSize,
                sz > 0
            else { continue }

            var req = URLRequest(url: sessionURL)
            req.httpMethod = "PUT"
            req.setValue("bytes 0-\(sz - 1)/\(sz)", forHTTPHeaderField: "Content-Range")
            let task = session.uploadTask(with: req, fromFile: fileURL)
            task.taskDescription = Self.makeTaskDescription(
                bundleId: bundleId, relativePath: entry.relativePath
            )
            task.resume()
            reenqueued += 1
        }
        print("[BlobUploadManager] 🔄 re-minted \(bundleId): re-enqueued \(reenqueued) blob(s)")

        // 6. Staleness path: Phase-1 is already complete (gate was true when the staleness
        //    guard fired). No blobs were re-enqueued above. Enqueue bundle.pb directly with
        //    the fresh record, whose clientMintTimestamp now passes the staleness check.
        if !loopGuardEnabled && freshRecord.allNonBundlePbBlobsUploaded {
            await enqueueBundlePb(bundleId: bundleId, record: freshRecord)
        }
    }

    // MARK: - Unbuilt seams

    /// UNBUILT — P5 seam: upload pipeline terminal state.
    /// Future unit: surface bundle upload completion to UI / polling / FCM,
    /// delete the on-device session dir, and remove the UploadSessionRecord.
    func onBundleComplete(bundleId: String) async {
        _bundleCompleteInvocations.append(bundleId)
        print("[BlobUploadManager] TODO onBundleComplete(\(bundleId)) — P5 not yet built")
    }

    /// UNBUILT — fatal blob error handler.
    /// Future unit: mark bundle failed in the store, surface to UI / FCM.
    func onFatalBlobError(bundleId: String, relativePath: String, reason: String) async {
        _fatalBlobErrorInvocations.append((bundleId: bundleId, relativePath: relativePath, reason: reason))
        print("[BlobUploadManager] ✗ fatal blob error: \(bundleId)/\(relativePath) reason=\(reason)")
    }
}

// MARK: - BlobUploadError

enum BlobUploadError: LocalizedError {
    case invalidSessionUri(String)
    case emptyBlob(String)
    case missingContext(String)
    case missingOutputDir(String)

    var errorDescription: String? {
        switch self {
        case .invalidSessionUri(let s): return "Invalid session URI: \(s)"
        case .emptyBlob(let p):         return "Zero-size blob at path: \(p)"
        case .missingContext(let id):   return "No upload context for bundle: \(id)"
        case .missingOutputDir(let id): return "No outputDir in record for bundle: \(id)"
        }
    }
}
