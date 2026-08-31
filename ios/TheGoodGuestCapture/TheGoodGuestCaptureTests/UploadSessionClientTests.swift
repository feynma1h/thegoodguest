/// Integration tests for UploadSessionClient against the live api-public service.
///
/// PREREQUISITES — the XCTSkipIf guard below is fail-open, but the project's
/// ONLY scheme (TheGoodGuestCapture-Integration) already sets
/// RUN_INTEGRATION_TESTS=1, so in practice these ALWAYS run live and go RED
/// when the backend is unreachable. They require:
///   1. Network access to api-public-q62kcditqa-as.a.run.app
///   2. GoogleService-Info.plist present in the app target bundle (for Firebase auth)
///   3. Headroom in the per-UID daily capture ceiling that endpoint enforces
///
/// To run the offline subset instead, skip this class:
///   -skip-testing:TheGoodGuestCaptureTests/UploadSessionClientTests
/// which is what .github/workflows/ios.yml does, and why that workflow is
/// manual-only.
///
/// Tests use real Firebase anonymous tokens. The api-public production instance
/// uses FirebaseTokenVerifier (ENVIRONMENT=production), so "test-uid:<uid>"
/// NullTokenVerifier tokens are NOT accepted against the deployed service.
///
/// The manifest-path-violation case below is pinned against the live server,
/// not against the decision notes: api-public validates manifest path format
/// and rejects a leading "/" with 400. An earlier reading of the contract as
/// "no semantic validation" was wrong, and the test asserts the measured
/// behaviour so a contract change breaks here rather than on a phone.

import XCTest
@testable import TheGoodGuestCapture
import FirebaseAuth
import FirebaseCore

final class UploadSessionClientTests: XCTestCase {

    private var client: UploadSessionClient!
    private var bundleId: String!

    override func setUpWithError() throws {
        guard ProcessInfo.processInfo.environment["RUN_INTEGRATION_TESTS"] == "1" else {
            throw XCTSkip("Set RUN_INTEGRATION_TESTS=1 to run integration tests.")
        }
        // FirebaseApp.configure() is called by the app delegate; confirm it's up.
        if FirebaseApp.app() == nil {
            FirebaseApp.configure()
        }
        client   = UploadSessionClient()
        bundleId = UUID().uuidString.lowercased()
    }

    // MARK: - Happy path

    func test_createUploadSession_happyPath_returns200WithEntries() async throws {
        guard ProcessInfo.processInfo.environment["RUN_INTEGRATION_TESTS"] == "1" else { return }

        // Sign in anonymously.
        let authResult = try await Auth.auth().signInAnonymously()
        let user = authResult.user

        // Build a minimal manifest: one frame + bundle.pb.
        let manifest: [UploadManifestEntry] = [
            UploadManifestEntry(relativePath: "frames/000000.jpg", expectedSizeBytes: 1024),
            UploadManifestEntry(relativePath: "bundle.pb",         expectedSizeBytes: 256),
        ]

        let entries = try await client.createUploadSession(
            bundleId: bundleId,
            manifest: manifest,
            tokenProvider: { try await user.getIDToken() }
        )

        // Server returns one entry per manifest item, no order guarantee.
        XCTAssertEqual(entries.count, manifest.count,
                       "Expected one UploadSessionEntry per manifest item")

        let entryMap = Dictionary(uniqueKeysWithValues: entries.map { ($0.relativePath, $0.sessionUri) })
        XCTAssertNotNil(entryMap["frames/000000.jpg"], "Missing session_uri for frames/000000.jpg")
        XCTAssertNotNil(entryMap["bundle.pb"],         "Missing session_uri for bundle.pb")

        for (path, uri) in entryMap {
            XCTAssertTrue(uri.hasPrefix("https://"),
                          "session_uri for \(path) should be an HTTPS GCS URI, got: \(uri)")
        }

        // Clean up — sign out to avoid UID accumulation in tests.
        try? Auth.auth().signOut()
    }

