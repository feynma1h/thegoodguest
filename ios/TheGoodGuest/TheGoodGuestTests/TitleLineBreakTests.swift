/// Pins how a title holds its last two words together (`RSLayout`), so a
/// card or a screen's title never ends on one short word alone.

import XCTest
@testable import TheGoodGuest

final class TitleLineBreakTests: XCTestCase {

    private let held = "\u{00A0}"

    func testARoomsNameKeepsItsLastTwoWordsTogether() {
        XCTAssertEqual("The 28 August room".rsKeepingLastWordsTogether, "The 28 August\(held)room")
    }

    func testATimedNameKeepsItsTimeTogether() {
        XCTAssertEqual("The 28 August room, 2:10 pm".rsKeepingLastWordsTogether,
                       "The 28 August room, 2:10\(held)pm")
    }

    /// Wider than the narrowest line a title gets, the pair would break
    /// inside a word, so it is left to break between them.
    func testAPairTooLongToHoldIsLeftAlone() {
        XCTAssertEqual("The 3 September room".rsKeepingLastWordsTogether, "The 3 September room")
    }

    func testOneWordIsLeftAlone() {
        XCTAssertEqual("Account".rsKeepingLastWordsTogether, "Account")
    }
}
