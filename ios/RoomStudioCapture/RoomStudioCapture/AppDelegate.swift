/// UIApplicationDelegate for RoomStudio Capture.
///
/// Handles the OS-relaunch path for in-flight background URLSession uploads. When the system
/// relaunches the app after background transfers complete (or progress), it calls
/// application(_:handleEventsForBackgroundURLSession:completionHandler:) early in the launch
/// sequence. The app must:
///   1. Recreate (or access) the background URLSession with the matching identifier so the
///      delegate reattaches to in-flight tasks.
///   2. Store the completionHandler.
///   3. Call the completionHandler only after all queued delegate events have been delivered,
///      signalled by BlobUploadDelegate.urlSessionDidFinishEvents(forBackgroundURLSession:)
///      → BlobUploadManager.drainBackgroundSessionEvents().
///
/// UIBackgroundModes note: no UIBackgroundModes key is required for background URLSession
/// uploads and OS relaunch-to-deliver. Background URLSession is implemented at the OS
/// networking daemon level (nsurlsessiond) and is distinct from BGTaskScheduler fetch /
/// processing modes, which do require a UIBackgroundModes Info.plist entry.
///
/// Wired via @UIApplicationDelegateAdaptor in RoomStudioCaptureApp.
///
/// Decisions: 0040 (background URLSession relaunch), 0041 (D2 AppDelegate wiring seam)

import os
import UIKit

final class AppDelegate: NSObject, UIApplicationDelegate {

    // Logging privacy policy: UUIDs, blob paths, and enum values may be .public;
    // user identifiers and error payloads stay default-private (redacted in shipped logs).
    private let logger = Logger(subsystem: "com.roomstudio.RoomStudioCapture", category: "AppDelegate")

    /// Called by the system when the app is relaunched to deliver background URLSession events.
    ///
    /// Accesses BlobUploadManager.shared to recreate the background URLSession with
    /// backgroundSessionIdentifier, reattaching the delegate to any in-flight tasks.
    /// Stores the completionHandler (wrapped for main-queue delivery per Apple requirement)
    /// so drainBackgroundSessionEvents can call it without queue awareness.
    func application(
        _ application: UIApplication,
        handleEventsForBackgroundURLSession identifier: String,
        completionHandler: @escaping () -> Void
    ) {
        guard identifier == BlobUploadManager.backgroundSessionIdentifier else { return }
        logger.info("[AppDelegate] OS relaunch for background URLSession: \(identifier, privacy: .public)")
        // Apple requires the system-provided completionHandler to be called on the main queue.
        // Wrap before storing so drainBackgroundSessionEvents can invoke it directly.
        let mainQueueHandler: () -> Void = {
            DispatchQueue.main.async { completionHandler() }
        }
        Task {
            await BlobUploadManager.shared.setBackgroundCompletionHandler(mainQueueHandler)
        }
    }
}
