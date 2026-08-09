/// Pins for the floor plan's pure math: segment construction, grid heading,
/// corner adjacency, fit, and the camera plan pose. Synthetic
/// inputs only — the real-room extraction is pinned by FloorPlanFixtureTests
/// on the spike fixture. No RoomPlan session, no ARKit; simulator-safe.

import simd
import XCTest
@testable import RoomStudioCapture

final class FloorPlanMathTests: XCTestCase {

    // MARK: - Segment

    func test_segment_fromCenterAxisWidth() throws {
        let seg = try XCTUnwrap(FloorPlanMath.segment(
            center: SIMD2(1, 2), xAxis: SIMD2(2, 0), width: 4))
        XCTAssertEqual(seg.0.x, -1, accuracy: 1e-5)
        XCTAssertEqual(seg.0.y, 2, accuracy: 1e-5)
        XCTAssertEqual(seg.1.x, 3, accuracy: 1e-5)
        XCTAssertEqual(seg.1.y, 2, accuracy: 1e-5)
    }

    func test_segment_degenerateAxisOrWidth_isNil() {
        // An axis with no XZ component (a surface lying flat) cannot make a
        // wall segment; neither can an unreadably thin width.
        XCTAssertNil(FloorPlanMath.segment(center: .zero, xAxis: SIMD2(0.01, 0), width: 2))
        XCTAssertNil(FloorPlanMath.segment(center: .zero, xAxis: SIMD2(1, 0), width: 0.01))
    }

    // MARK: - Rotation helpers

    func test_rotate_quarterTurn() {
        let r = FloorPlanMath.rotate(SIMD2(1, 0), by: .pi / 2)
        XCTAssertEqual(r.x, 0, accuracy: 1e-5)
        XCTAssertEqual(r.y, 1, accuracy: 1e-5)
    }

    func test_rot90() {
        let r = FloorPlanMath.rot90(SIMD2(1, 0))
        XCTAssertEqual(r.x, 0, accuracy: 1e-6)
        XCTAssertEqual(r.y, 1, accuracy: 1e-6)
    }

    // MARK: - Grid heading

    private func wall(_ s: SIMD2<Float>, _ e: SIMD2<Float>,
                      _ kind: FloorPlanWall.Kind = .wall) -> FloorPlanWall {
        FloorPlanWall(id: UUID(), kind: kind, start: s, end: e)
    }

    func test_gridHeading_perpendicularFamiliesAgree() {
        // Walls at 30° and 120° are one grid: perpendicular families must
        // reinforce, not cancel (the 4·φ trick).
        let a: Float = .pi / 6
        let b: Float = a + .pi / 2
        let walls = [
            wall(.zero, 3 * SIMD2(cos(a), sin(a))),
            wall(.zero, 2 * SIMD2(cos(b), sin(b))),
        ]
        let g = try! XCTUnwrap(FloorPlanMath.gridHeading(walls: walls))
        XCTAssertEqual(g, .pi / 6, accuracy: 1e-3)
    }

    func test_gridHeading_lengthWeighted() {
        // A long on-axis wall dominates a short off-grid one.
        let walls = [
            wall(.zero, SIMD2(10, 0)),
            wall(SIMD2(0, 1), SIMD2(0, 1) + 0.5 * SIMD2(cos(Float.pi / 6), sin(Float.pi / 6))),
        ]
        let g = try! XCTUnwrap(FloorPlanMath.gridHeading(walls: walls))
        XCTAssertLessThan(abs(g), .pi / 180 * 2, "10 m at 0° vs 0.5 m at 30° stays within 2°")
    }

    func test_gridHeading_noWalls_isNil() {
        XCTAssertNil(FloorPlanMath.gridHeading(walls: []))
    }

    func test_gridArc_shortestWayModNinety() {
        // 0° → 50° is −40° the short way round the 90° grid circle.
        let arc = FloorPlanMath.gridArc(from: 0, to: .pi / 180 * 50)
        XCTAssertEqual(arc, -.pi / 180 * 40, accuracy: 1e-4)
        // 0° → 40° goes forward.
        XCTAssertEqual(FloorPlanMath.gridArc(from: 0, to: .pi / 180 * 40),
                       .pi / 180 * 40, accuracy: 1e-4)
    }

    // MARK: - Corner adjacency

    func test_cornerCount_closedRectangle_isFour() {
        let a = SIMD2<Float>(0, 0), b = SIMD2<Float>(4, 0)
        let c = SIMD2<Float>(4, 3), d = SIMD2<Float>(0, 3)
        let walls = [wall(a, b), wall(b, c), wall(c, d), wall(d, a)]
        XCTAssertEqual(FloorPlanMath.cornerCount(walls: walls), 4)
    }

