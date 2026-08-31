/// Pins the sign-in invitation's trigger and its once-ever memory.
///
/// The home-strip presentation table that used to live here went with the
/// strip: home no longer carries rooms at all, so there is no longer a
/// decision about whether to show them instead of the claim. What that table
/// protected — that a failed fetch must never render as "no rooms" — is now
/// pinned in HomeLineTests and ContentsTests, where the count is stated.


import XCTest
@testable import TheGoodGuest

private func room(_ id: String) -> RoomSummary {
    RoomSummary(id: id, bundleId: "\(id)-bundle", title: "the July 12 room",
                statusLine: "on your desk", state: .ready)
}

final class WhySignInInvitationTests: XCTestCase {

    func testOfferedOnlyWithAKnownNonZeroCountAndAnUnlinkedIdentity() {
        let oneRoom  = RoomsLoadState.loaded(rooms: [room("a")], stale: false)
        let noRooms  = RoomsLoadState.loaded(rooms: [], stale: false)

        let cases: [(RoomsLoadState, Bool, Bool, Bool, String)] = [
            // rooms,   isLinked, alreadyOffered, expected, why
            (oneRoom,   false,    false,          true,  "the case it exists for"),
            (oneRoom,   true,     false,          false, "already linked — nothing to argue"),
            (oneRoom,   false,    true,           false, "an invitation, not a nag"),
            (noRooms,   false,    false,          false, "nothing to lose yet"),
            (.idle,     false,    false,          false, "count unknown"),
            (.loading,  false,    false,          false, "count unknown"),
            (.failed(reason: "offline"), false, false, false,
             "a failed fetch is not zero rooms, and not a count to assert either"),
        ]
        for (rooms, isLinked, alreadyOffered, expected, why) in cases {
            XCTAssertEqual(
                WhySignInInvitation.shouldPresent(
                    rooms: rooms, isLinked: isLinked, alreadyOffered: alreadyOffered),
                expected, why)
        }
    }

    func testStaleRoomsStillCarryAUsableCount() {
        // Stale means "possibly not current", not "possibly not real". Those
        // rooms were sent; the argument holds.
        XCTAssertTrue(WhySignInInvitation.shouldPresent(
            rooms: .loaded(rooms: [room("a")], stale: true),
            isLinked: false, alreadyOffered: false))
    }
}

@MainActor
final class WhySignInOfferTests: XCTestCase {

    private var suiteName = ""
    private var defaults: UserDefaults!

    override func setUp() {
        super.setUp()
        suiteName = "thegoodguest.tests.whysignin.\(UUID().uuidString)"
        defaults = UserDefaults(suiteName: suiteName)
    }

    override func tearDown() {
        defaults.removePersistentDomain(forName: suiteName)
        defaults = nil
        super.tearDown()
    }

    func testUnaskedByDefaultAndRememberedOnceMarked() {
        XCTAssertFalse(WhySignInOffer.hasOffered(defaults))
        WhySignInOffer.markOffered(defaults)
        XCTAssertTrue(WhySignInOffer.hasOffered(defaults))
    }

    func testTheMemoryIsWhatStopsTheSecondOffer() {
        let rooms = RoomsLoadState.loaded(rooms: [room("a")], stale: false)
        XCTAssertTrue(WhySignInInvitation.shouldPresent(
            rooms: rooms, isLinked: false, alreadyOffered: WhySignInOffer.hasOffered(defaults)))

        WhySignInOffer.markOffered(defaults)

        XCTAssertFalse(WhySignInInvitation.shouldPresent(
            rooms: rooms, isLinked: false, alreadyOffered: WhySignInOffer.hasOffered(defaults)))
    }
}
