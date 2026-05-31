/// Background URLSession manager for Phase-1 blob uploads (P4, decision 0040).
///
/// One shared instance per app. A single background URLSession (identifier:
/// BlobUploadManager.backgroundSessionIdentifier) persists across app suspension
/// and kill. On a relaunch triggered by pending background events, accessing
/// BlobUploadManager.shared re-attaches to the same session and the delegate
/// starts receiving completions.
///
/// Public API:
///   enqueuePhasOneBlobs(record:outputDir:)  — create one PUT task per non-bundle.pb blob
///   handleTaskCompletion(taskDescription:statusCode:error:) — called by BlobUploadDelegate;
///       also the entry point for unit tests (call directly, bypassing URLSession)
///   setBackgroundCompletionHandler(_:) — called by the AppDelegate background-session hook
///
/// Task description format:
///   "\(bundleId)|\(relativePath)"
///   Stable across kill/relaunch per Apple docs ("The system preserves this property even
///   after you restart the app"). taskIdentifier is ephemeral — a new Int is assigned per
///   session instance. NEVER use taskIdentifier for cross-launch association.
///
/// Unbuilt seams (Chat-scoped future units):
///   onSessionExpired(bundleId:)          — 410 re-mint via /upload_session
///   onFatalBlobError(bundleId:relativePath:reason:) — surface error to UI / FCM
///
/// AppDelegate hook (not yet wired — requires @UIApplicationDelegateAdaptor):
///   application(_:handleEventsForBackgroundURLSession:completionHandler:)
///   → Task { await BlobUploadManager.shared.setBackgroundCompletionHandler(handler) }
///
/// Decisions: 0040

import Foundation

// MARK: - UploadContext

/// In-memory state for one active bundle upload.
/// Created at enqueuePhasOneBlobs time; not persisted.
/// If the app is killed and relaunched, context is absent for that bundle.
/// 200/201 and 410 completions can be handled without it; re-PUT and
/// retryable-error paths route to onFatalBlobError when context is missing.
private struct UploadContext: Sendable {
    let outputDir: URL
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

    // MARK: - Test observability

    /// Populated by onSessionExpired. Tests read via await to confirm routing.
    var _sessionExpiredInvocations: [String] = []
    /// Populated by onBundleComplete. Tests read via await to confirm routing.
    var _bundleCompleteInvocations: [String] = []

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

