/// Pins the four-way load state — the property every history surface rests on.
///
/// The distinction under test is "no rooms" versus "could not ask". Collapsing
/// them is a one-character change (`?? []`) and it produces a screen that tells
/// a user with rooms that they have none, at the exact moment they are being
/// asked to sign in to keep them. So each of the four states is reached here
/// deliberately, and the empty and failed cases are asserted to be different
/// values rather than merely different code paths.
///
/// Offline: the real ScenesListClient over an URLProtocol stub, so the store is
/// tested against the transport it actually uses, with the retry sleeper
/// injected so a failure path costs no wall-clock.

import XCTest
@testable import TheGoodGuestCapture

// MARK: - Scripted transport

private final class StoreStubProtocol: URLProtocol, @unchecked Sendable {
    struct Response {
        var status: Int
        var body: String = "{\"scenes\": []}"
    }

    nonisolated(unsafe) private static var script: [Response] = []
    nonisolated(unsafe) private static var served = 0
    private static let lock = NSLock()

    static func load(_ responses: [Response]) {
        lock.lock(); defer { lock.unlock() }
        script = responses
        served = 0
    }
    static var requestCount: Int { lock.lock(); defer { lock.unlock() }; return served }

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
                                   httpVersion: "HTTP/1.1", headerFields: nil)!
        client?.urlProtocol(self, didReceive: http, cacheStoragePolicy: .notAllowed)
        client?.urlProtocol(self, didLoad: Data(response.body.utf8))
        client?.urlProtocolDidFinishLoading(self)
    }
}

private func sceneBody(_ ids: [String], status: String = "ready") -> String {
    let scenes = ids.map { id in
        """
        {"scene_id": "\(id)", "bundle_id": "\(id)-bundle", "status": "\(status)",
         "result_uri": null, "missing_paths": [],
         "created_at": "2026-08-21T12:00:00+00:00", "updated_at": "2026-08-21T12:00:00+00:00"}
        """
    }
    return "{\"scenes\": [\(scenes.joined(separator: ","))]}"
}

@MainActor
final class RoomsStoreTests: XCTestCase {

    private func makeStore() -> RoomsStore {
        let config = URLSessionConfiguration.ephemeral
        config.protocolClasses = [StoreStubProtocol.self]
        let client = ScenesListClient(
            baseURL: URL(string: "https://api.test.invalid")!,
            urlSession: URLSession(configuration: config),
            sleeper: { _ in }
        )
        return RoomsStore(
            client: client,
            now: { Date(timeIntervalSince1970: 1_787_400_000) },
            tokenProvider: { "token" }
        )
    }

    // MARK: - The four states

    func testStartsIdleAndKnowsNothing() {
        let store = makeStore()
        XCTAssertEqual(store.state, .idle)
        XCTAssertNil(store.state.knownRooms)
        XCTAssertNil(store.state.knownCount)
    }

    func testSuccessfulFetchLoadsRooms() async {
        StoreStubProtocol.load([.init(status: 200, body: sceneBody(["a", "b"]))])
        let store = makeStore()

        await store.refresh()

        XCTAssertEqual(store.state.knownCount, 2)
        XCTAssertEqual(store.state.knownRooms?.map(\.id), ["a", "b"])
        if case .loaded(_, let stale) = store.state { XCTAssertFalse(stale) } else { XCTFail("not loaded") }
    }

    func testAnEmptyListIsKnownToBeZeroNotUnknown() async {
        StoreStubProtocol.load([.init(status: 200, body: "{\"scenes\": []}")])
        let store = makeStore()

        await store.refresh()

        XCTAssertEqual(store.state, .loaded(rooms: [], stale: false))
        XCTAssertEqual(store.state.knownCount, 0, "the server said zero — that IS an answer")
    }

    func testAFailedFirstFetchIsFailedNotEmpty() async {
        StoreStubProtocol.load([.init(status: 503)])
        let store = makeStore()

        await store.refresh()

        guard case .failed = store.state else {
            return XCTFail("expected .failed, got \(store.state)")
        }
        XCTAssertNil(store.state.knownRooms, "a failure must not present as zero rooms")
        XCTAssertNil(store.state.knownCount)
    }

    func testEmptyAndFailedAreDifferentValues() async {
        StoreStubProtocol.load([.init(status: 200, body: "{\"scenes\": []}")])
        let empty = makeStore()
        await empty.refresh()

        StoreStubProtocol.load([.init(status: 503)])
        let failed = makeStore()
        await failed.refresh()

        XCTAssertNotEqual(empty.state, failed.state)
    }

    // MARK: - Refresh after a success

    func testARefreshFailureKeepsTheKnownRoomsAndMarksThemStale() async {
        StoreStubProtocol.load([.init(status: 200, body: sceneBody(["a", "b"]))])
        let store = makeStore()
        await store.refresh()

        StoreStubProtocol.load([.init(status: 503)])
        await store.refresh()

        // Those two rooms were really sent. What is in doubt is whether the list
        // is current — which is exactly what `stale` says, and all it says.
        XCTAssertEqual(store.state.knownCount, 2)
        if case .loaded(_, let stale) = store.state { XCTAssertTrue(stale) } else { XCTFail("not loaded") }
    }

    func testASuccessfulRefreshClearsStaleness() async {
        StoreStubProtocol.load([.init(status: 200, body: sceneBody(["a"]))])
        let store = makeStore()
        await store.refresh()

        StoreStubProtocol.load([.init(status: 503)])
        await store.refresh()

        StoreStubProtocol.load([.init(status: 200, body: sceneBody(["a", "b"]))])
        await store.refresh()

        XCTAssertEqual(store.state, .loaded(rooms: store.state.knownRooms ?? [], stale: false))
        XCTAssertEqual(store.state.knownCount, 2)
    }

    func testARefreshThatFindsNoRoomsReportsZeroRatherThanKeepingTheOldOnes() async {
        // Rooms deleted on the web must disappear here. `stale` is for a failed
        // question, never for an answer we dislike.
        StoreStubProtocol.load([.init(status: 200, body: sceneBody(["a"]))])
        let store = makeStore()
        await store.refresh()

        StoreStubProtocol.load([.init(status: 200, body: "{\"scenes\": []}")])
        await store.refresh()

        XCTAssertEqual(store.state, .loaded(rooms: [], stale: false))
    }

    // MARK: - Single flight

    func testConcurrentRefreshesShareOneFetch() async {
        StoreStubProtocol.load([.init(status: 200, body: sceneBody(["a"]))])
        let store = makeStore()

        // Home's .task and the list's refresh can land together; without the
        // single flight they race to publish.
        async let first: Void  = store.refresh()
        async let second: Void = store.refresh()
        _ = await (first, second)

        XCTAssertEqual(StoreStubProtocol.requestCount, 1)
        XCTAssertEqual(store.state.knownCount, 1)
    }

    // MARK: - Clearing

    func testClearReturnsToKnowingNothing() async {
        StoreStubProtocol.load([.init(status: 200, body: sceneBody(["a"]))])
        let store = makeStore()
        await store.refresh()
        XCTAssertEqual(store.state.knownCount, 1)

        store.clear()

        XCTAssertEqual(store.state, .idle)
        XCTAssertNil(store.state.knownCount, "cleared is unknown, not zero")
    }

    // MARK: - Mapping

    func testStatusReachesTheRowTreatment() async {
        StoreStubProtocol.load([.init(status: 200, body: sceneBody(["a"], status: "processing"))])
        let store = makeStore()

        await store.refresh()

        XCTAssertEqual(store.state.knownRooms?.first?.state, .processing)
    }
}
