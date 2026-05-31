/// Startup sweep that reclaims orphaned capture session directories from Application Support.
///
/// Capture blobs are written to `<App Support>/<bundleId>/captures/<session-uuid>/` (decision 0043).
/// That location does NOT auto-purge the way `temporaryDirectory` does. Two mechanisms bound
/// disk growth:
///
///   1. onBundleComplete (BlobUploadManager) — eager cleanup on successful upload.
///      Deletes the session dir AND removes the UploadSessionRecord from the store.
///
///   2. CaptureStorageSweeper.sweep() — startup safety net.
///      On app launch, deletes any session dir whose store record is absent. This catches:
///        • Abandoned captures (app killed before POST /upload_session returned a record).
///        • Sessions where onBundleComplete cleaned the record but dir deletion failed.
///
/// Deletion predicate:
///   • Dir name is a valid lowercase UUID (captures by this app).
///   • The dir was last modified > `minAgeBeforeDelete` seconds ago (race guard: a new
///     capture dir exists for a brief window before its record is written; the age
///     threshold skips dirs that are too fresh to have a record yet).
///   • No UploadSessionRecord exists in the store for that bundle ID.
///
/// Directories whose record still exists (upload in progress or stalled) are NEVER deleted.
///
/// Decisions: 0040 (item 7 durability), 0043 (blob durability, App Support move)

import Foundation

// MARK: - CaptureStorageSweeper

actor CaptureStorageSweeper {

    static let shared = CaptureStorageSweeper()

    // MARK: - Constants

    /// Skip dirs younger than this threshold — a new capture dir exists briefly before
    /// its UploadSessionRecord is written. 300 s is far more conservative than needed
    /// (the POST /upload_session roundtrip takes < 30 s), but is cheap to hold.
    static let minAgeBeforeDelete: TimeInterval = 300

    // MARK: - Stored properties

    private let capturesRoot: URL
    private let store: UploadSessionStore

    // MARK: - Path helper (shared with CaptureManager.makeOutputDir)

    /// Absolute URL of the per-app captures root directory.
    ///
    /// Structure: `<Application Support>/<bundleId>/captures/`
    /// Each session writes to a subdir named after its bundle UUID.
    /// CaptureManager.makeOutputDir appends `/<session-uuid>` to this path.
    static func capturesRootURL() -> URL {
        let appSupport = FileManager.default
            .urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
        return appSupport
            .appendingPathComponent(
                Bundle.main.bundleIdentifier ?? "com.roomstudio.RoomStudioCapture"
            )
            .appendingPathComponent("captures")
    }

    // MARK: - Init

    private init() {
        self.capturesRoot = Self.capturesRootURL()
        self.store        = .shared
    }

    /// Testing init — inject capturesRoot and store.
    init(capturesRoot: URL, store: UploadSessionStore) {
        self.capturesRoot = capturesRoot
        self.store        = store
    }

    // MARK: - Sweep

    /// Delete orphaned capture session directories.
    ///
    /// Safe to call concurrently with running uploads: the actor serializes calls,
    /// and the age threshold + record presence check ensure in-flight dirs are spared.
    func sweep() async {
        guard let entries = try? FileManager.default.contentsOfDirectory(
            at: capturesRoot,
            includingPropertiesForKeys: [.contentModificationDateKey, .isDirectoryKey]
        ) else {
            // captures dir doesn't exist yet — nothing to sweep.
            return
        }

        var deleted = 0
        var skipped = 0

        for entry in entries {
            let name = entry.lastPathComponent

            // Only process directories named like bundle IDs (lowercase UUIDs).
            guard UUID(uuidString: name) != nil else { continue }

            // Race guard: skip dirs created or modified too recently.
            // A new capture dir is created before its record is persisted;
            // the age threshold ensures we don't delete it mid-write.
            let values = try? entry.resourceValues(
                forKeys: [.contentModificationDateKey, .isDirectoryKey]
            )
            guard values?.isDirectory == true else { continue }
            if let modDate = values?.contentModificationDate,
               Date().timeIntervalSince(modDate) < Self.minAgeBeforeDelete {
                skipped += 1
                continue
            }

            // Delete if no store record exists for this bundle ID.
            let hasRecord = (try? await store.load(bundleId: name)) != nil
            if !hasRecord {
                try? FileManager.default.removeItem(at: entry)
                deleted += 1
                print("[CaptureStorageSweeper] deleted orphaned session dir: \(name)")
            }
        }

        if deleted > 0 || skipped > 0 {
            print("[CaptureStorageSweeper] sweep complete — deleted: \(deleted), skipped (too recent): \(skipped)")
        }
    }
}
