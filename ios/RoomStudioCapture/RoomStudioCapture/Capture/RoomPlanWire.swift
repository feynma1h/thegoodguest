/// Pure decisions for the RoomPlan co-run wire (decision 0077, chunk RP-6).
///
/// CaptureManager owns the RoomCaptureSession lifecycle; every decision that
/// determines WHAT ships — tier, provenance string, census copy — lives here
/// as a pure function so it is reviewable as a table and pinned by
/// RoomPlanWireTests, per the house pattern (WaitFlowState, BundleRestore).
///
/// Read by: CaptureManager (tier + serialization), ReviewView via RootFlowView
/// (census line), RoomPlanWireTests.

import Foundation

// MARK: - RoomCensus

/// Entity counts from a built CapturedRoom. Published by CaptureManager when a
/// room SHIPS (never for a room that failed the tier condition — the review
/// census must describe data the server will actually see).
struct RoomCensus: Equatable {
    let objects: Int
    let walls: Int
    let doors: Int
    let windows: Int
    let openings: Int
    let floors: Int

    /// The review-screen census line, e.g. "9 objects · 13 walls · 2 doors".
    ///
    /// Objects and walls always show (zero included — an honest "0 objects" is
    /// information); doors and windows only when present. Openings and floors
    /// never show: the floor is implicit in any built room, and openings are a
    /// modeling detail, not something a person recognizes as theirs.
    var reviewLine: String {
        var parts = [
            Self.counted(objects, "object"),
            Self.counted(walls, "wall"),
        ]
        if doors > 0 { parts.append(Self.counted(doors, "door")) }
        if windows > 0 { parts.append(Self.counted(windows, "window")) }
        return parts.joined(separator: " · ")
    }

    private static func counted(_ n: Int, _ noun: String) -> String {
        "\(n) \(noun)\(n == 1 ? "" : "s")"
    }
}

// MARK: - RoomPlanWire

enum RoomPlanWire {

    /// Tier condition (decision 0077): LIDAR_ROOMPLAN iff a built CapturedRoom
    /// with at least one wall or floor ships. A room with only objects is not
    /// a room model the server can anchor anything to.
    static func roomQualifies(wallCount: Int, floorCount: Int) -> Bool {
        wallCount >= 1 || floorCount >= 1
    }

    /// The final bundle tier. `roomPlanShipped` means roomplan/room.json was
    /// written and the RoomPlanModel message will be set on the bundle.
    ///
    /// A shipped room without LiDAR cannot occur (RoomCaptureSession requires
    /// LiDAR); the table still defines it — hardware truth wins, so a
    /// contradictory flag degrades to ARKIT_ONLY rather than minting a LiDAR
    /// tier the frames can't back.
    static func finalTier(hasLidar: Bool, roomPlanShipped: Bool) -> RSCaptureTier {
        guard hasLidar else { return .arkitOnly }
        return roomPlanShipped ? .lidarRoomplan : .lidarArkit
    }

    /// RoomPlan provenance at capture time, e.g.
    /// "ios26.5.2;CapturedRoom.v2;beautifyObjects" (decision 0077's contract
    /// shape). The CapturedRoom schema version is read back out of the encoded
    /// JSON (Apple exposes no property for it); nil → "v?" — provenance must
    /// never fail the capture.
    static func versionString(osVersion: String, capturedRoomVersion: Int?) -> String {
        let v = capturedRoomVersion.map(String.init) ?? "?"
        return "ios\(osVersion);CapturedRoom.v\(v);beautifyObjects"
    }

    /// Peek the Codable schema version out of an encoded CapturedRoom JSON.
    /// Returns nil on any shape surprise — the caller degrades to "v?".
    static func capturedRoomVersion(fromJSON data: Data) -> Int? {
        guard let obj = try? JSONSerialization.jsonObject(with: data),
              let dict = obj as? [String: Any]
        else { return nil }
        return dict["version"] as? Int
    }
}
