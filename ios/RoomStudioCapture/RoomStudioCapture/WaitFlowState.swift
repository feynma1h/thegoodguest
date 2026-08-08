/// The post-send routing decision, as a pure function.
///
/// WHY THIS EXISTS: which screen a sent capture shows is decided from three
/// independent inputs — the upload-session state, a possible terminal blob
/// failure, and the poll state. That decision lived spread across a @ViewBuilder
/// and several computed properties inside RootFlowView, where it could not be
/// tested and could only be reviewed by reading SwiftUI. Four review passes each
/// found a different hole in it (a stale outcome flashing on re-send, a wait that
/// claimed the room had arrived before upload, a terminal failure that polled
/// forever, a "trip" failure for a capture that never left the phone).
///
/// Keeping it here — a value type over plain inputs, no SwiftUI, no singletons —
/// means the routing table is stated once, reads as a table, and is pinned by
/// tests instead of by eye.
///
/// Read by: RootFlowView (the only caller). Pinned by: WaitFlowStateTests.

import SwiftUI

/// What the post-send surface should show.
/// nonisolated (with WaitPhase and WaitFlowState below): pure routing
/// vocabulary, consulted from MainActor views, nonisolated tests, and the
/// CaptureReaper-adjacent tables — the target's MainActor default isolation
/// must not attach to the Equatable conformances.
nonisolated enum WaitScreen: Equatable {
    /// Handing the capture over, or uploading it: nothing has arrived yet.
    case sending
    /// Uploaded and being worked on. `anchor` is the SERVER-side scene start, nil
    /// until the first successful poll delivers it.
    case waiting(phase: WaitPhase, anchor: Date?)
    /// The room is ready — the doorway.
    case doorway
    /// The pipeline finished in a hard-failed state.
    case processingFailed
    /// The upload was incomplete (failed_incomplete). `missingCount` is how many
    /// blob paths the server reported absent — a fact about the room worth
    /// stating, and separable from the re-upload that does NOT exist yet
    /// (decision 0084). 0 means the server named none, which the copy degrades
    /// to the unquantified wording rather than announcing "0 files".
    case incompleteUpload(missingCount: Int)
    /// Could not send it up. `terminal` = retrying provably cannot help.
    case sendFailed(terminal: Bool)
    /// The account's daily upload-session quota is spent (429, decision 0087).
    /// Neither a retry-now nor a dead end: it lifts by itself at `resetsAt`, and
    /// the capture is safe on disk until then. Its own screen because both of the
    /// existing failure treatments would lie — one invites a retry that provably
    /// fails, the other implies the capture is lost.
    case sendRateLimited(resetsAt: Date?)
    /// The upload PAUSED (retries exhausted this launch, or the process lost its
    /// context). It resumes on the next launch — not in this one — so the screen
    /// must stop implying that waiting here will do anything.
    case sendPaused
    /// The blobs for THIS capture failed terminally — no Scene will ever exist.
    case uploadFailed
    /// Lost contact while checking on an uploaded room; `stopped` = loop is dead.
    case checkFailed(anchor: Date?, stopped: Bool)
    /// The polled room belongs to a different identity (by-bundle 403 on a
    /// verified token — decision 0074, e.g. records migrated by an iCloud backup
    /// while the Firebase identity was minted fresh). The flow acknowledges the
    /// record and stands down automatically (standsDownAutomatically below), so
    /// this renders for at most a frame in passing.
    case notOurs
}

/// The narrated sub-state of an in-flight room (mirrors WaitingView.Phase's
/// analyzing family, without the failure cases).
nonisolated enum WaitPhase: Equatable { case queued, analyzing, longRunning }

