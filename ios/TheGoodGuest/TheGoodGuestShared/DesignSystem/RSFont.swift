/// The Good Guest type roles, translated to SwiftUI. Every screen reaches for
/// one of these — never a bare `.font(.system(...))`.
///
///   • GUEST voice   — the guest speaking. Newsreader *italic*.
///   • DISPLAY       — titles. Newsreader upright, light, set tight.
///   • UI            — Albert Sans: everything you read to operate the app,
///                     buttons, labels, status, body copy.
///   • MONO          — JetBrains Mono, for MEASUREMENTS only (4.40 × 3.60 m).
///                     Not for IDs, times, counts or labels.
///
/// The faces are the website's (approved 2026-11-10), bundled as variable
/// fonts under `TheGoodGuestShared/Fonts/` and registered by `RSFontFiles`.
/// The fixed-size path below sets the weight axis directly, and Newsreader's
/// optical-size axis to the size it is drawn at, so a 40pt title gets the
/// display cut and a 15pt line the text cut. The semantic variants use the
/// faces' named instances through `Font.custom(_:size:relativeTo:)`, which
/// scales with Dynamic Type exactly as the system styles did.
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

// MARK: - The ceiling

enum RSTypeSize {

    /// The largest Dynamic Type step the app renders at.
    ///
    /// WHY A CEILING EXISTS AT ALL. The tiers below stop titles, machine data
    /// and control labels, and measured across all 83 states they hit their
    /// target on every screen those cover — a median 1.73x denser at AX5, 29 of
    /// 30 under 2x. They could not touch the screens made of the guest's prose,
    /// which stayed at a median 3.93x, because reading text scaled without
    /// limit. On this app that is most of it: the desk, notes and the house are
    /// a title, an eyebrow and a paragraph, and at the top step the paragraph
    /// is the screen.
    ///
    /// WHY UNIFORM, AND NOT A READING TIER. A tier for prose would have to be
    /// tighter than the display tier above it to help, which inverts the
    /// hierarchy — a colophon set larger than the titles it sits under. One
    /// ceiling applied to the whole tree keeps every ratio between every pair
    /// of styles exactly where the default size has it, so the accessibility
    /// layout is the same layout, larger. Nothing is dropped, reordered or
    /// summarised to make it fit; that was the constraint.
    ///
    /// WHAT IT COSTS, plainly: someone who sets the top step asks for body text
    /// at 53pt and gets 33. That is a real reduction for the people the setting
    /// exists for, and it is the reason this is ONE constant rather than a
    /// number spread across call sites. Raising it is a one-line change, and
    /// `tools/ios_density_guard.py` will say what it costs in crowding.
    static let ceiling: DynamicTypeSize = .accessibility2
}

extension View {

    /// Hold the whole tree at `RSTypeSize.ceiling`.
    ///
    /// Applied ONCE, at the app's root, so no screen can forget it and no
    /// screen can disagree with another about how large is too large.
    func rsTypeCeiling() -> some View {
        dynamicTypeSize(...RSTypeSize.ceiling)
    }
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

    // MARK: Guest voice — Newsreader italic (the guest speaking)

    static func guest(_ style: Font.TextStyle = .body) -> Font {
        .custom(Face.serifItalic(.regular), size: baseSize(style), relativeTo: style)
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
        return Font(uiFont(role: role, size: points, weight: weight))
    }

    /// The face for a role at an exact point size, with its variation axes set.
    ///
    /// Display defaults to Light, which is how the language sets titles; the
    /// guest and the interface default to Regular, measurements to Medium.
    static func uiFont(role: RSFontRole, size: CGFloat, weight: Font.Weight?) -> UIFont {
        let weight = weight ?? defaultWeight(role)
        switch role {
        case .guest:
            return Face.variable(Face.serifItalicDefault, size: size,
                                 weight: Face.axisWeight(weight, range: 200...800),
                                 opticalSize: size)
        case .display:
            return Face.variable(Face.serifDefault, size: size,
                                 weight: Face.axisWeight(weight, range: 200...800),
                                 opticalSize: size)
        case .ui:
            return Face.variable(Face.sansDefault, size: size,
                                 weight: Face.axisWeight(weight, range: 100...900))
        case .mono:
            return Face.variable(Face.monoDefault, size: size,
                                 weight: Face.axisWeight(weight, range: 100...800))
        }
    }

    /// A role's weight when the call site names none.
    static func defaultWeight(_ role: RSFontRole) -> Font.Weight {
        switch role {
        case .guest, .ui: .regular
        case .display:    .light
        case .mono:       .medium
        }
    }

    /// The weight a style takes with Bold Text on: a step heavier, as the
    /// system's own faces go (Regular to Semibold, Semibold to Bold). The
    /// bundled faces are variable, so every step exists. Without this the
    /// setting changed nothing in the app: its faces are set at explicit
    /// weights, and only the system's fonts follow the setting by themselves.
    static func bolder(_ weight: Font.Weight) -> Font.Weight {
        switch weight {
        case .ultraLight, .thin: .light
        case .light:             .medium
        case .medium, .semibold: .bold
        case .bold:              .heavy
        case .heavy, .black:     .black
        default:                 .semibold
        }
    }

    // MARK: Display — Newsreader upright (titles)

    static func display(_ style: Font.TextStyle = .title) -> Font {
        .custom(Face.serif(.light), size: baseSize(style), relativeTo: style)
    }

    // MARK: UI sans — Albert Sans, everything you operate

    static func ui(_ style: Font.TextStyle = .body, weight: Font.Weight = .regular) -> Font {
        .custom(Face.sans(weight), size: baseSize(style), relativeTo: style)
    }

