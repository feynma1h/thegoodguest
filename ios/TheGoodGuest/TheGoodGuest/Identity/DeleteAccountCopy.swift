/// What the deletion screen says, in each state it can be in, as a pure
/// function.
///
/// Same discipline as `HomeLine`, `Contents` and `SurfacePlacement`: the words
/// are a table so they can be read side by side and pinned as one, rather than
/// spread through a SwiftUI body where a state's copy is only visible to
/// whoever renders that state.
///
/// THE HONESTY RULES THIS TABLE EXISTS TO HOLD. Deletion is the one screen in
/// the app where a wrong sentence costs something irreversible, and three of
/// its states are easy to word wrongly:
///
///   1. **A count describes the PASS, never the account.** The route is
///      idempotent, so a deletion whose response was lost returns 200 with
///      every count at zero on the retry — the first call did the work. Copy
///      that reads those zeros as "you had nothing" would tell a person their
///      rooms never existed. So counts are stated only when non-zero, and
///      always as what was removed rather than as what was held.
///   2. **`partial` has not deleted anything the user can see.** The route
///      stops before touching Firestore, so the identity is alive and every
///      room is still there. The word "deleted" must not appear in it.
///   3. **A failure lost nothing.** The route documents that it leaves nothing
///      in a partial state. "Some of it went" would be both wrong and the more
///      frightening reading, so each failure says plainly that nothing was
///      touched.
///   4. **"Gone" must not overstate when Apple was not told.** Deletion
///      proceeds even when the Sign in with Apple token could not be revoked —
///      that is TN3194's instruction, not our leniency — but the account then
///      still appears under the person's Apple ID. Saying only "gone" would be
///      true of our systems and false of what they can see on their phone, so
///      that one outcome carries the manual step and the others do not.
///
/// Read by: DeleteAccountView. Pinned by: DeleteAccountCopyTests.

import Foundation

// MARK: - State

/// Where the deletion screen is. One case per thing the user can be looking at.
nonisolated enum DeleteAccountState: Equatable {
    /// Nothing has been asked for yet.
    case confirm
    /// A pass is running.
    case working
    /// The identity is gone. Counts are what THIS pass removed; the
    /// revocation is what happened to the Apple token, which changes what the
    /// screen must still ask of the user.
    case done(AccountDeletionCounts, AppleRevocation)
    /// A pass stopped early. Nothing the user owns has been removed.
    case partial(AccountDeletionCounts)
    /// A pass failed. Nothing was touched.
    case failed(AccountDeletionError)
}

// MARK: - Rendered copy

/// One screen's worth of words, plus the two things the layout needs to know.
nonisolated struct DeleteAccountCopy: Equatable {
    let title: String
    let body: String
    /// The filled button's label. `nil` renders no primary at all — the state
    /// offers no action, which is only true while a pass is running.
    let primary: String?
    /// True when tapping the primary must be confirmed again before anything
    /// is sent.
    ///
    /// NOT the same as "the action is destructive" — every primary on this
    /// screen except "Start again" destroys something. It is true exactly
    /// once, on the first ask, because that is the only tap a person can make
    /// without having already decided: `partial` and `failed` are both reached
    /// BY having confirmed, and asking a second time would charge someone for
    /// a failure that was not theirs.
    ///
    /// Colour is deliberately not carried here. Rust is the app's primary
    /// button colour rather than an error cue (see RSColor), so inking this
    /// screen's buttons differently would say something the palette does not
    /// mean.
    let requiresConfirmation: Bool
    /// The one closing line under the primary. Never two — see RSActions.
    let closing: String
    /// Whether the header offers a way out. False while a pass is running:
    /// the request is already on the wire and closing the screen would not
    /// stop it, so offering an exit would imply a cancellation that does not
    /// exist.
    let dismissable: Bool
}

// MARK: - The table

