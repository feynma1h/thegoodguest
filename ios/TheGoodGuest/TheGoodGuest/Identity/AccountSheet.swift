/// Account: one native sheet behind home's account button.
///
/// It replaces three surfaces (2026-11-10): the You screen, the sign-in sheet
/// it opened, and Why sign in, which nothing presented (0237). Signing in,
/// what this iPhone is, the privacy policy and deleting everything now live in
/// one place, and the linked state is reachable — the old profile hid its only
/// way into the sign-in sheet once signed in, so "also link Google" could not
/// be reached.
///
/// THE LINKING LOGIC IS UNCHANGED from the sign-in sheet: Apple and Google link
/// in place (the UID is asserted unchanged), and a conflict is an explicit
/// switch-or-keep choice in a system alert (0216). There is still no sign-out
/// on the phone; deletion is the account operation it offers (5.1.1(v)).
///
/// Read by: RootFlowView (presented as a sheet), the gallery.

import AuthenticationServices
import FirebaseAuth
import FirebaseCore
import GoogleSignIn
import SwiftUI

struct AccountSheet: View {
    @ObservedObject private var auth = AuthManager.shared
    @Environment(\.dismiss) private var dismiss

    /// The gallery's seams: render one state without an identity.
    var uidOverride: String?? = nil
    var linkedOverride: Bool? = nil
    var initialFailure: String? = nil
    var showsConflict = false

    @State private var currentRawNonce: String?
    @State private var isWorking = false
    @State private var failureMessage: String?
    @State private var conflictCredential: AuthCredential?
    @State private var conflictProviderNoun = "Apple ID"
    @State private var showConflictChoice = false
    @State private var showConflictDeadEnd = false
    @State private var copied = false
    @State private var path: [Route] = []

    enum Route: Hashable { case delete }

    private var uid: String? { uidOverride ?? auth.currentUID }
    private var isLinked: Bool { linkedOverride ?? auth.isLinked }

