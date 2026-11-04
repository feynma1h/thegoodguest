/// A synthetic room for the live-boxes geometry tests: gravity-aligned boxes
/// with known poses inside a walled room, ray-cast into a LiDAR-sized depth map
/// and a detector-sized instance mask, with the defects real frames carry.
///
/// DELIBERATELY INDEPENDENT OF THE CODE UNDER TEST. The renderer states the
/// conventions in its own words — depth pixel centres, the pinhole model, the
/// quarter-turn as a rotation matrix about the image centre, the letterbox —
/// rather than calling `SensorFrame`, so a convention error in production code
/// shows up as a box in the wrong place instead of being shared by both sides.
/// Only the ground-truth VALUE type (`GravityBox`) and the upright-turn choice
/// (pinned on its own in LiveBoxesGeometryTests) are borrowed.
///
/// The defects, all seeded so every run is the same run:
///   • depth noise growing with range;
///   • flying pixels: at a depth edge, half the pixels read a blend of the two
///     surfaces, at medium confidence;
///   • dropouts: a few percent of pixels at low confidence with a wrong depth;
///   • mask bleed: the instance mask spills one prototype cell past the
///     object's silhouette at random points along its edge;
///   • filled masks, on request: the mask covers the convex hull of the
///     object's silhouette, as a real detector's mask of a chair covers the
///     floor between its legs and the wall between its slats.
///
/// An object can be OPEN — legs, a seat, slats — built from solid parts whose
/// enclosing box is the ground truth, and the room's walls are reported as
/// ARKit's vertical planes would report them. Glass is a part the detector
/// outlines and LiDAR does not see: `maskParts` shape the object's own
/// silhouette, `parts` alone meet the depth rays.
///
/// For the depth models it also renders what a model would see — the true
/// depth, and a model's own map of the room in its own input's frame — and
/// what ARKit would track without LiDAR: the floor as a plane anchor, and
/// feature points with noise and outliers.
///
/// Read by: LiveBoxesLiftingTests, LiveBoxesDepthTests.

import simd
@testable import TheGoodGuest

/// SplitMix64 — tiny, seedable, and the same on every platform.
struct SeededGenerator {
    private var state: UInt64

    init(seed: UInt64) { state = seed }

    mutating func next() -> UInt64 {
        state &+= 0x9E37_79B9_7F4A_7C15
        var z = state
        z = (z ^ (z >> 30)) &* 0xBF58_476D_1CE4_E5B9
        z = (z ^ (z >> 27)) &* 0x94D0_49BB_1331_11EB
        return z ^ (z >> 31)
    }

    /// Uniform in [0, 1).
    mutating func unit() -> Float { Float(next() >> 40) / Float(1 << 24) }

    /// Standard normal (Box–Muller).
    mutating func gaussian() -> Float {
        let u1 = max(unit(), 1e-7), u2 = unit()
        return sqrt(-2 * log(u1)) * cos(2 * .pi * u2)
    }
}

struct SyntheticObject {
    let id: Int
    let name: String
    /// The ground truth: the box around every part.
    let box: GravityBox
    /// What rays hit: the box itself, or the solid parts of an open object.
    let parts: [GravityBox]
    /// What the detector outlines, when that is more than LiDAR sees — a
    /// glass top. Nil: the parts.
    private(set) var maskParts: [GravityBox]?

    init(id: Int, name: String, box: GravityBox, parts: [GravityBox]? = nil) {
        self.id = id
        self.name = name
        self.box = box
        self.parts = parts ?? [box]
    }

