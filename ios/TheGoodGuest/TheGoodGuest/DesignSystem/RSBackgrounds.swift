/// The ground light screens sit on.
///
/// A flat colour, deliberately: the parchment gradient it replaces was one of
/// the cream era's signatures, and the website's ground is flat too. Dusk
/// screens set `rsDusk` themselves rather than through this.
///
/// Read by every light screen, as a background or through `rsGroundScreen()`.

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
