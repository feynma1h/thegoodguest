/// Pins the mint path's 429 handling — decision 0038's reserved Retry-After
/// follow-up, made real by decision 0087's per-UID daily mint quota.
///
/// WHY THIS MATTERS: the shipped client classified a 429 as `unexpectedStatus`
/// and gave up. Once api-public began enforcing a quota, that turned a limit
/// which lifts by itself into a dead end the user could only escape by
/// rescanning — into the same cap. What is pinned here is the whole chain: a
/// SHORT stated wait is slept out invisibly (the near-midnight case), a LONG one
/// is surfaced with its reset time and never retried early, and neither is ever
/// silently converted into a retry storm.
///
/// Offline: an URLProtocol stub serves the scripted responses. No network, no
/// real waiting (the sleeper is injected and recorded).

import XCTest
@testable import TheGoodGuestCapture

// MARK: - Scripted transport

/// Serves a queued list of (status, headers, body) and records the requests.
private final class StubProtocol: URLProtocol, @unchecked Sendable {
    struct Response {
        var status: Int
        var headers: [String: String] = [:]
        var body: String = "[]"
    }

    nonisolated(unsafe) private static var script: [Response] = []
    nonisolated(unsafe) private static var served = 0
    private static let lock = NSLock()

    static func load(_ responses: [Response]) {
        lock.lock(); defer { lock.unlock() }
        script = responses
        served = 0
    }
    static var requestCount: Int {
        lock.lock(); defer { lock.unlock() }
        return served
    }
    private static func next() -> Response {
        lock.lock(); defer { lock.unlock() }
        let response = served < script.count ? script[served] : script.last!
        served += 1
        return response
    }

    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }
    override func stopLoading() {}

    override func startLoading() {
        let response = Self.next()
        let http = HTTPURLResponse(url: request.url!, statusCode: response.status,
                                   httpVersion: "HTTP/1.1", headerFields: response.headers)!
        client?.urlProtocol(self, didReceive: http, cacheStoragePolicy: .notAllowed)
        client?.urlProtocol(self, didLoad: Data(response.body.utf8))
        client?.urlProtocolDidFinishLoading(self)
    }
}

final class UploadSessionRateLimitTests: XCTestCase {

    private let now = Date(timeIntervalSince1970: 1_786_147_200)   // 2026-08-08 00:00 UTC
    private let midnight = "2026-08-09T00:00:00+00:00"             // +86400 s
    private var slept: [TimeInterval] = []

    private func makeClient() -> UploadSessionClient {
        let config = URLSessionConfiguration.ephemeral
        config.protocolClasses = [StubProtocol.self]
        let fixedNow = now
        return UploadSessionClient(
            baseURL: URL(string: "https://api.test.invalid")!,
            urlSession: URLSession(configuration: config),
            clock: { fixedNow },
            sleeper: { [weak self] seconds in
                await MainActor.run { self?.slept.append(seconds) }
            }
        )
    }

    private func mint(_ client: UploadSessionClient) async throws -> [UploadSessionEntry] {
        try await client.createUploadSession(
            bundleId: "11111111-2222-4333-8444-555555555555",
            manifest: [UploadManifestEntry(relativePath: "bundle.pb", expectedSizeBytes: 10)],
            tokenProvider: { "token" }
        )
    }

    private func rateLimitBody(_ resetsAt: String? = nil) -> String {
        let resets = resetsAt.map { "\"resets_at\": \"\($0)\", " } ?? ""
        return """
        {"error": "rate_limited", \(resets)"detail": "daily upload-session mint quota (50) exhausted for this account"}
        """
    }

    override func setUp() {
        super.setUp()
        slept = []
    }

    // MARK: - The real production shape: hours until midnight

    func test_longWait_isSurfacedNotSleptAndNotRetried() async throws {
        // What api-public actually sends: the quota rolls at the next UTC midnight,
        // so Retry-After is normally hours.
        StubProtocol.load([.init(status: 429,
                                 headers: ["Retry-After": "86400"],
                                 body: rateLimitBody(midnight))])
        let client = makeClient()

        do {
            _ = try await mint(client)
            XCTFail("expected the rate limit to surface")
        } catch UploadSessionError.rateLimited(let retryAfter, let resetsAt, let detail) {
            XCTAssertEqual(retryAfter, 86400)
            XCTAssertEqual(resetsAt, now.addingTimeInterval(86_400),
                           "the body's resets_at, parsed — the next UTC midnight")
            XCTAssertTrue(detail.contains("quota"), "the server's own detail is carried, not invented")
        }
        XCTAssertEqual(slept, [], "a wait measured in hours must never be slept in-process")
        XCTAssertEqual(StubProtocol.requestCount, 1,
                       "and it must never be retried early — the server said not yet")
    }

    // MARK: - The near-midnight case the hold cap exists for

