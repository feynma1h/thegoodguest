/// THROWAWAY SPIKE (board item 3 → board 7 design session input). Ships nothing.
///
/// The instrumentation core of the RoomPlan co-run spike. Owns ONE shared
/// ARSession configured exactly like the production CaptureManager
/// (ARWorldTrackingConfiguration, .gravity alignment, horizontal+vertical
/// plane detection, .sceneDepth), attaches a RoomCaptureSession(arSession:)
/// to it mid-flight, and measures what survives:
///
///   Q1  does frame.sceneDepth keep arriving under an active RoomPlan scan,
///       what does RoomPlan's installed configuration look like, and does a
///       mid-scan re-run that re-inserts .sceneDepth restore depth without
///       killing the scan ("Re-assert depth" button);
///   Q2  does the production keyframe pattern (pose-delta filter → JPEG +
///       depth rasters) keep running off the shared session — including who
///       owns ARSession.delegate (auto-interposer if RoomPlan steals it);
///   Q3  memory under co-run (1 Hz phys_footprint) plus a deliberate
///       ARFrame-retention leak mode with an auto-release guard;
///   Q4-6 CapturedRoom census stream (didAdd/didChange/didUpdate timeline)
///       and final CapturedRoom JSON + USDZ exports for the operator walk.
///
/// Every observation lands in Documents/runs/<runID>/ via RunRecorder; key
/// events mirror to stdout for `devicectl ... launch --console`.
///
/// Read by: the board-7 RoomPlan integration design session. Not product code.

import ARKit
import Combine
import CoreImage
import Foundation
import RoomPlan
import UIKit

// MARK: - Mode / Phase

enum SpikeMode: String, CaseIterable, Identifiable {
    case probe
    case solo
    case leak

    var id: String { rawValue }
    var label: String {
        switch self {
        case .probe: return "Probe co-run"
        case .solo: return "Solo baseline"
        case .leak: return "Leak mode"
        }
    }
}

enum SpikePhase: String {
    case idle
    case solo
    case rp
    case rpReasserted = "rp_reasserted"
    case rpStopped = "rp_stopped"
    case postStopReassert = "post_stop_reassert"
    case finished

    /// Frames are counted in every phase where the ARSession may be running.
    var isCapturing: Bool { self != .idle && self != .finished }
}

// MARK: - SpikeController

@MainActor
final class SpikeController: NSObject, ObservableObject {

    // Operator-set before a run.
    @Published var mode: SpikeMode = .probe
    /// When true (probe/leak), the ARSession is NOT pre-run with the production
    /// config; RoomCaptureSession bootstraps the never-run shared session
    /// itself. Probes the alternative ordering.
    @Published var rpFirst = false

    // Live readouts.
    @Published private(set) var phase: SpikePhase = .idle
    @Published private(set) var statusLines: [String] = ["Ready."]
    @Published private(set) var depthBadge: String = "DEPTH —"
    @Published private(set) var depthGood: Bool? = nil
    @Published private(set) var lastInstruction: String = "—"
    @Published private(set) var trackingStateUI: String = "—"
    @Published private(set) var objectsCountUI: Int = 0
    @Published private(set) var wallsCountUI: Int = 0
    @Published private(set) var summary: String = ""
    @Published private(set) var objectRows: [String] = []

    let arSession = ARSession()

    private var captureSession: RoomCaptureSession?
    private var recorder: RunRecorder?
    private var keyframer = SpikeKeyframer()
    private let ciContext = CIContext()
    private var tickTimer: Timer?
    private var runToken = UUID()

    // Frame statistics (MainActor-mutated, matching the production
    // per-frame main hop).
    private var runStart: TimeInterval = 0
    private var framesInTick = 0
    private var depthInTick = 0
    private var smoothedInTick = 0
    private var totalFrames = 0
    private var totalDepthFrames = 0
    private var framesSinceRPStart = 0
    private var keyframeCount = 0
    private var lastConfigDesc = ""
    private var lastDelegateDesc = ""
    /// Per-frame detail rows are logged until this deadline; bumped +6 s at
    /// every interesting transition so strip/restore edges are frame-accurate.
    private var transitionDetailUntil: TimeInterval = 0
    private var baselineFootprint: Double = 0

    // RoomPlan bookkeeping.
    private var rpStartedAt: TimeInterval = 0
    private var rpEndReceived = false
    private var builderDone = false
    private var lastRoom: CapturedRoom?
    private var builtRoom: CapturedRoom?
    private var roomUpdateCount = 0
    private var lastRoomDumpAt: TimeInterval = 0

    // Delegate interposition.
    private var interposer: FrameTapProxy?

