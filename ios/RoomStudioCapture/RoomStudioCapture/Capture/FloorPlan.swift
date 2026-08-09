/// The live floor plan's data layer (decision 0077 choice 3). A CapturedRoom
/// becomes a small value snapshot — wall segments, furniture footprints, the
/// floor polygon — projected onto the world XZ plane, plus the pure math the
/// renderer needs (room-grid heading, fit-to-rect, corner adjacency).
///
/// Copy-out principle (decision 0076 Q3): extraction runs on RoomPlan's delivery
/// thread and only plain values cross to the MainActor; no RoomPlan type ever
/// reaches view land, and nothing here retains an ARFrame. `FloorPlanFeed` is
/// a SEPARATE ObservableObject from CaptureManager on purpose: camera-pose
/// updates arrive at up to ~20 Hz, and publishing them through CaptureManager
/// would re-render every screen observing it (RootFlowView) at that rate —
/// only FloorPlanView observes the feed.
///
/// Read by: CaptureManager (extraction + publishing), FloorPlanView (render),
/// ReviewView (the built room, static), FloorPlanMathTests (synthetic math) and
/// FloorPlanFixtureTests (the spike CapturedRoom fixture — the same room
/// perception-obj's roomplan_room pins server-side).

import Combine
import Foundation
import RoomPlan
import simd

// MARK: - Snapshot values

/// One wall-plane segment in world XZ. Doors/windows/openings are segments in
/// the same plane as their wall, distinguished by `kind` so the renderer can
/// treat them as cuts in the wall stroke rather than walls of their own.
nonisolated struct FloorPlanWall: Equatable, Identifiable, Sendable {
    enum Kind: Equatable, Sendable { case wall, door, window, opening }
    let id: UUID
    let kind: Kind
    /// Segment endpoints in world XZ (SIMD2 stores (x, z)).
    let start: SIMD2<Float>
    let end: SIMD2<Float>
}

/// One furniture box footprint in world XZ. RoomPlan boxes are upright by
/// construction (0076 Q4: column 1 ≡ +Y, pure yaw), so the footprint is fully
/// described by center + in-plane x-axis + half extents; the local z axis is
/// always rot90(xAxis) for an upright box.
nonisolated struct FloorPlanBox: Equatable, Identifiable, Sendable {
    let id: UUID
    let center: SIMD2<Float>
    /// Unit direction of the box's local X axis in world XZ.
    let xAxis: SIMD2<Float>
    /// (dimensions.x/2, dimensions.z/2) — along xAxis and rot90(xAxis).
    let halfExtents: SIMD2<Float>
    /// RoomPlan's category, as a stable token ("bed", "storage", …) so the
    /// pure layers never import RoomPlan. Unknown future cases pass through
    /// and degrade in FloorPlanVoice's tables.
    let categoryToken: String
    let confidence: FloorPlanConfidence
}

/// CapturedRoom.Confidence, decoupled from RoomPlan for the pure layers.
nonisolated enum FloorPlanConfidence: Equatable, Sendable { case low, medium, high }

/// Where the camera is and which way it looks, in world XZ. `forward` is unit
/// length; when the camera points straight down (XZ-degenerate) the extractor
/// keeps the previous forward rather than publishing a spinning cone.
nonisolated struct FloorPlanCamera: Equatable, Sendable {
    let position: SIMD2<Float>
    let forward: SIMD2<Float>
}

nonisolated struct FloorPlanSnapshot: Equatable, Sendable {
    var walls: [FloorPlanWall] = []
    var boxes: [FloorPlanBox] = []
    /// The floor polygon in world XZ (RoomPlan's corners verbatim, transformed;
    /// empty when no floor has been detected yet).
    var floorPolygon: [SIMD2<Float>] = []
    nonisolated var isEmpty: Bool { walls.isEmpty && boxes.isEmpty && floorPolygon.isEmpty }
}

// MARK: - Extraction from CapturedRoom

