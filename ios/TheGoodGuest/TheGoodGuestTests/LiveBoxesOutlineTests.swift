/// The live-boxes chain on what LiDAR sees through: glass furniture boxed from
/// the detector's outlines and the floor (`OutlineBox`), through the same
/// per-detection step the pipeline runs (`DetectorPipeline.observation`).
///
/// On the phone the green glass coffee table (118 × 46 × 56 cm as RoomPlan
/// measured it) was finished at 175 × 52 × 91 cm, a patch of the floor seen
/// through it; with the floor always removed it had no box at all. Here it is
/// a top and two side panels of glass, which the detector outlines and LiDAR
/// does not see, and a glass-topped dining table on one pedestal among chairs.
/// Each walk has a control that lifts from depth alone.

import simd
import XCTest
@testable import TheGoodGuest

final class LiveBoxesOutlineTests: XCTestCase {

    private let centreTolerance: Float = 0.03
    private let extentTolerance: Float = 0.05
    private let yawToleranceDegrees: Float = 5

    private static let portrait: Float = .pi / 2

    // MARK: - The furniture

    private enum Build { case glass, solid }

    /// The green coffee table: a top and two side panels, 118 × 46 × 56 cm,
    /// in the middle of the room.
    private static func coffeeTable(_ build: Build, id: Int = 0,
                                    at position: SIMD3<Float> = .zero) -> SyntheticObject {
        let panels = [GravityBox(center: SIMD3(0, 0.45, 0), size: SIMD3(1.18, 0.02, 0.56), yaw: 0),
                      GravityBox(center: SIMD3(-0.58, 0.22, 0), size: SIMD3(0.02, 0.44, 0.56), yaw: 0),
                      GravityBox(center: SIMD3(0.58, 0.22, 0), size: SIMD3(0.02, 0.44, 0.56), yaw: 0)]
        return build == .solid
            ? SyntheticObject(id: id, name: "glass table", position: position, yaw: 0, parts: panels)
            : SyntheticObject(id: id, name: "glass table", position: position, yaw: 0, parts: [], glass: panels)
    }

    /// Views from `distance` round `target` at eye height, one per azimuth,
    /// the holds alternating.
    private static func around(_ target: SIMD3<Float>, distance: Float, azimuths: [Float]) -> [SyntheticCamera] {
        azimuths.enumerated().map { k, degrees in
            let a = degrees * .pi / 180
            return SyntheticCamera(eye: SIMD3(target.x + distance * cos(a), 1.45, target.z + distance * sin(a)),
                                   target: target, roll: [portrait, 0, -portrait][k % 3])
        }
    }

    private static let coffeeTableCentre = SIMD3<Float>(0, 0.23, 0)
    /// All the way round, a view every 45°.
    private static let roundTheTable = around(coffeeTableCentre, distance: 1.7,
                                              azimuths: [0, 45, 90, 135, 180, 225, 270, 315])
    /// Azimuth 0 is the +x end, and the table's long axis IS x: one view
    /// straight down its length, and one from each end.
    fileprivate static let endOn = around(coffeeTableCentre, distance: 1.7, azimuths: [0])
    fileprivate static let endToEnd = around(coffeeTableCentre, distance: 1.7, azimuths: [0, 180])

    // MARK: - The chain

    /// Every view through the pipeline's own step, for the objects in
    /// `lifting`; every object in the scene is detected, so each mask knows
    /// the others, and — as in the pipeline — only what can hide an object
    /// counts against its outline, unless `everyMaskHides`. A glass object's
    /// mask is its whole outline, as the detector draws it; a solid one's is
    /// what the camera sees of it. Masks are filled and bleed. With `outlines`
    /// off, the control: depth alone.
    private func walk(_ scene: SyntheticScene, views: [SyntheticCamera], lifting: Set<Int>,
                      scores: [Int: Float] = [:], seed: UInt64, outlines: Bool = true,
                      everyMaskHides: Bool = false, forceOutline: Bool = false) -> BoxFusion {
        var rng = SeededGenerator(seed: seed)
        var fusion = BoxFusion()
        for (index, camera) in views.enumerated() {
            let frame = scene.frame(camera: camera, rng: &rng)
            var claims: [Int: (mask: DepthMask, score: Float)] = [:]
            for object in scene.objects {
                let cells = object.isGlass
                    ? scene.silhouetteCells(of: object.id, camera: camera, turn: frame.sensor.turn)
                    : frame.protoIDs.map { $0 == object.id }
                guard let (det, bank) = SyntheticScene.detection(cells: cells, bleed: true, filled: true, rng: &rng),
                      let mask = bank.mask(for: det).depthMask(frame: frame.sensor) else { continue }
                claims[object.id] = (mask, scores[object.id] ?? 0.8)
            }
            let owned = DepthMask.owned(claims)
            var observations: [BoxObservation] = []
            for (id, claim) in claims.sorted(by: { $0.key < $1.key }) where lifting.contains(id) {
                let object = scene.objects.first { $0.id == id }!
                guard let label = DetectorVocabulary.role(for: object.name).label, let own = owned[id] else { continue }
                if outlines {
                    let others = claims.filter { other in
                        other.key != id && (everyMaskHides || scene.objects.contains {
                            $0.id == other.key && DetectorVocabulary.role(for: $0.name).canHide
                        })
                    }.map { $0.value.mask }
                    if case .seen(let o) = DetectorPipeline.observation(
                        name: object.name, label: label, category: nil, score: claim.score, flat: false,
                        mask: claim.mask, own: own, others: others, excluded: nil, depth: frame.depth,
                        frame: frame.sensor, surfaces: scene.surfaces, walls: scene.walls, wallGrid: 0,
                        touchesEdge: false, aimedAt: false, forceOutline: forceOutline) {
                        observations.append(o)
                    }
                } else if let lifted = DepthLifter.lift(mask: own, excluding: nil, depth: frame.depth,
                                                        frame: frame.sensor, surfaces: scene.surfaces,
                                                        walls: scene.walls, flat: false),
                          let o = BoxObservation(name: object.name, label: label, roomPlanCategory: nil,
                                                 score: claim.score, points: lifted.points, mask: claim.mask,
                                                 restsOn: lifted.restsOn, hangsFrom: lifted.hangsFrom,
                                                 against: lifted.against, wallGrid: 0) {
                    observations.append(o)
                }
            }
            fusion.integrate(observations, frame: frame.sensor, depth: frame.depth, time: Double(index), wallGrid: 0)
        }
        return fusion
    }

