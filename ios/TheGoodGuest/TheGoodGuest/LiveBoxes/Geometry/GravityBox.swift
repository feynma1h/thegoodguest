/// A gravity-aligned 3D box — upright, turned only about world +Y — and the fit
/// that makes one from an object's measured points. DEBUG-only (decision 0295).
///
/// UPRIGHT BY CONSTRUCTION, like RoomPlan's own boxes (0076 Q4). Furniture and
/// the long tail it is shown beside stand on floors and hang on walls, so the
/// only free rotation is yaw, and every extent is read from the object's own
/// points rather than from a prior about what a lamp should measure.
///
/// Yaw is right-handed about +Y, in radians, and CANONICAL in [0, π/2): a box
/// turned by a further quarter is the same box with its X and Z extents
/// swapped, so every box has exactly one representation and two fits of one
/// object compare by subtraction.
///
/// THE TURN IS THE ROOM'S UNLESS THE OBJECT CLEARLY SAYS OTHERWISE. With the
/// room's walls known, a box is square to them, as RoomPlan's boxes are. The
/// object's own direction turns it only when that direction is reliable and
/// more than 7° off the walls: its vertical faces agree strongly (any face
/// seen fixes a direction, which is what a partial view of a corner needs),
/// or, for a floor covering, its outline's minimum-area rectangle. On the
/// phone boxes re-guessed their turn from weak faces and partial outlines
/// every pass — a chair's by up to 45° — and every guess moved the box. A
/// track that has turned by its own faces keeps doing so a little past the
/// threshold, so it does not flip between the two. With no wall known, the
/// faces decide when they agree at all, and the outline otherwise.
///
/// Each extent is then a weighted trimmed range along those axes, so a stray
/// sample seen once cannot set a face that every view agrees on.
///
/// Read by: BoxFusion, RoomPlanMatch, SessionLog, LiveBoxesPresentation,
/// LiveBoxesARHost, LiveBoxesGeometryTests and LiveBoxesLiftingTests.

#if DEBUG

import simd

nonisolated struct GravityBox: Equatable, Sendable {
    /// Centre, world coordinates, metres.
    var center: SIMD3<Float>
    /// Extents along the box's local X, Y (height) and Z.
    var size: SIMD3<Float>
    /// Rotation about world +Y, radians, canonical in [0, π/2).
    var yaw: Float

    init(center: SIMD3<Float>, size: SIMD3<Float>, yaw: Float) {
        let quarter = Float.pi / 2
        let turns = (yaw / quarter).rounded(.down)
        var canonical = yaw - turns * quarter
        var s = size
        if canonical >= quarter { canonical -= quarter; s = SIMD3(s.z, s.y, s.x) }
        if Int(turns) & 1 != 0 { s = SIMD3(s.z, s.y, s.x) }
        self.center = center
        self.size = s
        self.yaw = max(0, canonical)
    }

    /// The local X axis on the floor plane, as (x, z).
    var planXAxis: SIMD2<Float> { SIMD2(cos(yaw), -sin(yaw)) }
    /// The local Z axis on the floor plane, as (x, z).
    var planZAxis: SIMD2<Float> { SIMD2(sin(yaw), cos(yaw)) }

    var volume: Float { size.x * size.y * size.z }

    var minY: Float { center.y - size.y / 2 }
    var maxY: Float { center.y + size.y / 2 }

    /// world_from_box: columns are the local axes, then the centre.
    var transform: simd_float4x4 {
        let c = cos(yaw), s = sin(yaw)
        return simd_float4x4(columns: (
            SIMD4(c, 0, -s, 0),
            SIMD4(0, 1, 0, 0),
            SIMD4(s, 0, c, 0),
            SIMD4(center, 1)))
    }

    /// The footprint's corners on the floor plane as (x, z), counter-clockwise
    /// in that (x, z) frame.
    var footprint: [SIMD2<Float>] {
        let c = SIMD2(center.x, center.z)
        let ax = planXAxis * (size.x / 2)
        let az = planZAxis * (size.z / 2)
        let quad = [c - ax - az, c + ax - az, c + ax + az, c - ax + az]
        return GravityBoxMath.signedArea(quad) >= 0 ? quad : quad.reversed()
    }

    /// The eight corners, bottom face first.
    var corners: [SIMD3<Float>] {
        footprint.map { SIMD3($0.x, minY, $0.y) } + footprint.map { SIMD3($0.x, maxY, $0.y) }
    }

    /// Whether `p` lies inside the box grown by `margin` on every side.
    func contains(_ p: SIMD3<Float>, margin: Float = 0) -> Bool {
        let d = SIMD2(p.x - center.x, p.z - center.z)
        return abs(simd_dot(d, planXAxis)) <= size.x / 2 + margin
            && abs(simd_dot(d, planZAxis)) <= size.z / 2 + margin
            && abs(p.y - center.y) <= size.y / 2 + margin
    }

    /// The volume two boxes share.
    func intersectionVolume(_ other: GravityBox) -> Float {
        let h = min(maxY, other.maxY) - max(minY, other.minY)
        guard h > 0 else { return 0 }
        return GravityBoxMath.convexIntersectionArea(footprint, other.footprint) * h
    }

    /// Intersection over union of the two volumes.
    func iou(_ other: GravityBox) -> Float {
        let i = intersectionVolume(other)
        let u = volume + other.volume - i
        return u > 1e-9 ? i / u : 0
    }

    /// The shared volume as a fraction of the SMALLER box — near 1 when one
    /// box sits inside the other, which IoU understates for a small box.
    func containment(_ other: GravityBox) -> Float {
        let m = min(volume, other.volume)
        return m > 1e-9 ? intersectionVolume(other) / m : 0
    }

    /// This box moved `fraction` of the way to `target`: the centre and the
    /// extents along straight lines, the turn the short way over the
    /// quarter-turn symmetry. Yaw is canonical in [0, π/2), so a box at 89°
    /// easing toward one at 1° turns two degrees, its X and Z extents read
    /// swapped, rather than spinning 88° back.
    func approaching(_ target: GravityBox, fraction f: Float) -> GravityBox {
        let quarter = Float.pi / 2
        let turns = ((target.yaw - yaw) / quarter).rounded()
        let size = Int(turns) & 1 == 0 ? target.size : SIMD3(target.size.z, target.size.y, target.size.x)
        let turn = target.yaw - turns * quarter - yaw
        return GravityBox(center: center + (target.center - center) * f,
                          size: self.size + (size - self.size) * f,
                          yaw: yaw + turn * f)
    }
}

