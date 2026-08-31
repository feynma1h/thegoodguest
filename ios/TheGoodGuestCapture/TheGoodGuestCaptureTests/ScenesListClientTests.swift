/// Pins GET /scenes — the fetch the history surfaces are made of.
///
/// WHAT MATTERS HERE is the shape of a failure, not the shape of a success.
/// Every surface downstream of this client tells the user something about how
/// many rooms they have, so the one outcome that must never be producible is a
/// failure that arrives looking like an empty list. Each error path below is
/// pinned as an ERROR, and the only way `[]` comes back is the server saying so.
///
/// Offline: an URLProtocol stub serves scripted responses and the retry sleeper
/// is injected, so the ladder is asserted without real waiting.

import XCTest
@testable import TheGoodGuestCapture

// MARK: - Scripted transport

private final class ScenesStubProtocol: URLProtocol, @unchecked Sendable {
    struct Response {
        var status: Int
        var body: String = "{\"scenes\": []}"
        /// When set, the request fails at the transport layer instead.
        var transportError: Bool = false
    }

    nonisolated(unsafe) private static var script: [Response] = []
    nonisolated(unsafe) private static var served = 0
    nonisolated(unsafe) private static var seenURLs: [URL] = []
    nonisolated(unsafe) private static var seenAuth: [String] = []
    private static let lock = NSLock()

    static func load(_ responses: [Response]) {
        lock.lock(); defer { lock.unlock() }
        script = responses
        served = 0
        seenURLs = []
        seenAuth = []
    }
    static var requestCount: Int { lock.lock(); defer { lock.unlock() }; return served }
    static var urls: [URL] { lock.lock(); defer { lock.unlock() }; return seenURLs }
    static var authHeaders: [String] { lock.lock(); defer { lock.unlock() }; return seenAuth }

    private static func next(_ request: URLRequest) -> Response {
        lock.lock(); defer { lock.unlock() }
        let response = served < script.count ? script[served] : script.last!
        served += 1
        if let url = request.url { seenURLs.append(url) }
        seenAuth.append(request.value(forHTTPHeaderField: "Authorization") ?? "")
        return response
    }

    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }
    override func stopLoading() {}

    override func startLoading() {
        let response = Self.next(request)
        if response.transportError {
            client?.urlProtocol(self, didFailWithError: URLError(.notConnectedToInternet))
            return
        }
        let http = HTTPURLResponse(url: request.url!, statusCode: response.status,
                                   httpVersion: "HTTP/1.1", headerFields: nil)!
        client?.urlProtocol(self, didReceive: http, cacheStoragePolicy: .notAllowed)
        client?.urlProtocol(self, didLoad: Data(response.body.utf8))
        client?.urlProtocolDidFinishLoading(self)
    }
}

/// Vends distinct tokens across concurrency domains, so a retry after a 401 is
/// distinguishable on the wire from a replay of the rejected one.
private final class TokenVendor: @unchecked Sendable {
    private var issued = 0
    private let lock = NSLock()

    func next() -> String {
        lock.lock(); defer { lock.unlock() }
        issued += 1
        return "t\(issued)"
    }
    var count: Int { lock.lock(); defer { lock.unlock() }; return issued }
}

// MARK: - Fixtures

private func sceneJSON(
    id: String,
    bundleId: String? = "b1",
    status: String = "ready",
    createdAt: String = "2026-08-12T15:40:00+00:00"
) -> String {
    let bundle = bundleId.map { "\"\($0)\"" } ?? "null"
    return """
    {"scene_id": "\(id)", "bundle_id": \(bundle), "status": "\(status)",
     "result_uri": null, "missing_paths": [],
     "created_at": "\(createdAt)", "updated_at": "\(createdAt)"}
    """
}

private func body(_ scenes: String...) -> String {
    "{\"scenes\": [\(scenes.joined(separator: ","))]}"
}

final class ScenesListClientTests: XCTestCase {

    private var slept: [TimeInterval] = []
    private let vendor = TokenVendor()

    private func makeClient() -> ScenesListClient {
        let config = URLSessionConfiguration.ephemeral
        config.protocolClasses = [ScenesStubProtocol.self]
        return ScenesListClient(
            baseURL: URL(string: "https://api.test.invalid")!,
            urlSession: URLSession(configuration: config),
            sleeper: { [weak self] seconds in
                await MainActor.run { self?.slept.append(seconds) }
            }
        )
    }

