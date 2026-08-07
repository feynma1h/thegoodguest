/// The three decisions behind the capture Live Activity, as pure functions.
///
/// WHY THIS EXISTS: the activity is fed from two places that cannot see each
/// other — the background URLSession completion path (which knows blob progress
/// and nothing else) and the foreground routing table (which knows the scene's
/// state and nothing about blobs). Merging two partial views of one capture,
/// deciding when a change is worth spending an ActivityKit update on, and mapping
/// the app's own WaitScreen onto the Lock Screen's vocabulary are all decisions —
/// and every one of them was a candidate for living inside an `if` in a completion
/// handler, where it could only be reviewed by reading and never by test. Same
/// treatment the rest of this app's decisions got (WaitFlowState, BundleRestore,
/// CaptureReclaim): a table over plain values.
///
/// Read by: LiveActivityController. Pinned by: LiveActivityPolicyTests.

import Foundation

nonisolated enum LiveActivityPolicy {

    // MARK: - Constants

    /// Floor between two published updates for the SAME stage kind. ActivityKit
    /// rate-limits an app that updates without restraint, and a real capture
    /// completes 127–2,170 blobs: publishing every completion would spend the
    /// budget within seconds of the send and get the later, more useful updates
    /// dropped. Stage CHANGES bypass this entirely — those are the information.
    static let minProgressInterval: TimeInterval = 2.0

    /// Progress must move at least this far (in whole percent) to be worth an
    /// update. Below it the Lock Screen shows the same number it already shows.
    static let minProgressStepPercent = 1

    // MARK: - Merge (two partial views of one capture)

    /// Fold an incoming stage into the current one.
    ///
    /// THE STICKY RULE: a terminal stage is never overwritten by a non-terminal
    /// one. Blob completions land on the background session for a while after the
    /// bundle is finalized, and a late `.sending(126, 127)` arriving after the
    /// poller said `.ready` would reopen the upload on the Lock Screen for a room
    /// that is already done. Terminal-over-terminal IS allowed: a poller that
    /// hard-fails after a local upload failure is a more informed answer.
    static func merge(current: RoomActivityStage?, incoming: RoomActivityStage) -> RoomActivityStage {
        guard let current else { return incoming }
        if current.isTerminal && !incoming.isTerminal { return current }
        return incoming
    }

    // MARK: - Publish throttle

    /// Whether `next` is worth an ActivityKit update.
    ///
    /// - A first publish always goes.
    /// - A change of stage KIND always goes (preparing → sending → ready …).
    /// - A terminal stage always goes, immediately: it ends the activity.
    /// - Progress within `.sending` goes only when it moved a whole step AND the
    ///   interval has elapsed — except a completed upload (sent == total), which
    ///   is the one progress value worth the budget regardless.
    static func shouldPublish(
        previous: RoomActivityStage?,
        next: RoomActivityStage,
        lastPublishedAt: Date?,
        now: Date
    ) -> Bool {
        guard let previous else { return true }
        if next.isTerminal { return true }
        if !sameKind(previous, next) { return true }

        guard case .sending(let nextSent, let nextTotal) = next,
              case .sending(let prevSent, let prevTotal) = previous
        else {
            // Same non-sending kind, nothing inside it changed.
            return false
        }
        if nextTotal != prevTotal { return true }
        if nextTotal > 0 && nextSent >= nextTotal { return true }

        let stepped = percent(sent: nextSent, total: nextTotal)
            - percent(sent: prevSent, total: prevTotal) >= minProgressStepPercent
        guard stepped else { return false }
        guard let lastPublishedAt else { return true }
        return now.timeIntervalSince(lastPublishedAt) >= minProgressInterval
    }

    /// Stage kind ignoring payload — two `.sending`s are the same kind, a
    /// `.sending` and a `.queued` are not.
    static func sameKind(_ a: RoomActivityStage, _ b: RoomActivityStage) -> Bool {
        switch (a, b) {
        case (.preparing, .preparing), (.sending, .sending), (.queued, .queued),
             (.analyzing, .analyzing), (.ready, .ready), (.paused, .paused):
            return true
        case (.failed(let x), .failed(let y)):
            return x == y
        default:
            return false
        }
    }

    private static func percent(sent: Int, total: Int) -> Int {
        guard total > 0 else { return 0 }
        return Int((Double(sent) / Double(total) * 100).rounded(.down))
    }

    // MARK: - The app's routing table → the Lock Screen's vocabulary

    /// Map the screen the app itself decided to show onto a Live Activity stage.
    ///
    /// `nil` means "this screen carries nothing the Lock Screen doesn't already
    /// know" — leave the activity alone. Two screens map that way on purpose:
    ///
    ///   • `.sending` — the routing table's "sending" covers session setup AND the
    ///     whole blob upload, which is exactly what the background path already
    ///     reports in finer grain. Overriding it here would throw away the count.
    ///   • `.checkFailed` — the room IS up there and the pipeline is working; a
    ///     connectivity blip on OUR side of the poll is not a failure of the
    ///     capture, and flipping the Lock Screen to a failure treatment for it
    ///     would be the surface lying about the room's fate.
    ///
    /// `.notOurs` also maps to nil: the flow stands down and ends the activity
    /// outright (decision 0074) rather than narrating a room this identity never
    /// owned.
    static func stage(for screen: WaitScreen) -> RoomActivityStage? {
        switch screen {
        case .sending:                  return nil
        case .checkFailed:              return nil
        case .notOurs:                  return nil
        case .waiting(let phase, _):    return phase == .queued ? .queued : .analyzing
        case .doorway:                  return .ready
        case .processingFailed:         return .failed(.processing)
        case .incompleteUpload:         return .failed(.incomplete)
        case .uploadFailed:             return .failed(.upload)
        // Nothing left the phone. From the Lock Screen's point of view that is the
        // same fact as a blob failure — "it didn't get up there" — and the in-app
        // screen owns the distinction between "retryable" and "our bug".
        case .sendFailed:               return .failed(.upload)
        // The daily cap gets the same treatment for the same reason, and it maps to
        // failed rather than paused deliberately: `.paused` promises the upload
        // resumes on the next app open, which is exactly what will NOT happen until
        // the quota rolls. The card's job is to stop implying motion; the screen
        // behind it owns "here is when it lifts".
        case .sendRateLimited:          return .failed(.upload)
        case .sendPaused:               return .paused
        }
    }
}
