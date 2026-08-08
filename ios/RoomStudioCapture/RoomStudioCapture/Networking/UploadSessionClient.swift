/// HTTP client for POST /captures/{bundle_id}/upload_session on api-public.
///
/// Accepts a token provider closure (rather than a raw token string) so it
/// can re-fetch a fresh token on a 401 and retry once without the caller
/// needing to wire the retry logic. 5xx and network errors are retried with
/// exponential backoff + jitter (decision 0037).
///
/// Return value is [UploadSessionEntry], keyed by relative_path. The server
/// gives NO ordering guarantees — always map by relative_path, never by index.
///
/// Read by: UploadCoordinator.

import Foundation

// MARK: - Request / response types

/// One entry in the request body sent to POST /upload_session.
/// Named distinctly from UploadSessionEntry (the response type).
nonisolated struct UploadManifestEntry: Codable, Equatable, Sendable {
    let relativePath: String
    let expectedSizeBytes: Int

    enum CodingKeys: String, CodingKey {
        case relativePath      = "relative_path"
        case expectedSizeBytes = "expected_size_bytes"
    }
}

/// One entry in the 200 response from POST /upload_session.
/// session_uri is a GCS resumable URI — it IS the upload credential.
nonisolated struct UploadSessionEntry: Codable, Sendable {
    let relativePath: String
    let sessionUri: String

    enum CodingKeys: String, CodingKey {
        case relativePath = "relative_path"
        case sessionUri   = "session_uri"
    }
}

// MARK: - Errors

/// Errors surfaced by UploadSessionClient.
enum UploadSessionError: LocalizedError {
    /// 401 — token invalid or expired; retried once internally.
    case unauthorized
    /// 403 — a different UID already owns this bundle_id. Fatal; do not retry.
    case forbidden(String)
    /// 400 or 422 — client-side bug (bad manifest path, missing header).
    /// Fatal; do not retry. Log and surface as a programming error.
    case clientError(Int, String)
    /// 5xx or network error — potentially transient; retried with backoff.
    case serverError(Int, String)
    /// 429 — the caller's per-UID UTC-day mint quota is exhausted (decision 0087).
    /// NOT terminal: it lifts on its own at `resetsAt` (the next UTC midnight).
    /// Thrown only once the stated wait exceeds what is sane to hold in-process;
    /// short waits are slept through inside the client and never surface.
    case rateLimited(retryAfter: TimeInterval?, resetsAt: Date?, detail: String)
    /// Unexpected HTTP status.
    case unexpectedStatus(Int, String)

    var errorDescription: String? {
        switch self {
        case .unauthorized:
            return "Upload session: 401 Unauthorized — token invalid."
        case .forbidden(let msg):
            return "Upload session: 403 Forbidden — \(msg)"
        case .clientError(let code, let body):
            return "Upload session: \(code) client error — \(body)"
        case .serverError(let code, let body):
            return "Upload session: \(code) server error — \(body)"
        case .rateLimited(let retryAfter, let resetsAt, let detail):
            let wait = retryAfter.map { "\(Int($0))s" } ?? "unstated"
            return "Upload session: 429 rate limited (retry after \(wait), resets \(resetsAt.map(String.init(describing:)) ?? "unknown")) — \(detail)"
        case .unexpectedStatus(let code, let body):
            return "Upload session: unexpected \(code) — \(body)"
        }
    }
}

/// The 429 body api-public sends on the daily mint quota (decision 0087):
/// `{"error": "rate_limited", "detail": "…", "resets_at": "<iso8601>"}`.
/// Decoded leniently — a missing or unparseable `resets_at` degrades to "no
/// stated time", never to a failure to recognise the rate limit itself.
private nonisolated struct RateLimitBody: Decodable {
    let detail: String?
    let resetsAt: String?

    enum CodingKeys: String, CodingKey {
        case detail
        case resetsAt = "resets_at"
    }
}

// MARK: - Private request body

