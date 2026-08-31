/// The Good Guest palette, translated to SwiftUI (design spec §10, decision 0072).
///
/// These are brand constants — fixed warm values, not system-adaptive semantic
/// colors. The app is deliberately light-first (ink-on-parchment); capture and
/// terminal-failure screens choose the dark surfaces explicitly rather than
/// relying on the system light/dark switch. Every screen composes from these
/// tokens; no view hard-codes a hex.
///
/// THE RULE OF GOLD survives translation intact: `rsGold` is a LIGHT-SEMANTIC
/// indicator only — the mesh ink, the "enough"/ready moment, the doorway. It is
/// never a generic accent and never success/error. Sensor/tracking colors
/// (`rsSensorGood` etc.) sit *outside* the brand — they read as instrument
/// truth, not decoration.

import SwiftUI

extension Color {

    // MARK: Surfaces & ink (light chrome)

    /// Parchment — grouped background for light screens.
    static let rsBackground = Color(rsHex: 0xebe5df)
    /// Cream — cards, sheets, secondary fills.
    static let rsSurface = Color(rsHex: 0xf9f2ec)
    /// Ink — primary label; also the dark capture & failure surface base.
    static let rsInk = Color(rsHex: 0x282723)

    /// Muted ink for support copy (~70% ink on parchment).
    static let rsInkMuted = Color(rsHex: 0x282723).opacity(0.68)
    /// Faint ink for eyebrows / tertiary (~50%).
    static let rsInkFaint = Color(rsHex: 0x282723).opacity(0.5)
    /// Hairline separators.
    static let rsHairline = Color(rsHex: 0x282723).opacity(0.12)

    // MARK: Actions

    /// Rust — the `.tint`; primary buttons, the capture shutter. NOT a light cue.
    static let rsAction = Color(rsHex: 0xc04d3e)
    /// Rust, pressed/hover.
    static let rsActionPressed = Color(rsHex: 0xa54235)

    // MARK: Gold — LIGHT-SEMANTIC ONLY

    /// Gold — mesh ink, "enough", the doorway, Pro-capture. Never a plain accent,
    /// never success/error. See the rule of gold above.
    static let rsGold = Color(rsHex: 0xc9a25e)
    /// Gold, darkened for text on light surfaces (contrast).
    static let rsGoldInk = Color(rsHex: 0x8e6a2e)
    /// Warm highlight inside the gold family (mesh strokes, glow).
    static let rsGoldLight = Color(rsHex: 0xe7cfa0)

    // MARK: Dark capture surfaces

    /// Deepest bezel/notch black.
    static let rsBlack = Color(rsHex: 0x0e0d0b)
    /// Warm dark — capture backdrop base.
    static let rsCaptureBase = Color(rsHex: 0x181714)
    /// Warm dark — one step up (guidance sheet, panels on dark).
    static let rsCaptureRaised = Color(rsHex: 0x24231f)
    /// Warm cream text on dark surfaces.
    static let rsOnDark = Color(rsHex: 0xfbf5f2)

    // MARK: Sensor / tracking — OUTSIDE the brand (instrument truth)

    /// Tracking good — reads as sensor truth, not decoration.
    static let rsSensorGood = Color(rsHex: 0x7fc8a0)
    /// Slow down / re-find surface. (Shares the gold hue but is a sensor read.)
    static let rsSensorWarn = Color(rsHex: 0xc9a25e)
    /// Lost tracking / too dark.
    static let rsSensorLost = Color(rsHex: 0xc04d3e)

    // MARK: Positive affordance (the sign-in checklist ticks)

    /// Sage — the "your rooms stay" reassurance ticks. Muted, never a brand accent.
    static let rsAffirm = Color(rsHex: 0x7a8f5a)

    /// Build a Color from a 24-bit RGB hex literal (e.g. 0xebe5df). Internal to
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
