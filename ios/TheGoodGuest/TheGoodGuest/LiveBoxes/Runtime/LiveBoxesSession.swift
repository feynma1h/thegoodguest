/// The live-boxes session: a detector running beside the capture, on the
/// capture's own ARSession, with everything it costs written down — DEBUG-only
/// (decision 0295).
///
/// THE CAPTURE'S SESSION, NOT A SECOND ONE. `CaptureManager` owns the
/// ARSession, its configuration, the RoomPlan co-run and the depth-loss guard
/// (`CaptureSessionSetup`, `RoomPlanWire`); it hands each frame and each
/// tracking-state change to this session's `driver`. Nothing here starts,
/// pauses or reconfigures ARKit, so the numbers it logs describe the scan the
/// person is making, and a scan without live boxes is not touched.
///
/// THE SCREEN CHOOSES WHICH TRACKS ARE BOXES. The session reports every track
/// the pipeline holds, each pass; which of them the person has boxed, and how a
/// box settles, is the screen's (`LiveBoxesPresentation`, `DotRules`).
///
/// DEPTH FROM LIDAR, OR FROM A MODEL. LiDAR where the phone has it; otherwise
/// the bundled depth model `DepthPolicy` names. A model is loaded, warmed with
/// one prediction, and installed with a new pipeline, so its boxes start
/// afresh; a model's passes need no LiDAR, only the anchors ARKit tracks.
///
/// THREADS. ARKit delivers frames to the capture's delegate, which forwards
/// them to the frame driver on its own queue. The driver gates a pass
/// (tracking normal, depth present, the previous pass done, the target interval
/// elapsed), copies out what the pass needs and hands it to the pipeline queue.
/// Results come back to the main actor, which owns every published value, the
/// meters and the log.
///
/// Read by: CaptureManager, LiveBoxesPresentation, LiveBoxesRuntimeTests.

#if DEBUG

import ARKit
import Combine
import Foundation
import os
import UIKit

// MARK: - What the screen reads

nonisolated enum DetectorStatus: Equatable, Sendable {
    case missing
    case loading(String)
    case ready(name: String, inputSize: Int, classes: Int, unmapped: Int)
    case failed(String)
}

nonisolated struct CostReadout: Equatable, Sendable {
    var predictP50: Double?
    var predictP95: Double?
    var passP50: Double?
    var passRate: Double = 0
    var arFrameRate: Double = 0
    var tracking = "notAvailable"
    var thermal = "nominal"
    var elapsed: Double = 0
    var availableMemoryMB: Double?
    /// A depth model's prediction p50; nil while LiDAR is the source.
    var depthP50: Double?
}

/// How often the detector runs. 2 per second is the charter's floor; at 5 a
/// furnished room took the phone from nominal to serious heat in 91 seconds.
nonisolated enum DetectionPacing {
    static let passesPerSecond: Double = 2

    /// Seconds between pass starts.
    static var interval: Double { 1 / passesPerSecond }
}

/// Why a frame did not start a pass, checked in this order. A detector that
/// never runs must say which gate holds it, in the log, rather than go quiet.
nonisolated enum PassGate: String, CaseIterable, Sendable {
    case noDetector = "no detector"
    case passRunning = "pass running"
    case paced
    case tracking
    case noDepth = "no depth"
    case depthUnreadable = "depth unreadable"

    /// The first gate that holds a frame, or nil when a pass may start —
    /// all but the last, which needs the depth map itself.
    static func holding(hasPipeline: Bool, busy: Bool, interval: Double, sinceLastStart: Double,
                        trackingNormal: Bool, hasDepth: Bool) -> PassGate? {
        if !hasPipeline { return .noDetector }
        if busy { return .passRunning }
        if sinceLastStart < interval { return .paced }
        if !trackingNormal { return .tracking }
        if !hasDepth { return .noDepth }
        return nil
    }

    /// The key a started pass is counted under, beside the gates.
    static let started = "started"
}

