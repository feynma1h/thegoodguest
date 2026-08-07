/// Static network configuration for RoomStudio Capture.
///
/// One place to change service URLs. The api-public URL is the Cloud Run
/// service URL for project "roomstudio", region asia-southeast1.
///
/// Read by: UploadSessionClient (default baseURL).

import Foundation

/// nonisolated: pure constants + pure functions, read from nonisolated network
/// code (UploadSessionClient) — the target's MainActor default isolation must
/// not apply here.
nonisolated enum NetworkConfig {
    /// Base URL for the api-public Cloud Run service.
    /// Route: POST /captures/{bundle_id}/upload_session
    static let apiPublicBaseURL = URL(string: "https://api-public-q62kcditqa-as.a.run.app")!

    /// Base URL of the web app ("the desk"), used by the doorway handoff.
    ///
    /// nil ON PURPOSE today: the production hosting channel is deliberately
    /// undeployed until launch hardening, and the preview channel's URL is
    /// temporary — baking either in would ship a link that 404s or expires. While
    /// this is nil the doorway hides its "step through" CTA rather than presenting
    /// a button that does nothing. Set it when a durable web origin exists.
    ///
    /// Note this is a plain `open(_:)` target, NOT an app-claimed universal link:
    /// it needs no associated-domains entitlement. The entitlement only matters
    /// for links this app CLAIMS, which is a separate, still-gated concern.
    static let webBaseURL: URL? = nil

    /// The web URL for one captured room, or nil when no web origin is configured.
    static func webRoomURL(bundleId: String) -> URL? {
        guard let webBaseURL else { return nil }
        return URL(string: "room?bundle=\(bundleId)", relativeTo: webBaseURL)
    }
}
