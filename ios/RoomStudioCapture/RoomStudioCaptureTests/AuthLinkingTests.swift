/// Tests for the Sign in with Apple support layer (decision 0051).
///
/// Pins the pure, offline-testable halves of the link flow:
///   - Nonce generation: length, charset membership, the exactly-64-character
///     charset invariant the unbiased `byte & 63` mapping depends on, and
///     call-to-call uniqueness.
///   - SHA-256 hex digests against known vectors (what Apple receives).
///   - classifyLinkError: the SDK-error → AppleLinkFailure mapping, including
///     the conflict case carrying the SDK's updated credential through intact.
///   - The OAuthProvider.appleCredential factory producing an apple.com
///     credential (the object linkAppleAccount hands to link(with:)).
///
/// The link/switch calls themselves are thin passthroughs to FirebaseAuth and
/// are verified on-device (Gate: link succeeds, UID unchanged) — they cannot
/// be exercised against a fake without wrapping the SDK for no product gain.

import AuthenticationServices
import FirebaseAuth
import XCTest

@testable import RoomStudioCapture

final class AuthLinkingTests: XCTestCase {

    // MARK: - Nonce

    func test_randomNonce_defaultLength32_charsetMembers() {
        let nonce = SignInWithApple.randomNonceString()
        XCTAssertEqual(nonce.count, 32)
        let allowed = Set(SignInWithApple.nonceCharset)
        XCTAssertTrue(nonce.allSatisfy { allowed.contains($0) },
                      "nonce contains characters outside the charset: \(nonce)")
    }

    func test_randomNonce_customLength() {
        XCTAssertEqual(SignInWithApple.randomNonceString(length: 8).count, 8)
        XCTAssertEqual(SignInWithApple.randomNonceString(length: 64).count, 64)
    }

    func test_randomNonce_uniqueAcrossCalls() {
        // 32 chars × 6 bits = 192 bits of entropy; equality means broken RNG.
        XCTAssertNotEqual(SignInWithApple.randomNonceString(),
                          SignInWithApple.randomNonceString())
    }

    func test_nonceCharset_exactly64UniqueCharacters() {
        // The `byte & 63` uniform mapping is only unbiased at exactly 64.
        XCTAssertEqual(SignInWithApple.nonceCharset.count, 64)
        XCTAssertEqual(Set(SignInWithApple.nonceCharset).count, 64)
    }

    // MARK: - SHA-256

    func test_sha256Hex_knownVector() {
        XCTAssertEqual(
            SignInWithApple.sha256Hex("test"),
            "9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08")
    }

    func test_sha256Hex_emptyString() {
        XCTAssertEqual(
            SignInWithApple.sha256Hex(""),
            "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855")
    }

    // MARK: - Error classification

    func test_classify_credentialAlreadyInUse_carriesUpdatedCredential() {
        let updated = OAuthProvider.appleCredential(
            withIDToken: "header.payload.sig", rawNonce: "nonce", fullName: nil)
        let error = NSError(
            domain: AuthErrorDomain,
            code: AuthErrorCode.credentialAlreadyInUse.rawValue,
            userInfo: [AuthErrorUserInfoUpdatedCredentialKey: updated])

        guard case .appleIDOwnedByAnotherAccount(let carried) =
            SignInWithApple.classifyLinkError(error)
        else {
            return XCTFail("expected .appleIDOwnedByAnotherAccount")
        }
        XCTAssertTrue(carried === updated,
                      "the SDK's updated credential must pass through unchanged")
    }

    func test_classify_credentialAlreadyInUse_withoutCredential() {
        let error = NSError(
            domain: AuthErrorDomain,
            code: AuthErrorCode.credentialAlreadyInUse.rawValue)

        guard case .appleIDOwnedByAnotherAccount(let carried) =
            SignInWithApple.classifyLinkError(error)
        else {
            return XCTFail("expected .appleIDOwnedByAnotherAccount")
        }
        XCTAssertNil(carried, "no credential from the SDK means no switch offer")
    }

    func test_classify_appleSheetCanceled() {
        let error = NSError(
            domain: ASAuthorizationError.errorDomain,
            code: ASAuthorizationError.canceled.rawValue)

        guard case .canceled = SignInWithApple.classifyLinkError(error) else {
            return XCTFail("expected .canceled")
        }
    }

    func test_classify_networkError_isRetryable() {
        let error = NSError(
            domain: AuthErrorDomain,
            code: AuthErrorCode.networkError.rawValue)

        guard case .retryable = SignInWithApple.classifyLinkError(error) else {
            return XCTFail("expected .retryable")
        }
    }

    func test_classify_unknownError_fallsThroughWithMessage() {
        let error = NSError(
            domain: "SomeOtherDomain", code: 42,
            userInfo: [NSLocalizedDescriptionKey: "it broke"])

        guard case .other(let message) = SignInWithApple.classifyLinkError(error)
        else {
            return XCTFail("expected .other")
        }
        XCTAssertEqual(message, "it broke")
    }

    // MARK: - Credential factory

    func test_appleCredentialFactory_providerIsApple() {
        let credential = OAuthProvider.appleCredential(
            withIDToken: "header.payload.sig", rawNonce: "nonce", fullName: nil)
        XCTAssertEqual(credential.provider, "apple.com")
    }
}
