/// Upload & processing, narrated as arrival (design spec §5). Once the bundle is
/// uploaded, the copy narrates *analysis* — the room being understood — never
/// pipeline internals ("meshing / segmenting"). A server-anchored clock keeps
/// time honest across relaunches. Every waiting state has a felt temperature:
/// patient (queued), reassuring (analyzing), candid if it runs long, and calm if
/// the line drops.
///
/// This is the in-app surface. The background-upload progress (bytes + time) is
/// the one place a progress bar is allowed and lives in the Live Activity
/// (separate widget target), not here. This view restyles the states of the
/// existing ScenePoller machine; the spine integration binds `phase`/`anchor` to
/// `ScenePollState.polling(...)` (its `sceneCreatedAt` is the anchor, its
/// `longRunning`/`connectionTrouble` flags pick the phase).

import SwiftUI

struct WaitingView: View {
    enum Phase { case queued, analyzing, longRunning, connectionTrouble }

    var phase: Phase = .analyzing
    /// Server-side scene start; the elapsed clock counts from here so it reads
    /// true even after the user leaves and returns.
    var anchor: Date = .now
    var onTryNow: () -> Void = {}
    var onLeave: () -> Void = {}

    @State private var breathe = false

    var body: some View {
        ZStack {
            ParchmentBackground()
            content
                .padding(.horizontal, 30)
        }
    }

    @ViewBuilder
    private var content: some View {
        switch phase {
        case .queued, .analyzing, .longRunning:
            analyzingBody
        case .connectionTrouble:
            connectionTroubleBody
        }
    }

    // MARK: Analyzing / queued / long-running

    private var analyzingBody: some View {
        VStack(spacing: 0) {
            Spacer()

            // Slow gold pulse — light, not machinery.
            ZStack {
                Circle()
                    .fill(RadialGradient(colors: [Color.rsGold, Color(rsHex: 0xb98d43)],
                                         center: .center, startRadius: 2, endRadius: 44))
                    .frame(width: 80, height: 80)
                    .shadow(color: Color.rsGold.opacity(0.4), radius: 30)
                    .scaleEffect(breathe ? 1.06 : 0.96)
                    .opacity(0.9)
            }

            if phase == .longRunning {
                stillWorkingPill.padding(.top, 26)
            }

            Text(title)
                .font(RSFont.display(size: 23))
                .foregroundStyle(Color.rsInk)
                .multilineTextAlignment(.center)
                .padding(.top, phase == .longRunning ? 14 : 30)

            GuestLine(guestLine, size: 15, alignment: .center)
                .padding(.horizontal, 6)
                .padding(.top, 10)

            Spacer()

            elapsedFooter
                .padding(.bottom, 10)
        }
        .onAppear {
            withAnimation(.easeInOut(duration: 3.2).repeatForever(autoreverses: true)) {
                breathe = true
            }
        }
    }

    private var stillWorkingPill: some View {
        HStack(spacing: 8) {
            Circle().fill(Color.rsGold).frame(width: 8, height: 8)
            Text("Still working")
                .font(RSFont.ui(.subheadline, weight: .semibold))
                .foregroundStyle(Color.rsInk)
        }
        .padding(.horizontal, 14).padding(.vertical, 7)
        .background(Capsule().fill(Color.rsSurface).overlay(Capsule().stroke(Color.rsHairline, lineWidth: 1)))
    }

    private var elapsedFooter: some View {
        HStack(spacing: 10) {
            Eyebrow("Elapsed")
            TimelineView(.periodic(from: .now, by: 1)) { context in
                Text(Self.clock(context.date.timeIntervalSince(anchor)))
                    .font(RSFont.mono(size: 15, weight: .medium))
                    .foregroundStyle(Color.rsInk)
                    .monospacedDigit()
            }
            if phase == .analyzing {
                Circle().fill(Color.rsInkFaint).frame(width: 4, height: 4)
                Text("usually about 4 minutes")
                    .font(RSFont.ui(.subheadline))
                    .foregroundStyle(Color.rsInkMuted)
            }
        }
        .padding(.top, 16)
        .overlay(alignment: .top) { Divider().background(Color.rsHairline) }
    }

    // MARK: Connection trouble

    private var connectionTroubleBody: some View {
        VStack {
            Spacer()
            VStack(alignment: .leading, spacing: 0) {
                HStack(spacing: 9) {
                    Image(systemName: "wifi.exclamationmark")
                        .font(.system(size: 16))
                        .foregroundStyle(Color.rsGoldLight)
                    Text("Can't reach the studio")
                        .font(RSFont.ui(.callout, weight: .semibold))
                        .foregroundStyle(Color.rsOnDark)
                }
                GuestLine("I've lost my line to the desk for a moment — your room is safe, I just can't check on it. I'll keep trying quietly.",
                          size: 14.5, onDark: true)
                    .padding(.top, 9)
                HStack(spacing: 8) {
                    Button(action: onTryNow) {
                        Text("Try now")
                            .font(RSFont.ui(.subheadline, weight: .semibold))
                            .foregroundStyle(Color.rsInk)
                            .padding(.horizontal, 16).padding(.vertical, 8)
                            .background(Capsule().fill(Color.rsSurface))
                    }
                    Button(action: onLeave) {
                        Text("Leave it with me")
                            .font(RSFont.ui(.subheadline, weight: .medium))
                            .foregroundStyle(Color.rsOnDark.opacity(0.85))
                            .padding(.horizontal, 16).padding(.vertical, 8)
                            .background(Capsule().stroke(Color.rsOnDark.opacity(0.35), lineWidth: 1.5))
                    }
                }
                .padding(.top, 14)
            }
            .padding(18)
            .background(Color.rsInk, in: RoundedRectangle(cornerRadius: 16, style: .continuous))
            Spacer()
            Text("Your room keeps its place in line — the clock counts from when it arrived, not from now.")
                .font(RSFont.ui(.footnote))
                .foregroundStyle(Color.rsInkMuted)
                .multilineTextAlignment(.center)
                .padding(.bottom, 14)
        }
    }

    // MARK: Copy

    private var title: String {
        switch phase {
        case .queued:       return "Getting in line"
        case .analyzing:    return "Making sense of your room"
        case .longRunning:  return "Making sense of your room"
        case .connectionTrouble: return ""
        }
    }

    private var guestLine: String {
        switch phase {
        case .queued:
            return "In line — I'll start the moment there's room."
        case .analyzing:
            return "It's here — all of it. Give me a few minutes to understand how you live in it."
        case .longRunning:
            return "Slower than I hoped — a couple more minutes. Your room has a lot going on, which is a compliment. You can leave; I'll knock."
        case .connectionTrouble:
            return ""
        }
    }

    /// mm:ss, or h:mm:ss past an hour. Clamps negative skew to zero.
    static func clock(_ seconds: TimeInterval) -> String {
        let s = max(0, Int(seconds))
        let h = s / 3600, m = (s % 3600) / 60, sec = s % 60
        return h > 0
            ? String(format: "%d:%02d:%02d", h, m, sec)
            : String(format: "%02d:%02d", m, sec)
    }
}

#Preview("Analyzing") {
    WaitingView(phase: .analyzing, anchor: Date().addingTimeInterval(-134))
}

#Preview("Long running") {
    WaitingView(phase: .longRunning, anchor: Date().addingTimeInterval(-398))
}

#Preview("Connection trouble") {
    WaitingView(phase: .connectionTrouble)
}
