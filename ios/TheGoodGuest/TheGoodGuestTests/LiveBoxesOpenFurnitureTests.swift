/// The live-boxes lifting chain on the furniture the phone got wrong: open
/// objects whose detector masks cover what is seen through them, and objects
/// with something standing in front of them.
///
/// On the phone a white armchair 25 cm from a wall was boxed 91 cm deep, and
/// a sofa's box ran forward into the glass table in front of it. A real mask
/// of a chair covers the floor between its legs and the wall between its
/// slats; the floor spans every depth from the chair to the wall, so nothing
/// that splits by depth alone can tell the wall from the chair. These scenes
/// build that: a slatted armchair from legs, seat, slats and arms, a sofa with
/// a glass-topped table whose frame stands inside the sofa's mask, and masks
/// filled to the convex hull of each silhouette.
///
/// The bar is the lifting tests' bar — centre 3 cm, extents 5 cm, yaw 5° —
/// with the room's walls known, as they are on the phone within seconds.
///
/// And a glass dining table with chairs pushed in: on the phone its "table"
/// boxes were chair-shaped, 88–97 cm tall, because LiDAR saw nothing of the
/// glass and the chairs inside the table's mask became the table.

import simd
import XCTest
@testable import TheGoodGuest

final class LiveBoxesOpenFurnitureTests: XCTestCase {

    private let centreTolerance: Float = 0.03
    private let extentTolerance: Float = 0.05
    private let yawToleranceDegrees: Float = 5

    private static func degrees(_ d: Float) -> Float { d * .pi / 180 }
    private static let portrait: Float = .pi / 2

    // MARK: - The furniture

    /// A monobloc-style armchair: four legs, a seat, five back slats under a
    /// top rail, two arms on posts. 56 × 90 × 51 cm.
    static func armchair(id: Int, at position: SIMD3<Float>, yaw: Float) -> SyntheticObject {
        var parts: [GravityBox] = []
        for x: Float in [-0.24, 0.24] {
            for z: Float in [-0.23, 0.23] {
                parts.append(GravityBox(center: SIMD3(x, 0.21, z), size: SIMD3(0.04, 0.42, 0.04), yaw: 0))
            }
        }
        parts.append(GravityBox(center: SIMD3(0, 0.44, 0), size: SIMD3(0.52, 0.04, 0.50), yaw: 0))
        for x: Float in [-0.22, -0.11, 0, 0.11, 0.22] {
            parts.append(GravityBox(center: SIMD3(x, 0.65, -0.245), size: SIMD3(0.06, 0.38, 0.03), yaw: 0))
        }
        parts.append(GravityBox(center: SIMD3(0, 0.87, -0.245), size: SIMD3(0.56, 0.06, 0.03), yaw: 0))
        for x: Float in [-0.26, 0.26] {
            parts.append(GravityBox(center: SIMD3(x, 0.655, 0), size: SIMD3(0.04, 0.03, 0.46), yaw: 0))
            parts.append(GravityBox(center: SIMD3(x, 0.555, 0.215), size: SIMD3(0.03, 0.19, 0.03), yaw: 0))
        }
        return SyntheticObject(id: id, name: "chair", position: position, yaw: yaw, parts: parts)
    }

    /// A three-seat sofa: seat block, back, two arms. 160 × 85 × 85 cm.
    static func sofa(id: Int, at position: SIMD3<Float>) -> SyntheticObject {
        SyntheticObject(id: id, name: "couch", position: position, yaw: 0, parts: [
            GravityBox(center: SIMD3(0, 0.21, 0), size: SIMD3(1.60, 0.42, 0.85), yaw: 0),
            GravityBox(center: SIMD3(0, 0.635, -0.325), size: SIMD3(1.60, 0.43, 0.20), yaw: 0),
            GravityBox(center: SIMD3(-0.71, 0.52, 0), size: SIMD3(0.18, 0.20, 0.85), yaw: 0),
            GravityBox(center: SIMD3(0.71, 0.52, 0), size: SIMD3(0.18, 0.20, 0.85), yaw: 0),
        ])
    }

