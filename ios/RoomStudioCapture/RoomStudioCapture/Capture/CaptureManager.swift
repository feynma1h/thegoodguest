/// Manages an ARWorldTracking session and accumulates keyframes to a local temp directory.
///
/// P2 scope: tier dispatch, depth capture (LiDAR devices), and bundle assembly.
/// P3 scope: passes Firebase anonymous UID into bundle assembly; publishes
///           assembledWithoutUserId for UploadCoordinator's backstop re-serialize.
///
/// On stop, all in-flight writes complete and BundleAssembler serializes bundle.pb
/// into the session output directory. The resulting URL is published as `bundlePath`.
///
/// Gravity is populated as a zero vector in P2; chunk C fills the formula after
/// Chat review (decision 0030).

import ARKit
import Combine
import CoreImage
import os
import UIKit

// MARK: - CapturedKeyframe

/// In-memory record for one accepted keyframe. All fields except `depth` are
/// present on every tier. `depth` is set iff the session is LiDAR tier and depth
/// was available on this ARFrame.
struct CapturedKeyframe {
    let index: UInt32
    /// Device-monotonic microseconds — same clock as ARFrame.timestamp.
    let timestampUs: Int64
    /// Relative path within the bundle output directory, e.g. "frames/000000.jpg".
    let rgbRelativePath: String
    let pose: RSPose
    let intrinsics: RSIntrinsics
    /// Zero vector in P2; formula filled in chunk C (decision 0030).
    let gravity: RSGravity
    /// Set iff LiDAR tier and frame.sceneDepth was non-nil. Contains relative
    /// paths ("depth/000000.f32", "confidence/000000.png") and depth intrinsics.
    let depth: RSDepth?
}

// MARK: - WriteStats

/// Mutable counters for JPEG/depth write observability.
/// Accessed exclusively from jpegQueue (serial DispatchQueue), which provides
/// the synchronisation — no locks needed. Not actor-isolated by design.
private final class WriteStats {
    var written  = 0
    var failures = 0
    func reset() { written = 0; failures = 0 }
}

// MARK: - CaptureManager

@MainActor
final class CaptureManager: NSObject, ObservableObject {

    @Published private(set) var frameCount: Int = 0
    @Published private(set) var isRunning: Bool = false
    @Published private(set) var trackingState: ARCamera.TrackingState = .notAvailable
    /// Most recent gravity vector in camera frame. Updated each accepted keyframe.
    /// Nil before first keyframe. Debug HUD reads this to eyeball sign/axis on device.
    @Published private(set) var lastGravity: SIMD3<Float>? = nil
    /// Set after stopCapture() and bundle assembly completes. Nil while capturing or
    /// before first stop.
    @Published private(set) var bundlePath: URL? = nil

    /// True when bundle.pb was assembled without a Firebase UID (first-ever offline
    /// launch). UploadCoordinator patches user_id in-place before building the manifest.
    /// Reset to false at the start of each capture.
    @Published private(set) var assembledWithoutUserId: Bool = false

    /// Root directory for this capture's output (temp, per-session UUID).
    /// Structure: <bundleOutputDir>/frames/NNNNNN.jpg
    ///            <bundleOutputDir>/depth/NNNNNN.f32     (LiDAR tier only)
    ///            <bundleOutputDir>/confidence/NNNNNN.png (LiDAR tier only)
    ///            <bundleOutputDir>/bundle.pb            (written on stop)
    private(set) var bundleOutputDir: URL?

    /// Accumulated keyframes in acceptance order.
    private(set) var capturedFrames: [CapturedKeyframe] = []

    /// Tier selected at session start based on hardware capability.
    private(set) var tier: RSCaptureTier = .arkitOnly

    /// Stable UUID for this capture session, generated at startCapture().
    private(set) var bundleId: UUID = UUID()

    /// Lowercased UUID string. Use this — not bundleId.uuidString — whenever
    /// constructing URL paths (upload session, GCS prefixes). The proto also
    /// emits this value, so all three legs (proto, upload session, GCS) stay
    /// consistent without each caller independently applying .lowercased().
    var bundleIdString: String { bundleId.uuidString.lowercased() }

    /// Device-monotonic microseconds (CACurrentMediaTime) at capture start/stop.
    private(set) var startedAtDeviceUs: Int64 = 0
    private(set) var endedAtDeviceUs: Int64 = 0

