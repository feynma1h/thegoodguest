/// The three sound cues (design spec §10, decision 0072). Sound appears at
/// exactly three moments and nowhere else:
///
///   • captureStart — a low warm tone as the first ink strokes appear
///   • enough       — a soft resolving two-note chord at "I've got the room"
///   • readyKnock   — a single soft wooden knock when the room is ready
///
/// Honors the silent switch: the audio session uses the `.ambient` category, so
/// the ring/silent switch silences these cues (they are decorative confirmations,
/// not content) and they never interrupt other audio.
///
/// ASSET SEAM: the cue files are not yet in the bundle. `play(_:)` looks each up
/// by name and no-ops cleanly if absent, so this is safe to call from the UI
/// today; drop the three short `.caf`/`.m4a` files in with the names below and
/// the cues light up with no call-site change.

import AVFoundation

@MainActor
final class RSSound {
    static let shared = RSSound()

    enum Cue {
        case captureStart, enough, readyKnock

        /// Bundle resource name (without extension) for this cue.
        var resource: String {
            switch self {
            case .captureStart: return "rs_capture_start"
            case .enough:       return "rs_enough"
            case .readyKnock:   return "rs_ready_knock"
            }
        }
    }

    private var players: [String: AVAudioPlayer] = [:]
    private var sessionConfigured = false

    private init() {}

    /// Play a cue. No-op if the asset is absent (see the asset seam above) or if
    /// the audio session can't be activated.
    static func play(_ cue: Cue) {
        shared.play(cue)
    }

    private func play(_ cue: Cue) {
        guard let player = player(for: cue) else { return }
        configureSessionIfNeeded()
        player.currentTime = 0
        player.play()
    }

    private func player(for cue: Cue) -> AVAudioPlayer? {
        if let existing = players[cue.resource] { return existing }
        // Try the common short-audio extensions in turn; absent → no cue.
        for ext in ["caf", "m4a", "wav", "aiff"] {
            if let url = Bundle.main.url(forResource: cue.resource, withExtension: ext),
               let player = try? AVAudioPlayer(contentsOf: url) {
                player.prepareToPlay()
                players[cue.resource] = player
                return player
            }
        }
        return nil
    }

    private func configureSessionIfNeeded() {
        guard !sessionConfigured else { return }
        // .ambient → silenced by the ring switch, mixes with other audio.
        try? AVAudioSession.sharedInstance().setCategory(.ambient, options: [.mixWithOthers])
        try? AVAudioSession.sharedInstance().setActive(true)
        sessionConfigured = true
    }
}
