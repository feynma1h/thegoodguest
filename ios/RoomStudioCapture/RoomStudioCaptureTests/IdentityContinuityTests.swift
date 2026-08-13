/// Table pins for the launch continuity reading (decision 0139).
///
/// The reading exists because `currentUser == nil` is true of a first run and
/// equally true of an install whose credential was discarded. These tests pin
/// the full truth table, and — the load-bearing pair — that the two known
/// churns on the operator's iPhone 16 Pro would each have been reported.

import XCTest
@testable import RoomStudioCapture

final class IdentityContinuityTests: XCTestCase {

    // MARK: - The full table

    func testAUserPresentIsAlwaysContinuous() {
        for deviceIdentity in [true, false] {
            for records in [true, false] {
                XCTAssertEqual(
                    IdentityContinuity.read(hasFirebaseUser: true,
                                            hasDeviceIdentity: deviceIdentity,
                                            hasCaptureRecords: records),
                    .continuous,
                    "a present user settles it regardless of the other signals")
            }
        }
    }

    func testNoTraceOfPriorUseIsAFirstRun() {
        XCTAssertEqual(
            IdentityContinuity.read(hasFirebaseUser: false,
                                    hasDeviceIdentity: false,
                                    hasCaptureRecords: false),
            .firstRun)
    }

    func testDeviceIdentityReadableMeansTheCredentialIsGone() {
        XCTAssertEqual(
            IdentityContinuity.read(hasFirebaseUser: false,
                                    hasDeviceIdentity: true,
                                    hasCaptureRecords: false),
            .credentialLost,
            "the device UUID shares an access group with Firebase's item, so "
            + "reading it back proves the Keychain is answering")
    }

    func testRecordsWithoutDeviceIdentityMeansTheKeychainIsSilent() {
        XCTAssertEqual(
            IdentityContinuity.read(hasFirebaseUser: false,
                                    hasDeviceIdentity: false,
                                    hasCaptureRecords: true),
            .keychainUnavailable,
            "records live outside the Keychain, so they outlive a read failure")
    }

    func testDeviceIdentityOutranksRecords() {
        // Records are reclaimed once the user has seen the outcome (0084), so
        // their absence proves nothing. The device UUID is the durable signal.
        XCTAssertEqual(
            IdentityContinuity.read(hasFirebaseUser: false,
                                    hasDeviceIdentity: true,
                                    hasCaptureRecords: true),
            .credentialLost)
    }

    // MARK: - What it would have caught

    func testBothKnownChurnsWouldHaveBeenReported() {
        // Measured in decision 0139: across both UID changes on the 16 Pro the
        // device UUID was byte-identical (0138) and capture records were on
        // disk. Either signal alone puts the launch in the loss set.
        let churn = IdentityContinuity.read(hasFirebaseUser: false,
                                            hasDeviceIdentity: true,
                                            hasCaptureRecords: true)
        XCTAssertEqual(churn, .credentialLost)
        XCTAssertTrue(IdentityContinuity.isLoss(churn))
    }

    func testAFirstRunIsNotReportedAsALoss() {
        XCTAssertFalse(IdentityContinuity.isLoss(
            IdentityContinuity.read(hasFirebaseUser: false,
                                    hasDeviceIdentity: false,
                                    hasCaptureRecords: false)))
        XCTAssertFalse(IdentityContinuity.isLoss(
            IdentityContinuity.read(hasFirebaseUser: true,
                                    hasDeviceIdentity: true,
                                    hasCaptureRecords: true)))
    }

    func testKeychainUnavailableIsALossButADifferentOne() {
        // Worth a fault too — the app is about to mint over a credential that
        // may still be intact — but the cure is different, so the readings
        // must not collapse into one.
        let unavailable = IdentityContinuity.read(hasFirebaseUser: false,
                                                  hasDeviceIdentity: false,
                                                  hasCaptureRecords: true)
        XCTAssertTrue(IdentityContinuity.isLoss(unavailable))
        XCTAssertNotEqual(unavailable, .credentialLost)
    }

    // MARK: - The non-minting read

    func testExistingDeviceIdDoesNotMint() {
        // The reading's Keychain probe must not create the thing it checks:
        // a minting read would make every launch after the first look like an
        // install that had captured, and would fabricate the loss signal.
        let before = DeviceIdentity.existingDeviceId()
        _ = DeviceIdentity.existingDeviceId()
        XCTAssertEqual(before, DeviceIdentity.existingDeviceId(),
                       "repeated reads must be stable and must not mint")
    }
}
