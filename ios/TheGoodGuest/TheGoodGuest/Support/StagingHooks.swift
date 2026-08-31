/// DEBUG-only staging hooks for on-device failure/lifecycle verification.
///
/// WHY THIS EXISTS: three of the app's terminal surfaces (failed_invalid,
/// failed_incomplete, the blob-fatal banner) and the OS-kill relaunch route
/// (decision 0045 Fork A) cannot be triggered on demand by honest use — they
/// need a sabotaged upload or a process death at a precise moment. These hooks
/// stage exactly that, while running the REAL machinery end-to-end: the fakes
/// are injected as ordinary completions through handleTaskCompletion, so
/// classification, sibling cancellation, persistence, and the backend's own
/// validation all execute for real. Compiled out of release builds entirely.
///
/// FLAGS — read from a JSON file the Mac can write into the app container
/// (`Documents/rs-staging.json`, via `devicectl device copy to`), with
/// UserDefaults (`-rs.staging.* value` launch arguments) as fallback:
///
///   corruptFrame:  "frames/000000.jpg" — overwrite that blob with garbage of
///                  the SAME byte length before the manifest is built. Ingest's
///                  decodability gate then fast-fails the bundle → failed_invalid.
///   dropBlob:      "frames/000001.jpg" — feed a fake 200 through the real
///                  completion path instead of PUTting. The client's Phase-1
///                  gate opens honestly, bundle.pb lands, and the backend finds
///                  the path missing → failed_incomplete with that exact path.
///   fatalBlob:     "frames/000002.jpg" — feed a fake 404: TERMINAL
///                  classification, sibling-task cancellation across the live
///                  concurrent PUTs, `.failed` + reason persisted → banner.
///   suspendBundlePb: true — create the bundle.pb PUT task and never call
///                  resume(). An in-process suspend() is ignored by
///                  nsurlsessiond on a background session (measured on device
///                  2026-08-08), so withholding resume is what actually
///                  produces "enqueued, not landed" — and it holds, rather
///                  than for a sub-second window no human can hit. A
///                  force-quit + reopen then exercises the relaunch-recovery
///                  route deterministically; the relaunch re-enqueues and
///                  resumes normally.
///   exitAfterCompletions: N — abrupt exit(0) after the Nth successful blob
///                  completion: an OS-kill-shaped death with sibling transfers
///                  in flight, for the background-relaunch (.task fires?) probe.
///
/// ONE-SHOT: the flags file is deleted (and the UserDefaults keys cleared) the
/// moment any hook fires, so the relaunch that follows behaves production-true.
///
/// BREADCRUMBS: append-only file at
/// `Application Support/<bundle-id>/staging/breadcrumbs.log` (CAFUFA), written
/// at lifecycle points (app-init, the rehydrate .task, the AppDelegate
/// background-relaunch hook, staged kills). Files, not os_log, on purpose: the
/// OS-kill route's logs are buffered/coalesced under suspension (the Anomaly-B
/// lesson) and the Mac can pull this file over `devicectl device copy from`
/// without the phone in hand.
///
/// Read by: BlobUploadManager (drop/fatal/suspend/exit hooks), RootFlowView
/// (pre-send sabotage), TheGoodGuestApp + AppDelegate (breadcrumbs).
/// Pinned by: StagingHooksTests.

#if DEBUG

import Foundation
import os

