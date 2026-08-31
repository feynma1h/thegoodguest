/// Scene status enum and full response model for GET /scenes/by-bundle/{bundle_id}.
///
/// SceneStatus uses LENIENT decoding: unknown wire strings map to .unknown(raw)
/// and NEVER throw. This is load-bearing — the backend once crashed a client by
/// adding a new status value that a strict enum rejected (decision 0027 lesson).
///
/// SceneResponse mirrors the server's 200-body shape verbatim. The server
/// returns HTTP 200 even for terminal failure states; the status field in the
/// body is authoritative.
///
/// Read by: ScenePoller, ScenesListClient, RoomHistory, CaptureReaper.

import Foundation

// MARK: - SceneStatus

/// nonisolated: pure value type, decoded on MainActor (ScenePoller) and off it
/// (CaptureReaper's confirming GET) — same reasoning as UploadSessionRecord.
nonisolated enum SceneStatus: Equatable {
    case queued
    case processing
    case ready
    case failed
    case failedIncomplete   // wire: "failed_incomplete"
    case failedInvalid      // wire: "failed_invalid"
    case unknown(String)    // any future wire value — treated as self-resolving transient

    // MARK: Raw-value init (used by Decodable below and directly in tests)

    init(rawValue: String) {
        switch rawValue {
        case "queued":            self = .queued
        case "processing":        self = .processing
        case "ready":             self = .ready
        case "failed":            self = .failed
        case "failed_incomplete": self = .failedIncomplete
        case "failed_invalid":    self = .failedInvalid
        default:                  self = .unknown(rawValue)
        }
    }

    // MARK: Classification

    enum Classification {
        /// Backend will move this state forward with no client action — keep polling.
        case selfResolvingTransient
        /// Upload incomplete; cannot proceed until the re-upload front re-fires.
        case recoverableTerminal
        /// Done (success or permanent failure) — stop polling.
        case hardTerminal
    }

    var classification: Classification {
        switch self {
        case .queued, .processing, .unknown:      return .selfResolvingTransient
        case .failedIncomplete:                   return .recoverableTerminal
        case .ready, .failed, .failedInvalid:     return .hardTerminal
        }
    }
}

extension SceneStatus: Decodable {
    init(from decoder: Decoder) throws {
        // NEVER throw on unknown values — map to .unknown(raw) instead.
        let raw = try decoder.singleValueContainer().decode(String.self)
        self.init(rawValue: raw)
    }
}

// MARK: - SceneResponse

/// Mirrors the 200-body of GET /scenes/by-bundle/{bundle_id}.
/// All optional fields match the server contract (nullable in the Firestore doc).
/// nonisolated: decoded from nonisolated contexts too (see SceneStatus above).
nonisolated struct SceneResponse: Decodable, Equatable {
    let sceneId:      String
    let bundleId:     String?
    let status:       SceneStatus
    let resultUri:    String?
    let missingPaths: [String]?
    let createdAt:    String
    let updatedAt:    String

    enum CodingKeys: String, CodingKey {
        case sceneId      = "scene_id"
        case bundleId     = "bundle_id"
        case status
        case resultUri    = "result_uri"
        case missingPaths = "missing_paths"
        case createdAt    = "created_at"
        case updatedAt    = "updated_at"
    }
}

// MARK: - created_at parsing

extension SceneResponse {

    /// `created_at` as a Date, or nil if the wire string is unparseable.
    ///
    /// This is the server-side scene creation time — the only honest anchor for
    /// the user-facing elapsed clock (the scene has been in the pipeline since
    /// this instant, regardless of when this client started polling).
    var createdAtDate: Date? { Self.parseISO8601(createdAt) }

    /// The server writes Python `datetime.isoformat()`: `+00:00` offset, usually
    /// with a 6-digit microsecond fraction (`2026-07-21T13:19:47.123456+00:00`).
    /// ISO8601DateFormatter's fractional-seconds option is unreliable beyond
    /// 3 digits, so the fraction is stripped before parsing — the elapsed display
    /// consumes whole seconds only. `Z`-suffix timestamps parse too.
    static func parseISO8601(_ raw: String) -> Date? {
        var s = raw
        if let dot = s.firstIndex(of: ".") {
            let fractionStart = s.index(after: dot)
            var fractionEnd = fractionStart
            while fractionEnd < s.endIndex, s[fractionEnd].isNumber {
                fractionEnd = s.index(after: fractionEnd)
            }
            if fractionEnd > fractionStart {
                s.removeSubrange(dot..<fractionEnd)
            }
        }
        // A fresh formatter per call: parsing happens at most once per poll tick
        // (≥ 2 s apart), and a shared static instance would need concurrency
        // annotations for no measurable win.
        return ISO8601DateFormatter().date(from: s)
    }
}
