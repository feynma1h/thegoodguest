/// Reading a prompt-free YOLOE-26 segmentation export: its metadata, its
/// end-to-end detection rows, and its instance masks — as pure functions over
/// plain arrays, so no Core ML type reaches the maths. DEBUG-only (decision 0295).
///
/// THE EXPORT'S SHAPE (pinned by LiveBoxesDecoderTests, and by 0295's rebuild
/// recipe): one image input, and two outputs told apart by rank rather than by
/// name, because the converter names them after graph nodes —
///
///   • detections, [1, N, 6 + M]: x1, y1, x2, y2 in model-input pixels, the
///     score, the class index, then M mask coefficients;
///   • prototypes, [1, M, H, W] at a fixed stride below the input.
///
/// An instance mask is the coefficients dotted into the prototypes, bilinearly
/// sampled, cropped to the detection's box and thresholded at logit 0 — the
/// same construction the model was trained against.
///
/// CLASS INDICES ARE CHECKED, NOT TRUSTED. The export carries the class as a
/// float, and an FP16 graph represents integers above 2048 only to the nearest
/// even number: with the full 4,585-name vocabulary a person came back as the
/// neighbouring "humidifier". The shipped vocabulary is far below that bound,
/// and a row whose class is not an integer is dropped rather than rounded into
/// somebody else's name.
///
/// Read by: DetectorPipeline, DetectorModel (metadata), LiveBoxesDecoderTests
/// and LiveBoxesLiftingTests.

#if DEBUG

import Foundation
import simd

// MARK: - Metadata

nonisolated struct DetectorModelInfo: Sendable, Equatable {
    /// Class names in index order.
    let names: [String]
    let inputWidth: Int
    let inputHeight: Int
    let endToEnd: Bool

    /// Parse the creator-defined metadata an Ultralytics export writes: `names`
    /// is a Python dict literal, `imgsz` a list `[height, width]`.
    static func parse(_ metadata: [String: String]) -> DetectorModelInfo? {
        guard let rawNames = metadata["names"], let rawSize = metadata["imgsz"] else { return nil }
        let names = parseNames(rawNames)
        let dims = rawSize.split(whereSeparator: { !$0.isNumber }).compactMap { Int($0) }
        guard !names.isEmpty, dims.count == 2 else { return nil }
        return DetectorModelInfo(names: names, inputWidth: dims[1], inputHeight: dims[0],
                                 endToEnd: metadata["end2end"] == "True")
    }

    /// `{0: 'lamp', 1: "child's room"}` → ["lamp", "child's room"]. A dict
    /// whose keys are not exactly 0..<n yields no names at all.
    static func parseNames(_ raw: String) -> [String] {
        var entries: [Int: String] = [:]
        let chars = Array(raw)
        var i = 0
        while i < chars.count {
            guard chars[i].isNumber else { i += 1; continue }
            var j = i
            while j < chars.count, chars[j].isNumber { j += 1 }
            guard let key = Int(String(chars[i..<j])) else { return [] }
            var k = j
            while k < chars.count, chars[k] == ":" || chars[k] == " " { k += 1 }
            guard k < chars.count, chars[k] == "'" || chars[k] == "\"" else { i = j; continue }
            let quote = chars[k]
            var value = ""
            var m = k + 1
            while m < chars.count, chars[m] != quote {
                if chars[m] == "\\", m + 1 < chars.count { m += 1 }
                value.append(chars[m])
                m += 1
            }
            entries[key] = value
            i = m + 1
        }
        guard !entries.isEmpty, Set(entries.keys) == Set(0..<entries.count) else { return [] }
        return (0..<entries.count).map { entries[$0]! }
    }
}

// MARK: - Detections

nonisolated struct RawDetection: Sendable, Equatable {
    let classIndex: Int
    let score: Float
    /// Box corners in model-input pixels.
    let modelMin: SIMD2<Float>
    let modelMax: SIMD2<Float>
    let coefficients: [Float]
}

nonisolated enum DetectionDecoder {

    /// The rows of an end-to-end head at or above `minimumScore`, best first.
    static func decode(rows: [Float], rowCount: Int, rowLength: Int, classCount: Int,
                       minimumScore: Float, modelWidth: Float, modelHeight: Float) -> [RawDetection] {
        guard rowLength >= 6, rows.count >= rowCount * rowLength else { return [] }
        var out: [RawDetection] = []
        for r in 0..<rowCount {
            let base = r * rowLength
            let score = rows[base + 4]
            guard score.isFinite, score >= minimumScore else { continue }
            // Range first: converting a NaN, an infinity or a huge value to Int traps.
            let rawClass = rows[base + 5]
            guard rawClass.isFinite, rawClass > -0.5, rawClass < Float(classCount) - 0.5 else { continue }
            let classIndex = Int(rawClass.rounded())
            guard abs(rawClass - Float(classIndex)) < 0.01 else { continue }
            let lo = SIMD2(max(0, min(rows[base], rows[base + 2])),
                           max(0, min(rows[base + 1], rows[base + 3])))
            let hi = SIMD2(min(modelWidth, max(rows[base], rows[base + 2])),
                           min(modelHeight, max(rows[base + 1], rows[base + 3])))
            guard hi.x - lo.x >= 1, hi.y - lo.y >= 1 else { continue }
            out.append(RawDetection(classIndex: classIndex, score: score,
                                    modelMin: lo, modelMax: hi,
                                    coefficients: Array(rows[(base + 6)..<(base + rowLength)])))
        }
        return out.sorted { $0.score > $1.score }
    }
}

