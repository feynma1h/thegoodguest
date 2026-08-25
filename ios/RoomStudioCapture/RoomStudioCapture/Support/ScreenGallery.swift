/// DEBUG-only screen gallery: renders exactly one screen, in isolation, from
/// fixtures — so every surface in the app can be photographed without staging
/// the state that would normally produce it.
///
/// WHY THIS EXISTS: most of the app's screens cannot be reached on demand. The
/// home notices need a terminally failed upload record, a bundle mid-flight and
/// a failed rooms fetch — three independent conditions, one of which requires a
/// real capture to have failed. The wait and failure screens need a round trip
/// to the backend. The doorway needs a room to have finished rebuilding. Every
/// one of them is a design surface someone has to be able to LOOK at, and the
/// iOS test policy is explicit that a green suite says nothing about rendering:
/// layout claims at accessibility sizes have to be verified by screenshot, and
/// three review passes previously claimed coverage they did not have.
///
/// So this is the screenshot half of that policy, made repeatable. It composes
/// each screen the same way `RootFlowView` composes it — the home variants in
/// particular go through `HomeView`'s real `notice` and `roomsStrip` slots, so a
/// photograph taken here is a photograph of the shipping layout and not of a
/// hand-assembled lookalike.
///
/// HOW TO DRIVE IT, following `StagingHooks`' launch-argument convention:
///
///     xcrun simctl launch <udid> com.roomstudio.RoomStudioCapture \
///         -rs.gallery.screen home-all
///
/// Pair it with `xcrun simctl ui <udid> content_size accessibility-extra-extra-extra-large`
/// to photograph the accessibility sizes, which is where this app's layout
/// defects have actually lived (decisions 0224 and 0238).
///
/// `ScreenGallery.screens` is the catalogue and the ONE list — the capture
/// script enumerates it rather than carrying its own copy, so a screen added
/// here is photographed without touching anything else.
///
/// Compiled out of release builds entirely. Nothing here runs in the live app:
/// the app entry point consults `requestedScreen` and falls through to
/// `RootFlowView` whenever the argument is absent.

#if DEBUG

import SwiftUI

// MARK: - Catalogue

enum ScreenGallery {

    /// The launch argument / UserDefaults key, matching StagingHooks' `-rs.*` shape.
    static let defaultsKey = "rs.gallery.screen"

    /// The screen this launch was asked for, or nil for the ordinary app.
    static var requestedScreen: String? {
        guard let raw = UserDefaults.standard.string(forKey: defaultsKey) else { return nil }
        let trimmed = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        return trimmed.isEmpty ? nil : trimmed
    }

    /// Every photographable screen: id, the caption a reader needs, and whether
    /// the screen animates on arrival (the capture script waits longer for those
    /// rather than photographing a half-played bloom).
    struct Entry {
        let id: String
        let title: String
        let note: String
        var settles = false
    }

