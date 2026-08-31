/// The widget extension's entry point.
///
/// This extension exists ONLY for the capture Live Activity (design spec §5) —
/// there is no Home Screen widget, so there is no asset catalog, no
/// configuration intent, and no timeline provider. If a Home Screen widget is
/// ever added it joins the bundle here.
///
/// The extension compiles `TheGoodGuestShared/` (the ActivityKit contract, the
/// voice table, and the design tokens) alongside its own views. It does NOT and
/// must not reach into the app target: an app extension is a separate process
/// with its own container, and the shared folder is the only sanctioned overlap.

import SwiftUI
import WidgetKit

@main
struct TheGoodGuestLiveActivityBundle: WidgetBundle {
    var body: some Widget {
        RoomUploadLiveActivity()
    }
}
