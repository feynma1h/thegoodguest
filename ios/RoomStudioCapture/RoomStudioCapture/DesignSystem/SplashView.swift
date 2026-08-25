/// The launch splash: the name, resolving into the mark.
///
/// This is the ONE place the wordmark and the mark both appear, and the whole
/// reason it is allowed is that they appear in SEQUENCE. The mark is the "oo"
/// of "the good guest" — set the two side by side and you print those letters
/// twice, which is why every other surface picks one (see Wordmark.swift). Show
/// them one after the other and the same fact becomes the point: the name is
/// there, the word closes on its own middle, and what is left standing is the
/// two loops it was already carrying.
///
/// The letters do not evaporate. They GATHER, and each one on its own clock:
/// the outermost set off first and the ones already touching the "oo" leave
/// last, so the word closes from its ends inward rather than sliding in as two
/// slabs. They chase the rings as they travel rather than collapsing at a spot
/// the rings have already left. Letters vanishing in place would say the mark
/// replaced the name; letters arriving say the mark was inside it all along.
///
/// THE MORPH IS EXACT, and not by careful tuning.
///
/// `WordmarkGeometry.rings` is not a shape that resembles the mark; it IS
/// `MarkGeometry.rings`, uniformly scaled into the lettering by the generator.
/// So the two ends of this animation are the same drawing at two similarities,
/// and interpolating their four numbers — centre, semi-major, semi-minor — is
/// itself a similarity of that drawing. The tilt never varies, and the axis
/// ratio survives the interpolation: with a0/b0 = a1/b1 = r, the ratio of the
/// two lerps is r again at every t. **Every intermediate frame is the mark, at
/// some size.** There is no cross-fade hiding a shape change, and nothing to
/// re-check if the lettering is ever re-traced.
///
/// It is an OVERLAY, not a route. RootFlowView is alive underneath from the
/// first frame and its launch tasks — anonymous sign-in, the storage sweep,
/// upload rehydration, the reap — run while this plays, so the splash spends
/// time the app was going to spend anyway rather than adding any. Nothing waits
/// on it and it cannot fail into a dead end: the timeline is unconditional.
///
/// Once per PROCESS, which is what a launch means. `WindowGroup` builds its
/// body once, so the state below cannot re-fire on a foreground resume — a
/// splash that replayed every time the user came back from the camera roll
/// would be the most irritating thing in the app.
///
/// Reduced motion gets the same three beats with no travel: the name holds, and
/// it cross-fades to the mark in place. The information is identical; only the
/// movement is gone.

import SwiftUI

/// The two ring pairs, interpolated. See the note above on why lerping these
/// four numbers is exact rather than approximate.
private struct MorphingRings: Shape {
    var progress: CGFloat
    /// Both in the view's own coordinates, already placed.
    let start: [MarkRing]
    let end: [MarkRing]

    var animatableData: CGFloat {
        get { progress }
        set { progress = newValue }
    }

    func path(in rect: CGRect) -> Path {
        var path = Path()
        for (from, to) in zip(start, end) {
            path.addPath(BrandPath.ring(lerp(from, to, progress)))
        }
        return path
    }

    private func lerp(_ a: MarkRing, _ b: MarkRing, _ t: CGFloat) -> MarkRing {
        MarkRing(outer: lerp(a.outer, b.outer, t), inner: lerp(a.inner, b.inner, t))
    }

    private func lerp(_ a: MarkEllipse, _ b: MarkEllipse, _ t: CGFloat) -> MarkEllipse {
        MarkEllipse(
            cx: a.cx + (b.cx - a.cx) * t,
            cy: a.cy + (b.cy - a.cy) * t,
            a: a.a + (b.a - a.a) * t,
            b: a.b + (b.b - a.b) * t
        )
    }
}

/// One letter of the lettering, travelling to the centre as a rigid body.
///
/// The whole word is drawn and then CLIPPED to this piece's own column, so a
/// letter keeps its shape exactly — it slides, it does not stretch. An earlier
/// pass moved every point by its own distance instead, which deformed the word
/// as it went and read as the letters rolling over each other rather than
/// being carried.
///
/// The clip happens before the offset, so the column travels with its letter.
/// Clipping after would hold a window still and wipe the letter across it.
///
/// Joined script has no contour boundary between a "t" and an "h", so the
/// columns come from `WordmarkGeometry.letterCuts`, which the generator finds
/// by looking for the thinnest part of the drawing near each letter-width
/// interval. Cuts fall through thin strokes, which is why the pieces separate
/// cleanly instead of tearing.
private struct LetterPiece: View {
    let index: Int
    let span: ClosedRange<CGFloat>
    let progress: CGFloat
    let scale: CGFloat
    let offset: CGPoint
    let anchorStart: CGPoint
    let anchorEnd: CGPoint
    let reach: CGFloat
    let boxHeight: CGFloat

