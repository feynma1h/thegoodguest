/// Owns the capture Live Activity's lifetime (design spec §5).
///
/// ONE ACTIVITY AT A TIME, keyed on bundle_id. Every entry point takes the
/// bundleId it believes it is reporting on and is DROPPED if that is not the
/// activity's own bundle. This project has been bitten twice by a surface
/// narrating the wrong capture — the stale doorway flashing over a new send
/// (405131a) and the phantom room from a migrated record (decision 0074) — and a
/// Lock Screen the user sees without opening the app is the worst place to
/// discover a third instance.
///
/// FED FROM TWO PLACES THAT CANNOT SEE EACH OTHER:
///   • BlobUploadManager — blob progress, terminal blob failure, deferral. Runs
///     on the background URLSession, so this is what keeps the Lock Screen honest
///     while the app is closed. This is the half that actually earns the feature.
///   • RootFlowView — the WaitScreen routing decision (queued/analyzing/ready/
///     failures). Foreground-only by nature: the poller does not run while the
///     app is dead.
/// LiveActivityPolicy merges the two and decides what is worth publishing.
///
/// FAILURE POSTURE: advisory, never load-bearing. Every ActivityKit call is
/// fire-and-forget and every error is swallowed to a log line. A Live Activity
/// that cannot start (unsupported device, user disabled them in Settings, budget
/// exhausted) must not affect an upload by even one branch.
///
/// Read by: RootFlowView (the WaitScreen mirror + lifecycle), BlobUploadManager
/// (progress, finalize, complete), UploadFailureMonitor (terminal failure,
/// paused). Pinned by: LiveActivityControllerTests (through the
/// LiveActivityHost seam — the tests never touch real ActivityKit).

import ActivityKit
import Foundation
import os

// MARK: - The ActivityKit seam

/// What the controller needs from ActivityKit. Injected so the decision logic can
/// be tested without a live system service (ActivityKit does nothing in a unit
/// test host: no activity is ever created, so a controller talking to it directly
/// would be untestable by construction).
@MainActor
protocol LiveActivityHost: AnyObject {
    /// False when the platform or the user says no. Checked before every start.
    var areActivitiesEnabled: Bool { get }
    /// True while an activity created by `start` is live.
    var isRunning: Bool { get }
    func start(attributes: RoomActivityAttributes, state: RoomActivityState, staleDate: Date?)
    func update(state: RoomActivityState, staleDate: Date?)
    /// `dismissAfter` nil = leave it to the system's default.
    func end(state: RoomActivityState, dismissAfter: Date?)
    /// End every activity of this type that this process can see, including ones
    /// started by a previous launch.
    func endAllOrphans(keeping bundleId: String?)
}

// MARK: - Controller

@MainActor
final class LiveActivityController {

    static let shared = LiveActivityController(host: ActivityKitHost())

    // Logging privacy policy (house rule): bundle ids and stage names may be
    // .public; nothing user-identifying is logged here at all.
    private let logger = Logger(subsystem: "com.roomstudio.RoomStudioCapture", category: "LiveActivity")

    private let host: LiveActivityHost
    /// Injected clock — tests drive the throttle without waiting.
    var clock: () -> Date = { Date() }

    private(set) var currentBundleId: String?
    private(set) var currentStage: RoomActivityStage?
    private var lastPublishedAt: Date?

    #if DEBUG
    /// Last (incoming -> adopted) pair recorded by the drop breadcrumb, so a
    /// card that is not adopted writes one line instead of thousands.
    private var lastDropSignature: String?
    #endif

    init(host: LiveActivityHost) { self.host = host }

    // MARK: - Constants

    /// How long a finished activity stays on the Lock Screen before the system
    /// clears it. Long enough to be seen after a walk, short enough that a
    /// yesterday's-room card is never sitting there. (ActivityKit caps the
    /// dismissal window at 4 hours regardless.)
    static let terminalDwell: TimeInterval = 15 * 60

    /// After this long with no update the system dims the activity as stale. Set
    /// generously: a long GPU queue is slow, not broken, and a dimmed card is a
    /// weaker claim than a wrong one.
    static let staleAfter: TimeInterval = 45 * 60

    /// SEAM — remote push updates (`pushType: .token`) would let the pipeline's
    /// own state reach the Lock Screen with the app closed, which is the one gap
    /// the foreground poller cannot cover. It needs an APNs key on a paid team
    /// (the same Developer Program enrollment that gates Sign in with Apple and
    /// FCM), so the activity is requested with `pushType: nil` for now. When
    /// enrollment lands: request with `.token`, forward `activity.pushToken`
    /// updates to the backend beside the FCM token at `/upload_session`, and the
    /// perception service's terminal-transition notifier gains a second target.
    static let pushTokenSeam = "enrollment-gated: request(pushType:.token) + forward activity.pushToken"

    // MARK: - Entry points

