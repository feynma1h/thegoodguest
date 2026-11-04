/// Pins for the live-boxes feature switch: it is ON by default, and a session
/// that is started while it is on runs and one that is stopped does not.

import XCTest
@testable import TheGoodGuest

final class LiveBoxesFeatureTests: XCTestCase {

    func test_theFeatureIsOnByDefault() {
        XCTAssertTrue(LiveBoxesFeature.isEnabled)
    }

    @MainActor
    func test_aSession_runsBetweenStartAndStop_andReportsTheMissingDetector() {
        let session = LiveBoxesSession()
        XCTAssertFalse(session.isRunning)
        session.start()
        XCTAssertTrue(session.isRunning)
        // The test bundle carries no export: a checkout without the model.
        XCTAssertEqual(session.detector, .missing)
        session.stop()
        XCTAssertFalse(session.isRunning)
    }
}
