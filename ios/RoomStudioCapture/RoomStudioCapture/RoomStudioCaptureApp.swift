/// App entry point for RoomStudio Capture.
///
/// P1: single-window app, ContentView owns the capture session.
/// Future phases will add navigation (scene list, status screens) here.

import SwiftUI

@main
struct RoomStudioCaptureApp: App {
    var body: some Scene {
        WindowGroup {
            ContentView()
        }
    }
}
