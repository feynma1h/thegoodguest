/// Pins for how fusion earns, keeps, names, carves and merges tracks — each on
/// the smallest synthetic room that shows the behaviour, through the production
/// lifter, so the observations have the shape real ones do.

import simd
import XCTest
@testable import TheGoodGuest

final class LiveBoxesFusionTests: XCTestCase {

    private static let table = SyntheticObject(
        id: 0, name: "side table",
        box: GravityBox(center: SIMD3(0, 0.3, -1), size: SIMD3(0.6, 0.6, 0.5), yaw: 0.3))
    private let scene = SyntheticScene(objects: [table])

    private func camera(azimuthDegrees a: Float, distance: Float = 1.8) -> SyntheticCamera {
        let r = a * .pi / 180
        let c = Self.table.box.center
        return SyntheticCamera(eye: SIMD3(c.x + distance * cos(r), 1.4, c.z + distance * sin(r)),
                               target: c, roll: .pi / 2)
    }

    // MARK: - Earning a place

    func test_aSecondSighting_confirmsATrack() throws {
        var rng = SeededGenerator(seed: 1)
        var fusion = BoxFusion()
        let first = scene.frame(camera: camera(azimuthDegrees: 80), rng: &rng)
        let o1 = try XCTUnwrap(scene.observation(of: 0, in: first, name: "side table", rng: &rng))
        fusion.integrate([o1], frame: first.sensor, depth: first.depth, time: 0)
        XCTAssertEqual(fusion.tracks.count, 1)
        XCTAssertFalse(fusion.tracks[0].isConfirmed)

        let second = scene.frame(camera: camera(azimuthDegrees: 100), rng: &rng)
        let o2 = try XCTUnwrap(scene.observation(of: 0, in: second, name: "side table", rng: &rng))
        fusion.integrate([o2], frame: second.sensor, depth: second.depth, time: 0.2)
        XCTAssertEqual(fusion.tracks.count, 1, "the second sighting joins the first track")
        XCTAssertTrue(fusion.tracks[0].isConfirmed)
        XCTAssertEqual(fusion.tracks[0].hits, 2)
    }

    func test_confirmation_takesAsManySightingsAsTheParametersSay() throws {
        var rng = SeededGenerator(seed: 1)
        var fusion = BoxFusion(parameters: FusionParameters(confirmingHits: 3))
        for (k, a) in [Float(80), 100, 120].enumerated() {
            let f = scene.frame(camera: camera(azimuthDegrees: a), rng: &rng)
            let o = try XCTUnwrap(scene.observation(of: 0, in: f, name: "side table", rng: &rng))
            fusion.integrate([o], frame: f.sensor, depth: f.depth, time: Double(k))
            XCTAssertEqual(fusion.tracks.count, 1)
            XCTAssertEqual(fusion.tracks[0].isConfirmed, k == 2, "after \(k + 1) sightings")
        }
    }

    func test_aTentativeTrack_lookedAtAndNotSeen_isRemoved() throws {
        var rng = SeededGenerator(seed: 2)
        var fusion = BoxFusion()
        let seen = scene.frame(camera: camera(azimuthDegrees: 90), rng: &rng)
        let o = try XCTUnwrap(scene.observation(of: 0, in: seen, name: "side table", rng: &rng))
        fusion.integrate([o], frame: seen.sensor, depth: seen.depth, time: 0)
        for k in 1...FusionParameters().tentativeMissLimit {
            XCTAssertEqual(fusion.tracks.count, 1, "still there before miss \(k)")
            let looked = scene.frame(camera: camera(azimuthDegrees: 90 + Float(k)), rng: &rng)
            fusion.integrate([], frame: looked.sensor, depth: looked.depth, time: Double(k) * 0.2)
        }
        XCTAssertTrue(fusion.tracks.isEmpty)
    }

    func test_aConfirmedTrack_survivesAFewMisses() throws {
        var rng = SeededGenerator(seed: 3)
        var fusion = BoxFusion()
        for (k, a) in [Float(70), 90, 110].enumerated() {
            let f = scene.frame(camera: camera(azimuthDegrees: a), rng: &rng)
            let o = try XCTUnwrap(scene.observation(of: 0, in: f, name: "side table", rng: &rng))
            fusion.integrate([o], frame: f.sensor, depth: f.depth, time: Double(k))
        }
        for k in 0..<4 {
            let f = scene.frame(camera: camera(azimuthDegrees: 95), rng: &rng)
            fusion.integrate([], frame: f.sensor, depth: f.depth, time: 3 + Double(k))
        }
        XCTAssertEqual(fusion.tracks.count, 1)
        XCTAssertEqual(fusion.tracks[0].misses, 4)
    }

