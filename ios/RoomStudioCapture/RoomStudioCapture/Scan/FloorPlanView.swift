/// The Good Guest live floor plan (decision 0077 choice 3) — the room
/// drawing itself in ink as RoomPlan finds it. Replaces the gold-ink mesh
/// placeholder behind LiveCaptureView's `LiveMeshHost` seam, and reappears at
/// review, static, as "the room you got".
///
/// THE RULE OF GOLD, applied: the drawn room is mesh ink — the light-semantic
/// use RSColor names explicitly (what the scan's light has revealed), same
/// family the placeholder and RoomSketch already used. The camera cone is the
/// brightest gold (the light being cast NOW); labels are machine data in
/// cream mono; nothing gold is ornament.
///
/// Rendering: SwiftUI Canvas inside a TimelineView. Walls stroke in from
/// their middles as they land; boxes settle in with a scale+fade; doors and
/// windows read as cuts in the wall line (a gap painted in the backdrop
/// color — no swing arcs: RoomPlan wall normals are not reliably interior
/// (measured on the reference room, 2 of its 13 walls point away), so a
/// swung door would be a guess). The plan keeps the room squared to the
/// screen via the wall-grid heading, smoothed;
/// Reduce Motion collapses every entrance to its finished state.
///
/// Read by: LiveCaptureView (live, via FloorPlanFeed), ReviewView (static).

import SwiftUI
import simd

// MARK: - The canvas

struct FloorPlanCanvas: View {
    var snapshot: FloorPlanSnapshot
    var camera: FloorPlanCamera? = nil
    /// False = review mode: everything drawn settled, no timeline.
    var animated: Bool = true
    /// Freezes the animation clock (tracking lost); the live wrapper also dims.
    var paused: Bool = false
    /// The surface behind the plan — door/window gaps are painted in it.
    var backdrop: Color = .rsCaptureBase
    /// Fit padding inside the canvas, in points.
    var padding: CGFloat = 24

    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @Environment(\.dynamicTypeSize) private var typeSize
    @State private var reveal = RevealClock()
    @State private var smoothing = PlanSmoothing()

    var body: some View {
        Group {
            if animated {
                TimelineView(.animation(paused: paused)) { timeline in
                    Canvas { context, size in
                        draw(&context, size: size, now: timeline.date)
                    }
                }
            } else {
                Canvas { context, size in
                    draw(&context, size: size, now: .distantFuture)
                }
            }
        }
        .onAppear { reveal.note(snapshot: snapshot) }
        .onChange(of: snapshot) { _, new in reveal.note(snapshot: new) }
        .accessibilityLabel(accessibilitySummary)
    }

    /// The plan, spoken: what a screen reader gets instead of the drawing.
    private var accessibilitySummary: String {
        let walls = snapshot.walls.filter { $0.kind == .wall }.count
        let boxes = snapshot.boxes.count
        if walls == 0 && boxes == 0 { return "Floor plan — listening for the room" }
        return "Floor plan — \(walls) wall\(walls == 1 ? "" : "s"), "
            + "\(boxes) piece\(boxes == 1 ? "" : "s") of furniture"
    }

    // MARK: Drawing

