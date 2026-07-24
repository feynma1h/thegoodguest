/// Idle home — the app's resting state (design spec §1). First-time, no-rooms
/// variant: one serif claim (the thesis), one sans support line, one rust
/// primary. No feed, no tabs, no dashboard — the whole screen leans toward the
/// single action. The profile glyph is the only chrome.
///
/// The returning-home variant (a thin recent-rooms strip above the same button)
/// rides with the history surface (§9) since it needs a rooms fetch — this view
/// takes `hasRooms`/`roomsStrip` so that variant can slot in without a rewrite.

import SwiftUI

struct HomeView<RoomsStrip: View>: View {
    var onScan: () -> Void = {}
    var onProfile: () -> Void = {}
    /// When true, the hero collapses and `roomsStrip` is shown above the button.
    var hasRooms: Bool = false
    @ViewBuilder var roomsStrip: () -> RoomsStrip

    var body: some View {
        VStack(spacing: 0) {
            header
                .padding(.top, 8)

            // Scrollable: at accessibility sizes the hero claim + support line
            // exceed the space between the header and the CTA, and with fixed
            // Spacers the clipped text was unrecoverable.
            ScrollView {
                if hasRooms {
                    roomsStrip()
                        .padding(.top, 20)
                } else {
                    hero
                        .padding(.top, 28)
                }
            }

            scanAction
        }
        .padding(.horizontal, 26)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .rsParchmentScreen()
    }

    // MARK: - Pieces

    private var header: some View {
        HStack {
            Wordmark()
            Spacer()
            Button(action: onProfile) {
                Image(systemName: "person.crop.circle")
                    .font(.system(size: 20, weight: .regular))
                    .foregroundStyle(Color.rsInk)
                    .frame(width: 34, height: 34)
                    .background(Color.rsInk.opacity(0.08), in: Circle())
            }
            .accessibilityLabel("You")
        }
    }

    private var hero: some View {
        VStack(alignment: .leading, spacing: 14) {
            Text("Every home holds a version of itself you've never seen.")
                .rsFont(.guest, size: 25)
                .foregroundStyle(Color.rsInk)
                .lineSpacing(4)
                .fixedSize(horizontal: false, vertical: true)
            Text("Walk one room slowly with your phone. It comes alive on your desk — real, in 3D, exactly as you live in it.")
                .font(RSFont.ui(.callout))
                .foregroundStyle(Color.rsInkMuted)
                .lineSpacing(3)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    private var scanAction: some View {
        VStack(spacing: 12) {
            Button {
                RSHaptics.fire(.scanTapped)
                onScan()
            } label: {
                Label {
                    Text("Scan a room")
                } icon: {
                    Image(systemName: "camera.viewfinder")
                }
            }
            .buttonStyle(RSPrimaryButtonStyle())

            Text("Takes about two minutes")
                .font(RSFont.ui(.footnote))
                .foregroundStyle(Color.rsInkFaint)
        }
        .padding(.bottom, 8)
    }
}

// Convenience initializer for the first-time state (no rooms strip).
extension HomeView where RoomsStrip == EmptyView {
    init(onScan: @escaping () -> Void = {}, onProfile: @escaping () -> Void = {}) {
        self.init(onScan: onScan, onProfile: onProfile, hasRooms: false, roomsStrip: { EmptyView() })
    }
}

#Preview("First-time home") {
    HomeView()
}

#Preview("Cold start") {
    ColdStartView()
}
