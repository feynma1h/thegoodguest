/// Builds the upload manifest from a completed capture output directory.
///
/// Called after BundleAssembler.write() — bundle.pb must already be on disk
/// before calling build(outputDir:), because bundle.pb is included in the
/// manifest and its size is read here.
///
/// relative_path values produced here must exactly match the GCS-relative
/// paths stored in the bundle proto (e.g. "frames/000000.jpg"). They are the
/// idempotency key on the server side: the same path-set → same session URIs.
///
/// bundle.pb is always appended last so the caller (UploadCoordinator, via
/// BlobUploadManager) can upload it last, which signals ingest completion
/// to api-internal.
///
/// Read by: UploadCoordinator, ManifestBuilderTests.

import Foundation

enum ManifestBuilder {

    enum BuildError: LocalizedError {
        case bundlePbMissing(URL)

        var errorDescription: String? {
            switch self {
            case .bundlePbMissing(let url):
                return "bundle.pb not found at \(url.path). Call BundleAssembler.write() first."
            }
        }
    }

    /// Enumerate all uploadable artifacts in outputDir and return a manifest
    /// suitable for POST /upload_session.
    ///
    /// Order within each subdirectory is lexicographic (frame index order).
    /// bundle.pb is always the final entry.
    static func build(outputDir: URL) throws -> [UploadManifestEntry] {
        let fm = FileManager.default
        var entries: [UploadManifestEntry] = []

        // Blob subdirectories, in canonical order.
        // depth/ and confidence/ are LiDAR-only; roomplan/ exists only when a
        // built CapturedRoom shipped (decision 0077). Skipped silently if absent
        // — like every other blob, roomplan files are phase-1 uploads gated
        // before bundle.pb by BlobUploadManager.
        let blobDirs: [(subdir: String, ext: String)] = [
            ("frames",     "jpg"),
            ("depth",      "f32"),
            ("confidence", "png"),
            ("roomplan",   "json"),
            ("roomplan",   "usdz"),
        ]

        for (subdir, ext) in blobDirs {
            let dirURL = outputDir.appendingPathComponent(subdir)
            guard fm.fileExists(atPath: dirURL.path) else { continue }

            let files = try fm.contentsOfDirectory(
                at: dirURL,
                includingPropertiesForKeys: [.fileSizeKey],
                options: .skipsHiddenFiles
            )
            let matching = files
                .filter { $0.pathExtension == ext }
                .sorted { $0.lastPathComponent < $1.lastPathComponent }

            for fileURL in matching {
                let size = (try? fileURL.resourceValues(forKeys: [.fileSizeKey]).fileSize) ?? 0
                entries.append(UploadManifestEntry(
                    relativePath: "\(subdir)/\(fileURL.lastPathComponent)",
                    expectedSizeBytes: size
                ))
            }
        }

        // bundle.pb — validated present, always last.
        let bundleURL = outputDir.appendingPathComponent("bundle.pb")
        guard fm.fileExists(atPath: bundleURL.path) else {
            throw BuildError.bundlePbMissing(bundleURL)
        }
        let bundleSize = (try? bundleURL.resourceValues(forKeys: [.fileSizeKey]).fileSize) ?? 0
        entries.append(UploadManifestEntry(
            relativePath: "bundle.pb",
            expectedSizeBytes: bundleSize
        ))

        return entries
    }
}
