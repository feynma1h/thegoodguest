/// Firebase auth layer for TheGoodGuest Capture.
///
/// Responsibilities:
///   - Ensure a stable UID exists before any upload call (anonymous on first
///     run; the same UID once upgraded to a linked real sign-in).
///   - Vend fresh idTokens on demand (never cache the raw string).
///   - Upgrade the anonymous user to a real credential — Sign in with Apple
///     or Google (decisions 0051/0094/0118) — by LINKING it to the existing
///     user: the UID never changes on link; every scene captured before
///     sign-in stays reachable after. Both providers run through the one
///     private link core; the web reads either (0094).
///
/// Key design decisions (decisions 0036, 0051, 0118):
///   - signInIfNeeded() is idempotent: reuses currentUser if non-nil (anonymous
///     OR linked), never calls signInAnonymously() twice. UID churn would
///     orphan prior scenes at poll time — we avoid it by checking for an
///     existing user first.
///   - linkAppleAccount()/linkGoogleAccount() call link(with:) on the EXISTING
///     user, never signIn(with:). A successful link is asserted UID-unchanged.
///     The only path that changes the UID is switchToExistingAccount(), which
///     runs solely on an explicit, warned user choice after a link conflict.
///   - There is no sign-out on iOS: with no current user, the next launch's
///     signInIfNeeded() would mint a FRESH anonymous UID and orphan every
///     local record — exactly the churn 0036 forbids. The web app is where
///     sign-out lives; this install keeps its identity.
///   - currentUID is offline-safe: Firebase persists the user in Keychain; the
///     UID is available without a network call after first online sign-in.
///     Capture and bundle.pb serialization read currentUID and remain fully
///     offline-capable after the first run.
///   - currentIDToken() is always live: calls getIDToken() on each invocation
///     and lets the Firebase SDK handle expiry and refresh transparently. Do
///     not cache the returned string — it expires after 1 hour.
///
/// Read by: CaptureManager (UID at stop-capture), UploadCoordinator (sign-in
///          gate + token vending before upload session call), SignInSheet
///          (link/switch flow + published link state).

import Combine
import FirebaseAuth
import FirebaseCore
import Foundation
import os

@MainActor
final class AuthManager: ObservableObject {

    static let shared = AuthManager()

    // MARK: - Published state

    /// Current UID (anonymous or linked), or nil if not yet signed in (or
    /// Firebase not configured). Updated on sign-in. Reads Firebase Keychain
    /// cache — offline-safe after the first online sign-in.
    @Published private(set) var uid: String?

    /// True when the current user carries an Apple credential (decision 0051's
    /// linked state). Drives per-provider account UI; false while anonymous.
    @Published private(set) var isAppleLinked = false

    /// True when the current user carries a Google credential (decision 0118).
    @Published private(set) var isGoogleLinked = false

    /// Linked to any real provider — the "signed in" bit. Rooms follow the
    /// account to the web with either provider (0094), so surfaces that ask
    /// "is this identity safe across devices" read this, not a per-provider
    /// flag. Derived from the two @Published flags, so observers re-render.
    var isLinked: Bool { isAppleLinked || isGoogleLinked }

    /// Display email for the linked Apple credential, when Apple shared one
    /// (private-relay addresses included). Display-only — never sent anywhere.
    @Published private(set) var appleEmail: String?

    /// Display email for the linked Google credential. Display-only.
    @Published private(set) var googleEmail: String?

    private let logger = Logger(
        subsystem: "com.thegoodguest.TheGoodGuest", category: "Auth")

    // MARK: - Init

    private init() {
        // IMPORTANT: do NOT access Auth.auth() in a property initializer default
        // value — it runs before this body and before the FirebaseApp guard.
        // Auth.auth() asserts FirebaseApp.defaultApp() != nil; calling it without
        // a GoogleService-Info.plist (e.g. test targets) causes a fatal crash.
        // The guard here keeps the store nil-safe in those environments.
        if FirebaseApp.app() != nil {
            uid = Auth.auth().currentUser?.uid
            refreshLinkState()
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

    /// Ensure a Firebase user exists — anonymous on first run; a user that
    /// has since been linked to an Apple credential also satisfies it. No-op
    /// if already signed in or if Firebase is not configured (test
    /// environments without plist).
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
            // About to mint. Record whether this install is genuinely new or
            // has just lost an identity it used to have — the guard above
            // cannot tell those apart (decision 0139), and the difference is
            // the difference between a first run and silent, permanent
            // orphaning of every scene the old UID owns. Reading only; it does
            // not change whether we sign in. It lives inside the task because
            // the store is an actor: awaiting it above would put a suspension
            // between the currentUser check and the single-flight assignment,
            // which is the double-sign-in race that assignment exists to close.
            await self.logContinuityReading()
            let result = try await Auth.auth().signInAnonymously()
            self.uid = result.user.uid
            self.refreshLinkState()
        }
        signInTask = task
        return try await task.value
    }

