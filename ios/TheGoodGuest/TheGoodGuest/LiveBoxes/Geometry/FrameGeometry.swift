/// The coordinate frames one ARFrame passes through on its way to a detector
/// and back to the world, as pure value maps — DEBUG-only (decision 0295).
///
/// FOUR RASTERS, ONE CONVENTION. Every raster is addressed in CONTINUOUS
/// coordinates with the origin at the top-left CORNER of the top-left pixel,
/// u right, v down: pixel (i, j) covers [i, i+1) × [j, j+1) and its centre is
/// (i + 0.5, j + 0.5). The rasters are:
///
///   • the camera image (`ARFrame.capturedImage`, 1920×1440), in the sensor's
///     fixed landscape orientation — ARKit's intrinsics refer to it;
///   • the depth map (`sceneDepth`, 256×192), registered to the same sensor
///     and sharing its aspect ratio, so depth → image is a pure scale;
///   • the UPRIGHT image — the camera image turned by a quarter-turn chosen
///     from gravity, so the detector sees the room the right way up (0283 and
///     0291 measured what a sideways frame costs a vision model);
///   • the model input — the upright image letterboxed into the network's
///     square (scaled uniformly, centred, padded).
///
/// Depth pixel centres map to image coordinates as (i + 0.5) · W_img / W_depth.
/// That is the registration Metal's normalized texture sampling implies, and it
/// is the ONLY place a half-pixel is added: every other map here is an exact
/// affine map between continuous coordinates, so a round trip is identity.
///
/// Camera-local points follow ARKit: +X right in the sensor image, +Y up, the
/// camera looks down −Z, and depth is z-depth along the viewing axis. So a
/// continuous image coordinate (u, v) at depth d is
/// ((u − cx)·d/fx, −(v − cy)·d/fy, −d). UI orientation never enters the maths;
/// the quarter-turn is physical (gravity), and it is undone before any point is
/// lifted.
///
/// Read by: DetectorPipeline, FramePreprocessor (the render transform),
/// DepthLifter, DetectionDecoder (masks), BoxFusion (votes),
/// LiveBoxesGeometryTests, LiveBoxesLiftingTests and LiveBoxesPreprocessorTests.

#if DEBUG

import simd

// MARK: - Intrinsics

/// Pinhole intrinsics at the camera image's own resolution.
nonisolated struct CameraIntrinsics: Equatable, Sendable {
    var fx: Float
    var fy: Float
    var cx: Float
    var cy: Float
    /// The camera image size the intrinsics refer to.
    var width: Int
    var height: Int

    /// ARKit's column-major intrinsics matrix: col 0 = (fx, 0, 0),
    /// col 1 = (0, fy, 0), col 2 = (cx, cy, 1).
    init(matrix m: simd_float3x3, width: Int, height: Int) {
        self.init(fx: m.columns.0.x, fy: m.columns.1.y,
                  cx: m.columns.2.x, cy: m.columns.2.y,
                  width: width, height: height)
    }

    init(fx: Float, fy: Float, cx: Float, cy: Float, width: Int, height: Int) {
        self.fx = fx; self.fy = fy; self.cx = cx; self.cy = cy
        self.width = width; self.height = height
    }

    /// The camera-local point seen at image coordinate `p` with z-depth `depth`.
    func unproject(_ p: SIMD2<Float>, depth: Float) -> SIMD3<Float> {
        SIMD3((p.x - cx) * depth / fx, -(p.y - cy) * depth / fy, -depth)
    }

    /// Where a camera-local point lands in the image, or nil behind the camera.
    func project(_ point: SIMD3<Float>) -> SIMD2<Float>? {
        guard point.z < -1e-4 else { return nil }
        let d = -point.z
        return SIMD2(cx + point.x * fx / d, cy - point.y * fy / d)
    }
}

// MARK: - Quarter-turn

