/// Table pins for CaptureReclaim (decision 0084) — the coupled-pair rule:
/// reclaim ONLY on a genuinely terminal, user-seen outcome; failed_incomplete
/// retains its files (the future re-upload coordinator's material); active
/// machinery and unacknowledged records are never touched.

import XCTest
@testable import TheGoodGuestCapture

final class CaptureReclaimTests: XCTestCase {

    // MARK: - Backend-status table

    func test_status_ready_reclaims() {
        XCTAssertTrue(CaptureReclaim.reclaims(status: .ready))
    }

    func test_status_failed_reclaims() {
        XCTAssertTrue(CaptureReclaim.reclaims(status: .failed))
    }

    func test_status_failedInvalid_reclaims() {
        XCTAssertTrue(CaptureReclaim.reclaims(status: .failedInvalid))
    }

    func test_status_failedIncomplete_retains_filesAreTheRecoveryMaterial() {
        XCTAssertFalse(CaptureReclaim.reclaims(status: .failedIncomplete))
    }

    func test_status_transientAndUnknown_retain() {
        XCTAssertFalse(CaptureReclaim.reclaims(status: .queued))
        XCTAssertFalse(CaptureReclaim.reclaims(status: .processing))
        XCTAssertFalse(CaptureReclaim.reclaims(status: .unknown("future_state")))
    }

    // MARK: - Flight-end table (keyed on the screen the user is leaving)

    func test_flightEnd_doorway_reclaims() {
        XCTAssertTrue(CaptureReclaim.reclaimsAtFlightEnd(.doorway))
    }

    func test_flightEnd_processingFailed_reclaims() {
        XCTAssertTrue(CaptureReclaim.reclaimsAtFlightEnd(.processingFailed))
    }

    func test_flightEnd_uploadFailed_reclaims_reasonIsOnScreen() {
        XCTAssertTrue(CaptureReclaim.reclaimsAtFlightEnd(.uploadFailed))
    }

    func test_flightEnd_incompleteUpload_retains() {
        XCTAssertFalse(CaptureReclaim.reclaimsAtFlightEnd(.incompleteUpload(missingCount: 1)))
        XCTAssertFalse(CaptureReclaim.reclaimsAtFlightEnd(.incompleteUpload(missingCount: 0)),
                       "retention is about the outcome, not about how many files the server named")
    }

    func test_flightEnd_everyNonTerminalScreen_retains() {
        XCTAssertFalse(CaptureReclaim.reclaimsAtFlightEnd(.sending))
        XCTAssertFalse(CaptureReclaim.reclaimsAtFlightEnd(.waiting(phase: .analyzing, anchor: nil)))
        XCTAssertFalse(CaptureReclaim.reclaimsAtFlightEnd(.sendFailed(terminal: true)))
        XCTAssertFalse(CaptureReclaim.reclaimsAtFlightEnd(.sendFailed(terminal: false)))
        XCTAssertFalse(CaptureReclaim.reclaimsAtFlightEnd(.sendPaused))
        XCTAssertFalse(CaptureReclaim.reclaimsAtFlightEnd(.checkFailed(anchor: nil, stopped: true)))
        XCTAssertFalse(CaptureReclaim.reclaimsAtFlightEnd(.checkFailed(anchor: Date(), stopped: false)))
    }

    func test_flightEnd_notOurs_retains_standDownOwnsForeignRecords() {
        // Decision 0074's stand-down acknowledges + hides; reclaiming would
        // destroy backup-migration evidence for no user-visible gain.
        XCTAssertFalse(CaptureReclaim.reclaimsAtFlightEnd(.notOurs))
    }

    // MARK: - Launch-scan table

    func test_launchScan_unacknowledged_alwaysSkips_restoreInventoryIsSacred() {
        XCTAssertEqual(CaptureReclaim.launchScanAction(phase: .complete, acknowledged: false), .skip)
        XCTAssertEqual(CaptureReclaim.launchScanAction(phase: .failed, acknowledged: false), .skip)
        XCTAssertEqual(CaptureReclaim.launchScanAction(phase: .uploadingBlobs, acknowledged: false), .skip)
        XCTAssertEqual(CaptureReclaim.launchScanAction(phase: .uploadingBundlePb, acknowledged: false), .skip)
    }

    func test_launchScan_acknowledgedComplete_confirmsViaServer_uploadDoneIsNotBackendTerminal() {
        XCTAssertEqual(CaptureReclaim.launchScanAction(phase: .complete, acknowledged: true), .confirmViaServer)
    }

    func test_launchScan_acknowledgedFailed_reclaimsDirectly_noSceneExistsToAsk() {
        XCTAssertEqual(CaptureReclaim.launchScanAction(phase: .failed, acknowledged: true), .reclaim)
    }

    func test_launchScan_acknowledgedActive_skips_liveMachinery() {
        XCTAssertEqual(CaptureReclaim.launchScanAction(phase: .uploadingBlobs, acknowledged: true), .skip)
        XCTAssertEqual(CaptureReclaim.launchScanAction(phase: .uploadingBundlePb, acknowledged: true), .skip)
    }
}
