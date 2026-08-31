/// Pins what the deletion screen says in each state it can be in.
///
/// WHY THIS IS A TEST AND NOT A READING. Deletion is the one screen where a
/// wrong sentence costs something irreversible, and the four ways to word it
/// wrongly are all plausible-looking:
///
///   - reporting a resumed pass's zero counts as "you had nothing",
///   - using the word "deleted" in the state where nothing has been,
///   - implying a failure got partway,
///   - saying "gone" when the Apple token outlived the account.
///
/// Each is a sentence a careful person would write by accident, and none is
/// visible by reading one state in isolation — which is exactly what reading a
/// SwiftUI body gives you. The table makes all five readable at once; these
/// pin the properties that must hold across them.

import XCTest
@testable import TheGoodGuest

final class DeleteAccountCopyTests: XCTestCase {

    private func copy(_ state: DeleteAccountState) -> DeleteAccountCopy {
        DeleteAccountWording.copy(for: state)
    }

    private var allStates: [DeleteAccountState] {
        [
            .confirm,
            .working,
            .done(AccountDeletionCounts(), .notLinked),
            .done(AccountDeletionCounts(rooms: 6, conversations: 3, files: 200), .revoked),
            .done(AccountDeletionCounts(rooms: 6, conversations: 3, files: 200), .notRevoked),
            .partial(AccountDeletionCounts(files: 40)),
            .failed(.serverError(500)),
            .failed(.unauthorized),
            .failed(.unavailable),
            .failed(.confirmationMismatch),
            .failed(.decodeFailed("x")),
            .failed(.unexpectedStatus(418)),
        ]
    }

    // MARK: - Rule 1: a count describes the pass, never the account

    func test_done_withNothingRemoved_doesNotClaimTheAccountWasEmpty() {
        let body = copy(.done(AccountDeletionCounts(), .notLinked)).body
        // The failure this guards: "there was nothing to delete" told to
        // someone whose six rooms were removed by the call before this one.
        XCTAssertTrue(
            body.contains("an earlier"),
            "a zero-count pass must allow that an earlier attempt did the work"
        )
        XCTAssertFalse(body.contains("this pass found"))
    }

    func test_done_withCounts_statesThemAsRemovedByThisPass() {
        let body = copy(.done(AccountDeletionCounts(rooms: 6, conversations: 3, files: 200), .revoked)).body
        XCTAssertTrue(body.contains("this pass found"))
        XCTAssertTrue(body.contains("6 rooms"))
    }

    func test_inventory_omitsEveryZeroCategory() {
        let one = DeleteAccountWording.inventory(AccountDeletionCounts(rooms: 4))
        XCTAssertEqual(one, "4 rooms")
        XCTAssertFalse(one.contains("0"))
    }

    func test_inventory_singularAndPluralAndJoining() {
        XCTAssertEqual(DeleteAccountWording.inventory(AccountDeletionCounts(rooms: 1)), "1 room")
        XCTAssertEqual(
            DeleteAccountWording.inventory(AccountDeletionCounts(rooms: 2, conversations: 1)),
            "2 rooms and 1 conversation"
        )
        XCTAssertEqual(
            DeleteAccountWording.inventory(
                AccountDeletionCounts(rooms: 2, conversations: 1, designSpecs: 1, files: 9)
            ),
            "2 rooms, 1 conversation, 1 arrangement and 9 files"
        )
    }

    func test_inventory_excludesUploadSessions() {
        // Bookkeeping, not a possession. Including it inflates a number that
        // sits next to the word "deleted".
        let text = DeleteAccountWording.inventory(
            AccountDeletionCounts(rooms: 1, uploadSessions: 99)
        )
        XCTAssertEqual(text, "1 room")
    }

    // MARK: - Rule 4: "gone" must not overstate when Apple was not told

    func test_onlyTheUnrevokedDoneStateAsksForAnythingMore() {
        let counts = AccountDeletionCounts(rooms: 6)
        for revocation in [AppleRevocation.notLinked, .revoked] {
            let body = copy(.done(counts, revocation)).body
            XCTAssertFalse(
                body.contains("Settings"),
                "\(revocation) must not hand the user a chore that is already done"
            )
        }
        let unrevoked = copy(.done(counts, .notRevoked)).body
        XCTAssertTrue(unrevoked.contains("Settings"))
        XCTAssertTrue(unrevoked.contains("Sign in with Apple"))
    }

    func test_theUnrevokedStateStillSaysTheDataIsGone() {
        // TN3194's fallback deletes the data regardless. The remaining step is
        // Apple's list, and the copy must not blur that into "not deleted".
        let body = copy(.done(AccountDeletionCounts(rooms: 6), .notRevoked)).body
        XCTAssertTrue(body.contains("Your account is gone"))
        XCTAssertTrue(body.contains("not archived or held anywhere"))
    }

