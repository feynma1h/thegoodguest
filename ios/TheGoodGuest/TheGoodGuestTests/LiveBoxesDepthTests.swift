/// The depth-model seam on synthetic rooms: a relative map fitted to what ARKit
/// tracks without LiDAR, a model's map read onto the depth grid in every hold,
/// what the menu offers when no model is bundled, how a model's map is read
/// and described, LiDAR's score, and what the log keeps of it all.
///
/// EVERY PIN HAS A CONTROL THAT MUST FAIL: the same arithmetic with the one
/// thing under test taken away — the robust step, the right turn, enough
/// anchors, the right kind of map — misses the bar the pin holds.
///
/// See LiveBoxesSyntheticScene for how a model's map and ARKit's anchors are
/// rendered, and why that code shares nothing with the maps it tests.

import CoreML
import CoreVideo
import simd
import XCTest
@testable import TheGoodGuest

final class LiveBoxesDepthTests: XCTestCase {

    // MARK: - The room

    private static func degrees(_ d: Float) -> Float { d * .pi / 180 }

    /// Furniture standing on the floor, so much of the floor's outline in view
    /// is hidden behind something.
    private static let room = SyntheticScene(objects: [
        SyntheticObject(id: 0, name: "sofa",
                        box: GravityBox(center: SIMD3(0.2, 0.42, -1.5), size: SIMD3(2.0, 0.84, 0.9), yaw: 0)),
        SyntheticObject(id: 1, name: "armchair",
                        box: GravityBox(center: SIMD3(1.5, 0.45, -0.3), size: SIMD3(0.8, 0.9, 0.8), yaw: degrees(-30))),
        SyntheticObject(id: 2, name: "coffee table",
                        box: GravityBox(center: SIMD3(0.2, 0.22, -0.4), size: SIMD3(1.1, 0.44, 0.6), yaw: degrees(5))),
        SyntheticObject(id: 3, name: "lamp",
                        box: GravityBox(center: SIMD3(-1.6, 0.8, -1.4), size: SIMD3(0.4, 1.6, 0.4), yaw: 0)),
        SyntheticObject(id: 4, name: "bookshelf",
                        box: GravityBox(center: SIMD3(-2.3, 0.9, 0.2), size: SIMD3(0.35, 1.8, 0.9), yaw: 0)),
    ])

    /// Standing by one wall, looking across the room, the phone upright.
    private static let camera = SyntheticCamera(eye: SIMD3(-0.4, 1.45, 1.7), target: SIMD3(0.3, 0.4, -1.0),
                                                roll: .pi / 2)

    /// A model's units: disparity d = a / z + b, which a fit undoes with
    /// scale 1/a and shift −b/a.
    private static let a: Float = 0.8
    private static let b: Float = 0.35

    /// Apple's conversion of Depth Anything V2 takes 518×392.
    private static let input = (width: 518, height: 392)

    private static func upright(_ camera: SyntheticCamera) -> QuarterTurn {
        QuarterTurn.upright(gravity: PoseExtractor.gravityInCameraFrame(simd_quaternion(camera.worldFromCamera)),
                            previous: nil)
    }

    /// A pass's frame, built at the depth model's input size.
    private static func frame(_ camera: SyntheticCamera, turn: QuarterTurn? = nil) -> SensorFrame {
        SensorFrame(intrinsics: SyntheticScene.intrinsics, depthWidth: SyntheticScene.depthWidth,
                    depthHeight: SyntheticScene.depthHeight, worldFromCamera: camera.worldFromCamera,
                    turn: turn ?? upright(camera), modelWidth: input.width, modelHeight: input.height)
    }

    private static func medianError(_ depth: [Float], _ truth: [Float]) -> Float {
        let errors = zip(depth, truth).map { $0 > 0 ? abs($0 - $1) / $1 : .infinity }.sorted()
        return errors[errors.count / 2]
    }

    private static func anchors(count: Int = 150, outliers: Float = 0.2, floor: Bool = true,
                                camera: SyntheticCamera = camera, seed: UInt64 = 11) -> DepthAnchors {
        var rng = SeededGenerator(seed: seed)
        return DepthAnchors(featurePoints: room.featurePoints(camera: camera, count: count, noise: 0.015,
                                                             outliers: outliers, rng: &rng),
                            planes: floor ? [room.floorAnchor()] : [])
    }