    /// An object made of parts given in its own frame — centred on its
    /// footprint, standing on y = 0 — then turned by `yaw` and set at
    /// `position` (its footprint's centre on the floor).
    init(id: Int, name: String, position: SIMD3<Float>, yaw: Float, parts local: [GravityBox],
         glass: [GravityBox] = []) {
        self.id = id
        self.name = name
        let c = cos(yaw), s = sin(yaw)
        // Local X → (c, 0, −s), local Z → (s, 0, c): the GravityBox convention.
        func place(_ p: SIMD3<Float>) -> SIMD3<Float> {
            position + SIMD3(p.x * c + p.z * s, p.y, -p.x * s + p.z * c)
        }
        func placed(_ b: GravityBox) -> GravityBox {
            GravityBox(center: place(b.center), size: b.size, yaw: b.yaw + yaw)
        }
        parts = local.map(placed)
        maskParts = glass.isEmpty ? nil : (local + glass).map(placed)
        var lo = SIMD3<Float>(repeating: .greatestFiniteMagnitude)
        var hi = SIMD3<Float>(repeating: -.greatestFiniteMagnitude)
        for part in local + glass {
            lo = simd_min(lo, part.center - part.size / 2)
            hi = simd_max(hi, part.center + part.size / 2)
        }
        box = GravityBox(center: place((lo + hi) / 2), size: hi - lo, yaw: yaw)
    }
}

struct SyntheticCamera {
    let worldFromCamera: simd_float4x4

    /// A camera at `eye` looking at `target`, rolled about its viewing axis.
    /// Roll 0 is the sensor's own landscape hold (camera +Y along world up);
    /// ±π/2 are the two portrait holds.
    init(eye: SIMD3<Float>, target: SIMD3<Float>, roll: Float) {
        let back = simd_normalize(eye - target)            // camera +Z
        let right0 = simd_normalize(simd_cross(SIMD3<Float>(0, 1, 0), back))
        let up0 = simd_cross(back, right0)
        let right = right0 * cos(roll) + up0 * sin(roll)
        let up = simd_cross(back, right)
        worldFromCamera = simd_float4x4(columns: (
            SIMD4(right, 0), SIMD4(up, 0), SIMD4(back, 0), SIMD4(eye, 1)))
    }

    var eye: SIMD3<Float> {
        SIMD3(worldFromCamera.columns.3.x, worldFromCamera.columns.3.y, worldFromCamera.columns.3.z)
    }
}

struct SyntheticRender {
    let depth: [Float]
    let confidence: [UInt8]
    /// The object hit at each depth pixel, -1 for the room itself.
    let objectAt: [Int]
}

struct SyntheticScene {
    static let imageWidth: Float = 1920
    static let imageHeight: Float = 1440
    static let depthWidth = 256
    static let depthHeight = 192
    static let modelSize = 640
    static let protoSize = 160

    /// Slightly off-centre on purpose: a swapped cx/cy or a W/2 shortcut moves boxes.
    static let intrinsics = CameraIntrinsics(fx: 1512.4, fy: 1512.4, cx: 958.3, cy: 723.6,
                                             width: 1920, height: 1440)

    let objects: [SyntheticObject]
    /// Horizontal planes ARKit would report besides the floor and the ceiling:
    /// table tops large enough to detect, where they are.
    var tops: [HorizontalSurface] = []
    let halfX: Float = 2.5
    let halfZ: Float = 2.0
    let ceilingY: Float = 2.6

    init(objects: [SyntheticObject], tops: [HorizontalSurface] = []) {
        self.objects = objects
        self.tops = tops
    }

    /// Every horizontal plane a frame of this room carries.
    var surfaces: [HorizontalSurface] {
        [HorizontalSurface(kind: .floor, height: 0, extent: nil),
         HorizontalSurface(kind: .ceiling, height: ceilingY, extent: nil)] + tops
    }

    /// The room's four walls as ARKit's vertical planes: each one's normal on
    /// the floor plane, where it stands, and how far along and up it runs.
    var walls: [VerticalSurface] {
        [VerticalSurface(normal: SIMD2(1, 0), offset: halfX, along: -halfZ...halfZ, heights: 0...ceilingY),
         VerticalSurface(normal: SIMD2(1, 0), offset: -halfX, along: -halfZ...halfZ, heights: 0...ceilingY),
         VerticalSurface(normal: SIMD2(0, 1), offset: halfZ, along: -halfX...halfX, heights: 0...ceilingY),
         VerticalSurface(normal: SIMD2(0, 1), offset: -halfZ, along: -halfX...halfX, heights: 0...ceilingY)]
    }

