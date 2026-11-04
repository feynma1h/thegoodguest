/// One detector pass, from a copied-out camera frame to fused 3D boxes, timed
/// stage by stage — DEBUG-only (decision 0295).
///
/// A pass is: choose the upright turn from gravity; render the detector's input
/// (and a depth model's, from the same buffer); take the pass's depth from its
/// `DepthSource` — a model's frame that cannot be fitted is no pass;
/// predict; decode rows and prototypes; union every EXCLUDED detection's mask
/// (people, animals) first; settle each pixel two masks claim (`DepthMask.owned`:
/// an object on another keeps it, else the surer detection); lift every
/// lifted detection from the pixels it owns, the excluded ones removed — or,
/// where LiDAR sees through it to the floor, take its outline instead
/// (`observation`, `OutlineBox`); fold the observations into fusion. Nothing
/// is retained across passes except the fusion itself and the last turn.
///
/// EVERY DETECTION THAT BECOMES NO SIGHTING SAYS WHY (`MissReason`), with
/// where it was, so the log can say why an object in the room never got a
/// dot: glass that showed only the wall and floor behind it, a door the
/// detector saw where a cabinet stands, a name too unsure to start a box.
/// Except a person's.
///
/// NO ARFRAME CROSSES INTO HERE. The frame driver copies the depth map and its
/// confidence, and hands the camera buffer over in a one-shot handoff the pass
/// empties as soon as the input is rendered — ARKit's capture pool is small,
/// and a pass that held its buffer for the whole lift would starve it (the
/// retained-frame failure 0076 measured).
///
/// Confined to the pipeline queue; the session only reads the results.
///
/// Read by: LiveBoxesSession, LiveBoxesModelTests.

#if DEBUG

import CoreML
import CoreVideo
import Foundation
import simd

/// A camera buffer passed to exactly one taker.
nonisolated final class PixelBufferHandoff: @unchecked Sendable {
    private let lock = NSLock()
    private var buffer: CVPixelBuffer?

    init(_ buffer: CVPixelBuffer) { self.buffer = buffer }

    func take() -> CVPixelBuffer? {
        lock.lock()
        defer { lock.unlock() }
        let b = buffer
        buffer = nil
        return b
    }
}

/// Everything one pass needs from one ARFrame.
nonisolated struct FrameSnapshot: Sendable {
    let image: PixelBufferHandoff
    /// LiDAR's depth, when the frame carried it.
    let depth: DepthGrid?
    let intrinsics: CameraIntrinsics
    let worldFromCamera: simd_float4x4
    let surfaces: [HorizontalSurface]
    /// ARFrame.timestamp.
    let time: Double
    /// The room's wall grid from ARKit's vertical planes (`WallGrid`), when
    /// any wall is known.
    var wallGrid: Float? = nil
    /// ARKit's vertical planes, as far as each was measured.
    var walls: [VerticalSurface] = []
    /// What a depth model's map is fitted to; empty when LiDAR is the source.
    var anchors = DepthAnchors()
}

