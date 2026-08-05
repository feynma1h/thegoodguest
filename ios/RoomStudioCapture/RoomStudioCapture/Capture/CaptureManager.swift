/// Manages an ARWorldTracking session and accumulates keyframes to the session
/// output directory: tier dispatch, depth capture (LiDAR devices), per-keyframe
/// pose/intrinsics/gravity extraction, RoomPlan co-run, and bundle assembly.
///
/// RoomPlan co-run (decisions 0076/0077, chunk RP-6): the production config runs
/// FIRST with .resetTracking (RoomPlan never resets tracking — the host owns
/// hygiene), then a RoomCaptureSession attaches to the SAME ARSession and runs.
/// The per-frame copy-out path is untouched; ARFrames are never retained
/// (10 retained = pipeline death in ~1 s, measured in the spike). Stop order:
/// stop(pauseARSession: false) → snapshot plane anchors → pause → await
/// RoomBuilder (~1.7 s, ~905 MB transient, after pause) → serialize
/// roomplan/room.json (+ optional room.usdz) → bundle assembly. RoomBuilder
/// hard failure or a room with no wall/floor ships LIDAR_ARKIT with no
/// room_plan — the capture is still valid. RoomPlan's 10 s tracking-failure
/// self-abort (didEndWith worldTrackingFailure) ends the capture gracefully
/// with the partial room; RootFlowView routes on the isRunning flip.
///
/// Passes the Firebase anonymous UID into bundle assembly and publishes
/// assembledWithoutUserId for UploadCoordinator's backstop re-serialize.
///
/// On stop, all in-flight writes complete and BundleAssembler serializes bundle.pb
/// into the session output directory. The resulting URL is published as `bundlePath`.

import ARKit
import Combine
import CoreImage
import os
import RoomPlan
import UIKit

// MARK: - CapturedKeyframe

/// In-memory record for one accepted keyframe. All fields except `depth` are
/// present on every tier. `depth` is set iff the session is LiDAR tier and depth
/// was available on this ARFrame.
struct CapturedKeyframe {
    let index: UInt32
    /// Device-monotonic microseconds — same clock as ARFrame.timestamp.
    let timestampUs: Int64
    /// Relative path within the bundle output directory, e.g. "frames/000000.jpg".
    let rgbRelativePath: String
    let pose: RSPose
    let intrinsics: RSIntrinsics
    /// Gravity direction in the camera frame (R^T · world-down); see
    /// PoseExtractor.gravityInCameraFrame and decisions 0030/0034.
    let gravity: RSGravity
    /// Set iff LiDAR tier and frame.sceneDepth was non-nil. Contains relative
    /// paths ("depth/000000.f32", "confidence/000000.png") and depth intrinsics.
    let depth: RSDepth?
}

// MARK: - WriteStats

/// Mutable counters for JPEG/depth write observability.
/// Accessed exclusively from jpegQueue (serial DispatchQueue), which provides
/// the synchronisation — no locks needed. Not actor-isolated by design.
private final class WriteStats {
    var written  = 0
    var failures = 0
    func reset() { written = 0; failures = 0 }
}

// MARK: - CaptureManager

@MainActor
final class CaptureManager: NSObject, ObservableObject {

    @Published private(set) var frameCount: Int = 0
    @Published private(set) var isRunning: Bool = false
    @Published private(set) var trackingState: ARCamera.TrackingState = .notAvailable
    /// Set after stopCapture() and bundle assembly completes. Nil while capturing or
    /// before first stop.
    @Published private(set) var bundlePath: URL? = nil

    /// True when bundle.pb was assembled without a Firebase UID (first-ever offline
    /// launch). UploadCoordinator patches user_id in-place before building the manifest.
    /// Reset to false at the start of each capture.
    @Published private(set) var assembledWithoutUserId: Bool = false
    /// Non-nil when bundle.pb assembly FAILED. `bundlePath` then never publishes, so
    /// this is the only signal distinguishing "still writing" from "will never write".
    @Published private(set) var assemblyFailure: String?

    /// Census of the BUILT room, set only when the room ships (tier
    /// LIDAR_ROOMPLAN) — the review line must describe data the server will
    /// actually see, so a room that failed the tier condition publishes nothing.
    @Published private(set) var builtCensus: RoomCensus?
    /// Floor plan of the BUILT room, published under exactly the same rule as
    /// builtCensus — review's "the room you got" must be what the server sees.
    @Published private(set) var builtFloorPlan: FloorPlanSnapshot?
    /// Live census from RoomPlan's didUpdate stream (full-room counts, 0076 Q6).
    /// Equality-gated: didUpdate fires on every refinement, and RootFlowView
    /// observes this manager. Feeds the §3 coverage ticks (RP-7).
    @Published private(set) var liveCensus: RoomCensus?
    /// Wall-corner adjacencies measured on the live plan (FloorPlanMath), the
    /// CORNERS tick's input. Updated in step with liveCensus.
    @Published private(set) var liveCornerCount: Int = 0
    /// RoomPlan's latest guidance instruction (sparse — ~one per scan measured).
    /// Raw relay; the guest-voice mapping rides floorPlanFeed.guidance (RP-7).
    @Published private(set) var roomPlanInstruction: RoomCaptureSession.Instruction?

