/// Pins for the live-boxes frame maps and box maths, one convention at a time:
/// where a depth pixel lands in the camera image, what each quarter-turn does
/// to a corner, where the letterbox puts the upright image, which way the
/// pinhole model's signs run, and how a gravity-aligned box is represented,
/// overlapped and fitted. Synthetic numbers only; simulator-safe.
///
/// The end-to-end chain over these maps is LiveBoxesLiftingTests; this file is
/// what says, in numbers, what each map IS.

import simd
import XCTest
@testable import TheGoodGuest

final class LiveBoxesGeometryTests: XCTestCase {

    private let intrinsics = CameraIntrinsics(fx: 1500, fy: 1500, cx: 960, cy: 720, width: 1920, height: 1440)

    private func frame(turn: QuarterTurn = .none, model: Int = 640,
                       pose: simd_float4x4 = matrix_identity_float4x4) -> SensorFrame {
        SensorFrame(intrinsics: intrinsics, depthWidth: 256, depthHeight: 192,
                    worldFromCamera: pose, turn: turn, modelWidth: model, modelHeight: model)
    }

    private func assertEqual(_ a: SIMD2<Float>, _ b: SIMD2<Float>, accuracy: Float = 1e-3,
                             file: StaticString = #filePath, line: UInt = #line) {
        XCTAssertEqual(a.x, b.x, accuracy: accuracy, file: file, line: line)
        XCTAssertEqual(a.y, b.y, accuracy: accuracy, file: file, line: line)
    }

    private func assertEqual(_ a: SIMD3<Float>, _ b: SIMD3<Float>, accuracy: Float = 1e-4,
                             file: StaticString = #filePath, line: UInt = #line) {
        XCTAssertEqual(a.x, b.x, accuracy: accuracy, file: file, line: line)
        XCTAssertEqual(a.y, b.y, accuracy: accuracy, file: file, line: line)
        XCTAssertEqual(a.z, b.z, accuracy: accuracy, file: file, line: line)
    }

    // MARK: - Depth ↔ image

    func test_depthPixelCentre_landsAtSevenAndAHalfPixelPitch() {
        // 1920 / 256 = 1440 / 192 = 7.5: depth pixel (i, j) covers
        // [7.5i, 7.5i + 7.5) of the image, so its centre is 7.5i + 3.75.
        let f = frame()
        assertEqual(f.imagePoint(depthX: 0, depthY: 0), SIMD2(3.75, 3.75))
        assertEqual(f.imagePoint(depthX: 255, depthY: 191), SIMD2(1916.25, 1436.25))
        assertEqual(f.imagePoint(depthX: 128, depthY: 96), SIMD2(963.75, 723.75))
    }

    func test_depthPoint_isThePureScaleBack() {
        let f = frame()
        assertEqual(f.depthPoint(image: f.imagePoint(depthX: 17, depthY: 140)), SIMD2(17.5, 140.5))
        assertEqual(f.depthPoint(image: SIMD2(1920, 1440)), SIMD2(256, 192))
    }

    // MARK: - Quarter-turns

    func test_quarterTurns_moveCornersWhereAClockwiseTurnWould() {
        let w: Float = 1920, h: Float = 1440
        // Clockwise: the top edge becomes the right edge.
        assertEqual(QuarterTurn.clockwise.apply(SIMD2(0, 0), width: w, height: h), SIMD2(h, 0))
        assertEqual(QuarterTurn.clockwise.apply(SIMD2(w, 0), width: w, height: h), SIMD2(h, w))
        assertEqual(QuarterTurn.clockwise.apply(SIMD2(0, h), width: w, height: h), SIMD2(0, 0))
        // Half: every corner goes to its opposite.
        assertEqual(QuarterTurn.half.apply(SIMD2(0, 0), width: w, height: h), SIMD2(w, h))
        // Counter-clockwise: the top edge becomes the left edge.
        assertEqual(QuarterTurn.counterClockwise.apply(SIMD2(0, 0), width: w, height: h), SIMD2(0, w))
        assertEqual(QuarterTurn.counterClockwise.apply(SIMD2(w, 0), width: w, height: h), SIMD2(0, 0))
    }

    func test_quarterTurns_invertTheirOwnApply() {
        let w: Float = 1920, h: Float = 1440
        for turn in QuarterTurn.allCases {
            for p in [SIMD2<Float>(0, 0), SIMD2(123.5, 987.25), SIMD2(1920, 1440), SIMD2(1919.5, 0.5)] {
                assertEqual(turn.invert(turn.apply(p, width: w, height: h), width: w, height: h), p)
            }
        }
    }

    func test_turnedSize_swapsOnlyForQuarterTurns() {
        XCTAssertTrue(QuarterTurn.none.turnedSize(width: 1920, height: 1440) == (1920, 1440))
        XCTAssertTrue(QuarterTurn.clockwise.turnedSize(width: 1920, height: 1440) == (1440, 1920))
        XCTAssertTrue(QuarterTurn.half.turnedSize(width: 1920, height: 1440) == (1920, 1440))
        XCTAssertTrue(QuarterTurn.counterClockwise.turnedSize(width: 1920, height: 1440) == (1440, 1920))
    }

