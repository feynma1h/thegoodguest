/// Review before send (design spec §4, beat two). A brief, confident review: the
/// finished sketch shown whole with mono capture metrics (the one place raw
/// numbers belong), the guest's plain verdict, and one honest chance to add more
/// before it travels. Finishing is a decision made with confidence, not a gamble.
///
/// NO PREVIEW OF THE REAL ROOM, on purpose: this shows the SKETCH, never a
/// rendered 3D room — the real room belongs to the reveal, on the web. Showing a
/// rough version here would spend the magic early.
///
/// Thin-coverage variant: when the capture has gaps, the copy shifts and "Add a
/// little more" becomes the primary path.

import SwiftUI

struct ReviewView: View {
    /// Mono capture metrics, e.g. "42 m² · 3.9 M PTS · LiDAR".
    var metrics: String = "42 m² · 3.9 M PTS · LiDAR"
    /// The guest's verdict on the capture.
    var verdict: String = "This is a clean one — I can see the whole room. Send it, and I'll start making sense of it on your desk."
    /// When true, coverage is thin — "Add a little more" leads.
    var thinCoverage: Bool = false
    var onSend: () -> Void = {}
    var onAddMore: () -> Void = {}

    var body: some View {
        VStack(spacing: 0) {
            Eyebrow("Your capture")
                .padding(.top, 8)

            sketchCard
                .padding(.top, 16)

            RSCard {
                Text(thinCoverage
                     ? "I've got the bones, but a few gaps. Worth another minute to fill them in?"
                     : verdict)
                    .font(RSFont.guest(size: 15.5))
                    .foregroundStyle(Color.rsInk)
                    .fixedSize(horizontal: false, vertical: true)
                    .frame(maxWidth: .infinity, alignment: .leading)
            }
            .padding(.top, 16)

            Spacer()

            actions
                .padding(.bottom, 8)
        }
        .padding(.horizontal, 24)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .rsParchmentScreen()
    }

    // MARK: Pieces

    private var sketchCard: some View {
        ZStack(alignment: .bottomLeading) {
            RoundedRectangle(cornerRadius: 16, style: .continuous)
                .fill(Color.rsCaptureRaised)
            RoomSketch()
                .padding(20)
            Text(metrics)
                .font(RSFont.mono(size: 10, weight: .medium))
                .tracking(0.6)
                .foregroundStyle(Color.rsOnDark.opacity(0.6))
                .padding(12)
        }
        .frame(height: 230)
        .clipShape(RoundedRectangle(cornerRadius: 16, style: .continuous))
        .shadow(color: Color.rsInk.opacity(0.2), radius: 10, y: 6)
    }

    private var actions: some View {
        VStack(spacing: 10) {
            if thinCoverage {
                Button { onAddMore() } label: {
                    Text("Add a little more")
                }
                .buttonStyle(RSPrimaryButtonStyle())
                Button { onSend() } label: { Text("Send it as is") }
                    .buttonStyle(RSQuietButtonStyle())
            } else {
                Button { onSend() } label: {
                    Label("Send it home", systemImage: "square.and.arrow.up")
                }
                .buttonStyle(RSPrimaryButtonStyle())
                Button { onAddMore() } label: { Text("Add a little more") }
                    .buttonStyle(RSQuietButtonStyle())
            }
        }
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
    ReviewView()
}

#Preview("Thin coverage") {
    ReviewView(thinCoverage: true)
}
