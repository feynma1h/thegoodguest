/// Many frames' observations of one object become one gravity-aligned box that
/// grows as the object is walked around — DEBUG-only (decision 0295).
///
/// A TRACK IS A SET OF SURFACE SAMPLES, NOT A RUNNING AVERAGE OF BOXES. Every
/// observation's points land in 2 cm voxels, and the track's box is refitted
/// from the voxels' centroids. So a box covers exactly the surfaces seen so far:
/// one view of a table is a table-top-and-front, three views are the table, and
/// nothing is extrapolated to the side nobody looked at.
///
/// EXCEPT WHAT LIDAR SEES THROUGH. An all-glass table leaves no surface
/// samples, only the floor through it; its sightings are its outlines
/// (`OutlineView`), and a track most of whose sightings were outlines is the
/// box standing on the floor that agrees best with them (`OutlineFit`). It is
/// joined by an outline its box agrees with in that outline's own view, and
/// missed when a frame looks at its box and does not detect it.
///
/// OTHER VIEWS VOTE ON EVERY VOXEL. When a frame looks at a track's voxel and
/// the depth there is visibly FURTHER than the voxel, the camera saw straight
/// through where the voxel claims a surface. When the frame detected the object
/// and the voxel's surface is visible, its pixel is either inside that
/// detection's mask or outside it. A voxel seen through more often than it was
/// supported, or seen outside the object more often than inside it, goes —
/// which is how mask bleed that one view caught, and anything that was moved,
/// stop shaping the box. Bleed lands on a different side of the silhouette in
/// every view; the object itself stays inside all of them.
///
/// A TRACK EARNS ITS PLACE. One sighting is tentative; a second confirms it. A
/// track the detector has only ever been unsure of needs to be seen again and
/// again at one place instead, and stays UNSURE until a sighting is sure. A
/// frame that looks straight at a track and does not detect it counts a miss,
/// and a track missed far more often than it is seen is removed. Tracks that
/// come to overlap are merged, and a track's label is whichever of its names
/// has accumulated the most detector score.
///
/// A BOX IS LOCKED WHEN THE PERSON FINISHES IT, AND THEN NEVER MOVES. Every
/// pass refits a track, so its box keeps shifting as points arrive and votes
/// take voxels away. Nothing here decides by itself that a fit is done: on the
/// phone a rule that did so locked a chair seen only from the front at half
/// its depth, and never locked the clock, the wall art or either sofa. The
/// person working on an object finishes it (`finish`) and the box they were
/// looking at is locked exactly as it was drawn; the fit carries on
/// underneath, for the log. A finished track is never removed, and never
/// merged with another finished one.
///
/// A TABLE IS A TABLE WHATEVER IT IS CALLED. The detector names one dining
/// table a kitchen table in one frame and an office desk in the next, and as two
/// labels its sightings split into tracks that each saw one end of it — 24, 23 and
/// 34 sightings in three boxes, none the table. The table names (`tableKinds`) join
/// and merge as one label.
///
/// A DIFFERENT NAME IS A DIFFERENT OBJECT UNTIL THE PIXELS SAY OTHERWISE. The
/// detector calls one shelf a bookshelf in one frame and a cabinet in the next,
/// so a detection may join a track of another label — but a cushion on a sofa
/// sits inside the sofa's box too. The difference is what the mask covers: a
/// detection of the same object covers the track wherever this frame sees it,
/// and a cushion's mask covers a corner of the sofa. So across labels a
/// detection joins only a track its mask covers, and two tracks merge only when
/// their BOXES agree — never because one sits inside the other, and never once
/// they have been detected side by side in one frame.
///
/// Read by: DetectorPipeline, LiveBoxesFusionTests and LiveBoxesLiftingTests.

#if DEBUG

import Foundation
import simd

// MARK: - Inputs

/// One detection of one object in one frame, already lifted — or, for an
/// object LiDAR sees through, outlined (`outline`).
nonisolated struct BoxObservation: Sendable {
    /// The detector's class name.
    let name: String
    /// The display label the vocabulary maps it to.
    let label: String
    /// RoomPlan's category token when the name is one of RoomPlan's own.
    let roomPlanCategory: String?
    let score: Float
    /// What LiDAR measured of it; none, when it saw only through it.
    let points: [SIMD3<Float>]
    /// The mask the points were lifted from, before filtering.
    let mask: DepthMask
    /// The object seen through to the floor it stands on, as its outline:
    /// its box is fitted to outlines, not to points (`OutlineFit`).
    let outline: OutlineView?
    /// The observation's own box — what association compares: fitted to
    /// the points, or to the outline alone.
    let box: GravityBox
    /// The surface height the lifter found it resting on, or hanging from.
    let restsOn: Float?
    let hangsFrom: Float?
    /// Walls the lifter found it standing against, each facing the object.
    let against: [VerticalSurface]
    /// The detection reached the edge of the camera image: part of an object.
    let touchesEdge: Bool
    /// The detection's outline covers the middle of the screen: the person is
    /// aiming at it. A tall cabinet up close is never seen whole, so a
    /// detection the frame cuts off starts a track only then.
    let aimedAt: Bool
    /// A floor covering, whose outline is its only direction.
    let flat: Bool

    /// An outline no box standing on the floor agrees with is dropped, and
    /// the points LiDAR did measure stand alone. Nil when there is no box at
    /// all: too few points, and no outline that fits.
    init?(name: String, label: String, roomPlanCategory: String?, score: Float,
          points: [SIMD3<Float>], mask: DepthMask, restsOn: Float? = nil, hangsFrom: Float? = nil,
          against: [VerticalSurface] = [], wallGrid: Float? = nil, touchesEdge: Bool = false,
          aimedAt: Bool = false, outline: OutlineView? = nil, flat: Bool = false) {
        var outline = outline
        var fitted = outline.flatMap { OutlineFit.fit([$0], wallGrid: wallGrid) }
        if fitted == nil {
            outline = nil
            fitted = GravityBoxFit.fit(points, wallGrid: wallGrid, flat: flat)
        }
        guard let fitted else { return nil }
        box = fitted
        self.name = name
        self.label = label
        self.roomPlanCategory = roomPlanCategory
        self.score = score
        self.points = points
        self.mask = mask
        self.outline = outline
        self.restsOn = restsOn
        self.hangsFrom = hangsFrom
        self.against = against
        self.flat = flat
        self.touchesEdge = touchesEdge
        self.aimedAt = aimedAt
    }
}

