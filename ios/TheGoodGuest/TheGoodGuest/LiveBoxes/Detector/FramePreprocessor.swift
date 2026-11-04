/// Turning a camera frame into the detector's input: the upright quarter-turn
/// and the letterbox, rendered in one Core Image pass into a pooled buffer —
/// DEBUG-only (decision 0295).
///
/// THE RENDER IS THE MAP. The affine transform handed to Core Image is read
/// off `SensorFrame.modelPoint(image:)` itself, at three points, rather than
/// assembled from a second description of the turn and the letterbox; so the
/// pixels the detector sees and the coordinates its boxes are mapped back
/// through cannot disagree. The only thing added here is Core Image's
/// bottom-left origin, flipped on both sides. LiveBoxesPreprocessorTests renders
/// a marker through it in every hold and finds it where the map says.
///
/// Colour is left alone: the working colour space is disabled, so the
/// camera's YCbCr is converted to the gamma-encoded RGB the detector was
/// trained on, and padding is the training letterbox's grey (114).
///
/// Read by: DetectorPipeline, LiveBoxesPreprocessorTests.

#if DEBUG

import CoreGraphics
import CoreImage
import CoreVideo
import simd

nonisolated final class FramePreprocessor: @unchecked Sendable {
    let width: Int
    let height: Int
    private let context: CIContext
    private var pool: CVPixelBufferPool?
    private let background: CIImage

    init(width: Int, height: Int) {
        self.width = width
        self.height = height
        context = CIContext(options: [.workingColorSpace: NSNull(), .outputColorSpace: NSNull(),
                                      .cacheIntermediates: false])
        let grey = CGFloat(114) / 255
        background = CIImage(color: CIColor(red: grey, green: grey, blue: grey))
            .cropped(to: CGRect(x: 0, y: 0, width: width, height: height))
        var poolRef: CVPixelBufferPool?
        let attributes: [String: Any] = [
            kCVPixelBufferPixelFormatTypeKey as String: kCVPixelFormatType_32BGRA,
            kCVPixelBufferWidthKey as String: width,
            kCVPixelBufferHeightKey as String: height,
            kCVPixelBufferIOSurfacePropertiesKey as String: [:] as [String: Any],
            kCVPixelBufferMetalCompatibilityKey as String: true,
        ]
        CVPixelBufferPoolCreate(nil, [kCVPixelBufferPoolMinimumBufferCountKey as String: 2] as CFDictionary,
                                attributes as CFDictionary, &poolRef)
        pool = poolRef
    }

    /// Render `image` (the camera frame `frame` describes) as the detector's input.
    func render(_ image: CVPixelBuffer, frame: SensorFrame) -> CVPixelBuffer? {
        guard let pool else { return nil }
        var out: CVPixelBuffer?
        guard CVPixelBufferPoolCreatePixelBuffer(nil, pool, &out) == kCVReturnSuccess, let out else { return nil }
        let transform = Self.coreImageTransform(frame: frame, outputHeight: Float(height))
        let placed = CIImage(cvPixelBuffer: image).transformed(by: transform)
        context.render(placed.composited(over: background), to: out,
                       bounds: CGRect(x: 0, y: 0, width: width, height: height), colorSpace: nil)
        return out
    }

    /// The Core Image transform from the camera image to the model input.
    ///
    /// `SensorFrame` maps top-left-origin image points to top-left-origin
    /// model points affinely: m = o + eₓ·u + e_y·v. Core Image addresses both
    /// rasters from the bottom-left, so with v = H − y and y' = S − m_y:
    ///   x' = (oₓ + e_yₓ·H) + eₓₓ·x − e_yₓ·y
    ///   y' = (S − o_y − e_y_y·H) − eₓ_y·x + e_y_y·y
    static func coreImageTransform(frame: SensorFrame, outputHeight s: Float) -> CGAffineTransform {
        let h = Float(frame.intrinsics.height)
        let o = frame.modelPoint(image: SIMD2(0, 0))
        let ex = frame.modelPoint(image: SIMD2(1, 0)) - o
        let ey = frame.modelPoint(image: SIMD2(0, 1)) - o
        return CGAffineTransform(a: CGFloat(ex.x), b: CGFloat(-ex.y),
                                 c: CGFloat(-ey.x), d: CGFloat(ey.y),
                                 tx: CGFloat(o.x + ey.x * h), ty: CGFloat(s - o.y - ey.y * h))
    }
}

#endif
