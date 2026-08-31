/// Review before send (design spec §4, beat two). A brief, confident review: the
/// finished sketch shown whole with mono capture metrics (the one place raw
/// numbers belong), the guest's plain verdict, and one honest chance to scan it
/// again before it travels. Finishing is a decision made with confidence, not a
/// gamble.
///
/// NO PREVIEW OF THE REAL ROOM, on purpose: this shows the SKETCH, never a
/// rendered 3D room — the real room belongs to the reveal, on the web. Showing a
/// rough version here would spend the magic early.
///
/// THIN-COVERAGE VARIANT: BUILT BUT NOT REACHABLE TODAY. `thinCoverage` is never
/// set true. A coverage SIGNAL now exists (the live census + floor plan), but
/// wiring it into a "your capture is thin" verdict is a copy claim about capture
/// quality that deserves an operator decision, not a threshold invented here —
/// deliberately deferred pending that decision. Until then its copy ("I've got
/// the bones, but a few gaps") must be read as designed-but-dormant, NOT as
/// something the screen can say today.
///
/// COPY FOLLOWS THE ACTIONS. `cardText` mirrors `actions`' precedence exactly, and
/// they must stay in step: the two disagreed once — a capture that could not be
/// sent at all (empty, or bundle.pb assembly failed) showed the rescan action
/// correctly while the card discarded the caller's verdict and claimed "I've got
/// the bones, but a few gaps", which is a coverage claim about a capture that does
/// not exist. The caller's verdict wins whenever the capture is not sendable.
///
/// NOTE ON THE SECONDARY ACTION: it RESCANS, it does not extend. CaptureManager's
/// startCapture() mints a new bundleId and clears frames/anchors/outputDir, so
/// there is no append path today — hence `rescanLabel`/`onRescan` rather than the
/// "add more" naming this screen started with. True resume-with-progress is an
/// activation follow-up; until it exists nothing here may imply additive
/// behaviour.

import SwiftUI

struct ReviewView: View {
    /// Mono capture metrics, e.g. "126 frames · LiDAR + RoomPlan". REQUIRED, with no
    /// default: a sample default ("42 m² · 3.9 M PTS") is invented capture data, and
    /// a call site that forgot to pass real numbers would ship it as measurement.
    var metrics: String
    /// The RoomPlan census line, e.g. "9 objects · 13 walls · 2 doors" (decision
    /// 0077). Nil hides it — a capture whose room did not ship must not show a
    /// census (the line describes what the server will see, and the
    /// composition is pinned in RoomCensus.reviewLine).
    var census: String? = nil
    /// The BUILT room's floor plan — "the room you got", the same component
    /// that drew live during capture, now settled. Published under the
    /// census's rule (only when the room ships), so like the census it
    /// shows what the server will see. Nil falls back to the generic sketch.
    var floorPlan: FloorPlanSnapshot? = nil
    /// The guest's verdict on the capture. REQUIRED, with no default, for the same
    /// reason as `metrics` and `rescanLabel`: the old default asserted "I can see the
    /// whole room", which is a coverage claim the app deliberately does not make.
    var verdict: String
    /// When true, coverage is thin — the rescan path leads. NEVER TRUE TODAY; see the
    /// thin-coverage note in the file header before wiring it.
    var thinCoverage: Bool = false
    /// False when there is nothing worth sending (an empty capture). The send
    /// action is withheld rather than letting the backend reject it and report the
    /// failure as if the upload broke in transit.
    var canSend: Bool = true
    /// True while bundle.pb is still being written — transient, unlike the other
    /// non-sendable states, so the action set must not reshuffle when it clears.
    var isPreparing: Bool = false
    /// The rescan label. REQUIRED, with no default: a default of "Add a little
    /// more" would ship an additive promise the capture layer cannot keep the
    /// moment any call site forgot to override it.
    var rescanLabel: String
    var onSend: () -> Void = {}
    var onRescan: () -> Void = {}
    /// Leave review without sending or rescanning. Required for the screen to have
    /// an exit at all — see `actions`.
    var onLeave: () -> Void = {}

