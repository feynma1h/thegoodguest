/// The navigation bar's two titles, set in the language rather than the
/// system's: the large title in Newsreader Light (the design's `.lt`, 34pt,
/// tracked in), the inline title in Albert Sans semibold (`.navtitle`, 17pt).
///
/// Set once at launch through UIKit's appearance proxy, which is the only way
/// SwiftUI's NavigationStack takes a title face. The sizes are scaled for the
/// reader's text size at launch and held at the display tier, like every serif
/// title; a text size changed while the app runs reaches the bar on the next
/// launch, which is how appearance proxies work.
///
/// Read by: TheGoodGuestApp.

import SwiftUI
import UIKit

enum RSNavigationBar {

    static let largeTitleSize: CGFloat = 34
    static let inlineTitleSize: CGFloat = 17

    static func apply() {
        let ink = UIColor(Color.rsInk)
        let bar = UINavigationBar.appearance()
        bar.largeTitleTextAttributes = [
            .font: largeTitleFont(),
            .foregroundColor: ink,
            .kern: -0.022 * largeTitleSize,
        ]
        bar.titleTextAttributes = [
            .font: inlineTitleFont(),
            .foregroundColor: ink,
        ]
    }

    static func largeTitleFont(traits: UITraitCollection? = nil) -> UIFont {
        scaled(RSFont.uiFont(role: .display, size: largeTitleSize, weight: .light),
               style: .largeTitle, traits: traits)
    }

    static func inlineTitleFont(traits: UITraitCollection? = nil) -> UIFont {
        scaled(RSFont.uiFont(role: .ui, size: inlineTitleSize, weight: .semibold),
               style: .headline, traits: traits)
    }

    private static func scaled(_ font: UIFont, style: UIFont.TextStyle, traits: UITraitCollection?) -> UIFont {
        UIFontMetrics(forTextStyle: style).scaledFont(
            for: font,
            maximumPointSize: font.pointSize * RSTypeCap.display.rawValue,
            compatibleWith: traits
        )
    }
}
