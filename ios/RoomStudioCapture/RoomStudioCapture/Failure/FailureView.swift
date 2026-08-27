/// When it goes wrong (design spec §7). Failure follows the web system's rule:
/// the guest owns what it couldn't do, never blames the user, and always offers
/// exactly one concrete path. Two kinds:
///
///   • recoverable — the backend's `failed_incomplete`: not all of the room's
///     data reached the desk (an incomplete upload). There is no partial room to
///     show honestly, so the screen offers exactly one path — and WHICH path
///     depends on whether the missing bytes are still on the phone. When they
///     are, it is now "send what's missing" against `missingPaths` (decision
///     0084's coordinator, un-blocked by 0116's force_remint); when they are
///     not, it stays the full rescan it always was. CaptureRecovery makes that
///     call from the disk, and `FailureCopy.Resend` carries it in. NO specific
///     bad region is named: the missing items are upload blobs, not a known
///     corner of the room. It DOES name how many files are missing — the server
///     sends `missing_paths` and the count is a fact about the room, separable
///     from the re-send promise, which only the `.available` copy makes. The
///     0072 redesign dropped the count silently; decision 0085's walk caught it.
///   • terminal — nothing survived; the deepest ink surface, one path: try again.
///     No specific cause is named — the pipeline surfaces no honest per-object
///     reason, so the copy stays general rather than inventing one.
///
/// The upload-failed relaunch banner is `UploadFailedBanner` (separate file), so
/// a failure is never silently lost.

import SwiftUI

/// What the failure screens SAY, as pure functions — the house treatment for a
/// decision that would otherwise be reviewable only by reading a SwiftUI body
/// (WaitFlowState, BundleRestore, CaptureReclaim, RoomActivityVoice all got it).
///
/// Only the incomplete-upload body needs it today: it is the one failure line
/// that varies with server data, and getting the singular/plural or the
/// zero-degrade wrong is exactly the class of defect a table test catches and an
/// eye does not.
///
/// Read by: FailureView. Pinned by: FailureCopyTests.
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
        case ..<1:  return "Some of your room's data didn't finish its trip to the desk"
        case 1:     return "One file didn't finish its trip to the desk"
        default:    return "\(missingCount) files didn't finish their trip to the desk"
        }
    }
}

struct FailureView: View {
    enum Kind: Equatable {
        /// `missingCount` — how many blob paths the server reported absent. See
        /// FailureCopy.incompleteBody for the honesty constraint on stating it.
        /// `resend` — whether those files can actually be sent again, decided by
        /// CaptureRecovery from the disk, never from the view.
        case recoverable(missingCount: Int, resend: FailureCopy.Resend)
        case terminal
        /// The upload itself failed terminally (http_4xx, 308_persistent,
        /// empty_bundle_pb, blob_unreadable_at_remint_manifest…). NOT a capture
        /// fault: "scan slower" fixes none of these, so it gets its own copy and
        /// carries the persisted reason, which is the only diagnostic the user has.
        case uploadFailed(reason: String?)
    }

    var kind: Kind = .recoverable(missingCount: 0, resend: .unavailable)
    var onPrimary: () -> Void = {}
    var onSecondary: () -> Void = {}
    /// Non-nil when this is pushed onto home's stack, which is the only way the
    /// recoverable variant is reached now. It then carries the same header band
    /// every other pushed screen does, rather than starting with a 200pt art
    /// block and no way out — an inconsistency measured across six screens
    /// before RSScreen existed.
    var onBack: (() -> Void)?

    var body: some View {
        switch kind {
        case .recoverable(let missingCount, let resend):
            recoverable(missingCount: missingCount, resend: resend)
        case .terminal:    terminal
        case .uploadFailed(let reason): uploadFailed(reason: reason)
        }
    }

    // MARK: Recoverable (incomplete upload → re-send the missing files, or rescan)

    private func recoverable(missingCount: Int, resend: FailureCopy.Resend) -> some View {
        VStack(spacing: 0) {
            if let onBack {
                ScreenHeader(title: "What's missing", onClose: onBack)
                    .frame(maxWidth: .infinity, alignment: .leading)
            } else {
                // Only without a header: the spacer centred a headerless
                // screen, and under a header it pushed the first element 76pt
                // below where every other screen's starts.
                Spacer(minLength: 12)
            }

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
            .padding(.top, onBack == nil ? 0 : RSScreen.contentGap)
            .frame(maxWidth: .infinity)

            RSCard {
                VStack(alignment: .leading, spacing: 7) {
                    Text("The room didn't all make it up")
                        .font(RSFont.ui(.callout, weight: .semibold))
                        .foregroundStyle(Color.rsInk)
                    Text(FailureCopy.incompleteBody(missingCount: missingCount, resend: resend))
                        .rsFont(.guest, size: 14.5)
                        .foregroundStyle(Color.rsInk)
                        .fixedSize(horizontal: false, vertical: true)
                }
                .frame(maxWidth: .infinity, alignment: .leading)
            }
            .padding(.top, 16)

            Spacer(minLength: 20)
        }
        .padding(.horizontal, RSScreen.horizontal)
        .frame(maxWidth: .infinity)
        .modifier(RSScrollableScreen(background: nil))
        .safeAreaInset(edge: .bottom) {
            // Labels come from the same table the flow binds its actions from,
            // so the button can never say one thing and do another.
            let actions = FailureCopy.recoverableActions(resend)
            VStack(spacing: 10) {
                Button(action: onPrimary) { Text(actions.primaryLabel) }
                    .buttonStyle(RSPrimaryButtonStyle())
                    .disabled(!actions.primaryEnabled)
                    // RSPrimaryButtonStyle does not read isEnabled, so a bare
                    // .disabled() is INVISIBLE — a full-strength rust button
                    // that ignores taps. Found by screenshot at AX5, not by
                    // reading. Dimming at the call site is ReviewView's
                    // established treatment for the same problem; changing the
                    // shared style would touch every primary in the app.
                    .opacity(actions.primaryEnabled ? 1 : 0.55)
                Button(action: onSecondary) { Text(actions.secondaryLabel) }
                    .buttonStyle(RSActionFootnoteStyle())
                    .padding(.top, 2)
            }
            .padding(.horizontal, RSScreen.horizontal)
            .rsActionBar()
        }
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

#Preview("Recoverable — can send (one file)") {
    FailureView(kind: .recoverable(missingCount: 1, resend: .available))
}

#Preview("Recoverable — can send (several)") {
    FailureView(kind: .recoverable(missingCount: 14, resend: .available))
}

#Preview("Recoverable — sending") {
    FailureView(kind: .recoverable(missingCount: 14, resend: .inFlight))
}

#Preview("Recoverable — send failed") {
    FailureView(kind: .recoverable(missingCount: 3, resend: .failed))
}

#Preview("Recoverable — rescan only") {
    FailureView(kind: .recoverable(missingCount: 14, resend: .unavailable))
}

#Preview("Recoverable — count unknown") {
    FailureView(kind: .recoverable(missingCount: 0, resend: .unavailable))
}

#Preview("Terminal") {
    FailureView(kind: .terminal)
}

#Preview("Upload failed") {
    FailureView(kind: .uploadFailed(reason: "http_403"))
}
