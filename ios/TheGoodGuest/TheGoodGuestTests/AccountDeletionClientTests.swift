/// Pins DELETE /account — the route App Store guideline 5.1.1(v) requires a
/// path to, and the only call in this app that destroys something.
///
/// WHAT MATTERS HERE is that two successes stay distinguishable and that a
/// failure can never read as one. The route has two success statuses with the
/// same body shape, and the difference between them is whether the user still
/// has an account: 200 means the identity is gone, 202 means the pass stopped
/// and everything is exactly where it was. A client that collapsed them would
/// tell someone their rooms were deleted while they were still sitting there.
///
/// The retry ladder is pinned too, because retrying a destructive call is only
/// safe while the server's idempotency holds — see the client's header. These
/// tests are what would fail if someone "fixed" the ladder by removing it, or
/// widened it to cover a status that is not safe to repeat.
///
/// Offline: an URLProtocol stub serves scripted responses and the retry sleeper
/// is injected, so the ladder is asserted without real waiting.

import XCTest
@testable import TheGoodGuest

// MARK: - Scripted transport

private final class DeleteStubProtocol: URLProtocol, @unchecked Sendable {
    struct Response {
        var status: Int
        var body: String = ""
        var transportError: Bool = false
    }

    nonisolated(unsafe) private static var script: [Response] = []
    nonisolated(unsafe) private static var served = 0
    nonisolated(unsafe) private static var seenMethods: [String] = []
    nonisolated(unsafe) private static var seenURLs: [URL] = []
    nonisolated(unsafe) private static var seenAuth: [String] = []
    nonisolated(unsafe) private static var seenBodies: [String] = []
    private static let lock = NSLock()

    static func load(_ responses: [Response]) {
        lock.lock(); defer { lock.unlock() }
        script = responses
        served = 0
        seenMethods = []; seenURLs = []; seenAuth = []; seenBodies = []
    }
    static var requestCount: Int { lock.lock(); defer { lock.unlock() }; return served }
    static var methods: [String] { lock.lock(); defer { lock.unlock() }; return seenMethods }
    static var urls: [URL] { lock.lock(); defer { lock.unlock() }; return seenURLs }
    static var authHeaders: [String] { lock.lock(); defer { lock.unlock() }; return seenAuth }
    static var bodies: [String] { lock.lock(); defer { lock.unlock() }; return seenBodies }