    /// How far the best track of `object`'s label is from it, as a line, and
    /// whether that is within the bar.
    private func measure(_ fusion: BoxFusion, _ object: SyntheticObject,
                         _ context: String) -> (held: Bool, text: String, track: BoxTrack?) {
        let label = DetectorVocabulary.role(for: object.name).label
        let tracks = fusion.tracks.filter { $0.label == label }
        guard let track = tracks.max(by: { $0.box.iou(object.box) < $1.box.iou(object.box) }) else {
            return (false, "\(context): no \(object.name) track", nil)
        }
        var best = (centre: Float.greatestFiniteMagnitude, extents: SIMD3<Float>.zero, yaw: Float.greatestFiniteMagnitude)
        for k in 0..<4 {
            let turned = object.box.yaw + Float(k) * .pi / 2
            let diff = abs(atan2(sin(track.box.yaw - turned), cos(track.box.yaw - turned))) * 180 / .pi
            let size = k % 2 == 0 ? object.box.size : SIMD3(object.box.size.z, object.box.size.y, object.box.size.x)
            if diff < best.yaw {
                best = (simd_distance(track.box.center, object.box.center), simd_abs(track.box.size - size), diff)
            }
        }
        let shift = (track.box.center - object.box.center) * 100
        let text = String(format: "%@: centre %.1f cm (x %+.1f y %+.1f z %+.1f), extents (%.1f, %.1f, %.1f) cm, "
                          + "yaw %.1f°, box %.0f×%.0f×%.0f cm, %d track(s), seen through %@",
                          context, best.centre * 100, shift.x, shift.y, shift.z, best.extents.x * 100,
                          best.extents.y * 100, best.extents.z * 100, best.yaw, track.box.size.x * 100,
                          track.box.size.y * 100, track.box.size.z * 100, tracks.count,
                          track.isSeenThrough ? "yes" : "no")
        print("[LiveBoxesOutlineTests] " + text)
        return (best.centre <= centreTolerance && best.extents.max() <= extentTolerance
                && best.yaw <= yawToleranceDegrees, text, track)
    }

    // MARK: - Agreement

    func test_theTrueBox_agreesWithItsOwnOutline_andAMovedOrDeeperOneLess() throws {
        let table = Self.coffeeTable(.glass)
        let scene = SyntheticScene(objects: [table])
        var rng = SeededGenerator(seed: 50)
        let camera = Self.roundTheTable[2]
        let frame = scene.frame(camera: camera, rng: &rng)
        let cells = scene.silhouetteCells(of: 0, camera: camera, turn: frame.sensor.turn)
        let (det, bank) = try XCTUnwrap(SyntheticScene.detection(cells: cells, bleed: false, filled: true, rng: &rng))
        let view = OutlineView(mask: try XCTUnwrap(bank.mask(for: det).depthMask(frame: frame.sensor)), others: [],
                               frame: frame.sensor, floor: 0)
        let truth = try XCTUnwrap(OutlineFit.agreement(table.box, view))
        XCTAssertGreaterThan(truth.covered, 0.9)
        XCTAssertGreaterThan(truth.filled, 0.9)
        // Moved, it leaves part of the outline out; deeper, it holds more
        // than the outline, which costs it less.
        let moved = try XCTUnwrap(OutlineFit.agreement(
            GravityBox(center: table.box.center + SIMD3(0.12, 0, 0), size: table.box.size, yaw: 0), view))
        let deeper = try XCTUnwrap(OutlineFit.agreement(
            GravityBox(center: table.box.center, size: table.box.size * SIMD3(1, 1, 1.6), yaw: 0), view))
        XCTAssertLessThan(moved.covered, truth.covered - 0.05)
        XCTAssertLessThan(moved.score, truth.score)
        XCTAssertGreaterThan(deeper.covered, truth.covered - 0.01)
        XCTAssertLessThan(deeper.filled, truth.filled - 0.1)
        XCTAssertLessThan(deeper.score, truth.score)
    }

