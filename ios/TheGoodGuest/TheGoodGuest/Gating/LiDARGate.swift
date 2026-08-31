/// LiDAR-only device gate (decision 0072). The app ships LiDAR-only for now, so
/// there is one capture path and the tier split collapses on the client. This is
/// the single runtime capability check; the spine integration shows
/// `UnsupportedDeviceView` at the root when `isSupported` is false.
///
/// Scene reconstruction (`.mesh`) is available only on LiDAR-equipped devices, so
/// it is the canonical "is this a LiDAR device" signal and also exactly the
/// capability the live capture screen needs.
///
/// NOTES:
///  • The iOS Simulator reports false here (no LiDAR), so a hard root gate would
///    hide the flow during development — the spine treats the simulator as
///    supported via `#if targetEnvironment(simulator)`. Not a release path.
///  • The App Store install-time hard gate is `UIRequiredDeviceCapabilities`
///    (add `arkit` + a LiDAR capability) in the app's Info.plist — a RELEASE step,
///    deliberately not set yet because it would also block the simulator and the
///    non-LiDAR dev device. The backend keeps all tiers; this is a client gate only.

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
