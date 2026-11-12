/// The camera behind the scan screen, in every build.
///
/// Until the 2026-11-10 redesign a Release scan showed no camera at all — the
/// floor plan drew itself on black — and only Debug builds, through live boxes,
/// showed what the phone was pointing at. The redesign makes the camera the
/// scan screen on every iPhone: a phone without LiDAR has no live plan to show,
/// and on a LiDAR phone the plan becomes a small card over the camera.
///
/// It only RENDERS the capture's own session: `automaticallyConfigureSession`
/// is off, so nothing here runs, reconfigures or pauses the ARSession the
/// capture records from, and the bundle is exactly what it was without it.
/// Nothing is detected here; live boxes (Debug only, decision 0295) supply
/// their own host with the same rendering.
///
/// Read by: RootFlowView (as the scan screen's camera layer).

import ARKit
import RealityKit
import SwiftUI

struct CameraFeedView: UIViewRepresentable {
    let session: ARSession

    func makeUIView(context: Context) -> ARView {
        let view = ARView(frame: .zero, cameraMode: .ar, automaticallyConfigureSession: false)
        view.session = session
        view.renderOptions = [.disableMotionBlur, .disableDepthOfField, .disableCameraGrain,
                              .disableHDR, .disableGroundingShadows, .disableAREnvironmentLighting,
                              .disablePersonOcclusion]
        view.environment.sceneUnderstanding.options = []
        return view
    }

    func updateUIView(_ uiView: ARView, context: Context) {
        if uiView.session !== session { uiView.session = session }
    }
}