    func test_whereAnotherObjectIs_anOutlineCannotSayItsOwnIsNot() throws {
        // The same outline, and a box half again as wide; a detection over the
        // extra half says nothing, so there the wider box is not wrong.
        let table = Self.coffeeTable(.glass)
        let scene = SyntheticScene(objects: [table])
        var rng = SeededGenerator(seed: 51)
        let camera = Self.roundTheTable[2]
        let frame = scene.frame(camera: camera, rng: &rng)
        let cells = scene.silhouetteCells(of: 0, camera: camera, turn: frame.sensor.turn)
        let (det, bank) = try XCTUnwrap(SyntheticScene.detection(cells: cells, bleed: false, filled: true, rng: &rng))
        let mask = try XCTUnwrap(bank.mask(for: det).depthMask(frame: frame.sensor))
        let wider = GravityBox(center: table.box.center + SIMD3(0.3, 0, 0), size: table.box.size + SIMD3(0.6, 0, 0),
                               yaw: 0)
        let everywhere = DepthMask(xRange: 0...255, yRange: 0...191) { _, _ in true }
        let alone = OutlineView(mask: mask, others: [], frame: frame.sensor, floor: 0)
        let beside = OutlineView(mask: mask, others: [everywhere], frame: frame.sensor, floor: 0)
        XCTAssertLessThan(try XCTUnwrap(OutlineFit.agreement(wider, alone)).filled, 0.8)
        XCTAssertGreaterThan(try XCTUnwrap(OutlineFit.agreement(wider, beside)).filled, 0.9)
    }

    // MARK: - Glass

    func test_anAllGlassTable_walkedRound_isBoxedFromItsOutlines() {
        let scene = SyntheticScene(objects: [Self.coffeeTable(.glass)])
        let fusion = walk(scene, views: Self.roundTheTable, lifting: [0], seed: 52)
        let result = measure(fusion, scene.objects[0], "all-glass table, walked round")
        XCTAssertTrue(result.held, result.text)
        XCTAssertEqual(result.track?.isSeenThrough, true)
        XCTAssertEqual(fusion.tracks.count, 1)
    }

    func test_anAllGlassTable_fromDepthAlone_hasNoBox() {
        // The control: the same walk lifted from depth alone leaves nothing.
        let scene = SyntheticScene(objects: [Self.coffeeTable(.glass)])
        let fusion = walk(scene, views: Self.roundTheTable, lifting: [0], seed: 52, outlines: false)
        XCTAssertTrue(fusion.tracks.isEmpty, "\(fusion.tracks.map { $0.box.size })")
    }

    func test_anAllGlassTable_seenFromOneSide_isNoPatchOfFloor() {
        // Across 60° only: its height and its width across the views are
        // told by one side; how deep it is, less so.
        let scene = SyntheticScene(objects: [Self.coffeeTable(.glass)])
        let views = Self.around(Self.coffeeTableCentre, distance: 1.7, azimuths: [60, 75, 90, 105, 120])
        let fusion = walk(scene, views: views, lifting: [0], seed: 53)
        let result = measure(fusion, scene.objects[0], "all-glass table, one side")
        guard let box = result.track?.box else { return XCTFail(result.text) }
        XCTAssertEqual(box.size.y, 0.46, accuracy: extentTolerance, result.text)
        XCTAssertEqual(max(box.size.x, box.size.z), 1.18, accuracy: extentTolerance, result.text)
        XCTAssertEqual(box.minY, 0, accuracy: 0.01, "it stands on the floor")
    }

    func test_aSolidTable_isStillBoxedFromItsPoints() {
        // What LiDAR does see keeps its own route: the same table, solid.
        let scene = SyntheticScene(objects: [Self.coffeeTable(.solid)])
        let fusion = walk(scene, views: Self.roundTheTable, lifting: [0], seed: 54)
        let result = measure(fusion, scene.objects[0], "solid table")
        XCTAssertEqual(result.track?.isSeenThrough, false, result.text)
        XCTAssertTrue(result.held, result.text)
    }

    func test_aTableWhoseDepthSeesTheGlass_isBoxedFromItsOutlines_whenForced_andFromItsPointsWhenNot() {
        // What a depth model gives: a glass top is a surface, not the floor seen through.
        let scene = SyntheticScene(objects: [Self.coffeeTable(.solid)])
        let forced = walk(scene, views: Self.roundTheTable, lifting: [0], seed: 69, forceOutline: true)
        let free = walk(scene, views: Self.roundTheTable, lifting: [0], seed: 69)
        let viaOutline = measure(forced, scene.objects[0], "model depth, forced to the outline route")
        let viaPoints = measure(free, scene.objects[0], "model depth, left to the points")
        XCTAssertEqual(viaOutline.track?.isSeenThrough, true, viaOutline.text)
        XCTAssertEqual(viaPoints.track?.isSeenThrough, false, viaPoints.text)
        guard let box = viaOutline.track?.box else { return XCTFail(viaOutline.text) }
        XCTAssertEqual(box.size.y, 0.46, accuracy: extentTolerance, viaOutline.text)
        XCTAssertEqual(max(box.size.x, box.size.z), 1.18, accuracy: extentTolerance, viaOutline.text)
        XCTAssertEqual(box.minY, 0, accuracy: 0.01, "it stands on the floor")
    }

    func test_anAllGlassTable_forcedToTheOutlineRoute_isStillBoxedFromItsOutlines() {
        // The glass-table rule now applies to LiDAR too, where the table is seen through.
        let scene = SyntheticScene(objects: [Self.coffeeTable(.glass)])
        let fusion = walk(scene, views: Self.roundTheTable, lifting: [0], seed: 71, forceOutline: true)
        let result = measure(fusion, scene.objects[0], "all-glass table, forced, LiDAR-like depth")
        XCTAssertTrue(result.held, result.text)
        XCTAssertEqual(result.track?.isSeenThrough, true)
        XCTAssertEqual(fusion.tracks.count, 1)
    }

