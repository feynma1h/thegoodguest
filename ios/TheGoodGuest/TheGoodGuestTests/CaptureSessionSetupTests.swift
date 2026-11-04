/// Pins for the capture session's shared configuration: what production
/// capture installs, stated once, so any other session that measures a room
/// (the live-boxes detector) is measuring the same session. No ARKit run —
/// configuration objects and a never-run session only; simulator-safe.

import ARKit
import XCTest
@testable import TheGoodGuest

final class CaptureSessionSetupTests: XCTestCase {

    func test_worldTracking_isGravityAligned_withBothPlaneDirections() {
        for hasLidar in [false, true] {
            let config = CaptureSessionSetup.worldTrackingConfiguration(hasLidar: hasLidar)
            XCTAssertEqual(config.worldAlignment, .gravity)
            XCTAssertEqual(config.planeDetection, [.horizontal, .vertical])
        }
    }

    func test_withoutLidar_sceneDepthIsNeverRequested() {
        let config = CaptureSessionSetup.worldTrackingConfiguration(hasLidar: false)
        XCTAssertFalse(config.frameSemantics.contains(.sceneDepth))
    }

    func test_sceneDepth_isRequestedExactlyWhereTheHardwareDeliversIt() {
        let config = CaptureSessionSetup.worldTrackingConfiguration(hasLidar: true)
        XCTAssertEqual(config.frameSemantics.contains(.sceneDepth),
                       ARWorldTrackingConfiguration.supportsFrameSemantics(.sceneDepth))
    }

    func test_roomPlan_needsLidar() {
        XCTAssertFalse(CaptureSessionSetup.supportsRoomPlan(hasLidar: false))
    }

    func test_reassert_onASessionThatNeverRan_refusesWithoutTouchingIt() {
        let session = ARSession()
        guard case .failure(let refusal) = CaptureSessionSetup.reassertSceneDepth(on: session) else {
            return XCTFail("a session with no configuration has nothing to re-assert")
        }
        XCTAssertEqual(refusal, .noInstalledConfiguration)
        XCTAssertNil(session.configuration)
    }
}