nonisolated struct FusionParameters: Sendable, Equatable, Codable {
    var voxelSize: Float = 0.02
    /// Same label: associate at or above any of these.
    var associationIoU: Float = 0.1
    var associationContainment: Float = 0.5
    var associationInside: Float = 0.3
    /// Different labels: only when the new points sit inside the track this much,
    var crossLabelInside: Float = 0.6
    /// and the new mask covers this much of the track where the frame sees it.
    var crossLabelCoverage: Float = 0.6
    /// An outline joins a track whose box, drawn into its view, agrees with
    /// it this much (`OutlineFit.Agreement.score`) — this much across labels.
    var outlineAssociation: Float = 0.5
    var crossLabelOutlineAssociation: Float = 0.7
    /// A voxel's own depth agrees with the frame within this, metres.
    var visibilityTolerance: Float = 0.05
    /// The frame measures this much further than the voxel: seen through it.
    var freeSpaceMargin: Float = 0.10
    /// How far above an agreed resting surface a box's bottom may sit and still
    /// be taken down to it: the lifter's band plus its contact margin, and a
    /// centimetre for the voxel grid.
    var contactReach: Float = 0.06
    var confirmingHits: Int = 2
    var tentativeMissLimit: Int = 3
    var confirmedMissLimit: Int = 8
    var confirmedMinimumHitRatio: Float = 0.25
    var mergeIoU: Float = 0.3
    var mergeContainment: Float = 0.6
    /// Different labels merge on agreeing boxes only, never on containment.
    var crossLabelMergeIoU: Float = 0.5
    var maximumVoxelsPerTrack: Int = 30_000
    /// A track none of whose points this frame can see casts no vote and
    /// takes no miss, so its voxels are not visited. Changes only the time;
    /// off exists to prove that.
    var skipsTracksOutOfView = true
    /// A track still under this on every side after `smallTrackHits`
    /// sightings is a fragment, not an object, and goes.
    var smallestObject: Float = 0.10
    var smallTrackHits = 5
    /// At most this many tracks; beyond it the stalest tentative ones go
    /// first, then the stalest confirmed ones. A cluttered room took the phone
    /// to 92 tracks in two minutes, and every one costs memory and time.
    var maximumTracks = 60
    /// A detection starts a new track only at this score, and only when the
    /// frame does not cut it off or the person is aiming at it; otherwise it
    /// can still add to a track that exists. The operator saw boxes grown from
    /// things barely in view; the pooja cabinet, tall and close, was then
    /// never seen whole at all. On the phone the weakest detections
    /// (0.38–0.54) were mostly wrong or doubled, the dining table called a
    /// desk at 0.44 among them.
    var startingScore: Float = 0.5
    /// From this score up to the starting score, a detection with no track to
    /// join starts an UNSURE track instead, where no track stands already —
    /// one confirmed only by `unsureConfirmingHits` sightings, seen again and
    /// again at one place. In the 00:45 walk the white glass-door cabinet was
    /// "file cabinet" 0.44, "cabinet" 0.34 and "shelf" 0.32 at one spot, and
    /// the dining table "kitchen table" at 0.41–0.48: neither ever had a dot.
    var unsureScore: Float = 0.3
    var unsureConfirmingHits: Int = 4
}

/// What became of one observation: it joined a track, started one, or did
/// neither — which the session log records, because a detection that becomes
/// no track never becomes a dot.
nonisolated enum Sighting: Sendable, Equatable {
    case joined(UUID)
    case started(UUID)
    /// No track to join, and under the unsure score — or under the starting
    /// score where a track already stands.
    case tooUnsure
    /// No track to join, and cut off by the frame without being aimed at.
    case cutOff
}

/// The box the screen draws for a track, fixed when the person finished it.
nonisolated struct LockedBox: Sendable, Equatable {
    let box: GravityBox
    /// When it was finished, on the ARFrame clock.
    let time: Double
    /// What the track had to show for itself then.
    let hits: Int
    let arcDegrees: Int
    let bestScore: Float
}

// MARK: - Tracks