    func test_aDetectionCutOffByTheFrame_startsABox_whenTheMiddleOfTheScreenIsNotOnIt() throws {
        var rng = SeededGenerator(seed: 70)
        let scene = SyntheticScene(objects: [Self.coffeeTable(.solid)])
        let frame = scene.frame(camera: Self.roundTheTable[0], rng: &rng)
        guard let o = scene.observation(of: 0, in: frame, name: "glass table", rng: &rng) else { return XCTFail("no observation") }
        let cut = BoxObservation(name: o.name, label: o.label, roomPlanCategory: nil, score: 0.8, points: o.points,
                                 mask: o.mask, restsOn: o.restsOn, hangsFrom: o.hangsFrom, against: o.against,
                                 wallGrid: 0, touchesEdge: true, aimedAt: false)
        let aimed = BoxObservation(name: o.name, label: o.label, roomPlanCategory: nil, score: 0.8, points: o.points,
                                   mask: o.mask, restsOn: o.restsOn, hangsFrom: o.hangsFrom, against: o.against,
                                   wallGrid: 0, touchesEdge: true, aimedAt: true)
        var refused = BoxFusion()
        let sightings = refused.integrate([try XCTUnwrap(cut)], frame: frame.sensor, depth: frame.depth, time: 0, wallGrid: 0)
        XCTAssertEqual(sightings, [.cutOff], "as before: not aimed at, not started")
        var started = BoxFusion()
        _ = started.integrate([try XCTUnwrap(aimed)], frame: frame.sensor, depth: frame.depth, time: 0, wallGrid: 0)
        XCTAssertEqual(started.tracks.count, 1, "what startsCutOff makes of every detection")
    }

    // MARK: - Glass among chairs

    /// The glass-topped dining table on its pedestal with a chair pushed in
    /// either side, in the middle of the room.
    private static let diningScene = SyntheticScene(objects: [
        LiveBoxesOpenFurnitureTests.glassDiningTable(id: 0, at: .zero),
        LiveBoxesOpenFurnitureTests.diningChair(id: 1, at: SIMD3(0, 0, -0.55), yaw: 0),
        LiveBoxesOpenFurnitureTests.diningChair(id: 2, at: SIMD3(0.3, 0, 0.55), yaw: .pi),
    ])

    func test_aGlassDiningTableAmongChairs_walkedRound_isBoxedFromItsOutlines() {
        let views = Self.around(SIMD3(0, 0.4, 0), distance: 1.8, azimuths: [0, 45, 90, 135, 180, 225, 270, 315])
        let fusion = walk(Self.diningScene, views: views, lifting: [0, 1, 2], scores: [0: 0.65, 1: 0.93, 2: 0.9],
                          seed: 55)
        let result = measure(fusion, Self.diningScene.objects[0], "glass dining table among chairs")
        XCTAssertTrue(result.held, result.text)
        XCTAssertEqual(result.track?.isSeenThrough, true)
        for chair in Self.diningScene.objects.dropFirst() {
            let chairs = measure(fusion, chair, "dining chair \(chair.id)")
            XCTAssertEqual(chairs.track?.isSeenThrough, false, chairs.text)
        }
    }

    // MARK: - Off the floor

    /// What becomes of an object LiDAR measures nothing of: its depth
    /// blanked under its bleeding, filled outline, seen from `eye`.
    private func blackObject(_ object: SyntheticObject, from eye: SIMD3<Float>, seed: UInt64) throws -> Observed {
        let scene = SyntheticScene(objects: [object])
        var rng = SeededGenerator(seed: seed)
        let camera = SyntheticCamera(eye: eye, target: object.box.center, roll: Self.portrait)
        let frame = scene.frame(camera: camera, rng: &rng)
        let (det, bank) = try XCTUnwrap(SyntheticScene.detection(of: object.id, protoIDs: frame.protoIDs, bleed: true,
                                                                  filled: true, rng: &rng))
        let mask = try XCTUnwrap(bank.mask(for: det).depthMask(frame: frame.sensor))
        var values = frame.depth.depth
        for y in mask.yRange { for x in mask.xRange where mask[x, y] { values[y * frame.depth.width + x] = 0 } }
        let blank = DepthGrid(width: frame.depth.width, height: frame.depth.height, depth: values,
                              confidence: frame.depth.confidence)
        let label = try XCTUnwrap(DetectorVocabulary.role(for: object.name).label)
        return DetectorPipeline.observation(
            name: object.name, label: label, category: nil, score: 0.8, flat: false, mask: mask, own: mask,
            others: [], excluded: nil, depth: blank, frame: frame.sensor, surfaces: scene.surfaces,
            walls: scene.walls, wallGrid: 0, touchesEdge: false, aimedAt: false)
    }

    func test_anOutlineWithNoDepthAndTheWallRoundIt_isNotSeenThrough() throws {
        // A black screen on the wall gives LiDAR nothing, like a black glass
        // top — but the wall is round it, not the floor.
        let screen = SyntheticObject(id: 0, name: "television",
                                     box: GravityBox(center: SIMD3(0, 1.3, -1.97), size: SIMD3(1.2, 0.7, 0.06), yaw: 0))
        guard case .missed(let reason) = try blackObject(screen, from: SIMD3(0.2, 1.45, 0.2), seed: 56) else {
            return XCTFail("a box from the screen's outline")
        }
        XCTAssertEqual(reason, .noDepth)
    }

