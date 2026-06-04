/// Capture UI: start/stop button, live frame counter, tracking-state indicator,
/// bundle-path readout, and upload-session status.
///
/// P2 additions: tier badge, bundle.pb path shown after stop + assembly.
/// P3 additions: upload session state badge; coordinator triggered when bundlePath is set.
///
/// On-device verification checklist for P3 sign-off:
///   □ Auth badge shows "Authenticated" after launch (requires network + GoogleService-Info.plist)
///   □ Stop → assembly → "bundle.pb ready" → upload status progresses to "Session ready"
///   □ Console: "POST /captures/<id>/upload_session → 200" with manifest path count
///   □ Session record persisted: verify with lldb or log

import ARKit
import SwiftUI

struct ContentView: View {

    @StateObject private var capture     = CaptureManager()
    @StateObject private var coordinator = UploadCoordinator()
    @ObservedObject private var poller   = ScenePoller.shared

    var body: some View {
        VStack(spacing: 24) {
            Spacer()

            tierBadge
            trackingStatusBadge
            frameCountDisplay

            #if DEBUG
            gravityDebugHUD
            #endif

            Spacer()

            bundleReadout
            uploadSessionBadge

            if poller.pollState != .idle {
                SceneStatusView()
                    .transition(.opacity)
            }

            captureButton
                .padding(.horizontal, 32)
                .padding(.bottom, 48)
        }
        // Start upload session creation as soon as bundle.pb is ready.
        .onChange(of: capture.bundlePath) { _, newPath in
            guard newPath != nil else { return }
            Task { await coordinator.beginUploadSession(for: capture) }
        }
    }

    // MARK: - Subviews

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

    #if DEBUG
    /// Live gravity readout for on-device sign/axis eyeball check (chunk C sign-off).
    @ViewBuilder
    private var gravityDebugHUD: some View {
        if let g = capture.lastGravity {
            Text(String(format: "g_cam: (%+.2f, %+.2f, %+.2f)", g.x, g.y, g.z))
                .font(.system(.caption2, design: .monospaced))
                .foregroundStyle(.secondary)
        }
    }
    #endif

    /// Upload session status badge — shown after stop-capture triggers P3 pipeline.
    @ViewBuilder
    private var uploadSessionBadge: some View {
        let (label, color): (String, Color) = switch coordinator.sessionState {
        case .idle:              ("", .clear)
        case .authenticating:    ("Authenticating…", .orange)
        case .patchingBundle:    ("Patching bundle…", .orange)
        case .buildingManifest:  ("Building manifest…", .orange)
        case .creatingSession:   ("Creating session…", .orange)
        case .ready:             ("Session ready ✓", .green)
        case .failed(let msg):   ("Session error: \(msg)", .red)
        }
        if !label.isEmpty {
            Text(label)
                .font(.caption.weight(.medium))
                .foregroundStyle(color)
                .multilineTextAlignment(.center)
                .padding(.horizontal, 16)
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
