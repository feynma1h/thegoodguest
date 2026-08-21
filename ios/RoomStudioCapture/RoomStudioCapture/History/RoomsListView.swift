/// Thin history (design spec §9). The phone keeps a *thin* recent-rooms list —
/// status and a way back to the web, nothing editable. Room management (renaming,
/// comparing, deleting) is conversational and belongs to the guest on the web.
/// The phone is a camera with a memory of what it's sent, not a library.
///
/// Tapping a ready room hands off (§6); a processing room opens its waiting state
/// (§5). The invitation to scan stays anchored at the bottom — the app never
/// stops being a camera first. Titles are derived (RoomHistory); state reads as
/// treatment + words, never editable here.
///
/// The view takes a `RoomsLoadState`, not an array. That is the whole reason it
/// could not simply be handed `rooms` once the fetch existed: an array cannot
/// say "I couldn't ask", so a failed fetch would arrive here as an empty list
/// and this screen would tell the user their rooms are gone. Every one of the
/// four states below is drawn, and only one of them draws nothing.
///
/// Read by: RootFlowView.

import SwiftUI

struct RoomsListView: View {
    /// Required, and a state rather than an array — see above.
    var state: RoomsLoadState
    /// Whether a ready room has anywhere to go. Mirrors DoorwayView's parameter
    /// of the same name; false hides every chevron rather than offering a tap
    /// that lands nowhere.
    var canOpenWeb: Bool = false
    var onOpen: (RoomSummary) -> Void = { _ in }
    var onRetry: () -> Void = {}
    var onScanAnother: () -> Void = {}
    var onProfile: () -> Void = {}
    /// Non-nil when this screen is presented over home, which is the only way
    /// it is reachable today. nil renders it as a root screen (its own preview).
    var onClose: (() -> Void)?

    var body: some View {
        VStack(spacing: 0) {
            header

            content
                .padding(.top, 16)

            Spacer(minLength: 16)

            Button {
                RSHaptics.fire(.scanTapped)
                onScanAnother()
            } label: {
                Label(scanLabel, systemImage: "camera.viewfinder")
            }
            .buttonStyle(RSPrimaryButtonStyle())
            .padding(.bottom, 10)
        }
        .padding(.horizontal, 24)
        .frame(maxWidth: .infinity)
        .modifier(RSScrollableScreen(background: nil))
    }

    /// "Scan another room" is a claim about what came before it. With no rooms
    /// known — none sent, or none knowable — it is the first invitation again.
    private var scanLabel: String {
        if let rooms = state.knownRooms, !rooms.isEmpty { return "Scan another room" }
        return "Scan a room"
    }

    @ViewBuilder
    private var content: some View {
        switch state {
        case .idle, .loading:
            waiting

        case .loaded(let rooms, let stale) where !rooms.isEmpty:
            VStack(spacing: 10) {
                ForEach(rooms) { room in
                    RoomRowButton(room: room, canOpenWeb: canOpenWeb, onOpen: onOpen)
                }
            }

            if stale {
                staleNote
                    .padding(.top, 14)
            }

            Text(canOpenWeb
                 ? "Rename, compare & revisit happen with the guest, on the web →"
                 : "Rename, compare & revisit happen with the guest, on the web")
                .font(RSFont.ui(.footnote))
                .foregroundStyle(Color.rsInkFaint)
                .multilineTextAlignment(.center)
                .frame(maxWidth: .infinity)
                .padding(.top, 16)

        case .loaded:
            empty

        case .failed:
            unreachable
        }
    }

    // MARK: - The four states

    private var waiting: some View {
        VStack(spacing: 12) {
            ProgressView()
                .tint(Color.rsInkFaint)
            Text("Let me see what you've sent…")
                .rsFont(.guest, size: 15.5)
                .foregroundStyle(Color.rsInkMuted)
        }
        .frame(maxWidth: .infinity)
        .padding(.vertical, 36)
    }