    /// The live floor plan's publisher (RP-7). A separate ObservableObject on
    /// purpose: camera poses publish at up to ~20 Hz, and @Published state on
    /// this manager would re-render every observer (RootFlowView) at that
    /// rate — only the floor-plan subtree observes the feed.
    let floorPlanFeed = FloorPlanFeed()
    /// Objects already announced as "new piece" moments (didAdd dedupe).
    private var announcedPieceIds: Set<UUID> = []
    /// Camera-pose publish throttle state (time + movement gates).
    private var lastCameraPublishAt: TimeInterval = 0
    private var lastCameraPosition: SIMD2<Float>?
    private var lastCameraForward: SIMD2<Float>?

    /// Root directory for this capture's output (temp, per-session UUID).
    /// Structure: <bundleOutputDir>/frames/NNNNNN.jpg
    ///            <bundleOutputDir>/depth/NNNNNN.f32     (LiDAR tier only)
    ///            <bundleOutputDir>/confidence/NNNNNN.png (LiDAR tier only)
    ///            <bundleOutputDir>/bundle.pb            (written on stop)
    private(set) var bundleOutputDir: URL?

    /// Accumulated keyframes in acceptance order.
    private(set) var capturedFrames: [CapturedKeyframe] = []

    /// The session's FINAL plane-anchor set, converted at stopCapture()
    /// (decision 0066: the room shell's measured geometry source). Empty
    /// until first stop; reset at startCapture(). Converted immediately so
    /// no ARKit anchor objects outlive the session snapshot.
    private(set) var capturedPlaneAnchors: [RSPlaneAnchor] = []

    /// Tier selected at session start based on hardware capability.
    private(set) var tier: RSCaptureTier = .arkitOnly

    /// Stable UUID for this capture session, generated at startCapture().
    private(set) var bundleId: UUID = UUID()

    /// Lowercased UUID string. Use this — not bundleId.uuidString — whenever
    /// constructing URL paths (upload session, GCS prefixes). The proto also
    /// emits this value, so all three legs (proto, upload session, GCS) stay
    /// consistent without each caller independently applying .lowercased().
    var bundleIdString: String { bundleId.uuidString.lowercased() }

    /// Device-monotonic microseconds (CACurrentMediaTime) at capture start/stop.
    private(set) var startedAtDeviceUs: Int64 = 0
    private(set) var endedAtDeviceUs: Int64 = 0

    /// Wall-clock microseconds (Unix epoch) at capture start. Display/sort only.
    private(set) var startedAtWallUs: Int64 = 0

    private let arSession   = ARSession()
    private var accumulator = KeyframeAccumulator()

    // RoomPlan co-run state (decisions 0076/0077). All MainActor-mutated.
    private var roomCaptureSession: RoomCaptureSession?
    /// True once didEndWith has delivered CapturedRoomData for this capture —
    /// stopCapture must not call stop() again after the 10 s self-abort.
    private var rpEndReceived = false
    private var capturedRoomData: CapturedRoomData?
    /// Whether this session runs with LiDAR (frozen at startCapture; `tier` is
    /// provisional until assembly, so the final-tier computation needs the
    /// hardware fact independently).
    private var sessionHasLidar = false
    /// One-shot latches for the stop pipeline. finalizeStarted guards the
    /// didEndWith → build path; assemblyStarted guards bundle assembly (the
    /// timeout path and the build path can only assemble once between them).
    private var finalizeStarted = false
    private var assemblyStarted = false
    /// Belt-and-braces: didEndWith has always arrived promptly in measurement
    /// (0076), but if it never comes the capture must not strand review at
    /// "Packing it up" — after this many seconds post-stop, assemble without a
    /// room (LIDAR_ARKIT semantics; the capture stays valid).
    private static let roomPlanEndTimeoutSec: TimeInterval = 15

    // Depth-loss guard (found live at RP-6 Gate 1: the same-runloop co-run
    // attach shipped a capture with sceneDepth nil on all 268 frames; the
    // spike's attach always followed later and never saw it). State feeds
    // RoomPlanWire.shouldReassertDepth; the cure is 0076's measured-survivable
    // mid-scan config re-run.
    private var depthEverSeen = false
    private var depthReasserted = false
    private var depthlessFrameCount = 0

    /// Dedicated queue for JPEG + depth encoding; avoids blocking the main thread.
    /// CIContext is thread-safe for concurrent rendering and is reused across frames.
    private let jpegQueue   = DispatchQueue(label: "com.roomstudio.capture.jpeg", qos: .utility)
    private let ciContext   = CIContext()
    private let writeStats  = WriteStats()

    // Logging privacy policy: UUIDs, blob paths, and enum values may be .public;
    // user identifiers and error payloads stay default-private (redacted in shipped logs).
    private let logger = Logger(subsystem: "com.roomstudio.RoomStudioCapture", category: "Capture")

    override init() {
        super.init()
        arSession.delegate = self
    }

    // MARK: - Session control