    func test_aTrackOutOfView_isNotMissed() throws {
        var rng = SeededGenerator(seed: 4)
        var fusion = BoxFusion()
        let seen = scene.frame(camera: camera(azimuthDegrees: 90), rng: &rng)
        let o = try XCTUnwrap(scene.observation(of: 0, in: seen, name: "side table", rng: &rng))
        fusion.integrate([o], frame: seen.sensor, depth: seen.depth, time: 0)
        // Facing the other way: the table is behind the camera.
        let away = SyntheticCamera(eye: SIMD3(0, 1.4, 0.8), target: SIMD3(0, 1, 2), roll: .pi / 2)
        for k in 0..<5 {
            let f = scene.frame(camera: away, rng: &rng)
            fusion.integrate([], frame: f.sensor, depth: f.depth, time: Double(k + 1))
        }
        XCTAssertEqual(fusion.tracks.first?.misses, 0)
    }

    func test_aTrackRecordsHowFarItsFitMovesBetweenPasses() throws {
        var rng = SeededGenerator(seed: 11)
        var fusion = BoxFusion()
        for (k, a) in [Float(70), 85, 100, 115].enumerated() {
            let f = scene.frame(camera: camera(azimuthDegrees: a), rng: &rng)
            let o = try XCTUnwrap(scene.observation(of: 0, in: f, name: "side table", rng: &rng))
            fusion.integrate([o], frame: f.sensor, depth: f.depth, time: Double(k))
        }
        let movement = try XCTUnwrap(fusion.tracks.first).movement
        XCTAssertEqual(movement.refits, 4, "every pass that sees the object refits it, the first included")
        XCTAssertGreaterThan(movement.centreMaxCm, 0, "a refit moves the box, which is the jitter")
        XCTAssertGreaterThanOrEqual(movement.centreMaxCm, movement.centreMeanCm)
        XCTAssertGreaterThanOrEqual(movement.yawMaxDegrees, movement.yawMeanDegrees)
        XCTAssertLessThan(movement.yawMaxDegrees, 45, "yaw movement reads over the quarter turn")
    }

    // MARK: - Naming

    func test_label_isWhicheverNameEarnedTheMostScore() throws {
        var rng = SeededGenerator(seed: 5)
        var fusion = BoxFusion()
        // The first sighting starts the track, so it needs the starting score.
        let sightings: [(String, Float)] = [("mirror", 0.9), ("picture frame", 0.3), ("picture frame", 0.35)]
        for (k, sighting) in sightings.enumerated() {
            let f = scene.frame(camera: camera(azimuthDegrees: 80 + Float(k) * 10), rng: &rng)
            let o = try XCTUnwrap(scene.observation(of: 0, in: f, name: sighting.0, score: sighting.1, rng: &rng))
            fusion.integrate([o], frame: f.sensor, depth: f.depth, time: Double(k))
        }
        XCTAssertEqual(fusion.tracks.count, 1)
        XCTAssertEqual(fusion.tracks[0].label, "MIRROR")
        XCTAssertEqual(fusion.tracks[0].dominantName, "mirror")
        XCTAssertEqual(fusion.tracks[0].names["picture frame"] ?? 0, 0.65, accuracy: 1e-4)
    }

    // MARK: - Carving

    func test_voxelsTheCameraSeesThrough_areRemoved() throws {
        var rng = SeededGenerator(seed: 6)
        var fusion = BoxFusion()
        let f0 = scene.frame(camera: camera(azimuthDegrees: 90), rng: &rng)
        let real = try XCTUnwrap(scene.observation(of: 0, in: f0, name: "side table", rng: &rng))
        // The same sighting with a phantom slab floating 40 cm above the table,
        // where every later view measures the wall behind.
        let phantom = (0..<400).map { k in
            SIMD3<Float>(-0.2 + Float(k % 20) * 0.02, 1.0, -1.1 + Float(k / 20) * 0.01)
        }
        let polluted = try XCTUnwrap(BoxObservation(name: "side table", label: "SIDE TABLE", roomPlanCategory: nil,
                                                    score: 0.8, points: real.points + phantom, mask: real.mask))
        fusion.integrate([polluted], frame: f0.sensor, depth: f0.depth, time: 0)
        XCTAssertGreaterThan(fusion.tracks[0].box.maxY, 0.95)
        for (k, a) in [Float(60), 120, 75, 105].enumerated() {
            let f = scene.frame(camera: camera(azimuthDegrees: a), rng: &rng)
            let o = try XCTUnwrap(scene.observation(of: 0, in: f, name: "side table", rng: &rng))
            fusion.integrate([o], frame: f.sensor, depth: f.depth, time: Double(k + 1))
        }
        XCTAssertEqual(fusion.tracks.count, 1)
        XCTAssertLessThan(fusion.tracks[0].box.maxY, 0.66, "the phantom slab was carved away")
    }