    // MARK: - Upright

    func test_upright_readsGravity_notTheInterface() {
        // Camera frame = world (the sensor's own landscape hold): down is −Y.
        XCTAssertEqual(QuarterTurn.upright(gravity: SIMD3(0, -1, 0), previous: nil), .none)
        // Held in portrait, world-down lies along camera ±X (decision 0034).
        XCTAssertEqual(QuarterTurn.upright(gravity: SIMD3(1, 0, 0), previous: nil), .clockwise)
        XCTAssertEqual(QuarterTurn.upright(gravity: SIMD3(-1, 0, 0), previous: nil), .counterClockwise)
        // Upside down.
        XCTAssertEqual(QuarterTurn.upright(gravity: SIMD3(0, 1, 0), previous: nil), .half)
    }

    func test_upright_turnedImageHasDownAtTheBottom() {
        // Whatever the roll, the chosen turn maps the image-plane down
        // direction (gx, −gy) onto +v.
        for roll in stride(from: Float(-3.1), through: 3.1, by: 0.37) {
            let g = SIMD3(sin(roll), -cos(roll), 0)
            let turn = QuarterTurn.upright(gravity: g, previous: nil)
            let base = SIMD2<Float>(500, 500)
            let tip = base + 100 * SIMD2(g.x, -g.y)
            let a = turn.apply(base, width: 1920, height: 1440)
            let b = turn.apply(tip, width: 1920, height: 1440)
            let down = simd_normalize(b - a)
            XCTAssertGreaterThan(down.y, cos(Float.pi / 4) - 1e-3, "roll \(roll) turn \(turn)")
        }
    }

    func test_upright_keepsThePreviousTurn_whenGravityHasNoImageDirection() {
        // Looking straight at the floor: gravity is along the viewing axis.
        XCTAssertEqual(QuarterTurn.upright(gravity: SIMD3(0.05, -0.1, -0.99), previous: .clockwise), .clockwise)
        XCTAssertEqual(QuarterTurn.upright(gravity: SIMD3(0.05, -0.1, -0.99), previous: nil), .none)
    }

    func test_upright_hysteresis_holdsNearTheDiagonal() {
        // 50° from portrait-clockwise toward landscape: a fresh choice picks
        // landscape, but a phone already in portrait stays there until 55°.
        let a: Float = 50 * .pi / 180
        let g = SIMD3(cos(a), -sin(a), 0)
        XCTAssertEqual(QuarterTurn.upright(gravity: g, previous: nil), .none)
        XCTAssertEqual(QuarterTurn.upright(gravity: g, previous: .clockwise), .clockwise)
        let b: Float = 60 * .pi / 180
        XCTAssertEqual(QuarterTurn.upright(gravity: SIMD3(cos(b), -sin(b), 0), previous: .clockwise), .none)
    }

    // MARK: - Letterbox

    func test_letterbox_portraitInto640_scalesByAThird_padsTheSides() {
        let box = Letterbox(sourceWidth: 1440, sourceHeight: 1920, targetWidth: 640, targetHeight: 640)
        XCTAssertEqual(box.scale, 1.0 / 3.0, accuracy: 1e-6)
        XCTAssertEqual(box.padX, 80, accuracy: 1e-4)
        XCTAssertEqual(box.padY, 0, accuracy: 1e-4)
        assertEqual(box.toTarget(SIMD2(0, 0)), SIMD2(80, 0))
        assertEqual(box.toTarget(SIMD2(1440, 1920)), SIMD2(560, 640))
    }

    func test_letterbox_landscapeInto512_padsTopAndBottom() {
        let box = Letterbox(sourceWidth: 1920, sourceHeight: 1440, targetWidth: 512, targetHeight: 512)
        XCTAssertEqual(box.padX, 0, accuracy: 1e-4)
        XCTAssertEqual(box.padY, 64, accuracy: 1e-4)
        assertEqual(box.toSource(box.toTarget(SIMD2(777, 333))), SIMD2(777, 333))
    }

    func test_sensorFrame_modelAndImage_roundTrip_inEveryTurn() {
        for turn in QuarterTurn.allCases {
            let f = frame(turn: turn)
            for p in [SIMD2<Float>(3.75, 3.75), SIMD2(960, 720), SIMD2(1916.25, 12.5)] {
                assertEqual(f.imagePoint(model: f.modelPoint(image: p)), p, accuracy: 2e-3)
            }
        }
    }

    func test_sensorFrame_portraitTurn_putsTheImageCentreAtTheModelCentre() {
        assertEqual(frame(turn: .clockwise).modelPoint(image: SIMD2(960, 720)), SIMD2(320, 320))
        assertEqual(frame(turn: .counterClockwise).modelPoint(image: SIMD2(960, 720)), SIMD2(320, 320))
    }

