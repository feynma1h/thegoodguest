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
struct UploadManifestEntry: Codable, Equatable, Sendable {
    let relativePath: String
    let expectedSizeBytes: Int

    enum CodingKeys: String, CodingKey {
        case relativePath      = "relative_path"
        case expectedSizeBytes = "expected_size_bytes"
    }
}

/// One entry in the 200 response from POST /upload_session.
/// session_uri is a GCS resumable URI — it IS the upload credential.
struct UploadSessionEntry: Codable, Sendable {
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
        case .unexpectedStatus(let code, let body):
            return "Upload session: unexpected \(code) — \(body)"
        }
    }
}

// MARK: - Private request body

private struct UploadSessionRequestBody: Encodable {
    let manifest: [UploadManifestEntry]
    let fcmToken: String?

    enum CodingKeys: String, CodingKey {
        case manifest
        case fcmToken = "fcm_token"
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

    init(
        baseURL: URL = NetworkConfig.apiPublicBaseURL,
        urlSession: URLSession = .shared
    ) {
        self.baseURL    = baseURL
        self.urlSession = urlSession
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
    ///
    /// - Returns: Array of UploadSessionEntry. Map by relativePath — server
    ///   gives no ordering guarantee.
    func createUploadSession(
        bundleId: String,
        manifest: [UploadManifestEntry],
        tokenProvider: @Sendable () async throws -> String,
        fcmToken: String? = nil
    ) async throws -> [UploadSessionEntry] {
        var idToken = try await tokenProvider()

        do {
            return try await requestWithBackoff(
                bundleId: bundleId,
                manifest: manifest,
                idToken: idToken,
                fcmToken: fcmToken,
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
                attempt: 0
            )
        }
    }

    // MARK: - Private

    private func requestWithBackoff(
        bundleId: String,
        manifest: [UploadManifestEntry],
        idToken: String,
        fcmToken: String?,
        attempt: Int
    ) async throws -> [UploadSessionEntry] {
        do {
            return try await executeOnce(
                bundleId: bundleId,
                manifest: manifest,
                idToken: idToken,
                fcmToken: fcmToken
            )
        } catch UploadSessionError.serverError where attempt < maxRetries {
            let jitter = Double.random(in: 0..<1.0)
            let delay  = min(baseDelaySec * pow(2.0, Double(attempt)) + jitter, maxDelaySec)
            try await Task.sleep(nanoseconds: UInt64(delay * 1_000_000_000))
            return try await requestWithBackoff(
                bundleId: bundleId,
                manifest: manifest,
                idToken: idToken,
                fcmToken: fcmToken,
                attempt: attempt + 1
            )
        }
        // All other errors propagate immediately.
    }

    private func executeOnce(
        bundleId: String,
        manifest: [UploadManifestEntry],
        idToken: String,
        fcmToken: String?
    ) async throws -> [UploadSessionEntry] {
        let url = baseURL
            .appendingPathComponent("captures")
            .appendingPathComponent(bundleId)
            .appendingPathComponent("upload_session")

        var request           = URLRequest(url: url)
        request.httpMethod    = "POST"
        request.setValue("application/json",    forHTTPHeaderField: "Content-Type")
        request.setValue("Bearer \(idToken)",   forHTTPHeaderField: "Authorization")

        let body = UploadSessionRequestBody(manifest: manifest, fcmToken: fcmToken)
        request.httpBody = try JSONEncoder().encode(body)

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
        case 500...599:
            throw UploadSessionError.serverError(http.statusCode, body_str)
        default:
            throw UploadSessionError.unexpectedStatus(http.statusCode, body_str)
        }
    }
}