    private func draw(_ context: inout GraphicsContext, size: CGSize, now: Date) {
        let instant = !animated || reduceMotion

        // 1. Grid heading, smoothed shortest-arc mod 90°.
        let targetGrid = FloorPlanMath.gridHeading(walls: snapshot.walls)
        let grid = smoothing.stepGrid(target: targetGrid, now: now, instant: instant)

        // 2. Content bounds in the grid frame.
        func toGrid(_ p: SIMD2<Float>) -> SIMD2<Float> { FloorPlanMath.rotate(p, by: -grid) }
        var boundsMin = SIMD2<Float>(.greatestFiniteMagnitude, .greatestFiniteMagnitude)
        var boundsMax = SIMD2<Float>(-.greatestFiniteMagnitude, -.greatestFiniteMagnitude)
        var any = false
        func grow(_ p: SIMD2<Float>) {
            boundsMin = simd_min(boundsMin, p); boundsMax = simd_max(boundsMax, p); any = true
        }
        for w in snapshot.walls { grow(toGrid(w.start)); grow(toGrid(w.end)) }
        for b in snapshot.boxes {
            let r = simd_length(b.halfExtents)
            let c = toGrid(b.center)
            grow(c - SIMD2(r, r)); grow(c + SIMD2(r, r))
        }
        for p in snapshot.floorPolygon { grow(toGrid(p)) }
        if let camera { grow(toGrid(camera.position)) }
        guard any else { return }   // nothing to draw yet — no pose, no room

        // 3. Fit, smoothed.
        let fitTarget = FloorPlanMath.fit(boundsMin: boundsMin, boundsMax: boundsMax,
                                          into: size, padding: padding)
        let fit = smoothing.stepFit(target: fitTarget, now: now, instant: instant)
        smoothing.commit(now: now)
        func at(_ p: SIMD2<Float>) -> CGPoint { fit.apply(toGrid(p), in: size) }

        // 4. Floor wash — the room's ground, barely there.
        if snapshot.floorPolygon.count >= 3 {
            let alpha = reveal.progress(.floor, now: now, duration: 1.2, instant: instant)
            var path = Path()
            path.addLines(snapshot.floorPolygon.map(at))
            path.closeSubpath()
            context.fill(path, with: .color(Color.rsGold.opacity(0.055 * alpha)))
            context.stroke(path, with: .color(Color.rsGold.opacity(0.22 * alpha)),
                           style: StrokeStyle(lineWidth: 0.8))
        }

        // 5. Walls stroke in from their middles.
        for wall in snapshot.walls where wall.kind == .wall {
            let p = easeOut(reveal.progress(.entity(wall.id), now: now,
                                            duration: 0.9, instant: instant))
            guard p > 0.01 else { continue }
            let s = at(wall.start), e = at(wall.end)
            let mid = CGPoint(x: (s.x + e.x) / 2, y: (s.y + e.y) / 2)
            var path = Path()
            path.move(to: lerp(mid, s, p))
            path.addLine(to: lerp(mid, e, p))
            context.stroke(path, with: .color(Color.rsGoldLight.opacity(0.85)),
                           style: StrokeStyle(lineWidth: 1.6, lineCap: .round))
            if p > 0.97 {
                dot(&context, at: s, radius: 1.8, color: Color.rsGold.opacity(0.55))
                dot(&context, at: e, radius: 1.8, color: Color.rsGold.opacity(0.55))
            }
        }

        // 6. Doors / windows / openings — cuts in the wall line.
        for cut in snapshot.walls where cut.kind != .wall {
            let alpha = reveal.progress(.entity(cut.id), now: now,
                                        duration: 0.6, instant: instant)
            guard alpha > 0.01 else { continue }
            let s = at(cut.start), e = at(cut.end)
            var gap = Path()
            gap.move(to: s); gap.addLine(to: e)
            context.stroke(gap, with: .color(backdrop.opacity(alpha)),
                           style: StrokeStyle(lineWidth: 4, lineCap: .butt))
            switch cut.kind {
            case .door:
                // Jamb dots at both ends of the gap.
                dot(&context, at: s, radius: 1.6, color: Color.rsGoldLight.opacity(0.8 * alpha))
                dot(&context, at: e, radius: 1.6, color: Color.rsGoldLight.opacity(0.8 * alpha))
            case .window:
                // The glass line, thin, centered in the gap.
                var glass = Path()
                glass.move(to: s); glass.addLine(to: e)
                context.stroke(glass, with: .color(Color.rsGoldLight.opacity(0.45 * alpha)),
                               style: StrokeStyle(lineWidth: 0.9))
            case .opening, .wall:
                break   // an opening is just the gap
            }
        }

        // 7. Furniture boxes settle in, labeled where confidence allows.
        for box in snapshot.boxes {
            let p = easeOut(reveal.progress(.entity(box.id), now: now,
                                            duration: 0.5, instant: instant))
            guard p > 0.01 else { continue }
            let center = at(box.center)
            let axisG = FloorPlanMath.rotate(box.xAxis, by: -grid)
            let angle = CGFloat(atan2(axisG.y, axisG.x))
            let w = max(CGFloat(box.halfExtents.x * 2) * fit.scale, 4)
            let h = max(CGFloat(box.halfExtents.y * 2) * fit.scale, 4)
            let settle = 0.85 + 0.15 * p

            var boxCtx = context
            boxCtx.translateBy(x: center.x, y: center.y)
            boxCtx.rotate(by: .radians(Double(angle)))
            boxCtx.scaleBy(x: settle, y: settle)
            let rect = CGRect(x: -w / 2, y: -h / 2, width: w, height: h)
            let shape = Path(roundedRect: rect, cornerRadius: min(3, min(w, h) / 4))
            boxCtx.fill(shape, with: .color(Color.rsGold.opacity(0.07 * p)))
            boxCtx.stroke(shape, with: .color(Color.rsGoldLight.opacity(0.8 * p)),
                          style: StrokeStyle(lineWidth: 1.2))

            // Upright label (machine data, cream mono), only where it fits
            // inside the rotated footprint's screen box.
            if let label = FloorPlanVoice.boxLabel(categoryToken: box.categoryToken,
                                                   confidence: box.confidence) {
                let text = Text(label)
                    .font(RSFont.resolved(role: .mono, size: 8.5, weight: .semibold,
                                          relativeTo: .caption2, maxSize: 11,
                                          typeSize: typeSize))
                    .tracking(0.8)
                    .foregroundStyle(Color.rsOnDark.opacity(0.78 * p))
                let resolved = context.resolve(text)
                let textSize = resolved.measure(in: CGSize(width: 200, height: 40))
                let boundW = abs(w * cos(angle)) + abs(h * sin(angle))
                let boundH = abs(w * sin(angle)) + abs(h * cos(angle))
                if textSize.width <= boundW - 6, textSize.height <= boundH - 2 {
                    context.draw(resolved, at: center)
                }
            }
        }

        // 8. The camera — where the scan's light is being cast now.
        if let camera {
            let cam = at(camera.position)
            let fwdG = FloorPlanMath.rotate(camera.forward, by: -grid)
            let angle = Double(atan2(fwdG.y, fwdG.x))
            let radius = min(max(1.7 * fit.scale, 30), 64)
            let halfCone = 24.0 * .pi / 180

            var cone = Path()
            cone.move(to: cam)
            cone.addArc(center: cam, radius: radius,
                        startAngle: .radians(angle - halfCone),
                        endAngle: .radians(angle + halfCone),
                        clockwise: false)
            cone.closeSubpath()
            context.fill(cone, with: .radialGradient(
                Gradient(colors: [Color.rsGold.opacity(0.30), Color.rsGold.opacity(0)]),
                center: cam, startRadius: 2, endRadius: radius))

            dot(&context, at: cam, radius: 9, color: Color.rsGold.opacity(0.20))
            dot(&context, at: cam, radius: 4.5, color: Color.rsGold.opacity(0.95))
            dot(&context, at: cam, radius: 1.8, color: Color.rsOnDark.opacity(0.9))
        }
    }

