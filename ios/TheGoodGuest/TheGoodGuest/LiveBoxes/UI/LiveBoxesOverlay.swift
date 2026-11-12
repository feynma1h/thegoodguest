/// What sits over the camera in the world, re-rendered on its own every frame:
/// the dots, and the cues that point to a box — DEBUG-only (decision 0295).
///
/// The AR host places these from `ARView.project` every frame and publishes
/// them here; only these layers observe `ProjectedOverlay`, so the rest of the
/// Scan screen is not redrawn sixty times a second. No object is named: a
/// detection's label can be wrong, and a wrong name over someone's furniture
/// is worse than none.
///
/// Read by: LiveBoxesCamera, LiveBoxesARHost.

#if DEBUG

import Combine
import SwiftUI
import UIKit

/// The one ink the overlay draws in: soft white.
enum BoxInk {
    static let white = Color(red: 0.96, green: 0.95, blue: 0.92)
}

/// A dot as the overlay draws it.
struct ProjectedDot: Identifiable, Equatable {
    let id: UUID
    let point: CGPoint
    /// The object already has its box, and wears no mark.
    var boxed = false
}

/// Where a box picked from the strip is, for the glow and the pulse.
enum BoxLocator: Equatable {
    case inView(CGPoint)
    /// Off screen: where a line from the middle of the screen toward the box leaves it.
    case edge(CGPoint)
}

/// What the camera view shows over the camera, placed every frame by the AR host.
@MainActor
final class ProjectedOverlay: ObservableObject {
    @Published var dots: [ProjectedDot] = []
    /// Where the box picked in the strip is.
    @Published var locator: BoxLocator?
    /// The picked box's edges on screen, as pairs of end points.
    @Published var pickedEdges: [CGPoint] = []
}

/// A still of an object, taken from the camera frame when it is boxed. In
/// memory only; it never enters the bundle.
@MainActor
final class BoxThumbs: ObservableObject {
    @Published private(set) var images: [UUID: UIImage] = [:]
    var source: ((UUID) -> UIImage?)?

    func capture(_ id: UUID) {
        guard images[id] == nil, let image = source?(id) else { return }
        images[id] = image
    }
}

/// The dots, over the camera. A tap on one boxes its object.
struct OverlayLayer: View {
    @ObservedObject var overlay: ProjectedOverlay
    let activate: (UUID) -> Void

    var body: some View {
        GeometryReader { _ in
            // A boxed object wears no mark: its box says so.
            ForEach(overlay.dots.filter { !$0.boxed }) { dot in
                DotMark()
                    .position(dot.point)
                    .onTapGesture { activate(dot.id) }
                    .accessibilityElement()
                    .accessibilityLabel("Box this object")
                    .accessibilityAddTraits(.isButton)
            }
        }
    }
}

/// An object's dot: small and pale, with a soft halo that says it can be tapped.
private struct DotMark: View {
    var body: some View {
        ZStack {
            Circle()
                .stroke(BoxInk.white.opacity(0.35), lineWidth: 1.5)
                .frame(width: 26, height: 26)
            Circle()
                .fill(Color.rsOnDusk.opacity(0.92))
                .overlay(Circle().stroke(Color.rsDusk.opacity(0.45), lineWidth: 1))
                .frame(width: 14, height: 14)
                .shadow(color: Color.rsDusk.opacity(0.4), radius: 2)
        }
        .frame(width: 60, height: 60)
        .contentShape(Circle())
    }
}

// MARK: - Cues over the camera

/// Points to the box picked in the strip. One out of view lights a line of light
/// along the screen's edge, brightest where a line toward the box leaves the
/// screen and fading away along the edge either side, the way Siri's glow hugs
/// the screen. One in view is lit by `PickedGlow`.
struct LocatorGlow: View {
    @ObservedObject var overlay: ProjectedOverlay

    var body: some View {
        // Redrawn every frame only while the glow is showing.
        TimelineView(.animation(paused: overlay.locator == nil)) { timeline in
            let t = timeline.date.timeIntervalSinceReferenceDate
            let pulse = 0.5 + 0.5 * sin(t * 2.6)
            ZStack {
                if case .edge(let point)? = overlay.locator {
                    ZStack {
                        // A deep bloom inward, a bright band, and a fine hot line right on the edge.
                        RoundedRectangle(cornerRadius: 56, style: .continuous)
                            .strokeBorder(BoxInk.white.opacity(0.6), lineWidth: 52)
                            .blur(radius: 20)
                        RoundedRectangle(cornerRadius: 56, style: .continuous)
                            .strokeBorder(BoxInk.white.opacity(0.95), lineWidth: 14)
                            .blur(radius: 7)
                        RoundedRectangle(cornerRadius: 56, style: .continuous)
                            .strokeBorder(Color.white, lineWidth: 4)
                            .blur(radius: 0.8)
                    }
                    // Drawn once as a picture; only the mask and the pulse change after that.
                    .drawingGroup()
                    .mask(GeometryReader { geo in
                        RadialGradient(stops: [.init(color: .white, location: 0),
                                               .init(color: .white.opacity(0.7), location: 0.35),
                                               .init(color: .white.opacity(0), location: 1)],
                                       center: .init(x: point.x / max(geo.size.width, 1),
                                                     y: point.y / max(geo.size.height, 1)),
                                       startRadius: 0, endRadius: 260)
                    })
                    .opacity(0.82 + 0.18 * pulse)
                    .transition(.opacity)
                }
            }
        }
        .ignoresSafeArea()
        .allowsHitTesting(false)
        .animation(.easeOut(duration: 0.25), value: overlay.locator != nil)
    }
}


/// Lights the box picked in the strip when it is in view: its edges glow, with a
/// light that travels round them. It only shows; it never changes what the box measures.
struct PickedGlow: View {
    @ObservedObject var overlay: ProjectedOverlay

    var body: some View {
        TimelineView(.animation(paused: overlay.pickedEdges.isEmpty)) { timeline in
            let t = timeline.date.timeIntervalSinceReferenceDate
            let points = overlay.pickedEdges
            GeometryReader { geo in
                if !points.isEmpty {
                    let path = Path { p in
                        for i in stride(from: 0, to: points.count - 1, by: 2) {
                            p.move(to: points[i])
                            p.addLine(to: points[i + 1])
                        }
                    }
                    let centre = points.reduce(CGPoint.zero) { CGPoint(x: $0.x + $1.x, y: $0.y + $1.y) }
                    let middle = UnitPoint(x: centre.x / CGFloat(points.count) / max(geo.size.width, 1),
                                           y: centre.y / CGFloat(points.count) / max(geo.size.height, 1))
                    let champagne = Color(red: 1, green: 0.9, blue: 0.72)
                    let light = AngularGradient(
                        colors: [Color.white.opacity(0.28), .white, champagne, Color.white.opacity(0.28), Color.white.opacity(0.28)],
                        center: middle, angle: .degrees(t * 70))
                    ZStack {
                        path.stroke(light, style: StrokeStyle(lineWidth: 9, lineCap: .round, lineJoin: .round))
                            .blur(radius: 5).opacity(0.75)
                        path.stroke(light, style: StrokeStyle(lineWidth: 1.8, lineCap: .round, lineJoin: .round))
                    }
                }
            }
        }
        .ignoresSafeArea()
        .allowsHitTesting(false)
    }
}


#endif