/// Which load is current. Every load takes a new ticket, and so does stopping;
/// a load that finishes installs its result only while its ticket is still the
/// current one.
nonisolated struct LoadTickets {
    private(set) var current = 0

    mutating func next() -> Int {
        current += 1
        return current
    }

    func isCurrent(_ ticket: Int) -> Bool { ticket == current }
}

nonisolated enum LiveBoxesTokens {
    static func tracking(_ state: ARCamera.TrackingState) -> String {
        switch state {
        case .normal: return "normal"
        case .notAvailable: return "notAvailable"
        case .limited(let reason):
            switch reason {
            case .initializing: return "limited(initializing)"
            case .excessiveMotion: return "limited(excessiveMotion)"
            case .insufficientFeatures: return "limited(insufficientFeatures)"
            case .relocalizing: return "limited(relocalizing)"
            @unknown default: return "limited(unknown)"
            }
        }
    }

    static func thermal(_ state: ProcessInfo.ThermalState) -> String {
        switch state {
        case .nominal: return "nominal"
        case .fair: return "fair"
        case .serious: return "serious"
        case .critical: return "critical"
        @unknown default: return "unknown"
        }
    }
}

// MARK: - The session

@MainActor
final class LiveBoxesSession: NSObject, ObservableObject {

    @Published private(set) var detector: DetectorStatus = .missing
    /// Every track; the screen draws the locked ones' locked boxes.
    @Published private(set) var tracks: [TrackSummary] = []
    /// The last pass's depth, from whichever source: not published, read by the screen each frame.
    private(set) var latestSight: DepthSight?
    @Published private(set) var isRunning = false
    /// Where the depth comes from: `LiDAR`, or the depth model's name.
    @Published private(set) var depthName = DepthSource.lidarName

    let hasLidar = ARWorldTrackingConfiguration.supportsSceneReconstruction(.meshWithClassification)

    // Both drain an autorelease pool after every block: ARKit's frames and Core
    // ML's outputs are autoreleased, and neither queue is ever idle for long.
    private let frameQueue = DispatchQueue(label: "com.thegoodguest.liveboxes.frames", qos: .userInitiated,
                                           autoreleaseFrequency: .workItem)
    private let pipelineQueue = DispatchQueue(label: "com.thegoodguest.liveboxes.pipeline", qos: .userInitiated,
                                              autoreleaseFrequency: .workItem)
    private let writeQueue = DispatchQueue(label: "com.thegoodguest.liveboxes.log", qos: .utility)
    private(set) lazy var driver = LiveBoxesFrameDriver(queue: frameQueue, pipelineQueue: pipelineQueue,
                                                        owner: self)

    /// The fits themselves, as the log records them.
    private var fittedTracks: [TrackSummary] = []
    private var meter = CostMeter()
    private var loads = LoadTickets()
    private var installedPipeline: DetectorPipeline?
    /// The depth source every new pipeline is built with, and which model load is current.
    private var depthSource: DepthSource = .lidar
    private var depthLoads = LoadTickets()
    /// What the installed pipeline runs, as the log records it.
    private var installed: (name: String, info: DetectorModelInfo, compute: ComputeChoice, scoreThreshold: Float)?
    private var trackingTime = StateDurations()
    private var thermalTime = StateDurations()
    private var roomPlanTime = StateDurations()
    /// RoomPlan's boxes, for the log's comparison; only filled where `RoomPlanClasses.boxedByRoomPlan`.
    private var roomPlanBoxes: [RoomPlanBox] = []
    private var readout = CostReadout()
    private var log: SessionLog
    private let logURL: URL
    private var startedAt: Double = 0
    private var frameRate: Double = 0
    /// Frames since the last sample by what became of them, and how long the
    /// running pass had been running at the driver's last report.
    private var frameOutcomes: [String: Int] = [:]
    private var passRunningFor: Double?
    private var voxels: Int?
    /// Detections that became no sighting, and why (`MissTally`).
    private var missTally = MissTally()
    private var sampler: Timer?
    private var autosaver: Timer?
    private var thermalObserver: NSObjectProtocol?
    private let logger = Logger(subsystem: "com.thegoodguest.TheGoodGuest", category: "LiveBoxes")

