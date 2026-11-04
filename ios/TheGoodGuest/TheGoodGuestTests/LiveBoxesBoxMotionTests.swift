/// Pins for how a box moves and merges: table names are one kind in fusion, a
/// finish follows an object through the tracks that absorb it, and a box eases
/// toward a new fit along straight lines and the short way round a quarter turn.

import simd
import XCTest
@testable import TheGoodGuest

final class LiveBoxesBoxMotionTests: XCTestCase {

    private let a = UUID(), b = UUID()

    func test_tableNamesAreOneKindInFusion_andOtherNamesAreNot() {
        XCTAssertTrue(BoxFusion.sameKind("TABLE", "DESK"))
        XCTAssertTrue(BoxFusion.sameKind("COFFEE TABLE", "SIDE TABLE"))
        XCTAssertTrue(BoxFusion.sameKind("SOFA", "SOFA"))
        XCTAssertFalse(BoxFusion.sameKind("TABLE", "CHAIR"))
        XCTAssertFalse(BoxFusion.sameKind("CUSHION", "SOFA"))
    }

    func test_resolve_followsAChainOfMerges() {
        let c = UUID(), stranger = UUID()
        let merged = [a: b, b: c]
        XCTAssertEqual(BoxFusion.resolve(a, through: merged), c)
        XCTAssertEqual(BoxFusion.resolve(c, through: merged), c)
        XCTAssertEqual(BoxFusion.resolve(stranger, through: merged), stranger)
    }

    private func assertSameBox(_ x: GravityBox, _ y: GravityBox, _ message: String = "",
                               file: StaticString = #filePath, line: UInt = #line) {
        XCTAssertLessThan(simd_distance(x.center, y.center), 1e-4, message, file: file, line: line)
        XCTAssertEqual(x.yaw, y.yaw, accuracy: 1e-4, message, file: file, line: line)
        XCTAssertLessThan(simd_reduce_max(simd_abs(x.size - y.size)), 1e-4, message, file: file, line: line)
    }

    func test_approaching_movesTheCentreAndExtentsAlongStraightLines() {
        let from = GravityBox(center: SIMD3(0, 0.5, -1), size: SIMD3(0.4, 1.0, 0.3), yaw: 0.2)
        let to = GravityBox(center: SIMD3(0.2, 0.6, -1.4), size: SIMD3(0.6, 1.2, 0.5), yaw: 0.3)
        assertSameBox(from.approaching(to, fraction: 0), from, "none of the way")
        assertSameBox(from.approaching(to, fraction: 1), to, "all of the way")
        assertSameBox(from.approaching(to, fraction: 0.5),
                      GravityBox(center: SIMD3(0.1, 0.55, -1.2), size: SIMD3(0.5, 1.1, 0.4), yaw: 0.25))
    }

    func test_approaching_turnsTheShortWay_overTheQuarterTurn() {
        let degree = Float.pi / 180
        let from = GravityBox(center: .zero, size: SIMD3(0.8, 1, 0.4), yaw: 88 * degree)
        // The same box turned six degrees on, which is canonical at 4° with X and Z swapped.
        let to = GravityBox(center: .zero, size: SIMD3(0.8, 1, 0.4), yaw: 94 * degree)
        XCTAssertEqual(to.yaw, 4 * degree, accuracy: 1e-5)
        XCTAssertEqual(to.size.x, 0.4, accuracy: 1e-6)
        let halfway = from.approaching(to, fraction: 0.5)
        assertSameBox(halfway, GravityBox(center: .zero, size: SIMD3(0.8, 1, 0.4), yaw: 91 * degree),
                      "three degrees on, not 42° back with its extents averaged")
        XCTAssertGreaterThan(halfway.iou(from), 0.9, "a three-degree turn barely moves it")
    }
}
