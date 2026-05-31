/// Unit tests for ManifestBuilder.
///
/// Creates on-disk fixture directories in a temp location, calls
/// ManifestBuilder.build(outputDir:), and asserts invariants.
/// No network, no Firebase — runs on the simulator with no special setup.

import XCTest
@testable import RoomStudioCapture

final class ManifestBuilderTests: XCTestCase {

    private var tempDir: URL!

    override func setUpWithError() throws {
        // Fresh temp directory for each test.
        tempDir = FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(
            at: tempDir, withIntermediateDirectories: true)
    }

    override func tearDownWithError() throws {
        try? FileManager.default.removeItem(at: tempDir)
    }

    // MARK: - Helpers

    private func makeDir(_ subdir: String) throws {
        try FileManager.default.createDirectory(
            at: tempDir.appendingPathComponent(subdir),
            withIntermediateDirectories: true)
    }

    private func writeFile(_ path: String, bytes: Int) throws {
        let url  = tempDir.appendingPathComponent(path)
        let data = Data(repeating: 0xAB, count: bytes)
        try data.write(to: url)
    }

    // MARK: - Tests

    func test_framesOnly_orderedAndBundleLast() throws {
        try makeDir("frames")
        try writeFile("frames/000002.jpg", bytes: 300)
        try writeFile("frames/000000.jpg", bytes: 100)
        try writeFile("frames/000001.jpg", bytes: 200)
        try writeFile("bundle.pb",         bytes: 50)

        let manifest = try ManifestBuilder.build(outputDir: tempDir)

        XCTAssertEqual(manifest.count, 4)
        // Frame order is lexicographic (= index order for zero-padded names).
        XCTAssertEqual(manifest[0].relativePath, "frames/000000.jpg")
        XCTAssertEqual(manifest[1].relativePath, "frames/000001.jpg")
        XCTAssertEqual(manifest[2].relativePath, "frames/000002.jpg")
        // bundle.pb is always last.
        XCTAssertEqual(manifest[3].relativePath, "bundle.pb")
    }

    func test_expectedSizeBytes_matchActualFileSize() throws {
        try makeDir("frames")
        try writeFile("frames/000000.jpg", bytes: 1234)
        try writeFile("bundle.pb",         bytes: 567)

        let manifest = try ManifestBuilder.build(outputDir: tempDir)

        XCTAssertEqual(manifest[0].expectedSizeBytes, 1234)
        XCTAssertEqual(manifest.last?.expectedSizeBytes, 567)
    }

    func test_lidarArtifacts_includedWhenPresent() throws {
        try makeDir("frames")
        try makeDir("depth")
        try makeDir("confidence")
        try writeFile("frames/000000.jpg",      bytes: 100)
        try writeFile("depth/000000.f32",       bytes: 200)
        try writeFile("confidence/000000.png",  bytes: 50)
        try writeFile("bundle.pb",              bytes: 40)

        let manifest = try ManifestBuilder.build(outputDir: tempDir)

        let paths = manifest.map(\.relativePath)
        XCTAssertTrue(paths.contains("frames/000000.jpg"))
        XCTAssertTrue(paths.contains("depth/000000.f32"))
        XCTAssertTrue(paths.contains("confidence/000000.png"))
        XCTAssertEqual(paths.last, "bundle.pb")
    }

    func test_missingDepthDir_silentlySkipped() throws {
        // Only frames + bundle.pb — no depth/ directory at all.
        try makeDir("frames")
        try writeFile("frames/000000.jpg", bytes: 100)
        try writeFile("bundle.pb",         bytes: 40)

        let manifest = try ManifestBuilder.build(outputDir: tempDir)

        let paths = manifest.map(\.relativePath)
        XCTAssertFalse(paths.contains { $0.hasPrefix("depth/") })
        XCTAssertEqual(paths.last, "bundle.pb")
    }

    func test_noLeadingSlashOnRelativePaths() throws {
        try makeDir("frames")
        try writeFile("frames/000000.jpg", bytes: 100)
        try writeFile("bundle.pb",         bytes: 40)

        let manifest = try ManifestBuilder.build(outputDir: tempDir)

        for entry in manifest {
            XCTAssertFalse(entry.relativePath.hasPrefix("/"),
                           "relative_path must not start with '/': \(entry.relativePath)")
            XCTAssertFalse(entry.relativePath.hasPrefix("gs://"),
                           "relative_path must not be a GCS URI: \(entry.relativePath)")
        }
    }

    func test_noDoubleDotComponents() throws {
        try makeDir("frames")
        try writeFile("frames/000000.jpg", bytes: 100)
        try writeFile("bundle.pb",         bytes: 40)

        let manifest = try ManifestBuilder.build(outputDir: tempDir)

        for entry in manifest {
            XCTAssertFalse(entry.relativePath.contains(".."),
                           "relative_path must not contain '..': \(entry.relativePath)")
        }
    }

    func test_onlyMatchingExtensionsIncluded() throws {
        // Write a .txt file in frames/ — should not appear in the manifest.
        try makeDir("frames")
        try writeFile("frames/000000.jpg",     bytes: 100)
        try writeFile("frames/000000.txt",     bytes: 10)   // noise
        try writeFile("frames/.hidden.jpg",    bytes: 10)   // hidden — skipped by options
        try writeFile("bundle.pb",             bytes: 40)

        let manifest = try ManifestBuilder.build(outputDir: tempDir)

        let paths = manifest.map(\.relativePath)
        XCTAssertFalse(paths.contains("frames/000000.txt"))
        XCTAssertTrue(paths.contains("frames/000000.jpg"))
    }

    func test_bundlePbMissing_throws() throws {
        try makeDir("frames")
        try writeFile("frames/000000.jpg", bytes: 100)
        // No bundle.pb written.

        XCTAssertThrowsError(try ManifestBuilder.build(outputDir: tempDir)) { error in
            guard case ManifestBuilder.BuildError.bundlePbMissing = error else {
                XCTFail("Expected bundlePbMissing, got \(error)")
                return
            }
        }
    }

    func test_emptyFramesDir_bundlePbOnly() throws {
        // Empty frames dir — only bundle.pb in the manifest.
        try makeDir("frames")
        try writeFile("bundle.pb", bytes: 40)

        let manifest = try ManifestBuilder.build(outputDir: tempDir)

        XCTAssertEqual(manifest.count, 1)
        XCTAssertEqual(manifest[0].relativePath, "bundle.pb")
    }

    func test_multipleFrames_correctCount() throws {
        try makeDir("frames")
        for i in 0..<10 {
            try writeFile(String(format: "frames/%06d.jpg", i), bytes: 50 + i)
        }
        try writeFile("bundle.pb", bytes: 40)

        let manifest = try ManifestBuilder.build(outputDir: tempDir)

        // 10 frames + 1 bundle.pb
        XCTAssertEqual(manifest.count, 11)
        XCTAssertEqual(manifest.last?.relativePath, "bundle.pb")
    }
}
