/// Foreground poll client for GET /scenes/by-bundle/{bundle_id} on api-public.
///
/// Owns the scene status lifecycle from upload completion until the backend
/// reaches a terminal state (ready / failed / failed_invalid) or a recoverable
/// stop (failed_incomplete — re-upload needed from the other front).
///
/// FOREGROUND-ONLY: uses URLSession.shared, not the background blob session.
/// Polling is paused when the app backgrounds (RootFlowView's scenePhase handler).
///
/// Polling is the authoritative channel for scene-completion detection — FCM
/// push (ready/failed) is a best-effort accelerant, not a substitute: it can
/// go undelivered (permission denied, device offline) or arrive too late to
/// act on (background processing is throttled by the OS). The loop therefore
/// NEVER hard-gives-up on transient failures while the screen is foregrounded.
/// Token acquisition is part of that posture: a tick that cannot obtain an auth
/// token (cold-launch race against the app-level sign-in, or offline sign-in
/// failure) is a transient tick, and the default token path re-attempts
/// signInIfNeeded each tick so the loop self-heals. The 0038 hard give-up —
/// 401 AFTER a successful refresh — is a different judgment and stays fatal.
///
/// Testability: all I/O is injected (now, sleep, performGET, tokenProvider).
/// Tests drive pure logic without real clocks or network.
///
/// Two entry paths into polling:
///   1. notifyBundleComplete(bundleId:) — called by BlobUploadManager (A-nudge route,
///      decision 0045). Starts polling immediately only if the status screen is
///      already visible. Otherwise a no-op — the .complete disk record is the
///      shared seam; onAppear reads it independently.
///   2. start(bundleId:) — called by RootFlowView (the connection-trouble "Try now"
///      resume and resumePollIfUploadFinished).
///
/// Read by: RootFlowView (routing + lifecycle), BlobUploadManager (one outbound
/// call), CaptureReaper (liveGET).

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
    case notOwned               // 403 — verified token, different owner; stop loop
    case fatal(String)          // 401-after-refresh, 400/422; stop loop
}

/// Observable state published to the UI.
enum ScenePollState: Equatable {
    case idle
    /// Active poll. `latest` is the last known status (shown instantly on resume).
    /// `since` is when THIS client's poll session started — it anchors poll
    /// cadence only, never user-facing time. `sceneCreatedAt` is the server-side
    /// scene creation time from the poll payload (nil until the first 200 — the
    /// scene document does not exist until ingest); it is the only honest anchor
    /// for the elapsed clock and the longRunning flip, and it survives
    /// re-foreground/relaunch because every fresh 200 re-delivers it.
    /// `longRunning` flips messaging after `ScenePoller.longRunningThreshold`.
    /// `connectionTrouble` is set after a transient network failure tick.
    case polling(latest: SceneStatus, since: Date, sceneCreatedAt: Date?, longRunning: Bool, connectionTrouble: Bool)
    case succeeded(SceneResponse)             // status == ready
    case failedTerminal(SceneStatus)          // status == failed or failed_invalid
    case recoverable(missingPaths: [String])  // status == failed_incomplete
    /// Terminal-not-ours (decision 0074): the server answered 403 to a VERIFIED
    /// token — this identity does not own the polled scene, and no amount of
    /// waiting, retrying, or token refreshing can change that. Distinct from
    /// .pollError so the flow can acknowledge the record and stand down instead
    /// of rendering connection trouble ("your room is safe up there" is false
    /// for a foreign room).
    case notOwned
    case pollError(String)                    // fatal request error
}

// MARK: - ScenePoller

@MainActor
final class ScenePoller: ObservableObject {

    // MARK: Singleton

    static let shared = ScenePoller()

    // MARK: Timing constants

    // Cadence values sanity-checked against the first real capture
    // (2026-07-21, scene 25a14caf): the 2 s window catches the ~3–5 s
    // pre-GPU failed_invalid fast-fail; the 10 s/30 s tiers are proportionate
    // to a pipeline whose GPU cold start alone is ~3.5 min. Not re-derived
    // since: the perception envelope fix (frame sampling + budget admission)
    // has shipped, so real completion times now exist — these constants have
    // simply not been tuned against them. Revisit with production /process
    // durations.
    /// Elapsed < cadenceShortWindow  → cadenceShort between ticks.
    static let cadenceShortWindow:  TimeInterval = 30
    /// Elapsed < cadenceMediumWindow → cadenceMedium between ticks.
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
    /// True while a status surface is in the view hierarchy and foregrounded.
    private(set) var isVisible: Bool = false
    /// The bundle the ACTIVE flight cares about (set by each root's send site,
    /// cleared by reset()). While set, notifyBundleComplete ignores completions
    /// for OTHER bundles: a previous capture's cross-launch upload finishing
    /// mid-flight would otherwise start polling the OLD bundle and render its
    /// doorway over the new capture's wait — the same class of stale-panel
    /// defect the status surface had before, in its RootFlowView-era form.
    /// Declaring it is also what drops a previous flight's already-published
    /// state, so neither root can narrate a finished room over a scan still on
    /// its way up — see expectBundle.
    /// nil = no active expectation; any completion may start (the
    /// restore/re-entry path).
    private(set) var expectedBundleId: String?