    /// Gather the two independent signals and log what they say about this
    /// launch. Never mints, never throws, never changes the sign-in decision.
    private func logContinuityReading() async {
        let hasDeviceIdentity = DeviceIdentity.existingDeviceId() != nil
        let hasCaptureRecords =
            !((try? await UploadSessionStore.shared.allBundleIds()) ?? []).isEmpty
        let reading = IdentityContinuity.read(
            hasFirebaseUser: false,
            hasDeviceIdentity: hasDeviceIdentity,
            hasCaptureRecords: hasCaptureRecords)
        let line = """
            auth.continuity minting anonymous user: reading=\(String(describing: reading)) \
            device_identity=\(hasDeviceIdentity) capture_records=\(hasCaptureRecords)
            """
        if IdentityContinuity.isLoss(reading) {
            logger.fault("\(line, privacy: .public)")
        } else {
            logger.info("\(line, privacy: .public)")
        }
    }

    // MARK: - Account linking (decisions 0051/0118)

    /// Outcome of one link attempt (either provider), for the sign-in UI.
    enum LinkResult {
        /// Linked to the existing user. UID verified unchanged.
        case linked
        /// The provider identity already belongs to a DIFFERENT account. The
        /// credential (single-use, from the SDK) switches to it via
        /// switchToExistingAccount — only on an explicit user choice.
        case conflict(existingAccountCredential: AuthCredential?)
        /// User dismissed the provider's sheet; nothing changed, show nothing.
        case canceled
        /// Link failed; current account untouched. Message is display-ready.
        case failed(message: String)
    }

    /// Upgrade the current (anonymous) user with an Apple credential by
    /// LINKING — never a fresh sign-in. The UID is asserted unchanged; a
    /// mismatch is treated as failure, not silently adopted (0036's no-churn
    /// invariant is load-bearing: the UID owns every scene this install ever
    /// uploaded).
    ///
    /// `idTokenString`/`rawNonce` come from the ASAuthorization flow in
    /// SignInSheet; `fullName` is only non-nil on the FIRST authorization for
    /// this Apple ID and is forwarded so Firebase records a display name.
    func linkAppleAccount(
        idTokenString: String,
        rawNonce: String,
        fullName: PersonNameComponents?
    ) async -> LinkResult {
        await link(credential: OAuthProvider.appleCredential(
            withIDToken: idTokenString, rawNonce: rawNonce, fullName: fullName))
    }

    /// Upgrade the current (anonymous) user with a Google credential by
    /// LINKING — same core, same invariants as Apple (decision 0118). The
    /// tokens come from the GIDSignIn flow in SignInSheet; no client nonce is
    /// involved (GIDSignIn owns its own replay protection).
    func linkGoogleAccount(idToken: String, accessToken: String) async -> LinkResult {
        await link(credential: GoogleAuthProvider.credential(
            withIDToken: idToken, accessToken: accessToken))
    }

