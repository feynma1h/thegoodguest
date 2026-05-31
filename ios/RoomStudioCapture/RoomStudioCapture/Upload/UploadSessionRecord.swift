/// Persisted record for one completed POST /upload_session response.
///
/// Keyed by bundle_id. Stored to disk by UploadSessionStore (decision 0037).
/// P4 reads this to retrieve session URIs for the blob PUT phase and to track
/// per-blob upload status through the Phase-1→Phase-2 gate (decision 0040).
///
/// Fields:
///   bundleId            — lowercased canonical UUIDv4; the Firestore key.
///   tierRawValue        — RSCaptureTier.rawValue (Int32 proto field number).
///   clientMintTimestamp — when this record was created on the client.
///                         IMPORTANT: the server response carries no expires_at
///                         (gap F1). The real upload window is bounded by the
///                         captures bucket lifecycle (age=1d per-object) and the
///                         upload_sessions Firestore TTL (7d) — do not assume
///                         7 days from the GCS resumable-URI nominal.
///   sessionEntries      — the raw server response (relative_path + session_uri).
///                         Map by relativePath, not by index.
///   manifestPaths       — the path-set sent to the server. Stored so P4 can
///                         verify idempotency before re-minting if needed.
///   blobStatuses        — per-relative_path upload status. Initialized to
///                         all .pending on record creation. Updated by
///                         UploadSessionStore.markBlobUploaded after each
///                         successful PUT. Pre-P4 records on disk (no
///                         blobStatuses key) decode as all .pending.
///   outputDir           — absolute URL of the on-device capture output directory.
///                         Persisted so that the cold-relaunch path (no in-memory
///                         UploadContext) can reconstruct file URLs for blob PUTs
///                         without any external state. Nil for pre-P4 records.
///
/// Note on nonisolated annotations:
///   UploadSessionRecord participates in @MainActor UploadCoordinator's @Published
///   state, causing Swift to infer some computed properties as @MainActor. The
///   nonisolated annotation on each accessor corrects this: these properties
///   contain no actor-isolated state and are safe to call from any context.

import Foundation

// MARK: - BlobUploadStatus

/// Upload status for one blob in a capture bundle.
enum BlobUploadStatus: String, Codable, Sendable {
    /// Blob has not yet been successfully PUT to GCS.
    case pending
    /// Blob PUT completed with HTTP 200 or 201 from GCS.
    case uploaded
}

// MARK: - UploadSessionRecord

struct UploadSessionRecord: Codable, Sendable {

    let bundleId: String
    /// RSCaptureTier raw value (Int — SwiftProtobuf enum rawValue). Convenience accessor: `tier`.
    let tierRawValue: Int
    /// Client-side timestamp of when the session was created (or last re-minted).
    /// Resets to Date() on each successful /upload_session re-mint (onSessionExpired path).
    let clientMintTimestamp: Date
    /// Server response entries. Map by relativePath; order is undefined.
    let sessionEntries: [UploadSessionEntry]
    /// The manifest path-set sent in the request — the idempotency key.
    let manifestPaths: [String]
    /// Per-blob upload status. Keyed by relative_path.
    /// Immutable per-value: use markingBlobUploaded(_:) to get an updated copy.
    /// UploadSessionStore.markBlobUploaded saves the updated copy atomically.
    /// Old records (pre-P4, no blobStatuses key) decode to all .pending.
    let blobStatuses: [String: BlobUploadStatus]
    /// Absolute URL of the on-device capture output directory.
    /// Nil for pre-P4 records that predate this field.
    /// Used by the cold-relaunch path to reconstruct blob file URLs without in-memory UploadContext.
    let outputDir: URL?

    // MARK: - Production init

    /// Initialize a new record. All blobs start as .pending.
    /// Used by UploadCoordinator after the /upload_session response is received.
    init(
        bundleId: String,
        tierRawValue: Int,
        clientMintTimestamp: Date,
        sessionEntries: [UploadSessionEntry],
        manifestPaths: [String],
        outputDir: URL? = nil
    ) {
        self.bundleId            = bundleId
        self.tierRawValue        = tierRawValue
        self.clientMintTimestamp = clientMintTimestamp
        self.sessionEntries      = sessionEntries
        self.manifestPaths       = manifestPaths
        self.blobStatuses        = Dictionary(
            uniqueKeysWithValues: sessionEntries.map { ($0.relativePath, BlobUploadStatus.pending) }
        )
        self.outputDir           = outputDir
    }

