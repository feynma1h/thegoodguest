/// The wordmark and the placeholder product name (design spec §1/§10). This is
/// the SINGLE point of change for the name on iOS — the mirror of the web app's
/// `Wordmark.tsx`. No product name has been chosen; "roomstudio" is a stand-in.
/// When the name lands, change `RSBrand.name` here and nowhere else.
///
/// The mark is the room corner: a pointy-top hexagon divided by a three-way
/// seam into two wall faces and a floor — the captured volume, seen at true
/// 30° isometric. Its geometry is NOT authored here. It comes from
/// `MarkGeometry.swift`, which `tools/gen_mark.py` generates from the one
/// source every surface is cut from — this lockup, the app icon, the web
/// wordmark, the tab icon and the share card. To change the mark, change the
/// generator and re-run it.
///
/// The mark's colours are absolute rather than a `color` parameter, and they
/// are the app's own tokens: `rsInk`, `rsSurface`, `rsAction`. A mark that
/// took the tint of whatever it sat next to would be a different mark on every
/// screen; this one is the same object the person already met on their home
/// screen. `onDark` picks the ink plate and nothing else — the framed plate
/// on light chrome, the frameless plate on the capture and failure surfaces,
/// where decision 0176 measured a full rim band reading as a heavy ring rather
/// than a drawn edge.

import SwiftUI

enum RSBrand {
    /// Placeholder product name. One-file swap when the real name is chosen.
    static let name = "The Good Guest"
}

/// One filled polygon of the mark, scaled from the generated 1024 design space.
private struct MarkPolygon: Shape {
    let points: [CGPoint]

    func path(in rect: CGRect) -> Path {
        var path = Path()
        guard let first = points.first else { return path }
        let scale = min(rect.width, rect.height) / MarkGeometry.canvas
        func place(_ p: CGPoint) -> CGPoint {
            CGPoint(x: rect.minX + p.x * scale, y: rect.minY + p.y * scale)
        }
        path.move(to: place(first))
        for point in points.dropFirst() { path.addLine(to: place(point)) }
        path.closeSubpath()
        return path
    }
}

/// The mark alone. Sizable; used solo (profile hero, push icon) and inside the
/// horizontal lockup.
struct Mark: View {
    var size: CGFloat = 30
    /// True on the capture and terminal-failure surfaces — see the type note.
    var onDark = false

    var body: some View {
        ZStack {
            MarkPolygon(points: onDark ? MarkGeometry.plateFrameless : MarkGeometry.plateFramed)
                .fill(Color.rsInk)
            MarkPolygon(points: MarkGeometry.faces[0]).fill(Color.rsSurface)
            MarkPolygon(points: MarkGeometry.faces[1]).fill(Color.rsSurface)
            MarkPolygon(points: MarkGeometry.faces[2]).fill(Color.rsAction)
        }
        .frame(width: size, height: size)
        .accessibilityHidden(true)
    }
}

/// Horizontal lockup: the mark + the name in the display serif. The app's quiet
/// chrome identity (home header, etc.).
struct Wordmark: View {
    var glyphSize: CGFloat = 30
    var nameSize: CGFloat = 17
    var color: Color = .rsInk
    var onDark = false

    var body: some View {
        HStack(spacing: 9) {
            Mark(size: glyphSize, onDark: onDark)
            Text(RSBrand.name)
                .rsFont(.display, size: nameSize, weight: .medium)
                .foregroundStyle(color)
        }
    }
}

#Preview {
    VStack(spacing: 40) {
        Mark(size: 44)
        Wordmark()
        Mark(size: 34)
    }
    .frame(maxWidth: .infinity, maxHeight: .infinity)
    .background(Color.rsBackground)
}
