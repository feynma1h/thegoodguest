/// Pins the shared `Retry-After` / ISO-8601 parsing.
///
/// The delta-seconds and HTTP-date cases came from BlobUploadManagerTests
/// unchanged when the mint path became the parser's second consumer — the
/// behaviour did not move, only the type did. The ISO-8601 cases are new: they
/// pin the two forms api-public's `resets_at` actually takes on the wire.

import XCTest
@testable import TheGoodGuest

final class RetryAfterTests: XCTestCase {

    // MARK: - Retry-After header

    func test_parse_deltaSeconds() {
        let now = Date()
        XCTAssertEqual(RetryAfter.parse("120", now: now), 120)
        XCTAssertEqual(RetryAfter.parse("0", now: now), 0,
                       "Zero is a valid stated wait (retry immediately)")
        XCTAssertEqual(RetryAfter.parse(" 15 ", now: now), 15,
                       "Surrounding whitespace must be tolerated")
    }

    func test_parse_httpDate() {
        // RFC 7231's own example date, pinned against a fixed epoch:
        // "Wed, 21 Oct 2015 07:28:00 GMT" == 1445412480.
        let now = Date(timeIntervalSince1970: 1_445_412_420)  // 60s before the date
        XCTAssertEqual(RetryAfter.parse("Wed, 21 Oct 2015 07:28:00 GMT", now: now), 60)
    }

    func test_parse_pastHTTPDate_clampsToZero() {
        let now = Date(timeIntervalSince1970: 1_445_412_580)  // 100s after the date
        XCTAssertEqual(RetryAfter.parse("Wed, 21 Oct 2015 07:28:00 GMT", now: now), 0,
                       "A date already in the past means the wait has elapsed")
    }

    func test_parse_malformed_returnsNil() {
        let now = Date()
        XCTAssertNil(RetryAfter.parse(nil, now: now))
        XCTAssertNil(RetryAfter.parse("", now: now))
        XCTAssertNil(RetryAfter.parse("soon", now: now))
        XCTAssertNil(RetryAfter.parse("-5", now: now),
                     "Negative delta-seconds is malformed, not a zero wait")
        XCTAssertNil(RetryAfter.parse("inf", now: now),
                     "Non-finite values must not produce an unbounded sleep")
    }

    // MARK: - resets_at (Python datetime.isoformat)

    func test_parseISO8601_offsetForm() {
        // What api-public actually emits: datetime.isoformat() writes +00:00, not Z.
        let date = RetryAfter.parseISO8601("2026-08-09T00:00:00+00:00")
        XCTAssertEqual(date, Date(timeIntervalSince1970: 1_786_233_600))
    }

    func test_parseISO8601_withMicroseconds() {
        // isoformat() emits microseconds when they are non-zero, from the same
        // endpoint — so both forms are on the wire and both must parse.
        let date = RetryAfter.parseISO8601("2026-08-09T00:00:00.123456+00:00")
        XCTAssertEqual(date, Date(timeIntervalSince1970: 1_786_233_600),
                       "sub-second precision is meaningless for a midnight roll — stripped, not failed")
    }

    func test_parseISO8601_zForm() {
        XCTAssertEqual(RetryAfter.parseISO8601("2026-08-09T00:00:00Z"),
                       Date(timeIntervalSince1970: 1_786_233_600))
    }

    func test_parseISO8601_malformed_returnsNil() {
        XCTAssertNil(RetryAfter.parseISO8601(nil))
        XCTAssertNil(RetryAfter.parseISO8601(""))
        XCTAssertNil(RetryAfter.parseISO8601("tomorrow"))
        XCTAssertNil(RetryAfter.parseISO8601("2026-08-09"),
                     "a bare date is not an instant — the UI would have to invent a time")
    }
}
