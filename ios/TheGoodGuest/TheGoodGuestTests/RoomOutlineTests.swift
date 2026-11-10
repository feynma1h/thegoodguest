/// Pins the room picture's outline: the geometry that squares a room to its
/// frame, and the overall size it reports as a measurement.

import XCTest
@testable import TheGoodGuest

final class RoomOutlineTests: XCTestCase {

    private func rotated(_ points: [[Double]], by degrees: Double) -> [[Double]] {
        let a = degrees * .pi / 180
        return points.map { [$0[0] * cos(a) - $0[1] * sin(a), $0[0] * sin(a) + $0[1] * cos(a)] }
    }

    func testARectangleReportsItsSidesLongestFirst() {
        let outline = RoomOutline.make(polygon: [[0, 0], [3.6, 0], [3.6, 4.4], [0, 4.4]])
        XCTAssertEqual(outline?.sizeText, "4.40 × 3.60 m")
    }

    func testTheSizeDoesNotDependOnHowTheRoomSitsInTheWorld() {
        let room = [[0, 0], [4.4, 0], [4.4, 3.6], [0, 3.6]]
        for degrees in [0.0, 17, 30, 45, 90, 133] {
            XCTAssertEqual(RoomOutline.make(polygon: rotated(room, by: degrees))?.sizeText, "4.40 × 3.60 m", "\(degrees)°")
        }
    }

    func testAnLShapedRoomReportsItsOverallExtent() {
        let outline = RoomOutline.make(polygon: [[0, 0], [4.4, 0], [4.4, 3.6], [1.2, 3.6], [1.2, 2.9], [0, 2.9]])
        XCTAssertEqual(outline?.sizeText, "4.40 × 3.60 m")
        XCTAssertEqual(outline?.points.count, 6)
    }

    func testWorldPointsAreReadAsXAndZ() {
        // RoomPlan's shell gives [x, y, z]; the floor's height is not part of the plan.
        let outline = RoomOutline.make(polygon: [[0, -1.4, 0], [5.2, -1.4, 0], [5.2, -1.4, 4.1], [0, -1.4, 4.1]])
        XCTAssertEqual(outline?.sizeText, "5.20 × 4.10 m")
    }

    func testTheOutlineFitsItsFrame() {
        let outline = RoomOutline.make(polygon: rotated([[0, 0], [4.4, 0], [4.4, 3.6], [0, 3.6]], by: 30))!
        for p in outline.points {
            XCTAssertGreaterThanOrEqual(p.x, -0.0001); XCTAssertLessThanOrEqual(p.x, 1.0001)
            XCTAssertGreaterThanOrEqual(p.y, -0.0001); XCTAssertLessThanOrEqual(p.y, 1.0001)
        }
        let xs = outline.points.map(\.x)
        XCTAssertEqual(xs.max()! - xs.min()!, 1, accuracy: 0.001, "the long side spans the frame")
    }

    func testNothingToDrawIsNil() {
        XCTAssertNil(RoomOutline.make(polygon: []))
        XCTAssertNil(RoomOutline.make(polygon: [[0, 0], [1, 1]]))
        XCTAssertNil(RoomOutline.make(polygon: [[0, 0], [1, 0], [2, 0]]), "a line has no area")
    }
}
