/// The two sign-in moments (design spec §8): the "why sign in" invitation and the
/// account-conflict choice.
///
/// WhySignInSheet — a bottom sheet triggered at natural moments (after a first
/// room, before handoff on a shared computer). The emotional argument is
/// loss-prevention, spoken by the guest; the checklist reassures that linking
/// never wipes existing rooms.
///
/// AccountConflictView — the Apple ID already owns another account. Framed as
/// choosing between two *lives*, never a destructive merge. No option silently
/// deletes rooms; the not-chosen set is held, recoverable, and the choice is
/// explicit (decision 0051/0064 — `switchToExistingAccount` is the app's only
/// deliberate UID-change path).

import SwiftUI

struct WhySignInSheet: View {
    // Required — no sample default. This count is asserted to the user ("You've got
    // N rooms with me already"); a default would ship an invented number the moment
    // this sheet is wired.
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

struct AccountConflictView: View {
    // Required — no sample defaults. Real counts must come from the caller; a
    // default would ship an invented room count the moment this is wired.
    var existingRooms: Int
    var thisPhoneRooms: Int
    var onSwitch: () -> Void = {}
    var onKeep: () -> Void = {}

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            Text("This Apple ID already has a home")
                .font(RSFont.ui(.title3, weight: .semibold))
                .foregroundStyle(Color.rsInk)
                .fixedSize(horizontal: false, vertical: true)
                .padding(.top, 8)

            GuestLine("You've used this Apple ID before — it has \(existingRooms) rooms of its own. Which life should this phone join?",
                      size: 15)
                .padding(.top, 10)

            optionCard(
                title: "Switch to my existing account",
                // NO retention promise: AuthManager.switchToExistingAccount is explicit that
                // rooms under the old anonymous UID stop being reachable from this
                // install, there is no anon-credential recovery, and scenes have no TTL.
                // This is the sentence the destructive choice leans on — it must be true.
                subtitle: "Keep the \(existingRooms) rooms there · the \(thisPhoneRooms) scanned on this phone won't be reachable from this install afterward",
                emphasized: true,
                action: onSwitch
            )
            .padding(.top, 18)

            optionCard(
                title: "Keep the \(thisPhoneRooms) rooms on this phone",
                subtitle: "Sign in later with a different Apple ID",
                emphasized: false,
                action: onKeep
            )
            .padding(.top, 10)

            Spacer()
        }
        .padding(.horizontal, 26)
        .padding(.top, 30)
        .frame(maxWidth: .infinity, alignment: .topLeading)
        .modifier(RSScrollableScreen(background: nil))
    }

    private func optionCard(title: String, subtitle: String, emphasized: Bool, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            VStack(alignment: .leading, spacing: 3) {
                Text(title)
                    .font(RSFont.ui(.callout, weight: .semibold))
                    .fixedSize(horizontal: false, vertical: true)
                    .foregroundStyle(emphasized ? Color.rsAction : Color.rsInk)
                Text(subtitle)
                    .font(RSFont.ui(.footnote))
                    .foregroundStyle(Color.rsInkMuted)
                    .multilineTextAlignment(.leading)
                    .fixedSize(horizontal: false, vertical: true)
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(13)
            .background(Color.rsSurface, in: RoundedRectangle(cornerRadius: 12, style: .continuous))
            .overlay(
                RoundedRectangle(cornerRadius: 12, style: .continuous)
                    .stroke(emphasized ? Color.rsAction : Color.rsInk.opacity(0.25), lineWidth: 1.5)
            )
        }
    }
}

#Preview("Why sign in") {
    Color.rsBackground.ignoresSafeArea()
        .sheet(isPresented: .constant(true)) {
            WhySignInSheet(roomCount: 2).presentationDetents([.medium, .large])
        }
}

#Preview("Account conflict") {
    AccountConflictView(existingRooms: 4, thisPhoneRooms: 2)
}
