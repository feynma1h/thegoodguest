/// Shared account-linking vocabulary for decision 0051's upgrade-and-link
/// flow, provider-generic since Google joined Apple as a link provider
/// (decisions 0094/0118). Both providers link a real credential to the
/// EXISTING anonymous user — the UID never changes on link — and both funnel
/// every failure through the ONE classifier here.
///
/// Why one classifier: the failure set that matters is defined by the LINK
/// stage (FirebaseAuth error codes), which is provider-independent; each
/// provider contributes only its own "the user closed the sheet" code. Two
/// classifiers would be two places for the conflict case to rot — the same
/// argument decision 0094 made for the web's single `signInAsReader` body.
///
/// Read by: AuthManager (link core), SignInSheet (classifying provider-flow
///          errors thrown before the link stage), AuthLinkingTests (pins).

import AuthenticationServices
import FirebaseAuth
import Foundation
import GoogleSignIn

/// Why a link attempt did not end in `.linked`, reduced to what the UI can
/// act on. Produced by `AccountLinking.classifyLinkError`.
nonisolated enum LinkFailure {
    /// The provider identity is already the credential of a DIFFERENT
    /// Firebase account (AuthErrorCode.credentialAlreadyInUse).
    /// `existingAccountCredential` is the SDK-provided single-use credential
    /// that signs in to that account if the user explicitly chooses to
    /// switch; nil when the SDK gave none back (no switch possible — only
    /// retry).
    case ownedByAnotherAccount(existingAccountCredential: AuthCredential?)
    /// The user dismissed the provider's sheet. Not an error; show nothing.
    case canceled
    /// Transient (network mid-flow). Safe to retry; current account untouched.
    case retryable(message: String)
    /// Everything else. Surface the message; current account untouched.
    case other(message: String)
}

/// Which real sign-in providers the current Firebase user carries, derived
/// from `providerData` provider IDs. Pure so the derivation is table-pinnable;
/// AuthManager publishes what this computes.
nonisolated struct LinkedProviders: Equatable {
    static let appleProviderID = "apple.com"
    static let googleProviderID = "google.com"

    let apple: Bool
    let google: Bool

    /// Linked to anything real — the "signed in" bit surfaces like ProfileView
    /// and DoorwayView read. Anonymous users carry no providerData, so an
    /// empty list is the anonymous state.
    var any: Bool { apple || google }

    init(providerIDs: some Sequence<String>) {
        var apple = false
        var google = false
        for id in providerIDs {
            if id == Self.appleProviderID { apple = true }
            if id == Self.googleProviderID { google = true }
        }
        self.apple = apple
        self.google = google
    }
}

nonisolated enum AccountLinking {

    /// Reduce a thrown link/authorization error to a LinkFailure.
    ///
    /// Handles all three domains a link attempt can throw from: the Apple
    /// authorization flow (ASAuthorizationError), the Google sign-in flow
    /// (GIDSignInError), and the Firebase link stage itself (AuthErrorDomain).
    /// Only errors that change what the UI does get their own case; the rest
    /// collapse into `.other` with the SDK's own message.
    ///
    /// Note on AuthErrorCode.emailAlreadyInUse — reachable via Google when
    /// the Google account's email already belongs to a different Firebase
    /// account through a DIFFERENT provider: it carries no switchable
    /// credential, so it deliberately stays `.other` with the SDK's own
    /// message rather than masquerading as a switchable conflict.
    static func classifyLinkError(_ error: Error) -> LinkFailure {
        let ns = error as NSError

        if ns.domain == ASAuthorizationError.errorDomain,
           ns.code == ASAuthorizationError.canceled.rawValue {
            return .canceled
        }

        if ns.domain == GIDSignInError.errorDomain,
           ns.code == GIDSignInError.canceled.rawValue {
            return .canceled
        }

        if ns.domain == AuthErrorDomain {
            switch AuthErrorCode(rawValue: ns.code) {
            case .credentialAlreadyInUse:
                let credential = ns.userInfo[AuthErrorUserInfoUpdatedCredentialKey]
                    as? AuthCredential
                return .ownedByAnotherAccount(
                    existingAccountCredential: credential)
            case .networkError:
                return .retryable(
                    message: "The network dropped during sign-in. Try again.")
            default:
                break
            }
        }

        return .other(message: ns.localizedDescription)
    }
}
