/// Pins what the phone says about a room — the derivation from GET /scenes to
/// a room's name and state, as a table.
///
/// Two properties are worth naming. Nothing here invents a number: a scene whose
/// `created_at` did not parse gets a name with no date in it, and a room still
/// being rebuilt reports elapsed time rather than the design's "about 2 min",
/// which the pipeline never tells the phone. And a row offers a tap only when
/// there is somewhere for it to land — `NetworkConfig.webBaseURL` is nil today,
/// which the doorway already handles the same way.

import XCTest
@testable import TheGoodGuest

// MARK: - Fixtures

private let calendar = Calendar.current

private func date(_ y: Int, _ m: Int, _ d: Int, _ hh: Int = 12, _ mm: Int = 0) -> Date {
    calendar.date(from: DateComponents(year: y, month: m, day: d, hour: hh, minute: mm))!
}

/// Build a SceneResponse through its real Decodable path, so the tests exercise
/// the same wire mapping production does rather than a hand-built struct.
private func scene(
    id: String,
    bundleId: String? = "b1",
    status: String = "ready",
    createdAt: Date? = nil,
    rawCreatedAt: String? = nil,
    stillURL: String? = nil
) throws -> SceneResponse {
    let created: String
    if let rawCreatedAt {
        created = rawCreatedAt
    } else {
        let formatter = ISO8601DateFormatter()
        created = formatter.string(from: createdAt ?? Date())
    }
    var dict: [String: Any] = [
        "scene_id": id,
        "bundle_id": bundleId as Any,
        "status": status,
        "result_uri": NSNull(),
        "missing_paths": [],
        "created_at": created,
        "updated_at": created,
    ]
    if let stillURL { dict["still_url"] = stillURL }
    let data = try JSONSerialization.data(withJSONObject: dict)
    return try JSONDecoder().decode(SceneResponse.self, from: data)
}

final class RoomHistoryTests: XCTestCase {

    private let now = date(2026, 8, 21, 17, 30)

    // MARK: - Title

    func testTitleTable() {
        // The website's form, so one room reads the same on both. The year
        // appears only when it is not this year's.
        let cases: [(Date?, Bool, String)] = [
            (date(2026, 8, 21, 9, 5),  false, "The 21 August room"),
            (date(2026, 8, 20, 23, 59), false, "The 20 August room"),
            (date(2026, 7, 12, 15, 40), false, "The 12 July room"),
            (date(2026, 1, 3, 8, 0),   false, "The 3 January room"),
            (date(2025, 12, 30, 8, 0), false, "The 30 December 2025 room"),
            (nil,                       false, "A room you sent"),
        ]
        for (sentAt, withTime, expected) in cases {
            XCTAssertEqual(
                RoomHistory.title(sentAt: sentAt, now: now, withTime: withTime, calendar: calendar),
                expected
            )
        }
    }

    func testTitleWithTimeAppendsLowercaseClock() {
        XCTAssertEqual(
            RoomHistory.title(sentAt: date(2026, 7, 12, 15, 40), now: now, withTime: true, calendar: calendar),
            "The 12 July room, 3:40 pm"
        )
        XCTAssertEqual(
            RoomHistory.title(sentAt: date(2026, 8, 21, 9, 5), now: now, withTime: true, calendar: calendar),
            "The 21 August room, 9:05 am"
        )
    }

    func testUndatedRoomNeverGainsATimeEither() {
        // withTime is a fact about the list; it must not manufacture a clock for
        // a room whose timestamp did not parse.
        XCTAssertEqual(
            RoomHistory.title(sentAt: nil, now: now, withTime: true, calendar: calendar),
            "A room you sent"
        )
    }

    // MARK: - Whole-list disambiguation

