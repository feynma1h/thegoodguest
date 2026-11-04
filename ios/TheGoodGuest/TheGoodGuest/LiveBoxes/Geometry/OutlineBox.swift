/// Boxes for what LiDAR cannot see, from the detector's outlines and the
/// floor — DEBUG-only (decision 0295).
///
/// THROUGH GLASS, LIDAR MEASURES WHAT IS BEHIND. An all-glass coffee table's
/// outline measures only the floor under and beyond it, and a black glass top
/// measures nothing at all; neither leaves the lifter a point of the table.
/// But the detector still outlines the table, and a table stands on the
/// floor. So an object LiDAR sees through to the floor it stands on — or sees
/// nothing of, with the floor all round it (`FloorShare.seenThrough`) — is
/// boxed from its outlines instead: the box standing on the floor whose
/// silhouette, drawn into each view, best covers the outline seen there
/// without holding much more (`OutlineFit`). From one side, a deep low box and a shallow tall one can
/// draw the same silhouette; views from round the object tell them apart,
/// which is what the floor ring asks the person for. Depth decides only the
/// route: the floor is ARKit's plane and the outlines are the detector's, so
/// the fit itself needs no LiDAR.
///
/// AN OUTLINE IS JUDGED ONLY WHERE IT CAN SAY SOMETHING. A pixel another
/// object's detection claims — a chair pushed in at the table, a person
/// walking past — says nothing about where the table is not, and neither does
/// anything outside the frame; agreement is counted over the rest.
///
/// Read by: BoxFusion, DetectorPipeline, LiveBoxesOutlineTests.

#if DEBUG

import simd

// MARK: - The route

/// What the depth under and just round an outline says about the floor.
nonisolated struct FloorShare: Sendable, Equatable {
    /// The share of the depths measured under the outline that are the floor,
    /// or below it; nil when none was measured.
    let under: Float?
    /// The share of the depths measured in a ring just round the outline that
    /// are the floor; nil when none was measured.
    let around: Float?

    /// A measured depth is one the lifter would read (filters 1 and 2); the
    /// floor is its band and anything below it. The ring, 3 pixels wide, is
    /// read only when `around` asks for it: growing a mask costs more than
    /// reading it, and only an outline over no depth needs its surroundings.
    static func measure(mask: DepthMask, excluding excluded: DepthMask?, depth: DepthGrid, frame: SensorFrame,
                        floor: Float, around: Bool,
                        parameters p: DepthLiftParameters = DepthLiftParameters()) -> FloorShare {
        func isFloor(_ x: Int, _ y: Int) -> Bool? {
            let d = depth.depth(x: x, y: y)
            guard DepthGrid.isMeasured(d), d >= p.minimumDepth, d <= p.maximumDepth,
                  depth.confidence(x: x, y: y) >= p.minimumConfidence else { return nil }
            return frame.worldPoint(depthX: x, depthY: y, depth: d).y <= floor + p.supportBand
        }
        var under = (floor: 0, measured: 0), ring = (floor: 0, measured: 0)
        let region = around ? mask.dilated(by: 3, width: depth.width, height: depth.height) : mask
        for y in region.yRange {
            for x in region.xRange where region[x, y] && excluded?[x, y] != true {
                guard let onFloor = isFloor(x, y) else { continue }
                if mask[x, y] {
                    under.measured += 1
                    if onFloor { under.floor += 1 }
                } else {
                    ring.measured += 1
                    if onFloor { ring.floor += 1 }
                }
            }
        }
        return FloorShare(under: under.measured > 0 ? Float(under.floor) / Float(under.measured) : nil,
                          around: ring.measured > 0 ? Float(ring.floor) / Float(ring.measured) : nil)
    }

    /// Whether a detection is boxed from its outline: LiDAR saw through it
    /// to the floor — half of what was measured under it is the floor when
    /// the lifter kept nothing, three quarters when it kept something, so an
    /// open chair it did measure stays its own — or saw nothing of it, and
    /// the floor is all round it. A black screen on a wall has the wall round
    /// it; a vase on a table, the table.
    func seenThrough(_ attempt: LiftAttempt) -> Bool {
        switch attempt {
        case .lifted: return (under ?? 0) >= 0.75
        case .rejected(.onlySurfaces), .rejected(.tooLittleSeen): return (under ?? 0) >= 0.5
        case .rejected(.noDepth): return (around ?? 0) >= 0.2
        case .rejected(.tooFewPixels): return false
        }
    }
}

