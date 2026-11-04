/// A depth model's relative map laid onto the depth grid the lifter reads, put
/// into metres from what ARKit tracks without LiDAR, and scored against LiDAR
/// where a phone has it — DEBUG-only (decision 0295).
///
/// ONTO THE GRID. The centre of every depth-grid pixel is a point of the camera
/// image; the upright turn and the letterbox (`SensorFrame`, built at the
/// model's input size) take it into the model's input, the map's own
/// resolution scales that to a map point, and the map is read there
/// bilinearly — never from what the model made of the letterbox's padding.
/// The same map renders the model's input (`FramePreprocessor`), so the input
/// and the reading of its output cannot disagree.
///
/// THE ANCHORS are what ARKit measures on any phone. A feature point it tracked
/// in this frame is a surface in view at a known depth. A plane it found — the
/// floor above all, then walls and table tops — is a surface at a known depth
/// wherever its measured outline is in view, unless something stands in front
/// of it; the fit's robustness is for that.
///
/// ONE GLOBAL FIT PER FRAME, never a per-pixel correction: a scale for `depth`,
/// a scale and a shift in inverse depth for `disparity`, nothing for `metric`.
/// The map's shape stays the model's; only its units come from ARKit. RANSAC
/// over minimal sets of anchors finds the fit most anchors agree with to 8 %,
/// and least squares over those anchors refines it. Every error is relative.
///
/// THE FIT IS THE CONFIDENCE. Every pixel carries its frame's: high when the
/// median anchor is within 5 % of the fit, medium within 10 %. Past that, or
/// with too few anchors, the frame has no depth at all — as a LiDAR frame
/// without `sceneDepth` has none. A model that returns its own confidence
/// (DA3's: at least 1, larger surer, on no fixed scale) marks the pixels it
/// is least sure of low, which the lifter skips: those under its frame's
/// 10th percentile, the threshold DA3's own code takes by default.
///
/// Read by: DepthSource, LiveBoxesDepthTests.

#if DEBUG

import simd

/// A plane ARKit measured, as far as it measured it.
nonisolated struct AnchorPlane: Sendable, Equatable {
    /// `ARPlaneAnchor.transform`: the plane is its local y = 0.
    let worldFromPlane: simd_float4x4
    /// Its measured outline in its own (x, z), in order around it.
    let outline: [SIMD2<Float>]
}

/// What ARKit tracked in one frame, for fitting a depth model's map.
nonisolated struct DepthAnchors: Sendable, Equatable {
    /// `ARFrame.rawFeaturePoints`, in world coordinates.
    var featurePoints: [SIMD3<Float>] = []
    var planes: [AnchorPlane] = []
}

/// One anchor on the depth grid: where it is, and its z-depth by ARKit.
nonisolated struct DepthTarget: Sendable, Equatable {
    /// Continuous depth-grid coordinates.
    let point: SIMD2<Float>
    let depth: Float
    let onPlane: Bool
}

/// One frame's fit of a map to its anchors, as the log records it.
nonisolated struct DepthFit: Sendable, Equatable, Codable {
    enum Failure: String, Sendable, Codable {
        case tooFewAnchors = "too few anchors"
        case anchorsDisagree = "anchors disagree"
    }

    var scale: Float = 1
    var shift: Float = 0
    /// Anchors in view; of them, on a plane; within `inlierError` of the fit.
    var anchors = 0
    var planeAnchors = 0
    var inliers = 0
    /// The median relative depth error over every anchor, after the fit.
    var residual: Float?
    /// Why the frame has no depth; nil when it has.
    var failure: Failure?
}

/// A model's depth against LiDAR's of the same frame, over the pixels LiDAR
/// measured with high confidence between 0.2 and 5 m.
nonisolated struct DepthScore: Sendable, Equatable, Codable {
    struct Band: Sendable, Equatable, Codable {
        /// LiDAR depths from the previous band's `upTo` (or 0.2 m) to this, metres.
        var upTo: Float
        var pixels: Int
        var medianError: Float?
    }

    var pixels: Int
    /// The median of |model − LiDAR| / LiDAR.
    var medianError: Float?
    var bands: [Band]
    /// The same median had the frame's fit been the best one against LiDAR
    /// itself: the part of the error that is the model's shape, not the anchors'.
    var bestFitMedianError: Float?
    /// Of `pixels`, those the model's own confidence marked unsure, and their
    /// median error: whether its confidence finds its worst pixels.
    var unsurePixels = 0
    var unsureMedianError: Float?
}