    // MARK: - Merging

    func test_twoTracksOfOneObject_mergeOnceTheyOverlap() throws {
        var rng = SeededGenerator(seed: 7)
        var fusion = BoxFusion()
        let f = scene.frame(camera: camera(azimuthDegrees: 90), rng: &rng)
        let whole = try XCTUnwrap(scene.observation(of: 0, in: f, name: "side table", rng: &rng))
        // Split one sighting into its left and right halves, reported as two
        // detections in one frame — each seeds a track of its own.
        let centre = whole.box.center
        let left = whole.points.filter { $0.x < centre.x }
        let right = whole.points.filter { $0.x >= centre.x }
        let halves = [left, right].compactMap {
            BoxObservation(name: "side table", label: "SIDE TABLE", roomPlanCategory: nil, score: 0.8,
                           points: $0, mask: whole.mask)
        }
        XCTAssertEqual(halves.count, 2)
        fusion.integrate(halves, frame: f.sensor, depth: f.depth, time: 0)
        for (k, a) in [Float(80), 100].enumerated() {
            let g = scene.frame(camera: camera(azimuthDegrees: a), rng: &rng)
            let o = try XCTUnwrap(scene.observation(of: 0, in: g, name: "side table", rng: &rng))
            fusion.integrate([o], frame: g.sensor, depth: g.depth, time: Double(k + 1))
        }
        XCTAssertEqual(fusion.tracks.count, 1)
    }

    func test_differentObjects_withDifferentLabels_stayApart() throws {
        let lamp = SyntheticObject(id: 1, name: "lamp",
                                   box: GravityBox(center: SIMD3(0.55, 0.8, -1.0), size: SIMD3(0.3, 1.6, 0.3), yaw: 0))
        let room = SyntheticScene(objects: [Self.table, lamp])
        var rng = SeededGenerator(seed: 8)
        var fusion = BoxFusion()
        for (k, a) in [Float(80), 100, 120].enumerated() {
            let f = room.frame(camera: camera(azimuthDegrees: a, distance: 2.2), rng: &rng)
            let observations = [
                room.observation(of: 0, in: f, name: "side table", rng: &rng),
                room.observation(of: 1, in: f, name: "lamp", rng: &rng),
            ].compactMap { $0 }
            fusion.integrate(observations, frame: f.sensor, depth: f.depth, time: Double(k))
        }
        XCTAssertEqual(Set(fusion.tracks.map(\.label)), ["SIDE TABLE", "LAMP"])
        XCTAssertEqual(fusion.tracks.count, 2)
    }

    // MARK: - Holding the load down

    func test_aWeakDetection_startsOnlyAnUnsureTrack_thatASureSightingMakesSure() throws {
        var rng = SeededGenerator(seed: 14)
        var fusion = BoxFusion()
        for (k, a) in [Float(80), 90].enumerated() {
            let f = scene.frame(camera: camera(azimuthDegrees: a), rng: &rng)
            let weak = try XCTUnwrap(scene.observation(of: 0, in: f, name: "side table", score: 0.4, rng: &rng))
            fusion.integrate([weak], frame: f.sensor, depth: f.depth, time: Double(k))
        }
        let unsure = try XCTUnwrap(fusion.tracks.first, "0.4 starts an unsure track")
        XCTAssertEqual(fusion.tracks.count, 1)
        XCTAssertTrue(unsure.isUnsure)
        XCTAssertFalse(unsure.isConfirmed, "two sightings confirm a sure track, not an unsure one")

        let f3 = scene.frame(camera: camera(azimuthDegrees: 100), rng: &rng)
        let strong = try XCTUnwrap(scene.observation(of: 0, in: f3, name: "side table", score: 0.8, rng: &rng))
        fusion.integrate([strong], frame: f3.sensor, depth: f3.depth, time: 2)
        XCTAssertEqual(fusion.tracks.count, 1)
        XCTAssertEqual(fusion.tracks[0].hits, 3, "the sure sighting joined the unsure track")
        XCTAssertFalse(fusion.tracks[0].isUnsure)
        XCTAssertTrue(fusion.tracks[0].isConfirmed)
    }

