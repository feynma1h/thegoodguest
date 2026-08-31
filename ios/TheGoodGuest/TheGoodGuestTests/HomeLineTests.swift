/// Pins home's one sentence and the contents sheet's four rows.
///
/// Both exist because the 2b design moves ALL of home's reporting onto other
/// screens and leaves one sentence pointing at them. If that sentence picks the
/// wrong destination, the news is not merely mis-styled — it is unreachable
/// from the only surface that mentions it.
///
/// The two tables are tested together because they read one `HomeDay` and must
/// not disagree: a sheet saying "2 NEED YOU" beside a line saying "all quiet"
/// is the same class of contradiction the re-entry row used to produce against
/// the wait screen.

import XCTest
@testable import TheGoodGuest

final class HomeLineTests: XCTestCase {

    // MARK: Priority

    func testPriorityOrderIsNeedsYouThenArrivalThenFlightThenQuiet() {
        // Every higher priority present at once: the sentence must pick the
        // top one and route there, never to two places.
        let loud = HomeDay(needsYou: 2, hasUnseenArrival: true,
                           hasRoomInFlight: true, roomCount: 6)
        XCTAssertEqual(HomeLineResolver.line(for: loud)?.destination, .notes)
        XCTAssertEqual(HomeLineResolver.line(for: loud)?.tone, .needsYou)

        let arrival = HomeDay(hasUnseenArrival: true, hasRoomInFlight: true, roomCount: 6)
        XCTAssertEqual(HomeLineResolver.line(for: arrival)?.destination, .doorway)
        XCTAssertEqual(HomeLineResolver.line(for: arrival)?.tone, .arrival)

        let flight = HomeDay(hasRoomInFlight: true, roomCount: 6)
        XCTAssertEqual(HomeLineResolver.line(for: flight)?.destination, .desk)
        XCTAssertEqual(HomeLineResolver.line(for: flight)?.tone, .inFlight)

        let quiet = HomeDay(roomCount: 6)
        XCTAssertEqual(HomeLineResolver.line(for: quiet)?.destination, .house)
        XCTAssertEqual(HomeLineResolver.line(for: quiet)?.tone, .quiet)
    }

    func testFirstRunReportsNothing() {
        // The whisper that teaches where things live owns this space; an empty
        // sentence would leave a gap where the teaching line belongs.
        XCTAssertNil(HomeLineResolver.line(for: HomeDay(isFirstRun: true)))
    }

    // MARK: One sentence, both facts

    func testNeedsYouCarriesTheFlightWithoutRoutingToIt() {
        let both = HomeDay(needsYou: 1, hasRoomInFlight: true, roomCount: 3)
        let line = HomeLineResolver.line(for: both)
        XCTAssertEqual(line?.destination, .notes, "routes to the higher priority only")
        XCTAssertTrue(line!.text.contains("on its way"), "but still mentions the flight")

        let aloneText = HomeLineResolver.line(for: HomeDay(needsYou: 1, roomCount: 3))!.text
        XCTAssertFalse(aloneText.contains("on its way"),
                       "with no flight, the clause must not appear")
    }

    // MARK: The honesty constraint

    func testAnUnknownCountStatesNoNumber() {
        // The whole point: a failed fetch is not zero rooms, and the quiet line
        // has no standing to imply either a number or an absence.
        let unknown = HomeLineResolver.line(for: HomeDay(roomCount: nil))!
        XCTAssertEqual(unknown.destination, .house)
        for digit in "0123456789" {
            XCTAssertFalse(unknown.text.contains(digit),
                           "an unknown count must not produce a number: \(unknown.text)")
        }
        XCTAssertFalse(unknown.text.lowercased().contains("no rooms"),
                       "and must not imply an absence either")
    }

    func testKnownCountsAgreeInNumber() {
        func text(_ n: Int) -> String {
            HomeLineResolver.line(for: HomeDay(roomCount: n))!.text
        }
        XCTAssertTrue(text(1).contains("one room"), text(1))
        XCTAssertTrue(text(6).contains("6 rooms"), text(6))
        XCTAssertTrue(text(0).contains("nothing sent yet"), text(0))
    }
}