    /// Two rooms from one day share a title here; `RoomCards` appends each
    /// one's time on home (RoomCardsTests), from the instant asserted below.
    func testRoomsSharingADayRepeatTheirTitleAndCarryTheirInstant() throws {
        let scenes = [
            try scene(id: "a", createdAt: date(2026, 8, 21, 16, 0)),
            try scene(id: "b", createdAt: date(2026, 8, 21, 11, 20)),
            try scene(id: "c", createdAt: date(2026, 7, 12, 15, 40)),
        ]

        let rows = RoomHistory.summaries(from: scenes, now: now, calendar: calendar)

        XCTAssertEqual(rows.map(\.title), [
            "The 21 August room",
            "The 21 August room",
            "The 12 July room",
        ])
        // What the column has to work with, and what makes the repeat legible.
        XCTAssertEqual(rows.compactMap(\.sentAt).count, 3)
        XCTAssertEqual(rows.compactMap(\.sentAt).map(RoomHistory.clockTime),
                       ["4:00 pm", "11:20 am", "3:40 pm"])
    }

    /// A room whose `created_at` did not parse carries no stamp, because the
    /// alternative is a fabricated one.
    func testAnUnparseableDateLeavesNoStamp() throws {
        let rows = RoomHistory.summaries(
            from: [try scene(id: "x", rawCreatedAt: "not-a-date")],
            now: now, calendar: calendar)
        XCTAssertNil(rows[0].sentAt)
        XCTAssertEqual(rows[0].title, "A room you sent")
    }

    func testServerOrderIsPreserved() throws {
        let scenes = [
            try scene(id: "newest", createdAt: date(2026, 8, 21, 16, 0)),
            try scene(id: "oldest", createdAt: date(2026, 1, 2, 9, 0)),
        ]
        let rows = RoomHistory.summaries(from: scenes, now: now, calendar: calendar)
        XCTAssertEqual(rows.map(\.id), ["newest", "oldest"])
    }

    func testUnparseableCreatedAtDoesNotCollideWithOtherUndatedRooms() throws {
        // Two rooms with no date are two "a room you sent" rows. That is honest
        // — they are still distinct rows with distinct ids — and specifically it
        // must not crash or fabricate a day key that groups them.
        let scenes = [
            try scene(id: "a", rawCreatedAt: "not-a-date"),
            try scene(id: "b", rawCreatedAt: "also-not-a-date"),
        ]
        let rows = RoomHistory.summaries(from: scenes, now: now, calendar: calendar)
        XCTAssertEqual(rows.map(\.title), ["A room you sent", "A room you sent"])
        XCTAssertEqual(rows.map(\.id), ["a", "b"])
    }

    func testBundleIdIsCarriedThroughForTheWebHandoff() throws {
        let rows = RoomHistory.summaries(
            from: [try scene(id: "a", bundleId: "bundle-7")], now: now, calendar: calendar)
        XCTAssertEqual(rows.first?.bundleId, "bundle-7")
    }

    func testTheStillLinkIsCarriedWhenTheServerSendsOne() throws {
        let rows = RoomHistory.summaries(
            from: [try scene(id: "a", stillURL: "https://storage.example/still.jpg?sig=1"),
                   try scene(id: "b")],
            now: now, calendar: calendar)
        XCTAssertEqual(rows[0].stillURL?.absoluteString, "https://storage.example/still.jpg?sig=1")
        XCTAssertNil(rows[1].stillURL, "a server without stills sends none, and the room keeps its outline")
        XCTAssertNil(rows[0].stillNightURL)
    }

    // MARK: - State

    func testStateTable() {
        let cases: [(SceneStatus, RoomSummary.State)] = [
            (.ready,             .ready),
            (.queued,            .processing),
            (.processing,        .processing),
            (.unknown("later"),  .processing),
            (.failed,            .failed),
            (.failedInvalid,     .failed),
            (.failedIncomplete,  .failed),
        ]
        for (status, expected) in cases {
            XCTAssertEqual(RoomHistory.state(for: status), expected, "\(status)")
        }
    }

    // MARK: - Elapsed phrasing

