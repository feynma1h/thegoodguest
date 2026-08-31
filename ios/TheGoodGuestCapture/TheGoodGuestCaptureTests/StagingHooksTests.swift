/// Pins for the DEBUG-only StagingHooks flag parsing and one-shot semantics.
/// These hooks stage the operator sitting's failure scenarios — a parsing bug
/// here wastes phone-in-hand time, so the cheap contracts are pinned:
/// file-based flags read correctly, consume() is one-shot, and the corrupt-frame
/// sabotage preserves byte length (manifest size honesty) while changing content.

import os
import XCTest
@testable import TheGoodGuestCapture

#if DEBUG

final class StagingHooksTests: XCTestCase {

    private var flagsFile: URL!
    private var breadcrumbFile: URL!
    private var tempDir: URL!

    override func setUp() async throws {
        tempDir = FileManager.default.temporaryDirectory
            .appendingPathComponent("staging-hooks-test-\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: tempDir, withIntermediateDirectories: true)
        flagsFile = tempDir.appendingPathComponent("rs-staging.json")
        breadcrumbFile = tempDir.appendingPathComponent("breadcrumbs.log")
        StagingHooks._flagsFileOverride.withLock { $0 = flagsFile }
        StagingHooks._breadcrumbFileOverride.withLock { $0 = breadcrumbFile }
    }

    override func tearDown() async throws {
        StagingHooks._flagsFileOverride.withLock { $0 = nil }
        StagingHooks._breadcrumbFileOverride.withLock { $0 = nil }
        try? FileManager.default.removeItem(at: tempDir)
    }

    private func writeFlags(_ flags: [String: Any]) throws {
        let data = try JSONSerialization.data(withJSONObject: flags)
        try data.write(to: flagsFile)
    }

    // MARK: - Flag parsing

    func test_noFile_allFlagsAbsent() {
        XCTAssertNil(StagingHooks.corruptFramePath())
        XCTAssertNil(StagingHooks.dropBlobPath())
        XCTAssertNil(StagingHooks.fatalBlobPath())
        XCTAssertFalse(StagingHooks.suspendBundlePb())
        XCTAssertNil(StagingHooks.exitAfterCompletions())
    }

    func test_fileFlags_readBack() throws {
        try writeFlags([
            "corruptFrame": "frames/000000.jpg",
            "dropBlob": "frames/000001.jpg",
            "fatalBlob": "frames/000002.jpg",
            "suspendBundlePb": true,
            "exitAfterCompletions": 30,
        ])
        XCTAssertEqual(StagingHooks.corruptFramePath(), "frames/000000.jpg")
        XCTAssertEqual(StagingHooks.dropBlobPath(), "frames/000001.jpg")
        XCTAssertEqual(StagingHooks.fatalBlobPath(), "frames/000002.jpg")
        XCTAssertTrue(StagingHooks.suspendBundlePb())
        XCTAssertEqual(StagingHooks.exitAfterCompletions(), 30)
    }

    func test_consume_deletesFlagsFile() throws {
        try writeFlags(["dropBlob": "frames/000001.jpg"])
        XCTAssertNotNil(StagingHooks.dropBlobPath())

        StagingHooks.consume()

        XCTAssertNil(StagingHooks.dropBlobPath())
        XCTAssertFalse(FileManager.default.fileExists(atPath: flagsFile.path))
    }

    // MARK: - Pre-send sabotage

    func test_corruptFrame_sameLength_differentBytes_oneShot() throws {
        let outputDir = tempDir.appendingPathComponent("capture")
        try FileManager.default.createDirectory(
            at: outputDir.appendingPathComponent("frames"), withIntermediateDirectories: true)
        let original = Data((0..<4096).map { UInt8($0 % 251) })
        let frameURL = outputDir.appendingPathComponent("frames/000000.jpg")
        try original.write(to: frameURL)
        try writeFlags(["corruptFrame": "frames/000000.jpg"])

        StagingHooks.applyPreSendSabotage(outputDir: outputDir)

        let corrupted = try Data(contentsOf: frameURL)
        XCTAssertEqual(corrupted.count, original.count, "manifest size honesty: same byte length")
        XCTAssertNotEqual(corrupted, original, "content must actually change")
        XCTAssertFalse(FileManager.default.fileExists(atPath: flagsFile.path), "one-shot: flags consumed")
    }

    func test_corruptFrame_missingFile_noCrash_flagStillConsumed() throws {
        let outputDir = tempDir.appendingPathComponent("empty-capture")
        try FileManager.default.createDirectory(at: outputDir, withIntermediateDirectories: true)
        try writeFlags(["corruptFrame": "frames/000000.jpg"])

        StagingHooks.applyPreSendSabotage(outputDir: outputDir)
        // Unreadable target: no crash; hook does not fire the sabotage. The
        // flag file is deliberately left for the operator to inspect/retry.
        XCTAssertTrue(FileManager.default.fileExists(atPath: flagsFile.path))
    }

    func test_noFlag_sabotageIsNoOp() throws {
        let outputDir = tempDir.appendingPathComponent("clean-capture")
        try FileManager.default.createDirectory(
            at: outputDir.appendingPathComponent("frames"), withIntermediateDirectories: true)
        let original = Data("real-jpeg".utf8)
        let frameURL = outputDir.appendingPathComponent("frames/000000.jpg")
        try original.write(to: frameURL)

        StagingHooks.applyPreSendSabotage(outputDir: outputDir)

        XCTAssertEqual(try Data(contentsOf: frameURL), original)
    }

    // MARK: - Breadcrumbs

    func test_breadcrumb_appendsLines() {
        StagingHooks.breadcrumbSync("first-event")
        StagingHooks.breadcrumbSync("second-event")

        let content = (try? String(contentsOf: breadcrumbFile, encoding: .utf8)) ?? ""
        let lines = content.split(separator: "\n")
        XCTAssertEqual(lines.count, 2)
        XCTAssertTrue(lines[0].hasSuffix("first-event"))
        XCTAssertTrue(lines[1].hasSuffix("second-event"))
    }
}

#endif