    // MARK: - The fit

    func test_theFit_recoversAKnownScaleAndShift_fromTheFloorAndNoisyFeaturePoints() throws {
        let frame = Self.frame(Self.camera)
        let truth = Self.room.trueDepth(camera: Self.camera)
        let map = truth.map { Self.a / $0 + Self.b }
        let anchors = Self.anchors()

        let fit = DepthAlignment.fit(kind: .disparity, grid: map, frame: frame, anchors: anchors)
        XCTAssertNil(fit.failure)
        XCTAssertEqual(fit.scale, 1 / Self.a, accuracy: 0.01 / Self.a)
        XCTAssertEqual(fit.shift, -Self.b / Self.a, accuracy: 0.01)
        let depth = DepthAlignment.grid(map, width: frame.depthWidth, height: frame.depthHeight, kind: .disparity,
                                        fit: fit).depth
        XCTAssertLessThan(Self.medianError(depth, truth), 0.005)
        XCTAssertGreaterThan(fit.planeAnchors, 40)
        XCTAssertLessThan(fit.inliers, fit.anchors - 30, "the anchors carry the outliers the fit must refuse")

        // CONTROL: least squares alone, over the same anchors, is pulled off
        // by the floor hidden behind the furniture and the stray feature points.
        let targets = DepthAlignment.targets(anchors, frame: frame)
        let values = targets.map {
            DepthAlignment.sample(map, width: frame.depthWidth, height: frame.depthHeight, at: $0.point)
        }
        let plain = try XCTUnwrap(DepthAlignment.leastSquares(kind: .disparity, values: values,
                                                              depths: targets.map(\.depth)))
        let plainDepth = map.map { DepthAlignment.metres($0, kind: .disparity, scale: plain.scale, shift: plain.shift) }
        XCTAssertGreaterThan(Self.medianError(plainDepth, truth), 0.02)
    }

    func test_theFit_recoversAScale_forAMapOfRelativeDepth() {
        let frame = Self.frame(Self.camera)
        let truth = Self.room.trueDepth(camera: Self.camera)
        var rng = SeededGenerator(seed: 5)
        // Relative depth, with a percent of the model's own error on every pixel.
        let map = truth.map { $0 / 1.7 * (1 + 0.01 * rng.gaussian()) }

        let fit = DepthAlignment.fit(kind: .depth, grid: map, frame: frame, anchors: Self.anchors())
        XCTAssertNil(fit.failure)
        XCTAssertEqual(fit.shift, 0)
        XCTAssertEqual(fit.scale, 1.7, accuracy: 0.017)

        // CONTROL: the same map read as disparity cannot be fitted: nearer
        // would have to be farther.
        let wrong = DepthAlignment.fit(kind: .disparity, grid: map, frame: frame, anchors: Self.anchors())
        XCTAssertEqual(wrong.failure, .anchorsDisagree)
    }

    func test_tooFewAnchors_giveTheFrameNoDepth_andSaySo() {
        let frame = Self.frame(Self.camera)
        let map = Self.room.trueDepth(camera: Self.camera).map { Self.a / $0 + Self.b }

        let few = DepthAlignment.fit(kind: .disparity, grid: map, frame: frame,
                                     anchors: Self.anchors(count: 12, outliers: 0, floor: false))
        XCTAssertEqual(few.failure, .tooFewAnchors)
        XCTAssertEqual(few.anchors, 12)

        // CONTROL: enough feature points alone are enough.
        let enough = DepthAlignment.fit(kind: .disparity, grid: map, frame: frame,
                                        anchors: Self.anchors(count: 60, outliers: 0, floor: false))
        XCTAssertNil(enough.failure)
    }

