/// Unit tests for ARKit→proto pose extraction invariants.
///
/// No ARKit runtime required — these tests exercise only simd math,
/// mirroring the contract in capture_bundle.proto's Pose docstring and
/// pose_math.py (Python side). Together they form the first cross-language
/// invariant check: both sides must agree that poses have unit-norm quaternions.

import XCTest
import simd
@testable import RoomStudioCapture

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

    // MARK: - Depth intrinsics scaling

    /// Pins scaleIntrinsics against hand-computed literals for a realistic device bundle.
    ///
    /// Inputs: fx=1471.8, fy=1471.8, cx=924.2, cy=721.1, rgb=1920×1440, depth=256×192.
    /// sx = sy = 256/1920 = 192/1440 = 0.13333…
    /// Expected (hand-computed, NOT re-derived via the same expression):
    ///   fx: 1471.8 × 0.13333 = 196.24  → assert ≈196.2
    ///   fy: 1471.8 × 0.13333 = 196.24  → assert ≈196.2
    ///   cx:  924.2 × 0.13333 = 123.23  → assert ≈123.2
    ///   cy:  721.1 × 0.13333 =  96.15  → assert ≈96.1
    ///   width=256, height=192 (exact)
    func testScaleIntrinsics_realisticDevice() {
        let result = PoseExtractor.scaleIntrinsics(
            fx: 1471.8, fy: 1471.8,
            cx: 924.2,  cy: 721.1,
            rgbWidth: 1920, rgbHeight: 1440,
            depthWidth: 256, depthHeight: 192
        )
        XCTAssertEqual(result.fx,     196.2, accuracy: 0.2, "fx_depth")
        XCTAssertEqual(result.fy,     196.2, accuracy: 0.2, "fy_depth")
        XCTAssertEqual(result.cx,     123.2, accuracy: 0.2, "cx_depth")
        XCTAssertEqual(result.cy,      96.1, accuracy: 0.2, "cy_depth")
        XCTAssertEqual(result.width,   256,               "depth width")
        XCTAssertEqual(result.height,  192,               "depth height")
    }

    // MARK: - Gravity

    /// Pins gravityInCameraFrame against two hand-derived canonical orientations.
    ///
    /// Identity (camera upright, looking toward horizon):
    ///   q maps world→camera as identity; world-down (0,-1,0) stays (0,-1,0).
    ///
    /// Pitched 90° about -X (camera looking straight down at floor):
    ///   Rotating -90° about world-X carries world-Y down into world-Z:
    ///   world-down (0,-1,0) maps to (0,0,-1) in camera frame.
    func testGravityInCameraFrame_canonicalOrientations() {
        // Identity: camera upright, g_cam should equal world-down
        let qIdentity = simd_quatf(ix: 0, iy: 0, iz: 0, r: 1)
        let gIdentity = PoseExtractor.gravityInCameraFrame(qIdentity)
        XCTAssertEqual(gIdentity.x,  0, accuracy: 1e-5, "identity gx")
        XCTAssertEqual(gIdentity.y, -1, accuracy: 1e-5, "identity gy")
        XCTAssertEqual(gIdentity.z,  0, accuracy: 1e-5, "identity gz")

        // Pitched 90° toward floor (rotation about -X axis by 90°)
        let r = Float(1.0 / 2.0.squareRoot())
        let qPitched = simd_quatf(ix: -r, iy: 0, iz: 0, r: r)
        let gPitched = PoseExtractor.gravityInCameraFrame(qPitched)
        XCTAssertEqual(gPitched.x,  0, accuracy: 1e-5, "pitched gx")
        XCTAssertEqual(gPitched.y,  0, accuracy: 1e-5, "pitched gy")
        XCTAssertEqual(gPitched.z, -1, accuracy: 1e-5, "pitched gz")
    }

    // MARK: - Helpers

    private func norm(_ q: simd_quatf) -> Float {
        let v = q.vector
        return sqrt(v.x*v.x + v.y*v.y + v.z*v.z + v.w*v.w)
    }
}