    /// Five sightings of the table at `score`, from 70° round to 110°.
    private func seenAgainAndAgain(score: Float, parameters: FusionParameters = FusionParameters(),
                                   seed: UInt64) throws -> (fusion: BoxFusion, confirmedAfter: Int?) {
        var rng = SeededGenerator(seed: seed)
        var fusion = BoxFusion(parameters: parameters)
        var confirmedAfter: Int?
        for (k, a) in [Float(70), 80, 90, 100, 110].enumerated() {
            let f = scene.frame(camera: camera(azimuthDegrees: a), rng: &rng)
            let o = try XCTUnwrap(scene.observation(of: 0, in: f, name: "side table", score: score, rng: &rng))
            fusion.integrate([o], frame: f.sensor, depth: f.depth, time: Double(k))
            if confirmedAfter == nil, fusion.tracks.first?.isConfirmed == true { confirmedAfter = k + 1 }
        }
        return (fusion, confirmedAfter)
    }

    func test_anObjectTheDetectorIsUnsureOf_seenAgainAndAgainInOnePlace_isConfirmed() throws {
        // The white glass-door cabinet was never over 0.44, from wherever the
        // person stood. Seen again and again in one place, it is an object.
        let seen = try seenAgainAndAgain(score: 0.44, seed: 28)
        XCTAssertEqual(seen.fusion.tracks.count, 1)
        XCTAssertEqual(seen.confirmedAfter, FusionParameters().unsureConfirmingHits)
        XCTAssertTrue(seen.fusion.tracks[0].isUnsure)
        // The control: with no unsure start, the same sightings leave nothing.
        var off = FusionParameters()
        off.unsureScore = off.startingScore
        XCTAssertTrue(try seenAgainAndAgain(score: 0.44, parameters: off, seed: 28).fusion.tracks.isEmpty)
    }

    func test_unsureDetectionsHereAndThere_confirmNothing() throws {
        // What the starting score kept out: weak names that never come back
        // to one place. Each stays a single tentative sighting, and no dot.
        var rng = SeededGenerator(seed: 29)
        var fusion = BoxFusion()
        let f = skyward(&rng)
        for (k, x) in [Float(-2), -1, 0, 1, 2].enumerated() {
            let there = try XCTUnwrap(cube(at: SIMD3(x, 0.5, -1.5), side: 0.3))
            let weak = try XCTUnwrap(BoxObservation(name: "vase", label: "VASE", roomPlanCategory: nil, score: 0.4,
                                                    points: there.points, mask: there.mask))
            fusion.integrate([weak], frame: f.sensor, depth: f.depth, time: Double(k))
        }
        XCTAssertEqual(fusion.tracks.count, 5)
        XCTAssertFalse(fusion.tracks.contains(where: \.isConfirmed))
    }

    func test_anUnsureDetectionWhereATrackStands_startsNothing() throws {
        // Under 0.5 the detector names what is on or in other objects, and
        // doubles them: an unsure name inside a box already there is neither.
        var rng = SeededGenerator(seed: 30)
        var fusion = BoxFusion()
        let f = skyward(&rng)
        let cabinet = try XCTUnwrap(cube(at: SIMD3(1, 0.6, 1), side: 0.8, name: "file cabinet"))
        fusion.integrate([cabinet], frame: f.sensor, depth: f.depth, time: 0)
        func weakShelf(at centre: SIMD3<Float>) throws -> BoxObservation {
            let points = try XCTUnwrap(cube(at: centre, side: 0.3)).points
            return try XCTUnwrap(BoxObservation(name: "shelf", label: "SHELF", roomPlanCategory: nil, score: 0.32,
                                                points: points, mask: cabinet.mask))
        }
        XCTAssertEqual(fusion.integrate([try weakShelf(at: SIMD3(1, 0.6, 1))], frame: f.sensor, depth: f.depth,
                                        time: 1), [.tooUnsure])
        XCTAssertEqual(fusion.tracks.count, 1)
        // The control: the same weak name where nothing stands starts a track.
        let elsewhere = fusion.integrate([try weakShelf(at: SIMD3(-1, 0.6, 1))], frame: f.sensor, depth: f.depth,
                                         time: 2)
        XCTAssertEqual(fusion.tracks.count, 2)
        XCTAssertEqual(elsewhere, [.started(try XCTUnwrap(fusion.tracks.last).id)])
    }


    /// A cube of `n`³ points: an observation that needs no rendering.
    private func cube(at centre: SIMD3<Float>, side: Float, name: String = "vase", n: Int = 8) -> BoxObservation? {
        var points: [SIMD3<Float>] = []
        for i in 0..<n { for j in 0..<n { for k in 0..<n {
            let u = SIMD3(Float(i), Float(j), Float(k)) / Float(n - 1) - 0.5
            points.append(centre + u * side)
        } } }
        let mask = DepthMask(xRange: 0...0, yRange: 0...0, bits: [false])
        return BoxObservation(name: name, label: DetectorVocabulary.role(for: name).label ?? "VASE",
                              roomPlanCategory: nil, score: 0.8, points: points, mask: mask)
    }

