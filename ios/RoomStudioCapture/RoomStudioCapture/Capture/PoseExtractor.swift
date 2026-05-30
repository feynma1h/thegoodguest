/// Helpers for extracting proto-ready values from ARCamera and ARDepthData.
///
/// All outputs are in ARKit-native frame (right-handed, +Y up). The iOS client
/// does NOT transform — see capture_bundle.proto file header and decision 0029.
///
/// Gravity extraction formula is intentionally deferred to implementation review
/// against pose_math.py and the Gravity docstring (decision 0029/0030). The stub
/// below compiles but is marked with a TODO so P2 doesn't silently ship wrong gravity.

import ARKit
import AVFoundation
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

    /// Intrinsics for the depth raster from an ARDepthData frame.
    ///
    /// Source: cameraCalibrationData.intrinsicMatrix — same column-major layout as
    /// ARCamera.intrinsics: fx=[0][0], fy=[1][1], cx=[2][0], cy=[2][1].
    /// Width and height are the actual depth pixel buffer dimensions (typically
    /// 256×192), NOT the referencing dimensions in cameraCalibrationData.
    /// See decision 0029 mapping table.
    static func depthIntrinsics(from depthData: ARDepthData) -> RSIntrinsics {
        let m  = depthData.cameraCalibrationData.intrinsicMatrix
        let w  = UInt32(CVPixelBufferGetWidth(depthData.depthMap))
        let h  = UInt32(CVPixelBufferGetHeight(depthData.depthMap))
        return RSIntrinsics.with {
            $0.fx     = m.columns.0.x
            $0.fy     = m.columns.1.y
            $0.cx     = m.columns.2.x
            $0.cy     = m.columns.2.y
            $0.width  = w
            $0.height = h
        }
    }
}