    override init() {
        let now = Date()
        logURL = SessionLog.directory().appendingPathComponent(SessionLog.fileName(startedAt: now))
        log = SessionLog(startedAt: ISO8601DateFormatter().string(from: now),
                         device: SessionLog.Device(model: Self.machine(),
                                                   system: "iOS \(UIDevice.current.systemVersion)",
                                                   app: Self.appVersion(),
                                                   optimized: SessionLog.isOptimizedBuild),
                         lift: DepthLiftParameters(), fusion: FusionParameters())
        super.init()
    }

    // MARK: Lifecycle

    func start() {
        guard LiveBoxesFeature.isEnabled, !isRunning else { return }
        isRunning = true
        startedAt = CACurrentMediaTime()
        roomPlanTime.note("off", at: 0)
        noteThermal()

        driver.setInterval(DetectionPacing.interval)
        loadDetector()
        chooseDepth()

        thermalObserver = NotificationCenter.default.addObserver(
            forName: ProcessInfo.thermalStateDidChangeNotification, object: nil, queue: .main
        ) { [weak self] _ in
            Task { @MainActor [weak self] in self?.noteThermal() }
        }
        sampler = Timer.scheduledTimer(withTimeInterval: 1, repeats: true) { [weak self] _ in
            Task { @MainActor [weak self] in self?.sample() }
        }
        autosaver = Timer.scheduledTimer(withTimeInterval: 10, repeats: true) { [weak self] _ in
            Task { @MainActor [weak self] in self?.saveLog() }
        }
        event("session", "started")
    }

    func stop() {
        guard isRunning else { return }
        sampler?.invalidate()
        autosaver?.invalidate()
        if let thermalObserver { NotificationCenter.default.removeObserver(thermalObserver) }
        _ = loads.next()
        _ = depthLoads.next()
        driver.setPipeline(nil)
        installed = nil
        installedPipeline = nil
        event("session", "stopped")
        saveLog()
        isRunning = false
    }

    // MARK: Depth

    /// LiDAR where the phone has it; otherwise the bundled model `DepthPolicy` names.
    private func chooseDepth() {
        guard !hasLidar else { return }
        let bundled = DepthCatalog.bundled()
        guard let stem = DepthPolicy.modelStem(among: bundled.map(\.stem)),
              let model = bundled.first(where: { $0.stem == stem }) else {
            event("depth", "no LiDAR and no depth model bundled: no pass can run")
            return
        }
        let ticket = depthLoads.next()
        depthName = stem
        event("depth", "loading \(stem)")
        pipelineQueue.async { [weak self] in
            let clock = ContinuousClock()
            let start = clock.now
            let result = Result { () throws -> DepthModelRunner in
                let runner = DepthModelRunner(model: try LoadedDepthModel.load(model, compute: .all))
                try runner.warmUp()
                return runner
            }
            let took = (clock.now - start).components
            let seconds = Double(took.seconds) + Double(took.attoseconds) / 1e18
            Task { @MainActor [weak self] in self?.depthLoaded(result, stem: stem, seconds: seconds, ticket: ticket) }
        }
    }

    private func depthLoaded(_ result: Result<DepthModelRunner, Error>, stem: String, seconds: Double, ticket: Int) {
        // Overtaken by stop(): install nothing, say nothing.
        guard depthLoads.isCurrent(ticket), isRunning else { return }
        switch result {
        case .success(let runner):
            let model = runner.model, source = DepthSource.model(runner)
            depthName = model.info.name
            log.depthModels.append(SessionLog.DepthModel(
                t: elapsed, name: model.info.name, kind: model.info.kind.rawValue, source: model.info.source,
                license: model.info.license, inputWidth: model.inputWidth, inputHeight: model.inputHeight,
                compute: model.compute.rawValue, loadSeconds: seconds, lift: source.liftParameters,
                fusion: source.fusionParameters))
            event("depth", String(format: "ready %@ (%@, %d×%d input) in %.1f s", model.info.name,
                                  model.info.kind.rawValue, model.inputWidth, model.inputHeight, seconds))
            installDepth(source)
        case .failure(let error):
            let reason = (error as? DepthLoadError)?.description ?? error.localizedDescription
            depthName = DepthSource.lidarName
            event("depth", "failed \(stem): \(reason)")
        }
    }

