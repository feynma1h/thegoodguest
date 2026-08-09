/// The sign-in moment (decisions 0051/0118): why this app asks, and the ways in.
///
/// Presented from ProfileView's sign-in row (RootFlowView's profile sheet); also
/// from ContentView's account control on the retained rollback path. Three jobs:
///   - Say honestly why signing in matters (rooms follow the account to the
///     web and to a next phone) — capture itself never requires it.
///   - Run a provider's sign-in flow — Sign in with Apple, or Google (0094
///     made the web read both, 0118 makes iOS link both) — and hand the result
///     to AuthManager's link path, which LINKS to the existing anonymous user
///     (UID unchanged — the 0036/0051 invariant). Apple stays first in the
///     order (App Store guideline 4.8; the web's SignInPanel makes the same
///     choice).
///   - On a link conflict (the identity already owns a different account), put
///     the choice to the user with the real cost spelled out; switching is
///     never silent. The conflict copy names the provider that was attempted.
///
/// A user linked with ONE provider is offered the other: either reaches the
/// same rooms on the web, and carrying both is how a household with one Apple
/// ID and one Google account stays whole.
///
/// The footer shows the full device identity UID in mono (machine data): the
/// visible proof, before and after linking, that sign-in kept the same
/// identity.
///
/// Read by: ProfileView (sheet presentation); ContentView on the rollback path.

import AuthenticationServices
import FirebaseAuth
import FirebaseCore
import GoogleSignIn
import GoogleSignInSwift
import SwiftUI

struct SignInSheet: View {

    @ObservedObject private var auth = AuthManager.shared
    @Environment(\.dismiss) private var dismiss

    /// Raw nonce for the in-flight Apple request; its SHA-256 went to Apple.
    @State private var currentRawNonce: String?
    @State private var isWorking = false
    @State private var failureMessage: String?

    /// Non-nil while the conflict choice is up: the single-use credential
    /// that signs in to the account already owning the attempted identity.
    @State private var conflictCredential: AuthCredential?
    /// What the conflict alerts call the identity ("Apple ID" / "Google
    /// account") — set by whichever provider flow hit the conflict.
    @State private var conflictProviderNoun = "Apple ID"
    @State private var showConflictChoice = false
    @State private var showConflictDeadEnd = false

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            Text(auth.isLinked ? "Signed in" : "Sign in")
                .font(.title2.weight(.semibold))
                .padding(.top, 28)

