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
enum WaitScreen: Equatable {
    /// Handing the capture over, or uploading it: nothing has arrived yet.
    case sending
    /// Uploaded and being worked on. `anchor` is the SERVER-side scene start, nil
    /// until the first successful poll delivers it.
    case waiting(phase: WaitPhase, anchor: Date?)
    /// The room is ready — the doorway.
    case doorway
    /// The pipeline finished in a hard-failed state.
    case processingFailed
    /// The upload was incomplete (failed_incomplete).
    case incompleteUpload
    /// Could not send it up. `terminal` = retrying provably cannot help.
    case sendFailed(terminal: Bool)
    /// The blobs for THIS capture failed terminally — no Scene will ever exist.
    case uploadFailed
    /// Lost contact while checking on an uploaded room; `stopped` = loop is dead.
    case checkFailed(anchor: Date?, stopped: Bool)
}

/// The narrated sub-state of an in-flight room (mirrors WaitingView.Phase's
/// analyzing family, without the failure cases).
enum WaitPhase: Equatable { case queued, analyzing, longRunning }

enum WaitFlowState {

    /// Decide the screen. Order matters and is the whole point:
    ///
    /// 1. A failed upload SESSION outranks everything — no bytes moved.
    /// 2. A terminal blob failure for THIS bundle outranks the poll, because the
    ///    poller cannot know: bundle.pb never lands, so it 404s forever by design.
    /// 3. Otherwise the poll state decides, and `.idle` means "not polling yet",
    ///    which during a send means still uploading — never "analyzing".
    static func screen(
        session: SessionOutcome,
        terminalBlobFailureForThisBundle: Bool,
        poll: PollSnapshot
    ) -> WaitScreen {
        if case .failed(let terminal) = session { return .sendFailed(terminal: terminal) }
        if terminalBlobFailureForThisBundle { return .uploadFailed }

        switch poll {
        case .idle:
            return .sending
        case .polling(let queued, let longRunning, let connectionTrouble, let anchor):
            if connectionTrouble { return .checkFailed(anchor: anchor, stopped: false) }
            let phase: WaitPhase = longRunning ? .longRunning : (queued ? .queued : .analyzing)
            return .waiting(phase: phase, anchor: anchor)
        case .succeeded:
            return .doorway
        case .failedTerminal:
            return .processingFailed
        case .recoverable:
            return .incompleteUpload
        case .pollError(let anchor):
            return .checkFailed(anchor: anchor, stopped: true)
        }
    }

    /// The upload-session half of the input, reduced to what routing needs.
    enum SessionOutcome: Equatable {
        case pending
        case ready
        case failed(terminal: Bool)
    }

    /// The poll half, reduced likewise. `anchor` is always the server-side scene
    /// creation time — never a client-side stand-in.
    enum PollSnapshot: Equatable {
        case idle
        case polling(queued: Bool, longRunning: Bool, connectionTrouble: Bool, anchor: Date?)
        case succeeded
        case failedTerminal
        case recoverable
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
