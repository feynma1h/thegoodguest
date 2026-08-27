/// The measurements every screen in the app shares, and the header band that
/// enforces them.
///
/// WHY THIS EXISTS. Each screen had grown its own header and its own insets,
/// and they had drifted: measured by screenshot across six surfaces, the header
/// ink started anywhere between 73pt and 89pt down the screen and the first line
/// of content between 112pt and 156pt. Nothing was wrong on any screen taken
/// alone — the numbers were plausible everywhere — but moving between them, the
/// mark and the first line visibly jumped.
///
/// THE CAUSES WERE ALL DIFFERENT, which is why no single number fixed it:
///
///   • home's mark sits inside a 44pt tap target, so its ink centres lower than
///     a bare 32pt header row;
///   • the contents put its top inset on the SCREEN rather than on the header,
///     so it stacked with the header's own;
///   • profile set its title two points smaller than every other screen, which
///     made its header band shorter;
///   • notes, the desk and the house each chose their own gap below the header
///     — 26, 30 and 22;
///   • and the recovery screen had no header at all.
///
/// So the fix is not a constant, it is a COMPONENT. `ScreenHeaderFrame` gives
/// every header the same band whatever it contains, and the metrics below are
/// the only place the numbers live. A screen that composes from these cannot
/// drift, and one that does not is visible in a diff.
///
/// THE BAND IS 44pt because that is the tap-target minimum home's mark needs.
/// Making every other header the same height costs nothing — their content
/// centres in it — and it is what puts the mark, the back chevron and every
/// title on one line across the app.

import SwiftUI

enum RSScreen {
    /// The margin every screen's content sits inside.
    static let horizontal: CGFloat = 26
    /// Above the header band.
    static let headerTop: CGFloat = 8
    /// The header band itself. 44pt is the tap-target minimum, and using it
    /// everywhere is what aligns the mark with the titles.
    static let headerHeight: CGFloat = 44
    /// Between the header band and the first line of content.
    static let contentGap: CGFloat = 26
    /// Above the bottom edge, for screens with a pinned action.
    static let bottom: CGFloat = 12
    /// Between the scroll region and the pinned action block.
    static let actionTop: CGFloat = 14

    /// The gap to use when the first element carries its OWN top inset — a
    /// list row with vertical padding, say. Without this the row's padding
    /// stacks on the standard gap and the first LINE of that screen sits lower
    /// than the first line of a screen that starts with a heading: measured at
    /// 158pt against everyone else's 142–146 before this existed.
    static func contentGap(insetBy own: CGFloat) -> CGFloat {
        max(0, contentGap - own)
    }
}

/// The header band. Whatever it holds sits centred in the same 44pt strip on
/// every screen, so the first line of content below it starts at one height.
struct ScreenHeaderFrame<Content: View>: View {
    @ViewBuilder var content: Content

    var body: some View {
        HStack(alignment: .center, spacing: 10) {
            content
            Spacer(minLength: 0)
        }
        .frame(minHeight: RSScreen.headerHeight, alignment: .leading)
        .padding(.top, RSScreen.headerTop)
    }
}

/// The ordinary pushed-screen header: a back chevron and a title in the guest's
/// display serif.
///
/// The title is capped and allowed to wrap, and the chevron is centred in the
/// band rather than against the text — found by screenshot on the old rooms
/// list, where an uncapped title wrapped to two lines and a chevron aligned to
/// it came to rest between them, reading as a stray glyph inside the heading
/// rather than as the way out.
struct ScreenHeader: View {
    let title: String
    var onClose: () -> Void = {}

    var body: some View {
        ScreenHeaderFrame {
            BackChevron(action: onClose)
            Text(title)
                .rsFont(.display, size: 22, weight: .medium, maxSize: 30)
                .foregroundStyle(Color.rsInk)
                .fixedSize(horizontal: false, vertical: true)
        }
    }
}

/// The way out, at one size everywhere.
struct BackChevron: View {
    var action: () -> Void = {}

    var body: some View {
        Button(action: action) {
            Image(systemName: "chevron.left")
                .font(.system(size: 18, weight: .medium))
                .foregroundStyle(Color.rsInkMuted)
                .frame(width: 32, height: 32)
                .contentShape(Rectangle())
        }
        .accessibilityLabel("Back")
    }
}

extension View {
    /// The standard screen inset. One call so a screen cannot pick its own
    /// margin by accident.
    func rsScreenInsets() -> some View {
        padding(.horizontal, RSScreen.horizontal)
            .padding(.bottom, RSScreen.bottom)
    }

    /// The gap between the header band and the first line of content.
    ///
    /// `ownInset` is any top padding the first element already carries, so the
    /// first line lands at one height whether the screen opens with a heading
    /// or with a padded row.
    func rsBelowHeader(ownInset: CGFloat = 0) -> some View {
        padding(.top, RSScreen.contentGap(insetBy: ownInset))
    }

    /// A screen's primary action block, at one height on every screen.
    ///
    /// Vertical only: the horizontal margin is set once at the screen root, so
    /// applying it again here would double it — and the whole point is that
    /// every primary button starts and ends at the same x as every other.
    ///
    /// This is meant to be applied OUTSIDE the scroll region. Decision 0224
    /// established that content scrolls and the action does not, and 0253
    /// measured that the rule had reached exactly two screens out of eleven;
    /// the screens that adopt this get the rule for free.
    func rsActionBar() -> some View {
        padding(.top, RSScreen.actionTop)
            .padding(.bottom, RSScreen.bottom)
    }
}