    /// The long-running poll loop task.
    var _runTask: Task<Void, Never>?
    /// The current cadence-sleep sub-task; cancelled by checkNow().
    private var sleepTask: Task<Void, Never>?

    private let logger = Logger(subsystem: "com.thegoodguest.TheGoodGuestCapture", category: "ScenePoller")

    // MARK: Init

    init(
        now:           @escaping () -> Date = { Date() },
        sleep:         @escaping (TimeInterval) async throws -> Void = { interval in
            try await Task.sleep(nanoseconds: UInt64(interval * 1_000_000_000))
        },
        performGET:    @escaping (String, String) async -> GETOutcome = ScenePoller.liveGET,
        tokenProvider: @escaping () async throws -> String = {
            // Cold-launch order safety: ensure the anonymous user exists before
            // vending a token, instead of assuming the app-level launch sign-in
            // already won the race. No-op when signed in; single-flighted inside
            // AuthManager, so racing the launch .task cannot double-sign-in
            // (UID churn, decision 0036).
            try await AuthManager.shared.signInIfNeeded()
            return try await AuthManager.shared.currentIDToken()
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
    /// or recoverable stop, so recovery flows (e.g. a re-upload retry after
    /// .recoverable) can restart polling.
    func start(bundleId: String) {
        if case .polling = pollState, currentBundleId == bundleId { return }
        cancelLoop()
        currentBundleId = bundleId
        let startDate   = now()
        pollState       = .polling(latest: .queued, since: startDate, sceneCreatedAt: nil, longRunning: false, connectionTrouble: false)
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
    ///
    /// Does NOT touch `isVisible`: that flag means "a status surface is on screen"
    /// and is owned by setVisible(). Setting it here made a background→foreground
    /// transition assert visibility even when no status surface was mounted, which
    /// the completion kick's guard then trusted.
    func resume() {
        guard let bundleId = currentBundleId else { return }
        switch pollState {
        case .succeeded, .failedTerminal, .recoverable, .notOwned, .pollError: return
        default: break
        }
        cancelLoop()
        // Preserve the original startDate so poll cadence is continuous.
        let startDate = extractStartDate() ?? now()
        // Preserve last-known status so the view doesn't blank.
        let lastStatus = extractLastStatus() ?? .queued
        // Preserve the server-side anchor and recompute longRunning from it, so
        // the resumed UI is honest immediately — before the first fresh tick.
        let sceneCreatedAt = extractSceneCreatedAt()
        let longRunning = now().timeIntervalSince(sceneCreatedAt ?? startDate) >= Self.longRunningThreshold
        pollState = .polling(latest: lastStatus, since: startDate, sceneCreatedAt: sceneCreatedAt, longRunning: longRunning, connectionTrouble: false)
        _runTask  = Task { [weak self] in await self?.run(bundleId: bundleId, startDate: startDate) }
        logger.info("[ScenePoller] resumed \(bundleId, privacy: .public)")
    }

    /// Hard reset to the pre-send baseline. Unlike pause() — which deliberately
    /// PRESERVES pollState/currentBundleId so resume() can render instantly — reset()
    /// drops the loop AND returns to .idle with no bundle. Call this synchronously
    /// before starting a new bundle so a fresh send never renders the previous
    /// capture's terminal outcome (a prior .succeeded/.failedTerminal/.pollError)
    /// during the setup window, and so a stale "Try now" can't re-poll the old bundle.
    func reset() {
        cancelLoop()
        currentBundleId = nil
        expectedBundleId = nil
        pollState = .idle
        logger.info("[ScenePoller] reset")
    }

    /// Declare which bundle the active flight is about (see expectedBundleId).
    ///
    /// Declaring a flight for a DIFFERENT bundle stands the previous one down.
    /// Published state always belongs to some bundle, and once a new capture is
    /// on its way the old one's state is the PREVIOUS room's — a status surface
    /// rendering it says "Room ready" over a scan that has not left the phone.
    /// The drop lives here rather than at each send site because it is the same
    /// judgment notifyBundleComplete already makes on the way in: a bundle that
    /// is not the flight has nothing to say about it. A site that reset()s first
    /// (a full per-send teardown does) arrives here with nothing to drop, so the
    /// order it calls in stops mattering.
    ///
    /// Re-declaring the SAME bundle is not a stand-down — that would kill the
    /// live poll of the very room in flight — and neither is clearing to nil.
    func expectBundle(_ bundleId: String?) {
        if let bundleId, let current = currentBundleId, current != bundleId {
            logger.info("[ScenePoller] standing down \(current, privacy: .public) — flight is now \(bundleId, privacy: .public)")
            reset()
        }
        expectedBundleId = bundleId
    }

    /// Fire an immediate poll tick by cancelling the current cadence sleep.
    /// Safe to call at any time; no-op if no sleep is in progress.
    func checkNow() {
        sleepTask?.cancel()
        sleepTask = nil
    }

    /// Visibility gate for the foreground gating rule (see decisions 0046/0047):
    /// called from RootFlowView (the wait screen's onAppear/onDisappear and the
    /// scenePhase handler).
    func setVisible(_ visible: Bool) {
        isVisible = visible
    }

    /// Called by BlobUploadManager.onBundleComplete (A-nudge kick).
    ///
    /// Starts polling immediately ONLY if the status view is already visible,
    /// and — when a flight expectation is set — only for the expected bundle.
    /// A different bundle's completion (a previous capture's resumed upload
    /// finishing cross-launch) is dropped: its .complete disk record is the
    /// shared seam, and the launch restore surfaces it on a later launch.
    /// If backgrounded, this is a no-op — same record seam, read by
    /// resumePollIfUploadFinished independently.
    func notifyBundleComplete(bundleId: String) {
        logger.info("[ScenePoller] notifyBundleComplete \(bundleId, privacy: .public) visible=\(self.isVisible)")
        guard isVisible else { return }
        if let expected = expectedBundleId, expected != bundleId {
            logger.info("[ScenePoller] ⚑ completion for \(bundleId, privacy: .public) ignored — active flight is \(expected, privacy: .public)")
            return
        }
        start(bundleId: bundleId)
    }

    // MARK: - Private: outer loop

    private func run(bundleId: String, startDate: Date) async {
        var lastStatus: SceneStatus = .queued
        // Server-side scene creation time, learned from the first 200 payload
        // and carried across notCreated/transient ticks (initialised from the
        // current state so resume() inherits it). Anchors the elapsed clock and
        // the longRunning flip. Poll CADENCE stays anchored to startDate: a
        // relaunch restarting the cadence ladder costs a handful of extra
        // requests and is by design.
        var sceneCreatedAt: Date? = extractSceneCreatedAt()

        while !Task.isCancelled {
            let tick    = await fetchTick(bundleId: bundleId)
            guard !Task.isCancelled else { return }

            if case .scene(let response) = tick, let createdAt = response.createdAtDate {
                sceneCreatedAt = createdAt
            }

            let elapsed     = now().timeIntervalSince(startDate)
            let longRunning = now().timeIntervalSince(sceneCreatedAt ?? startDate) >= Self.longRunningThreshold

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
                    pollState = .polling(latest: lastStatus, since: startDate, sceneCreatedAt: sceneCreatedAt, longRunning: longRunning, connectionTrouble: false)
                }

            case .notCreated:
                pollState = .polling(latest: lastStatus, since: startDate, sceneCreatedAt: sceneCreatedAt, longRunning: longRunning, connectionTrouble: false)

            case .transientFail:
                // Never give up — flip to connectionTrouble sub-state but keep going.
                pollState = .polling(latest: lastStatus, since: startDate, sceneCreatedAt: sceneCreatedAt, longRunning: longRunning, connectionTrouble: true)

            case .notOwned:
                pollState = .notOwned
                logger.info("[ScenePoller] not owned \(bundleId, privacy: .public) — standing down")
                return

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
            // TRANSIENT, not fatal — mirroring the network-down posture at the
            // HTTP layer. At cold launch this tick can precede the first
            // successful sign-in (no cached user yet, sign-in still in flight or
            // failed offline); polling is the sole completion channel, so a
            // permanent stop here would strand the scene status behind an app
            // relaunch. The loop keeps ticking (connection-trouble sub-state)
            // and the default token path re-attempts sign-in until it lands.
            // The 0038 hard give-up (401 AFTER a refresh) stays in handleStatus.
            logger.info("[ScenePoller] token unavailable this tick (transient): \(error.localizedDescription, privacy: .public)")
            return .transientFail
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
            // Ownership, not auth staleness (decision 0074). api-public 403s only
            // AFTER the token verifies (an invalid/expired token is a 401), and only
            // for "owned by a different user" / "scene has no owner" — both
            // definitive for this identity, however it arose (backup-migrated
            // records, UID churn). A refresh would present the SAME uid, so unlike
            // the 401 branch below there is nothing to retry.
            return .notOwned

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
        if case .polling(_, let since, _, _, _) = pollState { return since }
        return nil
    }

    private func extractLastStatus() -> SceneStatus? {
        if case .polling(let latest, _, _, _, _) = pollState { return latest }
        return nil
    }

    private func extractSceneCreatedAt() -> Date? {
        if case .polling(_, _, let createdAt, _, _) = pollState { return createdAt }
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
