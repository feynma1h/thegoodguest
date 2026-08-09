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
/// refresh() never clears a surfaced failure: no code path un-fails a record
/// (terminal is terminal; record deletion is owned by CaptureReaper, decision
/// 0084). Clearing is dismiss()'s job, and dismissal is session-local: the
/// record persists, so a dismissed failure reappears on the next launch — the
/// condition still holds — UNTIL the flight is acknowledged (endFlight from the
/// uploadFailed screen), after which the reaper reclaims the record and the
/// banner finally rests.
///
/// When several bundles have failed, the most recent (by clientMintTimestamp — no
/// failure timestamp is persisted) is surfaced; dismissing it lets the next one show.
///
/// Read by: RootFlowView (the live root — it holds the shared instance, scans
/// via .task, and routes dismissal) and UploadFailureView on the retained
/// ContentView rollback path. BlobUploadManager drives it from several sites:
/// one terminal notifyUploadFailed, plus the notifyUploadDeferred /
/// clearDeferral pair that tracks whether a blob is merely waiting.

import Combine
import Foundation

@MainActor
final class UploadFailureMonitor: ObservableObject {

    static let shared = UploadFailureMonitor()

    struct UploadFailure: Equatable {
        let bundleId: String
        let reason: String
    }

    struct UploadDeferral: Equatable {
        let bundleId: String
        let reason: String
    }

    /// The failure currently surfaced to the UI; nil renders nothing.
    @Published private(set) var latestFailure: UploadFailure?

    /// An upload that PAUSED rather than failed: retries are exhausted for this
    /// launch (DEFERRED-TRANSIENT) or the process lost its context (DEFERRED-
    /// INTERRUPTED). Recovery is real but only happens via
    /// rehydrateAllUnfinishedBundles at the NEXT launch, so a screen that keeps
    /// saying "sending…" is telling the user to wait for something that cannot
    /// happen in this process.
    ///
    /// Non-nil while ANY blob of the bundle is deferred. Tracked PER PATH: a real
    /// capture uploads ~127 blobs concurrently, so a bundle-scoped flag was wiped
    /// by the next sibling blob's success milliseconds later — the deferred blob
    /// never moved, the Phase-1 gate never opened, and the screen reverted to
    /// "sending" forever, which is the exact state this signal exists to prevent.
    @Published private(set) var latestDeferral: UploadDeferral?

    /// bundleId → the blob paths currently deferred for it.
    private var deferredPaths: [String: Set<String>] = [:]

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
        // The Lock Screen is told BEFORE the dismissal guard: dismissing the
        // in-app banner is a statement about the banner, not about the upload, and
        // a card left saying "sending" for a bundle that terminally failed is the
        // exact stale-surface class the review passes kept finding.
        LiveActivityController.shared.noteUploadFailed(bundleId: bundleId)
        guard !dismissedThisLaunch.contains(bundleId) else { return }
        latestFailure = UploadFailure(bundleId: bundleId, reason: reason)
    }

    /// In-process kick from BlobUploadManager's deferral paths. In-memory only:
    /// the persisted record already carries the state, and the relaunch rehydration
    /// is the actual recovery mechanism.
    func notifyUploadDeferred(bundleId: String, relativePath: String, reason: String) {
        deferredPaths[bundleId, default: []].insert(relativePath)
        latestDeferral = UploadDeferral(bundleId: bundleId, reason: reason)
        // Hooked at the SOURCE rather than off the wait screen: a deferral raised
        // while the app is backgrounded is precisely when the Lock Screen must stop
        // implying the upload is still moving. It resumes on the next app open, and
        // the card says so.
        LiveActivityController.shared.noteUploadPaused(bundleId: bundleId)
    }

    /// One blob progressed. Clears only THAT path — the bundle stays paused while
    /// any sibling is still deferred.
    func clearDeferral(bundleId: String, relativePath: String) {
        guard var paths = deferredPaths[bundleId] else { return }
        paths.remove(relativePath)
        if paths.isEmpty {
            deferredPaths[bundleId] = nil
            if latestDeferral?.bundleId == bundleId { latestDeferral = nil }
        } else {
            deferredPaths[bundleId] = paths
        }
    }

    /// Clear every deferral for a bundle (completion), or all of them (a new send).
    func clearDeferral(bundleId: String? = nil) {
        if let bundleId {
            deferredPaths[bundleId] = nil
            if latestDeferral?.bundleId == bundleId { latestDeferral = nil }
        } else {
            deferredPaths.removeAll()
            latestDeferral = nil
        }
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
