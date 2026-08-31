/// The haptic vocabulary (design spec §10, decision 0072). Haptics are used
/// only where they earn their place — a felt confirmation that something
/// happened or arrived, never ambient buzz. Call sites fire semantic events, not
/// raw generators, so the mapping lives in one place.
///
/// Restraint is the point: when the app speaks with the Taptic Engine, it means
/// something crossed a threshold.

import UIKit

enum RSHaptic {
    /// "Scan a room" tapped on the home screen. A single soft impact.
    case scanTapped
    /// Capture began — the first ink strokes land. Medium impact (paired with a tone).
    case captureStart
    /// A coverage surface completed (a floor/walls/corners tick fills). Light tick.
    case surfaceCovered
    /// "I've got the room" — enough coverage reached, or Finish. Success.
    case gotTheRoom
    /// Finish/stop tapped (when not already at "enough"). Medium impact.
    case finish
    /// The room is ready — the doorway. Success (paired with the knock).
    case roomReady
    /// A failure surfaced. Warning, once — never a harsh error buzz.
    case failure
    /// Sign-in link succeeded — the two selves became one. Success.
    case linkSucceeded

    func fire() {
        switch self {
        case .scanTapped:
            UIImpactFeedbackGenerator(style: .soft).impactOccurred()
        case .captureStart, .finish:
            UIImpactFeedbackGenerator(style: .medium).impactOccurred()
        case .surfaceCovered:
            UIImpactFeedbackGenerator(style: .light).impactOccurred()
        case .gotTheRoom, .roomReady, .linkSucceeded:
            UINotificationFeedbackGenerator().notificationOccurred(.success)
        case .failure:
            UINotificationFeedbackGenerator().notificationOccurred(.warning)
        }
    }
}

enum RSHaptics {
    /// Fire a semantic haptic event. No-op safe on devices without a Taptic Engine.
    static func fire(_ event: RSHaptic) {
        event.fire()
    }
}