    /// How much of the run is spent staggering the departures.
    private static let stagger: CGFloat = 0.40

    /// The piece's own clock. Furthest from the loops leaves first, so the word
    /// closes from its ends inward rather than all at once.
    private var local: CGFloat {
        let midX = (span.lowerBound + span.upperBound) / 2
        let far = reach > 0 ? min(1, abs(midX - anchorStart.x) / reach) : 0
        let delay = (1 - far) * Self.stagger
        return min(1, max(0, (progress - delay) / (1 - Self.stagger)))
    }

    var body: some View {
        let eased = local * local * (3 - 2 * local)
        let anchorNow = CGPoint(
            x: anchorStart.x + (anchorEnd.x - anchorStart.x) * progress,
            y: anchorStart.y + (anchorEnd.y - anchorStart.y) * progress
        )
        let midX = (span.lowerBound + span.upperBound) / 2
        let home = CGPoint(x: midX, y: anchorStart.y)

        FullScript(scale: scale, offset: offset)
            .fill(Color.rsAction, style: FillStyle(eoFill: true))
            .clipShape(
                Rectangle().path(
                    in: CGRect(
                        x: span.lowerBound, y: offset.y - boxHeight,
                        width: span.upperBound - span.lowerBound, height: boxHeight * 3
                    )
                )
            )
            .offset(
                x: (anchorNow.x - home.x) * eased,
                y: (anchorNow.y - home.y) * eased
            )
            // Each letter dims as IT arrives, not when the word does, so the
            // ones already stacked at the centre stop competing with the ones
            // still on their way.
            .opacity(Double(1 - eased * eased))
    }
}

/// The lettering, whole and still. Every piece draws this and shows one column.
private struct FullScript: Shape {
    let scale: CGFloat
    let offset: CGPoint

    func path(in rect: CGRect) -> Path {
        BrandPath.script { raw in
            CGPoint(x: raw.x * scale + offset.x, y: raw.y * scale + offset.y)
        }
    }
}

struct SplashView: View {
    /// Called once the mark has settled and the splash has faded.
    var onFinished: () -> Void = {}

    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var progress: CGFloat = 0
    @State private var scriptOpacity: CGFloat = 0
    @State private var markOpacity: CGFloat = 0
    @State private var veil: CGFloat = 1

    /// How wide the name is set, and how tall the mark ends up. The wordmark
    /// floor is the binding constraint: the script's x-height is 16% of its
    /// box, so 300pt of width gives a 12pt x-height — comfortably above the
    /// 8pt below which this lettering stops being readable.
    private let nameWidth: CGFloat = 300
    private let markHeight: CGFloat = 58

    var body: some View {
        GeometryReader { geo in
            let centre = CGPoint(x: geo.size.width / 2, y: geo.size.height / 2)
            let nameW = min(nameWidth, geo.size.width - 64)
            let nameScale = nameW / WordmarkGeometry.width
            let nameOrigin = CGPoint(
                x: centre.x - nameW / 2,
                y: centre.y - WordmarkGeometry.height * nameScale / 2
            )
            let markScale = markHeight / MarkGeometry.inkHeight

            let startRings = placed(
                WordmarkGeometry.rings, scale: nameScale, offset: nameOrigin
            )
            let endRings = placed(
                MarkGeometry.rings,
                scale: markScale,
                offset: CGPoint(
                    x: centre.x - MarkGeometry.canvas * markScale / 2,
                    y: centre.y - MarkGeometry.canvas * markScale / 2
                )
            )

            ZStack {
                ForEach(Array(letterSpans(scale: nameScale, offset: nameOrigin).enumerated()),
                        id: \.offset) { i, span in
                    LetterPiece(
                        index: i,
                        span: span,
                        progress: progress,
                        scale: nameScale,
                        offset: nameOrigin,
                        anchorStart: midpoint(of: startRings),
                        anchorEnd: midpoint(of: endRings),
                        reach: max(
                            midpoint(of: startRings).x - nameOrigin.x,
                            nameOrigin.x + WordmarkGeometry.width * nameScale
                                - midpoint(of: startRings).x
                        ),
                        boxHeight: WordmarkGeometry.height * nameScale
                    )
                }
                .opacity(scriptOpacity)

                MorphingRings(progress: progress, start: startRings, end: endRings)
                    .fill(Color.rsAction, style: FillStyle(eoFill: true))
                    .opacity(markOpacity)
            }
            .frame(width: geo.size.width, height: geo.size.height)
        }
        .rsParchmentScreen()
        .opacity(veil)
        .accessibilityElement()
        .accessibilityLabel(RSBrand.name)
        .task { await play() }
    }

    /// One design space's rings, moved into the view's own coordinates.
    private func placed(_ rings: [MarkRing], scale: CGFloat, offset: CGPoint) -> [MarkRing] {
        func move(_ e: MarkEllipse) -> MarkEllipse {
            MarkEllipse(
                cx: e.cx * scale + offset.x,
                cy: e.cy * scale + offset.y,
                a: e.a * scale,
                b: e.b * scale
            )
        }
        return rings.map { MarkRing(outer: move($0.outer), inner: move($0.inner)) }
    }

