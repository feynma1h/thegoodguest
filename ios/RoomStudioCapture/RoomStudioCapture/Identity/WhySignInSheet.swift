/// The "why sign in" invitation (design spec §8): a bottom sheet triggered at
/// natural moments (after a first room, before handoff on a shared computer).
/// The emotional argument is loss-prevention, spoken by the guest; the checklist
/// reassures that linking never wipes existing rooms.
///
/// `roomCount` is required and carries no sample default: the sheet asserts it
/// to the user ("You've got N rooms with me already"), so a default would ship
/// an invented number the moment this is wired. Its honest source is GET
/// /scenes, by way of RoomsStore — and `WhySignInInvitation` below is what
/// guarantees the sheet is never presented without one. A count that is merely
/// unknown is not zero, and this sheet has no form that can say "some rooms".
///
/// §8's OTHER screen, the account-conflict choice, is deliberately not here
/// (decision 0216). It asked for a count of the rooms held by the account being
/// switched to, and that number cannot be obtained without first becoming that
/// account — which is the exact act it existed to ask permission for. The
/// conflict is put to the user by SignInSheet, with the real cost stated and
/// nothing counted (decision 0064).
///
/// Read by: RootFlowView, on the first return home with a room and no linked
/// identity.

import SwiftUI

struct WhySignInSheet: View {
    // Required — no sample default. This count is asserted to the user ("You've
    // got N rooms with me already"); a default would ship an invented number the
    // moment this sheet is wired.
    var roomCount: Int
    var onSignIn: () -> Void = {}
    var onNotNow: () -> Void = {}

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            Image(systemName: "shield.lefthalf.filled")
                .font(.system(size: 20))
                .foregroundStyle(Color.rsGoldInk)
                .frame(width: 40, height: 40)
                .background(Color.rsGold.opacity(0.22), in: RoundedRectangle(cornerRadius: 11, style: .continuous))

            Text("Keep your rooms, wherever you are.")
                .rsFont(.display, size: 23)
                .foregroundStyle(Color.rsInk)
                .fixedSize(horizontal: false, vertical: true)
                .padding(.top, 16)

            GuestLine("You've got \(roomWord) with me already. Sign in and they come with you — to your desk, to a new phone, to next year. Nothing you've built is left behind. That's the whole reason.",
                      size: 15)
                .padding(.top, 12)

            VStack(alignment: .leading, spacing: 9) {
                checklistRow("Your \(roomCount) rooms stay exactly as they are")
                checklistRow("The same you, on the web and the phone")
                checklistRow("No email, no password to remember")
            }
            .padding(13)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(Color.rsInk.opacity(0.04), in: RoundedRectangle(cornerRadius: 12, style: .continuous))
            .padding(.top, 16)

        }
        .padding(.horizontal, RSScreen.horizontal)
        .padding(.top, RSScreen.contentGap)
        .frame(maxWidth: .infinity, alignment: .topLeading)
        .modifier(RSScrollableScreen(background: Color.rsSurface))
        .safeAreaInset(edge: .bottom) {
            // Deliberately NOT a SignInWithAppleButton here. A local one would
            // need its own nonce/scopes and Result handling; the earlier stub
            // set no nonce, discarded the Result, and called onSignIn() on
            // cancel and failure alike. Identity has ONE real implementation —
            // SignInSheet — so this invitation hands off to it rather than
            // growing a second, weaker path.
            RSActions {
                Button(action: onSignIn) {
                    Text("Sign in to keep your rooms")
                        .font(RSFont.ui(.headline, weight: .semibold))
                        .foregroundStyle(Color.rsSurface)
                        .frame(maxWidth: .infinity)
                        .padding(.vertical, 17)
                        .background(Color.rsInk, in: RoundedRectangle(cornerRadius: 16, style: .continuous))
                }
            } closing: {
                Button(action: onNotNow) { Text("Not now") }
                    .buttonStyle(RSActionFootnoteStyle())
            }
            .padding(.horizontal, RSScreen.horizontal)
        }
    }

    private var roomWord: String {
        roomCount == 1 ? "one room" : "\(roomCount) rooms"
    }

    private func checklistRow(_ text: String) -> some View {
        HStack(spacing: 9) {
            Image(systemName: "checkmark")
                .font(.system(size: 12, weight: .bold))
                .foregroundStyle(Color.rsAffirm)
            Text(text)
                .font(RSFont.ui(.subheadline))
                .foregroundStyle(Color.rsInk)
        }
    }
}

#Preview("Why sign in") {
    Color.rsBackground.ignoresSafeArea()
        .sheet(isPresented: .constant(true)) {
            WhySignInSheet(roomCount: 2).presentationDetents([.medium, .large])
        }
}


// MARK: - The presented form

/// WhySignInSheet with its hand-off wired.
///
/// The sheet itself deliberately owns no identity code — "Identity has ONE real
/// implementation" is the note in its body, and SignInSheet is it. This wrapper
/// is the seam that keeps that true: the invitation argues, SignInSheet acts.
/// Nested presentation is the same shape ProfileView already uses for the same
/// hand-off, and it avoids the dismiss-then-present race that sequencing two
/// sheets off one parent produces.
struct WhySignInInvitationSheet: View {
    let roomCount: Int
    var onDismiss: () -> Void = {}

    @State private var showSignIn = false

    var body: some View {
        WhySignInSheet(
            roomCount: roomCount,
            onSignIn: { showSignIn = true },
            onNotNow: onDismiss
        )
        .sheet(isPresented: $showSignIn) { SignInSheet() }
    }
}

// MARK: - When to offer it

/// The trigger, as a table.
///
/// The design places this "at natural moments (after a first room…)", which in
/// this flow is the first time the user lands back on home with a room to lose.
/// Three things gate it, and the third is the one worth stating: the sheet's
/// entire argument is a count, so it must not be offered while the count is
/// unknown. `.failed` and `.loading` are both "unknown" and neither is zero —
/// the invitation simply waits for the next launch rather than guessing.
///
/// Offered once, ever. It is an invitation, not a nag, and ProfileView carries
/// the same action permanently for anyone who says "Not now".
nonisolated enum WhySignInInvitation {

    static func shouldPresent(rooms: RoomsLoadState, isLinked: Bool, alreadyOffered: Bool) -> Bool {
        guard !isLinked, !alreadyOffered else { return false }
        guard let count = rooms.knownCount else { return false }
        return count >= 1
    }
}

/// The "offered once" memory.
///
/// UserDefaults rather than anything derived: there is no server-side record of
/// having been asked, and re-deriving it from the room count would re-offer the
/// sheet on every launch for anyone who declined.
@MainActor
enum WhySignInOffer {
    static let defaultsKey = "roomstudio.whySignIn.offered"

    static func hasOffered(_ defaults: UserDefaults = .standard) -> Bool {
        defaults.bool(forKey: defaultsKey)
    }

    static func markOffered(_ defaults: UserDefaults = .standard) {
        defaults.set(true, forKey: defaultsKey)
    }
}
