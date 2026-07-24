/// Thin history (design spec §9). The phone keeps a *thin* recent-rooms list —
/// status and a way back to the web, nothing editable. Room management (renaming,
/// comparing, deleting) is conversational and belongs to the guest on the web.
/// The phone is a camera with a memory of what it's sent, not a library.
///
/// Tapping a ready room hands off (§6); a processing room opens its waiting state
/// (§5). The invitation to scan stays anchored at the bottom — the app never
/// stops being a camera first. The spine integration binds `rooms` to GET /scenes
/// (newest-first); titles are derived ("the July 12 room"), state reads as
/// treatment + words, never editable here.

import SwiftUI

struct RoomSummary: Identifiable {
    enum State { case ready, processing, failed }
    let id: String
    let title: String
    let statusLine: String
    let state: State
}

struct RoomsListView: View {
    // Required — no sample default, so wiring this up can never silently ship
    // fixture rooms as if they were the user's.
    var rooms: [RoomSummary]
    var onOpen: (RoomSummary) -> Void = { _ in }
    var onScanAnother: () -> Void = {}
    var onProfile: () -> Void = {}

    var body: some View {
        VStack(spacing: 0) {
            header

            VStack(spacing: 10) {
                ForEach(rooms) { room in
                    Button { onOpen(room) } label: { RoomRow(room: room) }
                        .buttonStyle(.plain)
                }
            }
            .padding(.top, 16)

            Text("Rename, compare & revisit happen with the guest, on the web →")
                .font(RSFont.ui(.footnote))
                .foregroundStyle(Color.rsInkFaint)
                .multilineTextAlignment(.center)
                .frame(maxWidth: .infinity)
                .padding(.top, 16)

            Spacer()

            Button {
                RSHaptics.fire(.scanTapped)
                onScanAnother()
            } label: {
                Label("Scan another room", systemImage: "camera.viewfinder")
            }
            .buttonStyle(RSPrimaryButtonStyle())
            .padding(.bottom, 10)
        }
        .padding(.horizontal, 24)
        .frame(maxWidth: .infinity)
        .modifier(RSScrollableScreen(background: nil))
    }

    private var header: some View {
        HStack {
            Text("Your rooms")
                .rsFont(.display, size: 22, weight: .medium)
                .foregroundStyle(Color.rsInk)
            Spacer()
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

    var body: some View {
        HStack(spacing: 13) {
            thumbnail
            VStack(alignment: .leading, spacing: 2) {
                Text(room.title)
                    .rsFont(.guest, size: 15.5)
                    .foregroundStyle(Color.rsInk)
                Text(room.statusLine)
                    .font(RSFont.ui(.footnote))
                    .foregroundStyle(statusColor)
            }
            Spacer()
            if room.state == .ready {
                Image(systemName: "chevron.right")
                    .font(.system(size: 13, weight: .semibold))
                    .foregroundStyle(Color.rsInk.opacity(0.4))
            }
        }
        .padding(12)
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

extension RoomSummary {
    static let samples: [RoomSummary] = [
        .init(id: "1", title: "the everything room", statusLine: "on your desk · visited yesterday", state: .ready),
        .init(id: "2", title: "the study", statusLine: "being rebuilt · about 2 min", state: .processing),
    ]
}

#Preview {
    RoomsListView(rooms: RoomSummary.samples)
}