    /// Every pass from now on takes its depth from `source`, in a new pipeline
    /// whose boxes start afresh. A detector still loading is built with it.
    private func installDepth(_ source: DepthSource) {
        depthSource = source
        readout.depthP50 = nil
        event("depth", "source \(source.name)")
        guard let detector = installedPipeline?.detector else { return }
        let pipeline = DetectorPipeline(detector: detector, depth: source)
        installedPipeline = pipeline
        driver.setPipeline(pipeline)
        recordDetectorConfiguration()
    }

    // MARK: Detector

    private func loadDetector() {
        let ticket = loads.next()
        driver.setPipeline(nil)
        installed = nil
        installedPipeline = nil
        guard let chosen = DetectorCatalog.choose(DetectorCatalog.bundled(), requested: nil) else {
            detector = .missing
            event("detector", "missing")
            return
        }
        detector = .loading(chosen.name)
        pipelineQueue.async { [weak self] in
            let result = Result { try LoadedDetector.load(chosen, compute: .all) }
            Task { @MainActor [weak self] in
                self?.detectorLoaded(result, name: chosen.name, ticket: ticket)
            }
        }
    }

    private func detectorLoaded(_ result: Result<LoadedDetector, Error>, name: String, ticket: Int) {
        // Overtaken by stop(): install nothing, say nothing.
        guard loads.isCurrent(ticket), isRunning else { return }
        switch result {
        case .success(let loaded):
            let pipeline = DetectorPipeline(detector: loaded, depth: depthSource)
            installedPipeline = pipeline
            let unmapped = pipeline.unmappedNames
            detector = .ready(name: name, inputSize: loaded.info.inputWidth,
                              classes: loaded.info.names.count, unmapped: unmapped.count)
            if !unmapped.isEmpty { event("detector", "unmapped names: \(unmapped.joined(separator: ", "))") }
            driver.setPipeline(pipeline)
            installed = (name, loaded.info, .all, pipeline.scoreThreshold)
            recordDetectorConfiguration()
            event("detector", "ready \(name) on \(ComputeChoice.all.rawValue)")
        case .failure(let error):
            let reason = (error as? DetectorLoadError)?.description ?? error.localizedDescription
            detector = .failed(reason)
            event("detector", "failed \(name): \(reason)")
        }
    }

    private func recordDetectorConfiguration() {
        guard let installed else { return }
        log.detectors.append(SessionLog.Detector(t: elapsed, model: installed.name,
                                                 inputWidth: installed.info.inputWidth,
                                                 inputHeight: installed.info.inputHeight,
                                                 classes: installed.info.names.count,
                                                 compute: installed.compute.rawValue,
                                                 targetRateHz: DetectionPacing.passesPerSecond,
                                                 scoreThreshold: installed.scoreThreshold,
                                                 depth: depthSource.name))
    }

    // MARK: From the driver

    fileprivate func accept(_ result: PassResult) {
        guard isRunning else { return }
        let t = result.time - startedAt
        if let layout = result.outputLayout { event("detector", "output \(layout)") }
        if log.record(result, at: t) {
            meter.notePass(at: t, timing: result.timing)
        } else if let failure = result.failure {
            logger.info("[LiveBoxes] pass failed: \(failure, privacy: .public)")
        }
        if result.failure == nil {
            voxels = result.voxels
            latestSight = result.sight
        }
        missTally.add(result.misses)
        let next = result.tracks
        fittedTracks = next
        tracks = next
    }

    fileprivate func noteTracking(_ token: String, at time: Double) {
        let t = time - startedAt
        if token != trackingTime.current { event("tracking", token, at: t) }
        trackingTime.note(token, at: t)
        readout.tracking = token
    }