    /// Start the activity for a send that is beginning now. Idempotent per bundle.
    func begin(bundleId: String) {
        guard host.areActivitiesEnabled else {
            logger.info("[LiveActivity] not enabled — skipping start for \(bundleId, privacy: .public)")
            return
        }
        if currentBundleId == bundleId, host.isRunning { return }
        // A previous capture's card must not linger beside the new one.
        endOrphans(keeping: bundleId)

        let now = clock()
        currentBundleId = bundleId
        currentStage    = .preparing
        lastPublishedAt = now
        host.start(
            attributes: RoomActivityAttributes(bundleId: bundleId, startedAt: now),
            state: RoomActivityState(stage: .preparing),
            staleDate: now.addingTimeInterval(Self.staleAfter)
        )
        logger.info("[LiveActivity] started for \(bundleId, privacy: .public)")
    }

    /// Blob progress from the background session. `total` counts non-bundle.pb
    /// blobs only (bundle.pb is the finalize, not part of the room's data).
    func noteUploadProgress(bundleId: String, sent: Int, total: Int) {
        apply(.sending(sent: sent, total: total), for: bundleId)
    }

    /// Every blob is up and the `bundle.pb` finalize is enqueued.
    ///
    /// THIS IS THE HALF THAT WAS MISSING. Without it the last thing the
    /// background session could ever publish was `.sending(N, N)`, so a card on
    /// a closed phone sat at a completed count labelled in progress forever —
    /// decision 0085's stale "Sending your room 331 of 331". Reached from
    /// `enqueueBundlePb`, which is on the background path, so it lands with the
    /// app closed.
    func noteFinalizing(bundleId: String) {
        apply(.finalizing, for: bundleId)
    }

    /// `bundle.pb` landed: the capture now exists server-side and is waiting for
    /// the pipeline. The honest end of what a closed phone can know — past here
    /// the poller is required, and that boundary is the `pushTokenSeam` above.
    func noteUploadComplete(bundleId: String) {
        apply(.queued, for: bundleId)
    }

    /// The upload stopped for this launch and resumes on the next app open.
    func noteUploadPaused(bundleId: String) {
        apply(.paused, for: bundleId)
    }

    /// The blobs for this bundle failed terminally — no scene will ever exist.
    func noteUploadFailed(bundleId: String) {
        apply(.failed(.upload), for: bundleId)
    }

    /// Mirror the app's own routing decision. `nil` from the policy means the
    /// screen adds nothing the activity doesn't already know.
    func noteWaitScreen(_ screen: WaitScreen, bundleId: String?) {
        guard let bundleId, let stage = LiveActivityPolicy.stage(for: screen) else { return }
        apply(stage, for: bundleId)
    }

    /// The user is done with this capture (doorway Done, a failure's off-ramp, the
    /// decision-0074 stand-down). Ends the card with whatever it last showed.
    func end(bundleId: String?) {
        guard let bundleId, bundleId == currentBundleId else { return }
        let state = RoomActivityState(stage: currentStage ?? .ready)
        host.end(state: state, dismissAfter: clock().addingTimeInterval(Self.terminalDwell))
        #if DEBUG
        StagingHooks.breadcrumb("liveactivity-end \(bundleId) showing=\(stageName(state.stage))")
        #endif
        clearLocalState()
        logger.info("[LiveActivity] ended for \(bundleId, privacy: .public)")
    }

    /// Launch-time reconciliation. An activity can outlive the process that
    /// started it (force-quit, OS kill) — and it SHOULD, because the background
    /// URLSession that feeds it outlives the process too. So this does not blindly
    /// clear: it ADOPTS the activity belonging to the bundle the launch restore
    /// picked (so this process's progress updates reach the card the user is
    /// already looking at) and ends every other one. Same shape as the launch
    /// reaper's scan, and for the same reason.
    ///
    /// The stage is deliberately left nil after adoption: this process does not
    /// know what the card currently says, and the first real update publishes
    /// unconditionally (shouldPublish returns true on a nil previous), which is
    /// the correct outcome — one redundant update beats a wrong throttle.
    func reconcileOnLaunch(restoredBundleId: String?) {
        #if DEBUG
        StagingHooks.breadcrumb("liveactivity-reconcile keep=\(restoredBundleId ?? "nil")")
        #endif
        endOrphans(keeping: restoredBundleId)
        currentBundleId = restoredBundleId
        currentStage    = nil
        lastPublishedAt = nil
        #if DEBUG
        lastDropSignature = nil
        #endif
    }

    // MARK: - Internals

