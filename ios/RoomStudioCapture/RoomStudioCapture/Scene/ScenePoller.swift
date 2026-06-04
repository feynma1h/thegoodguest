/// Foreground poll client for GET /scenes/by-bundle/{bundle_id} on api-public.
///
/// Owns the scene status lifecycle from upload completion until the backend
/// reaches a terminal state (ready / failed / failed_invalid) or a recoverable
/// stop (failed_incomplete — re-upload needed from the other front).
///
/// FOREGROUND-ONLY: uses URLSession.shared, not the background blob session.
/// Polling must be paused when the app backgrounds (SceneStatusView handles this).
///
/// FCM push for ready/failed is currently broken (backend sends to device_id
/// instead of fcm_token). Polling is therefore the sole completion channel for
/// the user while the screen is open. The loop NEVER hard-gives-up on transient
/// failures while foregrounded.
///
/// Testability: all I/O is injected (now, sleep, performGET, tokenProvider).
/// Tests drive pure logic without real clocks or network.
///
/// Two entry paths into polling:
///   1. notifyBundleComplete(bundleId:) — called by BlobUploadManager (A-nudge route,
///      decision 0045). Starts polling immediately only if the status screen is
///      already visible. Otherwise a no-op — the .complete disk record is the
///      shared seam; onAppear reads it independently.
///   2. start(bundleId:) — called directly from SceneStatusView.onAppear.
///
/// Read by: SceneStatusView, BlobUploadManager (one outbound call only).

import Combine
import Foundation
import os

// MARK: - Supporting types

/// Raw outcome of a single HTTP GET attempt — below the retry layer.
typealias GETOutcome = Result<(statusCode: Int, data: Data), Error>

/// What one complete poll tick (with inner 0038 retry policy applied) resolves to.
enum SceneFetchResult {
    case scene(SceneResponse)   // 200 decoded
    case notCreated             // 404 — Firestore doc not yet written; keep polling
    case transientFail          // 5xx exhausted / network down; keep polling
    case fatal(String)          // 401-after-refresh, 403, 400/422; stop loop
}

/// Observable state published to the UI.
enum ScenePollState: Equatable {
    case idle
    /// Active poll. `latest` is the last known status (shown instantly on resume).
    /// `longRunning` flips messaging after `ScenePoller.longRunningThreshold`.
    /// `connectionTrouble` is set after a transient network failure tick.
    case polling(latest: SceneStatus, since: Date, longRunning: Bool, connectionTrouble: Bool)
    case succeeded(SceneResponse)             // status == ready
    case failedTerminal(SceneStatus)          // status == failed or failed_invalid
    case recoverable(missingPaths: [String])  // status == failed_incomplete
    case pollError(String)                    // fatal request error
}

// MARK: - ScenePoller

@MainActor
final class ScenePoller: ObservableObject {

    // MARK: Singleton

    static let shared = ScenePoller()

    // MARK: Timing constants

    /// Elapsed < cadenceShortWindow  → cadenceShort between ticks.
    static let cadenceShortWindow:  TimeInterval = 30
    /// Elapsed < cadenceMediumWindow → cadenceMedium between ticks.
    /// Named constant — retune once real perception latencies are known.
    static let cadenceMediumWindow: TimeInterval = 300   // 5 min
    static let cadenceShort:        TimeInterval = 2
    static let cadenceMedium:       TimeInterval = 10
    static let cadenceLong:         TimeInterval = 30
    /// Above this elapsed threshold flip messaging to "taking longer than usual".
    static let longRunningThreshold: TimeInterval = 600  // 10 min

    // Inner 0038 policy — mirrors UploadSessionClient (do NOT touch that file).
    private static let innerMaxRetries = 3
    private static let innerBase: TimeInterval = 1.0
    private static let innerMax:  TimeInterval = 30.0

    // MARK: Published state

    @Published private(set) var pollState: ScenePollState = .idle

    // MARK: Injected seams (defaults are the real implementations)

    private let now:           () -> Date
    private let sleep:         (TimeInterval) async throws -> Void
    private let performGET:    (String, String) async -> GETOutcome
    private let tokenProvider: () async throws -> String

    // MARK: Private state

    /// The bundle currently being polled (or last polled). Preserved across pause/resume.
    private(set) var currentBundleId: String?
    /// True while SceneStatusView is in the view hierarchy and foregrounded.
    private(set) var isVisible: Bool = false

    /// The long-running poll loop task.
    var _runTask: Task<Void, Never>?
    /// The current cadence-sleep sub-task; cancelled by checkNow().
    private var sleepTask: Task<Void, Never>?

    private let logger = Logger(subsystem: "com.roomstudio.RoomStudioCapture", category: "ScenePoller")

    // MARK: Init