    fileprivate func noteFrameRate(_ rate: Double) {
        frameRate = rate
    }

    fileprivate func noteFrameOutcomes(_ outcomes: [String: Int], passRunningFor running: Double?) {
        for (outcome, count) in outcomes { frameOutcomes[outcome, default: 0] += count }
        passRunningFor = running
    }

    fileprivate func noteUnreadableDepth(format: String) {
        event("depth", "depth map format \(format) is not DepthFloat32; no pass can read it")
    }

    // MARK: RoomPlan

    /// RoomPlan's boxes, for the log to compare the detector's against. Ignored
    /// unless `RoomPlanClasses.boxedByRoomPlan`: nothing in the app sends them.
    func acceptRoomPlan(_ boxes: [RoomPlanBox]) {
        guard isRunning, RoomPlanClasses.boxedByRoomPlan else { return }
        roomPlanBoxes = boxes
    }

    // MARK: Meters and the log

    private var elapsed: Double { isRunning ? CACurrentMediaTime() - startedAt : readout.elapsed }

    private func noteThermal() {
        let token = LiveBoxesTokens.thermal(ProcessInfo.processInfo.thermalState)
        if token != thermalTime.current { event("thermal", token) }
        thermalTime.note(token, at: elapsed)
        readout.thermal = token
    }

    private func sample() {
        let now = elapsed
        let latency = meter.predictLatency(now: now)
        readout.predictP50 = latency?.p50
        readout.predictP95 = latency?.p95
        readout.passP50 = meter.passLatency(now: now)
        readout.depthP50 = meter.depthLatency(now: now)
        readout.passRate = meter.detectionRate(now: now, startedAt: 0)
        readout.arFrameRate = frameRate
        readout.elapsed = now
        let available = Double(os_proc_available_memory()) / 1_048_576
        readout.availableMemoryMB = available > 0 ? available : nil
        let memory = MemoryReading.current()
        log.samples.append(SessionLog.Sample(
            t: now, tracking: readout.tracking, thermal: readout.thermal, roomPlan: RoomPlanClasses.boxedByRoomPlan,
            arFrameRate: frameRate, passRate: readout.passRate, predictP50: readout.predictP50,
            predictP95: readout.predictP95, passP50: readout.passP50, tracks: tracks.count,
            confirmed: tracks.filter(\.confirmed).count, availableMemoryMB: readout.availableMemoryMB,
            frames: frameOutcomes, passRunningFor: passRunningFor,
            footprintMB: memory?.footprintMB, voxels: voxels, graphicsMB: memory?.graphicsMB,
            neuralMB: memory?.neuralMB, mediaMB: memory?.mediaMB, heapMB: memory?.heapMB,
            locked: tracks.filter { $0.locked != nil }.count))
        frameOutcomes = [:]
    }

    /// A line from the screen into the session log, for reading after a walk.
    func note(_ kind: String, _ value: String) { event(kind, value) }

    private func event(_ kind: String, _ value: String, at t: Double? = nil) {
        log.events.append(SessionLog.Event(t: t ?? elapsed, kind: kind, value: value))
        logger.info("[LiveBoxes] \(kind, privacy: .public): \(value, privacy: .public)")
    }

