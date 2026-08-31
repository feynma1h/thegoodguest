/// Pins for the floor plan's language tables (FloorPlanVoice):
/// category naming under the confidence gate, the instruction relay, the
/// spoken-line priority, the "enough" confirmation, and the coverage-tick
/// mapping. These are the decisions the capture screen SPEAKS — pinned as
/// tables per the house pattern so a copy drift is a test failure.

import XCTest
@testable import TheGoodGuestCapture

final class FloorPlanVoiceTests: XCTestCase {

    // MARK: - Box labels (confidence-gated naming)

    func test_boxLabel_knownCategories() {
        XCTAssertEqual(FloorPlanVoice.boxLabel(categoryToken: "bed", confidence: .high), "BED")
        XCTAssertEqual(FloorPlanVoice.boxLabel(categoryToken: "television", confidence: .medium), "TV")
        XCTAssertEqual(FloorPlanVoice.boxLabel(categoryToken: "storage", confidence: .medium), "STORAGE")
    }

    func test_boxLabel_lowConfidence_staysQuiet() {
        // The spike's wardrobe shipped as "refrigerator" at LOW confidence —
        // the app must not speak a confidently wrong name (0076 Q4).
        XCTAssertNil(FloorPlanVoice.boxLabel(categoryToken: "refrigerator", confidence: .low))
        XCTAssertNil(FloorPlanVoice.boxLabel(categoryToken: "bed", confidence: .low))
    }

    func test_boxLabel_unknownCategory_staysQuiet() {
        XCTAssertNil(FloorPlanVoice.boxLabel(categoryToken: "hologram", confidence: .high))
    }

    // MARK: - Moment lines

    func test_momentLine_namedAtMediumPlus() {
        XCTAssertEqual(FloorPlanVoice.momentLine(categoryToken: "bed", confidence: .high),
                       "A bed — noted.")
        XCTAssertEqual(FloorPlanVoice.momentLine(categoryToken: "oven", confidence: .medium),
                       "An oven — noted.")
        XCTAssertEqual(FloorPlanVoice.momentLine(categoryToken: "stairs", confidence: .high),
                       "The stairs — noted.")
    }

    func test_momentLine_hedgesLowConfidenceAndUnknown() {
        XCTAssertEqual(FloorPlanVoice.momentLine(categoryToken: "refrigerator", confidence: .low),
                       "Something new — noted.")
        XCTAssertEqual(FloorPlanVoice.momentLine(categoryToken: "hologram", confidence: .high),
                       "Something new — noted.")
    }

    // MARK: - Dedupe

    func test_unannounced_filtersSeenIdsPreservingOrder() {
        let a = FloorPlanPiece(id: UUID(), categoryToken: "bed", confidence: .high)
        let b = FloorPlanPiece(id: UUID(), categoryToken: "chair", confidence: .medium)
        let c = FloorPlanPiece(id: UUID(), categoryToken: "table", confidence: .high)
        let fresh = FloorPlanVoice.unannounced([a, b, c], seen: [b.id])
        XCTAssertEqual(fresh, [a, c])
        XCTAssertEqual(FloorPlanVoice.unannounced([a], seen: [a.id]), [])
    }

    // MARK: - Instruction relay

    func test_guidanceLine_table() {
        XCTAssertEqual(FloorPlanVoice.guidanceLine(instructionToken: "moveCloseToWall"),
                       "A little closer to that wall, when you can.")
        XCTAssertEqual(FloorPlanVoice.guidanceLine(instructionToken: "moveAwayFromWall"),
                       "A step back from the wall — I'll see it better.")
        XCTAssertEqual(FloorPlanVoice.guidanceLine(instructionToken: "slowDown"),
                       "Slower, just a touch.")
        XCTAssertEqual(FloorPlanVoice.guidanceLine(instructionToken: "turnOnLight"),
                       "A bit more light would help me see.")
        XCTAssertEqual(FloorPlanVoice.guidanceLine(instructionToken: "lowTexture"),
                       "Show me an edge or a corner — something with shape.")
        XCTAssertNil(FloorPlanVoice.guidanceLine(instructionToken: "normal"),
                     "normal = guidance stands down")
        XCTAssertNil(FloorPlanVoice.guidanceLine(instructionToken: "someFutureCase"),
                     "unknown instructions degrade to silence, never to a guess")
    }

    // MARK: - The "enough" confirmation