    // Leak mode.
    private var retention = false
    private var retainedFrames: [ARFrame] = []
    private var retentionBaselineMB: Double = 0
    private var retentionStartedAt: TimeInterval = 0
    private var lowFpsTicks = 0

    override init() {
        super.init()
        arSession.delegate = self
    }

    // MARK: - Run lifecycle

    func startRun() {
        guard phase == .idle else { return }
        guard let rec = RunRecorder(mode: mode.rawValue) else {
            statusLines = ["FAILED to create run directory"]
            return
        }
        recorder = rec
        runToken = UUID()
        keyframer.reset()
        resetCounters()
        runStart = CACurrentMediaTime()
        baselineFootprint = memoryFootprintMB()
        UIApplication.shared.isIdleTimerDisabled = true

        // Reclaim the delegate from any previous run's proxy.
        arSession.delegate = self
        interposer = nil

        var systemInfo = utsname()
        uname(&systemInfo)
        let machine = withUnsafeBytes(of: &systemInfo.machine) { raw in
            String(decoding: raw.prefix(while: { $0 != 0 }), as: UTF8.self)
        }
        rec.event([
            "type": "run_start", "run_id": rec.runID, "mode": mode.rawValue,
            "rp_first": rpFirst, "machine": machine,
            "os": UIDevice.current.systemVersion,
            "wall": ISO8601DateFormatter().string(from: Date()),
            "rp_supported": RoomCaptureSession.isSupported,
            "baseline_mem_mb": r3(baselineFootprint),
        ])

        if mode == .solo || !rpFirst {
            runProductionConfig(reset: true, label: "solo_start")
        } else {
            rec.event(["type": "frame_flow_note", "t": tNow(),
                       "note": "rp_first: ARSession left un-run; RoomPlan bootstraps it"])
        }
        setPhase(.solo)

        tickTimer = Timer.scheduledTimer(withTimeInterval: 1.0, repeats: true) { [weak self] _ in
            DispatchQueue.main.async { self?.tick() }
        }
    }

    /// The production CaptureManager configuration, verbatim.
    private func runProductionConfig(reset: Bool, label: String) {
        let config = ARWorldTrackingConfiguration()
        config.worldAlignment = .gravity
        config.planeDetection = [.horizontal, .vertical]
        if ARWorldTrackingConfiguration.supportsFrameSemantics(.sceneDepth) {
            config.frameSemantics.insert(.sceneDepth)
        }
        let options: ARSession.RunOptions = reset ? [.resetTracking, .removeExistingAnchors] : []
        arSession.run(config, options: options)
        recorder?.event(["type": "config_run", "t": tNow(), "which": "production",
                         "label": label, "reset": reset,
                         "config": Self.describeConfig(config)])
        markTransition(label)
    }

    func beginRoomScan() {
        guard phase == .solo, mode != .solo else { return }
        guard RoomCaptureSession.isSupported else {
            recorder?.event(["type": "frame_flow_note", "t": tNow(),
                             "note": "RoomCaptureSession.isSupported == false"])
            statusLines = ["RoomPlan NOT supported on this device"]
            return
        }
        recorder?.event(["type": "pre_rp_construct", "t": tNow(),
                         "delegate": describeDelegate(),
                         "config": Self.describeConfig(arSession.configuration)])
        let cs = RoomCaptureSession(arSession: arSession)
        captureSession = cs
        recorder?.event(["type": "post_rp_construct", "t": tNow(),
                         "same_ar_session": cs.arSession === arSession,
                         "delegate": describeDelegate(),
                         "config": Self.describeConfig(arSession.configuration)])
        cs.delegate = self
        let rpConfig = RoomCaptureSession.Configuration()
        recorder?.event(["type": "rp_run_calling", "t": tNow(),
                         "coaching": rpConfig.isCoachingEnabled])
        cs.run(configuration: rpConfig)
        rpStartedAt = CACurrentMediaTime()
        framesSinceRPStart = 0
        rpEndReceived = false
        recorder?.event(["type": "post_rp_run", "t": tNow(),
                         "delegate": describeDelegate(),
                         "config": Self.describeConfig(arSession.configuration)])
        markTransition("rp_run")
        setPhase(.rp)

        if mode == .leak {
            retention = true
            retentionBaselineMB = memoryFootprintMB()
            retentionStartedAt = CACurrentMediaTime()
            recorder?.event(["type": "retention_started", "t": tNow(),
                             "baseline_mb": r3(retentionBaselineMB)])
        }
    }