    /// The top of `box` as ARKit would measure it: a table plane over exactly
    /// its footprint.
    static func top(of box: GravityBox) -> HorizontalSurface {
        HorizontalSurface(kind: .support, height: box.maxY,
                          extent: PlanRectangle(center: SIMD2(box.center.x, box.center.z), axis: box.planXAxis,
                                                halfExtents: SIMD2(box.size.x, box.size.z) / 2))
    }

    // MARK: Ray casting

    /// Nearest hit along origin + t·direction, t > 0: the distance parameter
    /// and the object id (-1 for the room).
    func cast(origin o: SIMD3<Float>, direction d: SIMD3<Float>) -> (t: Float, id: Int) {
        var best = roomHit(o, d)
        var id = -1
        let dd = simd_dot(d, d)
        for object in objects {
            // Bounding sphere first: most rays miss most boxes.
            let rel = object.box.center - o
            let along = simd_dot(rel, d) / dd
            let radius = simd_length(object.box.size) / 2
            guard simd_length_squared(rel - d * along) <= radius * radius else { continue }
            for part in object.parts {
                if let t = boxHit(part, o, d), t < best {
                    best = t
                    id = object.id
                }
            }
        }
        return (best, id)
    }

    private func roomHit(_ o: SIMD3<Float>, _ d: SIMD3<Float>) -> Float {
        var t = Float.greatestFiniteMagnitude
        if d.x > 1e-6 { t = min(t, (halfX - o.x) / d.x) }
        if d.x < -1e-6 { t = min(t, (-halfX - o.x) / d.x) }
        if d.z > 1e-6 { t = min(t, (halfZ - o.z) / d.z) }
        if d.z < -1e-6 { t = min(t, (-halfZ - o.z) / d.z) }
        if d.y > 1e-6 { t = min(t, (ceilingY - o.y) / d.y) }
        if d.y < -1e-6 { t = min(t, (0 - o.y) / d.y) }
        return t
    }

    /// Slab test in the box's own frame. Its local X is (cos ψ, 0, −sin ψ) and
    /// local Z is (sin ψ, 0, cos ψ): a right-handed turn by ψ about +Y.
    private func boxHit(_ box: GravityBox, _ o: SIMD3<Float>, _ d: SIMD3<Float>) -> Float? {
        let ax = SIMD3<Float>(cos(box.yaw), 0, -sin(box.yaw))
        let az = SIMD3<Float>(sin(box.yaw), 0, cos(box.yaw))
        let rel = o - box.center
        let lo = SIMD3(simd_dot(rel, ax), rel.y, simd_dot(rel, az))
        let ld = SIMD3(simd_dot(d, ax), d.y, simd_dot(d, az))
        let half = box.size / 2
        var tNear = -Float.greatestFiniteMagnitude, tFar = Float.greatestFiniteMagnitude
        for axis in 0..<3 {
            if abs(ld[axis]) < 1e-7 {
                if abs(lo[axis]) > half[axis] { return nil }
            } else {
                var t1 = (-half[axis] - lo[axis]) / ld[axis]
                var t2 = (half[axis] - lo[axis]) / ld[axis]
                if t1 > t2 { swap(&t1, &t2) }
                tNear = max(tNear, t1)
                tFar = min(tFar, t2)
                if tNear > tFar { return nil }
            }
        }
        return tNear > 1e-4 ? tNear : nil
    }

    /// The ray through a continuous camera-image point, world direction scaled
    /// so the ray parameter IS z-depth (camera-space direction has z = −1).
    func ray(camera: SyntheticCamera, u: Float, v: Float) -> SIMD3<Float> {
        let k = Self.intrinsics
        let local = SIMD3((u - k.cx) / k.fx, -(v - k.cy) / k.fy, -1)
        let w = camera.worldFromCamera * SIMD4(local, 0)
        return SIMD3(w.x, w.y, w.z)
    }

    // MARK: Depth

