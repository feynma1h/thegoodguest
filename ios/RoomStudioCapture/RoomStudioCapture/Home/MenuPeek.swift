/// The mark, and the hint that plays once per launch to say it is a way in.
///
/// THE PROBLEM IT SOLVES. A mark in a corner is a logo, and logos are not
/// tappable. The first attempt at making it obviously a control put a caption
/// under it, which is the app explaining its own interface. The second put the
/// mark in a bordered plate with a chevron, which read as a logo someone had
/// bolted a button to. This is the third: the mark is left exactly as it is,
/// and instead of dressing it, the app shows what is behind it — once, briefly,
/// on each fresh launch — and then gets out of the way.
///
/// A row slides out from behind the mark: a dotted leader and the word MENU,
/// set the way the contents screen sets its own leaders and mono truths, so the
/// hint is a preview of the thing it is pointing at rather than a label about
/// it.
///
/// ONCE PER PROCESS, which is what "a fresh open" means. The latch is static
/// rather than @State: home is the root of a NavigationStack and stays alive
/// while other screens are pushed over it, so `onAppear` fires again every time
/// the user comes back from the contents — and a hint that replayed on the way
/// back from the very screen it advertises would be absurd.
///
/// IT WAITS FOR THE SPLASH. The brief says the peek begins half a second after
/// home appears, and home appears on the first frame of the process: it is
/// alive underneath the splash the whole time that plays, so a timer started at
/// `onAppear` would run the entire hint behind it and finish before anyone saw
/// home at all. It starts when the splash clears instead, which is what "after
/// home appears" means from the only side that matters.
///
/// IT CARRIES THE SPLASH'S LANDING SITE. The mark here is the rectangle the
/// launch animation walks its own mark into, published as an anchor preference
/// — see SplashView. Whatever wraps the mark has to keep publishing it, or the
/// splash silently falls back to fading at screen centre.
///
/// THE REVEAL IS A MASK, not a slide. The row is laid out once, at its final
/// size, and uncovered from the mark's edge rightward — so nothing stretches,
/// and the letterforms are the right shape at every frame. The mark is drawn
/// over the row's leading edge, so the row emerges from behind it.

import SwiftUI

/// The once-per-process latch.
@MainActor
enum MenuPeekOnce {
    private static var claimed = false

    /// True exactly once per launch, for the first caller.
    static func claim() -> Bool {
        guard !claimed else { return false }
        claimed = true
        return true
    }

    #if DEBUG
    /// The screenshot gallery renders one screen per launch, so the latch would
    /// let the peek play there — which is what we want. This exists only so a
    /// test or a preview can replay it.
    static func reset() { claimed = false }
    #endif
}

struct MenuPeekMark: View {
    var onTap: () -> Void = {}

    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @Environment(\.splashIsPlaying) private var splashIsPlaying

    /// How much of the row is uncovered, 0...1.
    @State private var reveal: CGFloat = 0
    @State private var rowOpacity: CGFloat = 0
    @State private var play: Task<Void, Never>?

    // The brief's numbers, in one place.
    private enum Peek {
        static let gap: CGFloat = 14
        static let leaderWidth: CGFloat = 64
        static let delay: Duration = .milliseconds(500)
        static let move: Double = 0.8
        static let hold: Duration = .milliseconds(2300)
        /// Reduced motion keeps the information and drops the movement: the row
        /// is simply present for as long as it would otherwise have been
        /// readable, which is the hold plus the two passes it replaces.
        static let staticHold: Duration = .milliseconds(2300)
    }