    /// A frame looking straight up at nothing, so no track is in view.
    private func skyward(_ rng: inout SeededGenerator) -> SyntheticScene.Frame {
        scene.frame(camera: SyntheticCamera(eye: SIMD3(0, 1.4, 0), target: SIMD3(0.01, 3, 0), roll: 0), rng: &rng)
    }

    func test_oneTableNamedTwoWays_isOneTrack_butATableAndAVaseAreTwo() throws {
        var rng = SeededGenerator(seed: 16)
        var fusion = BoxFusion()
        let f = skyward(&rng)
        func table(_ name: String) throws -> BoxObservation {
            try XCTUnwrap(cube(at: SIMD3(1, 0.4, 1), side: 0.8, name: name))
        }
        fusion.integrate([try table("kitchen table")], frame: f.sensor, depth: f.depth, time: 0)
        fusion.integrate([try table("office desk")], frame: f.sensor, depth: f.depth, time: 1)
        fusion.integrate([try table("kitchen table")], frame: f.sensor, depth: f.depth, time: 2)
        fusion.integrate([try table("office desk")], frame: f.sensor, depth: f.depth, time: 3)
        XCTAssertEqual(fusion.tracks.count, 1, "both names are the table's")
        XCTAssertEqual(fusion.tracks[0].hits, 4)
    }

    func test_aDetectionTheFrameCutsOff_startsNoTrack_butAddsToOne() throws {
        var rng = SeededGenerator(seed: 15)
        var fusion = BoxFusion()
        let f = skyward(&rng)
        func vase(cutOff: Bool) throws -> BoxObservation {
            let whole = try XCTUnwrap(cube(at: SIMD3(1, 0.5, 1), side: 0.3))
            return try XCTUnwrap(BoxObservation(name: whole.name, label: whole.label, roomPlanCategory: nil,
                                                score: 0.9, points: whole.points, mask: whole.mask, touchesEdge: cutOff))
        }
        fusion.integrate([try vase(cutOff: true)], frame: f.sensor, depth: f.depth, time: 0)
        XCTAssertTrue(fusion.tracks.isEmpty, "a cut-off detection starts nothing")
        fusion.integrate([try vase(cutOff: false)], frame: f.sensor, depth: f.depth, time: 1)
        fusion.integrate([try vase(cutOff: true)], frame: f.sensor, depth: f.depth, time: 2)
        XCTAssertEqual(fusion.tracks.count, 1)
        XCTAssertEqual(fusion.tracks[0].hits, 2, "once the vase has a track, a cut-off view still adds to it")
    }

    func test_aCutOffDetectionThePersonAimsAt_startsATrack() throws {
        // The pooja cabinet, tall and close: the frame always cut it off. Aimed
        // at, it starts a track; the control, the same view not aimed at, does not.
        var rng = SeededGenerator(seed: 27)
        let f = skyward(&rng)
        let cabinet = try XCTUnwrap(cube(at: SIMD3(1, 0.5, 1), side: 0.3, name: "file cabinet"))
        func cutOff(aimedAt: Bool) throws -> BoxObservation {
            try XCTUnwrap(BoxObservation(name: cabinet.name, label: cabinet.label, roomPlanCategory: nil, score: 0.63,
                                         points: cabinet.points, mask: cabinet.mask, touchesEdge: true,
                                         aimedAt: aimedAt))
        }
        var control = BoxFusion()
        XCTAssertEqual(control.integrate([try cutOff(aimedAt: false)], frame: f.sensor, depth: f.depth, time: 0),
                       [.cutOff])
        XCTAssertTrue(control.tracks.isEmpty)
        var fusion = BoxFusion()
        let sightings = fusion.integrate([try cutOff(aimedAt: true)], frame: f.sensor, depth: f.depth, time: 0)
        XCTAssertEqual(sightings, [.started(try XCTUnwrap(fusion.tracks.first).id)])
    }

