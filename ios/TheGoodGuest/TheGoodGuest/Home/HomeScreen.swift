/// Home: your rooms, with Scan a room always at the bottom and your account
/// top right — the shape people expect of an iPhone app.
///
/// What it shows is decided by `RoomCards` (pure, tested); this file only
/// draws it. The first run is a welcome rather than an empty list: the example
/// room, the website's line, and the button.
///
/// THE ACTION IS PINNED, the content scrolls (decisions 0224, 0287): the bar
/// is opaque and full-bleed, so nothing reads through it at the largest sizes.
///
/// ON THE COLUMN, with every other screen (`RSLayout`). The title is the
/// content's first line rather than the navigation bar's large title: UIKit
/// sets a large title on its own margin, which is the column on some phones and
/// not on others, and never on an iPad. The bar keeps the name, for the way
/// back and for VoiceOver, without drawing it.
///
/// Read by: RootFlowView.

import SwiftUI

struct HomeScreen: View {
    let content: HomeContent
    var onScan: () -> Void = {}
    var onOpenAccount: () -> Void = {}
    var onOpenCard: (HomeCard) -> Void = { _ in }
    var onRetry: () -> Void = {}
    var onRefresh: () async -> Void = {}

    @Environment(\.splashIsPlaying) private var splashIsPlaying

    var body: some View {
        Group {
            if content.firstRun {
                firstRun
            } else {
                rooms
            }
        }
        .safeAreaInset(edge: .bottom, spacing: 0) { scanBar }
        .background(GroundBackground())
        .navigationTitle(content.firstRun ? "" : "Your rooms")
        .navigationBarTitleDisplayMode(.inline)
        .toolbar(removing: .title)
        .toolbar {
            ToolbarItem(placement: .topBarLeading) {
                Mark(height: 15)
                    // The splash's mark lands here (0255): this one waits
                    // unseen until it has, and says where it is.
                    .opacity(splashIsPlaying ? 0 : 1)
                    .onGeometryChange(for: CGRect.self) { $0.frame(in: .global) } action: {
                        MarkSlotReport.shared.frame = $0
                    }
                    .accessibilityLabel(RSBrand.name)
                    .accessibilityAddTraits(.isHeader)
            }
            .sharedBackgroundVisibility(.hidden)
            ToolbarItem(placement: .topBarTrailing) {
                Button(action: onOpenAccount) {
                    Image(systemName: "person.crop.circle")
                }
                .accessibilityLabel("Account")
            }
        }
    }

    // MARK: First run

