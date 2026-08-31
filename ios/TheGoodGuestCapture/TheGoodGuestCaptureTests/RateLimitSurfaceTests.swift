/// Pins the user-facing half of the mint 429: the routing decision, the reaper's
/// verdict, and the honesty of the copy.
///
/// The rate limit is the first send outcome that is neither "try again" nor "it's
/// gone", so every table that switches on a send outcome had to answer for it.
/// Those answers are here rather than spread across the tables' own files,
/// because what makes them right is one shared fact: the capture is intact and
/// the limit lifts by itself.

import XCTest
@testable import TheGoodGuestCapture

final class RateLimitSurfaceTests: XCTestCase {

    private let now = Date(timeIntervalSince1970: 1_786_147_200)  // 2026-08-08 00:00 UTC

    // MARK: - Routing

    func test_rateLimitGetsItsOwnScreen_notAFailureTreatment() {
        let resets = now.addingTimeInterval(3600)
        let screen = WaitFlowState.screen(
            sessionFailure: .rateLimited(resetsAt: resets),
            terminalBlobFailureForThisBundle: false,
            poll: .idle)
        XCTAssertEqual(screen, .sendRateLimited(resetsAt: resets))
    }

    func test_rateLimitOutranksAStalePollState() {
        // Same precedence rule as every other session outcome: no bytes moved, so
        // a leftover poll state from a previous capture must not win.
        XCTAssertEqual(
            WaitFlowState.screen(sessionFailure: .rateLimited(resetsAt: nil),
                                 terminalBlobFailureForThisBundle: true,
                                 poll: .succeeded),
            .sendRateLimited(resetsAt: nil))
    }

    @MainActor
    func test_adapterCarriesTheResetTime() {
        let resets = now.addingTimeInterval(7200)
        XCTAssertEqual(WaitFlowState.sessionFailure(from: .rateLimited(resetsAt: resets)),
                       .rateLimited(resetsAt: resets))
        XCTAssertEqual(WaitFlowState.sessionFailure(from: .rateLimited(resetsAt: nil)),
                       .rateLimited(resetsAt: nil))
        // And it is NOT collapsed into a refusal, which would offer a retry that
        // provably fails until the quota rolls.
        XCTAssertNotEqual(WaitFlowState.sessionFailure(from: .rateLimited(resetsAt: nil)),
                          .refused(terminal: false))
    }

    // MARK: - The reaper must not eat a perfectly good capture

    func test_flightEndRetainsTheCapture() {
        XCTAssertFalse(CaptureReclaim.reclaimsAtFlightEnd(.sendRateLimited(resetsAt: now)),
                       "nothing left the phone and the same capture sends once the quota rolls")
    }

    // MARK: - The Lock Screen mirror

    func test_liveActivityStopsImplyingMotion() {
        // Mapped to failed, not paused: `.paused` promises a resume on the next app
        // open, which is exactly what will NOT happen until the day rolls.
        XCTAssertEqual(LiveActivityPolicy.stage(for: .sendRateLimited(resetsAt: now)),
                       .failed(.upload))
        XCTAssertNotEqual(LiveActivityPolicy.stage(for: .sendRateLimited(resetsAt: now)), .paused)
    }

    // MARK: - Copy honesty

    func test_copyNeverPromisesATimeTheServerDidNotName() {
        let line = DeskCopy.rateLimitLine(resetsAt: nil, now: now)
        for invented in ["tomorrow", "later today", "in an hour", "in about an hour"] {
            XCTAssertFalse(line.lowercased().contains(invented),
                           "an unstated reset must not be narrated as \(invented)")
        }
        XCTAssertTrue(line.contains("safe on your phone"))
    }

    func test_copyDistinguishesLaterTodayFromTomorrow() {
        // A reset a few hours away on the same day must not be called "tomorrow" —
        // the quota rolls at UTC midnight, which lands mid-afternoon in some zones.
        // Anchored at 09:00 LOCAL so the assertion holds in every time zone: a
        // fixed UTC instant is late evening somewhere, where +4h really is tomorrow.
        let morning = Calendar.current.startOfDay(for: now).addingTimeInterval(9 * 3600)
        let sameDay = DeskCopy.rateLimitLine(resetsAt: morning.addingTimeInterval(4 * 3600),
                                                now: morning)
        let nextDay = DeskCopy.rateLimitLine(resetsAt: morning.addingTimeInterval(30 * 3600),
                                                now: morning)
        XCTAssertTrue(sameDay.contains("later today"))
        XCTAssertFalse(sameDay.contains("tomorrow"))
        XCTAssertTrue(nextDay.contains("tomorrow"))
    }

    func test_copyRoundsShortWaitsHonestly() {
        XCTAssertTrue(DeskCopy.rateLimitLine(resetsAt: now.addingTimeInterval(600), now: now)
            .contains("in under an hour"))
        XCTAssertTrue(DeskCopy.rateLimitLine(resetsAt: now.addingTimeInterval(5400), now: now)
            .contains("in about an hour"))
    }

    func test_aResetAlreadyPastIsTreatedAsUnstated() {
        // Clock skew must not produce "I can take more in under an hour" for a
        // moment that has already gone by.
        let line = DeskCopy.rateLimitLine(resetsAt: now.addingTimeInterval(-60), now: now)
        XCTAssertFalse(line.contains("I can take more"))
    }

    func test_copyOwnsTheLimitAndDoesNotBlameTheUser() {
        for resets: Date? in [nil, now.addingTimeInterval(3600), now.addingTimeInterval(30 * 3600)] {
            let line = DeskCopy.rateLimitLine(resetsAt: resets, now: now).lowercased()
            XCTAssertTrue(line.contains("i've hit my limit"), "the guest owns it")
            for blame in ["you've uploaded too", "you have exceeded", "your limit", "too many"] {
                XCTAssertFalse(line.contains(blame), "copy blames the user: \(blame)")
            }
        }
    }

    func test_resetStampIsMachineData() {
        // Mono slot: an exact instant, not prose. The line above owns the reading.
        let stamp = DeskCopy.resetStamp(Date(timeIntervalSince1970: 1_786_320_000))
        XCTAssertTrue(stamp.hasPrefix("RESETS "))
        XCTAssertFalse(stamp.contains("tomorrow"))
    }
}