    func test_depthPixelRange_coversExactlyTheCentresInside() throws {
        let f = frame()
        // Model (0, 80)…(640, 560) is the whole landscape image; every depth pixel.
        let all = try XCTUnwrap(f.depthPixelRange(modelMin: SIMD2(0, 80), modelMax: SIMD2(640, 560)))
        XCTAssertEqual(all.x, 0...255)
        XCTAssertEqual(all.y, 0...191)
        // The first depth pixel's centre is at model (1.25, 81.25).
        let corner = try XCTUnwrap(f.depthPixelRange(modelMin: SIMD2(0, 80), modelMax: SIMD2(1.3, 81.3)))
        XCTAssertEqual(corner.x, 0...0)
        XCTAssertEqual(corner.y, 0...0)
        XCTAssertNil(f.depthPixelRange(modelMin: SIMD2(0, 0), modelMax: SIMD2(640, 79)))
    }

    func test_touchesImageEdge_findsWhatTheFrameCutsOff() {
        let f = frame()   // landscape into 640: the image spans model y 80…560
        let margin = DepthLiftParameters().edgeMargin
        XCTAssertFalse(f.touchesImageEdge(modelMin: SIMD2(300, 300), modelMax: SIMD2(340, 340), margin: margin))
        XCTAssertTrue(f.touchesImageEdge(modelMin: SIMD2(5, 300), modelMax: SIMD2(100, 400), margin: margin),
                      "15 image pixels from the left edge")
        XCTAssertTrue(f.touchesImageEdge(modelMin: SIMD2(300, 300), modelMax: SIMD2(340, 558), margin: margin),
                      "the bottom of the image is model y 560")
        // Held in portrait, the left of the upright image is the top of the sensor's.
        let portrait = frame(turn: .clockwise)
        XCTAssertTrue(portrait.touchesImageEdge(modelMin: SIMD2(81, 300), modelMax: SIMD2(200, 400), margin: margin))
        XCTAssertFalse(portrait.touchesImageEdge(modelMin: SIMD2(200, 300), modelMax: SIMD2(300, 400), margin: margin))
    }

    func test_centreDepthPixel_liesUnderTheMiddleOfTheImage_inEveryHold() {
        for turn in QuarterTurn.allCases {
            let f = frame(turn: turn)
            let c = f.centreDepthPixel
            XCTAssertTrue(c == (128, 96), "\(turn): \(c)")
            // Its 7.5-pixel square of the image holds the image's middle.
            let centre = f.imagePoint(depthX: c.x, depthY: c.y)
            XCTAssertLessThanOrEqual(abs(centre.x - 960), 3.75, "\(turn)")
            XCTAssertLessThanOrEqual(abs(centre.y - 720), 3.75, "\(turn)")
        }
    }

    func test_viewFraction_isTheShareOfTheDepthMapABoxCovers() {
        let f = frame()
        // The whole landscape image, then a quarter of it, then outside it.
        XCTAssertEqual(f.viewFraction(modelMin: SIMD2(0, 80), modelMax: SIMD2(640, 560)), 1, accuracy: 1e-6)
        XCTAssertEqual(f.viewFraction(modelMin: SIMD2(0, 80), modelMax: SIMD2(320, 320)), 0.25, accuracy: 0.01)
        XCTAssertEqual(f.viewFraction(modelMin: SIMD2(0, 0), modelMax: SIMD2(640, 79)), 0)
        // Half a percent of a 640-wide landscape frame is about a 32-pixel square.
        XCTAssertLessThan(f.viewFraction(modelMin: SIMD2(300, 300), modelMax: SIMD2(330, 330)),
                          DepthLiftParameters().minimumViewFraction)
        XCTAssertGreaterThan(f.viewFraction(modelMin: SIMD2(300, 300), modelMax: SIMD2(340, 340)),
                             DepthLiftParameters().minimumViewFraction)
    }

    // MARK: - Pinhole signs

    func test_unproject_followsARKitSigns() {
        // Right of the principal point is +X, below it is −Y, depth is −Z.
        assertEqual(intrinsics.unproject(SIMD2(1110, 870), depth: 2), SIMD3(0.2, -0.2, -2))
        assertEqual(intrinsics.unproject(SIMD2(960, 720), depth: 3), SIMD3(0, 0, -3))
    }

    func test_project_isTheInverse_andRefusesPointsBehind() throws {
        let p = SIMD3<Float>(0.31, -0.42, -2.7)
        let image = try XCTUnwrap(intrinsics.project(p))
        assertEqual(intrinsics.unproject(image, depth: 2.7), p)
        XCTAssertNil(intrinsics.project(SIMD3(0, 0, 1)))
    }

    func test_worldPoint_appliesWorldFromCamera() {
        var pose = matrix_float4x4(simd_quatf(angle: .pi / 2, axis: SIMD3(0, 1, 0)))
        pose.columns.3 = SIMD4(1, 1.5, -2, 1)
        let f = frame(pose: pose)
        // The central depth pixel looks down camera −Z; the camera is turned
        // 90° about +Y, so camera −Z is world −X.
        let centre = f.intrinsics.unproject(f.imagePoint(depthX: 128, depthY: 96), depth: 2)
        let expected = SIMD3<Float>(1, 1.5, -2) + simd_quatf(angle: .pi / 2, axis: SIMD3(0, 1, 0)).act(centre)
        assertEqual(f.worldPoint(depthX: 128, depthY: 96, depth: 2), expected)
        XCTAssertEqual(expected.x, -1, accuracy: 0.02)
        let back = f.depthProjection(world: expected)
        XCTAssertEqual(back?.depth ?? 0, 2, accuracy: 1e-4)
        assertEqual(back?.point ?? .zero, SIMD2(128.5, 96.5), accuracy: 1e-3)
    }

