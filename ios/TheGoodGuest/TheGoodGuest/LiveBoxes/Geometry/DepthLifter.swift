/// From a detector's mask and one frame's LiDAR depth to the world points that
/// are the object — DEBUG-only (decision 0295).
///
/// A mask is a claim about PIXELS, and the depth under it is only partly the
/// object: its edge bleeds onto whatever is behind, LiDAR smears a depth edge
/// into "flying" pixels between the two surfaces, some pixels carry low
/// confidence, and anyone standing in front of the object is inside its mask.
/// Each filter below removes one of those, and none of them assumes anything
/// about what the object is:
///
///   1. EXCLUSION — pixels claimed by an excluded detection (a person, a pet)
///      never count for anything else. A person is never lifted (0089).
///   2. CONFIDENCE AND RANGE — below medium confidence, or outside the range
///      LiDAR measures, a depth is not a measurement.
///   3. DEPTH EDGES — a pixel with a 4-neighbour NEARER than it by more than a
///      few centimetres (or percent) is behind a silhouette: a flying pixel,
///      or the background bleed starts on. The silhouette's own foreground
///      pixel has only farther neighbours and stays, so an edge costs the
///      object nothing.
///   4. BORDERS — near the mask's edge a depth must agree with the mask's own
///      depths around it. Bleed onto a background at a depth the object also
///      spans (the wall beside a tall shelf seen from close) passes 3, and
///      fails here.
///   5. SURFACES — points within a band of the floor, the ceiling, a table top
///      below the object, or a wall behind it are that surface. The floor and
///      the ceiling are never the object, even when they are all its outline
///      measures: through an all-glass table there is only floor, which is then
///      the outline's middle. A real mask covers far more of them than its edge:
///      a chair's mask takes in the floor between its legs and the wall between
///      its slats. The band hides the object's own last centimetres too, so an
///      object whose lowest remaining points reach the band's edge is reported
///      as resting on that surface, and fusion takes its box down to it. A
///      floor or a ceiling reaches the whole room; a table top or a wall only as
///      far as ARKit measured it. A wall counts only when the object stands
///      off it on the camera's side — a picture on it, or the front of a
///      wardrobe ARKit took for a wall, is the object, not its background —
///      and an object whose points reach that band is reported as standing
///      against the wall, so fusion puts its back on the wall as RoomPlan does.
///   6. ONE OBJECT — what is left is cut into pieces that touch in 3D, and the
///      object is the NEAREST piece of any size — at least a quarter of the
///      largest — with anything standing on it or hanging under it. An object
///      stands before its background: around a floor lamp's pole the mask is
///      mostly wall, and that patch of wall can outnumber the shade. Something
///      small in front (a glass table's frame before a sofa) is never a
///      quarter of the object; something large in front is detected itself,
///      and keeps its own pixels. Removing the surfaces first is what makes this work: the
///      floor spans every depth from a chair to the wall behind it, so while it
///      was there nothing split by depth could tell them apart. A plane ARKit
///      placed a centimetre off leaves a thin sheet of its points just past the
///      band. Off a floor, a table or a ceiling the sheet takes no part in the
///      pieces and comes back only straight under (or over) the object — a
///      chair's last centimetres of leg, not the floor in front of a sofa. Off
///      a wall, where an object's back really is, it joins a piece but never
///      joins two.
///   7. COVERAGE — if what is left is a small share of the mask's measured
///      pixels, LiDAR did not see the object: glass, a mirror, a thin frame
///      the detector named for the space it encloses. No observation.
///
/// A floor covering (`flat`) is coplanar with what it lies on, so it skips 4
/// to 7 and keeps the largest group of depths split at gaps instead.
///
/// Read by: DetectorPipeline, BoxFusion (masks and depth for its votes),
/// LiveBoxesGeometryTests, LiveBoxesLiftingTests and LiveBoxesOpenFurnitureTests.

#if DEBUG

import simd

// MARK: - Depth

/// A depth map and its confidence, copied out of an ARFrame.
nonisolated struct DepthGrid: Sendable {
    let width: Int
    let height: Int
    /// z-depth, metres, row-major. Zero, negative or NaN where nothing was measured.
    let depth: [Float]
    /// ARConfidenceLevel raw values (0 low, 1 medium, 2 high), row-major.
    let confidence: [UInt8]?

    init(width: Int, height: Int, depth: [Float], confidence: [UInt8]?) {
        precondition(depth.count == width * height)
        precondition(confidence.map { $0.count == width * height } ?? true)
        self.width = width
        self.height = height
        self.depth = depth
        self.confidence = confidence
    }

    @inline(__always) func depth(x: Int, y: Int) -> Float { depth[y * width + x] }

    @inline(__always) func confidence(x: Int, y: Int) -> UInt8 {
        confidence?[y * width + x] ?? 2
    }

    @inline(__always) static func isMeasured(_ d: Float) -> Bool { d.isFinite && d > 0 }

    /// The median of the depths measured with at least `minimumConfidence`
    /// within `radius` pixels of (x, y), or nil when none was.
    func medianDepth(x: Int, y: Int, radius: Int, minimumConfidence: UInt8) -> Float? {
        var found: [Float] = []
        for yy in max(y - radius, 0)...min(y + radius, height - 1) {
            for xx in max(x - radius, 0)...min(x + radius, width - 1) {
                let d = depth(x: xx, y: yy)
                if Self.isMeasured(d), confidence(x: xx, y: yy) >= minimumConfidence { found.append(d) }
            }
        }
        guard !found.isEmpty else { return nil }
        found.sort()
        return found[found.count / 2]
    }
}

