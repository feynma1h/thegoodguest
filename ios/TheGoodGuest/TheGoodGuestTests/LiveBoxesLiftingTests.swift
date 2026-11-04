/// The live-boxes lifting chain, end to end on synthetic rooms with known
/// boxes: a detector mask in model space, through the letterbox and the upright
/// turn, onto LiDAR depth, into world points, through fusion across views, and
/// out as a gravity-aligned box compared against the truth.
///
/// THE TOLERANCES ARE THE ACCEPTANCE BAR, not a description of today's output:
/// centre within 3 cm, every extent within 5 cm, and yaw within 5° for any
/// object at least 20 cm across. A failure prints every object's errors, so a
/// regression reads as numbers rather than as a red dot.
///
/// The frames carry what real ones do — range-dependent noise, flying pixels at
/// depth edges, low-confidence dropouts, and masks that bleed past the
/// silhouette — and the views mix both portrait holds with landscape. See
/// LiveBoxesSyntheticScene for how each is made, and why it does not share
/// code with the maps it tests.

import simd
import XCTest
@testable import TheGoodGuest

final class LiveBoxesLiftingTests: XCTestCase {

    // MARK: - The bar

    private let centreTolerance: Float = 0.03
    private let extentTolerance: Float = 0.05
    private let yawToleranceDegrees: Float = 5
    private let yawMinimumSize: Float = 0.20

    // MARK: - The room

    private static func degrees(_ d: Float) -> Float { d * .pi / 180 }

    private static let sideTable = GravityBox(center: SIMD3(0.6, 0.275, -0.9), size: SIMD3(0.50, 0.55, 0.42),
                                              yaw: degrees(25))

    private static let furnishedRoom = SyntheticScene(objects: [
        SyntheticObject(id: 0, name: "side table", box: sideTable),
        SyntheticObject(id: 1, name: "computer monitor",
                        box: GravityBox(center: SIMD3(0.6, 0.725, -0.9), size: SIMD3(0.48, 0.35, 0.10),
                                        yaw: degrees(25))),
        SyntheticObject(id: 2, name: "bookshelf",
                        box: GravityBox(center: SIMD3(-2.34, 0.9, 0.3), size: SIMD3(0.30, 1.80, 0.80),
                                        yaw: 0)),
        SyntheticObject(id: 3, name: "lamp",
                        box: GravityBox(center: SIMD3(1.55, 0.8, 1.0), size: SIMD3(0.40, 1.60, 0.40),
                                        yaw: degrees(12))),
        SyntheticObject(id: 4, name: "houseplant",
                        box: GravityBox(center: SIMD3(-0.9, 0.45, 1.1), size: SIMD3(0.45, 0.90, 0.45),
                                        yaw: degrees(40))),
        SyntheticObject(id: 5, name: "picture frame",
                        box: GravityBox(center: SIMD3(-0.4, 1.5, -1.98), size: SIMD3(0.90, 0.60, 0.04),
                                        yaw: 0)),
        SyntheticObject(id: 6, name: "carpet",
                        box: GravityBox(center: SIMD3(0.2, 0.006, 0.4), size: SIMD3(1.6, 0.012, 1.1),
                                        yaw: degrees(8))),
    ], tops: [SyntheticScene.top(of: sideTable)])

    private static let portrait: Float = .pi / 2

    /// Views chosen per object the way someone walking the room would take
    /// them: a few steps apart, eye height, turning to face it.
    private static let walk: [SyntheticCamera] = {
        func around(_ c: SIMD3<Float>, distance: Float, azimuths: [Float], height: Float = 1.45,
                    rolls: [Float]) -> [SyntheticCamera] {
            zip(azimuths, rolls).map { azimuth, roll in
                let a = degrees(azimuth)
                let eye = SIMD3(c.x + distance * cos(a), height, c.z + distance * sin(a))
                return SyntheticCamera(eye: eye, target: c, roll: roll)
            }
        }
        var views: [SyntheticCamera] = []
        views += around(SIMD3(0.6, 0.45, -0.9), distance: 1.7, azimuths: [145, 90, 35, -30],
                        rolls: [portrait, -portrait, 0, portrait + 0.06])
        views += around(SIMD3(-2.34, 0.9, 0.3), distance: 1.8, azimuths: [-45, 0, 45],
                        rolls: [portrait, 0, -portrait])
        views += around(SIMD3(1.55, 0.8, 1.0), distance: 1.7, azimuths: [180, 225, 270, 150],
                        rolls: [-portrait, portrait, 0, portrait])
        views += around(SIMD3(-0.9, 0.45, 1.1), distance: 1.6, azimuths: [0, -60, -120, 20],
                        rolls: [portrait, 0, -portrait, portrait])
        views += around(SIMD3(-0.4, 1.5, -1.98), distance: 2.0, azimuths: [50, 90, 130],
                        rolls: [portrait, -portrait, 0])
        views += around(SIMD3(0.2, 0.0, 0.4), distance: 2.0, azimuths: [0, 180, 270], height: 1.5,
                        rolls: [portrait, -portrait, 0])
        return views
    }()

