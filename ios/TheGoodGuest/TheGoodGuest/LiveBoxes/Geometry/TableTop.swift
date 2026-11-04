/// A table's box reaches to the whole of its top — DEBUG-only (decision 0295).
///
/// A table's fit often covers one end of it: the points that vote for it are the
/// ones the camera saw. ARKit measures the top as a plane, and where that plane
/// lies at the fit's top height, holds the fit's centre, is no larger than a
/// table and runs the way the fit does, the fit grows to cover the plane's
/// footprint — along its own axes, so the turn is the fit's, and never smaller.
/// A plane that runs another way is partial or tilted, and is left alone.
///
/// Read by: LiveBoxesPresentation, LiveBoxesDotTests.

#if DEBUG

import simd

nonisolated enum TableTop {
    static let planeTurnTolerance: Float = 15 * .pi / 180

    static func extended(_ fit: GravityBox, tops: [HorizontalSurface]) -> GravityBox {
        let x = fit.planXAxis, z = fit.planZAxis
        let best = tops.compactMap { s -> (HorizontalSurface, PlanRectangle)? in
            guard let e = s.extent, abs(s.height - fit.maxY) <= 0.08,
                  e.contains(SIMD2(fit.center.x, fit.center.z), margin: 0.15),
                  max(e.halfExtents.x, e.halfExtents.y) * 2 <= 2.4,
                  e.halfExtents.x * e.halfExtents.y * 4 <= 2.5 else { return nil }
            // How far the plane's axis is from one of the fit's, a quarter turn at most.
            let turn = abs(atan2(e.axis.x * x.y - e.axis.y * x.x, simd_dot(e.axis, x)))
            let off = min(turn.truncatingRemainder(dividingBy: .pi / 2), .pi / 2 - turn.truncatingRemainder(dividingBy: .pi / 2))
            guard off <= planeTurnTolerance else { return nil }
            return (s, e)
        }.max { $0.1.halfExtents.x * $0.1.halfExtents.y < $1.1.halfExtents.x * $1.1.halfExtents.y }
        guard let (surface, e) = best, surface.height > fit.minY + 0.2 else { return fit }
        let across = SIMD2(-e.axis.y, e.axis.x)
        let corners = [(-1, -1), (1, -1), (1, 1), (-1, 1)].map { sx, sz in
            e.center + e.axis * (Float(sx) * e.halfExtents.x) + across * (Float(sz) * e.halfExtents.y)
        }
        let here = SIMD2(fit.center.x, fit.center.z)
        let alongX = corners.map { simd_dot($0 - here, x) } + [-fit.size.x / 2, fit.size.x / 2]
        let alongZ = corners.map { simd_dot($0 - here, z) } + [-fit.size.z / 2, fit.size.z / 2]
        let (loX, hiX) = (alongX.min()!, alongX.max()!), (loZ, hiZ) = (alongZ.min()!, alongZ.max()!)
        let middle = here + x * ((loX + hiX) / 2) + z * ((loZ + hiZ) / 2)
        let height = max(surface.height, fit.maxY) - fit.minY
        return GravityBox(center: SIMD3(middle.x, fit.minY + height / 2, middle.y),
                          size: SIMD3(hiX - loX, height, hiZ - loZ), yaw: fit.yaw)
    }
}

#endif