/// A rotation of an image by a multiple of 90°, named by how many CLOCKWISE
/// quarter-turns it applies. Turning by one quarter maps the image's top edge
/// onto its right edge.
nonisolated enum QuarterTurn: Int, CaseIterable, Sendable, Codable {
    case none = 0
    case clockwise = 1
    case half = 2
    case counterClockwise = 3

    /// The size of a `width`×`height` image after the turn.
    func turnedSize(width: Int, height: Int) -> (width: Int, height: Int) {
        switch self {
        case .none, .half:                    return (width, height)
        case .clockwise, .counterClockwise:   return (height, width)
        }
    }

    /// A point in the unturned `width`×`height` image, in the turned image.
    func apply(_ p: SIMD2<Float>, width w: Float, height h: Float) -> SIMD2<Float> {
        switch self {
        case .none:             return p
        case .clockwise:        return SIMD2(h - p.y, p.x)
        case .half:             return SIMD2(w - p.x, h - p.y)
        case .counterClockwise: return SIMD2(p.y, w - p.x)
        }
    }

    /// The inverse of `apply`, with the UNTURNED image's dimensions.
    func invert(_ q: SIMD2<Float>, width w: Float, height h: Float) -> SIMD2<Float> {
        switch self {
        case .none:             return q
        case .clockwise:        return SIMD2(q.y, h - q.x)
        case .half:             return SIMD2(w - q.x, h - q.y)
        case .counterClockwise: return SIMD2(w - q.y, q.x)
        }
    }

    /// The turn that brings world-down to the bottom of the image.
    ///
    /// `gravity` is world-down in the camera's local frame
    /// (`PoseExtractor.gravityInCameraFrame`). Its image-plane direction is
    /// (gx, −gy) because image v grows down while camera Y grows up; a turn of
    /// k quarters adds k·90° to that direction's angle, and upright is +90°.
    ///
    /// Two stabilisers, both physical rather than cosmetic: when the camera
    /// looks nearly straight up or down, gravity has no usable image-plane
    /// direction and the previous turn is kept; and the previous turn is also
    /// kept until the new one wins by `hysteresisDegrees`, so holding the phone
    /// near a diagonal does not alternate the detector's input every frame.
    static func upright(gravity g: SIMD3<Float>, previous: QuarterTurn?,
                        hysteresisDegrees: Float = 10) -> QuarterTurn {
        let down = SIMD2<Float>(g.x, -g.y)
        guard simd_length(down) > 0.3 else { return previous ?? .none }
        let angle = atan2(down.y, down.x)
        func miss(_ turn: QuarterTurn) -> Float {
            let a = angle + Float(turn.rawValue) * .pi / 2 - .pi / 2
            return abs(atan2(sin(a), cos(a)))
        }
        let best = QuarterTurn.allCases.min { miss($0) < miss($1) } ?? .none
        if let previous, previous != best,
           miss(previous) <= .pi / 4 + hysteresisDegrees * .pi / 180 {
            return previous
        }
        return best
    }
}

// MARK: - Letterbox

/// Uniform scale into a model input, centred, with the remainder padded —
/// the same placement the detector was trained with.
nonisolated struct Letterbox: Equatable, Sendable {
    let sourceWidth: Float
    let sourceHeight: Float
    let targetWidth: Float
    let targetHeight: Float
    let scale: Float
    let padX: Float
    let padY: Float

    init(sourceWidth: Float, sourceHeight: Float, targetWidth: Float, targetHeight: Float) {
        self.sourceWidth = sourceWidth
        self.sourceHeight = sourceHeight
        self.targetWidth = targetWidth
        self.targetHeight = targetHeight
        let s = min(targetWidth / sourceWidth, targetHeight / sourceHeight)
        scale = s
        padX = (targetWidth - sourceWidth * s) / 2
        padY = (targetHeight - sourceHeight * s) / 2
    }

    func toTarget(_ p: SIMD2<Float>) -> SIMD2<Float> {
        p * scale + SIMD2(padX, padY)
    }

    func toSource(_ q: SIMD2<Float>) -> SIMD2<Float> {
        (q - SIMD2(padX, padY)) / scale
    }
}

// MARK: - One frame's maps

