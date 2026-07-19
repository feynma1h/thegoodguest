/// URLSessionTaskDelegate for BlobUploadManager's background URLSession.
///
/// This class is an NSObject bridge: URLSession calls it on an arbitrary OS queue;
/// it dispatches each event into BlobUploadManager.shared's actor executor via
/// `Task { await BlobUploadManager.shared.someMethod(...) }`.
///
/// urlSession(_:task:didCompleteWithError:)
///   Acquires a UIBackgroundTask assertion synchronously BEFORE the Task{} spawn.
///   Without this, iOS can suspend the process in the window between this callback
///   and the Task→BlobUploadManager actor crossing, starving the
///   handleTaskCompletion chain. The BackgroundTaskHandle guards against double-end
///   from both the expiration path and the defer in handleTaskCompletion.
///
///   Also increments the drain-gate counter synchronously before Task spawn.
///   The OS guarantees urlSessionDidFinishEvents fires after all didCompleteWithError
///   callbacks on the same serial delegate queue, so all increments are visible before
///   drainBackgroundSessionEvents observes the count.
///
/// urlSessionDidFinishEvents(forBackgroundURLSession:)
///   Sets drainObserved and calls fireCompletionHandlerIfReady(). The stored system
///   completion handler fires only after BOTH the drain flag is set AND the pending-
///   completions counter reaches zero, preventing premature app suspend.
///
/// AppDelegate wiring (via @UIApplicationDelegateAdaptor in RoomStudioCaptureApp):
///     func application(_:handleEventsForBackgroundURLSession:completionHandler:) {
///         if identifier == BlobUploadManager.backgroundSessionIdentifier {
///             Task {
///                 await BlobUploadManager.shared.setBackgroundCompletionHandler(handler)
///             }
///         }
///     }
///
/// Decisions: 0040, 0044

@preconcurrency import UIKit

final class BlobUploadDelegate: NSObject, URLSessionTaskDelegate {

    // MARK: - Task completion

    func urlSession(
        _ session: URLSession,
        task: URLSessionTask,
        didCompleteWithError error: Error?
    ) {
        let statusCode = (task.response as? HTTPURLResponse)?.statusCode
        let desc = task.taskDescription

        // Acquire the UIBackgroundTask assertion synchronously on the OS delegate
        // queue, BEFORE the Task{} spawn. UIApplication.beginBackgroundTask is documented
        // thread-safe despite its @MainActor annotation; @preconcurrency suppresses the
        // Swift 6 isolation check at this call site.
        //
        // var + forward-reference in expiration closure: safe because the OS cannot fire
        // the expiration handler before beginBackgroundTask returns — the assignment on
        // the next line always precedes any expiration-handler invocation.
        var handle: BackgroundTaskHandle!
        let token = UIApplication.shared.beginBackgroundTask(withName: "blob-upload-completion") {
            handle.endIfNeeded()
        }
        handle = BackgroundTaskHandle {
            // Token .invalid means beginBackgroundTask failed (e.g. app extension context).
            // Calling endBackgroundTask(.invalid) is a documented no-op but guard explicitly.
            guard token != .invalid else { return }
            UIApplication.shared.endBackgroundTask(token)
        }

        // Increment before spawn so urlSessionDidFinishEvents never observes
        // count == 0 while handleTaskCompletion chains are still pending.
        BlobUploadManager.shared.incrementPendingCompletions()

        Task {
            await BlobUploadManager.shared.handleTaskCompletion(
                taskDescription:     desc,
                statusCode:          statusCode,
                error:               error,
                backgroundTaskToken: handle
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