    func startCapture() {
        bundlePath = nil
        assembledWithoutUserId = false
        assemblyFailure = nil
        capturedFrames  = []
        capturedPlaneAnchors = []
        accumulator.reset()
        frameCount      = 0
        bundleId        = UUID()

        // RoomPlan co-run state.
        roomCaptureSession  = nil
        rpEndReceived       = false
        capturedRoomData    = nil
        finalizeStarted     = false
        assemblyStarted     = false
        builtCensus         = nil
        builtFloorPlan      = nil
        liveCensus          = nil
        liveCornerCount     = 0
        roomPlanInstruction = nil
        depthEverSeen       = false
        depthReasserted     = false
        depthlessFrameCount = 0

        // Live floor plan state (RP-7).
        floorPlanFeed.reset()
        announcedPieceIds   = []
        lastCameraPublishAt = 0
        lastCameraPosition  = nil
        lastCameraForward   = nil

        // Tier dispatch: provisional until assembly — LIDAR_ROOMPLAN is decided
        // by whether a built room actually ships (RoomPlanWire.finalTier).
        let hasLidar = ARWorldTrackingConfiguration.supportsSceneReconstruction(.meshWithClassification)
        sessionHasLidar = hasLidar
        tier = hasLidar ? .lidarArkit : .arkitOnly

        startedAtDeviceUs = Int64(CACurrentMediaTime() * 1_000_000)
        startedAtWallUs   = Int64(Date().timeIntervalSince1970 * 1_000_000)
        bundleOutputDir   = makeOutputDir(forLidar: hasLidar)

        let stats = writeStats
        jpegQueue.async { stats.reset() }

        let config = ARWorldTrackingConfiguration()
        config.worldAlignment = .gravity
        // Plane detection on every tier (decision 0066): ARKit measures
        // floors and walls on all devices; the final anchor set is read at
        // stopCapture() and shipped in the bundle as plane_anchors.
        config.planeDetection = [.horizontal, .vertical]
        if hasLidar, ARWorldTrackingConfiguration.supportsFrameSemantics(.sceneDepth) {
            config.frameSemantics.insert(.sceneDepth)
        }
        // Production config FIRST, with reset — RoomPlan never resets tracking,
        // so this run is the session's tracking hygiene (0076 Q3).
        arSession.run(config, options: [.resetTracking, .removeExistingAnchors])

        // Attach the RoomPlan co-run to the SAME session (0076: its native
        // config is a superset of ours; depth and the keyframe path survive).
        // Not supported (non-LiDAR, simulator) → plain LIDAR_ARKIT/ARKIT_ONLY.
        if hasLidar, RoomCaptureSession.isSupported {
            let cs = RoomCaptureSession(arSession: arSession)
            cs.delegate = self
            cs.run(configuration: RoomCaptureSession.Configuration())
            roomCaptureSession = cs
            // Attach-time observability (the spike's config instrument, kept):
            // the frame-semantics raw value says whether .sceneDepth (bit 8)
            // survived the attach. The frame-level guard below is the actual
            // protection; this line is for reading the story off a console.
            let fs = arSession.configuration?.frameSemantics.rawValue ?? 0
            logger.info("[CaptureManager] roomplan attached: installed fs=\(fs, privacy: .public)")
        }
        logger.info("[CaptureManager] capture started: bundleId=\(self.bundleIdString, privacy: .public) tier=\(String(describing: self.tier), privacy: .public) roomplan=\(self.roomCaptureSession != nil, privacy: .public)")
        isRunning = true
    }

