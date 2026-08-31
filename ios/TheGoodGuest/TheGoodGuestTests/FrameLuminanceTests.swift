/// Pins for the per-keyframe luminance statistic and its session census.
///
/// Two kinds of test here. The statistic is pinned on synthetic planes, so the
/// video-range rescale and the buffer-geometry guards are reviewable as a table.
/// The census is pinned on the REAL mean-luma readings of the preserved rp6g2
/// capture — the one that shipped 28 blank keyframes without anything saying so
/// (decisions 0234/0235/0240). That fixture is the point: the census has to make
/// that capture legible at the moment it is recorded, not weeks later offline.
///
/// No ARKit and no CoreVideo buffers; simulator-safe.

import CoreVideo
import XCTest
@testable import TheGoodGuest

final class FrameLuminanceTests: XCTestCase {

    // MARK: - meanLuma, synthetic planes

    /// A plane of a single value reads back as that value on the full-range scale.
    func test_meanLuma_fullRange_uniformPlane() throws {
        let bytes = [UInt8](repeating: 200, count: 64 * 64)
        let mean = bytes.withUnsafeBytes {
            FrameLuminance.meanLuma(
                plane: $0, width: 64, height: 64, bytesPerRow: 64,
                range: .full, rowStride: 1)
        }
        XCTAssertEqual(try XCTUnwrap(mean), 200, accuracy: 1e-4)
    }

    /// Video range puts black at 16 and white at 235. A studio-swing black frame
    /// must read 0, not 16 — otherwise the same dark room reads differently on
    /// two devices and the corpus numbers stop being comparable.
    func test_meanLuma_videoRange_blackFloorReadsZero() throws {
        let bytes = [UInt8](repeating: 16, count: 32 * 32)
        let mean = bytes.withUnsafeBytes {
            FrameLuminance.meanLuma(
                plane: $0, width: 32, height: 32, bytesPerRow: 32,
                range: .video, rowStride: 1)
        }
        XCTAssertEqual(try XCTUnwrap(mean), 0, accuracy: 1e-4)
    }

    func test_meanLuma_videoRange_whiteCeilingReadsFullScale() throws {
        let bytes = [UInt8](repeating: 235, count: 32 * 32)
        let mean = bytes.withUnsafeBytes {
            FrameLuminance.meanLuma(
                plane: $0, width: 32, height: 32, bytesPerRow: 32,
                range: .video, rowStride: 1)
        }
        XCTAssertEqual(try XCTUnwrap(mean), 255, accuracy: 1e-3)
    }

    /// Footroom excursions are legal in studio swing; a brightness below zero
    /// is not.
    func test_meanLuma_videoRange_clampsBelowFootroom() throws {
        let bytes = [UInt8](repeating: 4, count: 16 * 16)
        let mean = bytes.withUnsafeBytes {
            FrameLuminance.meanLuma(
                plane: $0, width: 16, height: 16, bytesPerRow: 16,
                range: .video, rowStride: 1)
        }
        XCTAssertEqual(try XCTUnwrap(mean), 0, accuracy: 1e-6)
    }

    /// Row padding is not image data. A plane whose stride exceeds its width
    /// must not average the padding, or every reading picks up whatever the
    /// allocator left there.
    func test_meanLuma_ignoresRowPadding() throws {
        let width = 8, height = 8, stride = 16
        var bytes = [UInt8](repeating: 255, count: height * stride)   // padding = 255
        for row in 0..<height {
            for col in 0..<width { bytes[row * stride + col] = 10 }   // image = 10
        }
        let mean = bytes.withUnsafeBytes {
            FrameLuminance.meanLuma(
                plane: $0, width: width, height: height, bytesPerRow: stride,
                range: .full, rowStride: 1)
        }
        XCTAssertEqual(try XCTUnwrap(mean), 10, accuracy: 1e-4)
    }