// nonisolated: encoded from the client actor's context — the target's
// MainActor default isolation would make the Encodable conformance
// actor-crossing (a Swift 6 error).
private nonisolated struct UploadSessionRequestBody: Encodable {
    let manifest: [UploadManifestEntry]
    let fcmToken: String?
    /// Decision 0116's second input. The manifest says WHAT the client intends to
    /// upload; this says WHETHER the URIs it already holds still work — one input
    /// could not carry both questions, which is why a POST retry and a retry of a
    /// dead session were indistinguishable.
    ///
    /// nil, NOT false, on the ordinary path: the synthesized encoder uses
    /// encodeIfPresent for an Optional, so an ordinary mint puts the key nowhere
    /// on the wire and its request stays byte-identical to the deployed 0035
    /// shape. (The server reads absent and null the same way; this is about not
    /// changing a request that already works.) Pinned by
    /// UploadSessionForceRemintTests.
    let forceRemint: Bool?

    enum CodingKeys: String, CodingKey {
        case manifest
        case fcmToken    = "fcm_token"
        case forceRemint = "force_remint"
    }
}

// MARK: - Client

/// Actor-isolated HTTP client. Thread-safe by construction; safe to call from
/// any async context. Use UploadSessionClient.shared for production.
actor UploadSessionClient {

    static let shared = UploadSessionClient()

    private let baseURL: URL
    private let urlSession: URLSession

    // Retry policy for 5xx / network errors (decision 0038).
    private let maxRetries      = 3
    private let baseDelaySec    = 1.0
    private let maxDelaySec     = 30.0

    /// Longest server-directed wait this client will sleep through in-process on a
    /// 429, mirroring BlobUploadManager.maxRetryAfterHoldSec exactly — one number,
    /// one meaning, on both paths that honor Retry-After.
    ///
    /// It matters more here than it does for blobs: api-public's quota resets at
    /// the next UTC MIDNIGHT, so the stated wait is normally hours. Sleeping that
    /// is not an option (the app would be long dead), and retrying sooner than the
    /// server asked is not either — so anything past this cap is surfaced to the
    /// user with the time it lifts, and nothing is retried behind their back. The
    /// cap is not dead code: a mint attempted just before midnight gets a wait of
    /// a few seconds, and that one is worth simply waiting out.
    static let maxRetryAfterHoldSec: TimeInterval = 60.0

    /// How many times a single mint may sleep out a short 429 before giving up and
    /// surfacing it. Bounded for the same reason the 5xx ladder is: a server stuck
    /// answering "one more second" must not hold the send forever.
    static let maxRateLimitHolds = 2

    /// Per-request timeout for the mint POST. MUST exceed api-public's Cloud
    /// Run request ceiling (120 s): a local timeout below the server's own
    /// limit manufactures a failure for a mint the server may still complete.
    /// Measured live (RP-6 Gate 3): a ~2,200-path long-walk mint died twice
    /// over — client abandoned at URLSession's default 60 s, server 504'd at
    /// its 120 s ceiling — and the mint stores nothing on abort, so a retry
    /// restarts from zero. The client half of the fix is outliving the server
    /// window; the server half (UPLOAD_SESSION_MINT_CONCURRENCY bump) is an
    /// env-only revision recorded for RP-8.
    static let mintTimeoutSec: TimeInterval = 180

    /// Returns "now". Injected in tests so a 429's stated wait can be evaluated
    /// against a fixed clock (the HTTP-date form is relative to it).
    private var clock: () -> Date = { Date() }

    /// Suspends between attempts. Injected in tests to assert the schedule —
    /// including which 429 waits are slept through — without real waiting.
    private var sleeper: @Sendable (TimeInterval) async -> Void = { seconds in
        try? await Task.sleep(nanoseconds: UInt64(seconds * 1_000_000_000))
    }

    init(
        baseURL: URL = NetworkConfig.apiPublicBaseURL,
        urlSession: URLSession = .shared,
        clock: @escaping () -> Date = { Date() },
        sleeper: (@Sendable (TimeInterval) async -> Void)? = nil
    ) {
        self.baseURL    = baseURL
        self.urlSession = urlSession
        self.clock      = clock
        if let sleeper { self.sleeper = sleeper }
    }

    // MARK: - Public API

    /// Create an upload session for one bundle.
    ///
    /// - Parameters:
    ///   - bundleId: Lowercased canonical UUIDv4 (CaptureManager.bundleIdString).
    ///   - manifest: Ordered artifact list from ManifestBuilder.build(outputDir:).
    ///   - tokenProvider: Called to obtain a fresh idToken. Re-called on 401.
    ///     Pass `{ try await AuthManager.shared.currentIDToken() }`.
    ///   - fcmToken: FCM registration token for terminal-state push
    ///     notifications.
    ///   - forceRemint: Decision 0116. Declares that the session URIs the caller
    ///     already holds are dead, so the server must mint fresh ones for the
    ///     same paths instead of replaying the stored ones. Set it ONLY on
    ///     evidence — a 410, or a `failed_incomplete` scene naming missing paths
    ///     — never on an ordinary POST retry: each forced mint spends a unit of
    ///     the caller's daily mint quota, and the replay it suppresses is what
    ///     makes an ordinary retry free.
    ///
    /// - Returns: Array of UploadSessionEntry. Map by relativePath — server
    ///   gives no ordering guarantee.
    func createUploadSession(
        bundleId: String,
        manifest: [UploadManifestEntry],
        tokenProvider: @Sendable () async throws -> String,
        fcmToken: String? = nil,
        forceRemint: Bool = false
    ) async throws -> [UploadSessionEntry] {
        var idToken = try await tokenProvider()

        do {
            return try await requestWithBackoff(
                bundleId: bundleId,
                manifest: manifest,
                idToken: idToken,
                fcmToken: fcmToken,
                forceRemint: forceRemint,
                attempt: 0
            )
        } catch UploadSessionError.unauthorized {
            // Single 401 retry with a fresh token; the SDK will have refreshed by now.
            idToken = try await tokenProvider()
            return try await requestWithBackoff(
                bundleId: bundleId,
                manifest: manifest,
                idToken: idToken,
                fcmToken: fcmToken,
                forceRemint: forceRemint,
                attempt: 0
            )
        }
    }

    // MARK: - Wire body

    /// The POST body, encoded.
    ///
    /// Factored out and left INTERNAL (not private) so the wire shape can be
    /// pinned directly instead of inferred from an observed request — the whole
    /// point of `forceRemint` being Optional is what it does to the bytes, and a
    /// test that cannot see the bytes cannot pin it.
    static func encodedRequestBody(
        manifest: [UploadManifestEntry],
        fcmToken: String?,
        forceRemint: Bool
    ) throws -> Data {
        try JSONEncoder().encode(UploadSessionRequestBody(
            manifest: manifest,
            fcmToken: fcmToken,
            // false → nil → the key is absent. See UploadSessionRequestBody.
            forceRemint: forceRemint ? true : nil
        ))
    }

    // MARK: - Private

    private func requestWithBackoff(
        bundleId: String,
        manifest: [UploadManifestEntry],
        idToken: String,
        fcmToken: String?,
        forceRemint: Bool,
        attempt: Int,
        rateLimitHolds: Int = 0
    ) async throws -> [UploadSessionEntry] {
        do {
            return try await executeOnce(
                bundleId: bundleId,
                manifest: manifest,
                idToken: idToken,
                fcmToken: fcmToken,
                forceRemint: forceRemint
            )
        } catch UploadSessionError.serverError where attempt < maxRetries {
            let jitter = Double.random(in: 0..<1.0)
            let delay  = min(baseDelaySec * pow(2.0, Double(attempt)) + jitter, maxDelaySec)
            await sleeper(delay)
            return try await requestWithBackoff(
                bundleId: bundleId,
                manifest: manifest,
                idToken: idToken,
                fcmToken: fcmToken,
                forceRemint: forceRemint,
                attempt: attempt + 1,
                rateLimitHolds: rateLimitHolds
            )
        } catch UploadSessionError.rateLimited(let retryAfter, let resetsAt, let detail) {
            // Honor the server's stated wait the way the blob PUTs do — but only
            // when it is short enough to be worth holding. The quota rolls at UTC
            // midnight, so the normal answer is hours: that one is surfaced with
            // its reset time rather than slept on or retried early.
            guard let retryAfter,
                  retryAfter <= Self.maxRetryAfterHoldSec,
                  rateLimitHolds < Self.maxRateLimitHolds
            else {
                throw UploadSessionError.rateLimited(
                    retryAfter: retryAfter, resetsAt: resetsAt, detail: detail)
            }
            // Jitter on top: Retry-After is a minimum, not an appointment, and
            // several devices told the same second must not return in lockstep.
            await sleeper(retryAfter + Double.random(in: 0..<1.0))
            return try await requestWithBackoff(
                bundleId: bundleId,
                manifest: manifest,
                idToken: idToken,
                fcmToken: fcmToken,
                forceRemint: forceRemint,
                attempt: attempt,
                rateLimitHolds: rateLimitHolds + 1
            )
        }
        // All other errors propagate immediately.
    }

    private func executeOnce(
        bundleId: String,
        manifest: [UploadManifestEntry],
        idToken: String,
        fcmToken: String?,
        forceRemint: Bool
    ) async throws -> [UploadSessionEntry] {
        let url = baseURL
            .appendingPathComponent("captures")
            .appendingPathComponent(bundleId)
            .appendingPathComponent("upload_session")

        var request           = URLRequest(url: url)
        request.httpMethod    = "POST"
        request.timeoutInterval = Self.mintTimeoutSec
        request.setValue("application/json",    forHTTPHeaderField: "Content-Type")
        request.setValue("Bearer \(idToken)",   forHTTPHeaderField: "Authorization")

        request.httpBody = try Self.encodedRequestBody(
            manifest: manifest, fcmToken: fcmToken, forceRemint: forceRemint
        )

        let (data, response): (Data, URLResponse)
        do {
            (data, response) = try await urlSession.data(for: request)
        } catch {
            // Network-layer failure (no connectivity, timeout, etc.) → treat as 5xx.
            throw UploadSessionError.serverError(0, error.localizedDescription)
        }

        guard let http = response as? HTTPURLResponse else {
            throw UploadSessionError.serverError(0, "Non-HTTP response")
        }

        let body_str = String(data: data, encoding: .utf8) ?? ""
        switch http.statusCode {
        case 200:
            return try JSONDecoder().decode([UploadSessionEntry].self, from: data)
        case 401:
            throw UploadSessionError.unauthorized
        case 403:
            throw UploadSessionError.forbidden(body_str)
        case 400, 422:
            throw UploadSessionError.clientError(http.statusCode, body_str)
        case 429:
            // Decision 0087's per-UID daily mint quota. The header is authoritative
            // for HOW LONG (it is what the retry ladder honors); `resets_at` is what
            // the user is told, so a missing header still yields a usable state.
            let parsed = try? JSONDecoder().decode(RateLimitBody.self, from: data)
            let resetsAt = RetryAfter.parseISO8601(parsed?.resetsAt)
            var retryAfter = RetryAfter.parse(
                http.value(forHTTPHeaderField: "Retry-After"), now: clock())
            if retryAfter == nil, let resetsAt {
                // Fall back to the body: an intermediary that strips headers must
                // not turn a bounded wait into an unbounded one.
                retryAfter = max(0, resetsAt.timeIntervalSince(clock()))
            }
            throw UploadSessionError.rateLimited(
                retryAfter: retryAfter,
                resetsAt: resetsAt,
                detail: parsed?.detail ?? body_str
            )
        case 500...599:
            throw UploadSessionError.serverError(http.statusCode, body_str)
        default:
            throw UploadSessionError.unexpectedStatus(http.statusCode, body_str)
        }
    }
}
