/// Pins the Apple token revocation step — the half of guideline 5.1.1(v) that
/// deleting the account does not satisfy on its own.
///
/// TWO PROPERTIES CARRY THIS, and they pull in opposite directions, which is
/// why they are pinned together:
///
///   - a revocation that CAN happen must happen, or Apple rejects the app at
///     review and the account keeps appearing under the person's Apple ID;
///   - a revocation that CANNOT happen must not stop the deletion. That is
///     TN3194's own instruction. A build that threw here would hold someone's
///     data hostage to a service neither party controls, and would fail the
///     guideline in the other direction.
///
/// The seams exist for this test rather than for tidiness: Apple's sheet and
/// Firebase's revokeToken are both unreachable offline, and without them every
/// branch below would be verifiable only by deleting a real account.

import XCTest
@testable import TheGoodGuest

final class AppleAccountRevocationTests: XCTestCase {

    private func run(
        isAppleLinked: Bool,
        code: String?,
        revokeThrows: Bool = false
    ) async -> (AppleRevocation, codeAsked: Bool, revoked: [String]) {
        var codeAsked = false
        var revoked: [String] = []
        let outcome = await AppleAccountRevocation.revokeIfNeeded(
            isAppleLinked: isAppleLinked,
            fetchCode: { codeAsked = true; return code },
            revoke: { c in
                revoked.append(c)
                if revokeThrows { throw URLError(.notConnectedToInternet) }
            }
        )
        return (outcome, codeAsked, revoked)
    }

    // MARK: - It happens when it can

    func test_linkedAccountWithACode_isRevoked() async {
        let (outcome, asked, revoked) = await run(isAppleLinked: true, code: "abc123")
        XCTAssertEqual(outcome, .revoked)
        XCTAssertTrue(asked)
        XCTAssertEqual(revoked, ["abc123"], "the fresh code must reach revokeToken verbatim")
    }

    // MARK: - It is not attempted when there is nothing to revoke

    func test_unlinkedAccount_neverPresentsApple() async {
        // A Google-only or anonymous user being shown Apple's sheet during
        // deletion would be inexplicable, and there is no token to revoke.
        let (outcome, asked, revoked) = await run(isAppleLinked: false, code: "abc123")
        XCTAssertEqual(outcome, .notLinked)
        XCTAssertFalse(asked, "Apple must not be asked when no Apple identity exists")
        XCTAssertTrue(revoked.isEmpty)
    }

    // MARK: - It never blocks the deletion

    func test_cancelledAuthorization_isNotRevoked_ratherThanAnError() async {
        // The user dismissed Apple's sheet. They still asked to be deleted.
        let (outcome, asked, revoked) = await run(isAppleLinked: true, code: nil)
        XCTAssertEqual(outcome, .notRevoked)
        XCTAssertTrue(asked)
        XCTAssertTrue(revoked.isEmpty)
    }

    func test_emptyCode_isNotRevoked() async {
        let (outcome, _, revoked) = await run(isAppleLinked: true, code: "")
        XCTAssertEqual(outcome, .notRevoked)
        XCTAssertTrue(revoked.isEmpty, "an empty code must not be sent to revokeToken")
    }

    func test_revokeThrowing_isNotRevoked_ratherThanAThrow() async {
        // Offline, or Apple refused. TN3194: fulfil the deletion anyway.
        let (outcome, _, revoked) = await run(
            isAppleLinked: true, code: "abc123", revokeThrows: true
        )
        XCTAssertEqual(outcome, .notRevoked)
        XCTAssertEqual(revoked, ["abc123"], "it must have been attempted before giving up")
    }

    func test_noBranchEverThrows() async {
        // The signature is non-throwing, so this is pinned by construction —
        // stated anyway, because the property is the whole point and a future
        // change to `throws` would be a silent guideline regression that
        // compiles at every call site the moment someone adds `try`.
        for linked in [true, false] {
            for code in [nil, "", "abc"] as [String?] {
                for throwing in [true, false] {
                    let (outcome, _, _) = await run(
                        isAppleLinked: linked, code: code, revokeThrows: throwing
                    )
                    XCTAssertTrue(
                        [.notLinked, .revoked, .notRevoked].contains(outcome),
                        "every path must yield an outcome, never a failure"
                    )
                }
            }
        }
    }
}
