/// Terminal-state reclaim for finished captures — the close of the
/// completed-capture disk-accumulation gap (decision 0084).
///
/// THE RULE (the coupled-pair charter): a capture's record + session dir are
/// reclaimed ONLY on a genuinely terminal outcome the user has been shown —
/// never on mere upload success. Specifically:
///
///   • backend ready / failed / failed_invalid  → reclaim (server has the data,
///     or no re-send of the same bytes can change the answer).
///   • backend failed_incomplete                → RETAIN EVERYTHING. The on-disk
///     blobs are the material the re-send uses: CaptureRecovery decides from
///     disk whether the re-send can honestly be offered, and
///     BlobUploadManager.resendMissingBlobs force-re-mints (decision 0116)
///     exactly those paths plus bundle.pb and re-sends them. Reclaiming here
///     would destroy the only copy of the bytes recovery needs.
///   • upload-phase .failed (client-terminal)   → reclaim only once the user has
///     acknowledged the flight (endFlight from the uploadFailed screen, or a
///     prior acknowledgment) — the reason has been shown; the record's only
///     remaining job was to resurface the banner.
///   • notOwned (decision 0074)                 → retain. The stand-down owns
///     that flow (acknowledge + hide); reclaiming a foreign record would
///     destroy backup-migration evidence for no user-visible gain.
///
/// TWO RECLAIM SITES, one decision module:
///   1. Flight end — RootFlowView.endFlight consults
///      CaptureReclaim.reclaimsAtFlightEnd(screen:) with the screen the user is
///      leaving. Keying on WaitScreen (not raw poll state) is deliberate: it is
///      the routing table's own vocabulary, and it encodes "the user SAW this
///      outcome" — a .succeeded poll observed while the user is elsewhere must
///      not delete the record before they ever reach the doorway.
///   2. Launch scan — CaptureReaper.reapAcknowledgedAtLaunch() sweeps records
///      the user already finished with (DismissedBundles): .failed reclaims
///      directly; .complete reclaims only after ONE confirming GET shows a
///      terminal backend state (never reclaim on a guess — an offline launch
///      retains everything). Unacknowledged records are never touched: they are
///      the launch-restore's inventory (BundleRestore).
///
/// Deletion order is record FIRST, then dir: a crash between the two leaves an
/// orphaned dir that CaptureStorageSweeper's existing no-record pass reclaims on
/// the next launch. The reverse order would leave a .complete record whose dir
/// is gone — a re-advertised room with nothing behind it.
///
/// Read by: RootFlowView (flight end), TheGoodGuestCaptureApp (launch scan).
/// Pinned by: CaptureReclaimTests (tables), CaptureReaperTests (IO).

import Foundation
import os

// MARK: - CaptureReclaim (pure decision tables)

