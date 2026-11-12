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
    var cameraStatus: () -> AVAuthorizationStatus = {
        AVCaptureDevice.authorizationStatus(for: .video)
    }
    /// What this iPhone measures with. Every iPhone scans (operator ruling,
    /// 2026-11-10); a Pro with LiDAR measures more exactly, and the sheet says
    /// which this one is rather than badging the good case.
    var hasLidar: Bool = LiDARGate.isSupported
    /// The boxing tip appears only where boxes can be made: furniture is
    /// rebuilt from the boxes, and unboxed pieces do not appear (0323).
    var showsBoxingTip: Bool = GuidanceSheet.boxesAvailable

    @State private var permissionDenied = false
    @Environment(\.scenePhase) private var scenePhase

    static var boxesAvailable: Bool {
        #if DEBUG
        return LiveBoxesFeature.isEnabled
        #else
        return false
        #endif
    }

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 0) {
                    RSScreenTitle("Before you start")
                    VStack(alignment: .leading, spacing: 18) {
                        GuidanceRow(symbol: "arrow.up.and.down.and.arrow.left.and.right",
                                    title: "Move slowly, keep it level",
                                    detail: "A steady walking pace. Sweep the phone gently across every wall.")
                        GuidanceRow(symbol: "viewfinder",
                                    title: "Get every corner and the floor",
                                    detail: "Corners are what tell me the room’s true shape.")
                        GuidanceRow(symbol: "sun.max",
                                    title: "Turn the lights on",
                                    detail: "Even light helps me see truly. I’ll tell you if it gets too dark.")
                        GuidanceRow(symbol: "person.2",
                                    title: "Ask people to step out",
                                    detail: "Anyone standing in the room gets measured as part of it.")
                        if showsBoxingTip {
                            GuidanceRow(symbol: "cube",
                                        title: "Tap a dot to box a piece",
                                        detail: "Box the furniture you want rebuilt, then walk round it.")
                        }
                    }
                    .padding(.top, 22)
                    VStack(alignment: .leading, spacing: 10) {
                        fact(symbol: hasLidar ? "dot.radiowaves.left.and.right" : "camera",
                             text: hasLidar
                                ? "This iPhone measures with LiDAR, its depth sensor."
                                : "This iPhone measures with its camera. Pro models with LiDAR measure walls and sizes more exactly.")
                        fact(symbol: "lock",
                             text: "Nothing leaves your phone until you send it.")
                    }
                    .padding(.top, 18)
                    .overlay(alignment: .top) {
                        Rectangle().fill(Color.rsHairline).frame(height: 1).offset(y: 0)
                    }
                    .padding(.top, 20)
                }
                .rsScreenContent()
            }
            .background(GroundBackground())
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button(action: onDismiss) { Image(systemName: "xmark") }
                        .accessibilityLabel("Close")
                }
            }
            .safeAreaInset(edge: .bottom, spacing: 0) {
                RSPinnedBar {
                    if permissionDenied {
                        Label {
                            Text("The camera is off for \(RSBrand.name). Turn it on in Settings, then come back.")
                                .rsFont(.ui, size: 15, weight: .semibold)
                                .foregroundStyle(Color.rsInk)
                                .fixedSize(horizontal: false, vertical: true)
                        } icon: {
                            Image(systemName: "exclamationmark.circle").foregroundStyle(Color.rsInk)
                        }
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .padding(.bottom, 10)
                    }
                    startButton
                }
            }
        }
        .tint(Color.rsInk)
        .onAppear { permissionDenied = Self.isDenied(cameraStatus()) }
        .onChange(of: scenePhase) { _, phase in
            guard phase == .active else { return }
            permissionDenied = Self.isDenied(cameraStatus())
        }
    }

    private func fact(symbol: String, text: String) -> some View {
        Label {
            Text(text)
                .rsFont(.ui, size: 14)
                .foregroundStyle(Color.rsInk2)
                .fixedSize(horizontal: false, vertical: true)
        } icon: {
            Image(systemName: symbol)
                .font(.system(size: 14))
                .foregroundStyle(Color.rsInk)
        }
    }

    @ViewBuilder
    private var startButton: some View {
        if permissionDenied {
            Button("Open Settings") { openSettings() }
                .buttonStyle(RSPrimaryButtonStyle())
        } else {
            Button("Start scanning") { requestCameraThenStart() }
                .buttonStyle(RSPrimaryButtonStyle())
        }
    }

    static func isDenied(_ status: AVAuthorizationStatus) -> Bool {
        status == .denied || status == .restricted
    }

    private func requestCameraThenStart() {
        switch cameraStatus() {
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
                .font(.system(size: 17, weight: .regular))
                .foregroundStyle(Color.rsInk)
                .frame(width: 40, height: 40)
                .background(Color.rsInset, in: Circle())
                .accessibilityHidden(true)
            VStack(alignment: .leading, spacing: 2) {
                Text(title)
                    .rsFont(.ui, size: 16, weight: .semibold)
                    .foregroundStyle(Color.rsInk)
                    .fixedSize(horizontal: false, vertical: true)
                Text(detail)
                    .rsFont(.ui, size: 14)
                    .foregroundStyle(Color.rsInk2)
                    .fixedSize(horizontal: false, vertical: true)
            }
            .padding(.top, 2)
        }
        .accessibilityElement(children: .combine)
    }
}

#Preview {
    Color.rsGround.ignoresSafeArea()
        .sheet(isPresented: .constant(true)) {
            GuidanceSheet()
                .presentationDetents([.medium, .large])
                .presentationDragIndicator(.visible)
        }
}