/// How far a track's fit moved between passes. Every pass refits a track from
/// its voxels, so a box that is not changing still wanders: this is by how
/// much, which is what a finished box keeps off the screen.
nonisolated struct TrackMovement: Sendable, Equatable, Codable {
    var refits = 0
    var centreMeanCm: Float = 0
    var centreMaxCm: Float = 0
    var yawMeanDegrees: Float = 0
    var yawMaxDegrees: Float = 0

    fileprivate mutating func note(centreMetres: Float, yawRadians: Float) {
        let centre = centreMetres * 100, yaw = abs(yawRadians) * 180 / .pi
        centreMeanCm = (centreMeanCm * Float(refits) + centre) / Float(refits + 1)
        yawMeanDegrees = (yawMeanDegrees * Float(refits) + yaw) / Float(refits + 1)
        centreMaxCm = max(centreMaxCm, centre)
        yawMaxDegrees = max(yawMaxDegrees, yaw)
        refits += 1
    }

    fileprivate mutating func absorb(_ other: TrackMovement) {
        guard other.refits > 0 else { return }
        let total = Float(refits + other.refits)
        centreMeanCm = (centreMeanCm * Float(refits) + other.centreMeanCm * Float(other.refits)) / total
        yawMeanDegrees = (yawMeanDegrees * Float(refits) + other.yawMeanDegrees * Float(other.refits)) / total
        centreMaxCm = max(centreMaxCm, other.centreMaxCm)
        yawMaxDegrees = max(yawMaxDegrees, other.yawMaxDegrees)
        refits += other.refits
    }
}

nonisolated struct VoxelKey: Hashable, Sendable {
    let x: Int32, y: Int32, z: Int32

    init(_ p: SIMD3<Float>, size: Float) {
        x = Int32((p.x / size).rounded(.down))
        y = Int32((p.y / size).rounded(.down))
        z = Int32((p.z / size).rounded(.down))
    }
}

nonisolated struct Voxel: Sendable {
    var sum: SIMD3<Float>
    var points: Int
    /// Observations whose points landed here.
    var support: Int
    /// Views that detected the object and saw this voxel inside its mask.
    var inside: Int
    /// Views that detected the object and saw this voxel outside its mask.
    var outside: Int
    /// Views that measured clear space behind where this voxel claims a surface.
    var seenThrough: Int
    var lastObservation: Int

    var centroid: SIMD3<Float> { sum / Float(points) }

    /// More evidence against the voxel than for it.
    var isRefuted: Bool {
        (seenThrough >= 2 && seenThrough > support) || (inside + outside >= 3 && outside > inside)
    }
}

