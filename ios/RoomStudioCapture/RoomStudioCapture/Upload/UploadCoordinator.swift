/// Orchestrates upload-session creation for one capture bundle.
///
/// Pipeline (called after CaptureManager publishes bundlePath):
///   1. signInIfNeeded()     — ensure anonymous Firebase user exists
///   2. backstop patch       — if bundle.pb has empty user_id (first-ever offline
///                             launch), read + patch + rewrite it in-place
///   3. ManifestBuilder      — enumerate on-disk artifacts
///   4. UploadSessionClient  — POST /upload_session with Bearer idToken
///   5. UploadSessionStore   — persist UploadSessionRecord to disk
///
/// BlobUploadManager picks up from `sessionState == .ready(_)` and executes
/// the blob PUTs.
///
/// Read by: ContentView (observe sessionState for UI feedback).

import Combine
import Foundation
import os
import SwiftProtobuf
import UIKit

@MainActor
final class UploadCoordinator: ObservableObject {

    // Logging privacy policy: UUIDs, blob paths, and enum values may be .public;
    // user identifiers and error payloads stay default-private (redacted in shipped logs).
    private let logger = Logger(subsystem: "com.roomstudio.RoomStudioCapture", category: "Coordinator")

    // MARK: - Published state

    enum SessionState {
        case idle
        case authenticating
        case patchingBundle          // backstop: patching user_id in bundle.pb
        case buildingManifest
        case creatingSession
        case ready(UploadSessionRecord)
        /// `terminal` marks a failure that retrying provably cannot fix (a 4xx
        /// client error — the "do not retry" case below). UI must not offer an
        /// endless "Try again" for these; transient/unknown failures stay false.
        case failed(String, terminal: Bool = false)
    }

    @Published private(set) var sessionState: SessionState = .idle

    /// Incremented per call. A call that has been superseded by a newer one drops
    /// its state writes instead of clobbering the newer send's outcome — the 0038
    /// retry ladder can hold a POST for ~a minute, long enough for the user to
    /// leave, rescan and send again. Guarding at the CALLER could only ever protect
    /// writes made after its await; every write below happens inside this call.
    private var callSequence = 0

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

    /// Clear any prior run's terminal session state (.ready/.failed) back to .idle.
    /// Call synchronously before a new send so an observer never briefly renders the
    /// previous capture's session outcome during the next send's setup window.
    func reset() {
        // Bump too: an older beginUploadSession suspended in the 0038 ladder would
        // otherwise still satisfy `mine == callSequence` and could publish a
        // terminal .failed over a send that just started.
        callSequence &+= 1
        sessionState = .idle
    }

