/// What home shows, as a pure function: your rooms as cards, in order, with
/// the only counts the phone can vouch for.
///
/// THE REDESIGN'S HOME (2026-11-10). Home used to hold a claim, one routing
/// sentence and a scan button, with the rooms, the desk and Notes each a screen
/// of their own behind a contents page. Home is now the rooms themselves: the
/// room in flight and anything that needs the person are cards pinned on top,
/// then every room the server has, newest first. Tapping a card opens that
/// room's own screen.
///
/// THE HONESTY RULES this inherits from the screens it replaces:
///   • A count is stated only when the server answered: an unknown is never
///     drawn as a zero, and a failed fetch never looks like "no rooms".
///   • First run is a KNOWN zero: the server said none, and nothing is on its
///     way or waiting.
///   • Loading, unreachable and empty stay three different screens.
///   • A room is never shown twice: the flight's own scene is folded into the
///     flight's card.
///
/// Read by: HomeScreen. Pinned by: RoomCardsTests.

import Foundation

/// The room this phone is sending or watching, as home needs it.
nonisolated struct HomeFlight: Equatable {
    let bundleId: String
    let placement: SurfacePlacement
    /// When it was sent, when known: names the card like any other room.
    var sentAt: Date? = nil
}

/// A failed send from an earlier launch, waiting to be acknowledged.
nonisolated struct HomeEarlierFailure: Equatable {
    let bundleId: String
    let reason: String?
}

nonisolated struct HomeCard: Identifiable, Equatable {
    enum Destination: Equatable {
        /// The room this phone is sending or watching.
        case flight
        /// A scan from an earlier launch that never finished sending.
        case earlierFailure
        /// A room the server has.
        case room(RoomSummary)
    }

    let id: String
    let title: String
    /// One line under the title: where the room is.
    let line: String
    /// The room needs the person. Shown with weight and a mark, not colour.
    var attention = false
    /// A room that has arrived and has not been opened yet.
    var isNew = false
    /// For a room still on its way: which of the three steps is happening
    /// (0 sending, 1 being rebuilt). Nil for every other card.
    var progressStep: Int? = nil
    /// The guest's line on a room still on its way.
    var guest: String? = nil
    /// The picture's source, when the server knows the room.
    var sceneId: String? = nil
    var stillURL: URL? = nil
    var stillNightURL: URL? = nil
    let destination: Destination
}

nonisolated struct HomeContent: Equatable {
    /// Nothing sent, nothing on its way: the welcome, not an empty list.
    var firstRun = false
    /// The server has not answered yet.
    var loading = false
    /// The server could not be asked.
    var unreachable = false
    /// "6 rooms, newest first" — only for a count the server gave.
    var countLine: String? = nil
    /// A refresh failed and the list is the last one known.
    var staleLine: String? = nil
    var cards: [HomeCard] = []
}

nonisolated enum RoomCards {

    static let staleText = "This might be a moment out of date. Pull down to refresh."

    static func content(rooms: RoomsLoadState,
                        flight: HomeFlight?,
                        earlierFailure: HomeEarlierFailure?,
                        now: Date,
                        calendar: Calendar = .current) -> HomeContent {
        let listed = rooms.knownRooms ?? []
        var local: [HomeCard] = []

        if let flight, let card = flightCard(flight, listed: listed, now: now, calendar: calendar) {
            local.append(card)
        }
        if let earlierFailure, earlierFailure.bundleId != flight?.bundleId {
            let status = RoomStatusCopy.needsYou(.uploadFailed(reason: earlierFailure.reason))
            local.append(HomeCard(id: "failure-" + earlierFailure.bundleId,
                                  title: "A room you scanned",
                                  line: status.cardLine,
                                  attention: true,
                                  destination: .earlierFailure))
        }

        var content = HomeContent()
        switch rooms {
        case .idle, .loading:
            content.loading = true
            content.cards = local
            return content
        case .failed:
            content.unreachable = true
            content.cards = local
            return content
        case .loaded(_, let stale):
            if listed.isEmpty && local.isEmpty {
                content.firstRun = true
                return content
            }
            content.staleLine = stale ? staleText : nil
            content.countLine = listed.count > 1 ? "\(listed.count) rooms, newest first" : nil
            let others = listed.filter { $0.bundleId == nil || $0.bundleId != flight?.bundleId }
            content.cards = local + roomCards(others, all: listed, now: now, calendar: calendar)
            return content
        }
    }

    // MARK: Cards

    private static func flightCard(_ flight: HomeFlight, listed: [RoomSummary],
                                   now: Date, calendar: Calendar) -> HomeCard? {
        let scene = listed.first { $0.bundleId == flight.bundleId }
        let title = RoomHistory.title(sentAt: flight.sentAt ?? scene?.sentAt ?? now, now: now,
                                      withTime: false, calendar: calendar)
        let id = "flight-" + flight.bundleId
        switch flight.placement {
        case .desk(let state):
            let status = RoomStatusCopy.onItsWay(state, now: now)
            return HomeCard(id: id, title: title, line: status.cardLine,
                            attention: status.needsAttention,
                            progressStep: progressStep(state),
                            guest: flightGuest(state),
                            destination: .flight)
        case .doorway:
            return HomeCard(id: id, title: title, line: "Ready", isNew: true,
                            sceneId: scene?.id, stillURL: scene?.stillURL, stillNightURL: scene?.stillNightURL,
                            destination: .flight)
        case .note(let kind):
            let status = RoomStatusCopy.needsYou(kind)
            return HomeCard(id: id, title: title, line: status.cardLine, attention: true,
                            sceneId: scene?.id, destination: .flight)
        case .nowhere:
            return nil
        }
    }

    /// Rooms the server has, newest first as it sent them. Two rooms from one
    /// day both carry their time, so neither title is ambiguous.
    private static func roomCards(_ rooms: [RoomSummary], all: [RoomSummary],
                                  now: Date, calendar: Calendar) -> [HomeCard] {
        rooms.map { room in
            let sharesDay = room.sentAt.map { day in
                all.filter { other in other.id != room.id && other.sentAt.map { calendar.isDate($0, inSameDayAs: day) } == true }.count > 0
            } ?? false
            let title = sharesDay
                ? RoomHistory.title(sentAt: room.sentAt, now: now, withTime: true, calendar: calendar)
                : room.title
            let status = RoomStatusCopy.listed(room.status, sentAt: room.sentAt, now: now)
            return HomeCard(id: room.id, title: title,
                            line: room.state == .ready ? "Ready" : status.cardLine,
                            attention: status.needsAttention,
                            sceneId: room.id, stillURL: room.stillURL, stillNightURL: room.stillNightURL,
                            destination: .room(room))
        }
    }

    private static func progressStep(_ state: DeskState) -> Int? {
        switch state {
        case .sending:                return 0
        case .working, .checkFailed:  return 1
        case .paused, .rateLimited, .retryableSendFailure: return nil
        }
    }

    /// The website's waiting lines, on the card of a room still moving.
    private static func flightGuest(_ state: DeskState) -> String? {
        switch state {
        case .sending:
            return "On its way up. You can put the phone down."
        case .working(_, let longRunning):
            return longRunning ? RoomStatusCopy.workingLong : RoomStatusCopy.working
        case .paused, .rateLimited, .retryableSendFailure, .checkFailed:
            return nil
        }
    }
}
