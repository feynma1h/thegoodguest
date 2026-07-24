/// The three Good Guest type roles, translated to SwiftUI (design spec §10,
/// decision 0072). Every screen reaches for one of these three — never a bare
/// `.font(.system(...))`.
///
///   • GUEST voice   — the guest speaking: greetings, narration, confessions,
///                     the doorway. Source Serif 4, *italic*. Warmth.
///   • DISPLAY       — the same serif, upright, for large arrival titles
///                     ("Your room is ready."). Not italic.
///   • UI            — Instrument Sans: buttons, labels, controls.
///   • MONO (machine)— IBM Plex Mono: IDs, capture metrics, the elapsed clock,
///                     byte counts. Never prose.
///
/// FONT BUNDLING SEAM: the branded faces (Source Serif 4 / Instrument Sans /
/// IBM Plex Mono) are not yet in the app bundle, so these fall back to the
/// spec's specified system substitutes — New York (`.serif`), SF Pro
/// (`.default`), and `.monospaced`. When the `.ttf`/`.otf` files are added and
/// registered, change ONLY the private face helpers at the bottom of this file
/// to `Font.custom(_:size:relativeTo:)`; every call site keeps working (and the
/// `relativeTo:` scaling below becomes Font.custom's own, so behaviour matches).
///
/// DYNAMIC TYPE: `Font.system(size:)` is inert, so fixed point sizes are applied
/// through the `.rsFont(...)` VIEW MODIFIER (bottom of this file), never through a
/// bare `Font`. The modifier reads `@Environment(\.dynamicTypeSize)`, which is what
/// makes scaling actually work:
///
///   • it gives SwiftUI a dependency to invalidate on, so text re-lays-out when the
///     size changes WHILE RUNNING (a global `UITraitCollection.current` read is
///     captured once and then frozen — the trap this replaced), and
///   • it honours in-app `.dynamicTypeSize(...)` overrides, which never touch
///     `UITraitCollection.current` at all.
///
/// Fixed-size text scales UNCAPPED by default; pass `maxSize` only for text inside
/// a fixed frame (the capture shutter, coverage ticks, a metric strip). A blanket
/// cap inverts the type hierarchy, because the text-style variants scale without
/// one.
///
/// There are deliberately NO fixed-size `Font`-returning helpers: a `Font` cannot
/// read the environment, so offering one would be offering a silently inert path.
/// The text-style variants (`guest(_:)`, `ui(_:)`, …) return `Font` and scale
/// natively — use those wherever a semantic style fits.

import SwiftUI
import UIKit

/// Which of the three Good Guest type roles a fixed-size line belongs to.
enum RSFontRole { case guest, display, ui, mono }

enum RSFont {

    // MARK: Guest voice — serif italic (the guest speaking)

    static func guest(_ style: Font.TextStyle = .body) -> Font {
        serif(style).italic()
    }

    /// Resolve a fixed point size for an ALREADY-KNOWN type size. Internal to the
    /// `.rsFont` modifier — call sites use the modifier so the environment (and
    /// therefore SwiftUI invalidation) is never bypassed.
    static func resolved(
        role: RSFontRole,
        size: CGFloat,
        weight: Font.Weight?,
        relativeTo: Font.TextStyle,
        maxSize: CGFloat?,
        typeSize: DynamicTypeSize
    ) -> Font {
        let traits = UITraitCollection(preferredContentSizeCategory: contentSizeCategory(typeSize))
        var points = UIFontMetrics(forTextStyle: uiTextStyle(relativeTo))
            .scaledValue(for: size, compatibleWith: traits)
        if let maxSize { points = min(points, maxSize) }

        let base: Font = switch role {
        case .guest:   .system(size: points, design: .serif)
        case .display: .system(size: points, design: .serif)
        case .ui:      .system(size: points, design: .default)
        case .mono:    .system(size: points, design: .monospaced)
        }
        let weighted = weight.map { base.weight($0) } ?? base
        return role == .guest ? weighted.italic() : weighted
    }

