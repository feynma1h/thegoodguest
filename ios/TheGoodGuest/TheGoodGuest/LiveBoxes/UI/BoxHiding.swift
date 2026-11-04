/// Whether a wall or another piece of furniture hides a dot or a box from where
/// the camera stands now — DEBUG-only (decision 0295).
///
/// A wall hides what is behind it, and the next room's boxes must not show
/// through. Three things judge it, for any depth source:
///   • the DEPTH of the latest pass, read in the direction of each of a box's
///     probe points: a surface nearer than the object could reach is in front
///     of it (`BoxOcclusion.isBlocked(depth:measured:radius:)`);
///   • ARKit's WALL planes, checked every frame from where the camera is NOW: a
///     plane counts as a wall only when measured wide and tall enough
///     (`isWall`), the camera must be clear of it, and the depth read at the
///     crossing must be the plane itself (`crossing`, `isBlocked(wallDepth:)`),
///     so an opening in a wall does not hide what is seen through it;
///   • what was REMEMBERED from this spot (`VisibilityMemory`), for the boxes a
///     pass cannot see from here, as the boxes of the room you just came back to.
/// A box hides when most of its READABLE points are blocked and returns when
/// few are; with too few readable points the verdict is left as it was
/// (`judge`, `verdict`). A few frames of agreement are needed either way.
///
/// Read by: LiveBoxesARHost, LiveBoxesHidingTests.

#if DEBUG

import Foundation
import simd

/// What was visible from where. Whether a wall or a piece of furniture hides a box depends on
/// where the camera stands, not which way it points, so a verdict is kept per box by the place
/// the camera stood (cells 0.4 m across, on the floor plan). A box no depth pass can judge from
/// here (it is off the pass's view, as the boxes of the room you just came back to are) takes the
/// verdict remembered from this cell or the next, at once. A pass that can judge it overrides.
nonisolated struct VisibilityMemory {
    static let cell: Float = 0.4
    static let cellsPerBox = 300

    private struct Cell: Hashable { let x: Int32, z: Int32 }
    private var seen: [UUID: [Cell: (blocked: Bool, order: Int)]] = [:]
    private var counter = 0

    private static func cell(_ p: SIMD3<Float>) -> Cell {
        Cell(x: Int32((p.x / cell).rounded(.down)), z: Int32((p.z / cell).rounded(.down)))
    }

    mutating func note(_ id: UUID, from camera: SIMD3<Float>, blocked: Bool) {
        counter += 1
        var cells = seen[id, default: [:]]
        cells[Self.cell(camera)] = (blocked, counter)
        if cells.count > Self.cellsPerBox, let oldest = cells.min(by: { $0.value.order < $1.value.order })?.key {
            cells[oldest] = nil
        }
        seen[id] = cells
    }

    /// The verdict remembered from this cell, else the nearest cell beside it (the newest on a tie).
    func verdict(_ id: UUID, from camera: SIMD3<Float>) -> Bool? {
        guard let cells = seen[id] else { return nil }
        let here = Self.cell(camera)
        var best: (distance: Int32, order: Int, blocked: Bool)?
        for dx: Int32 in -1...1 {
            for dz: Int32 in -1...1 {
                guard let found = cells[Cell(x: here.x + dx, z: here.z + dz)] else { continue }
                let distance = abs(dx) + abs(dz)
                if let current = best, distance > current.distance || (distance == current.distance && found.order < current.order) {
                    continue
                }
                best = (distance, found.order, found.blocked)
            }
        }
        return best?.blocked
    }

    mutating func keep(only ids: Set<UUID>) {
        seen = seen.filter { ids.contains($0.key) }
    }
}

