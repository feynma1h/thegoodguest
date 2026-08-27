/// The desk — the room in flight, with an address.
///
/// The old wait screens were a place you were HELD: you sent a room and stayed
/// on a screen until a terminal state let you go. The desk is a place you can
/// always reach and always leave. That single change is what lets paused and
/// rate-limited finally have a surface — both were previously states you could
/// only see by being trapped in them.
///
/// NO ORB, NO PILL. The old analyzing screen carried a slowly pulsing gold
/// circle and, past a threshold, a "Still working" capsule above a title and a
/// line that already said the same thing. Three elements stated one fact and
/// the two ornamental ones said nothing about this product. What is left is
/// what the phone actually knows: which room, what is happening to it, and how
/// long it has been.
///
/// THE ELAPSED FIGURE IS COARSE, and deliberately. The old screen ran a live
/// mm:ss clock, which is the right treatment for a screen you are held on and
/// the wrong one for a place you drop in on — a ticking second counter turns a
/// visit into a vigil. `RoomHistory.elapsedPhrase` is the same coarse phrasing
/// the house uses for the same fact, so one room reads identically wherever it
/// appears. It is still counted from the SERVER's clock and it is still elapsed
/// only: the pipeline gives the phone no estimate, so there is none to show.
///
/// CONTROLS SPEAK IN THE USER'S VOICE. The old "Leave it with me" was the
/// guest's line on the user's button, which left someone mid-upload working out
/// whether leaving would break it. "I'll come back" says what the person is
/// doing, and the prose above it carries the reassurance rather than burying it.
///
/// Read by: RootFlowView, from home's sentence and the contents sheet.

import SwiftUI

// MARK: - What the desk says

/// The desk's copy, as a pure function of the state.
///
/// A table for the same reason `FailureCopy` is one: these sentences promise
/// things about someone's data — that leaving is safe, that nothing is lost,
/// that it will resume — and each promise is only true in some states. Pinned
/// by DeskCopyTests.
nonisolated enum DeskCopy {

    /// The mono status line: what is happening, and how long it has been.
    /// Machine truth, so mono, and never an estimate.
    static func status(_ state: DeskState, now: Date) -> String {
        switch state {
        case .sending:
            return "LEAVING YOUR PHONE"
        case .working(let anchor, _):
            guard let anchor, now >= anchor else { return "AT THE DESK" }
            return "AT THE DESK · \(RoomHistory.elapsedPhrase(from: anchor, to: now).uppercased()) SO FAR"
        case .paused:
            return "PAUSED · RESUMES NEXT VISIT"
        case .rateLimited:
            return "PAUSED · TODAY'S LIMIT REACHED"
        case .retryableSendFailure:
            return "STILL ON YOUR PHONE"
        case .checkFailed:
            return "AT THE DESK · CAN'T CHECK JUST NOW"
        }
    }

    /// The guest's line. Carries the reassurance the control used to have to
    /// imply.
    static func line(_ state: DeskState, now: Date) -> String {
        switch state {
        case .sending:
            return "You can put me away — sending carries on by itself."
        case .working(_, let longRunning):
            return longRunning
                ? "Slower than I hoped — your room has a lot going on, which is a compliment. I'm still at it."
                : "I'm making sense of what you showed me."
        case .paused:
            return "Asleep until you next open me — there's nothing for you to do."
        case .rateLimited(let resetsAt):
            return WaitingView.rateLimitLine(resetsAt: resetsAt, now: now)
        case .retryableSendFailure:
            return "I couldn't get it up to the desk just now, so it hasn't started yet. Nothing's lost — it's still here on your phone."
        case .checkFailed(_, let stopped):
            return stopped
                ? "I've lost my line to the desk. Your room is safe up there; I just can't check on it, and I've stopped trying."
                : "I've lost my line to the desk for a moment. Your room is safe — I'll keep trying quietly."
        }
    }

    /// The one control, in the user's voice. Nil where leaving is the only
    /// move and the header's back button already offers it.
    static func action(_ state: DeskState) -> String? {
        switch state {
        case .retryableSendFailure: return "Try again"
        case .checkFailed(_, let stopped): return stopped ? "Look again" : nil
        case .sending, .working, .paused, .rateLimited: return nil
        }
    }
}

// MARK: - The screen

struct DeskView: View {
    /// Nil when nothing is in flight — the clear state.
    var state: DeskState?
    /// The room's derived title ("today's room"). Nil in the clear state.
    var roomTitle: String?
    var onAct: () -> Void = {}
    var onOpenHouse: () -> Void = {}
    var onClose: () -> Void = {}

