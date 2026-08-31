/// Real-room pins for the floor-plan extraction: the spike reference room's
/// CapturedRoom JSON (the SAME fixture perception-obj's roomplan_room pins
/// server-side, committed verbatim from the probe run) decodes through
/// Apple's Codable path and extracts to the numbers the design recorded —
/// 13 walls, 9 objects, the 14.98 m² ten-corner floor, the ~43.7° wall-grid
/// heading, the −84.3° dining chair, and the low-confidence
/// wardrobe/"refrigerator" staying unlabeled.
///
/// Pinned at achieved accuracy per house rule. If Apple's Codable schema
/// changes (a `version` bump), the DECODE fails first — which is exactly the
/// signal the server-side version pin in test_roomplan_room.py watches for;
/// this is its client twin.

import RoomPlan
import simd
import XCTest
@testable import TheGoodGuest

final class FloorPlanFixtureTests: XCTestCase {

    private static var cachedRoom: CapturedRoom?

    private func loadRoom() throws -> CapturedRoom {
        if let room = Self.cachedRoom { return room }
        let url = try XCTUnwrap(
            Bundle(for: FloorPlanFixtureTests.self)
                .url(forResource: "captured_room_built", withExtension: "json"),
            "Fixture missing from the test bundle — captured_room_built.json must sit in TheGoodGuestTests/")
        let room = try JSONDecoder().decode(CapturedRoom.self, from: Data(contentsOf: url))
        Self.cachedRoom = room
        return room
    }

    // MARK: - Decode + census

    func test_fixtureDecodes_withSpikeCensus() throws {
        let room = try loadRoom()
        XCTAssertEqual(room.walls.count, 13)
        XCTAssertEqual(room.doors.count, 2)
        XCTAssertEqual(room.windows.count, 2)
        XCTAssertEqual(room.openings.count, 2)
        XCTAssertEqual(room.objects.count, 9)
        XCTAssertEqual(room.floors.count, 1)
    }

    // MARK: - Extraction

    func test_extraction_wallSegments() throws {
        let snap = FloorPlanSnapshot(room: try loadRoom())
        XCTAssertEqual(snap.walls.filter { $0.kind == .wall }.count, 13)
        XCTAssertEqual(snap.walls.filter { $0.kind == .door }.count, 2)
        XCTAssertEqual(snap.walls.filter { $0.kind == .window }.count, 2)
        XCTAssertEqual(snap.walls.filter { $0.kind == .opening }.count, 2)
        // Every segment is drawable: no degenerate leftovers. The floor is the
        // extraction's own width gate (0.05 m) — the real room carries one
        // 5.2 cm sliver opening, measured on first run.
        for w in snap.walls {
            XCTAssertGreaterThan(simd_distance(w.start, w.end), 0.05)
        }
    }

    func test_extraction_gridHeading_matchesSpikeFamilies() throws {
        // The two perpendicular wall families sit at ~43.7° to the world axes
        // (the design's "43.5° family heading", re-derived by
        // FloorPlanMath.gridHeading at 43.680°; pinned at achieved accuracy).
        let snap = FloorPlanSnapshot(room: try loadRoom())
        let g = try XCTUnwrap(FloorPlanMath.gridHeading(walls: snap.walls))
        XCTAssertEqual(Double(g) * 180 / .pi, 43.680, accuracy: 0.1)
    }

    func test_extraction_cornerAdjacencies() throws {
        // 13 walls incl. the door-height nook segments join at 14 measured
        // corner adjacencies under the 0.35 m / 45°–135° rule — comfortably
        // "a closed room's worth" for the CORNERS tick.
        let snap = FloorPlanSnapshot(room: try loadRoom())
        XCTAssertEqual(FloorPlanMath.cornerCount(walls: snap.walls), 14)
    }

    func test_extraction_floorPolygon() throws {
        // The ten-corner floor at 14.98 m² (0076 Q5), transformed to world XZ.
        let snap = FloorPlanSnapshot(room: try loadRoom())
        XCTAssertEqual(snap.floorPolygon.count, 10)
        var area: Float = 0
        for i in snap.floorPolygon.indices {
            let a = snap.floorPolygon[i]
            let b = snap.floorPolygon[(i + 1) % snap.floorPolygon.count]
            area += a.x * b.y - b.x * a.y
        }
        XCTAssertEqual(abs(area) / 2, 14.9815, accuracy: 0.02)
    }

    func test_extraction_boxes() throws {
        let snap = FloorPlanSnapshot(room: try loadRoom())
        XCTAssertEqual(snap.boxes.count, 9, "All 9 upright boxes extract (0076 Q4)")

        // The bed's footprint is the box truth: 1.85 × 2.16 m (decision 0077 —
        // the depth fit had halved it; the box owns measurement).
        let bed = try XCTUnwrap(snap.boxes.first { $0.categoryToken == "bed" })
        XCTAssertEqual(bed.halfExtents.x * 2, 1.85, accuracy: 0.01)
        XCTAssertEqual(bed.halfExtents.y * 2, 2.16, accuracy: 0.01)

        // The dining chair sits at −84.3° world yaw (the "40.8° off the wall
        // grid" chair) — yaw recovered from the stored xAxis via the spike's
        // own formula, atan2(−z, x).
        let yaws = snap.boxes.map { atan2(-$0.xAxis.y, $0.xAxis.x) * 180 / .pi }
        XCTAssertTrue(yaws.contains { abs($0 - (-84.30)) < 0.1 },
                      "expected the −84.3° chair; got \(yaws)")
    }

    func test_extraction_wardrobeMislabel_staysUnlabeled() throws {
        // The one category error in the reference room: a wardrobe shipped as
        // "refrigerator" at LOW confidence. End-to-end the honesty rule holds:
        // the box extracts, and the label gate keeps it nameless.
        let snap = FloorPlanSnapshot(room: try loadRoom())
        let fridge = try XCTUnwrap(snap.boxes.first { $0.categoryToken == "refrigerator" })
        XCTAssertEqual(fridge.confidence, .low)
        XCTAssertNil(FloorPlanVoice.boxLabel(categoryToken: fridge.categoryToken,
                                             confidence: fridge.confidence))
        XCTAssertEqual(FloorPlanVoice.momentLine(categoryToken: fridge.categoryToken,
                                                 confidence: fridge.confidence),
                       "Something new — noted.")
    }

    func test_extraction_wallsAreUpright_gridFrameSquares() throws {
        // With the grid heading applied, every wall segment sits near
        // axis-aligned — the property that makes the squared-to-screen
        // rendering honest. Pinned at achieved accuracy: the worst wall
        // measured 2.54° off the length-weighted grid on first run (the
        // spike's "within 0.3°" was family-internal, not vs the mean).
        let snap = FloorPlanSnapshot(room: try loadRoom())
        let g = try XCTUnwrap(FloorPlanMath.gridHeading(walls: snap.walls))
        for w in snap.walls where w.kind == .wall {
            let d = FloorPlanMath.rotate(w.end - w.start, by: -g)
            let heading = atan2(d.y, d.x) * 180 / .pi
            let offAxis = abs(heading.truncatingRemainder(dividingBy: 90))
            let dist = min(offAxis, 90 - offAxis)
            XCTAssertLessThan(dist, 3.0, "wall off the grid by \(dist)°")
        }
    }
}
