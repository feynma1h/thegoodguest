/// Idle home — the app's resting state, rebuilt to the 2b design.
///
/// Home now holds three things and nothing else: the claim, one sentence that
/// reports, and the pinned action. Everything it used to stack — the
/// upload-failed banner, the re-entry row, the rooms-trouble line — lives on a
/// screen of its own, and the sentence is the only thing that says so.
///
/// WHY THE NOTICE SLOT IS GONE. It was the right fix for the wrong shape. The
/// slot existed so notices would scroll instead of squeezing the pinned action
/// (decision 0224), and it worked — but three of them could still stack, and
/// the claim was pushed down the page by however much the day happened to
/// weigh. The sentence cannot stack: `HomeLineResolver` returns exactly one, or
/// none. The claim's position is now fixed whatever the day looks like, which
/// is the property the slot could never give it.
///
/// THE CLAIM NO LONGER DISAPPEARS. The old home swapped the hero for the rooms
/// strip the moment any room existed, so the product's own thesis vanished
/// permanently after the first scan with nowhere to find it again. The rooms
/// moved to the house; the claim stayed. It is on screen on day one and on day
/// four hundred.
///
/// THE WAY IN IS THE MARK, which opens the contents — the whole map of the app,
/// as a screen you navigate to and come back from rather than a sheet that
/// slides over. Nothing explains it in words and nothing dresses it up: once
/// per launch a dotted leader and the word MENU slide out from behind it, and
/// then it is a mark again. See MenuPeek.
///
/// The mark and not a lockup: the brand lane's rule is that the mark IS the two
/// middle letters of the name, so the two are never set side by side and app
/// chrome takes the mark alone. That makes the tap target a ~22pt glyph, so it
/// is placed in a 44pt frame — the platform minimum, and not a number this
/// screen may negotiate down.

import SwiftUI

struct HomeView: View {
    /// What the day looks like. One value feeds both the sentence and the
    /// contents sheet, so the two cannot disagree.
    var day: HomeDay = HomeDay()
    var onScan: () -> Void = {}
    /// Tapping the mark. Opens the contents.
    var onOpenContents: () -> Void = {}
    /// Tapping the sentence. Nil destination means there is no sentence.
    var onFollowLine: (HomeDestination) -> Void = { _ in }

    @Environment(\.dynamicTypeSize) private var typeSize

    private var line: HomeLine? { HomeLineResolver.line(for: day) }

    var body: some View {
        VStack(spacing: 0) {
            header

            // Scrollable: at accessibility sizes the claim alone exceeds the
            // space between the header and the action, and with a fixed layout
            // the clipped text was unrecoverable. Content scrolls; the action
            // does not.
            ScrollView {
                // WHEN ONLY ONE CAN BE SEEN, THE ONE THAT CHANGES WINS.
                //
                // At accessibility sizes the claim alone fills the whole scroll
                // region, and the sentence — home's entire reporting surface —
                // went below the fold with nothing indicating it was there.
                // Found by screenshot; the suite was green throughout, because
                // the routing was correct and only the rendering was not. A
                // home that cannot say "something needs you" is worse than the
                // stacked notices this design replaced.
                //
                // So at those sizes the order swaps. The claim is a standing
                // statement and can be scrolled to; the sentence is why the
                // person opened the app.
                VStack(alignment: .leading, spacing: 26) {
                    if typeSize.isAccessibilitySize {
                        reportingLine
                        claim
                    } else {
                        claim
                        reportingLine
                    }
                }
                .rsBelowHeader()
                .frame(maxWidth: .infinity, alignment: .leading)
            }

            scanAction
        }
        .padding(.horizontal, RSScreen.horizontal)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .rsParchmentScreen()
    }

    // MARK: - Pieces

    /// The mark, bare, with the hint that says it is a way in.
    ///
    /// No plate, no border, no chevron — the mark is left exactly as the brand
    /// draws it. What makes it legible as a control is `MenuPeekMark`, which
    /// shows what is behind it once per launch and then gets out of the way.
    /// The tap target is still 44pt; it is simply invisible.
    ///
    /// The old profile glyph moved into the contents: home's corner carries one
    /// affordance, not two, and a second glyph beside the first would make
    /// neither of them obviously the way in.
    private var header: some View {
        ScreenHeaderFrame {
            MenuPeekMark(onTap: onOpenContents)
        }
    }

