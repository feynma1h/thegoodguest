/// Pins for the RoomPlan wire decisions (decision 0077, chunk RP-6).
///
/// Every decision that determines what ships — the tier condition, the final
/// tier table, the provenance string, the census line — is a pure function in
/// RoomPlanWire.swift precisely so it can be pinned here as a table instead of
/// read out of CaptureManager's stop pipeline. Also pins the BundleAssembler
/// round-trip: a RoomPlanModel survives serialize → parse verbatim, and a nil
/// roomPlan leaves the field ABSENT (hasRoomPlan false), which is the wire
/// shape every pre-RoomPlan bundle already has.
///
/// No network, no Firebase, no ARKit — runs on the simulator.

import SwiftProtobuf
import XCTest
@testable import RoomStudioCapture

final class RoomPlanWireTests: XCTestCase {

    // MARK: - Tier condition (0077: ≥1 wall OR floor)

    func test_roomQualifies_table() {
        XCTAssertFalse(RoomPlanWire.roomQualifies(wallCount: 0, floorCount: 0),
                       "A room with no wall and no floor is not a room model")
        XCTAssertTrue(RoomPlanWire.roomQualifies(wallCount: 1, floorCount: 0))
        XCTAssertTrue(RoomPlanWire.roomQualifies(wallCount: 0, floorCount: 1))
        XCTAssertTrue(RoomPlanWire.roomQualifies(wallCount: 13, floorCount: 1),
                      "The spike reference room (13 walls, 1 floor) qualifies")
    }

    // MARK: - Final tier table

    func test_finalTier_table() {
        XCTAssertEqual(RoomPlanWire.finalTier(hasLidar: true, roomPlanShipped: true),
                       .lidarRoomplan)
        XCTAssertEqual(RoomPlanWire.finalTier(hasLidar: true, roomPlanShipped: false),
                       .lidarArkit,
                       "RoomPlan hard failure ships LIDAR_ARKIT — capture still valid")
        XCTAssertEqual(RoomPlanWire.finalTier(hasLidar: false, roomPlanShipped: false),
                       .arkitOnly)
        // Contradiction (cannot occur — RoomPlan requires LiDAR): hardware truth
        // wins; never mint a LiDAR tier the frames can't back.
        XCTAssertEqual(RoomPlanWire.finalTier(hasLidar: false, roomPlanShipped: true),
                       .arkitOnly)
    }

    // MARK: - Provenance string

    func test_versionString_composition() {
        XCTAssertEqual(
            RoomPlanWire.versionString(osVersion: "26.5.2", capturedRoomVersion: 2),
            "ios26.5.2;CapturedRoom.v2;beautifyObjects"
        )
        XCTAssertEqual(
            RoomPlanWire.versionString(osVersion: "26.5.2", capturedRoomVersion: nil),
            "ios26.5.2;CapturedRoom.v?;beautifyObjects",
            "Unknown schema version degrades to v? — provenance never fails the capture"
        )
    }