    func test_aMapTheAnchorsDisagreeWith_givesTheFrameNoDepth() {
        let frame = Self.frame(Self.camera)
        // A map of another view: the camera turned to face the side wall.
        let elsewhere = SyntheticCamera(eye: SIMD3(-0.4, 1.45, 1.7), target: SIMD3(2.4, 1.0, 1.2), roll: .pi / 2)
        let wrongMap = Self.room.trueDepth(camera: elsewhere).map { Self.a / $0 + Self.b }

        let fit = DepthAlignment.fit(kind: .disparity, grid: wrongMap, frame: frame, anchors: Self.anchors())
        XCTAssertEqual(fit.failure, .anchorsDisagree)

        // CONTROL: the frame's own map, the same anchors.
        let map = Self.room.trueDepth(camera: Self.camera).map { Self.a / $0 + Self.b }
        XCTAssertNil(DepthAlignment.fit(kind: .disparity, grid: map, frame: frame, anchors: Self.anchors()).failure)
    }

    func test_aPlaneAnchors_onlyWhereItsMeasuredOutlineIsInView_atTheFloorsDepth() {
        let frame = Self.frame(Self.camera)
        let truth = Self.room.trueDepth(camera: Self.camera)
        let inset: Float = 1.2
        let patch = DepthAlignment.targets(DepthAnchors(planes: [Self.room.floorAnchor(inset: inset)]), frame: frame)
        let whole = DepthAlignment.targets(DepthAnchors(planes: [Self.room.floorAnchor()]), frame: frame)
        XCTAssertGreaterThan(patch.count, 10)
        XCTAssertLessThan(patch.count, whole.count, "CONTROL: the whole floor's outline gives more")

        let sx = SyntheticScene.imageWidth / Float(SyntheticScene.depthWidth)
        let sy = SyntheticScene.imageHeight / Float(SyntheticScene.depthHeight)
        var seenOnTheFloor = 0
        for target in patch {
            XCTAssertTrue(target.onPlane)
            // Where the pixel's ray meets that depth, by the scene's own camera.
            let p = Self.camera.eye + Self.room.ray(camera: Self.camera, u: target.point.x * sx,
                                                    v: target.point.y * sy) * target.depth
            XCTAssertEqual(p.y, 0, accuracy: 1e-3)
            XCTAssertLessThanOrEqual(abs(p.x), Self.room.halfX - inset + 1e-3)
            XCTAssertLessThanOrEqual(abs(p.z), Self.room.halfZ - inset + 1e-3)
            let k = Int(target.point.y) * SyntheticScene.depthWidth + Int(target.point.x)
            if abs(truth[k] - target.depth) < 1e-3 { seenOnTheFloor += 1 }
        }
        XCTAssertGreaterThan(seenOnTheFloor, patch.count / 2, "most of the patch is in plain view")
        XCTAssertLessThan(seenOnTheFloor, patch.count, "and some of it is behind the coffee table")
    }

    // MARK: - Onto the grid

    func test_theMapIsReadOntoTheDepthGrid_throughTheTurnAndTheLetterbox_inEveryHold() {
        // A map at half the input's resolution whose value is its own place,
        // and whose pixels over the letterbox's padding hold a wild value.
        // Bilinear reading gives back the place exactly wherever the grid
        // lands — held at the image's last pixel centres — and never the padding.
        let output = (width: Self.input.width / 2, height: Self.input.height / 2)
        func place(_ p: SIMD2<Float>) -> Float { 0.01 * p.x + 0.02 * p.y }

        func worstMiss(reading turn: QuarterTurn, as truth: QuarterTurn) -> Float {
            let region = Self.imageRegion(truth, scale: 0.5)
            var values = [Float](repeating: 0, count: output.width * output.height)
            for j in 0..<output.height {
                for i in 0..<output.width {
                    let c = SIMD2(Float(i) + 0.5, Float(j) + 0.5)
                    let onImage = c.x >= region.lo.x && c.y >= region.lo.y && c.x <= region.hi.x && c.y <= region.hi.y
                    values[j * output.width + i] = onImage ? place(c) : 1000
                }
            }
            let map = DepthModelMap(width: output.width, height: output.height, values: values)
            let grid = DepthAlignment.resample(map, frame: Self.frame(Self.camera, turn: turn))
            // The first and last map pixel centres on the image.
            let first = (region.lo - 0.5).rounded(.up) + 0.5, last = (region.hi - 0.5).rounded(.down) + 0.5
            var worst: Float = 0
            for y in 0..<SyntheticScene.depthHeight {
                for x in 0..<SyntheticScene.depthWidth {
                    let image = SIMD2((Float(x) + 0.5) * 7.5, (Float(y) + 0.5) * 7.5)
                    let m = simd_clamp(Self.modelPoint(image: image, turn: truth) / 2, first, last)
                    worst = max(worst, abs(grid[y * SyntheticScene.depthWidth + x] - place(m)))
                }
            }
            return worst
        }
        for turn in QuarterTurn.allCases {
            XCTAssertLessThan(worstMiss(reading: turn, as: turn), 1e-4, "\(turn)")
            // CONTROL: read through the next quarter-turn, the map lands elsewhere.
            let wrong = QuarterTurn(rawValue: (turn.rawValue + 1) % 4)!
            XCTAssertGreaterThan(worstMiss(reading: wrong, as: turn), 0.5, "\(turn) read as \(wrong)")
        }
    }

