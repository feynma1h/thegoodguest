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
/// AppDelegate wiring (via @UIApplicationDelegateAdaptor in TheGoodGuestCaptureApp):
///     func application(_:handleEventsForBackgroundURLSession:completionHandler:) {
///         if identifier == BlobUploadManager.backgroundSessionIdentifier {
///             Task {
///                 await BlobUploadManager.shared.setBackgroundCompletionHandler(handler)
///             }
///         }
///     }
///
/// Decisions: 0040, 0044

import os
@preconcurrency import UIKit

final class BlobUploadDelegate: NSObject, URLSessionTaskDelegate {

    // MARK: - Task completion

    func urlSession(
        _ session: URLSession,
        task: URLSessionTask,
        didCompleteWithError error: Error?
    ) {
        let httpResponse = task.response as? HTTPURLResponse
        let statusCode = httpResponse?.statusCode
        // Raw header string; parsed by the manager (which owns the clock for the
        // HTTP-date form). Honored on the 408/429/5xx retry paths.
        let retryAfterHeader = httpResponse?.value(forHTTPHeaderField: "Retry-After")
        let desc = task.taskDescription

        // Acquire the UIBackgroundTask assertion synchronously on the OS delegate
        // queue, BEFORE the Task{} spawn. UIApplication.beginBackgroundTask is documented
        // thread-safe despite its @MainActor annotation; @preconcurrency suppresses the
        // Swift 6 isolation check at this call site.
        //
        // The handle and the expiration closure reference each other; a lock box
        // breaks the cycle without a mutated-after-capture var (a Swift 6 error).
        // The OS cannot fire the expiration handler before beginBackgroundTask
        // returns; even if it could, the nil read is a no-op and the
        // handleTaskCompletion defer still ends the assertion.
        let handleBox = OSAllocatedUnfairLock<BackgroundTaskHandle?>(initialState: nil)
        let token = UIApplication.shared.beginBackgroundTask(withName: "blob-upload-completion") {
            handleBox.withLock { $0 }?.endIfNeeded()
        }
        let handle = BackgroundTaskHandle {
            // Token .invalid means beginBackgroundTask failed (e.g. app extension context).
            // Calling endBackgroundTask(.invalid) is a documented no-op but guard explicitly.
            guard token != .invalid else { return }
            // endBackgroundTask via the main actor: the endAction runs from the
            // manager actor's defer or the (main-thread) expiration handler; the
            // one-hop delay in releasing the assertion is harmless.
            Task { @MainActor in UIApplication.shared.endBackgroundTask(token) }
        }
        handleBox.withLock { $0 = handle }

        // Increment before spawn so urlSessionDidFinishEvents never observes
        // count == 0 while handleTaskCompletion chains are still pending.
        BlobUploadManager.shared.incrementPendingCompletions()

        Task {
            await BlobUploadManager.shared.handleTaskCompletion(
                taskDescription:     desc,
                statusCode:          statusCode,
                error:               error,
                retryAfterHeader:    retryAfterHeader,
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
