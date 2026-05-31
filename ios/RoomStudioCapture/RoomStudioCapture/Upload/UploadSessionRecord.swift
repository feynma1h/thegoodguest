/// Persisted record for one completed POST /upload_session response.
///
/// Keyed by bundle_id. Stored to disk by UploadSessionStore (decision 0038).
/// P4 reads this to retrieve session URIs for the blob PUT phase.
///
/// Fields:
///   bundleId            — lowercased canonical UUIDv4; the Firestore key.
///   tierRawValue        — RSCaptureTier.rawValue (Int32 proto field number).
///   clientMintTimestamp — when this record was created on the client.
///                         IMPORTANT: the server response carries no expires_at
///                         (gap F1). The real upload window is bounded by the
///                         captures bucket lifecycle (age=1d) and the
///                         upload_sessions Firestore TTL — do not assume 7 days.
///   sessionEntries      — the raw server response (relative_path + session_uri).
///                         Map by relativePath, not by index.
///   manifestPaths       — the path-set sent to the server. Stored so P4 can
///                         verify idempotency before re-minting if needed.

import Foundation

struct UploadSessionRecord: Codable, Sendable {

    let bundleId: String
    /// RSCaptureTier raw value (Int — SwiftProtobuf enum rawValue). Convenience accessor: `tier`.
    let tierRawValue: Int
    /// Client-side timestamp of when the session was created.
    let clientMintTimestamp: Date
    /// Server response entries. Map by relativePath; order is undefined.
    let sessionEntries: [UploadSessionEntry]
    /// The manifest path-set sent in the request — the idempotency key.
    let manifestPaths: [String]

    /// Convenience: the proto tier enum.
    var tier: RSCaptureTier { RSCaptureTier(rawValue: tierRawValue) ?? .arkitOnly }

    /// session_uri lookup by relative_path. Returns nil for unknown paths.
    func sessionUri(for relativePath: String) -> String? {
        sessionEntries.first { $0.relativePath == relativePath }?.sessionUri
    }

    /// Dictionary view of relativePath → sessionUri for bulk lookup.
    var sessionUriMap: [String: String] {
        Dictionary(uniqueKeysWithValues: sessionEntries.map { ($0.relativePath, $0.sessionUri) })
    }
}