    /// Subsampling is a cost decision, not a measurement decision. A linear ramp
    /// is the worst case for it — the sampled rows and columns sit off-centre by
    /// half a stride each — and even there the strided read tracks the
    /// exhaustive one to a few counts out of 126.
    func test_meanLuma_subsampleTracksFullRead() throws {
        let w = 64, h = 64
        var bytes = [UInt8](repeating: 0, count: w * h)
        for row in 0..<h {
            for col in 0..<w { bytes[row * w + col] = UInt8(row + col) }
        }
        let full = try XCTUnwrap(bytes.withUnsafeBytes {
            FrameLuminance.meanLuma(plane: $0, width: w, height: h, bytesPerRow: w,
                                    range: .full, rowStride: 1)
        })
        let strided = try XCTUnwrap(bytes.withUnsafeBytes {
            FrameLuminance.meanLuma(plane: $0, width: w, height: h, bytesPerRow: w,
                                    range: .full, rowStride: 4)
        })
        XCTAssertEqual(full, strided, accuracy: 4.0)
    }

    /// The invariant that actually matters: whatever the stride costs in
    /// precision, it must never move a blank frame across the reporting floor.
    func test_meanLuma_darkPlaneReadsDarkAtEveryStride() throws {
        let w = 128, h = 128
        var bytes = [UInt8](repeating: 0, count: w * h)
        // Sensor noise in near-darkness: a few counts, unevenly spread.
        for i in stride(from: 0, to: bytes.count, by: 3) { bytes[i] = 5 }
        for stepSize in [1, 2, 4, 8] {
            let mean = try XCTUnwrap(bytes.withUnsafeBytes {
                FrameLuminance.meanLuma(plane: $0, width: w, height: h, bytesPerRow: w,
                                        range: .full, rowStride: stepSize)
            })
            XCTAssertLessThan(mean, LuminanceCensus.darkThreshold,
                              "stride \(stepSize) read \(mean)")
        }
    }

    /// A plane shorter than the geometry describes is a programming error.
    /// Returning nil is the loud answer; reading past the end would return a
    /// plausible wrong number instead.
    func test_meanLuma_shortPlane_isNil() {
        let bytes = [UInt8](repeating: 128, count: 10)
        let mean = bytes.withUnsafeBytes {
            FrameLuminance.meanLuma(plane: $0, width: 64, height: 64, bytesPerRow: 64,
                                    range: .full, rowStride: 1)
        }
        XCTAssertNil(mean)
    }

    /// The last row need not carry stride padding; requiring it would reject
    /// buffers CoreVideo legitimately vends.
    func test_meanLuma_lastRowWithoutPadding_isRead() throws {
        let width = 8, height = 4, stride = 16
        let count = (height - 1) * stride + width
        let bytes = [UInt8](repeating: 100, count: count)
        let mean = bytes.withUnsafeBytes {
            FrameLuminance.meanLuma(plane: $0, width: width, height: height,
                                    bytesPerRow: stride, range: .full, rowStride: 1)
        }
        XCTAssertEqual(try XCTUnwrap(mean), 100, accuracy: 1e-4)
    }

    func test_meanLuma_degenerateGeometry_isNil() {
        let bytes = [UInt8](repeating: 1, count: 256)
        bytes.withUnsafeBytes {
            XCTAssertNil(FrameLuminance.meanLuma(plane: $0, width: 0, height: 16,
                                                 bytesPerRow: 16, range: .full))
            XCTAssertNil(FrameLuminance.meanLuma(plane: $0, width: 16, height: 0,
                                                 bytesPerRow: 16, range: .full))
            XCTAssertNil(FrameLuminance.meanLuma(plane: $0, width: 16, height: 16,
                                                 bytesPerRow: 16, range: .full, rowStride: 0))
            // bytesPerRow below width describes an impossible plane.
            XCTAssertNil(FrameLuminance.meanLuma(plane: $0, width: 16, height: 4,
                                                 bytesPerRow: 8, range: .full))
        }
    }

    // MARK: - Pixel-format mapping