// MARK: - Masks

/// The prototype tensor of one inference.
nonisolated struct ProtoBank: Sendable {
    let channels: Int
    let width: Int
    let height: Int
    /// Channel-major: values[c * height * width + y * width + x].
    let values: [Float]
    let modelWidth: Float
    let modelHeight: Float

    init(channels: Int, width: Int, height: Int, values: [Float],
         modelWidth: Float, modelHeight: Float) {
        precondition(values.count == channels * width * height)
        self.channels = channels
        self.width = width
        self.height = height
        self.values = values
        self.modelWidth = modelWidth
        self.modelHeight = modelHeight
    }

    /// The detection's mask logits on the prototype grid, over the cells its
    /// box touches plus one cell of margin for interpolation.
    func mask(for detection: RawDetection) -> ProtoMask {
        let sx = modelWidth / Float(width), sy = modelHeight / Float(height)
        let x0 = max(Int((detection.modelMin.x / sx).rounded(.down)) - 1, 0)
        let x1 = min(Int((detection.modelMax.x / sx).rounded(.up)) + 1, width - 1)
        let y0 = max(Int((detection.modelMin.y / sy).rounded(.down)) - 1, 0)
        let y1 = min(Int((detection.modelMax.y / sy).rounded(.up)) + 1, height - 1)
        let cw = max(x1 - x0 + 1, 1), ch = max(y1 - y0 + 1, 1)
        var logits = [Float](repeating: 0, count: cw * ch)
        let plane = width * height
        let n = min(channels, detection.coefficients.count)
        for c in 0..<n {
            let w = detection.coefficients[c]
            let offset = c * plane
            for y in 0..<ch {
                let row = offset + (y0 + y) * width
                for x in 0..<cw {
                    logits[y * cw + x] += w * values[row + x0 + x]
                }
            }
        }
        return ProtoMask(cellX: x0...(x0 + cw - 1), cellY: y0...(y0 + ch - 1),
                         logits: logits, strideX: sx, strideY: sy,
                         modelMin: detection.modelMin, modelMax: detection.modelMax)
    }
}

/// One detection's mask, sampleable anywhere in model-input coordinates.
nonisolated struct ProtoMask: Sendable {
    let cellX: ClosedRange<Int>
    let cellY: ClosedRange<Int>
    let logits: [Float]
    let strideX: Float
    let strideY: Float
    let modelMin: SIMD2<Float>
    let modelMax: SIMD2<Float>

    /// The interpolated logit at a model-input point. Cell (i, j) is centred
    /// at ((i + 0.5)·strideX, (j + 0.5)·strideY).
    func logit(model p: SIMD2<Float>) -> Float {
        let gx = p.x / strideX - 0.5, gy = p.y / strideY - 0.5
        let fx = gx.rounded(.down), fy = gy.rounded(.down)
        let tx = gx - fx, ty = gy - fy
        let w = cellX.count
        func at(_ i: Int, _ j: Int) -> Float {
            let ci = min(max(i, cellX.lowerBound), cellX.upperBound) - cellX.lowerBound
            let cj = min(max(j, cellY.lowerBound), cellY.upperBound) - cellY.lowerBound
            return logits[cj * w + ci]
        }
        let i = Int(fx), j = Int(fy)
        let top = at(i, j) * (1 - tx) + at(i + 1, j) * tx
        let bottom = at(i, j + 1) * (1 - tx) + at(i + 1, j + 1) * tx
        return top * (1 - ty) + bottom * ty
    }

    /// Inside the box and on the object's side of the threshold.
    func contains(model p: SIMD2<Float>) -> Bool {
        p.x >= modelMin.x && p.x <= modelMax.x && p.y >= modelMin.y && p.y <= modelMax.y
            && logit(model: p) > 0
    }

    /// The mask resampled at the depth map's pixel centres. Nil when the box
    /// covers no depth pixel.
    func depthMask(frame: SensorFrame) -> DepthMask? {
        guard let range = frame.depthPixelRange(modelMin: modelMin, modelMax: modelMax) else { return nil }
        return DepthMask(xRange: range.x, yRange: range.y) { x, y in
            contains(model: frame.modelPoint(depthX: x, depthY: y))
        }
    }
}

#endif
