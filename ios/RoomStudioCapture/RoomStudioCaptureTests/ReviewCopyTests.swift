/// Pins the review card's copy precedence against its action set.
///
/// The defect these exist for: the card's text and the action buttons are two
/// expressions of one decision, written as separate expressions in the same view.
/// `actions` ranked isPreparing → !canSend → thinCoverage; the card ranked
/// thinCoverage above everything. So a capture that could not be sent AT ALL — an
/// empty pass, or one whose bundle.pb assembly failed — showed the rescan action
/// correctly while the card threw away the caller's verdict and claimed "I've got
/// the bones, but a few gaps": a coverage claim about a capture that does not
/// exist, on the one screen whose job is telling the truth before sending.
///
/// Unreachable today (thinCoverage is never set true — task #13), which is exactly
/// why it is pinned: the trap springs the day coverage gets wired, and by then
/// nobody will remember the two expressions have to agree.

import XCTest
@testable import RoomStudioCapture

final class ReviewCopyTests: XCTestCase {

    private let verdict = "CALLER VERDICT"
    private let gaps = "I've got the bones, but a few gaps. Worth another minute to fill them in?"

    private func text(thin: Bool = false, canSend: Bool = true, preparing: Bool = false) -> String {
        ReviewView.cardText(verdict: verdict,
                            thinCoverage: thin,
                            canSend: canSend,
                            isPreparing: preparing)
    }

    // MARK: - The regression

    /// THE DEFECT: nothing sendable + thin coverage must NOT claim coverage. The
    /// caller owns which non-sendable case it is (empty vs assembly failure) and
    /// says so in the verdict.
    func testNotSendableKeepsTheCallersVerdictEvenWhenThin() {
        XCTAssertEqual(text(thin: true, canSend: false), verdict)
        XCTAssertNotEqual(text(thin: true, canSend: false), gaps,
                          "a capture that cannot be sent must not be described by its coverage")
    }

    /// Same for the transient packing state: "packing it up" outranks a gaps claim.
    func testPreparingKeepsTheCallersVerdictEvenWhenThin() {
        XCTAssertEqual(text(thin: true, preparing: true), verdict)
    }

    /// The precedence must match `actions`, which ranks isPreparing first, then
    /// !canSend, then thinCoverage. Pinned as a table so a change to one side
    /// without the other fails here.
    func testPrecedenceMatchesTheActionSet() {
        // (thin, canSend, preparing) -> expected
        let cases: [(Bool, Bool, Bool, String)] = [
            (false, true,  false, verdict),  // ordinary sendable capture
            (true,  true,  false, gaps),     // thin, but sendable — the gaps copy leads
            (false, false, false, verdict),  // empty / assembly failed
            (true,  false, false, verdict),  // both → not-sendable wins
            (false, true,  true,  verdict),  // still packing
            (true,  true,  true,  verdict),  // both → packing wins
            (true,  false, true,  verdict),  // all three → still the verdict
        ]
        for (thin, canSend, preparing, expected) in cases {
            XCTAssertEqual(
                text(thin: thin, canSend: canSend, preparing: preparing), expected,
                "thin=\(thin) canSend=\(canSend) preparing=\(preparing)")
        }
    }

    // MARK: - The dormant treatment

    /// The ONE case the gaps copy is for. Unreachable in the app today (task #13),
    /// so this is also the record of what wiring thinCoverage is supposed to produce.
    func testThinCoverageCopyAppliesOnlyToASendableThinCapture() {
        XCTAssertEqual(text(thin: true), gaps)
    }

    /// A whole capture never gets the gaps copy.
    func testWholeCaptureUsesTheVerdict() {
        XCTAssertEqual(text(), verdict)
    }
}