    func test_aModelsMapOfTheRoom_becomesItsDepthInMetres_inEveryHold() {
        let output = (width: Self.input.width / 2, height: Self.input.height / 2)
        for roll: Float in [0, .pi / 2, -.pi / 2, .pi] {
            let camera = SyntheticCamera(eye: Self.camera.eye, target: SIMD3(0.3, 0.4, -1.0), roll: roll)
            let turn = Self.upright(camera)
            let truth = Self.room.trueDepth(camera: camera)
            let map = Self.room.modelMap(camera: camera, turn: turn, input: Self.input, output: output) {
                Self.a / $0 + Self.b
            }
            func error(readingAs turn: QuarterTurn) -> Float {
                let frame = Self.frame(camera, turn: turn)
                let values = DepthAlignment.resample(map, frame: frame)
                let fit = DepthAlignment.fit(kind: .disparity, grid: values, frame: frame,
                                             anchors: Self.anchors(camera: camera))
                guard fit.failure == nil else { return .infinity }
                return Self.medianError(DepthAlignment.grid(values, width: frame.depthWidth, height: frame.depthHeight,
                                                            kind: .disparity, fit: fit).depth, truth)
            }
            XCTAssertLessThan(error(readingAs: turn), 0.01, "roll \(roll), \(turn)")
            // CONTROL: the right map read through the wrong turn is not the room.
            XCTAssertGreaterThan(error(readingAs: QuarterTurn(rawValue: (turn.rawValue + 1) % 4)!), 0.05,
                                 "roll \(roll)")
        }
    }

    /// Camera image → the depth model's input, written as a rotation about the
    /// image centre and a letterbox rather than with `SensorFrame`.
    private static func modelPoint(image p: SIMD2<Float>, turn: QuarterTurn) -> SIMD2<Float> {
        let size = SIMD2(SyntheticScene.imageWidth, SyntheticScene.imageHeight)
        let turned = turn.rawValue % 2 == 0 ? size : SIMD2(size.y, size.x)
        let angle = Float(turn.rawValue) * .pi / 2
        let c = cos(angle).rounded(), s = sin(angle).rounded()
        let rel = p - size / 2
        // Clockwise by k quarters on screen, y down: (1, 0) → (c, s).
        let upright = SIMD2(c * rel.x - s * rel.y, s * rel.x + c * rel.y) + turned / 2
        let target = SIMD2(Float(input.width), Float(input.height))
        let scale = min(target.x / turned.x, target.y / turned.y)
        return upright * scale + (target - turned * scale) / 2
    }

    /// Where the camera image lies in the depth model's input, as `scale`
    /// times input coordinates: inside the letterbox's padding.
    private static func imageRegion(_ turn: QuarterTurn, scale k: Float) -> (lo: SIMD2<Float>, hi: SIMD2<Float>) {
        let size = SIMD2(SyntheticScene.imageWidth, SyntheticScene.imageHeight)
        let turned = turn.rawValue % 2 == 0 ? size : SIMD2(size.y, size.x)
        let target = SIMD2(Float(input.width), Float(input.height))
        let scale = min(target.x / turned.x, target.y / turned.y)
        let pad = (target - turned * scale) / 2
        return (pad * k, (target - pad) * k)
    }

    // MARK: - Which model

