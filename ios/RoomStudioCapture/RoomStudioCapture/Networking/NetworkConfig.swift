/// Static network configuration for RoomStudio Capture.
///
/// One place to change service URLs. The api-public URL is the Cloud Run
/// service URL for project "roomstudio", region asia-southeast1.
///
/// Read by: UploadSessionClient (default baseURL).

import Foundation

enum NetworkConfig {
    /// Base URL for the api-public Cloud Run service.
    /// Route: POST /captures/{bundle_id}/upload_session
    static let apiPublicBaseURL = URL(string: "https://api-public-q62kcditqa-as.a.run.app")!
}
