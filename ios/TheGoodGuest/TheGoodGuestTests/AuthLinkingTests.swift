/// Tests for the account-linking support layer (decisions 0051/0118).
///
/// Pins the pure, offline-testable halves of the link flow, both providers:
///   - Nonce generation: length, charset membership, the exactly-64-character
///     charset invariant the unbiased `byte & 63` mapping depends on, and
///     call-to-call uniqueness.
///   - SHA-256 hex digests against known vectors (what Apple receives).
///   - AccountLinking.classifyLinkError: the SDK-error → LinkFailure mapping
///     across all three domains (Apple authorization, Google sign-in flow,
///     Firebase link stage), including the conflict case carrying the SDK's
///     updated credential through intact.
///   - The credential factories producing apple.com / google.com credentials
///     (the objects AuthManager's link core hands to link(with:)).
///   - SignInWithGoogle: reversed-client-ID derivation, the preflight verdict
///     table, and the drift pin between the COMMITTED URL scheme
///     (TheGoodGuest-Info.plist) and the GITIGNORED client ID
///     (GoogleService-Info.plist).
///   - LinkedProviders: the providerData → published-state derivation table.
///
/// The link/switch calls themselves are thin passthroughs to FirebaseAuth and
/// are verified on-device (Gate: link succeeds, UID unchanged) — they cannot
/// be exercised against a fake without wrapping the SDK for no product gain.

import AuthenticationServices
import FirebaseAuth
import GoogleSignIn
import XCTest