// MARK: - Masks

/// A boolean mask over a rectangle of the depth map. Everything outside the
/// rectangle is outside the mask.
nonisolated struct DepthMask: Sendable, Equatable {
    let xRange: ClosedRange<Int>
    let yRange: ClosedRange<Int>
    private(set) var bits: [Bool]

    init(xRange: ClosedRange<Int>, yRange: ClosedRange<Int>, bits: [Bool]) {
        precondition(bits.count == xRange.count * yRange.count)
        self.xRange = xRange
        self.yRange = yRange
        self.bits = bits
    }

    /// Sample `inside` at every pixel of the rectangle.
    init(xRange: ClosedRange<Int>, yRange: ClosedRange<Int>, inside: (Int, Int) -> Bool) {
        var bits = [Bool](repeating: false, count: xRange.count * yRange.count)
        var k = 0
        for y in yRange {
            for x in xRange {
                bits[k] = inside(x, y)
                k += 1
            }
        }
        self.init(xRange: xRange, yRange: yRange, bits: bits)
    }

    subscript(x: Int, y: Int) -> Bool {
        guard xRange.contains(x), yRange.contains(y) else { return false }
        return bits[(y - yRange.lowerBound) * xRange.count + (x - xRange.lowerBound)]
    }

    var count: Int { bits.reduce(0) { $0 + ($1 ? 1 : 0) } }

    /// This mask minus every pixel `other` claims.
    func subtracting(_ other: DepthMask) -> DepthMask {
        var out = self
        var k = 0
        for y in yRange {
            for x in xRange {
                if out.bits[k], other[x, y] { out.bits[k] = false }
                k += 1
            }
        }
        return out
    }

    /// Every pixel either mask claims, over the rectangle covering both.
    func union(_ other: DepthMask) -> DepthMask {
        let xr = min(xRange.lowerBound, other.xRange.lowerBound)...max(xRange.upperBound, other.xRange.upperBound)
        let yr = min(yRange.lowerBound, other.yRange.lowerBound)...max(yRange.upperBound, other.yRange.upperBound)
        return DepthMask(xRange: xr, yRange: yr) { x, y in self[x, y] || other[x, y] }
    }

    /// This mask grown by `radius` pixels (Chebyshev), within a
    /// `width`×`height` depth map.
    func dilated(by radius: Int, width: Int, height: Int) -> DepthMask {
        guard radius > 0 else { return self }
        let xr = max(xRange.lowerBound - radius, 0)...min(xRange.upperBound + radius, width - 1)
        let yr = max(yRange.lowerBound - radius, 0)...min(yRange.upperBound + radius, height - 1)
        return DepthMask(xRange: xr, yRange: yr) { x, y in
            for dy in -radius...radius {
                for dx in -radius...radius where self[x + dx, y + dy] { return true }
            }
            return false
        }
    }

    /// For every pixel of the rectangle, its Chebyshev distance to the nearest
    /// pixel outside the mask, the rectangle's outside counting as outside:
    /// 1 on the edge, growing inward, 0 off the mask. Row-major.
    func inset() -> [Int] {
        let w = xRange.count, h = yRange.count
        var d = bits.map { $0 ? w + h : 0 }
        func at(_ i: Int, _ j: Int) -> Int {
            (i < 0 || j < 0 || i >= w || j >= h) ? 0 : d[j * w + i]
        }
        for j in 0..<h {
            for i in 0..<w where d[j * w + i] > 0 {
                d[j * w + i] = min(d[j * w + i], at(i - 1, j) + 1, at(i - 1, j - 1) + 1,
                                   at(i, j - 1) + 1, at(i + 1, j - 1) + 1)
            }
        }
        for j in stride(from: h - 1, through: 0, by: -1) {
            for i in stride(from: w - 1, through: 0, by: -1) where d[j * w + i] > 0 {
                d[j * w + i] = min(d[j * w + i], at(i + 1, j) + 1, at(i + 1, j + 1) + 1,
                                   at(i, j + 1) + 1, at(i - 1, j + 1) + 1)
            }
        }
        return d
    }
}

