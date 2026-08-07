/// Capture UI: start/stop button, live frame counter, tracking-state indicator,
/// tier badge, bundle-path readout, upload-session status badge, the upload-failure
/// banner (UploadFailureView), the scene processing status panel (SceneStatusView),
/// and the account control (top-trailing — sign-in entry point per decision 0051).
///
/// Triggers UploadCoordinator.beginUploadSession when CaptureManager publishes
/// bundlePath (stop-capture → assembly complete).

import ARKit
import SwiftUI

struct ContentView: View {

    @StateObject private var capture     = CaptureManager()
    @StateObject private var coordinator = UploadCoordinator()
    @ObservedObject private var poller   = ScenePoller.shared
    @ObservedObject private var failureMonitor = UploadFailureMonitor.shared
    @ObservedObject private var auth     = AuthManager.shared

    @State private var showSignInSheet = false

    var body: some View {
        VStack(spacing: 24) {
            Spacer()

            tierBadge
            trackingStatusBadge
            frameCountDisplay

            Spacer()

            bundleReadout
            uploadSessionBadge

            // Always mounted, same rationale as SceneStatusView below: renders nothing
            // until a .failed record is surfaced, but its .task is the independent scan
            // path for upload-level terminal failures persisted by prior launches.
            UploadFailureView()
                .transition(.opacity)

            // Always mounted: SceneStatusView renders nothing while the poller is
            // idle, but its .task is the independent poll-start path (it scans the
            // store for a completed bundle). Gating the view on pollState != .idle
            // would deadlock poll start: the state can only leave .idle from inside
            // the view (onAppear) or via the visibility-gated completion kick.
            SceneStatusView()
                .transition(.opacity)

            captureButton
                .padding(.horizontal, 32)
                .padding(.bottom, 48)
        }
        // Start upload session creation as soon as bundle.pb is ready.
        .onChange(of: capture.bundlePath) { _, newPath in
            guard newPath != nil else { return }
            Task { await coordinator.beginUploadSession(for: capture) }
        }
        .overlay(alignment: .topTrailing) {
            accountControl
                .padding(.top, 12)
                .padding(.trailing, 20)
        }
        .sheet(isPresented: $showSignInSheet) {
            SignInSheet()
        }
    }

    // MARK: - Subviews

    /// Account control (decision 0051). Anonymous → a quiet "Sign in" entry
    /// point; linked → the signed-in state, tappable for details. Hidden
    /// entirely when Firebase isn't configured (simulator tests without the
    /// plist) — no dead buttons.
    @ViewBuilder
    private var accountControl: some View {
        if auth.isConfigured {
            Button {
                showSignInSheet = true
            } label: {
                if auth.isAppleLinked {
                    Label("Signed in", systemImage: "checkmark.circle.fill")
                        .font(.caption.weight(.medium))
                        .foregroundStyle(.secondary)
                } else {
                    Text("Sign in")
                        .font(.caption.weight(.semibold))
                }
            }
            .buttonStyle(.bordered)
            .controlSize(.small)
            .clipShape(Capsule())
        }
    }

    /// Tier chip — shows which capture path is active on this device.
    private var tierBadge: some View {
        let (label, color): (String, Color) = switch capture.tier {
        case .lidarRoomplan: ("LIDAR + ROOMPLAN", .purple)
        case .lidarArkit:    ("LIDAR ARKIT",      .teal)
        default:             ("ARKIT ONLY",        .blue)
        }
        return Text(label)
            .font(.caption.weight(.semibold))
            .padding(.horizontal, 10)
            .padding(.vertical, 4)
            .background(color.opacity(0.15))
            .foregroundStyle(color)
            .clipShape(Capsule())
    }

    /// Coloured dot + label showing current ARKit tracking quality.
    private var trackingStatusBadge: some View {
        HStack(spacing: 8) {
            Circle()
                .fill(trackingStateColor)
                .frame(width: 10, height: 10)
            Text(trackingStateLabel)
                .font(.subheadline)
                .foregroundStyle(.secondary)
        }
    }