nonisolated enum DeleteAccountWording {

    static func copy(for state: DeleteAccountState) -> DeleteAccountCopy {
        switch state {

        case .confirm:
            return DeleteAccountCopy(
                title: "Delete everything",
                body: "This removes your account and every room in it — the scans, "
                    + "what you measured, anything you and I said about them. It "
                    + "reaches the files too, not just the record of them.\n\n"
                    + "There is no copy kept anywhere, and I cannot undo it.",
                primary: "Delete everything",
                requiresConfirmation: true,
                closing: "Not now",
                dismissable: true
            )

        case .working:
            return DeleteAccountCopy(
                title: "Deleting",
                body: "Going through your rooms, then the conversations, then the "
                    + "files underneath them. Each one goes by hand, so this can "
                    + "take a moment on a full house.",
                primary: nil,
                requiresConfirmation: false,
                closing: "Please stay on this screen",
                dismissable: false
            )

        case .done(let counts, let revocation):
            return DeleteAccountCopy(
                title: "Gone",
                body: doneBody(counts, revocation),
                primary: "Start again",
                requiresConfirmation: false,
                closing: "This device is a stranger now",
                dismissable: false
            )

        // The counts are deliberately not read. Rule 2: nothing the user owns
        // has gone, and naming what the pass DID reach would be true while
        // reading as loss — the things it reaches first are files behind rooms
        // that still exist. The outcome carries them for the caller to log;
        // this screen does not state them.
        case .partial:
            return DeleteAccountCopy(
                title: "Not finished",
                body: "Some of the files could not be reached, so I stopped before "
                    + "touching anything else. Your rooms and your account are "
                    + "exactly as they were.\n\n"
                    + "Going again picks up where this stopped.",
                primary: "Keep going",
                requiresConfirmation: false,
                closing: "Nothing has been lost",
                dismissable: true
            )

        case .failed(let error):
            return DeleteAccountCopy(
                title: "That didn't work",
                body: failureBody(error),
                primary: "Try again",
                requiresConfirmation: false,
                closing: "Not now",
                dismissable: true
            )
        }
    }

    // MARK: Bodies

    /// Rule 1 lives here. A pass that removed nothing says so about the PASS,
    /// and says nothing at all about what the account once held.
    private static func doneBody(
        _ counts: AccountDeletionCounts,
        _ revocation: AppleRevocation
    ) -> String {
        let tail = "Your rooms are not archived or held anywhere; they are deleted."
        let opening: String
        if counts.isEmpty {
            opening = "Your account is gone.\n\nThere was nothing left to take by the "
                + "time this ran — either it was already empty, or an earlier "
                + "attempt had finished the work."
        } else {
            opening = "Your account is gone, and so is everything this pass found: "
                + inventory(counts) + "."
        }
        // THE INSTRUCTION COMES SECOND, NOT LAST, and that ordering was found
        // by screenshot rather than by reading. Trailing it after the
        // reassurance put the one ACTIONABLE sentence on this screen below the
        // fold at accessibility sizes, under a pinned "Start again" that was
        // fully visible — so the state whose entire purpose is to deliver that
        // instruction could be dismissed without it ever being seen. It
        // scrolled, which is what made the defect invisible to the layout
        // audit and to reading the table.
        return opening + appleStep(revocation) + "\n\n" + tail
    }

    /// Rule 4. Only `.notRevoked` asks for anything; the other two would be
    /// giving a person a chore that is already done, on a screen whose whole
    /// job is to say the work is finished.
    private static func appleStep(_ revocation: AppleRevocation) -> String {
        guard revocation == .notRevoked else { return "" }
        return "\n\nOne thing I could not finish: this app still appears under "
            + "your Apple ID. To remove it, open Settings, tap your name, then "
            + "Sign in with Apple, and stop using it for The Good Guest."
    }

    /// The removed things, in the order a person would think of them. Only
    /// non-zero lines appear — a "0 conversations" reads as an accusation of
    /// never having talked, and adds nothing.
    static func inventory(_ counts: AccountDeletionCounts) -> String {
        var parts: [String] = []
        func add(_ n: Int, _ one: String, _ many: String) {
            guard n > 0 else { return }
            parts.append(n == 1 ? "1 \(one)" : "\(n) \(many)")
        }
        add(counts.rooms, "room", "rooms")
        add(counts.conversations, "conversation", "conversations")
        add(counts.designSpecs, "arrangement", "arrangements")
        add(counts.files, "file", "files")

        switch parts.count {
        case 0:  return "nothing"
        case 1:  return parts[0]
        default: return parts.dropLast().joined(separator: ", ") + " and " + parts[parts.count - 1]
        }
    }

    /// Rule 3. Every branch says nothing was touched, because the route
    /// guarantees it and because the alternative reading is the frightening one.
    private static func failureBody(_ error: AccountDeletionError) -> String {
        let intact = "Your account and every room in it are still here — nothing "
            + "was left half-deleted."
        switch error {
        case .serverError:
            return "I couldn't reach the desk, or it couldn't finish.\n\n" + intact
        case .unauthorized:
            return "I couldn't prove this device is you, so I didn't ask for "
                + "anything to be removed.\n\n" + intact
        case .unavailable:
            return "Deleting isn't available right now.\n\n" + intact
        case .confirmationMismatch, .decodeFailed, .unexpectedStatus:
            // A client-side or contract fault. The user cannot act on the
            // distinction, so it is not drawn for them — but it is not
            // disguised as a network problem either.
            return "Something didn't line up between this app and the desk.\n\n"
                + intact
        }
    }
}
