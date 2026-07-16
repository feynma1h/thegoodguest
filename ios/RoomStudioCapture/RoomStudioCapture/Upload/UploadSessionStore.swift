/// Persistent store for UploadSessionRecord values, keyed by bundle_id.
///
/// Each record is stored as a JSON file at:
///   <Application Support>/<bundle-id>/upload_sessions/<bundle_id>.json
///
/// Files are written with NSFileProtectionCompleteUntilFirstUserAuthentication
/// (AES-256 at rest, readable while locked after first unlock). See decisions
/// 0037 and 0042 for rationale: CAFUFA is required so the background URLSession
/// completion delegate can read the record while the device is locked (decision
/// 0040 item 7); NSFileProtectionComplete would silently stall finalize until
/// the next unlock.
///
/// The store is an actor so all read/write operations are serialised without
/// explicit locking.
///
/// Read by: UploadCoordinator (save after session creation),
///          BlobUploadManager (load session URIs for the PUT phases).

import Foundation

actor UploadSessionStore {

    static let shared = UploadSessionStore()

    private let directory: URL
    private let encoder: JSONEncoder
    private let decoder: JSONDecoder

    private init() {
        let appSupport = FileManager.default
            .urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
        let dir = appSupport
            .appendingPathComponent(
                Bundle.main.bundleIdentifier ?? "com.roomstudio.RoomStudioCapture"
            )
            .appendingPathComponent("upload_sessions")

        // Create directory with CAFUFA so files created inside inherit the class.
        // Complete is incompatible with background-while-locked finalize (decision 0042).
        try? FileManager.default.createDirectory(
            at: dir,
            withIntermediateDirectories: true,
            attributes: [.protectionKey: FileProtectionType.completeUntilFirstUserAuthentication]
        )
        self.directory = dir

        let enc = JSONEncoder()
        enc.dateEncodingStrategy = .iso8601
        enc.outputFormatting = .prettyPrinted
        self.encoder = enc

        let dec = JSONDecoder()
        dec.dateDecodingStrategy = .iso8601
        self.decoder = dec
    }

    // For testing: inject a custom directory.
    init(directory: URL) {
        try? FileManager.default.createDirectory(
            at: directory,
            withIntermediateDirectories: true,
            attributes: [.protectionKey: FileProtectionType.completeUntilFirstUserAuthentication]
        )
        self.directory = directory
        let enc = JSONEncoder()
        enc.dateEncodingStrategy = .iso8601
        enc.outputFormatting = .prettyPrinted
        self.encoder = enc
        let dec = JSONDecoder()
        dec.dateDecodingStrategy = .iso8601
        self.decoder = dec
    }

    // MARK: - Public API

    /// Persist a session record, overwriting any prior record for the same bundle_id.
    func save(_ record: UploadSessionRecord) throws {
        let url  = fileURL(for: record.bundleId)
        let data = try encoder.encode(record)
        try data.write(to: url, options: [.atomic, .completeFileProtectionUntilFirstUserAuthentication])
    }

    /// Load the session record for a bundle, or nil if none exists.
    func load(bundleId: String) throws -> UploadSessionRecord? {
        let url = fileURL(for: bundleId)
        guard FileManager.default.fileExists(atPath: url.path) else { return nil }
        let data = try Data(contentsOf: url)
        return try decoder.decode(UploadSessionRecord.self, from: data)
    }

    /// Mark a blob as uploaded and persist the updated record atomically.
    ///
    /// Called by the background URLSession delegate after each successful blob PUT
    /// (HTTP 200 or 201 from GCS). The actor serializes concurrent delegate calls for
    /// the same bundle so no two completions race on disk.
    ///
    /// Returns the updated record so the caller can immediately evaluate
    /// `record.allNonBundlePbBlobsUploaded` without a second load call.
    /// Returns nil if no record exists for bundleId (should not occur in normal flow;
    /// log and skip enqueuing bundle.pb if encountered).
    @discardableResult
    func markBlobUploaded(bundleId: String, relativePath: String) throws -> UploadSessionRecord? {
        guard let existing = try load(bundleId: bundleId) else { return nil }
        let updated = existing.markingBlobUploaded(relativePath)
        try save(updated)
        return updated
    }

    /// Delete the session record for a bundle (upload-success cleanup).
    func delete(bundleId: String) throws {
        let url = fileURL(for: bundleId)
        guard FileManager.default.fileExists(atPath: url.path) else { return }
        try FileManager.default.removeItem(at: url)
    }

    /// Return all bundle IDs that have a persisted record in the upload_sessions directory.
    ///
    /// Used by BlobUploadManager.rehydrateAllUnfinishedBundles to enumerate all records
    /// on launch without requiring a known bundle ID. Scans the directory for <uuid>.json
    /// files and returns the UUID string (sans extension) for each.
    ///
    /// Returns [] if the directory does not exist (first launch, no records yet).
    func allBundleIds() throws -> [String] {
        guard FileManager.default.fileExists(atPath: directory.path) else { return [] }
        let files = try FileManager.default.contentsOfDirectory(atPath: directory.path)
        return files.compactMap { filename -> String? in
            guard filename.hasSuffix(".json") else { return nil }
            let candidateId = String(filename.dropLast(5))   // strip ".json"
            guard UUID(uuidString: candidateId) != nil else { return nil }
            return candidateId
        }
    }

    // MARK: - Private

    private func fileURL(for bundleId: String) -> URL {
        directory.appendingPathComponent("\(bundleId).json")
    }
}
