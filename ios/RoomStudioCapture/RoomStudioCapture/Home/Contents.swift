/// The contents sheet's entries, as a pure function.
///
/// The 2b design puts the whole map behind the brand element in home's header:
/// a book's table of contents — serif entries, dot leaders, a mono truth on the
/// right — rather than a tab bar. Four entries, always the same four, always in
/// the same order, because a contents page whose rows move is not a contents
/// page.
///
/// THE STATUS COLUMN IS THE HONESTY CONSTRAINT WEARING A DIFFERENT HAT. Each
/// row states a small machine truth: how many rooms, whether the desk is busy,
/// whether anything needs you. Each of those can be unknown — the rooms fetch
/// fails, and the count goes with it — and the design's rule is that a count
/// the phone cannot vouch for is simply BLANK. Never zero, never "0 rooms",
/// never a dash that reads as none. `nil` here means "not stated", and the view
/// renders nothing at all in that column.
///
/// That is the same refusal `RoomsLoadState` makes, carried one screen further:
/// the store already declines to collapse "none" with "couldn't ask", and this
/// table would quietly undo that if it defaulted an unknown count to 0.
///
/// Read by: ContentsSheet. Pinned by: ContentsTests.

import Foundation

// MARK: - Entries

/// The four places the app keeps things. Order is the rendering order and is
/// part of the design: the house first because it is what the product is for,
/// then the desk, then notes, then you.
nonisolated enum ContentsEntry: String, CaseIterable, Equatable {
    case house
    case desk
    case notes
    case you

    /// The serif title, as the design sets it.
    var title: String {
        switch self {
        case .house: return "The house"
        case .desk:  return "The desk"
        case .notes: return "Notes"
        case .you:   return "You"
        }
    }
}

/// How a row is inked. Mirrors HomeLineTone's discipline: rust only for
/// something that needs a decision, gold only for light arriving.
nonisolated enum ContentsTone: Equatable {
    case needsYou
    case arrival
    case quiet
}

/// One rendered row. `status` nil means the row states nothing — see the
/// blank-not-zero rule above.
nonisolated struct ContentsRow: Equatable {
    let entry: ContentsEntry
    let status: String?
    let tone: ContentsTone
}

// MARK: - The table

nonisolated enum Contents {

    /// The four rows for a given day.
    ///
    /// Takes the same `HomeDay` home's sentence takes, deliberately: the sheet
    /// and the line are two renderings of one state, and giving them separate
    /// inputs is how they would come to disagree about whether anything needs
    /// you.
    static func rows(for day: HomeDay) -> [ContentsRow] {
        [
            ContentsRow(entry: .house,
                        status: houseStatus(day.roomCount),
                        tone: .quiet),
            ContentsRow(entry: .desk,
                        status: day.hasRoomInFlight ? "1 IN FLIGHT" : "CLEAR",
                        tone: day.hasRoomInFlight ? .arrival : .quiet),
            ContentsRow(entry: .notes,
                        status: notesStatus(day),
                        tone: notesTone(day)),
            // The profile states nothing. It is not a count and not a state —
            // it is a place — and inventing a status for symmetry would be the
            // one row on this sheet that asserts something it does not know.
            ContentsRow(entry: .you, status: nil, tone: .quiet),
        ]
    }

    // MARK: Status

    /// Blank when the count is unknown. See the header: this is the whole
    /// reason the parameter is Optional rather than defaulted.
    private static func houseStatus(_ roomCount: Int?) -> String? {
        guard let roomCount else { return nil }
        switch roomCount {
        case ..<1:  return "NO ROOMS YET"
        case 1:     return "1 ROOM"
        default:    return "\(roomCount) ROOMS"
        }
    }

    private static func notesStatus(_ day: HomeDay) -> String? {
        if day.needsYou > 0 {
            return day.needsYou == 1 ? "1 NEEDS YOU" : "\(day.needsYou) NEED YOU"
        }
        return day.hasUnseenArrival ? "NEWS" : "NOTHING NEW"
    }

    private static func notesTone(_ day: HomeDay) -> ContentsTone {
        if day.needsYou > 0 { return .needsYou }
        return day.hasUnseenArrival ? .arrival : .quiet
    }
}
