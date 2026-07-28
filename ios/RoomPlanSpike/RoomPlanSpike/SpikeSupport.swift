/// THROWAWAY SPIKE (board item 3 → board 7 design session input). Ships nothing.
///
/// Support types for the RoomPlan co-run spike: on-disk run recorder (NDJSON
/// events + keyframe stream + JSON artifacts), the ARSessionDelegate interposer
/// used when RoomCaptureSession steals the shared session's delegate, the
/// production keyframe filter (math copied from
/// ios/RoomStudioCapture/.../KeyframeAccumulator.swift so Q2's "can the
/// production pattern run" is answered with the production pattern itself),
/// and small JSON-safe math helpers.
///
/// Read by: the board-7 RoomPlan integration design session (via the decision
/// note + READY REPORT this spike produces). Not linked into any product.

import ARKit
import Foundation
import UIKit

// MARK: - JSON-safe rounding helpers

/// Round to 3 decimals, clamping non-finite values so JSONSerialization never
/// throws on a NaN that ARKit handed us mid-initialization.
func r3(_ x: Float) -> Double { r3(Double(x)) }
func r3(_ x: Double) -> Double {
    guard x.isFinite else { return -999.0 }
    return (x * 1000).rounded() / 1000
}

func flat16(_ m: simd_float4x4) -> [Double] {
    [m.columns.0, m.columns.1, m.columns.2, m.columns.3].flatMap {
        [r3($0.x), r3($0.y), r3($0.z), r3($0.w)]
    }
}

/// Heading of the local +X axis projected on the world XZ plane, degrees.
/// World yaw origin is arbitrary (ARKit heading at session start); RELATIVE
/// yaws between objects/walls are the meaningful quantity offline.
func yawDeg(_ m: simd_float4x4) -> Double {
    let x = m.columns.0
    let deg = atan2(Double(-x.z), Double(x.x)) * 180.0 / .pi
    return deg.isFinite ? (deg * 10).rounded() / 10 : -999
}

// MARK: - SpikeKeyframer

/// Pose-delta keyframe filter — verbatim math from the production
/// KeyframeAccumulator (10 cm / 5°) so the spike's keyframe stream is the
/// production keyframe stream.
struct SpikeKeyframer {
    var translationThreshold: Float = 0.10
    var rotationThreshold: Float = 5.0 * .pi / 180.0

    private var lastPosition: simd_float3?
    private var lastQuat: simd_quatf?

    mutating func shouldAccept(camera: ARCamera) -> Bool {
        let t = camera.transform
        let pos = simd_float3(t.columns.3.x, t.columns.3.y, t.columns.3.z)
        let q = simd_quaternion(t)

        guard let lastPos = lastPosition, let lastQ = lastQuat else {
            lastPosition = pos
            lastQuat = q
            return true
        }

        let translationDelta = simd_length(pos - lastPos)
        let dot = min(abs(simd_dot(q.vector, lastQ.vector)), 1.0)
        let rotationDelta = 2.0 * acos(dot)

        guard translationDelta >= translationThreshold ||
              rotationDelta >= rotationThreshold
        else { return false }

        lastPosition = pos
        lastQuat = q
        return true
    }

    mutating func reset() {
        lastPosition = nil
        lastQuat = nil
    }
}

// MARK: - RunRecorder

/// One instance per run. Owns the run directory and a serial IO queue
/// (mirroring the production jpegQueue pattern). Everything lands under
/// Documents/runs/<runID>/ so `devicectl device copy from` can pull it.
///
/// Streams: events.ndjson (every instrument event), keyframes.ndjson
/// (production-shaped keyframe records). One-shot JSONs (captured rooms,
/// plane anchors, run summary) are written independently and remain writable
/// after closeStreams() — the RoomBuilder task may finish after finalize.
final class RunRecorder {

    let runDir: URL
    let runID: String

    private let ioQueue = DispatchQueue(label: "com.roomstudio.spike.io", qos: .utility)
    private var eventsHandle: FileHandle?
    private var keyframesHandle: FileHandle?
    private var streamsClosed = false

    // Mutated on ioQueue only (production WriteStats pattern).
    private var jpegWritten = 0
    private var jpegFailed = 0
    private var depthWritten = 0
    private var depthFailed = 0

    /// Event types mirrored to stdout so `devicectl ... launch --console`
    /// gives the Mac a live view of the run.
    private static let printedTypes: Set<String> = [
        "run_start", "run_end", "config_run", "config_changed",
        "delegate_changed", "pre_rp_construct", "post_rp_construct",
        "rp_run_calling", "post_rp_run", "rp_did_start",
        "reassert_depth_pre", "reassert_depth_post", "reassert_refused",
        "interposer_engaged", "take_delegate", "rp_stop_calling", "rp_end",
        "room_built", "build_failed", "export_failed",
        "leak_guard_tripped", "leak_released", "retention_started",
        "phase", "tick", "instruction", "ar_error", "ar_interruption",
        "tracking_state", "frame_flow_note",
    ]