    private var firstRun: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 0) {
                ZStack(alignment: .bottomLeading) {
                    // minWidth 0: a filled picture asks for its own width at
                    // this height (358pt for this one), and a frame without a
                    // minimum never shrinks below what its child asks for. On
                    // a 375pt phone that made the whole screen 15pt wider than
                    // the window, shifted half of it off the left and clipped
                    // the right.
                    Image("ExampleRoom")
                        .resizable()
                        .aspectRatio(contentMode: .fill)
                        .frame(minWidth: 0, maxWidth: .infinity)
                        .rsHeroFrame()
                        .clipped()
                        .accessibilityLabel("An example room in 3D, cut away so you can see in")
                    Text("An example room")
                        .rsFont(.ui, size: 13)
                        .foregroundStyle(Color.rsInk2)
                        // A label on the picture, not reading text: past
                        // XXXL it grew into the drawing (an SE and an iPad at
                        // AX5). Held there as a control's label is (0258).
                        .rsControlLabel()
                        .padding(14)
                }
                .background(Color.rsInset)
                .clipShape(RoundedRectangle(cornerRadius: 26, style: .continuous))

                RSScreenTitle("Meet your room again.", size: .display())
                    .padding(.top, 26)
                Text("Walk one room slowly with your iPhone. It stands back up in 3D, at its true size, with a guest who can talk it through.")
                    .rsFont(.ui, size: 16)
                    .foregroundStyle(Color.rsInk2)
                    .lineSpacing(3)
                    .fixedSize(horizontal: false, vertical: true)
                    .padding(.top, 14)
            }
            .rsScreenContent()
        }
    }

    // MARK: Rooms

    private var rooms: some View {
        ScrollView {
            LazyVStack(alignment: .leading, spacing: 12) {
                VStack(alignment: .leading, spacing: 4) {
                    RSScreenTitle("Your rooms")
                    if let countLine = content.countLine {
                        lineText(countLine)
                    }
                }
                .padding(.bottom, 6)
                if let staleLine = content.staleLine {
                    Label {
                        lineText(staleLine)
                    } icon: {
                        Image(systemName: "arrow.clockwise")
                            .font(.system(size: 13, weight: .semibold))
                            .foregroundStyle(Color.rsInk2)
                    }
                }
                ForEach(content.cards) { card in
                    Button { onOpenCard(card) } label: { HomeCardView(card: card) }
                        .buttonStyle(.plain)
                }
                if content.loading {
                    if content.cards.isEmpty {
                        HStack(spacing: 10) {
                            ProgressView()
                            lineText("Looking for your rooms…")
                        }
                        .padding(.vertical, 4)
                        ForEach(0..<3, id: \.self) { i in
                            SkeletonCard().opacity(1 - Double(i) * 0.28)
                        }
                    } else {
                        HStack(spacing: 10) {
                            ProgressView()
                            lineText("Looking for your other rooms…")
                        }
                    }
                }
                if content.unreachable {
                    UnreachableCard(onRetry: onRetry)
                }
            }
            .rsScreenContent()
        }
        .refreshable { await onRefresh() }
    }

    private func lineText(_ text: String) -> some View {
        Text(text)
            .rsFont(.ui, size: 14)
            .foregroundStyle(Color.rsInk2)
            .fixedSize(horizontal: false, vertical: true)
    }

    // MARK: The pinned action

    private var scanBar: some View {
        RSPinnedBar {
            Button {
                RSHaptics.fire(.scanTapped)
                onScan()
            } label: {
                Text(content.firstRun ? "Scan your first room" : "Scan a room")
            }
            .buttonStyle(RSPrimaryButtonStyle())
            if content.firstRun {
                RSBarCaption("Takes about two minutes")
            }
        }
    }
}

// MARK: - A card

struct HomeCardView: View {
    let card: HomeCard
    @ObservedObject private var pictures = RoomPictureStore.shared

    var body: some View {
        Group {
            if let step = card.progressStep {
                flight(step: step)
            } else {
                row
            }
        }
        .background(Color.rsSurface, in: RoundedRectangle(cornerRadius: 22, style: .continuous))
        .shadow(color: Color.rsInk.opacity(0.05), radius: 14, y: 8)
        .contentShape(RoundedRectangle(cornerRadius: 22, style: .continuous))
        .accessibilityElement(children: .combine)
        .accessibilityHint("Opens this room")
    }

