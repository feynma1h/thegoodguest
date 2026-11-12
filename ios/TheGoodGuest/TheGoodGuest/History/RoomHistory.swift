/// What the phone can honestly say about a room it has sent, derived from
/// GET /scenes and nothing else.
///
/// The phone is a camera with a memory of what it has sent, not a library, so
/// everything here is deliberately thin: a room has no name until the guest
/// gives it one on the web, and /scenes carries no name field, so a room is
/// titled by the day it was sent — "The 10 November room", the website's form,
/// so one room reads the same on both. Two rooms sent on one day are told apart
/// by `RoomCards`, which appends the time to both.
///
/// Every function here is pure and takes `now` explicitly, so the copy is
/// pinned as a table rather than read out of SwiftUI (the iOS test policy's
/// standing rule). Nothing here invents a number: an unparseable `created_at`
/// produces a room with no date in its name, never a guessed one.
///
/// Read by: RoomsStore (the mapping), RoomCards and the room screens.

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
    let status: SceneStatus
    /// When the room was sent. Optional because `created_at` can fail to
    /// parse, and a fabricated date would be worse than an absent one.
    var sentAt: Date? = nil
    /// The server's still of the finished room, by day and by lamplight, when
    /// it has rendered one. Signed and short-lived: never a cache key.
    var stillURL: URL? = nil
    var stillNightURL: URL? = nil

    var state: State { RoomHistory.state(for: status) }
}

// MARK: - Derivation

nonisolated enum RoomHistory {

    // MARK: Whole-list mapping

    /// Map the server's scenes to rooms, preserving its newest-first order.
    static func summaries(from scenes: [SceneResponse], now: Date, calendar: Calendar = .current) -> [RoomSummary] {
        scenes.map { scene in
            RoomSummary(
                id: scene.sceneId,
                bundleId: scene.bundleId,
                title: title(sentAt: scene.createdAtDate, now: now,
                             withTime: false, calendar: calendar),
                status: scene.status,
                sentAt: scene.createdAtDate,
                stillURL: scene.stillUrl.flatMap(URL.init(string:)),
                stillNightURL: scene.stillNightUrl.flatMap(URL.init(string:))
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
    /// account from their iPhone, which for them does not exist.
    ///
    /// So the link is offered only to a linked identity. For everyone else the
    /// surfaces point at signing in, which is both true and the actual next
    /// step.
    static func webHandoffLands(hasWebOrigin: Bool, isLinked: Bool) -> Bool {
        hasWebOrigin && isLinked
    }

    /// Whether this room can be opened on the web: ready, reachable, and with
    /// the bundle id the room URL is built from.
    static func isOpenable(_ room: RoomSummary, canOpenWeb: Bool) -> Bool {
        room.state == .ready && canOpenWeb && room.bundleId != nil
    }

    // MARK: State

    /// The three treatments a room gets. `failed_incomplete` is failed here and
    /// says something different on its own screen.
    static func state(for status: SceneStatus) -> RoomSummary.State {
        switch status {
        case .ready:                            return .ready
        case .queued, .processing, .unknown:    return .processing
        case .failed, .failedInvalid, .failedIncomplete: return .failed
        }
    }

    // MARK: Title

    /// "The 10 November room" — the year is added only when it is not this
    /// year's ("The 12 August 2025 room"), and the time only when asked for.
    static func title(sentAt: Date?, now: Date, withTime: Bool, calendar: Calendar = .current) -> String {
        guard let sentAt else { return "A room you sent" }
        var day = dayMonth(sentAt, calendar: calendar)
        if calendar.component(.year, from: sentAt) != calendar.component(.year, from: now) {
            day += " \(calendar.component(.year, from: sentAt))"
        }
        let base = "The \(day) room"
        return withTime ? "\(base), \(clockTime(sentAt))" : base
    }

    // MARK: - Phrasing primitives

    /// Coarse elapsed phrase. Deliberately coarse: a live-ticking second count
    /// would be a clock the phone has no reason to keep.
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

    /// "10 November". Fixed en_US_POSIX month names, matching the rest of the
    /// app's copy, which is written in English throughout.
    static func dayMonth(_ date: Date, calendar: Calendar = .current) -> String {
        let formatter = DateFormatter()
        formatter.locale     = Locale(identifier: "en_US_POSIX")
        formatter.timeZone   = calendar.timeZone
        formatter.dateFormat = "d MMMM"
        return formatter.string(from: date)
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