    private var empty: some View {
        VStack(spacing: 10) {
            RoomSketch()
                .frame(width: 54, height: 54)
                .opacity(0.35)
            Text("Nothing here yet.")
                .rsFont(.display, size: 18)
                .foregroundStyle(Color.rsInk)
            Text("You haven't sent me a room yet. The first one takes about two minutes.")
                .font(RSFont.ui(.subheadline))
                .foregroundStyle(Color.rsInkMuted)
                .multilineTextAlignment(.center)
                .fixedSize(horizontal: false, vertical: true)
        }
        .frame(maxWidth: .infinity)
        .padding(.vertical, 30)
        .padding(.horizontal, 12)
    }

    /// The failure state says the phone could not ask. It deliberately does NOT
    /// say "no rooms", show an empty list, or offer the reassurance the empty
    /// state offers — the user's rooms are almost certainly fine, and this
    /// screen has no standing to claim either way.
    private var unreachable: some View {
        VStack(spacing: 10) {
            Image(systemName: "wifi.exclamationmark")
                .font(.system(size: 24, weight: .light))
                .foregroundStyle(Color.rsInkFaint)
            Text("I couldn't reach your rooms just now.")
                .rsFont(.guest, size: 16)
                .foregroundStyle(Color.rsInk)
                .multilineTextAlignment(.center)
                .fixedSize(horizontal: false, vertical: true)
            Text("They're safe where they are — this is my end, not yours.")
                .font(RSFont.ui(.subheadline))
                .foregroundStyle(Color.rsInkMuted)
                .multilineTextAlignment(.center)
                .fixedSize(horizontal: false, vertical: true)
            Button(action: onRetry) { Text("Try again") }
                .buttonStyle(RSQuietButtonStyle())
                .padding(.top, 2)
        }
        .frame(maxWidth: .infinity)
        .padding(.vertical, 30)
        .padding(.horizontal, 12)
    }

    private var staleNote: some View {
        HStack(spacing: 7) {
            Image(systemName: "arrow.clockwise")
                .font(.system(size: 11, weight: .semibold))
            Text("This might be a moment out of date.")
                .font(RSFont.ui(.footnote))
            Button(action: onRetry) { Text("Refresh") }
                .font(RSFont.ui(.footnote, weight: .semibold))
        }
        .foregroundStyle(Color.rsInkMuted)
        .frame(maxWidth: .infinity)
    }

    /// Capped and top-aligned, found by screenshot: at AX5 the uncapped title
    /// wrapped to two lines and the back chevron — vertically centred against
    /// the wrapped block — came to rest between them, reading as a stray glyph
    /// inside the heading rather than as the way out of the screen.
    private var header: some View {
        HStack(alignment: .top, spacing: 10) {
            if let onClose {
                Button(action: onClose) {
                    Image(systemName: "chevron.left")
                        .font(.system(size: 18, weight: .medium))
                        .foregroundStyle(Color.rsInkMuted)
                        .frame(width: 32, height: 32)
                }
                .accessibilityLabel("Back")
            }
            Text("Your rooms")
                .rsFont(.display, size: 22, weight: .medium, maxSize: 30)
                .foregroundStyle(Color.rsInk)
                .fixedSize(horizontal: false, vertical: true)
                .frame(minHeight: 32, alignment: .center)
            Spacer(minLength: 6)
            Button(action: onProfile) {
                Image(systemName: "person.crop.circle")
                    .font(.system(size: 18))
                    .foregroundStyle(Color.rsInk)
                    .frame(width: 32, height: 32)
                    .background(Color.rsInk.opacity(0.08), in: Circle())
            }
            .accessibilityLabel("You")
        }
        .padding(.top, 8)
    }
}

/// One room in the thin list: a sketch thumbnail (or a spinner while rebuilding),
/// the derived title, and the state as words. A chevron only when it's ready to
/// open on the web.
struct RoomRow: View {
    let room: RoomSummary
    var canOpenWeb: Bool = false

