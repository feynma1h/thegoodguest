/// The missing-files copy and its two offers, as a pure table.
///
/// Moved here from the old What's missing screen when the room screen took
/// over its job (2026-11-10). The table is unchanged except that "to the desk"
/// left the count clause along with the desk itself. `RoomStatusCopy.missing`
/// words the room screen from it; FailureCopyTests pins it.
///
/// Read by: RoomStatusCopy, RootFlowView (which binds the actions).

import Foundation

/// What the failure screens SAY, as pure functions — the house treatment for a
/// decision that would otherwise be reviewable only by reading a SwiftUI body
/// (WaitFlowState, BundleRestore, CaptureReclaim, RoomActivityVoice all got it).
///
/// Only the incomplete-upload body needs it today: it is the one failure line
/// that varies with server data, and getting the singular/plural or the
/// zero-degrade wrong is exactly the class of defect a table test catches and an
/// eye does not.
///
/// Pinned by: FailureCopyTests.
nonisolated enum FailureCopy {

    /// Whether a re-send of the missing files can be offered, and what it is
    /// doing. Decided by CaptureRecovery from facts on disk — never guessed at
    /// the view layer, because the whole honesty constraint below turns on it.
    enum Resend: Equatable {
        /// The named files are on this phone. The re-send is real: offer it.
        case available
        /// No honest re-send (files gone, or nothing usable named). Rescan only —
        /// this is the state the screen shipped in before recovery existed, and
        /// its copy is unchanged.
        case unavailable
        /// A re-send is running right now.
        case inFlight
        /// A re-send was attempted and did not go through. The files are still
        /// here, so the offer stands.
        case failed
    }

    /// What the recoverable screen's two buttons DO.
    enum Action: Equatable {
        /// Re-send the missing blobs (BlobUploadManager.resendMissingBlobs).
        case resend
        /// Start a fresh capture.
        case rescan
        /// Leave the flight, keeping the capture on disk.
        case leave
    }

    /// The recoverable screen's buttons, as a table.
    ///
    /// Labels and actions are decided TOGETHER, in one place, because the defect
    /// they invite is a mismatch between them: a screen that says "Send what's
    /// missing" and starts a rescan destroys the capture the sentence just
    /// promised to send. The view renders the labels from here and the flow
    /// binds the actions from here, so neither side can drift.
    struct Actions: Equatable {
        let primary: Action
        let primaryLabel: String
        /// False while a re-send is in flight — the one state where tapping
        /// again would spend a second mint for no gain.
        let primaryEnabled: Bool
        let secondary: Action
        let secondaryLabel: String
    }

    static func recoverableActions(_ resend: Resend) -> Actions {
        switch resend {
        case .available:
            return Actions(primary: .resend, primaryLabel: "Send what's missing",
                           primaryEnabled: true,
                           secondary: .leave, secondaryLabel: "Not now")
        case .inFlight:
            return Actions(primary: .resend, primaryLabel: "Sending…",
                           primaryEnabled: false,
                           secondary: .leave, secondaryLabel: "Not now")
        case .failed:
            // The rescan moves up to the secondary slot here — it is the real
            // alternative once sending has failed once, and "Not now" is still
            // reachable by leaving the screen.
            return Actions(primary: .resend, primaryLabel: "Try sending again",
                           primaryEnabled: true,
                           secondary: .rescan, secondaryLabel: "Scan the room again")
        case .unavailable:
            return Actions(primary: .rescan, primaryLabel: "Scan the room again",
                           primaryEnabled: true,
                           secondary: .leave, secondaryLabel: "Not now")
        }
    }

    /// The `failed_incomplete` body when no re-send can be offered.
    /// `missingCount` is the number of blob paths the server reported absent.
    ///
    /// THE HONESTY CONSTRAINT (decision 0084): naming the count must not imply
    /// that those files can be re-sent. In THIS state they cannot — the bytes
    /// are gone from the phone, or the server named nothing usable — so the
    /// count is stated as a FACT and the only offered path stays a full rescan.
    /// "N files need re-uploading" is exactly the sentence that would promise one.
    ///
    /// The constraint has NOT been relaxed by the re-send landing; it has been
    /// made conditional. `incompleteBody(missingCount:resend:)` may promise a
    /// re-send only in `.available`, where CaptureRecovery has confirmed every
    /// named file is on disk. This function is what ships everywhere else, and
    /// it is unchanged.
    ///
    /// A count of 0 degrades to the unquantified wording: the server can omit
    /// `missing_paths`, and "0 files didn't make it" is both false and absurd.
    static func incompleteBody(missingCount: Int) -> String {
        countClause(missingCount)
            + ", so I can't show you a partial version honestly. "
            + "Nothing's wrong with the room itself — one more full pass and I'll have all of it."
    }

    /// The `failed_incomplete` body for a given re-send state.
    ///
    /// Only `.available` promises anything, and only because CaptureRecovery
    /// checked: every named file exists in the capture's output directory, and
    /// `force_remint` (decision 0116) makes fresh upload URIs obtainable for
    /// them. That is the whole content of the promise — it says the files are
    /// here and can go again, not that the room will succeed.
    static func incompleteBody(missingCount: Int, resend: Resend) -> String {
        switch resend {
        case .unavailable:
            return incompleteBody(missingCount: missingCount)
        case .available:
            return countClause(missingCount)
                + ", so I can't show you a partial version honestly. "
                + "I still have them here on the phone, though — I can send just those, "
                + "and you won't have to walk the room again."
        case .inFlight:
            return countClause(missingCount)
                + ". I'm sending those now — the rest of the room is already up there, "
                + "so this is the last of it."
        case .failed:
            return countClause(missingCount)
                + ", and my attempt to send them just now didn't get through. "
                + "They're still here on the phone, so it's worth one more go — "
                + "or one more full pass, if you'd rather start clean."
        }
    }

    /// The shared opening clause: how many files did not arrive.
    /// One implementation so the singular/plural agreement and the zero-degrade
    /// cannot differ between the four bodies above.
    private static func countClause(_ missingCount: Int) -> String {
        switch missingCount {
        case ..<1:  return "Some of your room's data didn't finish its trip"
        case 1:     return "One file didn't finish its trip"
        default:    return "\(missingCount) files didn't finish their trip"
        }
    }
}
