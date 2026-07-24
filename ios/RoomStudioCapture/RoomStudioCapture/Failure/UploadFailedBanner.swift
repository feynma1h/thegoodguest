/// The upload-failed banner (design spec §7). Pinned to the top of the idle home
/// on the next launch after an upload stalls — so a crash or a dead battery
/// mid-upload never loses the room silently. The capture file is retained
/// on-device.
///
/// This is the Good Guest restyle of the existing functional `UploadFailureView`
/// (Upload/). The spine integration swaps the old banner for this and binds it to
/// `UploadFailureMonitor`. Kept a pure presentation component so it previews
/// standalone.
///
/// NO RETRY AFFORDANCE, deliberately: this banner surfaces only
/// `uploadPhase == .failed` records (see `UploadFailureMonitor`), which are
/// TERMINAL by construction (P5(b) — DEFERRED paths retry cross-launch without
/// setting `.failed`). `BlobUploadManager.rehydrateBundle` refuses `.failed`
/// records, so a "try again" here would be a silent no-op. It is a truthful
/// notification with one honest action — dismiss — matching the original
/// `UploadFailureView` semantics. A real re-drive belongs to the deferred
/// terminal-state-handling design, not a dead button.
///
/// The room is not named: iOS holds no room name (rooms are named on the web
/// from captured data), so the copy stays general rather than inventing one.

import SwiftUI

struct UploadFailedBanner: View {
    var onDismiss: () -> Void = {}

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack(spacing: 9) {
                Image(systemName: "exclamationmark.triangle")
                    .font(.system(size: 14, weight: .medium))
                    .foregroundStyle(Color.rsGoldLight)
                Text("One room didn't make it up")
                    .font(RSFont.ui(.subheadline, weight: .semibold))
                    .foregroundStyle(Color.rsOnDark)
            }
            GuestLine("A scan stalled on its way to the desk. It's still here on your phone, safe.",
                      size: 13, onDark: true)

            HStack(spacing: 8) {
                Button(action: onDismiss) {
                    Text("Dismiss")
                        .font(RSFont.ui(.footnote, weight: .medium))
                        .foregroundStyle(Color.rsOnDark.opacity(0.7))
                        .padding(.horizontal, 8).padding(.vertical, 6)
                }
            }
            .padding(.top, 4)
        }
        .padding(14)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Color.rsInk, in: RoundedRectangle(cornerRadius: 12, style: .continuous))
        .onAppear { RSHaptics.fire(.failure) }
    }
}

#Preview {
    VStack {
        UploadFailedBanner()
            .padding()
        Spacer()
    }
    .frame(maxWidth: .infinity, maxHeight: .infinity)
    .rsParchmentScreen()
}
