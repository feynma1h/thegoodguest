/// App entry point for RoomStudio Capture.
///
/// P1: single-window app, ContentView owns the capture session.
/// P3: FirebaseApp.configure() called at launch; anonymous sign-in attempted
///     as soon as the app has network. GoogleService-Info.plist must be present
///     in the app bundle — obtain it from the Firebase console for project
///     "roomstudio", iOS app bundle ID com.roomstudio.RoomStudioCapture.
/// Future phases will add navigation (scene list, status screens) here.

import FirebaseCore
import SwiftUI

@main
struct RoomStudioCaptureApp: App {

    @UIApplicationDelegateAdaptor(AppDelegate.self) var appDelegate

    init() {
        // Reads GoogleService-Info.plist from the app bundle.
        // Skipped gracefully if the plist is absent (simulator tests without the file).
        // For production / on-device use, add GoogleService-Info.plist via Xcode:
        //   File > Add Files > GoogleService-Info.plist, target: RoomStudioCapture.
        if Bundle.main.path(forResource: "GoogleService-Info", ofType: "plist") != nil {
            FirebaseApp.configure()
        } else {
            print("[RoomStudioCaptureApp] GoogleService-Info.plist not found — Firebase auth disabled. Add the plist for production builds.")
        }
    }

    var body: some Scene {
        WindowGroup {
            ContentView()
                .task {
                    // Attempt anonymous sign-in at launch so the UID is cached
                    // in Keychain before the user finishes their first capture.
                    // signInIfNeeded() is a no-op if already signed in.
                    try? await AuthManager.shared.signInIfNeeded()
                }
                .task {
                    // Reclaim orphaned capture session dirs from Application Support.
                    // See CaptureStorageSweeper and decision 0043.
                    await CaptureStorageSweeper.shared.sweep()
                }
        }
    }
}
