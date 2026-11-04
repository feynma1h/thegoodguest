/// What live boxes costs, measured as it runs — DEBUG-only
/// (decision 0295). Pure values over timestamps, so the arithmetic behind
/// every number in its log is pinned by
/// LiveBoxesCostTests rather than read off a UI.
///
/// Four quantities, each over a stated window:
///   • detector LATENCY — the Core ML prediction alone, p50 and p95, over the
///     last 30 s. Preprocessing and lifting are timed separately, because the
///     question "can the Neural Engine keep up beside RoomPlan" is about the
///     prediction. A depth model's prediction, when one is the depth source,
///     is timed the same way and apart.
///   • effective DETECTION RATE — detector passes completed per second over
///     the last 10 s, whatever they found. A pass that found nothing still
///     looked.
///   • ARKit FRAME RATE — frames delivered per second over the last 2 s: the
///     first thing to fall if the detector starves tracking.
///   • TIME IN STATE — how long tracking and thermal state spent in each
///     value, so "five minutes" can be read as "four of them serious".
///   • MEMORY — the app's footprint, which the system's limit is measured
///     against, split the way the kernel accounts it (`MemoryReading`).
///
/// Read by: LiveBoxesSession, SessionLog, DetectorPipeline, LiveBoxesRuntimeTests.

#if DEBUG

import Darwin
import Foundation

nonisolated enum Percentile {
    /// The nearest-rank percentile (q in 0…1) of `values`, or nil when empty.
    static func of(_ values: [Double], _ q: Double) -> Double? {
        guard !values.isEmpty else { return nil }
        let sorted = values.sorted()
        let rank = Int((q * Double(sorted.count)).rounded(.up))
        return sorted[min(max(rank - 1, 0), sorted.count - 1)]
    }
}

/// The time a pass spent in each stage, milliseconds.
nonisolated struct PassTiming: Sendable, Equatable, Codable {
    var preprocess: Double = 0
    var predict: Double = 0
    var decode: Double = 0
    var lift: Double = 0
    var fuse: Double = 0
    /// A depth model's prediction, then fitting its map (and scoring it
    /// against LiDAR); both 0 when LiDAR is the source.
    var depth: Double = 0
    var align: Double = 0

    var total: Double { preprocess + predict + decode + lift + fuse + depth + align }
}

nonisolated struct CostMeter: Sendable {
    static let latencyWindow: Double = 30
    static let rateWindow: Double = 10
    static let frameWindow: Double = 2

    private var passes: [(time: Double, timing: PassTiming)] = []
    private var frames: [Double] = []

    mutating func notePass(at time: Double, timing: PassTiming) {
        passes.append((time, timing))
        passes.removeAll { $0.time < time - Self.latencyWindow }
    }

    mutating func noteFrame(at time: Double) {
        frames.append(time)
        if frames.count > 512 { frames.removeFirst(frames.count - 512) }
    }

    /// Prediction latency p50 and p95 over the latency window.
    func predictLatency(now: Double) -> (p50: Double, p95: Double)? {
        let recent = passes.filter { $0.time >= now - Self.latencyWindow }.map(\.timing.predict)
        guard let p50 = Percentile.of(recent, 0.5), let p95 = Percentile.of(recent, 0.95) else { return nil }
        return (p50, p95)
    }

    /// Whole-pass time p50 over the latency window.
    func passLatency(now: Double) -> Double? {
        Percentile.of(passes.filter { $0.time >= now - Self.latencyWindow }.map(\.timing.total), 0.5)
    }

    /// A depth model's prediction p50 over the latency window; nil while
    /// LiDAR is the source.
    func depthLatency(now: Double) -> Double? {
        Percentile.of(passes.filter { $0.time >= now - Self.latencyWindow && $0.timing.depth > 0 }
            .map(\.timing.depth), 0.5)
    }

    /// Passes per second over the rate window. Before a full window has
    /// elapsed since `startedAt`, the rate is over the time actually elapsed.
    func detectionRate(now: Double, startedAt: Double) -> Double {
        let span = min(Self.rateWindow, max(now - startedAt, 0))
        guard span > 0.5 else { return 0 }
        return Double(passes.filter { $0.time >= now - span && $0.time <= now }.count) / span
    }

    /// ARKit frames per second over the frame window.
    func frameRate(now: Double) -> Double {
        let span = Self.frameWindow
        return Double(frames.filter { $0 > now - span && $0 <= now }.count) / span
    }
}

/// The app's memory in MB, as the kernel accounts it. The footprint is what
/// the system's limit is measured against; graphics (Metal, RealityKit),
/// neural (Core ML on the Neural Engine) and media (camera buffers) are the
/// parts of it the kernel tags; the heap is what malloc holds — the tracks,
/// and ARKit's own maps. On the phone the footprint climbed in steps of
/// 30–150 MB that matched neither passes nor the voxels the tracks held,
/// so a reading says which of these moved.
nonisolated struct MemoryReading: Sendable, Equatable {
    var footprintMB: Double
    var graphicsMB: Double
    var neuralMB: Double
    var mediaMB: Double
    var heapMB: Double

    static func current() -> MemoryReading? {
        var info = task_vm_info_data_t()
        var count = mach_msg_type_number_t(MemoryLayout<task_vm_info_data_t>.size / MemoryLayout<natural_t>.size)
        let result = withUnsafeMutablePointer(to: &info) {
            $0.withMemoryRebound(to: integer_t.self, capacity: Int(count)) {
                task_info(mach_task_self_, task_flavor_t(TASK_VM_INFO), $0, &count)
            }
        }
        guard result == KERN_SUCCESS else { return nil }
        var heap = malloc_statistics_t()
        malloc_zone_statistics(nil, &heap)
        let mb = 1_048_576.0
        return MemoryReading(footprintMB: Double(info.phys_footprint) / mb,
                             graphicsMB: Double(info.ledger_tag_graphics_footprint) / mb,
                             neuralMB: Double(info.ledger_tag_neural_footprint) / mb,
                             mediaMB: Double(info.ledger_tag_media_footprint) / mb,
                             heapMB: Double(heap.size_in_use) / mb)
    }
}

/// How long something spent in each of its states.
nonisolated struct StateDurations: Sendable, Equatable {
    private(set) var totals: [String: Double] = [:]
    private(set) var current: String?
    private var since: Double = 0

    /// Enter `state` at `time`. Re-entering the current state changes nothing.
    mutating func note(_ state: String, at time: Double) {
        guard state != current else { return }
        if let current { totals[current, default: 0] += max(time - since, 0) }
        current = state
        since = time
    }

    /// Totals including the time spent in the current state up to `time`.
    func durations(until time: Double) -> [String: Double] {
        var out = totals
        if let current { out[current, default: 0] += max(time - since, 0) }
        return out
    }
}

#endif