    /// Q1's workaround probe: take RoomPlan's installed configuration (a copy),
    /// re-insert .sceneDepth, and re-run WITHOUT reset options. Measures both
    /// whether depth returns and whether the scan survives.
    func reassertDepth() {
        guard phase == .rp || phase == .rpReasserted else { return }
        guard let cfg = arSession.configuration else {
            recorder?.event(["type": "reassert_refused", "t": tNow(),
                             "reason": "configuration nil"])
            return
        }
        recorder?.event(["type": "reassert_depth_pre", "t": tNow(),
                         "config": Self.describeConfig(cfg)])
        guard type(of: cfg).supportsFrameSemantics(.sceneDepth) else {
            recorder?.event(["type": "reassert_refused", "t": tNow(),
                             "reason": "config class does not support sceneDepth",
                             "class": String(describing: type(of: cfg))])
            return
        }
        cfg.frameSemantics.insert(.sceneDepth)
        arSession.run(cfg, options: [])
        recorder?.event(["type": "reassert_depth_post", "t": tNow(),
                         "config": Self.describeConfig(arSession.configuration)])
        markTransition("reassert_depth")
        setPhase(.rpReasserted)
    }

    /// Manual interposition (the 1 Hz tick also auto-engages 3 s after RP
    /// start if our frame callbacks went silent and the delegate is foreign).
    func engageInterposerManually() {
        engageInterposer(reason: "manual")
    }

    /// Blunt fallback probe: point the delegate straight back at the spike and
    /// see whether RoomPlan keeps scanning (census continuing) without it.
    func takeDelegateBack() {
        let prev = describeDelegate()
        arSession.delegate = self
        interposer = nil
        recorder?.event(["type": "take_delegate", "t": tNow(), "prev": prev])
        markTransition("take_delegate")
    }

    func finishScan() {
        switch phase {
        case .rp, .rpReasserted:
            recorder?.event(["type": "rp_stop_calling", "t": tNow(),
                             "rp_end_already": rpEndReceived])
            if !rpEndReceived {
                captureSession?.stop(pauseARSession: false)
            }
            markTransition("rp_stop")
            setPhase(.rpStopped)
            // Post-stop chain: 4 s of as-left flow, then production config
            // re-assert (does depth come back for a post-scan capture leg?),
            // 4 s of that, then finalize.
            let tok = runToken
            DispatchQueue.main.asyncAfter(deadline: .now() + 4) { [weak self] in
                guard let self, self.runToken == tok, self.phase == .rpStopped else { return }
                self.runProductionConfig(reset: false, label: "post_stop_reassert")
                self.setPhase(.postStopReassert)
                DispatchQueue.main.asyncAfter(deadline: .now() + 4) { [weak self] in
                    guard let self, self.runToken == tok, self.phase == .postStopReassert else { return }
                    self.finalizeRun()
                }
            }
        case .solo:
            finalizeRun()
        default:
            break
        }
    }

    private func finalizeRun() {
        // Final plane-anchor snapshot BEFORE pausing (production stopCapture
        // parallel) — lets offline analysis compare RoomPlan's walls against
        // the raw ARKit anchors from the very same session.
        var planes: [[String: Any]] = []
        var meshCount = 0
        if let f = arSession.currentFrame {
            for a in f.anchors {
                if let p = a as? ARPlaneAnchor {
                    planes.append([
                        "id": String(p.identifier.uuidString.prefix(8)),
                        "alignment": p.alignment == .horizontal ? "horizontal" : "vertical",
                        "classification": String(describing: p.classification),
                        "center": [r3(p.center.x), r3(p.center.y), r3(p.center.z)],
                        "extent_w": r3(p.planeExtent.width),
                        "extent_h": r3(p.planeExtent.height),
                        "rot_y": r3(p.planeExtent.rotationOnYAxis),
                        "transform": flat16(p.transform),
                    ])
                } else if a is ARMeshAnchor {
                    meshCount += 1
                }
            }
        }
        recorder?.writeJSONObject(["plane_anchors": planes, "mesh_anchor_count": meshCount],
                                  name: "plane_anchors.json")

        arSession.pause()
        UIApplication.shared.isIdleTimerDisabled = false
        tickTimer?.invalidate()
        tickTimer = nil
        retainedFrames.removeAll()
        retention = false

        if let room = lastRoom {
            writeRoom(room, name: "captured_room_live.json")
        }
        let stats = recorder?.blobStats()
        recorder?.event([
            "type": "run_end", "t": tNow(),
            "frames_total": totalFrames, "frames_depth_total": totalDepthFrames,
            "keyframes": keyframeCount,
            "jpeg_written": stats?.jpegWritten ?? -1, "jpeg_failed": stats?.jpegFailed ?? -1,
            "depth_written": stats?.depthWritten ?? -1, "depth_failed": stats?.depthFailed ?? -1,
            "rp_updates": roomUpdateCount,
            "mem_mb": r3(memoryFootprintMB()), "baseline_mem_mb": r3(baselineFootprint),
            "plane_anchor_count": planes.count, "mesh_anchor_count": meshCount,
        ])
        recorder?.sync()
        // Streams stay open if the RoomBuilder task is still running — its
        // completion closes them (see didEndWith handler).
        if builderDone || captureSession == nil {
            recorder?.closeStreams()
        }
        setPhase(.finished)
        rebuildSummary()
    }