    /// A room still on its way: where it is, the three steps, and the guest.
    private func flight(step: Int) -> some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack(alignment: .firstTextBaseline) {
                title
                Spacer(minLength: 8)
                chevron
            }
            Text(card.line)
                .rsFont(.ui, size: 14)
                .foregroundStyle(Color.rsInk2)
                .padding(.top, 4)
            HStack(spacing: 4) {
                ForEach(0..<3, id: \.self) { i in
                    Capsule()
                        .fill(i < step ? Color.rsInk : (i == step ? Color.rsInk.opacity(0.4) : Color.rsInset))
                        .frame(height: 4)
                }
            }
            .padding(.top, 14)
            .accessibilityHidden(true)
            HStack {
                Text("Sent"); Spacer(); Text("Rebuilding"); Spacer(); Text("Ready")
            }
            .rsFont(.ui, size: 12, cap: .display)
            .foregroundStyle(Color.rsInk2)
            .padding(.top, 7)
            .accessibilityHidden(true)
            if let guest = card.guest {
                GuestLine(guest, size: 17)
                    .fixedSize(horizontal: false, vertical: true)
                    .padding(.top, 14)
            }
        }
        .padding(EdgeInsets(top: 16, leading: 16, bottom: 18, trailing: 16))
    }

    /// Any other room: its picture, its name, its size, where it is.
    private var row: some View {
        HStack(alignment: .center, spacing: 14) {
            RoomPicture(sceneId: card.sceneId, stillURL: card.stillURL, stillNightURL: card.stillNightURL)
                .frame(width: 64, height: 64)
                .clipShape(RoundedRectangle(cornerRadius: 14, style: .continuous))
            VStack(alignment: .leading, spacing: 3) {
                title
                if let sceneId = card.sceneId, let outline = pictures.outlines[sceneId] {
                    MeasureText(outline.sizeText)
                }
                status
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            chevron
        }
        .padding(12)
    }

    private var title: some View {
        Text(card.title.rsKeepingLastWordsTogether)
            .rsFont(.ui, size: 17, weight: .semibold)
            .foregroundStyle(Color.rsInk)
            .fixedSize(horizontal: false, vertical: true)
            .multilineTextAlignment(.leading)
    }

    @ViewBuilder
    private var status: some View {
        if card.attention {
            Label {
                Text(card.line)
                    .rsFont(.ui, size: 14, weight: .semibold)
                    .foregroundStyle(Color.rsInk)
                    .fixedSize(horizontal: false, vertical: true)
            } icon: {
                Image(systemName: "exclamationmark.circle")
                    .font(.system(size: 14, weight: .semibold))
                    .foregroundStyle(Color.rsInk)
            }
            .labelStyle(.titleAndIcon)
        } else if card.isNew {
            HStack(spacing: 8) {
                Text("New")
                    .rsFont(.ui, size: 12, weight: .semibold, cap: .display)
                    .foregroundStyle(Color.white)
                    .padding(.horizontal, 9)
                    .frame(minHeight: 22)
                    .background(Color.rsInk, in: Capsule())
                Text(card.line)
                    .rsFont(.ui, size: 14)
                    .foregroundStyle(Color.rsInk2)
            }
        } else {
            Text(card.line)
                .rsFont(.ui, size: 14)
                .foregroundStyle(Color.rsInk2)
                .fixedSize(horizontal: false, vertical: true)
        }
    }

    private var chevron: some View {
        Image(systemName: "chevron.right")
            .font(.system(size: 14, weight: .semibold))
            .foregroundStyle(Color.rsInk3)
            .accessibilityHidden(true)
    }
}

/// A grey card shape while the list is loading. No shimmer: nothing pretends
/// to be content.
private struct SkeletonCard: View {
    var body: some View {
        HStack(spacing: 14) {
            RoundedRectangle(cornerRadius: 14, style: .continuous).fill(Color.rsInset).frame(width: 64, height: 64)
            VStack(alignment: .leading, spacing: 10) {
                Capsule().fill(Color.rsInset).frame(width: 170, height: 13)
                Capsule().fill(Color.rsInset).frame(width: 90, height: 11)
            }
            Spacer()
        }
        .padding(12)
        .background(Color.rsSurface, in: RoundedRectangle(cornerRadius: 22, style: .continuous))
        .accessibilityHidden(true)
    }
}

/// The rooms could not be asked for. Says so, and refuses to guess a count.
private struct UnreachableCard: View {
    var onRetry: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            Image(systemName: "wifi.exclamationmark")
                .font(.system(size: 22, weight: .regular))
                .foregroundStyle(Color.rsInk)
                .accessibilityHidden(true)
            Text("I couldn’t check your rooms just now.")
                .rsFont(.ui, size: 17, weight: .semibold)
                .foregroundStyle(Color.rsInk)
                .fixedSize(horizontal: false, vertical: true)
                .padding(.top, 12)
            Text("So I won’t guess at a count. Your rooms are safe; this is only the phone not getting through.")
                .rsFont(.ui, size: 16)
                .foregroundStyle(Color.rsInk2)
                .lineSpacing(2)
                .fixedSize(horizontal: false, vertical: true)
                .padding(.top, 6)
            Button(action: onRetry) {
                Label("Try again", systemImage: "arrow.clockwise")
                    .rsFont(.ui, size: 16, weight: .semibold)
                    .foregroundStyle(Color.rsInk)
                    .frame(minHeight: 44)
            }
            .padding(.top, 6)
        }
        .padding(EdgeInsets(top: 20, leading: 18, bottom: 10, trailing: 18))
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Color.rsSurface, in: RoundedRectangle(cornerRadius: 22, style: .continuous))
    }
}
