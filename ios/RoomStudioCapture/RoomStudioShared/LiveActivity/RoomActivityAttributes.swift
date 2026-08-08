/// The ActivityKit contract for the capture Live Activity (design spec §5).
///
/// WHY IT LIVES IN `RoomStudioShared/`: an ActivityAttributes type must be the
/// SAME type in the app (which starts and updates the activity) and in the widget
/// extension (which renders it). Two structurally-identical copies would encode
/// and decode fine right up until one side gained a case — so there is exactly one
/// declaration, compiled into both targets via the shared synchronized folder.
///
/// STAGES ARE WHAT THE PHONE CAN HONESTLY KNOW. Upload progress is real in the
/// background: the blob PUTs run on a background URLSession that outlives the app
/// being foregrounded, so `.sending` keeps ticking on the Lock Screen with the app
/// closed. The post-upload stages (`.queued`/`.analyzing`/`.ready`) come from the
/// scene poller, which only runs while the app is alive — so they update whenever
/// the user is in the app and then persist on the Lock Screen. Closing that gap
/// needs remote push updates (`pushType: .token`), which is enrollment-gated; the
/// seam is named in LiveActivityController.pushTokenSeam.
///
/// Read by: LiveActivityController (app), RoomUploadLiveActivity (extension).
/// Pinned by: LiveActivityVoiceTests, LiveActivityPolicyTests.

import ActivityKit
import Foundation

/// Static, fixed for the life of one activity. Everything that changes lives in
/// ContentState — ActivityKit cannot update attributes after `request`.
///
/// nonisolated: the app target defaults to MainActor isolation
/// (SWIFT_DEFAULT_ACTOR_ISOLATION), and an actor-isolated Codable conformance is
/// a Swift 6 error when ActivityKit encodes off the main actor.
nonisolated struct RoomActivityAttributes: ActivityAttributes {
    typealias ContentState = RoomActivityState

    /// The capture this activity is about. The controller keys every update on it
    /// so a stale activity from a previous capture can never be driven by a new
    /// one's progress.
    let bundleId: String
    /// When the send started, for the Lock Screen's elapsed read.
    let startedAt: Date
}

/// The mutable half — one stage, nothing else. Deliberately not a bag of optional
/// fields: every renderable difference is a distinct stage, so the extension's
/// views switch over a closed set instead of reconstructing intent from flags.
nonisolated struct RoomActivityState: Codable, Hashable, Sendable {
    var stage: RoomActivityStage

    init(stage: RoomActivityStage) { self.stage = stage }
}

/// Where the capture is. Mirrors the in-app wait surfaces one-for-one (the
/// WaitScreen routing table), because the Lock Screen contradicting the screen
/// the user just left is the failure mode that matters here.
nonisolated enum RoomActivityStage: Codable, Hashable, Sendable {
    /// Signed in, manifest building, minting the upload session. Real time on a
    /// long walk (a 2,170-path mint measured 14 s), so it gets an honest stage
    /// rather than a fake 0-of-0 progress bar.
    case preparing
    /// Blobs in flight. `total` counts the non-bundle.pb blobs — bundle.pb goes
    /// last, after the gate, and counting it would show 99% for the whole upload.
    case sending(sent: Int, total: Int)
    /// Every blob is up and the `bundle.pb` finalize (~51 KB) is enqueued. Its
    /// arrival in GCS is what makes the capture exist server-side, so until it
    /// lands there is genuinely no room up there yet.
    ///
    /// ITS OWN STAGE for two reasons, both from the decision-0085 walk:
    /// `.sending(N, N)` is a completed count still labelled in progress — the
    /// stale card that read "Sending your room 331 of 331" — and this one task
    /// can be held by the OS for many minutes when it was enqueued by a
    /// background-relaunched process (decision 0110). The copy therefore states
    /// what is KNOWN and names the action that releases the hold, rather than
    /// predicting which branch we are in.
    case finalizing
    /// Uploaded; the pipeline hasn't picked it up yet.
    case queued
    /// The pipeline is working on it.
    case analyzing
    /// Terminal, good: the doorway is open.
    case ready
    /// The upload stopped for this launch (retries exhausted / context lost). It
    /// resumes when the app is next opened — NOT by waiting, which is why this is
    /// its own stage rather than a flavour of `.sending`.
    case paused
    /// Terminal, bad.
    case failed(RoomActivityFailure)
}

/// Which half of the trip failed. The Lock Screen never shows the raw reason
/// string (`http_404`, `308_persistent`): that is diagnostic text for the in-app
/// failure screen, not for a surface a stranger can read over a shoulder.
nonisolated enum RoomActivityFailure: String, Codable, Hashable, Sendable {
    /// The blobs never made it up — no scene will ever exist.
    case upload
    /// The pipeline hard-failed on a room that did arrive.
    case processing
    /// `failed_incomplete`: some of the room's data is missing up there.
    case incomplete
}

extension RoomActivityStage {
    /// Terminal stages END the activity (after a dwell) instead of updating it,
    /// and are STICKY against late background progress updates — a blob completion
    /// arriving after the poller said `ready` must not reopen the upload.
    var isTerminal: Bool {
        switch self {
        case .ready, .failed: return true
        case .preparing, .sending, .finalizing, .queued, .analyzing, .paused: return false
        }
    }

    /// 0…1 for the determinate stages, nil where a bar would be inventing a number.
    var fraction: Double? {
        guard case .sending(let sent, let total) = self, total > 0 else { return nil }
        return min(1.0, max(0.0, Double(sent) / Double(total)))
    }
}
