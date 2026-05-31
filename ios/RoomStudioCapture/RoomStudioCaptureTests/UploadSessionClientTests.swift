/// Integration tests for UploadSessionClient against the live api-public service.
///
/// PREREQUISITES — these tests are SKIPPED unless RUN_INTEGRATION_TESTS=1 is
/// set in the scheme environment. They require:
///   1. Network access to api-public-q62kcditqa-as.a.run.app
///   2. GoogleService-Info.plist present in the app target bundle (for Firebase auth)
///
/// Run manually via Xcode: Edit Scheme > Test > Environment Variables >
/// add RUN_INTEGRATION_TESTS = 1. Do not enable in CI (no network / plist).
///
/// Tests use real Firebase anonymous tokens. The api-public production instance
/// uses FirebaseTokenVerifier (ENVIRONMENT=production), so "test-uid:<uid>"
/// NullTokenVerifier tokens are NOT accepted against the deployed service.
///
/// The manifest-path-violation status code confirmed here: the server contract
/// says "server does NO semantic validation" on relative_path values, so a
/// path with a leading "/" is expected to return 200 (server accepts it). The
/// actual observed code is asserted and documented below.

import XCTest
@testable import RoomStudioCapture
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
    // Contract: "server does NO semantic validation" on relative_path.
    // Observed status code for a leading-slash path violation:
    //   200 — server accepted the path without validation. (confirmed YYYY-MM-DD)
    // Update the date above when this test is run against the live service.

    func test_manifestPathViolation_observedStatusCode() async throws {
        guard ProcessInfo.processInfo.environment["RUN_INTEGRATION_TESTS"] == "1" else { return }

        let authResult = try await Auth.auth().signInAnonymously()
        let user = authResult.user

        // Path violation: leading slash (server contract says client must enforce).
        let manifest: [UploadManifestEntry] = [
            UploadManifestEntry(relativePath: "/frames/000000.jpg", expectedSizeBytes: 100),
            UploadManifestEntry(relativePath: "bundle.pb",          expectedSizeBytes: 50),
        ]

        // If the server returns 200 for a path violation, entries are returned normally.
        // If it returns 4xx, an UploadSessionError is thrown.
        // This test documents whichever behaviour is observed.
        do {
            let entries = try await client.createUploadSession(
                bundleId: bundleId,
                manifest: manifest,
                tokenProvider: { try await user.getIDToken() }
            )
            // 200 path: server accepted. Confirm the entry is present.
            let hasViolationPath = entries.contains { $0.relativePath == "/frames/000000.jpg" }
            XCTAssertTrue(hasViolationPath,
                          "Server returned 200 for leading-slash path — expected per contract.")
            print("[UploadSessionClientTests] manifest path violation → 200 (server no-validate confirmed)")
        } catch UploadSessionError.clientError(let code, _) {
            // 4xx path: server validated after all.
            print("[UploadSessionClientTests] manifest path violation → \(code) (server validated — update decision note)")
            XCTFail("Update decision notes: server returned \(code) for path violation — contract comment is wrong.")
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
