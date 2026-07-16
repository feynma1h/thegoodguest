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
/// Read by: ScenePoller, SceneStatusView.

import Foundation

// MARK: - SceneStatus

enum SceneStatus: Equatable {
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
struct SceneResponse: Decodable, Equatable {
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
