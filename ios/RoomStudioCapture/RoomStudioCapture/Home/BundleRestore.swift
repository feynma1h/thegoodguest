/// Which bundle — if any — the home screen should re-adopt at launch, and the
/// record of which bundles the user has already finished with.
///
/// WHY THIS EXISTS: activating RootFlowView would otherwise have LOST the relaunch
/// recovery ContentView's SceneStatusView provided (finding a bundle whose upload
/// completed while the app was dead). The first version of that recovery re-scanned
/// the store from home's `.task` and adopted the newest non-failed record — which
/// re-adopted a bundle the user had just dismissed, because:
///
///   • home's `.task` re-fires every time the flow returns to `.home`, not once per
///     launch (verified: one home → capture → review → home round trip runs it
///     twice), so `endFlight()` clearing `sentBundleId` was undone on arrival; and
///   • a `.complete` record outlives upload success by design (reclaim happens
///     only on a user-seen terminal outcome — CaptureReaper, decision 0084), so
///     an unlatched restore re-adopted the same finished room every launch and
///     home permanently claimed it was "on its way".
///
/// So restoration needs two things the store cannot tell it: run ONCE per launch,
/// and know which bundles the user has deliberately ended. Acknowledgement is a
/// UI-level fact, so it lives here in UserDefaults rather than in the upload record
/// (whose decode is strict and whose format is shared with the upload machinery).
///
/// Read by: RootFlowView. Pinned by: BundleRestoreTests.

import Foundation

// MARK: - Which bundle to re-adopt

enum BundleRestore {

    /// One stored record, reduced to what the choice actually uses.
    struct Candidate: Equatable {
        let bundleId: String
        let phase: UploadPhase
        let minted: Date
    }

    /// The bundle to re-adopt, or nil.
    ///
    /// Skips `.failed` (UploadFailureMonitor's banner owns those) and anything the
    /// user has already finished with; newest by mint timestamp wins. A `.complete`
    /// record IS eligible — that is the whole point of the recovery — but only until
    /// the user ends its flight, which is what `dismissed` records.
    static func pick(from candidates: [Candidate], dismissed: Set<String>) -> String? {
        candidates
            .filter { $0.phase != .failed && !dismissed.contains($0.bundleId) }
            .max { $0.minted < $1.minted }?
            .bundleId
    }
}

// MARK: - Bundles the user has finished with

/// Persisted set of bundle ids the user has deliberately ended (every terminal exit
/// routes through RootFlowView.endFlight). Survives relaunch BY DESIGN: without
/// that, the next launch re-adopts the same finished room forever.
///
/// Bounded so a long-lived install cannot grow it without limit; the cap is far
/// above any plausible number of live bundles, and evicting the oldest entry can
/// only ever resurrect a room the user finished with long ago.
///
/// nonisolated: read from MainActor (RootFlowView) and from CaptureReaper's
/// nonisolated acknowledged-set closure; UserDefaults is documented thread-safe.
nonisolated struct DismissedBundles {

    static let maxRetained = 50
    private static let key = "RootFlow.dismissedBundleIds"

    private let defaults: UserDefaults

    init(defaults: UserDefaults = .standard) {
        self.defaults = defaults
    }

    /// Ids in insertion order, oldest first.
    var ids: [String] {
        defaults.stringArray(forKey: Self.key) ?? []
    }

    var set: Set<String> { Set(ids) }

    /// Record that the user is done with this bundle. Idempotent — re-acknowledging
    /// does not reorder an existing entry, so eviction stays oldest-first.
    func acknowledge(_ bundleId: String) {
        var current = ids
        guard !current.contains(bundleId) else { return }
        current.append(bundleId)
        if current.count > Self.maxRetained {
            current.removeFirst(current.count - Self.maxRetained)
        }
        defaults.set(current, forKey: Self.key)
    }
}
