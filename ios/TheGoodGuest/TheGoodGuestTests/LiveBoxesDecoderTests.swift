/// Pins for reading the detector's export without Core ML: the metadata
/// strings an Ultralytics export writes, the end-to-end detection rows, the
/// class-index guard that keeps an FP16 rounding from becoming somebody else's
/// name, and the prototype masks sampled in model space.
///
/// The metadata fixtures are the exact shapes read out of an exported package
/// (`names` a Python dict literal, `imgsz` a list) — a handful of class names,
/// no weights.

import simd
import XCTest
@testable import TheGoodGuest

final class LiveBoxesDecoderTests: XCTestCase {

    // MARK: - Metadata

    func test_metadata_parsesNamesSizeAndHead() throws {
        let info = try XCTUnwrap(DetectorModelInfo.parse([
            "names": "{0: 'lamp', 1: 'table lamp', 2: 'bedside lamp'}",
            "imgsz": "[640, 640]",
            "end2end": "True",
            "task": "segment",
        ]))
        XCTAssertEqual(info.names, ["lamp", "table lamp", "bedside lamp"])
        XCTAssertEqual(info.inputWidth, 640)
        XCTAssertEqual(info.inputHeight, 640)
        XCTAssertTrue(info.endToEnd)
    }

    func test_metadata_imgszIsHeightThenWidth() throws {
        let info = try XCTUnwrap(DetectorModelInfo.parse(["names": "{0: 'a'}", "imgsz": "[480, 640]"]))
        XCTAssertEqual(info.inputWidth, 640)
        XCTAssertEqual(info.inputHeight, 480)
        XCTAssertFalse(info.endToEnd)
    }

    func test_names_acceptBothQuoteStyles_andDigitsInsideNames() {
        XCTAssertEqual(DetectorModelInfo.parseNames("{0: \"child's room\", 1: '3d glasses', 2: 'a, b'}"),
                       ["child's room", "3d glasses", "a, b"])
    }

    func test_names_withAGapInTheKeys_areRejected() {
        XCTAssertEqual(DetectorModelInfo.parseNames("{0: 'lamp', 2: 'vase'}"), [])
        XCTAssertNil(DetectorModelInfo.parse(["names": "{}", "imgsz": "[640, 640]"]))
    }

    // MARK: - Rows

    private func row(_ box: (Float, Float, Float, Float), score: Float, cls: Float,
                     coefficients: [Float] = [0.5, -0.5]) -> [Float] {
        [box.0, box.1, box.2, box.3, score, cls] + coefficients
    }

    func test_decode_keepsRowsAboveTheScore_bestFirst() {
        let rows = row((10, 10, 50, 60), score: 0.4, cls: 2)
            + row((100, 100, 200, 220), score: 0.9, cls: 1)
            + row((0, 0, 5, 5), score: 0.1, cls: 1)
        let out = DetectionDecoder.decode(rows: rows, rowCount: 3, rowLength: 8, classCount: 3,
                                          minimumScore: 0.25, modelWidth: 640, modelHeight: 640)
        XCTAssertEqual(out.map(\.classIndex), [1, 2])
        XCTAssertEqual(out[0].modelMin, SIMD2(100, 100))
        XCTAssertEqual(out[0].modelMax, SIMD2(200, 220))
        XCTAssertEqual(out[0].coefficients, [0.5, -0.5])
    }

    func test_decode_dropsAClassIndexThatIsNotAnInteger() {
        // An FP16 graph rounds odd indices above 2048 to their even
        // neighbours; a value between integers is corrupt, never rounded.
        let rows = row((10, 10, 50, 60), score: 0.9, cls: 1.5) + row((10, 10, 50, 60), score: 0.9, cls: 7)
        let out = DetectionDecoder.decode(rows: rows, rowCount: 2, rowLength: 8, classCount: 5,
                                          minimumScore: 0.25, modelWidth: 640, modelHeight: 640)
        XCTAssertTrue(out.isEmpty, "a non-integer class and an out-of-range class are both dropped")
    }

    func test_decode_dropsAClassThatIsNotANumber_insteadOfTrapping() {
        let bad: [Float] = [.nan, .infinity, -.infinity, 1e30, -1e30, -3]
        let rows = bad.flatMap { row((10, 10, 50, 60), score: 0.9, cls: $0) } + row((10, 10, 50, 60), score: 0.9, cls: 4)
        let out = DetectionDecoder.decode(rows: rows, rowCount: bad.count + 1, rowLength: 8, classCount: 5,
                                          minimumScore: 0.25, modelWidth: 640, modelHeight: 640)
        XCTAssertEqual(out.map(\.classIndex), [4])
    }

