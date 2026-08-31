/// App entry point for TheGoodGuest Capture.
///
/// Single-window app; RootFlowView is the root and coordinates the capture
/// flow. At launch: FirebaseApp.configure(), then four .task jobs — anonymous sign-in,
/// orphaned-capture-directory sweep, upload rehydration, and the
/// acknowledged-flight reap (decision 0084). The splash plays over the top of
/// all four rather than in front of them.
/// GoogleService-Info.plist must be present in the app bundle — obtain it
/// from the Firebase console for project "thegoodguest", iOS app bundle ID
/// com.thegoodguest.TheGoodGuestCapture.
///
/// In DEBUG the `-rs.gallery.screen <id>` launch argument diverts the window to
/// ScreenGallery — one screen, from fixtures, with none of the launch work
/// below — so every surface can be photographed. See ScreenGallery.

import FirebaseCore
import GoogleSignIn
import SwiftUI

@main
struct TheGoodGuestCaptureApp: App {

    @UIApplicationDelegateAdaptor(AppDelegate.self) var appDelegate

    init() {
        // Reads GoogleService-Info.plist from the app bundle.
        // Skipped gracefully if the plist is absent (simulator tests without the file).
        // For production / on-device use, add GoogleService-Info.plist via Xcode:
        //   File > Add Files > GoogleService-Info.plist, target: TheGoodGuestCapture.
        if Bundle.main.path(forResource: "GoogleService-Info", ofType: "plist") != nil {
            FirebaseApp.configure()
        } else {
            print("[TheGoodGuestCaptureApp] GoogleService-Info.plist not found — Firebase auth disabled. Add the plist for production builds.")
        }
        #if DEBUG
        // Lifecycle breadcrumb (StagingHooks): distinguishes a background
        // OS-relaunch (init fires, .task may not) from a foreground open — the
        // decision-0045 Fork A instrument. File-based on purpose; os_log is
        // buffered/coalesced under suspension.
        StagingHooks.breadcrumb("app-init")
        #endif
    }

    var body: some Scene {
        WindowGroup {
            #if DEBUG
            // The screenshot harness (ScreenGallery) renders ONE screen from
            // fixtures and runs none of the launch work below — no sign-in, no
            // sweep, no rehydration, and no splash: a harness that sat through
            // the launch animation before every shot would make the capture
            // pass slower for no gain. Absent the launch argument this is inert
            // and the live root below is what ships.
            if let screen = ScreenGallery.requestedScreen {
                ScreenGalleryView(screen: screen)
                    .rsTypeCeiling()
            } else {
                liveRoot
                    .rsTypeCeiling()
            }
            #else
            liveRoot
                .rsTypeCeiling()
            #endif
        }
    }

    /// The real app root and its launch work.
    @ViewBuilder
    private var liveRoot: some View {
        RootFlowView()
            .splashOnLaunch()
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
            .task {
                // Resume any in-flight bundle uploads from prior sessions.
                // Covers the swipe-up force-quit path (view appears → .task fires).
                #if DEBUG
                StagingHooks.breadcrumb("app-task-rehydrate-fired")
                #endif
                await BlobUploadManager.shared.rehydrateAllUnfinishedBundles()
            }
            .task {
                // Reclaim acknowledged, finished flights from earlier launches
                // (record + session dir): .failed directly, .complete only
                // after one confirming GET shows a terminal backend state.
                // Unacknowledged records are the launch restore's inventory
                // and are never touched. Decision 0084.
                await CaptureReaper.shared.reapAcknowledgedAtLaunch()
            }
            .onOpenURL { url in
                // Google Sign-In's redirect back into the app (the
                // reversed-client-ID scheme in TheGoodGuestCapture-Info.plist).
                // Returns false for URLs that aren't GIDSignIn's — no other
                // scheme is registered today, so nothing else consumes them.
                _ = GIDSignIn.sharedInstance.handle(url)
            }
    }
}