    func testElapsedPhraseTable() {
        let start = date(2026, 8, 21, 12, 0)
        let cases: [(TimeInterval, String)] = [
            (0,        "under a minute"),
            (59,       "under a minute"),
            (60,       "1 min"),
            (599,      "9 min"),
            (3_599,    "59 min"),
            (3_600,    "1 hr"),
            (7_200,    "2 hr"),
            (86_399,   "23 hr"),
            (86_400,   "1 day"),
            (200_000,  "2 days"),
        ]
        for (seconds, expected) in cases {
            XCTAssertEqual(
                RoomHistory.elapsedPhrase(from: start, to: start.addingTimeInterval(seconds)),
                expected, "\(seconds)s"
            )
        }
    }

    // MARK: - Openability

    func testOnlyAReadyRoomWithABundleAndAWebOriginIsOpenable() {
        let ready      = RoomSummary(id: "1", bundleId: "b", title: "t", status: .ready)
        let processing = RoomSummary(id: "2", bundleId: "b", title: "t", status: .processing)
        let failed     = RoomSummary(id: "3", bundleId: "b", title: "t", status: .failed)
        let noBundle   = RoomSummary(id: "4", bundleId: nil, title: "t", status: .ready)

        XCTAssertTrue(RoomHistory.isOpenable(ready, canOpenWeb: true))
        XCTAssertFalse(RoomHistory.isOpenable(ready, canOpenWeb: false))
        XCTAssertFalse(RoomHistory.isOpenable(processing, canOpenWeb: true))
        XCTAssertFalse(RoomHistory.isOpenable(failed, canOpenWeb: true))
        XCTAssertFalse(RoomHistory.isOpenable(noBundle, canOpenWeb: true))
    }

    // MARK: - Whether the handoff would land

    func testTheHandoffNeedsAnOriginAndALinkedIdentity() {
        // The truth table, all four corners. The interesting one is the third:
        // a live origin with an unlinked identity, which is what shipping the
        // URL alone would have produced for every anonymous user.
        XCTAssertTrue(RoomHistory.webHandoffLands(hasWebOrigin: true, isLinked: true))
        XCTAssertFalse(RoomHistory.webHandoffLands(hasWebOrigin: false, isLinked: true))
        XCTAssertFalse(RoomHistory.webHandoffLands(hasWebOrigin: true, isLinked: false))
        XCTAssertFalse(RoomHistory.webHandoffLands(hasWebOrigin: false, isLinked: false))
    }

    func testAnUnlinkedIdentityIsNeverOfferedTheWeb() {
        // Stated separately from the table because it is the property, not a
        // row: rooms are scoped to the caller's token and an anonymous UID does
        // not leave the phone, so following the link would reach a page asking
        // for an account that does not exist. A disabled row is the better
        // outcome, and this is what keeps it disabled.
        let ready = RoomSummary(id: "1", bundleId: "b", title: "t", status: .ready)
        let lands = RoomHistory.webHandoffLands(hasWebOrigin: true, isLinked: false)
        XCTAssertFalse(RoomHistory.isOpenable(ready, canOpenWeb: lands))
    }

    func testTheOriginIsConfiguredSoLinkingIsWhatDecides() {
        // Pins the constant AND the consequence together. If webBaseURL is ever
        // unset, the first assertion fails and names why the rooms went quiet
        // rather than leaving it to be discovered on a device.
        XCTAssertNotNil(NetworkConfig.webBaseURL, "the web origin must stay configured")
        XCTAssertEqual(
            RoomHistory.webHandoffLands(
                hasWebOrigin: NetworkConfig.webBaseURL != nil, isLinked: true),
            true
        )
        XCTAssertEqual(
            RoomHistory.webHandoffLands(
                hasWebOrigin: NetworkConfig.webBaseURL != nil, isLinked: false),
            false
        )
    }

    func testTheRoomURLIsBuiltAgainstTheLiveOrigin() {
        let url = NetworkConfig.webRoomURL(bundleId: "abc-123")
        XCTAssertEqual(url?.absoluteString, "https://thegoodguest.web.app/room?bundle=abc-123")
    }
}