// MARK: - The fit

nonisolated enum GravityBoxFit {

    /// Below this many points there is no box worth drawing.
    static let minimumPoints = 12

    /// With no wall known, the yaw comes from the object's faces when enough
    /// of its samples lie on faces and those faces agree; otherwise from the
    /// minimum-area rectangle.
    static let faceConsistency: Float = 0.5
    static let faceShare: Float = 0.1
    /// With the walls known, faces turn a box away from them only when they
    /// agree this well, cover this much of it, and point this far off the walls.
    static let turnedFaceConsistency: Float = 0.7
    static let turnedFaceShare: Float = 0.15
    static let snapDegrees: Float = 7
    /// How far below `turnedFaceConsistency` a track that has turned by its
    /// own faces keeps doing so.
    static let turnHysteresis: Float = 0.1

    /// The gravity-aligned box around `points`, or nil when there are too few.
    ///
    /// `weights` says how much each point counts — a voxel centroid carries
    /// the number of measurements that landed in it, so a face sampled from
    /// every view outweighs a stray sample seen once. `trim` is the fraction of
    /// that weight allowed beyond each face, applied separately along each
    /// axis once the yaw is chosen.
    ///
    /// `wallGrid` is the room's wall direction (`WallGrid.phi`), when any wall
    /// is known. `flat` marks a floor covering, whose outline is its only
    /// direction. `keepsTurn` says the track last turned by its own faces.
    static func fit(_ points: [SIMD3<Float>], weights: [Float]? = nil, trim: Float = 0.005,
                    wallGrid: Float? = nil, flat: Bool = false, keepsTurn: Bool = false) -> GravityBox? {
        guard points.count >= minimumPoints else { return nil }
        let w = weights ?? [Float](repeating: 1, count: points.count)
        precondition(w.count == points.count)

        // Height: a trimmed range of Y.
        let (y0, y1) = trimmedRange(points.map(\.y), weights: w, trim: trim)

        // Floor plane: drop radial outliers, then take the yaw from the
        // object's vertical faces, or failing those from the minimum-area
        // rectangle around the hull.
        let keep = inliers(points.map { SIMD2($0.x, $0.z) })
        guard keep.count >= 3 else { return nil }
        let plan = keep.map { SIMD2(points[$0].x, points[$0].z) }
        let planWeights = keep.map { w[$0] }
        let faces = faceDirection(plan, weights: planWeights)
        let phi: Float
        if let grid = wallGrid {
            var own: Float?
            if flat {
                own = minimumAreaDirection(GravityBoxMath.convexHull(plan))
            } else if let faces, faces.faceShare >= turnedFaceShare,
                      faces.consistency >= turnedFaceConsistency - (keepsTurn ? turnHysteresis : 0) {
                own = faces.phi
            }
            if let own, quarterDistance(own, grid) > snapDegrees * .pi / 180 {
                phi = own
            } else {
                phi = grid
            }
        } else if let faces, faces.consistency >= faceConsistency, faces.faceShare >= faceShare {
            phi = faces.phi
        } else {
            phi = minimumAreaDirection(GravityBoxMath.convexHull(plan))
        }
        let u = SIMD2(cos(phi), sin(phi))
        let v = SIMD2(-u.y, u.x)
        let (u0, u1) = trimmedRange(plan.map { simd_dot($0, u) }, weights: planWeights, trim: trim)
        let (v0, v1) = trimmedRange(plan.map { simd_dot($0, v) }, weights: planWeights, trim: trim)
        let mid = u * ((u0 + u1) / 2) + v * ((v0 + v1) / 2)

        // The rectangle's first axis is (cos φ, sin φ) in (x, z); a box's
        // local X on the plane is (cos ψ, −sin ψ), so ψ = −φ.
        return GravityBox(center: SIMD3(mid.x, (y0 + y1) / 2, mid.y),
                          size: SIMD3(u1 - u0, y1 - y0, v1 - v0),
                          yaw: -phi)
    }

    /// The box with its face nearest `wall` moved onto the wall — grown to it
    /// or pulled back out of it — when that face is square to the wall and
    /// within `reach` of it. `wall` faces the object. RoomPlan clips and aligns
    /// its boxes to nearby walls the same way; here the band that removes the
    /// wall's points also hid the object's own last centimetres against it.
    static func aligned(_ box: GravityBox, against wall: VerticalSurface, reach: Float) -> GravityBox {
        let square = cos(Float(3) * .pi / 180)
        let axes = [box.planXAxis, box.planZAxis]
        guard let k = axes.firstIndex(where: { abs(simd_dot($0, wall.normal)) >= square }) else { return box }
        let nearest = box.footprint.map { wall.distance(SIMD3($0.x, 0, $0.y)) }.min() ?? 0
        guard abs(nearest) <= reach else { return box }
        var size = box.size
        if k == 0 { size.x += nearest } else { size.z += nearest }
        guard size.x > 0.01, size.z > 0.01 else { return box }
        let shift = -wall.normal * (nearest / 2)
        return GravityBox(center: SIMD3(box.center.x + shift.x, box.center.y, box.center.z + shift.y),
                          size: size, yaw: box.yaw)
    }

    /// The range of a weighted sample with `trim` of the total weight
    /// excluded at each end.
    static func trimmedRange(_ values: [Float], weights: [Float], trim: Float) -> (Float, Float) {
        let order = values.indices.sorted { values[$0] < values[$1] }
        let cut = weights.reduce(0, +) * trim
        var low = values[order[0]], high = values[order[order.count - 1]]
        var total: Float = 0
        for i in order {
            total += weights[i]
            if total > cut { low = values[i]; break }
        }
        total = 0
        for i in order.reversed() {
            total += weights[i]
            if total > cut { high = values[i]; break }
        }
        return (low, max(low, high))
    }

    /// Indices of the points within a generous radius of the median centre:
    /// beyond the median distance plus four median absolute deviations (and
    /// never closer than 5 cm), a point is not the object.
    static func inliers(_ plan: [SIMD2<Float>]) -> [Int] {
        let mx = median(plan.map(\.x)), mz = median(plan.map(\.y))
        let c = SIMD2(mx, mz)
        let d = plan.map { simd_distance($0, c) }
        let md = median(d)
        let mad = median(d.map { abs($0 - md) })
        let limit = max(md + 4 * mad, md + 0.05)
        return d.indices.filter { d[$0] <= limit }
    }

    /// The direction φ in [0, π/2) the object's vertical faces run in; how
    /// consistently its line-like neighbourhoods point that way (0 random,
    /// 1 exactly); and what share of its samples are line-like at all.
    ///
    /// On the floor plane a vertical face is a LINE of samples and a top or a
    /// blob is an area. Each 2 cm column's neighbourhood within `radius` cells
    /// gives a local direction and how line-like it is; directions are pooled
    /// as 4θ, so the two perpendicular face families of a box reinforce one
    /// another instead of cancelling — the same device as the floor plan's
    /// grid heading.
    static func faceDirection(_ plan: [SIMD2<Float>], weights: [Float],
                              cell: Float = 0.02, radius: Int = 3)
        -> (phi: Float, consistency: Float, faceShare: Float)? {
        struct Column { var sum: SIMD2<Float>; var weight: Float }
        struct Key: Hashable { let i: Int32; let k: Int32 }
        var columns: [Key: Column] = [:]
        for (p, w) in zip(plan, weights) {
            let key = Key(i: Int32((p.x / cell).rounded(.down)), k: Int32((p.y / cell).rounded(.down)))
            columns[key, default: Column(sum: .zero, weight: 0)].sum += p * w
            columns[key, default: Column(sum: .zero, weight: 0)].weight += w
        }
        guard columns.count >= 6 else { return nil }
        var c4: Float = 0, s4: Float = 0, faceWeight: Float = 0, total: Float = 0
        for (key, column) in columns {
            var n: Float = 0
            var mean = SIMD2<Float>.zero
            var neighbours: [(SIMD2<Float>, Float)] = []
            for di in -radius...radius {
                for dk in -radius...radius {
                    guard let other = columns[Key(i: key.i + Int32(di), k: key.k + Int32(dk))] else { continue }
                    let centroid = other.sum / other.weight
                    neighbours.append((centroid, other.weight))
                    mean += centroid * other.weight
                    n += other.weight
                }
            }
            guard neighbours.count >= 3, n > 0 else { continue }
            mean /= n
            var sxx: Float = 0, szz: Float = 0, sxz: Float = 0
            for (q, w) in neighbours {
                let d = q - mean
                sxx += w * d.x * d.x; szz += w * d.y * d.y; sxz += w * d.x * d.y
            }
            let trace = sxx + szz
            guard trace > 1e-9 else { continue }
            let lineness = sqrt((sxx - szz) * (sxx - szz) + 4 * sxz * sxz) / trace
            let theta = 0.5 * atan2(2 * sxz, sxx - szz)
            // A face's neighbourhood is almost exactly a line; a corner's is an
            // L whose principal axis leans toward the longer arm. The fourth
            // power keeps faces and all but silences corners and blobs.
            let l2 = lineness * lineness
            let weight = l2 * l2 * column.weight
            c4 += weight * cos(4 * theta)
            s4 += weight * sin(4 * theta)
            faceWeight += weight
            total += column.weight
        }
        guard total > 0, faceWeight > 0 else { return nil }
        return (phi: quarterWrap(atan2(s4, c4) / 4),
                consistency: sqrt(c4 * c4 + s4 * s4) / faceWeight,
                faceShare: faceWeight / total)
    }

    private static func median(_ values: [Float]) -> Float {
        let s = values.sorted()
        return s.isEmpty ? 0 : s[s.count / 2]
    }

    /// The direction φ in [0, π/2) of the minimum-area enclosing rectangle —
    /// one side of which is always collinear with a hull edge.
    static func minimumAreaDirection(_ hull: [SIMD2<Float>]) -> Float {
        guard hull.count >= 3 else {
            guard hull.count == 2 else { return 0 }
            let d = hull[1] - hull[0]
            return quarterWrap(atan2(d.y, d.x))
        }
        var bestArea = Float.greatestFiniteMagnitude
        var bestPhi: Float = 0
        for i in hull.indices {
            let d = hull[(i + 1) % hull.count] - hull[i]
            guard simd_length(d) > 1e-6 else { continue }
            let phi = quarterWrap(atan2(d.y, d.x))
            let u = SIMD2(cos(phi), sin(phi))
            let v = SIMD2(-u.y, u.x)
            var u0 = Float.greatestFiniteMagnitude, u1 = -Float.greatestFiniteMagnitude
            var v0 = Float.greatestFiniteMagnitude, v1 = -Float.greatestFiniteMagnitude
            for p in hull {
                let a = simd_dot(p, u), b = simd_dot(p, v)
                u0 = min(u0, a); u1 = max(u1, a)
                v0 = min(v0, b); v1 = max(v1, b)
            }
            let area = (u1 - u0) * (v1 - v0)
            if area < bestArea { bestArea = area; bestPhi = phi }
        }
        return bestPhi
    }

    /// How far apart two plan directions are over the quarter-turn symmetry,
    /// radians in [0, π/4].
    static func quarterDistance(_ a: Float, _ b: Float) -> Float {
        let q = Float.pi / 2
        let d = abs(a - b).truncatingRemainder(dividingBy: q)
        return min(d, q - d)
    }

    /// Whether `box` is turned away from `wallGrid` rather than square to it.
    static func isTurned(_ box: GravityBox, from wallGrid: Float?) -> Bool {
        guard let wallGrid else { return false }
        return quarterDistance(-box.yaw, wallGrid) > 1e-4
    }

    private static func quarterWrap(_ angle: Float) -> Float {
        let q = Float.pi / 2
        let r = angle - (angle / q).rounded(.down) * q
        return r >= q ? r - q : r
    }
}