    /// Wall-clock microseconds (Unix epoch) at capture start. Display/sort only.
    private(set) var startedAtWallUs: Int64 = 0

    private let arSession   = ARSession()
    private var accumulator = KeyframeAccumulator()

    /// Dedicated queue for JPEG + depth encoding; avoids blocking the main thread.
    /// CIContext is thread-safe for concurrent rendering and is reused across frames.
    private let jpegQueue   = DispatchQueue(label: "com.roomstudio.capture.jpeg", qos: .utility)
    private let ciContext   = CIContext()
    private let writeStats  = WriteStats()

    // Logging privacy policy: UUIDs, blob paths, and enum values may be .public;
    // user identifiers and error payloads stay default-private (redacted in shipped logs).
    private let logger = Logger(subsystem: "com.roomstudio.RoomStudioCapture", category: "Capture")

    override init() {
        super.init()
        arSession.delegate = self
    }

    // MARK: - Session control

    func startCapture() {
        bundlePath = nil
        assembledWithoutUserId = false
        capturedFrames  = []
        accumulator.reset()
        frameCount      = 0
        bundleId        = UUID()

        // Tier dispatch: LiDAR devices use LIDAR_ARKIT; LIDAR_ROOMPLAN is deferred.
        let hasLidar = ARWorldTrackingConfiguration.supportsSceneReconstruction(.meshWithClassification)
        tier = hasLidar ? .lidarArkit : .arkitOnly

        startedAtDeviceUs = Int64(CACurrentMediaTime() * 1_000_000)
        startedAtWallUs   = Int64(Date().timeIntervalSince1970 * 1_000_000)
        bundleOutputDir   = makeOutputDir(forLidar: hasLidar)

        let stats = writeStats
        jpegQueue.async { stats.reset() }

        let config = ARWorldTrackingConfiguration()
        config.worldAlignment = .gravity
        if hasLidar, ARWorldTrackingConfiguration.supportsFrameSemantics(.sceneDepth) {
            config.frameSemantics.insert(.sceneDepth)
        }
        arSession.run(config, options: [.resetTracking, .removeExistingAnchors])
        logger.info("[CaptureManager] capture started: bundleId=\(self.bundleIdString, privacy: .public) tier=\(String(describing: self.tier), privacy: .public)")
        isRunning = true
    }

    /// Stop the session. Waits for in-flight writes, logs summary, assembles bundle.pb.
    func stopCapture() {
        arSession.pause()
        isRunning = false
        endedAtDeviceUs = Int64(CACurrentMediaTime() * 1_000_000)

        // Snapshot immutable session state before hopping off MainActor.
        // userId: read from Keychain-backed Firebase cache — offline-safe.
        // Empty string on a first-ever offline launch (backstop handled by UploadCoordinator).
        let userId    = AuthManager.shared.currentUID ?? ""
        let noUid     = userId.isEmpty
        let frames    = capturedFrames
        let outDir    = bundleOutputDir!
        let assembler = BundleAssembler(
            bundleId:          bundleId,
            tier:              tier,
            startedAtDeviceUs: startedAtDeviceUs,
            endedAtDeviceUs:   endedAtDeviceUs,
            startedAtWallUs:   startedAtWallUs,
            frames:            frames,
            outputDir:         outDir
        )
        let stats     = writeStats
        let accepted  = frameCount

        // Enqueue on jpegQueue — this block runs after all in-flight JPEG/depth writes.
        let log = logger
        jpegQueue.async { [weak self] in
            let framesDir = outDir.appendingPathComponent("frames")
            let onDisk = (try? FileManager.default.contentsOfDirectory(
                at: framesDir, includingPropertiesForKeys: nil
            ).filter { $0.pathExtension == "jpg" }.count) ?? -1
            log.info("""
            [CaptureManager] stop — write verification
              accepted : \(accepted)
              written  : \(stats.written)
              failures : \(stats.failures)
              on-disk  : \(onDisk) .jpg files
              temp-dir : \(framesDir.path, privacy: .public)
            """)

            do {
                let url = try assembler.write(userId: userId)
                log.info("[CaptureManager] bundle.pb → \(url.path, privacy: .public) (user_id: \(userId.isEmpty ? "<none — backstop pending>" : userId))")
                DispatchQueue.main.async {
                    self?.bundlePath = url
                    self?.assembledWithoutUserId = noUid
                }
            } catch {
                log.info("[CaptureManager] bundle assembly failed: \(error.localizedDescription)")
            }
        }
    }