    @ViewBuilder
    private var reportingLine: some View {
        if let line {
            LineButton(line: line) { onFollowLine(line.destination) }
        }
    }

    private var claim: some View {
        VStack(alignment: .leading, spacing: 14) {
            Text("Every home holds a version of itself you've never seen.")
                .rsFont(.guest, size: 25)
                .foregroundStyle(Color.rsInk)
                .lineSpacing(4)
                .fixedSize(horizontal: false, vertical: true)
            // The support line is first-run only. Once someone has walked a
            // room, telling them how to walk one is instruction they no longer
            // need, and the sentence below is using that space to report.
            if day.isFirstRun {
                Text("Walk one room slowly with your phone. It comes alive on your desk — real, in 3D, exactly as you live in it.")
                    .font(RSFont.ui(.callout))
                    .foregroundStyle(Color.rsInkMuted)
                    .lineSpacing(3)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    private var scanAction: some View {
        RSActions {
            Button {
                RSHaptics.fire(.scanTapped)
                onScan()
            } label: {
                // NO GLYPH, pending a ruling. The design replaces Apple's
                // viewfinder with the product's own mark here, and the mark is
                // the right instinct — but at button size it collapses into an
                // unreadable smudge, which is worse than the stock symbol it
                // was meant to improve on. A full-width rust button reading
                // "Scan a room" needs no glyph at all, so it ships without one
                // rather than with a broken one.
                Text("Scan a room")
            }
            .buttonStyle(RSPrimaryButtonStyle())
        } closing: {
            Text("Takes about two minutes")
                .font(RSFont.ui(.footnote))
                .foregroundStyle(Color.rsInkFaint)
        }
    }
}

/// The mark at chrome size, in ONE place.
///
/// One size for the mark wherever it acts as chrome — home's header and the
/// contents sheet — so the thing you tap and the thing at the top of what it
/// opens are recognisably the same object. It earned its keep immediately: the
/// brand lane's re-cut mark landed with a different API, and this was the only
/// line that had to change.
struct ChromeMark: View {
    var body: some View { Mark(height: 22) }
}

// MARK: - The sentence

/// Home's one reporting sentence, rendered as the control it is.
///
/// The whole row is the target: the sentence states a fact and offers one move,
/// so there is no second affordance competing with the scan action for the eye.
/// Top-aligned, because at accessibility sizes the sentence wraps to several
/// lines and a vertically centred chevron comes to rest in the middle of them,
/// reading as though it pointed at one word.
private struct LineButton: View {
    let line: HomeLine
    var onTap: () -> Void = {}

    var body: some View {
        Button(action: onTap) {
            HStack(alignment: .top, spacing: 10) {
                Text(line.text)
                    .rsFont(.guest, size: 17)
                    .foregroundStyle(ink)
                    .lineSpacing(3)
                    .fixedSize(horizontal: false, vertical: true)
                    .multilineTextAlignment(.leading)
                Spacer(minLength: 4)
                Image(systemName: "chevron.right")
                    .font(.system(size: 13, weight: .semibold))
                    .foregroundStyle(ink.opacity(0.45))
                    .frame(height: 24, alignment: .center)
            }
            .frame(maxWidth: .infinity, alignment: .leading)
        }
        .buttonStyle(.plain)
    }

    /// The rule of gold, enforced at the one place the sentence is inked: gold
    /// only ever means light arriving, rust is the single urgency colour, and
    /// everything else is ordinary ink.
    private var ink: Color {
        switch line.tone {
        case .needsYou: return .rsAction
        case .arrival:  return .rsGoldInk
        case .inFlight: return .rsGoldInk
        case .quiet:    return .rsInkMuted
        }
    }
}

// MARK: - Previews

#Preview("First run") {
    HomeView(day: HomeDay(isFirstRun: true))
}

#Preview("Ordinary day") {
    HomeView(day: HomeDay(roomCount: 6))
}

#Preview("A room in flight") {
    HomeView(day: HomeDay(hasRoomInFlight: true, roomCount: 6))
}

#Preview("Arrival") {
    HomeView(day: HomeDay(hasUnseenArrival: true, roomCount: 6))
}

#Preview("Needs you") {
    HomeView(day: HomeDay(needsYou: 1, hasRoomInFlight: true, roomCount: 6))
}

#Preview("Rooms unreachable") {
    HomeView(day: HomeDay(roomCount: nil))
}