    /// Testing init: accepts injected store and URLSession.
    /// Call handleTaskCompletion directly in tests — no network required.
    init(store: UploadSessionStore, session: URLSession = URLSession(configuration: .ephemeral)) {
        self.store   = store
        self.session = session
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
    /// - Sets Content-Range: bytes 0-{size-1}/{size} (required by GCS single-shot resumable PUT).
    /// - Does NOT set Content-Length: URLSession computes it from the file URL automatically.
    /// - Does NOT set Content-Type: the session_uri was minted with
    ///   X-Upload-Content-Type: application/octet-stream; the server controls the stored type
    ///   (gap F2, decision 0040 item 2).
    /// - task.taskDescription = makeTaskDescription(bundleId:relativePath:) for stable
    ///   cross-relaunch association.
    ///
    /// Stores an UploadContext for this bundle in memory; used by the completion delegate
    /// to re-enqueue on 308/5xx and by onAllBlobsUploaded to locate the output directory.
    /// Context is NOT persisted — absent after a kill/relaunch.
    func enqueuePhasOneBlobs(record: UploadSessionRecord, outputDir: URL) throws {
        let bundleId = record.bundleId
        contexts[bundleId] = UploadContext(outputDir: outputDir)

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
            // GCS resumable session expired. Surface to re-mint seam (not yet built).
            onSessionExpired(bundleId: bundleId)

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
                // Phase-1 complete. Retrieve the in-memory outputDir and hand off to the
                // bundle.pb finalizer. Context is absent after a kill/relaunch; in that case
                // the relaunch path (UploadCoordinator, not yet built) calls onAllBlobsUploaded
                // directly with the reconstructed outputDir.
                guard let ctx = contexts[bundleId] else {
                    print("[BlobUploadManager] ⚠ no upload context for \(bundleId) at gate — cannot finalize")
                    await onFatalBlobError(bundleId: bundleId, relativePath: relativePath,
                                           reason: "finalize_no_context")
                    return
                }
                await onAllBlobsUploaded(bundleId: bundleId, record: record, outputDir: ctx.outputDir)
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

    /// Re-create and resume an upload task for a blob, using the in-memory context for
    /// the file URL and the persisted record for the session URI.
    ///
    /// Requires: contexts[bundleId] is set (callers must guard this before calling).
    private func enqueueReput(bundleId: String, relativePath: String) async throws {
        guard let ctx = contexts[bundleId] else {
            throw BlobUploadError.missingContext(bundleId)
        }
        guard let record = try await store.load(bundleId: bundleId) else {
            throw BlobUploadError.missingContext(bundleId)
        }
        let sessionUri = record.sessionUri(for: relativePath)
        guard let sessionUri, let sessionURL = URL(string: sessionUri) else {
            throw BlobUploadError.invalidSessionUri(relativePath)
        }
        let fileURL = ctx.outputDir.appendingPathComponent(relativePath)
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
    /// 12 h, early blobs may have been GC'd by the age=1 per-object lifecycle rule.
    /// Routes to onSessionExpired (re-mint seam) rather than finalizing against
    /// possibly-absent blobs. Server-side failure mode for a late finalize is
    /// failed_incomplete (confirmed in scene.py); we avoid it proactively.
    ///
    /// PUT semantics are identical to Phase-1 blobs: single-shot whole-file
    /// uploadTask(with:fromFile:), Content-Range set, Content-Length and Content-Type
    /// omitted (URLSession and session URI handle them, respectively — F2).
    func onAllBlobsUploaded(bundleId: String, record: UploadSessionRecord, outputDir: URL) async {
        guard Date().timeIntervalSince(record.clientMintTimestamp) <= Self.stalenessThreshold else {
            print("[BlobUploadManager] ⚠ bundle \(bundleId) session stale (>12 h) — routing to re-mint")
            onSessionExpired(bundleId: bundleId)
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

    // MARK: - Unbuilt seams

    /// UNBUILT — 410 dead-session handler.
    /// Future unit (Chat-scoped): re-mint via /upload_session, persist fresh URIs, restart affected blobs.
    func onSessionExpired(bundleId: String) {
        _sessionExpiredInvocations.append(bundleId)
        print("[BlobUploadManager] TODO onSessionExpired(\(bundleId)) — 410 re-mint not yet built")
    }

    /// UNBUILT — P5 seam: upload pipeline terminal state.
    /// Future unit: surface bundle upload completion to UI / polling / FCM.
    func onBundleComplete(bundleId: String) async {
        _bundleCompleteInvocations.append(bundleId)
        print("[BlobUploadManager] TODO onBundleComplete(\(bundleId)) — P5 not yet built")
    }

    /// UNBUILT — fatal blob error handler.
    /// Future unit: mark bundle failed in the store, surface to UI / FCM.
    func onFatalBlobError(bundleId: String, relativePath: String, reason: String) async {
        print("[BlobUploadManager] ✗ fatal blob error: \(bundleId)/\(relativePath) reason=\(reason)")
    }
}

// MARK: - BlobUploadError

enum BlobUploadError: LocalizedError {
    case invalidSessionUri(String)
    case emptyBlob(String)
    case missingContext(String)

    var errorDescription: String? {
        switch self {
        case .invalidSessionUri(let s): return "Invalid session URI: \(s)"
        case .emptyBlob(let p):         return "Zero-size blob at path: \(p)"
        case .missingContext(let id):   return "No upload context for bundle: \(id)"
        }
    }
}
