/// Capture UI: start/stop button, live frame counter, tracking-state indicator,
/// and bundle-path readout after assembly.
///
/// P2 additions: tier badge, bundle.pb path shown after stop + assembly.
///
/// On-device verification checklist for P2 sign-off:
///   □ Tier badge shows correct tier (ARKIT ONLY vs LIDAR ARKIT) for the device
///   □ Frame counter climbs while walking; Stop → assembly → bundlePath text appears
///   □ Console: "bundle.pb → <path>" printed; file exists at that path
///   □ python tools/inspect_bundle.py <path> passes on the resulting bundle.pb

import ARKit
import SwiftUI

struct ContentView: View {

    @StateObject private var capture = CaptureManager()

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

            captureButton
                .padding(.horizontal, 32)
                .padding(.bottom, 48)
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