    func test_withNoDepthModelBundled_noModelIsChosen() {
        // The test bundle carries no model: a checkout without one.
        let found = DepthCatalog.bundled(in: Bundle(for: LiveBoxesDepthTests.self))
        XCTAssertTrue(found.isEmpty)
        XCTAssertNil(DepthPolicy.modelStem(among: found.map(\.stem)))
    }

    func test_depthAnything2_isTheDefault_andVersion3IsSwitchedOff() {
        XCTAssertFalse(DepthPolicy.allowsDepthAnything3, "v3 stays in the code and out of use")
        let both = [DepthPolicy.depthAnything3Stem, DepthPolicy.depthAnything2Stem]
        XCTAssertEqual(DepthPolicy.modelStem(among: both), DepthPolicy.depthAnything2Stem)
        XCTAssertNil(DepthPolicy.modelStem(among: [DepthPolicy.depthAnything3Stem]),
                     "v3 alone is not chosen while it is switched off")
        XCTAssertNil(DepthPolicy.modelStem(among: ["depth_other"]))
    }

    // MARK: - A model, described and read

    func test_aModelsDescription_readsTheContract_andNoKindMeansDisparity() {
        XCTAssertEqual(DepthModelInfo.parse([:], stem: "depth_da2_small"),
                       DepthModelInfo(name: "depth_da2_small", kind: .disparity, source: nil, license: nil))
        let full = DepthModelInfo.parse([DepthModelInfo.kindKey: "depth", DepthModelInfo.nameKey: "DA3 Small",
                                         DepthModelInfo.sourceKey: "https://huggingface.co/depth-anything/DA3-SMALL",
                                         DepthModelInfo.licenseKey: "Apache-2.0"], stem: "depth_da3_small")
        XCTAssertEqual(full, DepthModelInfo(name: "DA3 Small", kind: .depth,
                                            source: "https://huggingface.co/depth-anything/DA3-SMALL",
                                            license: "Apache-2.0"))
        XCTAssertEqual(DepthModelInfo.parse([DepthModelInfo.kindKey: "metric"], stem: "depth_x")?.kind, .metric)
        // CONTROL: a kind the contract does not name is refused, never guessed.
        XCTAssertNil(DepthModelInfo.parse([DepthModelInfo.kindKey: "inverse depth"], stem: "depth_x"))
    }

    func test_theOutputsRead_areTheOnesTheMetadataNames_orTheOnlyMap() {
        func choose(_ maps: Set<String>, _ metadata: [String: String] = [:]) -> [String?]? {
            DepthModelOutputs.choose(maps: maps, metadata: metadata).map { [$0.map, $0.confidence] }
        }
        let both: [String: String] = [DepthModelInfo.outputKey: "depth", DepthModelInfo.confidenceKey: "confidence"]
        XCTAssertEqual(choose(["disparity"]), ["disparity", nil], "the only map, as Apple's DA2 has it")
        XCTAssertEqual(choose(["depth", "confidence"], both), ["depth", "confidence"], "both named, as DA3's export")
        XCTAssertEqual(choose(["depth", "confidence"], [DepthModelInfo.confidenceKey: "confidence"]),
                       ["depth", "confidence"], "the confidence named, the map the one left")
        // CONTROLS: two maps and no names is ambiguous; a name must be an output, and not both.
        XCTAssertNil(choose(["depth", "confidence"]))
        XCTAssertNil(choose(["depth"], [DepthModelInfo.outputKey: "inverse_depth"]))
        XCTAssertNil(choose(["depth", "confidence"], [DepthModelInfo.outputKey: "depth",
                                                      DepthModelInfo.confidenceKey: "depth"]))
    }

