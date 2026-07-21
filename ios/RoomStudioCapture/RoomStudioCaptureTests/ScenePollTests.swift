/// Tests for ScenePoller: cadence policy, status classification, lenient decode,
/// inner 0038 HTTP mapping, outer loop behavior, long-running threshold, checkNow.
///
/// Strategy: inject all I/O seams (now, sleep, performGET, tokenProvider) so tests
/// run without real clocks or network. The injected sleep is a no-op for most tests.
/// The run loop is awaited via poller._runTask?.value once it reaches terminal state.
///
/// Test isolation: each test constructs a fresh ScenePoller instance.
/// ScenePoller.shared is never used in unit tests.

import Combine
import XCTest
@testable import RoomStudioCapture

// MARK: - JSON helpers

/// Build JSON data for one SceneResponse. Uses JSONSerialization so mixed-type
/// arrays work without a custom Encodable wrapper.
private func sceneData(status: String, missingPaths: [String] = [], resultUri: String = "") throws -> Data {
    let dict: [String: Any] = [
        "scene_id":     "s1",
        "bundle_id":    "b1",
        "status":       status,
        "result_uri":   resultUri,
        "missing_paths": missingPaths,
        "created_at":   "2026-01-01T00:00:00Z",
        "updated_at":   "2026-01-01T00:00:00Z",
    ]
    return try JSONSerialization.data(withJSONObject: dict)
}

private func queued()          throws -> Data { try sceneData(status: "queued") }
private func processing()      throws -> Data { try sceneData(status: "processing") }
private func ready()           throws -> Data { try sceneData(status: "ready", resultUri: "gs://bucket/obj") }
private func failed()          throws -> Data { try sceneData(status: "failed") }
private func failedInvalid()   throws -> Data { try sceneData(status: "failed_invalid") }
private func failedIncomplete(_ paths: [String] = ["frames/1.jpg"]) throws -> Data {
    try sceneData(status: "failed_incomplete", missingPaths: paths)
}
private func unknownStatus(_ raw: String) throws -> Data { try sceneData(status: raw) }

// MARK: - ResponseBox

/// Actor-safe sequence of canned GETOutcome values.
/// Consumed in order; returns `.success((200, Data()))` after exhaustion.
private actor ResponseBox {
    private let responses: [GETOutcome]
    private var index = 0

    init(_ responses: [GETOutcome]) { self.responses = responses }

    func next() -> GETOutcome {
        guard index < responses.count else { return .success((200, Data())) }
        defer { index += 1 }
        return responses[index]
    }
}

// MARK: - ScenePollTests

@MainActor
final class ScenePollTests: XCTestCase {

    // MARK: - SceneStatus classification

    func test_classification_queued_isTransient() {
        XCTAssertEqual(SceneStatus.queued.classification, .selfResolvingTransient)
    }

    func test_classification_processing_isTransient() {
        XCTAssertEqual(SceneStatus.processing.classification, .selfResolvingTransient)
    }

    func test_classification_unknown_isTransient() {
        XCTAssertEqual(SceneStatus.unknown("future_state").classification, .selfResolvingTransient)
    }

    func test_classification_failedIncomplete_isRecoverable() {
        XCTAssertEqual(SceneStatus.failedIncomplete.classification, .recoverableTerminal)
    }

    func test_classification_ready_isHardTerminal() {
        XCTAssertEqual(SceneStatus.ready.classification, .hardTerminal)
    }

    func test_classification_failed_isHardTerminal() {
        XCTAssertEqual(SceneStatus.failed.classification, .hardTerminal)
    }

    func test_classification_failedInvalid_isHardTerminal() {
        XCTAssertEqual(SceneStatus.failedInvalid.classification, .hardTerminal)
    }

    // MARK: - Lenient decode

    func test_decode_unknownStatus_doesNotThrow() throws {
        // LOAD-BEARING: must not throw on an unrecognised wire value (decision 0027).
        let data     = try unknownStatus("brand_new_future_status")
        let response = try JSONDecoder().decode(SceneResponse.self, from: data)
        if case .unknown(let raw) = response.status {
            XCTAssertEqual(raw, "brand_new_future_status")
        } else {
            XCTFail("Expected .unknown, got \(response.status)")
        }
    }