@testable import TheGoodGuest

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

        guard case .ownedByAnotherAccount(let carried) =
            AccountLinking.classifyLinkError(error)
        else {
            return XCTFail("expected .ownedByAnotherAccount")
        }
        XCTAssertTrue(carried === updated,
                      "the SDK's updated credential must pass through unchanged")
    }

    func test_classify_credentialAlreadyInUse_withoutCredential() {
        let error = NSError(
            domain: AuthErrorDomain,
            code: AuthErrorCode.credentialAlreadyInUse.rawValue)

        guard case .ownedByAnotherAccount(let carried) =
            AccountLinking.classifyLinkError(error)
        else {
            return XCTFail("expected .ownedByAnotherAccount")
        }
        XCTAssertNil(carried, "no credential from the SDK means no switch offer")
    }

    func test_classify_appleSheetCanceled() {
        let error = NSError(
            domain: ASAuthorizationError.errorDomain,
            code: ASAuthorizationError.canceled.rawValue)

        guard case .canceled = AccountLinking.classifyLinkError(error) else {
            return XCTFail("expected .canceled")
        }
    }

    func test_classify_googleSheetCanceled() {
        // The Google flow's "user closed the sheet" — GIDSignInError.canceled —
        // must be as silent as Apple's.
        let error = NSError(
            domain: GIDSignInError.errorDomain,
            code: GIDSignInError.canceled.rawValue)

        guard case .canceled = AccountLinking.classifyLinkError(error) else {
            return XCTFail("expected .canceled")
        }
    }

    func test_classify_networkError_isRetryable() {
        let error = NSError(
            domain: AuthErrorDomain,
            code: AuthErrorCode.networkError.rawValue)

        guard case .retryable = AccountLinking.classifyLinkError(error) else {
            return XCTFail("expected .retryable")
        }
    }

    func test_classify_emailAlreadyInUse_staysOther() {
        // Reachable via Google (the Google email belongs to another account
        // through a DIFFERENT provider). No switchable credential exists, so
        // it must NOT masquerade as a switchable conflict.
        let error = NSError(
            domain: AuthErrorDomain,
            code: AuthErrorCode.emailAlreadyInUse.rawValue,
            userInfo: [NSLocalizedDescriptionKey:
                "The email address is already in use by another account."])

        guard case .other(let message) = AccountLinking.classifyLinkError(error)
        else {
            return XCTFail("expected .other")
        }
        XCTAssertFalse(message.isEmpty)
    }

    func test_classify_unknownError_fallsThroughWithMessage() {
        let error = NSError(
            domain: "SomeOtherDomain", code: 42,
            userInfo: [NSLocalizedDescriptionKey: "it broke"])

        guard case .other(let message) = AccountLinking.classifyLinkError(error)
        else {
            return XCTFail("expected .other")
        }
        XCTAssertEqual(message, "it broke")
    }

    // MARK: - Credential factories

    func test_appleCredentialFactory_providerIsApple() {
        let credential = OAuthProvider.appleCredential(
            withIDToken: "header.payload.sig", rawNonce: "nonce", fullName: nil)
        XCTAssertEqual(credential.provider, "apple.com")
    }

    func test_googleCredentialFactory_providerIsGoogle() {
        let credential = GoogleAuthProvider.credential(
            withIDToken: "header.payload.sig", accessToken: "access-token")
        XCTAssertEqual(credential.provider, "google.com")
    }

    // MARK: - Google reversed client ID + preflight

    func test_reversedClientID_derivation() {
        XCTAssertEqual(
            SignInWithGoogle.reversedClientID(
                fromClientID: "12345-abcde.apps.googleusercontent.com"),
            "com.googleusercontent.apps.12345-abcde")
    }

    func test_reversedClientID_rejectsNonGoogleShapes() {
        // Wrong suffix: not a Google iOS client ID.
        XCTAssertNil(SignInWithGoogle.reversedClientID(
            fromClientID: "12345-abcde.example.com"))
        // Bare suffix: nothing to reverse.
        XCTAssertNil(SignInWithGoogle.reversedClientID(
            fromClientID: ".apps.googleusercontent.com"))
        XCTAssertNil(SignInWithGoogle.reversedClientID(fromClientID: ""))
    }

    func test_preflight_missingClientID() {
        // Nil (Firebase absent) and malformed (not a Google client ID) both
        // land on the re-download message, never on a crashing sign-in start.
        XCTAssertEqual(
            SignInWithGoogle.preflight(clientID: nil, registeredURLSchemes: []),
            .missingClientID)
        XCTAssertEqual(
            SignInWithGoogle.preflight(
                clientID: "not-a-client-id", registeredURLSchemes: []),
            .missingClientID)
    }

    func test_preflight_schemeNotRegistered() {
        // The exact state GIDSignIn would turn into an uncatchable NSException.
        XCTAssertEqual(
            SignInWithGoogle.preflight(
                clientID: "12345-abcde.apps.googleusercontent.com",
                registeredURLSchemes: ["some.other.scheme"]),
            .schemeNotRegistered(expected: "com.googleusercontent.apps.12345-abcde"))
    }

    func test_preflight_ready() {
        XCTAssertEqual(
            SignInWithGoogle.preflight(
                clientID: "12345-abcde.apps.googleusercontent.com",
                registeredURLSchemes: [
                    "some.other.scheme",
                    "com.googleusercontent.apps.12345-abcde",
                ]),
            .ready(reversedScheme: "com.googleusercontent.apps.12345-abcde"))
    }

    /// THE drift pin: the redirect scheme is COMMITTED
    /// (TheGoodGuest-Info.plist) while the client ID it derives from is
    /// GITIGNORED (GoogleService-Info.plist) — nothing but this test notices
    /// when a regenerated OAuth client or a stale local plist splits them.
    /// Bundle.main is the HOST APP bundle (TEST_HOST), so this reads the real
    /// built products of both files.
    func test_appBundle_registersRedirectSchemeForLiveClientID() throws {
        guard
            let plistPath = Bundle.main.path(
                forResource: "GoogleService-Info", ofType: "plist"),
            let plist = NSDictionary(contentsOfFile: plistPath)
        else {
            throw XCTSkip("no GoogleService-Info.plist in the app bundle (worktree note in CLAUDE.md)")
        }
        guard let clientID = plist["CLIENT_ID"] as? String else {
            // A stale plist predating the iOS OAuth client: preflight refuses
            // at runtime (honest degrade), so the committed scheme is not
            // WRONG here — it is unconfirmable. Re-download the plist from
            // the Firebase console to make this pin bite again.
            throw XCTSkip("GoogleService-Info.plist has no CLIENT_ID — re-download it from the Firebase console")
        }
        let expected = try XCTUnwrap(
            SignInWithGoogle.reversedClientID(fromClientID: clientID),
            "CLIENT_ID in the app bundle is not a Google iOS client ID: \(clientID)")
        let registered = SignInWithGoogle.registeredURLSchemes(in: .main)
        XCTAssertTrue(
            registered.contains(expected),
            """
            The app bundle does not register \(expected). Update \
            TheGoodGuest-Info.plist to match the plist's \
            REVERSED_CLIENT_ID, or Google sign-in will refuse at preflight.
            """)
    }

    // MARK: - LinkedProviders derivation

    func test_linkedProviders_anonymousHasNone() {
        let providers = LinkedProviders(providerIDs: [String]())
        XCTAssertFalse(providers.apple)
        XCTAssertFalse(providers.google)
        XCTAssertFalse(providers.any)
    }

    func test_linkedProviders_singleProviders_unknownIgnored() {
        let apple = LinkedProviders(providerIDs: ["apple.com", "password"])
        XCTAssertTrue(apple.apple)
        XCTAssertFalse(apple.google)
        XCTAssertTrue(apple.any)

        let google = LinkedProviders(providerIDs: ["github.com", "google.com"])
        XCTAssertFalse(google.apple)
        XCTAssertTrue(google.google)
        XCTAssertTrue(google.any)
    }

    func test_linkedProviders_bothProviders() {
        let both = LinkedProviders(providerIDs: ["google.com", "apple.com"])
        XCTAssertTrue(both.apple)
        XCTAssertTrue(both.google)
        XCTAssertTrue(both.any)
    }
}