    static let screens: [Entry] = [
        // ── Home: the subject. Every variant the flow can produce. ──────────
        .init(id: "home-first",       title: "Home · first time",
              note: "The hero claim and one action. No rooms, nothing to say."),
        .init(id: "home-strip",       title: "Home · returning",
              note: "The strip replaces the hero the moment any room is known."),
        .init(id: "home-strip-stale", title: "Home · list may be stale",
              note: "A refresh failed after an earlier success; the rooms are kept."),
        .init(id: "home-trouble",     title: "Home · rooms unreachable",
              note: "Hero plus an honest line. Never the hero alone — that would read as no rooms."),
        .init(id: "home-banner",      title: "Home · upload failed",
              note: "A terminally failed upload from a previous launch."),
        .init(id: "home-reentry",     title: "Home · room in flight",
              note: "The way back into a room still being rebuilt."),
        .init(id: "home-all",         title: "Home · everything at once",
              note: "All three notices, the hero, and the pinned action. Nothing caps this stack."),

        // ── The other history surface ───────────────────────────────────────
        .init(id: "rooms-list",        title: "Your rooms",
              note: "Thin by design: status and a way back to the web, nothing editable."),
        .init(id: "rooms-stale",       title: "Your rooms · stale",
              note: "The same stale line the strip carries, on the full list."),
        .init(id: "rooms-empty",       title: "Your rooms · empty",
              note: "Genuinely none sent — distinct from not being able to ask."),
        .init(id: "rooms-loading",     title: "Your rooms · loading",
              note: "Nothing known yet."),
        .init(id: "rooms-unreachable", title: "Your rooms · unreachable",
              note: "The phone could not ask. It does not claim there are none."),

        // ── The capture flow ────────────────────────────────────────────────
        .init(id: "guidance",  title: "Before you start",
              note: "What the scan button opens. Camera permission is asked here, in context."),
        .init(id: "capture",   title: "Capturing",
              note: "The room drawing itself in ink. Tracking pill, coverage ticks, one spoken line."),
        .init(id: "capture-dark", title: "Capturing · too dark",
              note: "Tracking truth outranks anything the guest would otherwise say."),
        .init(id: "gotroom",   title: "I've got the room",
              note: "The single joyful beat. Holds 1.8 s, then review.", settles: true),
        .init(id: "review",    title: "Review",
              note: "The sketch, the capture metrics, and one honest chance to scan again."),

        // ── Waiting ─────────────────────────────────────────────────────────
        .init(id: "wait-sending",   title: "Sending",
              note: "Nothing has arrived yet, so no arrival claim and no clock."),
        .init(id: "wait-analyzing", title: "Analyzing",
              note: "Uploaded. The clock counts from the server's own start time."),
        .init(id: "wait-long",      title: "Still working",
              note: "Candid when it runs long. No ETA — the pipeline gives the phone none."),
        .init(id: "wait-trouble",   title: "Can't reach the studio",
              note: "The room is safe; the check is not landing."),
        .init(id: "wait-paused",    title: "Paused",
              note: "Resumes next launch. Nothing to do now — which the home row does not say."),
        .init(id: "wait-limited",   title: "Daily limit",
              note: "Not a failure treatment. The only useful fact is when it lifts."),

        // ── Arrival and failure ─────────────────────────────────────────────
        .init(id: "doorway",         title: "The doorway",
              note: "The arrival. Never auto-navigates — the user chooses to step through.", settles: true),
        .init(id: "fail-incomplete", title: "Incomplete upload",
              note: "Names the missing count. Offers a re-send only when the bytes are provably still here."),
        .init(id: "fail-rescan",     title: "Incomplete · rescan only",
              note: "The same screen when the files are gone. It promises nothing."),
        .init(id: "fail-terminal",   title: "Terminal failure",
              note: "Nothing survived. The deepest ink surface, one path out."),
        .init(id: "fail-upload",     title: "Upload failed",
              note: "The send broke, not the scan. Carries the only diagnostic the user has."),

        // ── Identity ────────────────────────────────────────────────────────
        .init(id: "profile",   title: "You",
              note: "The device ID as proof of continuity. Signing out lives on the web."),
        .init(id: "whysignin", title: "Why sign in",
              note: "Auto-presented once. Its whole argument is a count."),

        // ── Outside the flow ────────────────────────────────────────────────
        .init(id: "unsupported", title: "No depth camera",
              note: "The root gate. Honest, and offers nothing to do."),
        .init(id: "coldstart",   title: "Cold start",
              note: "Built, but the flow opens straight at home."),
        .init(id: "qr",          title: "QR bridge",
              note: "Built, but blocked on deep links. The code encodes nothing."),
    ]
}

// MARK: - Fixtures

/// Synthetic, and obviously so: no real capture, no real identity. The rooms
/// carry the three states the row treatment distinguishes.
private enum GalleryFixture {

    static let rooms: [RoomSummary] = [
        .init(id: "s1", bundleId: "b1", title: "today's room",
              statusLine: "being rebuilt · 4 min so far", state: .processing),
        .init(id: "s2", bundleId: "b2", title: "yesterday's room",
              statusLine: "on your desk", state: .ready),
        .init(id: "s3", bundleId: "b3", title: "the July 12 room",
              statusLine: "on your desk", state: .ready),
    ]

    static let uid = "gallery-fixture-not-a-real-uid"

    static let failureReason = "blob_unreadable_at_remint_manifest"

    /// A server anchor far enough back that the elapsed clock reads as a real wait.
    static var anchor: Date { Date().addingTimeInterval(-268) }
}

// MARK: - Home, composed the way the flow composes it

/// Home through its REAL slots. The notice stack mirrors `RootFlowView`'s
/// composition exactly — same order, same spacing, same components — because a
/// screenshot of a lookalike would be worth nothing to anyone deciding how to
/// reorganise the real one.
private struct GalleryHome: View {
    var rooms: [RoomSummary] = []
    var stale = false
    var banner = false
    var reentry = false
    var trouble = false

    var body: some View {
        HomeView(
            hasRooms: !rooms.isEmpty,
            roomsStrip: {
                RecentRoomsStrip(rooms: rooms, stale: stale, canOpenWeb: false)
            },
            notice: {
                VStack(spacing: 14) {
                    if banner { UploadFailedBanner(reason: GalleryFixture.failureReason) }
                    if reentry { ReEntryRow() }
                    if trouble { RoomsTroubleLine() }
                }
            }
        )
    }
}

