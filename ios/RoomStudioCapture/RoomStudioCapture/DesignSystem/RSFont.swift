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
/// registered, change ONLY the three private helpers at the bottom of this file
/// to `Font.custom(_:size:relativeTo:)`; every call site keeps working.

import SwiftUI

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
        // System fixed sizes do NOT scale with Dynamic Type; `relativeTo` is
        // retained so the call sites are ready for the Font.custom swap, where it
        // becomes live. Prefer the text-style variants for scaling body copy.
        .system(size: size, design: .serif)
    }

    private static func sans(_ style: Font.TextStyle) -> Font {
        .system(style, design: .default)
    }
    private static func sans(size: CGFloat, relativeTo: Font.TextStyle) -> Font {
        .system(size: size, design: .default)
    }

    private static func monospaced(_ style: Font.TextStyle) -> Font {
        .system(style, design: .monospaced)
    }
    private static func monospaced(size: CGFloat, relativeTo: Font.TextStyle) -> Font {
        .system(size: size, design: .monospaced)
    }
}