nonisolated enum WaitFlowState {

    /// Decide the screen. Order matters and is the whole point:
    ///
    /// 1. A failed upload SESSION outranks everything — no bytes moved.
    /// 2. A terminal blob failure for THIS bundle outranks the poll, because the
    ///    poller cannot know: bundle.pb never lands, so it 404s forever by design.
    /// 3. Otherwise the poll state decides, and `.idle` means "not polling yet",
    ///    which during a send means still uploading — never "analyzing".
    static func screen(
        sessionFailure: SessionFailure?,
        terminalBlobFailureForThisBundle: Bool,
        deferredForThisBundle: Bool = false,
        poll: PollSnapshot
    ) -> WaitScreen {
        if let sessionFailure {
            switch sessionFailure {
            case .refused(let terminal):       return .sendFailed(terminal: terminal)
            case .rateLimited(let resetsAt):   return .sendRateLimited(resetsAt: resetsAt)
            }
        }
        if terminalBlobFailureForThisBundle { return .uploadFailed }

        switch poll {
        case .idle:
            // Only meaningful pre-poll: once polling starts the bytes are up, so a
            // stale deferral must never override a live wait.
            return deferredForThisBundle ? .sendPaused : .sending
        case .polling(let queued, let longRunning, let connectionTrouble, let anchor):
            if connectionTrouble { return .checkFailed(anchor: anchor, stopped: false) }
            let phase: WaitPhase = longRunning ? .longRunning : (queued ? .queued : .analyzing)
            return .waiting(phase: phase, anchor: anchor)
        case .succeeded:
            return .doorway
        case .failedTerminal:
            return .processingFailed
        case .recoverable(let missingCount):
            return .incompleteUpload(missingCount: missingCount)
        case .notOwned:
            return .notOurs
        case .pollError(let anchor):
            return .checkFailed(anchor: anchor, stopped: true)
        }
    }

    /// Whether this poll state ends the flight WITHOUT user action: acknowledge the
    /// record (the doorway-Done semantics) and return home. True exactly for
    /// terminal-not-ours (decision 0074) — a 403 on a verified token means this
    /// identity will never own that scene, so no user decision is being taken away
    /// by not asking. Every other terminal state carries an outcome the user should
    /// see (doorway, failure treatments), and every transient state must keep its
    /// screen.
    static func standsDownAutomatically(_ state: ScenePollState) -> Bool {
        if case .notOwned = state { return true }
        return false
    }

    /// Which record the stand-down acknowledges: the bundle the poller actually
    /// asked about (that is the id the 403 answered), falling back to the flight's
    /// id when the poller has already been reset. Both nil = nothing to acknowledge.
    static func foreignBundleToAcknowledge(pollerBundleId: String?, sentBundleId: String?) -> String? {
        pollerBundleId ?? sentBundleId
    }

    /// The upload-session half of the input, reduced to WHAT ROUTING ACTUALLY USES:
    /// only refusal changes the screen. Modelling .pending/.ready as distinct cases
    /// implied a routing input that did not exist — it read as coverage in a table
    /// test without being any.
    ///
    /// An enum rather than a struct of flags since the rate limit arrived: it is
    /// not a degree of `terminal`, it is a different kind of "no" — one that answers
    /// differently tomorrow — and expressing it as a third boolean state would have
    /// made two of the four combinations unreachable.
    enum SessionFailure: Equatable {
        /// The server (or a local invariant) refused the send. `terminal` = retrying
        /// provably cannot fix it (a 4xx, a 403, a broken invariant).
        case refused(terminal: Bool)
        /// The daily mint quota is spent; it lifts at `resetsAt` on its own.
        case rateLimited(resetsAt: Date?)
    }

    /// Adapt the real coordinator state. Lives here, beside the table it feeds, so
    /// the adapter is testable too: a correct table fed a wrong snapshot is still
    /// the wrong screen.
    static func sessionFailure(from state: UploadCoordinator.SessionState) -> SessionFailure? {
        switch state {
        case .failed(_, let terminal):    return .refused(terminal: terminal)
        case .rateLimited(let resetsAt):  return .rateLimited(resetsAt: resetsAt)
        default:                          return nil
        }
    }

    /// Adapt the real poll state. `fallbackAnchor` supplies the server anchor for
    /// `.pollError`, which carries no payload of its own.
    static func snapshot(from state: ScenePollState, fallbackAnchor: Date?) -> PollSnapshot {
        switch state {
        case .idle:
            return .idle
        case .polling(let latest, _, let sceneCreatedAt, let longRunning, let connectionTrouble):
            return .polling(queued: latest == .queued,
                            longRunning: longRunning,
                            connectionTrouble: connectionTrouble,
                            anchor: sceneCreatedAt)
        case .succeeded:      return .succeeded
        case .failedTerminal: return .failedTerminal
        // Only the COUNT crosses into routing. The paths themselves are plumbing
        // ("frames/000005.jpg") — the same category as the raw `http_404` the
        // walk called out as leaking, and not something a user can act on.
        case .recoverable(let paths): return .recoverable(missingCount: paths.count)
        case .notOwned:       return .notOwned
        case .pollError:      return .pollError(anchor: fallbackAnchor)
        }
    }

    /// The poll half, reduced likewise. `anchor` is always the server-side scene
    /// creation time — never a client-side stand-in.
    enum PollSnapshot: Equatable {
        case idle
        case polling(queued: Bool, longRunning: Bool, connectionTrouble: Bool, anchor: Date?)
        case succeeded
        case failedTerminal
        case recoverable(missingCount: Int)
        case notOwned
        case pollError(anchor: Date?)
    }
}

extension WaitPhase {
    /// Presentation bridge. WaitPhase stays free of the view layer so the routing
    /// table can be tested without SwiftUI.
    var waitingPhase: WaitingView.Phase {
        switch self {
        case .queued:      return .queued
        case .analyzing:   return .analyzing
        case .longRunning: return .longRunning
        }
    }
}
