/// The capture bundle's timeline as it goes on the wire (decision 0298).
///
/// The privacy manifest declares SystemBootTime with 35F9.1 alone, whose terms
/// let only elapsed time between events in the app leave the device. A
/// device-monotonic reading counts from boot, so BundleAssembler writes the
/// capture window and every frame timestamp relative to capture start. Pinned
/// through a written bundle.pb rather than the arithmetic, because what leaves
/// the device is what the declaration is about.

import SwiftProtobuf
import XCTest
@testable import TheGoodGuest

final class BundleClockTests: XCTestCase {

    /// A day of uptime at capture start — far larger than any capture, so a
    /// reading that reached the wire as taken could not pass for an offset.
    private let startUs: Int64 = 86_400_000_000

    func test_bundleAssembler_writesTheTimelineFromCaptureStart() throws {
        let dir = FileManager.default.temporaryDirectory
            .appendingPathComponent("bundle-clock-test-\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: dir) }

        let assembler = BundleAssembler(
            bundleId:          UUID(),
            tier:              .arkitOnly,
            startedAtDeviceUs: startUs,
            endedAtDeviceUs:   startUs + 42_000_000,
            startedAtWallUs:   1_789_000_000_000_000,
            frames:            [keyframe(0, atDeviceUs: startUs + 500_000),
                                keyframe(1, atDeviceUs: startUs + 1_250_000)],
            planeAnchors:      [],
            roomPlan:          nil,
            outputDir:         dir
        )
        let url = try assembler.write(userId: "test-user")
        let parsed = try RSCaptureBundle(serializedBytes: Data(contentsOf: url))

        XCTAssertEqual(parsed.startedAtDeviceUs, 0, "capture start is the origin")
        XCTAssertEqual(parsed.endedAtDeviceUs, 42_000_000, "the end is the capture's duration")
        XCTAssertEqual(parsed.frames.map(\.timestampUs), [500_000, 1_250_000],
                       "each frame is its offset into the capture")
        // The wall clock is not a boot-time reading, and goes on the wire as taken.
        XCTAssertEqual(parsed.startedAtWallUs, 1_789_000_000_000_000)
    }

    private func keyframe(_ index: UInt32, atDeviceUs deviceUs: Int64) -> CapturedKeyframe {
        CapturedKeyframe(
            index:           index,
            timestampUs:     deviceUs,
            rgbRelativePath: String(format: "frames/%06d.jpg", index),
            pose:            RSPose(),
            intrinsics:      RSIntrinsics(),
            gravity:         RSGravity(),
            depth:           nil
        )
    }
}
