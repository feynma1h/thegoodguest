/// The doorway — the phone's last act (design spec §6). Not a toast, not an
/// auto-redirect: a held threshold that treats the reveal as worth arriving to.
/// The reveal itself never fires on the phone; the phone opens the door and steps
/// back. A literal lit doorway, gold light spilling from the room beyond.
///
/// On appear: success haptic + a soft wooden knock; the doorway light blooms up
/// over ~1.2s (Reduce Motion → a crossfade instead). The CTA is gold — the
/// light-semantic peak of the whole app. It NEVER auto-navigates: the user
/// chooses to step through.
///
/// Handoff transport (universal link to the web, same signed-in identity) is
/// enrollment/entitlement-gated (associated-domains) — `onStepThrough` is the
/// seam; wire the real link when the gate clears (decision 0072).

import SwiftUI

struct DoorwayView: View {
    var onStepThrough: () -> Void = {}

    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var bloom = false

    var body: some View {
        ZStack {
            // Warm gold-lit darkness.
            RadialGradient(
                colors: [Color(rsHex: 0x4a3a24), Color(rsHex: 0x2e2213), Color.rsCaptureBase],
                center: .init(x: 0.5, y: 0.34), startRadius: 20, endRadius: 560
            )
            .ignoresSafeArea()

            doorway
                .opacity(bloom ? 1 : 0)
                .scaleEffect(reduceMotion ? 1 : (bloom ? 1 : 0.9), anchor: .center)

            VStack(spacing: 0) {
                Spacer()
                Text("Your room is ready.")
                    .font(RSFont.display(size: 27))
                    .foregroundStyle(Color.rsOnDark)
                    .multilineTextAlignment(.center)

                GuestLine("I've understood it — and I think you'll want to see it properly. It's waiting on your desk, where there's room to look around.",
                          size: 16, onDark: true, alignment: .center)
                    .padding(.horizontal, 30)
                    .padding(.top, 12)

                Button(action: onStepThrough) {
                    HStack(spacing: 9) {
                        Text("Step into it on the web")
                        Image(systemName: "arrow.right")
                            .font(.system(size: 15, weight: .semibold))
                    }
                }
                .buttonStyle(RSGoldButtonStyle())
                .padding(.top, 26)

                Text("Opens your desk in the browser · you're already signed in there")
                    .font(RSFont.ui(.footnote))
                    .foregroundStyle(Color.rsOnDark.opacity(0.6))
                    .multilineTextAlignment(.center)
                    .padding(.top, 14)
            }
            .padding(.horizontal, 30)
            .padding(.bottom, 20)
        }
        .onAppear {
            RSHaptics.fire(.roomReady)
            RSSound.play(.readyKnock)
            if reduceMotion {
                bloom = true
            } else {
                withAnimation(.easeOut(duration: 1.2)) { bloom = true }
            }
        }
    }

    /// The lit doorway — a top-rounded portal with gold light spilling out.
    private var doorway: some View {
        ZStack {
            UnevenRoundedRectangle(topLeadingRadius: 75, bottomLeadingRadius: 8,
                                   bottomTrailingRadius: 8, topTrailingRadius: 75,
                                   style: .continuous)
                .fill(LinearGradient(colors: [Color.rsGold.opacity(0.55), Color.rsGoldLight.opacity(0.15)],
                                     startPoint: .top, endPoint: .bottom))
                .frame(width: 150, height: 250)
                .overlay(
                    UnevenRoundedRectangle(topLeadingRadius: 75, bottomLeadingRadius: 8,
                                           bottomTrailingRadius: 8, topTrailingRadius: 75,
                                           style: .continuous)
                        .stroke(Color.rsGoldLight.opacity(0.4), lineWidth: 1)
                )
                .shadow(color: Color.rsGold.opacity(0.45), radius: 70)
            // Inner light core.
            UnevenRoundedRectangle(topLeadingRadius: 60, bottomLeadingRadius: 6,
                                   bottomTrailingRadius: 6, topTrailingRadius: 60,
                                   style: .continuous)
                .fill(RadialGradient(colors: [Color.rsSurface.opacity(0.5), Color.rsGold.opacity(0.05)],
                                     center: .init(x: 0.5, y: 0.3), startRadius: 4, endRadius: 160))
                .frame(width: 120, height: 230)
        }
        .offset(y: -120)
    }
}

#Preview {
    DoorwayView()
}
