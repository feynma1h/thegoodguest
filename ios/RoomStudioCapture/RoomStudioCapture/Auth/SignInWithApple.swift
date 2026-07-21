/// Sign in with Apple support for account linking (decision 0051).
///
/// Pure helpers kept out of AuthManager so they are unit-testable without a
/// configured FirebaseApp or a network:
///   - Nonce generation + SHA-256: the Apple → Firebase replay guard. The RAW
///     nonce goes to Firebase inside the credential; its SHA-256 goes to Apple
///     in the authorization request.
///   - AppleLinkFailure classification: maps the SDK error zoo (FirebaseAuth
///     AuthErrorCode, ASAuthorizationError) onto the small set of outcomes the
///     sign-in UI actually distinguishes.
///
/// Read by: AuthManager (link path), SignInSheet (request/nonce wiring),
///          AuthLinkingTests (pins).

import AuthenticationServices
import CryptoKit
import FirebaseAuth
import Foundation

/// Why an Apple link attempt did not end in `.linked`, reduced to what the UI
/// can act on. Produced by `SignInWithApple.classifyLinkError`.
enum AppleLinkFailure {
    /// The Apple ID is already the credential of a DIFFERENT Firebase account
    /// (AuthErrorCode.credentialAlreadyInUse). `existingAccountCredential` is
    /// the SDK-provided single-use credential that signs in to that account if
    /// the user explicitly chooses to switch; nil when the SDK gave none back
    /// (no switch possible — only retry).
    case appleIDOwnedByAnotherAccount(existingAccountCredential: AuthCredential?)
    /// The user dismissed the Apple sheet. Not an error; show nothing.
    case canceled
    /// Transient (network mid-flow). Safe to retry; current account untouched.
    case retryable(message: String)
    /// Everything else. Surface the message; current account untouched.
    case other(message: String)
}

enum SignInWithApple {

    /// Cryptographically random nonce for the Apple request.
    ///
    /// The charset is exactly 64 characters so `byte & 63` maps uniformly —
    /// no rejection sampling, no modulo bias.
    nonisolated static let nonceCharset =
        Array("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-.")

    nonisolated static func randomNonceString(length: Int = 32) -> String {
        precondition(length > 0, "nonce length must be positive")
        var bytes = [UInt8](repeating: 0, count: length)
        let status = SecRandomCopyBytes(kSecRandomDefault, length, &bytes)
        // SecRandomCopyBytes only fails when the system CSPRNG is unavailable;
        // proceeding with a predictable nonce would defeat the replay guard.
        precondition(status == errSecSuccess, "SecRandomCopyBytes failed: \(status)")
        return String(bytes.map { nonceCharset[Int($0 & 63)] })
    }

    /// Lowercase hex SHA-256, the digest form Apple expects in `request.nonce`.
    nonisolated static func sha256Hex(_ input: String) -> String {
        SHA256.hash(data: Data(input.utf8))
            .map { String(format: "%02x", $0) }
            .joined()
    }

    /// Reduce a thrown link/authorization error to an AppleLinkFailure.
    ///
    /// Only errors that change what the UI does get their own case; the rest
    /// collapse into `.other` with the SDK's own message.
    nonisolated static func classifyLinkError(_ error: Error) -> AppleLinkFailure {
        let ns = error as NSError

        if ns.domain == ASAuthorizationError.errorDomain,
           ns.code == ASAuthorizationError.canceled.rawValue {
            return .canceled
        }

        if ns.domain == AuthErrorDomain {
            switch AuthErrorCode(rawValue: ns.code) {
            case .credentialAlreadyInUse:
                let credential = ns.userInfo[AuthErrorUserInfoUpdatedCredentialKey]
                    as? AuthCredential
                return .appleIDOwnedByAnotherAccount(
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