    func test_anOutlineWithNoDepthAndTheFloorRoundIt_isBoxedFromItsOutline() throws {
        // The control: something as black standing on the floor — the floor
        // is round it — is taken from its outline.
        let ottoman = SyntheticObject(id: 0, name: "footrest",
                                      box: GravityBox(center: SIMD3(0, 0.225, -0.8), size: SIMD3(0.5, 0.45, 0.5), yaw: 0))
        guard case .seen(let observation) = try blackObject(ottoman, from: SIMD3(0.3, 1.45, 0.8), seed: 57) else {
            return XCTFail("no observation of the black ottoman")
        }
        XCTAssertNotNil(observation.outline)
        XCTAssertTrue(observation.points.isEmpty)
        XCTAssertEqual(observation.box.minY, 0, accuracy: 0.01)
    }
}

extension LiveBoxesOutlineTests {

    // MARK: - A rug under the glass

    /// The coffee table on a rug of 2 × 1.4 m, the rug detected too.
    private static let tableOnARug = SyntheticScene(objects: [
        coffeeTable(.glass),
        SyntheticObject(id: 1, name: "carpet",
                        box: GravityBox(center: SIMD3(0, 0.006, 0), size: SIMD3(2.0, 0.012, 1.4), yaw: 0)),
    ])

    func test_aGlassTableOnARug_isBoxedToTheTable() {
        // A rug lies under the table and can never hide it, so where the rug
        // is, the table's outline still says the table is not.
        let fusion = walk(Self.tableOnARug, views: Self.roundTheTable, lifting: [0], seed: 58)
        let result = measure(fusion, Self.tableOnARug.objects[0], "all-glass table on a rug")
        XCTAssertTrue(result.held, result.text)
    }

    func test_aRugTakenForSomethingThatCanHideTheTable_letsItsBoxSpread() {
        // The control: the rug's pixels saying nothing, the box may cover them free.
        let fusion = walk(Self.tableOnARug, views: Self.roundTheTable, lifting: [0], seed: 58, everyMaskHides: true)
        XCTAssertFalse(measure(fusion, Self.tableOnARug.objects[0], "all-glass table on a rug, rug hides").held)
    }

    // MARK: - Two names for one glass table

    /// The glass table's outline in `view`, under `name` at `score`, through
    /// the pipeline's step; `own` is the part of it this detection owns.
    private func outline(_ scene: SyntheticScene, _ frame: SyntheticScene.Frame, mask: DepthMask, own: DepthMask,
                         name: String, score: Float) -> BoxObservation? {
        guard let label = DetectorVocabulary.role(for: name).label,
              case .seen(let o) = DetectorPipeline.observation(
                  name: name, label: label, category: nil, score: score, flat: false, mask: mask, own: own,
                  others: [], excluded: nil, depth: frame.depth, frame: frame.sensor, surfaces: scene.surfaces,
                  walls: scene.walls, wallGrid: 0, touchesEdge: false, aimedAt: false)
        else { return nil }
        return o
    }

    /// The walk round the glass table with the detector naming it twice in
    /// every view: "glass table" and, a cell larger, "cocktail table".
    private func namedTwice(owning: Bool) throws -> BoxFusion {
        let scene = SyntheticScene(objects: [Self.coffeeTable(.glass)])
        var rng = SeededGenerator(seed: 59)
        var fusion = BoxFusion()
        for (index, camera) in Self.roundTheTable.enumerated() {
            let frame = scene.frame(camera: camera, rng: &rng)
            let cells = scene.silhouetteCells(of: 0, camera: camera, turn: frame.sensor.turn)
            let (det, bank) = try XCTUnwrap(SyntheticScene.detection(cells: cells, bleed: false, filled: true,
                                                                      rng: &rng))
            let (wide, wideBank) = try XCTUnwrap(SyntheticScene.detection(cells: cells, bleed: true, filled: true,
                                                                          rng: &rng))
            let masks = [try XCTUnwrap(bank.mask(for: det).depthMask(frame: frame.sensor)),
                         try XCTUnwrap(wideBank.mask(for: wide).depthMask(frame: frame.sensor))]
            let claims: [Int: (mask: DepthMask, score: Float)] = [0: (masks[0], 0.8), 1: (masks[1], 0.6)]
            let own = owning ? DepthMask.owned(claims) : claims.mapValues { $0.mask }
            let observations = [outline(scene, frame, mask: masks[0], own: own[0]!, name: "glass table", score: 0.8),
                                outline(scene, frame, mask: masks[1], own: own[1]!, name: "cocktail table",
                                        score: 0.6)].compactMap { $0 }
            fusion.integrate(observations, frame: frame.sensor, depth: frame.depth, time: Double(index), wallGrid: 0)
        }
        return fusion
    }

    func test_aGlassTableNamedTwiceInEveryView_isOneTrack() throws {
        // The larger outline gives up the shared pixels to the one inside it,
        // as a LiDAR detection would, and is then no second table.
        XCTAssertEqual(try namedTwice(owning: true).tracks.count, 1)
    }

    func test_twoTableNames_areOneTrack_evenWithoutSettlingTheSharedPixels() throws {
        // Every mask keeping every pixel: the table names are one kind in fusion, so the two
        // outlines of one table no longer split it into two tracks.
        XCTAssertEqual(try namedTwice(owning: false).tracks.count, 1)
    }

    // MARK: - An unsure outline where a box stands

