/// Quiet banner surfacing an upload-level terminal failure (uploadPhase == .failed).
///
/// Mounted unconditionally in ContentView and renders nothing while no failure is
/// surfaced — the same always-mounted pattern as SceneStatusView: the .task on the
/// container is the independent scan path (UploadFailureMonitor.refresh) that finds
/// .failed records persisted by prior launches, while the in-process kick arrives via
/// BlobUploadManager.onFatalBlobError → notifyUploadFailed.
///
/// Copy is honest about the semantics: a .failed bundle never retries itself
/// (rehydration skips terminal records) and no re-upload path exists for it, so a new
/// capture is the only way forward. Dismiss hides the banner for this launch only —
/// the record persists, so the failure reappears on relaunch (see UploadFailureMonitor).

import SwiftUI

struct UploadFailureView: View {

    @ObservedObject private var monitor = UploadFailureMonitor.shared

    var body: some View {
        // VStack (not bare conditional content): the container node always exists, so
        // .task fires even while there is nothing to show — it IS the scan trigger.
        VStack {
            if let failure = monitor.latestFailure {
                banner(failure)
            }
        }
        .task { await UploadFailureMonitor.shared.refresh() }
    }

    private func banner(_ failure: UploadFailureMonitor.UploadFailure) -> some View {
        VStack(spacing: 8) {
            HStack(spacing: 6) {
                Image(systemName: "exclamationmark.triangle.fill")
                    .foregroundStyle(.red)
                Text("Upload failed")
                    .font(.subheadline.weight(.semibold))
            }

            Text("This capture couldn't be uploaded, and it won't retry on its own. Capture the room again when you're ready.")
                .font(.caption)
                .foregroundStyle(.secondary)
                .multilineTextAlignment(.center)

            // Machine data reads as machine data: the raw failureReason, monospaced.
            Text(failure.reason)
                .font(.caption2.monospaced())
                .foregroundStyle(.tertiary)
                .lineLimit(2)
                .multilineTextAlignment(.center)

            Button("Dismiss") {
                Task { await UploadFailureMonitor.shared.dismiss() }
            }
            .buttonStyle(.plain)
            .font(.footnote.weight(.medium))
            .foregroundStyle(.secondary)
            .padding(.top, 2)
        }
        .padding(14)
        .frame(maxWidth: .infinity)
        .background(.red.opacity(0.06), in: RoundedRectangle(cornerRadius: 12))
        .padding(.horizontal, 24)
    }
}

#Preview {
    UploadFailureView()
}
