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
import os

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
    /// Maximum number of cross-launch retry attempts before a DEFERRED-TRANSIENT error
    /// escalates to a permanent terminal failure. Counted by deferTransientBlobError;
    /// reset to 0 on any successful blob upload (markingBlobUploaded). Decision 0045.
    static let maxCrossLaunchRetries = 10
    /// Sessions older than this threshold may have had early blobs GC'd by the
    /// age=1 lifecycle rule. Re-mint rather than finalizing against absent blobs.
    static let stalenessThreshold: TimeInterval = 12 * 3600

    private static let baseDelaySec: TimeInterval = 1.0   // mirrors 0038
    private static let maxDelaySec:  TimeInterval = 30.0

    // MARK: - Stored properties

    // Logging privacy policy: UUIDs, blob paths, and enum values may be .public;
    // user identifiers and error payloads stay default-private (redacted in shipped logs).
    private let logger = Logger(subsystem: "com.roomstudio.RoomStudioCapture", category: "BlobUpload")

    private let session: URLSession
    let store: UploadSessionStore                     // internal (not private) for tests
    private var contexts: [String: UploadContext] = [:]
    /// In-process one-shot latch: bundleIds whose bundle.pb enqueue is currently in flight.
    /// Prevents a second onAllBlobsUploaded call (from a concurrent actor task) from double-
    /// enqueuing bundle.pb within the same process. Cleared on task completion or fatal exit.
    /// Empty on every relaunch — cross-process guard uses getAllTasks instead (decision 0045).
    private var bundlePbEnqueueInFlight: Set<String> = []

    /// Set by the AppDelegate background-session hook; called in urlSessionDidFinishEvents.
    var backgroundSessionCompletionHandler: (() -> Void)?

    // Part B (M2 fix): counts handleTaskCompletion invocations in-flight. Incremented
    // synchronously in BlobUploadDelegate.didCompleteWithError before Task spawn;
    // decremented in handleTaskCompletion's defer. OSAllocatedUnfairLock: readable from
    // any thread without an actor hop. Decision 0044.
    private let _pendingCount = OSAllocatedUnfairLock<Int>(initialState: 0)

    /// True once urlSessionDidFinishEvents has been observed for the current delivery round.
    private var drainObserved = false

    /// True once the system completion handler has been called; prevents double-fire from
    /// the three trigger paths (drain, last-decrement, handler-stored-late). Decision 0044.
    private var handlerFired = false

    /// Per-process identity token. UUID assigned once at init; never persisted.
    /// Exists as a stable anchor for the per-launch idempotency semantics in
    /// deferTransientBlobError (see transientCountedThisLaunch). Decision 0045.
    private let launchToken: UUID = UUID()
    /// BundleIds whose permanent fatal error was determined within this process.
    /// Prevents re-entry into handleTaskCompletion dispatch for cancelled-sibling
    /// completions that arrive after onFatalBlobError ran. Not persisted: the
    /// cross-launch guard uses uploadPhase == .failed in the store record.
    private var failedBundles: Set<String> = []
    /// BundleIds that have already had their crossLaunchRetryCount bumped within
    /// this process. Ensures at most one counter increment per bundle per launch,
    /// preventing a retry storm from exhausting the N=10 cross-launch budget.
    /// Cleared for a bundle when a blob upload succeeds (progress resets the guard).
    private var transientCountedThisLaunch: Set<String> = []

    // MARK: - Injectable dependencies

    /// Returns "now". Inject a fixed Date in tests for deterministic staleness-guard behavior.
    var clock: () -> Date = { Date() }

    /// Called by onSessionExpired to re-POST /upload_session.
    /// Receives (bundleId, manifestEntries) and returns fresh [UploadSessionEntry].
    /// Production: wrap UploadSessionClient.shared.createUploadSession + AuthManager.shared.
    /// Tests: inject a stub that returns predetermined entries or throws.
    /// Nil means "not wired" — routes to onFatalBlobError.
    var remintProvider: (@Sendable (String, [UploadManifestEntry]) async throws -> [UploadSessionEntry])?

    /// Returns all tasks in the background URLSession.
    /// Production: nil (uses session.getAllTasks). Tests: inject a stub for reconciliation tests.
    var getAllTasksProvider: (@Sendable () async -> [URLSessionTask])?

    // MARK: - Test observability

    /// Populated by onSessionExpired. Tests read via await to confirm routing.
    var _sessionExpiredInvocations: [String] = []
    /// Populated by onBundleComplete. Tests read via await to confirm routing.
    var _bundleCompleteInvocations: [String] = []
    /// Populated by onFatalBlobError. Tests read via await to confirm routing.
    var _fatalBlobErrorInvocations: [(bundleId: String, relativePath: String, reason: String)] = []
    /// Incremented at task.resume() in enqueueBundlePb. Tests verify latch prevents double-enqueue.
    var _bundlePbTasksCreatedCount: Int = 0
    /// Set to the count of blobs enqueued by the last enqueuePhasOneBlobs call.
    /// Tests verify reconciliation skips blobs whose live task is already in the URLSession.
    var _phase1BlobsEnqueuedCount: Int = 0

    // Part B test observability — nonisolated so tests can read without await.
    nonisolated var _pendingCompletionsCount: Int { _pendingCount.withLock { $0 } }
    /// Actor-isolated; read with await.
    var _drainObserved: Bool { drainObserved }
    var _handlerFired: Bool  { handlerFired }

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

    /// Store the system-provided background-session completion handler and route through
    /// the fire gate. Decision 0044.
    ///
    /// Clears handlerFired so a previously-fired round doesn't block the new one.
    /// drainObserved is NOT reset here — it is cleared in fireCompletionHandlerIfReady
    /// at fire-time, so any drain that arrived before this call (AppDelegate Task-hop-
    /// delayed handler-stored-late path) remains visible and fires the handler immediately.
    func setBackgroundCompletionHandler(_ handler: @escaping () -> Void) {
        handlerFired = false
        backgroundSessionCompletionHandler = handler
        fireCompletionHandlerIfReady()
    }

    /// Called by BlobUploadDelegate.urlSessionDidFinishEvents(forBackgroundURLSession:).
    /// Sets the drainObserved flag and routes through the fire gate. The stored handler
    /// fires only after BOTH this flag is true AND the pending-completions counter reaches
    /// zero — preventing premature suspend before in-flight handleTaskCompletion chains
    /// (including markBlobUploaded and enqueueBundlePb) have resolved. Decision 0044.
    func drainBackgroundSessionEvents() {
        drainObserved = true
        fireCompletionHandlerIfReady()
    }

    /// Fire the system-provided completion handler exactly once, iff all three conditions
    /// are met: (a) urlSessionDidFinishEvents observed, (b) no handleTaskCompletion chains
    /// in flight (pending count == 0), (c) a handler is stored and has not already fired.
    ///
    /// Three trigger sites funnel here — drainBackgroundSessionEvents, the last
    /// decrementPendingCompletions, and setBackgroundCompletionHandler — so the actor
    /// serializes all three without a race. Decision 0044.
    private func fireCompletionHandlerIfReady() {
        guard drainObserved,
              _pendingCount.withLock({ $0 }) == 0,
              let handler = backgroundSessionCompletionHandler,
              !handlerFired
        else { return }
        handlerFired  = true
        drainObserved = false   // cleared at fire-time so no stale true bleeds into next round
        backgroundSessionCompletionHandler = nil
        handler()
    }

    // MARK: - Drain-gate counter (Part B)

    /// Increment the in-flight counter. Call synchronously in the OS delegate callback,
    /// before spawning the Task, so the count is non-zero when urlSessionDidFinishEvents
    /// fires. Safe to call from any thread (OSAllocatedUnfairLock). Decision 0044.
    nonisolated func incrementPendingCompletions() {
        _pendingCount.withLock { $0 += 1 }
    }

    /// Decrement the in-flight counter. Called from handleTaskCompletion's defer.
    /// If the count reaches zero, spawns a Task to call fireCompletionHandlerIfReady —
    /// the last-decrement trigger path. Decision 0044.
    nonisolated func decrementPendingCompletions() {
        let remaining = _pendingCount.withLock { (n: inout Int) -> Int in
            n -= 1
            return n
        }
        if remaining == 0 {
            Task { await self.fireCompletionHandlerIfReady() }
        }
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

    // MARK: - getAllTasks wrapper

    /// Fetch all tasks in the background URLSession.
    /// Uses getAllTasksProvider if injected (tests), otherwise calls session.getAllTasks.
    private func getAllTasks() async -> [URLSessionTask] {
        if let provider = getAllTasksProvider {
            return await provider()
        }
        return await withCheckedContinuation { continuation in
            session.getAllTasks { continuation.resume(returning: $0) }
        }
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
    func enqueuePhasOneBlobs(record: UploadSessionRecord) async throws {
        guard let outputDir = record.outputDir else {
            throw BlobUploadError.missingOutputDir(record.bundleId)
        }
        let bundleId = record.bundleId

        // Preserve existing context if one exists (retryCount + reputtedPaths intact).
        // Only create a fresh UploadContext for the very first call for this bundle.
        // Unconditional overwrite would zero retry/308 state mid-flight (decision 0045).
        if contexts[bundleId] == nil {
            contexts[bundleId] = UploadContext()
        }

        // Fetch live tasks once. Skip any blob whose task is already in the URLSession —
        // prevents duplicate PUTs when called again while first-wave tasks are still running
        // (same-process and cross-process guard for Phase-1 blobs, decision 0045).
        let liveTasks = await getAllTasks()
        let liveDescriptions = Set(liveTasks.compactMap(\.taskDescription))

        var enqueued = 0
        _phase1BlobsEnqueuedCount = 0
        // bundle.pb is excluded here: the Phase-1→Phase-2 gate (allNonBundlePbBlobsUploaded)
        // ensures bundle.pb is enqueued by onAllBlobsUploaded only after all other blobs
        // succeed. Including bundle.pb here would violate the 0040 ordering guarantee.
        for entry in record.sessionEntries where entry.relativePath != "bundle.pb" {
            guard record.blobStatuses[entry.relativePath] != .uploaded else { continue }

            // Skip if a live URLSession task already exists for this blob.
            let taskDesc = Self.makeTaskDescription(bundleId: bundleId, relativePath: entry.relativePath)
            guard !liveDescriptions.contains(taskDesc) else {
                logger.info("[BlobUploadManager] ⚠ live task exists for \(entry.relativePath, privacy: .public) in bundle \(bundleId, privacy: .public) — skipping")
                continue
            }

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
            task.taskDescription = taskDesc
            task.resume()
            enqueued += 1
        }
        _phase1BlobsEnqueuedCount = enqueued
        logger.info("[BlobUploadManager] enqueued \(enqueued) Phase-1 task(s) for bundle \(bundleId, privacy: .public)")
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
        error: Error?,
        backgroundTaskToken: BackgroundTaskHandle? = nil
    ) async {
        // Single defer covers every exit path (Q2 map, decision 0044):
        // malformed-desc early return, all onFatalBlobError routing sites, markBlobUploaded
        // nil/throw, gate-not-fired return, onBundleComplete routing, enqueueReput/task.resume
        // success, onAllBlobsUploaded→enqueueBundlePb, onSessionExpired all terminals.
        // Re-enqueue paths (308/5xx/410 success) start a new URLSession task whose own
        // didCompleteWithError callback acquires its own token and increments its own counter.
        defer {
            backgroundTaskToken?.endIfNeeded()
            decrementPendingCompletions()
        }
        guard
            let desc = taskDescription,
            let (bundleId, relativePath) = Self.parseTaskDescription(desc)
        else {
            logger.info("[BlobUploadManager] ⚠ malformed taskDescription '\(taskDescription ?? "nil", privacy: .public)' — skipping")
            return
        }

        // Re-entry guard: drop completions for bundles whose fatal error already fired this
        // process. Fires for cancelled-sibling didCompleteWithError callbacks that arrive after
        // onFatalBlobError ran. Defer (endIfNeeded + decrementPendingCompletions) fires regardless.
        if failedBundles.contains(bundleId) {
            logger.info("[BlobUploadManager] ⚑ dropping completion for failed bundle \(bundleId, privacy: .public)/\(relativePath, privacy: .public)")
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
            // For bundle.pb: clear the in-process latch so the re-mint path can re-enqueue
            // bundle.pb after blobs are re-uploaded and the Phase-1 gate re-fires.
            if relativePath == "bundle.pb" { bundlePbEnqueueInFlight.remove(bundleId) }
            await onSessionExpired(bundleId: bundleId)

        case 408, 429:
            // DEFERRED-TRANSIENT: transient GCS rate-limit (429) or request-timeout (408).
            // Retry-After honoring is a pre-launch gap (0038) — not built here.
            // Load record for counter. If no record, route to fatal (can't track budget).
            if let record = try? await store.load(bundleId: bundleId) {
                await deferTransientBlobError(bundleId: bundleId, relativePath: relativePath,
                                              reason: "http_\(statusCode!)", record: record)
            } else {
                await onFatalBlobError(bundleId: bundleId, relativePath: relativePath,
                                       reason: "http_\(statusCode!)_no_record")
            }

        case let code where (400..<500).contains(code ?? -1):
            // TERMINAL: deterministic 4xx (400/401/403/404/409/422/…).
            // 410 is handled by the case above; 408/429 are handled by the case above.
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
            // Persist .complete phase. Does NOT delete the record or session dir —
            // that is reserved for the disk-accumulation unit (P5 onBundleComplete).
            if let current = try? await store.load(bundleId: bundleId) {
                try? await store.save(current.markingPhase(.complete))
            }
            bundlePbEnqueueInFlight.remove(bundleId)
            logger.info("[BlobUploadManager] ✓ bundle.pb uploaded for bundle \(bundleId, privacy: .public)")
            await onBundleComplete(bundleId: bundleId)
            return
        }

        do {
            guard let record = try await store.markBlobUploaded(
                bundleId: bundleId, relativePath: relativePath
            ) else {
                logger.info("[BlobUploadManager] ⚠ markBlobUploaded returned nil for \(bundleId, privacy: .public)/\(relativePath, privacy: .public)")
                return
            }
            logger.debug("[BlobUploadManager] ✓ uploaded \(relativePath, privacy: .public) for bundle \(bundleId, privacy: .public)")
            // Progress: clear per-launch idempotency guard so a subsequent transient error
            // in the same launch can re-count. crossLaunchRetryCount is reset to 0 by
            // markingBlobUploaded (via markBlobUploaded → markingBlobUploaded). Decision 0045.
            transientCountedThisLaunch.remove(bundleId)

            if record.allNonBundlePbBlobsUploaded {
                // Phase-1 complete. Hand off to bundle.pb finalizer.
                // outputDir comes from the persisted record — works on cold relaunch too.
                await onAllBlobsUploaded(bundleId: bundleId, record: record)
            }
        } catch {
            logger.info("[BlobUploadManager] ⚠ store update failed for \(bundleId, privacy: .public)/\(relativePath, privacy: .public): \(error.localizedDescription)")
        }
    }

    // MARK: - Private: 308 path

    private func handleResumeIncomplete(bundleId: String, relativePath: String) async {
        guard var ctx = contexts[bundleId] else {
            // DEFERRED-INTERRUPTED: context absent because this process was killed/relaunched.
            // The persisted record preserves the session URI; relaunch re-enqueues from the
            // on-disk record. No counter bump (this is a process-restart artifact, not a failure).
            logger.info("[BlobUploadManager] ↩ deferred (no-context): \(bundleId, privacy: .public)/\(relativePath, privacy: .public) reason=308_no_context")
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
            logger.info("[BlobUploadManager] 308 → re-PUT \(relativePath, privacy: .public) (first attempt)")
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
            // DEFERRED-INTERRUPTED: context absent because this process was killed/relaunched.
            // Blob stays .pending; relaunch re-enqueues from the persisted record. No counter bump.
            let reason = networkError.map { "network_no_context: \($0)" }
                ?? "http_\(statusCode)_no_context"
            logger.info("[BlobUploadManager] ↩ deferred (no-context): \(bundleId, privacy: .public)/\(relativePath, privacy: .public) reason=\(reason)")
            return
        }
        let attempts = ctx.retryCount[relativePath, default: 0]
        guard attempts < Self.maxRetries else {
            contexts[bundleId] = ctx
            let reason = networkError.map { "network_exhausted: \($0)" }
                ?? "http_\(statusCode)_exhausted"
            // DEFERRED-TRANSIENT: in-process retries exhausted. Bump cross-launch counter;
            // blob stays .pending. Relaunch path re-enqueues via enqueuePhasOneBlobs.
            if let record = try? await store.load(bundleId: bundleId) {
                await deferTransientBlobError(bundleId: bundleId, relativePath: relativePath,
                                              reason: reason, record: record)
            } else {
                await onFatalBlobError(bundleId: bundleId, relativePath: relativePath, reason: reason)
            }
            return
        }
        ctx.retryCount[relativePath] = attempts + 1
        contexts[bundleId] = ctx

        let jitter = Double.random(in: 0..<1.0)
        let delay  = min(Self.baseDelaySec * pow(2.0, Double(attempts)) + jitter, Self.maxDelaySec)
        logger.info("[BlobUploadManager] retry \(attempts + 1)/\(Self.maxRetries) for \(relativePath, privacy: .public) in \(String(format: "%.2f", delay))s")
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
            logger.info("[BlobUploadManager] ⚠ bundle \(bundleId, privacy: .public) session stale (>12 h) — routing to re-mint")
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
        // ── In-process latch + terminal guard (no await before this block) ──────────────────
        // Check-and-set is synchronous on the actor executor, so no second task can interleave
        // between the guard and the insert (decision 0045).
        guard !bundlePbEnqueueInFlight.contains(bundleId) else {
            logger.info("[BlobUploadManager] ⚠ enqueueBundlePb: in-process latch hit for \(bundleId, privacy: .public) — skipping")
            return
        }
        guard record.uploadPhase != .complete else {
            logger.info("[BlobUploadManager] ⚠ enqueueBundlePb: phase=complete for \(bundleId, privacy: .public) — skipping")
            return
        }
        bundlePbEnqueueInFlight.insert(bundleId)
        // ─────────────────────────────────────────────────────────────────────────────────────

        // Cross-process guard: skip if a live URLSession task for bundle.pb already exists.
        // This catches the case where the OS redelivered events from a previous process that
        // created a task before dying. The in-process latch cannot cover this (decision 0045).
        let bundlePbDesc = Self.makeTaskDescription(bundleId: bundleId, relativePath: "bundle.pb")
        let liveTasks = await getAllTasks()
        if liveTasks.contains(where: { $0.taskDescription == bundlePbDesc }) {
            logger.info("[BlobUploadManager] ⚠ enqueueBundlePb: live URLSession task exists for \(bundleId, privacy: .public) — skipping")
            bundlePbEnqueueInFlight.remove(bundleId)
            return
        }

        guard let outputDir = record.outputDir else {
            logger.info("[BlobUploadManager] ⚠ no outputDir in record for \(bundleId, privacy: .public)")
            bundlePbEnqueueInFlight.remove(bundleId)
            await onFatalBlobError(bundleId: bundleId, relativePath: "bundle.pb",
                                   reason: "missing_output_dir")
            return
        }

        guard let sessionUri = record.sessionUri(for: "bundle.pb"),
              let sessionURL = URL(string: sessionUri) else {
            logger.info("[BlobUploadManager] ⚠ no bundle.pb session URI for \(bundleId, privacy: .public)")
            bundlePbEnqueueInFlight.remove(bundleId)
            await onFatalBlobError(bundleId: bundleId, relativePath: "bundle.pb",
                                   reason: "missing_bundle_pb_uri")
            return
        }

        let fileURL = outputDir.appendingPathComponent("bundle.pb")
        do {
            let size = try fileURL.resourceValues(forKeys: [.fileSizeKey]).fileSize ?? 0
            guard size > 0 else {
                bundlePbEnqueueInFlight.remove(bundleId)
                await onFatalBlobError(bundleId: bundleId, relativePath: "bundle.pb",
                                       reason: "empty_bundle_pb")
                return
            }

            // Persist .uploadingBundlePb before creating the task.
            if let current = try? await store.load(bundleId: bundleId) {
                try? await store.save(current.markingPhase(.uploadingBundlePb))
            }

            var req = URLRequest(url: sessionURL)
            req.httpMethod = "PUT"
            req.setValue("bytes 0-\(size - 1)/\(size)", forHTTPHeaderField: "Content-Range")
            // Content-Length: URLSession sets from file. Content-Type: omitted (F2).

            let task = session.uploadTask(with: req, fromFile: fileURL)
            task.taskDescription = bundlePbDesc
            task.resume()
            _bundlePbTasksCreatedCount += 1
            logger.info("[BlobUploadManager] → enqueued bundle.pb PUT for bundle \(bundleId, privacy: .public)")
        } catch {
            bundlePbEnqueueInFlight.remove(bundleId)
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
    ///       treat as success (do NOT fatal).
    ///       ALL non-bundle.pb blob statuses are reset to .pending and re-enqueued — the
    ///       age=1 GCS lifecycle rule may have GC'd any blob uploaded more than 24h ago.
    ///       If any blob file is missing from disk, routes to onFatalBlobError (abort).
    ///       bundle.pb is NOT enqueued directly; it is finalized via the Phase-1 gate once
    ///       all re-uploads complete.
    ///
    /// Re-mint flow:
    ///   1. Load persisted record (cold-relaunch safe: no in-memory context needed).
    ///   2. Call remintProvider with the stored manifest paths (expectedSizeBytes = 0,
    ///      server accepts per gap F3). Reuses the full 0038 retry/backoff + 401
    ///      token-refresh policy implemented in UploadSessionClient.
    ///   3. Loop guard (410 path only): if returned URIs == persisted URIs → fatal.
    ///   4. Persist fresh record (new sessionEntries + fresh clientMintTimestamp).
    ///   5. Re-enqueue blobs against the fresh URIs.
    ///      Staleness: reset ALL non-bundle.pb statuses to .pending + re-enqueue all
    ///                 (abort on missing file). bundle.pb deferred to gate path.
    ///      410: re-enqueue only non-uploaded blobs. bundle.pb deferred to gate path.
    ///
    /// Cold-relaunch safe: all state comes from the on-disk record; no UploadContext needed.
    func onSessionExpired(bundleId: String, loopGuardEnabled: Bool = true) async {
        _sessionExpiredInvocations.append(bundleId)
        logger.info("[BlobUploadManager] ↺ session expired for bundle \(bundleId, privacy: .public) — attempting re-mint")

        // 1. Load persisted record.
        guard let record = try? await store.load(bundleId: bundleId) else {
            logger.info("[BlobUploadManager] ⚠ onSessionExpired: no record for \(bundleId, privacy: .public)")
            await onFatalBlobError(bundleId: bundleId, relativePath: "*",
                                   reason: "expired_no_record")
            return
        }

        // 2. Re-mint via /upload_session (reuses 0038 retry/backoff + 401 token-refresh).
        guard let mintFn = remintProvider else {
            logger.info("[BlobUploadManager] ⚠ remintProvider not wired for \(bundleId, privacy: .public)")
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
            logger.info("[BlobUploadManager] ⚠ re-mint failed for \(bundleId, privacy: .public): \(error.localizedDescription)")
            // DEFERRED-TRANSIENT: transient network/server failure from /upload_session.
            // Blobs stay .pending; relaunch retries the full onSessionExpired path.
            await deferTransientBlobError(bundleId: bundleId, relativePath: "*",
                                          reason: "remint_failed: \(error)", record: record)
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
            logger.info("[BlobUploadManager] ⚠ re-mint returned identical URIs for \(bundleId, privacy: .public) — stale doc still in Firestore")
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
            logger.info("[BlobUploadManager] ⚠ failed to persist fresh record for \(bundleId, privacy: .public): \(error.localizedDescription)")
            // DEFERRED-TRANSIENT: transient disk/IO error persisting fresh URIs.
            // freshRecord has the correct new URIs but wasn't saved; blobs stay .pending.
            // If the counter bump save also fails (same IO error), count is not advanced —
            // tolerable: conservative, allows one extra attempt on the next launch.
            await deferTransientBlobError(bundleId: bundleId, relativePath: "*",
                                          reason: "remint_persist_failed: \(error)", record: freshRecord)
            return
        }

        // 5. Re-enqueue blobs against the fresh URIs.
        //    The two callers have different semantics here:
        //      Staleness path (!loopGuardEnabled): ALL blobs may have been GC'd by the age=1
        //        rule. Reset every non-bundle.pb status to .pending and re-enqueue all.
        //        Missing blob file = abort (cannot finalize against a gone-locally blob).
        //        bundle.pb is NOT enqueued here; the Phase-1 gate re-fires via normal path.
        //      410 path (loopGuardEnabled): only re-enqueue blobs not yet .uploaded.
        //        Already-done blobs are preserved; bundle.pb deferred to gate path.
        guard let outputDir = freshRecord.outputDir else {
            logger.info("[BlobUploadManager] ⚠ no outputDir in record for \(bundleId, privacy: .public) — cannot re-enqueue")
            await onFatalBlobError(bundleId: bundleId, relativePath: "*",
                                   reason: "remint_no_output_dir")
            return
        }

        if !loopGuardEnabled {
            // STALENESS PATH — three strictly ordered phases.
            //
            // Phase 1: read-only pre-pass. Confirm every non-bundle.pb file exists before
            // mutating any state or starting any upload. A missing-file abort must leave the
            // store untouched and start zero URLSession tasks (decision 0043 follow-up).
            let nonBundleEntries = freshRecord.sessionEntries.filter { $0.relativePath != "bundle.pb" }
            for entry in nonBundleEntries {
                let fileURL = outputDir.appendingPathComponent(entry.relativePath)
                guard FileManager.default.fileExists(atPath: fileURL.path) else {
                    logger.info("[BlobUploadManager] ✗ blob file missing at staleness re-enqueue: \(entry.relativePath, privacy: .public)")
                    // Called once for the first missing path; returns without touching
                    // blob statuses, the reset record, or any URLSession task.
                    await onFatalBlobError(bundleId: bundleId, relativePath: entry.relativePath,
                                           reason: "blob_file_missing_at_staleness_remint")
                    return
                }
            }

            // Phase 2: all files confirmed present — reset statuses and persist.
            let resetRecord = freshRecord.resettingNonBundlePbBlobsToPending()
            do {
                try await store.save(resetRecord)
            } catch {
                logger.info("[BlobUploadManager] ⚠ failed to persist reset record for \(bundleId, privacy: .public): \(error.localizedDescription)")
                // DEFERRED-TRANSIENT: transient disk/IO error persisting staleness-reset record.
                // freshRecord is the last successfully persisted version; bump its counter.
                await deferTransientBlobError(bundleId: bundleId, relativePath: "*",
                                              reason: "staleness_reset_persist_failed: \(error)", record: freshRecord)
                return
            }

            // Phase 3: enqueue all PUT tasks.
            var reenqueued = 0
            for entry in resetRecord.sessionEntries where entry.relativePath != "bundle.pb" {
                let fileURL = outputDir.appendingPathComponent(entry.relativePath)
                guard let sessionURL = URL(string: entry.sessionUri) else { continue }
                guard
                    let resources = try? fileURL.resourceValues(forKeys: [.fileSizeKey]),
                    let sz = resources.fileSize, sz > 0
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
            logger.info("[BlobUploadManager] 🔄 staleness re-mint \(bundleId, privacy: .public): reset all blobs, re-enqueued \(reenqueued) blob(s)")
            // bundle.pb is NOT enqueued here. When all re-uploads complete (200/201),
            // the Phase-1 gate fires → onAllBlobsUploaded → enqueueBundlePb.
            // clientMintTimestamp is now freshRecord's clock() value, so the staleness
            // check in the next onAllBlobsUploaded call passes immediately.
            return
        }

        // 410 PATH: re-enqueue only blobs that are not yet .uploaded.
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
        logger.info("[BlobUploadManager] 🔄 re-minted \(bundleId, privacy: .public): re-enqueued \(reenqueued) blob(s)")
    }

    // MARK: - Unbuilt seams

    /// UNBUILT — P5 seam: upload pipeline terminal state.
    /// Future unit: surface bundle upload completion to UI / polling / FCM,
    /// delete the on-device session dir, and remove the UploadSessionRecord.
    func onBundleComplete(bundleId: String) async {
        _bundleCompleteInvocations.append(bundleId)
        logger.info("[BlobUploadManager] TODO onBundleComplete(\(bundleId, privacy: .public)) — P5 not yet built")
    }

    // MARK: - Terminal fatal handler (P5 unit b)

    /// Permanent, unrecoverable error for a bundle. Marks the record .failed in the store,
    /// inserts the bundleId into failedBundles (re-entry guard), cancels sibling URLSession
    /// tasks for this bundle, and cleans up in-memory state.
    ///
    /// Classification: called ONLY for TERMINAL errors (deterministic failures that retry
    /// cannot recover: http_400/401/403/404, 308_persistent, empty_bundle_pb, …).
    /// For DEFERRED-TRANSIENT (exhausted retries) use deferTransientBlobError.
    /// For DEFERRED-INTERRUPTED (no-context, relaunch-recoverable) log inline, return.
    ///
    /// Decision 0045 (Fork C = R, unit b).
    func onFatalBlobError(bundleId: String, relativePath: String, reason: String) async {
        _fatalBlobErrorInvocations.append((bundleId: bundleId, relativePath: relativePath, reason: reason))
        logger.info("[BlobUploadManager] ✗ fatal: \(bundleId, privacy: .public)/\(relativePath, privacy: .public) reason=\(reason)")

        // 1. Set in-process guard FIRST: cancelled-sibling completions that arrive after this
        //    return are dropped by the re-entry guard in handleTaskCompletion.
        failedBundles.insert(bundleId)

        // 2. Clean up in-memory state so no dangling references remain.
        bundlePbEnqueueInFlight.remove(bundleId)
        contexts.removeValue(forKey: bundleId)
        transientCountedThisLaunch.remove(bundleId)

        // 3. Persist .failed phase + reason so the relaunch path (unit a) skips this bundle.
        if let current = try? await store.load(bundleId: bundleId) {
            try? await store.save(current.markingPhase(.failed, failureReason: reason))
        }

        // 4. Cancel sibling URLSession tasks for this bundle.
        //    .cancel() fires didCompleteWithError(NSURLErrorCancelled); the re-entry guard
        //    (step 1, already set) drops those callbacks without re-entering dispatch.
        let tasks = await getAllTasks()
        for task in tasks {
            guard let parsed = Self.parseTaskDescription(task.taskDescription ?? "") else { continue }
            if parsed.bundleId == bundleId { task.cancel() }
        }

        // TODO P5: surface terminal failure to UI / FCM.
    }

    // MARK: - Deferred transient error handler (P5 unit b)

    /// Cross-launch retry budgeting for DEFERRED-TRANSIENT errors. Called when an error is
    /// transient (network/server/IO) but in-process retries are exhausted, so recovery must
    /// wait for the next launch.
    ///
    /// Per-launch idempotent bump: at most one crossLaunchRetryCount increment per bundle
    /// per process launch (transientCountedThisLaunch guard). Prevents a retry storm within
    /// one launch from exhausting the N=10 cross-launch budget in a single session.
    ///
    /// Bound enforcement: if crossLaunchRetryCount would exceed maxCrossLaunchRetries,
    /// escalates to onFatalBlobError (permanent failure). The bundle is then marked .failed.
    ///
    /// On normal (non-escalating) deferral: saves record with incremented counter, leaves
    /// all blob statuses unchanged (.pending). The relaunch path (unit a) re-enqueues from
    /// the saved record on the next launch.
    ///
    /// Decision 0045 (Fork C = R, unit b).
    private func deferTransientBlobError(
        bundleId: String,
        relativePath: String,
        reason: String,
        record: UploadSessionRecord
    ) async {
        // Per-launch idempotent-bump guard: only count one transient deferral per bundle per launch.
        if transientCountedThisLaunch.contains(bundleId) {
            logger.info("[BlobUploadManager] ↩ deferred (transient, already counted this launch): \(bundleId, privacy: .public)/\(relativePath, privacy: .public) reason=\(reason)")
            // No counter bump. Blob stays .pending. Relaunch path re-enqueues from stored record.
            return
        }
        let newCount = record.crossLaunchRetryCount + 1
        guard newCount <= Self.maxCrossLaunchRetries else {
            logger.info("[BlobUploadManager] ⚑ cross-launch retry bound (\(Self.maxCrossLaunchRetries)) exceeded for \(bundleId, privacy: .public) — escalating to fatal")
            await onFatalBlobError(bundleId: bundleId, relativePath: relativePath, reason: reason)
            return
        }
        let bumped = record.bumpingCrossLaunchRetryCount()
        try? await store.save(bumped)
        transientCountedThisLaunch.insert(bundleId)
        logger.info("[BlobUploadManager] ↩ deferred (transient, attempt \(newCount)/\(Self.maxCrossLaunchRetries)): \(bundleId, privacy: .public)/\(relativePath, privacy: .public) reason=\(reason)")
        // Blob stays .pending in blobStatuses. Relaunch path re-enqueues via enqueuePhasOneBlobs.
    }
}

// MARK: - BackgroundTaskHandle

/// Guards a UIBackgroundTask assertion against double-end from two call paths:
///   (1) the OS expiration handler (fires on the main thread if the background window expires),
///   (2) the defer in handleTaskCompletion (fires on the actor executor at normal exit).
///
/// The end action is injected at creation time; production passes a closure that calls
/// UIApplication.endBackgroundTask(token). Tests inject a recording closure.
///
/// Thread-safety: OSAllocatedUnfairLock ensures exactly-once semantics regardless of
/// which path fires first. Decision 0044.
final class BackgroundTaskHandle: @unchecked Sendable {
    private let _lock = OSAllocatedUnfairLock(initialState: false)
    private let _endAction: @Sendable () -> Void

    init(_ endAction: @escaping @Sendable () -> Void) {
        self._endAction = endAction
    }

    func endIfNeeded() {
        let shouldEnd = _lock.withLock { (done: inout Bool) -> Bool in
            guard !done else { return false }
            done = true
            return true
        }
        guard shouldEnd else { return }
        _endAction()
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