    // MARK: - Boxes

    func test_yaw_isCanonical_andAQuarterTurnSwapsTheExtents() {
        let a = GravityBox(center: .zero, size: SIMD3(1, 2, 3), yaw: .pi / 2 + 0.2)
        XCTAssertEqual(a.yaw, 0.2, accuracy: 1e-5)
        assertEqual(a.size, SIMD3(3, 2, 1))
        let b = GravityBox(center: .zero, size: SIMD3(1, 2, 3), yaw: -0.2)
        XCTAssertEqual(b.yaw, .pi / 2 - 0.2, accuracy: 1e-5)
        assertEqual(b.size, SIMD3(3, 2, 1))
        let c = GravityBox(center: .zero, size: SIMD3(1, 2, 3), yaw: .pi + 0.2)
        assertEqual(c.size, SIMD3(1, 2, 3))
    }

    func test_planAxes_areARightHandedTurnAboutUp() {
        let box = GravityBox(center: .zero, size: SIMD3(1, 1, 1), yaw: 0.3)
        let rotated = simd_quatf(angle: 0.3, axis: SIMD3(0, 1, 0)).act(SIMD3<Float>(1, 0, 0))
        assertEqual(box.planXAxis, SIMD2(rotated.x, rotated.z))
        let t = box.transform
        assertEqual(SIMD3(t.columns.0.x, t.columns.0.y, t.columns.0.z), rotated)
    }

    func test_overlap_identicalDisjointAndNested() {
        let a = GravityBox(center: SIMD3(0, 0.5, 0), size: SIMD3(1, 1, 1), yaw: 0.4)
        XCTAssertEqual(a.iou(a), 1, accuracy: 1e-3)
        XCTAssertEqual(a.iou(GravityBox(center: SIMD3(5, 0.5, 0), size: SIMD3(1, 1, 1), yaw: 0.4)), 0)
        XCTAssertEqual(a.iou(GravityBox(center: SIMD3(0, 3, 0), size: SIMD3(1, 1, 1), yaw: 0.4)), 0)
        let inner = GravityBox(center: SIMD3(0, 0.5, 0), size: SIMD3(0.5, 0.5, 0.5), yaw: 0.4)
        XCTAssertEqual(a.iou(inner), 0.125, accuracy: 1e-3)
        XCTAssertEqual(a.containment(inner), 1, accuracy: 1e-3)
    }

    func test_intersection_ofTwoTurnedSquares_matchesTheOctagon() {
        // A unit square and the same square turned 45° share a regular octagon
        // of area 2(√2 − 1).
        let a = GravityBox(center: .zero, size: SIMD3(1, 1, 1), yaw: 0)
        let b = GravityBox(center: .zero, size: SIMD3(1, 1, 1), yaw: .pi / 4)
        XCTAssertEqual(a.intersectionVolume(b), 2 * (sqrt(2) - 1), accuracy: 1e-3)
    }

    func test_contains_respectsYawAndMargin() {
        let box = GravityBox(center: SIMD3(1, 1, 1), size: SIMD3(2, 2, 0.2), yaw: .pi / 4)
        XCTAssertTrue(box.contains(SIMD3(1.5, 1, 0.5)))       // along the turned long axis
        XCTAssertFalse(box.contains(SIMD3(1.5, 1, 1.5)))      // across it
        XCTAssertTrue(box.contains(SIMD3(1.5, 1, 1.5), margin: 0.65))
    }

    // MARK: - The fit

    private func facePoints(of box: GravityBox, spacing: Float = 0.02,
                            faces: Set<Int> = [0, 1, 2, 3, 4, 5]) -> [SIMD3<Float>] {
        var local: [SIMD3<Float>] = []
        let h = box.size / 2
        func grid(_ a: Float, _ b: Float) -> [(Float, Float)] {
            stride(from: -a, through: a, by: spacing).flatMap { u in
                stride(from: -b, through: b, by: spacing).map { (u, $0) }
            }
        }
        if faces.contains(0) { local += grid(h.y, h.z).map { SIMD3(h.x, $0.0, $0.1) } }
        if faces.contains(1) { local += grid(h.y, h.z).map { SIMD3(-h.x, $0.0, $0.1) } }
        if faces.contains(2) { local += grid(h.x, h.z).map { SIMD3($0.0, h.y, $0.1) } }
        if faces.contains(3) { local += grid(h.x, h.z).map { SIMD3($0.0, -h.y, $0.1) } }
        if faces.contains(4) { local += grid(h.x, h.y).map { SIMD3($0.0, $0.1, h.z) } }
        if faces.contains(5) { local += grid(h.x, h.y).map { SIMD3($0.0, $0.1, -h.z) } }
        let t = box.transform
        return local.map { let w = t * SIMD4($0, 1); return SIMD3(w.x, w.y, w.z) }
    }

