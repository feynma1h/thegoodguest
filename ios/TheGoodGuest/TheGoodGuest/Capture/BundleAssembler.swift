/// Assembles a CaptureBundle proto from captured data and writes it to disk.
///
/// Called by CaptureManager after all JPEG/depth writes have flushed. Runs on
/// CaptureManager's jpegQueue (serial), so no concurrency concerns here.
///
/// The resulting bundle.pb is the artifact the upload pipeline sends last
/// (UploadCoordinator → BlobUploadManager). Its GCS paths are relative
/// (e.g. "frames/000000.jpg"), matching the proto convention and the
/// backend's path-relative expectations.
///
/// THE TIMELINE ON THE WIRE STARTS AT CAPTURE START. The capture window and
/// every frame's timestamp are device-monotonic readings, and a reading of
/// that clock counts from device boot. The privacy manifest declares
/// SystemBootTime with 35F9.1, which lets only elapsed time between events in
/// the app leave the device, so each one is written as microseconds since
/// `startedAtDeviceUs` and `started_at_device_us` is always 0. Every reader
/// works in differences — durations and frame offsets — which come out the
/// same to the microsecond. Decision 0298.

import ARKit
import Darwin
import Foundation
import SwiftProtobuf
import UIKit

struct BundleAssembler {

    let bundleId:          UUID
    let tier:              RSCaptureTier
    /// Device-monotonic readings as CaptureManager took them, in the clock of
    /// ARFrame.timestamp — as is each frame's `timestampUs`. None is written
    /// as taken; see the file header.
    let startedAtDeviceUs: Int64
    let endedAtDeviceUs:   Int64
    let startedAtWallUs:   Int64
    let frames:            [CapturedKeyframe]
    /// The session's final plane-anchor set (decision 0066). Empty is
    /// valid — the shell degrades to "unavailable" server-side.
    let planeAnchors:      [RSPlaneAnchor]
    /// RoomPlan output (decision 0077). Non-nil iff roomplan/room.json was
    /// written — which is also exactly when tier == .lidarRoomplan; the caller
    /// (CaptureManager.assembleBundle) computes both from the same fact.
    let roomPlan:          RSRoomPlanModel?
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
        bundle.startedAtDeviceUs = sinceCaptureStart(startedAtDeviceUs)
        bundle.endedAtDeviceUs   = sinceCaptureStart(endedAtDeviceUs)
        bundle.startedAtWallUs   = startedAtWallUs

        for kf in frames {
            var frame            = RSFrame()
            frame.frameIndex     = kf.index
            frame.timestampUs    = sinceCaptureStart(kf.timestampUs)
            frame.rgbGcsPath     = kf.rgbRelativePath
            frame.cameraPose     = kf.pose
            frame.intrinsics     = kf.intrinsics
            frame.gravity        = kf.gravity
            if let d = kf.depth { frame.depth = d }
            bundle.frames.append(frame)
        }

        bundle.planeAnchors = planeAnchors
        if let roomPlan { bundle.roomPlan = roomPlan }

        let data = try bundle.serializedData()
        let url  = outputDir.appendingPathComponent("bundle.pb")
        // CAFUFA: consistent with frame/depth blobs and the session record (decisions 0042, 0043).
        try data.write(to: url, options: .completeFileProtectionUntilFirstUserAuthentication)
        return url
    }

    /// A device-monotonic reading as the bundle carries it: the time elapsed
    /// since capture start, never the reading itself.
    private func sinceCaptureStart(_ deviceUs: Int64) -> Int64 {
        deviceUs - startedAtDeviceUs
    }

    // MARK: - Device info

    private func makeDevice() -> RSDevice {
        var device          = RSDevice()
        device.hardwareID   = hardwareIdentifier()
        device.osVersion    = UIDevice.current.systemVersion
        device.appVersion   = appVersionString()
        device.hasLidar_p   = (tier == .lidarArkit || tier == .lidarRoomplan)
        device.deviceID     = DeviceIdentity.deviceId()
        return device
    }

    /// Machine model string: the value of sysctl "hw.machine" (raw model
    /// identifier, e.g. "iPhone15,3").
    /// Per decision 0028: use sysctlbyname, NOT utsname — utsname diverges
    /// on the simulator.
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