    /// The depth map a LiDAR frame would deliver from `camera`. Depth pixel
    /// (i, j) samples the camera image at its own centre: ((i + ½)·7.5, (j + ½)·7.5).
    func renderDepth(camera: SyntheticCamera, rng: inout SeededGenerator) -> SyntheticRender {
        let w = Self.depthWidth, h = Self.depthHeight
        let sx = Self.imageWidth / Float(w), sy = Self.imageHeight / Float(h)
        var clean = [Float](repeating: 0, count: w * h)
        var ids = [Int](repeating: -1, count: w * h)
        for j in 0..<h {
            for i in 0..<w {
                let hit = cast(origin: camera.eye,
                               direction: ray(camera: camera, u: (Float(i) + 0.5) * sx, v: (Float(j) + 0.5) * sy))
                clean[j * w + i] = hit.t
                ids[j * w + i] = hit.id
            }
        }
        var depth = clean
        var confidence = [UInt8](repeating: 2, count: w * h)
        for j in 0..<h {
            for i in 0..<w {
                let k = j * w + i
                let d = clean[k]
                depth[k] = d + rng.gaussian() * (0.002 + 0.004 * d)
                var edgeNeighbour: Float?
                for (di, dj) in [(1, 0), (-1, 0), (0, 1), (0, -1)] {
                    let ni = i + di, nj = j + dj
                    guard ni >= 0, nj >= 0, ni < w, nj < h else { continue }
                    let n = clean[nj * w + ni]
                    if abs(n - d) > 0.05, n > (edgeNeighbour ?? 0) { edgeNeighbour = n }
                }
                if let far = edgeNeighbour {
                    confidence[k] = 1
                    if rng.unit() < 0.5 { depth[k] = (d + far) / 2 }
                }
                if rng.unit() < 0.05 {
                    confidence[k] = 0
                    depth[k] = d + (rng.unit() - 0.5)
                }
            }
        }
        return SyntheticRender(depth: depth, confidence: confidence, objectAt: ids)
    }

    // MARK: One frame

    /// Everything the production chain needs from one view: the frame maps,
    /// the depth, and the prototype cells' object ids.
    struct Frame {
        let sensor: SensorFrame
        let depth: DepthGrid
        let protoIDs: [Int]
    }

    func frame(camera: SyntheticCamera, rng: inout SeededGenerator) -> Frame {
        let render = renderDepth(camera: camera, rng: &rng)
        let gravity = PoseExtractor.gravityInCameraFrame(simd_quaternion(camera.worldFromCamera))
        let turn = QuarterTurn.upright(gravity: gravity, previous: nil)
        let sensor = SensorFrame(intrinsics: Self.intrinsics, depthWidth: Self.depthWidth,
                                 depthHeight: Self.depthHeight, worldFromCamera: camera.worldFromCamera,
                                 turn: turn, modelWidth: Self.modelSize, modelHeight: Self.modelSize)
        return Frame(sensor: sensor,
                     depth: DepthGrid(width: Self.depthWidth, height: Self.depthHeight,
                                      depth: render.depth, confidence: render.confidence),
                     protoIDs: renderProtoIDs(camera: camera, turn: turn))
    }

    /// One object's observation in a frame, through the production lifter,
    /// under a detector name of the caller's choosing.
    func observation(of id: Int, in frame: Frame, name: String, score: Float = 0.8,
                     bleed: Bool = false, rng: inout SeededGenerator) -> BoxObservation? {
        observation(of: [id], in: frame, name: name, score: score, bleed: bleed, rng: &rng)
    }

    /// One detection whose mask covers every object in `ids` — a sofa's mask
    /// taking in the cushions on it, as real instance masks do.
    func observation(of ids: Set<Int>, in frame: Frame, name: String, score: Float = 0.8,
                     bleed: Bool = false, ownTop: Bool = false, rng: inout SeededGenerator) -> BoxObservation? {
        guard let (det, bank) = Self.detection(of: ids, protoIDs: frame.protoIDs, bleed: bleed, rng: &rng),
              let mask = bank.mask(for: det).depthMask(frame: frame.sensor),
              let label = DetectorVocabulary.role(for: name).label,
              let lifted = DepthLifter.lift(mask: mask, excluding: nil, depth: frame.depth, frame: frame.sensor,
                                            surfaces: surfaces, walls: walls, flat: false, ownTop: ownTop)
        else { return nil }
        return BoxObservation(name: name, label: label, roomPlanCategory: nil, score: score,
                              points: lifted.points, mask: mask,
                              restsOn: lifted.restsOn, hangsFrom: lifted.hangsFrom, against: lifted.against)
    }