    /// A glass-topped table: LiDAR and the eye both see through the top, so
    /// only the metal frame is solid.
    static func glassTable(id: Int, at position: SIMD3<Float>) -> SyntheticObject {
        var parts: [GravityBox] = []
        for x: Float in [-0.48, 0.48] {
            for z: Float in [-0.18, 0.18] {
                parts.append(GravityBox(center: SIMD3(x, 0.20, z), size: SIMD3(0.04, 0.40, 0.04), yaw: 0))
            }
        }
        for z: Float in [-0.18, 0.18] {
            parts.append(GravityBox(center: SIMD3(0, 0.385, z), size: SIMD3(1.0, 0.03, 0.03), yaw: 0))
        }
        for x: Float in [-0.485, 0.485] {
            parts.append(GravityBox(center: SIMD3(x, 0.385, 0), size: SIMD3(0.03, 0.03, 0.36), yaw: 0))
        }
        return SyntheticObject(id: id, name: "cocktail table", position: position, yaw: 0, parts: parts)
    }

    /// An armless dining chair: four legs, a seat, a solid back. 45 × 93 × 45 cm.
    static func diningChair(id: Int, at position: SIMD3<Float>, yaw: Float) -> SyntheticObject {
        var parts: [GravityBox] = []
        for x: Float in [-0.19, 0.19] {
            for z: Float in [-0.19, 0.19] {
                parts.append(GravityBox(center: SIMD3(x, 0.225, z), size: SIMD3(0.03, 0.45, 0.03), yaw: 0))
            }
        }
        parts.append(GravityBox(center: SIMD3(0, 0.47, 0), size: SIMD3(0.42, 0.04, 0.42), yaw: 0))
        parts.append(GravityBox(center: SIMD3(0, 0.72, -0.195), size: SIMD3(0.42, 0.42, 0.03), yaw: 0))
        return SyntheticObject(id: id, name: "chair", position: position, yaw: yaw, parts: parts)
    }

    /// A glass-topped dining table on one pedestal: LiDAR sees the pedestal
    /// and its foot, the detector outlines the glass as well.
    static func glassDiningTable(id: Int, at position: SIMD3<Float>) -> SyntheticObject {
        SyntheticObject(id: id, name: "kitchen table", position: position, yaw: 0, parts: [
            GravityBox(center: SIMD3(0, 0.37, 0), size: SIMD3(0.08, 0.70, 0.08), yaw: 0),
            GravityBox(center: SIMD3(0, 0.015, 0), size: SIMD3(0.5, 0.03, 0.5), yaw: 0),
        ], glass: [GravityBox(center: SIMD3(0, 0.735, 0), size: SIMD3(1.2, 0.03, 0.8), yaw: 0)])
    }

    /// A floor lamp: a round base, a pole 3 cm thick and a shade. 40 × 160 × 40 cm.
    static func floorLamp(id: Int, at position: SIMD3<Float>) -> SyntheticObject {
        SyntheticObject(id: id, name: "lamp", position: position, yaw: 0, parts: [
            GravityBox(center: SIMD3(0, 0.015, 0), size: SIMD3(0.30, 0.03, 0.30), yaw: 0),
            GravityBox(center: SIMD3(0, 0.66, 0), size: SIMD3(0.03, 1.26, 0.03), yaw: 0),
            GravityBox(center: SIMD3(0, 1.43, 0), size: SIMD3(0.40, 0.34, 0.40), yaw: 0),
        ])
    }

    /// The lamp with its shade 10 cm from the back wall, and one 20 cm off it.
    private static let lampScene = SyntheticScene(objects: [floorLamp(id: 0, at: SIMD3(-1.0, 0, -1.7))])
    private static let lampFurtherOutScene = SyntheticScene(objects: [floorLamp(id: 0, at: SIMD3(-1.0, 0, -1.6))])