    /// Begin upload session creation for a completed capture.
    ///
    /// Safe to call multiple times — if a session record already exists for
    /// the bundle_id, it is returned immediately without a new server call.
    ///
    /// - Parameter capture: The CaptureManager after stopCapture() has set bundlePath.
    func beginUploadSession(for capture: CaptureManager) async {
        callSequence &+= 1
        let mine = callSequence
        /// Publish only if this call is still the newest one.
        func publish(_ state: SessionState) {
            guard mine == callSequence else { return }
            sessionState = state
        }

        guard
            let outputDir = capture.bundleOutputDir,
            capture.bundlePath != nil
        else {
            publish(.failed("No bundle on disk — call stopCapture() first."))
            return
        }

        let bundleId = capture.bundleIdString

        // Acquire UIBackgroundTask assertion before the first await. UploadCoordinator is
        // @MainActor so UIApplication.shared is directly accessible (no @preconcurrency needed).
        // The handle and the expiration closure reference each other; a lock box
        // breaks the cycle without a mutated-after-capture var (a Swift 6 error).
        // If the OS could fire the expiration handler before the box is filled
        // (it cannot — beginBackgroundTask returns first), the nil read is a
        // no-op and the defer below still ends the assertion.
        let handleBox = OSAllocatedUnfairLock<BackgroundTaskHandle?>(initialState: nil)
        let bgToken = UIApplication.shared.beginBackgroundTask(withName: "upload-session-\(bundleId)") {
            handleBox.withLock { $0 }?.endIfNeeded()
        }
        let handle = BackgroundTaskHandle {
            // Token .invalid means beginBackgroundTask failed (e.g. app extension context).
            guard bgToken != .invalid else { return }
            // endBackgroundTask via the main actor: the @Sendable endAction may
            // not reference MainActor state directly under Swift 6; the one-hop
            // delay in releasing the assertion is harmless.
            Task { @MainActor in UIApplication.shared.endBackgroundTask(bgToken) }
        }
        handleBox.withLock { $0 = handle }
        // Single defer covers every exit path from here through publish(.ready(_)).
        defer { handle.endIfNeeded() }

        // Fast path: session record already persisted (e.g. app relaunched mid-upload).
        if let existing = try? await store.load(bundleId: bundleId) {
            publish(.ready(existing))
            logger.info("[UploadCoordinator] → handing off to BlobUploadManager for bundle \(bundleId, privacy: .public)")
            if existing.allNonBundlePbBlobsUploaded {
                // All non-bundle.pb blobs already uploaded; route to bundle.pb finalize.
                // onAllBlobsUploaded carries the staleness guard (>12h → re-mint).
                await BlobUploadManager.shared.onAllBlobsUploaded(bundleId: bundleId, record: existing)
            } else {
                do {
                    try await BlobUploadManager.shared.enqueuePhasOneBlobs(record: existing)
                } catch {
                    logger.info("[UploadCoordinator] ✗ Phase-1 enqueue failed: \(error)")
                }
            }
            return
        }

        // 1. Ensure signed in.
        publish(.authenticating)
        do {
            try await auth.signInIfNeeded()
        } catch {
            publish(.failed("Firebase sign-in failed: \(error.localizedDescription)"))
            return
        }
        guard let uid = auth.currentUID else {
            // Terminal: sign-in reported success with no UID — retrying the same
            // call cannot resolve an invariant violation.
            publish(.failed("No UID after sign-in — unexpected state.", terminal: true))
            return
        }

        // 2. Backstop: patch user_id in bundle.pb if it was empty at capture time.
        //    This only fires on a first-ever offline capture (rare path).
        if capture.assembledWithoutUserId {
            publish(.patchingBundle)
            let bundlePbURL = outputDir.appendingPathComponent("bundle.pb")
            do {
                var bundleData = try Data(contentsOf: bundlePbURL)
                var proto = try RSCaptureBundle(serializedBytes: bundleData)
                if proto.userID.isEmpty {
                    proto.userID = uid
                    bundleData   = try proto.serializedData()
                    try bundleData.write(to: bundlePbURL, options: [.atomic, .completeFileProtectionUntilFirstUserAuthentication])
                    logger.info("[UploadCoordinator] backstop: patched user_id in bundle.pb")
                }
            } catch {
                publish(.failed("Bundle patch failed: \(error.localizedDescription)"))
                return
            }
        }

        // 3. Build manifest.
        publish(.buildingManifest)
        let manifest: [UploadManifestEntry]
        do {
            manifest = try ManifestBuilder.build(outputDir: outputDir)
        } catch {
            publish(.failed("Manifest build failed: \(error.localizedDescription)"))
            return
        }

        // 4. Create upload session.
        publish(.creatingSession)
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
            // Terminal: a 403 (e.g. bundle_id ownership) will answer identically on
            // every retry, so the UI must offer an off-ramp, not "Try again".
            publish(.failed("Forbidden: \(msg)", terminal: true))
            return
        } catch UploadSessionError.clientError(let code, let body) {
            // Client bug — log loudly; do not retry. Marked terminal so the UI
            // offers a real off-ramp instead of an unbounded retry that cannot work.
            logger.info("[UploadCoordinator] PROGRAMMING ERROR — \(code): \(body)")
            publish(.failed("Client error \(code): \(body)", terminal: true))
            return
        } catch {
            publish(.failed("Upload session failed: \(error.localizedDescription)"))
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
            // in memory; the blob upload can proceed. Log and continue.
            logger.info("[UploadCoordinator] WARNING — persistence failed: \(error.localizedDescription)")
        }

        publish(.ready(record))
        logger.info("[UploadCoordinator] → handing off to BlobUploadManager for bundle \(bundleId, privacy: .public)")
        do {
            try await BlobUploadManager.shared.enqueuePhasOneBlobs(record: record)
        } catch {
            logger.info("[UploadCoordinator] ✗ Phase-1 enqueue failed: \(error)")
        }
    }
}
