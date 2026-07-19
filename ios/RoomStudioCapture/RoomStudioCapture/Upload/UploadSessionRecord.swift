/// Persisted record for one completed POST /upload_session response.
///
/// Keyed by bundle_id. Stored to disk by UploadSessionStore (decision 0037).
/// The upload pipeline (UploadCoordinator / BlobUploadManager) reads it to
/// retrieve session URIs for the blob PUTs and to track per-blob upload
/// status through the Phase-1 gate (decision 0040).
///
/// Fields:
///   bundleId            — lowercased canonical UUIDv4; the Firestore key.
///   tierRawValue        — the underlying Int of an RSCaptureTier case (via .rawValue).
///   clientMintTimestamp — when this record was created on the client.
///                         IMPORTANT: the server response carries no expires_at.
///                         The real upload window is bounded by the captures
///                         bucket lifecycle (age=1d per-object) and the
///                         upload_sessions Firestore TTL (7d) — do not assume
///                         7 days from the GCS resumable-URI nominal.
///   sessionEntries      — the raw server response (relative_path + session_uri).
///                         Map by relativePath, not by index.
///   manifestPaths       — the path-set sent to the server. It is the server-side
///                         idempotency key (same path-set → same session URIs),
///                         so the re-mint path re-sends exactly this set.
///   blobStatuses        — per-relative_path upload status. Initialized to
///                         all .pending on record creation. Updated by
///                         UploadSessionStore.markBlobUploaded after each
///                         successful PUT.
///   outputDir           — absolute URL of the on-device capture output directory.
///                         Persisted so that the cold-relaunch path (no in-memory
///                         UploadContext) can reconstruct file URLs for blob PUTs
///                         without any external state.
///
/// Note on nonisolated:
///   UploadSessionRecord participates in @MainActor UploadCoordinator's @Published
///   state, which would otherwise cause Swift to infer MainActor isolation for the
///   type and its Codable conformance. The type is declared nonisolated: it is a
///   pure value type with no actor-isolated state, encoded/decoded from the
///   UploadSessionStore actor and read from the BlobUploadManager actor.

import Foundation

// MARK: - BlobUploadStatus

/// Upload status for one blob in a capture bundle.
enum BlobUploadStatus: String, Codable, Sendable {
    /// Blob has not yet been successfully PUT to GCS.
    case pending
    /// Blob PUT completed with HTTP 200 or 201 from GCS.
    case uploaded
}

// MARK: - UploadPhase

/// Bundle-level upload lifecycle phase. Persisted so recovery paths can determine
/// the correct re-entry point without re-examining all blob statuses.
enum UploadPhase: String, Codable, Sendable {
    /// Non-bundle.pb blobs are being uploaded (initial state).
    case uploadingBlobs
    /// All non-bundle.pb blobs uploaded; bundle.pb PUT is in flight or about
    /// to be enqueued.
    case uploadingBundlePb
    /// bundle.pb PUT completed 200/201 — upload fully done.
    case complete
    /// Fatal, unrecoverable error. Set (with failureReason) by
    /// BlobUploadManager.onFatalBlobError.
    case failed
}

// MARK: - UploadSessionRecord

