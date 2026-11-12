/// What the Live Activity SAYS, as pure functions over the stage.
///
/// WHY THIS EXISTS: the Lock Screen and the Dynamic Island render the same stage
/// at three very different sizes, and the app's own wait screens say these things
/// already. Copy written inline in three SwiftUI bodies drifts — one surface says
/// "Sending from your phone" while another says "Uploading" — and drift on a surface the
/// user reads without opening the app is the kind that never gets caught. Stating
/// it once, as a table, makes both the wording and the mirroring testable.
///
/// THE COPY MIRRORS THE APP, deliberately: the titles are the room screen's own
/// steps (RoomStatusCopy), shortened where the Lock Screen's width demands it.
/// The Lock Screen contradicting the screen the user just left is the failure this
/// guards. Voice rules hold (design spec §7/§10): the guest owns what it couldn't
/// do, never blames the user, never promises a notification it cannot send, and
/// never states an ETA.
///
/// THE RULE OF LAMPLIGHT applies to `tint` as it does everywhere: lamplight is
/// LIGHT, so it appears only on dusk, for a room moving or ready. On the light
/// card everything is ink; terracotta never tints a status. Nothing here
/// introduces a hex.
///
/// Read by: RoomUploadLiveActivity (extension). Pinned by: LiveActivityVoiceTests.

import SwiftUI

nonisolated enum RoomActivityVoice {

    // MARK: - Words

    /// The headline. Short enough for the Dynamic Island's expanded centre.
    static func title(_ stage: RoomActivityStage) -> String {
        switch stage {
        case .preparing:        return "Packing it up"
        case .sending:          return "Sending from your phone"
        // Deliberately NOT "Almost there": that is a claim about time, and the
        // OS can hold the finalize for many minutes (decision 0110). This says
        // where the room is, which stays true however long the hold lasts.
        case .finalizing:       return "Sent from your phone"
        case .queued:           return "Getting in line"
        case .analyzing:        return "Being rebuilt"
        case .ready:            return "Your room is ready."
        case .paused:           return "Sending paused"
        case .failed(.upload):  return "Stalled on the way up"
        case .failed(.processing): return "Couldn’t be rebuilt"
        case .failed(.incomplete): return "Some files didn’t arrive"
        }
    }

    /// The guest's supporting line. One sentence — this is a glance surface.
    static func line(_ stage: RoomActivityStage) -> String {
        switch stage {
        case .preparing:
            return "Packing it up for the trip."
        case .sending:
            // Matches the room screen's sending state: leaving is safe, the background session
            // carries it. No "keep the app open" — that would be false.
            return "On its way up. You can put the phone down."
        case .finalizing:
            // Names the action that resets the OS's background-launch delay to
            // zero (decision 0110) WITHOUT claiming the transfer has stopped —
            // it may well land on its own. "if this sits for a while" is the
            // honest hedge in both branches; a flat "open me" would be the
            // `.paused` promise, which is a different and stronger claim.
            return "The whole room is up. Open me if it sits a while."
        case .queued:
            return "I'll start the moment there's room."
        case .analyzing:
            // No ETA and no "I'll knock": push isn't built, so a notification
            // promise is one nothing can keep.
            return "Give me a few minutes with it."
        case .ready:
            return "Come in when you have a minute."
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
        case .finalizing: return "···"
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

    /// SF Symbol for the stage. System symbols only: an extension cannot reach
    /// the app's asset catalog, where the mark's artwork lives.
    static func symbol(_ stage: RoomActivityStage) -> String {
        switch stage {
        case .preparing:  return "shippingbox"
        case .sending:    return "arrow.up.circle"
        // Filled sibling of `.sending`'s mark: the same journey, further along.
        case .finalizing: return "arrow.up.circle.fill"
        case .queued:     return "clock"
        case .analyzing:  return "sparkles"
        case .ready:      return "door.left.hand.open"
        case .paused:     return "pause.circle"
        case .failed:     return "exclamationmark.triangle"
        }
    }

    /// The stage's accent. Gold ONLY on `.ready` — the light-semantic moment (the
    /// doorway). Work in progress is rust; failure is ink, not red.
    /// The mark's colour for a stage. On the Lock Screen's light card every
    /// stage is ink: terracotta is the brand's, not a status, and colour does
    /// not carry the state there — the words do. On the Dynamic Island, which
    /// is dusk by nature, a room that is moving or ready is lamplight (light,
    /// the one thing lit) and a stopped one is plain light text.
    static func tint(_ stage: RoomActivityStage, onDusk: Bool = false) -> Color {
        guard onDusk else { return .rsInk }
        switch stage {
        case .preparing, .sending, .finalizing, .queued, .analyzing, .ready:
            return .rsLamp
        case .paused, .failed:
            return .rsOnDusk
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