    func test_capturedRoomVersion_peek() {
        let good = Data(#"{"version": 2, "walls": [], "objects": []}"#.utf8)
        XCTAssertEqual(RoomPlanWire.capturedRoomVersion(fromJSON: good), 2)

        let missing = Data(#"{"walls": []}"#.utf8)
        XCTAssertNil(RoomPlanWire.capturedRoomVersion(fromJSON: missing))

        let notADict = Data(#"[1, 2, 3]"#.utf8)
        XCTAssertNil(RoomPlanWire.capturedRoomVersion(fromJSON: notADict))

        let notJSON = Data("not json".utf8)
        XCTAssertNil(RoomPlanWire.capturedRoomVersion(fromJSON: notJSON))
    }

    // MARK: - Depth re-assert guard (found live at RP-6 Gate 1)

    func test_shouldReassertDepth_table() {
        let t = RoomPlanWire.depthReassertThreshold
        // The live failure: LiDAR session, depth never seen, threshold reached.
        XCTAssertTrue(RoomPlanWire.shouldReassertDepth(
            hasLidar: true, depthEverSeen: false, alreadyReasserted: false, depthlessFrames: t))
        // Below threshold: a boot edge must not trigger a config re-run.
        XCTAssertFalse(RoomPlanWire.shouldReassertDepth(
            hasLidar: true, depthEverSeen: false, alreadyReasserted: false, depthlessFrames: t - 1))
        // Depth WAS seen: later depthless frames are the legal mid-walk dropout
        // class (0033/0074-walk evidence) — never re-run for those.
        XCTAssertFalse(RoomPlanWire.shouldReassertDepth(
            hasLidar: true, depthEverSeen: true, alreadyReasserted: false, depthlessFrames: 1_000))
        // One-shot: never a second re-run.
        XCTAssertFalse(RoomPlanWire.shouldReassertDepth(
            hasLidar: true, depthEverSeen: false, alreadyReasserted: true, depthlessFrames: 1_000))
        // Non-LiDAR sessions have no depth to lose.
        XCTAssertFalse(RoomPlanWire.shouldReassertDepth(
            hasLidar: false, depthEverSeen: false, alreadyReasserted: false, depthlessFrames: 1_000))
    }

    // MARK: - Census line

    func test_censusLine_table() {
        // The design's example shape: doors show when present.
        XCTAssertEqual(
            RoomCensus(objects: 9, walls: 13, doors: 2, windows: 1,
                       openings: 10, floors: 1).reviewLine,
            "9 objects · 13 walls · 2 doors · 1 window"
        )
        // Zero doors/windows hide; objects + walls always show.
        XCTAssertEqual(
            RoomCensus(objects: 9, walls: 13, doors: 0, windows: 0,
                       openings: 0, floors: 1).reviewLine,
            "9 objects · 13 walls"
        )
        // Singulars.
        XCTAssertEqual(
            RoomCensus(objects: 1, walls: 1, doors: 1, windows: 0,
                       openings: 0, floors: 1).reviewLine,
            "1 object · 1 wall · 1 door"
        )
        // Honest zero: a floor-only room still states its (lack of) contents.
        XCTAssertEqual(
            RoomCensus(objects: 0, walls: 0, doors: 0, windows: 0,
                       openings: 0, floors: 1).reviewLine,
            "0 objects · 0 walls"
        )
        // Openings and floors never render (modeling detail / implicit).
        XCTAssertFalse(
            RoomCensus(objects: 2, walls: 4, doors: 0, windows: 0,
                       openings: 11, floors: 1).reviewLine.contains("opening")
        )
    }

    // MARK: - BundleAssembler round-trip

    private func makeAssembler(tier: RSCaptureTier,
                               roomPlan: RSRoomPlanModel?,
                               dir: URL) -> BundleAssembler {
        BundleAssembler(
            bundleId:          UUID(),
            tier:              tier,
            startedAtDeviceUs: 1_000,
            endedAtDeviceUs:   2_000,
            startedAtWallUs:   3_000,
            frames:            [],
            planeAnchors:      [],
            roomPlan:          roomPlan,
            outputDir:         dir
        )
    }

    func test_bundleAssembler_roundTripsRoomPlan() throws {
        let dir = FileManager.default.temporaryDirectory
            .appendingPathComponent("roomplan-wire-test-\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: dir) }

        var model = RSRoomPlanModel()
        model.jsonGcsPath     = "roomplan/room.json"
        model.usdzGcsPath     = "roomplan/room.usdz"
        model.roomplanVersion = "ios26.5.2;CapturedRoom.v2;beautifyObjects"

        let url = try makeAssembler(tier: .lidarRoomplan, roomPlan: model, dir: dir)
            .write(userId: "test-user")
        let parsed = try RSCaptureBundle(serializedBytes: Data(contentsOf: url))

        XCTAssertEqual(parsed.tier, .lidarRoomplan)
        XCTAssertTrue(parsed.hasRoomPlan)
        XCTAssertEqual(parsed.roomPlan.jsonGcsPath, "roomplan/room.json")
        XCTAssertEqual(parsed.roomPlan.usdzGcsPath, "roomplan/room.usdz")
        XCTAssertEqual(parsed.roomPlan.roomplanVersion,
                       "ios26.5.2;CapturedRoom.v2;beautifyObjects")
        // hasLidar must hold on the ROOMPLAN tier (device block, not frames).
        XCTAssertTrue(parsed.device.hasLidar_p)
    }

    func test_bundleAssembler_nilRoomPlanStaysAbsent() throws {
        let dir = FileManager.default.temporaryDirectory
            .appendingPathComponent("roomplan-wire-test-\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: dir) }

        let url = try makeAssembler(tier: .lidarArkit, roomPlan: nil, dir: dir)
            .write(userId: "test-user")
        let parsed = try RSCaptureBundle(serializedBytes: Data(contentsOf: url))

        XCTAssertEqual(parsed.tier, .lidarArkit)
        XCTAssertFalse(parsed.hasRoomPlan,
                       "nil roomPlan must leave the field absent — the pre-RoomPlan wire shape")
    }
}
