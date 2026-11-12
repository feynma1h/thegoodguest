/// Delete everything — the in-app path App Store guideline 5.1.1(v) requires.
///
/// The app creates an account the moment an anonymous UID is linked to Apple or
/// Google, which makes an in-app deletion route mandatory rather than a
/// courtesy. `DELETE /account` has been complete on api-public since decision
/// 0095; this screen is the call site it never had.
///
/// WHY DELETION AND NOT SIGN-OUT. There is deliberately no iOS sign-out
/// (decision 0064: a launch-time `signInIfNeeded` would just mint a fresh
/// anonymous UID, so "signing out" would read as losing every room). Deletion
/// is therefore the only account operation the phone offers, and it has to be
/// unambiguous about what it destroys.
///
/// THE SCREEN IS A STATE MACHINE AND THE WORDS ARE A TABLE. Every string comes
/// from `DeleteAccountWording`, which is pure and pinned — see its header for
/// the four honesty rules that make this screen's copy load-bearing rather
/// than decorative. Nothing here composes a sentence.
///
/// TWO STEPS, IN THIS ORDER. If the account carries an Apple identity, the
/// Sign in with Apple token is revoked BEFORE `DELETE /account` — revocation
/// runs against the live Firebase session, so once the server has removed the
/// identity there is nothing left to revoke with. Guideline 5.1.1(v) wants
/// both halves, and TN3194 is explicit that a revocation which cannot be
/// completed must NOT hold up the deletion: the pass carries on and the done
/// screen asks the person to finish it in Settings. See
/// `AppleAccountRevocation`.
///
/// WHAT HAPPENS AFTER. On `.done` the server has deleted the Firebase identity,
/// so the credential this app is holding belongs to a user that no longer
/// exists. Rather than leave it to be discovered at the next token refresh —
/// which is the UID-churn mechanism of decision 0139, arriving as a mystery —
/// the screen signs out explicitly and hands control back, so the next launch
/// is an honest first run.
///
/// Reached from: AccountSheet. States photographed by: ScreenGallery.

import SwiftUI

struct DeleteAccountView: View {

    /// The caller's uid, echoed to the server as the accident control. Optional
    /// for the same reason AccountSheet's is: nil is a real state (offline first
    /// launch), and with no uid there is nothing to delete and nothing to
    /// confirm — the screen says so rather than sending a request it knows is
    /// malformed.
    var uid: String?

    /// The way out. Not offered while a pass is running.
    var onClose: () -> Void = {}

    /// Called once the identity is gone and the local session has been cleared.
    /// The caller returns the app to its first-run state.
    var onFinished: () -> Void = {}

    /// Whether this identity carries an Apple provider, and so whether there
    /// is a token to revoke. Read once at presentation rather than observed:
    /// the deletion removes the provider, and a live binding would flip
    /// mid-pass and change what the screen thinks it still owes.
    var isAppleLinked: Bool = false

    /// Seam. Production passes the real client; the gallery and the tests pass
    /// a closure, which is what lets every state below be photographed without
    /// a network or an account.
    var perform: (String) async -> Result<AccountDeletionOutcome, AccountDeletionError>
        = { userID in
            do {
                let outcome = try await AccountDeletionClient.shared.delete(
                    userID: userID,
                    tokenProvider: { try await AuthManager.shared.currentIDToken() }
                )
                return .success(outcome)
            } catch let error as AccountDeletionError {
                return .failure(error)
            } catch {
                // AuthManager threw before the request went out — no token, so
                // nothing was asked for. Same user-facing truth as a 401.
                return .failure(.unauthorized)
            }
        }

    /// Revoking the Apple token. Injected so the tests reach every branch
    /// without Apple's sheet — see AppleAccountRevocation for why a failure
    /// here must not stop the deletion.
    var revokeApple: (Bool) async -> AppleRevocation = { linked in
        await AppleAccountRevocation.perform(isAppleLinked: linked)
    }

    /// Signing out after a successful deletion. Injected so the tests can
    /// observe that it happened without touching Firebase.
    var signOut: () -> Void = { AuthManager.shared.signOutAfterDeletion() }