    func newRun() {
        guard phase == .finished else { return }
        captureSession = nil
        interposer = nil
        recorder = nil
        lastRoom = nil
        builtRoom = nil
        phase = .idle
        statusLines = ["Ready."]
        summary = ""
        objectRows = []
        depthBadge = "DEPTH —"
        depthGood = nil
        lastInstruction = "—"
        objectsCountUI = 0
        wallsCountUI = 0
    }

    // MARK: - Per-frame path (arrives via own delegate OR FrameTapProxy)

    nonisolated func tapFrame(_ session: ARSession, _ frame: ARFrame) {
        // Extract on the delivery thread, hop to main — the production
        // CaptureManager pattern, verbatim.
        let camera = frame.camera
        let pixelBuffer = frame.capturedImage
        let timestamp = frame.timestamp
        let sceneDepth = frame.sceneDepth
        let smoothedDepth = frame.smoothedSceneDepth
        let trackingNormal: Bool
        if case .normal = camera.trackingState { trackingNormal = true } else { trackingNormal = false }
        DispatchQueue.main.async { [weak self] in
            self?.registerFrame(camera: camera, pixelBuffer: pixelBuffer, timestamp: timestamp,
                                sceneDepth: sceneDepth, smoothedDepth: smoothedDepth,
                                trackingNormal: trackingNormal, frame: frame)
        }
    }

    private func registerFrame(camera: ARCamera, pixelBuffer: CVPixelBuffer,
                               timestamp: TimeInterval,
                               sceneDepth: ARDepthData?, smoothedDepth: ARDepthData?,
                               trackingNormal: Bool, frame: ARFrame) {
        guard phase.isCapturing else { return }
        framesInTick += 1
        totalFrames += 1
        if phase == .rp || phase == .rpReasserted { framesSinceRPStart += 1 }
        if sceneDepth != nil { depthInTick += 1; totalDepthFrames += 1 }
        if smoothedDepth != nil { smoothedInTick += 1 }

        let now = CACurrentMediaTime()
        if now < transitionDetailUntil {
            recorder?.event([
                "type": "frame", "t": r3(now - runStart),
                "depth": sceneDepth != nil, "smoothed": smoothedDepth != nil,
                "res": "\(Int(camera.imageResolution.width))x\(Int(camera.imageResolution.height))",
                "tracking_normal": trackingNormal,
            ])
        }
        if retention && retainedFrames.count < 400 {
            retainedFrames.append(frame)
        }
        if trackingNormal, keyframer.shouldAccept(camera: camera) {
            acceptKeyframe(camera: camera, pixelBuffer: pixelBuffer,
                           timestamp: timestamp, sceneDepth: sceneDepth)
        }
    }

    private func acceptKeyframe(camera: ARCamera, pixelBuffer: CVPixelBuffer,
                                timestamp: TimeInterval, sceneDepth: ARDepthData?) {
        guard let recorder else { return }
        let index = keyframeCount
        keyframeCount += 1
        let rgbRel = String(format: "frames/%06d.jpg", index)
        recorder.writeJPEG(pixelBuffer, relativePath: rgbRel, ciContext: ciContext)

        let t = camera.transform
        let q = simd_quaternion(t)
        let g = q.inverse.act(simd_float3(0, -1, 0))  // production gravity math
        let K = camera.intrinsics
        let res = camera.imageResolution

        var line: [String: Any] = [
            "i": index,
            "t_us": Int(timestamp * 1_000_000),
            "phase": phase.rawValue,
            "rgb": rgbRel,
            "pos": [r3(t.columns.3.x), r3(t.columns.3.y), r3(t.columns.3.z)],
            "quat": [r3(q.vector.x), r3(q.vector.y), r3(q.vector.z), r3(q.vector.w)],
            "gravity": [r3(g.x), r3(g.y), r3(g.z)],
            "fx": r3(K.columns.0.x), "fy": r3(K.columns.1.y),
            "cx": r3(K.columns.2.x), "cy": r3(K.columns.2.y),
            "w": Int(res.width), "h": Int(res.height),
            "depth_present": sceneDepth != nil,
        ]
        if let sd = sceneDepth {
            let dw = CVPixelBufferGetWidth(sd.depthMap)
            let dh = CVPixelBufferGetHeight(sd.depthMap)
            let depthRel = String(format: "depth/%06d.f32", index)
            let confRel = String(format: "confidence/%06d.u8", index)
            recorder.writeDepth(sd.depthMap, confidenceMap: sd.confidenceMap,
                                depthRelPath: depthRel, confRelPath: confRel)
            // Production depth-intrinsics scaling (decision 0032).
            let sx = Float(dw) / Float(res.width)
            let sy = Float(dh) / Float(res.height)
            line["depth_rel"] = depthRel
            line["conf_rel"] = confRel
            line["depth_w"] = dw
            line["depth_h"] = dh
            line["depth_fx"] = r3(K.columns.0.x * sx)
            line["depth_fy"] = r3(K.columns.1.y * sy)
            line["depth_cx"] = r3(K.columns.2.x * sx)
            line["depth_cy"] = r3(K.columns.2.y * sy)
        }
        recorder.keyframeLine(line)
    }