    func test_decode_clampsToTheInput_andDropsDegenerateBoxes() {
        let rows = row((-20, 600, 30, 700), score: 0.9, cls: 0) + row((40, 40, 40.5, 90), score: 0.9, cls: 0)
        let out = DetectionDecoder.decode(rows: rows, rowCount: 2, rowLength: 8, classCount: 1,
                                          minimumScore: 0.25, modelWidth: 640, modelHeight: 640)
        XCTAssertEqual(out.count, 1)
        XCTAssertEqual(out[0].modelMin, SIMD2(0, 600))
        XCTAssertEqual(out[0].modelMax, SIMD2(30, 640))
    }

    // MARK: - Masks

    /// Two 8×8 prototypes over a 32×32 input (stride 4): one positive on the
    /// left half, one positive on the top half.
    private func bank() -> ProtoBank {
        var values = [Float](repeating: 0, count: 2 * 64)
        for y in 0..<8 {
            for x in 0..<8 {
                values[y * 8 + x] = x < 4 ? 1 : -1
                values[64 + y * 8 + x] = y < 4 ? 1 : -1
            }
        }
        return ProtoBank(channels: 2, width: 8, height: 8, values: values, modelWidth: 32, modelHeight: 32)
    }

    func test_mask_isTheCoefficientsDottedIntoThePrototypes() {
        let det = RawDetection(classIndex: 0, score: 1, modelMin: SIMD2(0, 0), modelMax: SIMD2(32, 32),
                               coefficients: [1, 1])
        let mask = bank().mask(for: det)
        // Cell centres: (2, 2) is top-left (1 + 1), (30, 30) bottom-right (−1 − 1),
        // (30, 2) top-right (−1 + 1).
        XCTAssertEqual(mask.logit(model: SIMD2(2, 2)), 2, accuracy: 1e-5)
        XCTAssertEqual(mask.logit(model: SIMD2(30, 30)), -2, accuracy: 1e-5)
        XCTAssertEqual(mask.logit(model: SIMD2(30, 2)), 0, accuracy: 1e-5)
        // Halfway between cells (x = 16 sits between centres 14 and 18): linear.
        XCTAssertEqual(mask.logit(model: SIMD2(16, 2)), 1, accuracy: 1e-5)
        XCTAssertTrue(mask.contains(model: SIMD2(2, 2)))
        XCTAssertFalse(mask.contains(model: SIMD2(30, 30)))
    }

    func test_mask_isCroppedToTheBox() {
        let det = RawDetection(classIndex: 0, score: 1, modelMin: SIMD2(0, 0), modelMax: SIMD2(10, 10),
                               coefficients: [1, 0])
        let mask = bank().mask(for: det)
        XCTAssertTrue(mask.contains(model: SIMD2(5, 5)))
        XCTAssertFalse(mask.contains(model: SIMD2(12, 20)), "positive logit, but outside the box")
    }

    func test_depthMask_samplesAtDepthPixelCentres() throws {
        // A 640 model over a landscape frame: the left half of the model is the
        // left half of the image, so the left half of the depth map.
        var values = [Float](repeating: 0, count: 160 * 160)
        for y in 0..<160 { for x in 0..<160 { values[y * 160 + x] = x < 80 ? 4 : -4 } }
        let bank = ProtoBank(channels: 1, width: 160, height: 160, values: values, modelWidth: 640, modelHeight: 640)
        let det = RawDetection(classIndex: 0, score: 1, modelMin: SIMD2(0, 80), modelMax: SIMD2(640, 560),
                               coefficients: [1])
        let frame = SensorFrame(intrinsics: CameraIntrinsics(fx: 1500, fy: 1500, cx: 960, cy: 720,
                                                             width: 1920, height: 1440),
                                depthWidth: 256, depthHeight: 192, worldFromCamera: matrix_identity_float4x4,
                                turn: .none, modelWidth: 640, modelHeight: 640)
        let mask = try XCTUnwrap(bank.mask(for: det).depthMask(frame: frame))
        XCTAssertEqual(mask.count, 128 * 192)
        XCTAssertTrue(mask[127, 50])
        XCTAssertFalse(mask[128, 50])
    }
}
