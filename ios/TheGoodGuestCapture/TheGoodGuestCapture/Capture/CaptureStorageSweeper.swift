/// Startup sweep that reclaims orphaned capture session directories from Application Support.
///
/// Capture blobs are written to `<App Support>/<app-bundle-id>/captures/<session-uuid>/` (decision 0043).
/// That location does NOT auto-purge the way `temporaryDirectory` does. Two mechanisms bound
/// disk growth:
///
///   1. CaptureReaper (decision 0084) — terminal-state reclaim. Deletes the
///      UploadSessionRecord and the session dir when a genuinely terminal
///      outcome has been shown to the user (flight end) or confirmed at the
///      launch scan. NOT on mere upload success — failed_incomplete keeps its
///      files. Deletes record FIRST, dir second, so a crash between the two
///      lands in this sweeper's case below.
///
///   2. CaptureStorageSweeper.sweep() — startup safety net.
///      On app launch, deletes any session dir whose store record is absent. This catches:
///        • Abandoned captures (app killed before POST /upload_session returned a record).
///        • Sessions where CaptureReaper deleted the record but crashed before the dir.
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
/// A third mechanism, sweepDeadRecords() (run first inside sweep()), reclaims the
/// mirror-image orphan: a record FILE that fails the strict decode AND has no
/// surviving capture directory — see the method doc and decision 0074.
///
/// Decisions: 0043 (sweep design, race guard, 300s threshold), 0074 (dead-record sweep)

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
    /// Structure: `<Application Support>/<app-bundle-id>/captures/`
    /// Each session writes to a subdir named after its bundle UUID.
    /// CaptureManager.makeOutputDir appends `/<session-uuid>` to this path.
    static func capturesRootURL() -> URL {
        let appSupport = FileManager.default
            .urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
        return appSupport
            .appendingPathComponent(
                Bundle.main.bundleIdentifier ?? "com.thegoodguest.TheGoodGuestCapture"
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

    /// Delete orphaned capture session directories, and dead record files.
    ///
    /// Safe to call concurrently with running uploads: the age threshold and the
    /// record-presence check ensure in-flight dirs are spared.
    func sweep() async {
        // Record sweep FIRST: an undecodable record cannot protect its dir from the
        // dir pass below (load() throws → hasRecord false), so running the record
        // pass first means each pass judges the disk as it found it — an
        // undecodable record whose dir still exists is KEPT this launch, and only
        // reclaimed on a later launch once the dir is genuinely gone.
        await sweepDeadRecords()

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

    // MARK: - Dead-record sweep (decision 0074, cosmetic sibling)

    /// Reclaim record FILES that are dead to every consumer.
    ///
    /// Deletion predicate — BOTH must hold:
    ///   • The record fails the strict decode (pre-P5 legacy or corrupt): invisible
    ///     to restore, rehydration, and the failure monitor alike, since all read
    ///     through load(). A decodable record is live machinery and is never touched
    ///     here, whatever its phase.
    ///   • No capture directory survives for it — neither at the conventional
    ///     location (capturesRoot/<bundle-id>) nor at the outputDir the record's
    ///     JSON names, so there is nothing a future re-upload could use.
    ///
    /// Anything else is left in place. First real population: the 34 June-era
    /// records an iCloud backup migrated to the 16 Pro (decision 0074) — records
    /// migrate, blobs do not, so they arrive already dirless.
    private func sweepDeadRecords() async {
        let dead = await store.undecodableRecords()
        guard !dead.isEmpty else { return }

        var reclaimed = 0
        for record in dead {
            var candidatePaths = [capturesRoot.appendingPathComponent(record.bundleId).path]
            if let raw = record.outputDirPath {
                // Codable encodes URL as absoluteString ("file:///…"); accept a bare
                // path too in case an older writer stored one.
                if let url = URL(string: raw), url.isFileURL { candidatePaths.append(url.path) }
                candidatePaths.append(raw)
            }
            guard !candidatePaths.contains(where: { FileManager.default.fileExists(atPath: $0) }) else {
                continue
            }
            try? await store.delete(bundleId: record.bundleId)
            reclaimed += 1
            print("[CaptureStorageSweeper] reclaimed dead record (undecodable, no capture dir): \(record.bundleId)")
        }

        if reclaimed > 0 {
            print("[CaptureStorageSweeper] dead-record sweep complete — reclaimed: \(reclaimed) of \(dead.count) undecodable")
        }
    }
}