    private static func next(_ request: URLRequest) -> Response {
        lock.lock(); defer { lock.unlock() }
        let response = served < script.count ? script[served] : script.last!
        served += 1
        seenMethods.append(request.httpMethod ?? "")
        if let url = request.url { seenURLs.append(url) }
        seenAuth.append(request.value(forHTTPHeaderField: "Authorization") ?? "")
        // URLProtocol strips httpBody into a stream; read whichever is present.
        if let data = request.httpBody {
            seenBodies.append(String(decoding: data, as: UTF8.self))
        } else if let stream = request.httpBodyStream {
            stream.open()
            var buffer = [UInt8](repeating: 0, count: 4096)
            let read = stream.read(&buffer, maxLength: buffer.count)
            stream.close()
            seenBodies.append(String(decoding: buffer[0..<max(0, read)], as: UTF8.self))
        } else {
            seenBodies.append("")
        }
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

private func responseBody(
    deleted: Bool,
    identityDeleted: Bool,
    rooms: Int = 0,
    conversations: Int = 0,
    messages: Int = 0,
    specs: Int = 0,
    sessions: Int = 0,
    files: Int = 0,
    detail: String? = nil
) -> String {
    let detailField = detail.map { ", \"detail\": \"\($0)\"" } ?? ""
    return """
    {"deleted": \(deleted), "identity_deleted": \(identityDeleted),
     "counts": {"rooms": \(rooms), "conversations": \(conversations),
                "conversation_messages": \(messages), "design_specs": \(specs),
                "upload_sessions": \(sessions), "files": \(files)}\(detailField)}
    """
}

final class AccountDeletionClientTests: XCTestCase {

    private var slept: [TimeInterval] = []
    private let vendor = TokenVendor()

    private func makeClient() -> AccountDeletionClient {
        let config = URLSessionConfiguration.ephemeral
        config.protocolClasses = [DeleteStubProtocol.self]
        return AccountDeletionClient(
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

    // MARK: - The two successes stay distinguishable

    func test_200_withIdentityDeleted_isComplete() async throws {
        DeleteStubProtocol.load([
            .init(status: 200, body: responseBody(deleted: true, identityDeleted: true,
                                                  rooms: 6, conversations: 2, files: 214))
        ])
        let outcome = try await makeClient().delete(userID: "u1", tokenProvider: tokenProvider())
        guard case .complete(let counts) = outcome else {
            return XCTFail("expected .complete, got \(outcome)")
        }
        XCTAssertEqual(counts.rooms, 6)
        XCTAssertEqual(counts.conversations, 2)
        XCTAssertEqual(counts.files, 214)
    }

    func test_202_isPartial_andCarriesTheDetail() async throws {
        DeleteStubProtocol.load([
            .init(status: 202, body: responseBody(deleted: false, identityDeleted: false,
                                                  files: 40, detail: "storage unreachable"))
        ])
        let outcome = try await makeClient().delete(userID: "u1", tokenProvider: tokenProvider())
        guard case .partial(let counts, let detail) = outcome else {
            return XCTFail("expected .partial, got \(outcome)")
        }
        XCTAssertEqual(counts.files, 40)
        XCTAssertEqual(detail, "storage unreachable")
    }

    func test_theBodyDecides_notTheStatus() async throws {
        // A 200 whose body says the identity survived is a server
        // contradiction. Trusting the status would have this screen tell
        // someone their account is gone while it is not.
        DeleteStubProtocol.load([
            .init(status: 200, body: responseBody(deleted: false, identityDeleted: false))
        ])
        let outcome = try await makeClient().delete(userID: "u1", tokenProvider: tokenProvider())
        guard case .partial = outcome else {
            return XCTFail("a body saying not-deleted must never read as complete")
        }
    }

    func test_deletedButIdentityAlive_isPartial() async throws {
        DeleteStubProtocol.load([
            .init(status: 200, body: responseBody(deleted: true, identityDeleted: false))
        ])
        let outcome = try await makeClient().delete(userID: "u1", tokenProvider: tokenProvider())
        guard case .partial = outcome else {
            return XCTFail("the identity must be gone before this reads as complete")
        }
    }

    // MARK: - A resumed pass is a success with nothing in it

    func test_repeatedDeletion_returnsCompleteWithZeroCounts() async throws {
        // The token outlives the user by up to an hour, and an already-absent
        // user is success (decision 0103). This is what the second call of a
        // deletion whose response was lost actually looks like.
        DeleteStubProtocol.load([
            .init(status: 200, body: responseBody(deleted: true, identityDeleted: true))
        ])
        let outcome = try await makeClient().delete(userID: "u1", tokenProvider: tokenProvider())
        guard case .complete(let counts) = outcome else {
            return XCTFail("expected .complete, got \(outcome)")
        }
        XCTAssertTrue(counts.isEmpty)
    }

    // MARK: - The request

    func test_theRequestIsADeleteToAccountCarryingTheUid() async throws {
        DeleteStubProtocol.load([
            .init(status: 200, body: responseBody(deleted: true, identityDeleted: true))
        ])
        _ = try await makeClient().delete(userID: "uid-42", tokenProvider: tokenProvider())

        XCTAssertEqual(DeleteStubProtocol.methods, ["DELETE"])
        XCTAssertEqual(DeleteStubProtocol.urls.first?.path, "/account")
        XCTAssertTrue(DeleteStubProtocol.authHeaders.first?.hasPrefix("Bearer ") ?? false)
        // The accident control. Its absence is what would let a stray request
        // erase an account.
        XCTAssertTrue(
            DeleteStubProtocol.bodies.first?.contains("\"confirm_user_id\":\"uid-42\"") ?? false,
            "body was \(DeleteStubProtocol.bodies.first ?? "(none)")"
        )
    }

    func test_deleteURL_isTheAccountRoute() {
        let url = AccountDeletionClient.deleteURL(baseURL: URL(string: "https://x.invalid")!)
        XCTAssertEqual(url.absoluteString, "https://x.invalid/account")
    }

    // MARK: - Failures never read as success

    func test_400_isConfirmationMismatch() async {
        DeleteStubProtocol.load([.init(status: 400)])
        await assertThrows(.confirmationMismatch)
    }

    func test_503_isUnavailable() async {
        DeleteStubProtocol.load([.init(status: 503)])
        await assertThrows(.unavailable)
    }

    func test_418_isUnexpected() async {
        DeleteStubProtocol.load([.init(status: 418)])
        await assertThrows(.unexpectedStatus(418))
    }

    func test_200_withUndecodableBody_isDecodeFailed() async {
        DeleteStubProtocol.load([.init(status: 200, body: "not json")])
        do {
            _ = try await makeClient().delete(userID: "u1", tokenProvider: tokenProvider())
            XCTFail("expected a throw")
        } catch let error as AccountDeletionError {
            guard case .decodeFailed = error else {
                return XCTFail("expected .decodeFailed, got \(error)")
            }
        } catch {
            XCTFail("unexpected \(error)")
        }
    }

    // MARK: - The 401 path

    func test_401_buysOneFreshTokenAndOneRetry() async throws {
        DeleteStubProtocol.load([
            .init(status: 401),
            .init(status: 200, body: responseBody(deleted: true, identityDeleted: true, rooms: 1)),
        ])
        let outcome = try await makeClient().delete(userID: "u1", tokenProvider: tokenProvider())
        guard case .complete = outcome else { return XCTFail("expected .complete") }
        XCTAssertEqual(vendor.count, 2, "the retry must use a FRESH token")
        XCTAssertNotEqual(DeleteStubProtocol.authHeaders[0], DeleteStubProtocol.authHeaders[1])
    }

    func test_401_twice_isUnauthorized() async {
        DeleteStubProtocol.load([.init(status: 401), .init(status: 401)])
        await assertThrows(.unauthorized)
    }

    // MARK: - The retry ladder

    func test_500_retriesThenGivesUp() async {
        DeleteStubProtocol.load([.init(status: 500)])
        await assertThrows(.serverError(500))
        // One initial attempt plus maxRetries.
        XCTAssertEqual(DeleteStubProtocol.requestCount, 4)
        XCTAssertEqual(slept.count, 3)
    }

    func test_transportFailure_retriesTheSameWay() async {
        DeleteStubProtocol.load([.init(status: 0, transportError: true)])
        await assertThrows(.serverError(0))
        XCTAssertEqual(DeleteStubProtocol.requestCount, 4)
    }

    func test_500_thenSuccess_recovers() async throws {
        DeleteStubProtocol.load([
            .init(status: 500),
            .init(status: 200, body: responseBody(deleted: true, identityDeleted: true, rooms: 2)),
        ])
        let outcome = try await makeClient().delete(userID: "u1", tokenProvider: tokenProvider())
        guard case .complete(let counts) = outcome else { return XCTFail("expected .complete") }
        XCTAssertEqual(counts.rooms, 2)
        XCTAssertEqual(slept.count, 1)
    }

    func test_theLadderDoesNotRetryAStatusThatIsNotSafeToRepeat() async {
        // 400 and 503 are answers, not outages. Repeating them would spend the
        // user's wait on a result that cannot change.
        for status in [400, 503, 418] {
            DeleteStubProtocol.load([.init(status: status)])
            _ = try? await makeClient().delete(userID: "u1", tokenProvider: tokenProvider())
            XCTAssertEqual(
                DeleteStubProtocol.requestCount, 1,
                "\(status) must not be retried"
            )
        }
    }

    // MARK: - Counts

    func test_belongings_excludesUploadSessions() {
        let counts = AccountDeletionCounts(
            rooms: 1, conversations: 2, conversationMessages: 3,
            designSpecs: 4, uploadSessions: 99, files: 5
        )
        XCTAssertEqual(counts.belongings, 15)
    }

    func test_isEmpty_isTrueOnlyWhenNothingWasRemoved() {
        XCTAssertTrue(AccountDeletionCounts().isEmpty)
        XCTAssertFalse(AccountDeletionCounts(uploadSessions: 1).isEmpty)
        XCTAssertFalse(AccountDeletionCounts(rooms: 1).isEmpty)
    }

    // MARK: - Helper

    private func assertThrows(
        _ expected: AccountDeletionError,
        file: StaticString = #filePath,
        line: UInt = #line
    ) async {
        do {
            _ = try await makeClient().delete(userID: "u1", tokenProvider: tokenProvider())
            XCTFail("expected \(expected)", file: file, line: line)
        } catch let error as AccountDeletionError {
            XCTAssertEqual(error, expected, file: file, line: line)
        } catch {
            XCTFail("unexpected \(error)", file: file, line: line)
        }
    }
}
