/// Static network configuration for TheGoodGuest Capture.
///
/// One place to change service URLs. The api-public URL is the Cloud Run
/// service URL for project "thegoodguest", region asia-southeast1.
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
    /// A PLAIN `open(_:)` TARGET, NOT an app-claimed universal link: it needs no
    /// associated-domains entitlement, and never did. The entitlement matters
    /// only for links this app CLAIMS — a separate concern this handoff does not
    /// touch, and the reason "needs associated domains" was the wrong reading of
    /// why the link was missing.
    ///
    /// It stayed nil while no durable origin existed and the preview channel's
    /// URL would have expired. `thegoodguest.web.app` is that durable origin.
    ///
    /// A LIVE ORIGIN IS NOT ENOUGH TO OFFER THE LINK, and nothing here can tell:
    /// rooms are scoped to the caller's token, an anonymous UID does not carry
    /// off the phone, and Safari holds no session from this app. So an unlinked
    /// user following this URL reaches a page that asks them to sign in with an
    /// account they do not have. `RoomHistory.webHandoffLands` is the predicate
    /// that decides whether to offer it; do not gate a surface on this constant
    /// alone.
    static let webBaseURL: URL? = URL(string: "https://thegoodguest.web.app")

    /// The web URL for one captured room, or nil when no web origin is
    /// configured. Non-nil does NOT mean the room will be visible there — see
    /// the note on `webBaseURL`.
    static func webRoomURL(bundleId: String) -> URL? {
        guard let webBaseURL else { return nil }
        return URL(string: "room?bundle=\(bundleId)", relativeTo: webBaseURL)
    }
}
