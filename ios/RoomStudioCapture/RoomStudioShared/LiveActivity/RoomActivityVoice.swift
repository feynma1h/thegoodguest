/// What the Live Activity SAYS, as pure functions over the stage.
///
/// WHY THIS EXISTS: the Lock Screen and the Dynamic Island render the same stage
/// at three very different sizes, and the app's own wait screens say these things
/// already. Copy written inline in three SwiftUI bodies drifts — one surface says
/// "Sending your room" while another says "Uploading" — and drift on a surface the
/// user reads without opening the app is the kind that never gets caught. Stating
/// it once, as a table, makes both the wording and the mirroring testable.
///
/// THE COPY MIRRORS THE APP, deliberately: the titles are WaitingView's and
/// FailureView's own lines, shortened where the Lock Screen's width demands it.
/// The Lock Screen contradicting the screen the user just left is the failure this
/// guards. Voice rules hold (design spec §7/§10): the guest owns what it couldn't
/// do, never blames the user, never promises a notification it cannot send, and
/// never states an ETA.
///
/// THE RULE OF GOLD applies to `tint` as it does everywhere: gold is
/// LIGHT-SEMANTIC — the ready moment, the doorway. Sending is rust (an action in
/// progress), failure is ink. Nothing here introduces a hex.
///
/// Read by: RoomUploadLiveActivity (extension). Pinned by: LiveActivityVoiceTests.

import SwiftUI

nonisolated enum RoomActivityVoice {

    // MARK: - Words

    /// The headline. Short enough for the Dynamic Island's expanded centre.
    static func title(_ stage: RoomActivityStage) -> String {
        switch stage {
        case .preparing:        return "Getting your room ready"
        case .sending:          return "Sending your room"
        case .queued:           return "Getting in line"
        case .analyzing:        return "Making sense of your room"
        case .ready:            return "Your room is ready."
        case .paused:           return "Paused for now"
        case .failed(.upload):  return "I couldn't get it up to the desk."
        case .failed(.processing): return "The scan didn't survive the trip."
        case .failed(.incomplete): return "The room didn't all make it up"
        }
    }

    /// The guest's supporting line. One sentence — this is a glance surface.
    static func line(_ stage: RoomActivityStage) -> String {
        switch stage {
        case .preparing:
            return "Packing it up for the trip."
        case .sending:
            // Matches WaitingView.sending: leaving is safe, the background session
            // carries it. No "keep the app open" — that would be false.
            return "On its way up. You can put the phone down."
        case .queued:
            return "I'll start the moment there's room."
        case .analyzing:
            // No ETA and no "I'll knock": push isn't built, so a notification
            // promise is one nothing can keep.
            return "Give me a few minutes with it."
        case .ready:
            return "Open me and step into it."
        case .paused:
            // Honest about WHERE the resume happens: waiting on this screen does
            // nothing, opening the app is what moves it.
            return "I'll pick it up next time you open me."
        case .failed(.upload), .failed(.processing):
            return "Open me and we'll go again."
        case .failed(.incomplete):
            return "One more full pass and I'll have all of it."
        }
    }

    /// The Dynamic Island's compact trailing slot and the minimal presentation —
    /// a few characters at most. Progress percent while sending, a mark otherwise.
    static func compact(_ stage: RoomActivityStage) -> String {
        if let fraction = stage.fraction {
            return "\(Int((fraction * 100).rounded()))%"
        }
        switch stage {
        case .preparing:  return "···"
        case .sending:    return "···"    // total not known yet
        case .queued:     return "···"
        case .analyzing:  return "···"
        case .ready:      return "✓"
        case .paused:     return "▮▮"
        case .failed:     return "!"
        }
    }

    /// Machine-data counter for the Lock Screen's mono slot: "128 of 385".
    /// nil wherever there is no honest count to show.
    static func counter(_ stage: RoomActivityStage) -> String? {
        guard case .sending(let sent, let total) = stage, total > 0 else { return nil }
        return "\(sent) of \(total)"
    }

    // MARK: - Marks

    /// SF Symbol for the stage. System symbols only: the brand faces and the
    /// wordmark are not in the app bundle yet (the RSFont seam), and an extension
    /// cannot reach the app's asset catalog regardless.
    static func symbol(_ stage: RoomActivityStage) -> String {
        switch stage {
        case .preparing:  return "shippingbox"
        case .sending:    return "arrow.up.circle"
        case .queued:     return "clock"
        case .analyzing:  return "sparkles"
        case .ready:      return "door.left.hand.open"
        case .paused:     return "pause.circle"
        case .failed:     return "exclamationmark.triangle"
        }
    }

    /// The stage's accent. Gold ONLY on `.ready` — the light-semantic moment (the
    /// doorway). Work in progress is rust; failure is ink, not red.
    static func tint(_ stage: RoomActivityStage) -> Color {
        switch stage {
        case .ready:                    return .rsGold
        case .failed:                   return .rsInk
        case .preparing, .sending, .queued, .analyzing, .paused:
            return .rsAction
        }
    }

    /// One-line VoiceOver read of the whole activity — the Lock Screen renders
    /// title, line and counter as separate views, which VoiceOver would otherwise
    /// announce as three unrelated fragments.
    static func accessibilityLabel(_ stage: RoomActivityStage) -> String {
        if let counter = counter(stage) {
            return "\(title(stage)). \(counter) sent. \(line(stage))"
        }
        return "\(title(stage)). \(line(stage))"
    }
}