    // MARK: Display — serif upright (arrival titles)

    static func display(_ style: Font.TextStyle = .title) -> Font {
        serif(style)
    }

    // MARK: UI sans — buttons, labels, controls

    static func ui(_ style: Font.TextStyle = .body, weight: Font.Weight = .regular) -> Font {
        sans(style).weight(weight)
    }

    // MARK: Mono — machine data only

    static func mono(_ style: Font.TextStyle = .caption, weight: Font.Weight = .medium) -> Font {
        monospaced(style).weight(weight)
    }

    // MARK: - Face helpers (the bundling seam — change these three, nothing else)

    private static func serif(_ style: Font.TextStyle) -> Font {
        .system(style, design: .serif)
    }
    private static func sans(_ style: Font.TextStyle) -> Font {
        .system(style, design: .default)
    }
    private static func monospaced(_ style: Font.TextStyle) -> Font {
        .system(style, design: .monospaced)
    }
    // MARK: - Dynamic Type

    private static func uiTextStyle(_ style: Font.TextStyle) -> UIFont.TextStyle {
        switch style {
        case .largeTitle:  return .largeTitle
        case .title:       return .title1
        case .title2:      return .title2
        case .title3:      return .title3
        case .headline:    return .headline
        case .subheadline: return .subheadline
        case .body:        return .body
        case .callout:     return .callout
        case .footnote:    return .footnote
        case .caption:     return .caption1
        case .caption2:    return .caption2
        @unknown default:  return .body
        }
    }

    private static func contentSizeCategory(_ size: DynamicTypeSize) -> UIContentSizeCategory {
        switch size {
        case .xSmall:            return .extraSmall
        case .small:             return .small
        case .medium:            return .medium
        case .large:             return .large
        case .xLarge:            return .extraLarge
        case .xxLarge:           return .extraExtraLarge
        case .xxxLarge:          return .extraExtraExtraLarge
        case .accessibility1:    return .accessibilityMedium
        case .accessibility2:    return .accessibilityLarge
        case .accessibility3:    return .accessibilityExtraLarge
        case .accessibility4:    return .accessibilityExtraExtraLarge
        case .accessibility5:    return .accessibilityExtraExtraExtraLarge
        @unknown default:        return .large
        }
    }
}

// MARK: - The fixed-size application point

/// Applies a fixed-size Good Guest font that ACTUALLY scales, by resolving the
/// point size against `@Environment(\.dynamicTypeSize)`. See the Dynamic Type note
/// at the top of this file for why a plain `Font` cannot do this.
private struct RSScaledFont: ViewModifier {
    @Environment(\.dynamicTypeSize) private var typeSize

    let role: RSFontRole
    let size: CGFloat
    let weight: Font.Weight?
    let relativeTo: Font.TextStyle
    let maxSize: CGFloat?

    func body(content: Content) -> some View {
        content.font(RSFont.resolved(
            role: role, size: size, weight: weight,
            relativeTo: relativeTo, maxSize: maxSize, typeSize: typeSize
        ))
    }
}

extension View {
    /// Apply a fixed-size Good Guest font.
    ///
    /// - Parameter maxSize: optional ceiling in points, for text inside a FIXED
    ///   frame (the capture shutter, coverage ticks, a metric strip) where
    ///   unbounded growth would burst the control. Defaults to nil — body copy must
    ///   scale freely, and a blanket cap here inverted the type hierarchy at
    ///   accessibility sizes (capped serif hero rendering smaller than uncapped
    ///   sans support text, since the text-style variants scale without limit).
    func rsFont(
        _ role: RSFontRole,
        size: CGFloat,
        weight: Font.Weight? = nil,
        relativeTo: Font.TextStyle = .body,
        maxSize: CGFloat? = nil
    ) -> some View {
        modifier(RSScaledFont(
            role: role, size: size, weight: weight,
            relativeTo: relativeTo, maxSize: maxSize
        ))
    }
}
