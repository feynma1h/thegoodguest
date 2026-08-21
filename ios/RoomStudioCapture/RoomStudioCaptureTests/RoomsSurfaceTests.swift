/// Pins what each surface DOES with the load state — home's variant, and whether
/// the sign-in invitation is offered at all.
///
/// Both tables exist for the same reason: the first-time hero and the sign-in
/// sheet each make a claim about how many rooms the user has, and a fetch that
/// has not returned or has failed is not a licence to make either claim. The
/// hero is allowed to hold the space (it is true for everyone) but never alone
/// after a failure, and the sheet — whose entire argument is a count — is simply
/// not offered until the count is known.

import XCTest
@testable import RoomStudioCapture

private func room(_ id: String) -> RoomSummary {
    RoomSummary(id: id, bundleId: "\(id)-bundle", title: "the July 12 room",
                statusLine: "on your desk", state: .ready)
}

final class HomeRoomsPresentationTests: XCTestCase {

    func testPresentationTable() {
        let cases: [(RoomsLoadState, HomeRooms.Presentation)] = [
            (.idle,                                     .hero),
            (.loading,                                  .hero),
            (.loaded(rooms: [], stale: false),          .hero),
            (.loaded(rooms: [], stale: true),           .hero),
            (.loaded(rooms: [room("a")], stale: false), .strip),
            (.loaded(rooms: [room("a")], stale: true),  .strip),
            (.failed(reason: "offline"),                .heroWithTrouble),
        ]
        for (state, expected) in cases {
            XCTAssertEqual(HomeRooms.presentation(for: state), expected, "\(state)")
        }
    }

    func testAFailedFetchNeverPresentsAsTheFirstTimeHeroAlone() {
        // The regression this exists to prevent: `hasRooms: !rooms.isEmpty` over
        // a state that collapses failure to [], which silently shows a returning
        // user the screen that says they have never scanned anything.
        XCTAssertNotEqual(HomeRooms.presentation(for: .failed(reason: "offline")), .hero)
    }

    func testStripShowsAtMostItsLimitAndKeepsOrder() {
        let rooms = ["a", "b", "c", "d", "e"].map(room)
        XCTAssertEqual(HomeRooms.stripRooms(rooms).map(\.id), ["a", "b", "c"])
        XCTAssertEqual(HomeRooms.stripRooms(Array(rooms.prefix(2))).map(\.id), ["a", "b"])
        XCTAssertTrue(HomeRooms.stripRooms([]).isEmpty)
    }
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
        suiteName = "roomstudio.tests.whysignin.\(UUID().uuidString)"
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