    /// Private init used by functional mutation methods to produce updated copies.
    private init(
        bundleId: String,
        tierRawValue: Int,
        clientMintTimestamp: Date,
        sessionEntries: [UploadSessionEntry],
        manifestPaths: [String],
        blobStatuses: [String: BlobUploadStatus],
        outputDir: URL?
    ) {
        self.bundleId            = bundleId
        self.tierRawValue        = tierRawValue
        self.clientMintTimestamp = clientMintTimestamp
        self.sessionEntries      = sessionEntries
        self.manifestPaths       = manifestPaths
        self.blobStatuses        = blobStatuses
        self.outputDir           = outputDir
    }

    // MARK: - Codable

    private enum CodingKeys: String, CodingKey {
        case bundleId
        case tierRawValue
        case clientMintTimestamp
        case sessionEntries
        case manifestPaths
        case blobStatuses
        case outputDir
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        bundleId            = try c.decode(String.self,               forKey: .bundleId)
        tierRawValue        = try c.decode(Int.self,                  forKey: .tierRawValue)
        clientMintTimestamp = try c.decode(Date.self,                 forKey: .clientMintTimestamp)
        sessionEntries      = try c.decode([UploadSessionEntry].self, forKey: .sessionEntries)
        manifestPaths       = try c.decode([String].self,             forKey: .manifestPaths)
        // Pre-P4 records on disk won't have blobStatuses. Treat all as .pending so the
        // upload restarts cleanly on relaunch rather than falsely gating to Phase 2.
        blobStatuses = try c.decodeIfPresent(
            [String: BlobUploadStatus].self,
            forKey: .blobStatuses
        ) ?? Dictionary(
            uniqueKeysWithValues: sessionEntries.map { ($0.relativePath, .pending) }
        )
        // Pre-P4 records won't have outputDir. Nil → cold-relaunch paths route to fatal.
        outputDir = try c.decodeIfPresent(URL.self, forKey: .outputDir)
    }

    // MARK: - Convenience accessors

    /// Convenience: the proto tier enum.
    var tier: RSCaptureTier { RSCaptureTier(rawValue: tierRawValue) ?? .arkitOnly }

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
            bundleId:            bundleId,
            tierRawValue:        tierRawValue,
            clientMintTimestamp: clientMintTimestamp,
            sessionEntries:      sessionEntries,
            manifestPaths:       manifestPaths,
            blobStatuses:        updated,
            outputDir:           outputDir
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
            bundleId:            bundleId,
            tierRawValue:        tierRawValue,
            clientMintTimestamp: clientMintTimestamp,
            sessionEntries:      sessionEntries,
            manifestPaths:       manifestPaths,
            blobStatuses:        updated,
            outputDir:           outputDir
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
            bundleId:            bundleId,
            tierRawValue:        tierRawValue,
            clientMintTimestamp: mintTimestamp,
            sessionEntries:      newEntries,
            manifestPaths:       manifestPaths,
            blobStatuses:        updated,
            outputDir:           outputDir
        )
    }

    // MARK: - Phase-1→Phase-2 gate predicate

    /// True when every non-bundle.pb blob has been successfully uploaded.
    ///
    /// This is the load-bearing Phase-1→Phase-2 gate (decision 0040, item 5).
    /// The bundle.pb upload task MUST NOT be enqueued until this returns true.
    ///
    /// Checked in two places:
    ///   1. In the background URLSession completion delegate, after each blob PUT
    ///      completes and UploadSessionStore.markBlobUploaded persists the status.
    ///   2. On app relaunch, by loading the persisted record from UploadSessionStore
    ///      and evaluating this predicate (reconstruct-on-relaunch path).
    ///
    /// bundle.pb is excluded from the check: it is the Phase-2 trigger, not a
    /// Phase-1 prerequisite. Its own status is tracked in blobStatuses but is
    /// never inspected by this predicate.
    ///
    /// Edge case: a manifest with no non-bundle.pb entries (pathological; never
    /// produced by ManifestBuilder in practice) returns true immediately.
    nonisolated var allNonBundlePbBlobsUploaded: Bool {
        let nonBundle = sessionEntries.filter { $0.relativePath != "bundle.pb" }
        guard !nonBundle.isEmpty else { return true }
        return nonBundle.allSatisfy { blobStatuses[$0.relativePath] == .uploaded }
    }
}
