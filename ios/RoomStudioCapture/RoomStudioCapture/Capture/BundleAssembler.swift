/// Assembles a CaptureBundle proto from captured data and writes it to disk.
///
/// Called by CaptureManager after all JPEG/depth writes have flushed. Runs on
/// CaptureManager's jpegQueue (serial), so no concurrency concerns here.
///
/// The resulting bundle.pb is the upload artifact for P3/P4. Its GCS paths are
/// relative (e.g. "frames/000000.jpg"), matching the proto convention and the
/// backend's path-relative expectations.

import ARKit
import Darwin
import Foundation
import SwiftProtobuf
import UIKit

struct BundleAssembler {

    let bundleId:          UUID
    let tier:              RSCaptureTier
    let startedAtDeviceUs: Int64
    let endedAtDeviceUs:   Int64
    let startedAtWallUs:   Int64
    let frames:            [CapturedKeyframe]
    let outputDir:         URL

    // MARK: - Public API

    /// Assemble the CaptureBundle proto and write it to outputDir/bundle.pb.
    ///
    /// - Parameter userId: Firebase anonymous UID. Pass the cached UID from
    ///   AuthManager.shared.currentUID; pass "" if no UID is available yet
    ///   (first-ever offline launch). UploadCoordinator patches a missing
    ///   user_id in-place before building the manifest (see decision 0036).
    ///
    /// Returns the URL of the written file.
    func write(userId: String) throws -> URL {
        var bundle               = RSCaptureBundle()
        bundle.schemaVersion     = "1"
        bundle.bundleID          = bundleId.uuidString.lowercased()
        bundle.userID            = userId
        bundle.device            = makeDevice()
        bundle.tier              = tier
        bundle.startedAtDeviceUs = startedAtDeviceUs
        bundle.endedAtDeviceUs   = endedAtDeviceUs
        bundle.startedAtWallUs   = startedAtWallUs

        for kf in frames {
            var frame            = RSFrame()
            frame.frameIndex     = kf.index
            frame.timestampUs    = kf.timestampUs
            frame.rgbGcsPath     = kf.rgbRelativePath
            frame.cameraPose     = kf.pose
            frame.intrinsics     = kf.intrinsics
            frame.gravity        = kf.gravity   // zero vector stub — chunk C fills formula
            if let d = kf.depth { frame.depth = d }
            bundle.frames.append(frame)
        }

        let data = try bundle.serializedData()
        let url  = outputDir.appendingPathComponent("bundle.pb")
        // CAFUFA: consistent with frame/depth blobs and the session record (decisions 0042, 0043).
        try data.write(to: url, options: .completeFileProtectionUntilFirstUserAuthentication)
        return url
    }

    // MARK: - Device info

    private func makeDevice() -> RSDevice {
        var device          = RSDevice()
        device.hardwareID   = hardwareIdentifier()
        device.osVersion    = UIDevice.current.systemVersion
        device.appVersion   = appVersionString()
        device.hasLidar_p   = (tier == .lidarArkit || tier == .lidarRoomplan)
        // device.deviceID: Keychain UUID deferred to a later chunk.
        // Backend falls back to hardware_id while this field is empty.
        return device
    }

    /// Machine model string via sysctlbyname("hw.machine").
    /// Returns "hw.machine" (raw model identifier, e.g. "iPhone15,3").
    /// Per decision 0028: use sysctlbyname, NOT utsname — the proto comment
    /// is stale; utsname diverges on the simulator.
    private func hardwareIdentifier() -> String {
        var size = 0
        sysctlbyname("hw.machine", nil, &size, nil, 0)
        guard size > 0 else { return "unknown" }
        var buf = [CChar](repeating: 0, count: size)
        sysctlbyname("hw.machine", &buf, &size, nil, 0)
        return String(cString: buf)
    }

    /// "CFBundleShortVersionString (CFBundleVersion)", e.g. "1.0 (42)".
    private func appVersionString() -> String {
        let info    = Bundle.main.infoDictionary
        let version = info?["CFBundleShortVersionString"] as? String ?? "?"
        let build   = info?["CFBundleVersion"]            as? String ?? "?"
        return "\(version) (\(build))"
    }
}
