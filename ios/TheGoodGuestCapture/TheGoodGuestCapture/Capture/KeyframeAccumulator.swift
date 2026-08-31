/// Filters an ARSession frame stream to keyframes by pose delta.
///
/// A frame is accepted when either the translational or rotational distance
/// from the last accepted pose exceeds its threshold. The first frame is
/// always accepted. Designed to be held as a value type inside CaptureManager;
/// call reset() when starting a new capture session.
///
/// Thresholds are tunable; initial values (10 cm / 5°) are a starting heuristic
/// chosen to balance coverage against bundle size for a typical room walk-around.

import ARKit
import simd

struct KeyframeAccumulator {

    /// Distance in meters a camera must travel before a new keyframe is accepted.
    var translationThreshold: Float = 0.10   // 10 cm

    /// Angle in radians a camera must rotate before a new keyframe is accepted.
    var rotationThreshold: Float = 5.0 * .pi / 180.0   // 5 degrees

    private var lastPosition: simd_float3?
    private var lastQuat: simd_quatf?

    /// Evaluate `camera` against the current pose threshold.
    ///
    /// Returns `true` and updates internal state when the frame should become a
    /// keyframe. Returns `false` without mutating state when the frame is too
    /// close to the last accepted pose.
    mutating func shouldAccept(camera: ARCamera) -> Bool {
        let t = camera.transform
        let pos = simd_float3(t.columns.3.x, t.columns.3.y, t.columns.3.z)
        let q   = simd_quaternion(t)

        guard let lastPos = lastPosition, let lastQ = lastQuat else {
            // First frame — always accept.
            lastPosition = pos
            lastQuat     = q
            return true
        }

        let translationDelta = simd_length(pos - lastPos)

        // Angular distance between two unit quaternions: 2 * acos(|q1 · q2|).
        // The absolute value handles the quaternion double-cover (q and -q represent
        // the same rotation). Clamp to [0, 1] to guard against float imprecision
        // pushing the dot product fractionally past 1.0 before acos.
        let dot          = min(abs(simd_dot(q.vector, lastQ.vector)), 1.0)
        let rotationDelta = 2.0 * acos(dot)

        guard translationDelta >= translationThreshold ||
              rotationDelta    >= rotationThreshold
        else { return false }

        lastPosition = pos
        lastQuat     = q
        return true
    }

    /// Reset accumulated state. Call before each new capture session.
    mutating func reset() {
        lastPosition = nil
        lastQuat     = nil
    }
}
