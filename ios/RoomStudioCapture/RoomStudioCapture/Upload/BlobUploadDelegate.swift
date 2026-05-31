/// URLSessionTaskDelegate for BlobUploadManager's background URLSession.
///
/// This class is an NSObject bridge: URLSession calls it on an arbitrary OS queue;
/// it dispatches each event into BlobUploadManager.shared's actor executor via
/// `Task { await BlobUploadManager.shared.someMethod(...) }`.
///
/// urlSession(_:task:didCompleteWithError:)
///   Maps each completing upload task to BlobUploadManager.handleTaskCompletion.
///   status code is extracted from task.response as? HTTPURLResponse; may be nil
///   for network-layer failures (error != nil).
///
/// urlSessionDidFinishEvents(forBackgroundURLSession:)
///   Signals that all queued events for the session have been delivered. Calls
///   BlobUploadManager.shared.drainBackgroundSessionEvents(), which invokes the
///   completion handler stored by the AppDelegate background-session hook so the
///   system can suspend the app.
///
///   AppDelegate wiring (not yet added — requires @UIApplicationDelegateAdaptor):
///     func application(_:handleEventsForBackgroundURLSession:completionHandler:) {
///         if identifier == BlobUploadManager.backgroundSessionIdentifier {
///             Task {
///                 await BlobUploadManager.shared.setBackgroundCompletionHandler(handler)
///             }
///         }
///     }
///
/// Decisions: 0040

import Foundation

final class BlobUploadDelegate: NSObject, URLSessionTaskDelegate {

    // MARK: - Task completion

    func urlSession(
        _ session: URLSession,
        task: URLSessionTask,
        didCompleteWithError error: Error?
    ) {
        // Extract HTTP status code from the response (nil if error is a network failure).
        let statusCode = (task.response as? HTTPURLResponse)?.statusCode
        let desc = task.taskDescription

        Task {
            await BlobUploadManager.shared.handleTaskCompletion(
                taskDescription: desc,
                statusCode:      statusCode,
                error:           error
            )
        }
    }

    // MARK: - Background session drain

    func urlSessionDidFinishEvents(forBackgroundURLSession session: URLSession) {
        Task {
            await BlobUploadManager.shared.drainBackgroundSessionEvents()
        }
    }
}