    init?(mode: String) {
        let fm = FileManager.default
        guard let docs = fm.urls(for: .documentDirectory, in: .userDomainMask).first else { return nil }
        let df = DateFormatter()
        df.dateFormat = "yyyyMMdd-HHmmss"
        df.locale = Locale(identifier: "en_US_POSIX")
        runID = "\(mode)-\(df.string(from: Date()))"
        runDir = docs.appendingPathComponent("runs").appendingPathComponent(runID)

        for sub in ["", "frames", "depth", "confidence"] {
            let dir = sub.isEmpty ? runDir : runDir.appendingPathComponent(sub)
            do {
                try fm.createDirectory(at: dir, withIntermediateDirectories: true)
            } catch {
                return nil
            }
        }
        for name in ["events.ndjson", "keyframes.ndjson"] {
            fm.createFile(atPath: runDir.appendingPathComponent(name).path, contents: nil)
        }
        eventsHandle = FileHandle(forWritingAtPath: runDir.appendingPathComponent("events.ndjson").path)
        keyframesHandle = FileHandle(forWritingAtPath: runDir.appendingPathComponent("keyframes.ndjson").path)
    }

    // MARK: streams

    func event(_ obj: [String: Any]) {
        let type = (obj["type"] as? String) ?? "?"
        let shouldPrint = Self.printedTypes.contains(type)
        ioQueue.async { [weak self] in
            guard let self else { return }
            let line = Self.jsonLine(obj)
            if shouldPrint { print("[spike] \(line)") }
            guard !self.streamsClosed, let h = self.eventsHandle else { return }
            h.write(Data((line + "\n").utf8))
        }
    }

    func keyframeLine(_ obj: [String: Any]) {
        ioQueue.async { [weak self] in
            guard let self, !self.streamsClosed, let h = self.keyframesHandle else { return }
            h.write(Data((Self.jsonLine(obj) + "\n").utf8))
        }
    }

    /// Periodic durability point — called from the 1 Hz tick so a crash loses
    /// at most ~a second of events.
    func sync() {
        ioQueue.async { [weak self] in
            guard let self else { return }
            try? self.eventsHandle?.synchronize()
            try? self.keyframesHandle?.synchronize()
        }
    }

    func closeStreams() {
        ioQueue.async { [weak self] in
            guard let self else { return }
            self.streamsClosed = true
            try? self.eventsHandle?.close()
            try? self.keyframesHandle?.close()
            self.eventsHandle = nil
            self.keyframesHandle = nil
        }
    }

    // MARK: blobs

    /// JPEG encode + write, production-identical path (CIImage → CGImage →
    /// UIImage.jpegData(0.85)) on the serial IO queue.
    func writeJPEG(_ pixelBuffer: CVPixelBuffer, relativePath: String, ciContext: CIContext) {
        let url = runDir.appendingPathComponent(relativePath)
        ioQueue.async { [weak self] in
            let ci = CIImage(cvImageBuffer: pixelBuffer)
            guard
                let cg = ciContext.createCGImage(ci, from: ci.extent),
                let data = UIImage(cgImage: cg).jpegData(compressionQuality: 0.85)
            else {
                self?.jpegFailed += 1
                return
            }
            do {
                try data.write(to: url)
                self?.jpegWritten += 1
            } catch {
                self?.jpegFailed += 1
            }
        }
    }

    /// Packed float32 depth + uint8 confidence rasters, production packing
    /// (row-major, stride stripped).
    func writeDepth(_ depthMap: CVPixelBuffer, confidenceMap: CVPixelBuffer?,
                    depthRelPath: String, confRelPath: String) {
        let depthURL = runDir.appendingPathComponent(depthRelPath)
        let confURL = runDir.appendingPathComponent(confRelPath)
        ioQueue.async { [weak self] in
            if let bytes = Self.extractPackedBytes(depthMap, bytesPerPixel: 4) {
                do {
                    try bytes.write(to: depthURL)
                    self?.depthWritten += 1
                } catch {
                    self?.depthFailed += 1
                }
            } else {
                self?.depthFailed += 1
            }
            if let conf = confidenceMap,
               let bytes = Self.extractPackedBytes(conf, bytesPerPixel: 1) {
                try? bytes.write(to: confURL)
            }
        }
    }

    /// One-shot artifact write (captured rooms, plane anchors, summary).
    /// Safe after closeStreams().
    func writeJSON(_ data: Data, name: String) {
        let url = runDir.appendingPathComponent(name)
        ioQueue.async {
            try? data.write(to: url)
        }
    }

