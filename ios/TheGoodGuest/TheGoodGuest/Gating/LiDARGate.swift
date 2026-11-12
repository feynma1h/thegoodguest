/// Whether this phone measures with LiDAR. It used to be a gate (decisions 0071,
/// 0072: LiDAR-only, with `UnsupportedDeviceView` at the root); every iPhone
/// scans now, and this is the single runtime check that decides which way —
/// LiDAR and RoomPlan, or the camera — and which words the screens use.
///
/// Scene reconstruction (`.mesh`) is available only on LiDAR-equipped devices, so
/// it is the canonical "is this a LiDAR device" signal and also exactly the
/// capability the live capture screen needs.
///
/// NOTES:
///  • The iOS Simulator reports false here (no LiDAR), so a hard root gate would
///    hide the flow during development — the spine treats the simulator as
///    supported via `#if targetEnvironment(simulator)`. Not a release path.
///  • There is no install-time gate (`UIRequiredDeviceCapabilities`) and there
///    must not be one: a camera-only iPhone is a supported phone.

import ARKit

enum LiDARGate {
    /// True only on LiDAR-equipped devices (iPhone/iPad Pro). False on the
    /// simulator and non-LiDAR phones.
    ///
    /// Probes `.meshWithClassification` — the SAME capability CaptureManager's tier
    /// dispatch uses. Probing the weaker `.mesh` here would let a device pass the
    /// gate, then fall to ARKIT_ONLY at capture time while the guidance sheet
    /// promised "LiDAR READY · PRO CAPTURE".
    static var isSupported: Bool {
        ARWorldTrackingConfiguration.supportsSceneReconstruction(.meshWithClassification)
    }
}