    /// The armchair with its back 25 cm from the room's back wall (z = −2).
    private static let chairScene = SyntheticScene(objects: [
        armchair(id: 0, at: SIMD3(0.4, 0, -1.49), yaw: 0),
    ])

    /// The sofa 7.5 cm off the back wall, the glass table 32.5 cm in front of it.
    private static let sofaScene = SyntheticScene(objects: [
        sofa(id: 0, at: SIMD3(-0.3, 0, -1.5)),
        glassTable(id: 1, at: SIMD3(-0.3, 0, -0.55)),
    ])

    private static func around(_ c: SIMD3<Float>, distance: Float, azimuths: [Float],
                               height: Float = 1.45, rolls: [Float]) -> [SyntheticCamera] {
        zip(azimuths, rolls).map { azimuth, roll in
            let a = degrees(azimuth)
            return SyntheticCamera(eye: SIMD3(c.x + distance * cos(a), height, c.z + distance * sin(a)),
                                   target: c, roll: roll)
        }
    }

    /// The glass table with a chair pushed in on the far side and one on the near side.
    private static let diningScene = SyntheticScene(objects: [
        glassDiningTable(id: 0, at: SIMD3(0, 0, -1.0)),
        diningChair(id: 1, at: SIMD3(0, 0, -1.55), yaw: 0),
        diningChair(id: 2, at: SIMD3(0.3, 0, -0.45), yaw: .pi),
    ])

    /// Someone walking past in front of it: five views across 60°.
    private static let chairViews = around(SIMD3(0.4, 0.45, -1.49), distance: 1.7,
                                           azimuths: [60, 75, 90, 105, 120],
                                           rolls: [portrait, 0, -portrait, portrait, 0])
    /// Across the room from it, from one end to the other — the arc the phone
    /// covered around the real sofa — with the glass table in between.
    private static let sofaViews = around(SIMD3(-0.3, 0.42, -1.5), distance: 2.2,
                                          azimuths: [30, 60, 90, 120, 150],
                                          rolls: [portrait, 0, -portrait, portrait, 0])

    private static let lampViews = around(SIMD3(-1.0, 0.9, -1.7), distance: 2.0,
                                          azimuths: [60, 75, 90, 105, 120],
                                          rolls: [portrait, 0, -portrait, portrait, 0])
    private static let diningViews = around(SIMD3(0, 0.5, -1.0), distance: 2.2,
                                            azimuths: [50, 70, 90, 110, 130],
                                            rolls: [portrait, 0, -portrait, portrait, 0])

    // MARK: - The chain

    /// Every view through the production chain for the objects named in
    /// `lifting`, with filled, bleeding masks.
    private func walk(_ scene: SyntheticScene, views: [SyntheticCamera], lifting: [Int], seed: UInt64,
                      knowsWalls: Bool = true, wallGrid: Float? = 0,
                      lift parameters: DepthLiftParameters = DepthLiftParameters()) -> BoxFusion {
        var rng = SeededGenerator(seed: seed)
        var fusion = BoxFusion()
        for (index, camera) in views.enumerated() {
            let frame = scene.frame(camera: camera, rng: &rng)
            var observations: [BoxObservation] = []
            for id in lifting {
                let object = scene.objects[id]
                guard let (det, bank) = SyntheticScene.detection(of: id, protoIDs: frame.protoIDs, bleed: true,
                                                                 filled: true, rng: &rng),
                      let mask = bank.mask(for: det).depthMask(frame: frame.sensor),
                      let label = DetectorVocabulary.role(for: object.name).label,
                      let lifted = DepthLifter.lift(mask: mask, excluding: nil, depth: frame.depth,
                                                    frame: frame.sensor, surfaces: scene.surfaces,
                                                    walls: knowsWalls ? scene.walls : [], flat: false,
                                                    parameters: parameters),
                      let observation = BoxObservation(name: object.name, label: label, roomPlanCategory: nil,
                                                       score: 0.8, points: lifted.points, mask: mask,
                                                       restsOn: lifted.restsOn, hangsFrom: lifted.hangsFrom,
                                                       against: lifted.against,
                                                       wallGrid: wallGrid)
                else { continue }
                observations.append(observation)
            }
            fusion.integrate(observations, frame: frame.sensor, depth: frame.depth, time: Double(index),
                             wallGrid: wallGrid)
        }
        return fusion
    }

