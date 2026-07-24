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
/// DYNAMIC TYPE: the fixed-size variants scale via UIFontMetrics — `Font.system(
/// size:)` alone is inert, which would leave nearly every line in this app
/// (guest voice, arrival titles, mono metrics) ignoring the user's text size.

import SwiftUI
import UIKit

enum RSFont {

    // MARK: Guest voice — serif italic (the guest speaking)

    static func guest(_ style: Font.TextStyle = .body) -> Font {
        serif(style).italic()
    }

    /// Fixed-size guest line (scales with Dynamic Type relative to `relativeTo`).
    static func guest(size: CGFloat, relativeTo: Font.TextStyle = .body) -> Font {
        serif(size: size, relativeTo: relativeTo).italic()
    }

    // MARK: Display — serif upright (arrival titles)

    static func display(_ style: Font.TextStyle = .title) -> Font {
        serif(style)
    }

    static func display(size: CGFloat, relativeTo: Font.TextStyle = .largeTitle) -> Font {
        serif(size: size, relativeTo: relativeTo)
    }

    // MARK: UI sans — buttons, labels, controls

    static func ui(_ style: Font.TextStyle = .body, weight: Font.Weight = .regular) -> Font {
        sans(style).weight(weight)
    }

    static func ui(size: CGFloat, weight: Font.Weight = .regular, relativeTo: Font.TextStyle = .body) -> Font {
        sans(size: size, relativeTo: relativeTo).weight(weight)
    }

    // MARK: Mono — machine data only

    static func mono(_ style: Font.TextStyle = .caption, weight: Font.Weight = .medium) -> Font {
        monospaced(style).weight(weight)
    }

    static func mono(size: CGFloat, weight: Font.Weight = .medium, relativeTo: Font.TextStyle = .caption) -> Font {
        monospaced(size: size, relativeTo: relativeTo).weight(weight)
    }

    // MARK: - Face helpers (the bundling seam — change these three, nothing else)

    private static func serif(_ style: Font.TextStyle) -> Font {
        .system(style, design: .serif)
    }
    private static func serif(size: CGFloat, relativeTo: Font.TextStyle) -> Font {
        .system(size: scaled(size, relativeTo: relativeTo), design: .serif)
    }

    private static func sans(_ style: Font.TextStyle) -> Font {
        .system(style, design: .default)
    }
    private static func sans(size: CGFloat, relativeTo: Font.TextStyle) -> Font {
        .system(size: scaled(size, relativeTo: relativeTo), design: .default)
    }

    private static func monospaced(_ style: Font.TextStyle) -> Font {
        .system(style, design: .monospaced)
    }
    private static func monospaced(size: CGFloat, relativeTo: Font.TextStyle) -> Font {
        .system(size: scaled(size, relativeTo: relativeTo), design: .monospaced)
    }

    // MARK: - Dynamic Type

    /// Scale a fixed point size against the user's text-size setting.
    ///
    /// `Font.system(size:)` is Dynamic Type–INERT, so every fixed-size call site
    /// (the guest voice, arrival titles, mono metrics — the majority of this app's
    /// text) would otherwise ignore the user's chosen size entirely. UIFontMetrics
    /// reproduces what `Font.custom(_:size:relativeTo:)` will do for free once the
    /// branded faces are bundled, so behaviour stays consistent across that swap.
    ///
    /// Read at body-evaluation time: SwiftUI re-evaluates on a size-category
    /// change, so the value tracks the setting without an explicit environment read.
    private static func scaled(_ size: CGFloat, relativeTo style: Font.TextStyle) -> CGFloat {
        UIFontMetrics(forTextStyle: uiTextStyle(style)).scaledValue(for: size)
    }

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
}