/// A track as the screen and the log need it: no voxels.
nonisolated struct TrackSummary: Sendable, Identifiable, Equatable {
    let id: UUID
    let label: String
    let name: String
    let names: [String: Float]
    let bestScore: Float
    let hits: Int
    let misses: Int
    let arcDegrees: Int
    let firstSeen: Double
    let lastSeen: Double
    let confirmed: Bool
    /// No sighting reached the starting score: the object wears a faint dot.
    let unsure: Bool
    /// Its box is fitted to outlines: LiDAR sees through it (`OutlineFit`).
    let seenThrough: Bool
    /// Its outlines pin every side of its footprint (`OutlineFit.pinned`).
    /// Meaningless unless `seenThrough`; true there so nothing else reads as
    /// unsure.
    let outlinesPinned: Bool
    /// WHETHER ITS SHAPE IS STILL A GUESS, which is a different question from
    /// `unsure` — that one is the detector's doubt about the NAME. A box
    /// fitted to outlines can score 0.97 and be a metre too long, because the
    /// image says almost nothing along the direction the camera is looking; a
    /// side the outlines do not pin is one nobody has measured.
    var boxUnsure: Bool { seenThrough && !outlinesPinned }
    /// The box fusion fitted this pass. The screen draws `locked`, never this.
    var box: GravityBox
    /// The box the screen draws, fixed when the person finished it.
    var locked: LockedBox?
    let roomPlanCategory: String?
    /// RoomPlan categories a long-tail box of this kind can duplicate.
    let roomPlanOverlap: Set<String>
    /// How far the fit moved between passes.
    let movement: TrackMovement
    /// The 10° directions it has been seen from (`BoxTrack.directionBin`).
    let seenFrom: Set<Int>

    init(id: UUID, label: String, name: String, names: [String: Float] = [:], bestScore: Float,
         hits: Int, misses: Int = 0, arcDegrees: Int, firstSeen: Double = 0, lastSeen: Double = 0,
         confirmed: Bool, unsure: Bool = false, seenThrough: Bool = false, outlinesPinned: Bool = true,
         box: GravityBox, locked: LockedBox? = nil,
         roomPlanCategory: String? = nil, roomPlanOverlap: Set<String> = [], movement: TrackMovement = TrackMovement(),
         seenFrom: Set<Int> = []) {
        self.id = id
        self.label = label
        self.name = name
        self.names = names
        self.bestScore = bestScore
        self.hits = hits
        self.misses = misses
        self.arcDegrees = arcDegrees
        self.firstSeen = firstSeen
        self.lastSeen = lastSeen
        self.confirmed = confirmed
        self.unsure = unsure
        self.seenThrough = seenThrough
        self.outlinesPinned = outlinesPinned
        self.box = box
        self.locked = locked
        self.roomPlanCategory = roomPlanCategory
        self.roomPlanOverlap = roomPlanOverlap
        self.movement = movement
        self.seenFrom = seenFrom
    }

    init(_ track: BoxTrack) {
        id = track.id
        label = track.label
        name = track.dominantName
        names = track.names
        bestScore = track.bestScore
        hits = track.hits
        misses = track.misses
        arcDegrees = track.observedArcDegrees
        firstSeen = track.firstSeen
        lastSeen = track.lastSeen
        confirmed = track.isConfirmed
        unsure = track.isUnsure
        seenThrough = track.isSeenThrough
        outlinesPinned = track.outlinesPinned
        box = track.box
        locked = track.locked
        roomPlanCategory = track.roomPlanCategory
        movement = track.movement
        seenFrom = track.azimuthBins
        if case .target(_, _, let overlap) = DetectorVocabulary.role(for: track.dominantName) {
            roomPlanOverlap = overlap
        } else {
            roomPlanOverlap = []
        }
    }
}

/// Why a detection became no sighting of any track — the words the session
/// log tallies it under (`MissTally`), so a walk past an object that never
/// got a dot says why. A person is never one: excluded detections are
/// counted, and nothing else about them is kept (0089).
nonisolated enum MissReason: String, Sendable, CaseIterable {
    /// A name for structure or clutter: a door, a window, a wall.
    case partOfTheRoom = "part of the room"
    /// One of RoomPlan's categories while RoomPlan boxes them.
    case leftToRoomPlan = "left to RoomPlan"
    case tooSmallInView = "too small in view"
    case tooFewPixels = "too few pixels"
    case noDepth = "no depth under it"
    case onlySurfaces = "only surfaces under it"
    case tooLittleSeen = "too little of it seen"
    /// Seen through to the floor, but no box standing on it agrees with the outline.
    case outlineOffTheFloor = "its outline fits no box on the floor"
    /// No track to join, and under the unsure score — or unsure where a
    /// track already stands.
    case tooUnsure = "too unsure to start a box"
    /// No track to join, and cut off by the frame without being aimed at.
    case cutOff = "cut off by the frame"
    /// `DepthMask.owned` left it the scraps of a mask another name took.
    case outnamed = "another name owns it"

    init(_ rejection: LiftRejection) {
        switch rejection {
        case .tooFewPixels:  self = .tooFewPixels
        case .noDepth:       self = .noDepth
        case .onlySurfaces:  self = .onlySurfaces
        case .tooLittleSeen: self = .tooLittleSeen
        }
    }

    /// Why a detection in `role` is not lifted at all; nil when it is lifted,
    /// or is a person, of whom nothing is kept.
    static func unlifted(_ role: DetectorRole, liftsRoomPlanCategories: Bool) -> MissReason? {
        switch role {
        case .excluded, .target: return nil
        case .absorber: return .partOfTheRoom
        case .roomPlanCategory: return liftsRoomPlanCategories ? nil : .leftToRoomPlan
        }
    }
}

