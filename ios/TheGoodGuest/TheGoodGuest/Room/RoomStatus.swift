/// What a room's own screen says and offers, as a pure table.
///
/// The redesign of 2026-11-10 gives every room one screen. The desk (a room on
/// its way), Notes (a room that needs you) and What's missing (the re-send)
/// were three places; they are now states of that screen, so a problem is read
/// where the room is. This file is their copy and their actions, merged: the
/// routing that decides WHICH state a room is in is still `SurfaceRouter` and
/// `FailureCopy`, unchanged and still pinned by their own tests.
///
/// THE SHAPE. Three steps — sent from your phone, being rebuilt, ready to open —
/// the same three the website's guest narrates while a room is rebuilt. Each
/// step is done, happening now, waiting, paused or in trouble, with at most one
/// line under it. Then the guest's own sentence, then at most two actions.
///
/// THE HONESTY RULES carried over from the screens this replaces:
///   • No estimate, ever. An elapsed time appears only with a server anchor,
///     and is counted from it; without one the step simply has no time.
///   • A reset time is said only when the server named one.
///   • Nothing says a file is safe on the phone where the next tap deletes it.
///   • No step or sentence blames the person.
///   • Times and counts are words in the interface face: mono is for
///     measurements, and there are no capitals-and-middle-dot status lines.
///
/// Read by: RoomScreen, RoomCards (for the card's one-line status), the
/// gallery. Pinned by: RoomStatusTests.

import Foundation

// MARK: - The pieces

/// One step of a room's way from the phone to the screen.
nonisolated struct RoomStep: Equatable {
    enum Mark: Equatable {
        case done
        case now
        case waiting
        case paused
        case attention
    }

    let title: String
    var detail: String? = nil
    let mark: Mark
}

/// What a button on the room screen does. Bound to real work by RootFlowView.
nonisolated enum RoomAction: Equatable {
    /// Send the scan again (it never left the phone).
    case sendAgain
    /// Restart the status check that gave up.
    case checkAgain
    /// Send only the files that did not arrive.
    case sendMissing
    /// Walk the room again from the start.
    case scanAgain
    /// The person has read it; the room's record can be let go.
    case acknowledge
    /// Let this scan go: it is not sent, and its files are freed.
    case discard
    /// Back to the rooms, with nothing changed.
    case leave
}

nonisolated struct RoomButton: Equatable {
    let label: String
    let action: RoomAction
    var enabled = true
    /// Shows a spinner in the button: the action is running.
    var busy = false
}

/// Everything the room screen draws below its title.
nonisolated struct RoomStatus: Equatable {
    let steps: [RoomStep]
    let guest: String
    /// One plain line under the steps: when a limit lifts, or that leaving is fine.
    var note: String? = nil
    /// A diagnostic the person may want to pass on; shown behind Details.
    var details: String? = nil
    var primary: RoomButton? = nil
    var secondary: RoomButton? = nil

    /// The single line a room card shows for this state.
    var cardLine: String {
        let current = steps.first { $0.mark != .done } ?? steps.last
        guard let current else { return "" }
        if let detail = current.detail, current.mark == .now {
            return "\(current.title), \(detail)"
        }
        return current.title
    }

    /// Whether the card should mark this room as needing the person.
    var needsAttention: Bool {
        steps.contains { $0.mark == .attention }
    }
}

// MARK: - The table

