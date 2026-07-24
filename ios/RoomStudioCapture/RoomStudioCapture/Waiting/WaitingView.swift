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
    enum Phase {
        /// Still handing the room over: sign-in / manifest / POST /upload_session,
        /// before a single byte has left the phone. NOT "analyzing" — the room has
        /// not arrived anywhere, so no arrival claim, no ETA, no elapsed clock.
        case sending
        case queued, analyzing, longRunning
        /// Lost contact WHILE CHECKING on an already-uploaded room — the room is up
        /// and holding its place; we just can't read its status this moment.
        case connectionTrouble
        /// Could not SEND the room up in the first place (sign-in / manifest / server
        /// rejection / bundle not written yet). Nothing was uploaded, so there is no
        /// "place in line" and no arrival clock — the copy must not imply otherwise.
        case sendFailed
        /// Send failed in a way retrying cannot fix (a 4xx — our bug, not the
        /// network). Still NOT a "the scan didn't survive the trip" failure: nothing
        /// ever left the phone and the capture is intact on disk, so this must not
        /// offer discarding it as the primary action.
        case sendFailedTerminal
        /// The upload paused and only resumes on the next launch. Distinct from
        /// sendFailed, which invites an immediate retry that would actually work.
        case sendPaused
    }

    var phase: Phase = .analyzing
    /// Server-side scene start; the elapsed clock counts from here so it reads
    /// true even after the user leaves and returns.
    ///
    /// OPTIONAL BY DESIGN: nil until the first 200 delivers `created_at`. Before
    /// that there is no honest thing to count from (matching SceneStatusView's
    /// server-anchored rule), so the clock is not rendered at all rather than
    /// silently counting from a client-side moment.
    var anchor: Date?
    /// True when the poll loop has STOPPED (a fatal poll error). Swaps the
    /// "I'll keep trying quietly" reassurance for the truth.
    var pollingStopped: Bool = false
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
        case .sending, .queued, .analyzing, .longRunning:
            analyzingBody
        case .connectionTrouble:
            connectionTroubleBody
        case .sendFailed:
            sendFailedBody(terminal: false)
        case .sendFailedTerminal:
            sendFailedBody(terminal: true)
        case .sendPaused:
            sendPausedBody
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
                .rsFont(.display, size: 23)
                .foregroundStyle(Color.rsInk)
                .multilineTextAlignment(.center)
                .padding(.top, phase == .longRunning ? 14 : 30)

            GuestLine(guestLine, size: 15, alignment: .center)
                .padding(.horizontal, 6)
                .padding(.top, 10)

            Spacer()

            // The wait must never be a trap: without this there is no back gesture
            // (the flow has no NavigationStack) and no control, so the user is held
            // here until a terminal poll state arrives. Leaving is reversible — home
            // shows a re-entry row while a room is in flight, and re-entering resumes
            // polling from the persisted upload record (RootFlowView).
            Button(action: onLeave) {
                Text("Leave it with me")
                    .font(RSFont.ui(.subheadline, weight: .medium))
                    .foregroundStyle(Color.rsInkMuted)
                    .padding(.horizontal, 18).padding(.vertical, 9)
                    .background(Capsule().stroke(Color.rsHairline, lineWidth: 1.5))
            }
            .padding(.bottom, 18)

            if anchor != nil {
                elapsedFooter
                    .padding(.bottom, 10)
            }
        }
        .frame(maxWidth: .infinity)
        .modifier(RSScrollableScreen(background: nil, transparent: true))
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

    /// Elapsed only — deliberately NO estimate. "Usually about N minutes" had no
    /// measured basis (GPU cold start alone is ~3.5 min and real captures have
    /// needed more than one processing pass), so an ETA here would be invented.
    /// The honest clock stands on its own.
    @ViewBuilder
    private var elapsedFooter: some View {
        if let anchor {
            HStack(spacing: 10) {
                Eyebrow("Elapsed")
                TimelineView(.periodic(from: .now, by: 1)) { context in
                    Text(Self.clock(context.date.timeIntervalSince(anchor)))
                        .rsFont(.mono, size: 15, weight: .medium)
                        .foregroundStyle(Color.rsInk)
                        .monospacedDigit()
                }
            }
            .padding(.top, 16)
            .overlay(alignment: .top) { Divider().background(Color.rsHairline) }
        }
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
                        .fixedSize(horizontal: false, vertical: true)
                        .foregroundStyle(Color.rsOnDark)
                }
                GuestLine(pollingStopped
                          ? "I've lost my line to the desk — your room is safe up there, I just can't check on it, and I've stopped trying. Tell me when to look again."
                          : "I've lost my line to the desk for a moment — your room is safe, I just can't check on it. I'll keep trying quietly.",
                          size: 14.5, onDark: true)
                    .fixedSize(horizontal: false, vertical: true)
                    .padding(.top, 9)
                ViewThatFits(in: .horizontal) {
                  HStack(spacing: 8) { tryNowButton; leaveButton }
                  VStack(alignment: .leading, spacing: 8) { tryNowButton; leaveButton }
                }
                .padding(.top, 14)
            }
            .padding(18)
            .background(Color.rsInk, in: RoundedRectangle(cornerRadius: 16, style: .continuous))
            Spacer()
            // Only claim the arrival clock when a server anchor actually exists —
            // before the first 200 there is no "when it arrived" to count from.
            if anchor != nil {
                Text("Your room keeps its place in line — the clock counts from when it arrived, not from now.")
                    .font(RSFont.ui(.footnote))
                    .foregroundStyle(Color.rsInkMuted)
                    .multilineTextAlignment(.center)
                    .fixedSize(horizontal: false, vertical: true)
                    .padding(.bottom, 14)
            }
        }
    }

    // MARK: Send failed (couldn't upload in the first place)

    private func sendFailedBody(terminal: Bool) -> some View {
        VStack {
            Spacer()
            VStack(alignment: .leading, spacing: 0) {
                HStack(spacing: 9) {
                    Image(systemName: "arrow.up.circle")
                        .font(.system(size: 16))
                        .foregroundStyle(Color.rsGoldLight)
                    Text(terminal ? "I couldn't send it up" : "Couldn't send it up")
                        .font(RSFont.ui(.callout, weight: .semibold))
                        .fixedSize(horizontal: false, vertical: true)
                        .foregroundStyle(Color.rsOnDark)
                }
                GuestLine(terminal
                          ? "Something on my end refused the room — that's my fault, not yours, and trying again won't move it. Your scan is safe on your phone; I'll pick it up once I'm fixed."
                          : "I couldn't get the room up to the desk just now — so it hasn't started yet. Nothing's lost; it's still here on your phone. Shall I try again?",
                          size: 14.5, onDark: true)
                    .fixedSize(horizontal: false, vertical: true)
                    .padding(.top, 9)
                HStack(spacing: 8) {
                    if !terminal {
                    Button(action: onTryNow) {
                        Text("Try again")
                            .font(RSFont.ui(.subheadline, weight: .semibold))
                            .foregroundStyle(Color.rsInk)
                            .padding(.horizontal, 16).padding(.vertical, 8)
                            .background(Capsule().fill(Color.rsSurface))
                    }
                    }
                    Button(action: onLeave) {
                        Text("Not now")
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
        }
        .frame(maxWidth: .infinity)
        .modifier(RSScrollableScreen(background: nil, transparent: true))
    }

    // MARK: Shared controls

    /// Extracted so ViewThatFits can lay them out side-by-side or stacked. At
    /// accessibility sizes an HStack truncated both labels to "Try…" / "Leav…",
    /// leaving the screen's only exit unreadable.
    private var tryNowButton: some View {
        Button(action: onTryNow) {
            Text("Try now")
                .font(RSFont.ui(.subheadline, weight: .semibold))
                .foregroundStyle(Color.rsInk)
                .fixedSize(horizontal: false, vertical: true)
                .padding(.horizontal, 16).padding(.vertical, 8)
                .background(Capsule().fill(Color.rsSurface))
        }
    }

    private var leaveButton: some View {
        Button(action: onLeave) {
            Text("Leave it with me")
                .font(RSFont.ui(.subheadline, weight: .medium))
                .foregroundStyle(Color.rsOnDark.opacity(0.85))
                .fixedSize(horizontal: false, vertical: true)
                .padding(.horizontal, 16).padding(.vertical, 8)
                .background(Capsule().stroke(Color.rsOnDark.opacity(0.35), lineWidth: 1.5))
        }
    }

    // MARK: Send paused (resumes next launch, not now)

    private var sendPausedBody: some View {
        VStack {
            Spacer()
            VStack(alignment: .leading, spacing: 0) {
                HStack(spacing: 9) {
                    Image(systemName: "pause.circle")
                        .font(.system(size: 16))
                        .foregroundStyle(Color.rsGoldLight)
                    Text("Paused on its way up")
                        .font(RSFont.ui(.callout, weight: .semibold))
                        .fixedSize(horizontal: false, vertical: true)
                        .foregroundStyle(Color.rsOnDark)
                }
                GuestLine("The connection gave out, so I've set this down rather than keep hammering at it. It's safe on your phone, and I'll pick it up the next time you open me — there's nothing to do now.",
                          size: 14.5, onDark: true)
                    .fixedSize(horizontal: false, vertical: true)
                    .padding(.top, 9)
                Button(action: onLeave) {
                    Text("All right")
                        .font(RSFont.ui(.subheadline, weight: .medium))
                        .foregroundStyle(Color.rsOnDark.opacity(0.85))
                        .padding(.horizontal, 16).padding(.vertical, 8)
                        .background(Capsule().stroke(Color.rsOnDark.opacity(0.35), lineWidth: 1.5))
                }
                .padding(.top, 14)
            }
            .padding(18)
            .background(Color.rsInk, in: RoundedRectangle(cornerRadius: 16, style: .continuous))
            Spacer()
        }
        .frame(maxWidth: .infinity)
        .modifier(RSScrollableScreen(background: nil, transparent: true))
    }

    // MARK: Copy

    private var title: String {
        switch phase {
        case .sending:      return "Sending your room"
        case .queued:       return "Getting in line"
        case .analyzing:    return "Making sense of your room"
        case .longRunning:  return "Making sense of your room"
        case .connectionTrouble, .sendFailed, .sendFailedTerminal, .sendPaused: return ""
        }
    }

    private var guestLine: String {
        switch phase {
        case .sending:
            // Nothing has arrived yet — no "it's here", no ETA.
            // No "keep the app open": the upload runs on a background URLSession,
            // and if it defers, staying in the app is exactly what prevents recovery
            // (rehydration happens at launch). Leaving is safe.
            return "On its way up to the desk. You can put the phone down."
        case .queued:
            return "In line — I'll start the moment there's room."
        case .analyzing:
            return "It's here — all of it. Give me a few minutes to understand how you live in it."
        case .longRunning:
            // No "I'll knock": push (FCM) registration is not built on iOS yet, so
            // promising a notification would be a promise nothing can keep.
            return "Slower than I hoped — a couple more minutes. Your room has a lot going on, which is a compliment."
        case .connectionTrouble, .sendFailed, .sendFailedTerminal, .sendPaused:
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

#Preview("Sending (no anchor yet)") {
    WaitingView(phase: .sending)
}

#Preview("Analyzing") {
    WaitingView(phase: .analyzing, anchor: Date().addingTimeInterval(-134))
}

#Preview("Long running") {
    WaitingView(phase: .longRunning, anchor: Date().addingTimeInterval(-398))
}

#Preview("Connection trouble") {
    WaitingView(phase: .connectionTrouble, anchor: Date().addingTimeInterval(-92))
}

#Preview("Poll stopped") {
    WaitingView(phase: .connectionTrouble, anchor: Date().addingTimeInterval(-92), pollingStopped: true)
}

#Preview("Send failed") {
    WaitingView(phase: .sendFailed)
}

#Preview("Send failed (terminal)") {
    WaitingView(phase: .sendFailedTerminal)
}

#Preview("Send paused") {
    WaitingView(phase: .sendPaused)
}
