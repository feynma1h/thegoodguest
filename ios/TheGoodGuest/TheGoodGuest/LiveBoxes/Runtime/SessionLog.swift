/// The live-boxes session log: numbers and box geometry, never
/// pixels — DEBUG-only (decision 0295).
///
/// One JSON document per session, written to the app's Documents under
/// `live-boxes/`, where `xcrun devicectl device copy from --domain-type
/// appDataContainer` reaches it. It is rewritten whole every 10 seconds and on
/// stop, so a session the phone kills leaves all but its last few seconds: the
/// first walk died with no crash report, between two saves 30 seconds apart.
///
/// WHAT IT NEVER HOLDS: an image, a mask, a depth map, or anything about a
/// person. Excluded detections are counted and nothing else — they are never
/// lifted, so there is no geometry of theirs to write (0089), and they are
/// never among the misses.
///
/// WHY AN OBJECT GOT NO DOT. Every other detection that became no sighting of
/// any track is tallied by name, reason and the 50 cm floor cell it was over
/// (`MissTally`), so a walk past a glass table that never got a dot says
/// whether it was seen at all, under what name, and which rule stopped it.
///
/// WHERE EACH PASS'S DEPTH CAME FROM. Every pass names its depth source; a pass
/// whose depth came from a model carries the model's fit to ARKit's anchors
/// and, on a phone with LiDAR, its score against LiDAR's depth of the same
/// frame. A model's frame that could not be fitted ran no detector, and is
/// kept apart in `depthFailures` with the reason.
///
/// Times are seconds since the session started, on the ARKit frame clock.
///
/// Read by: LiveBoxesSession (records and writes), LiveBoxesRuntimeTests, LiveBoxesDepthTests.

#if DEBUG

import Foundation
import simd