    /// The state the screen opens in. Production always opens on `.confirm`;
    /// the gallery opens directly on the state it is photographing.
    var initialState: DeleteAccountState = .confirm

    @State private var state: DeleteAccountState?
    @State private var askingToConfirm = false

    private var current: DeleteAccountState { state ?? initialState }
    private var copy: DeleteAccountCopy { DeleteAccountWording.copy(for: current) }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 0) {
                RSScreenTitle(copy.title, size: .title)
                Text(copy.body)
                    .rsFont(.ui, size: 16)
                    .foregroundStyle(Color.rsInk2)
                    .lineSpacing(3)
                    .fixedSize(horizontal: false, vertical: true)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(.top, 12)
                if case .working = current {
                    ProgressView()
                        .padding(.top, 24)
                        .frame(maxWidth: .infinity, alignment: .leading)
                }
            }
            .rsScreenContent()
        }
        .background(GroundBackground())
        .navigationBarTitleDisplayMode(.inline)
        // No way back while the request is on the wire: a back button would
        // promise a cancellation that does not exist.
        .navigationBarBackButtonHidden(!copy.dismissable)
        .safeAreaInset(edge: .bottom, spacing: 0) { actions }
        .interactiveDismissDisabled(!copy.dismissable)
        .alert("Delete everything?", isPresented: $askingToConfirm) {
            Button("Delete everything", role: .destructive) { start() }
            Button("Cancel", role: .cancel) {}
        } message: {
            Text("Your rooms and everything in them go for good. This cannot be undone.")
        }
    }

    private var actions: some View {
        RSPinnedBar {
            if let label = copy.primary {
                Button(label) { primaryTapped() }
                    .buttonStyle(RSPrimaryButtonStyle())
                    .disabled(!canAct)
                    .opacity(canAct ? 1 : 0.4)
                if !canAct {
                    // A grey button with no reason reads as broken. These are
                    // the account sheet's words for the same state.
                    RSBarCaption("Your account ID isn't ready yet.")
                }
            }
            closingLine
        }
    }

    /// A way out where there is one, otherwise a caption. The caption is set
    /// at its own height: held at a control's, it lifted the button above it
    /// 14pt higher than the same button on the screen's other states.
    @ViewBuilder
    private var closingLine: some View {
        if copy.dismissable {
            Button(copy.closing) { onClose() }
                .buttonStyle(RSQuietButtonStyle())
        } else {
            RSBarCaption(copy.closing)
        }
    }

    private var canAct: Bool {
        if case .done = current { return true }  // "Start again" needs no uid
        return uid != nil
    }

    // MARK: - Behaviour

    private func primaryTapped() {
        if case .done = current {
            // The identity is already gone and the local session is already
            // cleared — this only dismisses.
            onFinished()
            return
        }
        if copy.requiresConfirmation {
            askingToConfirm = true
        } else {
            start()
        }
    }

    private func start() {
        guard let uid else { return }
        state = .working
        Task {
            // Apple first, and its outcome never gates what follows. A person
            // who cancels Apple's sheet has still asked to be deleted, and
            // TN3194 says to honour that.
            let revocation = await revokeApple(isAppleLinked)
            let result = await perform(uid)
            await MainActor.run {
                switch result {
                case .success(.complete(let counts)):
                    // Order matters: clear the dead credential BEFORE showing
                    // the done state, so the screen cannot be read as finished
                    // while the app still holds a session for a deleted user.
                    signOut()
                    state = .done(counts, revocation)
                case .success(.partial(let counts, _)):
                    state = .partial(counts)
                case .failure(let error):
                    state = .failed(error)
                }
            }
        }
    }
}

#Preview("Confirm") {
    DeleteAccountView(uid: "rs_a4f9-2c7e-91d0", perform: { _ in .failure(.unavailable) })
}

#Preview("Done") {
    DeleteAccountView(
        uid: "rs_a4f9-2c7e-91d0",
        perform: { _ in .failure(.unavailable) },
        signOut: {},
        initialState: .done(
            AccountDeletionCounts(rooms: 6, conversations: 3, files: 214), .revoked)
    )
}
