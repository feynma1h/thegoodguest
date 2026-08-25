/// Reusable Good Guest building blocks (design spec §10, decision 0072): the two
/// button treatments, the guest line, the mono eyebrow, and the cream card
/// surface. Screens compose from these so the language stays consistent and the
/// rule of gold is enforced structurally — the gold CTA has its own style and is
/// reached for only at light-semantic peaks (Pro-capture start, the doorway).

import SwiftUI

// MARK: - Buttons

/// The primary action: rust fill, cream label, full-width, soft rust shadow.
/// The everyday CTA — "Scan a room", "Send it home", "Scan the room again".
struct RSPrimaryButtonStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(RSFont.ui(.headline, weight: .semibold))
            .foregroundStyle(Color.rsSurface)
            .frame(maxWidth: .infinity)
            .padding(.vertical, 17)
            .background(Color.rsAction, in: RoundedRectangle(cornerRadius: 16, style: .continuous))
            .shadow(color: Color.rsAction.opacity(0.26), radius: 20, y: 8)
            .opacity(configuration.isPressed ? 0.82 : 1)
            .scaleEffect(configuration.isPressed ? 0.985 : 1)
            .animation(.easeOut(duration: 0.12), value: configuration.isPressed)
    }
}

/// The light-semantic peak CTA: gold fill, ink label. Reserved for the
/// light-quality moments — Pro-capture start and the doorway. NOT a generic
/// accent button (see the rule of gold in RSColor).
struct RSGoldButtonStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(RSFont.ui(.headline, weight: .semibold))
            .foregroundStyle(Color.rsInk)
            .frame(maxWidth: .infinity)
            .padding(.vertical, 17)
            .background(Color.rsGold, in: RoundedRectangle(cornerRadius: 16, style: .continuous))
            .shadow(color: Color.rsGold.opacity(0.4), radius: 24, y: 8)
            .opacity(configuration.isPressed ? 0.85 : 1)
            .scaleEffect(configuration.isPressed ? 0.985 : 1)
            .animation(.easeOut(duration: 0.12), value: configuration.isPressed)
    }
}

/// A light primary for DARK surfaces — cream fill, ink label. The primary action
/// on the ink-dark screens (terminal failure's "Scan the room again"), where a
/// rust fill would recede into the warmth.
struct RSLightButtonStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(RSFont.ui(.headline, weight: .semibold))
            .foregroundStyle(Color.rsInk)
            .frame(maxWidth: .infinity)
            .padding(.vertical, 16)
            .background(Color.rsSurface, in: RoundedRectangle(cornerRadius: 14, style: .continuous))
            .opacity(configuration.isPressed ? 0.85 : 1)
            .scaleEffect(configuration.isPressed ? 0.985 : 1)
            .animation(.easeOut(duration: 0.12), value: configuration.isPressed)
    }
}

/// A quiet secondary choice — text only, muted ink. "Not now", "Later".
struct RSQuietButtonStyle: ButtonStyle {
    var onDark = false
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(RSFont.ui(.callout, weight: .medium))
            .foregroundStyle(onDark ? Color.rsOnDark.opacity(0.75) : Color.rsInkMuted)
            .frame(maxWidth: .infinity)
            .padding(.vertical, 12)
            .opacity(configuration.isPressed ? 0.6 : 1)
    }
}

// MARK: - Text roles

/// A line in the guest's voice — serif italic. The default color reads on light
/// surfaces; pass `onDark` for capture/failure screens.
struct GuestLine: View {
    let text: String
    var size: CGFloat = 16
    var onDark = false
    var textAlignment: TextAlignment = .leading
    /// Optional growth ceiling, for guest copy sitting between FIXED elements (the
    /// capture overlay, where the mesh above and the shutter below don't move).
    /// Body copy elsewhere scales uncapped.
    var maxSize: CGFloat?

    init(_ text: String, size: CGFloat = 16, onDark: Bool = false, alignment: TextAlignment = .leading, maxSize: CGFloat? = nil) {
        self.text = text
        self.size = size
        self.onDark = onDark
        self.textAlignment = alignment
        self.maxSize = maxSize
    }

    var body: some View {
        Text(text)
            .rsFont(.guest, size: size, maxSize: maxSize)
            .foregroundStyle(onDark ? Color.rsOnDark.opacity(0.82) : Color.rsInkMuted)
            .multilineTextAlignment(textAlignment)
            .lineSpacing(2)
    }
}

/// A mono eyebrow — small, upper, tracked. Section labels, "YOUR ID", state tags.
struct Eyebrow: View {
    let text: String
    var onDark = false

    init(_ text: String, onDark: Bool = false) {
        self.text = text
        self.onDark = onDark
    }

    var body: some View {
        Text(text.uppercased())
            .rsFont(.mono, size: 10, weight: .semibold)
            .tracking(1.4)
            .foregroundStyle(onDark ? Color.rsOnDark.opacity(0.5) : Color.rsInkFaint)
    }
}

// MARK: - Surfaces

/// The cream card surface — hairline border, continuous corners, standard inset.
struct RSCard<Content: View>: View {
    var padding: CGFloat = 18
    @ViewBuilder var content: Content

    var body: some View {
        content
            .padding(padding)
            .background(Color.rsSurface, in: RoundedRectangle(cornerRadius: 14, style: .continuous))
            .overlay(
                RoundedRectangle(cornerRadius: 14, style: .continuous)
                    .stroke(Color.rsHairline, lineWidth: 1)
            )
    }
}
