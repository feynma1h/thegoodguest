/// Whole-frame luminance for one keyframe, and the session census of it.
///
/// A capture can stop showing the room while everything the capture path checks
/// stays healthy: ARKit keeps tracking, the pose is valid, the LiDAR keeps
/// returning depth, and keyframes keep being accepted. Covering the lens does
/// exactly that. rp6g2 shipped 28 such keyframes and nothing on the device, in
/// the bundle, or in the pipeline said so — it took an offline pass over the
/// preserved capture weeks later to find them (decisions 0234/0235), by which
/// point the shipped sampler had already reconstructed that room from two of
/// them.
///
/// So the statistic is measured on every keyframe and reported at stop whether
/// or not anything is wrong. Nothing is dropped and nothing is gated on it: the
/// point is that the next dark room is data at the time it happens rather than
/// an invisible false positive (decision 0240).
///
/// The number is the mean of the camera's luma plane on a 0-255 scale, which is
/// the quantity the offline frame-usability pass reports, so an on-device
/// reading is directly comparable to the preserved corpus.

import CoreVideo
import Foundation

// MARK: - Luma encoding range

/// Which of the two 8-bit luma encodings a pixel buffer uses.
///
/// ARKit vends `capturedImage` as 420YpCbCr8BiPlanar; both the full-range and
/// video-range variants exist across configurations, and they put black at
/// different code values. Reading the format rather than assuming one keeps the
/// statistic on a single scale across devices.
enum LumaRange: Equatable {
    /// Y spans 0...255. Black is 0.
    case full
    /// Y spans 16...235 (ITU-R BT.601 studio swing). Black is 16.
    case video

    /// The range for a CoreVideo pixel-format type, or nil if the format is not
    /// a biplanar YCbCr one and therefore has no luma plane to read.
    static func forPixelFormat(_ format: OSType) -> LumaRange? {
        switch format {
        case kCVPixelFormatType_420YpCbCr8BiPlanarFullRange,
             kCVPixelFormatType_420YpCbCr8PlanarFullRange:
            return .full
        case kCVPixelFormatType_420YpCbCr8BiPlanarVideoRange,
             kCVPixelFormatType_420YpCbCr8Planar:
            return .video
        default:
            return nil
        }
    }
}

// MARK: - The statistic

enum FrameLuminance {

    /// Mean luma over a luma plane, normalised to a 0...255 full-range scale.
    ///
    /// Pure: a function of its arguments only, so the sampling and the
    /// video-range rescale are reviewable as a table rather than by reading the
    /// capture path. Returns nil when the described geometry does not fit the
    /// buffer — a short plane is a programming error, and reading past it would
    /// trade a loud nil for a plausible wrong number.
    ///
    /// `rowStride` subsamples both axes: 4 reads one pixel in sixteen, which is
    /// far more than a mean needs on a 1920x1440 frame and costs well under a
    /// millisecond. It never changes the answer beyond sampling noise, and it
    /// must not change whether the plane fits.
    static func meanLuma(
        plane:       UnsafeRawBufferPointer,
        width:       Int,
        height:      Int,
        bytesPerRow: Int,
        range:       LumaRange,
        rowStride:   Int = 4
    ) -> Float? {
        guard width > 0, height > 0, rowStride >= 1, bytesPerRow >= width else { return nil }
        // Last byte the sampler could touch. The final row need not be padded.
        guard plane.count >= (height - 1) * bytesPerRow + width else { return nil }

        var total   = 0
        var samples = 0
        var row     = 0
        while row < height {
            let base = row * bytesPerRow
            var col  = 0
            while col < width {
                total += Int(plane[base + col])
                samples += 1
                col += rowStride
            }
            row += rowStride
        }
        guard samples > 0 else { return nil }

        let mean = Float(total) / Float(samples)
        switch range {
        case .full:
            return mean
        case .video:
            // 16...235 -> 0...255. Clamped: studio swing permits footroom and
            // headroom excursions, and a negative "brightness" is not a thing.
            return min(max((mean - 16.0) * (255.0 / 219.0), 0.0), 255.0)
        }
    }