    private func dot(_ context: inout GraphicsContext, at p: CGPoint,
                     radius: CGFloat, color: Color) {
        context.fill(
            Path(ellipseIn: CGRect(x: p.x - radius, y: p.y - radius,
                                   width: radius * 2, height: radius * 2)),
            with: .color(color))
    }

    private func lerp(_ a: CGPoint, _ b: CGPoint, _ t: Double) -> CGPoint {
        CGPoint(x: a.x + (b.x - a.x) * t, y: a.y + (b.y - a.y) * t)
    }

    private func easeOut(_ t: Double) -> Double {
        1 - pow(1 - t, 3)
    }
}

// MARK: - Entrance + smoothing state

/// Tracks when each entity first appeared so its entrance can animate. A
/// reference type held in @State on purpose: mutated during draw without
/// invalidating the view (the TimelineView is the clock).
private final class RevealClock {
    enum Key: Hashable {
        case entity(UUID)
        case floor
    }
    private var firstSeen: [Key: Date] = [:]

    func note(snapshot: FloorPlanSnapshot, at now: Date = Date()) {
        for w in snapshot.walls where firstSeen[.entity(w.id)] == nil {
            firstSeen[.entity(w.id)] = now
        }
        for b in snapshot.boxes where firstSeen[.entity(b.id)] == nil {
            firstSeen[.entity(b.id)] = now
        }
        if !snapshot.floorPolygon.isEmpty, firstSeen[.floor] == nil {
            firstSeen[.floor] = now
        }
    }