    var body: some View {
        HStack(spacing: 13) {
            thumbnail
            VStack(alignment: .leading, spacing: 2) {
                Text(room.title)
                    .rsFont(.guest, size: 15.5)
                    .foregroundStyle(Color.rsInk)
                    .fixedSize(horizontal: false, vertical: true)
                    .multilineTextAlignment(.leading)
                Text(room.statusLine)
                    .font(RSFont.ui(.footnote))
                    .foregroundStyle(statusColor)
                    .fixedSize(horizontal: false, vertical: true)
                    .multilineTextAlignment(.leading)
            }
            Spacer(minLength: 6)
            if RoomHistory.isOpenable(room, canOpenWeb: canOpenWeb) {
                Image(systemName: "chevron.right")
                    .font(.system(size: 13, weight: .semibold))
                    .foregroundStyle(Color.rsInk.opacity(0.4))
            }
        }
        .padding(12)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Color.rsSurface.opacity(0.85), in: RoundedRectangle(cornerRadius: 14, style: .continuous))
        .overlay(RoundedRectangle(cornerRadius: 14, style: .continuous).stroke(Color.rsHairline, lineWidth: 1))
    }

    @ViewBuilder
    private var thumbnail: some View {
        ZStack {
            RoundedRectangle(cornerRadius: 10, style: .continuous).fill(Color.rsCaptureRaised)
            switch room.state {
            case .ready:
                RoomSketch().padding(7)
            case .processing:
                Circle()
                    .trim(from: 0, to: 0.3)
                    .stroke(Color.rsGold, style: StrokeStyle(lineWidth: 2.5, lineCap: .round))
                    .frame(width: 22, height: 22)
                    .rotationEffect(.degrees(-90))
            case .failed:
                Image(systemName: "exclamationmark")
                    .font(.system(size: 16, weight: .medium))
                    .foregroundStyle(Color.rsGoldLight)
            }
        }
        .frame(width: 52, height: 52)
    }

    private var statusColor: Color {
        switch room.state {
        case .ready:      return Color.rsInkMuted
        case .processing: return Color.rsGoldInk
        case .failed:     return Color.rsAction
        }
    }
}

/// A row that becomes a button only when it has somewhere to go, so the two
/// surfaces that draw rows cannot disagree about which ones are tappable.
struct RoomRowButton: View {
    let room: RoomSummary
    var canOpenWeb: Bool = false
    var onOpen: (RoomSummary) -> Void = { _ in }

    var body: some View {
        if RoomHistory.isOpenable(room, canOpenWeb: canOpenWeb) {
            Button { onOpen(room) } label: { RoomRow(room: room, canOpenWeb: canOpenWeb) }
                .buttonStyle(.plain)
        } else {
            RoomRow(room: room, canOpenWeb: canOpenWeb)
        }
    }
}

// MARK: - Previews

extension RoomSummary {
    /// Preview fixtures. Never reachable from the flow: RoomsListView takes a
    /// RoomsLoadState with no default, so nothing can render these by omission.
    static let samples: [RoomSummary] = [
        .init(id: "1", bundleId: "b1", title: "the July 12 room", statusLine: "on your desk", state: .ready),
        .init(id: "2", bundleId: "b2", title: "today's room", statusLine: "being rebuilt · 2 min so far", state: .processing),
    ]
}

#Preview("Rooms") {
    RoomsListView(state: .loaded(rooms: RoomSummary.samples, stale: false), canOpenWeb: true)
}

#Preview("Rooms · no web origin") {
    RoomsListView(state: .loaded(rooms: RoomSummary.samples, stale: true))
}

#Preview("Loading") {
    RoomsListView(state: .loading)
}

#Preview("Empty") {
    RoomsListView(state: .loaded(rooms: [], stale: false))
}

#Preview("Unreachable") {
    RoomsListView(state: .failed(reason: "offline"))
}