    /// The one link core both providers run through: link(with:) on the
    /// EXISTING user, UID asserted unchanged, failures classified by the
    /// shared AccountLinking.classifyLinkError.
    private func link(credential: AuthCredential) async -> LinkResult {
        guard isConfigured else {
            return .failed(message: AuthError.notConfigured.localizedDescription)
        }
        // First-launch edge: the launch sign-in may have failed offline. Link
        // needs a user to link TO; joining the single-flight sign-in here
        // cannot churn an existing UID (0036 guard inside signInIfNeeded).
        if Auth.auth().currentUser == nil {
            do { try await signInIfNeeded() } catch {
                return .failed(message:
                    "Couldn’t reach sign-in. Check the connection and try again.")
            }
        }
        guard let user = Auth.auth().currentUser else {
            return .failed(message: AuthError.notSignedIn.localizedDescription)
        }

        let uidBeforeLink = user.uid
        do {
            let result = try await user.link(with: credential)
            guard result.user.uid == uidBeforeLink else {
                // Firebase link semantics guarantee UID preservation; if that
                // ever breaks, refuse to carry on as a different identity.
                logger.fault("""
                    auth.link uid changed across link: \
                    before=\(uidBeforeLink, privacy: .public) \
                    after=\(result.user.uid, privacy: .public)
                    """)
                return .failed(message:
                    "Sign-in came back as a different account — nothing was changed. Please try again.")
            }
            uid = result.user.uid
            refreshLinkState()
            logger.info("""
                auth.link linked provider=\(credential.provider, privacy: .public) \
                uid=\(uidBeforeLink, privacy: .public) uid_unchanged=true
                """)
            return .linked
        } catch {
            switch AccountLinking.classifyLinkError(error) {
            case .ownedByAnotherAccount(let existing):
                logger.info("auth.link conflict credential_present=\(existing != nil)")
                return .conflict(existingAccountCredential: existing)
            case .canceled:
                return .canceled
            case .retryable(let message), .other(let message):
                logger.error("auth.link failed: \(error as NSError, privacy: .public)")
                return .failed(message: message)
            }
        }
    }

    /// Sign in to the account that already owns the provider identity (the
    /// Apple ID or Google account) — the one deliberate exception to the
    /// no-UID-churn rule, and it only runs after SignInSheet has shown the
    /// explicit warning and the user confirmed.
    /// Rooms scanned on this phone under the old anonymous UID stop being
    /// reachable from this install afterward.
    func switchToExistingAccount(_ credential: AuthCredential) async throws {
        guard isConfigured else { throw AuthError.notConfigured }
        let uidBefore = Auth.auth().currentUser?.uid ?? "none"
        let result = try await Auth.auth().signIn(with: credential)
        uid = result.user.uid
        refreshLinkState()
        logger.notice("""
            auth.switch user-confirmed account switch: \
            from=\(uidBefore, privacy: .public) \
            to=\(result.user.uid, privacy: .public)
            """)
    }

    /// Recompute the published link state from the current user's provider
    /// list (the pure LinkedProviders derivation). Call after every auth-state
    /// mutation.
    private func refreshLinkState() {
        guard isConfigured, let user = Auth.auth().currentUser else {
            isAppleLinked = false
            isGoogleLinked = false
            appleEmail = nil
            googleEmail = nil
            return
        }
        let providers = LinkedProviders(providerIDs: user.providerData.map(\.providerID))
        isAppleLinked = providers.apple
        isGoogleLinked = providers.google
        let apple = user.providerData.first {
            $0.providerID == LinkedProviders.appleProviderID
        }
        appleEmail = providers.apple ? (apple?.email ?? user.email) : nil
        let google = user.providerData.first {
            $0.providerID == LinkedProviders.googleProviderID
        }
        googleEmail = providers.google ? (google?.email ?? user.email) : nil
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

    // MARK: - After deletion

    /// Clear the local session once the SERVER has deleted this identity.
    ///
    /// THIS IS NOT A SIGN-OUT CONTROL, and the name is long so it cannot be
    /// mistaken for one. There is deliberately no sign-out in this app
    /// (decision 0064): `signInIfNeeded` runs at launch, so signing out would
    /// mint a fresh anonymous UID and read to the user as losing every room.
    /// That objection does not apply here, because the rooms are already gone
    /// and a fresh UID is exactly the correct next state.
    ///
    /// The alternative is to clear nothing and let the next token refresh
    /// discover that the user is absent. That path works, but it is the
    /// decision 0139 churn mechanism arriving unannounced — the SDK drops its
    /// own Keychain credential on rejection and the app silently mints a new
    /// UID, which is indistinguishable from the identity-destroying bug that
    /// mechanism causes when nobody asked for it. Doing it here, deliberately
    /// and at a known moment, is what keeps the instrumented churn reading
    /// honest.
    ///
    /// Best-effort by design: a throwing sign-out must not turn a completed
    /// deletion into a failure the user sees. The account is gone either way,
    /// and the stale credential cannot outlive its next refresh.
    func signOutAfterDeletion() {
        guard isConfigured else { return }
        try? Auth.auth().signOut()
        uid = nil
        isAppleLinked = false
        isGoogleLinked = false
        appleEmail = nil
        googleEmail = nil
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