nonisolated enum RoomStatusCopy {

    static let sent = RoomStep(title: "Sent from your phone", mark: .done)
    static let rebuiltLater = RoomStep(title: "Being rebuilt", mark: .waiting)
    static let readyLater = RoomStep(title: "Ready to open", mark: .waiting)

    static let leaving = "You can leave this screen. The room keeps rebuilding without the app open."
    static let working = "I’m inside — meeting each piece, working out where it stands."
    static let workingLong = "Slower than I hoped — your room has a lot going on, which is a compliment. I’m still at it."
    /// What is true of a scan that never left the phone. No record is written
    /// until the server accepts the send (UploadCoordinator), so the scan is
    /// held only while the app is open; the words say exactly that.
    static let kept = "Your scan is waiting on this phone. Keep the app open and send it when you can — if the app closes, you’ll need to walk the room again."

    /// A room on its way (the old desk's six states).
    static func onItsWay(_ state: DeskState, now: Date, locale: Locale = .current) -> RoomStatus {
        switch state {
        case .sending:
            return RoomStatus(
                steps: [RoomStep(title: "Sending from your phone", mark: .now), rebuiltLater, readyLater],
                guest: "You can put me away — sending carries on by itself."
            )

        case .working(let anchor, let longRunning):
            return RoomStatus(
                steps: [sent, rebuilding(anchor: anchor, now: now), readyLater],
                guest: longRunning ? workingLong : working,
                note: leaving
            )

        case .paused:
            return RoomStatus(
                steps: [RoomStep(title: "Sending paused",
                                 detail: "It carries on the next time you open the app",
                                 mark: .paused),
                        rebuiltLater, readyLater],
                guest: "Asleep until you next open me — there’s nothing for you to do."
            )

        case .rateLimited(let resetsAt):
            let lifted = resetsAt.map { $0 <= now } ?? false
            // What the person must DO goes first (0293): the scan is kept
            // only while the app is open, and at the largest text sizes a
            // sentence placed after the reason falls below the fold, under a
            // button that lets the scan go.
            let reason = lifted
                ? "I hit my limit for how many rooms I can take up today; the time it named has passed, so it should take this one now."
                : resetsAt == nil
                    ? "I’ve hit my limit for how many rooms I can take up today, and I wasn’t told when it lifts."
                    : "I’ve hit my limit for how many rooms I can take up today."
            return RoomStatus(
                steps: [RoomStep(title: "Not sent yet", detail: "Today’s limit is reached", mark: .attention),
                        rebuiltLater, readyLater],
                guest: kept + " " + reason,
                note: limitNote(resetsAt: resetsAt, now: now, locale: locale),
                // Sending before the reset is a refusal the person can predict,
                // so the button appears only once the named time has passed,
                // or when no time was named at all.
                primary: (resetsAt == nil || lifted) ? RoomButton(label: "Try sending it", action: .sendAgain) : nil,
                secondary: RoomButton(label: "Let this scan go", action: .discard)
            )

        case .retryableSendFailure:
            return RoomStatus(
                steps: [RoomStep(title: "Didn’t leave your phone",
                                 detail: "Nothing was sent, so nothing has started",
                                 mark: .attention),
                        rebuiltLater, readyLater],
                guest: "I couldn’t get it up just now. Nothing’s lost — it’s still here on this phone while the app is open.",
                primary: RoomButton(label: "Try again", action: .sendAgain),
                secondary: RoomButton(label: "Let this scan go", action: .discard)
            )

        case .checkFailed(_, let stopped):
            return RoomStatus(
                steps: [sent,
                        RoomStep(title: "Being rebuilt",
                                 detail: stopped ? "I’ve stopped checking on it" : "I can’t check on it just now",
                                 mark: stopped ? .attention : .now),
                        readyLater],
                guest: stopped
                    ? "I’ve lost my line to the server. Your room is safe up there; I just can’t check on it, and I’ve stopped trying."
                    : "I’ve lost my line to the server for a moment. Your room is safe up there — I’ll keep trying quietly.",
                primary: stopped ? RoomButton(label: "Check again", action: .checkAgain) : nil
            )
        }
    }

    /// A room that has stopped and needs the person (the old Notes cards).
    /// The incomplete upload is not here: it opens the re-send, `missing(...)`.
    static func needsYou(_ kind: NoteKind) -> RoomStatus {
        switch kind {
        case .uploadFailed(let reason):
            // The old card said the scan was "safe" above a button that freed
            // it. The send cannot be finished from here, so the words say so,
            // and the button that lets it go is named for what it does.
            return RoomStatus(
                steps: [RoomStep(title: "Stalled on the way up", mark: .attention), rebuiltLater, readyLater],
                guest: "This scan stalled on its way up, and I couldn’t finish sending it. One more walk of the room will do it.",
                details: reason,
                primary: RoomButton(label: "Scan the room again", action: .scanAgain),
                secondary: RoomButton(label: "Let this scan go", action: .discard)
            )
        case .processingFailed:
            return RoomStatus(
                steps: [sent, RoomStep(title: "Couldn’t be rebuilt", mark: .attention), readyLater],
                guest: "There’s nothing there I could honestly show you — and it’s not something you did.",
                primary: RoomButton(label: "Scan the room again", action: .scanAgain),
                secondary: RoomButton(label: "Got it", action: .acknowledge)
            )
        case .sendFailedTerminal:
            return RoomStatus(
                steps: [RoomStep(title: "Refused on the way up", mark: .attention), rebuiltLater, readyLater],
                guest: "Something on my end refused it. That’s my fault, not yours, and trying again won’t move it.",
                primary: RoomButton(label: "Got it", action: .acknowledge)
            )
        case .incompleteUpload(let missingCount):
            return missing(missingCount: missingCount, resend: .unavailable)
        }
    }

    /// Files that did not arrive, and what this phone can do about it (the old
    /// What's missing screen). The offer comes from `FailureCopy`, which is
    /// downstream of a disk check; this only words it.
    static func missing(missingCount: Int, resend: FailureCopy.Resend) -> RoomStatus {
        let actions = FailureCopy.recoverableActions(resend)
        let first: RoomStep = resend == .inFlight
            ? RoomStep(title: sendingMissingTitle(missingCount), mark: .now)
            : RoomStep(title: arrivedShortTitle(missingCount), mark: .attention)
        return RoomStatus(
            steps: [first,
                    RoomStep(title: "Being rebuilt", detail: "Waiting for the missing files", mark: .waiting),
                    readyLater],
            guest: FailureCopy.incompleteBody(missingCount: missingCount, resend: resend),
            primary: RoomButton(label: actions.primaryLabel,
                                action: roomAction(actions.primary),
                                enabled: actions.primaryEnabled,
                                busy: resend == .inFlight),
            secondary: RoomButton(label: actions.secondaryLabel, action: roomAction(actions.secondary))
        )
    }

    /// A room from the rooms list that is not this phone's current flight.
    /// Ready rooms open the ready screen instead and never reach this.
    static func listed(_ status: SceneStatus, sentAt: Date?, now: Date) -> RoomStatus {
        switch status {
        case .ready:
            return RoomStatus(steps: [sent, RoomStep(title: "Rebuilt", mark: .done),
                                      RoomStep(title: "Ready to open", mark: .done)],
                              guest: "It’s ready. Come in when you have a minute.")
        case .queued, .processing, .unknown:
            return RoomStatus(steps: [sent, rebuilding(anchor: sentAt, now: now), readyLater],
                              guest: working, note: leaving)
        case .failedIncomplete:
            return RoomStatus(
                steps: [RoomStep(title: "Sent, but some of it didn’t arrive", mark: .attention), rebuiltLater, readyLater],
                guest: "Part of this room didn’t finish its trip, so I can’t show it to you honestly. One more walk of the room will do it.",
                primary: RoomButton(label: "Scan the room again", action: .scanAgain)
            )
        case .failed, .failedInvalid:
            return RoomStatus(
                steps: [sent, RoomStep(title: "Couldn’t be rebuilt", mark: .attention), readyLater],
                guest: "There’s nothing there I could honestly show you — and it’s not something you did.",
                primary: RoomButton(label: "Scan the room again", action: .scanAgain)
            )
        }
    }

    // MARK: Pieces

    /// "Being rebuilt", with the time since the server anchor when there is one.
    static func rebuilding(anchor: Date?, now: Date) -> RoomStep {
        guard let anchor, now >= anchor else { return RoomStep(title: "Being rebuilt", mark: .now) }
        return RoomStep(title: "Being rebuilt",
                        detail: "\(RoomHistory.elapsedPhrase(from: anchor, to: now)) so far",
                        mark: .now)
    }

    /// When today's limit lifts, in plain words, or nil when the server named
    /// no time (or a time already past: that is not a time to wait for).
    static func limitNote(resetsAt: Date?, now: Date, locale: Locale = .current) -> String? {
        guard let resetsAt, resetsAt > now else { return nil }
        let hours = resetsAt.timeIntervalSince(now) / 3600
        let clock = timeText(resetsAt, locale: locale)
        if hours < 1 { return "I can take more rooms in under an hour, from \(clock)." }
        if hours < 2 { return "I can take more rooms in about an hour, from \(clock)." }
        if Calendar.current.isDate(resetsAt, inSameDayAs: now) {
            return "I can take more rooms later today, from \(clock)."
        }
        return "I can take more rooms tomorrow, from \(clock)."
    }

    /// A clock time in the reader's own convention (4:20 AM, or 04:20).
    static func timeText(_ date: Date, locale: Locale) -> String {
        let f = DateFormatter()
        f.locale = locale
        f.dateStyle = .none
        f.timeStyle = .short
        return f.string(from: date)
    }

    private static func arrivedShortTitle(_ missingCount: Int) -> String {
        switch missingCount {
        case ..<1: return "Sent, but some of it didn’t arrive"
        case 1:    return "Sent, but one file didn’t arrive"
        default:   return "Sent, but \(missingCount) files didn’t arrive"
        }
    }

    private static func sendingMissingTitle(_ missingCount: Int) -> String {
        switch missingCount {
        case ..<1: return "Sending what didn’t arrive"
        case 1:    return "Sending the missing file"
        default:   return "Sending the \(missingCount) missing files"
        }
    }

    private static func roomAction(_ action: FailureCopy.Action) -> RoomAction {
        switch action {
        case .resend: return .sendMissing
        case .rescan: return .scanAgain
        case .leave:  return .leave
        }
    }
}
