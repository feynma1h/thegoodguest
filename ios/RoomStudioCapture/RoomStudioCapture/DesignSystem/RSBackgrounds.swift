/// Shared screen backdrops (design spec §1–§9). The warm parchment gradient sits
/// behind every light chrome screen (home, review, analyzing, profile, history);
/// the dark capture/doorway radials are bespoke and live with their screens.
/// Factored here so the warm base reads identically everywhere.

import SwiftUI

/// The light-screen backdrop — a soft warm parchment gradient. Drop into a ZStack
/// behind screen content.
struct ParchmentBackground: View {
    var body: some View {
        LinearGradient(
            colors: [Color(rsHex: 0xf2e9d7), Color(rsHex: 0xe7ddc7)],
            startPoint: .top,
            endPoint: .bottom
        )
        .ignoresSafeArea()
    }
}

extension View {
    /// Place the parchment gradient behind this view, full-bleed.
    func rsParchmentScreen() -> some View {
        ZStack {
            ParchmentBackground()
            self
        }
    }
}


/// Makes a fixed-layout screen scrollable so accessibility text sizes can never
/// push content (or its only action) off-screen unrecoverably. `background` nil
/// uses the parchment treatment.
struct RSScrollableScreen: ViewModifier {
    var background: Color?
    /// True when the caller already paints its own backdrop (the doorway's gradient).
    var transparent: Bool = false

    func body(content: Content) -> some View {
        // GeometryReader, not UIScreen.main: the container is the honest quantity.
        // A device-screen constant is wrong by the safe-area/chrome inset on every
        // device (measurably ~24pt here, ~100pt on an SE), is unrelated to the window
        // in landscape or iPad Split View, and UIScreen.main is deprecated.
        GeometryReader { geo in
            ScrollView {
                content
                    // Fill the container when content is short, so Spacer()-based
                    // vertical centring still reads as designed at normal text sizes.
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
                ParchmentBackground().ignoresSafeArea()
            }
        }
    }
}