    var body: some View {
        NavigationStack(path: $path) {
            ScrollView {
                VStack(alignment: .leading, spacing: 0) {
                    Text(isLinked ? "Signed in." : "You’re a guest, so far.")
                        .rsFont(.display, size: 30, cap: .display)
                        .tracking(-0.5)
                        .foregroundStyle(Color.rsInk)
                        .fixedSize(horizontal: false, vertical: true)
                        .accessibilityAddTraits(.isHeader)
                        .padding(.horizontal, 4)
                    Text(isLinked
                         ? "Rooms on this iPhone follow your account, to the website and to your next phone."
                         : "Your rooms are tied to this iPhone. Sign in and they follow you, to the website and to your next phone. Scanning never needs it.")
                        .rsFont(.ui, size: 16)
                        .foregroundStyle(Color.rsInk2)
                        .lineSpacing(3)
                        .fixedSize(horizontal: false, vertical: true)
                        .padding(.top, 10)
                        .padding(.horizontal, 4)

                    if isLinked {
                        linkedSection.padding(.top, 20)
                    } else {
                        VStack(spacing: 10) {
                            appleButton
                            googleButton
                        }
                        .padding(.top, 20)
                    }

                    if let failureMessage = failureMessage ?? initialFailure {
                        Label {
                            Text(failureMessage)
                                .rsFont(.ui, size: 15, weight: .semibold)
                                .foregroundStyle(Color.rsInk)
                                .fixedSize(horizontal: false, vertical: true)
                        } icon: {
                            Image(systemName: "exclamationmark.circle")
                                .foregroundStyle(Color.rsInk)
                        }
                        .padding(.top, 12)
                        .padding(.horizontal, 4)
                    }

                    sectionLabel("This iPhone").padding(.top, 26)
                    RSList {
                        idRow
                    }

                    RSList {
                        if let privacy = NetworkConfig.webBaseURL.map({ $0.appendingPathComponent("privacy") }) {
                            Link(destination: privacy) {
                                RSListRow(title: "Privacy policy", trailing: .external)
                            }
                        }
                        NavigationLink(value: Route.delete) {
                            RSListRow(title: "Delete everything", trailing: .chevron)
                        }
                        .buttonStyle(.plain)
                    }
                    .padding(.top, 18)
                    Text("Your account and every room in it. There is no undo.")
                        .rsFont(.ui, size: 13)
                        .foregroundStyle(Color.rsInk2)
                        .fixedSize(horizontal: false, vertical: true)
                        .padding(.top, 8)
                        .padding(.horizontal, 16)

                    Text(versionLine)
                        .rsFont(.ui, size: 13)
                        .foregroundStyle(Color.rsInk2)
                        .frame(maxWidth: .infinity)
                        .padding(.top, 26)
                }
                .padding(.horizontal, 16)
                .padding(.top, 8)
                .padding(.bottom, 24)
            }
            .background(GroundBackground())
            .navigationTitle("Account")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button { dismiss() } label: { Image(systemName: "xmark") }
                        .accessibilityLabel("Close")
                }
            }
            .navigationDestination(for: Route.self) { _ in
                DeleteAccountView(
                    uid: uid,
                    onClose: { path.removeAll() },
                    // The identity is gone: close the sheet, and home is a
                    // first run, which is what the app now is.
                    onFinished: { dismiss() },
                    isAppleLinked: auth.isAppleLinked
                )
            }
        }
        .interactiveDismissDisabled(isWorking)
        .tint(Color.rsInk)
        .onAppear { if showsConflict { showConflictChoice = true } }
        .alert(Text("This \(conflictProviderNoun) already has a home"), isPresented: $showConflictChoice) {
            Button("Keep this iPhone’s rooms", role: .cancel) { conflictCredential = nil }
            Button("Use that account", role: .destructive) { switchAccounts() }
        } message: {
            Text("It belongs to a different account. Switching signs this iPhone into that one, and the rooms you scanned here before signing in won’t come with you.")
        }
        .alert(Text("This \(conflictProviderNoun) already has a home"), isPresented: $showConflictDeadEnd) {
            Button("OK", role: .cancel) {}
        } message: {
            Text("It belongs to a different account, and switching isn’t possible right now. Try again in a moment.")
        }
    }

    // MARK: Pieces

    private func sectionLabel(_ text: String) -> some View {
        Text(text)
            .rsFont(.ui, size: 13)
            .foregroundStyle(Color.rsInk2)
            .padding(.horizontal, 16)
            .padding(.bottom, 8)
    }

    private var idRow: some View {
        HStack(spacing: 12) {
            Text("Account ID")
                .rsFont(.ui, size: 17)
                .foregroundStyle(Color.rsInk)
            Spacer(minLength: 8)
            if let uid {
                Text(Self.shortened(uid))
                    .rsFont(.ui, size: 15)
                    .monospacedDigit()
                    .foregroundStyle(Color.rsInk2)
                    .lineLimit(1)
                Button {
                    UIPasteboard.general.string = uid
                    RSHaptics.fire(.scanTapped)
                    copied = true
                } label: {
                    Image(systemName: copied ? "checkmark" : "doc.on.doc")
                        .foregroundStyle(Color.rsInk)
                        .frame(width: 32, height: 32)
                }
                .accessibilityLabel(copied ? "Copied" : "Copy your account ID")
            } else {
                Text("Not ready yet")
                    .rsFont(.ui, size: 15)
                    .foregroundStyle(Color.rsInk2)
            }
        }
        .padding(.horizontal, 16)
        .frame(minHeight: 52)
        .accessibilityElement(children: .contain)
    }

    @ViewBuilder
    private var linkedSection: some View {
        RSList {
            if auth.isAppleLinked || linkedOverride == true {
                RSListRow(title: "Apple ID", value: auth.appleEmail ?? "Linked", trailing: .check)
            }
            if auth.isGoogleLinked {
                RSListRow(title: "Google account", value: auth.googleEmail ?? "Linked", trailing: .check)
            }
        }
        if !(auth.isAppleLinked && auth.isGoogleLinked) {
            Text("You can also link \(auth.isGoogleLinked ? "your Apple ID" : "Google"). Either sign-in opens your rooms on the website.")
                .rsFont(.ui, size: 13)
                .foregroundStyle(Color.rsInk2)
                .fixedSize(horizontal: false, vertical: true)
                .padding(.top, 10)
                .padding(.horizontal, 16)
            Group {
                if auth.isGoogleLinked { appleButton } else { googleButton }
            }
            .padding(.top, 10)
        }
        Text("To sign out, use the website.")
            .rsFont(.ui, size: 13)
            .foregroundStyle(Color.rsInk2)
            .padding(.top, 10)
            .padding(.horizontal, 16)
    }

    private var versionLine: String {
        let info = Bundle.main.infoDictionary
        let version = info?["CFBundleShortVersionString"] as? String ?? "1.0"
        let build = info?["CFBundleVersion"] as? String ?? "1"
        return "\(RSBrand.name) \(version) (\(build))"
    }

    /// The ID's ends, which is what a person reads back to support; the copy
    /// button carries the whole of it.
    static func shortened(_ uid: String) -> String {
        guard uid.count > 12 else { return uid }
        return "\(uid.prefix(4))…\(uid.suffix(4))"
    }

    // MARK: Sign-in (unchanged from the sign-in sheet)

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
        .frame(height: GoogleSignInPill.height)
        .clipShape(Capsule())
        .disabled(isWorking)
        .overlay { if isWorking { ProgressView().tint(.white) } }
    }

    private var googleButton: some View {
        GoogleSignInPill(disabled: isWorking) {
            startGoogleSignIn()
        }
    }

    private func handleAppleAuthorization(_ result: Result<ASAuthorization, Error>) {
        switch result {
        case .failure(let error):
            if case .canceled = AccountLinking.classifyLinkError(error) { return }
            failureMessage = "Sign-in didn’t finish. Nothing changed on this iPhone; try again."
        case .success(let authorization):
            guard
                let appleCredential = authorization.credential as? ASAuthorizationAppleIDCredential,
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

    private func startGoogleSignIn() {
        switch SignInWithGoogle.preflight(
            clientID: FirebaseApp.app()?.options.clientID,
            registeredURLSchemes: SignInWithGoogle.registeredURLSchemes(in: .main))
        {
        case .missingClientID:
            failureMessage = "Google sign-in isn’t set up in this build. Sign-in was not started."
            return
        case .schemeNotRegistered:
            failureMessage = "This build can’t receive Google’s reply. Sign-in was not started."
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
                let result = try await GIDSignIn.sharedInstance.signIn(withPresenting: presenter)
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
                failureMessage = "Sign-in didn’t finish. Nothing changed on this iPhone; try again."
            }
        }
    }

    private static func topPresentingViewController() -> UIViewController? {
        let windows = UIApplication.shared.connectedScenes
            .compactMap { $0 as? UIWindowScene }
            .flatMap(\.windows)
        var top = (windows.first { $0.isKeyWindow } ?? windows.first)?.rootViewController
        while let presented = top?.presentedViewController { top = presented }
        return top
    }

    private func handleLinkOutcome(_ outcome: AuthManager.LinkResult, providerNoun: String) {
        switch outcome {
        case .linked:
            failureMessage = nil
        case .conflict(let existing):
            conflictProviderNoun = providerNoun
            conflictCredential = existing
            if existing != nil { showConflictChoice = true } else { showConflictDeadEnd = true }
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
            } catch {
                isWorking = false
                failureMessage = "Switching didn’t finish — this iPhone is unchanged. Try again."
            }
        }
    }
}