    func test_integrate_saysWhatBecameOfEachObservation() throws {
        var rng = SeededGenerator(seed: 26)
        var fusion = BoxFusion()
        let f = skyward(&rng)
        let vase = try XCTUnwrap(cube(at: SIMD3(1, 0.5, 1), side: 0.3))
        let first = fusion.integrate([vase], frame: f.sensor, depth: f.depth, time: 0)
        let id = try XCTUnwrap(fusion.tracks.first?.id)
        XCTAssertEqual(first, [.started(id)])
        XCTAssertEqual(fusion.integrate([vase], frame: f.sensor, depth: f.depth, time: 1), [.joined(id)])
        // Across the room, where no track is: one too weak to start even an
        // unsure box, one cut off by the frame.
        let there = try XCTUnwrap(cube(at: SIMD3(-1, 0.5, 1), side: 0.3))
        let weak = try XCTUnwrap(BoxObservation(name: "vase", label: "VASE", roomPlanCategory: nil, score: 0.25,
                                                points: there.points, mask: there.mask))
        let cut = try XCTUnwrap(BoxObservation(name: "vase", label: "VASE", roomPlanCategory: nil, score: 0.9,
                                               points: there.points, mask: there.mask, touchesEdge: true))
        XCTAssertEqual(fusion.integrate([weak, cut], frame: f.sensor, depth: f.depth, time: 2), [.tooUnsure, .cutOff])
        XCTAssertEqual(fusion.tracks.count, 1)
    }

    func test_aFragmentThatStaysTiny_isDropped() throws {
        var rng = SeededGenerator(seed: 12)
        var fusion = BoxFusion()
        let f = skyward(&rng)
        for k in 0..<FusionParameters().smallTrackHits {
            let crumb = try XCTUnwrap(cube(at: SIMD3(1, 0.5, 1), side: 0.06))
            let vase = try XCTUnwrap(cube(at: SIMD3(-1, 0.5, 1), side: 0.30))
            fusion.integrate([crumb, vase], frame: f.sensor, depth: f.depth, time: Double(k))
        }
        XCTAssertEqual(fusion.tracks.count, 1, "the 6 cm crumb goes after five sightings; the vase stays")
        XCTAssertGreaterThan(fusion.tracks.first.map { simd_reduce_max($0.box.size) } ?? 0, 0.2)
    }

    func test_theTrackCount_isCapped_stalestTentativeFirst() throws {
        var rng = SeededGenerator(seed: 13)
        var parameters = FusionParameters()
        parameters.maximumTracks = 4
        var fusion = BoxFusion(parameters: parameters)
        let f = skyward(&rng)
        // Three objects seen twice (confirmed), then three more seen once, one per pass.
        let spots: [SIMD3<Float>] = (0..<6).map { SIMD3(Float($0) * 1.0 - 2.5, 0.5, -1.5) }
        for k in 0..<2 {
            let seen = try spots.prefix(3).map { try XCTUnwrap(cube(at: $0, side: 0.3)) }
            fusion.integrate(seen, frame: f.sensor, depth: f.depth, time: Double(k))
        }
        for (k, spot) in spots.suffix(3).enumerated() {
            fusion.integrate([try XCTUnwrap(cube(at: spot, side: 0.3))], frame: f.sensor, depth: f.depth,
                             time: 2 + Double(k))
        }
        XCTAssertEqual(fusion.tracks.count, 4)
        XCTAssertEqual(fusion.tracks.filter(\.isConfirmed).count, 3, "every confirmed track is kept")
        XCTAssertEqual(fusion.tracks.filter { !$0.isConfirmed }.map(\.lastSeen), [4], "the newest tentative one stays")
    }

    // MARK: - Nesting

    /// A sofa as a seat and a back (both id 0), and a cushion lying on the
    /// seat against the back (id 1) — inside the sofa's box, as a cushion is.
    private static let sofaSeat = GravityBox(center: SIMD3(0, 0.225, -1.2), size: SIMD3(2.0, 0.45, 0.9), yaw: 0)
    private static let cushion = GravityBox(center: SIMD3(-0.5, 0.525, -1.2), size: SIMD3(0.5, 0.15, 0.45), yaw: 0)
    private let lounge = SyntheticScene(objects: [
        SyntheticObject(id: 0, name: "couch", box: sofaSeat),
        SyntheticObject(id: 0, name: "couch",
                        box: GravityBox(center: SIMD3(0, 0.625, -1.55), size: SIMD3(2.0, 0.35, 0.2), yaw: 0)),
        SyntheticObject(id: 1, name: "pillow", box: cushion),
    ])

    private func loungeView(azimuthDegrees a: Float) -> SyntheticCamera {
        let r = a * .pi / 180
        return SyntheticCamera(eye: SIMD3(2.4 * cos(r), 1.45, -1.2 + 2.4 * sin(r)),
                               target: SIMD3(0, 0.4, -1.2), roll: .pi / 2)
    }