nonisolated struct BoxTrack: Sendable, Identifiable {
    let id: UUID
    private(set) var label: String
    private(set) var roomPlanCategory: String?
    /// Accumulated detector score per class name.
    private(set) var names: [String: Float]
    private(set) var bestScore: Float
    private(set) var hits: Int
    fileprivate(set) var misses: Int
    let firstSeen: Double
    private(set) var lastSeen: Double
    fileprivate(set) var box: GravityBox
    fileprivate(set) var voxels: [VoxelKey: Voxel]
    /// 10° bins of the directions this object has been seen from.
    private(set) var azimuthBins: Set<Int>
    /// How far this track's fit moved between passes.
    private(set) var movement = TrackMovement()
    private var labelScores: [String: Float]
    private var categoryByLabel: [String: String]
    /// Observations reporting contact with a surface, by height in whole
    /// centimetres: how many, and the summed height.
    private var restVotes: [Int: (count: Int, sum: Float)]
    private var hangVotes: [Int: (count: Int, sum: Float)]
    /// Walls observations reported it standing against, and how many did.
    private var wallVotes: [(wall: VerticalSurface, count: Int)]
    /// Tracks detected in the same frame as this one: other objects, whatever
    /// their boxes come to look like.
    fileprivate(set) var distinct: Set<UUID>
    private let confirmingHits: Int
    private let unsureConfirmingHits: Int
    private let startingScore: Float
    /// The smallest axis-aligned box around every point this track absorbed.
    /// It never shrinks when voxels go, so every voxel centroid lies inside it.
    fileprivate(set) var pointBounds: (lo: SIMD3<Float>, hi: SIMD3<Float>)
    /// A floor covering, whose outline is its only direction.
    private let flat: Bool
    /// The last refit turned the box by the object's own faces, away from the walls.
    private var turned = false
    /// The box the screen draws, once the person has finished it. Never changes after.
    fileprivate(set) var locked: LockedBox?
    /// For an object LiDAR sees through: the latest outline from each 10°
    /// direction it was seen from (`directionBin`), at most
    /// `maximumOutlines` of them; how many sightings were outlines; and
    /// whether a direction was added since the box was last fitted to them.
    fileprivate(set) var outlines: [Int: OutlineView] = [:]
    private var outlineSightings = 0
    private var outlinesFromNewDirection = false
    /// Whether the outlines kept pin the box's footprint on every side
    /// (`OutlineFit.pinned`). While they do not, the box is derived afresh
    /// from all of them each pass instead of being nudged from where it is:
    /// a high score does NOT mean a settled box, because the score is
    /// blindest along the direction the camera is looking. False until a fit
    /// says otherwise.
    private(set) var outlinesPinned = false
    /// Passes since the box was last derived afresh from all the outlines.
    private var passesSinceFreshFit = 0
    /// HOW OFTEN AN UNPINNED BOX IS RE-DERIVED WHILE NOTHING NEW ARRIVES.
    /// The fresh fit costs most of the time in this route, and standing still
    /// re-derives it from the same outlines for the same answer. A direction
    /// the track has not seen before always forces a fresh fit whatever this
    /// says, so what the cap skips is only repetition. Measured through the
    /// walks, worst extent error with the cap at 1 (every pass) through 8:
    /// end to end dwelling 1.5 cm, all the way round 2.2, the pedestal dining
    /// table 3.3 — the same at every setting — while dwelling at one end fell
    /// from 467 ms to 100 ms. Standing at one end is the only case that moves
    /// at all, and it IMPROVES (8.6 cm to 4.7-6.9). 4 is where the saving
    /// flattens, and it matches the 2-to-4 views convergence takes.
    static let freshRefitEveryNthPass = 4
    /// A fit reads every outline kept, so the evenest spread of this many is kept.
    static let maximumOutlines = 8

    /// Most sightings saw through it, so its box is fitted to their outlines.
    var isSeenThrough: Bool { !outlines.isEmpty && outlineSightings * 2 > hits }
    /// No sighting of it has reached the starting score.
    var isUnsure: Bool { bestScore < startingScore }
    var isConfirmed: Bool { hits >= (isUnsure ? unsureConfirmingHits : confirmingHits) }
    /// How much of the way around the object it has been seen from.
    var observedArcDegrees: Int { azimuthBins.count * 10 }
    var hitRatio: Float { Float(hits) / Float(max(hits + misses, 1)) }

    fileprivate init(observation o: BoxObservation, stamp: Int, time: Double,
                     camera: SIMD3<Float>, parameters p: FusionParameters) {
        id = UUID()
        confirmingHits = p.confirmingHits
        unsureConfirmingHits = p.unsureConfirmingHits
        startingScore = p.startingScore
        let voxelSize = p.voxelSize
        flat = o.flat
        distinct = []
        pointBounds = (SIMD3(repeating: .greatestFiniteMagnitude), SIMD3(repeating: -.greatestFiniteMagnitude))
        label = o.label
        roomPlanCategory = o.roomPlanCategory
        names = [:]
        bestScore = 0
        hits = 0
        misses = 0
        firstSeen = time
        lastSeen = time
        box = o.box
        voxels = [:]
        azimuthBins = []
        labelScores = [:]
        categoryByLabel = [:]
        restVotes = [:]
        hangVotes = [:]
        wallVotes = []
        absorb(o, stamp: stamp, time: time, camera: camera, voxelSize: voxelSize, cap: .max)
    }

    fileprivate mutating func absorb(_ o: BoxObservation, stamp: Int, time: Double,
                                     camera: SIMD3<Float>, voxelSize: Float, cap: Int) {
        for p in o.points {
            pointBounds.lo = simd_min(pointBounds.lo, p)
            pointBounds.hi = simd_max(pointBounds.hi, p)
            let key = VoxelKey(p, size: voxelSize)
            if var v = voxels[key] {
                v.sum += p
                v.points += 1
                if v.lastObservation != stamp { v.support += 1; v.lastObservation = stamp }
                voxels[key] = v
            } else if voxels.count < cap {
                voxels[key] = Voxel(sum: p, points: 1, support: 1, inside: 0, outside: 0,
                                    seenThrough: 0, lastObservation: stamp)
            }
        }
        names[o.name, default: 0] += o.score
        labelScores[o.label, default: 0] += o.score
        if let category = o.roomPlanCategory { categoryByLabel[o.label] = category }
        label = labelScores.max { $0.value < $1.value }?.key ?? o.label
        roomPlanCategory = categoryByLabel[label]
        bestScore = max(bestScore, o.score)
        hits += 1
        lastSeen = max(lastSeen, time)
        if let h = o.restsOn { Self.vote(&restVotes, h) }
        if let h = o.hangsFrom { Self.vote(&hangVotes, h) }
        for wall in o.against { Self.vote(&wallVotes, wall, count: 1) }
        let bin = Self.directionBin(camera: camera, around: box.center)
        azimuthBins.insert(bin)
        if let outline = o.outline {
            if outlines[bin] == nil { outlinesFromNewDirection = true }
            outlines[bin] = outline
            outlineSightings += 1
            thinOutlines()
        }
    }

    /// Down to `maximumOutlines`, dropping each time one of the two closest
    /// directions: the views left are as spread round the object as they can be.
    private mutating func thinOutlines() {
        while outlines.count > Self.maximumOutlines {
            let bins = outlines.keys.sorted()
            var closest = (bin: bins[0], gap: Int.max)
            for (k, b) in bins.enumerated() {
                let next = bins[(k + 1) % bins.count]
                let gap = (next - b + 36) % 36
                if gap < closest.gap { closest = (next, gap) }
            }
            outlines[closest.bin] = nil
        }
    }

    /// The 10° bin, 0 to 35, of the direction from `centre` toward `camera`
    /// on the floor plane: bin k holds the angles atan2(z, x) from −180° + 10k.
    static func directionBin(camera: SIMD3<Float>, around centre: SIMD3<Float>) -> Int {
        let angle = atan2(camera.z - centre.z, camera.x - centre.x) * 180 / .pi
        return Int(((angle + 180) / 10).rounded(.down)) % 36
    }

    fileprivate mutating func merge(_ other: BoxTrack) {
        for (key, v) in other.voxels {
            if var mine = voxels[key] {
                mine.sum += v.sum
                mine.points += v.points
                mine.support += v.support
                mine.inside += v.inside
                mine.outside += v.outside
                mine.seenThrough += v.seenThrough
                voxels[key] = mine
            } else {
                voxels[key] = v
            }
        }
        for (n, s) in other.names { names[n, default: 0] += s }
        for (l, s) in other.labelScores { labelScores[l, default: 0] += s }
        for (l, c) in other.categoryByLabel { categoryByLabel[l] = c }
        label = labelScores.max { $0.value < $1.value }?.key ?? label
        roomPlanCategory = categoryByLabel[label]
        bestScore = max(bestScore, other.bestScore)
        hits += other.hits
        misses += other.misses
        lastSeen = max(lastSeen, other.lastSeen)
        azimuthBins.formUnion(other.azimuthBins)
        movement.absorb(other.movement)
        distinct.formUnion(other.distinct)
        distinct.subtract([id, other.id])
        pointBounds = (simd_min(pointBounds.lo, other.pointBounds.lo), simd_max(pointBounds.hi, other.pointBounds.hi))
        for (k, v) in other.restVotes {
            restVotes[k, default: (0, 0)].count += v.count
            restVotes[k, default: (0, 0)].sum += v.sum
        }
        for (k, v) in other.hangVotes {
            hangVotes[k, default: (0, 0)].count += v.count
            hangVotes[k, default: (0, 0)].sum += v.sum
        }
        for v in other.wallVotes { Self.vote(&wallVotes, v.wall, count: v.count) }
        let before = Set(outlines.keys)
        outlines.merge(other.outlines) { mine, _ in mine }
        if Set(outlines.keys) != before { outlinesFromNewDirection = true }
        outlineSightings += other.outlineSightings
        thinOutlines()
    }

    /// One wall is the same wall again when it faces within 5° and stands within 3 cm:
    /// ARKit refines a plane as more of it is seen.
    private static func vote(_ votes: inout [(wall: VerticalSurface, count: Int)], _ wall: VerticalSurface, count: Int) {
        if let k = votes.firstIndex(where: {
            simd_dot($0.wall.normal, wall.normal) >= cos(Float(5) * .pi / 180) && abs($0.wall.offset - wall.offset) <= 0.03
        }) {
            votes[k].count += count
            votes[k].wall = wall
        } else {
            votes.append((wall, count))
        }
    }

    private static func vote(_ votes: inout [Int: (count: Int, sum: Float)], _ height: Float) {
        let key = Int((height * 100).rounded())
        votes[key, default: (0, 0)].count += 1
        votes[key, default: (0, 0)].sum += height
    }

    /// The surface most observations agreed on, when at least half did.
    private func agreedContact(_ votes: [Int: (count: Int, sum: Float)]) -> Float? {
        guard let best = votes.values.max(by: { $0.count < $1.count }), best.count * 2 >= hits
        else { return nil }
        return best.sum / Float(best.count)
    }

    /// The name that has earned the most score.
    var dominantName: String {
        names.max { $0.value < $1.value }?.key ?? ""
    }

    /// Refit from the voxels, then close the gap the supporting-surface band
    /// leaves: a box whose bottom sits just above the surface its observations
    /// agree it rests on reaches down to that surface (and likewise up to a
    /// ceiling it hangs from).
    /// `wallGrid` is the room's direction: the box is square to it unless the
    /// object's own direction is reliable and clearly turned (`GravityBoxFit`),
    /// so it lines up with the room, as RoomPlan's do, instead of re-guessing
    /// its turn every pass.
    /// A track seen through is fitted to its outlines instead, from the box it
    /// has — while they agree with some box standing on the floor.
    fileprivate mutating func refit(contactReach: Float, wallGrid: Float?) {
        if isSeenThrough {
            let views = outlines.sorted { $0.key < $1.key }.map { $0.value }
            passesSinceFreshFit += 1
            let fresh = outlinesFromNewDirection
                || (!outlinesPinned && passesSinceFreshFit >= Self.freshRefitEveryNthPass)
            if let fitted = OutlineFit.fit(views, wallGrid: wallGrid, start: box, fresh: fresh) {
                outlinesFromNewDirection = false
                if fresh { passesSinceFreshFit = 0 }
                outlinesPinned = OutlineFit.pinned(fitted, views)
                let quarter = Float.pi / 2
                let turned = fitted.yaw - box.yaw
                movement.note(centreMetres: simd_distance(fitted.center, box.center),
                              yawRadians: turned - (turned / quarter).rounded() * quarter)
                box = fitted
                return
            }
        }
        var centroids: [SIMD3<Float>] = []
        var weights: [Float] = []
        centroids.reserveCapacity(voxels.count)
        weights.reserveCapacity(voxels.count)
        for v in voxels.values {
            centroids.append(v.centroid)
            weights.append(Float(v.points))
        }
        guard var fitted = GravityBoxFit.fit(centroids, weights: weights, wallGrid: wallGrid, flat: flat,
                                             keepsTurn: turned) else { return }
        turned = GravityBoxFit.isTurned(fitted, from: wallGrid)
        var bottom = fitted.minY, top = fitted.maxY
        if let surface = agreedContact(restVotes), bottom >= surface, bottom - surface <= contactReach {
            bottom = surface
        }
        if let ceiling = agreedContact(hangVotes), top <= ceiling, ceiling - top <= contactReach {
            top = ceiling
        }
        if bottom != fitted.minY || top != fitted.maxY {
            fitted = GravityBox(center: SIMD3(fitted.center.x, (bottom + top) / 2, fitted.center.z),
                                size: SIMD3(fitted.size.x, top - bottom, fitted.size.z),
                                yaw: fitted.yaw)
        }
        // A view straight at the object's front cannot see where its back is,
        // so it is no evidence either way: two sightings that saw the object
        // reach the wall's band are enough, and the fused face must still be
        // within reach of the wall.
        for vote in wallVotes where vote.count >= 2 || vote.count * 2 >= hits {
            fitted = GravityBoxFit.aligned(fitted, against: vote.wall, reach: contactReach)
        }
        let quarter = Float.pi / 2
        let turned = fitted.yaw - box.yaw
        movement.note(centreMetres: simd_distance(fitted.center, box.center),
                      yawRadians: turned - (turned / quarter).rounded() * quarter)
        box = fitted
    }
}