    var body: some View {
        // Scrollable: at accessibility text sizes the sketch card + verdict + three
        // actions exceed the screen, and without this nothing is reachable.
        VStack(spacing: 0) {
        ScrollView {
            VStack(spacing: 0) {
                // In the shared header band, so this screen's first line sits
                // level with every other screen's — it has no back chevron, but
                // it has the same top strip.
                ScreenHeaderFrame { Eyebrow("Your capture") }

                sketchCard
                    .rsBelowHeader()

                RSCard {
                    Text(Self.cardText(verdict: verdict,
                                       thinCoverage: thinCoverage,
                                       canSend: canSend,
                                       isPreparing: isPreparing))
                        .rsFont(.guest, size: 15.5)
                        .foregroundStyle(Color.rsInk)
                        .fixedSize(horizontal: false, vertical: true)
                        .frame(maxWidth: .infinity, alignment: .leading)
                }
                .padding(.top, 16)

            }
            .frame(maxWidth: .infinity, minHeight: 0)
        }

        // Outside the scroll region: the send is the decision this screen
        // exists for, and it used to sit at the end of the content where a
        // long capture pushed it off the bottom.
        actions
        }
        .padding(.horizontal, RSScreen.horizontal)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .rsParchmentScreen()
    }

    // MARK: Copy

    /// The verdict card's text. Static + internal so the precedence can be pinned by
    /// tests instead of read out of a ViewBuilder — the copy and the action set are
    /// two expressions of one decision, and when they were written separately they
    /// drifted apart (see the header note).
    ///
    /// Precedence, mirroring `actions`:
    ///   1. Not sendable at all (still packing, empty capture, assembly failed) →
    ///      the CALLER's verdict, which is the only thing that knows which of those
    ///      it is. A coverage claim here would describe a capture that may not exist.
    ///   2. Thin coverage → the gaps copy. (Unreachable today; see the header.)
    ///   3. Otherwise → the caller's verdict.
    static func cardText(verdict: String, thinCoverage: Bool, canSend: Bool, isPreparing: Bool) -> String {
        if isPreparing || !canSend { return verdict }
        if thinCoverage {
            return "I've got the bones, but a few gaps. Worth another minute to fill them in?"
        }
        return verdict
    }

    // MARK: Pieces

    private var sketchCard: some View {
        ZStack(alignment: .bottomLeading) {
            RoundedRectangle(cornerRadius: 16, style: .continuous)
                .fill(Color.rsCaptureRaised)
            if let floorPlan, !floorPlan.isEmpty {
                // The real room, drawn — still a sketch, never a 3D preview
                // (the reveal belongs to the web; see the header).
                FloorPlanCanvas(snapshot: floorPlan, animated: false,
                                backdrop: Color.rsCaptureRaised, padding: 10)
                    .padding(.init(top: 14, leading: 14, bottom: 40, trailing: 14))
            } else {
                RoomSketch()
                    .padding(20)
            }
            VStack(alignment: .leading, spacing: 3) {
                // Bottom-anchored inside a fixed 230pt card: uncapped they wrap up
                // over the sketch ("126 frames · LiDAR + RoomPlan" at AX sizes).
                if let census {
                    Text(census)
                        .rsFont(.mono, size: 10, weight: .medium, maxSize: 14, cap: .mono)
                        .lineLimit(1)
                        .minimumScaleFactor(0.7)
                        .tracking(0.6)
                        .foregroundStyle(Color.rsOnDark.opacity(0.75))
                }
                Text(metrics)
                    .rsFont(.mono, size: 10, weight: .medium, maxSize: 14, cap: .mono)
                    .lineLimit(1)
                    .minimumScaleFactor(0.7)
                    .tracking(0.6)
                    .foregroundStyle(Color.rsOnDark.opacity(0.6))
            }
            .padding(12)
        }
        .frame(height: 230)
        .clipShape(RoundedRectangle(cornerRadius: 16, style: .continuous))
        .shadow(color: Color.rsInk.opacity(0.2), radius: 10, y: 6)
    }