    /// Stop the session. Waits for in-flight writes, logs summary, assembles bundle.pb.
    ///
    /// Stop order per decisions 0076/0077: RoomPlan stops FIRST against the
    /// still-running session (pauseARSession: false — it finalizes its
    /// CapturedRoomData there), then the anchor snapshot, then the pause.
    /// Assembly is deferred until didEndWith delivers the room data (or the
    /// timeout fires); a capture with no RoomPlan co-run assembles immediately.
    ///
    /// Idempotent via the isRunning guard: the RoomPlan 10 s self-abort calls
    /// this from didEndWith, and a user Finish racing it must not double-stop.
    func stopCapture() {
        guard isRunning else { return }
        isRunning = false
        endedAtDeviceUs = Int64(CACurrentMediaTime() * 1_000_000)

        // 1. RoomPlan first (no-op when it already ended via the self-abort).
        let rpActive = roomCaptureSession != nil
        if rpActive, !rpEndReceived {
            roomCaptureSession?.stop(pauseARSession: false)
        }

        // 2. Snapshot the FINAL plane-anchor set before pausing — the last
        // frame's anchors are the session's best merged/refined planes
        // (decision 0066). Same world frame as every camera pose.
        let arAnchors = (arSession.currentFrame?.anchors ?? [])
            .compactMap { $0 as? ARPlaneAnchor }
        capturedPlaneAnchors = arAnchors.map { PlaneAnchorExtractor.from($0) }

        // 3. Pause. RoomBuilder runs AFTER this (its ~905 MB transient must not
        // overlap the live session, 0076 Q3).
        arSession.pause()

        // V3-walk observability: counts by alignment + classification tell
        // the on-device plane-quality story without any new UI.
        let horiz = capturedPlaneAnchors.filter { $0.alignment == .horizontal }.count
        let vert  = capturedPlaneAnchors.filter { $0.alignment == .vertical }.count
        let classified = capturedPlaneAnchors.filter { !$0.classification.isEmpty }.count
        logger.info("[CaptureManager] plane anchors at stop: total=\(self.capturedPlaneAnchors.count, privacy: .public) horizontal=\(horiz, privacy: .public) vertical=\(vert, privacy: .public) classified=\(classified, privacy: .public)")

        // Depth observability at stop (the RP-6 Gate-1 depth loss was invisible
        // until the bundle was parsed server-side — never again).
        let withDepth = capturedFrames.filter { $0.depth != nil }.count
        logger.info("[CaptureManager] keyframes with depth at stop: \(withDepth, privacy: .public)/\(self.capturedFrames.count, privacy: .public) reasserted=\(self.depthReasserted, privacy: .public)")

        // Write verification runs on jpegQueue — after all in-flight JPEG/depth
        // writes, independent of how long the room build takes.
        let outDir   = bundleOutputDir!
        let stats    = writeStats
        let accepted = frameCount
        let log      = logger
        jpegQueue.async {
            let framesDir = outDir.appendingPathComponent("frames")
            let onDisk = (try? FileManager.default.contentsOfDirectory(
                at: framesDir, includingPropertiesForKeys: nil
            ).filter { $0.pathExtension == "jpg" }.count) ?? -1
            log.info("""
            [CaptureManager] stop — write verification
              accepted : \(accepted)
              written  : \(stats.written)
              failures : \(stats.failures)
              on-disk  : \(onDisk) .jpg files
              temp-dir : \(framesDir.path, privacy: .public)
            """)
        }

        // 4. Assembly gate. With a co-run, didEndWith owns the next step: on
        // the self-abort path it already fired (rpEndReceived), so finalize
        // now; otherwise it arrives momentarily and finalizes then.
        if rpActive {
            if rpEndReceived {
                finalizeRoomPlanAndAssemble()
            } else {
                scheduleRoomPlanEndTimeout()
            }
        } else {
            assembleBundle(roomPlan: nil)
        }
    }

    // MARK: - RoomPlan finalize + assembly

    /// Build the CapturedRoom from didEndWith's data, serialize it, and
    /// assemble the bundle. One-shot; every failure inside degrades to
    /// assembling WITHOUT a room (LIDAR_ARKIT semantics — never a lost capture).
    private func finalizeRoomPlanAndAssemble() {
        guard !finalizeStarted, !assemblyStarted else { return }
        finalizeStarted = true
        guard let data = capturedRoomData else {
            assembleBundle(roomPlan: nil)
            return
        }
        Task { @MainActor [weak self] in
            guard let self else { return }
            var built: CapturedRoom?
            do {
                built = try await RoomBuilder(options: [.beautifyObjects])
                    .capturedRoom(from: data)
            } catch {
                self.logger.info("[CaptureManager] RoomBuilder failed — shipping without room plan: \(error.localizedDescription)")
            }
            // The timeout may have assembled while the builder ran; the bundle
            // already shipped without a room, so writing roomplan/ blobs now
            // would put unreferenced files into the manifest at send time.
            guard !self.assemblyStarted else {
                self.logger.info("[CaptureManager] room built after assembly timeout — dropped")
                return
            }
            var model: RSRoomPlanModel?
            if let room = built {
                self.logger.info("[CaptureManager] room built: objects=\(room.objects.count, privacy: .public) walls=\(room.walls.count, privacy: .public) doors=\(room.doors.count, privacy: .public) windows=\(room.windows.count, privacy: .public) openings=\(room.openings.count, privacy: .public) floors=\(room.floors.count, privacy: .public)")
                if RoomPlanWire.roomQualifies(wallCount: room.walls.count,
                                              floorCount: room.floors.count) {
                    model = self.serializeRoomPlan(room)
                    if model != nil {
                        self.builtCensus = RoomCensus(
                            objects: room.objects.count,
                            walls: room.walls.count,
                            doors: room.doors.count,
                            windows: room.windows.count,
                            openings: room.openings.count,
                            floors: room.floors.count
                        )
                        self.builtFloorPlan = FloorPlanSnapshot(room: room)
                    }
                } else {
                    self.logger.info("[CaptureManager] built room has no wall/floor — shipping LIDAR_ARKIT")
                }
            }
            self.assembleBundle(roomPlan: model)
        }
    }

