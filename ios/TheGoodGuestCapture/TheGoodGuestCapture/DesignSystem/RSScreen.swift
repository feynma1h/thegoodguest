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
    /// Between the parts of the action block.
    static let actionSpacing: CGFloat = 10
    /// The closing line's slot. One line of footnote plus a control's touch
    /// padding, so a caption and a tappable line occupy the same height.
    static let closingHeight: CGFloat = 26

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
///
/// TRAILING CONTENT GOES IN ITS OWN SLOT, and that is not tidiness. The first
/// version took one content block and appended a `Spacer`; a caller that wanted
/// something at the right edge had to add a Spacer of its own, and the two then
/// SPLIT the free space between them — SwiftUI divides it equally among
/// spacers, so the guidance screen's close cross came to rest halfway across
/// the header instead of flush right. With the slot there is nothing for a
/// caller's spacer to fight.
struct ScreenHeaderFrame<Leading: View, Trailing: View>: View {
    @ViewBuilder var leading: Leading
    @ViewBuilder var trailing: Trailing

    var body: some View {
        HStack(alignment: .center, spacing: 10) {
            leading
            Spacer(minLength: 8)
            trailing
        }
        .frame(minHeight: RSScreen.headerHeight, alignment: .leading)
        .padding(.top, RSScreen.headerTop)
    }
}

extension ScreenHeaderFrame where Trailing == EmptyView {
    init(@ViewBuilder leading: () -> Leading) {
        self.init(leading: leading, trailing: { EmptyView() })
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
                .rsFont(.display, size: 22, weight: .medium, maxSize: 30, cap: .display)
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
    ///
    /// Two shapes of screen use this. Where the action is a sibling of the
    /// scroll region — home, review — the screen root supplies the horizontal
    /// margin and nothing scrolls behind it. Where it is pinned with
    /// `safeAreaInset`, content scrolls UNDERNEATH and the bar has to be
    /// opaque: see `rsPinnedActions`, which is the form those screens use.
    func rsActionBar() -> some View {
        padding(.top, RSScreen.actionTop)
            .padding(.bottom, RSScreen.bottom)
    }

    /// An action block pinned over a scroll region with `safeAreaInset`.
    ///
    /// FULL-BLEED AND OPAQUE, and that is the whole point rather than a
    /// finish. A safe-area inset reserves room at the bottom and lets content
    /// scroll behind what sits there, so a transparent action bar is one the
    /// body copy renders straight through. At the default text size nothing
    /// overflows far enough to show it; at AX5 it put the closing line
    /// letter-on-letter over the body on profile, the recovery screen and the
    /// QR bridge, unreadable on all three, while the suite stayed green. Only
    /// the guidance sheet escaped, because it set a background of its own —
    /// which is exactly the kind of per-screen memory this replaces.
    ///
    /// A flat fill, not the parchment gradient: measured off a real frame, the
    /// gradient moves 3 levels across this bar's whole height, so its bottom
    /// stop is indistinguishable from it here.
    ///
    /// It owns the horizontal margin too, because a bar that is inset before
    /// it is filled leaves a transparent strip down each edge — the same bug,
    /// 26pt wide. Padding then background and NOTHING ELSE: an added
    /// `frame(maxWidth: .infinity)` looks redundant and is not — inside a
    /// `safeAreaInset` it changes the height the bar is offered, and profile's
    /// primary went from wrapping to two lines to truncating at "Sign in to
    /// kee…". This is the shape the guidance sheet has been using all along.
    func rsPinnedActions(surface: Color = .rsBackground) -> some View {
        padding(.horizontal, RSScreen.horizontal)
            .background(surface)
    }
}


/// The line that sits under a primary action.
///
/// Home's "Takes about two minutes" and review's "Not now" are the same thing
/// in the layout — a single small line closing the action block — and they were
/// set differently, which is part of why the primaries above them did not line
/// up. One style so they cannot drift again.
///
/// It is a touch darker than a pure caption on purpose: this one is TAPPABLE,
/// and a control that looks exactly like a label is a control nobody presses.
struct RSActionFootnoteStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(RSFont.ui(.footnote))
            .rsControlLabel()
            .foregroundStyle(Color.rsInkMuted)
            .frame(maxWidth: .infinity)
            .padding(.vertical, 2)
            .opacity(configuration.isPressed ? 0.55 : 1)
    }
}


// MARK: - The action block

/// A screen's actions, shaped so the filled button lands at the same height on
/// every screen.
///
/// THE RULE IS ABOUT WHAT SITS BELOW. A primary button's distance from the
/// bottom of the phone is decided entirely by what follows it, so screens with
/// different numbers of controls put theirs at different heights — measured at
/// 77pt on home, 104pt on the recovery screen and 161pt on review, which is a
/// jump of nearly an inch between screens a person moves straight between.
///
/// So the block is fixed in shape: any EXTRA controls sit above the primary,
/// the primary comes next, and below it is exactly one small closing line —
/// home's "Takes about two minutes", review's "Not now". Since what is beneath
/// the primary is always the same one line, the primary is always the same
/// height off the bottom, whatever else the screen offers.
///
/// The cost, stated plainly: a secondary action reads BEFORE the primary rather
/// than after it, which is not the usual iOS order. That is the trade for the
/// buttons lining up, and it was made deliberately.
struct RSActions<Extra: View, Primary: View, Closing: View>: View {
    /// Secondary actions, above the primary. Empty on most screens.
    @ViewBuilder var extra: Extra
    /// The one filled button.
    @ViewBuilder var primary: Primary
    /// Exactly one small line. Never two, or the primary moves.
    @ViewBuilder var closing: Closing

    var body: some View {
        VStack(spacing: RSScreen.actionSpacing) {
            extra
            primary
            // A FIXED SLOT, so the closing line's own height cannot move the
            // button above it. A plain caption and a tappable footnote differ
            // by the button style's touch padding — a few points, but enough
            // that screens landed anywhere from 69pt to 79pt off the bottom
            // depending on which kind of line they closed with.
            closing
                .frame(minHeight: RSScreen.closingHeight)
        }
        .rsActionBar()
    }
}

extension RSActions where Extra == EmptyView {
    init(@ViewBuilder primary: () -> Primary, @ViewBuilder closing: () -> Closing) {
        self.init(extra: { EmptyView() }, primary: primary, closing: closing)
    }
}