    // MARK: - The chain

    private struct Outcome {
        var fusion = BoxFusion()
        var observationsByObject: [Int: Int] = [:]
    }

    /// Run every view through the production chain: mask → depth mask →
    /// lift → fuse.
    private func runWalk(scene: SyntheticScene, views: [SyntheticCamera], seed: UInt64,
                         bleed: Bool = true, exclude excludedIDs: Set<Int> = [],
                         claimExcludedPixels: Set<Int> = [], useExclusion: Bool = true,
                         fusion parameters: FusionParameters = FusionParameters(),
                         wallGrid: Float? = nil, knowsWalls: Bool = false) -> Outcome {
        var rng = SeededGenerator(seed: seed)
        var outcome = Outcome(fusion: BoxFusion(parameters: parameters))
        for (index, camera) in views.enumerated() {
            let render = scene.renderDepth(camera: camera, rng: &rng)
            let grid = DepthGrid(width: SyntheticScene.depthWidth, height: SyntheticScene.depthHeight,
                                 depth: render.depth, confidence: render.confidence)
            let gravity = PoseExtractor.gravityInCameraFrame(simd_quaternion(camera.worldFromCamera))
            let turn = QuarterTurn.upright(gravity: gravity, previous: nil)
            let frame = SensorFrame(intrinsics: SyntheticScene.intrinsics,
                                    depthWidth: SyntheticScene.depthWidth,
                                    depthHeight: SyntheticScene.depthHeight,
                                    worldFromCamera: camera.worldFromCamera, turn: turn,
                                    modelWidth: SyntheticScene.modelSize, modelHeight: SyntheticScene.modelSize)
            let protoIDs = scene.renderProtoIDs(camera: camera, turn: turn)

            var excluded: DepthMask?
            for id in excludedIDs {
                guard let (det, bank) = SyntheticScene.detection(of: id, protoIDs: protoIDs, bleed: bleed, rng: &rng),
                      let mask = bank.mask(for: det).depthMask(frame: frame) else { continue }
                excluded = excluded.map { $0.union(mask) } ?? mask
            }

            var observations: [BoxObservation] = []
            for object in scene.objects where !excludedIDs.contains(object.id) {
                guard let (det, bank) = SyntheticScene.detection(of: object.id, protoIDs: protoIDs,
                                                                 bleed: bleed, rng: &rng),
                      var mask = bank.mask(for: det).depthMask(frame: frame) else { continue }
                if claimExcludedPixels.contains(object.id), let excluded {
                    mask = mask.union(excluded)
                }
                let role = DetectorVocabulary.role(for: object.name)
                guard let label = role.label else { continue }
                var flat = false
                var category: String?
                if case .target(_, let f, _) = role { flat = f }
                if case .roomPlanCategory(_, let c) = role { category = c }
                guard let lifted = DepthLifter.lift(mask: mask, excluding: useExclusion ? excluded : nil,
                                                    depth: grid, frame: frame, surfaces: scene.surfaces,
                                                    walls: knowsWalls ? scene.walls : [], flat: flat),
                      let observation = BoxObservation(name: object.name, label: label,
                                                       roomPlanCategory: category, score: 0.8,
                                                       points: lifted.points, mask: mask,
                                                       restsOn: lifted.restsOn, hangsFrom: lifted.hangsFrom,
                                                       against: lifted.against,
                                                       wallGrid: wallGrid, flat: flat)
                else { continue }
                observations.append(observation)
                outcome.observationsByObject[object.id, default: 0] += 1
            }
            outcome.fusion.integrate(observations, frame: frame, depth: grid, time: Double(index), wallGrid: wallGrid)
        }
        return outcome
    }

    // MARK: - Comparison

    private struct Errors {
        let centre: Float
        let extents: SIMD3<Float>
        let yawDegrees: Float
        /// Fit centre minus true centre, world axes.
        var shift: SIMD3<Float> = .zero
    }

