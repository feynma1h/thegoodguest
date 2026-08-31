/// Pins FailureCopy — the failure screens' one server-data-dependent line.
///
/// WHY THIS EXISTS: decision 0085's walk found the missing-file count silently
/// absent from the recoverable screen. The server had sent
/// `missing_paths: ['frames/000005.jpg']`; the screen said nothing about it,
/// because the 0072 redesign gave `FailureView.Kind.recoverable` no associated
/// value and nobody noticed a claim had been dropped. Nothing failed — there was
/// no test that could.
///
/// So the copy is a table now, and the two things a body like this gets wrong —
/// the singular/plural agreement and the zero-degrade — are pinned rather than
/// eyeballed. The honesty constraint (decisions 0084 + 0116 — a re-send is
/// promised only when CaptureRecovery has confirmed the files are on disk) is
/// pinned too: it is a product invariant, not a wording preference.

import XCTest
@testable import TheGoodGuestCapture

final class FailureCopyTests: XCTestCase {

    // MARK: - The count is stated

    func testStatesTheCountWhenTheServerNamedFiles() {
        XCTAssertTrue(FailureCopy.incompleteBody(missingCount: 14).hasPrefix("14 files"))
        XCTAssertTrue(FailureCopy.incompleteBody(missingCount: 2).hasPrefix("2 files"))
        XCTAssertTrue(FailureCopy.incompleteBody(missingCount: 331).hasPrefix("331 files"))
    }

    /// The exact case decision 0085 observed: one path in `missing_paths`.
    func testSingularReadsAsOneFile() {
        let body = FailureCopy.incompleteBody(missingCount: 1)
        XCTAssertTrue(body.hasPrefix("One file didn't finish its trip"), body)
        XCTAssertFalse(body.contains("1 files"), "plural verb on a single file")
        XCTAssertFalse(body.contains("their trip"), "singular subject takes 'its trip'")
    }

    func testPluralAgreesWithTheVerb() {
        let body = FailureCopy.incompleteBody(missingCount: 5)
        XCTAssertTrue(body.contains("didn't finish their trip"), body)
        XCTAssertFalse(body.contains("its trip"))
    }

    // MARK: - The zero-degrade

    /// `missing_paths` is optional on the wire and the poller defaults it to [].
    /// "0 files didn't make it" is both false and absurd, so a count of zero falls
    /// back to the unquantified wording the screen shipped before the count existed.
    func testZeroDegradesToUnquantifiedWording() {
        let body = FailureCopy.incompleteBody(missingCount: 0)
        XCTAssertTrue(body.hasPrefix("Some of your room's data didn't finish its trip"), body)
        XCTAssertFalse(body.contains("0 "), body)
    }

    /// Defensive: a negative can only arrive from a future bug, and it must not
    /// render as "-3 files".
    func testNegativeCountDegradesLikeZero() {
        XCTAssertEqual(FailureCopy.incompleteBody(missingCount: -3),
                       FailureCopy.incompleteBody(missingCount: 0))
    }

    // MARK: - The honesty constraint (decision 0084)

    /// THE PRODUCT INVARIANT: the rescan-only body must never imply the missing
    /// blobs can be re-sent. Only `incompleteBody(missingCount:resend:)` in
    /// `.available` may make that promise, because only there has CaptureRecovery
    /// confirmed every named file is still on the phone. "N files need
    /// re-uploading" — the obvious phrasing to reach for when restoring a count
    /// — is exactly the promise this overload must not make.
    func testNeverPromisesAReUpload() {
        for count in [0, 1, 2, 40] {
            let body = FailureCopy.incompleteBody(missingCount: count).lowercased()
            XCTAssertFalse(body.contains("re-upload"), "count=\(count): \(body)")
            XCTAssertFalse(body.contains("reupload"), "count=\(count): \(body)")
            XCTAssertFalse(body.contains("send the rest"), "count=\(count): \(body)")
            XCTAssertFalse(body.contains("retry"), "count=\(count): \(body)")
        }
    }

    /// The offered path stays a full rescan, and the blame stays off the user —
    /// the §7 voice rules, which a count could easily have displaced.
    func testKeepsTheRescanPathAndTheNoBlameClause() {
        for count in [0, 1, 9] {
            let body = FailureCopy.incompleteBody(missingCount: count)
            XCTAssertTrue(body.contains("one more full pass"), "count=\(count)")
            XCTAssertTrue(body.contains("Nothing's wrong with the room itself"), "count=\(count)")
            XCTAssertTrue(body.contains("can't show you a partial version honestly"), "count=\(count)")
        }
    }

    /// Blob paths are plumbing — the same category as the raw `http_404` the walk
    /// called out as leaking. The count crosses into the copy; the paths never do.
    func testNeverNamesAPath() {
        for count in [0, 1, 6] {
            let body = FailureCopy.incompleteBody(missingCount: count)
            XCTAssertFalse(body.contains("frames/"), "count=\(count)")
            XCTAssertFalse(body.contains(".jpg"), "count=\(count)")
        }
    }

    // MARK: - The re-send states (decisions 0084 + 0116)

    private let allStates: [FailureCopy.Resend] = [.available, .unavailable, .inFlight, .failed]

    /// THE CONSTRAINT, NOW CONDITIONAL. force_remint made the re-send real, so
    /// the ban on promising one became a ban on promising one WHEN IT IS NOT
    /// AVAILABLE. `.unavailable` is the state where the bytes are gone from the
    /// phone, and there the old absolute rule stands unchanged — including the
    /// exact wording, which must remain the body this screen has always shipped.
    func testUnavailableIsTheOldCopy_verbatim() {
        for count in [0, 1, 14] {
            XCTAssertEqual(FailureCopy.incompleteBody(missingCount: count, resend: .unavailable),
                           FailureCopy.incompleteBody(missingCount: count))
        }
    }

