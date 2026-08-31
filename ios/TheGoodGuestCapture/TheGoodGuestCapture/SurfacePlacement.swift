/// Where each post-send state now lives, as a pure function.
///
/// WHAT CHANGED. Until now every post-send state rendered on one surface: the
/// user sent a room and stayed on a screen that became, in turn, the wait, the
/// doorway, or one of six failure treatments. The 2b design splits that by what
/// a state IS rather than by when it happens:
///
///   • THE DESK — a room still on its way. Something is happening, or will
///     happen, without the user doing anything. Reached from home's sentence
///     while a room is in flight.
///   • NOTES — a room that is finished and failed, waiting to be acknowledged.
///     Nothing more will happen to it on its own. Reached from home's sentence
///     when something needs the user.
///   • THE DOORWAY — the arrival, unchanged. A moment, not a screen you live
///     on; Notes keeps the record afterwards.
///
/// THE SEAM THIS SITS ON. `WaitFlowState` already decides which state a sent
/// capture is in, and that table is correct and heavily tested — it is not
/// re-litigated here. This function takes its answer and says where the answer
/// belongs now. Keeping them separate is deliberate: what state a room is in is
/// a question about the backend, and where that state is shown is a question
/// about the app's shape. Folding them together is how a routing table acquires
/// a second job and stops being reviewable.
///
/// THE ONE JUDGEMENT IN HERE is `sendFailed`, which splits on `terminal`:
///
///   • retryable → the desk. Nothing left the phone, the capture is intact,
///     and trying again genuinely works. That is a room still on its way, and
///     putting it in Notes would ask the user to acknowledge something that has
///     not finished happening.
///   • terminal → a note. Retrying provably cannot fix it, so the only thing
///     left is for the user to know.
///
/// `notOurs` is placed nowhere, deliberately. It is decision 0074's
/// terminal-not-ours case, which stands itself down on the same publish that
/// produces it — it renders for at most a frame on the way home, and giving it
/// a surface would mean building a screen for a state that erases itself.
///
/// Read by: RootFlowView. Pinned by: SurfacePlacementTests.

import Foundation

// MARK: - The desk

/// A room still on its way. Every case here resolves on its own, or resumes on
/// the next launch, without the user deciding anything.
nonisolated enum DeskState: Equatable {
    /// Bytes are moving, or the session is being set up. Nothing has arrived.
    case sending
    /// Uploaded and being rebuilt. `anchor` is the server's own clock — the
    /// only honest thing to count from, and nil until the first successful poll.
    case working(anchor: Date?, longRunning: Bool)
    /// The upload stopped for this launch and resumes on the next one. Nothing
    /// for the user to do, which the copy has to say plainly.
    case paused
    /// The daily cap. Lifts by itself; `resetsAt` is when, or nil if the server
    /// did not say.
    case rateLimited(resetsAt: Date?)
    /// The send failed in a way retrying can fix. The one desk state with an
    /// action attached.
    case retryableSendFailure
    /// Uploaded, but the status check is not landing. The room is safe; the
    /// phone just cannot see it. `stopped` means the loop gave up and only a
    /// tap will restart it.
    case checkFailed(anchor: Date?, stopped: Bool)
}

// MARK: - Notes

/// A finished, failed room waiting to be acknowledged. Every case here is
/// terminal: nothing further happens without the user.
nonisolated enum NoteKind: Equatable {
    /// The blobs failed terminally — no scene will ever exist. Carries the
    /// persisted reason, which is the only diagnostic the user has.
    case uploadFailed(reason: String?)
    /// The pipeline finished in a hard-failed state.
    case processingFailed
    /// The send was refused in a way retrying cannot fix.
    case sendFailedTerminal
    /// Not all of the room's data arrived. The ONE note that opens a screen
    /// rather than just being acknowledged: whether the missing bytes can be
    /// re-sent is a question about this phone's disk, and answering it needs
    /// the recovery surface, not a card.
    case incompleteUpload(missingCount: Int)
}

extension NoteKind {
    /// Whether acknowledging is the whole interaction. False for the one note
    /// that carries a real recovery path.
    var isAcknowledgeOnly: Bool {
        if case .incompleteUpload = self { return false }
        return true
    }
}

// MARK: - Placement

/// Where a post-send state is shown.
nonisolated enum SurfacePlacement: Equatable {
    case desk(DeskState)
    case note(NoteKind)
    /// The arrival moment. Notes keeps the record; this is shown once.
    case doorway
    /// Shown nowhere — the state stands itself down. See `notOurs` above.
    case nowhere
}

nonisolated enum SurfaceRouter {

    /// Place a decided wait state.
    ///
    /// Total over `WaitScreen` on purpose: a state added to that enum without a
    /// home here should fail to compile rather than silently vanish from the
    /// app, which is exactly what a `default` branch would allow.
    static func placement(for screen: WaitScreen) -> SurfacePlacement {
        switch screen {
        case .sending:
            return .desk(.sending)

        case .waiting(let phase, let anchor):
            // `queued` and `analyzing` are one desk state: both mean the room is
            // up and being worked on, and the difference between them is a
            // sentence, not a surface. `longRunning` is kept because the copy
            // turns candid at that point.
            return .desk(.working(anchor: anchor, longRunning: phase == .longRunning))

        case .checkFailed(let anchor, let stopped):
            return .desk(.checkFailed(anchor: anchor, stopped: stopped))

        case .sendPaused:
            return .desk(.paused)

        case .sendRateLimited(let resetsAt):
            return .desk(.rateLimited(resetsAt: resetsAt))

        case .sendFailed(let terminal):
            // The one judgement in this file — see the header.
            return terminal ? .note(.sendFailedTerminal) : .desk(.retryableSendFailure)

        case .uploadFailed:
            // The reason is read from the failure monitor at the call site; the
            // placement itself does not need it and must not go looking.
            return .note(.uploadFailed(reason: nil))

        case .processingFailed:
            return .note(.processingFailed)

        case .incompleteUpload(let missingCount):
            return .note(.incompleteUpload(missingCount: missingCount))

        case .doorway:
            return .doorway

        case .notOurs:
            return .nowhere
        }
    }

    /// Whether this state puts something in front of the user that needs a
    /// decision. Feeds `HomeDay.needsYou`, which is what turns home's sentence
    /// rust and points it at Notes.
    static func needsUser(_ screen: WaitScreen) -> Bool {
        if case .note = placement(for: screen) { return true }
        return false
    }

    /// Whether a room is still on its way. Feeds `HomeDay.hasRoomInFlight`.
    ///
    /// True for every desk state INCLUDING the retryable send failure and the
    /// paused upload: from home's point of view the room has not finished and
    /// has not failed, and the desk is where it is being dealt with. A user who
    /// is told "nothing is happening" about a capture sitting on their phone
    /// waiting to retry has been told something false.
    static func isInFlight(_ screen: WaitScreen) -> Bool {
        if case .desk = placement(for: screen) { return true }
        return false
    }
}