nonisolated enum DepthAlignment {
    /// An anchor within this relative error of a fit agrees with it.
    static let inlierError: Float = 0.08
    static let minimumAnchors = 20
    /// At least this many anchors, and this share of them, must agree.
    static let minimumInliers = 12
    static let minimumInlierShare: Float = 0.3
    /// Median anchor errors up to which a frame's depth has high confidence,
    /// then medium; past the second it has none.
    static let highResidual: Float = 0.05
    static let usableResidual: Float = 0.10
    /// Anchors nearer or farther than this, metres, are not used.
    static let anchorRange: ClosedRange<Float> = 0.2...10
    /// Planes are sampled at every this-many depth pixels in each direction.
    static let planeStep = 8
    /// A pixel whose own confidence is under this percentile of its frame's is unsure.
    static let unsurePercentile: Float = 0.10
    /// LiDAR's depths the score bands end at, metres.
    static let bandEdges: [Float] = [1, 2, 3, 5]

    // MARK: Onto the grid

    /// The map's value at the centre of every depth pixel, row-major. `frame`
    /// is the pass's frame built at the model's input size. Reading holds at
    /// the last map pixels on the camera image, so what the model made of
    /// the letterbox's padding never mixes into the image's edge.
    static func resample(_ map: DepthModelMap, frame: SensorFrame) -> [Float] {
        let box = frame.letterbox
        let scale = SIMD2(Float(map.width) / box.targetWidth, Float(map.height) / box.targetHeight)
        let lo = SIMD2(box.padX, box.padY) * scale
        let hi = (SIMD2(box.targetWidth, box.targetHeight) - SIMD2(box.padX, box.padY)) * scale
        let first = (lo - 0.5).rounded(.up) + 0.5
        let last = simd_max((hi - 0.5).rounded(.down) + 0.5, first)
        var out = [Float](repeating: 0, count: frame.depthWidth * frame.depthHeight)
        for y in 0..<frame.depthHeight {
            for x in 0..<frame.depthWidth {
                let p = simd_clamp(frame.modelPoint(depthX: x, depthY: y) * scale, first, last)
                out[y * frame.depthWidth + x] = sample(map.values, width: map.width, height: map.height, at: p)
            }
        }
        return out
    }

    /// A row-major raster read bilinearly at a continuous point — pixel
    /// centres at i + ½ — and held at its edges.
    static func sample(_ values: [Float], width: Int, height: Int, at p: SIMD2<Float>) -> Float {
        let fx = min(max(p.x - 0.5, 0), Float(width - 1))
        let fy = min(max(p.y - 0.5, 0), Float(height - 1))
        let x0 = Int(fx), y0 = Int(fy)
        let x1 = min(x0 + 1, width - 1), y1 = min(y0 + 1, height - 1)
        let ax = fx - Float(x0), ay = fy - Float(y0)
        let top = values[y0 * width + x0] * (1 - ax) + values[y0 * width + x1] * ax
        let bottom = values[y1 * width + x0] * (1 - ax) + values[y1 * width + x1] * ax
        return top * (1 - ay) + bottom * ay
    }

    // MARK: Anchors

    /// Every anchor in view, on the depth grid: each feature point that lands
    /// on it, and, at every `planeStep`-th pixel, the nearest plane whose
    /// measured outline the pixel's ray meets.
    static func targets(_ anchors: DepthAnchors, frame: SensorFrame) -> [DepthTarget] {
        var targets: [DepthTarget] = []
        let w = Float(frame.depthWidth), h = Float(frame.depthHeight)
        for p in anchors.featurePoints {
            guard let projection = frame.depthProjection(world: p), anchorRange.contains(projection.depth),
                  projection.point.x >= 0, projection.point.y >= 0, projection.point.x < w, projection.point.y < h
            else { continue }
            targets.append(DepthTarget(point: projection.point, depth: projection.depth, onPlane: false))
        }
        guard !anchors.planes.isEmpty else { return targets }
        let planes = anchors.planes.map { plane in
            (outline: plane.outline, planeFromWorld: plane.worldFromPlane.inverse,
             normal: SIMD3(plane.worldFromPlane.columns.1.x, plane.worldFromPlane.columns.1.y,
                           plane.worldFromPlane.columns.1.z),
             origin: SIMD3(plane.worldFromPlane.columns.3.x, plane.worldFromPlane.columns.3.y,
                           plane.worldFromPlane.columns.3.z))
        }
        let eye = frame.cameraPosition
        let k = frame.intrinsics
        for y in stride(from: planeStep / 2, to: frame.depthHeight, by: planeStep) {
            for x in stride(from: planeStep / 2, to: frame.depthWidth, by: planeStep) {
                // The ray through the pixel's centre, scaled so its parameter is z-depth.
                let u = frame.imagePoint(depthX: x, depthY: y)
                let ray = frame.worldFromCamera * SIMD4((u.x - k.cx) / k.fx, -(u.y - k.cy) / k.fy, -1, 0)
                let direction = SIMD3(ray.x, ray.y, ray.z)
                var nearest: Float?
                for plane in planes {
                    let facing = simd_dot(plane.normal, direction)
                    guard abs(facing) > 1e-6 else { continue }
                    let t = simd_dot(plane.normal, plane.origin - eye) / facing
                    guard anchorRange.contains(t), t < (nearest ?? .infinity) else { continue }
                    let local = plane.planeFromWorld * SIMD4(eye + direction * t, 1)
                    if contains(plane.outline, SIMD2(local.x, local.z)) { nearest = t }
                }
                if let t = nearest {
                    targets.append(DepthTarget(point: SIMD2(Float(x) + 0.5, Float(y) + 0.5), depth: t, onPlane: true))
                }
            }
        }
        return targets
    }

    /// Whether `p` lies inside the polygon `outline` (even–odd crossings).
    static func contains(_ outline: [SIMD2<Float>], _ p: SIMD2<Float>) -> Bool {
        guard outline.count >= 3 else { return false }
        var inside = false
        var j = outline.count - 1
        for i in outline.indices {
            let a = outline[i], b = outline[j]
            if (a.y > p.y) != (b.y > p.y), p.x < (b.x - a.x) * (p.y - a.y) / (b.y - a.y) + a.x { inside.toggle() }
            j = i
        }
        return inside
    }

    // MARK: The fit

    /// The frame's fit: every anchor in view, the resampled map read at each.
    static func fit(kind: DepthKind, grid values: [Float], frame: SensorFrame, anchors: DepthAnchors) -> DepthFit {
        let targets = targets(anchors, frame: frame)
        return fit(kind: kind,
                   values: targets.map { sample(values, width: frame.depthWidth, height: frame.depthHeight, at: $0.point) },
                   depths: targets.map(\.depth), planeAnchors: targets.filter(\.onPlane).count)
    }

    /// The fit of map `values` to ARKit's `depths` at the same anchors.
    static func fit(kind: DepthKind, values: [Float], depths: [Float], planeAnchors: Int = 0) -> DepthFit {
        var fit = DepthFit(anchors: values.count, planeAnchors: planeAnchors)
        guard values.count >= minimumAnchors else {
            fit.failure = .tooFewAnchors
            return fit
        }
        guard let model = robust(kind: kind, values: values, depths: depths) else {
            fit.failure = .anchorsDisagree
            return fit
        }
        fit.scale = model.scale
        fit.shift = model.shift
        let errors = zip(values, depths).map { error(kind, $0, $1, model) }
        let residual = median(errors) ?? .infinity
        fit.inliers = errors.filter { $0 <= inlierError }.count
        fit.residual = residual.isFinite ? residual : nil
        let needed = max(minimumInliers, Int((minimumInlierShare * Float(values.count)).rounded(.up)))
        if fit.inliers < needed || !(residual <= usableResidual) { fit.failure = .anchorsDisagree }
        return fit
    }

    /// RANSAC over minimal sets — one anchor fixes a scale, two a scale and a
    /// shift — scored by truncated squared error, then least squares over the
    /// anchors within `inlierError`, three times. Seeded: the same anchors
    /// always give the same fit. Nil when no minimal set gives a fit.
    static func robust(kind: DepthKind, values: [Float], depths: [Float],
                       iterations: Int = 128) -> (scale: Float, shift: Float)? {
        if kind == .metric { return (1, 0) }
        let n = values.count
        guard n > 0 else { return nil }
        var random = SplitMix(seed: 0x6A09_E667_F3BC_C909)
        let cap = inlierError * inlierError
        var best: (model: (scale: Float, shift: Float), cost: Float)?
        for _ in 0..<iterations {
            let i = Int(random.next() % UInt64(n)), j = Int(random.next() % UInt64(n))
            guard let model = minimal(kind, values, depths, i, j) else { continue }
            var cost: Float = 0
            for k in 0..<n {
                let e = error(kind, values[k], depths[k], model)
                cost += min(e * e, cap)
            }
            if best.map({ cost < $0.cost }) ?? true { best = (model, cost) }
        }
        guard var model = best?.model else { return nil }
        for _ in 0..<3 {
            let agreeing = (0..<n).filter { error(kind, values[$0], depths[$0], model) <= inlierError }
            guard let refined = leastSquares(kind: kind, values: agreeing.map { values[$0] },
                                             depths: agreeing.map { depths[$0] }) else { break }
            model = refined
        }
        return model
    }

    /// Least squares in relative error: Σ((s·m − z)/z)² for `depth`, and
    /// Σ((s·m + t − 1/z)·z)² for `disparity`. Nil when degenerate or the fit
    /// would make nearer farther.
    static func leastSquares(kind: DepthKind, values: [Float], depths: [Float]) -> (scale: Float, shift: Float)? {
        switch kind {
        case .metric:
            return (1, 0)
        case .depth:
            var sum = 0.0, squares = 0.0
            for (m, z) in zip(values, depths) {
                let r = Double(m) / Double(z)
                sum += r
                squares += r * r
            }
            guard squares > 0, sum > 0 else { return nil }
            return (Float(sum / squares), 0)
        case .disparity:
            // Rows (a, b) = (m·z, z), each wanting s·a + t·b = 1.
            var aa = 0.0, ab = 0.0, bb = 0.0, a1 = 0.0, b1 = 0.0
            for (m, z) in zip(values, depths) {
                let a = Double(m) * Double(z), b = Double(z)
                aa += a * a
                ab += a * b
                bb += b * b
                a1 += a
                b1 += b
            }
            let det = aa * bb - ab * ab
            guard det > 1e-9 * aa * bb else { return nil }
            let s = (a1 * bb - b1 * ab) / det
            let t = (aa * b1 - ab * a1) / det
            guard s > 0 else { return nil }
            return (Float(s), Float(t))
        }
    }

    /// The fit through anchors i and j (i alone for a scale).
    private static func minimal(_ kind: DepthKind, _ values: [Float], _ depths: [Float],
                                _ i: Int, _ j: Int) -> (scale: Float, shift: Float)? {
        switch kind {
        case .metric:
            return (1, 0)
        case .depth:
            guard values[i] > 0 else { return nil }
            return (depths[i] / values[i], 0)
        case .disparity:
            let dm = values[i] - values[j]
            guard abs(dm) > 1e-6 else { return nil }
            let s = (1 / depths[i] - 1 / depths[j]) / dm
            guard s > 0, s.isFinite else { return nil }
            return (s, 1 / depths[i] - s * values[i])
        }
    }

    /// The relative depth error of one anchor under a fit; infinite where the
    /// fit puts it behind the camera.
    private static func error(_ kind: DepthKind, _ value: Float, _ depth: Float,
                              _ model: (scale: Float, shift: Float)) -> Float {
        let z = metres(value, kind: kind, scale: model.scale, shift: model.shift)
        return z > 0 ? abs(z - depth) / depth : .infinity
    }

    /// A map value in metres under a fit; 0 where it names no depth in front
    /// of the camera.
    static func metres(_ value: Float, kind: DepthKind, scale: Float, shift: Float) -> Float {
        let z: Float
        switch kind {
        case .disparity:
            let inverse = scale * value + shift
            z = inverse > 0 ? 1 / inverse : 0
        case .depth:
            z = scale * value
        case .metric:
            z = value
        }
        return z.isFinite && z > 0 ? z : 0
    }

    /// The frame's depth grid: the resampled map in metres, every pixel at its
    /// frame's confidence, but low where `own` — the model's own confidence,
    /// resampled the same way — is under its frame's `unsurePercentile`.
    static func grid(_ values: [Float], width: Int, height: Int, kind: DepthKind, fit: DepthFit,
                     own: [Float]? = nil) -> DepthGrid {
        let level: UInt8 = (fit.residual ?? .infinity) <= highResidual ? 2 : 1
        var confidence = [UInt8](repeating: level, count: width * height)
        if let own, own.count == confidence.count {
            let sorted = own.sorted()
            let floor = sorted[Int(Float(sorted.count - 1) * unsurePercentile)]
            for k in confidence.indices where own[k] < floor { confidence[k] = 0 }
        }
        return DepthGrid(width: width, height: height,
                         depth: values.map { metres($0, kind: kind, scale: fit.scale, shift: fit.shift) },
                         confidence: confidence)
    }

    // MARK: LiDAR referees

    /// `model` against `lidar` on the same grid. `values` is the model's
    /// relative map on the grid, for the best fit against LiDAR itself.
    static func score(_ model: DepthGrid, against lidar: DepthGrid, values: [Float], kind: DepthKind) -> DepthScore? {
        guard model.width == lidar.width, model.height == lidar.height, values.count == lidar.depth.count
        else { return nil }
        var reference: [(k: Int, z: Float)] = []
        var errors: [Float] = []
        var unsure: [Float] = []
        var banded = [[Float]](repeating: [], count: bandEdges.count)
        for k in lidar.depth.indices {
            let z = lidar.depth[k]
            guard DepthGrid.isMeasured(z), z >= 0.2, z < bandEdges[bandEdges.count - 1],
                  (lidar.confidence?[k] ?? 2) >= 2,
                  let band = bandEdges.firstIndex(where: { z < $0 }) else { continue }
            reference.append((k, z))
            let m = model.depth[k]
            guard DepthGrid.isMeasured(m) else { continue }
            let e = abs(m - z) / z
            errors.append(e)
            banded[band].append(e)
            if model.confidence(x: k % model.width, y: k / model.width) == 0 { unsure.append(e) }
        }
        guard !reference.isEmpty else { return nil }
        // The best fit, from at most 2000 of the reference pixels.
        let step = max(reference.count / 2000, 1)
        let sampled = stride(from: 0, to: reference.count, by: step).map { reference[$0] }
        var best: Float?
        if let fit = robust(kind: kind, values: sampled.map { values[$0.k] }, depths: sampled.map(\.z)) {
            best = median(reference.compactMap { r -> Float? in
                let m = metres(values[r.k], kind: kind, scale: fit.scale, shift: fit.shift)
                return m > 0 ? abs(m - r.z) / r.z : nil
            })
        }
        return DepthScore(pixels: errors.count, medianError: median(errors),
                          bands: zip(bandEdges, banded).map { .init(upTo: $0, pixels: $1.count, medianError: median($1)) },
                          bestFitMedianError: best, unsurePixels: unsure.count, unsureMedianError: median(unsure))
    }

    static func median(_ values: [Float]) -> Float? {
        guard !values.isEmpty else { return nil }
        let sorted = values.sorted()
        return sorted[sorted.count / 2]
    }

    /// SplitMix64: a tiny seeded generator, so a fit never depends on the run.
    private struct SplitMix {
        private var state: UInt64
        init(seed: UInt64) { state = seed }
        mutating func next() -> UInt64 {
            state &+= 0x9E37_79B9_7F4A_7C15
            var z = state
            z = (z ^ (z >> 30)) &* 0xBF58_476D_1CE4_E5B9
            z = (z ^ (z >> 27)) &* 0x94D0_49BB_1331_11EB
            return z ^ (z >> 31)
        }
    }
}

#endif