    // MARK: - Observer taps

    nonisolated func tapTrackingState(_ camera: ARCamera) {
        let desc = String(describing: camera.trackingState)
        DispatchQueue.main.async { [weak self] in
            guard let self else { return }
            self.trackingStateUI = desc
            self.recorder?.event(["type": "tracking_state", "t": self.tNow(), "state": desc])
        }
    }

    nonisolated func tapSessionError(_ error: Error) {
        let desc = String(describing: error)
        DispatchQueue.main.async { [weak self] in
            guard let self else { return }
            self.recorder?.event(["type": "ar_error", "t": self.tNow(), "error": desc])
        }
    }

    nonisolated func tapInterruption(began: Bool) {
        DispatchQueue.main.async { [weak self] in
            guard let self else { return }
            self.recorder?.event(["type": "ar_interruption", "t": self.tNow(), "began": began])
        }
    }

    // MARK: - 1 Hz tick

    private func tick() {
        guard phase != .idle, phase != .finished else { return }
        let now = CACurrentMediaTime()
        let t = now - runStart
        let fps = framesInTick
        let depthCt = depthInTick
        let smoothCt = smoothedInTick
        framesInTick = 0
        depthInTick = 0
        smoothedInTick = 0
        let mem = memoryFootprintMB()

        let cfgDesc = Self.describeConfig(arSession.configuration)
        if cfgDesc != lastConfigDesc {
            recorder?.event(["type": "config_changed", "t": r3(t),
                             "from": lastConfigDesc, "to": cfgDesc])
            lastConfigDesc = cfgDesc
        }
        let delDesc = describeDelegate()
        if delDesc != lastDelegateDesc {
            recorder?.event(["type": "delegate_changed", "t": r3(t),
                             "from": lastDelegateDesc, "to": delDesc])
            lastDelegateDesc = delDesc
        }

        var camArr: [Double] = []
        var planeCt = 0
        var meshCt = 0
        var otherCt = 0
        if let f = arSession.currentFrame {
            let p = f.camera.transform.columns.3
            camArr = [r3(p.x), r3(p.y), r3(p.z)]
            for a in f.anchors {
                if a is ARPlaneAnchor { planeCt += 1 }
                else if a is ARMeshAnchor { meshCt += 1 }
                else { otherCt += 1 }
            }
        }

        recorder?.event([
            "type": "tick", "t": r3(t), "phase": phase.rawValue,
            "fps": fps, "depth": depthCt, "smoothed": smoothCt,
            "kf": keyframeCount, "mem_mb": r3(mem),
            "retained": retainedFrames.count, "cam": camArr,
            "anchors_plane": planeCt, "anchors_mesh": meshCt, "anchors_other": otherCt,
            "rp_updates": roomUpdateCount,
            "objects": lastRoom?.objects.count ?? -1,
            "walls": lastRoom?.walls.count ?? -1,
        ])
        recorder?.sync()

        autoInterposerCheck(now: now)
        leakGuardCheck(fps: fps, mem: mem, t: t)

        // UI.
        if fps > 0 {
            depthBadge = "DEPTH \(depthCt)/\(fps)  smoothed \(smoothCt)/\(fps)"
            depthGood = depthCt > 0
        } else {
            depthBadge = "DEPTH — (no frames)"
            depthGood = nil
        }
        statusLines = [
            String(format: "t=%.0fs  phase=%@  fps=%d", t, phase.rawValue, fps),
            "kf=\(keyframeCount)  frames=\(totalFrames)  rpUpd=\(roomUpdateCount)",
            "mem=\(Int(mem))MB (Δ\(Int(mem - baselineFootprint)))  retained=\(retainedFrames.count)",
            "anchors: plane=\(planeCt) mesh=\(meshCt) other=\(otherCt)",
            "cfg: \(cfgDesc)",
            "del: \(delDesc)",
            "tracking: \(trackingStateUI)",
        ]
    }

