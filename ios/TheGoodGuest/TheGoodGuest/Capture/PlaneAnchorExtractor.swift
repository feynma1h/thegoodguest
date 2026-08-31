/// ARPlaneAnchor → RSPlaneAnchor conversion (decision 0066: plane anchors
/// are the room shell's measured geometry source).
///
/// Mirrors PoseExtractor's structure: pure simd/primitive functions carry
/// the math (unit-testable without an AR session), thin ARKit-typed
/// wrappers pull values out of ARPlaneAnchor. All outputs are ARKit-native
/// frame; the client does NOT transform (capture_bundle.proto header).
///
/// Consumed by CaptureManager at capture stop — the session's FINAL anchor
/// set only (ARKit merges and refines anchors continuously mid-session).

import ARKit
import SwiftProtobuf
import simd

enum PlaneAnchorExtractor {

    // MARK: - Pure conversion (unit-tested)

    /// world_from_anchor pose from an anchor transform. Same extraction as
    /// PoseExtractor.pose (upper-left 3×3 → quaternion, column 3 →
    /// position), taking the raw matrix so tests can hand-construct it.
    static func pose(fromTransform t: simd_float4x4) -> RSPose {
        let q = simd_quaternion(t)
        return RSPose.with {
            $0.posX = t.columns.3.x
            $0.posY = t.columns.3.y
            $0.posZ = t.columns.3.z
            $0.quatX = q.vector.x
            $0.quatY = q.vector.y
            $0.quatZ = q.vector.z
            $0.quatW = q.vector.w  // real part; simd_quatf.vector is (ix,iy,iz,r)
        }
    }

    /// Anchor-space boundary polygon flattened to (x, z) pairs. The
    /// vertices lie in the anchor's X-Z plane (y ≈ 0 by ARKit's contract);
    /// y is dropped, not checked — the plane fit already absorbed it.
    static func flattenBoundary(_ vertices: [simd_float3]) -> [Float] {
        var out: [Float] = []
        out.reserveCapacity(vertices.count * 2)
        for v in vertices {
            out.append(v.x)
            out.append(v.z)
        }
        return out
    }

    /// ARPlaneAnchor.Alignment → proto enum. Future ARKit alignments (e.g.
    /// arbitrary slopes, should Apple add them) map to .unspecified rather
    /// than guessing a bucket.
    static func alignment(from a: ARPlaneAnchor.Alignment) -> RSPlaneAlignment {
        switch a {
        case .horizontal: return .horizontal
        case .vertical:   return .vertical
        @unknown default: return .unspecified
        }
    }

    /// ARPlaneAnchor.Classification → wire string. Known cases map to the
    /// proto's documented lowercase canon; .none (any status: device can't
    /// classify, or ARKit couldn't decide) maps to "" = unclassified —
    /// consumers never guess. An unknown future case ships its
    /// String(describing:) verbatim rather than being silently dropped.
    static func classificationString(from c: ARPlaneAnchor.Classification) -> String {
        switch c {
        case .wall:    return "wall"
        case .floor:   return "floor"
        case .ceiling: return "ceiling"
        case .table:   return "table"
        case .seat:    return "seat"
        case .window:  return "window"
        case .door:    return "door"
        case .none:    return ""
        @unknown default: return String(describing: c)
        }
    }

    /// Assemble an RSPlaneAnchor from primitives. Pure; tests exercise this
    /// directly with hand-built values.
    static func planeAnchor(
        transform:        simd_float4x4,
        center:           simd_float3,
        extentWidth:      Float,
        extentHeight:     Float,
        rotationOnYRad:   Float,
        alignment:        RSPlaneAlignment,
        classification:   String,
        boundaryVertices: [simd_float3]
    ) -> RSPlaneAnchor {
        return RSPlaneAnchor.with {
            $0.pose           = pose(fromTransform: transform)
            $0.centerX        = center.x
            $0.centerY        = center.y
            $0.centerZ        = center.z
            $0.extentWidth    = extentWidth
            $0.extentHeight   = extentHeight
            $0.rotationOnYRad = rotationOnYRad
            $0.alignment      = alignment
            $0.classification = classification
            $0.boundaryXz     = flattenBoundary(boundaryVertices)
        }
    }

    // MARK: - ARKit wrapper

    /// Convert one live ARPlaneAnchor. planeExtent is the iOS 16+ extent
    /// API (width/height/rotationOnYAxis about the anchor's +Y, applied at
    /// the plane center); the deprecated simd extent is not used.
    static func from(_ anchor: ARPlaneAnchor) -> RSPlaneAnchor {
        return planeAnchor(
            transform:        anchor.transform,
            center:           anchor.center,
            extentWidth:      anchor.planeExtent.width,
            extentHeight:     anchor.planeExtent.height,
            rotationOnYRad:   anchor.planeExtent.rotationOnYAxis,
            alignment:        alignment(from: anchor.alignment),
            classification:   classificationString(from: anchor.classification),
            boundaryVertices: anchor.geometry.boundaryVertices
        )
    }
}
