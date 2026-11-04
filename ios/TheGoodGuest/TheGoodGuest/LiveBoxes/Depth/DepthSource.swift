/// Where a pass's depth comes from — LiDAR's `sceneDepth`, or a depth model run
/// on the same camera frame and fitted to ARKit's anchors — and the parameters
/// that assume one or the other — DEBUG-only (decision 0295).
///
/// EVERYTHING DOWNSTREAM IS UNCHANGED. The lifter and fusion receive a metric
/// `DepthGrid` on the depth map's own raster (256×192, as `sceneDepth` is)
/// either way, with a confidence: LiDAR's own, or the model frame's fit
/// (`DepthAlignment`). A model's input is rendered from the camera buffer the
/// detector's input is rendered from, in the same pass, before it goes back to
/// ARKit.
///
/// WHAT ASSUMES LIDAR, AND WHAT A MODEL GETS INSTEAD. LiDAR's depth is off by a
/// centimetre or two, pixel by pixel. A fitted model's is smooth and off by a
/// few percent of the range, the whole map at once, and differently in the
/// next frame. So the bands that take a floor, a table top or a wall out of an
/// object's points, the margin that sets a box down on the floor, and fusion's
/// tolerances for a voxel being seen or seen through are wider for a model.
/// The edge step, the border agreement and the confidence threshold stay: a
/// model's map is locally smooth, so its steps are real edges, and every pixel
/// of a frame that passed its fit has medium confidence at least — unless the
/// model's own confidence marks it unsure.
///
/// A NEW SOURCE STARTS THE BOXES AFRESH, as a new detector does: boxes built
/// from one source's depth never mix with another's.
///
/// LIDAR REFEREES. On a phone that has it, a pass whose depth came from a model
/// is scored against LiDAR's depth of the same frame (`DepthScore`).
///
/// Read by: DetectorPipeline, LiveBoxesSession, LiveBoxesPresentation, LiveBoxesDepthTests.

#if DEBUG

import CoreVideo
import Foundation

/// A depth model ready to run: the model, and the render of its input. Used
/// from the pipeline queue.
nonisolated final class DepthModelRunner: @unchecked Sendable {
    let model: LoadedDepthModel
    private let preprocessor: FramePreprocessor

    init(model: LoadedDepthModel) {
        self.model = model
        preprocessor = FramePreprocessor(width: model.inputWidth, height: model.inputHeight)
    }

    /// A pass's frame with the model's input in place of the detector's.
    func frame(_ frame: SensorFrame) -> SensorFrame {
        SensorFrame(intrinsics: frame.intrinsics, depthWidth: frame.depthWidth, depthHeight: frame.depthHeight,
                    worldFromCamera: frame.worldFromCamera, turn: frame.turn,
                    modelWidth: model.inputWidth, modelHeight: model.inputHeight)
    }

    func render(_ image: CVPixelBuffer, frame: SensorFrame) -> CVPixelBuffer? {
        preprocessor.render(image, frame: self.frame(frame))
    }

    /// One prediction on a grey input, so the first pass is not the one that
    /// waits for Core ML to prepare the model.
    func warmUp() throws {
        var buffer: CVPixelBuffer?
        CVPixelBufferCreate(nil, model.inputWidth, model.inputHeight, kCVPixelFormatType_32BGRA,
                            [kCVPixelBufferIOSurfacePropertiesKey as String: [:] as [String: Any]] as CFDictionary,
                            &buffer)
        guard let buffer else { return }
        CVPixelBufferLockBaseAddress(buffer, [])
        if let base = CVPixelBufferGetBaseAddress(buffer) {
            memset(base, 114, CVPixelBufferGetBytesPerRow(buffer) * model.inputHeight)
        }
        CVPixelBufferUnlockBaseAddress(buffer, [])
        _ = try model.predict(buffer)
    }
}