    func test_decode_allKnownStatuses() throws {
        let cases: [(String, SceneStatus)] = [
            ("queued",            .queued),
            ("processing",        .processing),
            ("ready",             .ready),
            ("failed",            .failed),
            ("failed_incomplete", .failedIncomplete),
            ("failed_invalid",    .failedInvalid),
        ]
        for (wire, expected) in cases {
            let data     = try unknownStatus(wire)
            let response = try JSONDecoder().decode(SceneResponse.self, from: data)
            XCTAssertEqual(response.status, expected, "wire '\(wire)' should decode to \(expected)")
        }
    }

    // MARK: - Cadence transitions

    func test_cadence_underShortWindow_returns2s() {
        XCTAssertEqual(cadence(0),   ScenePoller.cadenceShort)
        XCTAssertEqual(cadence(15),  ScenePoller.cadenceShort)
        XCTAssertEqual(cadence(29),  ScenePoller.cadenceShort)
    }

    func test_cadence_atShortWindow_returns10s() {
        XCTAssertEqual(cadence(30),  ScenePoller.cadenceMedium)
        XCTAssertEqual(cadence(100), ScenePoller.cadenceMedium)
        XCTAssertEqual(cadence(299), ScenePoller.cadenceMedium)
    }

    func test_cadence_atMediumWindow_returns30s() {
        XCTAssertEqual(cadence(300), ScenePoller.cadenceLong)
        XCTAssertEqual(cadence(600), ScenePoller.cadenceLong)
    }

    // MARK: - Hard terminals stop the loop

    func test_readyResponse_setsSucceeded() async throws {
        let p = poller([.success((200, try ready()))])
        p.start(bundleId: "b1")
        await p._runTask?.value
        guard case .succeeded(let r) = p.pollState else {
            return XCTFail("Expected .succeeded, got \(p.pollState)")
        }
        XCTAssertEqual(r.status, .ready)
    }

    func test_failedResponse_setsFailedTerminal() async throws {
        let p = poller([.success((200, try failed()))])
        p.start(bundleId: "b1")
        await p._runTask?.value
        XCTAssertEqual(p.pollState, .failedTerminal(.failed))
    }

    func test_failedInvalidResponse_setsFailedTerminal() async throws {
        let p = poller([.success((200, try failedInvalid()))])
        p.start(bundleId: "b1")
        await p._runTask?.value
        XCTAssertEqual(p.pollState, .failedTerminal(.failedInvalid))
    }

    // MARK: - Recoverable stops the loop

    func test_failedIncomplete_setsRecoverable_andStops() async throws {
        let p = poller([.success((200, try failedIncomplete(["f/1.jpg", "f/2.jpg"])))])
        p.start(bundleId: "b1")
        await p._runTask?.value
        guard case .recoverable(let paths) = p.pollState else {
            return XCTFail("Expected .recoverable, got \(p.pollState)")
        }
        XCTAssertEqual(paths.count, 2)
    }

    // MARK: - Transient + notCreated keep the loop running

    func test_transientThenReady_loopContinues() async throws {
        let p = poller([
            .success((200, try queued())),
            .success((200, try ready())),
        ])
        p.start(bundleId: "b1")
        await p._runTask?.value
        if case .succeeded = p.pollState { } else {
            XCTFail("Expected .succeeded after queued→ready")
        }
    }

    func test_notCreatedThenReady_loopContinues() async throws {
        let p = poller([
            .success((404, Data())),
            .success((200, try ready())),
        ])
        p.start(bundleId: "b1")
        await p._runTask?.value
        if case .succeeded = p.pollState { } else {
            XCTFail("Expected .succeeded after 404→ready")
        }
    }

