/// Status screen shown after a bundle upload completes.
///
/// Observes ScenePoller.shared and renders each ScenePollState distinctly.
/// Last-known status renders INSTANTLY on appear (no blank/spinner flash) because
/// the poller preserves state across pause/resume and the kick may have already
/// advanced the state before this view appears.
///
/// Lifecycle:
///   onAppear  → setVisible(true), then start polling if poller is idle
///   onDisappear + background → pause()
///   foreground return → resume() (immediate tick, no cadence wait)
///
/// Re-upload action for .recoverable is intentionally absent here — that front
/// is separate. This view surfaces the count and the path list is on the model.

import os
import SwiftUI

private let logger = Logger(subsystem: "com.roomstudio.RoomStudioCapture", category: "SceneStatusView")

struct SceneStatusView: View {

    @ObservedObject private var poller = ScenePoller.shared
    @Environment(\.scenePhase) private var scenePhase

    var body: some View {
        VStack(spacing: 24) {
            Spacer()
            stateContent
            Spacer()
        }
        .padding(.horizontal, 32)
        .task { await onAppearAsync() }
        .onDisappear { ScenePoller.shared.pause() }
        .onChange(of: scenePhase) { _, phase in
            switch phase {
            case .active:
                ScenePoller.shared.resume()  // resume() also sets isVisible = true
            case .background, .inactive:
                ScenePoller.shared.pause()
            @unknown default:
                break
            }
        }
    }

    // MARK: - State rendering

    @ViewBuilder
    private var stateContent: some View {
        switch poller.pollState {
        case .idle:
            // Nothing to show: the view stays mounted (its .task is the
            // independent poll-start path) but renders empty until polling starts.
            EmptyView()

        case .polling(let latest, let since, let longRunning, let connectionTrouble):
            pollingView(latest: latest, since: since, longRunning: longRunning, connectionTrouble: connectionTrouble)

        case .succeeded(let response):
            successView(response: response)

        case .failedTerminal(let status):
            failedView(status: status)

        case .recoverable(let missingPaths):
            recoverableView(missingPaths: missingPaths)

        case .pollError(let message):
            errorView(message: message)
        }
    }

    // MARK: - Polling

    private func pollingView(
        latest: SceneStatus,
        since: Date,
        longRunning: Bool,
        connectionTrouble: Bool
    ) -> some View {
        VStack(spacing: 20) {
            ProgressView()
                .scaleEffect(1.4)

            VStack(spacing: 6) {
                Text(longRunning ? "Taking longer than usual" : statusLabel(latest))
                    .font(.headline)
                    .multilineTextAlignment(.center)

                Text(longRunning ? "We'll keep checking — hang tight." : "Processing your room…")
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
                    .multilineTextAlignment(.center)

                if connectionTrouble {
                    Text("Connection trouble, retrying…")
                        .font(.caption)
                        .foregroundStyle(.orange)
                        .padding(.top, 4)
                }

                Text(elapsedLabel(since: since))
                    .font(.caption2.monospacedDigit())
                    .foregroundStyle(.tertiary)
                    .padding(.top, 2)
            }

            if longRunning {
                // Quiet text link, not a bordered control — this is a reassurance
                // affordance, not a primary action.
                Button("Check now") {
                    ScenePoller.shared.checkNow()
                }
                .buttonStyle(.plain)
                .font(.footnote.weight(.medium))
                .foregroundStyle(.secondary)
                .padding(.top, 4)
            }
        }
    }

    // MARK: - Success