    // MARK: Detector output

    /// A camera-image point seen through the upright turn and the letterbox,
    /// written as a rotation about the image centre rather than as the case
    /// table production uses.
    static func imagePoint(model m: SIMD2<Float>, turn: QuarterTurn) -> SIMD2<Float>? {
        imagePoint(model: m, turn: turn, inputWidth: modelSize, inputHeight: modelSize)
    }

    /// The same, for a model input of any size — a depth model's is not square.
    static func imagePoint(model m: SIMD2<Float>, turn: QuarterTurn, inputWidth: Int, inputHeight: Int) -> SIMD2<Float>? {
        let turned = turn.rawValue % 2 == 0
            ? SIMD2(imageWidth, imageHeight) : SIMD2(imageHeight, imageWidth)
        let scale = min(Float(inputWidth) / turned.x, Float(inputHeight) / turned.y)
        let pad = (SIMD2<Float>(Float(inputWidth), Float(inputHeight)) - turned * scale) / 2
        let t = (m - pad) / scale
        guard t.x >= 0, t.y >= 0, t.x <= turned.x, t.y <= turned.y else { return nil }
        // Turned = R_k (p − c_src) + c_dst, R_k a clockwise turn by k quarters in
        // y-down image axes; so p = R_k⁻¹ (t − c_dst) + c_src.
        let angle = Float(turn.rawValue) * .pi / 2
        let c = cos(angle).rounded(), s = sin(angle).rounded()
        let rel = t - turned / 2
        // R_k = [[c, −s], [s, c]] maps (1, 0) → (c, s): clockwise on screen when y is down.
        let back = SIMD2(c * rel.x + s * rel.y, -s * rel.x + c * rel.y)
        return back + SIMD2(imageWidth, imageHeight) / 2
    }

    /// The prototype cells whose centre ray meets the object's own outline,
    /// glass included and nothing else in the way: the detector sees a chair
    /// through a glass table, and outlines the table's glass too.
    func silhouetteCells(of id: Int, camera: SyntheticCamera, turn: QuarterTurn) -> [Bool] {
        let n = Self.protoSize
        let stride = Float(Self.modelSize) / Float(n)
        let object = objects.first { $0.id == id }!
        let alone = SyntheticScene(objects: [SyntheticObject(id: id, name: object.name, box: object.box,
                                                             parts: object.maskParts ?? object.parts)])
        var cells = [Bool](repeating: false, count: n * n)
        for j in 0..<n {
            for i in 0..<n {
                let m = SIMD2((Float(i) + 0.5) * stride, (Float(j) + 0.5) * stride)
                guard let p = Self.imagePoint(model: m, turn: turn) else { continue }
                cells[j * n + i] = alone.cast(origin: camera.eye, direction: ray(camera: camera, u: p.x, v: p.y)).id == id
            }
        }
        return cells
    }

    /// Which object each prototype cell sees, by casting through the cell centre.
    func renderProtoIDs(camera: SyntheticCamera, turn: QuarterTurn) -> [Int] {
        let n = Self.protoSize
        let stride = Float(Self.modelSize) / Float(n)
        var ids = [Int](repeating: -2, count: n * n)
        for j in 0..<n {
            for i in 0..<n {
                let m = SIMD2((Float(i) + 0.5) * stride, (Float(j) + 0.5) * stride)
                guard let p = Self.imagePoint(model: m, turn: turn) else { continue }
                ids[j * n + i] = cast(origin: camera.eye, direction: ray(camera: camera, u: p.x, v: p.y)).id
            }
        }
        return ids
    }