nonisolated extension DepthMask {
    /// Each detection's mask minus the pixels another detection's mask claims
    /// more rightly. Where a cushion lies on a sofa, or a chair stands at a
    /// table, the detector's masks overlap: on the phone a glass table's box
    /// was made of the chairs in its mask, because LiDAR saw nothing of the
    /// glass. For each pair that overlaps:
    ///
    ///   • NESTED — at least `nesting` of the smaller mask lies inside the
    ///     larger: the smaller is an object on or in the other (a cushion, a
    ///     pillow), and keeps the shared pixels;
    ///   • SIDE BY SIDE — otherwise one stands before the other, and the
    ///     detection the detector is surer of keeps them, as panoptic merging
    ///     does; on a tie, the smaller.
    ///
    /// A pixel stays with a mask only while it wins against every other mask
    /// claiming it. Keys are the caller's.
    static func owned<Key: Hashable & Comparable>(_ claims: [Key: (mask: DepthMask, score: Float)],
                                                  nesting: Float = 0.7) -> [Key: DepthMask] {
        let keys = claims.keys.sorted()
        let counts = claims.mapValues { $0.mask.count }
        var own = claims.mapValues(\.mask)
        for (i, a) in keys.enumerated() {
            for b in keys[(i + 1)...] {
                let ma = claims[a]!.mask, mb = claims[b]!.mask
                let x0 = max(ma.xRange.lowerBound, mb.xRange.lowerBound), x1 = min(ma.xRange.upperBound, mb.xRange.upperBound)
                let y0 = max(ma.yRange.lowerBound, mb.yRange.lowerBound), y1 = min(ma.yRange.upperBound, mb.yRange.upperBound)
                guard x0 <= x1, y0 <= y1 else { continue }
                var shared = 0
                for y in y0...y1 {
                    for x in x0...x1 where ma[x, y] && mb[x, y] { shared += 1 }
                }
                guard shared > 0 else { continue }
                let small = (counts[a]!, a) <= (counts[b]!, b) ? a : b
                let sa = claims[a]!.score, sb = claims[b]!.score
                let winner: Key
                if Float(shared) >= nesting * Float(counts[small]!) || sa == sb {
                    winner = small
                } else {
                    winner = sa > sb ? a : b
                }
                let loser = winner == a ? b : a
                own[loser] = own[loser]!.subtracting(claims[winner]!.mask)
            }
        }
        return own
    }
}

// MARK: - Lifting

nonisolated struct DepthLiftParameters: Sendable, Equatable, Codable {
    /// ARConfidenceLevel at or above which a depth counts (1 = medium).
    var minimumConfidence: UInt8 = 1
    var minimumDepth: Float = 0.2
    /// LiDAR reads to about 5 m.
    var maximumDepth: Float = 5.0
    /// A 4-neighbour depth step above max(absolute, relative · depth) marks a silhouette.
    var edgeStepAbsolute: Float = 0.04
    var edgeStepRelative: Float = 0.03
    /// Within this many pixels of the mask's edge, a depth must agree with the
    /// median of the mask's own depths around it.
    var borderRadius: Int = 4
    var borderAgreementAbsolute: Float = 0.06
    var borderAgreementRelative: Float = 0.035
    /// Sorted depths further apart than max(absolute, relative · depth) split groups.
    var groupGapAbsolute: Float = 0.08
    var groupGapRelative: Float = 0.04
    /// Half-thickness of the band around a supporting surface's height.
    var supportBand: Float = 0.02
    /// An object whose lowest points (robustly) come within this of the band's
    /// edge touches the surface: the band hid its last centimetres.
    var contactMargin: Float = 0.03
    /// A table top's measured extent counts this much wider: ARKit grows a
    /// plane as more of it is seen.
    var planeMargin: Float = 0.10
    /// Fewer surviving pixels than this is no observation.
    var minimumPixels: Int = 24
    /// A detection whose box covers less of the view than this is not lifted
    /// at all: it is far away or tiny, LiDAR gives it a handful of samples, and
    /// on the phone such detections were most of the junk tracks.
    var minimumViewFraction: Float = 0.005
    /// A detection within this fraction of the image's edge is cut off by it:
    /// it can add to a track, but not start one.
    var edgeMargin: Float = 0.02
    /// Half-thickness of the band around a wall behind the object.
    var wallBand: Float = 0.03
    /// Points this close to a removed floor, table top or ceiling are its
    /// sheet: kept only in the columns, this wide, that the object stands over.
    var supportSheet: Float = 0.04
    var sheetColumn: Float = 0.02
    /// Points this close to a removed wall are its sheet: they join a piece of
    /// the object but never join two pieces.
    var wallSheet: Float = 0.06
    /// The cell size that decides which points touch: pieces closer than one
    /// cell join, pieces two cells apart never do.
    var componentCell: Float = 0.04
    /// A piece is the object's candidate from this share of the largest piece up.
    var substantialPiece: Float = 0.25
    /// The object's points must be at least this share of the mask's measured pixels.
    var minimumCoverage: Float = 0.15
}

