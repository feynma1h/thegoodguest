/// The wordmark and the placeholder product name (design spec §1/§10). This is
/// the SINGLE point of change for the name on iOS — the mirror of the web app's
/// `Wordmark.tsx`. No product name has been chosen; "roomstudio" is a stand-in.
/// When the name lands, change `RSBrand.name` (and the ❖ mark if it changes) here
/// and nowhere else.

import SwiftUI

enum RSBrand {
    /// Placeholder product name. One-file swap when the real name is chosen.
    static let name = "roomstudio"
    /// The mark glyph — a serif ❖ inside a rounded-square outline.
    static let mark = "❖"
}

/// The ❖ mark in a stroked rounded-square box. Sizable; used solo (avatar, push
/// icon) and inside the horizontal lockup.
struct WordmarkGlyph: View {
    var size: CGFloat = 30
    var color: Color = .rsInk
    var filled = false

    var body: some View {
        RoundedRectangle(cornerRadius: size * 0.3, style: .continuous)
            .stroke(color, lineWidth: filled ? 0 : max(1.2, size * 0.05))
            .background(
                filled
                    ? RoundedRectangle(cornerRadius: size * 0.3, style: .continuous).fill(color)
                    : nil
            )
            .frame(width: size, height: size)
            .overlay(
                Text(RSBrand.mark)
                    .rsFont(.display, size: size * 0.52, maxSize: size * 0.62)
                    .foregroundStyle(filled ? Color.rsSurface : color)
            )
    }
}

/// Horizontal lockup: the mark + the name in the display serif. The app's quiet
/// chrome identity (home header, etc.).
struct Wordmark: View {
    var glyphSize: CGFloat = 30
    var nameSize: CGFloat = 17
    var color: Color = .rsInk

    var body: some View {
        HStack(spacing: 9) {
            WordmarkGlyph(size: glyphSize, color: color)
            Text(RSBrand.name)
                .rsFont(.display, size: nameSize, weight: .medium)
                .foregroundStyle(color)
        }
    }
}

#Preview {
    VStack(spacing: 40) {
        WordmarkGlyph(size: 44)
        Wordmark()
        WordmarkGlyph(size: 34, color: .rsAction, filled: true)
    }
    .frame(maxWidth: .infinity, maxHeight: .infinity)
    .background(Color.rsBackground)
}
