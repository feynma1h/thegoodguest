/// The camera half of live boxes: the capture's ARSession camera feed with the
/// objects drawn in the world — DEBUG-only (decision 0295).
///
/// WHAT IT DRAWS (`LiveBoxesScene`):
///   • a DOT on every object found, placed over it in SwiftUI every frame from
///     `ARView.project` and eased toward the object (`OverlayLayer`);
///   • the boxes the person made, thin and solid, all alike. The CURRENT one
///     glides to each new fit — it closes most of the gap in a fraction of a
///     second, so it never pops — and breathes; a fit that lands somewhere
///     else entirely is ignored until it has held (`DotRules.isJump`), so a
///     box does not leap onto the object beside it. A SETTLED box is kept
///     exactly as it was.
/// A dot or a box with a wall or other furniture in front of it is not drawn
/// (`BoxHider`). The box picked in the strip is pointed to: its edges glow when
/// it is in view, and a light runs along the screen's edge toward it when not.
///
/// ONE ENTITY PER LAYER, HOWEVER MANY BOXES (`MeshLayer`).
///
/// The view takes the camera feed from the ARSession it is given and never
/// configures, runs or pauses it: that session is the capture's.
///
/// Read by: LiveBoxesCamera.

#if DEBUG

import ARKit
import Combine
import CoreImage
import RealityKit
import SwiftUI
import UIKit

struct LiveBoxesARHost: UIViewRepresentable {
    let session: ARSession
    let scene: LiveBoxesScene
    let overlay: ProjectedOverlay
    /// Stills of boxed objects.
    var thumbs: BoxThumbs?
    /// The box to point the person toward.
    var locate: UUID?
    /// A line for the session log when dots are hidden behind surfaces.
    var onNote: ((String) -> Void)?
    /// The latest pass's depth, from whichever source, to find what stands in front of an object.
    var sight: (() -> DepthSight?)?

    func makeCoordinator() -> Coordinator { Coordinator(overlay: overlay) }

    func makeUIView(context: Context) -> ARView {
        let view = ARView(frame: .zero, cameraMode: .ar, automaticallyConfigureSession: false)
        view.session = session
        view.renderOptions = [.disableMotionBlur, .disableDepthOfField, .disableCameraGrain,
                              .disableHDR, .disableGroundingShadows, .disableAREnvironmentLighting,
                              .disablePersonOcclusion, .disableFaceMesh]
        context.coordinator.install(in: view)
        return view
    }

    func updateUIView(_ view: ARView, context: Context) {
        context.coordinator.locate = locate
        context.coordinator.onNote = onNote
        context.coordinator.sight = sight
        thumbs?.source = { [weak coordinator = context.coordinator] id in coordinator?.thumbnail(of: id) }
        context.coordinator.update(scene)
    }

    static func dismantleUIView(_ view: ARView, coordinator: Coordinator) {
        coordinator.teardown()
    }

    @MainActor
    final class Coordinator: NSObject {
        /// How fast dots follow their objects, in seconds.
        private static let dotEasing: Double = 0.15
        /// A current box glides to each new fit: it closes most of the gap in about
        /// a third of a second, so it moves smoothly, never pops, and is never left behind.
        private static let followTime: Double = 0.12
        /// A fit that lands somewhere else entirely is not followed at once: it is
        /// ignored until it has held this long.
        private static let jumpHold: Double = 1.5
        /// A box taken back keeps its shape this long, for Undo; after that it starts afresh.
        private static let undoWindow: Double = 5