    func test_lumaRange_mapsBiplanarFormats() {
        XCTAssertEqual(LumaRange.forPixelFormat(kCVPixelFormatType_420YpCbCr8BiPlanarFullRange), .full)
        XCTAssertEqual(LumaRange.forPixelFormat(kCVPixelFormatType_420YpCbCr8BiPlanarVideoRange), .video)
        // A format with no luma plane has no reading to give.
        XCTAssertNil(LumaRange.forPixelFormat(kCVPixelFormatType_32BGRA))
    }

    // MARK: - Census

    func test_census_empty_saysSo() {
        let census = LuminanceCensus()
        XCTAssertEqual(census.count, 0)
        XCTAssertNil(census.longestDarkRun)
        XCTAssertEqual(census.summary, "luminance: no keyframes measured")
    }

    /// A clean capture still reports. A census that only prints when something
    /// is wrong cannot be distinguished from one that never ran.
    func test_census_cleanCapture_reportsAndNamesNoDarkFrames() {
        var census = LuminanceCensus()
        for i in 0..<10 { census.record(index: UInt32(i), mean: 120 + Float(i)) }
        XCTAssertEqual(census.darkCount, 0)
        XCTAssertNil(census.longestDarkRun)
        XCTAssertTrue(census.summary.contains("10 frames"), census.summary)
        XCTAssertTrue(census.summary.contains("none below 16"), census.summary)
    }

    func test_census_medianOfEvenAndOddCounts() throws {
        var odd = LuminanceCensus()
        for (i, v) in [30, 10, 20].enumerated() { odd.record(index: UInt32(i), mean: Float(v)) }
        XCTAssertEqual(try XCTUnwrap(odd.median), 20, accuracy: 1e-4)

        var even = LuminanceCensus()
        for (i, v) in [40, 10, 20, 30].enumerated() { even.record(index: UInt32(i), mean: Float(v)) }
        XCTAssertEqual(try XCTUnwrap(even.median), 25, accuracy: 1e-4)
    }

    /// The run is what separates a covered lens from a dim corner, so scattered
    /// dark frames must not report as one long run.
    func test_census_scatteredDarkFrames_doNotFormARun() throws {
        var census = LuminanceCensus()
        for i in 0..<10 {
            census.record(index: UInt32(i), mean: i % 2 == 0 ? 2 : 120)
        }
        XCTAssertEqual(census.darkCount, 5)
        XCTAssertEqual(try XCTUnwrap(census.longestDarkRun).length, 1)
    }

    func test_census_longestRunWinsOverEarlierShorterRun() throws {
        var census = LuminanceCensus()
        let dark: Set<UInt32> = [1, 2, 6, 7, 8, 9]
        for i in 0..<12 {
            census.record(index: UInt32(i), mean: dark.contains(UInt32(i)) ? 1 : 130)
        }
        let run = try XCTUnwrap(census.longestDarkRun)
        XCTAssertEqual(run.start, 6)
        XCTAssertEqual(run.length, 4)
    }

    /// Readings arrive on a serial queue in index order today; the run must not
    /// silently depend on that.
    func test_census_runIsIndependentOfRecordingOrder() throws {
        var forward = LuminanceCensus()
        var shuffled = LuminanceCensus()
        let means: [UInt32: Float] = [0: 130, 1: 1, 2: 1, 3: 1, 4: 130]
        for i in means.keys.sorted() { forward.record(index: i, mean: means[i]!) }
        for i in [4, 2, 0, 3, 1] as [UInt32] { shuffled.record(index: i, mean: means[i]!) }
        XCTAssertEqual(try XCTUnwrap(forward.longestDarkRun).start,
                       try XCTUnwrap(shuffled.longestDarkRun).start)
        XCTAssertEqual(try XCTUnwrap(forward.longestDarkRun).length,
                       try XCTUnwrap(shuffled.longestDarkRun).length)
    }

    func test_census_resetClearsReadings() {
        var census = LuminanceCensus()
        census.record(index: 0, mean: 1)
        census.reset()
        XCTAssertEqual(census.count, 0)
        XCTAssertEqual(census.summary, "luminance: no keyframes measured")
    }

    // MARK: - The rp6g2 fixture

