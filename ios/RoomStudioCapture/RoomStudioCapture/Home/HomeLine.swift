/// Home's one sentence, as a pure function.
///
/// The 2b design gives home three things and nothing else: the claim, the
/// pinned action, and ONE sentence that reports. Everything home used to stack
/// — the upload-failed banner, the re-entry row, the rooms-trouble line — now
/// lives on a screen of its own, and this sentence is the only thing that says
/// so. It routes: tap it and you land where the news actually is.
///
/// WHY A PURE FUNCTION. The sentence has to pick one of four things to be, from
/// four independent inputs, and it must never say two of them. That is a
/// routing table, and this repo's standing rule is that a routing table is
/// stated once, reads as a table, and is pinned by tests rather than by eye
/// (WaitFlowState, BundleRestore, CaptureReclaim, FailureCopy all got the same
/// treatment). A @ViewBuilder that decided this inline would be reviewable only
/// by reading SwiftUI.
///
/// PRIORITY, highest first — the design's own order:
///   1. needs-you  → Notes    · rust, the only urgency colour in the app
///   2. arrival    → doorway  · gold, because gold means light arriving
///   3. in flight  → desk     · gold, quiet
///   4. otherwise  → house    · no colour; a standing fact, kept warm
///
/// The one sentence may MENTION a lower-priority fact while routing to the
/// higher one ("Something here needs you — and today's room is on its way"),
/// which is how the design keeps it to one sentence without dropping half the
/// day. It never routes to two places.
///
/// THE HONESTY CONSTRAINT lands here in one specific way: the quiet line wants
/// to state a count, and a count is exactly what the phone stops knowing when
/// the rooms fetch fails. `RoomsLoadState` already refuses to collapse "none"
/// with "couldn't ask", and this function inherits that refusal — an unknown
/// count produces a line that states no number rather than a zero.
///
/// Read by: HomeView. Pinned by: HomeLineTests.

import Foundation

// MARK: - Where the sentence points

/// The screen home's sentence hands you to. `you` is deliberately absent: the
/// profile is reached from the contents sheet, never from the reporting line.
nonisolated enum HomeDestination: Equatable {
    /// Needs-you items and news (the Notes screen).
    case notes
    /// A room that has finished and has not been stepped into yet.
    case doorway
    /// The room currently in flight (the Desk screen).
    case desk
    /// The rooms that have landed (the House screen).
    case house
}

/// How the sentence is inked. Not a palette choice — a semantic one, and the
/// rule of gold is enforced here rather than at the call site: gold is light
/// arriving, rust is the single urgency colour, quiet is everything else.
/// Nothing in this app may use gold to mean success or rust to mean error.
nonisolated enum HomeLineTone: Equatable {
    /// Something needs a decision from the user. Rust.
    case needsYou
    /// A room has arrived. Gold.
    case arrival
    /// Work is in progress and nothing is wrong. Gold, quieter.
    case inFlight
    /// A standing fact. Ink, no accent.
    case quiet
}

/// The rendered sentence and where it goes.
nonisolated struct HomeLine: Equatable {
    let text: String
    let destination: HomeDestination
    let tone: HomeLineTone
}

// MARK: - What the day looks like

/// Everything the sentence is allowed to consider, reduced to what routing
/// actually uses.
///
/// `roomCount` is Optional for the reason the whole app is careful about:
/// nil is "the phone could not ask", which is not zero, and the line must not
/// turn it into one.
nonisolated struct HomeDay: Equatable {
    /// How many items are waiting for a decision — failures, a fetch that
    /// could not be retried, anything with an action attached.
    var needsYou: Int = 0
    /// A room finished and the user has not stepped into it yet.
    var hasUnseenArrival: Bool = false
    /// A capture is uploading or being rebuilt right now.
    var hasRoomInFlight: Bool = false
    /// Rooms that have landed, or nil when the phone could not ask.
    var roomCount: Int? = nil
    /// True before the user has ever sent anything — the first-run screen,
    /// which reports nothing because there is nothing yet to report.
    var isFirstRun: Bool = false
}

// MARK: - The table

nonisolated enum HomeLineResolver {

    /// The sentence for a given day, or nil on first run.
    ///
    /// Nil rather than an empty string: first run has no news, and the design
    /// gives that space to the one-time whisper that teaches where everything
    /// lives. A caller that renders an empty sentence would leave a gap where
    /// the teaching line belongs.
    static func line(for day: HomeDay) -> HomeLine? {
        guard !day.isFirstRun else { return nil }

        if day.needsYou > 0 {
            return HomeLine(text: needsYouText(day),
                            destination: .notes,
                            tone: .needsYou)
        }
        if day.hasUnseenArrival {
            return HomeLine(text: "A room arrived — come see.",
                            destination: .doorway,
                            tone: .arrival)
        }
        if day.hasRoomInFlight {
            return HomeLine(text: "Today's room is on its way — I'm at the desk with it.",
                            destination: .desk,
                            tone: .inFlight)
        }
        return HomeLine(text: quietText(day.roomCount),
                        destination: .house,
                        tone: .quiet)
    }

    // MARK: Copy

    /// Needs-you carries the flight as a subordinate clause when both are true,
    /// so one sentence covers the day without ever routing to two places.
    private static func needsYouText(_ day: HomeDay) -> String {
        day.hasRoomInFlight
            ? "Something here needs you — and today's room is on its way."
            : "Something here needs you."
    }

    /// The standing fact. States a count only when one is known.
    ///
    /// The nil branch is the honesty constraint, not a fallback: a failed fetch
    /// is not zero rooms, and this line has no standing to imply either a
    /// number or an absence. It says where things are and stops.
    private static func quietText(_ roomCount: Int?) -> String {
        guard let roomCount else {
            return "All quiet — everything you've sent is in the house."
        }
        switch roomCount {
        case ..<1:  return "All quiet — nothing sent yet."
        case 1:     return "All quiet — one room, on your desk."
        default:    return "All quiet — \(roomCount) rooms, on your desk."
        }
    }
}