/// nonisolated: called from the BlobUploadManager actor, MainActor views, and
/// App/AppDelegate init paths alike; internal serialisation via `ioQueue`.
nonisolated enum StagingHooks {

    // MARK: - Locations (overridable for tests)

    /// The flags file. Tests point this at a temp dir; production resolves
    /// Documents/rs-staging.json lazily.
    static let _flagsFileOverride = OSAllocatedUnfairLock<URL?>(initialState: nil)
    /// The breadcrumbs file. Same override pattern.
    static let _breadcrumbFileOverride = OSAllocatedUnfairLock<URL?>(initialState: nil)

    private static var flagsFileURL: URL {
        if let override = _flagsFileOverride.withLock({ $0 }) { return override }
        return FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("rs-staging.json")
    }

    private static var breadcrumbFileURL: URL {
        if let override = _breadcrumbFileOverride.withLock({ $0 }) { return override }
        let dir = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
            .appendingPathComponent(Bundle.main.bundleIdentifier ?? "com.thegoodguest.TheGoodGuest")
            .appendingPathComponent("staging")
        return dir.appendingPathComponent("breadcrumbs.log")
    }

    /// Serialises breadcrumb appends across actors/threads.
    private static let ioQueue = DispatchQueue(label: "com.thegoodguest.staging.io", qos: .utility)

    private static let logger = Logger(subsystem: "com.thegoodguest.TheGoodGuest", category: "Staging")

    // MARK: - Flag reads

    private static let defaultsKeys = [
        "rs.staging.corruptFrame", "rs.staging.dropBlob", "rs.staging.fatalBlob",
        "rs.staging.suspendBundlePb", "rs.staging.exitAfterCompletions",
    ]

    private static func flags() -> [String: Any] {
        guard let data = try? Data(contentsOf: flagsFileURL),
              let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any]
        else { return [:] }
        return json
    }

    private static func stringFlag(_ key: String) -> String? {
        if let value = flags()[key] as? String, !value.isEmpty { return value }
        if let value = UserDefaults.standard.string(forKey: "rs.staging.\(key)"), !value.isEmpty { return value }
        return nil
    }

    static func corruptFramePath() -> String? { stringFlag("corruptFrame") }
    static func dropBlobPath()     -> String? { stringFlag("dropBlob") }
    static func fatalBlobPath()    -> String? { stringFlag("fatalBlob") }

    static func suspendBundlePb() -> Bool {
        if let value = flags()["suspendBundlePb"] as? Bool { return value }
        return UserDefaults.standard.bool(forKey: "rs.staging.suspendBundlePb")
    }

    static func exitAfterCompletions() -> Int? {
        if let value = flags()["exitAfterCompletions"] as? Int, value > 0 { return value }
        let fromDefaults = UserDefaults.standard.integer(forKey: "rs.staging.exitAfterCompletions")
        return fromDefaults > 0 ? fromDefaults : nil
    }

    // MARK: - One-shot consume

    /// Delete the flags file and clear the UserDefaults keys. Called by the
    /// site that FIRED a hook, so the relaunch behaves production-true.
    static func consume() {
        try? FileManager.default.removeItem(at: flagsFileURL)
        for key in defaultsKeys { UserDefaults.standard.removeObject(forKey: key) }
    }

    // MARK: - Pre-send sabotage (failed_invalid staging)

    /// If corruptFrame is requested and the file exists, overwrite it with
    /// garbage of the SAME byte length (the manifest's expected_size_bytes is
    /// read from disk at send time, so size honesty is preserved — only the
    /// pixel content becomes undecodable). One-shot.
    static func applyPreSendSabotage(outputDir: URL?) {
        guard let outputDir, let relativePath = corruptFramePath() else { return }
        let fileURL = outputDir.appendingPathComponent(relativePath)
        guard let size = try? fileURL.resourceValues(forKeys: [.fileSizeKey]).fileSize, size > 0 else {
            logger.info("[StagingHooks] corruptFrame requested but \(relativePath, privacy: .public) unreadable — skipping")
            return
        }
        var garbage = Data(capacity: size)
        var seed: UInt64 = 0x5eed_c0de_d00d_f00d
        for _ in 0..<size {
            seed = seed &* 6364136223846793005 &+ 1442695040888963407
            garbage.append(UInt8(truncatingIfNeeded: seed >> 33))
        }
        do {
            try garbage.write(to: fileURL, options: .completeFileProtectionUntilFirstUserAuthentication)
            breadcrumb("staging corrupt-frame \(relativePath) (\(size)B)")
            logger.info("[StagingHooks] ✂ corrupted \(relativePath, privacy: .public) (\(size)B, same length)")
        } catch {
            logger.info("[StagingHooks] corruptFrame write failed: \(error.localizedDescription)")
        }
        consume()
    }

    // MARK: - Staged OS-kill counter

    private static let successCount = OSAllocatedUnfairLock<Int>(initialState: 0)

    /// Called after each successful non-bundle.pb blob completion. When the
    /// exitAfterCompletions target is reached: breadcrumb, consume, exit(0) —
    /// an OS-kill-shaped abrupt death with sibling transfers still in flight.
    static func noteBlobSuccessAndMaybeExit() {
        guard let target = exitAfterCompletions() else { return }
        let count = successCount.withLock { (n: inout Int) -> Int in
            n += 1
            return n
        }
        guard count >= target else { return }
        breadcrumbSync("staging staged-os-kill after \(count) completions")
        consume()
        exit(0)
    }

    // MARK: - Breadcrumbs

    /// Append a timestamped line (async — normal call sites).
    static func breadcrumb(_ event: String) {
        let line = "\(ISO8601DateFormatter().string(from: Date())) \(event)\n"
        ioQueue.async { appendLine(line) }
    }

    /// Synchronous variant for call sites that terminate the process next.
    static func breadcrumbSync(_ event: String) {
        let line = "\(ISO8601DateFormatter().string(from: Date())) \(event)\n"
        ioQueue.sync { appendLine(line) }
    }

    private static func appendLine(_ line: String) {
        let url = breadcrumbFileURL
        let fm = FileManager.default
        if !fm.fileExists(atPath: url.path) {
            try? fm.createDirectory(
                at: url.deletingLastPathComponent(),
                withIntermediateDirectories: true,
                attributes: [.protectionKey: FileProtectionType.completeUntilFirstUserAuthentication]
            )
            fm.createFile(atPath: url.path, contents: nil, attributes: [
                .protectionKey: FileProtectionType.completeUntilFirstUserAuthentication,
            ])
        }
        guard let handle = try? FileHandle(forWritingTo: url) else { return }
        defer { try? handle.close() }
        _ = try? handle.seekToEnd()
        try? handle.write(contentsOf: Data(line.utf8))
    }
}

#endif