    func progress(_ key: Key, now: Date, duration: TimeInterval, instant: Bool) -> Double {
        if instant { return 1 }
        guard let t = firstSeen[key] else { return 1 }
        return min(max(now.timeIntervalSince(t) / duration, 0), 1)
    }
}

/// Low-pass smoothing for the grid heading and the fit, so refinements and
/// new walls glide instead of snapping. Reference type in @State for the same
/// reason as RevealClock.
private final class PlanSmoothing {
    private var grid: Float?
    private var fit: FloorPlanMath.Fit?
    private var lastAt: Date?

    /// ~0.5 s settle: k = 1 − e^(−6·dt).
    private func gain(now: Date) -> Float {
        let dt = Float(min(max(now.timeIntervalSince(lastAt ?? now), 0), 0.1))
        return 1 - exp(-6 * dt)
    }

    func stepGrid(target: Float?, now: Date, instant: Bool) -> Float {
        guard let target else { return grid ?? 0 }
        guard let current = grid, !instant else { grid = target; return target }
        let next = current + FloorPlanMath.gridArc(from: current, to: target) * gain(now: now)
        grid = next
        return next
    }

    func stepFit(target: FloorPlanMath.Fit, now: Date, instant: Bool) -> FloorPlanMath.Fit {
        guard let current = fit, !instant else { fit = target; return target }
        let k = CGFloat(gain(now: now))
        let next = FloorPlanMath.Fit(
            scale: current.scale + (target.scale - current.scale) * k,
            center: current.center + (target.center - current.center) * Float(k))
        fit = next
        return next
    }

    /// Advance the clock once per frame, after both steps used the same dt.
    func commit(now: Date) { lastAt = now }
}

// MARK: - Live wrapper

/// The live half: observes the feed (only this subtree re-renders at camera
/// rate) and applies the paused/dimmed envelope the placeholder had.
struct LiveFloorPlan: View {
    @ObservedObject var feed: FloorPlanFeed
    var paused: Bool
    var dimmed: Bool

    var body: some View {
        FloorPlanCanvas(snapshot: feed.snapshot, camera: feed.camera, paused: paused)
            .opacity(dimmed ? 0.25 : (paused ? 0.6 : 0.9))
            .animation(.easeInOut(duration: 0.4), value: dimmed)
            .animation(.easeInOut(duration: 0.4), value: paused)
    }
}

// MARK: - The spoken line

/// Selects the guest's one line from the competing voices (guidance, moments,
/// the "enough" confirmation, the default coaching) via FloorPlanVoice's
/// priority table, ticking twice a second so held lines decay on time. Also
/// the moment haptic's home: the soft surface-covered tap fires as a new
/// piece is announced.
struct LiveGuestLineView: View {
    @ObservedObject var feed: FloorPlanFeed
    var defaultLine: String

