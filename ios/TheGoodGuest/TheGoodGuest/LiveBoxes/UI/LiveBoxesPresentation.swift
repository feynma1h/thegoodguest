/// What the Scan screen's camera layer draws, as pure functions of the session's
/// tracks and the person's choices — DEBUG-only (decision 0295). The house
/// pattern: what is drawn is a table pinned by LiveBoxesPresentationTests, so
/// the screen is reviewable without reading SwiftUI.
///
/// EVERY OBJECT FOUND WEARS A DOT; A TAP BOXES IT. A track's fit moves every
/// pass, so no fit is drawn for its own sake. The dots are `DotRules.dotted`
/// minus the boxed; a boxed object is drawn as a box, all boxes alike. The one
/// just boxed is `current`: it keeps easing toward the detector's fit, so
/// walking round it improves it. The others are settled and never change.
///
/// ONE OBJECT AT A TIME. While a box is being worked on, no other object wears
/// a dot, so a second tap cannot catch another object.
///
/// NO NAMES. A detection's label can be wrong, so nothing is named.
///
/// Read by: LiveBoxesCamera, LiveBoxesARHost, LiveBoxesPresentationTests.

#if DEBUG

import Foundation
import simd

/// What the camera view draws, as values: the AR host's whole input.
nonisolated struct LiveBoxesScene: Equatable {
    struct Dot: Equatable {
        let id: UUID
        /// Where the dot sits on the object, world coordinates.
        let anchor: SIMD3<Float>
        /// The object already has its box, and wears no mark.
        var boxed = false
        /// How far the object reaches from its centre, metres: for hiding what
        /// stands behind a wall.
        var radius: Float = 0.3
        /// Points on the object (its centre, then its box's corners), world
        /// coordinates, each tested for a surface in front of it.
        var probes: [SIMD3<Float>] = []
    }

    struct Box: Equatable {
        let id: UUID
        let box: GravityBox
        /// The one being worked on: it still follows the detector's fit.
        let current: Bool
    }

    var dots: [Dot] = []
    var boxes: [Box] = []
}

nonisolated enum LiveBoxesPresentation {

    /// What the camera draws: a dot for every found object, and the boxes made.
    /// A boxed object that fusion merged away has no box left to show.
    ///
    /// `locked`: one object at a time. While a box is being worked on, no other
    /// object wears a dot.
    static func scene(_ tracks: [TrackSummary], boxed: Set<UUID>, current: UUID?,
                      locked: Bool = false, tops: [HorizontalSurface] = []) -> LiveBoxesScene {
        let boxedTracks = tracks.filter { boxed.contains($0.id) }
        let found = locked ? [] : DotRules.dotted(tracks, boxed: boxed, tops: tops)
        func dot(_ t: TrackSummary, boxed: Bool) -> LiveBoxesScene.Dot {
            let box = DotRules.box(of: t, tops: tops)
            return .init(id: t.id, anchor: box.center, boxed: boxed, radius: simd_length(box.size) / 2,
                         probes: [box.center] + box.corners)
        }
        return LiveBoxesScene(
            dots: found.map { dot($0, boxed: false) } + boxedTracks.map { dot($0, boxed: true) },
            boxes: boxedTracks.map { .init(id: $0.id, box: DotRules.box(of: $0, tops: tops), current: $0.id == current) })
    }

    // MARK: Words

    static let walkAroundHint = "Walk around it to finish the box"

    /// The box being worked on is one more look from right: a big object seen
    /// across a narrow arc, or glass the outlines have not pinned.
    static func needsWalkAround(_ track: TrackSummary?) -> Bool {
        track.map(DotRules.needsMoreViews) ?? false
    }

    static func countLabel(_ count: Int) -> String {
        count == 1 ? "1 box" : "\(count) boxes"
    }

    enum Toast: Equatable {
        case added(UUID)
        case removed(UUID)

        var label: String {
            switch self {
            case .added: "Box added  ·  Undo"
            case .removed: "Box removed  ·  Undo"
            }
        }
    }
}

#endif