/// nonisolated: pure tables consulted from MainActor (RootFlowView.endFlight)
/// AND the CaptureReaper actor — the target's MainActor default isolation must
/// not apply.
nonisolated enum CaptureReclaim {

    /// Backend-status table: which CONFIRMED scene statuses allow reclaim.
    /// failed_incomplete retains (files are the future re-upload's material);
    /// transient states retain (nothing is finished).
    static func reclaims(status: SceneStatus) -> Bool {
        switch status {
        case .ready, .failed, .failedInvalid:          return true
        case .queued, .processing, .failedIncomplete:  return false
        case .unknown:                                 return false
        }
    }

    /// Flight-end table over the screen the user is leaving via endFlight.
    ///
    ///   .doorway          → reclaim (ready — they walked through it)
    ///   .processingFailed → reclaim (failed / failed_invalid — they saw it)
    ///   .uploadFailed     → reclaim (client-terminal .failed — the reason is on
    ///                       screen right now; leaving it is the acknowledgment)
    ///   .incompleteUpload → RETAIN (failed_incomplete keeps its files)
    ///   .sendRateLimited  → RETAIN (the daily cap: nothing left the phone, and the
    ///                       same capture sends once the quota rolls — reclaiming
    ///                       here would destroy a perfectly good room over a limit
    ///                       that lifts by itself)
    ///   everything else   → retain (nothing terminal has been shown)
    static func reclaimsAtFlightEnd(_ screen: WaitScreen) -> Bool {
        switch screen {
        case .doorway, .processingFailed, .uploadFailed:
            return true
        case .sending, .waiting, .incompleteUpload, .sendFailed,
             .sendRateLimited, .sendPaused, .checkFailed, .notOurs:
            return false
        }
    }

    /// Launch-scan table. `acknowledged` is membership in DismissedBundles —
    /// the user deliberately ended this flight (endFlight semantics).
    ///
    ///   not acknowledged        → skip: the record is the launch-restore's
    ///                             inventory; reclaiming it would silently
    ///                             swallow a doorway the user never saw.
    ///   acknowledged + .failed  → reclaim: client-terminal, user is done with
    ///                             it; this is what finally ends the
    ///                             banner-every-launch loop for ended flights.
    ///   acknowledged + .complete→ confirm via server first: "upload done" is
    ///                             NOT "backend terminal" — the scene may still
    ///                             be processing, or failed_incomplete (files
    ///                             must survive).
    ///   acknowledged + active   → skip: live machinery (rehydration owns it).
    enum LaunchAction: Equatable {
        case skip
        case reclaim
        case confirmViaServer
    }

    static func launchScanAction(phase: UploadPhase, acknowledged: Bool) -> LaunchAction {
        guard acknowledged else { return .skip }
        switch phase {
        case .failed:                            return .reclaim
        case .complete:                          return .confirmViaServer
        case .uploadingBlobs, .uploadingBundlePb: return .skip
        }
    }
}

// MARK: - CaptureReaper (the IO)

