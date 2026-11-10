/// The ground light screens sit on.
///
/// A flat colour, deliberately: the parchment gradient it replaces was one of
/// the cream era's signatures, and the website's ground is flat too. Dusk
/// screens set `rsDusk` themselves rather than through this.
///
/// Read by every light screen through `rsGroundScreen()` and
/// `RSScrollableScreen`.

import SwiftUI

struct GroundBackground: View {
    var body: some View {
        Color.rsGround.ignoresSafeArea()
    }
}

extension View {
    /// Put this screen on the ground, edge to edge.
    func rsGroundScreen() -> some View {
        ZStack {
            GroundBackground()
            self
        }
    }
}

/// A screen whose content scrolls when it outgrows the frame (accessibility
/// sizes) and otherwise fills it, so a `Spacer` can still push content apart.
struct RSScrollableScreen: ViewModifier {
    var background: Color?
    var transparent: Bool = false

    func body(content: Content) -> some View {
        GeometryReader { geo in
            ScrollView {
                content
                    .frame(minHeight: geo.size.height)
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background {
            if transparent {
                Color.clear
            } else if let background {
                background.ignoresSafeArea()
            } else {
                GroundBackground()
            }
        }
    }
}
