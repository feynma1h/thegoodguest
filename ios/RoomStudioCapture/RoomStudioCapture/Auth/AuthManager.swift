/// Firebase anonymous auth layer for RoomStudio Capture.
///
/// Responsibilities:
///   - Ensure a stable anonymous UID exists before any upload call.
///   - Vend fresh idTokens on demand (never cache the raw string).
///
/// Key design decisions (decision 0036):
///   - signInIfNeeded() is idempotent: reuses currentUser if non-nil, never
///     calls signInAnonymously() twice. UID churn would orphan prior scenes at
///     poll time — we avoid it by checking for an existing user first.
///   - currentUID is offline-safe: Firebase persists the anonymous user in
///     Keychain; the UID is available without a network call after first online
///     sign-in. Capture and bundle.pb serialization read currentUID and remain
///     fully offline-capable after the first run.
///   - currentIDToken() is always live: calls getIDToken() on each invocation
///     and lets the Firebase SDK handle expiry and refresh transparently. Do
///     not cache the returned string — it expires after 1 hour.
///
/// Read by: CaptureManager (UID at stop-capture), UploadCoordinator (sign-in
///          gate + token vending before upload session call).

import Combine
import FirebaseAuth
import FirebaseCore
import Foundation

@MainActor
final class AuthManager: ObservableObject {

    static let shared = AuthManager()

    // MARK: - Published state

    /// Current anonymous UID, or nil if not yet signed in (or Firebase not configured).
    /// Updated on sign-in. Reads Firebase Keychain cache — offline-safe after
    /// the first online sign-in.
    @Published private(set) var uid: String?

    // MARK: - Init

    private init() {
        // IMPORTANT: do NOT access Auth.auth() in a property initializer default
        // value — it runs before this body and before the FirebaseApp guard.
        // Auth.auth() asserts FirebaseApp.defaultApp() != nil; calling it without
        // a GoogleService-Info.plist (e.g. test targets) causes a fatal crash.
        // The guard here keeps the store nil-safe in those environments.
        if FirebaseApp.app() != nil {
            uid = Auth.auth().currentUser?.uid
        }
    }

    // MARK: - Public API

    /// True if Firebase is configured in this app launch (GoogleService-Info.plist present).
    var isConfigured: Bool { FirebaseApp.app() != nil }

    /// The cached UID from Keychain — available offline after first sign-in.
    /// Returns nil if Firebase is not configured or no user has signed in.
    var currentUID: String? {
        guard isConfigured else { return nil }
        return Auth.auth().currentUser?.uid
    }

    /// In-flight anonymous sign-in, shared by concurrent callers (single-flight).
    /// @MainActor serializes ENTRY to signInIfNeeded, but signInAnonymously()
    /// suspends — without this, two callers overlapping across that suspension
    /// would both observe currentUser == nil and create two anonymous users, the
    /// second overwriting the first locally: exactly the UID churn decision 0036
    /// forbids. Concurrent callers at cold launch are real: ScenePoller's token
    /// path attempts sign-in and can race the app-level launch .task.
    private var signInTask: Task<Void, Error>?

    /// Ensure an anonymous Firebase user exists. No-op if already signed in
    /// or if Firebase is not configured (test environments without plist).
    /// Concurrent callers join the same in-flight sign-in (single-flight) —
    /// signInAnonymously() is never running twice.
    ///
    /// Call at app launch (when network is likely available) and immediately
    /// before any upload call that needs a token. Do NOT call inside
    /// stopCapture() — capture must remain offline-safe.
    ///
    /// Throws on network failure or Firebase configuration error. The caller
    /// decides whether to retry or surface an error to the user. After a failed
    /// attempt the in-flight slot is cleared, so a later call retries fresh.
    func signInIfNeeded() async throws {
        guard isConfigured else { return }
        // Reuse existing user — never create a new anonymous UID when one exists.
        if Auth.auth().currentUser != nil { return }
        // Join an in-flight sign-in instead of starting a second one.
        if let inFlight = signInTask {
            return try await inFlight.value
        }
        // No suspension between the checks above and this assignment (all on the
        // MainActor executor), so a second caller cannot interleave and double-start.
        let task = Task { @MainActor in
            defer { self.signInTask = nil }
            let result = try await Auth.auth().signInAnonymously()
            self.uid = result.user.uid
        }
        signInTask = task
        return try await task.value
    }

    /// Returns a fresh Firebase ID token. Never cache the return value.
    ///
    /// The Firebase SDK refreshes the token automatically when it is near
    /// expiry; this method does not force-refresh unless the SDK decides to.
    /// Call immediately before each network request that needs Bearer auth.
    ///
    /// Throws AuthError.notConfigured if Firebase is absent (test environment).
    /// Throws AuthError.notSignedIn if no user exists (call signInIfNeeded() first).
    func currentIDToken() async throws -> String {
        guard isConfigured else { throw AuthError.notConfigured }
        guard let user = Auth.auth().currentUser else {
            throw AuthError.notSignedIn
        }
        return try await user.getIDToken()
    }

    // MARK: - Errors

    enum AuthError: LocalizedError {
        case notConfigured
        case notSignedIn

        var errorDescription: String? {
            switch self {
            case .notConfigured:
                return "Firebase is not configured. Add GoogleService-Info.plist to the app bundle."
            case .notSignedIn:
                return "No authenticated user. Call signInIfNeeded() before requesting a token."
            }
        }
    }
}