/// What became of one detection on its way to fusion: an observation, or why none.
nonisolated enum Observed: Sendable {
    case seen(BoxObservation)
    case missed(MissReason)
}

/// A detection that became no sighting: its name, why, its score, and where
/// it was — from the depth around the middle of its box, when any was measured.
nonisolated struct DetectionMiss: Sendable, Equatable {
    let name: String
    let reason: MissReason
    let score: Float
    let at: SIMD3<Float>?
}

nonisolated struct PassResult: Sendable {
    let time: Double
    let timing: PassTiming
    /// Rows above the score threshold.
    let detections: Int
    /// Detections that became observations.
    let lifted: Int
    /// Detections whose pixels were removed from everything else.
    let excluded: Int
    let turn: QuarterTurn
    let tracks: [TrackSummary]
    /// Set when the pass could not run at all.
    let failure: String?
    /// The model outputs' shapes, strides and storage type, on a pipeline's
    /// first prediction only.
    var outputLayout: String? = nil
    /// Detections not lifted because they covered too little of the view.
    var tooSmall: Int = 0
    /// Voxels held by every track after the pass.
    var voxels: Int = 0
    /// Which track each merged-away track went into, so far this session.
    var mergedInto: [UUID: UUID] = [:]
    /// The detections that became no sighting of any track, and why.
    var misses: [DetectionMiss] = []
    /// Where the pass's depth came from, and for a model's, its fit and score.
    var depth: DepthPassLog? = nil
    /// The pass's depth, for the screen to read what stands in front of an object.
    var sight: DepthSight? = nil
}