nonisolated enum DepthSource: Sendable {
    case lidar
    case model(DepthModelRunner)

    static let lidarName = "LiDAR"
    /// A model's depth grid where no LiDAR grid gives the size: `sceneDepth`'s.
    static let gridWidth = 256
    static let gridHeight = 192

    var name: String {
        switch self {
        case .lidar: return Self.lidarName
        case .model(let runner): return runner.model.info.name
        }
    }

    /// Whether a pass needs the frame's LiDAR depth to run at all.
    var needsLidar: Bool {
        if case .lidar = self { return true }
        return false
    }

    var liftParameters: DepthLiftParameters {
        var p = DepthLiftParameters()
        guard case .model = self else { return p }
        // A fitted map's floor, table tops and walls are off by centimetres
        // where LiDAR's are off by millimetres.
        p.supportBand = 0.05
        p.supportSheet = 0.08
        p.contactMargin = 0.05
        p.wallBand = 0.06
        p.wallSheet = 0.10
        return p
    }

    var fusionParameters: FusionParameters {
        var p = FusionParameters()
        guard case .model = self else { return p }
        // Two frames' fits disagree by a few percent of the range: at 3 m that
        // is more than LiDAR's whole tolerance.
        p.visibilityTolerance = 0.12
        p.freeSpaceMargin = 0.25
        p.contactReach = 0.11
        return p
    }

    /// The model's input, rendered from the camera buffer; nil for LiDAR.
    func render(_ image: CVPixelBuffer, frame: SensorFrame) -> CVPixelBuffer? {
        guard case .model(let runner) = self else { return nil }
        return runner.render(image, frame: frame)
    }

    /// This pass's depth. LiDAR's is the frame's own. A model's comes from
    /// `input`, fitted to the frame's anchors, and is scored against LiDAR's
    /// when the frame carried it. `frame` is the pass's.
    func depth(for snapshot: FrameSnapshot, input: CVPixelBuffer?, frame: SensorFrame) -> DepthStage {
        guard case .model(let runner) = self else {
            return DepthStage(grid: snapshot.depth, log: DepthPassLog(source: name))
        }
        var stage = DepthStage(grid: nil, log: DepthPassLog(source: name))
        guard let input else {
            stage.log.failure = "the frame could not be rendered as its input"
            return stage
        }
        let clock = ContinuousClock()
        var mark = clock.now
        func milliseconds() -> Double {
            let now = clock.now
            let d = now - mark
            mark = now
            return Double(d.components.seconds) * 1000 + Double(d.components.attoseconds) / 1e15
        }
        let prediction: DepthPrediction
        do {
            prediction = try runner.model.predict(input)
        } catch {
            stage.log.failure = "prediction failed: \(error.localizedDescription)"
            return stage
        }
        stage.predict = milliseconds()
        let kind = runner.model.info.kind
        let modelFrame = runner.frame(frame)
        let values = DepthAlignment.resample(prediction.map, frame: modelFrame)
        let fit = DepthAlignment.fit(kind: kind, grid: values, frame: frame, anchors: snapshot.anchors)
        stage.log.fit = fit
        if let failure = fit.failure {
            stage.log.failure = "no fit: \(failure.rawValue)"
        } else {
            let own = prediction.confidence.map { DepthAlignment.resample($0, frame: modelFrame) }
            let grid = DepthAlignment.grid(values, width: frame.depthWidth, height: frame.depthHeight, kind: kind,
                                           fit: fit, own: own)
            stage.grid = grid
            if let lidar = snapshot.depth {
                stage.log.againstLidar = DepthAlignment.score(grid, against: lidar, values: values, kind: kind)
            }
        }
        stage.align = milliseconds()
        return stage
    }
}

/// A pass's depth as the screen reads it: the metric grid and the frame it was
/// taken in, whichever source made it. What stands between the camera and an
/// object is read from this, not from LiDAR alone, so a phone without LiDAR
/// hides what is behind a wall too.
nonisolated struct DepthSight: Sendable {
    let grid: DepthGrid
    let frame: SensorFrame
    let time: Double
    /// ARKit's vertical planes as of the pass, for what a wall hides.
    var walls: [VerticalSurface] = []
    /// ARKit's table-top planes (a surface things stand on, with its measured extent) as of the pass.
    var tops: [HorizontalSurface] = []
}

/// One pass's depth: the grid, or none, and what the log says of it.
nonisolated struct DepthStage: Sendable {
    var grid: DepthGrid?
    var log: DepthPassLog
    /// The model's prediction, and fitting and scoring its map, milliseconds.
    var predict: Double = 0
    var align: Double = 0
}

/// One pass's depth as the log records it.
nonisolated struct DepthPassLog: Sendable, Equatable, Codable {
    /// `LiDAR`, or the model's name.
    var source: String
    var fit: DepthFit?
    var againstLidar: DepthScore?
    /// Why a model gave this pass no depth.
    var failure: String?
}

/// Which bundled depth model a phone without LiDAR runs.
///
/// Depth Anything v2 Small is the model: on the operator's phone it measured
/// better than v3 under the same fitting (`DepthAlignment`). The v3 code stays
/// — its metric-depth kind and its own per-pixel confidence are read and
/// fitted — but nothing selects it while `allowsDepthAnything3` is false.
/// Flipping that one constant is all a v3 trial needs.
nonisolated enum DepthPolicy {
    static let depthAnything2Stem = "depth_da2_small"
    static let depthAnything3Stem = "depth_da3_small"
    static let allowsDepthAnything3 = false

    /// The model to run among the bundled `stems`, or nil when none is allowed.
    static func modelStem(among stems: [String]) -> String? {
        if stems.contains(depthAnything2Stem) { return depthAnything2Stem }
        if allowsDepthAnything3, stems.contains(depthAnything3Stem) { return depthAnything3Stem }
        return nil
    }
}

#endif
