/// RoomPlan's own boxes as the session log holds them, and the two comparisons
/// the detector's boxes are read against — DEBUG-only (decision 0295). OFF: see
/// `RoomPlanClasses`.
///
///   • DUPLICATE — a long-tail box that sits on a RoomPlan box of a category it
///     can be (a SHELF on RoomPlan's `storage`) is flagged, not hidden: whether
///     the two double up is one of the operator's verdicts.
///   • AGREEMENT — a detector box for one of RoomPlan's OWN categories, against
///     RoomPlan's box for the same object, is the one geometry check available
///     on real furniture without the operator's eyes. Errors are read over the
///     box's quarter-turn symmetry, exactly as the synthetic acceptance does.
///
/// Read by: LiveBoxesSession, SessionLog, LiveBoxesRuntimeTests.

#if DEBUG

import Foundation
import simd

/// Whether RoomPlan boxes its own categories (chairs, tables, sofas …) and the
/// detector leaves them to it. FALSE: live boxes boxes what the person taps, and
/// no RoomPlan box is used for it, so the detector lifts those categories itself
/// and nothing feeds the comparisons below. The handling is kept, not removed:
/// with this on, those names are `MissReason.leftToRoomPlan`, and the log
/// records each box's agreement with RoomPlan's and any it duplicates.
nonisolated enum RoomPlanClasses {
    static let boxedByRoomPlan = false
}

nonisolated struct RoomPlanBox: Sendable, Equatable, Identifiable {
    let id: UUID
    /// RoomPlan's category token (`String(describing:)`).
    let category: String
    let confidence: FloorPlanConfidence
    let box: GravityBox

    /// From a CapturedRoom object's transform (column 1 is +Y for RoomPlan's
    /// upright boxes, 0076 Q4) and dimensions. Nil when the box is not upright.
    init?(id: UUID, category: String, confidence: FloorPlanConfidence,
          transform t: simd_float4x4, dimensions: SIMD3<Float>) {
        let x = SIMD2(t.columns.0.x, t.columns.0.z)
        let length = simd_length(x)
        guard length > 0.5 else { return nil }
        let axis = x / length
        // A box's plan X axis is (cos ψ, −sin ψ).
        let yaw = atan2(-axis.y, axis.x)
        self.id = id
        self.category = category
        self.confidence = confidence
        box = GravityBox(center: SIMD3(t.columns.3.x, t.columns.3.y, t.columns.3.z),
                         size: dimensions, yaw: yaw)
    }
}

nonisolated struct BoxAgreement: Sendable, Equatable, Codable {
    let centreDistance: Float
    /// |fit − RoomPlan| per extent, in the orientation the yaws agree on.
    let extentErrors: [Float]
    let yawDegrees: Float
    let iou: Float
}

nonisolated enum RoomPlanMatch {

    /// The RoomPlan category a long-tail box duplicates, if it sits on a
    /// RoomPlan box of a category it can be.
    static func duplicatedCategory(_ box: GravityBox, overlap categories: Set<String>,
                                   among roomPlan: [RoomPlanBox]) -> String? {
        guard !categories.isEmpty else { return nil }
        return roomPlan
            .filter { categories.contains($0.category) }
            .map { ($0.category, max(box.iou($0.box), box.containment($0.box))) }
            .filter { $0.1 >= 0.5 }
            .max { $0.1 < $1.1 }?.0
    }

    /// The best-overlapping RoomPlan box of `category`, and how well `box`
    /// agrees with it. Nil when no RoomPlan box of that category overlaps.
    static func agreement(_ box: GravityBox, category: String,
                          among roomPlan: [RoomPlanBox]) -> (id: UUID, agreement: BoxAgreement)? {
        guard let match = roomPlan
            .filter({ $0.category == category && box.intersectionVolume($0.box) > 0 })
            .max(by: { box.iou($0.box) < box.iou($1.box) })
        else { return nil }
        return (match.id, compare(box, match.box))
    }

    /// Errors of `fit` against `reference`, over the quarter-turn symmetry.
    static func compare(_ fit: GravityBox, _ reference: GravityBox) -> BoxAgreement {
        var best: BoxAgreement?
        for k in 0..<4 {
            let turned = reference.yaw + Float(k) * .pi / 2
            let diff = abs(atan2(sin(fit.yaw - turned), cos(fit.yaw - turned))) * 180 / .pi
            let size = k % 2 == 0 ? reference.size : SIMD3(reference.size.z, reference.size.y, reference.size.x)
            let errors = simd_abs(fit.size - size)
            let candidate = BoxAgreement(centreDistance: simd_distance(fit.center, reference.center),
                                         extentErrors: [errors.x, errors.y, errors.z],
                                         yawDegrees: diff, iou: fit.iou(reference))
            if best == nil || candidate.yawDegrees < best!.yawDegrees { best = candidate }
        }
        return best!
    }
}

#endif