    func test_fit_recoversATurnedBox_fromItsSurface() throws {
        let truth = GravityBox(center: SIMD3(0.4, 0.3, -1.2), size: SIMD3(0.8, 0.6, 0.5), yaw: 0.52)
        let fit = try XCTUnwrap(GravityBoxFit.fit(facePoints(of: truth)))
        assertEqual(fit.center, truth.center, accuracy: 0.015)
        assertEqual(fit.size, truth.size, accuracy: 0.03)
        XCTAssertEqual(fit.yaw, truth.yaw, accuracy: 0.02)
    }

    func test_fit_takesYawFromTwoVisibleFaces() throws {
        // A corner seen from outside: two vertical faces and the top.
        let truth = GravityBox(center: SIMD3(0, 0.5, 0), size: SIMD3(1.2, 1, 0.6), yaw: 1.1)
        let fit = try XCTUnwrap(GravityBoxFit.fit(facePoints(of: truth, faces: [0, 2, 4])))
        XCTAssertEqual(fit.yaw, truth.yaw, accuracy: 0.02)
    }

    func test_faceDirection_readsVerticalFaces_andIgnoresTops() throws {
        let truth = GravityBox(center: SIMD3(0.4, 0.3, -1.2), size: SIMD3(0.8, 0.6, 0.5), yaw: 0.52)
        func direction(_ faces: Set<Int>) -> (phi: Float, consistency: Float, faceShare: Float)? {
            let plan = facePoints(of: truth, faces: faces).map { SIMD2($0.x, $0.z) }
            return GravityBoxFit.faceDirection(plan, weights: [Float](repeating: 1, count: plan.count))
        }
        // Four walls of samples: consistent, mostly face, and the right way.
        let walls = try XCTUnwrap(direction([0, 1, 4, 5]))
        XCTAssertGreaterThan(walls.consistency, 0.9)
        XCTAssertGreaterThan(walls.faceShare, GravityBoxFit.faceShare)
        let wrapped = atan2(sin(4 * (-walls.phi - truth.yaw)), cos(4 * (-walls.phi - truth.yaw))) / 4
        XCTAssertEqual(wrapped, 0, accuracy: 0.012)
        // A top alone is an area, not a face: too little share to trust, so a
        // flat object's yaw falls to the minimum-area rectangle.
        let top = try XCTUnwrap(direction([2]))
        XCTAssertLessThan(top.faceShare, GravityBoxFit.faceShare)
    }

    func test_fit_lightStraysCannotSetAFace() throws {
        let truth = GravityBox(center: .zero, size: SIMD3(0.6, 0.6, 0.6), yaw: 0.2)
        var points = facePoints(of: truth)
        var weights = [Float](repeating: 20, count: points.count)
        // A handful of single-sample strays half a metre out.
        for k in 0..<12 {
            points.append(SIMD3(0.8 + Float(k) * 0.01, 0, 0))
            weights.append(1)
        }
        let fit = try XCTUnwrap(GravityBoxFit.fit(points, weights: weights))
        XCTAssertLessThan(max(fit.size.x, fit.size.z), 0.66)
    }

    func test_fit_aRoundObjectTakesTheWalls_aBoxClearlyTurnedKeepsItsFaces() throws {
        // A cylinder has no faces: its turn comes from the walls, not its hull.
        var ring: [SIMD3<Float>] = []
        for k in 0..<72 {
            let a = Float(k) * 5 * .pi / 180
            for y in stride(from: Float(0), through: 0.4, by: 0.05) {
                ring.append(SIMD3(1 + 0.15 * cos(a), y, -2 + 0.15 * sin(a)))
            }
        }
        for phi: Float in [0.3, 1.1] {
            let fit = try XCTUnwrap(GravityBoxFit.fit(ring, wallGrid: phi))
            let turn = (-fit.yaw).truncatingRemainder(dividingBy: .pi / 2)
            let wrapped = turn < 0 ? turn + .pi / 2 : turn
            XCTAssertEqual(wrapped, phi.truncatingRemainder(dividingBy: .pi / 2), accuracy: 1e-4, "phi \(phi)")
        }
        // A box whose faces are turned 43° from the walls keeps the turn its faces give.
        let truth = GravityBox(center: SIMD3(0.4, 0.3, -1.2), size: SIMD3(0.8, 0.6, 0.5), yaw: 0.52)
        let boxFit = try XCTUnwrap(GravityBoxFit.fit(facePoints(of: truth), wallGrid: 0.3))
        XCTAssertEqual(boxFit.yaw, truth.yaw, accuracy: 0.02)
    }

    private func turn(_ box: GravityBox, from grid: Float) -> Float {
        GravityBoxFit.quarterDistance(-box.yaw, grid) * 180 / .pi
    }

    func test_withTheWallsKnown_aBoxWithinSevenDegreesOfThem_isSquareToThem() throws {
        // Clean faces 4° off the walls: square to the walls, exactly.
        let near = GravityBox(center: SIMD3(0.4, 0.3, -1.2), size: SIMD3(0.8, 0.6, 0.5), yaw: 4 * .pi / 180)
        let snapped = try XCTUnwrap(GravityBoxFit.fit(facePoints(of: near), wallGrid: 0))
        XCTAssertEqual(turn(snapped, from: 0), 0, accuracy: 1e-4)
        XCTAssertFalse(GravityBoxFit.isTurned(snapped, from: 0))
        // 20° off: the faces are reliable and clearly turned, and turn the box.
        let off = GravityBox(center: SIMD3(0.4, 0.3, -1.2), size: SIMD3(0.8, 0.6, 0.5), yaw: 20 * .pi / 180)
        let turned = try XCTUnwrap(GravityBoxFit.fit(facePoints(of: off), wallGrid: 0))
        XCTAssertEqual(turn(turned, from: 0), 20, accuracy: 1)
        XCTAssertTrue(GravityBoxFit.isTurned(turned, from: 0))
    }