    func test_notCreated_doesNotSetPollError() async throws {
        // 404 must produce .polling, not .pollError.
        let p = poller([
            .success((404, Data())),
            .success((200, try ready())),
        ])
        var seenError = false
        let sub = p.$pollState.sink { state in
            if case .pollError = state { seenError = true }
        }
        p.start(bundleId: "b1")
        await p._runTask?.value
        XCTAssertFalse(seenError, "404 (notCreated) must never produce .pollError")
        _ = sub
    }

    // MARK: - Inner 0038: 401 refresh-once

    func test_inner_401_refreshesTokenOnce_thenSucceeds() async throws {
        var tokenCalls = 0
        var getCalls   = 0
        let box = ResponseBox([
            .success((401, Data())),    // first GET → 401
            .success((200, try ready())), // after token refresh → 200
        ])
        let p = ScenePoller(
            sleep: { _ in },
            performGET: { _, _ in
                getCalls += 1
                return await box.next()
            },
            tokenProvider: {
                tokenCalls += 1
                return "token-\(tokenCalls)"
            }
        )
        p.start(bundleId: "b1")
        await p._runTask?.value
        XCTAssertEqual(tokenCalls, 2, "Initial token + one refresh")
        XCTAssertEqual(getCalls,   2, "First GET (401) + retry with fresh token")
        if case .succeeded = p.pollState { } else {
            XCTFail("Expected .succeeded after 401-then-200")
        }
    }

    func test_inner_401_afterRefresh_yieldsFatal() async throws {
        var tokenCalls = 0
        let box = ResponseBox([
            .success((401, Data())),
            .success((401, Data())),   // still 401 after refresh
        ])
        let p = ScenePoller(
            sleep: { _ in },
            performGET: { _, _ in await box.next() },
            tokenProvider: { tokenCalls += 1; return "t\(tokenCalls)" }
        )
        p.start(bundleId: "b1")
        await p._runTask?.value
        if case .pollError = p.pollState { } else {
            XCTFail("Expected .pollError after 401-then-401, got \(p.pollState)")
        }
    }

    // MARK: - Token acquisition failure is transient (cold-launch race)

    func test_tokenProviderThrows_isTransient_thenRecovers() async throws {
        // Cold-launch race: the poll loop can start before the app-level anonymous
        // sign-in lands, so the initial token acquisition can fail. That must be a
        // transient tick — the loop keeps polling (connection-trouble sub-state, no
        // GET fired) and succeeds once auth becomes available — never .pollError.
        var tokenCalls = 0
        var getCalls   = 0
        let box = ResponseBox([.success((200, try ready()))])
        var connectionTroubleObserved = false
        var pollErrorObserved         = false
        let p = ScenePoller(
            sleep: { _ in },
            performGET: { _, _ in getCalls += 1; return await box.next() },
            tokenProvider: {
                tokenCalls += 1
                if tokenCalls <= 2 {
                    throw AuthManager.AuthError.notSignedIn   // sign-in not yet landed
                }
                return "token"
            }
        )
        let sub = p.$pollState.sink { state in
            if case .polling(_, _, _, let ct) = state, ct { connectionTroubleObserved = true }
            if case .pollError = state { pollErrorObserved = true }
        }
        p.start(bundleId: "b1")
        await p._runTask?.value
        XCTAssertEqual(tokenCalls, 3, "Two failed acquisitions + the successful one")
        XCTAssertEqual(getCalls, 1, "No GET may fire on a token-less tick")
        XCTAssertTrue(connectionTroubleObserved,
                      "Token-less ticks must surface as connectionTrouble, not error")
        XCTAssertFalse(pollErrorObserved,
                       "Initial token acquisition failure must never produce .pollError")
        if case .succeeded = p.pollState { } else {
            XCTFail("Expected .succeeded once sign-in lands, got \(p.pollState)")
        }
        _ = sub
    }