    private func closeUp(azimuthDegrees a: Float) -> SyntheticCamera {
        let r = a * .pi / 180
        let c = Self.cushion.center
        return SyntheticCamera(eye: SIMD3(c.x + 1.0 * cos(r), 1.1, c.z + 1.0 * sin(r)), target: c, roll: .pi / 2)
    }

    func test_aCushionOnASofa_isItsOwnTrack() throws {
        var rng = SeededGenerator(seed: 9)
        var fusion = BoxFusion()
        for (k, a) in [Float(60), 90, 120].enumerated() {
            let f = lounge.frame(camera: loungeView(azimuthDegrees: a), rng: &rng)
            // The sofa's mask takes in the cushion on it; the cushion's is its own.
            let observations = [
                lounge.observation(of: [0, 1], in: f, name: "couch", rng: &rng),
                lounge.observation(of: 1, in: f, name: "pillow", rng: &rng),
            ].compactMap { $0 }
            XCTAssertEqual(observations.count, 2)
            fusion.integrate(observations, frame: f.sensor, depth: f.depth, time: Double(k))
        }
        let cushion = try XCTUnwrap(fusion.tracks.first { $0.label == "CUSHION" }, "the cushion was absorbed")
        XCTAssertTrue(cushion.isConfirmed)
        XCTAssertLessThan(simd_distance(cushion.box.center, Self.cushion.center), 0.05)
        XCTAssertEqual(fusion.tracks.filter { $0.label == "SOFA" }.count, 1)
    }

    func test_closeUpsOfTheCushion_neitherJoinNorCarveTheSofa() throws {
        var rng = SeededGenerator(seed: 10)
        var fusion = BoxFusion()
        // From across the room only the sofa is detected, its mask over the cushion too.
        for (k, a) in [Float(60), 90, 120].enumerated() {
            let f = lounge.frame(camera: loungeView(azimuthDegrees: a), rng: &rng)
            let sofa = try XCTUnwrap(lounge.observation(of: [0, 1], in: f, name: "couch", rng: &rng))
            fusion.integrate([sofa], frame: f.sensor, depth: f.depth, time: Double(k))
        }
        let before = try XCTUnwrap(fusion.tracks.first { $0.label == "SOFA" }).box
        // Close up, only the cushion is.
        for (k, a) in [Float(75), 90, 105, 85].enumerated() {
            let f = lounge.frame(camera: closeUp(azimuthDegrees: a), rng: &rng)
            let pillow = try XCTUnwrap(lounge.observation(of: 1, in: f, name: "pillow", rng: &rng))
            fusion.integrate([pillow], frame: f.sensor, depth: f.depth, time: 3 + Double(k))
        }
        let sofa = try XCTUnwrap(fusion.tracks.first { $0.label == "SOFA" })
        XCTAssertNil(sofa.names["pillow"], "a close-up of the cushion joined the sofa")
        XCTAssertEqual(max(sofa.box.size.x, sofa.box.size.z), max(before.size.x, before.size.z), accuracy: 0.05,
                       "the cushion's mask carved the sofa")
        XCTAssertEqual(sofa.box.size.y, before.size.y, accuracy: 0.05, "the cushion's mask carved the sofa")
        let cushion = try XCTUnwrap(fusion.tracks.first { $0.label == "CUSHION" })
        XCTAssertLessThan(simd_distance(cushion.box.center, Self.cushion.center), 0.05)
    }

    // MARK: - Finishing

    /// The side table, pushed 25 cm along x.
    private static let movedTable = SyntheticObject(
        id: 0, name: "side table",
        box: GravityBox(center: SIMD3(0.25, 0.3, -1), size: SIMD3(0.6, 0.6, 0.5), yaw: 0.3))

    /// Sightings of the table from each azimuth, in order.
    private func look(_ fusion: inout BoxFusion, at azimuths: [Float], scene: SyntheticScene,
                      from time: Double, rng: inout SeededGenerator) throws {
        for (k, a) in azimuths.enumerated() {
            let f = scene.frame(camera: camera(azimuthDegrees: a), rng: &rng)
            let o = try XCTUnwrap(scene.observation(of: 0, in: f, name: "side table", rng: &rng))
            fusion.integrate([o], frame: f.sensor, depth: f.depth, time: time + Double(k))
        }
    }

