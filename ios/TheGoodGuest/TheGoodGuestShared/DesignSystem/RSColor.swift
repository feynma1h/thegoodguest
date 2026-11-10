/// The Good Guest palette, translated to SwiftUI.
///
/// The website's language, approved 2026-11-10: a daylight ground with slate
/// ink for everything you read, dusk only where the camera or the night is,
/// terracotta only in the mark and in measurements, lamplight only as light.
/// Cream, parchment and warm-brown ink are retired (they were decision 0057's).
///
/// These are brand constants, not system-adaptive colours: each screen picks
/// light or dusk for itself, and the app does not follow the phone's Dark Mode
/// (operator ruling, 2026-11-10). Every screen composes from these tokens; no
/// view hard-codes a hex.
///
/// THE TWO RULES that survive every screen:
///   • Terracotta (`rsTerracotta`) is the mark, the wordmark's rings and
///     measurement annotations. It never fills a button and never colours a
///     sentence. Text-sized measurements use `rsTerracottaText`.
///   • Lamplight (`rsLamp`) is light: a lit or active indicator on dusk. It is
///     never an accent on a light screen and never means success.
///
/// Read by every screen and by the Live Activity. `tools/test_gen_mark.py`
/// pins `rsTerracotta`, `rsGround` and `rsInk` to the app icon's ink and tiles.

import SwiftUI

extension Color {

    // MARK: Light screens

    /// The ground every light screen sits on.
    static let rsGround = Color(rsHex: 0xf5f6f8)
    /// Cards, sheets and lists on the ground.
    static let rsSurface = Color(rsHex: 0xffffff)
    /// Stages and tiles set into a surface: where a room or a plan is drawn.
    static let rsInset = Color(rsHex: 0xe4e9ed)
    /// Ink: titles, body, the filled button.
    static let rsInk = Color(rsHex: 0x121a23)
    /// Secondary ink. 6.9:1 on the ground, so it is allowed for body text.
    static let rsInk2 = Color(rsHex: 0x4a5664)
    /// Tertiary ink, for LARGE text only (3.3:1 on the ground): never a caption.
    static let rsInk3 = Color(rsHex: 0x808b98)
    /// Hairlines between rows.
    static let rsHairline = Color(rsHex: 0x121a23).opacity(0.10)

    // MARK: Terracotta — the mark and measurements only

    /// The brand ink: the mark, the wordmark's rings, measurement annotations.
    static let rsTerracotta = Color(rsHex: 0xc04d3e)
    /// Terracotta at text size (measurements set in mono), for contrast.
    static let rsTerracottaText = Color(rsHex: 0xa54235)

    // MARK: Dusk screens — the camera, the room by lamplight

    static let rsDusk = Color(rsHex: 0x0d141c)
    static let rsRaised = Color(rsHex: 0x121b25)
    static let rsRaised2 = Color(rsHex: 0x18222e)
    /// Text on dusk.
    static let rsOnDusk = Color(rsHex: 0xeef2f6)
    /// Secondary text on dusk (8.6:1).
    static let rsOnDusk2 = Color(rsHex: 0xa7b2bf)

    // MARK: Lamplight — light only

    static let rsLamp = Color(rsHex: 0xf0b26a)

    /// Build a Color from a 24-bit RGB hex literal (e.g. 0xf5f6f8). Internal to
    /// the design system — screens use the named tokens above, not raw hex.
    init(rsHex hex: UInt32) {
        self.init(
            .sRGB,
            red:   Double((hex >> 16) & 0xff) / 255.0,
            green: Double((hex >> 8) & 0xff) / 255.0,
            blue:  Double(hex & 0xff) / 255.0,
            opacity: 1.0
        )
    }
}
