/// Tests for CaptureManager output directory location and protection attributes.
///
/// Decision 0043: capture blobs must live in Application Support (not temporaryDirectory)
/// with isExcludedFromBackup set and CAFUFA protection so blobs survive kill/relaunch
/// across the full upload window.
///
/// Note: CaptureManager requires ARSession which doesn't run on the simulator.
/// startCapture() is called only to trigger makeOutputDir; the AR session setup
/// fails silently on simulator — bundleOutputDir is still set before arSession.run().

import XCTest
@testable import TheGoodGuest

@MainActor
final class CaptureManagerTests: XCTestCase {

    private var manager: CaptureManager!

    override func setUp() async throws {
        manager = CaptureManager()
    }

    override func tearDown() async throws {
        // Clean up the session dir created by startCapture.
        if let dir = manager.bundleOutputDir {
            try? FileManager.default.removeItem(at: dir)
        }
    }

    // MARK: - Output directory location (decision 0043)

    func test_startCapture_outputDirIsUnderApplicationSupport() {
        manager.startCapture()
        guard let outputDir = manager.bundleOutputDir else {
            XCTFail("bundleOutputDir must be set after startCapture()")
            return
        }
        let appSupport = FileManager.default
            .urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
        XCTAssertTrue(
            outputDir.path.hasPrefix(appSupport.path),
            "Output dir must be under Application Support, not tmp. Got: \(outputDir.path)"
        )
    }

    func test_startCapture_outputDirIsNotUnderTemporaryDirectory() {
        manager.startCapture()
        guard let outputDir = manager.bundleOutputDir else {
            XCTFail("bundleOutputDir must be set after startCapture()")
            return
        }
        let tmp = FileManager.default.temporaryDirectory
        XCTAssertFalse(
            outputDir.path.hasPrefix(tmp.path),
            "Output dir must NOT be in temporaryDirectory (purged while app is not running). Got: \(outputDir.path)"
        )
    }

    func test_startCapture_outputDirNameMatchesBundleId() {
        manager.startCapture()
        guard let outputDir = manager.bundleOutputDir else {
            XCTFail("bundleOutputDir must be set after startCapture()")
            return
        }
        // The session dir name must equal the lowercased bundle UUID so the sweep
        // can look up the matching store record by dir name (decision 0043).
        XCTAssertEqual(
            outputDir.lastPathComponent, manager.bundleIdString,
            "Session dir name must match bundleIdString for sweep lookup"
        )
    }

    func test_startCapture_outputDirIsUnderCapturesSubdir() {
        manager.startCapture()
        guard let outputDir = manager.bundleOutputDir else {
            XCTFail("bundleOutputDir must be set after startCapture()")
            return
        }
        // Parent of the session dir must be the "captures" directory.
        let parent = outputDir.deletingLastPathComponent()
        XCTAssertEqual(
            parent.lastPathComponent, "captures",
            "Session dir must be a direct child of the 'captures' directory"
        )
    }

    func test_startCapture_outputDirExistsOnDisk() {
        manager.startCapture()
        guard let outputDir = manager.bundleOutputDir else {
            XCTFail("bundleOutputDir must be set after startCapture()")
            return
        }
        XCTAssertTrue(
            FileManager.default.fileExists(atPath: outputDir.path),
            "Output directory must be created on disk by startCapture()"
        )
    }

    // MARK: - isExcludedFromBackup (decision 0043)

    func test_startCapture_outputDirIsExcludedFromBackup() throws {
        manager.startCapture()
        guard let outputDir = manager.bundleOutputDir else {
            XCTFail("bundleOutputDir must be set after startCapture()")
            return
        }
        let values = try outputDir.resourceValues(forKeys: [.isExcludedFromBackupKey])
        XCTAssertEqual(
            values.isExcludedFromBackup, true,
            "Output dir must have isExcludedFromBackup=true: capture blobs are large and regenerable"
        )
    }

    // MARK: - Cold-relaunch path

    func test_startCapture_outputDirMatchesCapturesRootURL() {
        manager.startCapture()
        guard let outputDir = manager.bundleOutputDir else {
            XCTFail("bundleOutputDir must be set after startCapture()")
            return
        }
        // The captures root used by CaptureStorageSweeper must agree with the path
        // used by makeOutputDir — both call CaptureStorageSweeper.capturesRootURL().
        let expectedParent = CaptureStorageSweeper.capturesRootURL()
        XCTAssertEqual(
            outputDir.deletingLastPathComponent().standardized,
            expectedParent.standardized,
            "Session dir parent must equal CaptureStorageSweeper.capturesRootURL()"
        )
    }
}