    func writeJSONObject(_ obj: Any, name: String) {
        let url = runDir.appendingPathComponent(name)
        ioQueue.async {
            guard JSONSerialization.isValidJSONObject(obj),
                  let data = try? JSONSerialization.data(
                    withJSONObject: obj, options: [.prettyPrinted, .sortedKeys])
            else { return }
            try? data.write(to: url)
        }
    }

    /// Synchronous read of blob-write counters (call sparingly, e.g. finalize).
    func blobStats() -> (jpegWritten: Int, jpegFailed: Int, depthWritten: Int, depthFailed: Int) {
        ioQueue.sync { (jpegWritten, jpegFailed, depthWritten, depthFailed) }
    }

    // MARK: helpers

    private static func jsonLine(_ obj: [String: Any]) -> String {
        guard JSONSerialization.isValidJSONObject(obj),
              let data = try? JSONSerialization.data(withJSONObject: obj, options: [.sortedKeys]),
              let s = String(data: data, encoding: .utf8)
        else {
            return #"{"type":"serialization_error"}"#
        }
        return s
    }

    /// Verbatim from production CaptureManager.extractPackedBytes.
    static func extractPackedBytes(_ buffer: CVPixelBuffer, bytesPerPixel: Int) -> Data? {
        guard CVPixelBufferLockBaseAddress(buffer, .readOnly) == kCVReturnSuccess else { return nil }
        defer { CVPixelBufferUnlockBaseAddress(buffer, .readOnly) }
        guard let base = CVPixelBufferGetBaseAddress(buffer) else { return nil }
        let w = CVPixelBufferGetWidth(buffer)
        let h = CVPixelBufferGetHeight(buffer)
        let stride = CVPixelBufferGetBytesPerRow(buffer)
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

// MARK: - FrameTapProxy

/// ARSessionDelegate interposer. If RoomCaptureSession installs itself (or an
/// internal object) as the shared ARSession's delegate — evicting the app —
/// this proxy is swapped in: it taps the frame/observer callbacks the spike
/// instruments and forwards EVERYTHING (including selectors it doesn't
/// implement, via forwardingTarget) to RoomPlan's evicted delegate so the scan
/// keeps working.
///
/// forwardTarget is held STRONGLY on purpose: ARSession.delegate is weak, and
/// if RoomPlan's object had no other strong owner it would deallocate the
/// moment we replace the delegate. The proxy is released at run reset.
final class FrameTapProxy: NSObject, ARSessionDelegate {

    let forwardTarget: (any ARSessionDelegate)?
    weak var tap: SpikeController?

    init(forwardTo target: (any ARSessionDelegate)?, tap: SpikeController) {
        self.forwardTarget = target
        self.tap = tap
        super.init()
    }

    override func responds(to aSelector: Selector!) -> Bool {
        if super.responds(to: aSelector) { return true }
        if let f = forwardTarget as? NSObject { return f.responds(to: aSelector) }
        return false
    }

    override func forwardingTarget(for aSelector: Selector!) -> Any? {
        if let f = forwardTarget as? NSObject, f.responds(to: aSelector) { return f }
        return super.forwardingTarget(for: aSelector)
    }

    // Explicitly implemented (tap + forward). Everything else auto-forwards.

    func session(_ session: ARSession, didUpdate frame: ARFrame) {
        tap?.tapFrame(session, frame)
        forwardTarget?.session?(session, didUpdate: frame)
    }

    func session(_ session: ARSession, cameraDidChangeTrackingState camera: ARCamera) {
        tap?.tapTrackingState(camera)
        forwardTarget?.session?(session, cameraDidChangeTrackingState: camera)
    }

    func session(_ session: ARSession, didFailWithError error: Error) {
        tap?.tapSessionError(error)
        forwardTarget?.session?(session, didFailWithError: error)
    }

    func sessionWasInterrupted(_ session: ARSession) {
        tap?.tapInterruption(began: true)
        forwardTarget?.sessionWasInterrupted?(session)
    }

    func sessionInterruptionEnded(_ session: ARSession) {
        tap?.tapInterruption(began: false)
        forwardTarget?.sessionInterruptionEnded?(session)
    }
}

// MARK: - Memory footprint

/// phys_footprint in MB via TASK_VM_INFO — the number Xcode's memory gauge
/// shows. Returns -1 on failure.
func memoryFootprintMB() -> Double {
    var info = task_vm_info_data_t()
    var count = mach_msg_type_number_t(
        MemoryLayout<task_vm_info_data_t>.size / MemoryLayout<natural_t>.size)
    let kr = withUnsafeMutablePointer(to: &info) {
        $0.withMemoryRebound(to: integer_t.self, capacity: Int(count)) {
            task_info(mach_task_self_, task_flavor_t(TASK_VM_INFO), $0, &count)
        }
    }
    guard kr == KERN_SUCCESS else { return -1 }
    return Double(info.phys_footprint) / 1_048_576.0
}