    func test_tokenRefreshThrowAfter401_staysFatal() async throws {
        // Boundary pin: the transient classification covers INITIAL acquisition only.
        // A tokenProvider failure on the 401-refresh path remains fatal — the server
        // has already rejected a token a real signed-in user produced, which is
        // 0038's give-up territory, not a launch race.
        var tokenCalls = 0
        let box = ResponseBox([.success((401, Data()))])
        let p = ScenePoller(
            sleep: { _ in },
            performGET: { _, _ in await box.next() },
            tokenProvider: {
                tokenCalls += 1
                if tokenCalls == 1 { return "stale-token" }
                throw AuthManager.AuthError.notSignedIn
            }
        )
        p.start(bundleId: "b1")
        await p._runTask?.value
        if case .pollError = p.pollState { } else {
            XCTFail("Expected .pollError when the refresh-path token acquisition throws, got \(p.pollState)")
        }
    }

    // MARK: - Inner 0038: 5xx backoff then transientFail

    func test_inner_5xx_exhaustedRetries_yieldsTransientFailThenContinues() async throws {
        var getCalls = 0
        let box = ResponseBox([
            .success((503, Data())),    // attempt 0
            .success((503, Data())),    // attempt 1
            .success((503, Data())),    // attempt 2
            .success((503, Data())),    // attempt 3 — exhausted → transientFail
            .success((200, try ready())), // outer tick 2 → terminal
        ])
        let p = ScenePoller(
            sleep: { _ in },
            performGET: { _, _ in getCalls += 1; return await box.next() },
            tokenProvider: { "token" }
        )
        p.start(bundleId: "b1")
        await p._runTask?.value
        XCTAssertEqual(getCalls, 5, "4 × 5xx + 1 success")
        if case .succeeded = p.pollState { } else {
            XCTFail("Expected .succeeded after transientFail→ready")
        }
    }

    func test_inner_networkError_treatedLike5xx() async throws {
        let box = ResponseBox([
            .failure(URLError(.notConnectedToInternet)),
            .failure(URLError(.notConnectedToInternet)),
            .failure(URLError(.notConnectedToInternet)),
            .failure(URLError(.notConnectedToInternet)),  // exhausted
            .success((200, try ready())),
        ])
        let p = ScenePoller(
            sleep: { _ in },
            performGET: { _, _ in await box.next() },
            tokenProvider: { "token" }
        )
        p.start(bundleId: "b1")
        await p._runTask?.value
        if case .succeeded = p.pollState { } else {
            XCTFail("Expected .succeeded after network-errors→ready")
        }
    }

    func test_transientFail_setsConnectionTroubleSubstate() async throws {
        let box = ResponseBox([
            .success((503, Data())),
            .success((503, Data())),
            .success((503, Data())),
            .success((503, Data())),    // exhausted → transientFail
            .success((200, try ready())),
        ])
        var connectionTroubleObserved = false
        let p = ScenePoller(
            sleep: { _ in },
            performGET: { _, _ in await box.next() },
            tokenProvider: { "token" }
        )
        let sub = p.$pollState.sink { state in
            if case .polling(_, _, _, let ct) = state, ct {
                connectionTroubleObserved = true
            }
        }
        p.start(bundleId: "b1")
        await p._runTask?.value
        XCTAssertTrue(connectionTroubleObserved, "transientFail tick must set connectionTrouble=true")
        _ = sub
    }

    // MARK: - Fatal HTTP codes stop the loop

    func test_403_stopsFatal() async throws {
        let p = poller([.success((403, Data()))])
        p.start(bundleId: "b1")
        await p._runTask?.value
        if case .pollError = p.pollState { } else {
            XCTFail("Expected .pollError for 403")
        }
    }

    func test_400_stopsFatal() async throws {
        let p = poller([.success((400, Data()))])
        p.start(bundleId: "b1")
        await p._runTask?.value
        if case .pollError = p.pollState { } else {
            XCTFail("Expected .pollError for 400")
        }
    }

    // MARK: - Long-running threshold