/// A horizontal plane ARKit measured: how high it is, and where.
nonisolated struct HorizontalSurface: Sendable, Equatable {
    enum Kind: Sendable, Equatable {
        /// Things stand on a floor anywhere in the room.
        case floor
        /// Things hang from a ceiling anywhere in the room.
        case ceiling
        /// A table top or a seat: things stand on it where it is.
        case support
        /// A plane ARKit did not classify, where it is: it supports what is
        /// above it and is the ceiling of what hangs below it.
        case unclassified
    }

    let kind: Kind
    let height: Float
    /// Its extent on the floor plane; nil for a floor or a ceiling.
    let extent: PlanRectangle?

    var supportsObjects: Bool { kind != .ceiling }
    var hangsObjects: Bool { kind == .ceiling || kind == .unclassified }

    /// Whether a world point lies over or under this surface.
    func covers(_ p: SIMD3<Float>, margin: Float) -> Bool {
        extent?.contains(SIMD2(p.x, p.z), margin: margin) ?? true
    }
}

/// A vertical plane ARKit measured — a wall, or a face as large as one — as far
/// as it was measured.
nonisolated struct VerticalSurface: Sendable, Equatable {
    /// Unit normal on the floor plane, (x, z).
    let normal: SIMD2<Float>
    /// The plane is every point p with normal · (p.x, p.z) = offset.
    let offset: Float
    /// How far it runs along the floor plane — along (−normal.z, normal.x) —
    /// and in height.
    let along: ClosedRange<Float>
    let heights: ClosedRange<Float>

    init(normal: SIMD2<Float>, offset: Float, along: ClosedRange<Float>, heights: ClosedRange<Float>) {
        self.normal = normal
        self.offset = offset
        self.along = along
        self.heights = heights
    }

    /// The plane ARKit reports — its normal and a point on it in world
    /// coordinates, and its measured boundary as world points — or nil when
    /// the normal is not horizontal enough for a wall or there is no boundary.
    init?(normal n: SIMD3<Float>, point: SIMD3<Float>, boundary: [SIMD3<Float>]) {
        let flat = SIMD2(n.x, n.z)
        guard !boundary.isEmpty, simd_length(flat) >= 0.95 * simd_length(n), simd_length(flat) > 1e-6 else {
            return nil
        }
        let unit = simd_normalize(flat)
        let tangent = SIMD2(-unit.y, unit.x)
        let t = boundary.map { simd_dot(tangent, SIMD2($0.x, $0.z)) }
        let y = boundary.map(\.y)
        self.init(normal: unit, offset: simd_dot(unit, SIMD2(point.x, point.z)),
                  along: t.min()!...t.max()!, heights: y.min()!...y.max()!)
    }

    /// The same plane with its normal facing the other way when `side` is negative.
    func facing(_ side: Float) -> VerticalSurface {
        guard side < 0 else { return self }
        return VerticalSurface(normal: -normal, offset: -offset,
                               along: -along.upperBound...(-along.lowerBound), heights: heights)
    }

    /// Signed distance from the plane, positive on the normal's side.
    func distance(_ p: SIMD3<Float>) -> Float {
        simd_dot(normal, SIMD2(p.x, p.z)) - offset
    }

    /// Whether a point lies in front of or behind the measured part of the plane.
    func covers(_ p: SIMD3<Float>, margin: Float) -> Bool {
        let t = simd_dot(SIMD2(-normal.y, normal.x), SIMD2(p.x, p.z))
        return t >= along.lowerBound - margin && t <= along.upperBound + margin
            && p.y >= heights.lowerBound - margin && p.y <= heights.upperBound + margin
    }
}

/// The room's wall grid: the direction walls run, modulo a quarter turn, as
/// an angle φ of a floor-plane axis (cos φ, sin φ) in (x, z). A length-weighted
/// circular mean over 4φ, so perpendicular walls reinforce one grid instead of
/// cancelling — the heading `FloorPlanMath.gridHeading` takes from RoomPlan's
/// walls, here from ARKit's vertical planes, which outlive RoomPlan.
nonisolated enum WallGrid {
    /// `walls` are directions along (or across) each wall in (x, z), with a
    /// weight such as its measured width. Nil until a wall is known.
    static func phi(_ walls: [(direction: SIMD2<Float>, weight: Float)]) -> Float? {
        var sx: Float = 0, sy: Float = 0
        for wall in walls where wall.weight > 0 && simd_length(wall.direction) > 1e-6 {
            let angle = atan2(wall.direction.y, wall.direction.x)
            sx += wall.weight * cos(4 * angle)
            sy += wall.weight * sin(4 * angle)
        }
        guard sx * sx + sy * sy > 1e-9 else { return nil }
        return atan2(sy, sx) / 4
    }
}

