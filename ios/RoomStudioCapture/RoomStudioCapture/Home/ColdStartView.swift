/// Cold start (design spec §1). Shown for ~1s on first launch while the anonymous
/// identity is minted silently in the background — no account screen, no
/// permission prompt (permissions are asked in context at capture time, §2).
/// One warm line: the app setting a place for you.

import SwiftUI

struct ColdStartView: View {
    @State private var spin = false

    var body: some View {
        VStack(spacing: 0) {
            Spacer()

            WordmarkGlyph(size: 44)
            Text(RSBrand.name)
                .font(RSFont.display(size: 20).weight(.medium))
                .foregroundStyle(Color.rsInk)
                .padding(.top, 16)

            // A quiet rust arc turning over a faint track — the app is getting ready.
            Circle()
                .trim(from: 0, to: 0.22)
                .stroke(Color.rsAction, style: StrokeStyle(lineWidth: 2.5, lineCap: .round))
                .background(Circle().stroke(Color.rsInk.opacity(0.15), lineWidth: 2.5))
                .frame(width: 26, height: 26)
                .rotationEffect(.degrees(spin ? 360 : 0))
                .padding(.top, 40)
                .onAppear {
                    withAnimation(.linear(duration: 1.1).repeatForever(autoreverses: false)) {
                        spin = true
                    }
                }

            GuestLine("Setting a place for you…", alignment: .center)
                .padding(.top, 24)

            Spacer()
        }
        .frame(maxWidth: .infinity)
        .rsParchmentScreen()
    }
}

#Preview {
    ColdStartView()
}