// MARK: - Fusion

nonisolated struct BoxFusion: Sendable {
    /// Labels the detector uses for one kind of thing, so a track's sightings do not split by name.
    static let tableKinds: Set<String> = ["TABLE", "COFFEE TABLE", "SIDE TABLE", "DESK"]

    /// Whether two labels are one kind of thing for associating and merging.
    static func sameKind(_ a: String, _ b: String) -> Bool {
        a == b || (tableKinds.contains(a) && tableKinds.contains(b))
    }

    let parameters: FusionParameters
    private(set) var tracks: [BoxTrack] = []
    /// Which track each merged-away track went into, so a finish sent for one
    /// reaches the track that absorbed it.
    private(set) var mergedInto: [UUID: UUID] = [:]
    private var stamp = 0
    /// The last wall grid a frame knew; walls do not move.
    private var wallGrid: Float?

    init(parameters: FusionParameters = FusionParameters()) {
        self.parameters = parameters
    }

    /// The track `id` is now, following merges.
    func resolve(_ id: UUID) -> UUID {
        Self.resolve(id, through: mergedInto)
    }

    /// The track `id` is now, following the merges `mergedInto` records —
    /// for whoever holds a copy of it, like the screen following the object
    /// the person is working on.
    static func resolve(_ id: UUID, through mergedInto: [UUID: UUID]) -> UUID {
        var id = id
        while let next = mergedInto[id] { id = next }
        return id
    }

    /// Lock the track `id` — or the track it was merged into — at `box`, the
    /// box the person was looking at when they finished it. False when that
    /// track is gone, or was already finished: a finished box never changes.
    @discardableResult
    mutating func finish(_ id: UUID, box: GravityBox, time: Double) -> Bool {
        let target = resolve(id)
        guard let i = tracks.firstIndex(where: { $0.id == target }), tracks[i].locked == nil else { return false }
        let t = tracks[i]
        tracks[i].locked = LockedBox(box: box, time: time, hits: t.hits, arcDegrees: t.observedArcDegrees,
                                     bestScore: t.bestScore)
        return true
    }

    /// Fold one frame's observations in. `frame` and `depth` are the frame
    /// they were lifted from, which is also what the votes are read against.
    /// Returns what became of each observation, in order.
    @discardableResult
    mutating func integrate(_ observations: [BoxObservation], frame: SensorFrame,
                            depth: DepthGrid, time: Double, wallGrid: Float? = nil) -> [Sighting] {
        let p = parameters
        self.wallGrid = wallGrid ?? self.wallGrid
        let camera = frame.cameraPosition

        // 1. Associate, best pairs first, each side used once. An outline is
        // compared in its own view: the track's box, drawn there, against it.
        var pairs: [(o: Int, t: Int, score: Float)] = []
        for (oi, o) in observations.enumerated() {
            for (ti, t) in tracks.enumerated() {
                if let outline = o.outline {
                    guard boxesNear(o.box, t.box, margin: 0.5), let seen = OutlineFit.agreement(t.box, outline)?.score
                    else { continue }
                    let same = Self.sameKind(t.label, o.label)
                    if seen >= (same ? p.outlineAssociation : p.crossLabelOutlineAssociation) {
                        pairs.append((oi, ti, (same ? 1 : 0) + seen))
                    }
                    continue
                }
                guard boxesNear(o.box, t.box, margin: 0.15) else { continue }
                let inside = insideFraction(o.points, t.box, margin: 0.03)
                if Self.sameKind(t.label, o.label) {
                    let iou = o.box.iou(t.box), containment = o.box.containment(t.box)
                    guard iou >= p.associationIoU || containment >= p.associationContainment
                            || inside >= p.associationInside else { continue }
                    pairs.append((oi, ti, 1 + max(iou, containment * 0.8, inside)))
                } else if inside >= p.crossLabelInside,
                          let covered = coverage(of: t, by: o.mask, frame: frame, depth: depth),
                          covered >= p.crossLabelCoverage {
                    pairs.append((oi, ti, inside))
                }
            }
        }
        pairs.sort { $0.score > $1.score }
        var matchedTrack = [Int?](repeating: nil, count: observations.count)
        var trackMatched = [Bool](repeating: false, count: tracks.count)
        for pair in pairs where matchedTrack[pair.o] == nil && !trackMatched[pair.t] {
            matchedTrack[pair.o] = pair.t
            trackMatched[pair.t] = true
        }

        // 2. Absorb matches; unmatched observations start tracks.
        var maskByTrack: [UUID: DepthMask] = [:]
        var sightings: [Sighting] = []
        for (oi, o) in observations.enumerated() {
            stamp += 1
            if let ti = matchedTrack[oi] {
                tracks[ti].absorb(o, stamp: stamp, time: time, camera: camera,
                                  voxelSize: p.voxelSize, cap: p.maximumVoxelsPerTrack)
                maskByTrack[tracks[ti].id] = o.mask
                sightings.append(.joined(tracks[ti].id))
            } else if o.score < p.unsureScore {
                sightings.append(.tooUnsure)
            } else if o.touchesEdge && !o.aimedAt {
                sightings.append(.cutOff)
            } else if o.score < p.startingScore, tracks.contains(where: { standsIn(o, $0.box) }) {
                // Unsure, where a track stands already: under 0.5 the
                // detector names what is on or in other objects, and doubles them.
                sightings.append(.tooUnsure)
            } else {
                let track = BoxTrack(observation: o, stamp: stamp, time: time, camera: camera, parameters: p)
                maskByTrack[track.id] = o.mask
                tracks.append(track)
                trackMatched.append(true)
                sightings.append(.started(track.id))
            }
        }
        let detectedTogether = Set(maskByTrack.keys)
        if detectedTogether.count > 1 {
            for ti in tracks.indices where detectedTogether.contains(tracks[ti].id) {
                tracks[ti].distinct.formUnion(detectedTogether)
                tracks[ti].distinct.remove(tracks[ti].id)
            }
        }

        // 3. Votes and misses, against this frame's depth. A track this frame
        // cannot see at all would get neither, so its voxels are not visited.
        // One seen through is missed when the frame looks at its box.
        enum Vote { case inside, outside, seenThrough }
        for ti in tracks.indices {
            let mask = maskByTrack[tracks[ti].id]
            let seenThrough = tracks[ti].isSeenThrough
            if mask == nil, p.skipsTracksOutOfView,
               !mayLandOnDepth(seenThrough ? Self.bounds(tracks[ti].box) : tracks[ti].pointBounds,
                               frame: frame, depth: depth) { continue }
            var visible = 0
            var votes: [(VoxelKey, Vote)] = []
            for (key, voxel) in tracks[ti].voxels {
                guard let projection = frame.depthProjection(world: voxel.centroid) else { continue }
                let x = Int(projection.point.x.rounded(.down)), y = Int(projection.point.y.rounded(.down))
                guard x >= 0, y >= 0, x < depth.width, y < depth.height else { continue }
                let measured = depth.depth(x: x, y: y)
                guard DepthGrid.isMeasured(measured), depth.confidence(x: x, y: y) >= 1 else { continue }
                if measured > projection.depth + p.freeSpaceMargin {
                    votes.append((key, .seenThrough))
                } else if measured >= projection.depth - p.visibilityTolerance {
                    visible += 1
                    if let mask { votes.append((key, mask[x, y] ? .inside : .outside)) }
                }
            }
            var removals = 0
            for (key, vote) in votes {
                guard var v = tracks[ti].voxels[key] else { continue }
                switch vote {
                case .inside:      v.inside += 1
                case .outside:     v.outside += 1
                case .seenThrough: v.seenThrough += 1
                }
                if v.isRefuted {
                    tracks[ti].voxels[key] = nil
                    removals += 1
                } else {
                    tracks[ti].voxels[key] = v
                }
            }
            if mask == nil, seenThrough ? OutlineFit.inView(tracks[ti].box, frame: frame)
                                        : visible >= max(12, tracks[ti].voxels.count * 3 / 10) {
                tracks[ti].misses += 1
            }
            if mask != nil || (removals > 0 && !seenThrough) {
                tracks[ti].refit(contactReach: p.contactReach, wallGrid: wallGrid)
            }
        }

        // 4. Prune what has not earned its place, then hold the count down.
        // A finished track has: the person said so.
        tracks.removeAll { t in
            if t.locked != nil { return false }
            // One seen through is its outlines; any other is its voxels.
            if t.voxels.count < GravityBoxFit.minimumPoints && !t.isSeenThrough { return true }
            if t.hits >= p.smallTrackHits, simd_reduce_max(t.box.size) < p.smallestObject { return true }
            if !t.isConfirmed { return t.misses >= p.tentativeMissLimit }
            return t.misses >= p.confirmedMissLimit && t.hitRatio < p.confirmedMinimumHitRatio
        }
        if tracks.count > p.maximumTracks {
            // Finished, then confirmed, then tentative; unsure below sure at each.
            func rank(_ t: BoxTrack) -> Int {
                t.locked != nil ? 4 : (t.isConfirmed ? 2 : 0) + (t.isUnsure ? 0 : 1)
            }
            let stalest = tracks.indices.sorted {
                (rank(tracks[$0]), tracks[$0].lastSeen) < (rank(tracks[$1]), tracks[$1].lastSeen)
            }
            let dropped = Set(stalest.prefix(tracks.count - p.maximumTracks).map { tracks[$0].id })
            tracks.removeAll { dropped.contains($0.id) }
        }

        // 5. Merge tracks that have come to describe one object.
        mergeOverlapping()
        return sightings
    }

    private mutating func mergeOverlapping() {
        let p = parameters
        var i = 0
        while i < tracks.count {
            var j = i + 1
            while j < tracks.count {
                let a = tracks[i].box, b = tracks[j].box
                let lockedFirst = tracks[i].locked != nil, lockedSecond = tracks[j].locked != nil
                // Two finished boxes are two objects: the person said so twice.
                let merges = !(lockedFirst && lockedSecond) && (Self.sameKind(tracks[i].label, tracks[j].label)
                    ? (a.iou(b) >= p.mergeIoU || a.containment(b) >= p.mergeContainment)
                    : (a.iou(b) >= p.crossLabelMergeIoU && !tracks[i].distinct.contains(tracks[j].id)))
                if merges {
                    // A finished box stays where it is drawn: the finished track is kept.
                    let keepFirst = lockedFirst != lockedSecond ? lockedFirst : tracks[i].hits >= tracks[j].hits
                    var kept = keepFirst ? tracks[i] : tracks[j]
                    let absorbed = keepFirst ? tracks[j] : tracks[i]
                    kept.merge(absorbed)
                    kept.refit(contactReach: p.contactReach, wallGrid: wallGrid)
                    mergedInto[absorbed.id] = kept.id
                    tracks[i] = kept
                    tracks.remove(at: j)
                    for t in tracks.indices where tracks[t].distinct.contains(absorbed.id) {
                        tracks[t].distinct.remove(absorbed.id)
                        if tracks[t].id != kept.id { tracks[t].distinct.insert(kept.id) }
                    }
                } else {
                    j += 1
                }
            }
            i += 1
        }
    }

    private func boxesNear(_ a: GravityBox, _ b: GravityBox, margin: Float) -> Bool {
        let reach = (simd_length(SIMD2(a.size.x, a.size.z)) + simd_length(SIMD2(b.size.x, b.size.z))) / 2
        let d = SIMD2(a.center.x - b.center.x, a.center.z - b.center.z)
        return simd_length(d) <= reach + margin
            && min(a.maxY, b.maxY) + margin >= max(a.minY, b.minY)
    }

    /// The axis-aligned bounds of a box's corners.
    private static func bounds(_ box: GravityBox) -> (lo: SIMD3<Float>, hi: SIMD3<Float>) {
        box.corners.reduce((lo: SIMD3<Float>(repeating: .greatestFiniteMagnitude),
                            hi: SIMD3<Float>(repeating: -.greatestFiniteMagnitude))) {
            (simd_min($0.lo, $1), simd_max($0.hi, $1))
        }
    }

    /// Whether any point inside `bounds` can land on the depth map. False only
    /// when every corner is behind the camera, or every corner is in front and
    /// lands past the same edge: a box wholly in front projects inside the hull
    /// of its corners' projections, so then no voxel in it lands on the map
    /// either. A millimetre of padding covers a centroid's rounding.
    private func mayLandOnDepth(_ bounds: (lo: SIMD3<Float>, hi: SIMD3<Float>), frame: SensorFrame,
                                depth: DepthGrid) -> Bool {
        let lo = bounds.lo - 0.001, hi = bounds.hi + 0.001
        guard lo.x <= hi.x, lo.y <= hi.y, lo.z <= hi.z else { return false }
        var behind = 0, left = 0, right = 0, above = 0, below = 0
        for i in 0..<8 {
            let corner = SIMD3(i & 1 == 0 ? lo.x : hi.x, i & 2 == 0 ? lo.y : hi.y, i & 4 == 0 ? lo.z : hi.z)
            guard let projection = frame.depthProjection(world: corner) else {
                behind += 1
                continue
            }
            if projection.point.x < 0 { left += 1 }
            if projection.point.x >= Float(depth.width) { right += 1 }
            if projection.point.y < 0 { above += 1 }
            if projection.point.y >= Float(depth.height) { below += 1 }
        }
        if behind == 8 { return false }
        if behind > 0 { return true }
        return left < 8 && right < 8 && above < 8 && below < 8
    }

    /// Of the track's voxels this frame measures — in view, and the depth there
    /// agreeing with the voxel rather than with something nearer or further —
    /// the fraction inside `mask`. Nil when too few are measured to say.
    private func coverage(of track: BoxTrack, by mask: DepthMask, frame: SensorFrame, depth: DepthGrid) -> Float? {
        let step = max(track.voxels.count / 600, 1)
        var measuredVoxels = 0, inside = 0, k = 0
        for voxel in track.voxels.values {
            k += 1
            guard k % step == 0, let projection = frame.depthProjection(world: voxel.centroid) else { continue }
            let x = Int(projection.point.x.rounded(.down)), y = Int(projection.point.y.rounded(.down))
            guard x >= 0, y >= 0, x < depth.width, y < depth.height else { continue }
            let d = depth.depth(x: x, y: y)
            guard DepthGrid.isMeasured(d), depth.confidence(x: x, y: y) >= 1,
                  abs(d - projection.depth) <= parameters.visibilityTolerance else { continue }
            measuredVoxels += 1
            if mask[x, y] { inside += 1 }
        }
        return measuredVoxels >= GravityBoxFit.minimumPoints ? Float(inside) / Float(measuredVoxels) : nil
    }

    /// Whether most of an observation lies within `box`: its points, or,
    /// seen through, its outline in its own view.
    private func standsIn(_ o: BoxObservation, _ box: GravityBox) -> Bool {
        if let outline = o.outline { return (OutlineFit.agreement(box, outline)?.covered ?? 0) >= 0.5 }
        return insideFraction(o.points, box, margin: 0.03) >= 0.5
    }

    private func insideFraction(_ points: [SIMD3<Float>], _ box: GravityBox, margin: Float) -> Float {
        guard !points.isEmpty else { return 0 }
        let step = max(points.count / 400, 1)
        var inside = 0, total = 0
        for k in stride(from: 0, to: points.count, by: step) {
            total += 1
            if box.contains(points[k], margin: margin) { inside += 1 }
        }
        return Float(inside) / Float(total)
    }
}

#endif
