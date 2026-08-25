/// The brand on iOS: the mark, the name, and the rule that keeps them apart.
///
/// THE RULE. The mark IS the "oo" of "the good guest" — the same two loops the
/// script draws in the middle of "good", compacted and tilted. So the mark and
/// the name are NEVER set side by side: a lockup of the two would print the
/// same two letters twice, once as a drawing and once as a word. Every surface
/// picks one. The app's chrome takes the mark alone, because it is a signature
/// for someone already inside — and because the name has just had a whole
/// screen to itself.
///
/// That screen is the only place both appear, and they appear in SEQUENCE
/// rather than together: `SplashView` opens on the name and resolves it into
/// the mark, which states the rule as a motion instead of breaking it.
///
/// The mark's geometry is NOT authored here. It comes from `MarkGeometry.swift`,
/// which `tools/gen_mark.py` generates from the one source every surface is cut
/// from — the app icon, the tab icon, the web's mark and the share cards. To
/// change the mark, change the generator and re-run it.
///
/// The ring is the band between two concentric ellipses, and it is filled
/// EVEN-ODD. Fill it nonzero and the interior stops being a hole, the two rings
/// become solid blobs, and the interlock — the only thing that makes this a
/// mark rather than an ellipse — is gone.
///
/// The mark's colour is absolute rather than a `color` parameter, and it is the
/// app's own token: `rsAction`. A mark that took the tint of whatever it sat
/// next to would be a different mark on every screen; this one is the same
/// object the person already met on their home screen. `tone` picks the ink and
/// nothing else — terracotta on light chrome, and the reverse cream on the
/// capture and failure surfaces, where terracotta on near-black reaches only
/// 3.11:1 and reads too quiet at chrome sizes.

import SwiftUI

enum RSBrand {
    /// The product name. The one-file swap for the name on iOS.
    ///
    /// It is also set as `INFOPLIST_KEY_CFBundleDisplayName` in the Xcode
    /// project, which is what the Home Screen shows under the icon — that one
    /// cannot read this constant, so the two are kept in step by
    /// `BrandNameTests`.
    static let name = "The Good Guest"
}

/// Which ink the mark is drawn in. Geometry never varies.
enum MarkTone {
    /// Terracotta, for light chrome. The mark as drawn.
    case ink
    /// Cream, for the dark capture and failure surfaces.
    case reverse

    var color: Color {
        switch self {
        case .ink: .rsAction
        case .reverse: .rsOnDark
        }
    }
}

/// One ring of the mark: the band between two concentric tilted ellipses.
private struct MarkRingShape: Shape {
    let ring: MarkRing

    func path(in rect: CGRect) -> Path {
        // The generated values live in a square design space; the ink inside it
        // is wider than it is tall, so fit by the ink box rather than by the
        // canvas or the mark would sit in 48% empty air.
        let scale = min(
            rect.width / MarkGeometry.inkWidth,
            rect.height / MarkGeometry.inkHeight
        )
        let centre = CGPoint(x: rect.midX, y: rect.midY)
        var path = Path()
        for ellipse in [ring.outer, ring.inner] {
            var local = Path()
            local.addEllipse(
                in: CGRect(
                    x: -ellipse.a, y: -ellipse.b,
                    width: ellipse.a * 2, height: ellipse.b * 2
                )
            )
            let placed = local.applying(
                CGAffineTransform(rotationAngle: MarkGeometry.tiltDegrees * .pi / 180)
                    .concatenating(
                        CGAffineTransform(
                            translationX: ellipse.cx - MarkGeometry.canvas / 2,
                            y: ellipse.cy - MarkGeometry.canvas / 2
                        )
                    )
                    .concatenating(CGAffineTransform(scaleX: scale, y: scale))
                    .concatenating(CGAffineTransform(translationX: centre.x, y: centre.y))
            )
            path.addPath(placed)
        }
        return path
    }
}

/// The mark, at the given ink HEIGHT. The whole of the brand in chrome — never
/// with the name beside it.
///
/// Sized by height because the mark is 1.72 times wider than it is tall, so a
/// square frame would be mostly empty and every call site would be picking a
/// number that means nothing. The design file's floor is height >= 20pt; below
/// that the ring band falls under 1.5pt and greys out.
struct Mark: View {
    var height: CGFloat = 20
    var tone: MarkTone = .ink

    var body: some View {
        ZStack {
            ForEach(Array(MarkGeometry.rings.enumerated()), id: \.offset) { _, ring in
                MarkRingShape(ring: ring).fill(tone.color, style: FillStyle(eoFill: true))
            }
        }
        .frame(width: height * MarkGeometry.inkWidth / MarkGeometry.inkHeight, height: height)
        .accessibilityHidden(true)
    }
}

#Preview {
    VStack(spacing: 40) {
        Mark(height: 44)
        Mark(height: 20)
        Mark(height: 34, tone: .reverse).padding(24).background(Color.rsCaptureBase)
    }
    .frame(maxWidth: .infinity, maxHeight: .infinity)
    .background(Color.rsBackground)
}