/// A rectangle on the floor plane, in (x, z).
nonisolated struct PlanRectangle: Sendable, Equatable {
    let center: SIMD2<Float>
    /// Unit direction of the first pair of sides.
    let axis: SIMD2<Float>
    /// Half the side along `axis`, then half the side across it.
    let halfExtents: SIMD2<Float>

    func contains(_ p: SIMD2<Float>, margin: Float = 0) -> Bool {
        let d = p - center
        return abs(simd_dot(d, axis)) <= halfExtents.x + margin
            && abs(simd_dot(d, SIMD2(-axis.y, axis.x))) <= halfExtents.y + margin
    }

    /// The minimum-area rectangle around `points` — a plane's boundary — or
    /// nil when they enclose no area.
    static func enclosing(_ points: [SIMD2<Float>]) -> PlanRectangle? {
        let hull = GravityBoxMath.convexHull(points)
        guard hull.count >= 3 else { return nil }
        let phi = GravityBoxFit.minimumAreaDirection(hull)
        let u = SIMD2(cos(phi), sin(phi)), v = SIMD2(-u.y, u.x)
        var lo = SIMD2<Float>(repeating: .greatestFiniteMagnitude)
        var hi = SIMD2<Float>(repeating: -.greatestFiniteMagnitude)
        for p in hull {
            let q = SIMD2(simd_dot(p, u), simd_dot(p, v))
            lo = simd_min(lo, q)
            hi = simd_max(hi, q)
        }
        let mid = (lo + hi) / 2
        return PlanRectangle(center: u * mid.x + v * mid.y, axis: u, halfExtents: (hi - lo) / 2)
    }
}

nonisolated struct LiftedPoints: Sendable {
    /// World points, one per surviving depth pixel.
    let points: [SIMD3<Float>]
    /// Pixels under the mask before any filter.
    let maskPixels: Int
    /// Median z-depth of the kept pixels.
    let medianDepth: Float
    /// The height of the surface the object stands on, when its lowest points
    /// reach down into that surface's band.
    let restsOn: Float?
    /// The height of the ceiling it hangs from, likewise.
    let hangsFrom: Float?
    /// Walls it stands against, likewise, each facing the object.
    var against: [VerticalSurface] = []
}

/// Why a mask gave no points: the filter that left too few, in the words the
/// session log uses. Glass is what these were first needed for: through it
/// LiDAR measures whatever stands behind, and nothing of the glass.
nonisolated enum LiftRejection: String, Sendable, CaseIterable {
    /// Fewer pixels under the mask than an observation needs.
    case tooFewPixels = "too few pixels"
    /// Too few depths measured with confidence, in range, off a depth edge
    /// and agreeing at the border: glass, black, or too far.
    case noDepth = "no depth under it"
    /// What was measured was surfaces filter 5 removes — the floor, a table
    /// top below the object's middle, the ceiling, a wall behind it — seen
    /// through glass, say.
    case onlySurfaces = "only surfaces under it"
    /// What is left is too small a share of what was measured to be the object.
    case tooLittleSeen = "too little of it seen"
}

nonisolated enum LiftAttempt: Sendable {
    case lifted(LiftedPoints)
    case rejected(LiftRejection)
}

