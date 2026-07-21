/// Pins for SceneStatusView's pure display helpers (static funcs — no view
/// instantiation, no rendering).
///
/// elapsedLabel: the honest elapsed clock introduced by the status-surface
/// honesty pass — anchored to the scene's server-side created_at and computed
/// against an explicit `now` (the 1 s TimelineView tick date in production).
///
/// These are honesty pins, not layout tests: they guard against the clock
/// regressing to negative counts (clock skew) or unreadable formats.

import XCTest
@testable import RoomStudioCapture

final class SceneStatusViewTests: XCTestCase {

    // MARK: - elapsedLabel formatting

    private let anchor = Date(timeIntervalSince1970: 1_000_000)

    private func label(afterSeconds secs: TimeInterval) -> String {
        SceneStatusView.elapsedLabel(anchor: anchor, now: anchor.addingTimeInterval(secs))
    }

    func test_elapsedLabel_underOneMinute_isBareSeconds() {
        XCTAssertEqual(label(afterSeconds: 0),  "0s")
        XCTAssertEqual(label(afterSeconds: 5),  "5s")
        XCTAssertEqual(label(afterSeconds: 59), "59s")
    }

    func test_elapsedLabel_minutes_isMinutesColonSeconds() {
        XCTAssertEqual(label(afterSeconds: 60),          "1:00")
        XCTAssertEqual(label(afterSeconds: 65),          "1:05")
        XCTAssertEqual(label(afterSeconds: 45 * 60 + 7), "45:07")
    }

    func test_elapsedLabel_pastAnHour_gainsHourField() {
        // Real reconstructions have run past an hour; "62:05" reads as broken.
        XCTAssertEqual(label(afterSeconds: 3600),                    "1:00:00")
        XCTAssertEqual(label(afterSeconds: 3600 + 2 * 60 + 5),       "1:02:05")
        XCTAssertEqual(label(afterSeconds: 2 * 3600 + 59 * 60 + 59), "2:59:59")
    }

    func test_elapsedLabel_clockSkew_clampsToZero() {
        // Device clock behind the server: anchor in the local future must never
        // render a negative count.
        XCTAssertEqual(label(afterSeconds: -30), "0s")
    }
}
