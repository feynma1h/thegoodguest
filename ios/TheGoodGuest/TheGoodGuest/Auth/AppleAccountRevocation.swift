/// Revoking the Sign in with Apple token when the account is deleted.
///
/// App Review 5.1.1(v) does not stop at deleting the account. An app offering
/// Sign in with Apple must ALSO revoke the user's token through Apple, and
/// Apple checks it at review — see TN3194, "Handling account deletions and
/// revoking tokens for Sign in with Apple". `DELETE /account` calls Firebase
/// Admin's `delete_user`, which removes our record of the user and revokes
/// nothing at Apple: without this the app would keep appearing under the
/// person's Apple ID after they deleted everything.
///
/// WHY A FRESH AUTHORIZATION AND NOT A STORED CODE. The obvious design is to
/// keep the `authorizationCode` from the original sign-in and spend it at
/// deletion. It does not work: Apple's authorization codes are short-lived, so
/// a code captured when someone linked their account months ago is expired
/// before it is ever needed. The documented flow is to re-authorize at the
/// moment of deletion, which is why this presents Apple's sheet rather than
/// reading something out of the Keychain.
///
/// A FAILED REVOCATION MUST NOT BLOCK THE DELETION, and that is Apple's own
/// instruction rather than our leniency: TN3194 says that when no usable code
/// can be obtained, you still fulfil the deletion request and direct the user
/// to revoke access themselves. So every failure path here returns
/// `.notRevoked` instead of throwing, and the deletion screen carries the
/// instruction. Refusing to delete because Apple would not answer would fail
/// the guideline in the other direction, and would hold someone's data
/// hostage to a service neither of us controls.
///
/// ORDER MATTERS: revoke BEFORE `DELETE /account`. Revocation runs against the
/// live Firebase session, so once the server has deleted the identity there is
/// nothing left to revoke with.
///
/// Read by: DeleteAccountView.

import AuthenticationServices
import FirebaseAuth
import Foundation

// MARK: - Outcome

/// What happened to the Apple token. Three outcomes, and the screen says
/// something different for one of them.
nonisolated enum AppleRevocation: Equatable {
    /// No Apple identity on this account, so there is nothing to revoke. The
    /// ordinary case for an anonymous or Google-only user.
    case notLinked
    /// Apple accepted the revocation.
    case revoked
    /// The revocation did not happen — cancelled, offline, or refused. The
    /// deletion still proceeds (TN3194) and the user is told to finish the job
    /// in Settings.
    case notRevoked
}

// MARK: - The Apple round trip

/// Runs one Sign in with Apple authorization purely to obtain a fresh
/// authorization code.
///
/// Deliberately NOT reusing `SignInSheet`'s button flow: that path links an
/// identity and carries conflict handling, and this one must not change who is
/// signed in. It asks Apple for an authorization and reads one field off it.
@MainActor
final class AppleReauthorizer: NSObject,
                               ASAuthorizationControllerDelegate,
                               ASAuthorizationControllerPresentationContextProviding {

    private var continuation: CheckedContinuation<String?, Never>?

    /// The window Apple's sheet attaches to, resolved once at init.
    ///
    /// NON-OPTIONAL, AND THE INIT FAILS INSTEAD. `presentationAnchor` must
    /// return a window, and the old shape returned a freshly constructed one
    /// when no scene could be found. iOS 26 deprecates every way of building a
    /// window without a scene, which is Apple pointing at a real defect rather
    /// than a style preference: a scene-less window cannot present anything, so
    /// returning one turned "there is no UI" into a silent failure inside
    /// AuthenticationServices. Now it is refused before the request is made.
    private let anchor: UIWindow

    private init(anchor: UIWindow) {
        self.anchor = anchor
        super.init()
    }

    /// nil when the app has no window to present on. A factory rather than a
    /// failable init because `init?()` cannot override `NSObject.init()`.
    ///
    /// The caller reads nil the same way it reads a cancellation: the token was
    /// not revoked, and the deletion carries on regardless (TN3194).
    static func make() -> AppleReauthorizer? {
        let scenes = UIApplication.shared.connectedScenes.compactMap { $0 as? UIWindowScene }
        let scene = scenes.first { $0.activationState == .foregroundActive } ?? scenes.first
        guard let window = scene?.keyWindow ?? scene?.windows.first else { return nil }
        return AppleReauthorizer(anchor: window)
    }

    /// A fresh authorization code, or nil if the user cancelled or Apple
    /// refused. Never throws: every failure is the same instruction to the
    /// caller, which is to carry on with the deletion.
    func authorizationCode() async -> String? {
        await withCheckedContinuation { continuation in
            self.continuation = continuation
            let request = ASAuthorizationAppleIDProvider().createRequest()
            // No scopes requested. This is not a sign-in and we want no name or
            // email out of it — asking for data while deleting an account would
            // be a strange thing to do, and we would only have to delete it.
            request.requestedScopes = []
            let controller = ASAuthorizationController(authorizationRequests: [request])
            controller.delegate = self
            controller.presentationContextProvider = self
            controller.performRequests()
        }
    }

    private func finish(_ code: String?) {
        continuation?.resume(returning: code)
        continuation = nil
    }

    func authorizationController(
        controller: ASAuthorizationController,
        didCompleteWithAuthorization authorization: ASAuthorization
    ) {
        guard
            let credential = authorization.credential as? ASAuthorizationAppleIDCredential,
            let data = credential.authorizationCode,
            let code = String(data: data, encoding: .utf8)
        else {
            return finish(nil)
        }
        finish(code)
    }

    func authorizationController(
        controller: ASAuthorizationController,
        didCompleteWithError error: Error
    ) {
        finish(nil)
    }

    func presentationAnchor(for controller: ASAuthorizationController) -> ASPresentationAnchor {
        anchor
    }
}

// MARK: - The step

nonisolated enum AppleAccountRevocation {

    /// Revoke this account's Apple token, if it has one.
    ///
    /// - Parameters:
    ///   - isAppleLinked: Whether the identity carries an Apple provider. When
    ///     false this returns `.notLinked` without presenting anything —
    ///     showing Apple's sheet to a Google-only user would be inexplicable.
    ///   - fetchCode: Seam. Production runs `AppleReauthorizer`; tests supply
    ///     a closure, which is what makes every branch below reachable offline.
    ///   - revoke: Seam over `Auth.auth().revokeToken(withAuthorizationCode:)`.
    /// - Returns: What to tell the user. Never throws — see the header.
    static func revokeIfNeeded(
        isAppleLinked: Bool,
        fetchCode: () async -> String?,
        revoke: (String) async throws -> Void
    ) async -> AppleRevocation {
        guard isAppleLinked else { return .notLinked }
        guard let code = await fetchCode(), !code.isEmpty else { return .notRevoked }
        do {
            try await revoke(code)
            return .revoked
        } catch {
            return .notRevoked
        }
    }

    /// The production wiring of the two seams above.
    @MainActor
    static func perform(isAppleLinked: Bool) async -> AppleRevocation {
        await revokeIfNeeded(
            isAppleLinked: isAppleLinked,
            fetchCode: {
                guard let reauthorizer = AppleReauthorizer.make() else { return nil }
                return await reauthorizer.authorizationCode()
            },
            revoke: { try await Auth.auth().revokeToken(withAuthorizationCode: $0) }
        )
    }
}
