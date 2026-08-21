/// HTTP client for GET /scenes on api-public — the caller's own rooms, newest
/// first.
///
/// This is the fetch four surfaces were staged against and none could reach:
/// the recent-rooms strip, RoomsListView, and WhySignInSheet's count (the
/// history surfaces of design spec §8/§9). Before it, iOS spoke to exactly two
/// routes — /captures/{id}/upload_session and /scenes/by-bundle/{id} — and
/// could only ever ask about a bundle it had just sent, never about what it had
/// already sent.
///
/// SCOPED TO THE TOKEN, AND ONLY EVER TO THE TOKEN. api-public documents that
/// /scenes has no cross-user listing, and that is the property decision 0216
/// rests on: a count of rooms held by an account the caller is NOT cannot be
/// obtained, by construction, and no parameter here should ever be added to try.
/// This client asks one question — "what have I sent?" — for one identity, the
/// one the token proves.
///
/// Error posture mirrors UploadSessionClient (decision 0038): 5xx and network
/// failures retry with exponential backoff + jitter, a 401 buys exactly one
/// fresh token and one retry, and everything else is fatal to the call. What it
/// deliberately does NOT do is convert a failure into an empty list — a caller
/// that cannot tell "no rooms" from "could not ask" will assert the first while
/// meaning the second, and every surface downstream of this states a count to
/// the user. `[]` here means the server said so.
///
/// Read by: RoomsStore.

import Foundation

// MARK: - Errors

/// Errors surfaced by ScenesListClient. Equatable so callers can pin the exact
/// mapping in tests rather than matching on a message.
enum ScenesListError: LocalizedError, Equatable {
    /// 401 that survived one fresh token — the identity is not usable.
    case unauthorized
    /// 400 or 422 — a client-side bug (bad limit, missing header).
    case clientError(Int)
    /// 5xx or network failure with the retry ladder exhausted.
    case serverError(Int)
    /// 200 whose body did not decode.
    case decodeFailed(String)
    /// Any other status.
    case unexpectedStatus(Int)

    var errorDescription: String? {
        switch self {
        case .unauthorized:            return "Scenes list: 401 Unauthorized — token invalid."
        case .clientError(let code):   return "Scenes list: \(code) client error."
        case .serverError(let code):   return "Scenes list: \(code) server error."
        case .decodeFailed(let detail): return "Scenes list: could not decode — \(detail)"
        case .unexpectedStatus(let code): return "Scenes list: unexpected \(code)."
        }
    }
}

// MARK: - Wire body

/// The 200 body: `{"scenes": [<same per-scene shape as /scenes/by-bundle>]}`.
///
/// Decoded through SceneResponse rather than a parallel type, so the lenient
/// SceneStatus decode (unknown wire values → .unknown(raw), never a throw)
/// covers this route too. A backend that adds a status must not be able to
/// blank the user's room list.
private nonisolated struct ScenesListBody: Decodable {
    let scenes: [SceneResponse]
}

// MARK: - Client

/// Actor-isolated HTTP client. Thread-safe by construction.
/// Use ScenesListClient.shared in production.
actor ScenesListClient {

    static let shared = ScenesListClient()

    /// The server's documented range for `limit` (1...100; outside it is a 400).
    /// Requests are CLAMPED to it rather than validated, so no caller can
    /// manufacture a 400 that reads to the user as "your rooms are gone".
    static let limitRange = 1...100
    static let defaultLimit = 50

    private let baseURL: URL
    private let urlSession: URLSession

    // Retry policy for 5xx / network errors — same ladder as UploadSessionClient.
    private let maxRetries   = 3
    private let baseDelaySec = 1.0
    private let maxDelaySec  = 30.0

    /// Per-request timeout. Short by upload standards on purpose: this is a
    /// small read behind a screen the user is looking at, and a fetch that
    /// hangs past this is better surfaced as trouble they can retry than held
    /// open under a spinner.
    static let timeoutSec: TimeInterval = 30

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

    /// List the caller's scenes, newest first.
    ///
    /// - Parameters:
    ///   - limit: Max scenes returned. Clamped to `limitRange`.
    ///   - tokenProvider: Called for a Firebase ID token, and re-called once on
    ///     a 401. Pass `{ try await AuthManager.shared.currentIDToken() }`.
    /// - Returns: The caller's scenes. An empty array means the server said the
    ///   caller has none — never that the question could not be asked.
    func list(
        limit: Int = ScenesListClient.defaultLimit,
        tokenProvider: @Sendable () async throws -> String
    ) async throws -> [SceneResponse] {
        let idToken = try await tokenProvider()
        do {
            return try await requestWithBackoff(limit: limit, idToken: idToken, attempt: 0)
        } catch ScenesListError.unauthorized {
            // One fresh token, one retry — the SDK will have refreshed by now.
            let fresh = try await tokenProvider()
            return try await requestWithBackoff(limit: limit, idToken: fresh, attempt: 0)
        }
    }

    /// The URL one `list(limit:)` call would request.
    ///
    /// Internal rather than private so the clamp can be pinned directly: the
    /// whole point of clamping is which bytes go on the wire, and a test that
    /// can only observe the response cannot tell a clamped request from a
    /// lucky one.
    static func listURL(baseURL: URL = NetworkConfig.apiPublicBaseURL, limit: Int) -> URL {
        let clamped = min(max(limit, limitRange.lowerBound), limitRange.upperBound)
        var components = URLComponents(
            url: baseURL.appendingPathComponent("scenes"),
            resolvingAgainstBaseURL: false
        )!
        components.queryItems = [URLQueryItem(name: "limit", value: String(clamped))]
        return components.url!
    }

    // MARK: - Private

    private func requestWithBackoff(
        limit: Int,
        idToken: String,
        attempt: Int
    ) async throws -> [SceneResponse] {
        do {
            return try await executeOnce(limit: limit, idToken: idToken)
        } catch ScenesListError.serverError where attempt < maxRetries {
            let jitter = Double.random(in: 0..<1.0)
            let delay  = min(baseDelaySec * pow(2.0, Double(attempt)) + jitter, maxDelaySec)
            await sleeper(delay)
            return try await requestWithBackoff(limit: limit, idToken: idToken, attempt: attempt + 1)
        }
        // Everything else propagates immediately.
    }

    private func executeOnce(limit: Int, idToken: String) async throws -> [SceneResponse] {
        var request = URLRequest(url: Self.listURL(baseURL: baseURL, limit: limit))
        request.httpMethod      = "GET"
        request.timeoutInterval = Self.timeoutSec
        request.setValue("Bearer \(idToken)", forHTTPHeaderField: "Authorization")

        let (data, response): (Data, URLResponse)
        do {
            (data, response) = try await urlSession.data(for: request)
        } catch {
            // Network-layer failure → retryable, same as a 5xx.
            throw ScenesListError.serverError(0)
        }

        guard let http = response as? HTTPURLResponse else {
            throw ScenesListError.serverError(0)
        }

        switch http.statusCode {
        case 200:
            do {
                return try JSONDecoder().decode(ScenesListBody.self, from: data).scenes
            } catch {
                throw ScenesListError.decodeFailed(error.localizedDescription)
            }
        case 401:
            throw ScenesListError.unauthorized
        case 400, 422:
            throw ScenesListError.clientError(http.statusCode)
        case 500...599:
            throw ScenesListError.serverError(http.statusCode)
        default:
            throw ScenesListError.unexpectedStatus(http.statusCode)
        }
    }
}