    private func autoInterposerCheck(now: TimeInterval) {
        guard phase == .rp || phase == .rpReasserted,
              interposer == nil,
              rpStartedAt > 0, now - rpStartedAt >= 3,
              framesSinceRPStart == 0
        else { return }
        guard let current = arSession.delegate, (current as AnyObject) !== self else {
            // Delegate is still us (or nil) yet frames stopped — a different
            // failure mode than theft; record it once per run.
            recorder?.event(["type": "frame_flow_note", "t": tNow(),
                             "note": "no frames 3s after rp start; delegate NOT foreign",
                             "delegate": describeDelegate()])
            rpStartedAt = -1  // don't repeat
            return
        }
        engageInterposer(reason: "auto_no_frames_3s")
    }

    private func engageInterposer(reason: String) {
        guard let current = arSession.delegate else {
            recorder?.event(["type": "frame_flow_note", "t": tNow(),
                             "note": "delegate nil; nothing to interpose", "reason": reason])
            return
        }
        let obj = current as AnyObject
        guard obj !== self, !(obj is FrameTapProxy) else { return }
        let proxy = FrameTapProxy(forwardTo: current, tap: self)
        interposer = proxy
        arSession.delegate = proxy
        recorder?.event(["type": "interposer_engaged", "t": tNow(), "reason": reason,
                         "stolen_class": String(describing: type(of: obj))])
        markTransition("interposer")
    }

    private func leakGuardCheck(fps: Int, mem: Double, t: Double) {
        guard retention else { return }
        if fps < 3 { lowFpsTicks += 1 } else { lowFpsTicks = 0 }
        let delta = mem - retentionBaselineMB
        let elapsed = CACurrentMediaTime() - retentionStartedAt
        var reason: String?
        if delta > 1500 { reason = "mem_delta_\(Int(delta))MB" }
        else if lowFpsTicks >= 4 { reason = "fps_stalled" }
        else if retainedFrames.count >= 400 { reason = "count_cap" }
        else if elapsed > 75 { reason = "timeout_75s" }
        if let reason {
            recorder?.event(["type": "leak_guard_tripped", "t": r3(t), "reason": reason,
                             "retained": retainedFrames.count, "mem_delta_mb": r3(delta)])
            retainedFrames.removeAll()
            retention = false
            lowFpsTicks = 0
            recorder?.event(["type": "leak_released", "t": r3(t)])
            markTransition("leak_released")
        }
    }

    // MARK: - Census

    private func handleRoom(_ room: CapturedRoom, kind: String) {
        roomUpdateCount += 1
        lastRoom = room
        let now = CACurrentMediaTime()
        var ev: [String: Any] = [
            "type": "census", "t": tNow(), "kind": kind,
            "objects": room.objects.count, "walls": room.walls.count,
            "doors": room.doors.count, "windows": room.windows.count,
            "openings": room.openings.count, "floors": room.floors.count,
        ]
        if now - lastRoomDumpAt >= 1.0 {
            lastRoomDumpAt = now
            ev["objects_detail"] = room.objects.map { objectDict($0) }
            ev["walls_detail"] = room.walls.map { surfaceDict($0) }
            ev["floors_detail"] = room.floors.map { surfaceDict($0) }
        }
        recorder?.event(ev)
        objectsCountUI = room.objects.count
        wallsCountUI = room.walls.count
    }

    private func objectDict(_ o: CapturedRoom.Object) -> [String: Any] {
        let p = o.transform.columns.3
        return [
            "id": String(o.identifier.uuidString.prefix(8)),
            "cat": String(describing: o.category),
            "conf": String(describing: o.confidence),
            "dims": [r3(o.dimensions.x), r3(o.dimensions.y), r3(o.dimensions.z)],
            "pos": [r3(p.x), r3(p.y), r3(p.z)],
            "yaw_deg": yawDeg(o.transform),
        ]
    }

    private func surfaceDict(_ s: CapturedRoom.Surface) -> [String: Any] {
        let p = s.transform.columns.3
        return [
            "id": String(s.identifier.uuidString.prefix(8)),
            "cat": String(describing: s.category),
            "conf": String(describing: s.confidence),
            "dims": [r3(s.dimensions.x), r3(s.dimensions.y), r3(s.dimensions.z)],
            "pos": [r3(p.x), r3(p.y), r3(p.z)],
            "yaw_deg": yawDeg(s.transform),
            "corners": s.polygonCorners.count,
        ]
    }

    // MARK: - Artifacts

    private func writeRoom(_ room: CapturedRoom, name: String) {
        let enc = JSONEncoder()
        enc.outputFormatting = [.prettyPrinted, .sortedKeys]
        if let data = try? enc.encode(room) {
            recorder?.writeJSON(data, name: name)
        } else {
            recorder?.event(["type": "build_failed", "which": "encode_\(name)",
                             "error": "JSONEncoder failed"])
        }
    }