    // MARK: - Private helpers

    private func makeOutputDir(forLidar: Bool) -> URL {
        // Write to Application Support, not temporaryDirectory. iOS can purge tmp while
        // the app is not running; a 12h+ upload window crosses that boundary reliably.
        // App Support survives kill/relaunch/storage-pressure (decision 0043).
        let root = CaptureStorageSweeper.capturesRootURL()
                       .appendingPathComponent(bundleIdString)

        var subdirs = ["frames"]
        if forLidar { subdirs += ["depth", "confidence"] }

        // Create root + subdirs with explicit CAFUFA so background URLSession delivery
        // can read blob files while the device is locked (decisions 0040 item 7, 0042).
        for sub in ([""] + subdirs) {
            let dir = sub.isEmpty ? root : root.appendingPathComponent(sub)
            try? FileManager.default.createDirectory(
                at: dir,
                withIntermediateDirectories: true,
                attributes: [.protectionKey: FileProtectionType.completeUntilFirstUserAuthentication]
            )
        }

        // Exclude from iCloud/iTunes backup: capture blobs are large and regenerable.
        // Must be set on the directory itself (not inherited from parent).
        var mutableRoot = root
        var vals = URLResourceValues()
        vals.isExcludedFromBackup = true
        try? mutableRoot.setResourceValues(vals)

        return root
    }

    private func acceptFrame(
        camera:      ARCamera,
        pixelBuffer: CVImageBuffer,
        timestamp:   TimeInterval,
        depthData:   ARDepthData?
    ) {
        guard let outputDir = bundleOutputDir else { return }
        let index        = UInt32(capturedFrames.count)
        let relativePath = String(format: "frames/%06d.jpg", index)
        let fileURL      = outputDir.appendingPathComponent(relativePath)

        // Write JPEG on jpegQueue.
        let context = ciContext
        let stats   = writeStats
        let log = logger
        jpegQueue.async {
            let ci = CIImage(cvImageBuffer: pixelBuffer)
            guard
                let cg   = context.createCGImage(ci, from: ci.extent),
                let data = UIImage(cgImage: cg).jpegData(compressionQuality: 0.85)
            else {
                log.info("[CaptureManager] JPEG encode failed: \(relativePath, privacy: .public)")
                stats.failures += 1
                return
            }
            do {
                try data.write(to: fileURL, options: .completeFileProtectionUntilFirstUserAuthentication)
                stats.written += 1
            } catch {
                log.info("[CaptureManager] JPEG write error: \(relativePath, privacy: .public): \(error.localizedDescription)")
                stats.failures += 1
            }
        }

        // Capture depth for LiDAR frames.
        let depth: RSDepth? = depthData.flatMap { dd in
            captureDepth(dd, camera: camera, index: index, outputDir: outputDir, stats: stats)
        }

        let gravityProto = PoseExtractor.gravity(from: camera)
        capturedFrames.append(CapturedKeyframe(
            index:           index,
            timestampUs:     Int64(timestamp * 1_000_000),
            rgbRelativePath: relativePath,
            pose:            PoseExtractor.pose(from: camera),
            intrinsics:      PoseExtractor.intrinsics(from: camera),
            gravity:         gravityProto,
            depth:           depth
        ))
        lastGravity = SIMD3<Float>(gravityProto.x, gravityProto.y, gravityProto.z)
        frameCount = capturedFrames.count
    }

