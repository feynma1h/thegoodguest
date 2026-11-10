/// The app's one grid, in the website's terms: a screen has ONE left edge.
///
/// Its title, its lines, its cards and pictures, and the pinned button under
/// them all start on the same column. That is how the website lays out a page —
/// on a phone the "Your house" title, the line under it and the room cards all
/// start 16px in (`px-4`), and a panel's title, body and buttons share its one
/// padding — and it is how iOS sets its own screens, with a large title on the
/// layout margin beside the content.
///
/// WHY A COMPONENT AND NOT A NUMBER. The redesign's screens each set their own
/// insets, and the canvas they were drawn from put text 4pt inside the cards'
/// edge. Measured, the titles came to rest on three columns — 16 on home and a
/// room, 20 on review, account and deletion, 22 on guidance — and the pinned
/// button 38 or 42 off the bottom as each bar chose its own padding
/// (`tools/ios_layout_audit.py`, 2026-11-10). No one of those numbers was wrong
/// on its own screen; the drift only existed between them, which is the 0257
/// lesson, and the answer then was a component too.
///
/// So the column is set in one place: `rsScreenContent()` puts a screen's
/// scrolling content on it, `RSScreenTitle` sets a title at the top of it, and
/// `RSPinnedBar` pins the actions to it. On a wide window — an iPad, a phone on
/// its side — the column stops at a readable width and centres, as the
/// website's containers do.
///
/// Read by: every daylight and dusk screen. The capture HUD is full bleed and
/// is not on the column.

import SwiftUI

enum RSLayout {
    /// The column's edge, from the window's edge (inside its safe area): the
    /// website's phone gutter, and UIKit's own layout margin on every phone but
    /// the largest.
    static let margin: CGFloat = 16
    /// How wide the column may grow before it centres. Near UIKit's readable
    /// width; on a phone the column is always narrower than this.
    static let readableWidth: CGFloat = 640
    /// From the bottom of the navigation bar to a screen's title.
    static let titleTop: CGFloat = 4
    /// Under a screen's last line, so it can scroll clear of the pinned bar.
    static let contentBottom: CGFloat = 24
    /// The pinned bar: above its first control, and below its last, on top of
    /// the safe area (the home indicator's 34pt on a phone without a button).
    static let barTop: CGFloat = 12
    static let barBottom: CGFloat = 4
    /// Between the bar's controls. Tight because a quiet action is already a
    /// 50pt target.
    static let barSpacing: CGFloat = 2
    /// Above a caption in the bar, added to the spacing.
    static let captionTop: CGFloat = 8
    /// The fade above the pinned bar, where content scrolls into it.
    static let barFade: CGFloat = 22
    /// A screen's hero picture — the example room, a ready room — where there
    /// is room for it: the canvas's 340pt.
    static let heroHeight: CGFloat = 340
    /// And never more than this share of what the screen shows between its
    /// bars, so the words under the picture stay in view. 0.58 keeps the full
    /// 340 on every phone 390pt wide or more; on an iPhone SE it is about 280,
    /// and on a phone on its side about 140, where 340 was the whole screen.
    static let heroShare: CGFloat = 0.58
}

extension View {
    /// Put this content on the column: full width up to the readable width,
    /// leading-aligned, centred in a wider window.
    func rsColumn() -> some View {
        frame(maxWidth: .infinity, alignment: .leading)
            .frame(maxWidth: RSLayout.readableWidth)
            .padding(.horizontal, RSLayout.margin)
            .frame(maxWidth: .infinity)
    }

    /// A screen's scrolling content: on the column, its title just under the
    /// navigation bar, and room at the end to scroll clear of the pinned bar.
    func rsScreenContent() -> some View {
        padding(.top, RSLayout.titleTop)
            .padding(.bottom, RSLayout.contentBottom)
            .rsColumn()
    }

    /// A hero picture's height: `height` (the canvas's, 340 unless the screen
    /// says otherwise), or `heroShare` of the scroll view's visible height
    /// where that is less. Measured, on an iPhone SE the fixed 340 left the
    /// ready screen's size line and the guest's sentence half under the pinned
    /// bar, and the welcome's sentence under it too.
    func rsHeroFrame(_ height: CGFloat = RSLayout.heroHeight) -> some View {
        containerRelativeFrame(.vertical) { length, _ in
            min(height, length * RSLayout.heroShare)
        }
    }
}

