/// Manages an ARWorldTracking session and accumulates keyframes to a local temp directory.
///
/// P1 scope: capture-only. No proto serialization, no networking, no tier dispatch.
/// P2 will read `capturedFrames` and `bundleOutputDir` to assemble and serialize a
/// CaptureBundle proto. Gravity is intentionally omitted from CapturedKeyframe in P1
/// because PoseExtractor.gravity(from:) is a stub pending formula review (decision 0029).

import ARKit
import Combine
import CoreImage
import UIKit

// MARK: - CapturedKeyframe

/// In-memory record for one accepted keyframe. Proto-typed fields for forward
/// compatibility with P2 serialization; nothing is written to disk except the JPEG.
///
/// `gravity` is omitted until PoseExtractor.gravity(from:) is implemented and its
/// formula is confirmed (see TODO in PoseExtractor.swift, decision 0029).
struct CapturedKeyframe {
    let index: UInt32
    /// Device-monotonic microseconds — same clock as ARFrame.timestamp (CACurrentMediaTime).
    let timestampUs: Int64
    /// Relative path within the bundle output directory, e.g. "frames/000000.jpg".
    let rgbRelativePath: String
    let pose: RSPose
    let intrinsics: RSIntrinsics
}

// MARK: - WriteStats

/// Mutable counters for JPEG-write observability.
/// Accessed exclusively from jpegQueue (serial DispatchQueue), which provides
/// the synchronisation — no locks needed. Not actor-isolated by design.
/// P2 note: promote to structured logging / surface in UI when write failures
/// need operator visibility during real-bundle uploads.
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

    /// Root directory for this capture's output (temp, per-session UUID).
    /// Structure: <bundleOutputDir>/frames/NNNNNN.jpg
    private(set) var bundleOutputDir: URL?

    /// Accumulated keyframes in acceptance order. Read by P2 to build CaptureBundle.
    private(set) var capturedFrames: [CapturedKeyframe] = []

    private let arSession   = ARSession()
    private var accumulator = KeyframeAccumulator()

    /// Dedicated queue for JPEG encoding; avoids blocking the main thread.
    /// CIContext is thread-safe for concurrent rendering and is reused across frames.
    private let jpegQueue   = DispatchQueue(label: "com.roomstudio.capture.jpeg", qos: .utility)
    private let ciContext   = CIContext()
    private let writeStats  = WriteStats()

    override init() {
        super.init()
        arSession.delegate = self
    }

    // MARK: - Session control

    func startCapture() {
        let config = ARWorldTrackingConfiguration()
        config.worldAlignment = .gravity
        if ARWorldTrackingConfiguration.supportsFrameSemantics(.sceneDepth) {
            config.frameSemantics.insert(.sceneDepth)
        }
        capturedFrames  = []
        accumulator.reset()
        frameCount      = 0
        bundleOutputDir = makeOutputDir()
        // Reset write counters on the queue so any straggler from a previous
        // session has flushed before the new session's counts begin.
        let stats = writeStats
        jpegQueue.async { stats.reset() }
        arSession.run(config, options: [.resetTracking, .removeExistingAnchors])
        isRunning = true
    }

    /// Pause the session and log a write-verification summary to the console.
    /// The summary is enqueued on jpegQueue so it runs after all in-flight
    /// writes complete — on-disk count reflects actual landed files, not dispatched count.
    func stopCapture() {
        arSession.pause()
        isRunning = false
        logWriteSummary()
    }

    // MARK: - Private helpers

    private func makeOutputDir() -> URL {
        let root   = FileManager.default.temporaryDirectory
                         .appendingPathComponent(UUID().uuidString)
        let frames = root.appendingPathComponent("frames")
        try? FileManager.default.createDirectory(
            at: frames, withIntermediateDirectories: true)
        return root
    }

    private func acceptFrame(
        camera:      ARCamera,
        pixelBuffer: CVImageBuffer,
        timestamp:   TimeInterval
    ) {
        guard let outputDir = bundleOutputDir else { return }
        let index        = UInt32(capturedFrames.count)
        let relativePath = String(format: "frames/%06d.jpg", index)
        let fileURL      = outputDir.appendingPathComponent(relativePath)

        let context = ciContext
        let stats   = writeStats
        jpegQueue.async {
            let ci = CIImage(cvImageBuffer: pixelBuffer)
            guard
                let cg   = context.createCGImage(ci, from: ci.extent),
                let data = UIImage(cgImage: cg).jpegData(compressionQuality: 0.85)
            else {
                print("[CaptureManager] JPEG encode failed: \(relativePath)")
                stats.failures += 1
                return
            }
            do {
                try data.write(to: fileURL)
                stats.written += 1
            } catch {
                print("[CaptureManager] JPEG write error: \(relativePath): \(error)")
                stats.failures += 1
            }
        }

        capturedFrames.append(CapturedKeyframe(
            index:           index,
            timestampUs:     Int64(timestamp * 1_000_000),
            rgbRelativePath: relativePath,
            pose:            PoseExtractor.pose(from: camera),
            intrinsics:      PoseExtractor.intrinsics(from: camera)
        ))
        frameCount = capturedFrames.count
    }

    private func logWriteSummary() {
        let stats    = writeStats
        let dir      = bundleOutputDir
        let accepted = frameCount
        // Enqueue on jpegQueue so this block runs after all in-flight writes finish.
        jpegQueue.async {
            let framesDir = dir?.appendingPathComponent("frames")
            let onDisk: Int
            if let framesDir {
                onDisk = (try? FileManager.default.contentsOfDirectory(
                    at: framesDir, includingPropertiesForKeys: nil
                ).filter { $0.pathExtension == "jpg" }.count) ?? -1
            } else {
                onDisk = -1
            }
            print("""
            [CaptureManager] stop — write verification
              accepted : \(accepted)
              written  : \(stats.written)
              failures : \(stats.failures)
              on-disk  : \(onDisk) .jpg files
              temp-dir : \(framesDir?.path ?? "nil")
            """)
        }
    }
}

// MARK: - ARSessionDelegate

extension CaptureManager: ARSessionDelegate {

    nonisolated func session(_ session: ARSession, didUpdate frame: ARFrame) {
        // Skip frames with unreliable tracking — pose and gravity data invalid.
        switch frame.camera.trackingState {
        case .normal:              break
        case .limited, .notAvailable: return
        }

        // Extract values on this thread before hopping to MainActor.
        // ARFrame and CVImageBuffer are both reference-counted and safe to carry across.
        let camera      = frame.camera
        let pixelBuffer = frame.capturedImage
        let timestamp   = frame.timestamp

        DispatchQueue.main.async { [weak self] in
            guard let self, self.isRunning else { return }
            if self.accumulator.shouldAccept(camera: camera) {
                self.acceptFrame(
                    camera:      camera,
                    pixelBuffer: pixelBuffer,
                    timestamp:   timestamp)
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