    /// Write roomplan/room.json (+ optional room.usdz) into the session dir and
    /// return the proto model, or nil if the JSON leg failed — json_gcs_path is
    /// THE geometry source (decision 0077), so no json means no room_plan and
    /// tier LIDAR_ARKIT. A USDZ export failure never blocks the tier.
    private func serializeRoomPlan(_ room: CapturedRoom) -> RSRoomPlanModel? {
        guard let outDir = bundleOutputDir else { return nil }
        let rpDir = outDir.appendingPathComponent("roomplan")
        // CAFUFA like every other blob dir: background URLSession must read
        // these while the device is locked (decisions 0040/0042).
        try? FileManager.default.createDirectory(
            at: rpDir,
            withIntermediateDirectories: true,
            attributes: [.protectionKey: FileProtectionType.completeUntilFirstUserAuthentication]
        )

        let encoder = JSONEncoder()
        encoder.outputFormatting = [.sortedKeys]
        let jsonData: Data
        do {
            jsonData = try encoder.encode(room)
        } catch {
            logger.info("[CaptureManager] CapturedRoom encode failed — shipping LIDAR_ARKIT: \(error.localizedDescription)")
            return nil
        }
        let jsonURL = rpDir.appendingPathComponent("room.json")
        do {
            try jsonData.write(to: jsonURL, options: .completeFileProtectionUntilFirstUserAuthentication)
        } catch {
            logger.info("[CaptureManager] room.json write failed — shipping LIDAR_ARKIT: \(error.localizedDescription)")
            return nil
        }

        var model = RSRoomPlanModel()
        model.jsonGcsPath = "roomplan/room.json"
        model.roomplanVersion = RoomPlanWire.versionString(
            osVersion: UIDevice.current.systemVersion,
            capturedRoomVersion: RoomPlanWire.capturedRoomVersion(fromJSON: jsonData)
        )

        // USDZ: optional debugging / future-viewer artifact (~56 KB measured).
        let usdzURL = rpDir.appendingPathComponent("room.usdz")
        do {
            try room.export(to: usdzURL, exportOptions: .parametric)
            // export() writes without our protection class; align it after.
            try? FileManager.default.setAttributes(
                [.protectionKey: FileProtectionType.completeUntilFirstUserAuthentication],
                ofItemAtPath: usdzURL.path
            )
            model.usdzGcsPath = "roomplan/room.usdz"
        } catch {
            logger.info("[CaptureManager] USDZ export failed — shipping json only: \(error.localizedDescription)")
        }
        logger.info("[CaptureManager] roomplan serialized: json=\(jsonData.count, privacy: .public)B version=\(model.roomplanVersion, privacy: .public) usdz=\(model.usdzGcsPath.isEmpty ? "no" : "yes", privacy: .public)")
        return model
    }

    /// Compute the final tier and assemble bundle.pb on jpegQueue (after all
    /// blob writes). One-shot across the build and timeout paths.
    private func assembleBundle(roomPlan: RSRoomPlanModel?) {
        guard !assemblyStarted else { return }
        assemblyStarted = true
        tier = RoomPlanWire.finalTier(hasLidar: sessionHasLidar,
                                      roomPlanShipped: roomPlan != nil)

        // Snapshot immutable session state before hopping off MainActor.
        // userId: read from Keychain-backed Firebase cache — offline-safe.
        // Empty string on a first-ever offline launch (backstop handled by UploadCoordinator).
        let userId    = AuthManager.shared.currentUID ?? ""
        let noUid     = userId.isEmpty
        let assembler = BundleAssembler(
            bundleId:          bundleId,
            tier:              tier,
            startedAtDeviceUs: startedAtDeviceUs,
            endedAtDeviceUs:   endedAtDeviceUs,
            startedAtWallUs:   startedAtWallUs,
            frames:            capturedFrames,
            planeAnchors:      capturedPlaneAnchors,
            roomPlan:          roomPlan,
            outputDir:         bundleOutputDir!
        )
        let log = logger
        jpegQueue.async { [weak self] in
            do {
                let url = try assembler.write(userId: userId)
                log.info("[CaptureManager] bundle.pb → \(url.path, privacy: .public) tier=\(String(describing: assembler.tier), privacy: .public) (user_id: \(userId.isEmpty ? "<none — backstop pending>" : userId))")
                DispatchQueue.main.async {
                    self?.bundlePath = url
                    self?.assembledWithoutUserId = noUid
                }
            } catch {
                log.info("[CaptureManager] bundle assembly failed: \(error.localizedDescription)")
                // Publish it. Without this bundlePath stays nil forever and any UI
                // treating "no bundlePath yet" as transient (review's "packing it
                // up…") waits on a publish that will never come.
                DispatchQueue.main.async {
                    self?.assemblyFailure = error.localizedDescription
                }
            }
        }
    }

    /// If didEndWith never arrives (never observed — 0076 measured prompt
    /// delivery on both the stop and self-abort paths), assemble without a
    /// room after the deadline rather than stranding review at "Packing it up".
    private func scheduleRoomPlanEndTimeout() {
        let expected = bundleId
        Task { @MainActor [weak self] in
            try? await Task.sleep(nanoseconds: UInt64(Self.roomPlanEndTimeoutSec * 1_000_000_000))
            guard let self,
                  self.bundleId == expected,
                  !self.isRunning,
                  !self.finalizeStarted,
                  !self.assemblyStarted
            else { return }
            self.logger.info("[CaptureManager] RoomPlan didEndWith missing after \(Self.roomPlanEndTimeoutSec, privacy: .public)s — assembling without room plan")
            self.assembleBundle(roomPlan: nil)
        }
    }

    // MARK: - Private helpers