    func test_anUnsureOutlineWithinABoxAlreadyThere_startsNothing() throws {
        // A quarter of the table's outline, called a bookshelf at 0.35: its own
        // box is too small to agree with the table's across labels, and it
        // lies within the table's box, so it is no new object. The control:
        // the same outline where nothing stands starts an unsure track.
        let scene = SyntheticScene(objects: [Self.coffeeTable(.glass)])
        let table = walk(scene, views: Self.roundTheTable, lifting: [0], seed: 60)
        XCTAssertEqual(table.tracks.count, 1)
        var rng = SeededGenerator(seed: 61)
        let camera = Self.roundTheTable[2]
        let frame = scene.frame(camera: camera, rng: &rng)
        let cells = scene.silhouetteCells(of: 0, camera: camera, turn: frame.sensor.turn)
        let (det, bank) = try XCTUnwrap(SyntheticScene.detection(cells: cells, bleed: false, filled: true, rng: &rng))
        let whole = try XCTUnwrap(bank.mask(for: det).depthMask(frame: frame.sensor))
        let columns = whole.xRange.lowerBound...(whole.xRange.lowerBound + whole.xRange.count / 4)
        let quarter = DepthMask(xRange: columns, yRange: whole.yRange) { x, y in whole[x, y] }
        let desk = try XCTUnwrap(outline(scene, frame, mask: quarter, own: quarter, name: "bookshelf", score: 0.35))
        var withTable = table
        XCTAssertEqual(withTable.integrate([desk], frame: frame.sensor, depth: frame.depth, time: 20, wallGrid: 0),
                       [.tooUnsure])
        var empty = BoxFusion()
        let alone = empty.integrate([desk], frame: frame.sensor, depth: frame.depth, time: 20, wallGrid: 0)
        XCTAssertEqual(alone, [.started(try XCTUnwrap(empty.tracks.first).id)])
    }

    // MARK: - What LiDAR measured is kept

    func test_anOutlineNoBoxOnTheFloorFits_leavesTheObservationItsPoints() throws {
        // Looking level at the room, an outline all above the horizon meets
        // no floor: no box standing on it can agree. The points LiDAR measured
        // under it stand alone; the control, with none, is no observation.
        let camera = SyntheticCamera(eye: SIMD3(0, 1.45, 1), target: SIMD3(0, 1.45, -1), roll: 0)
        let frame = SensorFrame(intrinsics: SyntheticScene.intrinsics, depthWidth: 256, depthHeight: 192,
                                worldFromCamera: camera.worldFromCamera, turn: .none, modelWidth: 640, modelHeight: 640)
        let high = DepthMask(xRange: 100...156, yRange: 10...40) { _, _ in true }
        let view = OutlineView(mask: high, others: [], frame: frame, floor: 0)
        XCTAssertNil(OutlineFit.fit([view], wallGrid: 0))
        var shade: [SIMD3<Float>] = []
        for i in 0..<4 { for j in 0..<4 { for k in 0..<4 {
            shade.append(SIMD3(-0.2 + Float(i) * 0.13, 1.8 + Float(j) * 0.1, -1.2 + Float(k) * 0.13))
        } } }
        let kept = try XCTUnwrap(BoxObservation(name: "lamp", label: "LAMP", roomPlanCategory: nil, score: 0.8,
                                                points: shade, mask: high, outline: view))
        XCTAssertNil(kept.outline)
        XCTAssertEqual(kept.box.minY, 1.8, accuracy: 0.01)
        XCTAssertNil(BoxObservation(name: "lamp", label: "LAMP", roomPlanCategory: nil, score: 0.8, points: [],
                                    mask: high, outline: view))
    }

    // MARK: - Removing a track

    /// The glass table seen through `outlines` times, then once by LiDAR as
    /// a speck of it: twelve points in one voxel at the middle of its box.
    private func seenThroughThenMeasured(outlines: Int) throws -> BoxFusion {
        let scene = SyntheticScene(objects: [Self.coffeeTable(.glass)])
        var rng = SeededGenerator(seed: 62)
        var fusion = BoxFusion()
        var last: SyntheticScene.Frame?
        for k in 0..<outlines {
            let camera = Self.roundTheTable[2 + k]
            let frame = scene.frame(camera: camera, rng: &rng)
            let cells = scene.silhouetteCells(of: 0, camera: camera, turn: frame.sensor.turn)
            let (det, bank) = try XCTUnwrap(SyntheticScene.detection(cells: cells, bleed: false, filled: true,
                                                                      rng: &rng))
            let mask = try XCTUnwrap(bank.mask(for: det).depthMask(frame: frame.sensor))
            let o = try XCTUnwrap(outline(scene, frame, mask: mask, own: mask, name: "glass table", score: 0.8))
            fusion.integrate([o], frame: frame.sensor, depth: frame.depth, time: Double(k), wallGrid: 0)
            last = frame
        }
        let frame = try XCTUnwrap(last)
        let centre = try XCTUnwrap(fusion.tracks.first).box.center
        let speck = (0..<12).map { centre + SIMD3<Float>(Float($0 % 2) * 0.005, 0, Float($0 / 2 % 2) * 0.005) }
        let rim = try XCTUnwrap(BoxObservation(name: "glass table", label: "TABLE", roomPlanCategory: nil, score: 0.8,
                                               points: speck, mask: DepthMask(xRange: 0...0, yRange: 0...0,
                                                                              bits: [false])))
        fusion.integrate([rim], frame: frame.sensor, depth: frame.depth, time: 10, wallGrid: 0)
        return fusion
    }

