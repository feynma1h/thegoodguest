/// The QR / deep-link bridge (design spec §9). The web can hand a session *back*
/// to the phone — most usefully to fill a gap the reveal exposed. A universal link
/// (or QR when scanning from a desktop) opens the app straight into a targeted
/// rescan for that room, already signed in.
///
/// DECLARED PLACEHOLDER: the QR encodes nothing yet (no deep-link infra exists),
/// and the transport (universal links) is enrollment/entitlement-gated
/// (associated-domains) — this is the UI + the seam. `onScan` is wired when the
/// bridge infra lands (decision 0072). The QR glyph is a decorative stand-in.

import SwiftUI

struct QRBridgeView: View {
    var onScan: () -> Void = {}

    var body: some View {
        VStack(spacing: 0) {
            Spacer()

            Eyebrow("From your desk", onDark: true)

            QRPlaceholder()
                .frame(width: 150, height: 150)
                .padding(.top, 22)

            Text("The desk needs one more corner")
                .rsFont(.display, size: 22, cap: .display)
                .foregroundStyle(Color.rsOnDark)
                .multilineTextAlignment(.center)
                .padding(.top, 26)

            GuestLine("Your desk asked me to grab a spot it couldn't quite see. Point your phone at the screen and I'll pick up right where we left off.",
                      size: 15, onDark: true, alignment: .center)
                .padding(.horizontal, 34)
                .padding(.top, 12)

            Spacer()
        }
        .padding(.horizontal, RSScreen.horizontal)
        .frame(maxWidth: .infinity)
        .modifier(RSScrollableScreen(background: Color.rsCaptureRaised))
        .safeAreaInset(edge: .bottom) {
            RSActions {
                Button(action: onScan) { Text("Scan the code") }
                    .buttonStyle(RSGoldButtonStyle())
            } closing: {
                Text("Opens the camera to read the code")
                    .font(RSFont.ui(.footnote))
                    .foregroundStyle(Color.rsOnDark.opacity(0.5))
            }
            .rsPinnedActions(surface: .rsCaptureRaised)
        }
    }
}

/// A decorative QR-like glyph on a cream tile — a stand-in until real deep-link
/// codes exist. Deterministic pattern, not a scannable code.
private struct QRPlaceholder: View {
    private let cells = 9

    var body: some View {
        ZStack {
            RoundedRectangle(cornerRadius: 20, style: .continuous).fill(Color.rsSurface)
            Canvas { ctx, size in
                let pad: CGFloat = 18
                let grid = size.width - pad * 2
                let c = grid / CGFloat(cells)
                for row in 0..<cells {
                    for col in 0..<cells {
                        if Self.filled(row, col) {
                            let rect = CGRect(x: pad + CGFloat(col) * c, y: pad + CGFloat(row) * c, width: c, height: c)
                            ctx.fill(Path(rect), with: .color(.rsCaptureRaised))
                        }
                    }
                }
            }
        }
    }

    /// Fixed finder-corners + a deterministic body — evocative, not real data.
    static func filled(_ r: Int, _ c: Int) -> Bool {
        func corner(_ r: Int, _ c: Int) -> Bool { (r < 3 && c < 3) || (r < 3 && c > 5) || (r > 5 && c < 3) }
        if corner(r, c) { return !((r == 1 || r == 7) && (c == 1 || c == 7)) }
        return (r * 7 + c * 3) % 5 == 0
    }
}

#Preview {
    QRBridgeView()
}