    var body: some View {
        TimelineView(.periodic(from: .now, by: 0.5)) { timeline in
            GuestLine(line(now: timeline.date), size: 17, onDark: true,
                      alignment: .center, maxSize: 22)
                .contentTransition(.opacity)
        }
        .animation(.easeInOut(duration: 0.3), value: line(now: Date()))
        .onChange(of: feed.moment) { _, new in
            if new != nil { RSHaptics.fire(.surfaceCovered) }
        }
    }

    private func line(now: Date) -> String {
        let stable: Bool
        if let census = feed.census, let changedAt = feed.censusChangedAt {
            stable = FloorPlanVoice.censusStable(
                walls: census.walls, floors: census.floors,
                sinceChange: now.timeIntervalSince(changedAt))
        } else {
            stable = false
        }
        return FloorPlanVoice.liveGuestLine(
            guidance: feed.guidance?.line,
            guidanceAge: feed.guidance.map { now.timeIntervalSince($0.at) } ?? .infinity,
            moment: feed.moment?.line,
            momentAge: feed.moment.map { now.timeIntervalSince($0.at) } ?? .infinity,
            censusIsStable: stable,
            defaultLine: defaultLine)
    }
}

// MARK: - Previews

#Preview("Mid-scan") {
    ZStack {
        Color.rsCaptureBase.ignoresSafeArea()
        FloorPlanCanvas(snapshot: .previewRoom, camera: .previewCamera)
            .padding(30)
    }
}

#Preview("Review card") {
    ZStack {
        Color.rsCaptureRaised.ignoresSafeArea()
        FloorPlanCanvas(snapshot: .previewRoom, animated: false,
                        backdrop: .rsCaptureRaised)
            .frame(height: 230)
            .padding(20)
    }
}

extension FloorPlanSnapshot {
    /// A hand-built room for previews and the screenshot harness — synthetic,
    /// clearly not a real capture.
    static var previewRoom: FloorPlanSnapshot {
        let a = SIMD2<Float>(-2.1, -1.6), b = SIMD2<Float>(2.1, -1.6)
        let c = SIMD2<Float>(2.1, 1.6), d = SIMD2<Float>(-2.1, 1.6)
        func wall(_ s: SIMD2<Float>, _ e: SIMD2<Float>, _ kind: FloorPlanWall.Kind = .wall) -> FloorPlanWall {
            FloorPlanWall(id: UUID(), kind: kind, start: s, end: e)
        }
        return FloorPlanSnapshot(
            walls: [
                wall(a, b), wall(b, c), wall(c, d), wall(d, a),
                wall(SIMD2(-0.55, -1.6), SIMD2(0.35, -1.6), .door),
                wall(SIMD2(2.1, -0.9), SIMD2(2.1, 0.1), .window),
            ],
            boxes: [
                FloorPlanBox(id: UUID(), center: SIMD2(-1.05, 0.55),
                             xAxis: SIMD2(1, 0), halfExtents: SIMD2(0.95, 0.7),
                             categoryToken: "bed", confidence: .high),
                FloorPlanBox(id: UUID(), center: SIMD2(1.45, 1.0),
                             xAxis: FloorPlanMath.rotate(SIMD2(1, 0), by: 0.71),
                             halfExtents: SIMD2(0.28, 0.25),
                             categoryToken: "chair", confidence: .medium),
                FloorPlanBox(id: UUID(), center: SIMD2(1.5, -1.1),
                             xAxis: SIMD2(0, 1), halfExtents: SIMD2(0.6, 0.25),
                             categoryToken: "storage", confidence: .low),
            ],
            floorPolygon: [a, b, c, d])
    }
}

extension FloorPlanCamera {
    static var previewCamera: FloorPlanCamera {
        FloorPlanCamera(position: SIMD2(0.3, 0.2),
                        forward: simd_normalize(SIMD2(-0.7, -0.5)))
    }
}
