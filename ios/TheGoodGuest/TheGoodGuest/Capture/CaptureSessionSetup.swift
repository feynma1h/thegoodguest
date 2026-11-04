/// The capture session's configuration and its RoomPlan co-run attach, in one
/// place, so every session that measures a room runs the same session the
/// production capture does (decisions 0066, 0076, 0077, 0079).
///
/// What lives here is exactly what `CaptureManager.startCapture` installs:
/// gravity-aligned world tracking, horizontal and vertical plane detection on
/// every tier, `.sceneDepth` where the hardware has it, a RoomCaptureSession
/// attached to that same ARSession after the production run, and the one-shot
/// `.sceneDepth` re-assert that cures the same-runloop attach losing depth.
/// WHEN each step happens — reset options, the attach order, the depth-loss
/// guard's trigger — stays with the caller and `RoomPlanWire`.
///
/// Read by: CaptureManager, CaptureSessionSetupTests.

import ARKit
import RoomPlan

enum CaptureSessionSetup {

    /// The production world-tracking configuration.
    static func worldTrackingConfiguration(hasLidar: Bool) -> ARWorldTrackingConfiguration {
        let config = ARWorldTrackingConfiguration()
        config.worldAlignment = .gravity
        // Plane detection on every tier (decision 0066): ARKit measures floors
        // and walls on all devices; capture ships the final anchor set.
        config.planeDetection = [.horizontal, .vertical]
        if hasLidar, ARWorldTrackingConfiguration.supportsFrameSemantics(.sceneDepth) {
            config.frameSemantics.insert(.sceneDepth)
        }
        return config
    }

    /// Whether this device runs the RoomPlan co-run at all.
    static func supportsRoomPlan(hasLidar: Bool) -> Bool {
        hasLidar && RoomCaptureSession.isSupported
    }

    /// Attach a RoomCaptureSession to `session` and run it (0076: its native
    /// configuration is a superset of ours; depth and the frame path survive).
    /// Nil where RoomPlan is unsupported (non-LiDAR, simulator).
    static func attachRoomPlan(to session: ARSession, hasLidar: Bool,
                               delegate: RoomCaptureSessionDelegate) -> RoomCaptureSession? {
        guard supportsRoomPlan(hasLidar: hasLidar) else { return nil }
        let roomCapture = RoomCaptureSession(arSession: session)
        roomCapture.delegate = delegate
        roomCapture.run(configuration: RoomCaptureSession.Configuration())
        return roomCapture
    }

    /// 0076's measured-survivable cure for a session that has never delivered
    /// depth: take the INSTALLED configuration (RoomPlan's composite when
    /// co-running), re-insert `.sceneDepth`, and re-run with no options.
    /// Returns the frame-semantics raw values before and after, or the reason
    /// it could not run.
    static func reassertSceneDepth(on session: ARSession) -> Result<(before: UInt, after: UInt), ReassertRefusal> {
        guard let config = session.configuration else { return .failure(.noInstalledConfiguration) }
        guard type(of: config).supportsFrameSemantics(.sceneDepth) else {
            return .failure(.configurationLacksSceneDepth)
        }
        let before = config.frameSemantics.rawValue
        config.frameSemantics.insert(.sceneDepth)
        session.run(config, options: [])
        return .success((before, config.frameSemantics.rawValue))
    }

    enum ReassertRefusal: Error, Equatable {
        case noInstalledConfiguration
        case configurationLacksSceneDepth
    }
}
