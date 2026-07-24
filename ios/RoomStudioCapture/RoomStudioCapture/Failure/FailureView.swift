/// When it goes wrong (design spec §7). Failure follows the web system's rule:
/// the guest owns what it couldn't do, never blames the user, and always offers
/// exactly one concrete path. Two kinds:
///
///   • recoverable — the backend's `failed_incomplete`: not all of the room's
///     data reached the desk (an incomplete upload). There is no partial room to
///     show honestly and — today — no re-upload of just the missing blobs (see the
///     CLAUDE.md "no automatic re-upload for .recoverable" gap), so the one honest
///     path is a full rescan. NO specific bad region is named: the missing items
///     are upload blobs, not a known corner of the room. When the re-upload
///     coordinator lands, this becomes "send the rest" against `missingPaths`.
///   • terminal — nothing survived; the deepest ink surface, one path: try again.
///     No specific cause is named — the pipeline surfaces no honest per-object
///     reason, so the copy stays general rather than inventing one.
///
/// The upload-failed relaunch banner is `UploadFailedBanner` (separate file), so
/// a failure is never silently lost.

import SwiftUI

struct FailureView: View {
    enum Kind: Equatable {
        case recoverable
        case terminal
        /// The upload itself failed terminally (http_4xx, 308_persistent,
        /// empty_bundle_pb, blob_unreadable_at_remint_manifest…). NOT a capture
        /// fault: "scan slower" fixes none of these, so it gets its own copy and
        /// carries the persisted reason, which is the only diagnostic the user has.
        case uploadFailed(reason: String?)
    }

    var kind: Kind = .recoverable
    var onPrimary: () -> Void = {}
    var onSecondary: () -> Void = {}

    var body: some View {
        switch kind {
        case .recoverable: recoverable
        case .terminal:    terminal
        case .uploadFailed(let reason): uploadFailed(reason: reason)
        }
    }

    // MARK: Recoverable (incomplete upload → full rescan)

    private var recoverable: some View {
        VStack(spacing: 0) {
            Spacer(minLength: 12)

            // The drawn sketch as ambient brand art — NOT a claim that a partial
            // room was captured; failed_incomplete is an upload gap, not a coverage
            // one, and there is no honest partial to render.
            ZStack {
                RoundedRectangle(cornerRadius: 16, style: .continuous)
                    .fill(Color.rsCaptureRaised)
                RoomSketch().padding(20).opacity(0.5)
            }
            .frame(height: 200)
            .clipShape(RoundedRectangle(cornerRadius: 16, style: .continuous))

            RSCard {
                VStack(alignment: .leading, spacing: 7) {
                    Text("The room didn't all make it up")
                        .font(RSFont.ui(.callout, weight: .semibold))
                        .foregroundStyle(Color.rsInk)
                    Text("Some of your room's data didn't finish its trip to the desk, so I can't show you a partial version honestly. Nothing's wrong with the room itself — one more full pass and I'll have all of it.")
                        .rsFont(.guest, size: 14.5)
                        .foregroundStyle(Color.rsInk)
                        .fixedSize(horizontal: false, vertical: true)
                }
                .frame(maxWidth: .infinity, alignment: .leading)
            }
            .padding(.top, 16)

            Spacer()

            VStack(spacing: 10) {
                Button(action: onPrimary) { Text("Scan the room again") }
                    .buttonStyle(RSPrimaryButtonStyle())
                Button(action: onSecondary) { Text("Not now") }
                    .buttonStyle(RSQuietButtonStyle())
            }
            .padding(.bottom, 8)
        }
        .padding(.horizontal, 24)
        .frame(maxWidth: .infinity)
        .modifier(RSScrollableScreen(background: nil))
        .onAppear { RSHaptics.fire(.failure) }
    }

    // MARK: Upload failed (the send broke, not the scan)

    private func uploadFailed(reason: String?) -> some View {
        VStack(alignment: .leading, spacing: 0) {
            Spacer()

            Image(systemName: "arrow.up.circle")
                .font(.system(size: 34, weight: .regular))
                .foregroundStyle(Color.rsGoldLight)

            Text("I couldn't get it up to the desk.")
                .rsFont(.display, size: 24)
                .foregroundStyle(Color.rsOnDark)
                .padding(.top, 24)

            GuestLine("The scan itself was fine — it's the sending that broke, and it won't recover on its own. Nothing about how you scanned caused this.",
                      size: 15.5, onDark: true)
                .padding(.top, 14)

            if let reason {
                Text(reason)
                    .rsFont(.mono, size: 11, maxSize: 15)
                    .foregroundStyle(Color.rsOnDark.opacity(0.45))
                    .textSelection(.enabled)
                    .padding(.top, 12)
            }

            Spacer()

            VStack(spacing: 11) {
                Button(action: onPrimary) { Text("Scan the room again") }
                    .buttonStyle(RSLightButtonStyle())
                Button(action: onSecondary) { Text("Later") }
                    .buttonStyle(RSQuietButtonStyle(onDark: true))
            }
        }
        .padding(.horizontal, 32)
        .padding(.bottom, 20)
        .frame(maxWidth: .infinity, alignment: .leading)
        .modifier(RSScrollableScreen(background: Color.rsInk))
        .onAppear { RSHaptics.fire(.failure) }
    }

    // MARK: Terminal

    private var terminal: some View {
        VStack(alignment: .leading, spacing: 0) {
            Spacer()

            Image(systemName: "exclamationmark.square")
                .font(.system(size: 34, weight: .regular))
                .foregroundStyle(Color.rsGoldLight)

            Text("The scan didn't survive the trip.")
                .rsFont(.display, size: 24)
                .foregroundStyle(Color.rsOnDark)
                .padding(.top, 24)

            GuestLine("There's nothing here I could honestly show you — and it's not something you did. When you're near the room again, let's try one more pass. Slower is better this time.",
                      size: 15.5, onDark: true)
                .padding(.top, 14)

            Spacer()

            VStack(spacing: 11) {
                Button(action: onPrimary) { Text("Scan the room again") }
                    .buttonStyle(RSLightButtonStyle())
                Button(action: onSecondary) { Text("Later") }
                    .buttonStyle(RSQuietButtonStyle(onDark: true))
            }
        }
        .padding(.horizontal, 32)
        .padding(.bottom, 20)
        .frame(maxWidth: .infinity, alignment: .leading)
        .modifier(RSScrollableScreen(background: Color.rsInk))
        .onAppear { RSHaptics.fire(.failure) }
    }
}

#Preview("Recoverable") {
    FailureView(kind: .recoverable)
}

#Preview("Terminal") {
    FailureView(kind: .terminal)
}

#Preview("Upload failed") {
    FailureView(kind: .uploadFailed(reason: "http_403"))
}