    /// Errors between a fitted box and the truth, over the box's quarter-turn
    /// symmetry: the extents are compared in whichever of the four equivalent
    /// orientations the fit's yaw is closest to.
    private func errors(_ fit: GravityBox, _ truth: GravityBox) -> Errors {
        var best = Errors(centre: .greatestFiniteMagnitude, extents: .zero, yawDegrees: .greatestFiniteMagnitude)
        for k in 0..<4 {
            let turned = truth.yaw + Float(k) * .pi / 2
            let diff = atan2(sin(fit.yaw - turned), cos(fit.yaw - turned))
            let size = k % 2 == 0 ? truth.size : SIMD3(truth.size.z, truth.size.y, truth.size.x)
            let candidate = Errors(centre: simd_distance(fit.center, truth.center),
                                   extents: simd_abs(fit.size - size),
                                   yawDegrees: abs(diff) * 180 / .pi,
                                   shift: fit.center - truth.center)
            if candidate.yawDegrees < best.yawDegrees { best = candidate }
        }
        return best
    }

    private func describe(_ name: String, _ e: Errors) -> String {
        String(format: "%@: centre %.1f cm (x %+.1f y %+.1f z %+.1f), extents (%.1f, %.1f, %.1f) cm, yaw %.1f°",
               name, e.centre * 100, e.shift.x * 100, e.shift.y * 100, e.shift.z * 100,
               e.extents.x * 100, e.extents.y * 100, e.extents.z * 100, e.yawDegrees)
    }

    /// The furnished room's walk is rendered once and read by every test that
    /// needs it; the frames are seeded, so there is nothing to gain from
    /// rendering them twice.
    private static var walkOutcome: Outcome?

    private func furnishedWalk() -> Outcome {
        if let cached = Self.walkOutcome { return cached }
        let outcome = runWalk(scene: Self.furnishedRoom, views: Self.walk, seed: 20260914)
        Self.walkOutcome = outcome
        return outcome
    }

    // MARK: - Acceptance

    func test_fusedBoxes_matchGroundTruth_acrossAWalk() {
        assertWithinTheBar(furnishedWalk(), "no wall grid")
    }

    func test_fusedBoxes_matchGroundTruth_withTheRoomsWallsKnown() {
        // The phone knows the walls within seconds: their grid, and each one
        // as a plane. The synthetic room's run along x and z, grid 0. The
        // picture hangs 2 cm off one and the bookshelf stands 1 cm from
        // another, so a wall that is taken for background only when the
        // object stands off it is what keeps both.
        let outcome = runWalk(scene: Self.furnishedRoom, views: Self.walk, seed: 20260914, wallGrid: 0,
                              knowsWalls: true)
        assertWithinTheBar(outcome, "wall grid 0, walls known")
    }

    private func assertWithinTheBar(_ outcome: Outcome, _ context: String,
                                    file: StaticString = #filePath, line: UInt = #line) {
        let scene = Self.furnishedRoom
        var report: [String] = []
        var failures: [String] = []
        for object in scene.objects {
            let seen = outcome.observationsByObject[object.id] ?? 0
            XCTAssertGreaterThanOrEqual(seen, 3, "\(object.name) was observed in only \(seen) views",
                                        file: file, line: line)
            let label = DetectorVocabulary.role(for: object.name).label
            guard let track = outcome.fusion.tracks
                .filter({ $0.label == label })
                .max(by: { $0.box.iou(object.box) < $1.box.iou(object.box) }) else {
                failures.append("\(object.name): no track")
                continue
            }
            let e = errors(track.box, object.box)
            let line = describe(object.name, e)
            report.append(line)
            let bigEnough = max(object.box.size.x, object.box.size.z) >= yawMinimumSize
            if e.centre > centreTolerance
                || e.extents.max() > extentTolerance
                || (bigEnough && e.yawDegrees > yawToleranceDegrees) {
                failures.append(line)
            }
        }
        XCTAssertTrue(failures.isEmpty,
                      "\(context), outside tolerance:\n" + failures.joined(separator: "\n")
                      + "\nall:\n" + report.joined(separator: "\n"), file: file, line: line)
        print("[LiveBoxesLiftingTests] \(context): " + report.joined(separator: " | "))
    }

    func test_eachObject_endsAsExactlyOneTrack() {
        let scene = Self.furnishedRoom
        let outcome = furnishedWalk()
        for object in scene.objects {
            let label = DetectorVocabulary.role(for: object.name).label
            let overlapping = outcome.fusion.tracks.filter {
                $0.label == label && $0.box.intersectionVolume(object.box) > 0
            }
            XCTAssertEqual(overlapping.count, 1, "\(object.name) is \(overlapping.count) tracks")
        }
    }