    /// Build an RSDepth value and schedule the raster writes on jpegQueue.
    /// Returns nil if pixel buffer access fails.
    ///
    /// depthData comes from frame.sceneDepth (ARDepthData — LiDAR rear sensor).
    /// camera is the RGB ARCamera for the same frame; its intrinsics are scaled
    /// to the depth buffer dimensions to produce depth-raster intrinsics.
    private func captureDepth(
        _ depthData:  ARDepthData,
        camera:       ARCamera,
        index:        UInt32,
        outputDir:    URL,
        stats:        WriteStats
    ) -> RSDepth? {
        let depthRelPath = String(format: "depth/%06d.f32",  index)
        let confRelPath  = String(format: "confidence/%06d.png", index)

        let depthMap = depthData.depthMap       // DepthFloat32 CVPixelBuffer
        let confMap  = depthData.confidenceMap  // OneComponent8 CVPixelBuffer?

        // Compute intrinsics on the calling thread (MainActor).
        // depthData is ref-counted; pixel buffers are valid while held.
        let intrinsics = PoseExtractor.depthIntrinsics(from: camera, depthMap: depthMap)
        let w = intrinsics.width
        let h = intrinsics.height
        let depthURL   = outputDir.appendingPathComponent(depthRelPath)
        let confURL    = outputDir.appendingPathComponent(confRelPath)
        let log = logger

        jpegQueue.async {
            // Float32 raster: width*height*4 bytes, row-major, packed (no stride padding).
            if let bytes = Self.extractPackedBytes(depthMap, bytesPerPixel: 4) {
                do {
                    try bytes.write(to: depthURL, options: .completeFileProtectionUntilFirstUserAuthentication)
                } catch {
                    log.info("[CaptureManager] depth write error: \(depthRelPath, privacy: .public): \(error.localizedDescription)")
                    stats.failures += 1
                }
            }
            // Confidence raster: uint8, 0=low/1=med/2=high (ARConfidenceLevel).
            if let conf = confMap,
               let bytes = Self.extractPackedBytes(conf, bytesPerPixel: 1) {
                do {
                    try bytes.write(to: confURL, options: .completeFileProtectionUntilFirstUserAuthentication)
                } catch {
                    log.info("[CaptureManager] confidence write error: \(confRelPath, privacy: .public): \(error.localizedDescription)")
                }
            }
        }

        var depth = RSDepth()
        depth.depthGcsPath = depthRelPath
        depth.confidenceGcsPath = confRelPath
        depth.width      = w
        depth.height     = h
        depth.intrinsics = intrinsics
        return depth
    }

    /// Copy pixel buffer bytes into a packed Data (strips stride padding).
    /// Returns nil if the base address cannot be locked.
    private static func extractPackedBytes(_ buffer: CVPixelBuffer, bytesPerPixel: Int) -> Data? {
        guard CVPixelBufferLockBaseAddress(buffer, .readOnly) == kCVReturnSuccess else { return nil }
        defer { CVPixelBufferUnlockBaseAddress(buffer, .readOnly) }
        guard let base = CVPixelBufferGetBaseAddress(buffer) else { return nil }
        let w       = CVPixelBufferGetWidth(buffer)
        let h       = CVPixelBufferGetHeight(buffer)
        let stride  = CVPixelBufferGetBytesPerRow(buffer)
        let rowBytes = w * bytesPerPixel
        var out = Data(count: h * rowBytes)
        out.withUnsafeMutableBytes { dst in
            guard let dstBase = dst.baseAddress else { return }
            for row in 0..<h {
                memcpy(dstBase.advanced(by: row * rowBytes),
                       base.advanced(by: row * stride),
                       rowBytes)
            }
        }
        return out
    }
}

// MARK: - ARSessionDelegate

extension CaptureManager: ARSessionDelegate {

    nonisolated func session(_ session: ARSession, didUpdate frame: ARFrame) {
        // Skip frames with unreliable tracking — pose and gravity data invalid.
        switch frame.camera.trackingState {
        case .normal:                 break
        case .limited, .notAvailable: return
        }

        // Extract values on the ARKit thread before hopping to MainActor.
        // ARFrame and its pixel buffers are ref-counted and remain valid while held.
        let camera      = frame.camera
        let pixelBuffer = frame.capturedImage
        let timestamp   = frame.timestamp
        // sceneDepth: ARDepthData? — LiDAR rear sensor, nil on non-LiDAR devices.
        // capturedDepthData is the front TrueDepth camera; do NOT use it here.
        let depthData   = frame.sceneDepth

        DispatchQueue.main.async { [weak self] in
            guard let self, self.isRunning else { return }
            if self.accumulator.shouldAccept(camera: camera) {
                self.acceptFrame(
                    camera:      camera,
                    pixelBuffer: pixelBuffer,
                    timestamp:   timestamp,
                    depthData:   depthData)
            }
        }
    }

    nonisolated func session(
        _ session: ARSession,
        cameraDidChangeTrackingState camera: ARCamera
    ) {
        let state = camera.trackingState
        DispatchQueue.main.async { [weak self] in
            self?.trackingState = state
        }
    }
}