    func test_theAppleInstructionPrecedesTheReassurance() {
        // Found by screenshot: trailing the instruction put the only actionable
        // sentence below the fold at AX5, under a fully-visible "Start again".
        // It scrolled, so neither the layout audit nor reading the table could
        // see it. Pinned here so a later tidy-up cannot quietly restore it.
        let body = copy(.done(AccountDeletionCounts(rooms: 6), .notRevoked)).body
        guard
            let instruction = body.range(of: "still appears under"),
            let reassurance = body.range(of: "not archived or held anywhere")
        else { return XCTFail("both sentences must be present") }
        XCTAssertTrue(
            instruction.lowerBound < reassurance.lowerBound,
            "the step the user must take has to come before the closing reassurance"
        )
    }

    func test_theInventoryIsUnchangedByRevocation() {
        // The Apple tail is additive. A revocation outcome must not alter what
        // the pass reports having removed.
        let counts = AccountDeletionCounts(rooms: 6, conversations: 3)
        let expected = DeleteAccountWording.inventory(counts)
        for revocation in [AppleRevocation.notLinked, .revoked, .notRevoked] {
            XCTAssertTrue(
                copy(.done(counts, revocation)).body.contains(expected),
                "\(revocation) lost the inventory \(expected.debugDescription)"
            )
        }
    }

    // MARK: - Rule 2: partial has deleted nothing the user owns

    func test_partial_neverSaysAnythingWasDeleted() {
        let body = copy(.partial(AccountDeletionCounts(files: 40))).body.lowercased()
        for word in ["deleted", "gone", "removed"] {
            XCTAssertFalse(body.contains(word), "partial must not contain '\(word)'")
        }
        XCTAssertTrue(body.contains("exactly as they were"))
    }

    func test_partial_statesNoCountAtAll() {
        // The files it did reach sit behind rooms that still exist, so naming
        // them would be true and would read as loss.
        let body = copy(.partial(AccountDeletionCounts(files: 40))).body
        XCTAssertFalse(body.contains("40"))
    }

    // MARK: - Rule 3: a failure lost nothing

    func test_everyFailureSaysNothingWasHalfDeleted() {
        let failures: [AccountDeletionError] = [
            .serverError(500), .serverError(0), .unauthorized, .unavailable,
            .confirmationMismatch, .decodeFailed("x"), .unexpectedStatus(418),
        ]
        for error in failures {
            let body = copy(.failed(error)).body
            XCTAssertTrue(
                body.contains("nothing was left half-deleted"),
                "\(error) must say nothing was left half-deleted"
            )
            XCTAssertTrue(body.contains("still here"), "\(error) must say the rooms are still here")
        }
    }

    // MARK: - Shape

    func test_confirmationIsAskedExactlyOnce() {
        // Only the first ask. `partial` and `failed` are both reached BY having
        // confirmed, and re-asking charges the user for a failure that was not
        // theirs.
        XCTAssertTrue(copy(.confirm).requiresConfirmation)
        for state in allStates where !isConfirm(state) {
            XCTAssertFalse(
                copy(state).requiresConfirmation,
                "only the first ask confirms; \(state) must not"
            )
        }
    }

    func test_onlyTheRunningStateOffersNoAction() {
        XCTAssertNil(copy(.working).primary)
        for state in allStates where !isWorking(state) {
            XCTAssertNotNil(copy(state).primary, "\(state) must offer an action")
        }
    }

    func test_theWayOutIsClosedExactlyWhileItWouldLie() {
        // Running: the request is on the wire and closing would not stop it.
        XCTAssertFalse(copy(.working).dismissable)
        // Done: there is nothing to go back to.
        XCTAssertFalse(copy(.done(AccountDeletionCounts(), .notLinked)).dismissable)
        XCTAssertTrue(copy(.confirm).dismissable)
        XCTAssertTrue(copy(.partial(AccountDeletionCounts())).dismissable)
        XCTAssertTrue(copy(.failed(.unavailable)).dismissable)
    }

    func test_everyStateSaysSomething() {
        for state in allStates {
            let c = copy(state)
            XCTAssertFalse(c.title.isEmpty, "\(state) has no title")
            XCTAssertFalse(c.body.isEmpty, "\(state) has no body")
            XCTAssertFalse(c.closing.isEmpty, "\(state) has no closing line")
        }
    }

    func test_closingIsAlwaysOneLine() {
        // RSActions holds the primary at one height by giving the closing slot
        // exactly one line. A newline here moves the button.
        for state in allStates {
            XCTAssertFalse(
                copy(state).closing.contains("\n"),
                "\(state)'s closing line must be one line"
            )
        }
    }

    func test_confirmSaysItCannotBeUndone() {
        let body = copy(.confirm).body.lowercased()
        XCTAssertTrue(body.contains("undo"))
        XCTAssertTrue(body.contains("no copy"))
    }

    // MARK: - Helpers

    private func isConfirm(_ s: DeleteAccountState) -> Bool {
        if case .confirm = s { return true }
        return false
    }

    private func isWorking(_ s: DeleteAccountState) -> Bool {
        if case .working = s { return true }
        return false
    }
}
