/// The returning-home variant of §1 — a thin strip of recently sent rooms above
/// the same scan button. The first-time home is a hero claim and one action;
/// once there is history, the history takes that space and the action stays put.
///
/// Deliberately not the whole list: home orients you and gets out of the way,
/// and "see all" is one tap from here. The rows are the same RoomRow the list
/// draws, so a room reads identically wherever it appears.
///
/// WHAT HOME MUST NEVER DO is show the first-time hero as a *consequence* of a
/// failed fetch. The hero is the app's resting claim and is true for everyone,
/// but in this flow it is also the no-rooms variant — so falling back to it
/// silently when the fetch failed tells a returning user their rooms are gone.
/// `HomeRooms.presentation` is that decision as a table, and its fourth case
/// exists for exactly this: hero *plus* an honest line saying the phone could
/// not ask.
///
/// Read by: RootFlowView.

import SwiftUI

// MARK: - The presentation decision

nonisolated enum HomeRooms {

    /// How many rooms home shows before deferring to the full list.
    static let stripLimit = 3

    enum Presentation: Equatable {
        /// The first-time claim, alone. Nothing known yet, or genuinely no rooms.
        case hero
        /// The strip of recent rooms.
        case strip
        /// The claim, plus a line admitting the rooms could not be reached.
        case heroWithTrouble
    }

    static func presentation(for state: RoomsLoadState) -> Presentation {
        switch state {
        case .idle, .loading:
            // The hero is never false, so it is the honest thing to hold the
            // space with while the answer is on its way.
            return .hero
        case .loaded(let rooms, _):
            return rooms.isEmpty ? .hero : .strip
        case .failed:
            return .heroWithTrouble
        }
    }

    /// The rooms home shows, newest first.
    static func stripRooms(_ rooms: [RoomSummary]) -> [RoomSummary] {
        Array(rooms.prefix(stripLimit))
    }
}

// MARK: - The strip

struct RecentRoomsStrip: View {
    var rooms: [RoomSummary]
    var stale: Bool = false
    /// See RoomsListView.canOpenWeb — one flag, one meaning, on both surfaces.
    var canOpenWeb: Bool = false
    var onOpen: (RoomSummary) -> Void = { _ in }
    var onSeeAll: () -> Void = {}
    var onRetry: () -> Void = {}

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            Eyebrow("What you've sent")

            ForEach(HomeRooms.stripRooms(rooms)) { room in
                RoomRowButton(room: room, canOpenWeb: canOpenWeb, onOpen: onOpen)
            }

            if stale {
                Button(action: onRetry) {
                    HStack(spacing: 6) {
                        Image(systemName: "arrow.clockwise")
                            .font(.system(size: 11, weight: .semibold))
                        Text("This might be a moment out of date — refresh")
                            .font(RSFont.ui(.footnote))
                            .multilineTextAlignment(.leading)
                    }
                    .foregroundStyle(Color.rsInkMuted)
                }
                .buttonStyle(.plain)
            }

            Button(action: onSeeAll) {
                HStack(spacing: 5) {
                    Text(seeAllLabel)
                        .font(RSFont.ui(.subheadline, weight: .medium))
                    Image(systemName: "chevron.right")
                        .font(.system(size: 11, weight: .semibold))
                }
                .foregroundStyle(Color.rsInk)
            }
            .buttonStyle(.plain)
            .padding(.top, 2)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    private var seeAllLabel: String {
        rooms.count == 1 ? "Your rooms" : "All \(rooms.count) rooms"
    }
}

// MARK: - The trouble line

/// Home's failed-fetch line. Sits under the hero rather than replacing it: the
/// claim is still true, and what is being reported is that the phone could not
/// look, not that there is nothing to see.
struct RoomsTroubleLine: View {
    var onRetry: () -> Void = {}

    var body: some View {
        HStack(spacing: 9) {
            Image(systemName: "wifi.exclamationmark")
                .font(.system(size: 13, weight: .medium))
                .foregroundStyle(Color.rsInkFaint)
            Text("I couldn't check your rooms just now.")
                .font(RSFont.ui(.footnote))
                .foregroundStyle(Color.rsInkMuted)
                .fixedSize(horizontal: false, vertical: true)
                .multilineTextAlignment(.leading)
            Spacer(minLength: 6)
            Button(action: onRetry) { Text("Try again") }
                .font(RSFont.ui(.footnote, weight: .semibold))
                .foregroundStyle(Color.rsInk)
        }
        .padding(.horizontal, 14)
        .padding(.vertical, 11)
        .background(Color.rsSurface.opacity(0.9), in: RoundedRectangle(cornerRadius: 12, style: .continuous))
        .overlay(RoundedRectangle(cornerRadius: 12, style: .continuous).stroke(Color.rsHairline, lineWidth: 1))
    }
}

#Preview("Strip") {
    VStack {
        RecentRoomsStrip(rooms: RoomSummary.samples)
        RoomsTroubleLine()
    }
    .padding(26)
    .frame(maxWidth: .infinity, maxHeight: .infinity)
    .rsParchmentScreen()
}