    func test_nothingLocksByItself_andAFinishedBoxIsTheOneFinished_andNeverMoves() throws {
        var rng = SeededGenerator(seed: 21)
        var fusion = BoxFusion()
        // Eight sightings from 60° round, with steady fits: the rule this
        // replaced locked the table here.
        try look(&fusion, at: [60, 70, 80, 90, 100, 110, 120, 105], scene: scene, from: 0, rng: &rng)
        let track = try XCTUnwrap(fusion.tracks.first)
        XCTAssertNil(track.locked, "only the person finishes a box")
        // The box they finish is the one they were looking at, which the
        // screen eases toward the fit: a centimetre off it, say.
        let shown = GravityBox(center: track.box.center + SIMD3(0.01, 0, 0), size: track.box.size, yaw: track.box.yaw)
        XCTAssertTrue(fusion.finish(track.id, box: shown, time: 8))
        let locked = try XCTUnwrap(fusion.tracks.first?.locked)
        XCTAssertEqual(locked.box, shown, "exactly the box that was drawn")
        XCTAssertEqual(locked.hits, 8)
        XCTAssertFalse(fusion.finish(track.id, box: track.box, time: 9), "a finished box is not finished again")
        // The table is pushed 25 cm: the fit follows it, the finished box does not.
        let moved = SyntheticScene(objects: [Self.movedTable])
        try look(&fusion, at: [80, 90, 100, 95, 85, 90], scene: moved, from: 9, rng: &rng)
        let after = try XCTUnwrap(fusion.tracks.first)
        XCTAssertEqual(after.locked, locked, "a finished box never changes")
        XCTAssertGreaterThan(simd_distance(after.box.center, locked.box.center), 0.05, "the fit moved on")
    }

    func test_aFinishedTrack_outlastsTheMissesThatRemoveAnyOther() throws {
        func run(finishing: Bool) throws -> BoxFusion {
            var rng = SeededGenerator(seed: 22)
            var fusion = BoxFusion()
            try look(&fusion, at: [60, 70, 80, 90, 100, 110, 120, 105], scene: scene, from: 0, rng: &rng)
            if finishing, let t = fusion.tracks.first { fusion.finish(t.id, box: t.box, time: 8) }
            for k in 0..<40 {
                let f = scene.frame(camera: camera(azimuthDegrees: 95), rng: &rng)
                fusion.integrate([], frame: f.sensor, depth: f.depth, time: 8 + Double(k))
            }
            return fusion
        }
        // 8 sightings and 40 misses: a hit ratio of 0.17, under the 0.25 that
        // removes a confirmed track.
        XCTAssertNotNil(try run(finishing: true).tracks.first?.locked, "still drawn")
        XCTAssertTrue(try run(finishing: false).tracks.isEmpty, "the control: unfinished, the same misses remove it")
    }

    /// Two vases 60 cm apart — too far to join — then a dense sighting
    /// spanning both, which grows one track's fit over the other.
    private func twoVasesGrownTogether(finishing: Bool) throws -> BoxFusion {
        var rng = SeededGenerator(seed: 23)
        var fusion = BoxFusion()
        let f = skyward(&rng)
        let left = SIMD3<Float>(0, 0.5, 1), right = SIMD3<Float>(0.6, 0.5, 1)
        for k in 0..<2 {
            let seen = try [left, right].map { try XCTUnwrap(cube(at: $0, side: 0.3)) }
            fusion.integrate(seen, frame: f.sensor, depth: f.depth, time: Double(k))
        }
        XCTAssertEqual(fusion.tracks.count, 2)
        if finishing { for t in fusion.tracks { fusion.finish(t.id, box: t.box, time: 2) } }
        let spanning = try XCTUnwrap(cube(at: (left + right) / 2, side: 0.9, n: 16))
        fusion.integrate([spanning], frame: f.sensor, depth: f.depth, time: 3)
        return fusion
    }

    func test_twoFinishedTracks_neverMerge() throws {
        let control = try twoVasesGrownTogether(finishing: false)
        XCTAssertEqual(control.tracks.count, 1, "the control: unfinished, the grown fit takes the other in")
        let finished = try twoVasesGrownTogether(finishing: true)
        XCTAssertEqual(finished.tracks.count, 2)
        XCTAssertTrue(finished.tracks.allSatisfy { $0.locked != nil })
    }

    func test_aFinish_reachesTheTrackItsObjectWasMergedInto() throws {
        var fusion = try twoVasesGrownTogether(finishing: false)
        let kept = try XCTUnwrap(fusion.tracks.first)
        let absorbed = try XCTUnwrap(fusion.mergedInto.first { $0.value == kept.id }?.key)
        XCTAssertEqual(fusion.resolve(absorbed), kept.id)
        XCTAssertTrue(fusion.finish(absorbed, box: kept.box, time: 4), "finished while its track was merged away")
        XCTAssertEqual(fusion.tracks.first?.locked?.box, kept.box)
        XCTAssertFalse(fusion.finish(UUID(), box: kept.box, time: 5), "a track that never was")
    }
}