nonisolated enum DepthLifter {

    /// The world points under `mask`, or nil when too few survive (`attempt`).
    static func lift(mask: DepthMask, excluding excluded: DepthMask?,
                     depth grid: DepthGrid, frame: SensorFrame,
                     surfaces: [HorizontalSurface], walls: [VerticalSurface] = [], flat: Bool, ownTop: Bool = false,
                     parameters p: DepthLiftParameters = DepthLiftParameters()) -> LiftedPoints? {
        guard case .lifted(let points) = attempt(mask: mask, excluding: excluded, depth: grid, frame: frame,
                                                 surfaces: surfaces, walls: walls, flat: flat, ownTop: ownTop,
                                                 parameters: p)
        else { return nil }
        return points
    }

    /// The world points under `mask`, or which filter left too few of them.
    ///
    /// `flat` marks an object that is itself a floor covering (a rug, a mat):
    /// its own pixels are coplanar with what it lies on, so the border and
    /// supporting-surface filters would remove the object itself.
    ///
    /// `ownTop` marks an object whose own top is a surface ARKit reports (a table, a
    /// desk): only the floor is taken from under it. Otherwise, with a laptop and a
    /// bowl on it, the median point sits above the top and the top counts as a
    /// surface the object stands on, and is deleted from the object.
    static func attempt(mask: DepthMask, excluding excluded: DepthMask?,
                        depth grid: DepthGrid, frame: SensorFrame,
                        surfaces: [HorizontalSurface], walls: [VerticalSurface] = [], flat: Bool, ownTop: Bool = false,
                        parameters p: DepthLiftParameters = DepthLiftParameters()) -> LiftAttempt {
        let maskPixels = mask.count
        guard maskPixels >= p.minimumPixels else { return .rejected(.tooFewPixels) }
        let claimed = excluded.map { mask.subtracting($0) } ?? mask

        // Filters 1 and 2 give every claimed pixel's measured depth; filter 3
        // then marks which of those may become points. The border statistic
        // below reads the measured depths, edges included — near a silhouette
        // the edge band is exactly where the object's own depths are.
        let x0 = claimed.xRange.lowerBound, y0 = claimed.yRange.lowerBound
        let w = claimed.xRange.count, h = claimed.yRange.count
        var measured = [Float](repeating: .nan, count: w * h)
        var usable = [Bool](repeating: false, count: w * h)
        for y in claimed.yRange {
            for x in claimed.xRange where claimed[x, y] {
                let d = grid.depth(x: x, y: y)
                guard DepthGrid.isMeasured(d), d >= p.minimumDepth, d <= p.maximumDepth,
                      grid.confidence(x: x, y: y) >= p.minimumConfidence
                else { continue }
                let k = (y - y0) * w + (x - x0)
                measured[k] = d
                usable[k] = !isOnDepthEdge(x: x, y: y, depth: d, grid: grid, parameters: p)
            }
        }

        // Filter 4: the border.
        let inset = flat ? nil : claimed.inset()
        var candidates: [(x: Int, y: Int, d: Float)] = []
        candidates.reserveCapacity(maskPixels)
        var window: [Float] = []
        let r = p.borderRadius
        for j in 0..<h {
            for i in 0..<w where usable[j * w + i] {
                let d = measured[j * w + i]
                if let inset, inset[j * w + i] <= r {
                    window.removeAll(keepingCapacity: true)
                    for jj in max(j - r, 0)...min(j + r, h - 1) {
                        for ii in max(i - r, 0)...min(i + r, w - 1) {
                            let n = measured[jj * w + ii]
                            if !n.isNaN { window.append(n) }
                        }
                    }
                    window.sort()
                    let median = window[window.count / 2]
                    guard abs(d - median) <= max(p.borderAgreementAbsolute, p.borderAgreementRelative * d)
                    else { continue }
                }
                candidates.append((i + x0, j + y0, d))
            }
        }
        guard candidates.count >= p.minimumPixels else { return .rejected(.noDepth) }

        if flat {
            let group = dominantGroup(candidates.map(\.d), parameters: p)
            var points: [SIMD3<Float>] = []
            var depths: [Float] = []
            for c in candidates where c.d >= group.lowerBound && c.d <= group.upperBound {
                points.append(frame.worldPoint(depthX: c.x, depthY: c.y, depth: c.d))
                depths.append(c.d)
            }
            guard points.count >= p.minimumPixels else { return .rejected(.tooLittleSeen) }
            depths.sort()
            return .lifted(LiftedPoints(points: points, maskPixels: maskPixels, medianDepth: depths[depths.count / 2],
                                        restsOn: nil, hangsFrom: nil))
        }
        let world = candidates.map { frame.worldPoint(depthX: $0.x, depthY: $0.y, depth: $0.d) }

        // Filter 5: the surfaces below, above and behind. A floor or a ceiling
        // is never part of an object, even where it is all an outline holds:
        // an all-glass table's outline measures only the floor through it.
        let heights = world.map(\.y).sorted()
        let median = heights[heights.count / 2]
        let below = surfaces.filter {
            $0.supportsObjects && ($0.kind == .floor || (!ownTop && $0.height < median - p.supportBand))
        }
        let above = surfaces.filter { $0.hangsObjects && ($0.kind == .ceiling || $0.height > median + p.supportBand) }
        let camera = frame.cameraPosition
        let behind = walls.compactMap { wall -> (wall: VerticalSurface, side: Float)? in
            let side: Float = wall.distance(camera) >= 0 ? 1 : -1
            var offsets = world.compactMap { wall.covers($0, margin: p.planeMargin) ? side * wall.distance($0) : nil }
            guard offsets.count >= p.minimumPixels else { return nil }
            offsets.sort()
            // The wall is background when the object stands off it toward the
            // camera: more than a quarter of what the wall covers is well
            // clear of it, whatever share of the mask the wall itself fills.
            return offsets[offsets.count * 3 / 4] > 2 * p.wallBand ? (wall, side) : nil
        }
        let horizontal = below + above
        var kept: [Int] = []
        var sheet: [Bool] = []
        var hugging: [Int] = []
        kept.reserveCapacity(world.count)
        sheet.reserveCapacity(world.count)
        points: for (i, point) in world.enumerated() {
            var hugs = false, near = false
            for s in horizontal where s.covers(point, margin: p.planeMargin) {
                let d = abs(point.y - s.height)
                if d <= p.supportBand { continue points }
                if d <= p.supportSheet { hugs = true }
            }
            if hugs {
                hugging.append(i)
                continue
            }
            for b in behind where b.wall.covers(point, margin: p.planeMargin) {
                let d = b.side * b.wall.distance(point)
                if d <= p.wallBand { continue points }
                if d <= p.wallSheet { near = true }
            }
            kept.append(i)
            sheet.append(near)
        }
        guard kept.count >= p.minimumPixels else { return .rejected(.onlySurfaces) }

        // Filter 6: one object, and the sheet straight under or over it.
        let object = connectedObject(kept.map { world[$0] }, depths: kept.map { candidates[$0].d }, sheet: sheet,
                                     cell: p.componentCell, substantial: p.substantialPiece).map { kept[$0] }
        struct Column: Hashable { let x: Int32, z: Int32 }
        func column(_ q: SIMD3<Float>) -> Column {
            Column(x: Int32((q.x / p.sheetColumn).rounded(.down)), z: Int32((q.z / p.sheetColumn).rounded(.down)))
        }
        let columns = Set(object.map { column(world[$0]) })
        let chosen = object + hugging.filter { columns.contains(column(world[$0])) }
        // Filter 7: enough of the mask to be it.
        guard chosen.count >= p.minimumPixels,
              Float(chosen.count) >= p.minimumCoverage * Float(measured.lazy.filter { !$0.isNaN }.count)
        else { return .rejected(.tooLittleSeen) }
        let points = chosen.map { world[$0] }
        var depths = chosen.map { candidates[$0].d }

        var restsOn: Float?
        var hangsFrom: Float?
        if !below.isEmpty || !above.isEmpty {
            let ys = points.map(\.y).sorted()
            let low = ys[ys.count / 100], high = ys[ys.count - 1 - ys.count / 100]
            let reach = p.supportBand + p.contactMargin
            // Touching a surface means the object's own lowest (or highest)
            // points are over (or under) it, not merely at its height.
            func mostlyOver(_ s: HorizontalSurface, _ ends: [SIMD3<Float>]) -> Bool {
                ends.filter { s.covers($0, margin: p.planeMargin) }.count * 2 > ends.count
            }
            let bottom = points.filter { $0.y <= low + p.contactMargin }
            let top = points.filter { $0.y >= high - p.contactMargin }
            restsOn = below.filter { low >= $0.height && low - $0.height <= reach && mostlyOver($0, bottom) }
                .map(\.height).max()
            hangsFrom = above.filter { high <= $0.height && $0.height - high <= reach && mostlyOver($0, top) }
                .map(\.height).min()
        }
        var against: [VerticalSurface] = []
        for b in behind {
            let offsets = points.compactMap { b.wall.covers($0, margin: p.planeMargin) ? b.side * b.wall.distance($0) : nil }
            guard offsets.count * 2 > points.count else { continue }
            let nearest = offsets.sorted()[offsets.count / 100]
            if nearest - p.wallBand <= p.contactMargin { against.append(b.wall.facing(b.side)) }
        }
        depths.sort()
        return .lifted(LiftedPoints(points: points, maskPixels: maskPixels, medianDepth: depths[depths.count / 2],
                                    restsOn: restsOn, hangsFrom: hangsFrom, against: against))
    }

    /// The indices of the points that make one object: the points cut into
    /// pieces that touch — share or neighbour a `cell` — then the piece
    /// nearest the camera (least median `depths`) among those with at least
    /// `substantial` of the largest piece's points, and every other piece
    /// standing on it or hanging under it (most of its points over the chosen
    /// piece's footprint, like a chair's legs under its seat or a lamp's pole
    /// under its shade).
    ///
    /// A cell links its neighbours only when it holds at least two points off
    /// the `sheet` — the points just off a removed surface. A scatter of noise,
    /// or the sheet a plane placed a centimetre off leaves behind, joins a piece
    /// it touches but never joins two pieces together.
    static func connectedObject(_ points: [SIMD3<Float>], depths: [Float], sheet: [Bool], cell: Float,
                                substantial: Float) -> [Int] {
        precondition(sheet.count == points.count && depths.count == points.count)
        guard !points.isEmpty else { return [] }
        struct Key: Hashable { let x: Int32, y: Int32, z: Int32 }
        func key(_ p: SIMD3<Float>) -> Key {
            Key(x: Int32((p.x / cell).rounded(.down)), y: Int32((p.y / cell).rounded(.down)),
                z: Int32((p.z / cell).rounded(.down)))
        }
        var index: [Key: Int] = [:]
        var keys: [Key] = []
        var solid: [Int] = []
        var cellOf = [Int](repeating: 0, count: points.count)
        for (i, p) in points.enumerated() {
            let k = key(p)
            let c: Int
            if let existing = index[k] {
                c = existing
            } else {
                c = keys.count
                index[k] = c
                keys.append(k)
                solid.append(0)
            }
            cellOf[i] = c
            if !sheet[i] { solid[c] += 1 }
        }
        func neighbours(_ k: Key) -> [Int] {
            var out: [Int] = []
            for dz in Int32(-1)...1 {
                for dy in Int32(-1)...1 {
                    for dx in Int32(-1)...1 where dx != 0 || dy != 0 || dz != 0 {
                        if let n = index[Key(x: k.x + dx, y: k.y + dy, z: k.z + dz)] { out.append(n) }
                    }
                }
            }
            return out
        }
        var parent = Array(keys.indices)
        func find(_ a: Int) -> Int {
            var a = a
            while parent[a] != a {
                parent[a] = parent[parent[a]]
                a = parent[a]
            }
            return a
        }
        for c in keys.indices where solid[c] >= 2 {
            for n in neighbours(keys[c]) where solid[n] >= 2 {
                let a = find(c), b = find(n)
                if a != b { parent[a] = b }
            }
        }
        // A cell that cannot link joins one linking neighbour's piece, if any.
        for c in keys.indices where solid[c] < 2 {
            if let n = neighbours(keys[c]).first(where: { solid[$0] >= 2 }) { parent[c] = find(n) }
        }
        var size: [Int: Int] = [:]
        var pieceDepths: [Int: [Float]] = [:]
        for (i, c) in cellOf.enumerated() {
            let root = find(c)
            size[root, default: 0] += 1
            pieceDepths[root, default: []].append(depths[i])
        }
        guard let most = size.values.max() else { return [] }
        func median(_ root: Int) -> Float {
            let d = pieceDepths[root]!.sorted()
            return d[d.count / 2]
        }
        guard let largest = size.filter({ Float($0.value) >= substantial * Float(most) })
            .map({ (root: $0.key, depth: median($0.key)) })
            .min(by: { ($0.depth, $0.root) < ($1.depth, $1.root) })?.root else { return [] }
        struct Column: Hashable { let x: Int32, z: Int32 }
        var footprint = Set<Column>()
        for c in keys.indices where find(c) == largest {
            for dz in Int32(-1)...1 {
                for dx in Int32(-1)...1 { footprint.insert(Column(x: keys[c].x + dx, z: keys[c].z + dz)) }
            }
        }
        var over: [Int: Int] = [:]
        for c in cellOf {
            let root = find(c)
            if root != largest, footprint.contains(Column(x: keys[c].x, z: keys[c].z)) { over[root, default: 0] += 1 }
        }
        return points.indices.filter { i in
            let root = find(cellOf[i])
            return root == largest || (over[root] ?? 0) * 2 >= (size[root] ?? 0)
        }
    }

    /// Whether a pixel lies BEHIND a depth step: some 4-neighbour is nearer by
    /// more than the step limit. A silhouette's foreground pixel only has
    /// farther neighbours and is kept; a flying pixel, or the background just
    /// past an edge, has a nearer one and is not.
    static func isOnDepthEdge(x: Int, y: Int, depth d: Float, grid: DepthGrid,
                              parameters p: DepthLiftParameters) -> Bool {
        let limit = max(p.edgeStepAbsolute, p.edgeStepRelative * d)
        for (dx, dy) in [(1, 0), (-1, 0), (0, 1), (0, -1)] {
            let nx = x + dx, ny = y + dy
            guard nx >= 0, ny >= 0, nx < grid.width, ny < grid.height else { continue }
            let n = grid.depth(x: nx, y: ny)
            if DepthGrid.isMeasured(n), d - n > limit { return true }
        }
        return false
    }

    /// The depth range of the largest group, nearest first on a tie.
    static func dominantGroup(_ depths: [Float], parameters p: DepthLiftParameters) -> ClosedRange<Float> {
        let sorted = depths.sorted()
        var best = (start: 0, end: 0)
        var start = 0
        for i in 1...sorted.count {
            let splits = i == sorted.count
                || sorted[i] - sorted[i - 1] > max(p.groupGapAbsolute, p.groupGapRelative * sorted[i - 1])
            guard splits else { continue }
            if i - start > best.end - best.start { best = (start, i) }
            start = i
        }
        return sorted[best.start]...sorted[best.end - 1]
    }
}

#endif
