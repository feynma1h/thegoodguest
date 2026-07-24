/// "I've got the room" — the peak moment (design spec §4, beat one). Fires on
/// Finish (once a coverage signal exists — task #13 — it can fire the instant
/// coverage is sufficient): a gold bloom, the checkmark
/// breathing once, the success haptic + the resolving chord. The single
/// unambiguously joyful beat in the app — earned, not decorative. Holds briefly,
/// then the review screen (§4, beat two) takes over.

import SwiftUI

struct GotTheRoomView: View {
    var onContinue: () -> Void = {}
    @State private var breathe = false

    var body: some View {
        ZStack {
            // Warm gold-lit darkness.
            RadialGradient(
                colors: [Color(rsHex: 0x3a2c17), Color(rsHex: 0x241a0d), Color.rsCaptureBase],
                center: .init(x: 0.5, y: 0.42), startRadius: 30, endRadius: 520
            )
            .ignoresSafeArea()

            // Gold bloom behind the mark.
            RadialGradient(
                colors: [Color.rsGold.opacity(0.22), .clear],
                center: .init(x: 0.5, y: 0.42), startRadius: 0, endRadius: 260
            )
            .ignoresSafeArea()

            VStack(spacing: 0) {
                ZStack {
                    Circle()
                        .fill(Color.rsGold)
                        .frame(width: 64, height: 64)
                        .shadow(color: Color.rsGold.opacity(0.6), radius: 40)
                    Image(systemName: "checkmark")
                        .font(.system(size: 28, weight: .semibold))
                        .foregroundStyle(Color(rsHex: 0x2a2114))
                }
                .scaleEffect(breathe ? 1.06 : 1.0)

                Text("I've got the room.")
                    .font(RSFont.display(size: 26))
                    .foregroundStyle(Color.rsOnDark)
                    .padding(.top, 26)

                // No coverage claim: the app has no coverage signal yet (task #13),
                // so the copy celebrates finishing the pass without asserting what
                // was or wasn't captured.
                GuestLine("That's the pass done — let's send it home, and I'll start making sense of it on your desk.",
                          size: 16, onDark: true, alignment: .center)
                    .padding(.horizontal, 34)
                    .padding(.top, 12)
            }
        }
        .onAppear {
            RSHaptics.fire(.gotTheRoom)
            RSSound.play(.enough)
            // One gentle settle (spec §4: "one gentle breathe"), not an infinite pulse.
            withAnimation(.easeOut(duration: 0.6)) { breathe = true }
            // Hold the moment, then move to review.
            DispatchQueue.main.asyncAfter(deadline: .now() + 1.8) { onContinue() }
        }
    }
}

#Preview {
    GotTheRoomView()
}
