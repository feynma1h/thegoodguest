/// The upload-failed banner (design spec §7). Pinned to the top of the idle home
/// on the next launch after an upload stalls — so a crash or a dead battery
/// mid-upload never loses the room silently. The capture file is retained
/// on-device until it either uploads or the user dismisses.
///
/// This is the Good Guest restyle of the existing functional `UploadFailureView`
/// (Upload/). The spine integration swaps the old banner for this and binds it to
/// `UploadFailureMonitor` (room name + retry). Kept a pure presentation component
/// so it previews standalone.

import SwiftUI

struct UploadFailedBanner: View {
    var roomName: String = "the everything room"
    var onRetry: () -> Void = {}
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
            GuestLine("\(roomName.capitalizedFirst) stalled on its way to the desk. It's still here on your phone — shall I try again?",
                      size: 13, onDark: true)

            HStack(spacing: 8) {
                Button(action: onRetry) {
                    Text("Try again")
                        .font(RSFont.ui(.footnote, weight: .semibold))
                        .foregroundStyle(Color(rsHex: 0x2a2114))
                        .padding(.horizontal, 14).padding(.vertical, 6)
                        .background(Capsule().fill(Color.rsGold))
                }
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
    }
}

private extension String {
    /// Capitalize only the first character (leave "the everything room" lowercase
    /// mid-phrase; sentence-case the lead).
    var capitalizedFirst: String {
        guard let first else { return self }
        return first.uppercased() + dropFirst()
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