    /// Injected so the elapsed phrase is testable and the previews are stable.
    var now: Date = Date()

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            ScreenHeader(title: "The desk", onClose: onClose)

            if let state {
                busy(state)
            } else {
                clear
            }

            Spacer(minLength: 20)
        }
        .padding(.horizontal, 24)
        .padding(.bottom, 12)
        .frame(maxWidth: .infinity, alignment: .topLeading)
        .modifier(RSScrollableScreen(background: nil))
    }

    @ViewBuilder
    private func busy(_ state: DeskState) -> some View {
        VStack(alignment: .leading, spacing: 0) {
            if let roomTitle {
                Text(roomTitle)
                    .rsFont(.display, size: 24, weight: .medium)
                    .foregroundStyle(Color.rsInk)
                    .fixedSize(horizontal: false, vertical: true)
            }

            Text(DeskCopy.status(state, now: now))
                .rsFont(.mono, size: 10.5, weight: .semibold)
                .tracking(1.1)
                .foregroundStyle(statusInk(state))
                .fixedSize(horizontal: false, vertical: true)
                .padding(.top, 10)

            GuestLine(DeskCopy.line(state, now: now), size: 16)
                .fixedSize(horizontal: false, vertical: true)
                .padding(.top, 18)

            if let action = DeskCopy.action(state) {
                Button(action: onAct) {
                    Text(action)
                        .font(RSFont.ui(.subheadline, weight: .semibold))
                        .foregroundStyle(Color.rsInk)
                        .padding(.horizontal, 18).padding(.vertical, 9)
                        .background(Capsule().stroke(Color.rsInk.opacity(0.35), lineWidth: 1.5))
                }
                .padding(.top, 22)
            }
        }
        .padding(.top, 30)
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    /// The ordinary state, and it must be the screen's best one — most days
    /// nothing is in flight, and a desk that reads as empty-and-broken would
    /// make the whole surface feel like a dead end.
    private var clear: some View {
        VStack(alignment: .leading, spacing: 14) {
            Text("The desk is clear.")
                .rsFont(.display, size: 24, weight: .medium)
                .foregroundStyle(Color.rsInk)
                .fixedSize(horizontal: false, vertical: true)

            Button(action: onOpenHouse) {
                HStack(alignment: .top, spacing: 8) {
                    Text("Everything you've sent is in the house")
                        .rsFont(.guest, size: 16)
                        .foregroundStyle(Color.rsInkMuted)
                        .fixedSize(horizontal: false, vertical: true)
                        .multilineTextAlignment(.leading)
                    Image(systemName: "chevron.right")
                        .font(.system(size: 12, weight: .semibold))
                        .foregroundStyle(Color.rsInk.opacity(0.4))
                        .frame(height: 22, alignment: .center)
                }
            }
            .buttonStyle(.plain)
        }
        .padding(.top, 30)
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    /// Gold while something is genuinely moving; ordinary ink once it is
    /// resting or stuck. Never rust — nothing on this screen needs a decision,
    /// which is what sends a room to Notes instead.
    private func statusInk(_ state: DeskState) -> Color {
        switch state {
        case .sending, .working: return .rsGoldInk
        case .paused, .rateLimited, .retryableSendFailure, .checkFailed: return .rsInkFaint
        }
    }
}

// MARK: - Previews

#Preview("Sending") {
    DeskView(state: .sending, roomTitle: "today's room")
}

#Preview("At the desk") {
    DeskView(state: .working(anchor: Date().addingTimeInterval(-268), longRunning: false),
             roomTitle: "today's room")
}

#Preview("Taking a while") {
    DeskView(state: .working(anchor: Date().addingTimeInterval(-800), longRunning: true),
             roomTitle: "today's room")
}

#Preview("Paused") {
    DeskView(state: .paused, roomTitle: "yesterday's room")
}

#Preview("Today's limit") {
    DeskView(state: .rateLimited(resetsAt: Date().addingTimeInterval(31_000)),
             roomTitle: "today's room")
}

#Preview("Didn't leave the phone") {
    DeskView(state: .retryableSendFailure, roomTitle: "today's room")
}

#Preview("Can't check") {
    DeskView(state: .checkFailed(anchor: Date().addingTimeInterval(-268), stopped: true),
             roomTitle: "today's room")
}

#Preview("Clear") {
    DeskView(state: nil)
}