extension FloorPlanSnapshot {
    /// Project a CapturedRoom onto the world XZ plane. Pure; safe on the
    /// delegate delivery thread. Degenerate entities (a surface whose in-plane
    /// axis has no XZ component, a zero-width segment) are skipped — a wall
    /// that cannot be drawn honestly is not drawn at all.
    nonisolated init(room: CapturedRoom) {
        var walls: [FloorPlanWall] = []
        func add(_ surfaces: [CapturedRoom.Surface], as kind: FloorPlanWall.Kind) {
            for s in surfaces {
                guard let seg = FloorPlanMath.segment(
                    center: SIMD2(s.transform.columns.3.x, s.transform.columns.3.z),
                    xAxis: SIMD2(s.transform.columns.0.x, s.transform.columns.0.z),
                    width: s.dimensions.x
                ) else { continue }
                walls.append(FloorPlanWall(id: s.identifier, kind: kind,
                                           start: seg.0, end: seg.1))
            }
        }
        add(room.walls, as: .wall)
        add(room.doors, as: .door)
        add(room.windows, as: .window)
        add(room.openings, as: .opening)
        self.walls = walls

        self.boxes = room.objects.compactMap { o in
            let x = SIMD2(o.transform.columns.0.x, o.transform.columns.0.z)
            let len = simd_length(x)
            guard len > 0.5 else { return nil }   // not upright — cannot draw a footprint honestly
            return FloorPlanBox(
                id: o.identifier,
                center: SIMD2(o.transform.columns.3.x, o.transform.columns.3.z),
                xAxis: x / len,
                halfExtents: SIMD2(o.dimensions.x / 2, o.dimensions.z / 2),
                categoryToken: String(describing: o.category),
                confidence: FloorPlanConfidence(o.confidence)
            )
        }

        if let floor = room.floors.first {
            // Corners are in the surface's LOCAL frame; empty corners
            // degrade to the rectangle the dimensions describe.
            let local: [SIMD3<Float>] = floor.polygonCorners.isEmpty
                ? [SIMD3(-floor.dimensions.x / 2, -floor.dimensions.y / 2, 0),
                   SIMD3(floor.dimensions.x / 2, -floor.dimensions.y / 2, 0),
                   SIMD3(floor.dimensions.x / 2, floor.dimensions.y / 2, 0),
                   SIMD3(-floor.dimensions.x / 2, floor.dimensions.y / 2, 0)]
                : floor.polygonCorners
            self.floorPolygon = local.map { c in
                let w = floor.transform * SIMD4(c, 1)
                return SIMD2(w.x, w.z)
            }
        }
    }
}

extension FloorPlanConfidence {
    nonisolated init(_ c: CapturedRoom.Confidence) {
        switch c {
        case .high:   self = .high
        case .medium: self = .medium
        case .low:    self = .low
        @unknown default: self = .low   // trust nothing we don't know
        }
    }
}

// MARK: - Pure math

nonisolated enum FloorPlanMath {

    /// A surface's plan segment from its center, in-plane x axis, and width.
    /// Nil when the axis is XZ-degenerate or the width is unreadably small.
    nonisolated static func segment(center: SIMD2<Float>, xAxis: SIMD2<Float>, width: Float)
        -> (SIMD2<Float>, SIMD2<Float>)?
    {
        let len = simd_length(xAxis)
        guard len > 0.5, width > 0.05 else { return nil }
        let u = xAxis / len
        let h = width / 2
        return (center - h * u, center + h * u)
    }

    /// Rotate a plan point/direction by `angle` radians (counter-clockwise in
    /// the (x, z) plane as stored).
    nonisolated static func rotate(_ p: SIMD2<Float>, by angle: Float) -> SIMD2<Float> {
        let c = cos(angle), s = sin(angle)
        return SIMD2(p.x * c - p.y * s, p.x * s + p.y * c)
    }

    /// 90° counter-clockwise — the local z axis of an upright box whose local
    /// x axis is `a`.
    nonisolated static func rot90(_ a: SIMD2<Float>) -> SIMD2<Float> { SIMD2(-a.y, a.x) }

    /// The room's dominant wall-grid heading in radians, in (-π/4, π/4]:
    /// a length-weighted circular mean over 4·φ, so perpendicular wall
    /// families reinforce the same grid instead of cancelling. Nil until a
    /// wall exists. Rotating the plan by the NEGATED heading squares the room
    /// to the screen.
    nonisolated static func gridHeading(walls: [FloorPlanWall]) -> Float? {
        var sx: Float = 0, sy: Float = 0
        for w in walls {
            let d = w.end - w.start
            let len = simd_length(d)
            guard len > 0.001 else { continue }
            let phi = atan2(d.y, d.x)
            sx += len * cos(4 * phi)
            sy += len * sin(4 * phi)
        }
        guard sx * sx + sy * sy > 1e-9 else { return nil }
        return atan2(sy, sx) / 4
    }

    /// How far apart two headings are on the grid circle (mod π/2), signed,
    /// shortest way — what a renderer smoothing toward a new grid heading
    /// should add. In [-π/4, π/4].
    nonisolated static func gridArc(from: Float, to: Float) -> Float {
        atan2(sin(4 * (to - from)), cos(4 * (to - from))) / 4
    }

    /// Count wall-to-wall corner adjacencies: pairs of `.wall` segments whose
    /// nearest endpoints sit within `joinM` and whose headings differ by
    /// 45°–135° (a corner, not a continuation). Door/window/opening segments
    /// are collinear cuts in a wall and never corners.
    nonisolated static func cornerCount(walls: [FloorPlanWall],
                            joinM: Float = 0.35) -> Int {
        let real = walls.filter { $0.kind == .wall }
        var n = 0
        for i in real.indices {
            for j in real.indices where j > i {
                let a = real[i], b = real[j]
                let dmin = min(
                    simd_distance(a.start, b.start), simd_distance(a.start, b.end),
                    simd_distance(a.end, b.start), simd_distance(a.end, b.end)
                )
                guard dmin < joinM else { continue }
                let ha = atan2(a.end.y - a.start.y, a.end.x - a.start.x)
                let hb = atan2(b.end.y - b.start.y, b.end.x - b.start.x)
                var dh = abs(ha - hb).truncatingRemainder(dividingBy: .pi)
                dh = min(dh, .pi - dh)
                if dh >= .pi / 4, dh <= 3 * .pi / 4 { n += 1 }
            }
        }
        return n
    }

    /// Uniform fit of grid-frame content bounds into a view rect. `minSpanM`
    /// keeps a first lone wall from zooming to fill the screen (the room
    /// should ARRIVE, small and growing); `maxScale` caps points-per-meter for
    /// the same reason.
    struct Fit: Equatable {
        var scale: CGFloat          // points per meter
        var center: SIMD2<Float>    // grid-frame point mapped to the rect center

        nonisolated func apply(_ p: SIMD2<Float>, in size: CGSize) -> CGPoint {
            CGPoint(x: size.width / 2 + CGFloat(p.x - center.x) * scale,
                    y: size.height / 2 + CGFloat(p.y - center.y) * scale)
        }
    }

    nonisolated static func fit(boundsMin: SIMD2<Float>, boundsMax: SIMD2<Float>,
                    into size: CGSize, padding: CGFloat = 24,
                    minSpanM: Float = 2.5, maxScale: CGFloat = 90) -> Fit {
        let span = SIMD2(max(boundsMax.x - boundsMin.x, minSpanM),
                         max(boundsMax.y - boundsMin.y, minSpanM))
        let availW = max(size.width - 2 * padding, 1)
        let availH = max(size.height - 2 * padding, 1)
        let scale = min(availW / CGFloat(span.x), availH / CGFloat(span.y), maxScale)
        return Fit(scale: scale, center: (boundsMin + boundsMax) / 2)
    }

    /// The camera's plan pose from an ARCamera world transform. The camera
    /// looks down its local -Z; when that direction is XZ-degenerate (device
    /// pointing at the floor or ceiling), fall back to `previousForward` so
    /// the cone holds its heading instead of spinning — nil forward only when
    /// there has never been a usable heading.
    nonisolated static func cameraPlanPose(transform t: simd_float4x4,
                               previousForward: SIMD2<Float>?) -> FloorPlanCamera? {
        let position = SIMD2(t.columns.3.x, t.columns.3.z)
        let f = SIMD2(-t.columns.2.x, -t.columns.2.z)
        let len = simd_length(f)
        if len > 0.2 {
            return FloorPlanCamera(position: position, forward: f / len)
        }
        guard let previousForward else { return nil }
        return FloorPlanCamera(position: position, forward: previousForward)
    }
}

