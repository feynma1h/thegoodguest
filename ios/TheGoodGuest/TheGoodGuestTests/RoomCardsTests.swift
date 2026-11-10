/// Pins what home shows (RoomCards): which screen, in what order, with which
/// counts — and that an unknown is never drawn as a zero.

import XCTest
@testable import TheGoodGuest

final class RoomCardsTests: XCTestCase {

    private let calendar = Calendar.current
    private lazy var now = calendar.date(from: DateComponents(year: 2026, month: 8, day: 28, hour: 14, minute: 20))!

    private func room(_ id: String, daysAgo: Int, hour: Int = 10, _ status: SceneStatus = .ready,
                      bundle: String? = nil) -> RoomSummary {
        let day = calendar.date(byAdding: .day, value: -daysAgo, to: now)!
        let sent = calendar.date(bySettingHour: hour, minute: 0, second: 0, of: day)!
        return RoomSummary(id: id, bundleId: bundle ?? "b-\(id)",
                           title: RoomHistory.title(sentAt: sent, now: now, withTime: false, calendar: calendar),
                           status: status, sentAt: sent)
    }

    private func content(_ rooms: RoomsLoadState, flight: HomeFlight? = nil,
                         earlier: HomeEarlierFailure? = nil) -> HomeContent {
        RoomCards.content(rooms: rooms, flight: flight, earlierFailure: earlier, now: now, calendar: calendar)
    }

    // MARK: - Which screen

    func testFirstRunIsAKnownZeroWithNothingOnItsWay() {
        XCTAssertTrue(content(.loaded(rooms: [], stale: false)).firstRun)
        XCTAssertFalse(content(.loaded(rooms: [], stale: false),
                               flight: HomeFlight(bundleId: "f", placement: .desk(.sending))).firstRun,
                       "a first room on its way is not a first run")
        XCTAssertFalse(content(.loaded(rooms: [], stale: false),
                               earlier: HomeEarlierFailure(bundleId: "o", reason: nil)).firstRun)
    }

    func testAnUnknownIsNeverAZero() {
        for state: RoomsLoadState in [.idle, .loading, .failed(reason: "offline")] {
            let c = content(state)
            XCTAssertFalse(c.firstRun, "\(state) is not 'nothing sent'")
            XCTAssertNil(c.countLine, "\(state) has no count to state")
        }
        XCTAssertTrue(content(.loading).loading)
        XCTAssertTrue(content(.failed(reason: "x")).unreachable)
    }

    // MARK: - Counts

    func testTheCountIsTheServersAndOnlyForMoreThanOne() {
        let six = (0..<6).map { room("s\($0)", daysAgo: $0 * 3) }
        XCTAssertEqual(content(.loaded(rooms: six, stale: false)).countLine, "6 rooms, newest first")
        XCTAssertNil(content(.loaded(rooms: [room("a", daysAgo: 0)], stale: false)).countLine)
    }

    func testAStaleListSaysItMightBeOld() {
        XCTAssertEqual(content(.loaded(rooms: [room("a", daysAgo: 0)], stale: true)).staleLine, RoomCards.staleText)
        XCTAssertNil(content(.loaded(rooms: [room("a", daysAgo: 0)], stale: false)).staleLine)
    }

    // MARK: - Order

    func testTheFlightAndAnEarlierFailureArePinnedAboveTheRooms() {
        let c = content(.loaded(rooms: [room("a", daysAgo: 1), room("b", daysAgo: 4)], stale: false),
                        flight: HomeFlight(bundleId: "f", placement: .desk(.sending)),
                        earlier: HomeEarlierFailure(bundleId: "o", reason: nil))
        XCTAssertEqual(c.cards.map(\.destination).prefix(2), [.flight, .earlierFailure])
        XCTAssertEqual(c.cards.count, 4)
    }

    func testTheFlightsOwnSceneIsNotShownTwice() {
        let flying = room("a", daysAgo: 0, .processing, bundle: "f")
        let c = content(.loaded(rooms: [flying, room("b", daysAgo: 2)], stale: false),
                        flight: HomeFlight(bundleId: "f", placement: .desk(.working(anchor: nil, longRunning: false))))
        XCTAssertEqual(c.cards.count, 2)
        XCTAssertEqual(c.cards.first?.destination, .flight)
    }