// MARK: - One view

/// One view of an object as its outline: which depth pixels the detector's
/// mask covers, which say something about the object at all, where the camera
/// was, and the height of the floor it stands on.
nonisolated struct OutlineView: Sendable {
    let frame: SensorFrame
    let floor: Float
    /// Pixels inside the outline, and pixels that say something about the
    /// object — inside it, or outside it and claimed by no other object — as
    /// row-major bits over the whole depth map, 64 to a word.
    private let inside: [UInt64]
    private let known: [UInt64]
    private let words: Int
    let insideCount: Int

    /// THE MASK'S EDGE SAYS LESS THAN ITS MIDDLE. The detector's mask is
    /// filled and grown, so it reaches a pixel or two past the object; scored
    /// as if it were the outline, that slack pays a box to be too big, because
    /// covering counts for more than filling (`coveringWeight`). So a rim this
    /// deep counts neither
    /// inside the outline nor against a silhouette that covers it — the same
    /// "says nothing" another object's pixels get. Measured on the synthetic
    /// green glass table seen end-on: the true box covered only 0.9395 of its
    /// own outline and scored 0.9510, under a box 93 cm too long at 0.9749;
    /// with the rim spared, the truth scores 1.0000 and that box 0.9724.
    static let edgeRim = 1
    /// The rim is thinned rather than allowed to eat a thin object: the
    /// deepest rim up to `edgeRim` leaving this share of the mask inside.
    static let minimumInsideShare: Float = 0.5

    /// `others` are the masks of every other object detected in the frame,
    /// people included: where they are, this outline cannot say it is not.
    init(mask: DepthMask, others: [DepthMask], frame: SensorFrame, floor: Float) {
        let w = frame.depthWidth, h = frame.depthHeight
        let words = (w + 63) / 64
        var inside = [UInt64](repeating: 0, count: words * h)
        var known = [UInt64](repeating: 0, count: words * h)
        for y in 0..<h {
            for x in 0..<w { known[y * words + x / 64] |= 1 << UInt64(x % 64) }
        }
        for other in others {
            for y in other.yRange where y >= 0 && y < h {
                for x in other.xRange where x >= 0 && x < w && other[x, y] && !mask[x, y] {
                    known[y * words + x / 64] &= ~(1 << UInt64(x % 64))
                }
            }
        }
        // How deep a rim the mask can spare, by its pixels' distance to its
        // own edge (`DepthMask.inset`: 1 on the edge, growing inward).
        let inset = mask.inset()
        let stride = mask.xRange.count
        func insetAt(_ x: Int, _ y: Int) -> Int {
            inset[(y - mask.yRange.lowerBound) * stride + (x - mask.xRange.lowerBound)]
        }
        let total = mask.count
        var rim = Self.edgeRim
        while rim > 0 {
            var kept = 0
            for y in mask.yRange {
                for x in mask.xRange where mask[x, y] && insetAt(x, y) > rim { kept += 1 }
            }
            if Float(kept) >= Self.minimumInsideShare * Float(total) { break }
            rim -= 1
        }
        var count = 0
        for y in mask.yRange where y >= 0 && y < h {
            for x in mask.xRange where x >= 0 && x < w && mask[x, y] {
                if insetAt(x, y) > rim {
                    inside[y * words + x / 64] |= 1 << UInt64(x % 64)
                    count += 1
                } else {
                    known[y * words + x / 64] &= ~(1 << UInt64(x % 64))
                }
            }
        }
        self.frame = frame
        self.floor = floor
        self.inside = inside
        self.known = known
        self.words = words
        insideCount = count
    }

    /// Inside and known pixels in row `y`, columns `x0` through `x1`.
    func count(row y: Int, from x0: Int, through x1: Int) -> (inside: Int, known: Int) {
        var i = 0, k = 0
        let base = y * words
        for word in (x0 / 64)...(x1 / 64) {
            var m = UInt64.max
            if word == x0 / 64 { m &= UInt64.max << UInt64(x0 % 64) }
            if word == x1 / 64, x1 % 64 != 63 { m &= (1 << UInt64(x1 % 64 + 1)) - 1 }
            i += (inside[base + word] & m).nonzeroBitCount
            k += (known[base + word] & m).nonzeroBitCount
        }
        return (i, k)
    }

    /// Whether a world point can belong to the object as this view sees it:
    /// inside the outline, or where the view cannot say.
    func admits(_ p: SIMD3<Float>) -> Bool {
        guard let projection = frame.depthProjection(world: p) else { return true }
        let q = projection.point
        guard q.x >= 0, q.y >= 0, q.x < Float(frame.depthWidth), q.y < Float(frame.depthHeight) else { return true }
        let x = Int(q.x), y = Int(q.y)
        let bit = UInt64(1) << UInt64(x % 64), at = y * words + x / 64
        return inside[at] & bit != 0 || known[at] & bit == 0
    }

    /// Every `step`-th pixel inside the outline.
    func insidePixels(step: Int) -> [(x: Int, y: Int)] {
        var out: [(x: Int, y: Int)] = []
        var n = 0
        for y in 0..<frame.depthHeight {
            for word in 0..<words where inside[y * words + word] != 0 {
                var bits = inside[y * words + word]
                while bits != 0 {
                    let b = bits.trailingZeroBitCount
                    if n % step == 0 { out.append((x: word * 64 + b, y: y)) }
                    n += 1
                    bits &= bits - 1
                }
            }
        }
        return out
    }
}