    func test_aTrackMostlyMeasured_goesWithItsVoxels_evenWithAnOutline() throws {
        // One outline, then as many LiDAR sightings: its box is its voxels,
        // and too few of them is no object. The control: seen through more
        // often than measured, it is its outlines, and stays.
        XCTAssertTrue(try seenThroughThenMeasured(outlines: 1).tracks.isEmpty)
        XCTAssertEqual(try seenThroughThenMeasured(outlines: 2).tracks.count, 1)
    }
}

extension LiveBoxesOutlineTests {

    // MARK: - End-on, the direction nobody is measuring

    /// THE CASE THAT WAS NEVER TESTED, AND THE REASON THIS SHIPPED GREEN.
    /// Along the direction the camera looks the image says almost nothing: a
    /// metre of extra length costs 0.007 of score where the same metre
    /// sideways costs 0.195, a thirty-fold asymmetry that is pure
    /// perspective. The one-side walk this suite had used runs 60° to 120°,
    /// broadside to the table, where its long axis lies ACROSS the view — the
    /// one geometry this score handles well. End-on, at `50d01172`, a single
    /// view returned 211 × 10 × 81 cm for a true 118 × 46 × 56: a flat slab
    /// lying on the floor and stretching 93 cm past the far end, scoring
    /// 0.975 while it did so.
    func test_aLongGlassTable_seenEndOn_doesNotRunPastItsFarEnd() {
        let scene = SyntheticScene(objects: [Self.coffeeTable(.glass)])
        let table = scene.objects[0]
        let one = measure(walk(scene, views: Self.endOn, lifting: [0], seed: 63), table,
                          "all-glass table, ONE end-on view")
        guard let box = one.track?.box else { return XCTFail(one.text) }
        // One view cannot PIN the length and is not asked to. What it must not
        // do is run away down the view, or lie down as the slab did.
        XCTAssertLessThan(max(box.size.x, box.size.z), 1.45, one.text)
        XCTAssertGreaterThan(box.size.y, 0.3, one.text)
        XCTAssertEqual(box.minY, 0, accuracy: 0.01, one.text)
        XCTAssertEqual(one.track?.outlinesPinned, false, "one end cannot pin the length")

        // From both ends the length is pinned, and then it is right.
        let two = measure(walk(scene, views: Self.endToEnd, lifting: [0], seed: 64), table,
                          "all-glass table, BOTH ends")
        XCTAssertTrue(two.held, two.text)
        XCTAssertEqual(two.track?.outlinesPinned, true, two.text)
    }

    /// End-on, then the far end — the operator's own complaint, that standing
    /// at one end boxes the near end well and runs past the far one, and that
    /// walking to the far end moves the fault to the first. Dwelling at each
    /// end is what the phone does; a new direction is what carries the
    /// information, and `freshRefitEveryNthPass` must not cost that.
    func test_aLongGlassTable_endToEndAndBack_settlesInsteadOfFlipping() {
        let scene = SyntheticScene(objects: [Self.coffeeTable(.glass)])
        let dwelling = Self.around(Self.coffeeTableCentre, distance: 1.7,
                                   azimuths: [0, 0, 0, 180, 180, 180, 0, 0, 180, 180])
        let result = measure(walk(scene, views: dwelling, lifting: [0], seed: 65), scene.objects[0],
                             "all-glass table, end to end and back")
        XCTAssertTrue(result.held, result.text)
    }
}

extension LiveBoxesOutlineTests {

    // MARK: - A glass table the detector also calls a rug

    /// Whether a name's own role makes it a floor covering.
    private static func isFlat(_ name: String) -> Bool {
        if case .target(_, let flat, _) = DetectorVocabulary.role(for: name) { return flat }
        return false
    }

    /// One object the detector names more than once in every view, each name
    /// carrying the flatness its OWN role gives it and `DepthMask.owned`
    /// settling the pixels they share — the pipeline's own loop. A name's
    /// outline is the object's silhouette, as the detector draws it; the
    /// second one bleeds a cell wider, as two detections of one thing do.
    private func walkNamed(_ scene: SyntheticScene, of id: Int,
                           _ named: [(name: String, score: Float, bleed: Bool)],
                           views: [SyntheticCamera], seed: UInt64) throws -> BoxFusion {
        var rng = SeededGenerator(seed: seed)
        var fusion = BoxFusion()
        for (index, camera) in views.enumerated() {
            let frame = scene.frame(camera: camera, rng: &rng)
            let object = scene.objects.first { $0.id == id }!
            let cells = object.isGlass
                ? scene.silhouetteCells(of: id, camera: camera, turn: frame.sensor.turn)
                : frame.protoIDs.map { $0 == id }
            var claims: [Int: (mask: DepthMask, score: Float)] = [:]
            for (k, n) in named.enumerated() {
                guard let (det, bank) = SyntheticScene.detection(cells: cells, bleed: n.bleed, filled: true,
                                                                 rng: &rng),
                      let mask = bank.mask(for: det).depthMask(frame: frame.sensor) else { continue }
                claims[k] = (mask, n.score)
            }
            let owned = DepthMask.owned(claims)
            // As the pipeline does: only a name that can hide an object counts
            // against another's outline, and a floor covering hides nothing.
            let hiding = claims.filter { !Self.isFlat(named[$0.key].name) }.mapValues(\.mask)
            var observations: [BoxObservation] = []
            for (k, n) in named.enumerated() {
                guard let claim = claims[k], let own = owned[k],
                      let label = DetectorVocabulary.role(for: n.name).label else { continue }
                if case .seen(let o) = DetectorPipeline.observation(
                    name: n.name, label: label, category: nil, score: n.score,
                    flat: Self.isFlat(n.name), mask: claim.mask, own: own,
                    others: hiding.filter { $0.key != k }.map(\.value), excluded: nil,
                    depth: frame.depth, frame: frame.sensor, surfaces: scene.surfaces,
                    walls: scene.walls, wallGrid: 0, touchesEdge: false, aimedAt: false) {
                    observations.append(o)
                }
            }
            fusion.integrate(observations, frame: frame.sensor, depth: frame.depth, time: Double(index),
                             wallGrid: 0)
        }
        return fusion
    }