    private func tokenProvider() -> @Sendable () async throws -> String {
        let vendor = self.vendor
        return { vendor.next() }
    }

    override func setUp() {
        super.setUp()
        slept = []
    }

    // MARK: - Success

    func testDecodesScenesNewestFirstInServerOrder() async throws {
        ScenesStubProtocol.load([.init(status: 200, body: body(
            sceneJSON(id: "newest", createdAt: "2026-08-12T15:40:00+00:00"),
            sceneJSON(id: "older", createdAt: "2026-08-10T09:00:00+00:00")
        ))])

        let scenes = try await makeClient().list(tokenProvider: tokenProvider())

        // Order is the server's; the client must not re-sort and invent an
        // opinion about recency the server already expressed.
        XCTAssertEqual(scenes.map(\.sceneId), ["newest", "older"])
        XCTAssertEqual(scenes.first?.status, .ready)
    }

    func testEmptyListIsASuccess() async throws {
        ScenesStubProtocol.load([.init(status: 200, body: "{\"scenes\": []}")])
        let scenes = try await makeClient().list(tokenProvider: tokenProvider())
        XCTAssertTrue(scenes.isEmpty)
    }

    func testNullBundleIdDecodes() async throws {
        // The wire field is nullable; a scene whose ingest never recorded one
        // must still list, just without a way back to the web.
        ScenesStubProtocol.load([.init(status: 200, body: body(sceneJSON(id: "s1", bundleId: nil)))])
        let scenes = try await makeClient().list(tokenProvider: tokenProvider())
        XCTAssertNil(scenes.first?.bundleId)
    }

    func testUnknownStatusDecodesLeniently() async throws {
        // Shares SceneResponse with the poller precisely so this holds: a status
        // the backend adds tomorrow must not blank the user's room list today.
        ScenesStubProtocol.load([.init(status: 200, body: body(sceneJSON(id: "s1", status: "reticulating")))])
        let scenes = try await makeClient().list(tokenProvider: tokenProvider())
        XCTAssertEqual(scenes.first?.status, .unknown("reticulating"))
    }

    func testSendsBearerTokenAndClampedLimit() async throws {
        ScenesStubProtocol.load([.init(status: 200)])
        _ = try await makeClient().list(limit: 50, tokenProvider: tokenProvider())

        XCTAssertEqual(ScenesStubProtocol.authHeaders.first, "Bearer t1")
        XCTAssertEqual(ScenesStubProtocol.urls.first?.query, "limit=50")
    }

    // MARK: - The limit clamp

    func testLimitIsClampedToTheServersRange() {
        // The server 400s outside 1...100, and a 400 reaches the user as "I
        // couldn't reach your rooms" — a self-inflicted outage. Clamped, not
        // validated: no caller can produce it.
        let base = URL(string: "https://api.test.invalid")!
        XCTAssertEqual(ScenesListClient.listURL(baseURL: base, limit: 0).query, "limit=1")
        XCTAssertEqual(ScenesListClient.listURL(baseURL: base, limit: -5).query, "limit=1")
        XCTAssertEqual(ScenesListClient.listURL(baseURL: base, limit: 1000).query, "limit=100")
        XCTAssertEqual(ScenesListClient.listURL(baseURL: base, limit: 50).query, "limit=50")
        XCTAssertEqual(ScenesListClient.listURL(baseURL: base, limit: 100).query, "limit=100")
    }

    func testURLPathIsScenes() {
        let url = ScenesListClient.listURL(baseURL: URL(string: "https://api.test.invalid")!, limit: 50)
        XCTAssertEqual(url.path, "/scenes")
    }

    // MARK: - Auth

    func testOne401BuysOneFreshTokenAndOneRetry() async throws {
        ScenesStubProtocol.load([
            .init(status: 401),
            .init(status: 200, body: body(sceneJSON(id: "s1"))),
        ])

        let scenes = try await makeClient().list(tokenProvider: tokenProvider())

        XCTAssertEqual(scenes.count, 1)
        XCTAssertEqual(ScenesStubProtocol.authHeaders, ["Bearer t1", "Bearer t2"],
                       "the retry must carry a FRESH token, not replay the rejected one")
    }