    func test_cornerCount_parallelWalls_isZero() {
        // Near endpoints but collinear headings — a continuation, not a corner.
        let walls = [wall(SIMD2(0, 0), SIMD2(2, 0)), wall(SIMD2(2.1, 0), SIMD2(4, 0))]
        XCTAssertEqual(FloorPlanMath.cornerCount(walls: walls), 0)
    }

    func test_cornerCount_lPair_isOne() {
        let walls = [wall(SIMD2(0, 0), SIMD2(2, 0)), wall(SIMD2(2, 0), SIMD2(2, 2))]
        XCTAssertEqual(FloorPlanMath.cornerCount(walls: walls), 1)
    }

    func test_cornerCount_ignoresDoorSegments() {
        // A door at a wall junction is a cut in the wall, never a corner.
        let walls = [
            wall(SIMD2(0, 0), SIMD2(2, 0)),
            wall(SIMD2(2, 0), SIMD2(2, 2)),
            wall(SIMD2(1.2, 0), SIMD2(1.9, 0), .door),
        ]
        XCTAssertEqual(FloorPlanMath.cornerCount(walls: walls), 1)
    }

    func test_cornerCount_distantWalls_noCorner() {
        let walls = [wall(SIMD2(0, 0), SIMD2(2, 0)), wall(SIMD2(3, 0), SIMD2(3, 2))]
        XCTAssertEqual(FloorPlanMath.cornerCount(walls: walls), 0)
    }

    // MARK: - Fit

    func test_fit_scalesAndCenters() {
        let fit = FloorPlanMath.fit(boundsMin: SIMD2(-2, -1), boundsMax: SIMD2(2, 1),
                                    into: CGSize(width: 400, height: 300), padding: 50)
        XCTAssertEqual(fit.scale, 75, accuracy: 1e-6)   // min(300/4, 200/2) = 75
        let mid = fit.apply(SIMD2(0, 0), in: CGSize(width: 400, height: 300))
        XCTAssertEqual(mid.x, 200, accuracy: 1e-6)
        XCTAssertEqual(mid.y, 150, accuracy: 1e-6)
        let corner = fit.apply(SIMD2(2, 1), in: CGSize(width: 400, height: 300))
        XCTAssertEqual(corner.x, 350, accuracy: 1e-6)
        XCTAssertEqual(corner.y, 225, accuracy: 1e-6)
    }

    func test_fit_capsScale_soFirstWallArrivesSmall() {
        // A lone 1 m wall must not zoom to fill the screen: the min-span floor
        // and the max points-per-meter cap both hold it down.
        let fit = FloorPlanMath.fit(boundsMin: SIMD2(0, 0), boundsMax: SIMD2(1, 0),
                                    into: CGSize(width: 400, height: 400), padding: 24)
        XCTAssertLessThanOrEqual(fit.scale, 90)
    }

    // MARK: - Camera plan pose

    func test_cameraPlanPose_identity_looksDownNegativeZ() throws {
        let cam = try XCTUnwrap(FloorPlanMath.cameraPlanPose(
            transform: matrix_identity_float4x4, previousForward: nil))
        XCTAssertEqual(cam.position.x, 0, accuracy: 1e-6)
        XCTAssertEqual(cam.position.y, 0, accuracy: 1e-6)
        XCTAssertEqual(cam.forward.x, 0, accuracy: 1e-6)
        XCTAssertEqual(cam.forward.y, -1, accuracy: 1e-6)
    }

    func test_cameraPlanPose_yawedNinety() throws {
        // R_y(90°): camera now looks down world -X.
        var t = matrix_identity_float4x4
        t.columns.0 = SIMD4(0, 0, -1, 0)
        t.columns.2 = SIMD4(1, 0, 0, 0)
        t.columns.3 = SIMD4(2, 1.4, -3, 1)
        let cam = try XCTUnwrap(FloorPlanMath.cameraPlanPose(transform: t, previousForward: nil))
        XCTAssertEqual(cam.position.x, 2, accuracy: 1e-6)
        XCTAssertEqual(cam.position.y, -3, accuracy: 1e-6)
        XCTAssertEqual(cam.forward.x, -1, accuracy: 1e-6)
        XCTAssertEqual(cam.forward.y, 0, accuracy: 1e-6)
    }

    func test_cameraPlanPose_pointingStraightDown_keepsPreviousHeading() {
        // Camera -Z along world -Y (looking at the floor): XZ-degenerate.
        var t = matrix_identity_float4x4
        t.columns.1 = SIMD4(0, 0, -1, 0)
        t.columns.2 = SIMD4(0, 1, 0, 0)
        XCTAssertNil(FloorPlanMath.cameraPlanPose(transform: t, previousForward: nil),
                     "No heading ever seen — no cone rather than a spinning guess")
        let held = FloorPlanMath.cameraPlanPose(transform: t, previousForward: SIMD2(1, 0))
        XCTAssertEqual(held?.forward.x, 1)
        XCTAssertEqual(held?.forward.y, 0)
    }
}