nonisolated final class DetectorPipeline: @unchecked Sendable {
    let detector: LoadedDetector
    let depthSource: DepthSource
    private let preprocessor: FramePreprocessor
    private var fusion: BoxFusion
    private var previousTurn: QuarterTurn?
    private var layoutReported = false
    /// Whether RoomPlan's own categories are lifted: unless RoomPlan boxes them
    /// (`RoomPlanClasses.boxedByRoomPlan`), the detector does.
    let liftsRoomPlanCategories = !RoomPlanClasses.boxedByRoomPlan
    /// A detection cut off by the frame may start a box even when the middle of
    /// the screen is not on it. The rule was made for aim-and-hold; with a tap
    /// choosing the object, a cupboard that fills the frame never had the
    /// middle of the screen on its mask often enough to start.
    static let startsCutOffObjects = true
    /// Names the vocabulary leaves to the room that live boxes boxes anyway.
    /// "furniture" is what the detector calls a glass-doored cupboard; as an
    /// absorber it was dropped as part of the room.
    static let promotedRoles: [String: DetectorRole] = [
        "furniture": .target(label: "FURNITURE", flat: false, roomPlanOverlap: [])
    ]

    /// The role a name plays here: the vocabulary's, unless promoted.
    static func role(for name: String, promoted: [String: DetectorRole] = promotedRoles) -> DetectorRole {
        promoted[name] ?? DetectorVocabulary.role(for: name)
    }
    /// Names boxed from their outline and the floor whatever the depth says. A
    /// model's depth of a glass top is the glass (or a smooth guess), never the
    /// floor seen through it, so the seen-through test that sends LiDAR's glass
    /// tables this way does not fire; and LiDAR's own reading of glass is not
    /// something to trust either. A name that says glass is believed.
    static let outlineAlways: Set<String> = ["glass table"]
    /// Labels whose own top is a surface of the room: lifted without taking it away (`DepthLifter.attempt`).
    static let ownTopLabels = BoxFusion.tableKinds
    private let clock = ContinuousClock()

    let scoreThreshold: Float
    let liftParameters: DepthLiftParameters

    /// How far a floor covering may stand off its floor before its name is
    /// taken to be wrong (`observation`). Measured on the synthetic rugs,
    /// noise included: a 1.2 cm rug comes out 4.0-4.2 cm tall, a 5 cm one
    /// 7.6, and a 30 cm pile 32. The green glass table taken for a rug on the
    /// phone measured 46.5. So this sits well above any floor covering and
    /// well below that: what it rejects is a name, not a thing.
    static let floorCoveringRise: Float = 0.15

    init(detector: LoadedDetector, depth: DepthSource = .lidar, scoreThreshold: Float = 0.3) {
        self.detector = detector
        depthSource = depth
        self.scoreThreshold = scoreThreshold
        liftParameters = depth.liftParameters
        fusion = BoxFusion(parameters: depth.fusionParameters)
        preprocessor = FramePreprocessor(width: detector.info.inputWidth, height: detector.info.inputHeight)
    }

    /// Names in the model the vocabulary table does not know.
    var unmappedNames: [String] { detector.info.names.filter { !DetectorVocabulary.knows($0) } }

    /// One pass, inside its own autorelease pool. Core ML's outputs and Core
    /// Image's buffers come back autoreleased, and a queue that is never idle
    /// never drains its thread's pool: on the phone, free memory fell by about
    /// 4 MB with every pass until nothing ran.
    func process(_ snapshot: FrameSnapshot) -> PassResult {
        autoreleasepool { run(snapshot) }
    }

    private func run(_ snapshot: FrameSnapshot) -> PassResult {
        var timing = PassTiming()
        let info = detector.info
        let gravity = PoseExtractor.gravityInCameraFrame(simd_quaternion(snapshot.worldFromCamera))
        let turn = QuarterTurn.upright(gravity: gravity, previous: previousTurn)
        previousTurn = turn
        let frame = SensorFrame(intrinsics: snapshot.intrinsics,
                                depthWidth: snapshot.depth?.width ?? DepthSource.gridWidth,
                                depthHeight: snapshot.depth?.height ?? DepthSource.gridHeight,
                                worldFromCamera: snapshot.worldFromCamera, turn: turn,
                                modelWidth: info.inputWidth, modelHeight: info.inputHeight)
        var depthLog: DepthPassLog?
        func failed(_ reason: String) -> PassResult {
            PassResult(time: snapshot.time, timing: timing, detections: 0, lifted: 0, excluded: 0,
                       turn: turn, tracks: fusion.tracks.map(TrackSummary.init), failure: reason,
                       mergedInto: fusion.mergedInto, depth: depthLog)
        }

        var mark = clock.now
        guard let input = renderInput(snapshot, frame: frame) else {
            return failed("the frame could not be rendered as detector input")
        }
        timing.preprocess = milliseconds(since: &mark)

        let stage = depthSource.depth(for: snapshot, input: input.depth, frame: frame)
        timing.depth = stage.predict
        timing.align = stage.align
        depthLog = stage.log
        guard let depth = stage.grid else { return failed("no depth from \(depthSource.name)") }
        mark = clock.now

        let output: MLFeatureProvider
        do {
            let features = try MLDictionaryFeatureProvider(
                dictionary: [detector.inputName: MLFeatureValue(pixelBuffer: input.detector)])
            output = try detector.model.prediction(from: features)
        } catch {
            return failed("prediction failed: \(error.localizedDescription)")
        }
        timing.predict = milliseconds(since: &mark)

        guard let rowsArray = output.featureValue(for: detector.detectionsName)?.multiArrayValue,
              let protoArray = output.featureValue(for: detector.prototypesName)?.multiArrayValue
        else { return failed("the prediction had no detections or prototypes") }
        let rowShape = rowsArray.shape.map(\.intValue)
        let protoShape = protoArray.shape.map(\.intValue)
        var outputLayout: String?
        if !layoutReported {
            layoutReported = true
            outputLayout = "rows \(DetectorArrays.layout(rowsArray)); prototypes \(DetectorArrays.layout(protoArray))"
        }
        guard rowShape.count == 3, protoShape.count == 4 else {
            var result = failed("unexpected output shapes")
            result.outputLayout = outputLayout
            return result
        }
        let detections = DetectionDecoder.decode(
            rows: DetectorArrays.floats(rowsArray), rowCount: rowShape[1], rowLength: rowShape[2],
            classCount: info.names.count, minimumScore: scoreThreshold,
            modelWidth: Float(info.inputWidth), modelHeight: Float(info.inputHeight))
        let bank = ProtoBank(channels: protoShape[1], width: protoShape[3], height: protoShape[2],
                             values: DetectorArrays.floats(protoArray),
                             modelWidth: Float(info.inputWidth), modelHeight: Float(info.inputHeight))
        timing.decode = milliseconds(since: &mark)

        let roles = detections.map { Self.role(for: info.names[$0.classIndex]) }
        var excluded: DepthMask?
        var excludedCount = 0
        for (detection, role) in zip(detections, roles) where role == .excluded {
            excludedCount += 1
            guard let mask = bank.mask(for: detection).depthMask(frame: frame) else { continue }
            excluded = excluded.map { $0.union(mask) } ?? mask
        }
        // Every detection that becomes no sighting says why, for the log.
        var misses: [DetectionMiss] = []
        func missed(_ i: Int, _ reason: MissReason) {
            let detection = detections[i]
            misses.append(DetectionMiss(name: info.names[detection.classIndex], reason: reason, score: detection.score,
                                        at: Self.whereabouts(detection, frame: frame, depth: depth)))
        }
        var tooSmall = 0
        var lifting: [Int] = []
        for (i, (detection, role)) in zip(detections, roles).enumerated() {
            guard role.isLifted(includingRoomPlanCategories: liftsRoomPlanCategories) else {
                if let reason = MissReason.unlifted(role, liftsRoomPlanCategories: liftsRoomPlanCategories) {
                    missed(i, reason)
                }
                continue
            }
            // Size in view before anything is built for it: far or tiny is a
            // handful of LiDAR samples, and not worth a track.
            guard frame.viewFraction(modelMin: detection.modelMin, modelMax: detection.modelMax)
                    >= liftParameters.minimumViewFraction else {
                tooSmall += 1
                missed(i, .tooSmallInView)
                continue
            }
            lifting.append(i)
        }
        // Every mask that can take a pixel from one being lifted: those, and
        // any other detection not excluded whose box overlaps one of them —
        // RoomPlan's categories included, lifted or not.
        var claims: [Int: (mask: DepthMask, score: Float)] = [:]
        for (i, (detection, role)) in zip(detections, roles).enumerated() where role != .excluded {
            guard lifting.contains(where: { $0 == i || Self.overlap(detections[$0], detection) }),
                  let mask = bank.mask(for: detection).depthMask(frame: frame) else { continue }
            claims[i] = (mask, detection.score)
        }
        let owned = DepthMask.owned(claims)
        // Where the person is aiming: a detection whose outline covers it may
        // start a track even though the frame cuts it off.
        let aim = frame.centreDepthPixel
        // Every mask that can hide an object: where another object stands, an
        // outline cannot say its own is not. Not the room's, and not a rug's.
        let objects = claims.filter { roles[$0.key].canHide }.mapValues { $0.mask }
        var observations: [BoxObservation] = []
        // The detection behind each observation.
        var observed: [Int] = []
        for i in lifting {
            let detection = detections[i], role = roles[i]
            // Points come from the pixels it owns; votes read its whole mask.
            guard let label = role.label, let mask = claims[i]?.mask, let own = owned[i] else {
                missed(i, .tooFewPixels)
                continue
            }
            var flat = false
            var category: String?
            switch role {
            case .target(_, let isFlat, _): flat = isFlat
            case .roomPlanCategory(_, let token): category = token
            case .excluded, .absorber: break
            }
            let others = objects.filter { $0.key != i }.map(\.value) + (excluded.map { [$0] } ?? [])
            switch Self.observation(name: info.names[detection.classIndex], label: label, category: category,
                                    score: detection.score, flat: flat, mask: mask, own: own, others: others,
                                    excluded: excluded, depth: depth, frame: frame,
                                    surfaces: snapshot.surfaces, walls: snapshot.walls, wallGrid: snapshot.wallGrid,
                                    touchesEdge: frame.touchesImageEdge(modelMin: detection.modelMin,
                                                                        modelMax: detection.modelMax,
                                                                        margin: liftParameters.edgeMargin),
                                    aimedAt: Self.startsCutOffObjects || mask[aim.x, aim.y],
                                    forceOutline: Self.outlineAlways.contains(info.names[detection.classIndex]),
                                    parameters: liftParameters) {
            case .seen(let observation):
                observations.append(observation)
                observed.append(i)
            case .missed(let reason):
                missed(i, reason)
            }
        }
        timing.lift = milliseconds(since: &mark)

        let sightings = fusion.integrate(observations, frame: frame, depth: depth, time: snapshot.time,
                                         wallGrid: snapshot.wallGrid)
        timing.fuse = milliseconds(since: &mark)
        for (i, sighting) in zip(observed, sightings) {
            switch sighting {
            case .tooUnsure: missed(i, .tooUnsure)
            case .cutOff: missed(i, .cutOff)
            case .joined, .started: break
            }
        }

        return PassResult(time: snapshot.time, timing: timing, detections: detections.count,
                          lifted: observations.count, excluded: excludedCount, turn: turn,
                          tracks: fusion.tracks.map(TrackSummary.init), failure: nil, outputLayout: outputLayout,
                          tooSmall: tooSmall, voxels: fusion.tracks.reduce(0) { $0 + $1.voxels.count },
                          mergedInto: fusion.mergedInto, misses: misses, depth: depthLog,
                          sight: DepthSight(grid: depth, frame: frame, time: snapshot.time, walls: snapshot.walls,
                                            tops: snapshot.surfaces.filter { $0.extent != nil && $0.supportsObjects }))
    }

    /// The person finished `id` at `box` (`BoxFusion.finish`). On the
    /// pipeline queue, like every other touch of the fusion.
    func finish(_ id: UUID, box: GravityBox, time: Double) {
        fusion.finish(id, box: box, time: time)
    }

    /// One detection as an observation: lifted from the depth under the
    /// pixels it owns (`own`) — or, when LiDAR saw through it to the floor it
    /// stands on or saw nothing of it with the floor all round
    /// (`FloorShare.seenThrough`), as its outline, which `others` (every mask
    /// that can hide it, people's included) cannot contradict. Otherwise why
    /// neither.
    ///
    /// A DETECTION ANOTHER NAME OWNS IS NOT A SECOND OBJECT. Where two names
    /// land on one thing, `DepthMask.owned` gives the shared pixels to one of
    /// them; the other keeps scraps, and lifting those grows a box with no
    /// object under it. Measured on the green glass table, which the detector
    /// also names "carpet": the carpet kept 3 % of its own mask — the bleed
    /// rim — lifted the floor under it and sprawled to 300 x 226 cm, a second
    /// track outscoring the table's own. So a detection owning less than 30 %
    /// of its mask is no sighting at all, whichever route it would take.
    ///
    /// A FLOOR COVERING CANNOT STAND OFF THE FLOOR. `flat` keeps a rug out of
    /// the outline route, because a rug's own surface lies within the floor's
    /// support band and `FloorShare` cannot tell it from a glass table from
    /// one view. But the name can simply be wrong — through the glass the
    /// detector fires "carpet" on the table's silhouette — and then the
    /// geometry says so: a floor covering measures 4 cm tall, a thick one
    /// 7.6, while the glass table taken for a rug on the phone measured 46.5.
    /// A flat-named detection standing more than `floorCoveringRise` off its
    /// floor is not a floor covering, so it drops the claim and is lifted
    /// again as an ordinary object — which also opens the outline route to
    /// it. The claim is dropped, never the object: a floor cushion named
    /// "mat" keeps its box, as a thing rather than as a covering.
    static func observation(name: String, label: String, category: String?, score: Float, flat: Bool,
                            mask: DepthMask, own: DepthMask, others: [DepthMask], excluded: DepthMask?,
                            depth: DepthGrid, frame: SensorFrame, surfaces: [HorizontalSurface],
                            walls: [VerticalSurface], wallGrid: Float?, touchesEdge: Bool, aimedAt: Bool,
                            forceOutline: Bool = false,
                            parameters p: DepthLiftParameters = DepthLiftParameters()) -> Observed {
        guard own.count * 10 >= mask.count * 3 else { return .missed(.outnamed) }
        let floorHeight = surfaces.filter { $0.kind == .floor }.map(\.height).min()
        var flat = flat
        let ownTop = ownTopLabels.contains(label)
        var attempt = DepthLifter.attempt(mask: own, excluding: excluded, depth: depth, frame: frame,
                                          surfaces: surfaces, walls: walls, flat: flat, ownTop: ownTop, parameters: p)
        if flat, case .lifted(let points) = attempt, let floor = floorHeight,
           let top = points.points.map(\.y).max(), top > floor + floorCoveringRise {
            flat = false
            attempt = DepthLifter.attempt(mask: own, excluding: excluded, depth: depth, frame: frame,
                                          surfaces: surfaces, walls: walls, flat: false, ownTop: ownTop, parameters: p)
        }
        var outline: OutlineView?
        var sawNothing = false
        if case .rejected(.noDepth) = attempt { sawNothing = true }
        if !flat,
           let floor = floorHeight,
           forceOutline || FloorShare.measure(mask: own, excluding: excluded, depth: depth, frame: frame, floor: floor,
                                              around: sawNothing, parameters: p).seenThrough(attempt) {
            outline = OutlineView(mask: mask, others: others, frame: frame, floor: floor)
        }
        var lifted: LiftedPoints?
        switch attempt {
        case .lifted(let points): lifted = points
        case .rejected(let rejection): if outline == nil { return .missed(MissReason(rejection)) }
        }
        // Forced to the outline route: the depth's points are the glass, not the table.
        if forceOutline, outline != nil { lifted = nil }
        guard let observation = BoxObservation(name: name, label: label, roomPlanCategory: category, score: score,
                                               points: lifted?.points ?? [], mask: mask,
                                               restsOn: lifted?.restsOn, hangsFrom: lifted?.hangsFrom,
                                               against: lifted?.against ?? [], wallGrid: wallGrid,
                                               touchesEdge: touchesEdge, aimedAt: aimedAt, outline: outline,
                                               flat: flat)
        else { return .missed(lifted == nil ? .outlineOffTheFloor : .tooLittleSeen) }
        return .seen(observation)
    }

    /// Take the camera buffer and render the detector's input from it, and a
    /// depth model's when one is the source. The camera buffer is released
    /// when this returns, before the prediction — a local in `process` would
    /// live to the end of the pass in an unoptimised build.
    private func renderInput(_ snapshot: FrameSnapshot,
                             frame: SensorFrame) -> (detector: CVPixelBuffer, depth: CVPixelBuffer?)? {
        guard let image = snapshot.image.take(), let input = preprocessor.render(image, frame: frame) else { return nil }
        return (input, depthSource.render(image, frame: frame))
    }

    /// Where a detection is: the median depth measured around the middle of
    /// its box, as a world point — the floor under a glass table, the glass
    /// of a cabinet's door — or nil when nothing there was measured.
    private static func whereabouts(_ detection: RawDetection, frame: SensorFrame, depth: DepthGrid) -> SIMD3<Float>? {
        guard let range = frame.depthPixelRange(modelMin: detection.modelMin, modelMax: detection.modelMax)
        else { return nil }
        let x = (range.x.lowerBound + range.x.upperBound) / 2, y = (range.y.lowerBound + range.y.upperBound) / 2
        guard let d = depth.medianDepth(x: x, y: y, radius: 3, minimumConfidence: 1) else { return nil }
        return frame.worldPoint(depthX: x, depthY: y, depth: d)
    }

    /// Whether two detections' boxes overlap in the model input.
    private static func overlap(_ a: RawDetection, _ b: RawDetection) -> Bool {
        a.modelMin.x < b.modelMax.x && b.modelMin.x < a.modelMax.x
            && a.modelMin.y < b.modelMax.y && b.modelMin.y < a.modelMax.y
    }

    private func milliseconds(since mark: inout ContinuousClock.Instant) -> Double {
        let now = clock.now
        let d = now - mark
        mark = now
        return Double(d.components.seconds) * 1000 + Double(d.components.attoseconds) / 1e15
    }
}

#endif
