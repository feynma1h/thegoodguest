/// When it goes wrong (design spec §7). Failure follows the web system's rule:
/// the guest owns what it couldn't do, never blames the user, and always offers
/// exactly one concrete path. Two kinds:
///
///   • recoverable — part of the room made it; the bad region is set aside (never
///     rendered broken), with a targeted rescan of just that spot.
///   • terminal — nothing survived; the deepest ink surface, one path: try again.
///     No specific cause is named — the pipeline surfaces no honest per-object
///     reason, so the copy stays general rather than inventing one.
///
/// The upload-failed relaunch banner is `UploadFailedBanner` (separate file), so
/// a failure is never silently lost.

import SwiftUI

struct FailureView: View {
    enum Kind: Equatable {
        case recoverable(region: String)
        case terminal
    }

    var kind: Kind = .recoverable(region: "The corner by the door")
    var onPrimary: () -> Void = {}
    var onSecondary: () -> Void = {}

    var body: some View {
        switch kind {
        case .recoverable(let region): recoverable(region: region)
        case .terminal:                terminal
        }
    }

    // MARK: Recoverable

    private func recoverable(region: String) -> some View {
        VStack(spacing: 0) {
            Spacer(minLength: 12)

            // The capture, with the bad region set aside — never rendered broken.
            ZStack(alignment: .topTrailing) {
                RoundedRectangle(cornerRadius: 16, style: .continuous)
                    .fill(Color.rsCaptureRaised)
                RoomSketch().padding(20)
                setAsideTag.padding(14)
            }
            .frame(height: 200)
            .clipShape(RoundedRectangle(cornerRadius: 16, style: .continuous))

            RSCard {
                VStack(alignment: .leading, spacing: 7) {
                    Text("Most of the room made it")
                        .font(RSFont.ui(.callout, weight: .semibold))
                        .foregroundStyle(Color.rsInk)
                    Text("\(region) arrived scrambled, so I've set it aside rather than show you something false. We can work without it — or send that one corner again. Thirty seconds of phone time.")
                        .font(RSFont.guest(size: 14.5))
                        .foregroundStyle(Color.rsInk)
                        .fixedSize(horizontal: false, vertical: true)
                }
                .frame(maxWidth: .infinity, alignment: .leading)
            }
            .padding(.top, 16)

            Spacer()

            VStack(spacing: 10) {
                Button(action: onPrimary) { Text("Rescan just that corner") }
                    .buttonStyle(RSPrimaryButtonStyle())
                Button(action: onSecondary) { Text("Use it as is") }
                    .buttonStyle(RSQuietButtonStyle())
            }
            .padding(.bottom, 8)
        }
        .padding(.horizontal, 24)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .rsParchmentScreen()
        .onAppear { RSHaptics.fire(.failure) }
    }

    private var setAsideTag: some View {
        Text("set aside")
            .font(RSFont.guest(size: 11))
            .foregroundStyle(Color.rsOnDark.opacity(0.6))
            .frame(width: 80, height: 60)
            .background(
                RoundedRectangle(cornerRadius: 10, style: .continuous)
                    .stroke(style: StrokeStyle(lineWidth: 1.5, dash: [4, 3]))
                    .foregroundStyle(Color.rsOnDark.opacity(0.5))
            )
    }

    // MARK: Terminal

    private var terminal: some View {
        VStack(alignment: .leading, spacing: 0) {
            Spacer()

            Image(systemName: "exclamationmark.square")
                .font(.system(size: 34, weight: .regular))
                .foregroundStyle(Color.rsGoldLight)

            Text("The scan didn't survive the trip.")
                .font(RSFont.display(size: 24))
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
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .leading)
        .background(Color.rsInk.ignoresSafeArea())
        .onAppear { RSHaptics.fire(.failure) }
    }
}

#Preview("Recoverable") {
    FailureView(kind: .recoverable(region: "The corner by the door"))
}

#Preview("Terminal") {
    FailureView(kind: .terminal)
}