/// Whether something stands between the camera and a dot or a box, read from the
/// depth in the dot's direction: the depth there is nearer than the object
/// could be even at its front surface. A wall, say, with the next room's boxes behind it.
nonisolated struct BoxOcclusion {
    /// Metres of slack beyond the object's own reach, for depth noise and a
    /// camera that is not quite looking at the centre, plus a share of the range:
    /// a model's depth is off by a few percent of it, LiDAR's by far less.
    static let margin: Float = 0.25
    static let rangeShare: Float = 0.03
    /// Seconds a dot must be judged blocked, every frame, before it hides, and judged clear
    /// before it returns: a few frames, so one noisy one does not flicker it.
    static let secondsToHide = 0.15
    static let secondsToShow = 0.1
    /// Fewer readable points than this and the verdict is left as it was: a box mostly out
    /// of frame, or far off, is not judged on one corner.
    static let minimumReadable = 4
    /// Blocked at or above this share of the readable points, or clear at or below the other;
    /// between them, left as it was.
    static let hideShare: Float = 0.7
    static let showShare: Float = 0.35

    /// `depth`: how far along the camera's axis the point is;
    /// `measured`: the depth read in that direction, 0 or less if none.
    static func isBlocked(depth: Float, measured: Float, radius: Float) -> Bool {
        measured > 0.05 && measured < depth - (radius + margin + rangeShare * depth)
    }

    /// A plane counts as a wall only when ARKit measured it this wide and this tall: a furniture
    /// front or a curtain is neither, and standing on one side of it is not being in another room.
    static let minimumWallWidth: Float = 1.0
    static let minimumWallHeight: Float = 1.2
    /// The camera must be this far from a wall's plane, on one side: nearer than that, the
    /// plane's own position error decides which side it is on.
    static let cameraClearance: Float = 0.2

    static func isWall(_ wall: VerticalSurface) -> Bool {
        wall.along.upperBound - wall.along.lowerBound >= minimumWallWidth
            && wall.heights.upperBound - wall.heights.lowerBound >= minimumWallHeight
    }

    /// Where the line from the camera to a point crosses a wall that lies between them, and
    /// which wall (its index in `walls`): the camera clear of it, the point beyond it by at
    /// least `beyond` metres, and the crossing on the part of it ARKit measured (plus a
    /// margin). Nil when no wall is in the way.
    static func crossing(from camera: SIMD3<Float>, to point: SIMD3<Float>, walls: [VerticalSurface],
                         beyond: Float = 0.1, reach: Float = 0.3) -> (at: SIMD3<Float>, wall: Int)? {
        for (index, wall) in walls.enumerated() where isWall(wall) {
            let near = wall.distance(camera), far = wall.distance(point)
            guard near * far < 0, abs(near) >= cameraClearance, abs(far) >= beyond else { continue }
            let at = camera + (point - camera) * (near / (near - far))
            if wall.covers(at, margin: reach) { return (at, index) }
        }
        return nil
    }

    /// A wall plane crosses the line at `wallDepth` and the depth read there is that plane
    /// itself, within the slack: not something farther seen through an opening, and not some
    /// other surface nearer than it, which would confirm a plane that is not there.
    static func isBlocked(wallDepth: Float?, measured: Float) -> Bool {
        guard let wallDepth, measured > 0.05 else { return false }
        return abs(measured - wallDepth) <= margin + rangeShare * wallDepth
    }

    /// What a pass's readable points say of a box.
    enum Judgment: Equatable {
        case blocked, clear
        /// Between the two shares: leave the box as it was.
        case unsure
        /// Too few readable points to say: ask what was remembered from here.
        case unreadable
    }

    static func judge(blocked: Int, of read: Int) -> Judgment {
        guard read >= minimumReadable else { return .unreadable }
        let share = Float(blocked) / Float(read)
        if share >= hideShare { return .blocked }
        if share <= showShare { return .clear }
        return .unsure
    }

    /// The judgment as a verdict: blocked, clear, or nil to leave the box as it was.
    static func verdict(blocked: Int, of read: Int) -> Bool? {
        switch judge(blocked: blocked, of: read) {
        case .blocked: return true
        case .clear: return false
        case .unsure, .unreadable: return nil
        }
    }

    private var blockedSince: [UUID: Double] = [:]
    private var clearSince: [UUID: Double] = [:]
    private(set) var hidden: Set<UUID> = []

    /// One frame's verdict for one object, at `time` seconds. Returns whether it hid or returned.
    @discardableResult
    mutating func update(_ id: UUID, blocked isBlocked: Bool?, at time: Double = 0) -> Bool {
        guard let isBlocked else { return false }
        if isBlocked {
            clearSince[id] = nil
            let since = blockedSince[id] ?? time
            blockedSince[id] = since
            if time - since >= Self.secondsToHide, hidden.insert(id).inserted { return true }
        } else {
            blockedSince[id] = nil
            let since = clearSince[id] ?? time
            clearSince[id] = since
            if time - since >= Self.secondsToShow, hidden.remove(id) != nil { return true }
        }
        return false
    }

    /// Forget objects that are gone.
    mutating func keep(only ids: Set<UUID>) {
        blockedSince = blockedSince.filter { ids.contains($0.key) }
        clearSince = clearSince.filter { ids.contains($0.key) }
        hidden = hidden.intersection(ids)
    }
}

