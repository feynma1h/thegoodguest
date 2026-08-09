/// The sign-in moment (decision 0051): why this app asks, and the one way in.
///
/// Presented from ProfileView's sign-in row (RootFlowView's profile sheet); also
/// from ContentView's account control on the retained rollback path. Three jobs:
///   - Say honestly why signing in matters (rooms follow the account to the
///     web and to a next phone) — capture itself never requires it.
///   - Run the Sign in with Apple flow and hand the result to
///     AuthManager.linkAppleAccount, which LINKS to the existing anonymous
///     user (UID unchanged — the 0036/0051 invariant).
///   - On a link conflict (Apple ID already owns a different account), put
///     the choice to the user with the real cost spelled out; switching is
///     never silent.
///
/// The footer shows the full device identity UID in mono (machine data): the
/// visible proof, before and after linking, that sign-in kept the same
/// identity.
///
/// Read by: ProfileView (sheet presentation); ContentView on the rollback path.

import AuthenticationServices
import FirebaseAuth
import SwiftUI

struct SignInSheet: View {

    @ObservedObject private var auth = AuthManager.shared
    @Environment(\.dismiss) private var dismiss

    /// Raw nonce for the in-flight Apple request; its SHA-256 went to Apple.
    @State private var currentRawNonce: String?
    @State private var isWorking = false
    @State private var failureMessage: String?

    /// Non-nil while the conflict choice is up: the single-use credential
    /// that signs in to the account already owning this Apple ID.
    @State private var conflictCredential: AuthCredential?
    @State private var showConflictChoice = false
    @State private var showConflictDeadEnd = false

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            Text(auth.isAppleLinked ? "Signed in" : "Sign in")
                .font(.title2.weight(.semibold))
                .padding(.top, 28)

            if auth.isAppleLinked {
                linkedBody
            } else {
                signInBody
            }

            Spacer()

            // The verification affordance: identity is the UID, shown plainly.
            VStack(alignment: .leading, spacing: 4) {
                Text("device identity")
                    .font(.caption2)
                    .foregroundStyle(.tertiary)
                Text(auth.uid ?? "not signed in yet")
                    .font(.caption2.monospaced())
                    .foregroundStyle(.secondary)
                    .textSelection(.enabled)
            }
            .padding(.bottom, 20)
        }
        .padding(.horizontal, 24)
        .frame(maxWidth: .infinity, alignment: .leading)
        .presentationDetents([.medium])
        .interactiveDismissDisabled(isWorking)
        .alert("This Apple ID already has a home", isPresented: $showConflictChoice) {
            Button("Use that account", role: .destructive) {
                switchAccounts()
            }
            Button("Keep this phone’s rooms", role: .cancel) {
                conflictCredential = nil
            }
        } message: {
            Text("""
                It’s already attached to a different account. Switching signs \
                this phone into that account — rooms scanned on this phone \
                before signing in won’t appear there.
                """)
        }
        .alert("This Apple ID already has a home", isPresented: $showConflictDeadEnd) {
            Button("OK", role: .cancel) {}
        } message: {
            Text("""
                It’s already attached to a different account, and switching \
                isn’t possible right now. Try again in a moment.
                """)
        }
    }

    // MARK: - States

    private var signInBody: some View {
        VStack(alignment: .leading, spacing: 16) {
            Text("""
                Your rooms live with this phone right now. Sign in and they \
                follow your Apple ID instead — to the web app, and to your \
                next phone. Capturing never requires it.
                """)
                .font(.subheadline)
                .foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)

            SignInWithAppleButton(.signIn) { request in
                let rawNonce = SignInWithApple.randomNonceString()
                currentRawNonce = rawNonce
                request.requestedScopes = [.fullName, .email]
                request.nonce = SignInWithApple.sha256Hex(rawNonce)
            } onCompletion: { result in
                handleAuthorization(result)
            }
            .signInWithAppleButtonStyle(.black)
            .frame(height: 48)
            .disabled(isWorking)
            .overlay {
                if isWorking { ProgressView() }
            }

            if let failureMessage {
                Text(failureMessage)
                    .font(.caption)
                    .foregroundStyle(.red)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
    }

    private var linkedBody: some View {
        VStack(alignment: .leading, spacing: 8) {
            Label {
                Text("Rooms on this phone follow your Apple ID.")
            } icon: {
                Image(systemName: "checkmark.circle.fill")
                    .foregroundStyle(.green)
            }
            .font(.subheadline)

            if let email = auth.appleEmail {
                Text(email)
                    .font(.caption.monospaced())
                    .foregroundStyle(.secondary)
            }
        }
    }

    // MARK: - Flow

    private func handleAuthorization(_ result: Result<ASAuthorization, Error>) {
        switch result {
        case .failure(let error):
            if case .canceled = SignInWithApple.classifyLinkError(error) { return }
            failureMessage = "Sign-in didn’t complete. Try again."
        case .success(let authorization):
            guard
                let appleCredential = authorization.credential
                    as? ASAuthorizationAppleIDCredential,
                let tokenData = appleCredential.identityToken,
                let idTokenString = String(data: tokenData, encoding: .utf8),
                let rawNonce = currentRawNonce
            else {
                failureMessage = "Apple returned an unusable credential. Try again."
                return
            }
            isWorking = true
            failureMessage = nil
            Task {
                let outcome = await auth.linkAppleAccount(
                    idTokenString: idTokenString,
                    rawNonce: rawNonce,
                    fullName: appleCredential.fullName)
                isWorking = false
                currentRawNonce = nil
                switch outcome {
                case .linked:
                    dismiss()
                case .conflict(let existing):
                    conflictCredential = existing
                    if existing != nil {
                        showConflictChoice = true
                    } else {
                        showConflictDeadEnd = true
                    }
                case .canceled:
                    break
                case .failed(let message):
                    failureMessage = message
                }
            }
        }
    }

    private func switchAccounts() {
        guard let credential = conflictCredential else { return }
        conflictCredential = nil
        isWorking = true
        Task {
            do {
                try await auth.switchToExistingAccount(credential)
                isWorking = false
                dismiss()
            } catch {
                isWorking = false
                failureMessage =
                    "Switching didn’t complete — this phone is unchanged. Try again."
            }
        }
    }
}

#Preview {
    SignInSheet()
}
