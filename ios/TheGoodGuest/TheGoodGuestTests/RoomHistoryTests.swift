/// Pins what a room row SAYS — the derivation from GET /scenes to the words on
/// screen, as a table.
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
    rawCreatedAt: String? = nil
) throws -> SceneResponse {
    let created: String
    if let rawCreatedAt {
        created = rawCreatedAt
    } else {
        let formatter = ISO8601DateFormatter()
        created = formatter.string(from: createdAt ?? Date())
    }
    let dict: [String: Any] = [
        "scene_id": id,
        "bundle_id": bundleId as Any,
        "status": status,
        "result_uri": NSNull(),
        "missing_paths": [],
        "created_at": created,
        "updated_at": created,
    ]
    let data = try JSONSerialization.data(withJSONObject: dict)
    return try JSONDecoder().decode(SceneResponse.self, from: data)
}

final class RoomHistoryTests: XCTestCase {

    private let now = date(2026, 8, 21, 17, 30)

    // MARK: - Title

    func testTitleTable() {
        let cases: [(Date?, Bool, String)] = [
            (date(2026, 8, 21, 9, 5),  false, "today's room"),
            (date(2026, 8, 20, 23, 59), false, "yesterday's room"),
            (date(2026, 7, 12, 15, 40), false, "the July 12 room"),
            (date(2026, 1, 3, 8, 0),   false, "the January 3 room"),
            (nil,                       false, "a room you sent"),
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
            "the July 12 room, 3:40 pm"
        )
        XCTAssertEqual(
            RoomHistory.title(sentAt: date(2026, 8, 21, 9, 5), now: now, withTime: true, calendar: calendar),
            "today's room, 9:05 am"
        )
    }

    func testUndatedRoomNeverGainsATimeEither() {
        // withTime is a fact about the list; it must not manufacture a clock for
        // a room whose timestamp did not parse.
        XCTAssertEqual(
            RoomHistory.title(sentAt: nil, now: now, withTime: true, calendar: calendar),
            "a room you sent"
        )
    }

    // MARK: - Whole-list disambiguation

    /// Two rooms from one day are told apart by the house's mono stamp column,
    /// not by a time appended to the title.
    ///
    /// The title used to carry it, which made the disambiguation a fact about
    /// the LIST — it needed to know whether any other room shared the day. It
    /// is now a fact about the room: every summary carries the instant it was
    /// sent, and the column decides what to print. So the titles are allowed to
    /// repeat, and the thing that separates them is asserted below.
    func testRoomsSharingADayRepeatTheirTitleAndAreSeparatedByTheirStamp() throws {
        let scenes = [
            try scene(id: "a", createdAt: date(2026, 8, 21, 16, 0)),
            try scene(id: "b", createdAt: date(2026, 8, 21, 11, 20)),
            try scene(id: "c", createdAt: date(2026, 7, 12, 15, 40)),
        ]

        let rows = RoomHistory.summaries(from: scenes, now: now, calendar: calendar)

        XCTAssertEqual(rows.map(\.title), [
            "today's room",
            "today's room",
            "the July 12 room",
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
        XCTAssertEqual(rows[0].title, "a room you sent")
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
        XCTAssertEqual(rows.map(\.title), ["a room you sent", "a room you sent"])
        XCTAssertEqual(rows.map(\.id), ["a", "b"])
    }

    func testBundleIdIsCarriedThroughForTheWebHandoff() throws {
        let rows = RoomHistory.summaries(
            from: [try scene(id: "a", bundleId: "bundle-7")], now: now, calendar: calendar)
        XCTAssertEqual(rows.first?.bundleId, "bundle-7")
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

    // MARK: - Status line

    func testStatusLineTable() {
        let sent = date(2026, 8, 21, 17, 0)   // 30 minutes before `now`
        let cases: [(SceneStatus, String)] = [
            (.ready,            "on your desk"),
            (.queued,           "being rebuilt · 30 min so far"),
            (.processing,       "being rebuilt · 30 min so far"),
            (.unknown("x"),     "being rebuilt · 30 min so far"),
            (.failedIncomplete, "needs one more send"),
            (.failed,           "didn't make it to the desk"),
            (.failedInvalid,    "didn't make it to the desk"),
        ]
        for (status, expected) in cases {
            XCTAssertEqual(RoomHistory.statusLine(status: status, sentAt: sent, now: now), expected, "\(status)")
        }
    }

    func testProcessingWithNoUsableStartSaysOnlyWhatItKnows() {
        // No parseable start, or a start in the future (clock skew): report the
        // state, not an elapsed time computed from a number we do not trust.
        XCTAssertEqual(
            RoomHistory.statusLine(status: .processing, sentAt: nil, now: now),
            "being rebuilt"
        )
        XCTAssertEqual(
            RoomHistory.statusLine(status: .processing, sentAt: now.addingTimeInterval(600), now: now),
            "being rebuilt"
        )
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
        let ready      = RoomSummary(id: "1", bundleId: "b", title: "t", statusLine: "s", state: .ready)
        let processing = RoomSummary(id: "2", bundleId: "b", title: "t", statusLine: "s", state: .processing)
        let failed     = RoomSummary(id: "3", bundleId: "b", title: "t", statusLine: "s", state: .failed)
        let noBundle   = RoomSummary(id: "4", bundleId: nil, title: "t", statusLine: "s", state: .ready)

        XCTAssertTrue(RoomHistory.isOpenable(ready, canOpenWeb: true))
        XCTAssertFalse(RoomHistory.isOpenable(ready, canOpenWeb: false))
        XCTAssertFalse(RoomHistory.isOpenable(processing, canOpenWeb: true))
        XCTAssertFalse(RoomHistory.isOpenable(failed, canOpenWeb: true))
        XCTAssertFalse(RoomHistory.isOpenable(noBundle, canOpenWeb: true))
    }
}