/// The capture screen needs a live feed object, so it gets its own wrapper to
/// own one for the view's lifetime rather than rebuilding it every render.
private struct GalleryCapture: View {
    var tracking: TrackingQuality = .good

    @StateObject private var feed = FloorPlanFeed()

    var body: some View {
        LiveCaptureView(
            state: CaptureHUDState(
                tracking: tracking,
                guestLine: "Move slowly and I'll sketch the room as you go.",
                floor: .full, walls: .partial(0.62), corners: .partial(0.5)
            ),
            feed: feed
        )
        .onAppear {
            feed.publish(snapshot: .previewRoom)
            feed.publish(camera: .previewCamera)
        }
    }
}

// MARK: - The gallery itself

struct ScreenGalleryView: View {
    let screen: String

    var body: some View {
        switch screen {

        // Home
        case "home-first":       GalleryHome()
        case "home-strip":       GalleryHome(rooms: GalleryFixture.rooms)
        case "home-strip-stale": GalleryHome(rooms: GalleryFixture.rooms, stale: true)
        case "home-trouble":     GalleryHome(trouble: true)
        case "home-banner":      GalleryHome(banner: true)
        case "home-reentry":     GalleryHome(reentry: true)
        case "home-all":         GalleryHome(banner: true, reentry: true, trouble: true)

        // Rooms
        case "rooms-list":
            RoomsListView(state: .loaded(rooms: GalleryFixture.rooms, stale: false), onClose: {})
        case "rooms-stale":
            RoomsListView(state: .loaded(rooms: GalleryFixture.rooms, stale: true), onClose: {})
        case "rooms-empty":
            RoomsListView(state: .loaded(rooms: [], stale: false), onClose: {})
        case "rooms-loading":
            RoomsListView(state: .loading, onClose: {})
        case "rooms-unreachable":
            RoomsListView(state: .failed(reason: "offline"), onClose: {})

        // Capture flow
        case "guidance":     GuidanceSheet()
        case "capture":      GalleryCapture()
        case "capture-dark": GalleryCapture(tracking: .tooDark)
        case "gotroom":      GotTheRoomView()
        case "review":
            ReviewView(metrics: "126 frames · LiDAR + RoomPlan",
                       census: "9 objects · 13 walls · 2 doors",
                       floorPlan: .previewRoom,
                       verdict: "Here's your capture. Send it, and I'll start making sense of it on your desk.",
                       rescanLabel: "Scan again from scratch")

        // Waiting
        case "wait-sending":   WaitingView(phase: .sending)
        case "wait-analyzing": WaitingView(phase: .analyzing, anchor: GalleryFixture.anchor)
        case "wait-long":      WaitingView(phase: .longRunning, anchor: GalleryFixture.anchor)
        case "wait-trouble":   WaitingView(phase: .connectionTrouble, anchor: GalleryFixture.anchor)
        case "wait-paused":    WaitingView(phase: .sendPaused)
        case "wait-limited":
            WaitingView(phase: .sendRateLimited(resetsAt: GalleryFixture.anchor.addingTimeInterval(31_000)))

        // Arrival and failure
        case "doorway":
            DoorwayView(signedIntoWeb: true, canOpenWeb: true)
        case "fail-incomplete":
            FailureView(kind: .recoverable(missingCount: 3, resend: .available))
        case "fail-rescan":
            FailureView(kind: .recoverable(missingCount: 14, resend: .unavailable))
        case "fail-terminal":
            FailureView(kind: .terminal)
        case "fail-upload":
            FailureView(kind: .uploadFailed(reason: GalleryFixture.failureReason))

        // Identity
        case "profile":
            ProfileView(uid: GalleryFixture.uid)
        case "whysignin":
            WhySignInSheet(roomCount: 3)

        // Outside the flow
        case "unsupported": UnsupportedDeviceView()
        case "coldstart":   ColdStartView()
        case "qr":          QRBridgeView()

        default:
            unknown
        }
    }

    /// An unrecognised id is stated plainly rather than silently photographed as
    /// a blank screen — a blank frame in a contact sheet reads as a real screen
    /// that renders nothing, which is a much more expensive misunderstanding.
    private var unknown: some View {
        VStack(spacing: 10) {
            Text("No screen with id")
                .font(RSFont.ui(.callout, weight: .semibold))
                .foregroundStyle(Color.rsInk)
            Text(screen)
                .rsFont(.mono, size: 13)
                .foregroundStyle(Color.rsAction)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .rsParchmentScreen()
    }
}

#Preview("Gallery · home, everything at once") {
    ScreenGalleryView(screen: "home-all")
}

#endif
