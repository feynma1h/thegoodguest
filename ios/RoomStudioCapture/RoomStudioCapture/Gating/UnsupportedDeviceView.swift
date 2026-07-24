/// Shown when the device has no LiDAR (decision 0072 — LiDAR-only). Honest, never
/// a nag to upgrade: the guest explains it would rather not pretend to see a room
/// it can't measure truly. No CTA — there's nothing to do here but come back on a
/// capable device — so the screen stays calm and short.

import SwiftUI

struct UnsupportedDeviceView: View {
    var body: some View {
        VStack(spacing: 0) {
            Spacer()

            Wordmark()

            Image(systemName: "cube.transparent")
                .font(.system(size: 34, weight: .regular))
                .foregroundStyle(Color.rsGoldInk)
                .padding(.top, 40)

            Text("This one needs a depth camera.")
                .font(RSFont.display(size: 24))
                .foregroundStyle(Color.rsInk)
                .multilineTextAlignment(.center)
                .fixedSize(horizontal: false, vertical: true)
                .padding(.top, 22)

            GuestLine("I measure your room with a LiDAR sensor — the one the Pro iPhones and iPad Pros carry. On this device I can't see it truly, and I'd rather not pretend. Come find me on a LiDAR phone or iPad, and we'll begin.",
                      size: 16, alignment: .center)
                .padding(.horizontal, 34)
                .padding(.top, 14)

            Spacer()
            Spacer()
        }
        .padding(.horizontal, 26)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .rsParchmentScreen()
    }
}

#Preview {
    UnsupportedDeviceView()
}
