/// Pre-capture guidance (design spec §2). A short coaching sheet — not a tutorial
/// wall: how to move, what a good scan needs, one honest privacy line. The system
/// camera permission is requested here, in context, on "Start scanning" (never at
/// launch) — with the reason set just above it. If denied, the CTA becomes "Open
/// Settings".
///
/// Dark surface, to pre-empt the capture screen's darkness — the transition into
/// scanning is a fade, not a jolt. Under the LiDAR-only pivot (decision 0072) the
/// tier chip is always "PRO CAPTURE"; the STANDARD-CAPTURE variant is not built.
///
/// Presented as a medium-detent sheet (the caller sets the detents). Calls
/// `onStart` once camera access is granted.

import AVFoundation
import SwiftUI

struct GuidanceSheet: View {
    var onStart: () -> Void = {}
    var onDismiss: () -> Void = {}

    @State private var permissionDenied = false

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            header

            proChip
                .padding(.top, 14)

            VStack(alignment: .leading, spacing: 18) {
                GuidanceRow(
                    symbol: "move.3d",
                    title: "Move slowly, keep it level",
                    detail: "A steady walking pace. Sweep the phone gently, like you're painting the walls with your eyes."
                )
                GuidanceRow(
                    symbol: "circle.grid.cross",
                    title: "Get every corner & the floor",
                    detail: "Walls, floor, and where they meet. Corners are what tell the room its true shape."
                )
                GuidanceRow(
                    symbol: "sun.max",
                    title: "Turn the lights on",
                    detail: "Even light helps me see truly. I'll tell you if it gets too dark to trust."
                )
            }
            .padding(.top, 24)

            Spacer(minLength: 20)

            privacyLine
                .padding(.bottom, 12)

            startButton
        }
        .padding(.horizontal, 26)
        .padding(.top, 20)
        .padding(.bottom, 12)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .background(Color.rsCaptureRaised.ignoresSafeArea())
    }

    // MARK: - Pieces

    private var header: some View {
        HStack {
            Text("Before you start")
                .rsFont(.display, size: 15, weight: .medium)
                .foregroundStyle(Color.rsOnDark.opacity(0.8))
            Spacer()
            Button(action: onDismiss) {
                Image(systemName: "xmark")
                    .font(.system(size: 13, weight: .semibold))
                    .foregroundStyle(Color.rsOnDark)
                    .frame(width: 30, height: 30)
                    .background(Color.rsOnDark.opacity(0.12), in: Circle())
            }
            .accessibilityLabel("Close")
        }
    }

    private var proChip: some View {
        HStack(spacing: 7) {
            Circle().fill(Color.rsGold).frame(width: 7, height: 7)
            Text("LiDAR READY · PRO CAPTURE")
                .rsFont(.mono, size: 11, weight: .medium)
                .tracking(0.8)
                .foregroundStyle(Color.rsGoldLight)
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 6)
        .background(
            Capsule().fill(Color.rsGold.opacity(0.16))
                .overlay(Capsule().stroke(Color.rsGold.opacity(0.4), lineWidth: 1))
        )
    }

    private var privacyLine: some View {
        HStack(alignment: .top, spacing: 7) {
            Image(systemName: "lock")
                .font(.system(size: 12))
                .foregroundStyle(Color.rsOnDark.opacity(0.5))
                .padding(.top, 1)
            Text("\(RSBrand.name) uses the camera & LiDAR to measure your room. Nothing is uploaded until you finish.")
                .font(RSFont.ui(.footnote))
                .foregroundStyle(Color.rsOnDark.opacity(0.5))
                .fixedSize(horizontal: false, vertical: true)
        }
    }

    @ViewBuilder
    private var startButton: some View {
        if permissionDenied {
            Button {
                openSettings()
            } label: {
                Label("Open Settings", systemImage: "gear")
            }
            .buttonStyle(RSGoldButtonStyle())
        } else {
            Button {
                requestCameraThenStart()
            } label: {
                Label("Start scanning", systemImage: "camera.viewfinder")
            }
            .buttonStyle(RSGoldButtonStyle())
        }
    }

    // MARK: - Camera permission (in context)

    private func requestCameraThenStart() {
        switch AVCaptureDevice.authorizationStatus(for: .video) {
        case .authorized:
            onStart()
        case .notDetermined:
            AVCaptureDevice.requestAccess(for: .video) { granted in
                DispatchQueue.main.async {
                    if granted { onStart() } else { permissionDenied = true }
                }
            }
        default:
            permissionDenied = true
        }
    }

    private func openSettings() {
        guard let url = URL(string: UIApplication.openSettingsURLString) else { return }
        UIApplication.shared.open(url)
    }
}

/// One coaching row: an icon tile + a title and a line of guidance.
private struct GuidanceRow: View {
    let symbol: String
    let title: String
    let detail: String

    var body: some View {
        HStack(alignment: .top, spacing: 14) {
            Image(systemName: symbol)
                .font(.system(size: 19, weight: .regular))
                .foregroundStyle(Color.rsGoldLight)
                .frame(width: 38, height: 38)
                .background(Color.rsOnDark.opacity(0.1), in: RoundedRectangle(cornerRadius: 11, style: .continuous))
            VStack(alignment: .leading, spacing: 2) {
                Text(title)
                    .font(RSFont.ui(.callout, weight: .semibold))
                    .foregroundStyle(Color.rsOnDark)
                Text(detail)
                    .font(RSFont.ui(.subheadline))
                    .foregroundStyle(Color.rsOnDark.opacity(0.6))
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
    }
}

#Preview {
    Color.rsBackground.ignoresSafeArea()
        .sheet(isPresented: .constant(true)) {
            GuidanceSheet()
                .presentationDetents([.medium, .large])
                .presentationDragIndicator(.visible)
        }
}