nonisolated struct UploadSessionRecord: Codable, Sendable {

    let bundleId: String
    /// RSCaptureTier raw value (Int — SwiftProtobuf enum rawValue).
    let tierRawValue: Int
    /// Client-side timestamp of when the session was created (or last re-minted).
    /// Resets to Date() on each successful /upload_session re-mint (onSessionExpired
    /// path).
    let clientMintTimestamp: Date
    /// Server response entries. Map by relativePath; order is undefined.
    let sessionEntries: [UploadSessionEntry]
    /// The manifest path-set sent in the request — the idempotency key.
    let manifestPaths: [String]
    /// Per-blob upload status. Keyed by relative_path.
    /// Immutable per-value: use markingBlobUploaded(_:) to get an updated copy.
    /// UploadSessionStore.markBlobUploaded saves the updated copy atomically.
    let blobStatuses: [String: BlobUploadStatus]
    /// Absolute URL of the on-device capture output directory.
    /// Used by the cold-relaunch path to reconstruct blob file URLs without
    /// in-memory UploadContext.
    let outputDir: URL
    /// Bundle-level upload lifecycle phase. Defaults to `.uploadingBlobs` on new records.
    /// Persisted so relaunch paths can resume at the correct stage.
    let uploadPhase: UploadPhase
    /// Failure reason string. Set together with `.failed` by
    /// BlobUploadManager.onFatalBlobError; nil otherwise.
    let failureReason: String?
    /// Cross-launch retry counter. Bumped at most once per bundle per process launch by
    /// DEFERRED-TRANSIENT error paths (network_exhausted, remint_failed, etc.).
    /// Reset to 0 on any blob-upload success (markingBlobUploaded).
    /// When this exceeds BlobUploadManager.maxCrossLaunchRetries, the next transient
    /// deferral escalates to permanent failure.
    let crossLaunchRetryCount: Int

    // MARK: - Production init

    /// Initialize a new record. All blobs start as .pending.
    /// Used by UploadCoordinator after the /upload_session response is received.
    init(
        bundleId: String,
        tierRawValue: Int,
        clientMintTimestamp: Date,
        sessionEntries: [UploadSessionEntry],
        manifestPaths: [String],
        outputDir: URL
    ) {
        self.bundleId            = bundleId
        self.tierRawValue        = tierRawValue
        self.clientMintTimestamp = clientMintTimestamp
        self.sessionEntries      = sessionEntries
        self.manifestPaths       = manifestPaths
        self.blobStatuses        = Dictionary(
            uniqueKeysWithValues: sessionEntries.map { ($0.relativePath, BlobUploadStatus.pending) }
        )
        self.outputDir              = outputDir
        self.uploadPhase            = .uploadingBlobs
        self.failureReason          = nil
        self.crossLaunchRetryCount  = 0
    }

    /// Private init used by functional mutation methods to produce updated copies.
    /// nonisolated: called from nonisolated methods; contains no actor-isolated state.
    private nonisolated init(
        bundleId: String,
        tierRawValue: Int,
        clientMintTimestamp: Date,
        sessionEntries: [UploadSessionEntry],
        manifestPaths: [String],
        blobStatuses: [String: BlobUploadStatus],
        outputDir: URL,
        uploadPhase: UploadPhase = .uploadingBlobs,
        failureReason: String? = nil,
        crossLaunchRetryCount: Int = 0
    ) {
        self.bundleId               = bundleId
        self.tierRawValue           = tierRawValue
        self.clientMintTimestamp    = clientMintTimestamp
        self.sessionEntries         = sessionEntries
        self.manifestPaths          = manifestPaths
        self.blobStatuses           = blobStatuses
        self.outputDir              = outputDir
        self.uploadPhase            = uploadPhase
        self.failureReason          = failureReason
        self.crossLaunchRetryCount  = crossLaunchRetryCount
    }

    // MARK: - Convenience accessors

    /// session_uri lookup by relative_path. Returns nil for unknown paths.
    nonisolated func sessionUri(for relativePath: String) -> String? {
        sessionEntries.first { $0.relativePath == relativePath }?.sessionUri
    }

    /// Dictionary view of relativePath → sessionUri for bulk lookup.
    nonisolated var sessionUriMap: [String: String] {
        Dictionary(uniqueKeysWithValues: sessionEntries.map { ($0.relativePath, $0.sessionUri) })
    }

    // MARK: - Functional mutation

    /// Return a new record with relativePath marked as .uploaded.
    ///
    /// The caller (UploadSessionStore.markBlobUploaded) replaces the persisted record
    /// with the returned value. Using a functional update keeps blobStatuses a `let`
    /// constant, which avoids @MainActor isolation issues on the stored property.
    func markingBlobUploaded(_ relativePath: String) -> UploadSessionRecord {
        var updated = blobStatuses
        updated[relativePath] = .uploaded
        return UploadSessionRecord(
            bundleId:              bundleId,
            tierRawValue:          tierRawValue,
            clientMintTimestamp:   clientMintTimestamp,
            sessionEntries:        sessionEntries,
            manifestPaths:         manifestPaths,
            blobStatuses:          updated,
            outputDir:             outputDir,
            uploadPhase:           uploadPhase,
            failureReason:         failureReason,
            crossLaunchRetryCount: 0  // reset on progress: any successful upload clears the retry debt
        )
    }

    /// Return a new record with all non-bundle.pb blob statuses reset to .pending.
    ///
    /// Used by the staleness re-mint path (onSessionExpired with loopGuardEnabled: false)
    /// to force re-upload of all blobs against fresh URIs. The age=1 GCS lifecycle rule
    /// may have GC'd any blob uploaded more than 24h ago; resetting to .pending ensures
    /// the Phase-1 gate re-closes only after every blob is confirmed re-delivered.
    nonisolated func resettingNonBundlePbBlobsToPending() -> UploadSessionRecord {
        var updated = blobStatuses
        for key in updated.keys where key != "bundle.pb" {
            updated[key] = .pending
        }
        return UploadSessionRecord(
            bundleId:              bundleId,
            tierRawValue:          tierRawValue,
            clientMintTimestamp:   clientMintTimestamp,
            sessionEntries:        sessionEntries,
            manifestPaths:         manifestPaths,
            blobStatuses:          updated,
            outputDir:             outputDir,
            uploadPhase:           .uploadingBlobs,  // reset with blobs: all blobs need re-upload
            failureReason:         failureReason,
            crossLaunchRetryCount: crossLaunchRetryCount  // preserved: staleness reset is not a new error
        )
    }

    /// Return a new record with fresh session entries and an updated mint timestamp.
    ///
    /// Used by the 410 re-mint path (onSessionExpired) after /upload_session returns
    /// new session URIs. Preserves per-blob statuses: already-uploaded blobs keep
    /// their .uploaded status so the re-mint path doesn't re-enqueue them.
    /// Blobs present in the new entries but absent from blobStatuses default to .pending.
    nonisolated func updatingSessionEntries(
        _ newEntries: [UploadSessionEntry],
        mintTimestamp: Date
    ) -> UploadSessionRecord {
        let updated = Dictionary(
            uniqueKeysWithValues: newEntries.map { entry in
                (entry.relativePath, blobStatuses[entry.relativePath] ?? .pending)
            }
        )
        return UploadSessionRecord(
            bundleId:              bundleId,
            tierRawValue:          tierRawValue,
            clientMintTimestamp:   mintTimestamp,
            sessionEntries:        newEntries,
            manifestPaths:         manifestPaths,
            blobStatuses:          updated,
            outputDir:             outputDir,
            uploadPhase:           uploadPhase,
            failureReason:         failureReason,
            crossLaunchRetryCount: crossLaunchRetryCount  // preserved: remint doesn't clear the retry debt
        )
    }

    // MARK: - Phase mutation

    /// Return a new record with the given upload phase (and optionally a failure reason).
    nonisolated func markingPhase(
        _ phase: UploadPhase,
        failureReason newReason: String? = nil,
        crossLaunchRetryCount newCount: Int? = nil
    ) -> UploadSessionRecord {
        UploadSessionRecord(
            bundleId:              bundleId,
            tierRawValue:          tierRawValue,
            clientMintTimestamp:   clientMintTimestamp,
            sessionEntries:        sessionEntries,
            manifestPaths:         manifestPaths,
            blobStatuses:          blobStatuses,
            outputDir:             outputDir,
            uploadPhase:           phase,
            failureReason:         newReason ?? failureReason,
            crossLaunchRetryCount: newCount ?? crossLaunchRetryCount
        )
    }

    /// Return a new record with crossLaunchRetryCount incremented by 1, phase unchanged.
    /// Used by deferTransientBlobError to persist the cross-launch retry budget.
    nonisolated func bumpingCrossLaunchRetryCount() -> UploadSessionRecord {
        markingPhase(uploadPhase, crossLaunchRetryCount: crossLaunchRetryCount + 1)
    }

    // MARK: - Phase-1 gate predicate

    /// True when every non-bundle.pb blob has been successfully uploaded.
    ///
    /// This is the load-bearing Phase-1 gate (decision 0040): the bundle.pb
    /// upload task MUST NOT be enqueued until this returns true, because the
    /// arrival of bundle.pb in GCS is the backend's ingest signal.
    ///
    /// Checked in two places:
    ///   1. In the background URLSession completion delegate, after each blob PUT
    ///      completes and UploadSessionStore.markBlobUploaded persists the status.
    ///   2. On app relaunch, by loading the persisted record from UploadSessionStore
    ///      and evaluating this predicate (reconstruct-on-relaunch path).
    ///
    /// bundle.pb is excluded from the check: it is Phase-2 — the upload the
    /// Phase-1 gate releases — not one of Phase-1's prerequisites. Its own
    /// status is tracked in blobStatuses but is never inspected by this predicate.
    ///
    /// Edge case: a manifest with no non-bundle.pb entries (pathological; never
    /// produced by ManifestBuilder in practice) returns true immediately.
    nonisolated var allNonBundlePbBlobsUploaded: Bool {
        let nonBundle = sessionEntries.filter { $0.relativePath != "bundle.pb" }
        guard !nonBundle.isEmpty else { return true }
        return nonBundle.allSatisfy { blobStatuses[$0.relativePath] == .uploaded }
    }
}