    private func makeOutputDir(forLidar: Bool) -> URL {
        // Write to Application Support, not temporaryDirectory. iOS can purge tmp while
        // the app is not running; a 12h+ upload window crosses that boundary reliably.
        // App Support survives kill/relaunch/storage-pressure (decision 0043).
        let root = CaptureStorageSweeper.capturesRootURL()
                       .appendingPathComponent(bundleIdString)

        var subdirs = ["frames"]
        if forLidar { subdirs += ["depth", "confidence"] }

        // Create root + subdirs with explicit CAFUFA so background URLSession delivery
        // can read blob files while the device is locked (decisions 0040 item 7, 0042).
        for sub in ([""] + subdirs) {
            let dir = sub.isEmpty ? root : root.appendingPathComponent(sub)
            try? FileManager.default.createDirectory(
                at: dir,
                withIntermediateDirectories: true,
                attributes: [.protectionKey: FileProtectionType.completeUntilFirstUserAuthentication]
            )
        }

        // Exclude from iCloud/iTunes backup: capture blobs are large and regenerable.
        // Must be set on the directory itself (not inherited from parent).
        var mutableRoot = root
        var vals = URLResourceValues()
        vals.isExcludedFromBackup = true
        try? mutableRoot.setResourceValues(vals)

        return root
    }

    private func acceptFrame(
        camera:      ARCamera,
        pixelBuffer: CVImageBuffer,
        timestamp:   TimeInterval,
        depthData:   ARDepthData?
    ) {
        guard let outputDir = bundleOutputDir else { return }
        let index        = UInt32(capturedFrames.count)
        let relativePath = String(format: "frames/%06d.jpg", index)
        let fileURL      = outputDir.appendingPathComponent(relativePath)

        // Write JPEG on jpegQueue.
        let context = ciContext
        let stats   = writeStats
        let log = logger
        jpegQueue.async {
            let ci = CIImage(cvImageBuffer: pixelBuffer)
            guard
                let cg   = context.createCGImage(ci, from: ci.extent),
                let data = UIImage(cgImage: cg).jpegData(compressionQuality: 0.85)
            else {
                log.info("[CaptureManager] JPEG encode failed: \(relativePath, privacy: .public)")
                stats.failures += 1
                return
            }
            do {
                try data.write(to: fileURL, options: .completeFileProtectionUntilFirstUserAuthentication)
                stats.written += 1
            } catch {
                log.info("[CaptureManager] JPEG write error: \(relativePath, privacy: .public): \(error.localizedDescription)")
                stats.failures += 1
            }
        }

        // Capture depth for LiDAR frames (depthData is nil on non-LiDAR devices).
        let depth: RSDepth? = depthData.map { dd in
            captureDepth(dd, camera: camera, index: index, outputDir: outputDir, stats: stats)
        }

        let gravityProto = PoseExtractor.gravity(from: camera)
        capturedFrames.append(CapturedKeyframe(
            index:           index,
            timestampUs:     Int64(timestamp * 1_000_000),
            rgbRelativePath: relativePath,
            pose:            PoseExtractor.pose(from: camera),
            intrinsics:      PoseExtractor.intrinsics(from: camera),
            gravity:         gravityProto,
            depth:           depth
        ))
        frameCount = capturedFrames.count
    }

    /// Build an RSDepth value and schedule the raster writes on jpegQueue.
    /// Raster write failures are asynchronous: they are logged and counted in
    /// stats, not reflected in the return value.
    ///
    /// depthData comes from frame.sceneDepth (ARDepthData — LiDAR rear sensor).
    /// camera is the RGB ARCamera for the same frame; its intrinsics are scaled
    /// to the depth buffer dimensions to produce depth-raster intrinsics.
    private func captureDepth(
        _ depthData:  ARDepthData,
        camera:       ARCamera,
        index:        UInt32,
        outputDir:    URL,
        stats:        WriteStats
    ) -> RSDepth {
        let depthRelPath = String(format: "depth/%06d.f32",  index)
        let confRelPath  = String(format: "confidence/%06d.png", index)

        let depthMap = depthData.depthMap       // DepthFloat32 CVPixelBuffer
        let confMap  = depthData.confidenceMap  // OneComponent8 CVPixelBuffer?

        // Compute intrinsics on the calling thread (MainActor).
        // depthData is ref-counted; pixel buffers are valid while held.
        let intrinsics = PoseExtractor.depthIntrinsics(from: camera, depthMap: depthMap)
        let w = intrinsics.width
        let h = intrinsics.height
        let depthURL   = outputDir.appendingPathComponent(depthRelPath)
        let confURL    = outputDir.appendingPathComponent(confRelPath)
        let log = logger

        jpegQueue.async {
            // Float32 raster: width*height*4 bytes, row-major, packed (no stride padding).
            if let bytes = Self.extractPackedBytes(depthMap, bytesPerPixel: 4) {
                do {
                    try bytes.write(to: depthURL, options: .completeFileProtectionUntilFirstUserAuthentication)
                } catch {
                    log.info("[CaptureManager] depth write error: \(depthRelPath, privacy: .public): \(error.localizedDescription)")
                    stats.failures += 1
                }
            }
            // Confidence raster: uint8, 0=low/1=med/2=high (ARConfidenceLevel).
            if let conf = confMap,
               let bytes = Self.extractPackedBytes(conf, bytesPerPixel: 1) {
                do {
                    try bytes.write(to: confURL, options: .completeFileProtectionUntilFirstUserAuthentication)
                } catch {
                    log.info("[CaptureManager] confidence write error: \(confRelPath, privacy: .public): \(error.localizedDescription)")
                }
            }
        }

        var depth = RSDepth()
        depth.depthGcsPath = depthRelPath
        depth.confidenceGcsPath = confRelPath
        depth.width      = w
        depth.height     = h
        depth.intrinsics = intrinsics
        return depth
    }