/// Every map one detection needs, frozen at the frame it was taken from.
nonisolated struct SensorFrame: Sendable {
    let intrinsics: CameraIntrinsics
    let depthWidth: Int
    let depthHeight: Int
    /// ARCamera.transform: world_from_camera.
    let worldFromCamera: simd_float4x4
    let cameraFromWorld: simd_float4x4
    let turn: QuarterTurn
    let letterbox: Letterbox

    init(intrinsics: CameraIntrinsics, depthWidth: Int, depthHeight: Int,
         worldFromCamera: simd_float4x4, turn: QuarterTurn,
         modelWidth: Int, modelHeight: Int) {
        self.intrinsics = intrinsics
        self.depthWidth = depthWidth
        self.depthHeight = depthHeight
        self.worldFromCamera = worldFromCamera
        cameraFromWorld = worldFromCamera.inverse
        self.turn = turn
        let upright = turn.turnedSize(width: intrinsics.width, height: intrinsics.height)
        letterbox = Letterbox(sourceWidth: Float(upright.width), sourceHeight: Float(upright.height),
                              targetWidth: Float(modelWidth), targetHeight: Float(modelHeight))
    }

    private var imageWidth: Float { Float(intrinsics.width) }
    private var imageHeight: Float { Float(intrinsics.height) }

    /// Camera image → model input.
    func modelPoint(image p: SIMD2<Float>) -> SIMD2<Float> {
        letterbox.toTarget(turn.apply(p, width: imageWidth, height: imageHeight))
    }

    /// Model input → camera image.
    func imagePoint(model q: SIMD2<Float>) -> SIMD2<Float> {
        turn.invert(letterbox.toSource(q), width: imageWidth, height: imageHeight)
    }

    /// The centre of depth pixel (x, y), in camera image coordinates.
    func imagePoint(depthX x: Int, depthY y: Int) -> SIMD2<Float> {
        SIMD2((Float(x) + 0.5) * imageWidth / Float(depthWidth),
              (Float(y) + 0.5) * imageHeight / Float(depthHeight))
    }

    /// Camera image → continuous depth-map coordinates.
    func depthPoint(image p: SIMD2<Float>) -> SIMD2<Float> {
        SIMD2(p.x * Float(depthWidth) / imageWidth, p.y * Float(depthHeight) / imageHeight)
    }

    /// The centre of depth pixel (x, y), in model input coordinates.
    func modelPoint(depthX x: Int, depthY y: Int) -> SIMD2<Float> {
        modelPoint(image: imagePoint(depthX: x, depthY: y))
    }

    /// The world point measured by depth pixel (x, y) at z-depth `depth`.
    func worldPoint(depthX x: Int, depthY y: Int, depth: Float) -> SIMD3<Float> {
        let local = intrinsics.unproject(imagePoint(depthX: x, depthY: y), depth: depth)
        let w = worldFromCamera * SIMD4(local, 1)
        return SIMD3(w.x, w.y, w.z)
    }

    /// A world point in camera-local coordinates.
    func cameraPoint(world p: SIMD3<Float>) -> SIMD3<Float> {
        let c = cameraFromWorld * SIMD4(p, 1)
        return SIMD3(c.x, c.y, c.z)
    }

    /// Where a world point lands in the depth map (continuous), with its
    /// z-depth; nil behind the camera.
    func depthProjection(world p: SIMD3<Float>) -> (point: SIMD2<Float>, depth: Float)? {
        let local = cameraPoint(world: p)
        guard let image = intrinsics.project(local) else { return nil }
        return (depthPoint(image: image), -local.z)
    }

    /// The camera's position in the world.
    var cameraPosition: SIMD3<Float> {
        SIMD3(worldFromCamera.columns.3.x, worldFromCamera.columns.3.y, worldFromCamera.columns.3.z)
    }

    /// The depth pixels whose centres can fall inside a model-space rectangle,
    /// clamped to the depth map. Quarter-turns keep rectangles axis-aligned, so
    /// mapping two opposite corners is exact. Nil when the rectangle misses the
    /// depth map entirely.
    func depthPixelRange(modelMin: SIMD2<Float>, modelMax: SIMD2<Float>)
        -> (x: ClosedRange<Int>, y: ClosedRange<Int>)?
    {
        let a = depthPoint(image: imagePoint(model: modelMin))
        let b = depthPoint(image: imagePoint(model: modelMax))
        let lo = simd_min(a, b), hi = simd_max(a, b)
        // A pixel centre c = i + 0.5 lies in [lo, hi] iff i ∈ [ceil(lo − 0.5), floor(hi − 0.5)].
        let x0 = max(Int((lo.x - 0.5).rounded(.up)), 0)
        let x1 = min(Int((hi.x - 0.5).rounded(.down)), depthWidth - 1)
        let y0 = max(Int((lo.y - 0.5).rounded(.up)), 0)
        let y1 = min(Int((hi.y - 0.5).rounded(.down)), depthHeight - 1)
        guard x0 <= x1, y0 <= y1 else { return nil }
        return (x0...x1, y0...y1)
    }

    /// The depth pixel under the middle of the camera image, whatever the
    /// turn: the middle of the screen, which shows the image centred — where
    /// the person is aiming.
    var centreDepthPixel: (x: Int, y: Int) {
        let p = depthPoint(image: SIMD2(imageWidth / 2, imageHeight / 2))
        return (min(Int(p.x), depthWidth - 1), min(Int(p.y), depthHeight - 1))
    }

    /// Whether a model-space rectangle reaches within `margin` (a fraction of
    /// each side) of the camera image's edge: an object the frame cuts off,
    /// whose detection is a part of it, often misnamed, with its poorest mask.
    func touchesImageEdge(modelMin: SIMD2<Float>, modelMax: SIMD2<Float>, margin: Float) -> Bool {
        let a = imagePoint(model: modelMin), b = imagePoint(model: modelMax)
        let lo = simd_min(a, b), hi = simd_max(a, b)
        let mx = margin * imageWidth, my = margin * imageHeight
        return lo.x <= mx || lo.y <= my || hi.x >= imageWidth - mx || hi.y >= imageHeight - my
    }

    /// The fraction of the depth map a model-space rectangle covers: how big
    /// a detection is in view, which is also how many LiDAR samples it can have.
    func viewFraction(modelMin: SIMD2<Float>, modelMax: SIMD2<Float>) -> Float {
        guard let range = depthPixelRange(modelMin: modelMin, modelMax: modelMax) else { return 0 }
        return Float(range.x.count * range.y.count) / Float(depthWidth * depthHeight)
    }
}

#endif