    private func successView(response: SceneResponse) -> some View {
        VStack(spacing: 16) {
            Image(systemName: "checkmark.circle.fill")
                .font(.system(size: 64))
                .foregroundStyle(.green)

            Text("Room ready")
                .font(.title2.weight(.semibold))

            if let uri = response.resultUri {
                Text(uri)
                    .font(.caption2)
                    .foregroundStyle(.secondary)
                    .lineLimit(2)
                    .multilineTextAlignment(.center)
            }
        }
        .onAppear {
            // result_uri must be present on a ready scene; its absence is a
            // backend contract violation worth surfacing in logs, not hiding.
            if response.resultUri == nil {
                logger.error("[SceneStatusView] ready scene \(response.sceneId, privacy: .public) has no result_uri — backend contract violation")
            }
        }
    }

    // MARK: - Hard terminal failure

    private func failedView(status: SceneStatus) -> some View {
        VStack(spacing: 16) {
            Image(systemName: "xmark.circle.fill")
                .font(.system(size: 64))
                .foregroundStyle(.red)

            Text("Processing failed")
                .font(.title2.weight(.semibold))

            Text(failureDetail(status))
                .font(.subheadline)
                .foregroundStyle(.secondary)
                .multilineTextAlignment(.center)
        }
    }

    // MARK: - Recoverable (failed_incomplete)

    private func recoverableView(missingPaths: [String]) -> some View {
        VStack(spacing: 16) {
            Image(systemName: "arrow.triangle.2.circlepath")
                .font(.system(size: 64))
                .foregroundStyle(.orange)

            Text("Upload incomplete")
                .font(.title2.weight(.semibold))

            let count = missingPaths.count
            Text(count == 1
                 ? "1 file needs re-uploading."
                 : "\(count) files need re-uploading.")
                .font(.subheadline)
                .foregroundStyle(.secondary)
                .multilineTextAlignment(.center)

            Text("Re-upload will be handled automatically.")
                .font(.caption)
                .foregroundStyle(.tertiary)
                .multilineTextAlignment(.center)
        }
    }

    // MARK: - Poll error

    private func errorView(message: String) -> some View {
        VStack(spacing: 16) {
            Image(systemName: "wifi.slash")
                .font(.system(size: 64))
                .foregroundStyle(.secondary)

            Text("Could not reach server")
                .font(.title2.weight(.semibold))

            Text(message)
                .font(.caption)
                .foregroundStyle(.secondary)
                .multilineTextAlignment(.center)
                .lineLimit(4)
        }
    }

    // MARK: - Lifecycle helpers

    private func onAppearAsync() async {
        ScenePoller.shared.setVisible(true)
        // Only start if the poller is idle — if notifyBundleComplete already kicked it,
        // or if it's mid-poll from a prior resume, don't reset state.
        guard case .idle = ScenePoller.shared.pollState else { return }
        if let bundleId = await findCompletedBundleId() {
            ScenePoller.shared.start(bundleId: bundleId)
        }
    }

    /// Scan the persisted store for a bundle with uploadPhase == .complete.
    /// This is the independent start path that works with or without the kick.
    private func findCompletedBundleId() async -> String? {
        guard let ids = try? await UploadSessionStore.shared.allBundleIds() else { return nil }
        for id in ids {
            if let record = try? await UploadSessionStore.shared.load(bundleId: id),
               record.uploadPhase == .complete {
                return id
            }
        }
        return nil
    }

    // MARK: - Display helpers

    private func statusLabel(_ status: SceneStatus) -> String {
        switch status {
        case .queued:      return "Queued for processing"
        case .processing:  return "Processing"
        default:           return "Processing your room"
        }
    }

    private func failureDetail(_ status: SceneStatus) -> String {
        switch status {
        case .failedInvalid:
            return "The captured data could not be processed. Try capturing again."
        case .failed:
            return "Something went wrong on our end. Please try again."
        default:
            return "Processing ended unexpectedly."
        }
    }

    private func elapsedLabel(since: Date) -> String {
        let secs = Int(Date().timeIntervalSince(since))
        if secs < 60  { return "\(secs)s" }
        let m = secs / 60
        let s = secs % 60
        return String(format: "%d:%02d", m, s)
    }
}

#Preview {
    SceneStatusView()
}