    func testSecond401IsFatalAndNeverAnEmptyList() async {
        ScenesStubProtocol.load([.init(status: 401), .init(status: 401)])

        do {
            let scenes = try await makeClient().list(tokenProvider: tokenProvider())
            XCTFail("401 after a refresh must throw, got \(scenes.count) scene(s)")
        } catch {
            XCTAssertEqual(error as? ScenesListError, .unauthorized)
        }
    }

    // MARK: - Server and transport failures

    func testServerErrorRetriesThenThrows() async {
        ScenesStubProtocol.load([.init(status: 503)])

        do {
            _ = try await makeClient().list(tokenProvider: tokenProvider())
            XCTFail("an exhausted 5xx ladder must throw, never return []")
        } catch {
            XCTAssertEqual(error as? ScenesListError, .serverError(503))
        }
        // 1 initial + 3 retries, and each retry slept.
        XCTAssertEqual(ScenesStubProtocol.requestCount, 4)
        XCTAssertEqual(slept.count, 3)
    }

    func testServerErrorThatRecoversMidLadderSucceeds() async throws {
        ScenesStubProtocol.load([
            .init(status: 500),
            .init(status: 200, body: body(sceneJSON(id: "s1"))),
        ])
        let scenes = try await makeClient().list(tokenProvider: tokenProvider())
        XCTAssertEqual(scenes.count, 1)
        XCTAssertEqual(slept.count, 1)
    }

    func testBackoffIsExponentialAndCapped() async {
        ScenesStubProtocol.load([.init(status: 500)])
        _ = try? await makeClient().list(tokenProvider: tokenProvider())

        XCTAssertEqual(slept.count, 3)
        // base * 2^attempt + jitter(0..<1), capped at 30.
        XCTAssertTrue((1.0..<2.0).contains(slept[0]), "first delay \(slept[0])")
        XCTAssertTrue((2.0..<3.0).contains(slept[1]), "second delay \(slept[1])")
        XCTAssertTrue((4.0..<5.0).contains(slept[2]), "third delay \(slept[2])")
    }

    func testTransportFailureIsRetryableAndThenThrows() async {
        ScenesStubProtocol.load([.init(status: 0, transportError: true)])

        do {
            _ = try await makeClient().list(tokenProvider: tokenProvider())
            XCTFail("an offline device must throw, never return []")
        } catch {
            XCTAssertEqual(error as? ScenesListError, .serverError(0))
        }
        XCTAssertEqual(ScenesStubProtocol.requestCount, 4)
    }

    func testClientErrorIsFatalAndNotRetried() async {
        ScenesStubProtocol.load([.init(status: 400)])

        do {
            _ = try await makeClient().list(tokenProvider: tokenProvider())
            XCTFail("400 must throw")
        } catch {
            XCTAssertEqual(error as? ScenesListError, .clientError(400))
        }
        XCTAssertEqual(ScenesStubProtocol.requestCount, 1)
        XCTAssertTrue(slept.isEmpty)
    }

    func testUnexpectedStatusIsFatal() async {
        // /scenes has no ownership check — it is scoped to the token — so a 403
        // here is not an expected shape and must not be quietly swallowed.
        ScenesStubProtocol.load([.init(status: 403)])

        do {
            _ = try await makeClient().list(tokenProvider: tokenProvider())
            XCTFail("403 must throw")
        } catch {
            XCTAssertEqual(error as? ScenesListError, .unexpectedStatus(403))
        }
    }

    func testUndecodableBodyIsAFailureNotAnEmptyList() async {
        ScenesStubProtocol.load([.init(status: 200, body: "{\"rooms\": []}")])

        do {
            let scenes = try await makeClient().list(tokenProvider: tokenProvider())
            XCTFail("a body we cannot read must throw, got \(scenes.count) scene(s)")
        } catch {
            guard case .decodeFailed = (error as? ScenesListError) else {
                return XCTFail("expected .decodeFailed, got \(error)")
            }
        }
    }

    func testTokenProviderFailurePropagates() async {
        ScenesStubProtocol.load([.init(status: 200)])
        struct NoToken: Error {}

        do {
            _ = try await makeClient().list(tokenProvider: { throw NoToken() })
            XCTFail("no token must throw")
        } catch {
            XCTAssertTrue(error is NoToken)
        }
        XCTAssertEqual(ScenesStubProtocol.requestCount, 0)
    }
}
