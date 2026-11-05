/// The boxes the person made and kept on the Scan screen, as the capture
/// bundle carries them (decisions 0320, 0321).
///
/// These are the ONLY object source downstream: the cloud draws a furniture
/// model for every box here and nothing for an object that was not boxed. The
/// set is the FINAL one, read once when the capture stops; a box the person
/// removed, or that fusion merged away, is not in it. No pixels, no masks, no
/// detector internals — a centre, a yaw, a size, a name and a time.
///
/// This file is compiled into every build on purpose. It knows nothing of live
/// boxes: the Scan screen's camera layer (a Debug-only feature) hands
/// `CaptureManager` a list of `KeptBox`, and a build without that feature
/// hands over none, so its bundles carry no boxes.
///
/// Read by: CaptureManager, BundleAssembler, PersonBoxWireTests.

import Foundation
import simd

/// One box the person kept, in the world frame of the capture's own ARSession.
struct KeptBox: Equatable, Sendable {
    let id: UUID
    /// The detector's own class name for the object ("chair", "dining table").
    /// Advisory: a detection's name can be wrong.
    let detectorLabel: String
    /// Centre, world coordinates, metres.
    let center: SIMD3<Float>
    /// Rotation about world +Y, radians.
    let yaw: Float
    /// Extents along the box's own X (along the yaw direction), Y (up) and Z, metres.
    let size: SIMD3<Float>
    /// When the person boxed the object, on the device-monotonic clock of
    /// `CaptureManager.startedAtDeviceUs`, in microseconds.
    let madeAtDeviceUs: Int64
}

enum PersonBoxWire {

    /// Smallest and largest side the cloud will model, metres. A box outside
    /// this is a fit gone wrong, not an object.
    static let sideRange: ClosedRange<Float> = 0.05...6
    /// The most boxes one bundle carries. The cloud answers each box with a
    /// model, so the count is also the work a scan can ask for.
    static let maxBoxes = 40

    /// The wire form of the boxes kept, in the order they were made. A box with
    /// a number that is not finite, or a side outside `sideRange`, is left out
    /// rather than repaired; a repeated id keeps its first box; past `maxBoxes`
    /// the earliest are kept. Left out, never rejected: a bundle that fails
    /// loses the whole scan.
    ///
    /// Times are written as microseconds since capture start, like every other
    /// time in the bundle (decision 0298).
    static func messages(_ kept: [KeptBox], startedAtDeviceUs: Int64) -> [RSPersonBox] {
        var seen = Set<UUID>()
        var out: [RSPersonBox] = []
        for box in kept.sorted(by: { $0.madeAtDeviceUs < $1.madeAtDeviceUs }) where isUsable(box) {
            guard out.count < maxBoxes, seen.insert(box.id).inserted else { continue }
            var m = RSPersonBox()
            m.boxID = box.id.uuidString.lowercased()
            m.detectorLabel = box.detectorLabel
            m.centerX = box.center.x
            m.centerY = box.center.y
            m.centerZ = box.center.z
            m.yawRad = box.yaw
            m.sizeX = box.size.x
            m.sizeY = box.size.y
            m.sizeZ = box.size.z
            m.createdAtDeviceUs = box.madeAtDeviceUs - startedAtDeviceUs
            out.append(m)
        }
        return out
    }

    private static func isUsable(_ box: KeptBox) -> Bool {
        let numbers = [box.center.x, box.center.y, box.center.z, box.yaw, box.size.x, box.size.y, box.size.z]
        return numbers.allSatisfy(\.isFinite) && [box.size.x, box.size.y, box.size.z].allSatisfy(sideRange.contains)
    }
}
