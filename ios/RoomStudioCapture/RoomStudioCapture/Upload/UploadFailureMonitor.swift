/// Foreground observer for upload-level terminal failures (uploadPhase == .failed).
///
/// The failure counterpart of the completion architecture (decision 0045): the same
/// two entry paths ScenePoller uses for .complete —
///   1. notifyUploadFailed(bundleId:reason:) — in-process kick from
///      BlobUploadManager.onFatalBlobError. In-memory only; no disk I/O.
///   2. refresh() — independent scan of UploadSessionStore for persisted .failed
///      records, called from UploadFailureView's .task. Covers failures from prior
///      launches, which the kick cannot outlive.
///
/// Why this surface exists: when the upload itself permanently fails, no Scene is ever
/// created backend-side, so there is nothing to poll for (ScenePoller) or push about
/// (FCM) — a local read of the persisted .failed state is the only place the failure
/// can appear.
///
/// refresh() never clears a surfaced failure: no code path un-fails a record (terminal
/// is terminal, and record deletion is owned by the unbuilt terminal-state cleanup
/// design — see the completed-capture disk-accumulation gap). Clearing is dismiss()'s
/// job, and dismissal is session-local by design: the record persists, so a dismissed
/// failure reappears on the next launch — the condition still holds.
///
/// When several bundles have failed, the most recent (by clientMintTimestamp — no
/// failure timestamp is persisted) is surfaced; dismissing it lets the next one show.
///
/// Read by: UploadFailureView. One inbound kick from BlobUploadManager.

import Combine
import Foundation

@MainActor
final class UploadFailureMonitor: ObservableObject {

    static let shared = UploadFailureMonitor()

    struct UploadFailure: Equatable {
        let bundleId: String
        let reason: String
    }

    /// The failure currently surfaced to the UI; nil renders nothing.
    @Published private(set) var latestFailure: UploadFailure?

    /// BundleIds dismissed this launch. refresh() skips them and the kick ignores them.
    /// Deliberately not persisted — see the dismissal semantics in the header.
    private var dismissedThisLaunch: Set<String> = []

    private let store: UploadSessionStore

    init(store: UploadSessionStore = .shared) {
        self.store = store
    }

    /// In-process kick from BlobUploadManager.onFatalBlobError (mirrors
    /// ScenePoller.notifyBundleComplete). The caller has already persisted the
    /// .failed record — the shared seam refresh() reads independently.
    func notifyUploadFailed(bundleId: String, reason: String) {
        guard !dismissedThisLaunch.contains(bundleId) else { return }
        latestFailure = UploadFailure(bundleId: bundleId, reason: reason)
    }

    /// Independent scan path: surface the most recent undismissed .failed record.
    /// A store enumeration failure (or an individual unreadable record) is a silent
    /// skip, matching rehydrateAllUnfinishedBundles' posture; existing surfaced state
    /// is left untouched.
    func refresh() async {
        guard let ids = try? await store.allBundleIds() else { return }
        var newestDate = Date.distantPast
        var newestFailure: UploadFailure?
        for id in ids where !dismissedThisLaunch.contains(id) {
            guard let record = try? await store.load(bundleId: id),
                  record.uploadPhase == .failed
            else { continue }
            if record.clientMintTimestamp > newestDate {
                newestDate    = record.clientMintTimestamp
                newestFailure = UploadFailure(
                    bundleId: id,
                    reason: record.failureReason ?? "unknown"
                )
            }
        }
        if let newestFailure {
            latestFailure = newestFailure
        }
    }

    /// Session-local dismiss of the surfaced failure, then a rescan so the next
    /// undismissed .failed record (if any) surfaces in its place.
    func dismiss() async {
        guard let current = latestFailure else { return }
        dismissedThisLaunch.insert(current.bundleId)
        latestFailure = nil
        await refresh()
    }
}
