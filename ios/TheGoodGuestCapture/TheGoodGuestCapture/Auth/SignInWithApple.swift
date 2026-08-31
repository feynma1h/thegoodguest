/// Sign in with Apple support for account linking (decision 0051).
///
/// Pure helpers kept out of AuthManager so they are unit-testable without a
/// configured FirebaseApp or a network:
///   - Nonce generation + SHA-256: the Apple → Firebase replay guard. The RAW
///     nonce goes to Firebase inside the credential; its SHA-256 goes to Apple
///     in the authorization request. (Google's flow needs no client nonce —
///     GIDSignIn owns its own replay protection.)
///
/// Link-failure classification used to live here; it moved to
/// AccountLinking.classifyLinkError when Google became a second link provider
/// (decision 0118) — one classifier for both providers' link paths.
///
/// Read by: SignInSheet (request/nonce wiring), AuthLinkingTests (pins).

import CryptoKit
import Foundation

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
}
