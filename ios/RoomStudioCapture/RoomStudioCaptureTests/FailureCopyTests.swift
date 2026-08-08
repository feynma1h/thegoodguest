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
/// eyeballed. The honesty constraint (no re-upload promise, decision 0084) is
/// pinned too: it is a product invariant, not a wording preference.

import XCTest
@testable import RoomStudioCapture

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

    /// THE PRODUCT INVARIANT: there is no re-upload of the missing blobs. It is
    /// blocked on a mint-contract change server-side, not on client work, so any
    /// wording that promises one is a lie the user acts on. "N files need
    /// re-uploading" — the superseded SceneStatusView's line, and the obvious
    /// phrasing to reach for when restoring a count — is exactly that promise.
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
}
