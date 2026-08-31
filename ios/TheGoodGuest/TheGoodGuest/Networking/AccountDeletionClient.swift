/// HTTP client for DELETE /account on api-public — the complete erasure of the
/// caller's account and everything in it.
///
/// This is the route App Store guideline 5.1.1(v) requires an in-app path to.
/// The server half has been complete since decision 0095; until this client
/// there was no call site anywhere in the app, so the only deletion a person
/// had was one they could not reach from the phone that made their rooms.
///
/// THE TOKEN IS THE TARGET. There is no uid parameter — the route erases
/// whoever the bearer token says you are, and cannot be pointed at anyone else.
/// `confirm_user_id` in the body is an ACCIDENT control rather than a security
/// one (the verified token is already the security control): echoing your own
/// uid back is something only deliberate code does, so a client bug that fires
/// the wrong request cannot erase an account by accident.
///
/// RETRYING A DESTRUCTIVE CALL IS SAFE HERE, AND ONLY BECAUSE THE SERVER SAYS
/// SO. The ladder below looks wrong at a glance — automatic retries on an
/// irreversible whole-account erase — and it is correct for two documented
/// reasons, both of which would have to survive any server change:
///
///   1. The route is idempotent and resumable. A pass that stops partway
///      touches no Firestore record before storage is clear, so nothing is
///      stranded and the same call re-derives the same plan.
///   2. An already-absent user is SUCCESS, not failure (decision 0103). An ID
///      token stays valid for up to an hour after its user is deleted, so a
///      retry inside that window returns 200 rather than 500.
///
/// If either stops being true, this ladder becomes a bug — delete it, don't
/// tune it.
///
/// WHAT A REPEATED PASS COUNTS. Because of (2), a retry after a lost response
/// legitimately returns 200 with every count at zero: the first call did the
/// work, and this one found nothing left. The counts therefore describe THIS
/// PASS, never what the account held, and no surface may render them as
/// "you had N rooms". `DeleteAccountCopy` is where that rule is enforced.
///
/// Read by: DeleteAccountView.

import Foundation

// MARK: - Outcome

/// What one pass removed. Every field is what THIS call deleted — see the
/// header on why that is not the same as what the account contained.
nonisolated struct AccountDeletionCounts: Decodable, Equatable {
    var rooms: Int = 0
    var conversations: Int = 0
    var conversationMessages: Int = 0
    var designSpecs: Int = 0
    var uploadSessions: Int = 0
    var files: Int = 0

    enum CodingKeys: String, CodingKey {
        case rooms
        case conversations
        case conversationMessages = "conversation_messages"
        case designSpecs = "design_specs"
        case uploadSessions = "upload_sessions"
        case files
    }

    /// True when this pass removed nothing at all. Not an error — it is what a
    /// resumed deletion and an already-empty account both look like.
    var isEmpty: Bool {
        rooms == 0 && conversations == 0 && conversationMessages == 0
            && designSpecs == 0 && uploadSessions == 0 && files == 0
    }

    /// Everything the user would recognise as theirs, as one number. Upload
    /// sessions are bookkeeping and are deliberately excluded — a person does
    /// not think of them as a possession, and including them inflates a figure
    /// shown next to the word "deleted".
    var belongings: Int {
        rooms + conversations + conversationMessages + designSpecs + files
    }
}

/// The two ways the route can succeed. Neither is an error; they differ in
/// whether another pass is owed.
nonisolated enum AccountDeletionOutcome: Equatable {
    /// 200 — the pass completed and the identity is gone.
    case complete(AccountDeletionCounts)
    /// 202 — storage errors stopped the pass before any Firestore record was
    /// touched. Nothing is stranded; the same call resumes it. The identity is
    /// still alive, so the user is still signed in and still owns their rooms.
    case partial(AccountDeletionCounts, detail: String)
}

// MARK: - Errors

/// Errors surfaced by AccountDeletionClient. Equatable so callers can pin the
/// exact mapping in tests rather than matching on a message.
nonisolated enum AccountDeletionError: LocalizedError, Equatable {
    /// 401 that survived one fresh token — the identity is not usable.
    case unauthorized
    /// 400 confirmation_mismatch — the body's uid did not match the token's.
    /// A client bug by construction: this client fills both from one source.
    case confirmationMismatch
    /// 503 — the service has no datastore configured. Local dev only; the
    /// docstring on the route says it is never returned in production.
    case unavailable
    /// 5xx or network failure with the retry ladder exhausted. Nothing was
    /// left in a partial state — the route says so explicitly — so the honest
    /// surface is "try again", never "some of it went".
    case serverError(Int)
    /// A success status whose body did not decode.
    case decodeFailed(String)
    /// Any other status.
    case unexpectedStatus(Int)

    var errorDescription: String? {
        switch self {
        case .unauthorized:        return "Account deletion: 401 Unauthorized — token invalid."
        case .confirmationMismatch: return "Account deletion: 400 — confirm_user_id did not match the token."
        case .unavailable:         return "Account deletion: 503 — the service has no datastore."
        case .serverError(let c):  return "Account deletion: \(c) server error."
        case .decodeFailed(let d): return "Account deletion: could not decode — \(d)"
        case .unexpectedStatus(let c): return "Account deletion: unexpected \(c)."
        }
    }
}

// MARK: - Wire bodies

private nonisolated struct AccountDeleteRequestBody: Encodable {
    let confirmUserId: String
    enum CodingKeys: String, CodingKey { case confirmUserId = "confirm_user_id" }
}