    init(
        now:           @escaping () -> Date = { Date() },
        sleep:         @escaping (TimeInterval) async throws -> Void = { interval in
            try await Task.sleep(nanoseconds: UInt64(interval * 1_000_000_000))
        },
        performGET:    @escaping (String, String) async -> GETOutcome = ScenePoller.liveGET,
        tokenProvider: @escaping () async throws -> String = {
            try await AuthManager.shared.currentIDToken()
        }
    ) {
        self.now           = now
        self.sleep         = sleep
        self.performGET    = performGET
        self.tokenProvider = tokenProvider
    }

    // MARK: - Public API

    /// Begin polling for bundleId.
    ///
    /// Idempotent: same bundle while already polling = no-op (avoids resetting state
    /// mid-flight if the screen re-appears briefly). Re-callable after any terminal
    /// or recoverable stop — that re-callability IS the seam for the re-upload front.
    func start(bundleId: String) {
        if case .polling = pollState, currentBundleId == bundleId { return }
        cancelLoop()
        currentBundleId = bundleId
        let startDate   = now()
        pollState       = .polling(latest: .queued, since: startDate, longRunning: false, connectionTrouble: false)
        _runTask        = Task { [weak self] in await self?.run(bundleId: bundleId, startDate: startDate) }
        logger.info("[ScenePoller] start \(bundleId, privacy: .public)")
    }

    /// Pause polling without resetting state (app backgrounded or view disappeared).
    /// pollState and currentBundleId are preserved so resume() renders instantly.
    func pause() {
        isVisible = false
        cancelLoop()
        logger.info("[ScenePoller] paused")
    }

    /// Resume after a pause. Polls immediately (no initial cadence wait).
    /// No-op if already in a hard terminal or recoverable state.
    func resume() {
        isVisible = true
        guard let bundleId = currentBundleId else { return }
        switch pollState {
        case .succeeded, .failedTerminal, .recoverable, .pollError: return
        default: break
        }
        cancelLoop()
        // Preserve the original startDate so elapsed time (and cadence) are continuous.
        let startDate = extractStartDate() ?? now()
        // Preserve last-known status so the view doesn't blank.
        let lastStatus = extractLastStatus() ?? .queued
        pollState = .polling(latest: lastStatus, since: startDate, longRunning: false, connectionTrouble: false)
        _runTask  = Task { [weak self] in await self?.run(bundleId: bundleId, startDate: startDate) }
        logger.info("[ScenePoller] resumed \(bundleId, privacy: .public)")
    }

    /// Fire an immediate poll tick by cancelling the current cadence sleep.
    /// Safe to call at any time; no-op if no sleep is in progress.
    func checkNow() {
        sleepTask?.cancel()
        sleepTask = nil
    }

    /// Visibility gate for the foreground gating rule (§6):
    /// called from SceneStatusView.onAppear / onDisappear.
    func setVisible(_ visible: Bool) {
        isVisible = visible
    }

    /// Called by BlobUploadManager.onBundleComplete (A-nudge kick).
    ///
    /// Starts polling immediately ONLY if the status view is already visible.
    /// If backgrounded, this is a no-op — the .complete disk record is the shared
    /// seam and SceneStatusView.onAppear will pick it up independently.
    func notifyBundleComplete(bundleId: String) {
        logger.info("[ScenePoller] notifyBundleComplete \(bundleId, privacy: .public) visible=\(self.isVisible)")
        guard isVisible else { return }
        start(bundleId: bundleId)
    }

    // MARK: - Private: outer loop

    private func run(bundleId: String, startDate: Date) async {
        var lastStatus: SceneStatus = .queued

        while !Task.isCancelled {
            let tick    = await fetchTick(bundleId: bundleId)
            guard !Task.isCancelled else { return }

            let elapsed     = now().timeIntervalSince(startDate)
            let longRunning = elapsed >= Self.longRunningThreshold

            switch tick {
            case .scene(let response):
                lastStatus = response.status
                switch response.status.classification {
                case .hardTerminal:
                    if response.status == .ready {
                        pollState = .succeeded(response)
                    } else {
                        pollState = .failedTerminal(response.status)
                    }
                    logger.info("[ScenePoller] terminal=\(String(describing: response.status), privacy: .public) \(bundleId, privacy: .public)")
                    return

                case .recoverableTerminal:
                    pollState = .recoverable(missingPaths: response.missingPaths ?? [])
                    logger.info("[ScenePoller] recoverable \(bundleId, privacy: .public)")
                    return

                case .selfResolvingTransient:
                    pollState = .polling(latest: lastStatus, since: startDate, longRunning: longRunning, connectionTrouble: false)
                }

            case .notCreated:
                pollState = .polling(latest: lastStatus, since: startDate, longRunning: longRunning, connectionTrouble: false)

            case .transientFail:
                // Never give up — flip to connectionTrouble sub-state but keep going.
                pollState = .polling(latest: lastStatus, since: startDate, longRunning: longRunning, connectionTrouble: true)

            case .fatal(let msg):
                pollState = .pollError(msg)
                logger.info("[ScenePoller] fatal \(bundleId, privacy: .public): \(msg, privacy: .public)")
                return
            }

            let cadence = cadenceFor(elapsed: elapsed)
            sleepTask = Task { [weak self] in
                guard let self else { return }
                try? await self.sleep(cadence)
            }
            await sleepTask?.value
            sleepTask = nil
        }
    }