    /// The lettering's columns, in view coordinates: one per letter-ish piece.
    ///
    /// Built from the generated cuts, with the outer edges of the wordmark box
    /// closing the first and last. The pieces tile the box exactly, so no ink
    /// is dropped and none is drawn twice.
    private func letterSpans(scale: CGFloat, offset: CGPoint) -> [ClosedRange<CGFloat>] {
        let edges =
            [0] + WordmarkGeometry.letterCuts + [WordmarkGeometry.width]
        return zip(edges, edges.dropFirst()).map { a, b in
            (a * scale + offset.x)...(b * scale + offset.x)
        }
    }

    /// The centre of a placed ring pair — what the lettering gathers toward.
    private func midpoint(of rings: [MarkRing]) -> CGPoint {
        let xs = rings.map(\.outer.cx)
        let ys = rings.map(\.outer.cy)
        return CGPoint(
            x: xs.reduce(0, +) / CGFloat(xs.count),
            y: ys.reduce(0, +) / CGFloat(ys.count)
        )
    }

    /// Every duration in the splash, in one place.
    ///
    /// Paced to be READ rather than to get out of the way: the name is on
    /// screen for a second and a half before anything moves, and the gather
    /// runs long enough to watch the far letters leave before the near ones do.
    /// The whole thing is about 3.6s, which is the cost of the splash and the
    /// number to change if that is too much.
    private enum Timing {
        static let arrive = 0.55
        static let holdName = 0.90
        static let gather = 1.40
        /// The ink lasts about two thirds of the gather — long enough to see
        /// the cascade, short enough that nothing is still visible when it
        /// collapses onto the anchor.
        static let letterFade = 0.98
        static let holdMark = 0.45
        static let leave = 0.42

        static func ms(_ seconds: Double) -> Duration { .milliseconds(Int(seconds * 1000)) }
    }

    /// The three beats. Unconditional: nothing here can fail, so nothing can
    /// leave the splash on screen.
    private func play() async {
        guard !reduceMotion else { await playReduced(); return }

        // 1. The name arrives, and is given time to be read.
        withAnimation(.easeOut(duration: Timing.arrive)) {
            scriptOpacity = 1
            markOpacity = 1
        }
        try? await Task.sleep(for: Timing.ms(Timing.arrive + Timing.holdName))

        // 2. The word closes on its own "oo" while the loops carry it to the
        //    centre and open into the mark. ONE progress value drives both, so
        //    the letters cannot arrive somewhere the rings are not.
        withAnimation(.timingCurve(0.35, 0, 0.2, 1, duration: Timing.gather)) { progress = 1 }
        withAnimation(.easeIn(duration: Timing.letterFade)) { scriptOpacity = 0 }
        try? await Task.sleep(for: Timing.ms(Timing.gather))

        // 3. A beat on the mark, then out of the way.
        try? await Task.sleep(for: Timing.ms(Timing.holdMark))
        withAnimation(.easeOut(duration: Timing.leave)) { veil = 0 }
        try? await Task.sleep(for: Timing.ms(Timing.leave))
        onFinished()
    }

    private func playReduced() async {
        progress = 1
        withAnimation(.easeOut(duration: Timing.arrive)) { scriptOpacity = 1 }
        // The name still comes first; only the travel is gone, so the rings
        // wait where the mark will be rather than moving into it.
        markOpacity = 0
        try? await Task.sleep(for: Timing.ms(Timing.arrive + Timing.holdName))
        withAnimation(.easeInOut(duration: Timing.letterFade)) {
            scriptOpacity = 0
            markOpacity = 1
        }
        try? await Task.sleep(for: Timing.ms(Timing.letterFade + Timing.holdMark))
        withAnimation(.easeOut(duration: Timing.leave)) { veil = 0 }
        try? await Task.sleep(for: Timing.ms(Timing.leave))
        onFinished()
    }
}

extension View {
    /// Plays the splash over this view, once per process.
    ///
    /// The content below is live and its launch work runs the whole time — see
    /// the note at the top of this file for why that is the point.
    func splashOnLaunch() -> some View {
        modifier(SplashOverlay())
    }
}

private struct SplashOverlay: ViewModifier {
    @State private var showing = true

    func body(content: Content) -> some View {
        content.overlay {
            if showing {
                SplashView { showing = false }
                    .transition(.identity)
                    .zIndex(1)
            }
        }
    }
}

// There is deliberately no reduced-motion preview: `accessibilityReduceMotion`
// is a read-only environment key, so the only honest way to see that path is
// to turn the setting on -- `xcrun simctl ui <udid> reduce_motion enabled`.
#Preview("Splash") {
    SplashView()
}
