/// Offline pin for the mint POST timeout invariant (found live at RP-6 Gate 3).
///
/// The client's mint timeout must exceed api-public's Cloud Run request
/// ceiling (120 s as deployed): a local timeout below the server's own limit
/// manufactures a failure for a mint the server may still complete, and the
/// mint stores nothing on abort — so the abandoned request wastes the whole
/// attempt. The ~2,200-path long-walk mint died exactly this way (client
/// abandon at 60 s + server 504 at 120 s).
///
/// Unit test, no network — deliberately NOT in UploadSessionClientTests,
/// which is the live-gated class (the honest-count taxonomy keeps live and
/// offline tests in separate homes).

import XCTest
@testable import RoomStudioCapture

final class UploadSessionClientTimeoutTests: XCTestCase {

    func test_mintTimeout_exceedsServerRequestCeiling() {
        let cloudRunRequestCeilingSec: TimeInterval = 120
        XCTAssertGreaterThan(
            UploadSessionClient.mintTimeoutSec, cloudRunRequestCeilingSec,
            "The client must outlive any answer the server can still give — see the constant's docstring"
        )
    }
}
