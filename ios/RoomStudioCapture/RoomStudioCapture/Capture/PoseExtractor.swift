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

    /// World-down (0,-1,0) carried into the camera's local frame via the INVERSE
    /// (world->camera) rotation. `q` is camera->world (same quaternion as Pose.quat_*),
    /// so its inverse maps world vectors into camera-local. This is R^T * worldDown.
    /// world-down is (0,-1,0) ONLY under .gravity world alignment; it breaks under
    /// .camera alignment.
    static func gravityInCameraFrame(_ q: simd_quatf) -> simd_float3 {
        return q.inverse.act(simd_float3(0, -1, 0))
    }

    /// Gravity vector in the camera's local frame. Unit vector.
    /// Thin wrapper over gravityInCameraFrame — see that function's docstring.
    static func gravity(from camera: ARCamera) -> RSGravity {
        let g = gravityInCameraFrame(simd_quaternion(camera.transform))
        return RSGravity.with {
            $0.x = g.x
            $0.y = g.y
            $0.z = g.z
        }
    }

    /// Pure scaling arithmetic for depth intrinsics — no ARKit types, unit-testable.
    ///
    /// sx = depthWidth / rgbWidth, sy = depthHeight / rgbHeight. Each intrinsic
    /// scalar is scaled independently: fx/cx use sx, fy/cy use sy. Width/height
    /// are set to the depth raster dimensions. See decision 0032 for why scaling
    /// is required (unscaled RGB intrinsics in a depth-sized field would give
    /// fx_depth ≈ 1500 instead of the correct ≈196 for a 256×192 depth map).
    static func scaleIntrinsics(fx: Float, fy: Float, cx: Float, cy: Float,
                                rgbWidth: Float, rgbHeight: Float,
                                depthWidth: Int, depthHeight: Int) -> RSIntrinsics {
        let sx = Float(depthWidth)  / rgbWidth
        let sy = Float(depthHeight) / rgbHeight
        return RSIntrinsics.with {
            $0.fx     = fx * sx
            $0.fy     = fy * sy
            $0.cx     = cx * sx
            $0.cy     = cy * sy
            $0.width  = UInt32(depthWidth)
            $0.height = UInt32(depthHeight)
        }
    }

    /// Intrinsics for the LiDAR depth raster, derived by scaling the RGB
    /// camera's intrinsics to the depth buffer's resolution.
    ///
    /// ARFrame.sceneDepth (ARDepthData) carries no intrinsics object — unlike
    /// AVDepthData (the front TrueDepth camera), ARDepthData has only depthMap
    /// and confidenceMap. The LiDAR depth raster is registered to the wide RGB
    /// camera, so the correct depth intrinsics are camera.intrinsics scaled by
    /// (depth_w / rgb_w) in x and (depth_h / rgb_h) in y. Pure math lives in
    /// scaleIntrinsics; this wrapper pulls the values from ARKit types.
    static func depthIntrinsics(from camera: ARCamera,
                                depthMap: CVPixelBuffer) -> RSIntrinsics {
        let K  = camera.intrinsics
        let sz = camera.imageResolution
        return scaleIntrinsics(
            fx: K.columns.0.x, fy: K.columns.1.y,
            cx: K.columns.2.x, cy: K.columns.2.y,
            rgbWidth:    Float(sz.width),
            rgbHeight:   Float(sz.height),
            depthWidth:  CVPixelBufferGetWidth(depthMap),
            depthHeight: CVPixelBufferGetHeight(depthMap)
        )
    }
}