// MARK: - Feed

/// A transient line with its arrival time — the view decides freshness with
/// FloorPlanVoice's hold constants.
nonisolated struct FloorPlanEvent: Equatable {
    let line: String
    let at: Date
}

/// The floor plan's own publisher. Deliberately not @Published state on
/// CaptureManager — see the header note on render fan-out.
@MainActor
final class FloorPlanFeed: ObservableObject {
    @Published private(set) var snapshot = FloorPlanSnapshot()
    @Published private(set) var camera: FloorPlanCamera?
    /// The latest "new piece" moment (didAdd). Latest-wins by design: the plan
    /// itself shows every box landing; this line is a grace note, not a ledger.
    @Published private(set) var moment: FloorPlanEvent?
    /// RoomPlan's active guidance, mapped to the guest's voice. Nil when
    /// guidance stands down (.normal) or none has arrived.
    @Published private(set) var guidance: FloorPlanEvent?
    /// Census counts + when they last CHANGED — what the "enough" line reads.
    @Published private(set) var census: RoomCensus?
    @Published private(set) var censusChangedAt: Date?

    func publish(snapshot: FloorPlanSnapshot) {
        guard snapshot != self.snapshot else { return }
        self.snapshot = snapshot
    }

    func publish(camera: FloorPlanCamera) { self.camera = camera }

    func noteMoment(line: String, at: Date = Date()) {
        moment = FloorPlanEvent(line: line, at: at)
    }

    /// nil line = stand down now (RoomPlan sent .normal or an unknown case).
    func noteGuidance(line: String?, at: Date = Date()) {
        guidance = line.map { FloorPlanEvent(line: $0, at: at) }
    }

    func publish(census: RoomCensus, at: Date = Date()) {
        guard census != self.census else { return }
        self.census = census
        censusChangedAt = at
    }

    func reset() {
        snapshot = FloorPlanSnapshot()
        camera = nil
        moment = nil
        guidance = nil
        census = nil
        censusChangedAt = nil
    }
}
