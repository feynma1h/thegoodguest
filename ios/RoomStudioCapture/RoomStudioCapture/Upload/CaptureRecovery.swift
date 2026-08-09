/// What a `failed_incomplete` scene can honestly be offered — as a pure function.
///
/// THE BACKGROUND. When ingest finds blobs the bundle references but GCS does not
/// have, the scene stops at `failed_incomplete` and names the absent
/// `missing_paths`. Until 2026-08-08 there was nothing to do with that list: a
/// re-mint replayed the stored session URIs, and a finalized GCS resumable
/// session is single-use, so the client could only no-op or 410 (decisions 0084,
/// 0116). The screen therefore offered a full rescan and — load-bearing — its
/// copy was written to state the file COUNT without promising a re-send.
///
/// `force_remint` (decision 0116) removed the block, so the re-send is now real.
/// This module decides WHETHER it can be offered for a given failure, because
/// the promise is only honest when the bytes are actually on this phone:
///
///   • the server must have named paths this capture's manifest knows;
///   • every named blob must still exist in the capture's output directory;
///   • `bundle.pb` must exist too — it is always re-sent, last.
///
/// Decision 0084's reaper RETAINS record and files on `failed_incomplete`
/// precisely so those conditions normally hold. They can still fail: a record
/// restored from an iCloud backup carries no blobs (decision 0074), and a
/// storage sweep or a manual deletion can take the directory. In those cases the
/// only honest answer is the one the screen shipped before — rescan — and
/// offering "send what's missing" would be a button that cannot work.
///
/// The decision lives here, not inside a SwiftUI body, for the same reason
/// WaitFlowState, BundleRestore, CaptureReclaim and FailureCopy do: it is a
/// table over facts, and a table can be pinned.
///
/// Read by: BlobUploadManager.resendMissingBlobs (executes it), RootFlowView
/// (decides what the failure screen offers). Pinned by: CaptureRecoveryTests.

import Foundation

nonisolated enum CaptureRecovery {

    /// The finalize blob. Named once here so no caller re-spells it.
    static let bundlePbPath = "bundle.pb"

    /// What can be done about one `failed_incomplete` scene.
    enum Plan: Equatable {
        /// These blobs can be re-sent. `bundle.pb` is NOT in the list and is not
        /// optional — it is re-minted and re-sent last by the executor, because
        /// its own resumable session was consumed by the upload that produced
        /// this failure and its re-arrival in GCS is what re-triggers ingest
        /// (decisions 0040, 0116).
        case resend(blobs: [String])
        /// No honest re-send exists. The screen must offer a rescan.
        case rescanOnly(Obstacle)
    }

    /// Why a re-send cannot be offered. Carried (rather than collapsed to a
    /// bool) so the log says which of three quite different things happened.
    enum Obstacle: Equatable {
        /// The scene was `failed_incomplete` but named no usable path. Reachable
        /// from the wire: `missing_paths` is optional and the poller defaults it
        /// to []. Nothing to re-send means nothing to promise.
        case serverNamedNoPaths
        /// The server named paths this capture's manifest never carried. A
        /// bundle referencing a blob that was never in the manifest, or a record
        /// whose manifest has since been narrowed. We cannot build a manifest
        /// entry for a path we do not know, so we do not pretend to.
        case pathsNotInThisCapture([String])
        /// The bytes are gone from this phone. The one case where the user's
        /// data genuinely cannot be recovered by sending — only by rescanning.
        case filesGone([String])
    }

    /// Decide what to offer.
    ///
    /// - Parameters:
    ///   - missingPaths: `missing_paths` from the poll payload.
    ///   - manifestPaths: the record's path-set (the server's idempotency key).
    ///   - fileExists: existence probe for one relative path, injected so this
    ///     stays a pure function and the tests need no filesystem.
    static func plan(
        missingPaths: [String],
        manifestPaths: [String],
        fileExists: (String) -> Bool
    ) -> Plan {
        // bundle.pb is filtered OUT of the blob list even if the server named
        // it. It is never a Phase-1 upload: decision 0040 makes its arrival the
        // ingest signal, so it must be the last thing sent, and the executor
        // sends it through the Phase-1 gate rather than alongside the blobs.
        // Filtering here keeps that invariant true at the source instead of
        // relying on every downstream loop to re-exclude it.
        let blobs = Set(missingPaths).subtracting([bundlePbPath]).sorted()
        guard !blobs.isEmpty else { return .rescanOnly(.serverNamedNoPaths) }

        let known = Set(manifestPaths)
        let unknown = blobs.filter { !known.contains($0) }
        guard unknown.isEmpty else { return .rescanOnly(.pathsNotInThisCapture(unknown)) }

        // bundle.pb is checked alongside the blobs: it is re-sent on every
        // recovery, so its absence blocks the re-send exactly as a blob's does.
        let absent = (blobs + [bundlePbPath]).filter { !fileExists($0) }
        guard absent.isEmpty else { return .rescanOnly(.filesGone(absent.sorted())) }

        return .resend(blobs: blobs)
    }

    /// The path-set to re-mint for a recovery: the blobs, plus `bundle.pb`.
    ///
    /// bundle.pb is present for two independent reasons, either of which alone
    /// would require it: the server's manifest grammar demands exactly one
    /// bundle.pb in any manifest, and its stored session was consumed by the
    /// upload that produced this failure, so a fresh URI is the only way to PUT
    /// it again.
    ///
    /// This is deliberately a SUBSET of the original manifest. Sending the full
    /// path-set would re-mint ~2,000 sessions to fix a handful of files; the
    /// subset costs the same single mint-quota unit and moves far less. The cost
    /// of the subset is that it narrows the server's stored manifest, so a later
    /// ordinary re-mint of the FULL set no longer replays — it mints fresh,
    /// which is correct behaviour and one more quota unit.
    static func mintPaths(for blobs: [String]) -> [String] {
        blobs.filter { $0 != bundlePbPath } + [bundlePbPath]
    }
}