// MARK: - The fit

nonisolated enum OutlineFit {
    /// HOW MUCH MORE COVERING THE OUTLINE COUNTS THAN FILLING THE SILHOUETTE
    /// (`Agreement.score`). 0299 set this to 4, against a mask whose bleeding
    /// edge was still scored; sparing that rim (`OutlineView.edgeRim`) took
    /// away an accidental outward pull the 4 had been leaning on, and the
    /// weight then had to carry the inward one alone. Measured through the
    /// walks, worst extent error in centimetres:
    ///
    ///     weight    4      5      6      8     10
    ///     coffee end-on       40.9   14.9   14.9    8.9    8.9
    ///     coffee end-to-end    1.3    1.3    1.3    2.9    2.9
    ///     coffee round         2.2    2.0    2.0    2.2    2.2
    ///     coffee one side      1.6    2.6    2.6    2.6    3.6
    ///     pedestal dining      7.1    3.9    3.4    3.3    2.3
    ///
    /// The two cases 0299 traded against each other do NOT trade here: the
    /// pedestal table's inward pull and the glass table's outward one both
    /// ease as the weight rises, because the long flat slab's whole advantage
    /// was how well it FILLED its own silhouette — weight that less and it
    /// loses. 8 is where every case seen from more than one side sits within
    /// 3.3 cm and the single end-on view is at its best.
    static let coveringWeight: Float = 8
    /// A fit scoring less than this with its outlines, or less than half of
    /// whose silhouette its outlines fill, is no box standing on the floor:
    /// an outline off the floor, or views that disagree.
    static let minimumScore: Float = 0.7
    static let minimumFilled: Float = 0.5

    /// How a box's silhouette in a view and the view's outline agree, over
    /// the pixels the view knows.
    struct Agreement: Equatable, Sendable {
        /// The share of the outline the silhouette covers.
        var covered: Float
        /// The share of the silhouette the outline fills.
        var filled: Float

        /// A box holds its object, so all of the outline belongs inside its
        /// silhouette; but the silhouette also holds what an outline may
        /// leave out — the space under a table top, round a pedestal — so
        /// covering the outline counts `coveringWeight` times filling the
        /// silhouette: their F-beta score with beta² of that. Scored as their
        /// intersection over their union, a pedestal table's box came out
        /// 94 cm wide for 120.
        var score: Float {
            let w = OutlineFit.coveringWeight
            let d = w * filled + covered
            return d > 0 ? (1 + w) * filled * covered / d : 0
        }
    }

    /// The pixel span of each depth-map row a box's silhouette covers — the
    /// pixels whose centres fall inside the hull of its projected corners —
    /// or nil when any corner is behind the camera.
    static func silhouette(_ box: GravityBox, frame: SensorFrame) -> [(y: Int, x0: Int, x1: Int)]? {
        var corners: [SIMD2<Float>] = []
        for corner in box.corners {
            guard let p = frame.depthProjection(world: corner) else { return nil }
            corners.append(p.point)
        }
        let hull = GravityBoxMath.convexHull(corners)
        guard hull.count >= 3 else { return [] }
        let top = hull.map(\.y).min()!, bottom = hull.map(\.y).max()!
        let h = Float(frame.depthHeight), w = Float(frame.depthWidth)
        let y0 = Int(min(max(top - 0.5, 0), h).rounded(.up))
        let y1 = Int(max(min(bottom - 0.5, h - 1), -1).rounded(.down))
        guard y0 <= y1 else { return [] }
        var spans: [(y: Int, x0: Int, x1: Int)] = []
        for y in y0...y1 {
            let yc = Float(y) + 0.5
            var left = Float.greatestFiniteMagnitude, right = -Float.greatestFiniteMagnitude
            for i in hull.indices {
                let p = hull[i], q = hull[(i + 1) % hull.count]
                guard (p.y <= yc && yc < q.y) || (q.y <= yc && yc < p.y) else { continue }
                let x = p.x + (yc - p.y) * (q.x - p.x) / (q.y - p.y)
                left = min(left, x)
                right = max(right, x)
            }
            guard left <= right else { continue }
            let x0 = Int(min(max(left - 0.5, 0), w).rounded(.up))
            let x1 = Int(max(min(right - 0.5, w - 1), -1).rounded(.down))
            if x0 <= x1 { spans.append((y: y, x0: x0, x1: x1)) }
        }
        return spans
    }

    /// How a box's silhouette and a view's outline agree. Nil when the box
    /// is not wholly in front of the camera, or the outline is empty.
    static func agreement(_ box: GravityBox, _ view: OutlineView) -> Agreement? {
        guard view.insideCount > 0, let spans = silhouette(box, frame: view.frame) else { return nil }
        var both = 0, drawn = 0
        for span in spans {
            let c = view.count(row: span.y, from: span.x0, through: span.x1)
            both += c.inside
            drawn += c.known
        }
        return Agreement(covered: Float(both) / Float(view.insideCount),
                         filled: drawn > 0 ? Float(both) / Float(drawn) : 0)
    }

    /// The mean score and the mean filled share over the views; one that
    /// cannot judge the box counts as no agreement at all.
    static func agreement(_ box: GravityBox, _ views: [OutlineView]) -> (score: Float, filled: Float) {
        guard !views.isEmpty else { return (0, 0) }
        var score: Float = 0, filled: Float = 0
        for view in views {
            guard let a = agreement(box, view) else { continue }
            score += a.score
            filled += a.filled
        }
        return (score / Float(views.count), filled / Float(views.count))
    }

    /// Whether a frame looks at a box: every corner in front of the camera
    /// within `range`, and at least six of them inside the frame.
    static func inView(_ box: GravityBox, frame: SensorFrame, range: Float = 5) -> Bool {
        var inFrame = 0
        for corner in box.corners {
            guard let p = frame.depthProjection(world: corner), p.depth <= range else { return false }
            if p.point.x >= 0, p.point.y >= 0, p.point.x < Float(frame.depthWidth),
               p.point.y < Float(frame.depthHeight) { inFrame += 1 }
        }
        return inFrame >= 6
    }

    /// A box standing on the floor, turned by `yaw`, spanning `a` along its
    /// local X and `b` along its local Z, `height` tall.
    private struct Shape {
        var yaw: Float
        var a: SIMD2<Float>
        var b: SIMD2<Float>
        var height: Float

        var axes: (u: SIMD2<Float>, v: SIMD2<Float>) { (SIMD2(cos(yaw), -sin(yaw)), SIMD2(sin(yaw), cos(yaw))) }

        func box(floor: Float) -> GravityBox {
            let (u, v) = axes
            let c = u * ((a.x + a.y) / 2) + v * ((b.x + b.y) / 2)
            return GravityBox(center: SIMD3(c.x, floor + height / 2, c.y), size: SIMD3(a.y - a.x, height, b.y - b.x),
                              yaw: yaw)
        }

        /// A box's footprint along these axes, and its height over the floor.
        init(_ box: GravityBox, yaw: Float, floor: Float) {
            self.yaw = yaw
            let u = SIMD2(cos(yaw), -sin(yaw)), v = SIMD2(sin(yaw), cos(yaw))
            let along = box.footprint.map { simd_dot($0, u) }, across = box.footprint.map { simd_dot($0, v) }
            a = SIMD2(along.min()!, along.max()!)
            b = SIMD2(across.min()!, across.max()!)
            height = max(box.maxY - floor, 0.04)
        }

        init(yaw: Float, a: SIMD2<Float>, b: SIMD2<Float>, height: Float) {
            self.yaw = yaw
            self.a = a
            self.b = b
            self.height = height
        }
    }

    /// A fit from the box a track already has that scores this well is not
    /// fitted again from the floor hull, which costs most of the time.
    static let settledScore: Float = 0.9

    /// Heights the fresh fit is seeded from, over the floor under the
    /// outlines. ONE SIDE CANNOT TELL A DEEP LOW BOX FROM A SHALLOW TALL ONE
    /// (0299) — and the two are separate local maxima, which is the whole
    /// reason this ladder exists. The synthetic glass table seen end-on, whose
    /// truth is 118 × 46 cm, descends to 195 × 12 from a 12 cm seed and to
    /// 128 × 43 from a 70 cm one; the floor hull's own best height for its
    /// footprint is the 12 cm one, so before this the fit never tried the
    /// shape that wins. The score itself ranks them correctly (0.9886 against
    /// 0.9998), so the seeds only have to be offered.
    static let seedHeights: [Float] = [0.15, 0.3, 0.45, 0.7, 0.95]

    /// Seeds are compared at this step and only the best is refined to 1 cm:
    /// the fine steps are most of the cost, and a seed that is going to lose
    /// loses coarsely.
    static let coarseStep: Float = 0.04

    /// A seed must beat the fit already in hand by THIS MUCH to replace it.
    /// Where the outlines leave a side slack, two answers differ by less than
    /// this and the better one is not the truer one: at the 4× weight 0299
    /// set, the pedestal dining table among chairs scored 0.9477 at 113 cm
    /// wide against a true 120's 0.9419, because a taller narrower box draws
    /// nearly the same silhouette from a camera barely above its top. That
    /// coupling is what `coveringWeight` 8 answers (0300); this margin only
    /// keeps a seed from swapping one such answer for another. The glass table
    /// end-on gains 0.9886 → 0.9998, an order more, so the seed that matters
    /// is unaffected.
    static let seedMargin: Float = 0.002

    /// A side that can still move out this far without the fit scoring
    /// `slackTolerance` worse is not pinned by the outlines there.
    static let slackMargin: Float = 0.08
    static let slackTolerance: Float = 0.004


    /// The box standing on the views' floor that agrees best with their
    /// outlines: fitted from `start`, and — when there is none, when the
    /// views come from a direction they did not before (`fresh`), or when it
    /// ends scoring under `settledScore` — from the floor under every outline,
    /// whichever ends scoring more. One side of a table cannot tell a deep low
    /// box from a shallow tall one, so a box fitted from one side is no start
    /// for a fit from two. Square to `wallGrid` when the walls are known, as
    /// every other box is; otherwise turned to fit. Nil when the best scores
    /// under `minimumScore`, or is under `minimumFilled` filled.
    static func fit(_ views: [OutlineView], wallGrid: Float?, start: GravityBox? = nil,
                    fresh: Bool = true) -> GravityBox? {
        guard !views.isEmpty else { return nil }
        let floor = views.map(\.floor).sorted()[views.count / 2]
        let yaw = wallGrid.map { -$0 } ?? start?.yaw ?? 0
        var best = start.map { descend(Shape($0, yaw: yaw, floor: floor), views, floor: floor, turns: wallGrid == nil) }
        if fresh || (best?.score ?? 0) < settledScore, let hull = floorHull(views, yaw: yaw, floor: floor) {
            // The hull, coarsely. Its own footprint is a far better starting
            // shape than the raw hull, so the ladder is seeded from it — at
            // each of its heights, because at any one height it is only one
            // local maximum of several. Measured on the glass table end-on:
            // the hull descends to 195 × 12 at 0.9886, the same footprint
            // seeded at 70 cm to 128 × 42 at 0.9998. Every seed is COMPARED
            // coarsely and only the winner is refined: the fine steps are most
            // of the cost, and a seed that is going to lose loses coarsely.
            var coarse = descend(hull, views, floor: floor, turns: wallGrid == nil, until: coarseStep)
            let base = coarse.shape
            for height in seedHeights where abs(height - base.height) > coarseStep {
                var seed = base
                seed.height = height
                let got = descend(seed, views, floor: floor, turns: wallGrid == nil, until: coarseStep)
                if got.score > coarse.score + seedMargin { coarse = got }
            }
            let fitted = descend(coarse.shape, views, floor: floor, turns: wallGrid == nil)
            if best == nil || fitted.score > best!.score { best = fitted }
        }
        guard let best, best.score >= minimumScore else { return nil }
        let box = best.shape.box(floor: floor)
        return agreement(box, views).filled >= minimumFilled ? box : nil
    }

    /// WHETHER THE OUTLINES PIN THIS BOX: no side of its footprint can move
    /// outward by `slackMargin` and still score within `slackTolerance` of it.
    ///
    /// Along the direction a camera looks, the image says almost nothing: on
    /// the synthetic glass table a whole metre of extra length cost 0.007 of
    /// score where the same metre sideways cost 0.195. So a box from one end
    /// of a long table is not pinned along that length, however well it
    /// scores — which is why a seen-through track asks to be fitted afresh
    /// from all its outlines rather than nudged from where it is
    /// (`BoxFusion.refit`). Once the views round an object pin every side,
    /// the fresh fit — which costs most of the time — stops.
    static func pinned(_ box: GravityBox, _ views: [OutlineView]) -> Bool {
        guard !views.isEmpty else { return false }
        let floor = box.minY
        let base = agreement(box, views).score
        let shape = Shape(box, yaw: box.yaw, floor: floor)
        for k in 0..<4 {
            var t = shape
            switch k {
            case 0: t.a.x -= slackMargin
            case 1: t.a.y += slackMargin
            case 2: t.b.x -= slackMargin
            default: t.b.y += slackMargin
            }
            if agreement(t.box(floor: floor), views).score >= base - slackTolerance { return false }
        }
        return true
    }

    /// The floor under every outline — where rays through each outline's
    /// pixels meet the floor, kept where every view admits them — as extents
    /// along the box's axes, with the height that then agrees best. Nil when
    /// too little of the floor is left.
    private static func floorHull(_ views: [OutlineView], yaw: Float, floor: Float) -> Shape? {
        let u = SIMD2(cos(yaw), -sin(yaw)), v = SIMD2(sin(yaw), cos(yaw))
        var along: [Float] = [], across: [Float] = []
        for view in views {
            let camera = view.frame.cameraPosition
            for pixel in view.insidePixels(step: max(view.insideCount / 800, 1)) {
                let direction = view.frame.worldPoint(depthX: pixel.x, depthY: pixel.y, depth: 1) - camera
                guard direction.y < -1e-3 else { continue }
                let p = camera + direction * ((floor - camera.y) / direction.y)
                guard simd_length(SIMD2(p.x - camera.x, p.z - camera.z)) <= 6,
                      views.allSatisfy({ $0.admits(p) }) else { continue }
                along.append(simd_dot(SIMD2(p.x, p.z), u))
                across.append(simd_dot(SIMD2(p.x, p.z), v))
            }
        }
        guard along.count >= GravityBoxFit.minimumPoints else { return nil }
        along.sort()
        across.sort()
        let lo = along.count / 50, hi = along.count - 1 - along.count / 50
        var shape = Shape(yaw: yaw, a: SIMD2(along[lo], along[hi]), b: SIMD2(across[lo], across[hi]), height: 0.5)
        var best: (height: Float, score: Float) = (0.5, -1)
        for step in 1...50 {
            shape.height = Float(step) * 0.05
            let score = agreement(shape.box(floor: floor), views).score
            if score > best.score { best = (shape.height, score) }
        }
        shape.height = best.height
        return shape
    }

    /// Coordinate descent on the four sides, the height and — when `turns` —
    /// the turn about the box's own centre, in steps halving from 16 cm to 1 cm.
    private static func descend(_ start: Shape, _ views: [OutlineView], floor: Float,
                                turns: Bool, until finest: Float = 0.01) -> (shape: Shape, score: Float) {
        var shape = start
        var score = agreement(shape.box(floor: floor), views).score
        var step: Float = 0.16
        while step >= finest {
            var improved = true, sweeps = 0
            while improved && sweeps < 24 {
                improved = false
                sweeps += 1
                for k in 0..<(turns ? 6 : 5) {
                    for sign: Float in [1, -1] {
                        var t = shape
                        switch k {
                        case 0: t.a.x += sign * step
                        case 1: t.a.y += sign * step
                        case 2: t.b.x += sign * step
                        case 3: t.b.y += sign * step
                        case 4: t.height += sign * step
                        default:
                            // A turn of `step` radians about the box's centre.
                            let box = shape.box(floor: floor)
                            let c = SIMD2(box.center.x, box.center.z)
                            let ha = (shape.a.y - shape.a.x) / 2, hb = (shape.b.y - shape.b.x) / 2
                            t.yaw += sign * step
                            let (u, v) = t.axes
                            t.a = SIMD2(simd_dot(c, u) - ha, simd_dot(c, u) + ha)
                            t.b = SIMD2(simd_dot(c, v) - hb, simd_dot(c, v) + hb)
                        }
                        guard t.a.y - t.a.x >= 0.04, t.b.y - t.b.x >= 0.04, t.height >= 0.04, t.height <= 3
                        else { continue }
                        let candidate = agreement(t.box(floor: floor), views).score
                        if candidate > score + 1e-5 {
                            shape = t
                            score = candidate
                            improved = true
                        }
                    }
                }
            }
            step /= 2
        }
        return (shape, score)
    }
}

#endif