    private func exportUSDZ(_ room: CapturedRoom) {
        guard let dir = recorder?.runDir else { return }
        do {
            try room.export(to: dir.appendingPathComponent("room_parametric.usdz"),
                            exportOptions: .parametric)
        } catch {
            recorder?.event(["type": "export_failed", "which": "parametric",
                             "error": String(describing: error)])
        }
        do {
            try room.export(to: dir.appendingPathComponent("room_mesh.usdz"),
                            exportOptions: .mesh)
        } catch {
            recorder?.event(["type": "export_failed", "which": "mesh",
                             "error": String(describing: error)])
        }
    }

    private func rebuildSummary() {
        var lines: [String] = []
        lines.append("run: \(recorder?.runID ?? "?")")
        lines.append("frames \(totalFrames) (depth \(totalDepthFrames))  keyframes \(keyframeCount)")
        if let s = recorder?.blobStats() {
            lines.append("jpeg \(s.jpegWritten)w/\(s.jpegFailed)f  depth \(s.depthWritten)w/\(s.depthFailed)f")
        }
        let room = builtRoom ?? lastRoom
        if let room {
            let which = builtRoom != nil ? "built" : "live"
            lines.append("room(\(which)): \(room.objects.count) obj, \(room.walls.count) walls, \(room.doors.count) doors, \(room.windows.count) win, \(room.openings.count) openings, \(room.floors.count) floors")
            if let floor = room.floors.first {
                lines.append(String(format: "floor %.2f × %.2f m  (%d corners)",
                                    floor.dimensions.x, floor.dimensions.y,
                                    floor.polygonCorners.count))
            }
            objectRows = room.objects.map { o in
                String(format: "%@  %.2f×%.2f×%.2f  %@  yaw %.0f°",
                       String(describing: o.category),
                       o.dimensions.x, o.dimensions.y, o.dimensions.z,
                       String(describing: o.confidence), yawDeg(o.transform))
            }
        } else {
            lines.append("no CapturedRoom received")
        }
        summary = lines.joined(separator: "\n")
    }

    // MARK: - Helpers

    private func resetCounters() {
        framesInTick = 0
        depthInTick = 0
        smoothedInTick = 0
        totalFrames = 0
        totalDepthFrames = 0
        framesSinceRPStart = 0
        keyframeCount = 0
        lastConfigDesc = ""
        lastDelegateDesc = ""
        transitionDetailUntil = 0
        rpStartedAt = 0
        rpEndReceived = false
        builderDone = false
        lastRoom = nil
        builtRoom = nil
        roomUpdateCount = 0
        lastRoomDumpAt = 0
        retention = false
        retainedFrames = []
        lowFpsTicks = 0
        objectRows = []
        summary = ""
    }

    private func setPhase(_ p: SpikePhase) {
        phase = p
        recorder?.event(["type": "phase", "t": tNow(), "phase": p.rawValue])
    }

    private func markTransition(_ label: String) {
        transitionDetailUntil = CACurrentMediaTime() + 6
        recorder?.event(["type": "frame_flow_note", "t": tNow(),
                         "note": "detail window opened: \(label)"])
    }

    private func tNow() -> Double { r3(CACurrentMediaTime() - runStart) }

    private func describeDelegate() -> String {
        guard let d = arSession.delegate else { return "nil" }
        let obj = d as AnyObject
        let cls = String(describing: type(of: obj))
        let role: String
        if obj === self { role = "spike" }
        else if interposer != nil && obj === interposer { role = "interposer" }
        else { role = "FOREIGN" }
        let q = arSession.delegateQueue?.label ?? "main(default)"
        return "\(cls) [\(role)] q=\(q)"
    }

    nonisolated static func describeConfig(_ cfg: ARConfiguration?) -> String {
        guard let cfg else { return "nil" }
        var parts: [String] = [String(describing: type(of: cfg))]
        parts.append("align=\(cfg.worldAlignment.rawValue)")
        let fs = cfg.frameSemantics
        var names: [String] = []
        if fs.contains(.sceneDepth) { names.append("sceneDepth") }
        if fs.contains(.smoothedSceneDepth) { names.append("smoothedSceneDepth") }
        if fs.contains(.personSegmentation) { names.append("personSeg") }
        if fs.contains(.personSegmentationWithDepth) { names.append("personSegDepth") }
        if fs.contains(.bodyDetection) { names.append("bodyDetection") }
        parts.append("fs=\(fs.rawValue)[\(names.joined(separator: "+"))]")
        let vf = cfg.videoFormat
        parts.append("video=\(Int(vf.imageResolution.width))x\(Int(vf.imageResolution.height))@\(vf.framesPerSecond)")
        if let w = cfg as? ARWorldTrackingConfiguration {
            parts.append("planes=\(w.planeDetection.rawValue)")
            parts.append("recon=\(w.sceneReconstruction.rawValue)")
            parts.append("envTex=\(w.environmentTexturing.rawValue)")
            parts.append("autofocus=\(w.isAutoFocusEnabled)")
        }
        return parts.joined(separator: " ")
    }
}

