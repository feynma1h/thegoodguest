/// Pins that the detector sees the pixels the maps describe: a marker drawn
/// into a camera-format buffer (full-range YCbCr, 1920×1440, as ARKit delivers)
/// is rendered through the production preprocessor in every hold and found in
/// the model input exactly where `SensorFrame.modelPoint(image:)` puts it —
/// and the letterbox padding is the grey the detector was trained with.

import CoreVideo
import simd
import XCTest
@testable import TheGoodGuest

final class LiveBoxesPreprocessorTests: XCTestCase {

    private let intrinsics = CameraIntrinsics(fx: 1500, fy: 1500, cx: 960, cy: 720, width: 1920, height: 1440)

    /// A black camera frame with a white square centred at `centre`.
    private func cameraFrame(marker centre: SIMD2<Int>, half: Int = 12) throws -> CVPixelBuffer {
        var buffer: CVPixelBuffer?
        let attributes: [String: Any] = [kCVPixelBufferIOSurfacePropertiesKey as String: [:] as [String: Any]]
        CVPixelBufferCreate(nil, 1920, 1440, kCVPixelFormatType_420YpCbCr8BiPlanarFullRange,
                            attributes as CFDictionary, &buffer)
        let frame = try XCTUnwrap(buffer)
        CVPixelBufferLockBaseAddress(frame, [])
        defer { CVPixelBufferUnlockBaseAddress(frame, []) }
        let luma = CVPixelBufferGetBaseAddressOfPlane(frame, 0)!.assumingMemoryBound(to: UInt8.self)
        let lumaStride = CVPixelBufferGetBytesPerRowOfPlane(frame, 0)
        for y in 0..<1440 {
            for x in 0..<1920 {
                let inside = abs(x - centre.x) < half && abs(y - centre.y) < half
                luma[y * lumaStride + x] = inside ? 255 : 0
            }
        }
        let chroma = CVPixelBufferGetBaseAddressOfPlane(frame, 1)!.assumingMemoryBound(to: UInt8.self)
        let chromaStride = CVPixelBufferGetBytesPerRowOfPlane(frame, 1)
        for y in 0..<720 { for x in 0..<(960 * 2) { chroma[y * chromaStride + x] = 128 } }
        return frame
    }

    /// Centroid of bright pixels in a BGRA buffer.
    private func brightCentroid(_ buffer: CVPixelBuffer) -> SIMD2<Float>? {
        CVPixelBufferLockBaseAddress(buffer, .readOnly)
        defer { CVPixelBufferUnlockBaseAddress(buffer, .readOnly) }
        let base = CVPixelBufferGetBaseAddress(buffer)!.assumingMemoryBound(to: UInt8.self)
        let stride = CVPixelBufferGetBytesPerRow(buffer)
        var sum = SIMD2<Float>.zero
        var weight: Float = 0
        for y in 0..<CVPixelBufferGetHeight(buffer) {
            for x in 0..<CVPixelBufferGetWidth(buffer) {
                let g = Float(base[y * stride + x * 4 + 1])
                guard g > 160 else { continue }
                sum += SIMD2(Float(x) + 0.5, Float(y) + 0.5) * g
                weight += g
            }
        }
        return weight > 0 ? sum / weight : nil
    }

    private func pixel(_ buffer: CVPixelBuffer, _ x: Int, _ y: Int) -> SIMD3<UInt8> {
        CVPixelBufferLockBaseAddress(buffer, .readOnly)
        defer { CVPixelBufferUnlockBaseAddress(buffer, .readOnly) }
        let base = CVPixelBufferGetBaseAddress(buffer)!.assumingMemoryBound(to: UInt8.self)
        let o = y * CVPixelBufferGetBytesPerRow(buffer) + x * 4
        return SIMD3(base[o + 2], base[o + 1], base[o])
    }

    func test_marker_landsWhereTheMapsSay_inEveryHold() throws {
        let marker = SIMD2<Int>(1402, 318)
        let image = try cameraFrame(marker: marker)
        let preprocessor = FramePreprocessor(width: 640, height: 640)
        for turn in QuarterTurn.allCases {
            let frame = SensorFrame(intrinsics: intrinsics, depthWidth: 256, depthHeight: 192,
                                    worldFromCamera: matrix_identity_float4x4, turn: turn,
                                    modelWidth: 640, modelHeight: 640)
            let rendered = try XCTUnwrap(preprocessor.render(image, frame: frame), "\(turn)")
            let found = try XCTUnwrap(brightCentroid(rendered), "no marker for \(turn)")
            let expected = frame.modelPoint(image: SIMD2(Float(marker.x), Float(marker.y)))
            XCTAssertEqual(found.x, expected.x, accuracy: 1.5, "\(turn)")
            XCTAssertEqual(found.y, expected.y, accuracy: 1.5, "\(turn)")
        }
    }

    func test_padding_isTheTrainingGrey_andTheImageIsNotColourManaged() throws {
        let image = try cameraFrame(marker: SIMD2(960, 720))
        let frame = SensorFrame(intrinsics: intrinsics, depthWidth: 256, depthHeight: 192,
                                worldFromCamera: matrix_identity_float4x4, turn: .clockwise,
                                modelWidth: 640, modelHeight: 640)
        let rendered = try XCTUnwrap(FramePreprocessor(width: 640, height: 640).render(image, frame: frame))
        // Portrait into a square: 80 px of padding either side.
        let pad = pixel(rendered, 20, 320)
        for channel in [pad.x, pad.y, pad.z] { XCTAssertEqual(Int(channel), 114, accuracy: 2) }
        // Black camera pixels stay black: full-range Y 0 is RGB 0 with no
        // working-space conversion lifting it.
        let dark = pixel(rendered, 200, 100)
        for channel in [dark.x, dark.y, dark.z] { XCTAssertLessThanOrEqual(Int(channel), 3) }
    }
}
