/// The shared controls and text pieces, in the website's language.
///
/// ONE FILLED PILL PER SCREEN: ink on light screens, light on dusk ones. It is
/// the action the screen exists for. Everything else is a quiet text action or
/// a system button in the navigation bar. Terracotta never fills a control.
///
/// Labels are clamped by `rsControlLabel()` (decision 0258): a button keeps
/// the shape its fixed padding gives it at every text size.

import SwiftUI

/// The filled pill. Ink on light screens; on dusk, a light pill with dusk text.
struct RSPrimaryButtonStyle: ButtonStyle {
    var onDusk = false
    /// Bold Text: the label's face is named, so it follows the setting only
    /// when asked to.
    @Environment(\.legibilityWeight) private var legibilityWeight

    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(RSFont.ui(.headline, weight: legibilityWeight == .bold ? RSFont.bolder(.semibold) : .semibold))
            .rsControlLabel()
            .foregroundStyle(onDusk ? Color.rsDusk : Color.white)
            .fixedSize(horizontal: false, vertical: true)
            .multilineTextAlignment(.center)
            .frame(maxWidth: .infinity, minHeight: 56)
            .padding(.vertical, 2)
            .padding(.horizontal, 22)
            .background(onDusk ? Color.rsOnDusk : Color.rsInk, in: Capsule())
            .contentShape(Capsule())
            .opacity(configuration.isPressed ? 0.8 : 1)
            .scaleEffect(configuration.isPressed ? 0.985 : 1)
            .animation(.easeOut(duration: 0.12), value: configuration.isPressed)
    }
}

/// The quiet action: words in ink, no shape, a full-width 50pt target.
struct RSQuietButtonStyle: ButtonStyle {
    var onDark = false
    @Environment(\.legibilityWeight) private var legibilityWeight

    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(RSFont.ui(.callout, weight: legibilityWeight == .bold ? RSFont.bolder(.semibold) : .semibold))
            .rsControlLabel()
            .foregroundStyle(onDark ? Color.rsOnDusk : Color.rsInk)
            .frame(maxWidth: .infinity, minHeight: 50)
            .contentShape(Rectangle())
            .opacity(configuration.isPressed ? 0.55 : 1)
    }
}

/// The guest speaking: Newsreader italic, in full ink. Reading text, so it
/// scales to the ceiling and is capped by nothing else.
struct GuestLine: View {
    let text: String
    var size: CGFloat = 19
    var onDark = false
    var textAlignment: TextAlignment = .leading
    var maxSize: CGFloat?

    init(_ text: String, size: CGFloat = 19, onDark: Bool = false, alignment: TextAlignment = .leading, maxSize: CGFloat? = nil) {
        self.text = text
        self.size = size
        self.onDark = onDark
        self.textAlignment = alignment
        self.maxSize = maxSize
    }

    var body: some View {
        Text(text)
            .rsFont(.guest, size: size, maxSize: maxSize)
            .foregroundStyle(onDark ? Color.rsOnDusk : Color.rsInk)
            .multilineTextAlignment(textAlignment)
            .lineSpacing(3)
    }
}

/// The guest, under its own label, as on the website: the mark beside the
/// words "The guest" (never beside the product's name, decision 0248), then
/// what it says.
struct GuestVoice: View {
    let text: String
    var size: CGFloat = 19
    var onDark = false

    init(_ text: String, size: CGFloat = 19, onDark: Bool = false) {
        self.text = text
        self.size = size
        self.onDark = onDark
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(spacing: 8) {
                Mark(height: 11)
                Text("The guest")
                    .rsFont(.ui, size: 14, weight: .semibold, cap: .display)
                    .foregroundStyle(onDark ? Color.rsOnDusk : Color.rsInk)
            }
            .accessibilityHidden(true)
            GuestLine(text, size: size, onDark: onDark)
                .fixedSize(horizontal: false, vertical: true)
                .accessibilityLabel("The guest: \(text)")
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}

/// A measurement, set the one way measurements are set: JetBrains Mono in
/// text-sized terracotta. Nothing else in the app uses mono.
struct MeasureText: View {
    let text: String
    var size: CGFloat = 13
    var onDusk = false

    init(_ text: String, size: CGFloat = 13, onDusk: Bool = false) {
        self.text = text
        self.size = size
        self.onDusk = onDusk
    }

    var body: some View {
        Text(text)
            .rsFont(.mono, size: size, weight: .medium, cap: .mono)
            // On dusk the number is light; terracotta stays in the leader
            // lines, where it is a graphic and 3:1 is enough.
            .foregroundStyle(onDusk ? Color.rsOnDusk : Color.rsTerracottaText)
    }
}