    /// One object's detection as the exported head would report it: a box
    /// around its silhouette and a single-prototype mask whose edge bleeds.
    /// Nil when too little of the object is in view.
    static func detection(of id: Int, protoIDs: [Int], bleed: Bool, filled: Bool = false,
                          rng: inout SeededGenerator) -> (RawDetection, ProtoBank)? {
        detection(of: [id], protoIDs: protoIDs, bleed: bleed, filled: filled, rng: &rng)
    }

    static func detection(of ids: Set<Int>, protoIDs: [Int], bleed: Bool, filled: Bool = false,
                          rng: inout SeededGenerator) -> (RawDetection, ProtoBank)? {
        detection(cells: protoIDs.map { ids.contains($0) }, bleed: bleed, filled: filled, rng: &rng)
    }

    /// A detection whose mask is the given prototype cells, bleeding and
    /// filled as asked.
    static func detection(cells: [Bool], bleed: Bool, filled: Bool = false,
                          rng: inout SeededGenerator) -> (RawDetection, ProtoBank)? {
        let n = protoSize
        var inside = cells
        guard inside.filter({ $0 }).count >= 6 else { return nil }
        if filled { inside = convexFill(inside, size: n) }
        if bleed {
            let original = inside
            for j in 0..<n {
                for i in 0..<n where !original[j * n + i] {
                    var touches = false
                    for (di, dj) in [(1, 0), (-1, 0), (0, 1), (0, -1)] {
                        let ni = i + di, nj = j + dj
                        if ni >= 0, nj >= 0, ni < n, nj < n, original[nj * n + ni] { touches = true }
                    }
                    if touches, rng.unit() < 0.5 { inside[j * n + i] = true }
                }
            }
        }
        var lo = SIMD2<Float>(repeating: .greatestFiniteMagnitude)
        var hi = SIMD2<Float>(repeating: -.greatestFiniteMagnitude)
        let stride = Float(modelSize) / Float(n)
        for j in 0..<n {
            for i in 0..<n where inside[j * n + i] {
                lo = simd_min(lo, SIMD2(Float(i), Float(j)) * stride)
                hi = simd_max(hi, SIMD2(Float(i + 1), Float(j + 1)) * stride)
            }
        }
        let logits = inside.map { $0 ? Float(6) : Float(-6) }
        let bank = ProtoBank(channels: 1, width: n, height: n, values: logits,
                             modelWidth: Float(modelSize), modelHeight: Float(modelSize))
        let detection = RawDetection(classIndex: 0, score: 0.8, modelMin: lo, modelMax: hi, coefficients: [1])
        return (detection, bank)
    }

    /// Every cell whose centre lies inside the convex hull of the cells set in
    /// `inside` — a mask with no holes, whatever the object has between its parts.
    static func convexFill(_ inside: [Bool], size n: Int) -> [Bool] {
        var centres: [SIMD2<Float>] = []
        for j in 0..<n {
            for i in 0..<n where inside[j * n + i] {
                // The cell's corners, so a one-cell-wide part keeps its width.
                centres += [SIMD2(Float(i), Float(j)), SIMD2(Float(i + 1), Float(j)),
                            SIMD2(Float(i), Float(j + 1)), SIMD2(Float(i + 1), Float(j + 1))]
            }
        }
        let hull = GravityBoxMath.convexHull(centres)
        guard hull.count >= 3 else { return inside }
        var out = inside
        for j in 0..<n {
            for i in 0..<n where !out[j * n + i] {
                let p = SIMD2(Float(i) + 0.5, Float(j) + 0.5)
                var within = true
                for k in hull.indices {
                    let a = hull[k], b = hull[(k + 1) % hull.count]
                    if (b.x - a.x) * (p.y - a.y) - (b.y - a.y) * (p.x - a.x) < 0 { within = false; break }
                }
                if within { out[j * n + i] = true }
            }
        }
        return out
    }
}

// MARK: - Depth models