    /// Mean luma for an ARKit `capturedImage`, or nil if the buffer cannot be
    /// locked or carries no readable luma plane.
    static func meanLuma(pixelBuffer: CVPixelBuffer, rowStride: Int = 4) -> Float? {
        guard let range = LumaRange.forPixelFormat(CVPixelBufferGetPixelFormatType(pixelBuffer)) else {
            return nil
        }
        guard CVPixelBufferLockBaseAddress(pixelBuffer, .readOnly) == kCVReturnSuccess else {
            return nil
        }
        defer { CVPixelBufferUnlockBaseAddress(pixelBuffer, .readOnly) }

        // Plane 0 is luma on every biplanar format above; a non-planar buffer
        // reports 0 planes and uses the flat accessors.
        let planar      = CVPixelBufferGetPlaneCount(pixelBuffer) > 0
        let base        = planar ? CVPixelBufferGetBaseAddressOfPlane(pixelBuffer, 0)
                                 : CVPixelBufferGetBaseAddress(pixelBuffer)
        let width       = planar ? CVPixelBufferGetWidthOfPlane(pixelBuffer, 0)
                                 : CVPixelBufferGetWidth(pixelBuffer)
        let height      = planar ? CVPixelBufferGetHeightOfPlane(pixelBuffer, 0)
                                 : CVPixelBufferGetHeight(pixelBuffer)
        let bytesPerRow = planar ? CVPixelBufferGetBytesPerRowOfPlane(pixelBuffer, 0)
                                 : CVPixelBufferGetBytesPerRow(pixelBuffer)
        guard let base, height > 0, bytesPerRow > 0 else { return nil }

        return meanLuma(
            plane:       UnsafeRawBufferPointer(start: base, count: height * bytesPerRow),
            width:       width,
            height:      height,
            bytesPerRow: bytesPerRow,
            range:       range,
            rowStride:   rowStride)
    }
}

// MARK: - Session census

/// Accumulates one mean-luma reading per keyframe and answers the questions the
/// stop-time report asks of them.
///
/// A value type on purpose: all of the reasoning is here and testable as a
/// table, and the capture path holds it in a queue-confined box.
struct LuminanceCensus {

    /// Mean luma at or below which a frame is reported as carrying no image.
    ///
    /// 16 is the video-range black floor — a frame whose mean is under it is, on
    /// average, darker than the darkest value a studio-swing encoder can even
    /// represent. It is not a tuned number and it sits in a chasm rather than on
    /// a boundary: across the seven preserved captures (2,084 keyframes), the
    /// six healthy ones never read below 80.63, while rp6g2's covered-lens tail
    /// reads 0.13 to 11.77 and its next frame up reads 23.03.
    ///
    /// It is a REPORTING threshold, not a gate. Nothing is dropped on it, so
    /// having it slightly wrong costs a log line rather than a keyframe.
    static let darkThreshold: Float = 16.0

    /// One keyframe's reading. A named type rather than a tuple so the
    /// statistics below can address its fields by key path.
    struct Reading: Equatable {
        let index: UInt32
        let mean: Float
    }

    private(set) var readings: [Reading] = []

    mutating func record(index: UInt32, mean: Float) {
        readings.append(Reading(index: index, mean: mean))
    }

    mutating func reset() { readings.removeAll() }

    var count: Int { readings.count }

    func isDark(_ mean: Float) -> Bool { mean < Self.darkThreshold }

    var darkCount: Int { readings.filter { isDark($0.mean) }.count }

    var minimum: Float? { readings.map(\.mean).min() }
    var maximum: Float? { readings.map(\.mean).max() }

    var median: Float? {
        let sorted = readings.map(\.mean).sorted()
        guard !sorted.isEmpty else { return nil }
        let mid = sorted.count / 2
        return sorted.count % 2 == 1 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2
    }

    /// The longest unbroken run of consecutive dark keyframe indices.
    ///
    /// A run is what separates a covered lens from a dim corner: 27 consecutive
    /// blank frames is a capture that stopped seeing, where the same count
    /// scattered through a room is a hard room. Computed over sorted indices, so
    /// it does not depend on the order readings arrived in.
    var longestDarkRun: (start: UInt32, length: Int)? {
        let dark = readings.filter { isDark($0.mean) }.map(\.index).sorted()
        guard !dark.isEmpty else { return nil }

        var bestStart = dark[0], bestLen = 1
        var runStart  = dark[0], runLen  = 1
        for i in 1..<dark.count {
            if dark[i] == dark[i - 1] + 1 {
                runLen += 1
            } else {
                runStart = dark[i]
                runLen   = 1
            }
            if runLen > bestLen { bestLen = runLen; bestStart = runStart }
        }
        return (start: bestStart, length: bestLen)
    }

    /// The stop-time report. Emitted on every capture, including a clean one —
    /// a census that only prints when something is wrong cannot be trusted to
    /// have run.
    var summary: String {
        guard let minimum, let median, let maximum else {
            return "luminance: no keyframes measured"
        }
        let head = String(
            format: "luminance: %d frames, mean luma min %.2f / median %.2f / max %.2f",
            count, minimum, median, maximum)
        guard darkCount > 0, let run = longestDarkRun else {
            return head + "; none below \(Int(Self.darkThreshold))"
        }
        return head + String(
            format: "; %d below %d, longest run %d from frame %d",
            darkCount, Int(Self.darkThreshold), run.length, run.start)
    }
}

/// jpegQueue-confined box for the census.
///
/// Same shape and same reason as WriteStats: the encode queue is serial, which
/// is the synchronisation, so no locking and no actor isolation.
final class LuminanceRecorder {
    var census = LuminanceCensus()
}