    // MARK: - Private: inner fetch (one tick with 0038 retry policy)

    private func fetchTick(bundleId: String) async -> SceneFetchResult {
        let token: String
        do {
            token = try await tokenProvider()
        } catch {
            return .fatal("auth: \(error.localizedDescription)")
        }
        return await fetchWithRetry(bundleId: bundleId, idToken: token, attempt: 0, didRefresh401: false)
    }

    private func fetchWithRetry(
        bundleId:      String,
        idToken:       String,
        attempt:       Int,
        didRefresh401: Bool
    ) async -> SceneFetchResult {
        switch await performGET(bundleId, idToken) {
        case .success(let (statusCode, data)):
            return await handleStatus(
                statusCode: statusCode, data: data,
                bundleId: bundleId, idToken: idToken,
                attempt: attempt, didRefresh401: didRefresh401
            )
        case .failure:
            if attempt >= Self.innerMaxRetries { return .transientFail }
            await innerDelay(attempt: attempt)
            return await fetchWithRetry(bundleId: bundleId, idToken: idToken, attempt: attempt + 1, didRefresh401: didRefresh401)
        }
    }

    private func handleStatus(
        statusCode:    Int,
        data:          Data,
        bundleId:      String,
        idToken:       String,
        attempt:       Int,
        didRefresh401: Bool
    ) async -> SceneFetchResult {
        switch statusCode {
        case 200:
            do {
                return .scene(try JSONDecoder().decode(SceneResponse.self, from: data))
            } catch {
                return .fatal("decode: \(error.localizedDescription)")
            }

        case 404:
            return .notCreated

        case 401:
            if didRefresh401 { return .fatal("401 after token refresh") }
            let fresh: String
            do { fresh = try await tokenProvider() } catch { return .fatal("token refresh: \(error.localizedDescription)") }
            return await fetchWithRetry(bundleId: bundleId, idToken: fresh, attempt: attempt, didRefresh401: true)

        case 403:
            return .fatal("403 Forbidden")

        case 400, 422:
            return .fatal("Client error \(statusCode)")

        case 500...599:
            if attempt >= Self.innerMaxRetries { return .transientFail }
            await innerDelay(attempt: attempt)
            return await fetchWithRetry(bundleId: bundleId, idToken: idToken, attempt: attempt + 1, didRefresh401: didRefresh401)

        default:
            return .fatal("Unexpected HTTP \(statusCode)")
        }
    }

    private func innerDelay(attempt: Int) async {
        let jitter = Double.random(in: 0..<1.0)
        let delay  = min(Self.innerBase * pow(2.0, Double(attempt)) + jitter, Self.innerMax)
        try? await sleep(delay)
    }

    // MARK: - Private: helpers

    private func cadenceFor(elapsed: TimeInterval) -> TimeInterval {
        if elapsed < Self.cadenceShortWindow  { return Self.cadenceShort  }
        if elapsed < Self.cadenceMediumWindow { return Self.cadenceMedium }
        return Self.cadenceLong
    }

    private func cancelLoop() {
        _runTask?.cancel()
        sleepTask?.cancel()
        _runTask  = nil
        sleepTask = nil
    }

    private func extractStartDate() -> Date? {
        if case .polling(_, let since, _, _) = pollState { return since }
        return nil
    }

    private func extractLastStatus() -> SceneStatus? {
        if case .polling(let latest, _, _, _) = pollState { return latest }
        return nil
    }

    // MARK: - Live GET implementation

    nonisolated static func liveGET(bundleId: String, idToken: String) async -> GETOutcome {
        let url = NetworkConfig.apiPublicBaseURL
            .appendingPathComponent("scenes")
            .appendingPathComponent("by-bundle")
            .appendingPathComponent(bundleId)
        var request = URLRequest(url: url)
        request.setValue("Bearer \(idToken)", forHTTPHeaderField: "Authorization")
        do {
            let (data, response) = try await URLSession.shared.data(for: request)
            guard let http = response as? HTTPURLResponse else {
                return .failure(URLError(.badServerResponse))
            }
            return .success((http.statusCode, data))
        } catch {
            return .failure(error)
        }
    }
}