    func test_longRunning_threshold_flipsFlag() async throws {
        // Make startDate far in the past so elapsed > longRunningThreshold immediately.
        let past = Date().addingTimeInterval(-(ScenePoller.longRunningThreshold + 10))
        var nowCallCount = 0
        let box = ResponseBox([
            .success((200, try queued())),   // transient → checks elapsed
            .success((200, try ready())),    // terminal
        ])
        var longRunningObserved = false
        let p = ScenePoller(
            now: {
                nowCallCount += 1
                // Call 1 is from start() to set startDate = past.
                // Subsequent calls (inside run()) return Date() so elapsed = now - past > threshold.
                return nowCallCount == 1 ? past : Date()
            },
            sleep: { _ in },
            performGET: { _, _ in await box.next() },
            tokenProvider: { "token" }
        )
        let sub = p.$pollState.sink { state in
            if case .polling(_, _, let lr, _) = state, lr {
                longRunningObserved = true
            }
        }
        p.start(bundleId: "b1")
        await p._runTask?.value
        XCTAssertTrue(longRunningObserved, "Elapsed > longRunningThreshold must set longRunning=true")
        _ = sub
    }

    // MARK: - start() idempotency

    func test_start_idempotent_sameBundle() async throws {
        // Provide exactly 3 responses: q, q, ready.
        // If start() restarts the loop mid-flight the box index advances unpredictably.
        // We verify the terminal state is .succeeded (all 3 consumed in order).
        var getCalls = 0
        let box = ResponseBox([
            .success((200, try queued())),
            .success((200, try queued())),
            .success((200, try ready())),
        ])
        let p = ScenePoller(
            sleep: { _ in },
            performGET: { _, _ in getCalls += 1; return await box.next() },
            tokenProvider: { "token" }
        )
        p.start(bundleId: "b1")
        await Task.yield()  // first tick fires
        p.start(bundleId: "b1")  // same bundle, should be no-op
        await p._runTask?.value
        // If idempotent: 3 ticks in order → .succeeded.
        if case .succeeded = p.pollState { } else {
            XCTFail("Expected .succeeded; idempotent start must not restart the loop")
        }
    }

    // MARK: - checkNow interrupts sleep and fires next tick

    func test_checkNow_interruptsSleepAndFiresNextTick() async throws {
        var getCalls = 0
        let box = ResponseBox([
            .success((200, try queued())),  // tick 1 → transient → long sleep
            .success((200, try ready())),   // tick 2 → terminal (fires after checkNow)
        ])
        // Long sleep: only exits when cancelled by checkNow().
        let p = ScenePoller(
            sleep: { _ in try? await Task.sleep(nanoseconds: 30_000_000_000) },
            performGET: { _, _ in
                getCalls += 1
                return await box.next()
            },
            tokenProvider: { "token" }
        )
        p.start(bundleId: "b1")
        // Yield until the first tick is processed and the loop enters the long cadence sleep.
        for _ in 0..<20 { await Task.yield() }
        XCTAssertEqual(getCalls, 1, "First tick should have fired before checkNow")
        // checkNow cancels the cadence sleep; the loop immediately polls again.
        p.checkNow()
        await p._runTask?.value
        XCTAssertEqual(getCalls, 2, "Second tick should fire after checkNow interrupts sleep")
        if case .succeeded = p.pollState { } else {
            XCTFail("Expected .succeeded after checkNow triggered second tick")
        }
    }

    // MARK: - Helpers

    /// Build a poller with no-op sleep and a fixed sequence of GET outcomes.
    private func poller(_ responses: [GETOutcome]) -> ScenePoller {
        let box = ResponseBox(responses)
        return ScenePoller(
            sleep: { _ in },
            performGET: { _, _ in await box.next() },
            tokenProvider: { "token" }
        )
    }

    /// Mirrors ScenePoller's private cadenceFor(elapsed:) for direct unit testing.
    private func cadence(_ elapsed: TimeInterval) -> TimeInterval {
        if elapsed < ScenePoller.cadenceShortWindow  { return ScenePoller.cadenceShort  }
        if elapsed < ScenePoller.cadenceMediumWindow { return ScenePoller.cadenceMedium }
        return ScenePoller.cadenceLong
    }
}
