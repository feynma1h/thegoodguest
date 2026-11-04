/// The bundled detector export, when a build has one: that it loads, that its
/// shape is the one the decoder reads, that every class name it carries is in
/// the tracked vocabulary table, and that a whole pass runs on a synthetic
/// frame without failing. And every bundled depth model: that it loads by the
/// depth-model contract, describes itself the same way without loading, and
/// maps its whole input; and that a pass with it for depth runs, or says why
/// the frame had no depth.
///
/// SKIPPED, NOT FAILED, WITHOUT A MODEL. The export is untracked (decision
/// 0295), so a plain checkout has none; these tests skip there and the rest of
/// the suite is unaffected. With an export dropped into LiveBoxes/Model/ they
/// are the first place a mismatched export shows up — before a phone does.

import CoreVideo
import simd
import XCTest
@testable import TheGoodGuest

final class LiveBoxesModelTests: XCTestCase {

    private func bundled() throws -> BundledDetector {
        try XCTSkipIf(DetectorCatalog.bundled().isEmpty, "no detector export in this build")
        return try XCTUnwrap(DetectorCatalog.choose(DetectorCatalog.bundled(), requested: nil))
    }

    func test_export_loads_andIsTheEndToEndSegmentationHead() throws {
        let loaded = try LoadedDetector.load(try bundled(), compute: .cpu)
        XCTAssertTrue(loaded.info.endToEnd)
        XCTAssertEqual(loaded.info.inputWidth, loaded.info.inputHeight)
        XCTAssertLessThan(loaded.info.names.count, 2048)
    }

    func test_everyExportedName_isInTheVocabularyTable() throws {
        for model in DetectorCatalog.bundled() {
            let loaded = try LoadedDetector.load(model, compute: .cpu)
            let unknown = loaded.info.names.filter { !DetectorVocabulary.knows($0) }
            XCTAssertEqual(unknown, [], "\(model.name) carries names the table does not know")
        }
        try XCTSkipIf(DetectorCatalog.bundled().isEmpty, "no detector export in this build")
    }

    /// A camera frame as ARKit delivers one: 1920×1440 YCbCr, flat grey.
    private func cameraImage() throws -> CVPixelBuffer {
        var buffer: CVPixelBuffer?
        CVPixelBufferCreate(nil, 1920, 1440, kCVPixelFormatType_420YpCbCr8BiPlanarFullRange,
                            [kCVPixelBufferIOSurfacePropertiesKey as String: [:] as [String: Any]] as CFDictionary,
                            &buffer)
        let image = try XCTUnwrap(buffer)
        CVPixelBufferLockBaseAddress(image, [])
        memset(CVPixelBufferGetBaseAddressOfPlane(image, 0), 90, CVPixelBufferGetBytesPerRowOfPlane(image, 0) * 1440)
        memset(CVPixelBufferGetBaseAddressOfPlane(image, 1), 128, CVPixelBufferGetBytesPerRowOfPlane(image, 1) * 720)
        CVPixelBufferUnlockBaseAddress(image, [])
        return image
    }

    func test_aWholePass_runsOnASyntheticFrame() throws {
        let pipeline = DetectorPipeline(detector: try LoadedDetector.load(try bundled(), compute: .cpu))
        let image = try cameraImage()
        let depth = DepthGrid(width: 256, height: 192, depth: [Float](repeating: 2, count: 256 * 192),
                              confidence: [UInt8](repeating: 2, count: 256 * 192))
        let snapshot = FrameSnapshot(image: PixelBufferHandoff(image), depth: depth,
                                     intrinsics: CameraIntrinsics(fx: 1500, fy: 1500, cx: 960, cy: 720,
                                                                  width: 1920, height: 1440),
                                     worldFromCamera: matrix_identity_float4x4,
                                     surfaces: [], time: 1)
        let result = pipeline.process(snapshot)
        XCTAssertNil(result.failure)
        XCTAssertGreaterThan(result.timing.predict, 0)
        XCTAssertNil(snapshot.image.take(), "the pass took the camera buffer and let it go")
    }

    // MARK: - Depth models

    func test_bundledDepthModels_loadByTheContract_andMapTheirWholeInput() async throws {
        let models = DepthCatalog.bundled()
        try XCTSkipIf(models.isEmpty, "no depth model in this build")
        for model in models {
            let loaded = try LoadedDepthModel.load(model, compute: .cpu)
            let described = try await DepthCatalog.describe(model)
            XCTAssertEqual(described, loaded.info, "\(model.stem) describes itself the same way unloaded")
            let runner = DepthModelRunner(model: loaded)
            let frame = SensorFrame(intrinsics: CameraIntrinsics(fx: 1500, fy: 1500, cx: 960, cy: 720,
                                                                 width: 1920, height: 1440),
                                    depthWidth: 256, depthHeight: 192, worldFromCamera: matrix_identity_float4x4,
                                    turn: .clockwise, modelWidth: 640, modelHeight: 640)
            let input = try XCTUnwrap(runner.render(try cameraImage(), frame: frame))
            XCTAssertEqual(CVPixelBufferGetWidth(input), loaded.inputWidth)
            XCTAssertEqual(CVPixelBufferGetHeight(input), loaded.inputHeight)
            let prediction = try loaded.predict(input)
            let map = prediction.map
            XCTAssertGreaterThan(map.width * map.height, 0)
            XCTAssertTrue(map.values.allSatisfy(\.isFinite), "\(model.stem)")
            XCTAssertEqual(DepthAlignment.resample(map, frame: runner.frame(frame)).count, 256 * 192)
            XCTAssertEqual(prediction.confidence != nil, loaded.confidenceName != nil,
                           "\(model.stem) returns its own confidence exactly when its metadata names one")
        }
    }

    func test_aWholePass_withADepthModel_saysWhyAFrameWithNoAnchorsHadNoDepth() throws {
        let models = DepthCatalog.bundled()
        try XCTSkipIf(models.isEmpty, "no depth model in this build")
        let model = try LoadedDepthModel.load(models[0], compute: .cpu)
        let pipeline = DetectorPipeline(detector: try LoadedDetector.load(try bundled(), compute: .cpu),
                                        depth: .model(DepthModelRunner(model: model)))
        // No LiDAR, and nothing ARKit tracked: the model's map has no units.
        let snapshot = FrameSnapshot(image: PixelBufferHandoff(try cameraImage()), depth: nil,
                                     intrinsics: CameraIntrinsics(fx: 1500, fy: 1500, cx: 960, cy: 720,
                                                                  width: 1920, height: 1440),
                                     worldFromCamera: matrix_identity_float4x4, surfaces: [], time: 1)
        let result = pipeline.process(snapshot)
        XCTAssertEqual(result.failure, "no depth from \(model.info.name)")
        XCTAssertEqual(result.depth?.source, model.info.name)
        XCTAssertEqual(result.depth?.fit?.failure, .tooFewAnchors)
        XCTAssertGreaterThan(result.timing.depth, 0, "the model ran")
        XCTAssertEqual(result.timing.predict, 0, "the detector did not")
        XCTAssertNil(snapshot.image.take(), "the pass took the camera buffer and let it go")
    }
}