/// A screen's title: the first thing under the navigation bar, on the column.
///
/// Home's title is one of these too, rather than the navigation bar's large
/// title. UIKit sets a large title on its own layout margin, which is 16pt on
/// most phones, 20 on the largest and the window's edge on an iPad — the
/// column on some of them and never on all.
///
/// The sizes are the canvas's three: `large` (34, its `.lt`), `title` (30,
/// `.t2`) and `display` (40, `.dt`, which the ready screen sets at 38). Each is
/// tracked in by its own share of the size, as the canvas tracks them.
struct RSScreenTitle: View {
    enum Size {
        case large
        case title
        case display(CGFloat = 40)

        var points: CGFloat {
            switch self {
            case .large: 34
            case .title: 30
            case .display(let size): size
            }
        }

        var tracking: CGFloat {
            switch self {
            case .large: -0.022
            case .title: -0.02
            case .display: -0.03
            }
        }
    }

    let text: String
    var size: Size = .large
    var onDusk = false

    init(_ text: String, size: Size = .large, onDusk: Bool = false) {
        self.text = text
        self.size = size
        self.onDusk = onDusk
    }

    var body: some View {
        Text(text)
            .rsFont(.display, size: size.points, cap: .display)
            .tracking(size.tracking * size.points)
            .foregroundStyle(onDusk ? Color.rsOnDusk : Color.rsInk)
            .fixedSize(horizontal: false, vertical: true)
            .accessibilityAddTraits(.isHeader)
    }
}

/// A screen's actions, pinned under its content with `safeAreaInset`.
///
/// ONE BAR FOR EVERY SCREEN, so the filled button sits at one height wherever
/// the same things sit under it: alone, 38pt off the bottom of a phone without
/// a button; over a quiet action, 90; over a caption, a little lower than that.
/// The canvas drew one action block for every screen too (`.actions`).
///
/// OPAQUE AND FULL BLEED, because content scrolls behind it (0287): its ground
/// runs edge to edge and down under the home indicator, while its controls
/// stay on the column.
///
/// AND IT FADES IN, over the 22pt above it, as the canvas's action block does
/// (`.actions`: transparent to ground over 22px). Without it a line that
/// scrolls under the bar is cut through the middle at the bar's edge, which on
/// a small phone is the first thing the screen shows — review's guest line on
/// an iPhone SE. The controls themselves never sit on the fade.
struct RSPinnedBar<Content: View>: View {
    var surface: Color = .rsGround
    @ViewBuilder var content: Content

    init(surface: Color = .rsGround, @ViewBuilder content: () -> Content) {
        self.surface = surface
        self.content = content()
    }

    var body: some View {
        VStack(spacing: RSLayout.barSpacing) {
            content
        }
        .rsColumn()
        .padding(.top, RSLayout.barTop)
        .padding(.bottom, RSLayout.barBottom)
        .background(surface.ignoresSafeArea(edges: .bottom))
        .background(alignment: .top) {
            LinearGradient(colors: [surface.opacity(0), surface],
                           startPoint: .top, endPoint: .bottom)
                .frame(height: RSLayout.barFade)
                .offset(y: -RSLayout.barFade)
                .allowsHitTesting(false)
                .accessibilityHidden(true)
        }
    }
}

/// The small line a pinned bar may close with instead of a quiet action:
/// home's "Takes about two minutes", deletion's "Please stay on this screen",
/// ready's word about Safari. At its own height — a caption is not a control,
/// and holding it at a control's height moved the button above it.
struct RSBarCaption: View {
    let text: String
    var onDusk = false

    init(_ text: String, onDusk: Bool = false) {
        self.text = text
        self.onDusk = onDusk
    }

    var body: some View {
        Text(text)
            .rsFont(.ui, size: 13)
            .foregroundStyle(onDusk ? Color.rsOnDusk2 : Color.rsInk2)
            .multilineTextAlignment(.center)
            .fixedSize(horizontal: false, vertical: true)
            .padding(.horizontal, 8)
            .frame(maxWidth: .infinity)
            .padding(.top, RSLayout.captionTop)
    }
}
