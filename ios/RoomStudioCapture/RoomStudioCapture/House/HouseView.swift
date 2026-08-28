/// The house — the rooms that have landed, and the thesis' permanent address.
///
/// This is where the rooms went when home stopped carrying them. Home makes the
/// claim and points; the house holds the history. That split is what let the
/// claim stop disappearing after the first scan.
///
/// NO SCAN ACTION HERE, and that is a fix rather than an omission. The old
/// rooms list ended with "Scan another room" inside its own scroll region,
/// which at accessibility sizes fell below the fold — the screen ended
/// mid-sentence with its only action off-screen, on the one surface where
/// scanning and history shared space. Capture is home's gesture. The house is
/// somewhere you look.
///
/// THE THESIS SITS AT THE TOP as an epigraph. It is the claim's permanent
/// address: the one place it can be read at leisure rather than glanced past,
/// and the reason a user who wonders what this app was promising has somewhere
/// to go.
///
/// EVERY STATE STATES WHAT IT KNOWS. Four of them, and only one draws nothing:
/// rooms, rooms-that-may-be-stale, none, and could-not-ask. The last is the one
/// that matters — it declines to guess at a count rather than rendering an
/// empty list, because a failed fetch is not zero rooms and this screen has no
/// standing to say otherwise.
///
/// Read by: RootFlowView, pushed from home's sentence and from the contents.

import SwiftUI

struct HouseView: View {
    /// A state, not an array — an array cannot say "I couldn't ask", so a
    /// failed fetch would arrive here as an empty list and this screen would
    /// tell the user their rooms are gone.
    var state: RoomsLoadState
    /// Whether a ready room has anywhere to go. False with no web origin
    /// configured, which hides every chevron rather than offering a tap that
    /// lands nowhere.
    var canOpenWeb: Bool = false
    var onOpen: (RoomSummary) -> Void = { _ in }
    var onRetry: () -> Void = {}
    var onBack: () -> Void = {}
    /// Injected so the date stamps are stable in previews and screenshots.
    var now: Date = Date()

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            ScreenHeader(title: "The house", onClose: onBack)

            epigraph
                .rsBelowHeader()

            content
                .padding(.top, 26)

            Spacer(minLength: 24)
        }
        .rsScreenInsets()
        .frame(maxWidth: .infinity, alignment: .topLeading)
        .modifier(RSScrollableScreen(background: nil))
    }

    /// The claim, at rest. Quieter than home's copy of it — this is where it
    /// lives, not where it is being made.
    private var epigraph: some View {
        Text("Every home holds a version of itself you've never seen.")
            .rsFont(.guest, size: 17)
            .foregroundStyle(Color.rsInkMuted)
            .lineSpacing(3)
            .fixedSize(horizontal: false, vertical: true)
            .frame(maxWidth: .infinity, alignment: .leading)
    }

    @ViewBuilder
    private var content: some View {
        switch state {
        case .idle, .loading:
            waiting

        case .loaded(let rooms, let stale) where !rooms.isEmpty:
            VStack(alignment: .leading, spacing: 0) {
                if stale {
                    staleNote
                        .padding(.bottom, 16)
                }
                ForEach(rooms) { room in
                    HouseRow(room: room, stamp: stamp(for: room),
                             canOpenWeb: canOpenWeb, onOpen: onOpen)
                }
                footer
                    .padding(.top, 22)
            }

        case .loaded:
            empty

        case .failed:
            unreachable
        }
    }

    // MARK: The four states

    private var waiting: some View {
        Text("Let me see what you've sent…")
            .rsFont(.guest, size: 16)
            .foregroundStyle(Color.rsInkFaint)
            .fixedSize(horizontal: false, vertical: true)
    }

    private var empty: some View {
        Text("No rooms here yet — the first takes about two minutes.")
            .rsFont(.guest, size: 16)
            .foregroundStyle(Color.rsInkMuted)
            .fixedSize(horizontal: false, vertical: true)
    }

    /// Says the phone could not ask, and then says it will not guess. It does
    /// NOT say "no rooms", show an empty list, or offer the empty state's
    /// reassurance — the user's rooms are almost certainly fine and this screen
    /// has no standing to claim either way.
    private var unreachable: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("I couldn't check your rooms just now — so I won't guess at a count.")
                .rsFont(.guest, size: 16)
                .foregroundStyle(Color.rsInkMuted)
                .fixedSize(horizontal: false, vertical: true)
            Button(action: onRetry) {
                Text("Try again")
                    .font(RSFont.ui(.subheadline, weight: .semibold))
                    .foregroundStyle(Color.rsInk)
                    .padding(.horizontal, 16).padding(.vertical, 8)
                    .background(Capsule().stroke(Color.rsInk.opacity(0.3), lineWidth: 1.5))
            }
        }
    }

    private var staleNote: some View {
        Button(action: onRetry) {
            // Top-aligned: at accessibility sizes this wraps, and a centred
            // glyph beside wrapped prose comes to rest in the middle of it.
            HStack(alignment: .top, spacing: 8) {
                Image(systemName: "arrow.clockwise")
                    .font(.system(size: 11, weight: .semibold))
                    .frame(height: 17, alignment: .center)
                Text("This might be a moment out of date — refresh")
                    .font(RSFont.ui(.footnote))
                    .fixedSize(horizontal: false, vertical: true)
                    .multilineTextAlignment(.leading)
            }
            .foregroundStyle(Color.rsInkMuted)
        }
        .buttonStyle(.plain)
    }

    private var footer: some View {
        Text("Rooms are named and looked after at your desk, on the web.")
            .font(RSFont.ui(.footnote))
            .foregroundStyle(Color.rsInkFaint)
            .fixedSize(horizontal: false, vertical: true)
    }

    // MARK: The stamp

    /// The mono column: a clock time for a room sent today, a date otherwise.
    ///
    /// This is what tells two rooms from the same day apart, which is why the
    /// derived title no longer carries a time of its own — the fact belongs in
    /// the column where it lines up and can be scanned, not appended to a
    /// sentence.
    private func stamp(for room: RoomSummary) -> String? {
        guard let sentAt = room.sentAt else { return nil }
        if Calendar.current.isDate(sentAt, inSameDayAs: now) {
            return RoomHistory.clockTime(sentAt)
        }
        return RoomHistory.shortStamp(sentAt)
    }
}

