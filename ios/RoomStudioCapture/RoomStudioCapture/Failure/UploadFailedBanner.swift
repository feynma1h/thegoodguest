/// The upload-failed banner (design spec §7). Sits at the top of the idle home
/// on the next launch after an upload stalls — so a crash or a dead battery
/// mid-upload never loses the room silently. The capture file is retained
/// on-device.
///
/// It renders in `HomeView`'s `notice` slot, inside the scroll area, NOT in the
/// wrapper above it: a notice in that fixed column takes the height the pinned
/// scan action needs, and at accessibility sizes the action is what gives
/// (decision 0224).
///
/// Bound to `UploadFailureMonitor` by the spine. Kept a pure presentation
/// component so it previews standalone.
///
/// NO RETRY AFFORDANCE, deliberately: this banner surfaces only
/// `uploadPhase == .failed` records (see `UploadFailureMonitor`), which are
/// TERMINAL by construction: DEFERRED paths retry cross-launch without ever
/// setting `.failed` (decision 0045). `BlobUploadManager.rehydrateBundle`
/// refuses `.failed` records, so a "try again" here would be a silent no-op.
/// It is a truthful notification with one honest action — dismiss. A real
/// re-drive belongs to the deferred terminal-state-handling design, not a dead
/// button.
///
/// The room is not named: iOS holds no room name (rooms are named on the web
/// from captured data), so the copy stays general rather than inventing one.

import SwiftUI

struct UploadFailedBanner: View {
    /// The persisted `failureReason`. Shown verbatim in mono — it is the diagnostic
    /// value of this whole surface, and the banner it replaces displayed it. Without
    /// it the user can say only "a scan stalled", with nothing to report.
    var reason: String?
    var onDismiss: () -> Void = {}

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            // .top, not centred: at accessibility sizes the headline wraps and a
            // vertically centred glyph comes to rest in the middle of it, reading
            // as punctuation rather than as an icon. Decision 0224.
            HStack(alignment: .top, spacing: 9) {
                Image(systemName: "exclamationmark.triangle")
                    .font(.system(size: 14, weight: .medium))
                    .foregroundStyle(Color.rsGoldLight)
                    .frame(height: 20, alignment: .center)
                Text("One room didn't make it up")
                    .font(RSFont.ui(.subheadline, weight: .semibold))
                    .foregroundStyle(Color.rsOnDark)
                    .fixedSize(horizontal: false, vertical: true)
                    .multilineTextAlignment(.leading)
            }
            GuestLine("A scan stalled on its way to the desk. It's still here on your phone, safe.",
                      size: 13, onDark: true)

            if let reason {
                Text(reason)
                    .rsFont(.mono, size: 10, maxSize: 13)
                    .foregroundStyle(Color.rsOnDark.opacity(0.5))
                    .textSelection(.enabled)
                    .padding(.top, 2)
            }

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
        UploadFailedBanner(reason: "blob_unreadable_at_remint_manifest")
            .padding()
        Spacer()
    }
    .frame(maxWidth: .infinity, maxHeight: .infinity)
    .rsParchmentScreen()
}