    func test_shortWait_isSleptThenSucceeds_andNeverReachesTheUser() async throws {
        StubProtocol.load([
            .init(status: 429, headers: ["Retry-After": "5"], body: rateLimitBody(midnight)),
            .init(status: 200, body: #"[{"relative_path": "bundle.pb", "session_uri": "https://gcs/1"}]"#),
        ])
        let client = makeClient()

        let entries = try await mint(client)
        XCTAssertEqual(entries.count, 1)
        XCTAssertEqual(slept.count, 1)
        XCTAssertGreaterThanOrEqual(slept[0], 5, "never retried EARLIER than the server asked")
        XCTAssertLessThan(slept[0], 6, "the jitter on top is bounded to under a second")
        XCTAssertEqual(StubProtocol.requestCount, 2)
    }

    func test_repeatedShortWaits_areBounded() async throws {
        // A server stuck answering "one more second" must not hold the send forever.
        StubProtocol.load([.init(status: 429, headers: ["Retry-After": "1"],
                                 body: rateLimitBody(midnight))])
        let client = makeClient()

        do {
            _ = try await mint(client)
            XCTFail("expected the rate limit to surface once the holds are spent")
        } catch UploadSessionError.rateLimited {
            // expected
        }
        XCTAssertEqual(slept.count, UploadSessionClient.maxRateLimitHolds)
        XCTAssertEqual(StubProtocol.requestCount, UploadSessionClient.maxRateLimitHolds + 1)
    }

    func test_waitExactlyAtTheHoldCap_isStillHeld() async throws {
        StubProtocol.load([
            .init(status: 429,
                  headers: ["Retry-After": "\(Int(UploadSessionClient.maxRetryAfterHoldSec))"],
                  body: rateLimitBody(midnight)),
            .init(status: 200, body: #"[{"relative_path": "bundle.pb", "session_uri": "https://gcs/1"}]"#),
        ])
        _ = try await mint(makeClient())
        XCTAssertEqual(slept.count, 1, "the cap is inclusive — one second past it is the boundary, not this")
    }

    // MARK: - Degraded server answers

    func test_missingRetryAfterHeader_fallsBackToResetsAt() async throws {
        // An intermediary that strips headers must not turn a bounded wait into an
        // unbounded one — the body still names the moment.
        StubProtocol.load([.init(status: 429, body: rateLimitBody(midnight))])
        do {
            _ = try await mint(makeClient())
            XCTFail("expected the rate limit to surface")
        } catch UploadSessionError.rateLimited(let retryAfter, let resetsAt, _) {
            XCTAssertEqual(retryAfter, 86400, "derived from resets_at against the injected clock")
            XCTAssertNotNil(resetsAt)
        }
    }

    func test_noResetsAtAtAll_isStillRecognisedAsARateLimit() async throws {
        // Degrades to "no stated time" — never to an unrecognised status that the
        // caller would treat as a bug.
        StubProtocol.load([.init(status: 429, body: rateLimitBody())])
        do {
            _ = try await mint(makeClient())
            XCTFail("expected the rate limit to surface")
        } catch UploadSessionError.rateLimited(let retryAfter, let resetsAt, let detail) {
            XCTAssertNil(retryAfter)
            XCTAssertNil(resetsAt)
            XCTAssertFalse(detail.isEmpty)
        }
        XCTAssertEqual(slept, [], "an unstated wait is not a licence to retry immediately")
    }

    func test_unparseableBody_stillClassifiesAs429() async throws {
        StubProtocol.load([.init(status: 429, headers: ["Retry-After": "3600"], body: "not json")])
        do {
            _ = try await mint(makeClient())
            XCTFail("expected the rate limit to surface")
        } catch UploadSessionError.rateLimited(let retryAfter, _, _) {
            XCTAssertEqual(retryAfter, 3600, "the header alone is enough to classify and bound it")
        }
    }

    // MARK: - The classification the shipped build got wrong

    func test_429IsNoLongerAnUnexpectedStatus() async throws {
        StubProtocol.load([.init(status: 429, headers: ["Retry-After": "86400"],
                                 body: rateLimitBody(midnight))])
        do {
            _ = try await mint(makeClient())
            XCTFail("expected an error")
        } catch UploadSessionError.unexpectedStatus {
            XCTFail("429 must classify as rateLimited — treating it as unexpected is the shipped defect")
        } catch UploadSessionError.rateLimited {
            // the fix
        }
    }

    func test_otherStatusesAreUnaffected() async throws {
        StubProtocol.load([.init(status: 403, body: #"{"error": "forbidden"}"#)])
        do {
            _ = try await mint(makeClient())
            XCTFail("expected an error")
        } catch UploadSessionError.forbidden {
            // unchanged
        }
        XCTAssertEqual(slept, [])
    }
}