    /// Whether the best track of `object` is within the bar, and the line that says how far off it is.
    private func measure(_ fusion: BoxFusion, _ object: SyntheticObject, _ context: String) -> (held: Bool, text: String) {
        let label = DetectorVocabulary.role(for: object.name).label
        let tracks = fusion.tracks.filter { $0.label == label }
        guard let track = tracks.max(by: { $0.box.iou(object.box) < $1.box.iou(object.box) }) else {
            return (false, "\(context): no \(object.name) track")
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
        let text = String(format: "%@: centre %.1f cm (x %+.1f y %+.1f z %+.1f), extents (%.1f, %.1f, %.1f) cm, yaw %.1f°, box %.0f×%.0f×%.0f cm, %d track(s)",
                          context, best.centre * 100, shift.x, shift.y, shift.z, best.extents.x * 100,
                          best.extents.y * 100, best.extents.z * 100, best.yaw, track.box.size.x * 100,
                          track.box.size.y * 100, track.box.size.z * 100, tracks.count)
        print("[LiveBoxesOpenFurnitureTests] " + text)
        return (best.centre <= centreTolerance && best.extents.max() <= extentTolerance
                && best.yaw <= yawToleranceDegrees, text)
    }

    private func assertWithinTheBar(_ fusion: BoxFusion, _ object: SyntheticObject, _ context: String,
                                    file: StaticString = #filePath, line: UInt = #line) {
        let result = measure(fusion, object, context)
        XCTAssertTrue(result.held, result.text, file: file, line: line)
    }

    /// Lifting with every point one piece: what cutting into pieces removes.
    private var uncut: DepthLiftParameters {
        var p = DepthLiftParameters()
        p.componentCell = 10
        return p
    }

    // MARK: - Seen through

    func test_anArmchairBeforeAWall_isBoxedToTheChair_notToTheWall() {
        let fusion = walk(Self.chairScene, views: Self.chairViews, lifting: [0], seed: 1)
        assertWithinTheBar(fusion, Self.chairScene.objects[0], "armchair, walls known")
    }

    func test_anArmchairBeforeAWallARKitHasNotFound_isStillBoxedToTheChair() {
        // Before ARKit reports the wall as a plane, the wall is still further
        // back than anything connected to the chair.
        let fusion = walk(Self.chairScene, views: Self.chairViews, lifting: [0], seed: 1, knowsWalls: false)
        assertWithinTheBar(fusion, Self.chairScene.objects[0], "armchair, walls unknown")
    }

    func test_withoutCuttingIntoPieces_theUnfoundWallShapesTheArmchair() {
        // The control: the same frames, the wall unknown and nothing cut into
        // pieces, must fail — or the test above proves nothing.
        let fusion = walk(Self.chairScene, views: Self.chairViews, lifting: [0], seed: 1, knowsWalls: false,
                          lift: uncut)
        XCTAssertFalse(measure(fusion, Self.chairScene.objects[0], "armchair, uncut control").held)
    }

    // MARK: - Slender

    func test_aFloorLampBeforeAWallARKitHasNotFound_isBoxedToTheLamp() {
        // Around the pole the mask is mostly wall, and that patch of wall can
        // outnumber the shade's points: the lamp is the nearest piece, not
        // the largest.
        let fusion = walk(Self.lampFurtherOutScene, views: Self.lampViews, lifting: [0], seed: 4, knowsWalls: false)
        assertWithinTheBar(fusion, Self.lampFurtherOutScene.objects[0], "floor lamp 20 cm off a wall, walls unknown")
        XCTAssertEqual(fusion.tracks.filter { $0.label == "LAMP" }.count, 1, "a patch of wall boxed as a lamp")
    }

    func test_withTheLargestPieceInstead_aPatchOfWallIsBoxedAsALamp() {
        // The control: the same frames, the largest piece always the object.
        // Where the wall outnumbers the shade, the wall becomes a second lamp.
        var largest = DepthLiftParameters()
        largest.substantialPiece = 1
        let fusion = walk(Self.lampFurtherOutScene, views: Self.lampViews, lifting: [0], seed: 4, knowsWalls: false,
                          lift: largest)
        XCTAssertGreaterThan(fusion.tracks.filter { $0.label == "LAMP" }.count, 1)
    }

    func test_aFloorLampCloseToAKnownWall_isBoxedToTheLamp() {
        // 10 cm from the wall, LiDAR's flying pixels fill the gap; with the
        // wall known they are its sheet, which joins no two pieces.
        let fusion = walk(Self.lampScene, views: Self.lampViews, lifting: [0], seed: 4)
        assertWithinTheBar(fusion, Self.lampScene.objects[0], "floor lamp 10 cm off a wall, walls known")
    }

    // MARK: - Glass among chairs

    /// The dining walk as the pipeline runs it: every object's mask, the
    /// table's glass outlined, contested pixels settled when `owning`.
    private func diningWalk(owning: Bool, seed: UInt64) -> BoxFusion {
        let scene = Self.diningScene
        let scores: [Int: Float] = [0: 0.65, 1: 0.93, 2: 0.90]
        var rng = SeededGenerator(seed: seed)
        var fusion = BoxFusion()
        for (index, camera) in Self.diningViews.enumerated() {
            let frame = scene.frame(camera: camera, rng: &rng)
            var claims: [Int: (mask: DepthMask, score: Float)] = [:]
            for object in scene.objects {
                let cells = object.id == 0
                    ? scene.silhouetteCells(of: 0, camera: camera, turn: frame.sensor.turn)
                    : frame.protoIDs.map { $0 == object.id }
                guard let (det, bank) = SyntheticScene.detection(cells: cells, bleed: true, filled: true, rng: &rng),
                      let mask = bank.mask(for: det).depthMask(frame: frame.sensor) else { continue }
                claims[object.id] = (mask, scores[object.id]!)
            }
            let owned = owning ? DepthMask.owned(claims) : claims.mapValues(\.mask)
            var observations: [BoxObservation] = []
            for (id, claim) in claims.sorted(by: { $0.key < $1.key }) {
                let object = scene.objects[id]
                guard let label = DetectorVocabulary.role(for: object.name).label,
                      let lifted = DepthLifter.lift(mask: owned[id]!, excluding: nil, depth: frame.depth,
                                                    frame: frame.sensor, surfaces: scene.surfaces,
                                                    walls: scene.walls, flat: false),
                      let observation = BoxObservation(name: object.name, label: label, roomPlanCategory: nil,
                                                       score: claim.score, points: lifted.points, mask: claim.mask,
                                                       restsOn: lifted.restsOn, hangsFrom: lifted.hangsFrom,
                                                       against: lifted.against, wallGrid: 0)
                else { continue }
                observations.append(observation)
            }
            fusion.integrate(observations, frame: frame.sensor, depth: frame.depth, time: Double(index), wallGrid: 0)
        }
        return fusion
    }

    /// The largest share of a chair's true box that any table track's box takes in.
    private func tableTakesInAChair(_ fusion: BoxFusion, _ context: String) -> Float {
        let tableLabel = DetectorVocabulary.role(for: "kitchen table").label
        let chairs = Self.diningScene.objects.filter { $0.name == "chair" }
        var worst: Float = 0
        var boxes: [String] = []
        for track in fusion.tracks where track.label == tableLabel {
            boxes.append(String(format: "%.0f×%.0f×%.0f cm", track.box.size.x * 100, track.box.size.y * 100,
                                track.box.size.z * 100))
            for chair in chairs {
                worst = max(worst, track.box.intersectionVolume(chair.box) / chair.box.volume)
            }
        }
        print("[LiveBoxesOpenFurnitureTests] \(context): table boxes \(boxes), most of a chair taken in \(worst)")
        return worst
    }

    func test_aGlassTableAmongChairs_isNotBoxedFromTheChairs() {
        XCTAssertLessThan(tableTakesInAChair(diningWalk(owning: true, seed: 5), "glass table, owning"), 0.2)
    }

    func test_withoutSettlingContestedPixels_theGlassTableIsBoxedFromAChair() {
        // The control: the same frames with every mask keeping every pixel.
        XCTAssertGreaterThanOrEqual(tableTakesInAChair(diningWalk(owning: false, seed: 5), "glass table, control"), 0.2)
    }

    // MARK: - A dining table with things on it

    /// A solid dark-topped dining table on one pedestal, 140 × 75 × 80 cm.
    static func darkDiningTable(id: Int, at position: SIMD3<Float>) -> SyntheticObject {
        SyntheticObject(id: id, name: "kitchen table", position: position, yaw: 0, parts: [
            GravityBox(center: SIMD3(0, 0.36, 0), size: SIMD3(0.08, 0.68, 0.08), yaw: 0),
            GravityBox(center: SIMD3(0, 0.015, 0), size: SIMD3(0.5, 0.03, 0.5), yaw: 0),
            GravityBox(center: SIMD3(0, 0.735, 0), size: SIMD3(1.4, 0.03, 0.8), yaw: 0),
        ])
    }

    /// The table with three tall things standing on it: its mask takes them in, so the
    /// median point of the mask is above the table's own top.
    private static let cluttered: SyntheticScene = {
        let top = GravityBox(center: SIMD3(0, 0.735, -1.0), size: SIMD3(1.4, 0.03, 0.8), yaw: 0)
        let things = [-0.45, 0, 0.45].enumerated().map { i, x in
            SyntheticObject(id: 1 + i, name: "vase",
                            box: GravityBox(center: SIMD3(Float(x), 0.95, -1.0), size: SIMD3(0.3, 0.4, 0.3), yaw: 0))
        }
        return SyntheticScene(objects: [darkDiningTable(id: 0, at: SIMD3(0, 0, -1.0))] + things,
                              tops: [SyntheticScene.top(of: top)])
    }()

    private func clutteredTableBox(ownTop: Bool) -> GravityBox? {
        var rng = SeededGenerator(seed: 11)
        var fusion = BoxFusion()
        for (index, camera) in Self.diningViews.enumerated() {
            let frame = Self.cluttered.frame(camera: camera, rng: &rng)
            guard let observation = Self.cluttered.observation(of: [0, 1, 2, 3], in: frame, name: "kitchen table",
                                                              ownTop: ownTop, rng: &rng) else { continue }
            fusion.integrate([observation], frame: frame.sensor, depth: frame.depth, time: Double(index), wallGrid: 0)
        }
        let box = fusion.tracks.max { $0.hits < $1.hits }?.box
        print("[LiveBoxesOpenFurnitureTests] table with things on it, ownTop \(ownTop): "
              + (box.map { String(format: "%.0f×%.0f×%.0f cm", $0.size.x * 100, $0.size.y * 100, $0.size.z * 100) } ?? "no box"))
        return box
    }

    func test_aTableWithThingsOnIt_keepsItsOwnTop_soItsBoxIsTableSized() throws {
        let box = try XCTUnwrap(clutteredTableBox(ownTop: true))
        let widest = max(box.size.x, box.size.z)
        XCTAssertGreaterThan(widest, 1.2, "the top is in the box, not only the pedestal")
    }

    func test_theSameTable_withoutKeepingItsTop_isBoxedAsTheThingsOnIt() throws {
        // The control, and the fault seen on the phone: the median point is above the top, so the
        // top counts as a surface to stand on and is taken away, leaving a vase-sized box.
        let box = try XCTUnwrap(clutteredTableBox(ownTop: false))
        XCTAssertLessThan(max(box.size.x, box.size.z), 0.6)
    }

    // MARK: - In front

    // MARK: - Why a mask gives no points

    private enum Build { case glass, post, solid }

    /// A display case 35 cm off the back wall, 1.6 m from the camera: glass
    /// all through, glass round one solid post, or solid. Through the glass
    /// the camera sees the wall behind it and the floor under it.
    private static func displayCase(_ build: Build) -> SyntheticScene {
        let body = GravityBox(center: SIMD3(0, 0.5, 0), size: SIMD3(0.8, 1.0, 0.4), yaw: 0)
        let post = GravityBox(center: SIMD3(0, 0.45, 0.1), size: SIMD3(0.06, 0.9, 0.06), yaw: 0)
        let at = SIMD3<Float>(0, 0, -1.45)
        let object: SyntheticObject
        switch build {
        case .glass: object = SyntheticObject(id: 0, name: "cabinet", position: at, yaw: 0, parts: [], glass: [body])
        case .post:  object = SyntheticObject(id: 0, name: "cabinet", position: at, yaw: 0, parts: [post], glass: [body])
        case .solid: object = SyntheticObject(id: 0, name: "cabinet", position: at, yaw: 0, parts: [body])
        }
        return SyntheticScene(objects: [object])
    }

    private static let displayCaseView = SyntheticCamera(eye: SIMD3(0, 1.45, 0.15), target: SIMD3(0, 0.5, -1.45),
                                                         roll: portrait)

    /// The green glass coffee table on the phone — a top and two side panels,
    /// 118 × 46 × 56 cm as RoomPlan measured it — in the open, glass or solid.
    /// Through the glass the camera sees only the floor.
    private static func coffeeTable(_ build: Build) -> SyntheticScene {
        let panels = [GravityBox(center: SIMD3(0, 0.45, 0), size: SIMD3(1.18, 0.02, 0.56), yaw: 0),
                      GravityBox(center: SIMD3(-0.58, 0.22, 0), size: SIMD3(0.02, 0.44, 0.56), yaw: 0),
                      GravityBox(center: SIMD3(0.58, 0.22, 0), size: SIMD3(0.02, 0.44, 0.56), yaw: 0)]
        let at = SIMD3<Float>(0, 0, -0.4)
        return SyntheticScene(objects: [build == .solid
            ? SyntheticObject(id: 0, name: "glass table", position: at, yaw: 0, parts: panels)
            : SyntheticObject(id: 0, name: "glass table", position: at, yaw: 0, parts: [], glass: panels)])
    }

    private static let coffeeTableView = SyntheticCamera(eye: SIMD3(0.3, 1.45, 1.1), target: SIMD3(0, 0.23, -0.4),
                                                         roll: portrait)

    /// The lifter's verdict on the case's bleeding outline — over no measured
    /// depth at all when `blanking`.
    private func attempt(_ build: Build, seed: UInt64, blanking: Bool = false) throws -> LiftAttempt {
        try attempt(Self.displayCase(build), view: Self.displayCaseView, seed: seed, blanking: blanking)
    }

    /// The lifter's verdict on object 0's bleeding, filled outline from
    /// `view`, against the scene's own surfaces unless others are given.
    private func attempt(_ scene: SyntheticScene, view: SyntheticCamera, seed: UInt64, blanking: Bool = false,
                         surfaces: [HorizontalSurface]? = nil) throws -> LiftAttempt {
        var rng = SeededGenerator(seed: seed)
        let frame = scene.frame(camera: view, rng: &rng)
        let cells = scene.silhouetteCells(of: 0, camera: view, turn: frame.sensor.turn)
        let (det, bank) = try XCTUnwrap(SyntheticScene.detection(cells: cells, bleed: true, filled: true, rng: &rng))
        let mask = try XCTUnwrap(bank.mask(for: det).depthMask(frame: frame.sensor))
        var depth = frame.depth
        if blanking {
            var values = depth.depth
            for y in mask.yRange { for x in mask.xRange where mask[x, y] { values[y * depth.width + x] = 0 } }
            depth = DepthGrid(width: depth.width, height: depth.height, depth: values, confidence: depth.confidence)
        }
        return DepthLifter.attempt(mask: mask, excluding: nil, depth: depth, frame: frame.sensor,
                                   surfaces: surfaces ?? scene.surfaces, walls: scene.walls, flat: false)
    }

    private func rejection(_ attempt: LiftAttempt) -> LiftRejection? {
        if case .rejected(let why) = attempt { return why }
        return nil
    }

    func test_aGlassCaseBeforeAWall_leavesOnlyTheSurfacesSeenThroughIt() throws {
        XCTAssertEqual(rejection(try attempt(.glass, seed: 41)), .onlySurfaces)
        XCTAssertNil(rejection(try attempt(.solid, seed: 41)), "the control: the same case, solid, is lifted")
    }

    func test_anAllGlassTable_leavesOnlyTheFloorSeenThroughIt() throws {
        // Seen through, the table is all floor, so the floor is the middle of
        // what its outline measures — and it is still the floor.
        XCTAssertEqual(rejection(try attempt(Self.coffeeTable(.glass), view: Self.coffeeTableView, seed: 45)),
                       .onlySurfaces)
        XCTAssertNil(rejection(try attempt(Self.coffeeTable(.solid), view: Self.coffeeTableView, seed: 45)),
                     "the same table, solid, is lifted")
    }

    func test_theFloorRemovedOnlyBelowTheMiddle_comesBackAsTheGlassTable() throws {
        // The control: taken like a table top, a surface only below the
        // object's middle, the floor seen through the glass is the table.
        let room = PlanRectangle(center: .zero, axis: SIMD2(1, 0), halfExtents: SIMD2(2.5, 2.0))
        let floorAsATop = [HorizontalSurface(kind: .support, height: 0, extent: room),
                           HorizontalSurface(kind: .ceiling, height: 2.6, extent: nil)]
        let verdict = try attempt(Self.coffeeTable(.glass), view: Self.coffeeTableView, seed: 45,
                                  surfaces: floorAsATop)
        guard case .lifted(let floor) = verdict else { return XCTFail("rejected: \(verdict)") }
        let heights = floor.points.map(\.y)
        XCTAssertLessThan(heights.max() ?? 1, 0.05, "a patch of the floor, not the table")
    }

    func test_aGlassCaseRoundOnePost_isTooLittleSeen() throws {
        XCTAssertEqual(rejection(try attempt(.post, seed: 42)), .tooLittleSeen)
    }

    func test_anOutlineOverNothingMeasured_hasNoDepthUnderIt() throws {
        XCTAssertEqual(rejection(try attempt(.solid, seed: 43, blanking: true)), .noDepth)
    }

    func test_aFewPixels_areTooFewForAnything() {
        var rng = SeededGenerator(seed: 44)
        let scene = Self.displayCase(.solid)
        let frame = scene.frame(camera: Self.displayCaseView, rng: &rng)
        let speck = DepthMask(xRange: 128...130, yRange: 96...98) { _, _ in true }
        let verdict = DepthLifter.attempt(mask: speck, excluding: nil, depth: frame.depth, frame: frame.sensor,
                                          surfaces: scene.surfaces, walls: scene.walls, flat: false)
        XCTAssertEqual(rejection(verdict), .tooFewPixels)
    }

    func test_aSofaBehindAGlassTable_isBoxedToTheSofa() {
        let fusion = walk(Self.sofaScene, views: Self.sofaViews, lifting: [0], seed: 2)
        assertWithinTheBar(fusion, Self.sofaScene.objects[0], "sofa behind a glass table")
    }

    func test_withoutCuttingIntoPieces_theTablesFrameShapesTheSofa() {
        // The control, as above.
        let fusion = walk(Self.sofaScene, views: Self.sofaViews, lifting: [0], seed: 2, lift: uncut)
        XCTAssertFalse(measure(fusion, Self.sofaScene.objects[0], "sofa, uncut control").held)
    }
}