// MARK: - Plane geometry

nonisolated enum GravityBoxMath {

    /// Signed area; positive when the polygon runs counter-clockwise.
    static func signedArea(_ poly: [SIMD2<Float>]) -> Float {
        guard poly.count >= 3 else { return 0 }
        var a: Float = 0
        for i in poly.indices {
            let p = poly[i], q = poly[(i + 1) % poly.count]
            a += p.x * q.y - q.x * p.y
        }
        return a / 2
    }

    /// Andrew's monotone chain; counter-clockwise, no repeated endpoint.
    static func convexHull(_ points: [SIMD2<Float>]) -> [SIMD2<Float>] {
        let pts = points.sorted { $0.x < $1.x || ($0.x == $1.x && $0.y < $1.y) }
        guard pts.count >= 3 else { return pts }
        func cross(_ o: SIMD2<Float>, _ a: SIMD2<Float>, _ b: SIMD2<Float>) -> Float {
            (a.x - o.x) * (b.y - o.y) - (a.y - o.y) * (b.x - o.x)
        }
        var lower: [SIMD2<Float>] = []
        for p in pts {
            while lower.count >= 2, cross(lower[lower.count - 2], lower[lower.count - 1], p) <= 0 {
                lower.removeLast()
            }
            lower.append(p)
        }
        var upper: [SIMD2<Float>] = []
        for p in pts.reversed() {
            while upper.count >= 2, cross(upper[upper.count - 2], upper[upper.count - 1], p) <= 0 {
                upper.removeLast()
            }
            upper.append(p)
        }
        return Array(lower.dropLast() + upper.dropLast())
    }

    /// The area two convex counter-clockwise polygons share (Sutherland–Hodgman).
    static func convexIntersectionArea(_ subject: [SIMD2<Float>], _ clip: [SIMD2<Float>]) -> Float {
        var output = subject
        for i in clip.indices {
            let a = clip[i], b = clip[(i + 1) % clip.count]
            let input = output
            output = []
            guard !input.isEmpty else { break }
            func inside(_ p: SIMD2<Float>) -> Bool {
                (b.x - a.x) * (p.y - a.y) - (b.y - a.y) * (p.x - a.x) >= 0
            }
            func crossing(_ p: SIMD2<Float>, _ q: SIMD2<Float>) -> SIMD2<Float> {
                let r = q - p, s = b - a
                let denom = r.x * s.y - r.y * s.x
                guard abs(denom) > 1e-12 else { return p }
                let t = ((a.x - p.x) * s.y - (a.y - p.y) * s.x) / denom
                return p + r * t
            }
            for j in input.indices {
                let p = input[j], q = input[(j + 1) % input.count]
                switch (inside(p), inside(q)) {
                case (true, true):   output.append(q)
                case (true, false):  output.append(crossing(p, q))
                case (false, true):  output.append(crossing(p, q)); output.append(q)
                case (false, false): break
                }
            }
        }
        return max(0, signedArea(output))
    }
}

#endif