        private weak var view: ARView?
        private let root = AnchorEntity(world: matrix_identity_float4x4)
        private let overlay: ProjectedOverlay
        private var link: CADisplayLink?
        private var scene = LiveBoxesScene()
        var locate: UUID?
        var onNote: ((String) -> Void)?
        var sight: (() -> DepthSight?)?
        /// Dots and boxes with a surface in front of them.
        private var hider = BoxHider()
        private var lastPoints: [UUID: CGPoint] = [:]
        /// The current box as drawn, and where it is gliding to.
        private var slides: [UUID: Slide] = [:]
        /// The settled boxes, as they were when they settled.
        private var frozen: [UUID: GravityBox] = [:]
        private var absent: [UUID: Double] = [:]
        /// Which way the glow points, eased so it glides, as a screen direction.
        private var glowDirection: CGVector?
        private var settledLayer: MeshLayer?
        private var currentLayer: MeshLayer?
        /// Where each dot is drawn, easing toward where it belongs.
        private var anchors: [UUID: SIMD3<Float>] = [:]
        private var lastFrame: Double?

        private struct Slide {
            var shown: GravityBox
            var target: GravityBox
            var pending: Double?
        }

        init(overlay: ProjectedOverlay) { self.overlay = overlay }

        func install(in view: ARView) {
            self.view = view
            view.scene.addAnchor(root)
            settledLayer = layer(BoxInk.white, opacity: 0.8)
            currentLayer = layer(BoxInk.white)
            let link = CADisplayLink(target: self, selector: #selector(frame))
            link.preferredFrameRateRange = CAFrameRateRange(minimum: 30, maximum: 60, preferred: 60)
            link.add(to: .main, forMode: .common)
            self.link = link
        }

        func teardown() {
            link?.invalidate()
            link = nil
            overlay.dots = []
            overlay.locator = nil
            overlay.pickedEdges = []
        }

        func update(_ next: LiveBoxesScene) {
            scene = next
        }

        private func layer(_ colour: Color, opacity: Float = 1) -> MeshLayer? {
            var material = UnlitMaterial(color: UIColor(colour))
            if opacity < 1 { material.blending = .transparent(opacity: .init(floatLiteral: opacity)) }
            material.faceCulling = .none
            guard let layer = MeshLayer(material: material) else { return nil }
            root.addChild(layer.entity)
            return layer
        }

        // MARK: Each frame

        @objc private func frame() {
            guard let view else { return }
            let now = CACurrentMediaTime()
            let dt = lastFrame.map { min(now - $0, 0.1) } ?? 0
            lastFrame = now
            let bounds = view.bounds
            // `project` also maps points behind the camera; keep only those in front.
            let cameraFromWorld = view.session.currentFrame?.camera.transform.inverse
            func onScreen(_ p: SIMD3<Float>) -> CGPoint? {
                if let cameraFromWorld, (cameraFromWorld * SIMD4(p, 1)).z >= 0 { return nil }
                guard let point = view.project(p), bounds.insetBy(dx: -20, dy: -20).contains(point) else { return nil }
                return point
            }

            // Dots, eased toward their objects.
            let follow = Float(1 - exp(-dt / Self.dotEasing))
            var anchored: [UUID: SIMD3<Float>] = [:]
            var points: [UUID: CGPoint] = [:]
            for dot in scene.dots {
                let at = anchors[dot.id].map { $0 + (dot.anchor - $0) * follow } ?? dot.anchor
                anchored[dot.id] = at
                points[dot.id] = onScreen(at)
            }
            anchors = anchored
            lastPoints = points

            hide(now: now, camera: view.session.currentFrame.map {
                SIMD3($0.camera.transform.columns.3.x, $0.camera.transform.columns.3.y, $0.camera.transform.columns.3.z)
            })
            overlay.dots = scene.dots.compactMap { dot in
                guard !hider.hidden.contains(dot.id) else { return nil }
                return points[dot.id].map { ProjectedDot(id: dot.id, point: $0, boxed: dot.boxed) }
            }
            drawBoxes(now: now, dt: dt)
            publishLocator(points: points, view: view, dt: dt)
        }

        /// Which dots and boxes have something in front of them (`BoxHider`).
        private func hide(now: Double, camera: SIMD3<Float>?) {
            let subjects = scene.dots.map { BoxHider.Subject(id: $0.id, radius: $0.radius, probes: $0.probes) }
            for line in hider.update(subjects, sight: sight?(), camera: camera, now: now) { onNote?(line) }
        }

        /// The boxes the person made. The current one eases toward each new fit
        /// and breathes; a settled one is kept exactly as it was.
        private func drawBoxes(now: Double, dt: Double) {
            var settled: [GravityBox] = [], working: [GravityBox] = []
            for box in scene.boxes {
                absent[box.id] = nil
                if box.current {
                    var slide = slides[box.id] ?? Slide(shown: box.box, target: box.box, pending: nil)
                    if DotRules.isJump(from: slide.target, to: box.box) {
                        // Somewhere else entirely: wait to see whether it holds.
                        let since = slide.pending ?? now
                        slide.pending = since
                        if now - since > Self.jumpHold {
                            slide.target = box.box
                            slide.pending = nil
                        }
                    } else {
                        slide.target = box.box
                        slide.pending = nil
                    }
                    slide.shown = slide.shown.approaching(slide.target, fraction: Float(1 - exp(-dt / Self.followTime)))
                    slides[box.id] = slide
                    if !hider.hidden.contains(box.id) { working.append(slide.shown) }
                } else {
                    // Settled at the fit it was gliding to, wherever the glide had got to.
                    let kept = frozen[box.id] ?? slides[box.id]?.target ?? box.box
                    frozen[box.id] = kept
                    if hider.hidden.contains(box.id) { continue }
                    settled.append(kept)
                }
            }
            let present = Set(scene.boxes.map(\.id))
            for id in Set(slides.keys).union(frozen.keys) where !present.contains(id) {
                let since = absent[id] ?? now
                absent[id] = since
                if now - since > Self.undoWindow {
                    slides[id] = nil
                    frozen[id] = nil
                    absent[id] = nil
                }
            }
            // The box picked in the strip, while it is in view: its edges on screen, for the glow.
            var edges: [CGPoint] = []
            if let id = locate, lastPoints[id] != nil, let box = frozen[id] ?? slides[id]?.shown {
                edges = projectedEdges(of: box)
            }
            if overlay.pickedEdges != edges { overlay.pickedEdges = edges }
            settledLayer?.show(boxes: settled, thickness: 0.003)
            currentLayer?.show(boxes: working, thickness: 0.004)
            let breath = Float(0.85 + 0.15 * sin(now * 2.4))
            currentLayer?.entity.components.set(OpacityComponent(opacity: breath))
        }

        // MARK: Pointing to a box

        /// Where the box picked in the strip is: a pulse over it, or a glow from the screen edge nearest its direction.
        private func publishLocator(points: [UUID: CGPoint], view: ARView, dt: Double) {
            var next: BoxLocator?
            if let id = locate, let anchor = anchors[id] {
                if let point = points[id] {
                    next = .inView(point)
                    glowDirection = nil
                } else {
                    var d = direction(toward: anchor, in: view)
                    let length = hypot(d.dx, d.dy)
                    d = length < 1 ? CGVector(dx: 0, dy: 1) : CGVector(dx: d.dx / length, dy: d.dy / length)
                    // Ease the direction, not the point, so the glow glides round the edge.
                    let follow = CGFloat(1 - exp(-dt / 0.25))
                    let was = glowDirection ?? d
                    var eased = CGVector(dx: was.dx + (d.dx - was.dx) * follow, dy: was.dy + (d.dy - was.dy) * follow)
                    if hypot(eased.dx, eased.dy) < 0.05 { eased = d }
                    glowDirection = eased
                    next = .edge(Self.exit(eased, in: view.bounds))
                }
            } else {
                glowDirection = nil
            }
            if overlay.locator != next { overlay.locator = next }
        }

        /// Which way, on this screen, the world point lies from the middle of it.
        private func direction(toward world: SIMD3<Float>, in view: ARView) -> CGVector {
            guard let camera = view.session.currentFrame?.camera.transform else { return CGVector(dx: 0, dy: 1) }
            func xyz(_ c: SIMD4<Float>) -> SIMD3<Float> { SIMD3(c.x, c.y, c.z) }
            let centre = CGPoint(x: view.bounds.midX, y: view.bounds.midY)
            let local = camera.inverse * SIMD4(world, 1)
            // In front of the camera the projection is true, even off screen.
            if local.z < 0, let p = view.project(world) {
                return CGVector(dx: p.x - centre.x, dy: p.y - centre.y)
            }
            // Behind it, the camera's own right and up axes, as they point on this screen.
            let eye = xyz(camera.columns.3), forward = -xyz(camera.columns.2)
            func onScreen(_ axis: SIMD3<Float>) -> CGVector {
                guard let a = view.project(eye + forward), let b = view.project(eye + forward + axis * 0.3) else { return .zero }
                return CGVector(dx: b.x - a.x, dy: b.y - a.y)
            }
            let r = onScreen(xyz(camera.columns.0)), u = onScreen(xyz(camera.columns.1))
            return CGVector(dx: r.dx * CGFloat(local.x) + u.dx * CGFloat(local.y),
                            dy: r.dy * CGFloat(local.x) + u.dy * CGFloat(local.y))
        }

        /// Where a line from the middle of the screen along `d` leaves it.
        private static func exit(_ d: CGVector, in bounds: CGRect) -> CGPoint {
            let half = CGSize(width: bounds.width / 2, height: bounds.height / 2)
            let tx = d.dx == 0 ? CGFloat.infinity : half.width / abs(d.dx)
            let ty = d.dy == 0 ? CGFloat.infinity : half.height / abs(d.dy)
            let t = min(tx, ty)
            return CGPoint(x: bounds.midX + d.dx * t, y: bounds.midY + d.dy * t)
        }

        /// The box's twelve edges on screen, as pairs of end points; an edge with an end behind the camera is left out.
        private func projectedEdges(of box: GravityBox) -> [CGPoint] {
            guard let view, let camera = view.session.currentFrame?.camera.transform else { return [] }
            let cameraFromWorld = camera.inverse
            let h = box.size / 2
            var corners: [CGPoint?] = []
            for i in 0..<8 {
                let s = SIMD3<Float>(i & 4 == 0 ? -1 : 1, i & 2 == 0 ? -1 : 1, i & 1 == 0 ? -1 : 1)
                let w = box.transform * SIMD4(s * h, 1)
                let world = SIMD3(w.x, w.y, w.z)
                corners.append((cameraFromWorld * SIMD4(world, 1)).z >= 0 ? nil : view.project(world))
            }
            var out: [CGPoint] = []
            for i in 0..<8 {
                for bit in [1, 2, 4] where i & bit == 0 {
                    if let a = corners[i], let b = corners[i | bit] { out += [a, b] }
                }
            }
            return out
        }

        // MARK: Stills

        /// A small square still of the object, cut from the camera frame around where it is on screen.
        func thumbnail(of id: UUID) -> UIImage? {
            guard let view, let frame = view.session.currentFrame, let p = lastPoints[id] else { return nil }
            let size = view.bounds.size
            guard size.width > 0, size.height > 0 else { return nil }
            let toImage = frame.displayTransform(for: .portrait, viewportSize: size).inverted()
            let n = CGPoint(x: p.x / size.width, y: p.y / size.height).applying(toImage)
            let image = CIImage(cvPixelBuffer: frame.capturedImage)
            let w = image.extent.width, h = image.extent.height
            let side = h * 0.34
            var rect = CGRect(x: n.x * w - side / 2, y: (1 - n.y) * h - side / 2, width: side, height: side)
            rect.origin.x = min(max(rect.origin.x, 0), w - side)
            rect.origin.y = min(max(rect.origin.y, 0), h - side)
            let scale = 180 / side
            let still = image.cropped(to: rect)
                .transformed(by: CGAffineTransform(translationX: -rect.minX, y: -rect.minY))
                .transformed(by: CGAffineTransform(scaleX: scale, y: scale))
            guard let cg = Self.ciContext.createCGImage(still, from: CGRect(x: 0, y: 0, width: 180, height: 180)) else { return nil }
            return UIImage(cgImage: cg, scale: 1, orientation: .right)
        }
        private static let ciContext = CIContext()
    }
}

#endif