    func test_aModelsOwnConfidence_marksItsLeastSurePixels_andLiDARSaysHowTheyFare() throws {
        let w = 20, h = 10, n = w * h
        // Disparity 1/z exactly, so the identity fit gives the model's depth back.
        let lidar = (0..<n).map { 1.0 + Float($0 % w) * 0.1 }
        var depth = lidar
        // The model is surest where it is right: its worst 20 pixels, 10 % off,
        // carry the least confidence.
        var own = [Float](repeating: 3, count: n)
        for k in 0..<20 {
            own[k * 7] = 1.0 + Float(k) * 0.001
            depth[k * 7] = lidar[k * 7] * 1.1
        }
        let values = depth.map { 1 / $0 }
        let fit = DepthFit(scale: 1, shift: 0, anchors: 100, inliers: 100, residual: 0.03)

        let grid = DepthAlignment.grid(values, width: w, height: h, kind: .disparity, fit: fit, own: own)
        let unsure = Set(grid.confidence!.indices.filter { grid.confidence![$0] == 0 })
        XCTAssertEqual(unsure.count, Int(Float(n - 1) * DepthAlignment.unsurePercentile), "the frame's lowest tenth")
        XCTAssertTrue(unsure.allSatisfy { $0 % 7 == 0 && $0 < 140 })
        XCTAssertEqual(Set(grid.confidence!.filter { $0 != 0 }), [2], "the rest carry the fit's own confidence")
        // CONTROL: a model with no confidence of its own marks nothing.
        XCTAssertFalse(DepthAlignment.grid(values, width: w, height: h, kind: .disparity, fit: fit).confidence!
            .contains(0))

        let score = try XCTUnwrap(DepthAlignment.score(grid, against: DepthGrid(width: w, height: h, depth: lidar,
                                                                             confidence: nil),
                                                       values: values, kind: .disparity))
        XCTAssertEqual(score.unsurePixels, unsure.count)
        XCTAssertEqual(score.unsureMedianError ?? -1, 0.1, accuracy: 1e-4, "the unsure pixels are the bad ones")
        XCTAssertEqual(score.medianError ?? -1, 0, accuracy: 1e-5)
    }

    func test_aMap_readsFromEveryShapeTheContractAllows() throws {
        let values = (0..<12).map { Float($0) * 0.25 }
        let halves = try MLMultiArray(shape: [1, 1, 3, 4], dataType: .float16)
        let floats = try MLMultiArray(shape: [1, 3, 4], dataType: .float32)
        for (k, v) in values.enumerated() {
            halves[k] = NSNumber(value: v)
            floats[k] = NSNumber(value: v)
        }
        for array in [halves, floats] {
            let map = try DepthModelMap.read(MLFeatureValue(multiArray: array))
            XCTAssertEqual(map.width, 4)
            XCTAssertEqual(map.height, 3)
            XCTAssertEqual(map.values, values)
        }

        // A greyscale half-float image, rows padded past their width.
        var buffer: CVPixelBuffer?
        CVPixelBufferCreate(nil, 4, 3, kCVPixelFormatType_OneComponent16Half,
                            [kCVPixelBufferBytesPerRowAlignmentKey as String: 64] as CFDictionary, &buffer)
        let image = try XCTUnwrap(buffer)
        CVPixelBufferLockBaseAddress(image, [])
        let base = try XCTUnwrap(CVPixelBufferGetBaseAddress(image))
        let stride = CVPixelBufferGetBytesPerRow(image)
        XCTAssertGreaterThan(stride, 8, "the rows are padded, as the test needs")
        for y in 0..<3 {
            for x in 0..<4 {
                base.storeBytes(of: Float16(values[y * 4 + x]), toByteOffset: y * stride + x * 2, as: Float16.self)
            }
        }
        CVPixelBufferUnlockBaseAddress(image, [])
        XCTAssertEqual(try DepthModelMap.read(image).values, values)

        // CONTROL: two channels are not one map.
        let two = try MLMultiArray(shape: [1, 2, 3, 4], dataType: .float32)
        XCTAssertThrowsError(try DepthModelMap.read(MLFeatureValue(multiArray: two)))
    }

    // MARK: - LiDAR referees

