/// Helpers for extracting proto-ready values from ARCamera and ARDepthData.
///
/// All outputs are in ARKit-native frame (right-handed, +Y up). The iOS client
/// does NOT transform — see capture_bundle.proto file header and decision 0029.
///
/// Gravity extraction formula is intentionally deferred to implementation review
/// against pose_math.py and the Gravity docstring (decision 0029/0030). The stub
/// below compiles but is marked with a TODO so P2 doesn't silently ship wrong gravity.

import ARKit
import simd
import SwiftProtobuf

enum PoseExtractor {

    /// Camera pose (world_from_camera): position + unit quaternion (x, y, z, w).
    ///
    /// ARCamera.transform is a matrix_float4x4 where the upper-left 3×3 is the
    /// rotation R_world_from_cam and column 3 is the position in world coords.
    /// simd_quaternion(float4x4) extracts the rotation; .vector is (ix, iy, iz, r)
    /// = (x, y, z, w) — matching the proto's (quat_x, quat_y, quat_z, quat_w).
    /// See Pose docstring in capture_bundle.proto and decision 0029.
    static func pose(from camera: ARCamera) -> RSPose {
        let t = camera.transform
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

    /// Pinhole intrinsics from ARCamera.
    ///
    /// ARKit's intrinsics matrix is column-major:
    ///   col 0 = (fx,  0, 0)
    ///   col 1 = ( 0, fy, 0)
    ///   col 2 = (cx, cy, 1)
    /// ARKit frames are already undistorted; no distortion fields in the proto.
    static func intrinsics(from camera: ARCamera) -> RSIntrinsics {
        let m = camera.intrinsics
        let sz = camera.imageResolution
        return RSIntrinsics.with {
            $0.fx     = m.columns.0.x
            $0.fy     = m.columns.1.y
            $0.cx     = m.columns.2.x
            $0.cy     = m.columns.2.y
            $0.width  = UInt32(sz.width)
            $0.height = UInt32(sz.height)
        }
    }

    /// Gravity vector in the camera's local frame.
    ///
    /// TODO (P2→P3 gate): formula reviewed in Chat (decision 0030); implementation
    /// deferred to chunk C. Returns zero vector so the proto field is present but
    /// the backend ignores it until C ships the real value.
    static func gravity(from camera: ARCamera) -> RSGravity {
        _ = camera
        return RSGravity()
    }

    /// Intrinsics for the LiDAR depth raster, derived by scaling the RGB
    /// camera's intrinsics to the depth buffer's resolution.
    ///
    /// ARFrame.sceneDepth (ARDepthData) carries no intrinsics object — unlike
    /// AVDepthData (the front TrueDepth camera), ARDepthData has only depthMap
    /// and confidenceMap. The LiDAR depth raster is registered to the wide RGB
    /// camera, so the correct depth intrinsics are camera.intrinsics scaled by
    /// (depth_w / rgb_w) in x and (depth_h / rgb_h) in y. For a typical
    /// 256×192 depth map against a 1920×1440 RGB frame, sx ≈ 0.133, giving
    /// fx_depth ≈ 192 — not ~1500 (which would mean unscaled RGB intrinsics
    /// in a depth-sized field). See decision 0032 for the correction history.
    static func depthIntrinsics(from camera: ARCamera,
                                depthMap: CVPixelBuffer) -> RSIntrinsics {
        let dW = CVPixelBufferGetWidth(depthMap)
        let dH = CVPixelBufferGetHeight(depthMap)
        let sx = Float(dW) / Float(camera.imageResolution.width)
        let sy = Float(dH) / Float(camera.imageResolution.height)
        let K  = camera.intrinsics
        return RSIntrinsics.with {
            $0.fx     = K.columns.0.x * sx
            $0.fy     = K.columns.1.y * sy
            $0.cx     = K.columns.2.x * sx
            $0.cy     = K.columns.2.y * sy
            $0.width  = UInt32(dW)
            $0.height = UInt32(dH)
        }
    }
}