    /// The action block. Every branch has the same shape — anything extra
    /// above, the one filled button, then a single closing line — so "Send it
    /// home" sits at the same height off the bottom as home's "Scan a room",
    /// whichever branch is showing.
    ///
    /// The rescan moved ABOVE the send to make that true. It reads before the
    /// primary rather than after it, which is not the usual iOS order; that is
    /// the trade for the buttons lining up across screens.
    ///
    /// Precedence still mirrors `cardText` exactly, which is what stopped the
    /// copy and the actions drifting apart before.
    @ViewBuilder
    private var actions: some View {
        let leave = Button { onLeave() } label: { Text("Not now") }
            .buttonStyle(RSActionFootnoteStyle())

        if isPreparing {
            // TRANSIENT: the send is moments away, so keep it in the primary
            // slot (disabled) rather than promoting the destructive rescan into
            // it and swapping the button under the user's finger when the
            // bundle lands.
            RSActions {
                sendButton.disabled(true).opacity(0.55)
            } closing: { leave }
        } else if !canSend {
            // Nothing to send — the rescan leads, and there is nothing extra.
            RSActions {
                Button { onRescan() } label: { Text(rescanLabel) }
                    .buttonStyle(RSPrimaryButtonStyle())
            } closing: { leave }
        } else if thinCoverage {
            RSActions {
                Button { onSend() } label: { Text("Send it as is") }
                    .buttonStyle(RSQuietButtonStyle())
            } primary: {
                Button { onRescan() } label: { Text(rescanLabel) }
                    .buttonStyle(RSPrimaryButtonStyle())
            } closing: { leave }
        } else {
            RSActions {
                Button { onRescan() } label: { Text(rescanLabel) }
                    .buttonStyle(RSQuietButtonStyle())
            } primary: {
                sendButton
            } closing: { leave }
        }
    }

    private var sendButton: some View {
        Button { onSend() } label: { Text("Send it home") }
            .buttonStyle(RSPrimaryButtonStyle())
    }
}

/// A reusable gold-ink room sketch (the finished capture, drawn — not rendered).
/// Shared by review and the thin-history thumbnails.
struct RoomSketch: View {
    var body: some View {
        GeometryReader { geo in
            let w = geo.size.width, h = geo.size.height
            let ink = Color.rsGoldLight
            ZStack {
                Path { p in
                    p.move(to: pt(0.12, 0.35, w, h)); p.addLine(to: pt(0.5, 0.22, w, h))
                    p.addLine(to: pt(0.88, 0.35, w, h)); p.addLine(to: pt(0.88, 0.72, w, h))
                    p.addLine(to: pt(0.5, 0.87, w, h)); p.addLine(to: pt(0.12, 0.72, w, h)); p.closeSubpath()
                }.stroke(ink.opacity(0.8), lineWidth: 1.2)
                Path { p in
                    p.move(to: pt(0.5, 0.22, w, h)); p.addLine(to: pt(0.5, 0.87, w, h))
                    p.move(to: pt(0.12, 0.35, w, h)); p.addLine(to: pt(0.12, 0.72, w, h))
                    p.move(to: pt(0.88, 0.35, w, h)); p.addLine(to: pt(0.88, 0.72, w, h))
                }.stroke(ink.opacity(0.55), lineWidth: 1)
                Path { p in
                    p.move(to: pt(0.24, 0.5, w, h)); p.addLine(to: pt(0.42, 0.56, w, h))
                    p.addLine(to: pt(0.42, 0.72, w, h)); p.addLine(to: pt(0.24, 0.66, w, h)); p.closeSubpath()
                }.stroke(ink.opacity(0.5), lineWidth: 1)
            }
        }
    }

    private func pt(_ fx: Double, _ fy: Double, _ w: CGFloat, _ h: CGFloat) -> CGPoint {
        CGPoint(x: CGFloat(fx) * w, y: CGFloat(fy) * h)
    }
}

#Preview("Clean capture") {
    ReviewView(metrics: "126 frames · LiDAR + RoomPlan",
               census: "9 objects · 13 walls · 2 doors",
               verdict: "Here's your capture. Send it, and I'll start making sense of it on your desk.",
               rescanLabel: "Scan again from scratch")
}

#Preview("Clean capture — with floor plan") {
    ReviewView(metrics: "293 frames · LiDAR + RoomPlan",
               census: "3 objects · 4 walls · 1 door",
               floorPlan: .previewRoom,
               verdict: "Here's your capture. Send it, and I'll start making sense of it on your desk.",
               rescanLabel: "Scan again from scratch")
}

// DORMANT TREATMENT — thinCoverage is never true in the app. This preview is
// the only place it renders; see the header note before wiring it.
#Preview("Thin coverage (dormant)") {
    ReviewView(metrics: "48 frames · LiDAR + RoomPlan",
               verdict: "Here's your capture. Send it, and I'll start making sense of it on your desk.",
               thinCoverage: true,
               rescanLabel: "Scan again from scratch")
}