    /// Copy pixel buffer bytes into a packed Data (strips stride padding).
    /// Returns nil if the base address cannot be locked.
    private static func extractPackedBytes(_ buffer: CVPixelBuffer, bytesPerPixel: Int) -> Data? {
        guard CVPixelBufferLockBaseAddress(buffer, .readOnly) == kCVReturnSuccess else { return nil }
        defer { CVPixelBufferUnlockBaseAddress(buffer, .readOnly) }
        guard let base = CVPixelBufferGetBaseAddress(buffer) else { return nil }
        let w       = CVPixelBufferGetWidth(buffer)
        let h       = CVPixelBufferGetHeight(buffer)
        let stride  = CVPixelBufferGetBytesPerRow(buffer)
        let rowBytes = w * bytesPerPixel
        var out = Data(count: h * rowBytes)
        out.withUnsafeMutableBytes { dst in
            guard let dstBase = dst.baseAddress else { return }
            for row in 0..<h {
                memcpy(dstBase.advanced(by: row * rowBytes),
                       base.advanced(by: row * stride),
                       rowBytes)
            }
        }
        return out
    }
}

// MARK: - ARSessionDelegate

extension CaptureManager: ARSessionDelegate {

    nonisolated func session(_ session: ARSession, didUpdate frame: ARFrame) {
        // Skip frames with unreliable tracking — pose and gravity data invalid.
        switch frame.camera.trackingState {
        case .normal:                 break
        case .limited, .notAvailable: return
        }

        // Extract values on the ARKit thread before hopping to MainActor.
        // ARFrame and its pixel buffers are ref-counted and remain valid while held.
        let camera      = frame.camera
        let pixelBuffer = frame.capturedImage
        let timestamp   = frame.timestamp
        // sceneDepth: ARDepthData? — LiDAR rear sensor, nil on non-LiDAR devices.
        // capturedDepthData is the front TrueDepth camera; do NOT use it here.
        let depthData   = frame.sceneDepth
        // Plain values for the floor plan's camera cone (RP-7). Only .normal
        // frames reach here, so the pose is valid by construction.
        let cameraTransform = camera.transform

        DispatchQueue.main.async { [weak self] in
            guard let self, self.isRunning else { return }
            self.noteFrameDepth(depthData != nil)
            self.publishCameraPlanPose(cameraTransform)
            if self.accumulator.shouldAccept(camera: camera) {
                self.acceptFrame(
                    camera:      camera,
                    pixelBuffer: pixelBuffer,
                    timestamp:   timestamp,
                    depthData:   depthData)
            }
        }
    }

    /// Feed the floor plan's camera cone, throttled twice over: a 20 Hz time
    /// gate plus a movement gate, so holding still publishes nothing and the
    /// canvas doesn't redraw for sub-millimeter jitter.
    private func publishCameraPlanPose(_ transform: simd_float4x4) {
        let now = CACurrentMediaTime()
        guard now - lastCameraPublishAt >= 0.05 else { return }
        guard let cam = FloorPlanMath.cameraPlanPose(
            transform: transform, previousForward: lastCameraForward) else { return }
        if let p = lastCameraPosition, let f = lastCameraForward,
           simd_distance(p, cam.position) < 0.005,
           simd_distance(f, cam.forward) < 0.005 {
            return
        }
        lastCameraPublishAt = now
        lastCameraPosition = cam.position
        lastCameraForward = cam.forward
        floorPlanFeed.publish(camera: cam)
    }

    /// Depth-loss guard (see RoomPlanWire.shouldReassertDepth for the found-live
    /// failure and the rule). Runs on every frame; almost always a no-op.
    private func noteFrameDepth(_ hadDepth: Bool) {
        if hadDepth {
            depthEverSeen = true
            return
        }
        depthlessFrameCount += 1
        guard RoomPlanWire.shouldReassertDepth(hasLidar: sessionHasLidar,
                                               depthEverSeen: depthEverSeen,
                                               alreadyReasserted: depthReasserted,
                                               depthlessFrames: depthlessFrameCount)
        else { return }
        depthReasserted = true
        reassertSceneDepth()
    }