    /// Write the log as it stands. Returns the file name.
    @discardableResult
    func saveLog() -> String {
        let now = elapsed
        // The fits, not the steadied boxes the screen draws.
        log.tracks = fittedTracks.map { track in
            var agreement: BoxAgreement?
            if let category = track.roomPlanCategory {
                agreement = RoomPlanMatch.agreement(track.box, category: category, among: roomPlanBoxes)?.agreement
            }
            return SessionLog.Track(
                id: track.id.uuidString, label: track.label, name: track.name, names: track.names,
                bestScore: track.bestScore, hits: track.hits, misses: track.misses, arcDegrees: track.arcDegrees,
                firstSeen: track.firstSeen - startedAt, lastSeen: track.lastSeen - startedAt,
                confirmed: track.confirmed, box: SessionLog.Box(track.box),
                locked: track.locked.map { SessionLog.Box($0.box) }, lockedAt: track.locked.map { $0.time - startedAt },
                roomPlanCategory: track.roomPlanCategory,
                duplicatesRoomPlan: RoomPlanMatch.duplicatedCategory(track.box, overlap: track.roomPlanOverlap,
                                                                     among: roomPlanBoxes),
                roomPlanAgreement: agreement, movement: track.movement, seenThrough: track.seenThrough)
        }
        log.misses = missTally.entries
        log.roomPlanObjects = roomPlanBoxes.map {
            SessionLog.RoomPlanObject(id: $0.id.uuidString, category: $0.category,
                                      confidence: String(describing: $0.confidence), box: SessionLog.Box($0.box))
        }
        log.summary = log.summarised(now: now, tracking: trackingTime, thermal: thermalTime, roomPlan: roomPlanTime)
        let snapshot = log
        let url = logURL
        let name = url.lastPathComponent
        writeQueue.async {
            do {
                try FileManager.default.createDirectory(at: url.deletingLastPathComponent(),
                                                        withIntermediateDirectories: true)
                try snapshot.encoded().write(to: url, options: .atomic)
            } catch {
                Logger(subsystem: "com.thegoodguest.TheGoodGuest", category: "LiveBoxes")
                    .info("[LiveBoxes] log write failed: \(error.localizedDescription, privacy: .public)")
            }
        }
        return name
    }

    private static func machine() -> String {
        var info = utsname()
        uname(&info)
        return withUnsafeBytes(of: &info.machine) { raw in
            String(decoding: raw.prefix { $0 != 0 }, as: UTF8.self)
        }
    }

    private static func appVersion() -> String {
        let info = Bundle.main.infoDictionary
        let version = info?["CFBundleShortVersionString"] as? String ?? "?"
        let build = info?["CFBundleVersion"] as? String ?? "?"
        return "\(version) (\(build))"
    }
}

// MARK: - Frame driver

private struct FrameHandoff: @unchecked Sendable {
    let frame: ARFrame
}