    /// The promise exists in exactly one state. A `.unavailable` body that said
    /// "I can send just those" would be a button-shaped lie about files that are
    /// not there; the other two states describe an attempt, not an offer.
    func testOnlyAvailablePromisesToSendTheFilesItself() {
        XCTAssertTrue(FailureCopy.incompleteBody(missingCount: 3, resend: .available)
            .contains("I can send just those"))
        for state in allStates where state != .available {
            let body = FailureCopy.incompleteBody(missingCount: 3, resend: state)
            XCTAssertFalse(body.contains("I can send just those"), "\(state): \(body)")
        }
    }

    /// The one claim `.available` makes about the world — that the files are
    /// still on this phone — is the one CaptureRecovery actually verified.
    func testAvailableClaimsOnlyWhatWasChecked() {
        let body = FailureCopy.incompleteBody(missingCount: 2, resend: .available)
        XCTAssertTrue(body.contains("still have them here on the phone"), body)
        // It must not promise the ROOM will succeed — only that the files can go
        // again. The pipeline can still fail after a complete upload.
        XCTAssertFalse(body.lowercased().contains("will be ready"), body)
        XCTAssertFalse(body.lowercased().contains("guarantee"), body)
    }

    /// A failed attempt says so. Silently falling back to the rescan copy would
    /// leave the user's tap unaccounted for — they pressed a button and the
    /// screen would look exactly as it did before.
    func testFailedSaysTheAttemptDidNotGetThrough_andKeepsBothWaysOut() {
        let body = FailureCopy.incompleteBody(missingCount: 2, resend: .failed)
        XCTAssertTrue(body.contains("didn't get through"), body)
        XCTAssertTrue(body.contains("still here on the phone"), body)
        XCTAssertTrue(body.contains("one more full pass"), "the rescan must stay reachable: \(body)")
    }

    /// Every state states the count, with the same agreement rules — one clause
    /// implementation, so a body cannot drift into "1 files".
    func testEveryStateStatesTheCountWithCorrectAgreement() {
        for state in allStates {
            XCTAssertTrue(FailureCopy.incompleteBody(missingCount: 1, resend: state)
                .hasPrefix("One file"), "\(state)")
            XCTAssertTrue(FailureCopy.incompleteBody(missingCount: 9, resend: state)
                .hasPrefix("9 files"), "\(state)")
            XCTAssertTrue(FailureCopy.incompleteBody(missingCount: 0, resend: state)
                .hasPrefix("Some of your room's data"), "\(state)")
            XCTAssertFalse(FailureCopy.incompleteBody(missingCount: 1, resend: state)
                .contains("1 files"), "\(state)")
        }
    }

    /// The no-blame rule and the path ban hold in every state.
    func testNeverBlamesTheUserAndNeverNamesAPathInAnyState() {
        for state in allStates {
            for count in [0, 1, 6] {
                let body = FailureCopy.incompleteBody(missingCount: count, resend: state)
                XCTAssertFalse(body.contains("frames/"), "\(state) count=\(count)")
                XCTAssertFalse(body.contains(".jpg"), "\(state) count=\(count)")
                XCTAssertFalse(body.lowercased().contains("you didn't"), "\(state): \(body)")
                XCTAssertFalse(body.lowercased().contains("your fault"), "\(state): \(body)")
            }
        }
    }

    // MARK: - The actions table

    /// THE PAIRING THAT MATTERS. A screen saying "Send what's missing" whose
    /// button starts a rescan would destroy the capture the sentence just
    /// promised to send. Labels and actions are decided together, here, so the
    /// view and the flow read the same row.
    func testEveryLabelMatchesWhatItsButtonDoes() {
        let available = FailureCopy.recoverableActions(.available)
        XCTAssertEqual(available.primary, .resend)
        XCTAssertEqual(available.primaryLabel, "Send what's missing")
        XCTAssertEqual(available.secondary, .leave)

        let unavailable = FailureCopy.recoverableActions(.unavailable)
        XCTAssertEqual(unavailable.primary, .rescan)
        XCTAssertEqual(unavailable.primaryLabel, "Scan the room again")
        XCTAssertEqual(unavailable.secondary, .leave)

        let failed = FailureCopy.recoverableActions(.failed)
        XCTAssertEqual(failed.primary, .resend)
        XCTAssertEqual(failed.secondary, .rescan,
                       "after a failed send the rescan is the real alternative")
    }

    /// A resend button is never offered in a state whose copy does not promise
    /// one — the label/copy pair is what the user reads as a single sentence.
    func testTheRescanOnlyStateNeverOffersAResendButton() {
        XCTAssertNotEqual(FailureCopy.recoverableActions(.unavailable).primary, .resend)
        XCTAssertNotEqual(FailureCopy.recoverableActions(.unavailable).secondary, .resend)
    }

    /// Only the in-flight state disables its primary: tapping again there spends
    /// a second mint-quota unit for no gain. Every other state must stay
    /// actionable — a disabled button with no explanation is a dead end.
    func testOnlyTheInFlightStateDisablesItsPrimary() {
        for state in allStates {
            XCTAssertEqual(FailureCopy.recoverableActions(state).primaryEnabled,
                           state != .inFlight, "\(state)")
        }
    }

    /// Leaving is always reachable, one way or another: the capture stays on
    /// disk (CaptureReclaim retains on incompleteUpload), so no state may trap
    /// the user into acting.
    func testTheUserCanAlwaysGetOutOrStartOver() {
        for state in allStates {
            let actions = FailureCopy.recoverableActions(state)
            XCTAssertTrue([actions.primary, actions.secondary].contains { $0 != .resend },
                          "\(state) offers nothing but a re-send")
        }
    }
}