/// Both success bodies share a shape; `deleted` is what separates them.
private nonisolated struct AccountDeleteResponseBody: Decodable {
    let deleted: Bool
    let identityDeleted: Bool
    let counts: AccountDeletionCounts
    let detail: String?

    enum CodingKeys: String, CodingKey {
        case deleted
        case identityDeleted = "identity_deleted"
        case counts
        case detail
    }
}

// MARK: - Client

/// Actor-isolated HTTP client. Thread-safe by construction.
/// Use AccountDeletionClient.shared in production.
actor AccountDeletionClient {

    static let shared = AccountDeletionClient()

    private let baseURL: URL
    private let urlSession: URLSession

    // Same ladder as ScenesListClient and UploadSessionClient (decision 0038).
    private let maxRetries   = 3
    private let baseDelaySec = 1.0
    private let maxDelaySec  = 30.0

    /// Longer than the scenes list's 30 s: this pass walks every collection and
    /// every GCS prefix the user owns by hand, because Firestore does not
    /// cascade. A room-heavy account is legitimately slow, and a timeout that
    /// fires mid-pass turns a working deletion into a retry the user watches.
    static let timeoutSec: TimeInterval = 120

    private var sleeper: @Sendable (TimeInterval) async -> Void = { seconds in
        try? await Task.sleep(nanoseconds: UInt64(seconds * 1_000_000_000))
    }

    init(
        baseURL: URL = NetworkConfig.apiPublicBaseURL,
        urlSession: URLSession = .shared,
        sleeper: (@Sendable (TimeInterval) async -> Void)? = nil
    ) {
        self.baseURL    = baseURL
        self.urlSession = urlSession
        if let sleeper { self.sleeper = sleeper }
    }

    // MARK: - Public API

    /// Erase the caller's account.
    ///
    /// - Parameters:
    ///   - userID: The caller's own uid, echoed to the server as the accident
    ///     control. Pass `AuthManager.shared.currentUID`.
    ///   - tokenProvider: Called for a Firebase ID token, and re-called once on
    ///     a 401. Pass `{ try await AuthManager.shared.currentIDToken() }`.
    /// - Returns: `.complete` when the identity is gone, `.partial` when
    ///   another pass is owed. Both are successes.
    func delete(
        userID: String,
        tokenProvider: @Sendable () async throws -> String
    ) async throws -> AccountDeletionOutcome {
        let idToken = try await tokenProvider()
        do {
            return try await requestWithBackoff(userID: userID, idToken: idToken, attempt: 0)
        } catch AccountDeletionError.unauthorized {
            // One fresh token, one retry — the SDK will have refreshed by now.
            //
            // This is also the path a deletion whose response was lost takes:
            // the token outlives the user by up to an hour, so the retry
            // reaches a server that finds nothing left and answers 200 with
            // zero counts. That is a success, and the counts rule in the
            // header is what stops it reading as "there was nothing there".
            let fresh = try await tokenProvider()
            return try await requestWithBackoff(userID: userID, idToken: fresh, attempt: 0)
        }
    }

    /// The URL one `delete` call would request. Internal so tests can pin the
    /// path directly rather than inferring it from a stub's recording.
    static func deleteURL(baseURL: URL = NetworkConfig.apiPublicBaseURL) -> URL {
        baseURL.appendingPathComponent("account")
    }

    // MARK: - Private

    private func requestWithBackoff(
        userID: String,
        idToken: String,
        attempt: Int
    ) async throws -> AccountDeletionOutcome {
        do {
            return try await executeOnce(userID: userID, idToken: idToken)
        } catch AccountDeletionError.serverError where attempt < maxRetries {
            let jitter = Double.random(in: 0..<1.0)
            let delay  = min(baseDelaySec * pow(2.0, Double(attempt)) + jitter, maxDelaySec)
            await sleeper(delay)
            return try await requestWithBackoff(
                userID: userID, idToken: idToken, attempt: attempt + 1
            )
        }
        // Everything else propagates immediately.
    }

    private func executeOnce(
        userID: String,
        idToken: String
    ) async throws -> AccountDeletionOutcome {
        var request = URLRequest(url: Self.deleteURL(baseURL: baseURL))
        request.httpMethod      = "DELETE"
        request.timeoutInterval = Self.timeoutSec
        request.setValue("Bearer \(idToken)", forHTTPHeaderField: "Authorization")
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try? JSONEncoder().encode(
            AccountDeleteRequestBody(confirmUserId: userID)
        )

        let (data, response): (Data, URLResponse)
        do {
            (data, response) = try await urlSession.data(for: request)
        } catch {
            // Network-layer failure → retryable, same as a 5xx. Safe for the
            // two reasons in the header, not because a lost DELETE is harmless.
            throw AccountDeletionError.serverError(0)
        }

        guard let http = response as? HTTPURLResponse else {
            throw AccountDeletionError.serverError(0)
        }

        switch http.statusCode {
        case 200, 202:
            let body: AccountDeleteResponseBody
            do {
                body = try JSONDecoder().decode(AccountDeleteResponseBody.self, from: data)
            } catch {
                throw AccountDeletionError.decodeFailed(error.localizedDescription)
            }
            // The BODY decides, not the status. A 200 whose `deleted` is false
            // would be a server contradiction; trusting the body means the
            // screen never claims an identity is gone on a status code alone.
            if body.deleted && body.identityDeleted {
                return .complete(body.counts)
            }
            return .partial(body.counts, detail: body.detail ?? "")
        case 400:
            throw AccountDeletionError.confirmationMismatch
        case 401:
            throw AccountDeletionError.unauthorized
        case 503:
            throw AccountDeletionError.unavailable
        case 500...599:
            throw AccountDeletionError.serverError(http.statusCode)
        default:
            throw AccountDeletionError.unexpectedStatus(http.statusCode)
        }
    }
}