actor CaptureReaper {

    static let shared = CaptureReaper()

    // Logging privacy policy: UUIDs, blob paths, and enum values may be .public;
    // user identifiers and error payloads stay default-private.
    private let logger = Logger(subsystem: "com.thegoodguest.TheGoodGuestCapture", category: "CaptureReaper")

    private let store: UploadSessionStore
    /// One confirming GET for a .complete record: returns the decoded scene
    /// status on a 200, nil for anything else (404 / 403 / network / decode).
    /// nil NEVER reclaims — no positive confirmation, no deletion.
    private let fetchStatus: @Sendable (String) async -> SceneStatus?
    /// The acknowledged-bundle set (DismissedBundles). Injected so tests don't
    /// touch UserDefaults.
    private let acknowledged: @Sendable () -> Set<String>

    /// Production singleton: real store, real by-bundle GET (single attempt, no
    /// retry ladder — this is a janitor, not a user surface), real UserDefaults.
    private init() {
        self.store = .shared
        self.fetchStatus = { bundleId in await CaptureReaper.productionFetchStatus(bundleId) }
        self.acknowledged = { DismissedBundles().set }
    }

    /// The production confirming GET, as a named function rather than an inline
    /// closure: the closure form defeated the type-checker once breadcrumbs were
    /// added to its branches ("failed to produce diagnostic"), and a janitor's
    /// only evidence channel is worth keeping compilable.
    private static func productionFetchStatus(_ bundleId: String) async -> SceneStatus? {
        let short = String(bundleId.prefix(8))
        let token: String
        do {
            token = try await launchScanToken()
        } catch {
            #if DEBUG
            StagingHooks.breadcrumb("reaper-token-FAIL \(short)")
            #endif
            return nil
        }
        let outcome = await ScenePoller.liveGET(bundleId: bundleId, idToken: token)
        guard case .success(let pair) = outcome else {
            #if DEBUG
            StagingHooks.breadcrumb("reaper-get-transport-FAIL \(short)")
            #endif
            return nil
        }
        let code: Int = pair.0
        let data: Data = pair.1
        guard code == 200, let response = try? JSONDecoder().decode(SceneResponse.self, from: data) else {
            #if DEBUG
            StagingHooks.breadcrumb("reaper-get \(short) code=\(code) decoded=false")
            #endif
            return nil
        }
        #if DEBUG
        StagingHooks.breadcrumb("reaper-get \(short) code=200 status=\(String(describing: response.status))")
        #endif
        return response.status
    }

    /// Testing init.
    init(
        store: UploadSessionStore,
        fetchStatus: @escaping @Sendable (String) async -> SceneStatus?,
        acknowledged: @escaping @Sendable () -> Set<String>
    ) {
        self.store = store
        self.fetchStatus = fetchStatus
        self.acknowledged = acknowledged
    }

    /// Token for the launch scan's confirming GET — same cold-launch-safe path
    /// as ScenePoller's default (sign-in single-flighted inside AuthManager).
    private static func launchScanToken() async throws -> String {
        try await AuthManager.shared.signInIfNeeded()
        return try await AuthManager.shared.currentIDToken()
    }

    // MARK: - Reclaim (record first, then dir)

    /// Delete the record and session dir for a bundle whose terminal outcome has
    /// been decided by a CaptureReclaim table.
    ///
    /// Defensive re-check inside: an active-phase record (.uploadingBlobs /
    /// .uploadingBundlePb) is NEVER reclaimed regardless of what the caller
    /// concluded — live machinery must survive any future caller bug. A missing
    /// record or missing dir is success, not an error (the other half may have
    /// been reclaimed by a prior crash + sweep).
    func reclaim(bundleId: String) async {
        guard let record = try? await store.load(bundleId: bundleId) else { return }
        guard record.uploadPhase == .complete || record.uploadPhase == .failed else {
            logger.info("[CaptureReaper] ⚠ refusing reclaim of active bundle \(bundleId, privacy: .public) — phase=\(record.uploadPhase.rawValue, privacy: .public)")
            return
        }
        try? await store.delete(bundleId: bundleId)
        let dir = record.outputDir
        if FileManager.default.fileExists(atPath: dir.path) {
            try? FileManager.default.removeItem(at: dir)
        }
        logger.info("[CaptureReaper] ✓ reclaimed \(bundleId, privacy: .public) (phase=\(record.uploadPhase.rawValue, privacy: .public))")
    }

    // MARK: - Launch scan

    /// Sweep acknowledged, finished flights left behind by earlier launches.
    /// Bounded work: one store enumeration; at most one GET per acknowledged
    /// .complete record, and a reclaimed record never appears again.
    func reapAcknowledgedAtLaunch() async {
        guard let ids = try? await store.allBundleIds(), !ids.isEmpty else {
            #if DEBUG
            StagingHooks.breadcrumb("reaper-scan no-ids")
            #endif
            return
        }
        let acked = acknowledged()
        #if DEBUG
        StagingHooks.breadcrumb("reaper-scan ids=\(ids.count) acked=\(acked.count)")
        #endif
        for id in ids {
            guard let record = try? await store.load(bundleId: id) else {
                #if DEBUG
                StagingHooks.breadcrumb("reaper-load-FAIL \(id.prefix(8))")
                #endif
                continue
            }
            let action = CaptureReclaim.launchScanAction(phase: record.uploadPhase,
                                                         acknowledged: acked.contains(id))
            #if DEBUG
            StagingHooks.breadcrumb("reaper-action \(id.prefix(8)) phase=\(record.uploadPhase.rawValue) acked=\(acked.contains(id)) -> \(action)")
            #endif
            switch action {
            case .skip:
                continue
            case .reclaim:
                await reclaim(bundleId: id)
            case .confirmViaServer:
                guard let status = await fetchStatus(id),
                      CaptureReclaim.reclaims(status: status)
                else { continue }
                await reclaim(bundleId: id)
            }
        }
        #if DEBUG
        StagingHooks.breadcrumb("reaper-scan done")
        #endif
    }
}
