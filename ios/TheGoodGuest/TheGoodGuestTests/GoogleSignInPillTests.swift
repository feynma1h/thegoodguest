/// Pins that the Google button carries Google's own G, read from the
/// GoogleSignIn SDK's bundle rather than redrawn (see GoogleSignInPill).

import XCTest
@testable import TheGoodGuest

final class GoogleSignInPillTests: XCTestCase {

    func testGooglesOwnMarkResolvesFromItsSDK() throws {
        let logo = try XCTUnwrap(GoogleSignInPill.logo,
                                 "the G is read from GoogleSignIn_GoogleSignIn.bundle; if the SDK moved it, the button has lost its mark")
        XCTAssertEqual(logo.size.width, logo.size.height, "the G is square")
    }

    func testItIsTheSameHeightAsApplesButton() {
        // AccountSheet sizes Apple's button from this constant; equal size is
        // what Google's guidelines ask of the two.
        XCTAssertEqual(GoogleSignInPill.height, 54)
    }
}