/// The per-frame hiding of the dots and boxes the camera layer draws: one
/// instance per camera, fed the scene's subjects, the latest pass's depth and
/// the camera's position every frame.
nonisolated struct BoxHider {
    /// One dot or box to judge: how far the object reaches from its centre,
    /// and points on it (its centre, then its box's corners), world coordinates.
    struct Subject {
        let id: UUID
        let radius: Float
        let probes: [SIMD3<Float>]
    }

    private typealias Reading = (world: SIMD3<Float>, byDepth: Bool)

    private var occlusion = BoxOcclusion()
    private var memory = VisibilityMemory()
    private var readings: [UUID: [Reading]] = [:]
    private var sightTime: Double?
    private var notes = 0

    /// The ids hidden now.
    var hidden: Set<UUID> { occlusion.hidden }

    /// Judge every subject for this frame. When a depth pass arrives, each
    /// subject's points are read against it. Every frame after that, those
    /// points are checked against the wall planes from where the camera is now,
    /// so stepping round a wall changes the verdict this frame, not at the next
    /// pass. Returns a line for the session log for each subject that hid or
    /// returned, up to 250 a session.
    mutating func update(_ subjects: [Subject], sight: DepthSight?, camera: SIMD3<Float>?, now: Double) -> [String] {
        guard let sight, let camera else { return [] }
        if sight.time != sightTime {
            sightTime = sight.time
            readings = readPoints(of: subjects, in: sight)
        }
        let grid = sight.grid
        var lines: [String] = []
        for subject in subjects {
            guard let points = readings[subject.id] else { continue }
            var byDepth = 0, byWall = 0
            var blame: [Int: Int] = [:]
            for point in points {
                if point.byDepth { byDepth += 1; continue }
                if let crossing = BoxOcclusion.crossing(from: camera, to: point.world, walls: sight.walls),
                   let hit = sight.frame.depthProjection(world: crossing.at), hit.depth > 0 {
                    let x = Int(hit.point.x.rounded(.down)), y = Int(hit.point.y.rounded(.down))
                    if x >= 0, x < grid.width, y >= 0, y < grid.height,
                       let measured = grid.medianDepth(x: x, y: y, radius: 1, minimumConfidence: 1),
                       BoxOcclusion.isBlocked(wallDepth: hit.depth, measured: measured) {
                        byWall += 1
                        blame[crossing.wall, default: 0] += 1
                    }
                }
            }
            let blocked = byDepth + byWall
            // A pass that can judge the box decides, and is remembered for this spot; one that
            // cannot (the box is off its view) asks what was remembered from here.
            var verdict: Bool?
            var remembered = false
            switch BoxOcclusion.judge(blocked: blocked, of: points.count) {
            case .blocked: verdict = true; memory.note(subject.id, from: camera, blocked: true)
            case .clear: verdict = false; memory.note(subject.id, from: camera, blocked: false)
            case .unsure: break
            case .unreadable:
                verdict = memory.verdict(subject.id, from: camera)
                remembered = verdict != nil
            }
            if occlusion.update(subject.id, blocked: verdict, at: now), notes < 250 {
                notes += 1
                let hid = occlusion.hidden.contains(subject.id)
                var line = "box \(subject.id.uuidString.prefix(4)) r\(String(format: "%.1f", subject.radius)): blocked \(blocked) of \(points.count)"
                    + " (wall \(byWall), depth \(byDepth)) → " + (hid ? "hidden" : "shown")
                    + (remembered ? " (remembered from here)" : "")
                // Which plane did it: its size, and how far the camera is from it.
                if hid, let top = blame.max(by: { $0.value < $1.value }), sight.walls.indices.contains(top.key) {
                    let wall = sight.walls[top.key]
                    line += String(format: " by plane #%d %.1f m wide, %.1f m tall, normal (%.2f, %.2f), camera %.2f m from it, %d points",
                                   top.key, wall.along.upperBound - wall.along.lowerBound,
                                   wall.heights.upperBound - wall.heights.lowerBound, wall.normal.x, wall.normal.y,
                                   wall.distance(camera), top.value)
                }
                lines.append(line)
            }
        }
        let ids = Set(subjects.map(\.id))
        occlusion.keep(only: ids)
        memory.keep(only: ids)
        readings = readings.filter { ids.contains($0.key) }
        return lines
    }

    /// The points of each subject that a depth pass can read: on screen in the
    /// pass's frame with a depth there, and whether a surface is nearer than
    /// the object could reach.
    private func readPoints(of subjects: [Subject], in sight: DepthSight) -> [UUID: [Reading]] {
        let grid = sight.grid
        var out: [UUID: [Reading]] = [:]
        for subject in subjects where !subject.probes.isEmpty {
            var points: [Reading] = []
            for probe in subject.probes {
                guard let hit = sight.frame.depthProjection(world: probe), hit.depth > 0 else { continue }
                let x = Int(hit.point.x.rounded(.down)), y = Int(hit.point.y.rounded(.down))
                guard x >= 0, x < grid.width, y >= 0, y < grid.height,
                      let measured = grid.medianDepth(x: x, y: y, radius: 1, minimumConfidence: 1) else { continue }
                points.append((probe, BoxOcclusion.isBlocked(depth: hit.depth, measured: measured, radius: subject.radius)))
            }
            out[subject.id] = points
        }
        return out
    }
}

#endif