    func test_skippingTracksOutOfView_changesNothingButTheTime() {
        // The walk turns from object to object, so most tracks are out of view
        // in most frames: the skip is exercised on every one of them. Every
        // vote, miss and voxel must match. Boxes match to rounding: a refit sums
        // voxels in dictionary order, which differs between two runs with the
        // SAME settings by up to about 5e-7.
        let skipping = furnishedWalk().fusion.tracks
        var off = FusionParameters()
        off.skipsTracksOutOfView = false
        let visiting = runWalk(scene: Self.furnishedRoom, views: Self.walk, seed: 20260914, fusion: off).fusion.tracks
        XCTAssertEqual(skipping.count, visiting.count)
        for (a, b) in zip(skipping, visiting) {
            XCTAssertEqual(a.label, b.label)
            XCTAssertEqual(a.hits, b.hits, a.label)
            XCTAssertEqual(a.misses, b.misses, a.label)
            XCTAssertEqual(a.voxels.count, b.voxels.count, a.label)
            XCTAssertLessThan(simd_distance(a.box.center, b.box.center), 1e-5, a.label)
            XCTAssertLessThan(simd_length(a.box.size - b.box.size), 1e-5, a.label)
            XCTAssertLessThan(abs(a.box.yaw - b.box.yaw), 1e-5, a.label)
        }
    }

    // MARK: - Honest partial boxes

    func test_oneView_boxCoversOnlyWhatWasSeen() throws {
        let shelf = Self.furnishedRoom.objects[2]
        let scene = SyntheticScene(objects: [shelf])
        let front = SyntheticCamera(eye: SIMD3(-0.54, 1.45, 0.3), target: shelf.box.center, roll: Self.portrait)
        let outcome = runWalk(scene: scene, views: [front], seed: 7)
        let track = try XCTUnwrap(outcome.fusion.tracks.first)
        let e = errors(track.box, shelf.box)
        // Seen face-on, the shelf's depth is unknown: the box must be thin
        // rather than invented, and never larger than the object.
        XCTAssertLessThan(min(track.box.size.x, track.box.size.z), 0.10, describe("shelf", e))
        XCTAssertLessThanOrEqual(max(track.box.size.x, track.box.size.z), 0.80 + extentTolerance)
        XCTAssertLessThanOrEqual(track.box.size.y, 1.80 + extentTolerance)
    }

    func test_moreViews_growThePartialBoxToTheObject() throws {
        let shelf = Self.furnishedRoom.objects[2]
        let scene = SyntheticScene(objects: [shelf])
        let views = [-45, 0, 45].map { (a: Float) -> SyntheticCamera in
            let r = Self.degrees(a)
            return SyntheticCamera(eye: SIMD3(-2.34 + 1.8 * cos(r), 1.45, 0.3 + 1.8 * sin(r)),
                                   target: shelf.box.center, roll: Self.portrait)
        }
        let outcome = runWalk(scene: scene, views: views, seed: 11)
        let track = try XCTUnwrap(outcome.fusion.tracks.first)
        let e = errors(track.box, shelf.box)
        XCTAssertLessThanOrEqual(e.extents.max(), extentTolerance, describe("shelf", e))
    }

    // MARK: - Exclusion

    /// A person standing against the shelf, inside the shelf's own mask.
    private static let shelfWithPerson = SyntheticScene(objects: [
        furnishedRoom.objects[2],
        SyntheticObject(id: 9, name: "person",
                        box: GravityBox(center: SIMD3(-2.02, 0.85, 0.35), size: SIMD3(0.30, 1.70, 0.45), yaw: 0)),
    ])

    private static let shelfViews: [SyntheticCamera] = [Float(-40), 0, 40].map { a in
        let r = degrees(a)
        return SyntheticCamera(eye: SIMD3(-2.34 + 2.0 * cos(r), 1.5, 0.3 + 2.0 * sin(r)),
                               target: SIMD3(-2.34, 0.9, 0.3), roll: portrait)
    }

    func test_excludedPixels_neverShapeAnotherObject() throws {
        let outcome = runWalk(scene: Self.shelfWithPerson, views: Self.shelfViews, seed: 3,
                              exclude: [9], claimExcludedPixels: [2])
        let shelf = Self.shelfWithPerson.objects[0]
        let track = try XCTUnwrap(outcome.fusion.tracks.first { $0.label == "SHELF" })
        XCTAssertFalse(outcome.fusion.tracks.contains { $0.box.contains(SIMD3(-2.02, 1.4, 0.35)) },
                       "a box reaches into the person")
        let e = errors(track.box, shelf.box)
        XCTAssertLessThanOrEqual(e.extents.x, extentTolerance, describe("shelf", e))
    }