// MARK: - A grouped list, in the language

/// White rows on the ground, rounded as a group, hairlines between — the
/// system's inset-grouped list, drawn in the app's own type.
struct RSList<Content: View>: View {
    @ViewBuilder var content: Content

    var body: some View {
        VStack(spacing: 0) {
            Group(subviews: content) { rows in
                ForEach(Array(rows.enumerated()), id: \.offset) { index, row in
                    if index > 0 {
                        Rectangle().fill(Color.rsHairline).frame(height: 1).padding(.leading, 16)
                    }
                    row
                }
            }
        }
        .background(Color.rsSurface, in: RoundedRectangle(cornerRadius: 18, style: .continuous))
    }
}

struct RSListRow: View {
    enum Trailing { case none, chevron, external, check }

    let title: String
    var value: String? = nil
    var trailing: Trailing = .none

    var body: some View {
        HStack(spacing: 12) {
            Text(title)
                .rsFont(.ui, size: 17)
                .foregroundStyle(Color.rsInk)
            Spacer(minLength: 8)
            if let value {
                Text(value)
                    .rsFont(.ui, size: 15)
                    .foregroundStyle(Color.rsInk2)
                    .lineLimit(1)
                    .truncationMode(.middle)
            }
            switch trailing {
            case .none: EmptyView()
            case .chevron:
                Image(systemName: "chevron.right").font(.system(size: 14, weight: .semibold)).foregroundStyle(Color.rsInk3)
            case .external:
                Image(systemName: "arrow.up.right").font(.system(size: 14, weight: .semibold)).foregroundStyle(Color.rsInk3)
            case .check:
                Image(systemName: "checkmark").font(.system(size: 14, weight: .semibold)).foregroundStyle(Color.rsInk)
            }
        }
        .padding(.horizontal, 16)
        .frame(minHeight: 52)
        .contentShape(Rectangle())
    }
}