    func test_theScore_isTheMedianRelativeError_overallAndByBand_onLiDARsSurePixels() throws {
        // LiDAR at 0.5, 1.5, 2.5 and 4 m in four bands of rows; the model 2 %,
        // 4 %, 6 % and 8 % farther in each, and a row LiDAR was unsure of.
        let w = 10, h = 5
        let lidarDepths: [Float] = [0.5, 1.5, 2.5, 4.0, 1.0]
        let off: [Float] = [0.02, 0.04, 0.06, 0.08, 0.5]
        var lidar: [Float] = [], model: [Float] = [], confidence: [UInt8] = []
        for row in 0..<h {
            for _ in 0..<w {
                lidar.append(lidarDepths[row])
                model.append(lidarDepths[row] * (1 + off[row]))
                confidence.append(row == 4 ? 1 : 2)
            }
        }
        // The map the model's depth came from: disparity 1/z, exactly.
        let values = model.map { 1 / $0 }
        let score = try XCTUnwrap(DepthAlignment.score(
            DepthGrid(width: w, height: h, depth: model, confidence: [UInt8](repeating: 2, count: w * h)),
            against: DepthGrid(width: w, height: h, depth: lidar, confidence: confidence),
            values: values, kind: .disparity))
        XCTAssertEqual(score.pixels, 40, "CONTROL: LiDAR's unsure row is not scored")
        XCTAssertEqual(score.bands.map(\.upTo), [1, 2, 3, 5])
        XCTAssertEqual(score.bands.map(\.pixels), [10, 10, 10, 10])
        for (band, expected) in zip(score.bands, off) {
            XCTAssertEqual(band.medianError ?? -1, expected, accuracy: 1e-5)
        }
        XCTAssertEqual(score.medianError ?? -1, 0.06, accuracy: 1e-5, "the upper median of 2, 4, 6, 8 %")
        XCTAssertNotNil(score.bestFitMedianError)
    }

    // MARK: - The log

    func test_theLog_namesEveryPassesDepthSource_andKeepsAModelsFailuresApart() throws {
        var log = SessionLog(startedAt: "2026-09-20T10:00:00Z",
                             device: .init(model: "iPhone17,1", system: "iOS 27.0", app: "1.0 (1)", optimized: true),
                             lift: DepthLiftParameters(), fusion: FusionParameters())
        let fit = DepthFit(scale: 1.25, shift: -0.44, anchors: 212, planeAnchors: 150, inliers: 180, residual: 0.041)
        let score = DepthScore(pixels: 40_000, medianError: 0.06,
                               bands: [.init(upTo: 1, pixels: 9000, medianError: 0.04)], bestFitMedianError: 0.03)
        func result(_ depth: DepthPassLog, failure: String? = nil) -> PassResult {
            PassResult(time: 0, timing: PassTiming(predict: 20, depth: 33, align: 4), detections: 3, lifted: 1,
                       excluded: 0, turn: .clockwise, tracks: [], failure: failure, depth: depth)
        }
        XCTAssertTrue(log.record(result(DepthPassLog(source: "LiDAR")), at: 1))
        XCTAssertTrue(log.record(result(DepthPassLog(source: "DA2 Small", fit: fit, againstLidar: score)), at: 2))
        var failed = DepthPassLog(source: "DA2 Small", fit: DepthFit(anchors: 7, failure: .tooFewAnchors))
        failed.failure = "no fit: too few anchors"
        XCTAssertFalse(log.record(result(failed, failure: "no depth from DA2 Small"), at: 3))
        // CONTROL: a failure that is not the model's — the detector's own —
        // is not a depth failure.
        XCTAssertFalse(log.record(result(DepthPassLog(source: "DA2 Small", fit: fit), failure: "prediction failed"),
                                  at: 4))

        XCTAssertEqual(log.passes.map { $0.depth?.source }, ["LiDAR", "DA2 Small"])
        XCTAssertEqual(log.passes[1].depth?.againstLidar?.medianError, 0.06)
        XCTAssertEqual(log.depthFailures.map(\.t), [3])
        XCTAssertEqual(log.depthFailures.first?.predictMs, 33)
        XCTAssertEqual(log.depthFailures.first?.depth.fit?.failure, .tooFewAnchors)

        let decoded = try JSONDecoder().decode(SessionLog.self, from: log.encoded())
        XCTAssertEqual(decoded.passes, log.passes)
        XCTAssertEqual(decoded.depthFailures, log.depthFailures)

        // Numbers and names only, as everything else in the log.
        let forbidden = ["image", "mask", "raster", "rgb", "jpeg", "png", "photo", "person", "people", "face"]
        var names: [String] = []
        func collect(_ value: Any) {
            for child in Mirror(reflecting: value).children {
                if let label = child.label { names.append(label.lowercased()) }
                collect(child.value)
            }
        }
        collect(log)
        for name in names { XCTAssertFalse(forbidden.contains { name.contains($0) }, "log field '\(name)'") }
    }
}