    /// Large frame count — primary feedback that keyframes are accumulating.
    private var frameCountDisplay: some View {
        VStack(spacing: 4) {
            Text("\(capture.frameCount)")
                .font(.system(size: 72, weight: .bold, design: .rounded))
                .monospacedDigit()
                .contentTransition(.numericText())
            Text("frames")
                .font(.headline)
                .foregroundStyle(.secondary)
        }
    }

    /// Shows bundle.pb path after assembly completes, or a spinner while assembling.
    @ViewBuilder
    private var bundleReadout: some View {
        if let path = capture.bundlePath {
            Text("bundle.pb ready")
                .font(.caption.weight(.medium))
                .foregroundStyle(.green)
            Text(path.deletingLastPathComponent().lastPathComponent)
                .font(.caption2)
                .foregroundStyle(.secondary)
                .lineLimit(1)
                .truncationMode(.middle)
        } else if !capture.isRunning && capture.frameCount > 0 {
            ProgressView()
                .scaleEffect(0.7)
        }
    }

    /// Start / Stop — tint switches to red when a capture is in progress.
    private var captureButton: some View {
        Button(action: toggleCapture) {
            Text(capture.isRunning ? "Stop Capture" : "Start Capture")
                .font(.title2.weight(.semibold))
                .frame(maxWidth: .infinity)
                .padding(.vertical, 16)
        }
        .buttonStyle(.borderedProminent)
        .tint(capture.isRunning ? .red : .blue)
        .animation(.easeInOut(duration: 0.15), value: capture.isRunning)
    }

    /// Upload session status badge — shown after stop-capture triggers the
    /// upload-session pipeline.
    ///
    /// .ready means exactly one thing: the /upload_session mint succeeded and
    /// the blob PUTs were handed to the background URLSession. It is the least
    /// meaningful of the upload milestones (~10 s in), so the copy must not
    /// read as "done" — and once a superseding surface activates, the badge
    /// stands down: after upload completion the scene-status panel owns the
    /// narrative (an "uploading" claim would go stale), after a terminal upload
    /// failure the failure banner does.
    @ViewBuilder
    private var uploadSessionBadge: some View {
        if poller.pollState == .idle, failureMonitor.latestFailure == nil {
            let (label, color): (String, Color) = switch coordinator.sessionState {
            case .idle:              ("", .clear)
            case .authenticating:    ("Authenticating…", .orange)
            case .patchingBundle:    ("Patching bundle…", .orange)
            case .buildingManifest:  ("Building manifest…", .orange)
            case .creatingSession:   ("Creating session…", .orange)
            case .ready:             ("Upload authorized — uploading in background", .blue)
            case .failed(let msg, _): ("Session error: \(msg)", .red)
            // The daily mint cap (decision 0087). This is the unreferenced rollback
            // root — it gets a correct, plain line; RootFlowView owns the real
            // treatment (WaitingView.sendRateLimited).
            case .rateLimited:       ("Daily upload limit reached — try again later", .orange)
            }
            if !label.isEmpty {
                Text(label)
                    .font(.caption.weight(.medium))
                    .foregroundStyle(color)
                    .multilineTextAlignment(.center)
                    .padding(.horizontal, 16)
            }
        }
    }

    // MARK: - Actions

    private func toggleCapture() {
        if capture.isRunning {
            capture.stopCapture()
        } else {
            capture.startCapture()
        }
    }

    // MARK: - Tracking state helpers

    private var trackingStateColor: Color {
        switch capture.trackingState {
        case .normal:       return .green
        case .limited:      return .yellow
        case .notAvailable: return .gray
        @unknown default:   return .gray
        }
    }

    private var trackingStateLabel: String {
        switch capture.trackingState {
        case .normal:
            return "Tracking: Normal"
        case .limited(let reason):
            switch reason {
            case .initializing:         return "Tracking: Initializing"
            case .excessiveMotion:      return "Tracking: Excessive Motion"
            case .insufficientFeatures: return "Tracking: Insufficient Features"
            case .relocalizing:         return "Tracking: Relocalizing"
            @unknown default:           return "Tracking: Limited"
            }
        case .notAvailable:
            return "Tracking: Not Available"
        @unknown default:
            return "Tracking: Unknown"
        }
    }
}

#Preview {
    ContentView()
}