            if auth.isLinked {
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
        .alert(
            Text("This \(conflictProviderNoun) already has a home"),
            isPresented: $showConflictChoice
        ) {
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
        .alert(
            Text("This \(conflictProviderNoun) already has a home"),
            isPresented: $showConflictDeadEnd
        ) {
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
                follow your account instead — to the web app, and to your \
                next phone. Capturing never requires it.
                """)
                .font(.subheadline)
                .foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)

            appleButton

            googleButton

            if let failureMessage {
                Text(failureMessage)
                    .font(.caption)
                    .foregroundStyle(.red)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
    }

    private var linkedBody: some View {
        VStack(alignment: .leading, spacing: 12) {
            if auth.isAppleLinked {
                providerRow(name: "Apple ID", email: auth.appleEmail)
            }
            if auth.isGoogleLinked {
                providerRow(name: "Google account", email: auth.googleEmail)
            }

            // Offer the missing provider: either one reaches the same rooms
            // on the web, and both can live on this one identity.
            if !auth.isAppleLinked || !auth.isGoogleLinked {
                Text("You can also link \(auth.isAppleLinked ? "Google" : "your Apple ID") — either sign-in opens your rooms on the web.")
                    .font(.footnote)
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
                    .padding(.top, 8)

                if auth.isAppleLinked {
                    googleButton
                } else {
                    appleButton
                }

                if let failureMessage {
                    Text(failureMessage)
                        .font(.caption)
                        .foregroundStyle(.red)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
        }
    }

    private func providerRow(name: String, email: String?) -> some View {
        Label {
            VStack(alignment: .leading, spacing: 2) {
                Text("Rooms on this phone follow your \(name).")
                if let email {
                    Text(email)
                        .font(.caption.monospaced())
                        .foregroundStyle(.secondary)
                }
            }
        } icon: {
            Image(systemName: "checkmark.circle.fill")
                .foregroundStyle(.green)
        }
        .font(.subheadline)
    }

    // MARK: - Provider buttons

    private var appleButton: some View {
        SignInWithAppleButton(.signIn) { request in
            let rawNonce = SignInWithApple.randomNonceString()
            currentRawNonce = rawNonce
            request.requestedScopes = [.fullName, .email]
            request.nonce = SignInWithApple.sha256Hex(rawNonce)
        } onCompletion: { result in
            handleAppleAuthorization(result)
        }
        .signInWithAppleButtonStyle(.black)
        .frame(height: 48)
        .disabled(isWorking)
        .overlay {
            if isWorking { ProgressView() }
        }
    }

    private var googleButton: some View {
        // The SDK's own button (branding-compliant), like Apple's native
        // button above — identity buttons are not re-drawn in-house.
        GoogleSignInButton(
            scheme: .light,
            style: .wide,
            state: isWorking ? .disabled : .normal
        ) {
            startGoogleSignIn()
        }
        .frame(height: 44)
    }

    // MARK: - Apple flow

    private func handleAppleAuthorization(_ result: Result<ASAuthorization, Error>) {
        switch result {
        case .failure(let error):
            if case .canceled = AccountLinking.classifyLinkError(error) { return }
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
                handleLinkOutcome(outcome, providerNoun: "Apple ID")
            }
        }
    }

    // MARK: - Google flow

    private func startGoogleSignIn() {
        // Preflight instead of crashing: GIDSignIn raises an NSException when
        // the redirect scheme is unregistered, and has no configuration when
        // the local GoogleService-Info.plist predates the iOS OAuth client.
        switch SignInWithGoogle.preflight(
            clientID: FirebaseApp.app()?.options.clientID,
            registeredURLSchemes: SignInWithGoogle.registeredURLSchemes(in: .main))
        {
        case .missingClientID:
            failureMessage = """
                Google sign-in isn’t configured in this build — the app’s \
                GoogleService-Info.plist has no Google client. Re-download it \
                from the Firebase console.
                """
            return
        case .schemeNotRegistered:
            failureMessage = """
                This build can’t receive Google’s redirect (URL scheme not \
                registered). Sign-in was not started.
                """
            return
        case .ready:
            break
        }
        guard let clientID = FirebaseApp.app()?.options.clientID,
              let presenter = Self.topPresentingViewController()
        else {
            failureMessage = "Couldn’t start Google sign-in. Try again."
            return
        }

        GIDSignIn.sharedInstance.configuration = GIDConfiguration(clientID: clientID)
        isWorking = true
        failureMessage = nil
        Task {
            do {
                let result = try await GIDSignIn.sharedInstance
                    .signIn(withPresenting: presenter)
                guard let idToken = result.user.idToken?.tokenString else {
                    isWorking = false
                    failureMessage = "Google returned an unusable credential. Try again."
                    return
                }
                let outcome = await auth.linkGoogleAccount(
                    idToken: idToken,
                    accessToken: result.user.accessToken.tokenString)
                isWorking = false
                handleLinkOutcome(outcome, providerNoun: "Google account")
            } catch {
                isWorking = false
                if case .canceled = AccountLinking.classifyLinkError(error) { return }
                failureMessage = "Sign-in didn’t complete. Try again."
            }
        }
    }

    /// Where GIDSignIn presents its browser session from: the top of the
    /// presented-view-controller chain (this sheet, when it is up).
    private static func topPresentingViewController() -> UIViewController? {
        let windows = UIApplication.shared.connectedScenes
            .compactMap { $0 as? UIWindowScene }
            .flatMap(\.windows)
        var top = (windows.first { $0.isKeyWindow } ?? windows.first)?.rootViewController
        while let presented = top?.presentedViewController { top = presented }
        return top
    }

    // MARK: - Shared outcome handling

    private func handleLinkOutcome(_ outcome: AuthManager.LinkResult, providerNoun: String) {
        switch outcome {
        case .linked:
            dismiss()
        case .conflict(let existing):
            conflictProviderNoun = providerNoun
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