    func test_withoutExclusion_thePersonWouldShapeTheShelf() throws {
        // The control: the same frames with the exclusion switched off must
        // fail, or the test above proves nothing.
        let outcome = runWalk(scene: Self.shelfWithPerson, views: Self.shelfViews, seed: 3,
                              exclude: [9], claimExcludedPixels: [2], useExclusion: false)
        let shelf = Self.shelfWithPerson.objects[0]
        let track = try XCTUnwrap(outcome.fusion.tracks.first { $0.label == "SHELF" })
        let e = errors(track.box, shelf.box)
        XCTAssertGreaterThan(e.extents.max(), extentTolerance, describe("shelf", e))
    }

    // MARK: - Surfaces

    /// A picture hanging with its bottom edge at 0.79 m, and a desk top at
    /// 0.76 m across the room.
    private static let picture = GravityBox(center: SIMD3(-0.4, 1.09, -1.98), size: SIMD3(0.90, 0.60, 0.04), yaw: 0)
    private static let deskTop = PlanRectangle(center: SIMD2(1.6, 1.2), axis: SIMD2(1, 0), halfExtents: SIMD2(0.6, 0.35))

    private func pictureRestsOn(_ desk: HorizontalSurface) throws -> Float? {
        let scene = SyntheticScene(objects: [SyntheticObject(id: 0, name: "picture frame", box: Self.picture)],
                                   tops: [desk])
        var rng = SeededGenerator(seed: 12)
        let view = SyntheticCamera(eye: SIMD3(-0.4, 1.3, -0.3), target: Self.picture.center, roll: Self.portrait)
        let frame = scene.frame(camera: view, rng: &rng)
        return try XCTUnwrap(scene.observation(of: 0, in: frame, name: "picture frame", rng: &rng)).restsOn
    }

    func test_aDeskAcrossTheRoom_isNotThePicturesBottom() throws {
        XCTAssertNil(try pictureRestsOn(HorizontalSurface(kind: .support, height: 0.76, extent: Self.deskTop)))
    }

    func test_aSurfaceTakenAsRoomWide_wouldBeThePicturesBottom() throws {
        // The control: the same plane reaching the whole room, as every plane
        // did before extents, must claim the picture — or the test above
        // proves nothing.
        let restsOn = try XCTUnwrap(try pictureRestsOn(HorizontalSurface(kind: .floor, height: 0.76, extent: nil)))
        XCTAssertEqual(restsOn, 0.76, accuracy: 1e-6)
    }

    // MARK: - The maps, against the renderer

    /// With no bleed, the depth mask sampled through production's letterbox,
    /// turn and depth registration must land on the pixels the independent
    /// renderer says the object occupies — for every hold.
    func test_protoMask_landsOnTheObjectsDepthPixels_inEveryHold() throws {
        let scene = Self.furnishedRoom
        let table = scene.objects[0]
        for roll: Float in [0, Self.portrait, -Self.portrait, .pi] {
            var rng = SeededGenerator(seed: 5)
            let camera = SyntheticCamera(eye: SIMD3(0.6, 1.45, 0.9), target: table.box.center, roll: roll)
            let render = scene.renderDepth(camera: camera, rng: &rng)
            let gravity = PoseExtractor.gravityInCameraFrame(simd_quaternion(camera.worldFromCamera))
            let turn = QuarterTurn.upright(gravity: gravity, previous: nil)
            let frame = SensorFrame(intrinsics: SyntheticScene.intrinsics, depthWidth: 256, depthHeight: 192,
                                    worldFromCamera: camera.worldFromCamera, turn: turn,
                                    modelWidth: 640, modelHeight: 640)
            let ids = scene.renderProtoIDs(camera: camera, turn: turn)
            let (det, bank) = try XCTUnwrap(SyntheticScene.detection(of: table.id, protoIDs: ids,
                                                                      bleed: false, rng: &rng))
            let mask = try XCTUnwrap(bank.mask(for: det).depthMask(frame: frame))
            var both = 0, either = 0
            for y in 0..<192 {
                for x in 0..<256 {
                    let truth = render.objectAt[y * 256 + x] == table.id
                    let sampled = mask[x, y]
                    if truth && sampled { both += 1 }
                    if truth || sampled { either += 1 }
                }
            }
            let iou = Float(both) / Float(max(either, 1))
            XCTAssertGreaterThan(iou, 0.85, "roll \(roll): mask IoU \(iou) with turn \(turn)")
        }
    }
}
