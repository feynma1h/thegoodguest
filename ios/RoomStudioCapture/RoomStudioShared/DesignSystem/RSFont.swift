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
/// SCALING TIERS. Reading text scales without limit — body copy, the guest's
/// lines, status sentences, instructions. Everything that is NOT read as prose
/// carries a ceiling, expressed as a multiple of its own base size by
/// `RSTypeCap`: titles signal hierarchy rather than being read, machine data
/// keeps its shape, and a control's label must not burst the control.
///
/// A BLANKET cap is still wrong and always was: the semantic text-style
/// variants (`ui(_:)`, `guest(_:)`) scale without one, so capping the fixed
/// sizes alone once left a capped serif hero rendering smaller than the
/// uncapped sans support text beneath it. What makes tiers safe where a blanket
/// cap was not is that the tier is chosen by what the text DOES, and every
/// control label was moved onto the fixed-size path at the same time — so the
/// two halves of a hierarchy are never on opposite sides of the ceiling.
///
/// `maxSize` remains, in absolute points, for text inside a genuinely fixed
/// frame (the capture shutter, the coverage ticks, a metric strip). Where both
/// are given the tighter wins: those frames were measured, and a tier is a
/// house rule rather than a measurement of that control.
///
/// There are deliberately NO fixed-size `Font`-returning helpers: a `Font` cannot
/// read the environment, so offering one would be offering a silently inert path.
/// The text-style variants (`guest(_:)`, `ui(_:)`, …) return `Font` and scale
/// natively — use those wherever a semantic style fits.

import SwiftUI
import UIKit

/// Which of the three Good Guest type roles a fixed-size line belongs to.
enum RSFontRole { case guest, display, ui, mono }

/// How far a line is allowed to grow, as a multiple of its own base size.
///
/// Stated once, here, because the whole value of a tier is that every screen
/// gets the same answer — the previous per-call `maxSize` ceilings were each
/// correct for their own control and collectively said nothing.
///
/// There is deliberately NO case for reading text. Body copy, the guest's
/// voice and every instruction scale without limit, and the way to say so is
/// to pass no cap at all rather than to pass a large one.
///
/// Nor is there one for control labels: those are set from semantic styles,
/// which this mechanism cannot reach, and are clamped by `rsControlLabel()`
/// below instead. See that comment for why the obvious alternative — moving
/// them onto the fixed-size path — is worse.
enum RSTypeCap: CGFloat {
    /// Serif titles and screen headers. They mark where you are; they are not
    /// read at length.
    case display = 1.4
    /// Machine data — IDs, elapsed clocks, capture metrics, the status
    /// eyebrows. Keeps its uppercase and its letterspacing at every size.
    case mono = 1.6
}

// MARK: - The control tier

extension View {

    /// The control tier: a label may grow to about 1.35x and no further.
    ///
    /// A DYNAMIC TYPE CLAMP, not a point ceiling, and the difference is not
    /// cosmetic. Every filled button in the app sets its label from a SEMANTIC
    /// style (`RSFont.ui(.headline, weight: .semibold)`), and `maxSize` only
    /// reaches the fixed-size path — so capping these by that mechanism meant
    /// rewriting them as `.rsFont(.ui, size: 17, relativeTo: .headline)`.
    /// Measured, that is not the same font: a text style carries its own line
    /// height, a bare point size does not, and the primary button came out
    /// visibly SHORTER at the default text size. The brief's own rule is that
    /// buttons keep their shape, and the fix for the accessibility sizes had
    /// broken it at the default one.
    ///
    /// Clamping instead changes nothing at or below `xxxLarge` — verified
    /// pixel-identical — and above it holds the label where `xxxLarge` left it.
    /// That lands at exactly 1.35x for `.headline` (17 -> 23pt), 1.38x for
    /// `.callout` and 1.46x for `.footnote`: the tier is quantised to Dynamic
    /// Type's own steps rather than exact, which is the price of not
    /// substituting the font.
    ///
    /// It clamps a SUBTREE, so it belongs on the label and nowhere wider — put
    /// it on a screen and the screen's reading text stops scaling with it.
    func rsControlLabel() -> some View {
        dynamicTypeSize(...DynamicTypeSize.xxxLarge)
    }
}

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
        maxSize: CGFloat? = nil,
        cap: RSTypeCap? = nil
    ) -> some View {
        // The tighter of the two wins. A `maxSize` was measured against a
        // specific frame; a tier is a house rule. Where a control already had
        // a tighter ceiling than its tier, that ceiling was load-bearing.
        let tier = cap.map { size * $0.rawValue }
        let ceiling: CGFloat? = switch (maxSize, tier) {
        case let (m?, t?): min(m, t)
        case let (m?, nil): m
        case let (nil, t?): t
        case (nil, nil): nil
        }
        return modifier(RSScaledFont(
            role: role, size: size, weight: weight,
            relativeTo: relativeTo, maxSize: ceiling
        ))
    }
}