    func test_withTheWallsKnown_facesThatDoNotAgree_leaveTheBoxSquareToThem() throws {
        // A scatter with no faces to speak of — a plant, a cushion, a chair
        // seen in pieces — whatever its outline does from pass to pass.
        var rng = SeededGenerator(seed: 17)
        let blob = (0..<600).map { _ in
            SIMD3(0.3 * rng.gaussian() * 0.5, 0.4 + 0.2 * rng.gaussian(), -1 + 0.6 * rng.unit() * rng.unit())
        }
        let fit = try XCTUnwrap(GravityBoxFit.fit(blob, wallGrid: 0.35))
        XCTAssertEqual(turn(fit, from: 0.35), 0, accuracy: 1e-4)
    }

    func test_aRugsOutline_turnsItsBox_unlessWithinSevenDegreesOfTheWalls() throws {
        func rug(_ degrees: Float) -> [SIMD3<Float>] {
            facePoints(of: GravityBox(center: SIMD3(0, 0.006, -1), size: SIMD3(1.6, 0.012, 1.1),
                                      yaw: degrees * .pi / 180), faces: [2])
        }
        let turned = try XCTUnwrap(GravityBoxFit.fit(rug(12), wallGrid: 0, flat: true))
        XCTAssertEqual(turn(turned, from: 0), 12, accuracy: 1)
        let square = try XCTUnwrap(GravityBoxFit.fit(rug(5), wallGrid: 0, flat: true))
        XCTAssertEqual(turn(square, from: 0), 0, accuracy: 1e-4)
    }

    func test_quarterDistance_readsTheQuarterTurnSymmetry() {
        let d = Float.pi / 180
        XCTAssertEqual(GravityBoxFit.quarterDistance(5 * d, 85 * d) / d, 10, accuracy: 1e-3)
        XCTAssertEqual(GravityBoxFit.quarterDistance(-3 * d, 3 * d) / d, 6, accuracy: 1e-3)
        XCTAssertEqual(GravityBoxFit.quarterDistance(0, 45 * d) / d, 45, accuracy: 1e-3)
        XCTAssertEqual(GravityBoxFit.quarterDistance(10 * d, 190 * d) / d, 0, accuracy: 1e-3)
    }

    func test_wallGrid_isTheQuarterTurnMeanOfTheWalls() throws {
        XCTAssertNil(WallGrid.phi([]))
        // Walls along x and along z are one grid at 0.
        XCTAssertEqual(try XCTUnwrap(WallGrid.phi([(SIMD2(1, 0), 3), (SIMD2(0, 1), 2)])), 0, accuracy: 1e-5)
        // Walls at 30° and 120° (and a normal, pointing across one) are one grid at 30°.
        let a: Float = 30 * .pi / 180
        let walls: [(direction: SIMD2<Float>, weight: Float)] = [
            (SIMD2(cos(a), sin(a)), 2), (SIMD2(-sin(a), cos(a)), 3), (SIMD2(sin(a), -cos(a)), 1)]
        XCTAssertEqual(try XCTUnwrap(WallGrid.phi(walls)), a, accuracy: 1e-5)
    }

    func test_aVerticalPlane_becomesAWallWhereARKitMeasuredIt() throws {
        // A plane facing +z, standing at z = −2, measured from x −1 to 1.5 and up to 2.4 m.
        let boundary: [SIMD3<Float>] = [SIMD3(-1, 0, -2), SIMD3(1.5, 0, -2), SIMD3(1.5, 2.4, -2), SIMD3(-1, 2.4, -2)]
        let wall = try XCTUnwrap(VerticalSurface(normal: SIMD3(0, 0, 1), point: SIMD3(0.3, 1, -2), boundary: boundary))
        XCTAssertEqual(wall.distance(SIMD3(0.2, 1, -1.5)), 0.5, accuracy: 1e-6, "positive on the normal's side")
        XCTAssertEqual(wall.distance(SIMD3(0.2, 1, -2.1)), -0.1, accuracy: 1e-6)
        XCTAssertTrue(wall.covers(SIMD3(1.4, 2.3, -1.9), margin: 0))
        XCTAssertFalse(wall.covers(SIMD3(1.7, 1, -1.9), margin: 0.1), "past its measured end")
        XCTAssertTrue(wall.covers(SIMD3(1.55, 1, -1.9), margin: 0.1), "within the margin")
        XCTAssertFalse(wall.covers(SIMD3(0, 2.6, -1.9), margin: 0.1), "above what was measured")
        // A floor's normal, or one leaning like a ramp, is no wall.
        XCTAssertNil(VerticalSurface(normal: SIMD3(0, 1, 0), point: .zero, boundary: boundary))
        XCTAssertNil(VerticalSurface(normal: simd_normalize(SIMD3(0.5, 0.8, 0)), point: .zero, boundary: boundary))
        XCTAssertNil(VerticalSurface(normal: SIMD3(0, 0, 1), point: .zero, boundary: []))
    }

