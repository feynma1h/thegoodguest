/// Orchestrates the P3 upload-session creation pipeline for one capture bundle.
///
/// Pipeline (called after CaptureManager publishes bundlePath):
///   1. signInIfNeeded()     — ensure anonymous Firebase user exists
///   2. backstop patch       — if bundle.pb has empty user_id (first-ever offline
///                             launch), read + patch + rewrite it in-place
///   3. ManifestBuilder      — enumerate on-disk artifacts
///   4. UploadSessionClient  — POST /upload_session with Bearer idToken
///   5. UploadSessionStore   — persist UploadSessionRecord to disk
///
/// P4 picks up from `sessionState == .ready(_)` and executes the blob PUTs.
///
/// Read by: ContentView (observe sessionState for UI feedback).

import Combine
import Foundation
import SwiftProtobuf

@MainActor
final class UploadCoordinator: ObservableObject {

    // MARK: - Published state

    enum SessionState {
        case idle
        case authenticating
        case patchingBundle          // backstop: patching user_id in bundle.pb
        case buildingManifest
        case creatingSession
        case ready(UploadSessionRecord)
        case failed(String)          // human-readable error
    }

    @Published private(set) var sessionState: SessionState = .idle

    // MARK: - Dependencies (injectable for testing)

    private let auth:   AuthManager
    private let client: UploadSessionClient
    private let store:  UploadSessionStore

    // MARK: - Init

    /// Production init — uses shared singletons.
    /// Default parameter values are NOT used to avoid accessing @MainActor-isolated
    /// AuthManager.shared in a potentially nonisolated context (Swift 6 strictness).
    convenience init() {
        self.init(
            auth:   AuthManager.shared,
            client: UploadSessionClient.shared,
            store:  UploadSessionStore.shared
        )
    }

    /// Testing init — inject custom instances.
    init(auth: AuthManager, client: UploadSessionClient, store: UploadSessionStore) {
        self.auth   = auth
        self.client = client
        self.store  = store
    }

    // MARK: - Public API

    /// Begin upload session creation for a completed capture.
    ///
    /// Safe to call multiple times — if a session record already exists for
    /// the bundle_id, it is returned immediately without a new server call.
    ///
    /// - Parameter capture: The CaptureManager after stopCapture() has set bundlePath.
    func beginUploadSession(for capture: CaptureManager) async {
        guard
            let outputDir = capture.bundleOutputDir,
            capture.bundlePath != nil
        else {
            sessionState = .failed("No bundle on disk — call stopCapture() first.")
            return
        }

        let bundleId = capture.bundleIdString

        // Fast path: session record already persisted (e.g. app relaunched mid-upload).
        if let existing = try? await store.load(bundleId: bundleId) {
            sessionState = .ready(existing)
            return
        }

        // 1. Ensure signed in.
        sessionState = .authenticating
        do {
            try await auth.signInIfNeeded()
        } catch {
            sessionState = .failed("Firebase sign-in failed: \(error.localizedDescription)")
            return
        }
        guard let uid = auth.currentUID else {
            sessionState = .failed("No UID after sign-in — unexpected state.")
            return
        }

        // 2. Backstop: patch user_id in bundle.pb if it was empty at capture time.
        //    This only fires on a first-ever offline capture (rare path).
        if capture.assembledWithoutUserId {
            sessionState = .patchingBundle
            let bundlePbURL = outputDir.appendingPathComponent("bundle.pb")
            do {
                var bundleData = try Data(contentsOf: bundlePbURL)
                var proto = try RSCaptureBundle(serializedBytes: bundleData)
                if proto.userID.isEmpty {
                    proto.userID = uid
                    bundleData   = try proto.serializedData()
                    try bundleData.write(to: bundlePbURL, options: [.atomic, .completeFileProtectionUntilFirstUserAuthentication])
                    print("[UploadCoordinator] backstop: patched user_id in bundle.pb")
                }
            } catch {
                sessionState = .failed("Bundle patch failed: \(error.localizedDescription)")
                return
            }
        }

        // 3. Build manifest.
        sessionState = .buildingManifest
        let manifest: [UploadManifestEntry]
        do {
            manifest = try ManifestBuilder.build(outputDir: outputDir)
        } catch {
            sessionState = .failed("Manifest build failed: \(error.localizedDescription)")
            return
        }

        // 4. Create upload session.
        sessionState = .creatingSession
        let entries: [UploadSessionEntry]
        do {
            entries = try await client.createUploadSession(
                bundleId: bundleId,
                manifest: manifest,
                tokenProvider: { [weak self] in
                    guard let self else { throw AuthManager.AuthError.notSignedIn }
                    return try await self.auth.currentIDToken()
                }
            )
        } catch UploadSessionError.forbidden(let msg) {
            sessionState = .failed("Forbidden: \(msg)")
            return
        } catch UploadSessionError.clientError(let code, let body) {
            // Client bug — log loudly; do not retry.
            print("[UploadCoordinator] PROGRAMMING ERROR — \(code): \(body)")
            sessionState = .failed("Client error \(code): \(body)")
            return
        } catch {
            sessionState = .failed("Upload session failed: \(error.localizedDescription)")
            return
        }

        // 5. Persist record.
        let record = UploadSessionRecord(
            bundleId: bundleId,
            tierRawValue: capture.tier.rawValue,
            clientMintTimestamp: Date(),
            sessionEntries: entries,
            manifestPaths: manifest.map(\.relativePath),
            outputDir: outputDir
        )
        do {
            try await store.save(record)
        } catch {
            // Persistence failure is non-fatal — session URIs are in the record
            // in memory; P4 can proceed. Log and continue.
            print("[UploadCoordinator] WARNING — persistence failed: \(error)")
        }

        sessionState = .ready(record)
    }
}
