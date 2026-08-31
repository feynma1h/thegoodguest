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
///
/// `onScanAnother` is NOT transport-gated and must exist now: without a way back,
/// a successful capture is a dead end (the poller sits on .succeeded, so nothing
/// re-enables capture) and the only escape is force-quitting the app.
///
/// `signedIntoWeb` gates the "you're already signed in there" line: it is only
/// true once the user has linked Sign in with Apple (decision 0051). An
/// anonymous-only user is NOT signed in on the web (anon UIDs don't carry across
/// devices), so the claim must not ship for them.

import SwiftUI

struct DoorwayView: View {
    var onStepThrough: () -> Void = {}
    var onScanAnother: () -> Void = {}
    /// Plain way out. Without it the only control (once the web CTA is hidden) was
    /// "Scan another room", which drops straight into live capture — the user who
    /// just wants to put the phone down had to start a scan.
    var onDone: () -> Void = {}
    var signedIntoWeb: Bool = false
    /// False when no web origin is configured yet — the CTA and its "opens your
    /// desk in the browser" caption are then hidden rather than shown as a control
    /// that does nothing. "Scan another room" remains, so the screen still has a way out.
    var canOpenWeb: Bool = true

    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var bloom = false

    var body: some View {
        ZStack {
            // Warm gold-lit darkness.
            RadialGradient(
                colors: [Color(rsHex: 0x3f3d35), Color(rsHex: 0x26241f), Color.rsCaptureBase],
                center: .init(x: 0.5, y: 0.34), startRadius: 20, endRadius: 560
            )
            .ignoresSafeArea()

            doorway
                .opacity(bloom ? 1 : 0)
                .scaleEffect(reduceMotion ? 1 : (bloom ? 1 : 0.9), anchor: .center)

            VStack(spacing: 0) {
                Spacer()
                Text("Your room is ready.")
                    .rsFont(.display, size: 27, cap: .display)
                    .foregroundStyle(Color.rsOnDark)
                    .multilineTextAlignment(.center)

                GuestLine("I've understood it — and I think you'll want to see it properly. It's waiting on your desk, where there's room to look around.",
                          size: 16, onDark: true, alignment: .center)
                    .padding(.horizontal, 30)
                    .padding(.top, 12)

                if canOpenWeb {
                    Button(action: onStepThrough) {
                        HStack(spacing: 9) {
                            Text("Step into it on the web")
                            Image(systemName: "arrow.right")
                                .font(.system(size: 15, weight: .semibold))
                        }
                    }
                    .buttonStyle(RSGoldButtonStyle())
                    .padding(.top, 26)

                    Text(signedIntoWeb
                         ? "Opens your desk in the browser · you're already signed in there"
                         : "Opens your desk in the browser")
                        .font(RSFont.ui(.footnote))
                        .foregroundStyle(Color.rsOnDark.opacity(0.6))
                        .multilineTextAlignment(.center)
                        .padding(.top, 14)
                } else {
                    // Same rule as the CTA caption: an anonymous UID doesn't carry
                    // across devices, so for an unlinked user there is no computer
                    // where this room exists. Point at sign-in instead of promising.
                    Text(signedIntoWeb
                         ? "Open it on your computer — it's waiting there whenever you are."
                         : "Sign in on this phone and it'll be waiting on your computer too.")
                        .font(RSFont.ui(.footnote))
                        .foregroundStyle(Color.rsOnDark.opacity(0.6))
                        .multilineTextAlignment(.center)
                        .padding(.top, 26)
                }

                Button(action: onScanAnother) {
                    Text("Scan another room")
                        .font(RSFont.ui(.subheadline, weight: .medium))
                        .foregroundStyle(Color.rsOnDark.opacity(0.85))
                }
                .padding(.top, 22)

                Button(action: onDone) {
                    Text("Done")
                        .font(RSFont.ui(.subheadline, weight: .medium))
                        .foregroundStyle(Color.rsOnDark.opacity(0.6))
                }
                .padding(.top, 14)
            }
            .padding(.horizontal, 30)
            .padding(.bottom, 20)
            .frame(maxWidth: .infinity)
            .modifier(RSScrollableScreen(background: nil, transparent: true))
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