    /// Mean luma of all 124 keyframes of the preserved rp6g2 capture
    /// (`ea40c579-12e9-4173-8eb4-a65280650de8`), measured offline over the
    /// bundle's own JPEGs. Index i is frame i.
    private static let rp6g2MeanLuma: [Float] = [
        134.95, 132.02, 130.79, 130.87, 132.67, 133.55, 134.7, 141.39,
        148.09, 143.86, 135.56, 133.04, 132.66, 135.52, 139.67, 142.36,
        140.75, 114.93, 137.9, 138.7, 141.48, 145.89, 140.72, 137.57,
        135.64, 136.98, 137.49, 140.18, 142.04, 147.33, 150.79, 153.73,
        157.6, 163.3, 163.03, 163.16, 159.63, 159.7, 152.68, 144.91,
        135.24, 128.08, 123.29, 123.99, 122.87, 119.45, 112.55, 113.49,
        114.41, 117.64, 119, 123.89, 125.66, 128.39, 130.73, 130.75,
        127.84, 133.66, 141.79, 139.95, 138.91, 130.63, 114.58, 108.88,
        114.08, 111.78, 106.17, 109.07, 112.25, 115.27, 125.25, 139.6,
        150.33, 153.94, 153.1, 145.86, 136.67, 127.47, 118.99, 111.63,
        106.49, 111.98, 117.78, 123.57, 129.03, 133.27, 134.67, 133.75,
        138.13, 144.25, 142.14, 139.14, 137.34, 140.52, 142.96, 105.36,
        23.03, 0.13, 0.69, 0.79, 1.67, 1.92, 1.95, 2.51,
        2.99, 2.58, 2.87, 2.93, 11.87, 4.8, 4.83, 3.51,
        2.88, 2.64, 2.4, 2.23, 1.91, 1.74, 1.98, 2.01,
        1.73, 1.62, 1.15, 1.25,
    ]

    /// The capture that motivated all of this. Every number below was measured
    /// on the preserved bundle; the pin is that the census reports them.
    func test_census_rp6g2_reportsTheDarkTail() throws {
        var census = LuminanceCensus()
        for (i, mean) in Self.rp6g2MeanLuma.enumerated() {
            census.record(index: UInt32(i), mean: mean)
        }

        XCTAssertEqual(census.count, 124)
        // 27 keyframes below the floor, and they are ONE unbroken run to the
        // end of the capture — the signature of a lens that got covered and
        // stayed covered, not of a room with dark corners.
        XCTAssertEqual(census.darkCount, 27)
        let run = try XCTUnwrap(census.longestDarkRun)
        XCTAssertEqual(run.start, 97)
        XCTAssertEqual(run.length, 27)
        XCTAssertEqual(run.start + UInt32(run.length) - 1, 123, "the run reaches the last keyframe")

        // The median is a healthy room. Averaging alone would have hidden this,
        // which is why the summary reports the minimum and the run beside it.
        XCTAssertGreaterThan(try XCTUnwrap(census.median), 100)
        XCTAssertLessThan(try XCTUnwrap(census.minimum), 1)

        let summary = census.summary
        XCTAssertTrue(summary.contains("27 below 16"), summary)
        XCTAssertTrue(summary.contains("longest run 27 from frame 97"), summary)
    }

    /// The threshold is a chasm, not a boundary. Across the seven preserved
    /// captures the six healthy ones never read below 80.63, and rp6g2's own
    /// first frame above the floor reads 23.03 — so no plausible re-tune between
    /// 16 and 80 changes any verdict, and nothing is dropped on it regardless.
    func test_darkThreshold_sitsInTheGapBetweenBlankAndHealthy() {
        let darkestHealthyFrameInCorpus: Float = 80.63
        let brightestFrameInRp6g2DarkTail: Float = 11.87
        XCTAssertGreaterThan(LuminanceCensus.darkThreshold, brightestFrameInRp6g2DarkTail)
        XCTAssertLessThan(LuminanceCensus.darkThreshold, darkestHealthyFrameInCorpus)
    }
}
