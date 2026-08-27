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
/// Presented FULL SCREEN. It was a half-height sheet, which framed the last
/// thing a person reads before walking a room for two minutes as a disclosure
/// to skim past. Full screen also removes the drag-to-dismiss it used to have,
/// so the cross at the top right is the only way out — which is the same shape
/// every other screen in the app has.
///
/// Calls `onStart` once camera access is granted.

import AVFoundation
import SwiftUI

struct GuidanceSheet: View {
    var onStart: () -> Void = {}
    var onDismiss: () -> Void = {}

    @State private var permissionDenied = false
    @Environment(\.scenePhase) private var scenePhase

    var body: some View {
        // Scrollable: at accessibility sizes this content exceeds even the .large
        // detent, and without a scroll region the header, the close button and the
        // rows overflow BOTH edges of the sheet — leaving no way to start a scan.
        ScrollView {
            VStack(alignment: .leading, spacing: 0) {
            header

            proChip
                .rsBelowHeader()

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
                // The capture-time half of the person-observation gap. The server
                // suppresses people it can detect, but a shoulder at the frame edge
                // or an arm across a wall is not a person to a detector — it is just
                // that wall's colour, and it ships as the wall's colour. Asking here
                // is the only thing that catches those, and the WHY earns the ask:
                // stated as what it costs the ROOM, not as a warning about privacy,
                // which would make the guest sound like it is watching people.
                GuidanceRow(
                    symbol: "person.2.slash",
                    title: "Ask people to step out",
                    detail: "Anyone standing in the room gets measured as part of it — I'd read them as a wall. A minute alone in here and the room comes back as itself."
                )
            }
            .padding(.top, 24)

            privacyLine
                .padding(.top, 20)
                .padding(.bottom, 12)
            }
            .padding(.horizontal, RSScreen.horizontal)
            .frame(maxWidth: .infinity, alignment: .topLeading)
        }
        .safeAreaInset(edge: .bottom) {
            // Pinned OUTSIDE the scroll region: the one action this sheet exists for
            // must stay on screen at every text size.
            startButton
                .padding(.horizontal, RSScreen.horizontal)
                .rsActionBar()
                .background(Color.rsCaptureRaised)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .background(Color.rsCaptureRaised.ignoresSafeArea())
        // Coming back from Settings with permission granted must clear the denied
        // state; otherwise the sheet keeps offering "Open Settings" forever.
        .onChange(of: scenePhase) { _, phase in
            guard phase == .active else { return }
            permissionDenied = AVCaptureDevice.authorizationStatus(for: .video) == .denied
                || AVCaptureDevice.authorizationStatus(for: .video) == .restricted
        }
    }

    // MARK: - Pieces

    /// The shared header band, on the dark surface. The title is set at the
    /// same size as every other screen's now that this is a screen rather than
    /// a card — it was two-thirds that when it was something you peered at over
    /// the top of home.
    private var header: some View {
        ScreenHeaderFrame {
            Text("Before you start")
                .rsFont(.display, size: 22, weight: .medium, maxSize: 30)
                .foregroundStyle(Color.rsOnDark)
                .fixedSize(horizontal: false, vertical: true)
            Spacer(minLength: 8)
            Button(action: onDismiss) {
                Image(systemName: "xmark")
                    .font(.system(size: 14, weight: .semibold))
                    .foregroundStyle(Color.rsOnDark)
                    .frame(width: 32, height: 32)
                    .background(Color.rsOnDark.opacity(0.12), in: Circle())
                    .contentShape(Circle())
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
                // No glyph, matching home's scan action. Apple's viewfinder was
                // the generic stock symbol on both, and the two buttons that
                // start a capture should look like each other.
                Text("Start scanning")
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
                    .fixedSize(horizontal: false, vertical: true)
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
