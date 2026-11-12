/// Pins what review says about a capture before it is sent (ReviewCopy):
/// what will be rebuilt, how it was measured, and when it cannot be sent.

import XCTest
@testable import TheGoodGuest

final class ReviewCopyTests: XCTestCase {

    private let census = RoomCensus(objects: 9, walls: 13, doors: 2, windows: 1, openings: 0, floors: 1)

    func testAnEmptyCaptureCannotBeSentAndSaysSo() {
        let c = ReviewCopy.content(frames: 0, tier: .lidarRoomplan, census: nil, hasPlan: false,
                                   boxes: nil, isPreparing: false, assemblyFailure: nil)
        XCTAssertFalse(c.canSend)
        XCTAssertEqual(c.title, "I didn\u{2019}t catch enough to send.")
    }

    func testAFailedPackIsTerminalNotAWait() {
        let c = ReviewCopy.content(frames: 40, tier: .lidarArkit, census: nil, hasPlan: false,
                                   boxes: nil, isPreparing: false, assemblyFailure: "disk full")
        XCTAssertFalse(c.canSend)
        XCTAssertFalse(c.isPreparing)
    }

    func testPackingHoldsTheSendWithoutWithdrawingIt() {
        let c = ReviewCopy.content(frames: 126, tier: .lidarRoomplan, census: census, hasPlan: true,
                                   boxes: 2, isPreparing: true, assemblyFailure: nil)
        XCTAssertFalse(c.canSend)
        XCTAssertTrue(c.isPreparing)
    }

    func testTheFactsSayWhatWillBeRebuilt() {
        let c = ReviewCopy.content(frames: 126, tier: .lidarRoomplan, census: census, hasPlan: true,
                                   boxes: 2, isPreparing: false, assemblyFailure: nil)
        XCTAssertEqual(c.facts, ["13 walls, 2 doors and 1 window", "2 pieces boxed", "126 photos, measured with LiDAR"])
        XCTAssertNil(c.noPlanTitle)
        XCTAssertTrue(c.canSend)
    }

    func testABuildThatCannotBoxSaysNothingAboutBoxes() {
        let c = ReviewCopy.content(frames: 126, tier: .lidarRoomplan, census: census, hasPlan: true,
                                   boxes: nil, isPreparing: false, assemblyFailure: nil)
        XCTAssertFalse(c.facts.contains { $0.contains("boxed") })
        XCTAssertEqual(ReviewCopy.content(frames: 1, tier: .lidarArkit, census: nil, hasPlan: false, boxes: 1,
                                          isPreparing: false, assemblyFailure: nil).facts.first, "1 piece boxed")
    }

    func testACameraScanSaysHowItWasMeasuredOnce() {
        let c = ReviewCopy.content(frames: 131, tier: .arkitOnly, census: nil, hasPlan: false,
                                   boxes: nil, isPreparing: false, assemblyFailure: nil)
        XCTAssertEqual(c.facts, ["131 photos, measured with the camera"])
        XCTAssertEqual(c.noPlanTitle, "Measured with the camera")
        XCTAssertTrue(c.canSend, "every iPhone sends")
    }

    func testTheStructureListsOnlyWhatIsThere() {
        XCTAssertEqual(ReviewCopy.structure(RoomCensus(objects: 0, walls: 4, doors: 0, windows: 0, openings: 0, floors: 1)), "4 walls")
        XCTAssertEqual(ReviewCopy.structure(RoomCensus(objects: 0, walls: 1, doors: 1, windows: 0, openings: 0, floors: 1)), "1 wall and 1 door")
    }
}
