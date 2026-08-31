/// What the phone can honestly say about a room it has sent, derived from
/// GET /scenes and nothing else.
///
/// The phone is "a camera with a memory of what it's sent, not a library"
/// (design spec §9), so everything here is deliberately thin: a room has no
/// name until the guest gives it one on the web, and /scenes carries no name
/// field, so titles are derived from the day the room was sent. Two rooms sent
/// on the same day would otherwise be two identical rows, which is why
/// `summaries(from:now:)` takes the whole list — the disambiguation is a fact
/// about the list, not about any one room in it.
///
/// Every function here is pure and takes `now` explicitly, so the copy is
/// pinned as a table rather than read out of SwiftUI (the iOS test policy's
/// standing rule). Nothing here invents a number: an unparseable `created_at`
/// produces a room with no date in its name, never a guessed one.
///
/// Read by: RoomsStore (the mapping), RoomsListView / RecentRoomsStrip (the
/// rendered result).

import Foundation

// MARK: - RoomSummary

/// One room in the thin history. `id` is the scene id; `bundleId` is what the
/// web handoff needs (NetworkConfig.webRoomURL) and is Optional because the
/// wire field is.
nonisolated struct RoomSummary: Identifiable, Equatable {
    enum State { case ready, processing, failed }
    let id: String
    let bundleId: String?
    let title: String
    let statusLine: String
    let state: State
    /// When the room was sent, for the house's mono stamp column. Optional
    /// because `created_at` can fail to parse, and a fabricated date would be
    /// worse than an absent one.
    var sentAt: Date? = nil
}

// MARK: - Derivation