extension SyntheticScene {
    /// The true z-depth at every depth pixel's centre, with none of LiDAR's
    /// defects: what a perfect depth model would see, in metres.
    func trueDepth(camera: SyntheticCamera) -> [Float] {
        let w = Self.depthWidth, h = Self.depthHeight
        let sx = Self.imageWidth / Float(w), sy = Self.imageHeight / Float(h)
        var depth = [Float](repeating: 0, count: w * h)
        for j in 0..<h {
            for i in 0..<w {
                depth[j * w + i] = cast(origin: camera.eye,
                                        direction: ray(camera: camera, u: (Float(i) + 0.5) * sx,
                                                       v: (Float(j) + 0.5) * sy)).t
            }
        }
        return depth
    }

    /// A depth model's map of the room from `camera`. Its input is the camera
    /// image turned upright by `turn` and letterboxed into `input`; the map
    /// covers that input at the `output` resolution, and each pixel holds
    /// `value` of the z-depth seen through its centre — the padding, 0.
    func modelMap(camera: SyntheticCamera, turn: QuarterTurn, input: (width: Int, height: Int),
                  output: (width: Int, height: Int), value: (Float) -> Float) -> DepthModelMap {
        var values = [Float](repeating: 0, count: output.width * output.height)
        for j in 0..<output.height {
            for i in 0..<output.width {
                let m = SIMD2((Float(i) + 0.5) * Float(input.width) / Float(output.width),
                              (Float(j) + 0.5) * Float(input.height) / Float(output.height))
                guard let p = Self.imagePoint(model: m, turn: turn, inputWidth: input.width,
                                              inputHeight: input.height) else { continue }
                values[j * output.width + i] = value(cast(origin: camera.eye,
                                                          direction: ray(camera: camera, u: p.x, v: p.y)).t)
            }
        }
        return DepthModelMap(width: output.width, height: output.height, values: values)
    }

    /// The floor as ARKit reports a plane: an anchor turned by `yaw` about +Y
    /// and set at `origin` on the floor, the plane its local y = 0, and its
    /// measured outline — the room's floor shrunk by `inset` from every wall —
    /// in the anchor's own (x, z).
    func floorAnchor(inset: Float = 0, yaw: Float = 0.5, origin: SIMD2<Float> = SIMD2(0.3, -0.2)) -> AnchorPlane {
        let c = cos(yaw), s = sin(yaw)
        // A right-handed turn about +Y: local X → (c, 0, −s), local Z → (s, 0, c).
        let transform = simd_float4x4(columns: (SIMD4(c, 0, -s, 0), SIMD4(0, 1, 0, 0), SIMD4(s, 0, c, 0),
                                                SIMD4(origin.x, 0, origin.y, 1)))
        let corners = [SIMD2(-halfX + inset, -halfZ + inset), SIMD2(halfX - inset, -halfZ + inset),
                       SIMD2(halfX - inset, halfZ - inset), SIMD2(-halfX + inset, halfZ - inset)]
        let outline = corners.map { corner -> SIMD2<Float> in
            let d = corner - origin
            return SIMD2(d.x * c - d.y * s, d.x * s + d.y * c)
        }
        return AnchorPlane(worldFromPlane: transform, outline: outline)
    }

    /// Feature points ARKit would track from `camera`: the surfaces seen at
    /// `count` random depth pixels, each moved by `noise` metres (standard
    /// deviation, every axis), and a share `outliers` of them put at a wrong
    /// depth along their own ray instead.
    func featurePoints(camera: SyntheticCamera, count: Int, noise: Float, outliers: Float,
                       rng: inout SeededGenerator) -> [SIMD3<Float>] {
        let sx = Self.imageWidth / Float(Self.depthWidth), sy = Self.imageHeight / Float(Self.depthHeight)
        return (0..<count).map { _ in
            let i = Int(rng.unit() * Float(Self.depthWidth)), j = Int(rng.unit() * Float(Self.depthHeight))
            let direction = ray(camera: camera, u: (Float(i) + 0.5) * sx, v: (Float(j) + 0.5) * sy)
            let t = cast(origin: camera.eye, direction: direction).t
            if rng.unit() < outliers { return camera.eye + direction * t * (0.4 + 1.2 * rng.unit()) }
            return camera.eye + direction * t + SIMD3(rng.gaussian(), rng.gaussian(), rng.gaussian()) * noise
        }
    }
}
