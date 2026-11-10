/// Pins the user-facing half of the mint 429: the routing decision, the reaper's
/// verdict, and the honesty of the copy.
///
/// The rate limit is the first send outcome that is neither "try again" nor "it's
/// gone", so every table that switches on a send outcome had to answer for it.
/// Those answers are here rather than spread across the tables' own files,
/// because what makes them right is one shared fact: the capture is intact and
/// the limit lifts by itself.

import XCTest
@testable import TheGoodGuest

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

    // MARK: - Copy honesty (the room screen, RoomStatusCopy)

    private func limited(_ resetsAt: Date?, at time: Date? = nil) -> RoomStatus {
        RoomStatusCopy.onItsWay(.rateLimited(resetsAt: resetsAt), now: time ?? now,
                                locale: Locale(identifier: "en_GB"))
    }

    func test_copyNeverPromisesATimeTheServerDidNotName() {
        let status = limited(nil)
        XCTAssertNil(status.note, "an unstated reset gets no time at all")
        for invented in ["tomorrow", "later today", "in an hour", "in about an hour"] {
            XCTAssertFalse(status.guest.lowercased().contains(invented),
                           "an unstated reset must not be narrated as \(invented)")
        }
        XCTAssertTrue(status.guest.contains("waiting on this phone"))
    }

    func test_copyDistinguishesLaterTodayFromTomorrow() {
        // A reset a few hours away on the same day must not be called "tomorrow" —
        // the quota rolls at UTC midnight, which lands mid-afternoon in some zones.
        // Anchored at 09:00 LOCAL so the assertion holds in every time zone.
        let morning = Calendar.current.startOfDay(for: now).addingTimeInterval(9 * 3600)
        let sameDay = RoomStatusCopy.limitNote(resetsAt: morning.addingTimeInterval(4 * 3600), now: morning) ?? ""
        let nextDay = RoomStatusCopy.limitNote(resetsAt: morning.addingTimeInterval(30 * 3600), now: morning) ?? ""
        XCTAssertTrue(sameDay.contains("later today"), sameDay)
        XCTAssertFalse(sameDay.contains("tomorrow"))
        XCTAssertTrue(nextDay.contains("tomorrow"), nextDay)
    }

    func test_copyRoundsShortWaitsHonestly() {
        XCTAssertTrue((RoomStatusCopy.limitNote(resetsAt: now.addingTimeInterval(600), now: now) ?? "")
            .contains("in under an hour"))
        XCTAssertTrue((RoomStatusCopy.limitNote(resetsAt: now.addingTimeInterval(5400), now: now) ?? "")
            .contains("in about an hour"))
    }

    func test_aResetAlreadyPastIsTreatedAsUnstated() {
        // Clock skew must not produce "in under an hour" for a moment that has
        // already gone by.
        XCTAssertNil(RoomStatusCopy.limitNote(resetsAt: now.addingTimeInterval(-60), now: now))
    }

    func test_theSendIsOfferedOnlyOnceTheLimitCanHaveLifted() {
        XCTAssertNil(limited(now.addingTimeInterval(3600)).primary,
                     "sending before the named reset is a refusal the person can predict")
        XCTAssertEqual(limited(now.addingTimeInterval(-60)).primary?.action, .sendAgain)
        XCTAssertEqual(limited(nil).primary?.action, .sendAgain,
                       "no time named: trying is the only way to find out")
        XCTAssertEqual(limited(now.addingTimeInterval(3600)).secondary?.action, .discard,
                       "the scan can always be let go")
    }

    func test_whatToDoComesFirst() {
        // 0293: the pinned "Let this scan go" ends the scan, and at the largest
        // text sizes the end of the guest's line is below the fold under it.
        // The one instruction that keeps the scan alive must be what is read
        // first, whatever the reset.
        for resets: Date? in [nil, now.addingTimeInterval(3600), now.addingTimeInterval(30 * 3600),
                              now.addingTimeInterval(-60)] {
            XCTAssertTrue(limited(resets).guest.hasPrefix(RoomStatusCopy.kept), "\(String(describing: resets))")
        }
    }

    func test_aResetThatHasPassedIsNotCalledUnknown() {
        let line = limited(now.addingTimeInterval(-60)).guest
        XCTAssertFalse(line.contains("wasn\u{2019}t told"), "the server did name a time; it has passed")
        XCTAssertTrue(line.contains("should take this one now"))
    }

    func test_copyOwnsTheLimitAndDoesNotBlameTheUser() {
        for resets: Date? in [nil, now.addingTimeInterval(3600), now.addingTimeInterval(30 * 3600)] {
            let line = limited(resets).guest.lowercased()
            XCTAssertTrue(line.contains("i\u{2019}ve hit my limit"), "the guest owns it")
            for blame in ["you\u{2019}ve uploaded too", "you have exceeded", "your limit", "too many"] {
                XCTAssertFalse(line.contains(blame), "copy blames the user: \(blame)")
            }
        }
    }

    func test_theResetIsTheReadersOwnClock() {
        var c = DateComponents(); c.year = 2026; c.month = 8; c.day = 8; c.hour = 4; c.minute = 20
        let reset = Calendar.current.date(from: c)!
        let before = reset.addingTimeInterval(-20 * 3600)
        let british = RoomStatusCopy.limitNote(resetsAt: reset, now: before, locale: Locale(identifier: "en_GB")) ?? ""
        let american = RoomStatusCopy.limitNote(resetsAt: reset, now: before, locale: Locale(identifier: "en_US")) ?? ""
        XCTAssertTrue(british.contains("04:20"), british)
        XCTAssertTrue(american.contains("4:20"), american)
        XCTAssertFalse(british.uppercased() == british, "a time in words, not a machine stamp")
    }
}