nonisolated struct SessionLog: Codable, Sendable {
    static let currentSchema = "live-boxes-log/1"

    var schema = SessionLog.currentSchema
    /// Wall-clock start, ISO 8601, for filing only.
    var startedAt: String
    var device: Device
    /// Every detector configuration the session ran, in order.
    var detectors: [Detector] = []
    var lift: DepthLiftParameters
    var fusion: FusionParameters
    var samples: [Sample] = []
    var events: [Event] = []
    /// Passes that ran. One that could not run is counted in `failedPasses`
    /// and never timed.
    var passes: [Pass] = []
    var failedPasses = 0
    var tracks: [Track] = []
    var roomPlanObjects: [RoomPlanObject] = []
    /// Detections that became no sighting, most frequent first (`MissTally`).
    var misses: [Miss] = []
    /// Every depth model the session loaded, in order.
    var depthModels: [DepthModel] = []
    /// A model's frames that gave no depth, so ran no detector.
    var depthFailures: [DepthFailure] = []
    var summary: Summary?

    struct Device: Codable, Sendable, Equatable {
        var model: String
        var system: String
        var app: String
        /// Whether the build was compiled with optimisation. Decode, lift and
        /// fuse are Swift: an unoptimised build times the compiler, not the method.
        var optimized: Bool
    }

    /// `assert` evaluates its condition only in an unoptimised build.
    static var isOptimizedBuild: Bool {
        var optimized = true
        assert({ optimized = false; return true }())
        return optimized
    }

    struct Detector: Codable, Sendable, Equatable {
        var t: Double
        var model: String
        var inputWidth: Int
        var inputHeight: Int
        var classes: Int
        var compute: String
        var targetRateHz: Double
        var scoreThreshold: Float
        /// The depth source the configuration ran on: `LiDAR`, or a model's name.
        var depth: String? = nil
    }

    /// A depth model as it was loaded, and the parameters its passes lifted
    /// and fused with in place of LiDAR's.
    struct DepthModel: Codable, Sendable, Equatable {
        var t: Double
        var name: String
        var kind: String
        var source: String?
        var license: String?
        var inputWidth: Int
        var inputHeight: Int
        var compute: String
        /// Loading it and one prediction, seconds.
        var loadSeconds: Double
        var lift: DepthLiftParameters
        var fusion: FusionParameters
    }

    /// A model's frame that gave no depth: which, why, and what it cost.
    struct DepthFailure: Codable, Sendable, Equatable {
        var t: Double
        var depth: DepthPassLog
        /// The model's prediction, milliseconds; 0 when it never ran.
        var predictMs: Double
    }

    /// One reading a second.
    struct Sample: Codable, Sendable, Equatable {
        var t: Double
        var tracking: String
        var thermal: String
        var roomPlan: Bool
        var arFrameRate: Double
        var passRate: Double
        var predictP50: Double?
        var predictP95: Double?
        var passP50: Double?
        var tracks: Int
        var confirmed: Int
        var availableMemoryMB: Double?
        /// Frames since the last sample by what became of them: "started" a
        /// pass, or the `PassGate` that held them.
        var frames: [String: Int] = [:]
        /// How long the pass then running had been running, seconds.
        var passRunningFor: Double?
        /// The app's physical memory footprint, which the system's limit is
        /// measured against, and how many voxels the tracks hold: free memory
        /// fell in steps on the phone, and these say whose steps they are.
        var footprintMB: Double?
        var voxels: Int?
        /// The footprint's tagged parts and malloc's heap (`MemoryReading`):
        /// the steps matched no voxel count, so these say which part took them.
        var graphicsMB: Double?
        var neuralMB: Double?
        var mediaMB: Double?
        var heapMB: Double?
        /// Tracks whose box is locked: the boxes on screen.
        var locked: Int?
    }

    struct Event: Codable, Sendable, Equatable {
        var t: Double
        var kind: String
        var value: String
    }

    struct Pass: Codable, Sendable, Equatable {
        var t: Double
        var timing: PassTiming
        var detections: Int
        var lifted: Int
        var excluded: Int
        var turn: Int
        /// Detections not lifted because they covered too little of the view.
        var tooSmall = 0
        /// Where its depth came from; for a model's, the fit and LiDAR's score.
        var depth: DepthPassLog? = nil
    }

    struct Box: Codable, Sendable, Equatable {
        var center: [Float]
        var size: [Float]
        var yawDegrees: Float

        init(_ box: GravityBox) {
            center = [box.center.x, box.center.y, box.center.z]
            size = [box.size.x, box.size.y, box.size.z]
            yawDegrees = box.yaw * 180 / .pi
        }
    }

    struct Track: Codable, Sendable, Equatable {
        var id: String
        var label: String
        var name: String
        var names: [String: Float]
        var bestScore: Float
        var hits: Int
        var misses: Int
        var arcDegrees: Int
        var firstSeen: Double
        var lastSeen: Double
        var confirmed: Bool
        /// The fit as of the save.
        var box: Box
        /// The box the person finished, and when; nil while they had not.
        var locked: Box?
        var lockedAt: Double?
        /// RoomPlan's category, for a track of one of RoomPlan's own classes.
        var roomPlanCategory: String?
        /// The RoomPlan category a long-tail track sits on and may double.
        var duplicatesRoomPlan: String?
        /// For a RoomPlan-class track: how it agrees with RoomPlan's box.
        var roomPlanAgreement: BoxAgreement?
        /// How far this box's fit moved between passes — what a finished
        /// box keeps off the screen.
        var movement = TrackMovement()
        /// Its box was fitted to outlines: LiDAR saw through it.
        var seenThrough = false
    }

    /// Detections of one name that became no sighting for one reason, over
    /// one 50 cm cell of the floor.
    struct Miss: Codable, Sendable, Equatable {
        var name: String
        var reason: String
        var count: Int
        var bestScore: Float
        /// Where they were, on average, in world coordinates; nil when no
        /// depth around them was measured.
        var at: [Float]?
    }

    struct RoomPlanObject: Codable, Sendable, Equatable {
        var id: String
        var category: String
        var confidence: String
        var box: Box
    }

    struct Summary: Codable, Sendable, Equatable {
        var durationSeconds: Double
        var passes: Int
        var failedPasses: Int
        var meanPassRate: Double
        var predictP50: Double?
        var predictP95: Double?
        var passP50: Double?
        var trackingSeconds: [String: Double]
        var thermalSeconds: [String: Double]
        var roomPlanOnSeconds: Double
        var confirmedTracks: Int
        var lowestAvailableMemoryMB: Double?
    }

    /// Record one pass's result. A pass that could not run is not a pass: it
    /// is counted, its reason is written when it differs from the last one
    /// written, and it enters neither the timings nor the rate. Returns
    /// whether the pass ran.
    mutating func record(_ result: PassResult, at t: Double) -> Bool {
        guard let failure = result.failure else {
            passes.append(Pass(t: t, timing: result.timing, detections: result.detections,
                               lifted: result.lifted, excluded: result.excluded, turn: result.turn.rawValue,
                               tooSmall: result.tooSmall, depth: result.depth))
            return true
        }
        failedPasses += 1
        if let depth = result.depth, depth.failure != nil {
            depthFailures.append(DepthFailure(t: t, depth: depth, predictMs: result.timing.depth))
        }
        if events.last(where: { $0.kind == "pass failed" })?.value != failure {
            events.append(Event(t: t, kind: "pass failed", value: failure))
        }
        return false
    }

    /// The summary over everything recorded so far, as of `now`.
    func summarised(now: Double, tracking: StateDurations, thermal: StateDurations,
                    roomPlan: StateDurations) -> Summary {
        let predicts = passes.map(\.timing.predict)
        return Summary(durationSeconds: now,
                       passes: passes.count,
                       failedPasses: failedPasses,
                       meanPassRate: now > 0 ? Double(passes.count) / now : 0,
                       predictP50: Percentile.of(predicts, 0.5),
                       predictP95: Percentile.of(predicts, 0.95),
                       passP50: Percentile.of(passes.map(\.timing.total), 0.5),
                       trackingSeconds: tracking.durations(until: now),
                       thermalSeconds: thermal.durations(until: now),
                       roomPlanOnSeconds: roomPlan.durations(until: now)["on"] ?? 0,
                       confirmedTracks: tracks.filter(\.confirmed).count,
                       lowestAvailableMemoryMB: samples.compactMap(\.availableMemoryMB).min())
    }

    /// The document, pretty-printed with sorted keys so two logs diff cleanly.
    func encoded() throws -> Data {
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
        encoder.nonConformingFloatEncodingStrategy = .convertToString(
            positiveInfinity: "inf", negativeInfinity: "-inf", nan: "nan")
        return try encoder.encode(self)
    }

    /// Where logs live: Documents/live-boxes/.
    static func directory(fileManager: FileManager = .default) -> URL {
        fileManager.urls(for: .documentDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("live-boxes", isDirectory: true)
    }

    /// `live-boxes-20260915-101500.json`, from the start time in the device's zone.
    static func fileName(startedAt date: Date, calendar: Calendar = .current) -> String {
        let c = calendar.dateComponents([.year, .month, .day, .hour, .minute, .second], from: date)
        return String(format: "live-boxes-%04d%02d%02d-%02d%02d%02d.json",
                      c.year ?? 0, c.month ?? 0, c.day ?? 0, c.hour ?? 0, c.minute ?? 0, c.second ?? 0)
    }
}

/// Detections that became no sighting, tallied by detector name, reason and
/// the 50 cm floor cell they were over: one entry per object and reason, as
/// near as the floor can say which object it was.
nonisolated struct MissTally: Sendable {
    static let cell: Float = 0.5

    private struct Key: Hashable {
        let name: String
        let reason: MissReason
        let cell: SIMD2<Int32>?
    }

    private struct Count {
        var count = 0
        var best: Float = 0
        var sum = SIMD3<Float>()
        var placed = 0
    }

    private var counts: [Key: Count] = [:]

    mutating func add(_ misses: [DetectionMiss]) {
        for miss in misses {
            let cell = miss.at.map {
                SIMD2(Int32(($0.x / Self.cell).rounded(.down)), Int32(($0.z / Self.cell).rounded(.down)))
            }
            let key = Key(name: miss.name, reason: miss.reason, cell: cell)
            var c = counts[key] ?? Count()
            c.count += 1
            c.best = max(c.best, miss.score)
            if let at = miss.at {
                c.sum += at
                c.placed += 1
            }
            counts[key] = c
        }
    }

    /// The tally as the log writes it, most frequent first.
    var entries: [SessionLog.Miss] {
        counts.map { key, c in
            let mean = c.placed > 0 ? c.sum / Float(c.placed) : nil
            return SessionLog.Miss(name: key.name, reason: key.reason.rawValue, count: c.count, bestScore: c.best,
                                   at: mean.map { [$0.x, $0.y, $0.z] })
        }
        .sorted { a, b in a.count != b.count ? a.count > b.count : (a.name, a.reason) < (b.name, b.reason) }
    }
}

#endif