    func test_aBoxAgainstAWall_getsItsBackOnTheWall_andOnlyThen() {
        // A wall at z = −2, facing +z into the room.
        let wall = VerticalSurface(normal: SIMD2(0, 1), offset: -2, along: -3...3, heights: 0...2.5)
        func back(_ b: GravityBox) -> Float { b.center.z - b.size.z / 2 }
        func front(_ b: GravityBox) -> Float { b.center.z + b.size.z / 2 }
        // Its back 3 cm off the wall: grown onto it, the front where it was.
        let near = GravityBox(center: SIMD3(0, 0.9, -1.82), size: SIMD3(0.8, 1.8, 0.30), yaw: 0)
        let onto = GravityBoxFit.aligned(near, against: wall, reach: 0.06)
        XCTAssertEqual(back(onto), -2, accuracy: 1e-5)
        XCTAssertEqual(front(onto), front(near), accuracy: 1e-5)
        XCTAssertEqual(onto.size.x, near.size.x, accuracy: 1e-6)
        // Its back 2 cm into the wall: pulled out onto it.
        let into = GravityBox(center: SIMD3(0, 0.9, -1.87), size: SIMD3(0.8, 1.8, 0.30), yaw: 0)
        XCTAssertEqual(back(GravityBoxFit.aligned(into, against: wall, reach: 0.06)), -2, accuracy: 1e-5)
        // 7.5 cm off, like a sofa pulled out from the wall: a gap, left alone.
        let apart = GravityBox(center: SIMD3(0, 0.45, -1.775), size: SIMD3(1.6, 0.9, 0.30), yaw: 0)
        XCTAssertEqual(GravityBoxFit.aligned(apart, against: wall, reach: 0.06), apart)
        // Turned 20° to the wall: no face is square to it, left alone.
        let turned = GravityBox(center: near.center, size: near.size, yaw: 20 * .pi / 180)
        XCTAssertEqual(GravityBoxFit.aligned(turned, against: wall, reach: 0.06), turned)
        // A quarter turn is still square: the other extent meets the wall.
        let quarter = GravityBox(center: SIMD3(0, 0.9, -1.82), size: SIMD3(0.30, 1.8, 0.8), yaw: .pi / 2)
        XCTAssertEqual(back(GravityBoxFit.aligned(quarter, against: wall, reach: 0.06)), -2, accuracy: 1e-4)
    }

    func test_fit_needsAMinimumOfPoints() {
        XCTAssertNil(GravityBoxFit.fit([SIMD3<Float>](repeating: .zero, count: GravityBoxFit.minimumPoints - 1)))
    }

    // MARK: - Lifter parts

    func test_depthEdge_dropsWhatIsBehindAStep_keepsTheForeground() {
        // Row: 1.0 1.0 | 2.0 2.0 — the 1.0 at the step is foreground and stays;
        // the 2.0 beside it is background and goes.
        let grid = DepthGrid(width: 4, height: 1, depth: [1, 1, 2, 2], confidence: nil)
        let p = DepthLiftParameters()
        XCTAssertFalse(DepthLifter.isOnDepthEdge(x: 1, y: 0, depth: 1, grid: grid, parameters: p))
        XCTAssertTrue(DepthLifter.isOnDepthEdge(x: 2, y: 0, depth: 2, grid: grid, parameters: p))
        XCTAssertFalse(DepthLifter.isOnDepthEdge(x: 3, y: 0, depth: 2, grid: grid, parameters: p))
    }

    func test_dominantGroup_splitsAtTheGap_andPrefersTheLargerGroup() {
        let p = DepthLiftParameters()
        let depths: [Float] = [1.0, 1.01, 1.02, 1.03, 1.5, 1.51, 1.52, 1.53, 1.54]
        let group = DepthLifter.dominantGroup(depths, parameters: p)
        XCTAssertEqual(group.lowerBound, 1.5, accuracy: 1e-6)
        XCTAssertEqual(group.upperBound, 1.54, accuracy: 1e-6)
    }

    func test_planeExtent_isTheMinimumRectangleAroundItsBoundary() throws {
        // A turned 1.0 × 0.6 table top, its boundary sampled the way ARKit
        // reports one: points along every edge.
        let center = SIMD2<Float>(1.2, -0.7), angle: Float = 0.4
        let u = SIMD2(cos(angle), sin(angle)), v = SIMD2(-u.y, u.x)
        var boundary: [SIMD2<Float>] = []
        for k in 0...20 {
            let s = Float(k) / 20 - 0.5
            boundary += [center + u * s + v * 0.3, center + u * s - v * 0.3,
                         center + u * 0.5 + v * (s * 0.6), center - u * 0.5 + v * (s * 0.6)]
        }
        let extent = try XCTUnwrap(PlanRectangle.enclosing(boundary))
        assertEqual(extent.center, center)
        let halves = [extent.halfExtents.x, extent.halfExtents.y].sorted()
        XCTAssertEqual(halves[0], 0.3, accuracy: 1e-3)
        XCTAssertEqual(halves[1], 0.5, accuracy: 1e-3)
        XCTAssertTrue(extent.contains(center + u * 0.45 + v * 0.25))
        XCTAssertFalse(extent.contains(center + u * 0.25 + v * 0.45), "across the short side, past it")
        XCTAssertTrue(extent.contains(center + u * 0.25 + v * 0.45, margin: 0.2))
        XCTAssertNil(PlanRectangle.enclosing([SIMD2(0, 0), SIMD2(1, 1), SIMD2(2, 2)]), "a line encloses nothing")
    }

