/// Which objects get a dot, which are one object, and when a box is a jump —
/// DEBUG-only (decision 0295). Pure rules on the tracks the pipeline reports,
/// pinned by LiveBoxesDotTests; the screen only draws what they leave.
///
/// A DOT IS A CLAIM, SO IT HAS TO BE EARNED. A track seen twice, or half the
/// time, is as likely a ghost as an object (`isWorthADot`). One object has
/// one dot, whatever it was called in turn (`isTheSameObject`). A rug or mat
/// boxed on a table's silhouette is the table's shadow (`shadowsTable`), and
/// an object still guessing at its shape is asked to be walked round
/// (`needsMoreViews`). Glass is exempt from the sighting rule: its sightings
/// are outlines, not masks.
///
/// Read by: LiveBoxesPresentation, LiveBoxesDotTests.

#if DEBUG

import Foundation
import simd

nonisolated enum DotRules {

    /// The box a track is drawn with: the one the person finished, else the
    /// fit; a table's reaching to the whole of its top where ARKit has measured one.
    static func box(of t: TrackSummary, tops: [HorizontalSurface] = []) -> GravityBox {
        let fit = t.locked?.box ?? t.box
        return tableLabels.contains(t.label) && !t.seenThrough ? TableTop.extended(fit, tops: tops) : fit
    }

    /// The tracks that wear a dot: found, earned, not boxed already, not a
    /// table's shadow and not a second track of an object that has a dot.
    static func dotted(_ tracks: [TrackSummary], boxed: Set<UUID>, tops: [HorizontalSurface] = []) -> [TrackSummary] {
        // A glass table is also named as a rug on its own silhouette: that dot would box the floor under it.
        let tables = tracks.filter { tableLabels.contains($0.label) && $0.confirmed }.map { box(of: $0, tops: tops) }
        return tracks.filter { t in
            t.confirmed && !boxed.contains(t.id) && isWorthADot(t)
                && !shadowsTable(label: t.label, box: t.locked?.box ?? t.box, tables: tables)
                && !tracks.contains { other in isTheSameObject(other, as: t, boxed: boxed) }
        }
    }

    static let floorCoverings: Set<String> = ["RUG", "MAT"]
    static let tableLabels = DetectorPipeline.ownTopLabels

    /// A box this big, seen across less than this many degrees, is one more look from right.
    static let bigSide: Float = 1.0
    static let enoughArc = 60

    static func needsMoreViews(_ t: TrackSummary) -> Bool {
        if t.boxUnsure { return true }
        let box = t.locked?.box ?? t.box
        return max(box.size.x, box.size.z) >= bigSide && t.arcDegrees < enoughArc
    }

    /// A dot is only offered for a track that has been seen a few times and
    /// mostly when looked for: one glimpsed twice, or half the time, is as likely
    /// a ghost as an object. Glass is exempt; its sightings are outlines.
    static let minimumHits = 5
    static let minimumHitShare: Float = 0.6

    static func isWorthADot(_ t: TrackSummary) -> Bool {
        if t.seenThrough { return true }
        let looked = t.hits + t.misses
        return t.hits >= minimumHits && looked > 0 && Float(t.hits) / Float(looked) >= minimumHitShare
    }

    /// Names one piece of furniture can be given by turns: the detector calls a
    /// cupboard storage, furniture or cabinet, and a cat tree a nightstand. A
    /// chair tucked under a table is not the table, so the groups do not mix.
    static let furnitureGroups: [Set<String>] = [
        ["STORAGE", "FURNITURE", "CABINET", "NIGHTSTAND", "DRAWERS", "SHELF", "CAT TREE"],
        ["TABLE", "COFFEE TABLE", "SIDE TABLE", "DESK"],
        ["SOFA", "CHAIR", "BED", "BENCH", "STOOL"],
    ]
    /// ... and of two such, the one with this much more evidence takes the dot; closer than that, both keep theirs.
    static let clearWinnerFactor: Float = 1.25

    static func sameFurniture(_ a: String, _ b: String) -> Bool {
        furnitureGroups.contains { $0.contains(a) && $0.contains(b) }
    }

    /// How much a track has to show for itself: sightings, weighted by how
    /// often it was seen when looked for.
    static func evidence(_ t: TrackSummary) -> Float {
        let looked = t.hits + t.misses
        return looked > 0 ? Float(t.hits) * Float(t.hits) / Float(looked) : 0
    }

    /// Whether `a` is a second track of the object `b` already stands for: the
    /// same kind of thing, its box on b's or nearly on top of it, and b the one
    /// to keep (boxed, or seen more often, or the lower id when equal). Two
    /// names of one kind of furniture count as the same kind: then a boxed b, or
    /// one with clearly more evidence, takes the dot from a. One rule for every
    /// depth source: it reads sightings, not depth.
    static func isTheSameObject(_ b: TrackSummary, as a: TrackSummary, boxed: Set<UUID>) -> Bool {
        guard a.id != b.id, b.confirmed || boxed.contains(b.id) else { return false }
        let boxA = a.locked?.box ?? a.box, boxB = b.locked?.box ?? b.box
        if a.label != b.label {
            guard sameFurniture(a.label, b.label), overlapsAsSame(boxA, boxB) else { return false }
            if boxed.contains(a.id) != boxed.contains(b.id) { return boxed.contains(b.id) }
            return evidence(b) >= clearWinnerFactor * evidence(a)
        }
        guard overlapsAsSame(boxA, boxB) else { return false }
        let keepB = (boxed.contains(b.id) ? 2 : 1, b.hits, b.id.uuidString) > (boxed.contains(a.id) ? 2 : 1, a.hits, a.id.uuidString)
        return keepB
    }

    /// Two boxes that are one object: one mostly inside the other, or centres within 30 cm.
    static func overlapsAsSame(_ a: GravityBox, _ b: GravityBox) -> Bool {
        a.containment(b) >= 0.3 || simd_distance(a.center, b.center) < 0.3
    }

    /// Whether a floor covering's box is the shadow of a table: it sits mostly inside one.
    static func shadowsTable(label: String, box: GravityBox, tables: [GravityBox]) -> Bool {
        floorCoverings.contains(label) && tables.contains { box.containment($0) >= 0.5 }
    }

    /// A new fit is a jump when it sits somewhere else: well away from the
    /// box and sharing almost no volume with it. A box that is merely larger
    /// or a little off is not.
    static func isJump(from a: GravityBox, to b: GravityBox) -> Bool {
        simd_distance(a.center, b.center) > 0.4 && a.iou(b) < 0.05
    }
}

#endif