// MARK: - ARSessionDelegate

extension SpikeController: ARSessionDelegate {

    nonisolated func session(_ session: ARSession, didUpdate frame: ARFrame) {
        tapFrame(session, frame)
    }

    nonisolated func session(_ session: ARSession, cameraDidChangeTrackingState camera: ARCamera) {
        tapTrackingState(camera)
    }

    nonisolated func session(_ session: ARSession, didFailWithError error: Error) {
        tapSessionError(error)
    }

    nonisolated func sessionWasInterrupted(_ session: ARSession) {
        tapInterruption(began: true)
    }

    nonisolated func sessionInterruptionEnded(_ session: ARSession) {
        tapInterruption(began: false)
    }
}

// MARK: - RoomCaptureSessionDelegate

extension SpikeController: RoomCaptureSessionDelegate {

    nonisolated func captureSession(_ session: RoomCaptureSession,
                                    didStartWith configuration: RoomCaptureSession.Configuration) {
        let coaching = configuration.isCoachingEnabled
        DispatchQueue.main.async { [weak self] in
            guard let self else { return }
            self.recorder?.event(["type": "rp_did_start", "t": self.tNow(),
                                  "coaching": coaching,
                                  "ar_config_now": Self.describeConfig(self.arSession.configuration),
                                  "delegate_now": self.describeDelegate()])
        }
    }

    nonisolated func captureSession(_ session: RoomCaptureSession, didUpdate room: CapturedRoom) {
        DispatchQueue.main.async { [weak self] in self?.handleRoom(room, kind: "update") }
    }

    nonisolated func captureSession(_ session: RoomCaptureSession, didAdd room: CapturedRoom) {
        DispatchQueue.main.async { [weak self] in self?.handleRoom(room, kind: "add") }
    }

    nonisolated func captureSession(_ session: RoomCaptureSession, didChange room: CapturedRoom) {
        DispatchQueue.main.async { [weak self] in self?.handleRoom(room, kind: "change") }
    }

    nonisolated func captureSession(_ session: RoomCaptureSession, didRemove room: CapturedRoom) {
        DispatchQueue.main.async { [weak self] in self?.handleRoom(room, kind: "remove") }
    }

    nonisolated func captureSession(_ session: RoomCaptureSession,
                                    didProvide instruction: RoomCaptureSession.Instruction) {
        let name = String(describing: instruction)
        DispatchQueue.main.async { [weak self] in
            guard let self else { return }
            self.lastInstruction = name
            self.recorder?.event(["type": "instruction", "t": self.tNow(), "name": name])
        }
    }

    nonisolated func captureSession(_ session: RoomCaptureSession,
                                    didEndWith data: CapturedRoomData, error: (any Error)?) {
        let errDesc = error.map { String(describing: $0) }
        Task { @MainActor [weak self] in
            guard let self else { return }
            self.rpEndReceived = true
            self.recorder?.event(["type": "rp_end", "t": self.tNow(),
                                  "error": errDesc ?? "nil"])
            do {
                let beautified = try await RoomBuilder(options: [.beautifyObjects])
                    .capturedRoom(from: data)
                self.builtRoom = beautified
                self.writeRoom(beautified, name: "captured_room_built.json")
                self.exportUSDZ(beautified)
                self.recorder?.event(["type": "room_built", "t": self.tNow(),
                                      "objects": beautified.objects.count,
                                      "walls": beautified.walls.count,
                                      "doors": beautified.doors.count,
                                      "windows": beautified.windows.count,
                                      "openings": beautified.openings.count,
                                      "floors": beautified.floors.count,
                                      "sections": beautified.sections.count])
            } catch {
                self.recorder?.event(["type": "build_failed", "which": "beautified",
                                      "error": String(describing: error)])
            }
            do {
                let raw = try await RoomBuilder(options: []).capturedRoom(from: data)
                self.writeRoom(raw, name: "captured_room_raw.json")
            } catch {
                self.recorder?.event(["type": "build_failed", "which": "raw",
                                      "error": String(describing: error)])
            }
            self.builderDone = true
            if self.phase == .finished {
                self.recorder?.closeStreams()
                self.rebuildSummary()
            }
        }
    }
}