nonisolated enum RoomHistory {

    // MARK: Whole-list mapping

    /// Map the server's scenes to rows, preserving its newest-first order.
    ///
    /// A room whose `created_at` did not parse gets neither a date in its title
    /// nor a stamp, because the alternative is a fabricated one.
    ///
    /// TWO ROOMS FROM ONE DAY are told apart by the house's mono stamp column
    /// rather than by a time appended to the title. This function used to count
    /// same-day occurrences across the whole list to decide that, which is why
    /// it took the list rather than a scene — the disambiguation was a fact
    /// about the list. It is now a fact about the room, so the counting is
    /// gone, and `title(withTime:)` keeps its parameter for callers that want
    /// the older single-line form.
    static func summaries(from scenes: [SceneResponse], now: Date, calendar: Calendar = .current) -> [RoomSummary] {
        scenes.map { scene in
            RoomSummary(
                id: scene.sceneId,
                bundleId: scene.bundleId,
                title: title(sentAt: scene.createdAtDate, now: now,
                             withTime: false, calendar: calendar),
                statusLine: statusLine(status: scene.status, sentAt: scene.createdAtDate, now: now),
                state: state(for: scene.status),
                sentAt: scene.createdAtDate
            )
        }
    }

    // MARK: Reachability

    /// Whether the web handoff would actually land somewhere the person can
    /// see their room.
    ///
    /// TWO CONDITIONS, AND THE SECOND IS THE ONE THAT IS EASY TO MISS. A
    /// configured origin only says the page exists. Rooms are scoped to the
    /// caller's token; an anonymous UID does not carry off the phone, and
    /// Safari holds no session from this app — so an unlinked user following
    /// the link reaches a page correctly telling them to sign in with the
    /// account from their iPhone, which for them does not exist. That is a
    /// worse outcome than the disabled row it replaced, because it spends the
    /// person's attention before failing.
    ///
    /// So the link is offered only to a linked identity. For everyone else the
    /// surfaces point at signing in, which is both true and the actual next
    /// step.
    static func webHandoffLands(hasWebOrigin: Bool, isLinked: Bool) -> Bool {
        hasWebOrigin && isLinked
    }

    /// Whether tapping this row can honestly go anywhere.
    ///
    /// Mirrors DoorwayView's `canOpenWeb` exactly, and for the same reason: a
    /// row that depresses and does nothing is worse than a row that never
    /// offered. Callers pass `webHandoffLands`, never the bare origin check. A
    /// room still being rebuilt is not openable either — it has no desk to open
    /// on yet, and the home re-entry row is what re-enters the wait for the
    /// room actually in flight.
    static func isOpenable(_ room: RoomSummary, canOpenWeb: Bool) -> Bool {
        room.state == .ready && canOpenWeb && room.bundleId != nil
    }

    // MARK: State

    /// The three treatments the design gives a row. `failed_incomplete` reads as
    /// failed here and says something different in its status line — the row's
    /// treatment is about gravity, the line is about what happened.
    static func state(for status: SceneStatus) -> RoomSummary.State {
        switch status {
        case .ready:                            return .ready
        case .queued, .processing, .unknown:    return .processing
        case .failed, .failedInvalid, .failedIncomplete: return .failed
        }
    }

    // MARK: Title

    /// "today's room", "yesterday's room", "the July 12 room" — or, when the day
    /// is shared with another room in the same list, the same with the time.
    static func title(sentAt: Date?, now: Date, withTime: Bool, calendar: Calendar = .current) -> String {
        guard let sentAt else { return "a room you sent" }

        let base: String
        if calendar.isDate(sentAt, inSameDayAs: now) {
            base = "today's room"
        } else if let yesterday = calendar.date(byAdding: .day, value: -1, to: now),
                  calendar.isDate(sentAt, inSameDayAs: yesterday) {
            base = "yesterday's room"
        } else {
            base = "the \(monthDay(sentAt)) room"
        }
        return withTime ? "\(base), \(clockTime(sentAt))" : base
    }

    // MARK: Status line

    /// What the row says under the title. Nothing here is an estimate: a room
    /// still being rebuilt reports how long it HAS taken, never how long it has
    /// left — the pipeline does not tell the phone that, and the design's
    /// "about 2 min" would have to be invented.
    static func statusLine(status: SceneStatus, sentAt: Date?, now: Date) -> String {
        switch status {
        case .ready:
            return "on your desk"
        case .queued, .processing, .unknown:
            guard let sentAt, now >= sentAt else { return "being rebuilt" }
            return "being rebuilt · \(elapsedPhrase(from: sentAt, to: now)) so far"
        case .failedIncomplete:
            return "needs one more send"
        case .failed, .failedInvalid:
            return "didn't make it to the desk"
        }
    }

    // MARK: - Phrasing primitives

    /// Coarse elapsed phrase. Deliberately coarse: the row is glanced at, and a
    /// live-ticking second count on a list would be a clock the phone has no
    /// reason to keep.
    static func elapsedPhrase(from start: Date, to now: Date) -> String {
        let seconds = max(0, now.timeIntervalSince(start))
        if seconds < 60   { return "under a minute" }
        let minutes = Int(seconds / 60)
        if minutes < 60   { return "\(minutes) min" }
        let hours = Int(seconds / 3600)
        if hours < 24     { return hours == 1 ? "1 hr" : "\(hours) hr" }
        let days = Int(seconds / 86_400)
        return days == 1 ? "1 day" : "\(days) days"
    }

    /// "July 12". Fixed en_US_POSIX, matching the rest of the app's copy, which
    /// is written in English throughout — a half-localized row ("the 12 juillet
    /// room") would read worse than an unlocalized one.
    static func monthDay(_ date: Date) -> String {
        let formatter = DateFormatter()
        formatter.locale     = Locale(identifier: "en_US_POSIX")
        formatter.dateFormat = "MMMM d"
        return formatter.string(from: date)
    }

    /// "AUG 27" — the house's mono stamp column.
    ///
    /// Abbreviated where `monthDay` is not: the column is scanned down rather
    /// than read, and a spelled-out month wraps the row at accessibility sizes
    /// for a fact that is three letters wide. `monthDay` keeps its long form
    /// because it is set inside a sentence ("the August 12 room").
    static func shortStamp(_ date: Date) -> String {
        let formatter = DateFormatter()
        formatter.locale     = Locale(identifier: "en_US_POSIX")
        formatter.dateFormat = "MMM d"
        return formatter.string(from: date).uppercased()
    }

    /// "3:40 pm" — lowercase meridiem, matching the guest's voice rather than
    /// the system's shouted AM/PM.
    static func clockTime(_ date: Date) -> String {
        let formatter = DateFormatter()
        formatter.locale     = Locale(identifier: "en_US_POSIX")
        formatter.dateFormat = "h:mm a"
        return formatter.string(from: date).replacingOccurrences(of: "AM", with: "am")
                                           .replacingOccurrences(of: "PM", with: "pm")
    }
}