    func test_censusStable_table() {
        // A closed room's worth of walls + a floor + a settled census.
        XCTAssertTrue(FloorPlanVoice.censusStable(walls: 4, floors: 1, sinceChange: 12))
        XCTAssertTrue(FloorPlanVoice.censusStable(walls: 13, floors: 1, sinceChange: 120))
        XCTAssertFalse(FloorPlanVoice.censusStable(walls: 3, floors: 1, sinceChange: 60),
                       "Too few walls — not a closed room yet")
        XCTAssertFalse(FloorPlanVoice.censusStable(walls: 6, floors: 0, sinceChange: 60),
                       "No floor — not a room yet")
        XCTAssertFalse(FloorPlanVoice.censusStable(walls: 6, floors: 1, sinceChange: 5),
                       "Census still moving — not settled")
    }

    // MARK: - The one spoken line (priority)

    func test_liveGuestLine_priorityTable() {
        // 1. Fresh guidance outranks everything.
        XCTAssertEqual(
            FloorPlanVoice.liveGuestLine(guidance: "G", guidanceAge: 1,
                                         moment: "M", momentAge: 1,
                                         censusIsStable: true, defaultLine: "D"),
            "G")
        // 2. Fresh moment next.
        XCTAssertEqual(
            FloorPlanVoice.liveGuestLine(guidance: nil, guidanceAge: .infinity,
                                         moment: "M", momentAge: 1,
                                         censusIsStable: true, defaultLine: "D"),
            "M")
        // 3. Then the "enough" confirmation.
        XCTAssertEqual(
            FloorPlanVoice.liveGuestLine(guidance: nil, guidanceAge: .infinity,
                                         moment: nil, momentAge: .infinity,
                                         censusIsStable: true, defaultLine: "D"),
            FloorPlanVoice.censusStableLine)
        // 4. Then the default coaching line.
        XCTAssertEqual(
            FloorPlanVoice.liveGuestLine(guidance: nil, guidanceAge: .infinity,
                                         moment: nil, momentAge: .infinity,
                                         censusIsStable: false, defaultLine: "D"),
            "D")
    }

    func test_liveGuestLine_staleLinesDecay() {
        // A held guidance line decays past its hold; a stale moment too.
        XCTAssertEqual(
            FloorPlanVoice.liveGuestLine(guidance: "G",
                                         guidanceAge: FloorPlanVoice.guidanceHoldSec + 1,
                                         moment: "M",
                                         momentAge: FloorPlanVoice.momentHoldSec + 1,
                                         censusIsStable: false, defaultLine: "D"),
            "D")
        // Fresh moment shows once guidance has decayed.
        XCTAssertEqual(
            FloorPlanVoice.liveGuestLine(guidance: "G",
                                         guidanceAge: FloorPlanVoice.guidanceHoldSec + 1,
                                         moment: "M", momentAge: 1,
                                         censusIsStable: false, defaultLine: "D"),
            "M")
    }

    // MARK: - Coverage ticks

    func test_coverage_noCensus_allEmpty() {
        let c = FloorPlanVoice.coverage(census: nil, cornerCount: 9)
        XCTAssertEqual(c.floor, .empty)
        XCTAssertEqual(c.walls, .empty)
        XCTAssertEqual(c.corners, .empty)
    }

    func test_coverage_floorIsBinary() {
        let census = RoomCensus(objects: 0, walls: 0, doors: 0, windows: 0,
                                openings: 0, floors: 1)
        XCTAssertEqual(FloorPlanVoice.coverage(census: census, cornerCount: 0).floor, .full)
        let noFloor = RoomCensus(objects: 0, walls: 2, doors: 0, windows: 0,
                                 openings: 0, floors: 0)
        XCTAssertEqual(FloorPlanVoice.coverage(census: noFloor, cornerCount: 0).floor, .empty)
    }

    func test_coverage_wallsAndCornersFillTowardClosure() {
        // "Full" = a closed room's worth (4), not "all of yours".
        func census(walls: Int) -> RoomCensus {
            RoomCensus(objects: 0, walls: walls, doors: 0, windows: 0, openings: 0, floors: 1)
        }
        XCTAssertEqual(FloorPlanVoice.coverage(census: census(walls: 0), cornerCount: 0).walls, .empty)
        XCTAssertEqual(FloorPlanVoice.coverage(census: census(walls: 2), cornerCount: 1).walls, .partial(0.5))
        XCTAssertEqual(FloorPlanVoice.coverage(census: census(walls: 4), cornerCount: 2).walls, .full)
        XCTAssertEqual(FloorPlanVoice.coverage(census: census(walls: 13), cornerCount: 14).walls, .full)
        XCTAssertEqual(FloorPlanVoice.coverage(census: census(walls: 2), cornerCount: 1).corners, .partial(0.25))
        XCTAssertEqual(FloorPlanVoice.coverage(census: census(walls: 6), cornerCount: 5).corners, .full)
    }
}