    /// 0076's measured-survivable cure: take the INSTALLED configuration
    /// (RoomPlan's composite when co-running), re-insert .sceneDepth, and
    /// re-run with no options — the scan continues through it and the room
    /// still builds (spike Q1's re-assert probe, verbatim).
    private func reassertSceneDepth() {
        guard let cfg = arSession.configuration else {
            logger.info("[CaptureManager] depth re-assert skipped: no installed configuration")
            return
        }
        guard type(of: cfg).supportsFrameSemantics(.sceneDepth) else {
            logger.info("[CaptureManager] depth re-assert skipped: config class lacks sceneDepth support")
            return
        }
        let before = cfg.frameSemantics.rawValue
        cfg.frameSemantics.insert(.sceneDepth)
        arSession.run(cfg, options: [])
        logger.info("[CaptureManager] sceneDepth re-asserted after \(self.depthlessFrameCount, privacy: .public) depthless frames (fs \(before, privacy: .public) → \(cfg.frameSemantics.rawValue, privacy: .public))")
    }

    nonisolated func session(
        _ session: ARSession,
        cameraDidChangeTrackingState camera: ARCamera
    ) {
        let state = camera.trackingState
        DispatchQueue.main.async { [weak self] in
            self?.trackingState = state
        }
    }
}

// MARK: - RoomCaptureSessionDelegate

extension CaptureManager: RoomCaptureSessionDelegate {

    /// Full-room stream (didUpdate carries the FULL room — 0076 Q6): census
    /// counts plus the floor-plan snapshot, both extracted as plain values on
    /// the delivery thread; the CapturedRoom itself never crosses (copy-out
    /// principle). Census publishes are equality-gated — refinements arrive
    /// continuously and RootFlowView observes this manager.
    nonisolated func captureSession(_ session: RoomCaptureSession, didUpdate room: CapturedRoom) {
        let census = RoomCensus(
            objects: room.objects.count,
            walls: room.walls.count,
            doors: room.doors.count,
            windows: room.windows.count,
            openings: room.openings.count,
            floors: room.floors.count
        )
        let snapshot = FloorPlanSnapshot(room: room)
        let corners = FloorPlanMath.cornerCount(walls: snapshot.walls)
        DispatchQueue.main.async { [weak self] in
            guard let self, self.isRunning else { return }
            if census != self.liveCensus {
                self.liveCensus = census
                self.floorPlanFeed.publish(census: census)
            }
            if corners != self.liveCornerCount {
                self.liveCornerCount = corners
            }
            self.floorPlanFeed.publish(snapshot: snapshot)
        }
    }

    /// Delta stream: didAdd carries only the changed entities (0076 Q6) — the
    /// "new piece" signal. Objects become guest moments, deduped by identifier
    /// (FloorPlanVoice.unannounced); walls land silently on the plan via
    /// didUpdate. didChange/didRemove are deliberately unconsumed: refinement
    /// and removal state both arrive with the next full-room didUpdate.
    nonisolated func captureSession(_ session: RoomCaptureSession, didAdd room: CapturedRoom) {
        let pieces = room.objects.map {
            FloorPlanPiece(id: $0.identifier,
                           categoryToken: String(describing: $0.category),
                           confidence: FloorPlanConfidence($0.confidence))
        }
        guard !pieces.isEmpty else { return }
        DispatchQueue.main.async { [weak self] in
            guard let self, self.isRunning else { return }
            let fresh = FloorPlanVoice.unannounced(pieces, seen: self.announcedPieceIds)
            for piece in fresh {
                self.announcedPieceIds.insert(piece.id)
                self.floorPlanFeed.noteMoment(line: FloorPlanVoice.momentLine(
                    categoryToken: piece.categoryToken, confidence: piece.confidence))
            }
        }
    }

    nonisolated func captureSession(_ session: RoomCaptureSession,
                                    didProvide instruction: RoomCaptureSession.Instruction) {
        // Token, not the enum, so the guest-voice table (FloorPlanVoice) never
        // imports RoomPlan; unknown future cases degrade to standing down.
        let token = String(describing: instruction)
        DispatchQueue.main.async { [weak self] in
            guard let self, self.isRunning else { return }
            self.roomPlanInstruction = instruction
            self.floorPlanFeed.noteGuidance(
                line: FloorPlanVoice.guidanceLine(instructionToken: token))
        }
    }

    /// End of the RoomPlan scan. Two ways here:
    ///   - user stop: stopCapture() already ran (isRunning false) → finalize.
    ///   - the 10 s tracking-failure self-abort (0076 Q3): RoomPlan ends ITSELF
    ///     (error = worldTrackingFailure) while the capture is running → end
    ///     the capture gracefully; the partial room in `data` still ships if
    ///     it builds. stopCapture() sees rpEndReceived and finalizes.
    nonisolated func captureSession(_ session: RoomCaptureSession,
                                    didEndWith data: CapturedRoomData, error: (any Error)?) {
        let errorDescription = error.map { String(describing: $0) }
        Task { @MainActor [weak self] in
            guard let self else { return }
            self.rpEndReceived = true
            self.capturedRoomData = data
            if let errorDescription {
                self.logger.info("[CaptureManager] RoomPlan ended with error: \(errorDescription, privacy: .public)")
            }
            if self.isRunning {
                self.logger.info("[CaptureManager] RoomPlan self-abort — ending capture with the partial room")
                self.stopCapture()
            } else {
                self.finalizeRoomPlanAndAssemble()
            }
        }
    }
}
