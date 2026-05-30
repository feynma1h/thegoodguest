/// P1 capture UI: start/stop button, live frame counter, tracking-state indicator.
///
/// This view owns the CaptureManager for the lifetime of the app (P1: single screen).
/// P2+ will push a navigation stack here once scene upload and status screens exist.
///
/// On-device verification checklist for P1 sign-off:
///   □ Tracking state shows "Normal" after a few seconds
///   □ Frame counter climbs while walking (pose-delta filter active — static holds count)
///   □ Stop → counter freezes; Start → counter resets and climbs again
///   □ App does not crash or stall during a 60-second room walk

import ARKit
import SwiftUI

struct ContentView: View {

    @StateObject private var capture = CaptureManager()

    var body: some View {
        VStack(spacing: 24) {
            Spacer()

            trackingStatusBadge

            frameCountDisplay

            Spacer()

            captureButton
                .padding(.horizontal, 32)
                .padding(.bottom, 48)
        }
    }

    // MARK: - Subviews

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
