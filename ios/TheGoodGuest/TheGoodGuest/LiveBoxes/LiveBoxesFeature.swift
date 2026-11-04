/// The one switch for live boxes — DEBUG-only (decision 0295).
///
/// ON, the Scan screen shows the camera with live boxes on it and the detector
/// starts with the scan (decision 0301). OFF, nothing of the feature runs: the
/// Scan screen is the stock one, with its floor plan, and no frame is forwarded
/// anywhere. This is a code constant, default ON. It is not a Settings entry or
/// a launch argument: a build either has the feature or does not.
///
/// This is not the licence boundary. The feature is compiled only into Debug
/// builds whatever this says (tools/test_live_boxes_boundaries.py pins that);
/// this switch decides whether a Debug build uses it.
///
/// Read by: RootFlowView, LiveBoxesSession, LiveBoxesRuntimeTests.

#if DEBUG

nonisolated enum LiveBoxesFeature {
    static let isEnabled = true
}

#endif
