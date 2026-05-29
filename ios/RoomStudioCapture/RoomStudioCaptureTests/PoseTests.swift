/// Unit tests for ARKit→proto pose extraction invariants.
///
/// No ARKit runtime required — these tests exercise only simd math,
/// mirroring the contract in capture_bundle.proto's Pose docstring and
/// pose_math.py (Python side). Together they form the first cross-language
/// invariant check: both sides must agree that poses have unit-norm quaternions.

import XCTest
import simd

final class PoseTests: XCTestCase {

    // MARK: - Quaternion unit-norm invariant

    /// Identity rotation extracted via simd_quaternion(float4x4) must be unit norm.
    func testUnitNorm_identity() {
        let t = matrix_float4x4(diagonal: simd_float4(1, 1, 1, 1))
        let q = simd_quaternion(t)
        XCTAssertEqual(norm(q), 1.0, accuracy: 1e-3)
    }

    /// Arbitrary rotation extracted from a known quaternion round-trips to unit norm.
    func testUnitNorm_45degAroundY() {
        let original = simd_quatf(angle: .pi / 4, axis: simd_float3(0, 1, 0))
        var t = matrix_float4x4(original)
        t.columns.3 = simd_float4(1.5, 0.3, -2.1, 1)  // arbitrary position
        let extracted = simd_quaternion(t)
        XCTAssertEqual(norm(extracted), 1.0, accuracy: 1e-3)
    }

    /// Compose two rotations; extraction still yields unit norm.
    func testUnitNorm_composedRotation() {
        let q1 = simd_quatf(angle: .pi / 3, axis: simd_normalize(simd_float3(1, 1, 0)))
        let q2 = simd_quatf(angle: .pi / 6, axis: simd_float3(0, 0, 1))
        let composed = q1 * q2
        let t = matrix_float4x4(composed)
        let extracted = simd_quaternion(t)
        XCTAssertEqual(norm(extracted), 1.0, accuracy: 1e-3)
    }

    // MARK: - Quaternion component order

    /// simd_quatf.vector is (ix, iy, iz, r) — i.e. (x, y, z, w) in proto order.
    /// Verify with a known rotation so we're checking semantics, not just norms.
    func testComponentOrder_90degAroundZ() {
        // 90° around +Z: (x=0, y=0, z=sin45°, w=cos45°)
        let q = simd_quatf(angle: .pi / 2, axis: simd_float3(0, 0, 1))
        let v = q.vector
        let expected: Float = sqrt(2) / 2
        XCTAssertEqual(v.x, 0,        accuracy: 1e-5, "quat_x")
        XCTAssertEqual(v.y, 0,        accuracy: 1e-5, "quat_y")
        XCTAssertEqual(v.z, expected, accuracy: 1e-5, "quat_z")
        XCTAssertEqual(v.w, expected, accuracy: 1e-5, "quat_w (real part)")
    }

    // MARK: - Helpers

    private func norm(_ q: simd_quatf) -> Float {
        let v = q.vector
        return sqrt(v.x*v.x + v.y*v.y + v.z*v.z + v.w*v.w)
    }
}