    // MARK: - Idempotency

    func test_createUploadSession_idempotent_samePathSetReturnsSameUris() async throws {
        guard ProcessInfo.processInfo.environment["RUN_INTEGRATION_TESTS"] == "1" else { return }

        let authResult = try await Auth.auth().signInAnonymously()
        let user = authResult.user

        let manifest: [UploadManifestEntry] = [
            UploadManifestEntry(relativePath: "frames/000000.jpg", expectedSizeBytes: 512),
            UploadManifestEntry(relativePath: "bundle.pb",         expectedSizeBytes: 128),
        ]

        let entries1 = try await client.createUploadSession(
            bundleId: bundleId,
            manifest: manifest,
            tokenProvider: { try await user.getIDToken() }
        )
        let entries2 = try await client.createUploadSession(
            bundleId: bundleId,
            manifest: manifest,
            tokenProvider: { try await user.getIDToken() }
        )

        let map1 = Dictionary(uniqueKeysWithValues: entries1.map { ($0.relativePath, $0.sessionUri) })
        let map2 = Dictionary(uniqueKeysWithValues: entries2.map { ($0.relativePath, $0.sessionUri) })

        XCTAssertEqual(map1, map2, "Same manifest path-set should return same session URIs (idempotency)")

        try? Auth.auth().signOut()
    }

    // MARK: - Manifest path violation
    //
    // LIVE-VERIFIED 2026-05-31 against api-public-q62kcditqa-as.a.run.app:
    //   Leading-slash path ("/frames/000000.jpg") → HTTP 400.
    // The "server does NO semantic validation" framing in the original P3 contract
    // notes was wrong for basic path-format checks. The server rejects leading
    // slashes with 400. Decision notes 0035 (F3) and 0038 updated accordingly.
    //
    // The client-side rule ("client must enforce relative_path rules") remains
    // correct — ManifestBuilder never emits leading-slash paths.

    func test_manifestPathViolation_observedStatusCode() async throws {
        guard ProcessInfo.processInfo.environment["RUN_INTEGRATION_TESTS"] == "1" else { return }

        let authResult = try await Auth.auth().signInAnonymously()
        let user = authResult.user

        // Path violation: leading slash.
        let manifest: [UploadManifestEntry] = [
            UploadManifestEntry(relativePath: "/frames/000000.jpg", expectedSizeBytes: 100),
            UploadManifestEntry(relativePath: "bundle.pb",          expectedSizeBytes: 50),
        ]

        do {
            _ = try await client.createUploadSession(
                bundleId: bundleId,
                manifest: manifest,
                tokenProvider: { try await user.getIDToken() }
            )
            // If we reach here the server returned 200 — the validated behavior changed.
            XCTFail("Expected 400 for leading-slash path; server returned 200. Update decision notes.")
        } catch UploadSessionError.clientError(let code, let body) {
            // Expected: server validates basic path format. Leading "/" → 400.
            print("[UploadSessionClientTests] manifest path violation → \(code) body: \(body)")
            XCTAssertEqual(code, 400,
                           "Expected 400 for leading-slash path, got \(code). Body: \(body)")
        }

        try? Auth.auth().signOut()
    }

    // MARK: - Auth rejection

    func test_invalidToken_throws401() async throws {
        guard ProcessInfo.processInfo.environment["RUN_INTEGRATION_TESTS"] == "1" else { return }

        let manifest: [UploadManifestEntry] = [
            UploadManifestEntry(relativePath: "bundle.pb", expectedSizeBytes: 50),
        ]

        do {
            _ = try await client.createUploadSession(
                bundleId: bundleId,
                manifest: manifest,
                tokenProvider: { "not-a-real-token" }
            )
            XCTFail("Expected unauthorized error for a garbage token")
        } catch UploadSessionError.unauthorized {
            // Expected — token is garbage so both the first attempt and the
            // single retry throw 401, which propagates to the caller.
        }
    }
}