    private func apply(_ incoming: RoomActivityStage, for bundleId: String) {
        guard bundleId == currentBundleId else {
            logger.debug("[LiveActivity] dropped update for \(bundleId, privacy: .public) — not the active bundle")
            #if DEBUG
            // THE BREADCRUMB THAT MATTERS (decision 0111). This guard is the
            // invariant that stops a card narrating the wrong capture (0074, and
            // the stale doorway before it) — but it is also the one path that can
            // silently swallow the finalize/complete publishes, if a background
            // relaunch enqueues bundle.pb before reconcileOnLaunch has adopted
            // the card. De-duplicated by signature: an unadopted card would
            // otherwise write one line per blob completion, ~2,170 on a long walk.
            let signature = "\(bundleId)->\(currentBundleId ?? "nil")"
            if signature != lastDropSignature {
                lastDropSignature = signature
                StagingHooks.breadcrumb("liveactivity-drop \(bundleId) cur=\(currentBundleId ?? "nil")")
            }
            #endif
            return
        }
        let merged = LiveActivityPolicy.merge(current: currentStage, incoming: incoming)
        let now = clock()
        guard LiveActivityPolicy.shouldPublish(
            previous: currentStage, next: merged,
            lastPublishedAt: lastPublishedAt, now: now
        ) else {
            // Still record the merged stage: the throttle skipped PUBLISHING it,
            // not knowing it. Otherwise the next comparison is made against a
            // stale value and a slow trickle never publishes at all.
            currentStage = merged
            return
        }
        #if DEBUG
        // Stage-KIND changes only: the progress ticks inside `.sending` are the
        // throttle's business, and a line each would bury the transitions.
        if !LiveActivityPolicy.sameKind(currentStage ?? .preparing, merged) || currentStage == nil {
            StagingHooks.breadcrumb("liveactivity-publish \(stageName(merged)) \(bundleId)")
        }
        #endif
        currentStage    = merged
        lastPublishedAt = now

        if merged.isTerminal {
            host.end(state: RoomActivityState(stage: merged),
                     dismissAfter: now.addingTimeInterval(Self.terminalDwell))
            // Keep currentBundleId: a late duplicate terminal for the same bundle
            // must be recognised as "already ended", not adopted as a new card.
            logger.info("[LiveActivity] terminal \(String(describing: merged), privacy: .public) for \(bundleId, privacy: .public)")
        } else {
            host.update(state: RoomActivityState(stage: merged),
                        staleDate: now.addingTimeInterval(Self.staleAfter))
        }
    }

    private func endOrphans(keeping bundleId: String?) {
        host.endAllOrphans(keeping: bundleId)
    }

    #if DEBUG
    /// Stable short name for the breadcrumb file. `String(describing:)` on a
    /// stage with a payload prints the whole case, which is noise here.
    private func stageName(_ stage: RoomActivityStage) -> String {
        switch stage {
        case .preparing:  return "preparing"
        case .sending:    return "sending"
        case .finalizing: return "finalizing"
        case .queued:     return "queued"
        case .analyzing:  return "analyzing"
        case .ready:      return "ready"
        case .paused:     return "paused"
        case .failed(let which): return "failed-\(which.rawValue)"
        }
    }
    #endif

    private func clearLocalState() {
        currentBundleId = nil
        currentStage    = nil
        lastPublishedAt = nil
        #if DEBUG
        lastDropSignature = nil
        #endif
    }
}

// MARK: - Real ActivityKit host

/// The production seam implementation. Nothing above this line imports an
/// ActivityKit *call*, so the decision logic stays testable.
@MainActor
final class ActivityKitHost: LiveActivityHost {

    private let logger = Logger(subsystem: "com.roomstudio.RoomStudioCapture", category: "LiveActivity")
    private var activity: Activity<RoomActivityAttributes>?

    var areActivitiesEnabled: Bool { ActivityAuthorizationInfo().areActivitiesEnabled }
    var isRunning: Bool { activity?.activityState == .active }

    func start(attributes: RoomActivityAttributes, state: RoomActivityState, staleDate: Date?) {
        do {
            // pushType nil — local updates only. See LiveActivityController.pushTokenSeam.
            activity = try Activity.request(
                attributes: attributes,
                content: ActivityContent(state: state, staleDate: staleDate),
                pushType: nil
            )
        } catch {
            // Advisory surface: a refusal (budget, Settings, unsupported) must not
            // touch the upload. Log and carry on.
            logger.info("[LiveActivity] request failed: \(error.localizedDescription)")
            activity = nil
        }
    }

    func update(state: RoomActivityState, staleDate: Date?) {
        guard let activity else { return }
        Task { await activity.update(ActivityContent(state: state, staleDate: staleDate)) }
    }

    func end(state: RoomActivityState, dismissAfter: Date?) {
        guard let activity else { return }
        let policy: ActivityUIDismissalPolicy = dismissAfter.map { .after($0) } ?? .default
        Task { await activity.end(ActivityContent(state: state, staleDate: nil), dismissalPolicy: policy) }
        self.activity = nil
    }

    func endAllOrphans(keeping bundleId: String?) {
        // `Activity.activities` includes activities started by a PREVIOUS launch —
        // which is the whole point of calling this at launch.
        for running in Activity<RoomActivityAttributes>.activities
        where running.attributes.bundleId != bundleId {
            Task { await running.end(nil, dismissalPolicy: .immediate) }
        }
        if let bundleId {
            activity = Activity<RoomActivityAttributes>.activities
                .first { $0.attributes.bundleId == bundleId }
        } else {
            activity = nil
        }
    }
}