/// Takes the capture's frames and runs passes on them. Every method but the
/// two `ride` entry points runs on the frame queue, and every stored property
/// is touched only there.
nonisolated final class LiveBoxesFrameDriver: @unchecked Sendable {
    private let queue: DispatchQueue
    private let pipelineQueue: DispatchQueue
    private weak var owner: LiveBoxesSession?

    private var pipeline: DetectorPipeline?
    private var busy = false
    private var interval: Double = 0.2
    private var lastStart = -Double.infinity
    private var frameTimes: [Double] = []
    private var lastRatePublish: Double = 0
    /// Frames since the last report, by what became of them.
    private var frameOutcomes: [String: Int] = [:]
    private var lastOutcomeReport: Double = 0
    private var runningSince: Double?
    private var depthFormatReported = false

    init(queue: DispatchQueue, pipelineQueue: DispatchQueue, owner: LiveBoxesSession) {
        self.queue = queue
        self.pipelineQueue = pipelineQueue
        self.owner = owner
    }

    /// The capture's delegate callbacks, handed onto this driver's queue. Called from ARKit's delegate queue.
    func ride(frame: ARFrame) {
        // ARKit hands the frame over and never touches it again; it only changes queue here.
        let handoff = FrameHandoff(frame: frame)
        queue.async { self.handle(handoff.frame) }
    }

    func ride(tracking camera: ARCamera) {
        let token = LiveBoxesTokens.tracking(camera.trackingState)
        let t = ProcessInfo.processInfo.systemUptime
        Task { @MainActor [weak owner] in owner?.noteTracking(token, at: t) }
    }

    func setPipeline(_ pipeline: DetectorPipeline?) {
        queue.async { self.pipeline = pipeline }
    }

    func setInterval(_ seconds: Double) {
        queue.async { self.interval = seconds }
    }

    private func handle(_ frame: ARFrame) {
        let t = frame.timestamp
        frameTimes.append(t)
        if frameTimes.count > 256 { frameTimes.removeFirst(frameTimes.count - 256) }
        if t - lastRatePublish >= 0.5 {
            lastRatePublish = t
            let rate = Double(frameTimes.filter { $0 > t - 2 }.count) / 2
            Task { @MainActor [weak owner] in owner?.noteFrameRate(rate) }
        }

        if t - lastOutcomeReport >= 1 {
            lastOutcomeReport = t
            let outcomes = frameOutcomes
            let running = runningSince.map { t - $0 }
            frameOutcomes = [:]
            Task { @MainActor [weak owner] in owner?.noteFrameOutcomes(outcomes, passRunningFor: running) }
        }

        var trackingNormal = false
        if case .normal = frame.camera.trackingState { trackingNormal = true }
        // A depth model makes its own depth; LiDAR's, when there, only referees it.
        let needsLidar = pipeline?.depthSource.needsLidar ?? true
        if let gate = PassGate.holding(hasPipeline: pipeline != nil, busy: busy, interval: interval,
                                       sinceLastStart: t - lastStart, trackingNormal: trackingNormal,
                                       hasDepth: !needsLidar || frame.sceneDepth != nil) {
            frameOutcomes[gate.rawValue, default: 0] += 1
            return
        }
        guard let pipeline else { return }
        guard let snapshot = Self.snapshot(frame: frame, depth: frame.sceneDepth, needsLidar: needsLidar) else {
            frameOutcomes[PassGate.depthUnreadable.rawValue, default: 0] += 1
            if !depthFormatReported, let depth = frame.sceneDepth {
                depthFormatReported = true
                let format = Self.fourCharacterCode(CVPixelBufferGetPixelFormatType(depth.depthMap))
                Task { @MainActor [weak owner] in owner?.noteUnreadableDepth(format: format) }
            }
            return
        }
        frameOutcomes[PassGate.started, default: 0] += 1
        busy = true
        runningSince = t
        lastStart = t
        pipelineQueue.async { [weak self] in
            let result = pipeline.process(snapshot)
            self?.queue.async {
                self?.busy = false
                self?.runningSince = nil
            }
            Task { @MainActor [weak owner = self?.owner] in owner?.accept(result) }
        }
    }

    private static func fourCharacterCode(_ code: OSType) -> String {
        let bytes = [24, 16, 8, 0].map { UInt8((code >> $0) & 0xFF) }
        return bytes.allSatisfy({ $0 >= 32 && $0 < 127 }) ? String(decoding: bytes, as: UTF8.self) : String(code)
    }

    /// Copy out what a pass needs. The camera buffer goes into a one-shot
    /// handoff; depth and confidence are copied, so no ARKit buffer outlives
    /// the render. A depth model's pass also takes the anchors its map is
    /// fitted to — the frame's feature points and every plane's outline — and
    /// LiDAR's depth only when it can be read. Nil when a pass that needs
    /// LiDAR's depth cannot read it.
    private static func snapshot(frame: ARFrame, depth: ARDepthData?, needsLidar: Bool) -> FrameSnapshot? {
        let grid = depth.flatMap(copyDepth)
        if needsLidar, grid == nil { return nil }
        var anchors = DepthAnchors()
        if !needsLidar { anchors.featurePoints = frame.rawFeaturePoints?.points ?? [] }
        let camera = frame.camera
        let intrinsics = CameraIntrinsics(matrix: camera.intrinsics,
                                          width: Int(camera.imageResolution.width),
                                          height: Int(camera.imageResolution.height))
        var surfaces: [HorizontalSurface] = []
        var walls: [(direction: SIMD2<Float>, weight: Float)] = []
        var vertical: [VerticalSurface] = []
        for anchor in frame.anchors {
            guard let plane = anchor as? ARPlaneAnchor,
                  plane.planeExtent.width * plane.planeExtent.height >= 0.09 else { continue }
            if !needsLidar {
                anchors.planes.append(AnchorPlane(worldFromPlane: plane.transform,
                                                  outline: plane.geometry.boundaryVertices.map { SIMD2($0.x, $0.z) }))
            }
            if plane.alignment == .vertical {
                // A vertical plane's normal is its local +Y; across a wall is
                // as good as along it on a quarter-turn grid.
                let normal = plane.transform.columns.1
                walls.append((SIMD2(normal.x, normal.z), plane.planeExtent.width))
                let centre = plane.transform * SIMD4(plane.center, 1)
                let boundary = plane.geometry.boundaryVertices.map { v -> SIMD3<Float> in
                    let w = plane.transform * SIMD4(v, 1)
                    return SIMD3(w.x, w.y, w.z)
                }
                if let wall = VerticalSurface(normal: SIMD3(normal.x, normal.y, normal.z),
                                              point: SIMD3(centre.x, centre.y, centre.z), boundary: boundary) {
                    vertical.append(wall)
                }
                continue
            }
            guard plane.alignment == .horizontal else { continue }
            let height = (plane.transform * SIMD4(plane.center, 1)).y
            switch plane.classification {
            case .floor: surfaces.append(HorizontalSurface(kind: .floor, height: height, extent: nil))
            case .ceiling: surfaces.append(HorizontalSurface(kind: .ceiling, height: height, extent: nil))
            default:
                // Anywhere else only as far as it was measured: its boundary, in world (x, z).
                let boundary = plane.geometry.boundaryVertices.map { v -> SIMD2<Float> in
                    let w = plane.transform * SIMD4(v, 1)
                    return SIMD2(w.x, w.z)
                }
                guard let extent = PlanRectangle.enclosing(boundary) else { continue }
                let kind: HorizontalSurface.Kind
                switch plane.classification {
                case .table, .seat: kind = .support
                default: kind = .unclassified
                }
                surfaces.append(HorizontalSurface(kind: kind, height: height, extent: extent))
            }
        }
        return FrameSnapshot(image: PixelBufferHandoff(frame.capturedImage), depth: grid,
                             intrinsics: intrinsics, worldFromCamera: camera.transform,
                             surfaces: surfaces, time: frame.timestamp, wallGrid: WallGrid.phi(walls),
                             walls: vertical, anchors: anchors)
    }

    private static func copyDepth(_ data: ARDepthData) -> DepthGrid? {
        let map = data.depthMap
        guard CVPixelBufferGetPixelFormatType(map) == kCVPixelFormatType_DepthFloat32 else { return nil }
        let w = CVPixelBufferGetWidth(map), h = CVPixelBufferGetHeight(map)
        var depth = [Float](repeating: 0, count: w * h)
        CVPixelBufferLockBaseAddress(map, .readOnly)
        if let base = CVPixelBufferGetBaseAddress(map) {
            let stride = CVPixelBufferGetBytesPerRow(map)
            depth.withUnsafeMutableBytes { dst in
                for row in 0..<h {
                    memcpy(dst.baseAddress!.advanced(by: row * w * 4), base.advanced(by: row * stride), w * 4)
                }
            }
        }
        CVPixelBufferUnlockBaseAddress(map, .readOnly)
        var confidence: [UInt8]?
        if let conf = data.confidenceMap, CVPixelBufferGetWidth(conf) == w, CVPixelBufferGetHeight(conf) == h {
            var bytes = [UInt8](repeating: 0, count: w * h)
            CVPixelBufferLockBaseAddress(conf, .readOnly)
            if let base = CVPixelBufferGetBaseAddress(conf) {
                let stride = CVPixelBufferGetBytesPerRow(conf)
                bytes.withUnsafeMutableBytes { dst in
                    for row in 0..<h {
                        memcpy(dst.baseAddress!.advanced(by: row * w), base.advanced(by: row * stride), w)
                    }
                }
            }
            CVPixelBufferUnlockBaseAddress(conf, .readOnly)
            confidence = bytes
        }
        return DepthGrid(width: w, height: h, depth: depth, confidence: confidence)
    }
}

#endif
