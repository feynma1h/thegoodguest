/// The "why sign in" invitation (design spec §8): a bottom sheet triggered at
/// natural moments (after a first room, before handoff on a shared computer).
/// The emotional argument is loss-prevention, spoken by the guest; the checklist
/// reassures that linking never wipes existing rooms.
///
/// `roomCount` is required and carries no sample default: the sheet asserts it
/// to the user ("You've got N rooms with me already"), so a default would ship
/// an invented number the moment this is wired. The honest source is GET
/// /scenes — the same fetch RoomsListView waits on — and until that client
/// exists this sheet has no caller and renders only in its own preview.
///
/// §8's OTHER screen, the account-conflict choice, is deliberately not here
/// (decision 0216). It asked for a count of the rooms held by the account being
/// switched to, and that number cannot be obtained without first becoming that
/// account — which is the exact act it existed to ask permission for. The
/// conflict is put to the user by SignInSheet, with the real cost stated and
/// nothing counted (decision 0064).
///
/// Read by: nothing yet — see above.

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

            // Deliberately NOT a SignInWithAppleButton here. A local one would need
            // its own nonce/scopes and Result handling; the earlier stub set no
            // nonce, discarded the Result, and called onSignIn() on cancel and
            // failure alike. Identity has ONE real implementation — SignInSheet,
            // which links via AuthManager and handles the account conflict — so this
            // invitation hands off to it rather than growing a second, weaker path.
            Button(action: onSignIn) {
                Text("Sign in to keep your rooms")
                    .font(RSFont.ui(.headline, weight: .semibold))
                    .foregroundStyle(Color.rsSurface)
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, 15)
                    .background(Color.rsInk, in: RoundedRectangle(cornerRadius: 13, style: .continuous))
            }
            .padding(.top, 16)

            Button(action: onNotNow) { Text("Not now") }
                .buttonStyle(RSQuietButtonStyle())
                .padding(.top, 4)
        }
        .padding(.horizontal, 26)
        .padding(.top, 26)
        .padding(.bottom, 10)
        .frame(maxWidth: .infinity, alignment: .topLeading)
        .modifier(RSScrollableScreen(background: Color.rsSurface))
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