// MARK: - One room

/// A room in the house: the derived title, what became of it, and when.
///
/// No thumbnail. The old row drew a generic sketch identical for every room,
/// which said nothing about any of them; the honest picture is the room's own
/// floor plan, and that does not survive past the next scan yet. An absent
/// image beats a decorative one that pretends to be a likeness.
private struct HouseRow: View {
    let room: RoomSummary
    var stamp: String?
    var canOpenWeb: Bool = false
    var onOpen: (RoomSummary) -> Void = { _ in }

    @Environment(\.dynamicTypeSize) private var typeSize

    private var isOpenable: Bool { RoomHistory.isOpenable(room, canOpenWeb: canOpenWeb) }

    var body: some View {
        Group {
            if isOpenable {
                Button { onOpen(room) } label: { row }.buttonStyle(.plain)
            } else {
                row
            }
        }
        .overlay(alignment: .bottom) {
            Rectangle().fill(Color.rsHairline).frame(height: 1)
        }
    }

    private var row: some View {
        // At accessibility sizes the title and the stamp each need the full
        // width, so the column becomes a line beneath rather than a stub
        // squeezed against the edge.
        VStack(alignment: .leading, spacing: 5) {
            if typeSize.isAccessibilitySize {
                titleAndStatus
                if let stamp { stampText(stamp) }
            } else {
                HStack(alignment: .top, spacing: 12) {
                    titleAndStatus
                    Spacer(minLength: 8)
                    if let stamp { stampText(stamp).padding(.top, 3) }
                    if isOpenable {
                        Image(systemName: "chevron.right")
                            .font(.system(size: 12, weight: .semibold))
                            .foregroundStyle(Color.rsInk.opacity(0.35))
                            .frame(height: 22, alignment: .center)
                    }
                }
            }
        }
        .padding(.vertical, 15)
        .frame(maxWidth: .infinity, alignment: .leading)
        .contentShape(Rectangle())
    }

    private var titleAndStatus: some View {
        VStack(alignment: .leading, spacing: 3) {
            Text(room.title)
                .rsFont(.guest, size: 17)
                .foregroundStyle(Color.rsInk)
                .fixedSize(horizontal: false, vertical: true)
                .multilineTextAlignment(.leading)
            Text(room.statusLine)
                .font(RSFont.ui(.footnote))
                .foregroundStyle(statusInk)
                .fixedSize(horizontal: false, vertical: true)
                .multilineTextAlignment(.leading)
        }
    }

    private func stampText(_ s: String) -> some View {
        Text(s)
            .rsFont(.mono, size: 10, weight: .medium, cap: .mono)
            .tracking(0.9)
            .foregroundStyle(Color.rsInkFaint)
            .fixedSize(horizontal: false, vertical: true)
    }

    /// Gold while a room is still being worked on, ordinary ink once it has
    /// landed, rust when it did not. The rule of gold holds: this is light
    /// arriving, not a success colour.
    private var statusInk: Color {
        switch room.state {
        case .ready:      return .rsInkMuted
        case .processing: return .rsGoldInk
        case .failed:     return .rsAction
        }
    }
}

// MARK: - Previews

extension RoomSummary {
    /// Preview fixtures. Never reachable from the flow: HouseView takes a
    /// RoomsLoadState with no default, so nothing can render these by omission.
    static func samples(now: Date = Date()) -> [RoomSummary] {
        let day: TimeInterval = 86_400
        return [
            .init(id: "1", bundleId: "b1", title: "today's room",
                  statusLine: "being rebuilt · 4 min so far", state: .processing,
                  sentAt: now.addingTimeInterval(-240)),
            .init(id: "2", bundleId: "b2", title: "today's room",
                  statusLine: "on your desk", state: .ready,
                  sentAt: now.addingTimeInterval(-5 * 3600)),
            .init(id: "3", bundleId: "b3", title: "yesterday's room",
                  statusLine: "on your desk", state: .ready,
                  sentAt: now.addingTimeInterval(-day)),
            .init(id: "4", bundleId: "b4", title: "the August 12 room",
                  statusLine: "needs one more send", state: .failed,
                  sentAt: now.addingTimeInterval(-15 * day)),
        ]
    }
}

#Preview("Six rooms") {
    HouseView(state: .loaded(rooms: RoomSummary.samples(), stale: false))
}

#Preview("Stale") {
    HouseView(state: .loaded(rooms: RoomSummary.samples(), stale: true))
}

#Preview("Empty") {
    HouseView(state: .loaded(rooms: [], stale: false))
}

#Preview("Unreachable") {
    HouseView(state: .failed(reason: "offline"))
}