    // MARK: Mono — JetBrains Mono, measurements only

    static func mono(_ style: Font.TextStyle = .caption, weight: Font.Weight = .medium) -> Font {
        .custom(Face.mono(weight), size: baseSize(style), relativeTo: style)
    }

    // MARK: - Faces

    /// PostScript names of the bundled faces' named instances, and the
    /// variable-axis builder the fixed-size path uses. The names are the ones
    /// Core Text reports for the files in `Fonts/`; FontRegistrationTests pins
    /// that every one of them resolves.
    enum Face {
        static let serifDefault = "Newsreader16pt-Regular"
        static let serifItalicDefault = "Newsreader16pt-Italic"
        static let sansDefault = "AlbertSans-Regular"
        static let monoDefault = "JetBrainsMono-Regular"

        static func serif(_ weight: Font.Weight) -> String {
            switch weight {
            case .ultraLight, .thin: return "NewsreaderRoman-ExtraLight"
            case .light:             return "NewsreaderRoman-Light"
            case .medium:            return "NewsreaderRoman-Medium"
            case .semibold:          return "NewsreaderRoman-SemiBold"
            case .bold:              return "NewsreaderRoman-Bold"
            case .heavy, .black:     return "NewsreaderRoman-ExtraBold"
            default:                 return serifDefault
            }
        }

        static func serifItalic(_ weight: Font.Weight) -> String {
            switch weight {
            case .ultraLight, .thin: return "NewsreaderItalic-ExtraLight"
            case .light:             return "NewsreaderItalic-Light"
            case .medium:            return "NewsreaderItalic-Medium"
            case .semibold:          return "NewsreaderItalic-SemiBold"
            case .bold:              return "NewsreaderItalic-Bold"
            case .heavy, .black:     return "NewsreaderItalic-ExtraBold"
            default:                 return serifItalicDefault
            }
        }

        static func sans(_ weight: Font.Weight) -> String {
            switch weight {
            case .ultraLight: return "AlbertSansRoman-ExtraLight"
            case .thin:       return "AlbertSansRoman-Thin"
            case .light:      return "AlbertSansRoman-Light"
            case .medium:     return "AlbertSansRoman-Medium"
            case .semibold:   return "AlbertSansRoman-SemiBold"
            case .bold:       return "AlbertSansRoman-Bold"
            case .heavy:      return "AlbertSansRoman-ExtraBold"
            case .black:      return "AlbertSansRoman-Black"
            default:          return sansDefault
            }
        }

        static func mono(_ weight: Font.Weight) -> String {
            switch weight {
            case .ultraLight: return "JetBrainsMonoRoman-ExtraLight"
            case .thin:       return "JetBrainsMonoRoman-Thin"
            case .light:      return "JetBrainsMonoRoman-Light"
            case .regular:    return monoDefault
            case .bold:       return "JetBrainsMonoRoman-Bold"
            case .heavy, .black: return "JetBrainsMonoRoman-ExtraBold"
            default:          return "JetBrainsMonoRoman-Medium"
            }
        }

        /// The OpenType weight a SwiftUI weight stands for, inside a face's range.
        static func axisWeight(_ weight: Font.Weight, range: ClosedRange<CGFloat>) -> CGFloat {
            let value: CGFloat = switch weight {
            case .ultraLight: 200
            case .thin:       100
            case .light:      300
            case .medium:     500
            case .semibold:   600
            case .bold:       700
            case .heavy:      800
            case .black:      900
            default:          400
            }
            return min(max(value, range.lowerBound), range.upperBound)
        }

        private static let wght = NSNumber(value: 0x7767_6874 as UInt32)
        private static let opsz = NSNumber(value: 0x6F70_737A as UInt32)

        /// A variable face at `size`, with the weight axis set and — for a face
        /// that has one — the optical-size axis matched to the size it is drawn
        /// at (Newsreader's runs 6 to 72). An unregistered face resolves to the
        /// system font rather than crashing; FontRegistrationTests is what
        /// keeps that from shipping.
        static func variable(_ name: String, size: CGFloat, weight: CGFloat, opticalSize: CGFloat? = nil) -> UIFont {
            var axes: [NSNumber: CGFloat] = [wght: weight]
            if let opticalSize { axes[opsz] = min(max(opticalSize, 6), 72) }
            let descriptor = UIFontDescriptor(fontAttributes: [
                .name: name,
                UIFontDescriptor.AttributeName(rawValue: kCTFontVariationAttribute as String): axes,
            ])
            return UIFont(descriptor: descriptor, size: size)
        }
    }

    /// The size each text style starts from at the default Dynamic Type step,
    /// so `Font.custom(_:size:relativeTo:)` scales from the same place the
    /// system styles did.
    static func baseSize(_ style: Font.TextStyle) -> CGFloat {
        switch style {
        case .largeTitle:  return 34
        case .title:       return 28
        case .title2:      return 22
        case .title3:      return 20
        case .headline:    return 17
        case .body:        return 17
        case .callout:     return 16
        case .subheadline: return 15
        case .footnote:    return 13
        case .caption:     return 12
        case .caption2:    return 11
        @unknown default:  return 17
        }
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
    /// Bold Text, as SwiftUI reports it.
    @Environment(\.legibilityWeight) private var legibilityWeight

    let role: RSFontRole
    let size: CGFloat
    let weight: Font.Weight?
    let relativeTo: Font.TextStyle
    let maxSize: CGFloat?

    func body(content: Content) -> some View {
        let weight = legibilityWeight == .bold
            ? RSFont.bolder(weight ?? RSFont.defaultWeight(role))
            : weight
        return content.font(RSFont.resolved(
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