    /// THE GREEN TABLE WAS OFFERED AS A RUG. On the phone (the 03:10 glass
    /// walk) one coffee table carried two tracks: `TABLE glass table 0.76,
    /// 120 x 42 x 60, seen through` and `RUG carpet 0.81, 154 x 47 x 131`.
    /// The rug scored HIGHER, so that is the one the person was offered, and
    /// the log shows them finishing "RUG" — a floor covering 47 cm tall.
    ///
    /// Through the glass the detector sees floor, so it also fires carpet on
    /// the table's own silhouette; `DetectorVocabulary` calls those names
    /// flat, and a flat name was barred from the outline route, so it went
    /// down the lifter, lifted the floor it was standing over and grew. Here
    /// `DepthMask.owned` leaves the carpet 3 % of its own mask — the bleed
    /// rim — and a detection another name owns is no second object.
    func test_aGlassTableTheDetectorAlsoCallsARug_isOneTableAndNoRug() throws {
        let scene = SyntheticScene(objects: [Self.coffeeTable(.glass)])
        let fusion = try walkNamed(scene, of: 0,
                                   [(name: "glass table", score: 0.76, bleed: false),
                                    (name: "carpet", score: 0.81, bleed: true)],
                                   views: Self.roundTheTable, seed: 66)
        XCTAssertEqual(fusion.tracks.count, 1, "\(fusion.tracks.map { "\($0.label) \($0.box.size)" })")
        XCTAssertEqual(fusion.tracks.first?.label, "TABLE")
        let result = measure(fusion, scene.objects[0], "glass table also called a rug")
        XCTAssertTrue(result.held, result.text)
        XCTAssertEqual(result.track?.isSeenThrough, true)
    }

    /// THE CONTROL THE FIX HAS TO SURVIVE: a real floor covering is still a
    /// floor covering. `FloorShare.seenThrough` cannot tell a rug from a
    /// glass table from one view — a rug's own surface lies within the floor's
    /// support band, so `under` is about 1.0 for both — so what keeps rugs out
    /// of the outline route is only their name. The name is kept here, because
    /// the geometry agrees with it.
    func test_aRealRug_isStillBoxedAsAFloorCovering() throws {
        let rug = SyntheticObject(id: 0, name: "carpet",
                                  box: GravityBox(center: SIMD3(0, 0.006, 0), size: SIMD3(2.0, 0.012, 1.4),
                                                  yaw: 0))
        let scene = SyntheticScene(objects: [rug])
        let fusion = try walkNamed(scene, of: 0, [(name: "carpet", score: 0.81, bleed: true)],
                                   views: Self.around(SIMD3(0, 0.006, 0), distance: 1.7,
                                                      azimuths: [0, 45, 90, 135, 180, 225, 270, 315]),
                                   seed: 67)
        let track = try XCTUnwrap(fusion.tracks.first { $0.label == "RUG" },
                                 "\(fusion.tracks.map { $0.label })")
        // It lies on the floor and is boxed from its points, not its outline.
        XCTAssertLessThan(track.box.size.y, DetectorPipeline.floorCoveringRise, "\(track.box.size)")
        XCTAssertEqual(track.box.minY, 0, accuracy: 0.03)
        XCTAssertEqual(track.isSeenThrough, false)
        XCTAssertEqual(max(track.box.size.x, track.box.size.z), 2.0, accuracy: extentTolerance,
                       "\(track.box.size)")
    }

    /// A FLAT NAME TOO FAR OFF THE FLOOR LOSES THE NAME, NOT THE OBJECT. A
    /// 30 cm pile is not a floor covering whatever the detector calls it, so
    /// it stops being lifted as a sheet — but it is still something, and it
    /// keeps its box.
    func test_aFlatNameTooFarOffTheFloor_keepsItsObject() throws {
        let pile = SyntheticObject(id: 0, name: "carpet",
                                   box: GravityBox(center: SIMD3(0, 0.15, 0), size: SIMD3(2.0, 0.30, 1.4),
                                                   yaw: 0))
        let scene = SyntheticScene(objects: [pile])
        let fusion = try walkNamed(scene, of: 0, [(name: "carpet", score: 0.81, bleed: true)],
                                   views: Self.around(SIMD3(0, 0.15, 0), distance: 1.7,
                                                       azimuths: [0, 45, 90, 135, 180, 225, 270, 315]),
                                   seed: 68)
        let track = try XCTUnwrap(fusion.tracks.first, "the object went away with its name")
        XCTAssertEqual(track.box.size.y, 0.30, accuracy: extentTolerance, "\(track.box.size)")
    }
}

private extension SyntheticObject {
    /// Whether the detector outlines more of it than LiDAR sees.
    var isGlass: Bool { maskParts != nil }
}