    func test_floorsAndCeilingsReachTheRoom_tableTopsOnlyWhereTheyAre() {
        let top = HorizontalSurface(kind: .support, height: 0.75,
                                    extent: PlanRectangle(center: .zero, axis: SIMD2(1, 0), halfExtents: SIMD2(0.5, 0.3)))
        XCTAssertTrue(top.covers(SIMD3(0.4, 0.75, 0.2), margin: 0))
        XCTAssertFalse(top.covers(SIMD3(2, 0.75, 0), margin: 0.1))
        XCTAssertTrue(HorizontalSurface(kind: .floor, height: 0, extent: nil).covers(SIMD3(9, 0, -9), margin: 0))
        XCTAssertTrue(top.supportsObjects)
        XCTAssertFalse(top.hangsObjects, "a table top is nobody's ceiling")
        let unclassified = HorizontalSurface(kind: .unclassified, height: 1.2, extent: top.extent)
        XCTAssertTrue(unclassified.supportsObjects && unclassified.hangsObjects)
        XCTAssertFalse(HorizontalSurface(kind: .ceiling, height: 2.6, extent: nil).supportsObjects)
    }

    func test_maskInset_countsInwardFromTheEdge() {
        let mask = DepthMask(xRange: 0...4, yRange: 0...4) { x, y in (0...4).contains(x) && (0...4).contains(y) }
        let inset = mask.inset()
        XCTAssertEqual(inset[0], 1)            // a corner
        XCTAssertEqual(inset[1 * 5 + 1], 2)
        XCTAssertEqual(inset[2 * 5 + 2], 3)    // the centre of a 5×5
    }

    // MARK: - Who owns a pixel

    private func square(_ x: ClosedRange<Int>, _ y: ClosedRange<Int>) -> DepthMask {
        DepthMask(xRange: x, yRange: y) { _, _ in true }
    }

    private func owned(_ claims: [Int: (mask: DepthMask, score: Float)]) -> [Int: DepthMask] {
        DepthMask.owned(claims)
    }

    func test_anObjectOnAnother_keepsItsPixels_howeverSureTheOtherIs() throws {
        // A cushion wholly inside a sofa's mask; the sofa scored higher.
        let result = owned([0: (square(0...19, 0...9), 0.95), 1: (square(4...7, 2...5), 0.6)])
        XCTAssertEqual(try XCTUnwrap(result[1]).count, 16, "the cushion keeps all of itself")
        XCTAssertEqual(try XCTUnwrap(result[0]).count, 200 - 16)
        XCTAssertFalse(try XCTUnwrap(result[0])[5, 3])
    }

    func test_sideBySide_theSurerDetectionKeepsTheOverlap_andOnATieTheSmaller() throws {
        // A chair (0.93) standing before a table (0.65): 12 shared pixels, a
        // third of the chair — not nested. The chair is the larger here.
        let chair = square(0...5, 0...7), table = square(4...9, 2...5)
        var result = owned([0: (chair, 0.93), 1: (table, 0.65)])
        XCTAssertEqual(try XCTUnwrap(result[0]).count, 48, "the chair keeps the overlap")
        XCTAssertEqual(try XCTUnwrap(result[1]).count, 24 - 8)
        result = owned([0: (chair, 0.65), 1: (table, 0.93)])
        XCTAssertEqual(try XCTUnwrap(result[1]).count, 24, "the surer one, whichever it is")
        XCTAssertEqual(try XCTUnwrap(result[0]).count, 48 - 8)
        result = owned([0: (chair, 0.8), 1: (table, 0.8)])
        XCTAssertEqual(try XCTUnwrap(result[1]).count, 24, "a tie goes to the smaller")
    }

    func test_aPixelStaysOnlyWithAMaskThatWinsItAgainstEveryClaimant() throws {
        // A book on a shelf in front of which a chair stands.
        let shelf = square(0...9, 0...9), book = square(2...3, 2...3), chair = square(2...9, 2...9)
        let result = owned([0: (shelf, 0.7), 1: (book, 0.5), 2: (chair, 0.9)])
        XCTAssertEqual(try XCTUnwrap(result[1]).count, 4, "the book is inside both, and keeps itself")
        XCTAssertFalse(try XCTUnwrap(result[2])[2, 2], "the chair loses the book's pixels")
        XCTAssertFalse(try XCTUnwrap(result[0])[5, 5], "the shelf loses the chair standing before it")
        XCTAssertTrue(try XCTUnwrap(result[0])[0, 0])
    }
}