    func testAFailureForTheFlightItselfIsNotRepeatedAsAnEarlierOne() {
        let c = content(.loaded(rooms: [], stale: false),
                        flight: HomeFlight(bundleId: "f", placement: .note(.uploadFailed(reason: nil))),
                        earlier: HomeEarlierFailure(bundleId: "f", reason: nil))
        XCTAssertEqual(c.cards.count, 1)
    }

    // MARK: - The cards

    func testTwoRoomsFromOneDayBothCarryTheirTime() {
        let c = content(.loaded(rooms: [room("a", daysAgo: 0, hour: 16), room("b", daysAgo: 0, hour: 9),
                                        room("c", daysAgo: 5)], stale: false))
        XCTAssertEqual(c.cards.map(\.title), ["The 28 August room, 4:00 pm",
                                              "The 28 August room, 9:00 am",
                                              "The 23 August room"])
    }

    /// The room on its way is named like any other, so it is one of the two
    /// when it shares a day with a room the server already has.
    func testARoomOnItsWayAndOneFromEarlierThatDayBothCarryTheirTime() {
        let sent = calendar.date(bySettingHour: 14, minute: 5, second: 0, of: now)!
        let c = content(.loaded(rooms: [room("a", daysAgo: 0, hour: 9), room("b", daysAgo: 3)], stale: false),
                        flight: HomeFlight(bundleId: "f", placement: .desk(.sending), sentAt: sent))
        XCTAssertEqual(c.cards.map(\.title), ["The 28 August room, 2:05 pm",
                                              "The 28 August room, 9:00 am",
                                              "The 25 August room"])
    }

    /// At the doorway the flight's own scene is listed but not shown twice;
    /// it still counts against the other room from its day, once.
    func testARoomJustArrivedIsTimedAgainstAnotherFromItsDay() {
        let arrived = room("s", daysAgo: 0, hour: 13, bundle: "f")
        let c = content(.loaded(rooms: [arrived, room("a", daysAgo: 0, hour: 9)], stale: false),
                        flight: HomeFlight(bundleId: "f", placement: .doorway))
        XCTAssertEqual(c.cards.map(\.title), ["The 28 August room, 1:00 pm",
                                              "The 28 August room, 9:00 am"])
    }

    func testARoomOnItsWayAloneOnItsDayHasNoTime() {
        let c = content(.loaded(rooms: [room("a", daysAgo: 2)], stale: false),
                        flight: HomeFlight(bundleId: "f", placement: .desk(.sending)))
        XCTAssertEqual(c.cards.map(\.title), ["The 28 August room", "The 26 August room"])
    }

    func testAFlightCardShowsWhichStepIsHappening() {
        func card(_ placement: SurfacePlacement) -> HomeCard? {
            content(.loaded(rooms: [], stale: false), flight: HomeFlight(bundleId: "f", placement: placement)).cards.first
        }
        XCTAssertEqual(card(.desk(.sending))?.progressStep, 0)
        XCTAssertEqual(card(.desk(.working(anchor: nil, longRunning: false)))?.progressStep, 1)
        XCTAssertNil(card(.desk(.rateLimited(resetsAt: nil)))?.progressStep, "a held room is not moving")
        XCTAssertEqual(card(.desk(.rateLimited(resetsAt: nil)))?.attention, true)
        XCTAssertEqual(card(.doorway)?.isNew, true)
        XCTAssertEqual(card(.doorway)?.line, "Ready")
        XCTAssertNil(card(.nowhere), "a room that is not ours has no card")
    }

    func testAFailedRoomFromTheListAsksForAttention() {
        let c = content(.loaded(rooms: [room("a", daysAgo: 2, .failedIncomplete), room("b", daysAgo: 3)], stale: false))
        XCTAssertEqual(c.cards.map(\.attention), [true, false])
        XCTAssertEqual(c.cards[1].line, "Ready")
    }
}