final class ContentsTests: XCTestCase {

    private func row(_ rows: [ContentsRow], _ entry: ContentsEntry) -> ContentsRow {
        rows.first { $0.entry == entry }!
    }

    func testAlwaysTheSameFourEntriesInOrder() {
        // A contents page whose rows move or disappear is not a contents page.
        for day in [HomeDay(),
                    HomeDay(needsYou: 3, hasUnseenArrival: true,
                            hasRoomInFlight: true, roomCount: 9),
                    HomeDay(roomCount: nil),
                    HomeDay(isFirstRun: true)] {
            XCTAssertEqual(Contents.rows(for: day).map(\.entry),
                           [.house, .desk, .notes, .you], "\(day)")
        }
    }

    func testTheHouseGoesBlankRatherThanZeroWhenTheCountIsUnknown() {
        let unknown = row(Contents.rows(for: HomeDay(roomCount: nil)), .house)
        XCTAssertNil(unknown.status,
                     "blank, not zero — the design's rule and the store's own refusal")

        let none = row(Contents.rows(for: HomeDay(roomCount: 0)), .house)
        XCTAssertEqual(none.status, "NO ROOMS YET",
                       "a KNOWN zero is a fact and may be stated")
    }

    func testDeskAndNotesReportTheDayTheyAreGiven() {
        let busy = Contents.rows(for: HomeDay(needsYou: 2, hasRoomInFlight: true, roomCount: 4))
        XCTAssertEqual(row(busy, .desk).status, "1 IN FLIGHT")
        XCTAssertEqual(row(busy, .notes).status, "2 NEED YOU")
        XCTAssertEqual(row(busy, .notes).tone, .needsYou)

        let calm = Contents.rows(for: HomeDay(roomCount: 4))
        XCTAssertEqual(row(calm, .desk).status, "CLEAR")
        XCTAssertEqual(row(calm, .notes).status, "NOTHING NEW")
        XCTAssertEqual(row(calm, .notes).tone, .quiet)

        let single = Contents.rows(for: HomeDay(needsYou: 1))
        XCTAssertEqual(row(single, .notes).status, "1 NEEDS YOU", "singular agreement")
    }

    func testYouStatesNothing() {
        // Not a count and not a state — a place. Inventing a status for
        // symmetry would make it the one row asserting what it does not know.
        for day in [HomeDay(), HomeDay(needsYou: 5, roomCount: 12)] {
            XCTAssertNil(row(Contents.rows(for: day), .you).status)
        }
    }

    // MARK: The two surfaces agree

    func testTheSheetAndTheLineNeverContradictEachOther() {
        // One HomeDay, two renderings. A sheet saying "2 NEED YOU" beside a
        // line saying "all quiet" is the contradiction this shared input exists
        // to prevent.
        let days = [
            HomeDay(needsYou: 2, hasRoomInFlight: true, roomCount: 6),
            HomeDay(hasUnseenArrival: true, roomCount: 6),
            HomeDay(hasRoomInFlight: true, roomCount: 1),
            HomeDay(roomCount: nil),
            HomeDay(roomCount: 0),
        ]
        for day in days {
            let line = HomeLineResolver.line(for: day)
            let notes = row(Contents.rows(for: day), .notes)
            if day.needsYou > 0 {
                XCTAssertEqual(line?.tone, .needsYou, "\(day)")
                XCTAssertEqual(notes.tone, .needsYou, "\(day)")
            } else {
                XCTAssertNotEqual(line?.tone, .needsYou, "\(day)")
                XCTAssertNotEqual(notes.tone, .needsYou, "\(day)")
            }
            // The house row and the quiet line must make the same claim about
            // whether a count is known.
            let house = row(Contents.rows(for: day), .house)
            XCTAssertEqual(house.status == nil, day.roomCount == nil, "\(day)")
        }
    }
}