    var body: some View {
        ZStack(alignment: .leading) {
            row
                // Uncovered from the mark's edge rightward. A GeometryReader in
                // the mask rather than a fixed width, so the row's own measured
                // size decides how far the reveal has to travel — the label's
                // width moves with the text size.
                .mask(alignment: .leading) {
                    GeometryReader { geo in
                        Rectangle()
                            .frame(width: geo.size.width * reveal)
                            .frame(maxWidth: .infinity, alignment: .leading)
                    }
                }
                .opacity(rowOpacity)
                .allowsHitTesting(false)
                .accessibilityHidden(true)

            // Drawn last so it occludes the row's leading edge: the row comes
            // out from behind the mark rather than appearing beside it.
            //
            // This is also the splash's landing site. The anchor and the
            // hold-invisible-while-it-travels both live here because this is
            // where the mark actually is — moving them anywhere else would
            // publish the wrong rectangle, which is exactly the bug that
            // replacing the header with this view briefly introduced.
            ChromeMark()
                .anchorPreference(key: MarkSlotKey.self, value: .bounds) { $0 }
                .opacity(splashIsPlaying ? 0 : 1)
        }
        // The mark is ~22pt tall; the target is not.
        .frame(minWidth: 44, minHeight: 44, alignment: .leading)
        .contentShape(Rectangle())
        .onTapGesture { tapped() }
        .accessibilityElement()
        .accessibilityLabel("Contents")
        .accessibilityHint("The house, the desk, notes and you")
        .accessibilityAddTraits(.isButton)
        .accessibilityAction { tapped() }
        .onAppear { startIfDue() }
        // The splash is an overlay, so home never re-appears when it leaves —
        // this is the only signal that the screen is actually visible.
        .onChange(of: splashIsPlaying) { _, playing in
            if !playing { startIfDue() }
        }
        .onDisappear { play?.cancel() }
    }

    // MARK: The row

    private var row: some View {
        HStack(spacing: 0) {
            // The gap is inside the row so the mask's origin is the mark's own
            // edge: the first thing uncovered is empty space, which is what
            // makes the leader read as coming out from underneath.
            Color.clear.frame(width: markWidth + Peek.gap, height: 1)

            DottedLeader()
                .frame(width: Peek.leaderWidth, height: 2)

            Text("Menu")
                .rsFont(.mono, size: 11, weight: .medium, cap: .mono)
                .tracking(0.18 * 11)
                .textCase(.uppercase)
                .foregroundStyle(Color.peekLabel)
                .fixedSize()
                .padding(.leading, 10)
        }
    }

    /// The mark is 1.72 times wider than it is tall; the row has to clear it
    /// before the gap starts.
    private var markWidth: CGFloat {
        22 * MarkGeometry.inkWidth / MarkGeometry.inkHeight
    }

    // MARK: Playing

    private func startIfDue() {
        guard !splashIsPlaying, play == nil, MenuPeekOnce.claim() else { return }
        play = Task { await run() }
    }

    private func run() async {
        try? await Task.sleep(for: Peek.delay)
        guard !Task.isCancelled else { return }

        guard !reduceMotion else {
            rowOpacity = 1
            reveal = 1
            try? await Task.sleep(for: Peek.staticHold)
            guard !Task.isCancelled else { return }
            rowOpacity = 0
            reveal = 0
            return
        }

        withAnimation(.easeInOut(duration: Peek.move)) {
            reveal = 1
            rowOpacity = 1
        }
        try? await Task.sleep(for: .milliseconds(Int(Peek.move * 1000)) + Peek.hold)
        guard !Task.isCancelled else { return }

        withAnimation(.easeInOut(duration: Peek.move)) {
            reveal = 0
            rowOpacity = 0
        }
    }

    /// A tap during the hint takes it away at once and goes. Waiting for a
    /// retract the user has already answered would make the app feel like it
    /// was finishing its sentence first.
    private func tapped() {
        play?.cancel()
        play = nil
        reveal = 0
        rowOpacity = 0
        onTap()
    }
}

// MARK: - Pieces

/// The hint's leader, drawn to match the contents screen's own.
private struct DottedLeader: View {
    var body: some View {
        Line()
            .stroke(style: StrokeStyle(lineWidth: 2, lineCap: .round, dash: [0.5, 5]))
            .foregroundStyle(Color.peekLeader)
    }

    private struct Line: Shape {
        func path(in rect: CGRect) -> Path {
            var p = Path()
            p.move(to: CGPoint(x: rect.minX, y: rect.midY))
            p.addLine(to: CGPoint(x: rect.maxX, y: rect.midY))
            return p
        }
    }
}

extension Color {
    /// The hint's two greys, given by the design brief as literal values.
    ///
    /// NOT derived from the ink token, deliberately and against this app's
    /// usual rule that no view hard-codes a hex: they were specified exactly,
    /// and inventing an opacity of `rsInk` that happened to land near them
    /// would be pretending they came from the palette. Named here so there is
    /// one place to tokenise them if the brand ever absorbs them.
    static let peekLeader = Color(rsHex: 0xcfc6ba)
    static let peekLabel  = Color(rsHex: 0x8b837b)
}

#if DEBUG
#Preview("Peek") {
    MenuPeekMark()
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .padding(26)
        .rsParchmentScreen()
}
#endif
